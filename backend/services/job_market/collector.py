import atexit
import json
import logging
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..paths import APP_DATA_DIR, PROJECT_ROOT
from .store import MarketStore, SOURCES, after

logger = logging.getLogger(__name__)


class CollectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_hours: int = Field(default=6, ge=1, le=168, strict=True)
    sources: list[str] = Field(default_factory=lambda: list(SOURCES), min_length=1, max_length=4)
    max_pages: int = Field(default=2, ge=1, le=10, strict=True)
    max_jobs: int = Field(default=300, ge=20, le=2000, strict=True)
    timeout_seconds: int = Field(default=180, ge=30, le=1800, strict=True)
    companies: list[str] = Field(default_factory=list, max_length=20)
    locations: list[str] = Field(default_factory=list, max_length=8)
    industries: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("sources")
    @classmethod
    def known_sources(cls, value):
        if len(set(value)) != len(value) or any(item not in SOURCES for item in value):
            raise ValueError("未知或重复的数据来源")
        return value

    @field_validator("companies", "locations", "industries")
    @classmethod
    def bounded_filters(cls, value):
        if any(not item.strip() or len(item) > 100 for item in value):
            raise ValueError("筛选条件格式不正确")
        return list(dict.fromkeys(item.strip() for item in value))


class Collector:
    def __init__(self, store=None, *, source_runner=None, directory=None):
        self.directory = Path(directory or APP_DATA_DIR)
        self.store = store or MarketStore(self.directory / "job_market.sqlite3")
        if not self.store.settings():
            self.store.save_settings(CollectionSettings().model_dump(), due=after(15))
        self.source_runner = source_runner or self.run_source
        self.stop_event = threading.Event()
        self.scheduler = None

    def start(self, *, scheduled=False):
        current = self.store.settings()
        config = CollectionSettings.model_validate({key: value for key, value in current.items() if key != "next_run_at"}).model_dump()
        run_id = self.store.claim_run(config, "scheduled" if scheduled else "manual", require_due=scheduled)
        if not run_id:
            return None
        threading.Thread(target=self.collect, args=(run_id, config), daemon=True, name="job-market-collector").start()
        return run_id

    def collect(self, run_id, config):
        states = []
        try:
            for source in config["sources"]:
                if self.stop_event.is_set() or self.store.cancelled(run_id):
                    self.store.source_status(run_id, source, "cancelled", "已停止采集。")
                    states.append("cancelled")
                    continue
                self.store.source_status(run_id, source, "running")
                try:
                    state, message = self.source_runner(run_id, source, config)
                except Exception:
                    logger.exception("Job-market source failed: %s", source)
                    state, message = "failed", "来源采集异常，已保留历史记录。"
                if state in {"succeeded", "partial"}:
                    with self.store.connect() as conn:
                        valid = conn.execute("SELECT COUNT(*) FROM observations o JOIN jobs j ON o.job_id=j.id WHERE o.run_id=? AND j.source=?", (run_id, source)).fetchone()[0]
                    if not valid:
                        state, message = "failed", "本轮返回的数据缺少有效岗位字段，未记为成功更新。"
                self.store.source_status(run_id, source, state, message)
                states.append(state)
            rows = self.store.runs(1)
            counts = rows[0]["counts"] if rows and rows[0]["id"] == run_id else {}
            has_rows = bool(sum(counts.values()))
            cancelled = self.store.cancelled(run_id) or self.stop_event.is_set()
            success = all(state == "succeeded" for state in states)
            status = "cancelled" if cancelled else "succeeded" if success and has_rows else "partial" if has_rows else "empty" if all(state == "empty" for state in states) else "failed"
            self.store.finish(run_id, status)
        except Exception:
            logger.exception("Job-market collection failed")
            self.store.finish(run_id, "failed", "采集任务未完成，已保留获取到的记录。")

    @staticmethod
    def terminate(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    def python_executable(self):
        override = os.environ.get("JOBHUNTER_PYTHON", "")
        runtime = self.directory / "jobhunter-runtime" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        return override or (str(runtime) if runtime.is_file() else sys.executable)

    def run_source(self, run_id, source, config):
        runner = PROJECT_ROOT / "backend" / "integrations" / "jobhunter" / "runner.py"
        logs = self.directory / "job_market_logs"
        logs.mkdir(parents=True, exist_ok=True)
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "JOBHUNTER_LOG_DIR": str(logs)}
        events = queue.Queue(maxsize=200)
        with (logs / f"{run_id}-{source}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([self.python_executable(), "-B", str(runner), source], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", errors="replace", env=env, **options)
            try:
                process.stdin.write(json.dumps(config, ensure_ascii=False))
                process.stdin.close()
                def read():
                    try:
                        for line in iter(lambda: process.stdout.readline(2000001), ""):
                            if len(line) > 2000000:
                                events.put({"event": "protocol_error"})
                                break
                            try:
                                events.put(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                    finally:
                        events.put(None)
                threading.Thread(target=read, daemon=True).start()
                deadline = time.monotonic() + config["timeout_seconds"]
                last_heartbeat, result = 0, ("failed", "采集进程未返回有效结果，请检查运行环境。")
                while True:
                    if self.stop_event.is_set() or self.store.cancelled(run_id):
                        return "cancelled", "已停止，获取到的岗位已保留。"
                    if time.monotonic() > deadline:
                        return "timeout", "本轮已达到采集时限，获取到的岗位已保留。"
                    if time.monotonic() - last_heartbeat > 10:
                        self.store.heartbeat(run_id, f"正在更新{SOURCES[source]}")
                        last_heartbeat = time.monotonic()
                    try:
                        event = events.get(timeout=.5)
                    except queue.Empty:
                        continue
                    if event is None:
                        break
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("event")
                    if kind == "jobs" and isinstance(event.get("records"), list):
                        self.store.ingest(run_id, source, event["records"][:100])
                    elif kind == "progress":
                        self.store.heartbeat(run_id, str(event.get("message", "")))
                    elif kind == "finished":
                        state = event.get("status")
                        result = (state if state in {"succeeded", "partial", "failed", "empty", "unavailable"} else "failed", str(event.get("message", ""))[:400])
                    elif kind == "protocol_error":
                        return "failed", "采集结果格式异常。"
                return result
            finally:
                self.terminate(process)
                process.stdout.close()

    def start_scheduler(self):
        if self.scheduler is not None:
            return
        def loop():
            while not self.stop_event.wait(15):
                try:
                    self.start(scheduled=True)
                except Exception:
                    logger.exception("Job-market schedule check failed")
        self.scheduler = threading.Thread(target=loop, daemon=True, name="job-market-scheduler")
        self.scheduler.start()
        atexit.register(self.stop_event.set)
