import hashlib
import json
import re
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCES = {"ncss": "国家大学生就业服务平台", "api": "企业招聘 API", "shixiseng": "实习僧", "website": "企业招聘官网"}
FIELDS = ("job_title", "company_name", "location", "salary", "job_type", "education", "industry", "company_nature", "company_size", "welfare", "publish_date", "job_desc", "job_url")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="microseconds")


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value, limit=1000):
    if isinstance(value, list):
        value = " / ".join(str(item.get("name", "")) if isinstance(item, dict) else str(item) for item in value)
    parser = TextParser()
    parser.feed(str(value or "")[:50000])
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", "".join(parser.parts))
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()[:limit]


def canonical_url(value):
    try:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in {"spm", "from", "ref", "source", "trackid"}]
        fragment = parsed.fragment if parsed.fragment.startswith("/") else ""
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(sorted(query)), fragment))[:2000]
    except ValueError:
        return ""


def salary_range(value):
    text = str(value or "").strip().replace(",", "").replace("，", "").replace("～", "-").replace("–", "-")
    if not text or any(word in text for word in ("面议", "negotiable", "以上", "以下", "起")):
        return None, None, "unknown"
    # Require a stated currency scale or period. Annual/day/hour pay never enters monthly statistics.
    unit = "year" if re.search(r"年|year|annual", text, re.I) else "day" if re.search(r"天|日|day", text, re.I) else "hour" if re.search(r"小时|hour", text, re.I) else "month" if re.search(r"月|[kK]|千", text) else "unknown"
    if unit == "unknown":
        return None, None, unit
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kK万千]?)\s*(?:[-~至]\s*(\d+(?:\.\d+)?)\s*([kK万千]?))?", text)
    if not match:
        return None, None, "unknown"
    low, low_scale, high, high_scale = match.groups()
    multipliers = {"k": 1000, "K": 1000, "千": 1000, "万": 10000, "": 1}
    shared = high_scale or low_scale
    minimum = float(low) * multipliers[low_scale or shared]
    maximum = float(high or low) * multipliers[high_scale or shared]
    if minimum <= 0 or maximum < minimum or maximum > 10000000:
        return None, None, "unknown"
    return minimum, maximum, unit


def normalize(raw, source):
    if not isinstance(raw, dict) or source not in SOURCES:
        return None
    row = {key: plain(raw.get(key), 12000 if key == "job_desc" else 1000) for key in FIELDS}
    row["job_url"] = canonical_url(raw.get("job_url"))
    if not row["job_title"] or not row["company_name"] or not row["job_url"]:
        return None
    row["job_type"] = row["job_type"] if row["job_type"] in {"intern", "graduate", "experienced"} else "unknown"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["publish_date"]):
        row["publish_date"] = ""
    row["source"] = source
    row["source_label"] = SOURCES[source]
    row["salary_min"], row["salary_max"], row["salary_unit"] = salary_range(row["salary"])
    identity = str(raw.get("source_record_id") or "")
    if not identity:
        # Listing URLs alone are not unique: some upstream adapters only return a company landing page.
        identity = "\0".join(row[key] for key in ("job_url", "job_title", "company_name", "location"))
    row["id"] = hashlib.sha256((source + "\0" + identity).encode()).hexdigest()[:32]
    row["content_hash"] = hashlib.sha256(json.dumps({key: row[key] for key in FIELDS}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return row


class MarketStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        columns = ",".join(f"{key} TEXT NOT NULL" for key in FIELDS)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, {columns}, source TEXT NOT NULL, source_label TEXT NOT NULL,
                    salary_min REAL, salary_max REAL, salary_unit TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, changed_at TEXT NOT NULL, content_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_seen ON jobs(last_seen,source);
                CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_name);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, trigger TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, lease_until TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    config TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS runs_status ON runs(status,started_at);
                CREATE TABLE IF NOT EXISTS run_sources (
                    run_id TEXT NOT NULL REFERENCES runs(id), source TEXT NOT NULL, status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '', received INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(run_id,source));
                CREATE TABLE IF NOT EXISTS observations (
                    run_id TEXT NOT NULL REFERENCES runs(id), job_id TEXT NOT NULL REFERENCES jobs(id),
                    observed_at TEXT NOT NULL, change TEXT NOT NULL,
                    PRIMARY KEY(run_id,job_id));
                CREATE INDEX IF NOT EXISTS observations_date ON observations(observed_at,change);
                CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, next_run_at TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def settings(self):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM settings WHERE id=1").fetchone()
        return {**json.loads(row["payload"]), "next_run_at": row["next_run_at"]} if row else None

    def save_settings(self, config, *, due=None):
        with self.connect() as conn:
            conn.execute("INSERT INTO settings VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,next_run_at=excluded.next_run_at",
                         (json.dumps(config, ensure_ascii=False), due or after(config["interval_hours"] * 3600)))

    def claim_run(self, config, trigger="manual", *, require_due=False):
        from uuid import uuid4
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            stamp = now()
            conn.execute("UPDATE runs SET status='interrupted',finished_at=?,error='采集进程中断，保留已获取的记录。' WHERE status='running' AND lease_until<=?", (stamp, stamp))
            conn.execute("UPDATE run_sources SET status='interrupted',message='采集进程中断，已保留获取到的岗位。' WHERE status IN ('queued','running') AND run_id IN (SELECT id FROM runs WHERE status='interrupted')")
            if conn.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
                return None
            if require_due:
                setting = conn.execute("SELECT next_run_at,payload FROM settings WHERE id=1").fetchone()
                if not setting or setting["next_run_at"] > stamp or not json.loads(setting["payload"])["enabled"]:
                    return None
            run_id = uuid4().hex
            conn.execute("INSERT INTO runs(id,trigger,status,started_at,lease_until,config) VALUES(?,?,'running',?,?,?)",
                         (run_id, trigger, stamp, after(90), json.dumps(config, ensure_ascii=False)))
            conn.executemany("INSERT INTO run_sources(run_id,source,status) VALUES(?,?,'queued')", [(run_id, source) for source in config["sources"]])
            conn.execute("UPDATE settings SET next_run_at=? WHERE id=1", (after(config["interval_hours"] * 3600),))
            return run_id

    def heartbeat(self, run_id, message=""):
        with self.connect() as conn:
            conn.execute("UPDATE runs SET lease_until=?,message=? WHERE id=? AND status='running'", (after(90), message[:300], run_id))

    def cancelled(self, run_id):
        with self.connect() as conn:
            row = conn.execute("SELECT cancel_requested,status FROM runs WHERE id=?", (run_id,)).fetchone()
        return not row or row["cancel_requested"] or row["status"] != "running"

    def cancel(self):
        with self.connect() as conn:
            conn.execute("UPDATE runs SET cancel_requested=1 WHERE status='running'")

    def source_status(self, run_id, source, status, message=""):
        with self.connect() as conn:
            conn.execute("UPDATE run_sources SET status=?,message=? WHERE run_id=? AND source=?", (status, message[:400], run_id, source))

    def ingest(self, run_id, source, records):
        accepted, rejected = 0, 0
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute("SELECT status,cancel_requested FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["status"] != "running" or run["cancel_requested"]:
                return 0
            stamp = now()
            for raw in records:
                row = normalize(raw, source)
                if not row:
                    rejected += 1
                    continue
                old = conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
                # A list callback can precede detail enrichment: preserve already known nonempty fields.
                if old:
                    for key in FIELDS:
                        if not row[key] and old[key]:
                            row[key] = old[key]
                    row["salary_min"], row["salary_max"], row["salary_unit"] = salary_range(row["salary"])
                    row["content_hash"] = hashlib.sha256(json.dumps({key: row[key] for key in FIELDS}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                change = "new" if not old else "changed" if old["content_hash"] != row["content_hash"] else "seen"
                row.update(first_seen=old["first_seen"] if old else stamp, last_seen=stamp,
                           changed_at=stamp if change in {"new", "changed"} else old["changed_at"])
                columns = list(row)
                conn.execute(f"INSERT INTO jobs({','.join(columns)}) VALUES({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET " +
                    ",".join(f"{key}=excluded.{key}" for key in columns if key not in {"id", "first_seen"}), list(row.values()))
                conn.execute("""INSERT INTO observations VALUES(?,?,?,?) ON CONFLICT(run_id,job_id) DO UPDATE SET
                    observed_at=excluded.observed_at, change=CASE WHEN observations.change='new' THEN 'new'
                    WHEN observations.change='changed' THEN 'changed' ELSE excluded.change END""", (run_id, row["id"], stamp, change))
                accepted += 1
            conn.execute("UPDATE run_sources SET received=received+?,rejected=rejected+? WHERE run_id=? AND source=?", (accepted, rejected, run_id, source))
        return accepted

    def finish(self, run_id, status, error=""):
        with self.connect() as conn:
            conn.execute("UPDATE runs SET status=?,finished_at=?,error=? WHERE id=? AND status='running'", (status, now(), error[:400], run_id))
            if status in {"cancelled", "interrupted", "failed"}:
                conn.execute("UPDATE run_sources SET status=? WHERE run_id=? AND status IN ('running','queued')", (status, run_id))

    def runs(self, limit=12):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM runs ORDER BY started_at DESC,id DESC LIMIT ?", (limit,))]
            for row in rows:
                row.pop("config", None)
                row["sources"] = [dict(item) for item in conn.execute("SELECT * FROM run_sources WHERE run_id=?", (row["id"],))]
                row["counts"] = {item["change"]: item["count"] for item in conn.execute("SELECT change,COUNT(*) count FROM observations WHERE run_id=? GROUP BY change", (row["id"],))}
        return rows

    @staticmethod
    def where(filters):
        clauses, values = ["1=1"], []
        for key in ("source", "job_type", "salary_unit", "education", "company_nature"):
            if filters.get(key):
                clauses.append(f"{key}=?")
                values.append(filters[key])
        for key in ("location", "company_name", "industry"):
            if filters.get(key):
                clauses.append(f"instr(lower({key}),lower(?))>0")
                values.append(filters[key])
        if filters.get("q"):
            clauses.append("instr(lower(job_title||' '||company_name||' '||location||' '||job_desc),lower(?))>0")
            values.append(filters["q"])
        if filters.get("days"):
            clauses.append("last_seen>=?")
            values.append((datetime.now(timezone.utc) - timedelta(days=filters["days"])).isoformat(timespec="seconds"))
        for key, operator in (("salary_min", ">="), ("salary_max", "<=")):
            if filters.get(key) is not None:
                clauses.append(f"{key}{operator}?")
                values.append(filters[key])
        for key, operator in (("date_from", ">="), ("date_to", "<=")):
            if filters.get(key):
                clauses.append(f"publish_date{operator}? AND publish_date<>''")
                values.append(filters[key])
        return " AND ".join(clauses), values

    def jobs(self, filters, page=1, size=12, sort="recent"):
        where, values = self.where(filters)
        ordering = {"recent": "last_seen DESC,first_seen DESC,id", "newest": "first_seen DESC,id", "salary": "salary_min IS NULL,salary_min DESC,id"}[sort]
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", values).fetchone()[0]
            rows = [dict(row) for row in conn.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY {ordering} LIMIT ? OFFSET ?", [*values, size, (page - 1) * size])]
        for row in rows:
            row["stale"] = row["last_seen"] < (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        return {"items": rows, "total": total, "page": page, "page_size": size, "pages": max(1, (total + size - 1) // size)}

    def detail(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def stats(self, filters):
        where, values = self.where(filters)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        with self.connect() as conn:
            summary = dict(conn.execute(f"SELECT COUNT(*) total,COUNT(DISTINCT company_name) companies,MAX(last_seen) last_seen,SUM(first_seen>=?) new_7d FROM jobs WHERE {where}", [cutoff, *values]).fetchone())
            summary["salary"] = {}
            for unit in ("month", "day", "year", "hour"):
                amounts = [row[0] for row in conn.execute(f"SELECT (salary_min+salary_max)/2 FROM jobs WHERE {where} AND salary_unit=? AND salary_min IS NOT NULL", [*values, unit])]
                summary["salary"][unit] = {"count": len(amounts), "median_midpoint": round(statistics.median(amounts)) if amounts else None}
            for name, column in (("sources", "source"), ("cities", "location"), ("industries", "industry"), ("education", "education"), ("types", "job_type")):
                summary[name] = [dict(row) for row in conn.execute(f"SELECT {column} name,COUNT(*) count FROM jobs WHERE {where} AND {column}<>'' GROUP BY {column} ORDER BY count DESC,name LIMIT 8", values)]
            summary["timeline"] = [dict(row) for row in conn.execute(f"""SELECT date(o.observed_at,'+8 hours') day,
                COUNT(DISTINCT o.job_id) observed,COUNT(DISTINCT CASE WHEN o.change='new' THEN o.job_id END) added,
                COUNT(DISTINCT CASE WHEN o.change='changed' THEN o.job_id END) changed
                FROM observations o JOIN jobs j ON o.job_id=j.id WHERE o.observed_at>=? AND j.id IN (SELECT id FROM jobs WHERE {where})
                GROUP BY day ORDER BY day""", [cutoff, *values])]
            keywords = ["Python", "Java", "JavaScript", "SQL", "Excel", "Figma", "CAD", "C++", "机器学习", "数据分析", "项目管理", "英语", "沟通", "销售"]
            patterns = {word: re.compile((r"(?<![a-zA-Z0-9])" + re.escape(word) + r"(?![a-zA-Z0-9])") if word.isascii() else re.escape(word), re.I) for word in keywords}
            mentions = dict.fromkeys(keywords, 0)
            for row in conn.execute(f"SELECT job_desc FROM jobs WHERE {where}", values):
                for word, pattern in patterns.items():
                    mentions[word] += bool(pattern.search(row[0]))
            summary["skills"] = [{"name": word, "count": count} for word, count in sorted(mentions.items(), key=lambda pair: (-pair[1], pair[0])) if count][:8]
        summary["new_7d"] = summary["new_7d"] or 0
        summary["salary_note"] = "薪资中位数基于同一计薪周期的区间中点；日薪、月薪、年薪分别统计，未提供薪资的岗位不参与。"
        summary["scope_note"] = "统计仅代表已采集样本，新增指首次被本系统发现；未再次采集到不等于岗位关闭，招聘状态请以原站为准。"
        return summary
