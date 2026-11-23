"""Abortable background pipeline batch tasks with real-time SSE progress streaming."""
import json
import threading
import time
import uuid

from . import db, llm_env

STAGE_LABELS = {
    "evaluate": "批量 AI 评估",
    "rewrite": "批量简历微调",
    "greet": "批量打招呼语微调",
}


class PipelineTaskManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._tasks = {}  # task_id -> dict
        self._events = {}  # task_id -> threading.Event (abort)
        self._version = 0

    def _notify(self):
        self._version += 1
        self._cond.notify_all()

    def _public(self, task):
        return {
            "task_id": task["task_id"],
            "stage": task["stage"],
            "label": task["label"],
            "status": task["status"],
            "total": task["total"],
            "done": task["done"],
            "failed": task["failed"],
            "current": task["current"],
            "message": task["message"],
            "percent": int(round((task["done"] / task["total"]) * 100)) if task["total"] else (100 if task["status"] == "completed" else 0),
            "logs": task["logs"][-20:],
            "started_at": task["started_at"],
            "finished_at": task["finished_at"],
        }

    def active_for(self, owner):
        with self._lock:
            owned = [t for t in self._tasks.values() if t["owner"] == owner]
            owned.sort(key=lambda t: t["started_at"], reverse=True)
            running = [self._public(t) for t in owned if t["status"] == "running"]
            latest = self._public(owned[0]) if owned else None
            return {"running": running, "latest": latest, "version": self._version}

    def get_task(self, owner, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["owner"] != owner:
                return None
            return self._public(task)

    def abort(self, owner, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["owner"] != owner:
                return False
            ev = self._events.get(task_id)
            if ev:
                ev.set()
            if task["status"] == "running":
                task["message"] = "正在中止当前任务…"
                self._notify()
            return True

    def start(self, owner, stage, *, ids=None, style="standard", limit=20):
        if stage not in STAGE_LABELS:
            raise ValueError("仅支持 evaluate / rewrite / greet 批量任务。")
        with self._lock:
            for existing in self._tasks.values():
                if existing["owner"] == owner and existing["status"] == "running":
                    raise RuntimeError("已有后台流水线任务正在运行，请等待完成或先中止。")
            task_id = uuid.uuid4().hex[:12]
            abort_ev = threading.Event()
            task = {
                "task_id": task_id,
                "owner": owner,
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "status": "running",
                "total": 0,
                "done": 0,
                "failed": 0,
                "current": "",
                "message": "正在准备任务队列…",
                "logs": [],
                "started_at": time.time(),
                "finished_at": 0.0,
            }
            self._tasks[task_id] = task
            self._events[task_id] = abort_ev
            # Prune old finished tasks beyond 20
            finished = sorted(
                [t for t in self._tasks.values() if t["status"] != "running"],
                key=lambda t: t["started_at"],
            )
            for stale in finished[:-20]:
                self._tasks.pop(stale["task_id"], None)
                self._events.pop(stale["task_id"], None)
            self._notify()

        worker = threading.Thread(
            target=self._run_worker,
            args=(task_id, owner, stage, list(ids or []), style, int(limit or 20), abort_ev),
            daemon=True,
            name=f"pipeline-task-{task_id}",
        )
        worker.start()
        return self.get_task(owner, task_id)

    def _update(self, task_id, **fields):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            log_line = fields.pop("log", None)
            task.update(fields)
            if log_line:
                task["logs"].append(f"{time.strftime('%H:%M:%S')} {log_line}")
            self._notify()

    def _select_targets(self, conn, owner, stage, ids, limit):
        from . import recruitment_pipeline as rp
        rp.ensure_rows(conn, owner)
        if ids:
            targets = []
            for item in ids[:50]:
                ident = rp._identity(item)
                if not ident:
                    continue
                row = conn.execute(
                    """
                    SELECT j.source, j.url_key, j.title, j.company
                    FROM recruitment_pipeline p
                    JOIN recruitment_listings j USING(owner, source, url_key)
                    WHERE p.owner=? AND p.source=? AND p.url_key=?
                    """,
                    (owner, *ident),
                ).fetchone()
                if row:
                    targets.append(dict(row))
            return targets
        if stage == "evaluate":
            rows = rp._pipeline_candidates(conn, owner, ("cleaned", "reeval"), limit)
        elif stage == "rewrite":
            rows = rp._pipeline_candidates(conn, owner, ("deep",), limit)
        else:
            rows = [r for r in rp._pipeline_candidates(conn, owner, ("screened", "rewritten"), limit)
                    if r["stage"] == "rewritten" or r["review_type"] == "mass"]
        return [{"source": r["source"], "url_key": r["url_key"], "title": r["title"], "company": r["company"]} for r in rows]

    def _run_worker(self, task_id, owner, stage, ids, style, limit, abort_ev):
        from . import recruitment_pipeline as rp
        try:
            conn = db._get_conn()
            config = rp.load_config(conn, owner)
            targets = self._select_targets(conn, owner, stage, ids, limit)
            total = len(targets)
            if total == 0:
                self._update(
                    task_id, status="completed", total=0, done=0,
                    message="没有需要处理的候选岗位。", finished_at=time.time(),
                    log="队列为空，任务结束。",
                )
                return

            self._update(task_id, total=total, message=f"共 {total} 个岗位待处理…", log=f"启动 {STAGE_LABELS[stage]}（共 {total} 岗）")
            done = 0
            failed = 0
            for idx, item in enumerate(targets, 1):
                if abort_ev.is_set():
                    self._update(
                        task_id, status="aborted", done=done, failed=failed,
                        current="", message=f"已中止（已完成 {done}/{total} 岗）。",
                        finished_at=time.time(), log=f"用户中止任务（已完成 {done}/{total}）",
                    )
                    return
                label = f"{item['title']} · {item['company']}".strip(" ·")
                self._update(task_id, current=label, message=f"{idx}/{total} 正在处理 {label}…")
                try:
                    with conn:
                        conn.execute("BEGIN IMMEDIATE")
                        if stage == "rewrite":
                            res = rp.run_rewrite(conn, owner, config, 1, target=(item["source"], item["url_key"]))
                        elif stage == "greet":
                            res = rp.run_greet(conn, owner, config, 1, target=(item["source"], item["url_key"]), style=style)
                        else:
                            # Single-job evaluate via existing screen + deep logic
                            res = rp.run_evaluate_single(conn, owner, config, (item["source"], item["url_key"]))
                    if res.get("error"):
                        failed += 1
                        self._update(task_id, done=done, failed=failed, log=f"✗ {label}：{res['error']}")
                    else:
                        done += 1
                        self._update(task_id, done=done, failed=failed, log=f"✓ {label} 完成")
                except Exception as exc:
                    failed += 1
                    self._update(task_id, done=done, failed=failed, log=f"✗ {label}：{type(exc).__name__}")

            self._update(
                task_id, status="completed", done=done, failed=failed, current="",
                message=f"已完成 {done}/{total} 岗" + (f"（{failed} 失败）" if failed else "。"),
                finished_at=time.time(), log=f"全部完成：成功 {done}，失败 {failed}",
            )
        except Exception as exc:
            self._update(
                task_id, status="failed", current="",
                message=f"任务异常：{exc}", finished_at=time.time(),
                log=f"任务异常退出：{type(exc).__name__}",
            )

    def stream_sse(self, owner, *, max_seconds=120):
        deadline = time.monotonic() + max_seconds
        last_ver = -1
        while time.monotonic() < deadline:
            with self._lock:
                if self._version == last_ver:
                    self._cond.wait(timeout=8.0)
                snap = self.active_for(owner)
                cur_ver = snap["version"]
            if cur_ver != last_ver:
                last_ver = cur_ver
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                if not snap["running"]:
                    # Let client receive final completed/aborted event, then yield cleanly
                    return
            else:
                yield ": keep-alive\n\n"


TASK_MANAGER = PipelineTaskManager()
