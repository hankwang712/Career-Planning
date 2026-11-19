"""Account-scoped collection runs, listing search and CSV exchange."""

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from base64 import b64encode
import csv
from hashlib import sha256
from io import BytesIO, StringIO
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

from . import db, llm_env, recruitment_ai as ai, recruitment_cleaning as cleaning
from . import recruitment_pipeline as pipeline
from .paths import APP_DATA_DIR
from .recruitment_chrome import (
    CHROME_SOURCES, LOGIN_URLS, SESSION_LABELS, SESSION_MESSAGES, check_platform_login, collect_in_chrome,
    read_xiaohongshu_images, read_zhilian_detail, use_local_chrome,
)
from .recruitment_sources import (
    CITIES, CITY_CATALOG, SOURCES, collect_local_boss, collect_source, launch_browser, listing_url,
    read_saved_page, search_url, supports_city, xiaohongshu_note_url,
)
from .user_state import _current_user, _login_required, _public_user


blueprint = Blueprint("recruitment", __name__)
API = "/api/job-market/collection"
pipeline.register_routes(blueprint)
logger = logging.getLogger(__name__)
FIELDS = ("source", "title", "company", "location", "salary", "description", "url", "updated_at", "experience", "education")
CSV_ALIASES = {"platform": "source", "job_title": "title", "company_name": "company", "city": "location",
               "jd_text": "description", "job_link": "url", "post_link": "url", "raw_text": "description",
               "note_title": "title", "crawl_time": "updated_at", "experience_req": "experience",
               "education_req": "education", "work_address": "location"}
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
        CREATE TABLE IF NOT EXISTS recruitment_job_details (
            owner TEXT NOT NULL, source TEXT NOT NULL, url_key TEXT NOT NULL, description TEXT NOT NULL,
            PRIMARY KEY(owner, source, url_key),
            FOREIGN KEY(owner, source, url_key) REFERENCES recruitment_listings(owner, source, url_key) ON DELETE CASCADE
        );
    """)
    cleaning.init_schema(conn)
    ai.init_schema(conn)
    pipeline.init_schema(conn)


class CollectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keyword: str = Field(min_length=1, max_length=80)
    city: str = ""
    profile: cleaning.Profile = cleaning.DEFAULT_PROFILE
    sources: list[str] = Field(min_length=1, max_length=4)
    limit: int = Field(default=20, ge=1, le=30, strict=True)
    boss_local: bool = Field(default=False, strict=True)
    chrome_local: bool = Field(default=False, strict=True)


def clean_listing(fields):
    for key in ("title", "company", "location", "salary", "description", "experience", "education"):
        value = str(fields.get(key) or "").strip()
        if key == "salary" and UNRENDERABLE_TEXT.search(value):
            fields[key] = ""
        elif key == "description":
            lines = [line.strip() for line in value.splitlines() if not UNRENDERABLE_TEXT.search(line)]
            fields[key] = "\n".join(lines).strip()
        else:
            fields[key] = UNRENDERABLE_TEXT.sub("", value)
    return fields


def save_rows(conn, owner, source, rows, *, profile=cleaning.DEFAULT_PROFILE, cleaning_counts=None):
    seen = set()
    records = []
    note_links = []
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
        values = [row[key][:limit] for key, limit in
                  (("company", 250), ("location", 120), ("salary", 120), ("description", 6000),
                   ("experience", 120), ("education", 120))]
        records.append((owner, source, url, title, *values, url, time.time(), profile))
        if source == "xiaohongshu" and (note_url := xiaohongshu_note_url(str(row.get("note_url") or ""))):
            if listing_url(source, note_url) == url:
                note_links.append((owner, source, url, note_url))
    conn.executemany("""
        INSERT INTO recruitment_listings
            (owner, source, url_key, title, company, location, salary, description, experience, education, url, updated_at, profile)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner, source, url_key) DO UPDATE SET
            title=excluded.title, company=excluded.company, location=excluded.location,
            salary=CASE WHEN excluded.salary='' THEN recruitment_listings.salary ELSE excluded.salary END,
            experience=COALESCE(NULLIF(excluded.experience, ''), recruitment_listings.experience),
            education=COALESCE(NULLIF(excluded.education, ''), recruitment_listings.education),
            description=excluded.description, url=excluded.url, updated_at=excluded.updated_at,
            profile=CASE WHEN recruitment_listings.profile='general' THEN excluded.profile ELSE recruitment_listings.profile END
    """, records)
    conn.executemany("""
        INSERT INTO recruitment_note_links VALUES (?, ?, ?, ?)
        ON CONFLICT(owner, source, url_key) DO UPDATE SET note_url=excluded.note_url
        WHERE instr(excluded.note_url, 'xsec_token=') > 0
    """, note_links)
    counts = cleaning.apply_ingested(conn, owner, source, list(seen))
    if counts and cleaning_counts is not None:
        for status, count in counts.items():
            cleaning_counts[status] = cleaning_counts.get(status, 0) + count
    return len(records)


def save_progress(conn, owner, run_id, progress, status="running"):
    conn.execute("UPDATE recruitment_runs SET status=?, progress=? WHERE owner=? AND id=? AND status='running'",
                 (status, json.dumps(progress, ensure_ascii=False), owner, run_id))


def run_chrome_sources(owner, run_id, config, progress):
    lock = threading.Lock()

    def run_source(source):
        conn = db._get_conn()

        def update(status, message):
            with lock, conn:
                progress[source] = {"status": status, "message": message}
                save_progress(conn, owner, run_id, progress)

        status, message, rows = collect_in_chrome(source, config.keyword, config.city, config.limit, update)
        with lock, conn:
            counts = {}
            count = save_rows(conn, owner, source, rows, profile=config.profile, cleaning_counts=counts)
            progress[source] = {"status": status, "message": message, "count": count}
            if counts:
                progress[source]["cleaning"] = counts
            save_progress(conn, owner, run_id, progress)

    queued = [source for source in config.sources if progress[source]["status"] == "queued"]
    with ThreadPoolExecutor(max_workers=len(queued), thread_name_prefix="recruitment-chrome") as pool:
        list(pool.map(run_source, queued))


def run_collection(owner, run_id, config, progress):
    conn = db._get_conn()
    try:
        if config.chrome_local:
            run_chrome_sources(owner, run_id, config, progress)
            return
        from playwright.sync_api import Error as BrowserError, sync_playwright

        with sync_playwright() as playwright, ExitStack() as browsers:
            browser = None

            def browser_status(status, message):
                progress[source] = {"status": status, "message": message}
                with conn:
                    save_progress(conn, owner, run_id, progress)

            for source in config.sources:
                if progress[source]["status"] == "city_unsupported":
                    continue
                progress[source] = {"status": "running"}
                with conn:
                    save_progress(conn, owner, run_id, progress)
                try:
                    if config.boss_local and source == "boss" and use_local_chrome():
                        status, message, rows = collect_in_chrome(
                            source, config.keyword, config.city, config.limit, browser_status
                        )
                    elif source == "zhilian":
                        status, message, rows = "login_required", "智联采集需要启用本机 Chrome 并完成登录检查。", []
                    elif source == "boss" and config.boss_local:
                        profile = APP_DATA_DIR / "recruitment_profiles" / sha256(owner.encode()).hexdigest() / "boss"
                        status, message, rows = collect_local_boss(
                            playwright, profile, config.keyword, config.city, config.limit, browser_status
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
                    counts = {}
                    count = save_rows(conn, owner, source, rows, profile=config.profile, cleaning_counts=counts)
                    progress[source] = {"status": status, "message": message, "count": count}
                    if counts:
                        progress[source]["cleaning"] = counts
                    save_progress(conn, owner, run_id, progress)
    except Exception:
        logger.exception("Recruitment collection could not finish")
        for source in config.sources:
            if progress[source]["status"] in {"queued", "running", "opening", "waiting_user"}:
                progress[source] = {"status": "unavailable", "message": "浏览器采集未完成，请检查是否安装 Chromium、Chrome 或 Edge。", "count": 0}
    finally:
        with conn:
            attempted = [item for item in progress.values() if item["status"] != "city_unsupported"]
            if attempted and all(item.get("count") for item in attempted):
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
    user = _current_user()
    if not user:
        return redirect(url_for("site.index"))
    unsupported = {city: {source: SOURCES[source][0] for source in CHROME_SOURCES if not supports_city(source, city)}
                   for city in CITIES}
    return render_template("recruitment.html", initial_user=_public_user(user),
                           sources=SOURCES, city_catalog=CITY_CATALOG, unsupported_cities=unsupported,
                           boss_local=local_desktop_request(),
                           chrome_available=use_local_chrome(), chrome_sources=CHROME_SOURCES,
                           collection_sources={source: SOURCES[source] for source in CHROME_SOURCES},
                           login_urls=LOGIN_URLS, profiles=cleaning.PROFILES, ai_dimensions=ai.DIMENSIONS)


@blueprint.post(API + "/session/<source>")
@_login_required
def platform_login_status(source):
    if not local_desktop_request() or not use_local_chrome():
        return jsonify(message="请从已启用 Chrome 连接的电脑访问本机采集页。"), 403
    if source not in CHROME_SOURCES:
        return jsonify(message="该平台不支持本机 Chrome 登录检查。"), 404
    state = check_platform_login(source)
    return jsonify(state=state, label=SESSION_LABELS[state], message=SESSION_MESSAGES[state])


@blueprint.post(API + "/runs")
@_login_required
def start():
    try:
        config = CollectRequest.model_validate(request.get_json(silent=True))
    except ValidationError:
        return jsonify(message="请输入关键词，并选择平台和每个平台的采集上限。"), 400
    if (config.city and config.city not in CITIES) or any(source not in CHROME_SOURCES for source in config.sources):
        return jsonify(message="城市或采集平台不在可用选项中。"), 400
    if config.boss_local and ("boss" not in config.sources or not local_desktop_request()):
        return jsonify(message="请在运行智航生涯的电脑上打开本机地址，并勾选 BOSS 直聘。"), 403
    if config.chrome_local and (not local_desktop_request() or not use_local_chrome()):
        return jsonify(message="请从已启用 Chrome 连接的电脑访问本机采集页。"), 403
    config.sources = list(dict.fromkeys(config.sources))
    owner = _current_user()["username"]
    progress = {
        source: {"status": "queued"} if supports_city(source, config.city) else
        {"status": "city_unsupported", "message": f"{SOURCES[source][0]} 暂无「{config.city}」的城市筛选编码，已跳过。"}
        for source in config.sources
    }
    if all(item["status"] == "city_unsupported" for item in progress.values()):
        return jsonify(message="所选平台暂无该城市的采集选项，请更换城市或平台。"), 400
    run_id = uuid.uuid4().hex
    now = time.time()
    conn = db._get_conn()
    try:
        with conn:
            conn.execute("UPDATE recruitment_runs SET status='interrupted' WHERE status='running' AND started_at<?", (now - 300,))
            conn.execute("""
                INSERT INTO recruitment_runs (id, owner, keyword, city, started_at, status, progress, profile)
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
            """, (run_id, owner, config.keyword, config.city, now, json.dumps(progress), config.profile))
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
        rows = conn.execute("SELECT id, keyword, city, started_at, status, progress, profile FROM recruitment_runs "
                            "WHERE owner=? ORDER BY started_at DESC LIMIT 8", (owner,)).fetchall()
    return jsonify(items=[{**dict(row), "progress": {
        source: {**item, "search_url": search_url(source, row["keyword"], row["city"]), "login_url": LOGIN_URLS.get(source)}
        for source, item in json.loads(row["progress"]).items()
    }} for row in rows])


@blueprint.get(API + "/cleaning")
@_login_required
def cleaning_overview():
    profile = request.args.get("profile", cleaning.DEFAULT_PROFILE)
    if profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    return jsonify(rules=cleaning.load_rules(conn, owner, profile).model_dump(), examples=cleaning.SCOUT_EXAMPLES,
                   counts=cleaning.stored_counts(conn, owner, profile))


@blueprint.post(API + "/cleaning/<action>")
@_login_required
def cleaning_update(action):
    if action not in {"save", "preview", "apply"}:
        return jsonify(message="清洗操作不存在。"), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), dict):
        return jsonify(message="请输入有效的清洗规则。"), 400
    profile = payload.get("profile", cleaning.DEFAULT_PROFILE)
    if not isinstance(profile, str) or profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    try:
        rules = cleaning.CleaningRules.model_validate(payload["rules"])
    except ValidationError as error:
        reason = error.errors()[0]
        message = reason["msg"].removeprefix("Value error, ") if not reason["loc"] else "请检查薪资、经验上限或规则条目的格式与数量。"
        return jsonify(message=message), 400
    if profile != "internship" and (rules.min_daily_salary is not None or rules.max_daily_salary is not None):
        return jsonify(message="日薪规则适用于实习方向。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    if action == "preview":
        with conn:
            conn.execute("BEGIN")
            result, _ = cleaning.preview(conn, owner, profile, rules)
        return jsonify(result)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if action == "apply":
            result, rows = cleaning.preview(conn, owner, profile, rules)
            if result["token"] != payload.get("token"):
                return jsonify(message="岗位或规则已变化，请重新预览后应用。"), 409
            cleaning.write_results(conn, owner, rows)
        previous = cleaning.load_rules(conn, owner, profile)
        if previous.semantic_config() != rules.semantic_config():
            ai.invalidate(conn, owner, profile, "semantic")
        cleaning.save_rules(conn, owner, profile, rules)
        counts = cleaning.stored_counts(conn, owner, profile)
    return jsonify(rules=rules.model_dump(), counts=counts)


@blueprint.post(API + "/cleaning/describe")
@_login_required
def cleaning_describe():
    try:
        rule = cleaning.ScoutRule.model_validate(request.get_json(silent=True))
    except ValidationError:
        return jsonify(message="请先填写规则关键词。"), 400
    runtime = llm_env.recruitment_cleaner_runtime()
    if not all(runtime):
        return jsonify(message="请先在系统配置中填写招聘清洗模型。"), 400
    if not ai.SLOTS.acquire(blocking=False):
        return jsonify(message="AI 任务繁忙，请稍后重试。"), 429
    try:
        return jsonify(desc=ai.describe_rule(runtime, rule))
    except Exception as error:
        logger.warning("Cleaning rule description failed (%s)", type(error).__name__)
        return jsonify(message="未能生成判定标准，请检查模型配置后重试。"), 502
    finally:
        ai.SLOTS.release()


def listing_identity(payload):
    if not isinstance(payload, dict):
        return None, ""
    source, value = payload.get("source"), payload.get("url")
    if not isinstance(source, str) or source not in SOURCES or not isinstance(value, str) or len(value) > 4096:
        return None, ""
    return source, listing_url(source, value)


def semantic_reason(payload):
    if not payload:
        return ""
    result = json.loads(payload)
    return " · ".join(value for value in (result.get("rule"), result.get("reason"), result.get("evidence")) if value)


@blueprint.post(API + "/cleaning/release")
@_login_required
def cleaning_release():
    payload = request.get_json(silent=True)
    source, url = listing_identity(payload)
    if not url:
        return jsonify(message="岗位记录无效。"), 400
    profile = payload.get("profile", cleaning.DEFAULT_PROFILE)
    if not isinstance(profile, str) or profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        decision = conn.execute(f"""
            SELECT {cleaning.EFFECTIVE_STATUS} AS status, a.verdict AS semantic,
                   a.payload AS semantic_payload, r.reason
            FROM recruitment_cleaning_results r
            JOIN recruitment_listings j USING(owner, source, url_key)
            {cleaning.SEMANTIC_JOIN}
            WHERE j.owner=? AND j.source=? AND j.url_key=? AND j.profile=?
        """, (owner, source, url, profile)).fetchone()
        if not decision:
            return jsonify(message="该岗位当前没有可放行的清洗结果。"), 404
        if decision["status"] not in {"rejected", "released"}:
            return jsonify(message="该岗位当前无需放行。"), 409
        reason = decision["reason"] or semantic_reason(decision["semantic_payload"])
        conn.execute("""
            UPDATE recruitment_cleaning_results SET status='released', reason=?
            WHERE owner=? AND source=? AND url_key=?
        """, (reason, owner, source, url))
        pipeline.revive_released(conn, owner, source, url)
        counts = cleaning.stored_counts(conn, owner, profile)
    return jsonify(counts=counts)


@blueprint.post(API + "/jobs/profile")
@_login_required
def move_profile():
    payload = request.get_json(silent=True)
    source, url = listing_identity(payload)
    if not url:
        return jsonify(message="岗位记录无效。"), 400
    profile = payload.get("profile")
    if not isinstance(profile, str) or profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    with conn:
        result = conn.execute("""
            UPDATE recruitment_listings SET profile=? WHERE owner=? AND source=? AND url_key=?
        """, (profile, owner, source, url))
        if not result.rowcount:
            return jsonify(message="岗位记录不存在。"), 404
        cleaning.apply_ingested(conn, owner, source, [url])
    return jsonify(profile=profile)


def query_rows(owner, limit, offset=0, *, compact=False, include_counts=False):
    source = request.args.get("source", "")
    if source and source not in SOURCES:
        return [], 0, {}
    keyword = f"%{request.args.get('q', '').strip()[:120]}%"
    where = "j.owner=? AND (?='' OR j.source=?) AND (j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)"
    args = (owner, source, source, keyword, keyword, keyword)
    profile = request.args.get("profile", "")
    if profile:
        where += " AND j.profile=?"
        args += (profile,)
    effective = cleaning.EFFECTIVE_STATUS
    scored = f"(({effective}) IN ('passed', 'released') AND m.score IS NOT NULL)"
    conn = db._get_conn()
    joined = f""" FROM recruitment_listings j LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
        {cleaning.SEMANTIC_JOIN}
        LEFT JOIN recruitment_ai_results m ON m.owner=j.owner AND m.source=j.source AND m.url_key=j.url_key AND m.kind='match'
        WHERE """
    counts = {}
    if include_counts:
        counts = dict.fromkeys(("all", "unreviewed", "passed", "review", "rejected", "scored"), 0)
        for item in conn.execute(
            f"SELECT COALESCE({effective}, 'unreviewed') AS outcome, count(*) AS count, "
            f"sum(CASE WHEN {scored} THEN 1 ELSE 0 END) AS scored_count {joined}{where} GROUP BY 1", args,
        ):
            key = "passed" if item["outcome"] == "released" else item["outcome"]
            counts[key] += item["count"]
            counts["all"] += item["count"]
            counts["scored"] += item["scored_count"]
    status = request.args.get("clean_status", "")
    if status == "unreviewed":
        where += " AND r.status IS NULL"
    elif status == "passed":
        where += f" AND ({effective}) IN ('passed', 'released')"
    elif status in ("rejected", "review"):
        where += f" AND ({effective})=?"
        args += (status,)
    elif status == "scored":
        where += f" AND {scored}"
    total = counts.get(status, counts.get("all")) if include_counts else conn.execute(
        "SELECT count(*)" + joined + where, args,
    ).fetchone()[0]
    columns = ", ".join("j." + key for key in FIELDS if key != "description")
    details = "" if compact else """, COALESCE(
                (SELECT d.description FROM recruitment_job_details d
                 WHERE d.owner=j.owner AND d.source=j.source AND d.url_key=j.url_key),
                j.description) AS description, COALESCE(r.reason, '') AS cleaning_reason, a.payload AS semantic_payload"""
    order = "m.score DESC, " if request.args.get("sort") == "match" else ""
    items = conn.execute(
        f"""SELECT {columns}, COALESCE({effective}, 'unreviewed') AS cleaning_status, j.profile,
                m.score AS ai_score, m.verdict AS ai_match_status {details}
            {joined}{where}
            ORDER BY {order}j.updated_at DESC, j.source, j.url_key LIMIT ? OFFSET ?""",
        (*args, limit, offset),
    )
    rows = []
    for item in items:
        row = dict(item)
        if not compact:
            semantic_payload = row.pop("semantic_payload")
            if not row["cleaning_reason"] and row["cleaning_status"] in {"rejected", "review"}:
                row["cleaning_reason"] = semantic_reason(semantic_payload)
        clean_listing(row)
        if compact:
            row.pop("description", None)
        rows.append(row)
    return rows, total, counts


@blueprint.get(API + "/jobs")
@_login_required
def jobs():
    page_number = min(10000, max(1, request.args.get("page", 1, type=int)))
    owner = _current_user()["username"]
    items, total, counts = query_rows(owner, 20, (page_number - 1) * 20,
                                     compact=request.args.get("compact") == "1", include_counts=True)
    count_profile = request.args.get("count_profile", cleaning.DEFAULT_PROFILE)
    return jsonify(items=items, total=total, page=page_number, page_size=20, view_counts=counts,
                   cleaning_counts=cleaning.stored_counts(db._get_conn(), owner, count_profile))


@blueprint.post(API + "/jobs/detail")
@_login_required
def listing_detail():
    source, url = listing_identity(request.get_json(silent=True))
    if not url:
        return jsonify(message="岗位记录无效。"), 400
    row = ai_listing(db._get_conn(), (_current_user()["username"], source, url))
    if not row:
        return jsonify(message="岗位记录不存在。"), 404
    reason = row["cleaning_reason"]
    if not reason and row["cleaning_status"] in {"rejected", "review"}:
        reason = semantic_reason(row["semantic_payload"])
    return jsonify(description=clean_listing({"description": row["detail"]})["description"],
                   cleaning_reason=reason or "", cleaning_status=row["cleaning_status"] or "unreviewed")


@blueprint.route(API + "/ai/settings", methods=["GET", "POST"])
@_login_required
def recruitment_ai_settings():
    payload = request.get_json(silent=True) if request.method == "POST" else {}
    profile = (payload.get("profile") if isinstance(payload, dict) else None) if request.method == "POST" else request.args.get("profile")
    if not isinstance(profile, str) or profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    settings = ai.load_settings(conn, owner, profile)
    if request.method == "POST":
        try:
            updated = ai.MatchSettings.model_validate(payload.get("settings"))
        except ValidationError:
            return jsonify(message="请检查初评配置。"), 400
        if (not updated.weights.keys() <= ai.DIMENSIONS.keys() or any(value < 0 or value > 5 for value in updated.weights.values())
                or sum(value > 0 for value in updated.weights.values()) < 3):
            return jsonify(message="权重需为 0 到 5，至少启用三个维度。"), 400
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if ai.load_settings(conn, owner, profile) != updated:
                conn.execute("""
                    INSERT INTO recruitment_ai_settings VALUES (?, ?, ?)
                    ON CONFLICT(owner, profile) DO UPDATE SET settings=excluded.settings
                """, (owner, profile, updated.model_dump_json()))
                ai.invalidate(conn, owner, profile, "match")
        settings = updated
    response = jsonify(settings=settings.model_dump(), resume_available=bool(ai.resume_text(owner, settings)),
                       configured=llm_env.chat_configured())
    response.headers["Cache-Control"] = "no-store"
    return response


@blueprint.get(API + "/ai/candidates/<kind>")
@_login_required
def recruitment_ai_candidates(kind):
    profile = request.args.get("profile")
    if kind not in ("semantic", "match") or profile not in cleaning.PROFILES:
        return jsonify(message="初评任务参数无效。"), 400
    eligible = "r.status='passed'" if kind == "semantic" else f"({cleaning.EFFECTIVE_STATUS}) IN ('passed','released')"
    conn = db._get_conn()
    keyword = f"%{request.args.get('q', '').strip()[:100]}%"
    rows = conn.execute(f"""
        SELECT j.source, j.url, j.title, j.company, m.verdict, m.score
        FROM recruitment_listings j
        JOIN recruitment_cleaning_results r USING(owner, source, url_key)
        {cleaning.SEMANTIC_JOIN}
        LEFT JOIN recruitment_ai_results m ON m.owner=j.owner AND m.source=j.source AND m.url_key=j.url_key AND m.kind=?
        WHERE j.owner=? AND j.profile=? AND {eligible}
          AND (j.title LIKE ? OR j.company LIKE ?)
        ORDER BY m.verdict IS NULL DESC, j.updated_at DESC, j.source, j.url_key LIMIT 50
    """, (kind, _current_user()["username"], profile, keyword, keyword))
    return jsonify(items=[dict(row) for row in rows])


def ai_listing(conn, identity):
    return conn.execute(f"""
        SELECT j.profile, j.title, j.company, j.location, j.salary, j.description, j.experience, j.education,
               COALESCE(d.description, j.description) AS detail,
               n.note_url, r.status AS hard_status, {cleaning.EFFECTIVE_STATUS} AS cleaning_status,
               r.reason AS cleaning_reason, a.payload AS semantic_payload,
               v.payload AS vision_payload
        FROM recruitment_listings j
        LEFT JOIN recruitment_cleaning_results r USING(owner, source, url_key)
        {cleaning.SEMANTIC_JOIN}
        LEFT JOIN recruitment_job_details d ON d.owner=j.owner AND d.source=j.source AND d.url_key=j.url_key
        LEFT JOIN recruitment_note_links n ON n.owner=j.owner AND n.source=j.source AND n.url_key=j.url_key
        LEFT JOIN recruitment_ai_results v ON v.owner=j.owner AND v.source=j.source AND v.url_key=j.url_key AND v.kind='vision'
        WHERE j.owner=? AND j.source=? AND j.url_key=?
    """, identity).fetchone()


def ai_material(row, kind):
    job = {key: row[key] for key in ("title", "company", "location", "salary", "description")}
    job["description"] = row["detail"]
    if kind == "semantic":
        job.update(experience=row["experience"], education=row["education"])
    if kind != "vision" and row["vision_payload"]:
        extracted = json.loads(row["vision_payload"])["jobs"]
        if len(extracted) == 1:
            job.update({key: value for key, value in extracted[0].items() if value})
        elif len(extracted) > 1:
            job["description"] = ""
    return job


def image_uploads(files):
    from PIL import Image

    if len(files) > 4:
        raise ValueError("请选择最多 4 张图片。")
    images = []
    for file in files:
        data = file.stream.read(2_000_001)
        if not data or len(data) > 2_000_000:
            raise ValueError("每张图片须小于 2 MB。")
        try:
            with Image.open(BytesIO(data)) as image:
                mime = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}.get(image.format)
                if not mime or image.width * image.height > 24_000_000:
                    raise ValueError("请选择正常尺寸的 PNG、JPEG 或 WebP 图片。")
                image.verify()
        except (OSError, Image.DecompressionBombError) as error:
            raise ValueError("图片无法读取。") from error
        images.append(f"data:image/{mime};base64,{b64encode(data).decode('ascii')}")
    return images


@blueprint.post(API + "/ai/details")
@_login_required
def recruitment_ai_details():
    source, url = listing_identity(request.get_json(silent=True))
    if not url:
        return jsonify(message="岗位记录无效。"), 400
    identity = (_current_user()["username"], source, url)
    conn = db._get_conn()
    if not ai_listing(conn, identity):
        return jsonify(message="岗位记录不存在。"), 404
    rows = conn.execute("SELECT kind, payload FROM recruitment_ai_results WHERE owner=? AND source=? AND url_key=?", identity)
    response = jsonify(results={row["kind"]: json.loads(row["payload"]) for row in rows})
    response.headers["Cache-Control"] = "no-store"
    return response


def ai_context(conn, identity, row, kind):
    owner = identity[0]
    profile = row["profile"]
    if kind == "semantic":
        rules = cleaning.load_rules(conn, owner, profile)
        return rules, "", ai.fingerprint(rules.semantic_config())
    if kind == "match":
        settings = ai.load_settings(conn, owner, profile)
        resume = ai.resume_text(owner, settings)
        return settings, resume, ai.fingerprint([settings.model_dump(), resume])
    return None, "", ""


@blueprint.post(API + "/ai/run/<kind>")
@_login_required
def recruitment_ai_run(kind):
    if kind not in ai.KINDS:
        return jsonify(message="任务类型无效。"), 404
    payload = request.form.to_dict() if request.mimetype == "multipart/form-data" else request.get_json(silent=True)
    source, url = listing_identity(payload)
    if not url or (kind == "vision" and source != "xiaohongshu"):
        return jsonify(message="岗位记录或任务类型无效。"), 400
    identity = (_current_user()["username"], source, url)
    conn = db._get_conn()
    row = ai_listing(conn, identity)
    if not row:
        return jsonify(message="岗位记录不存在。"), 404
    if ((kind == "semantic" and row["hard_status"] != "passed")
            or (kind == "match" and row["cleaning_status"] not in {"passed", "released"})):
        return jsonify(message="请先通过规则清洗。"), 409
    if kind != "vision" and payload.get("profile") != row["profile"]:
        return jsonify(message="岗位求职方向已变更，请刷新。"), 409
    settings, resume, context = ai_context(conn, identity, row, kind)
    if kind == "semantic" and not any(settings.semantic_config()):
        return jsonify(message="请先保存 AI 初筛规则。"), 400
    if kind == "match" and not resume:
        return jsonify(message="请先配置本方向的基准简历，或上传并解析简历。"), 400
    runtime = llm_env.chat_runtime() if kind == "match" else llm_env.recruitment_cleaner_runtime()
    if not all(runtime):
        return jsonify(message="模型尚未配置，请查看系统配置。"), 400
    try:
        images = image_uploads(request.files.getlist("images")) if kind == "vision" else []
    except ValueError as error:
        return jsonify(message=str(error)), 400
    if kind == "vision" and not images and (not local_desktop_request() or not use_local_chrome()):
        return jsonify(message="可上传笔记配图，或在启用本机 Chrome 的页面读取原帖。"), 400
    if not ai.SLOTS.acquire(blocking=False):
        return jsonify(message="AI 任务繁忙，请稍后重试。"), 429
    try:
        job = ai_material(row, kind)
        if kind == "vision":
            note = xiaohongshu_note_url(row["note_url"] or url)
            if not images and note:
                images = read_xiaohongshu_images(note)
            if not images:
                return jsonify(message="未读取到配图，请在 Chrome 登录后重试，或上传笔记截图。"), 422
            result = ai.extract_note(runtime, job, images)
        elif kind == "semantic":
            result = ai.screen(runtime, job, settings)
        else:
            result = ai.match(runtime, job, resume, settings)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            current = ai_listing(conn, identity)
            if not current or tuple(current) != tuple(row) or ai_context(conn, identity, current, kind)[2] != context:
                return jsonify(message="岗位资料或配置发生变化，请重新运行。"), 409
            if kind == "vision":
                conn.execute("""
                    DELETE FROM recruitment_ai_results WHERE owner=? AND source=? AND url_key=? AND kind IN ('semantic','match')
                """, identity)
            elif kind == "semantic" and result["verdict"] != "passed":
                conn.execute("""
                    DELETE FROM recruitment_ai_results WHERE owner=? AND source=? AND url_key=? AND kind='match'
                """, identity)
            ai.write_result(conn, identity, kind, result)
        return jsonify(result=result)
    except Exception as error:
        logger.warning("Recruitment %s model operation failed (%s)", kind, type(error).__name__)
        if kind == "vision":
            return jsonify(message="图片提取失败，请确认当前清洗模型支持图文输入，再检查配置后重试。"), 502
        return jsonify(message="模型调用或结果校验失败，请检查配置后重试。"), 502
    finally:
        ai.SLOTS.release()


@blueprint.post(API + "/jobs/zhilian/detail")
@_login_required
def zhilian_job_detail():
    payload = request.get_json(silent=True)
    value = payload.get("url") if isinstance(payload, dict) else None
    url = listing_url("zhilian", value) if isinstance(value, str) and len(value) <= 2048 else ""
    if not url or urlsplit(url).hostname != "www.zhaopin.com" or not urlsplit(url).path.startswith("/jobdetail/"):
        return jsonify(message="职位链接无效。"), 400
    owner = _current_user()["username"]
    conn = db._get_conn()
    args = (owner, "zhilian", url)
    if not conn.execute("SELECT 1 FROM recruitment_listings WHERE owner=? AND source=? AND url_key=?", args).fetchone():
        return jsonify(message="岗位记录不存在。"), 404
    saved = conn.execute("SELECT description FROM recruitment_job_details WHERE owner=? AND source=? AND url_key=?", args).fetchone()
    if saved:
        return jsonify(description=saved["description"])
    if not local_desktop_request() or not use_local_chrome():
        return jsonify(message="首次读取职位详情，请从已启用 Chrome 连接的本机采集页打开。"), 403
    state, detail = read_zhilian_detail(url)
    text = clean_listing({"description": detail})["description"]
    if not text:
        return jsonify(message=SESSION_MESSAGES.get(state, "未读取到职位描述，可能已下架。可到原帖核对。")), 422
    with conn:
        inserted = conn.execute("INSERT OR IGNORE INTO recruitment_job_details VALUES (?, ?, ?, ?)", (*args, text)).rowcount
        if inserted:
            row = conn.execute("SELECT profile FROM recruitment_listings WHERE owner=? AND source=? AND url_key=?", args).fetchone()
            rules = cleaning.load_rules(conn, owner, row["profile"])
            if rules.experience_years_max is not None or rules.require_education or rules.exclude_education:
                conn.execute("""
                    DELETE FROM recruitment_cleaning_results
                    WHERE owner=? AND source=? AND url_key=? AND status <> 'released'
                """, args)
                cleaning.apply_ingested(conn, owner, "zhilian", [url])
    return jsonify(description=text)


@blueprint.get(API + "/export")
@_login_required
def export():
    rows, total, _ = query_rows(_current_user()["username"], 10000)
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "'" + row[key] if isinstance(row[key], str) and row[key].lstrip().startswith(("=", "+", "-", "@"))
                         else row[key] for key in FIELDS})
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=recruitment.csv", "X-Export-Total": str(total)
    })


@blueprint.post(API + "/import")
@_login_required
def import_csv():
    profile = request.form.get("profile", cleaning.DEFAULT_PROFILE)
    if profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
    file = request.files.get("file")
    data = file.stream.read(2_000_001) if file else b""
    if not data or len(data) > 2_000_000:
        return jsonify(message="请选择不超过 2 MB 的 CSV。"), 400
    grouped = {source: [] for source in SOURCES}
    try:
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")), strict=True)
        fields = {CSV_ALIASES.get(field, field) for field in reader.fieldnames or ()}
        if "url" not in fields or not fields.intersection({"title", "description"}):
            return jsonify(message="CSV 表头需要包含链接，以及标题或描述。兼容 url、job_link、title、job_title、description 和 jd_text。"), 400
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
    counts = {}
    with db._get_conn() as conn:
        count = sum(save_rows(conn, _current_user()["username"], source, rows, profile=profile, cleaning_counts=counts)
                    for source, rows in grouped.items())
    if not count:
        return jsonify(message="未找到有效结果。请核对平台标识、岗位标题和原站链接。"), 400
    return jsonify(count=count, cleaning=counts)


@blueprint.post(API + "/import-html")
@_login_required
def import_html():
    from lxml.etree import ParserError
    from playwright.sync_api import Error as BrowserError

    profile = request.form.get("profile", cleaning.DEFAULT_PROFILE)
    if profile not in cleaning.PROFILES:
        return jsonify(message="求职方向无效。"), 400
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
    counts = {}
    with db._get_conn() as conn:
        count = save_rows(conn, _current_user()["username"], source, rows, profile=profile, cleaning_counts=counts)
    if not count:
        return jsonify(message="页面里没有可以读取的公开岗位卡片。请保存已显示搜索结果的页面，或导入 CSV。"), 400
    return jsonify(count=count, cleaning=counts)
