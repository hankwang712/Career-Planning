"""Read JobHunter's existing store and merge recruitment leads without writing either source."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MARKET_DB = Path(__file__).resolve().parents[3] / "data/app_data/job_market.sqlite3"
TRACKING_KEYS = {"source", "sourcetoken", "from", "ref", "refer", "referer", "sessionid", "spm", "trackingid"}


def canonical_url(value):
    """Keep job IDs, functional query parameters and SPA fragments."""
    try:
        url = urlsplit(str(value or "").strip())
        if url.scheme not in {"http", "https"} or not url.hostname:
            return ""
        def query(value):
            return urlencode(sorted((key, val) for key, val in parse_qsl(value, keep_blank_values=True)
                                    if key.lower() not in TRACKING_KEYS and not key.lower().startswith("utm_")))
        fragment, sep, parameters = url.fragment.partition("?")
        fragment = fragment.rstrip("/") + ("?" + query(parameters) if sep and query(parameters) else "")
        return urlunsplit(("https", url.netloc.lower(), url.path.rstrip("/"), query(url.query), fragment))
    except ValueError:
        return ""


def normalized(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def batch_parts(value):
    value = normalized(value)
    year = re.search(r"(?:(20\d{2})|(\d{2}))届", value)
    year = (year[1] or "20" + year[2]) if year else ""
    kind = "intern" if "实习" in value else "graduate" if re.search("校招|校园|应届|届", value) else "experienced" if "社招" in value else ""
    season = next((word for word in ("暑期", "寒假", "春招", "秋招", "日常") if word in value), "")
    return year, kind, season


def compatible_batches(left, right):
    a, b = batch_parts(left), batch_parts(right)
    if any(x and y and x != y for x, y in zip(a, b)):
        return False
    # Unrecognised, distinct batch labels should not be silently collapsed.
    return not (left and right and not any(a) and not any(b) and normalized(left) != normalized(right))


def vacancy_id(value):
    url = urlsplit(canonical_url(value))
    for key, value in [*parse_qsl(url.query), *parse_qsl(url.fragment.partition("?")[2])]:
        if key.lower() in {"jobid", "positionid", "postid", "jdid", "job_code", "jobunionid"}:
            return url.hostname, value
    match = re.search(r"/(?:jobs?|positions?|posts?|vacanc(?:y|ies))/(?!list(?:/|$))([\w-]+)", url.path + "/" + url.fragment, re.I)
    return (url.hostname, match[1]) if match else None


def provenance(job):
    return job.get("provenance") or [{key: job.get(key, "") for key in
        ("source_type", "source_name", "source_record_id", "url", "announcement_url", "published_at", "updated_at", "snapshot_at", "batch", "deadline")}]


def merge_pair(left, right):
    def quality(job):
        return (job.get("detail_state") == "read", job.get("source_type") != "snapshot",
                bool(job.get("description")), len(job.get("description", "")), str(job.get("updated_at", "")))
    winner, other = (left, right) if quality(left) >= quality(right) else (right, left)
    merged = dict(winner)
    # Do not fill a winner's date/read-state from a different source: evidence stays attributable.
    for key in ("url", "announcement_url", "city", "degree", "industry"):
        if not merged.get(key) or key == "industry" and merged[key] == "综合":
            merged[key] = other.get(key, "")
    if len(str(other.get("batch", ""))) > len(str(merged.get("batch", ""))):
        merged["batch"] = other["batch"]
    origins = [*provenance(left), *provenance(right)]
    merged["provenance"] = [row for index, row in enumerate(origins) if row not in origins[:index]]
    merged["duplicate_count"] = left.get("duplicate_count", 0) + right.get("duplicate_count", 0) + 1
    return merged


def deduplicate_jobs(jobs):
    result, groups = [], {}
    for raw in jobs:
        if not raw:
            continue
        job = dict(raw)
        job["provenance"] = list(provenance(job))
        # A shared careers landing page alone is never a vacancy identity.
        key = tuple(normalized(job.get(field)) for field in ("company", "role", "city"))
        match = None
        for index in groups.get(key, []):
            existing = result[index]
            if not compatible_batches(existing.get("batch", ""), job.get("batch", "")):
                continue
            first, second = vacancy_id(existing.get("url")), vacancy_id(job.get("url"))
            if first and second and first[0] == second[0] and first[1] != second[1]:
                continue
            if key[0] and key[1]:
                match = index
                break
        if match is None:
            groups.setdefault(key, []).append(len(result))
            result.append(job)
        else:
            result[match] = merge_pair(result[match], job)
    return result


def read_jobhunter_jobs(path=None, limit=10000):
    path = Path(path or MARKET_DB)
    if not path.is_file():
        return {"jobs": [], "status": "not_collected", "limitations": ["JobHunter 尚无本地岗位库，本轮仅使用 Radar 数据。"]}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM jobs ORDER BY last_seen DESC,id LIMIT ?", (limit + 1,)).fetchall()
    except sqlite3.Error:
        return {"jobs": [], "status": "unavailable", "limitations": ["JobHunter 岗位库暂不可读取，本轮保留 Radar 检索结果。"]}
    limited = len(rows) > limit
    types = {"intern": "实习", "graduate": "校招", "experienced": "社招"}
    jobs = []
    for row in rows[:limit]:
        row = dict(row)
        jobs.append({"company": row["company_name"], "role": row["job_title"], "city": row["location"],
            "degree": row["education"], "batch": types.get(row["job_type"], ""), "deadline": "",
            "url": row["job_url"], "announcement_url": "", "industry": row["industry"],
            "description": row["job_desc"], "published_at": row["publish_date"],
            "updated_at": row["last_seen"], "snapshot_at": row["last_seen"],
            "source_type": "jobhunter", "source_name": "JobHunter · " + row["source_label"],
            "source_record_id": row["id"], "source_sheet": "", "detail_state": "not_read",
            "salary": row["salary"], "published_at_source": "jobhunter_listing" if row["publish_date"] else "unverified"})
    limitations = ["JobHunter 数据来自本地采集记录；最近采集时间不代表公告发布日期或岗位仍开放。"] if jobs else []
    if limited:
        limitations.append(f"JobHunter 本轮最多读取最近采集的 {limit} 条记录，历史岗位覆盖可能不完整。")
    return {"jobs": jobs, "status": "ok" if jobs else "empty", "limitations": limitations}
