"""Isolated JSONL bridge to pinned JobHunter crawlers. Never imports the host app."""
import json
import logging
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


class Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.count = 0

    def emit(self, record):
        self.count += 1


def main():
    config = json.load(sys.stdin)
    source = sys.argv[1]
    try:
        from crawler.api_crawler import ApiCrawler
        from crawler.ncss_crawler import NCSSCrawler
        from crawler.shixiseng_crawler import ShixisengCrawler
        from crawler.website_crawler import WebsiteCrawler
    except ImportError:
        emit("finished", status="unavailable", message="采集依赖未安装，请安装 backend/requirements-jobs.txt 并准备 Chromium。")
        return 2
    if not os.environ.get("JOBHUNTER_BROWSER") and os.name == "nt":
        for browser in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            if Path(browser).is_file():
                os.environ["JOBHUNTER_BROWSER"] = browser
                break
    crawler = {"api": ApiCrawler, "ncss": NCSSCrawler, "shixiseng": ShixisengCrawler, "website": WebsiteCrawler}[source]()
    crawler.max_pages = config["max_pages"]
    crawler.timeout = min(30000, config["timeout_seconds"] * 1000)
    crawler.max_retries = 1
    crawler.min_delay, crawler.max_delay = 2, 4
    seen = set()
    started = time.monotonic()
    phase = {"enriching": False}
    warnings = Warnings()
    logging.getLogger().addHandler(warnings)
    crawler.set_stop_check(lambda: (len(seen) >= config["max_jobs"] and not phase["enriching"]) or time.monotonic() - started >= config["timeout_seconds"])
    crawler.set_progress_callback(lambda message, total=0: emit("progress", message=str(message)[:250]))
    if source == "api":
        original = crawler._parse_api_item
        def parse_item(item, company, definition):
            row = original(item, company, definition)
            if row:
                identity = next((item.get(key) for key in ("id", "positionId", "jdId", "jobId", "Id", "PositionId", "postId", "jobUnionId", "job_code") if item.get(key)), None)
                if identity:
                    row["source_record_id"] = company + ":" + str(identity)
                if not str(row.get("job_url", "")).startswith(("https://", "http://")):
                    template = definition.get("job_url_template")
                    try:
                        row["job_url"] = template.format(**item) if template else definition.get("referer", "")
                    except (KeyError, ValueError):
                        row["job_url"] = definition.get("referer", "")
                if company == "腾讯" and item.get("postId"):
                    label = str(item.get("recruitLabelName") or item.get("projectName") or "")
                    row["job_type"] = "intern" if "实习" in label else "graduate" if "应届" in label or "校招" in label else row["job_type"]
                    crawler.emit_jobs([row])
                    try:
                        response = crawler.context.request.get(
                            "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId",
                            params={"postId": str(item["postId"])}, timeout=8000)
                        details = response.json().get("data") if response.ok else None
                        if isinstance(details, dict):
                            row["job_desc"] = "\n\n".join(str(details.get(key) or "") for key in ("desc", "request") if details.get(key))[:12000]
                        else:
                            logging.warning("Tencent detail unavailable")
                    except Exception:
                        logging.warning("Tencent detail request failed")
                    crawler.emit_jobs([row])
            return row
        crawler._parse_api_item = parse_item

    def jobs(records):
        batch = []
        for row in records:
            identity = str(row.get("source_record_id") or "") or str(row.get("job_url", "")) + str(row.get("job_title", ""))
            if identity not in seen and len(seen) >= config["max_jobs"]:
                continue
            seen.add(identity)
            batch.append(row)
            if len(batch) >= 10:
                emit("jobs", records=batch)
                batch = []
        if batch:
            emit("jobs", records=batch)
    crawler.set_jobs_callback(jobs)
    enrichment = "_enrich_jobs" if source == "ncss" else "enrich_jobs" if source == "shixiseng" else None
    if enrichment:
        original_enrich = getattr(crawler, enrichment)
        def enrich(*args, **kwargs):
            phase["enriching"] = True
            try:
                return original_enrich(*args, **kwargs)
            finally:
                phase["enriching"] = False
        setattr(crawler, enrichment, enrich)
    try:
        rows = crawler.run(filters={key: config[key] for key in ("companies", "industries", "locations") if config.get(key)})
        jobs(rows)
        status = "partial" if seen and warnings.count else "succeeded" if seen else "failed" if warnings.count else "empty"
        message = "部分请求未成功，已保留获取到的岗位。" if status == "partial" else "本轮未获得可解析的岗位，请检查来源访问或页面、接口适配状态。" if status == "failed" else "本轮未获得岗位，不能据此判断来源没有招聘。" if status == "empty" else "采集完成。"
        emit("finished", status=status, message=message)
        return 0
    except Exception:
        logging.exception("JobHunter source failed")
        emit("finished", status="failed", message="来源未完成采集，请检查网络、来源可用性或浏览器运行环境。")
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    raise SystemExit(main())
