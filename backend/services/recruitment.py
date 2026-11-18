"""Account-scoped collection runs, listing search and CSV exchange."""

from contextlib import ExitStack
import csv
from hashlib import sha256
from io import StringIO
from ipaddress import ip_address
import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, redirect, render_template, request, url_for
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import db
from .paths import APP_DATA_DIR
from .recruitment_chrome import collect_boss_in_chrome, use_local_chrome
from .recruitment_sources import (
    CITIES, SOURCES, collect_local_boss, collect_source, launch_browser, listing_url, read_saved_page, search_url,
)
from .user_state import _current_user, _login_required


blueprint = Blueprint("recruitment", __name__)
API = "/api/job-market/collection"
logger = logging.getLogger(__name__)
FIELDS = ("source", "title", "company", "location", "salary", "description", "url", "updated_at")
CSV_ALIASES = {"platform": "source", "job_title": "title", "company_name": "company", "city": "location",
               "jd_text": "description", "job_link": "url", "post_link": "url", "raw_text": "description",
               "note_title": "title", "crawl_time": "updated_at"}
html_import_lock = threading.Lock()
UNRENDERABLE_TEXT = re.compile(r"[\ue000-\uf8ff\U000f0000-\U0010fffd\ufffd]")


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recruitment_runs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            keyword TEXT NOT NULL, city TEXT NOT NULL, started_at REAL NOT NULL,
            status TEXT NOT NULL, progress TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS recruitment_runs_owner ON recruitment_runs(owner, started_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS recruitment_active_run ON recruitment_runs(status) WHERE status = 'running';
        CREATE TABLE IF NOT EXISTS recruitment_listings (
            owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE, source TEXT NOT NULL,
            url_key TEXT NOT NULL, title TEXT NOT NULL, company TEXT NOT NULL, location TEXT NOT NULL,
            salary TEXT NOT NULL, description TEXT NOT NULL, url TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY(owner, source, url_key)
        );
        CREATE INDEX IF NOT EXISTS recruitment_listings_owner ON recruitment_listings(owner, updated_at DESC);
    """)


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keyword: str = Field(min_length=1, max_length=80)
    city: str = ""
    sources: list[str] = Field(min_length=1, max_length=5)
    limit: int = Field(default=20, ge=1, le=30, strict=True)
    boss_local: bool = Field(default=False, strict=True)


def clean_listing(fields):
    for key in ("title", "company", "location", "salary", "description"):
        value = str(fields.get(key) or "").strip()
        if key == "salary" and UNRENDERABLE_TEXT.search(value):
            fields[key] = ""
        elif key == "description":
            lines = [line.strip() for line in value.splitlines() if not UNRENDERABLE_TEXT.search(line)]
            fields[key] = "\n".join(lines).strip()
        else:
            fields[key] = UNRENDERABLE_TEXT.sub("", value)
    return fields


def save_rows(conn, owner, source, rows):
    seen = set()
    records = []
    for row in rows:
        row = clean_listing(dict(row))
        url = listing_url(source, str(row.get("url") or "")) if row.get("url") else ""
        title = str(row.get("title") or "").strip()[:250]
        if not title and source == "xiaohongshu":
            description = str(row.get("description") or "").strip()
            title = (description.splitlines() or [""])[0][:250]
        if not url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        values = [str(row.get(key) or "").strip()[:limit] for key, limit in
                  (("company", 250), ("location", 120), ("salary", 120), ("description", 6000))]
        records.append((owner, source, url, title, *values, url, time.time()))
    conn.executemany("""
        INSERT INTO recruitment_listings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner, source, url_key) DO UPDATE SET
            title=excluded.title, company=excluded.company, location=excluded.location,
            salary=CASE WHEN excluded.salary='' THEN recruitment_listings.salary ELSE excluded.salary END,
            description=excluded.description, url=excluded.url, updated_at=excluded.updated_at
    """, records)
    return len(records)


def save_progress(conn, owner, run_id, progress, status="running"):
    conn.execute("UPDATE recruitment_runs SET status=?, progress=? WHERE owner=? AND id=? AND status='running'",
                 (status, json.dumps(progress, ensure_ascii=False), owner, run_id))


def run_collection(owner, run_id, config, progress):
    conn = db._get_conn()
    try:
        from playwright.sync_api import Error as BrowserError, sync_playwright

        with sync_playwright() as playwright, ExitStack() as browsers:
            browser = None

            def boss_status(status, message):
                progress["boss"] = {"status": status, "message": message}
                with conn:
                    save_progress(conn, owner, run_id, progress)

            for source in config.sources:
                progress[source] = {"status": "running"}
                with conn:
                    save_progress(conn, owner, run_id, progress)
                try:
                    if source == "boss" and config.boss_local:
                        if use_local_chrome():
                            status, message, rows = collect_boss_in_chrome(
                                config.keyword, config.city, config.limit, boss_status
                            )
                        else:
                            profile = APP_DATA_DIR / "recruitment_profiles" / sha256(owner.encode()).hexdigest() / "boss"
                            status, message, rows = collect_local_boss(
                                playwright, profile, config.keyword, config.city, config.limit, boss_status
                            )
                    else:
                        if browser is None:
                            browser = browsers.enter_context(launch_browser(playwright))
                        status, message, rows = collect_source(browser, source, config.keyword, config.city, config.limit)
                except BrowserError:
                    status, message, rows = "unavailable", "页面加载未完成，请尝试原站搜索。", []
                    if source == "boss" and config.boss_local:
                        status, message = "blocked", "BOSS 窗口已关闭或无法继续加载，可以重新开始。"
                with conn:
                    count = save_rows(conn, owner, source, rows)
                    progress[source] = {"status": status, "message": message, "count": count}
                    save_progress(conn, owner, run_id, progress)
    except Exception:
        logger.exception("Recruitment collection could not finish")
        for source in config.sources:
            if progress[source]["status"] in {"queued", "running", "opening", "waiting_user"}:
                progress[source] = {"status": "unavailable", "message": "浏览器采集未完成，请检查是否安装 Chromium、Chrome 或 Edge。", "count": 0}
    finally:
        with conn:
            if all(item.get("count") for item in progress.values()):
                status = "complete"
            elif any(item.get("count") for item in progress.values()):
                status = "partial"
            else:
                status = "empty" if any(item["status"] == "empty" for item in progress.values()) else "unavailable"
            save_progress(conn, owner, run_id, progress, status)
        conn.close()


def local_desktop_request():
    try:
        host = urlsplit("//" + request.host).hostname
        remote = ip_address(request.remote_addr or "")
        return (remote.is_loopback and host in {"localhost", "127.0.0.1", "::1"}
                and not any(header in request.headers for header in ("Forwarded", "X-Forwarded-For", "X-Forwarded-Host")))
    except ValueError:
        return False


@blueprint.get("/recruitment")
def page():
    if not _current_user():
        return redirect(url_for("site.index"))
    return render_template("recruitment.html", sources=SOURCES, cities=CITIES, boss_local=local_desktop_request(),
                           boss_chrome=use_local_chrome())


@blueprint.post(API + "/runs")
@_login_required
def start():
    try:
        config = CollectRequest.model_validate(request.get_json(silent=True))
    except ValidationError:
        return jsonify(message="请输入关键词，并选择平台和每个平台的采集上限。"), 400
    if (config.city and config.city not in CITIES) or any(source not in SOURCES for source in config.sources):
        return jsonify(message="城市或采集平台不在可用选项中。"), 400
    if config.boss_local and ("boss" not in config.sources or not local_desktop_request()):
        return jsonify(message="请在运行智航生涯的电脑上打开本机地址，并勾选 BOSS 直聘。"), 403
    config.sources = list(dict.fromkeys(config.sources))
    owner = _current_user()["username"]
    progress = {source: {"status": "queued"} for source in config.sources}
    run_id = uuid.uuid4().hex
    now = time.time()
    conn = db._get_conn()
    try:
        with conn:
            conn.execute("UPDATE recruitment_runs SET status='interrupted' WHERE status='running' AND started_at<?", (now - 300,))
            conn.execute("INSERT INTO recruitment_runs VALUES (?, ?, ?, ?, ?, 'running', ?)",
                         (run_id, owner, config.keyword, config.city, now, json.dumps(progress)))
    except sqlite3.IntegrityError:
        return jsonify(message="已有采集任务运行，请稍后重试。"), 409
    try:
        threading.Thread(target=run_collection, args=(owner, run_id, config, progress),
                         daemon=True, name="recruitment-collector").start()
    except RuntimeError:
        with conn:
            save_progress(conn, owner, run_id, progress, "interrupted")
        return jsonify(message="暂时无法启动采集，请重试。"), 503
    return jsonify(id=run_id), 202


@blueprint.get(API + "/runs")
@_login_required
def runs():
    owner = _current_user()["username"]
    with db._get_conn() as conn:
        conn.execute("UPDATE recruitment_runs SET status='interrupted' WHERE owner=? AND status='running' AND started_at<?",
                     (owner, time.time() - 300))
        rows = conn.execute("SELECT id, keyword, city, started_at, status, progress FROM recruitment_runs "
                            "WHERE owner=? ORDER BY started_at DESC LIMIT 8", (owner,)).fetchall()
    return jsonify(items=[{**dict(row), "progress": {
        source: {**item, "search_url": search_url(source, row["keyword"], row["city"])}
        for source, item in json.loads(row["progress"]).items()
    }} for row in rows])


def query_rows(owner, limit, offset=0):
    source = request.args.get("source", "")
    if source and source not in SOURCES:
        return [], 0
    keyword = f"%{request.args.get('q', '').strip()[:120]}%"
    where = "owner=? AND (?='' OR source=?) AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
    args = (owner, source, source, keyword, keyword, keyword)
    conn = db._get_conn()
    total = conn.execute("SELECT count(*) FROM recruitment_listings WHERE " + where, args).fetchone()[0]
    items = conn.execute("SELECT " + ", ".join(FIELDS) + " FROM recruitment_listings WHERE " + where
                         + " ORDER BY updated_at DESC, source, url_key LIMIT ? OFFSET ?", (*args, limit, offset))
    return [clean_listing(dict(item)) for item in items], total


@blueprint.get(API + "/jobs")
@_login_required
def jobs():
    page_number = min(10000, max(1, request.args.get("page", 1, type=int)))
    items, total = query_rows(_current_user()["username"], 20, (page_number - 1) * 20)
    return jsonify(items=items, total=total, page=page_number, page_size=20)


@blueprint.get(API + "/export")
@_login_required
def export():
    rows, total = query_rows(_current_user()["username"], 10000)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                         else value for key, value in row.items()})
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=recruitment.csv", "X-Export-Total": str(total)
    })


@blueprint.post(API + "/import")
@_login_required
def import_csv():
    file = request.files.get("file")
    data = file.stream.read(2_000_001) if file else b""
    if not data or len(data) > 2_000_000:
        return jsonify(message="请选择不超过 2 MB 的 CSV。"), 400
    grouped = {source: [] for source in SOURCES}
    try:
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")), strict=True)
        fields = {CSV_ALIASES.get(field, field) for field in reader.fieldnames or ()}
        if "url" not in fields or not fields.intersection({"title", "description"}):
            return jsonify(message="CSV 表头需要包含链接，以及标题或描述。支持导出文件及 Jobhunter AI 原始列名。"), 400
        for index, row in enumerate(reader):
            if index >= 3000:
                return jsonify(message="每次最多导入 3000 条岗位。"), 400
            record = {CSV_ALIASES.get(key, key): value for key, value in row.items()}
            source = str(record.get("source") or "").strip().lower()
            if not source:
                url = str(record.get("url") or "")
                if url.startswith("https://"):
                    source = next((name for name in SOURCES if listing_url(name, url)), "")
            if source in grouped:
                grouped[source].append(record)
    except (UnicodeDecodeError, csv.Error):
        return jsonify(message="请使用 UTF-8 编码的 CSV。"), 400
    with db._get_conn() as conn:
        count = sum(save_rows(conn, _current_user()["username"], source, rows) for source, rows in grouped.items())
    if not count:
        return jsonify(message="未找到有效结果。请核对平台标识、岗位标题和原站链接。"), 400
    return jsonify(count=count)


@blueprint.post(API + "/import-html")
@_login_required
def import_html():
    from lxml.etree import ParserError
    from playwright.sync_api import Error as BrowserError

    source = request.form.get("source")
    file = request.files.get("file")
    data = file.stream.read(5_000_001) if file else b""
    if source not in SOURCES or not data or len(data) > 5_000_000:
        return jsonify(message="请选择招聘平台和不超过 5 MB 的 HTML 文件。"), 400
    if not html_import_lock.acquire(blocking=False):
        return jsonify(message="正在读取另一份页面，请稍后重试。"), 409
    try:
        rows = read_saved_page(source, data.decode("utf-8-sig"))
    except (ParserError, UnicodeDecodeError):
        return jsonify(message="请选择浏览器保存的有效 UTF-8 HTML 文件。"), 400
    except BrowserError:
        return jsonify(message="暂时无法读取页面，请检查浏览器安装。"), 503
    finally:
        html_import_lock.release()
    with db._get_conn() as conn:
        count = save_rows(conn, _current_user()["username"], source, rows)
    if not count:
        return jsonify(message="页面里没有可以读取的公开岗位卡片。请保存已显示搜索结果的页面，或导入 CSV。"), 400
    return jsonify(count=count)
