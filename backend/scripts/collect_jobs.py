"""Run the same collector used by the app, or host a dedicated scheduler worker."""
import argparse
from pathlib import Path
import sys
import time
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.job_market.collector import Collector, CollectionSettings
from services.job_market.store import SOURCES


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="JobHunter 岗位采集与调度")
    parser.add_argument("--once", action="store_true", help="运行一次采集")
    parser.add_argument("--worker", action="store_true", help="运行独立定时采集进程")
    parser.add_argument("--sources", nargs="+", choices=list(SOURCES))
    parser.add_argument("--companies", nargs="+")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    args = parser.parse_args()
    collector = Collector()
    if args.worker:
        collector.start_scheduler()
        print("岗位定时采集进程已启动。", flush=True)
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            collector.stop_event.set()
        return
    if not args.once:
        parser.error("请指定 --once 或 --worker")
    settings = {key: value for key, value in collector.store.settings().items() if key != "next_run_at"}
    for key in ("sources", "companies", "max_pages", "max_jobs", "timeout_seconds"):
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    config = CollectionSettings.model_validate(settings).model_dump()
    run_id = collector.store.claim_run(config, "manual")
    if not run_id:
        raise SystemExit("已有采集任务正在运行。")
    print(json.dumps({"run_id": run_id, "sources": config["sources"], "status": "running"}), flush=True)
    try:
        collector.collect(run_id, config)
    except KeyboardInterrupt:
        collector.stop_event.set()
        collector.store.finish(run_id, "cancelled")
    run = next(row for row in collector.store.runs() if row["id"] == run_id)
    print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)
    if run["status"] not in {"succeeded", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
