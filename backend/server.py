#!/usr/bin/env python3
import sys

# Windows 控制台默认 GBK，强制 stdout/stderr 使用 UTF-8，避免中文日志乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import gzip
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
import difflib
import urllib.parse
import urllib.request
import urllib.error
import uuid
import webbrowser
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, url_for
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename
from services.news import get_career_news_payload
from services.news.api import create_blueprint as create_news_blueprint
from services.pages import create_blueprint as create_pages_blueprint
from services.report import (
    CAREER_REPORT_STAGE_DEFS,
    build_stage_progress,
    empty_report_job,
    empty_report_state,
    generate_career_report_bundle,
)
from services.report.workflow import (
    ReportNeedsInput, read_report_workflow, validate_report_request, validate_report_continuation,
)
from services.report.review import apply_availability
from services.report.context import apply_report_memory, explicit_report_cities
from services import personality
from services.report.legacy_report import (
    _build_dashboard_summary,
    _build_role_cards,
    _build_role_rankings,
    _normalize_match_output,
    _resolve_effective_match_output,
    _resolve_focus_role_name,
)
from services.report.exporters import (
    export_markdown_to_docx_bytes,
    export_markdown_to_pdf_bytes,
    normalize_br_tags_in_markdown,
    render_markdown_export_html,
    render_report_html,
    render_report_markdown,
)
from services.report.enhancements import (
    CAREER_FEEDBACK_VERSION,
    PORTRAIT_PROMPT_PIPELINE_VERSION,
    normalize_feedback_memory,
)
from services.resume import (
    HR_JUDGE_PROMPT,
    RESUME_REVIEW_PROMPT,
    STRUCTURED_RESUME_PROMPT,
    STRUCTURED_RESUME_SCHEMA,
    build_fallback_resume_highlight_deck,
    build_matcher_state,
    build_job_payload_from_text,
    build_resume_text_payload,
)
from services.resume.diagnosis_ui import (
    DIAGNOSIS_UI_EXTRACT_SYSTEM,
    build_diagnosis_ui_extract_prompt,
    diagnosis_ui_non_empty,
    normalize_diagnosis_ui,
)
from services import db as _app_db
from services import llm_env
from services.cors import cors_headers, normalize_origins
from services.job_registry import JobRegistry
from services import auth as _auth
from services.datasets import create_blueprint as create_datasets_blueprint
from services.career import create_blueprint as create_career_blueprint, snapshot as career_snapshot, sync_sources as sync_career_sources
from services.job_market.api import create_blueprint as create_job_market_blueprint
from services.community import create_blueprint as create_community_blueprint
from services.portrait import (
    create_blueprint as create_portrait_blueprint,
    normalize_profile_portrait_context,
    public_profile_portrait_state,
)
from services.llm_calls import call_markdown_chat, call_structured_chat
from services.interview import create_blueprint as create_interview_blueprint
from services.job_data import BOSS_INFO_DIR, create_blueprint as create_job_data_blueprint
from services.job_market.collector import Collector as JobMarketCollector
from services.chat import create_blueprint as create_chat_blueprint
from services.chat.api import create_app as create_chat_app
from services.chat.profile import build_background as build_chat_background
from services.paths import (
    APP_DATA_DIR,
    PUBLIC_DATA_DIR,
    STATIC_DIR,
    TEMPLATE_DIR,
)

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")

# 路径配置
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")
RESUME_UPLOAD_DIR = os.path.join(APP_DATA_DIR, "user_uploads")
CAREER_REPORT_DIR = os.path.join(APP_DATA_DIR, "career_reports")
ASSESSMENT_DATA_FILE = os.path.join(PUBLIC_DATA_DIR, "assessment-data.json")
APP_DATA_LOCK = threading.Lock()
ASSESSMENT_DATA_LOCK = threading.Lock()
ASSESSMENT_DATA_CACHE = {"signature": None, "payload": {}}
RESUME_ANALYSIS_LOCK = threading.Lock()
RESUME_ANALYSIS_JOBS = JobRegistry("resume")
CAREER_REPORT_LOCK = threading.Lock()
CAREER_REPORT_JOBS = JobRegistry("career_report")
RESUME_MAX_FILE_SIZE = 12 * 1024 * 1024
RESUME_MAX_PAGES = 20
RESUME_OCR_TIMEOUT_SECONDS = 35
RESUME_MAX_TEXT_CHARS = 24000


class CareerReportCanceled(RuntimeError):
    """Raised inside a background report job when the user cancels it."""


try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    import pymupdf as fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency
    pdfplumber = None

try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageFilter = None
    ImageOps = None

try:
    import pytesseract
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.endpoint("static")
def static_asset(filename):
    normalized = os.path.normpath(filename).replace("\\", "/")
    if normalized.lower().startswith("img/report/"):
        user = _current_user()
        if not user:
            return jsonify({"message": "文件不存在"}), 404
        name = os.path.basename(normalized)
        report_ids = [str(item.get("report_id") or "") for item in _list_career_report_version_summaries(user["username"])]
        prefixes = ["".join(ch for ch in report_id if ch.isalnum() or ch in "-_")[:24] + "_"
                    for report_id in report_ids if report_id]
        if not any(name.startswith(prefix) for prefix in prefixes):
            return jsonify({"message": "文件不存在"}), 404
    if os.path.isfile(os.path.join(PUBLIC_DATA_DIR, filename)):
        return send_from_directory(PUBLIC_DATA_DIR, filename, conditional=True)
    return app.send_static_file(filename)


class _QuietWerkzeugPollPathsFilter(logging.Filter):
    """屏蔽高频轮询接口的成功 access 行；4xx/5xx 仍会打印，便于排查问题。"""

    _SKIP_SUBSTRINGS = (
        "/api/career-report/generate/status",
        "/api/resume/analyze/status",
    )
    _WERKZEUG_STATUS_RE = re.compile(r'HTTP/1\.[01]"\s+(\d{3})\b')

    def filter(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for sub in self._SKIP_SUBSTRINGS:
            if sub not in msg:
                continue
            m = self._WERKZEUG_STATUS_RE.search(msg)
            if m:
                code = int(m.group(1))
                if 200 <= code < 400:
                    return False
            return True
        return True


for _lg_name in ("werkzeug",):
    logging.getLogger(_lg_name).addFilter(_QuietWerkzeugPollPathsFilter())

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
FRONTEND_ORIGIN = str(os.environ.get("FRONTEND_ORIGIN") or "").strip()
VITE_DEV_SERVER_URL = str(os.environ.get("VITE_DEV_SERVER_URL") or "").strip().rstrip("/")
VITE_MANIFEST_FILE = os.path.join(STATIC_DIR, "dist", ".vite", "manifest.json")
VITE_MANIFEST_CACHE = {"mtime": None, "payload": None}


@app.before_request
def _handle_api_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return ("", 204)
    return None


def _checked_report_identifier(value, *, allow_empty=False):
    if value is None or value == "":
        if allow_empty:
            return ""
        raise ValueError("缺少报告或快照编号")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("报告或快照编号格式不正确")
    return value


@app.before_request
def _validate_private_report_identifiers():
    if not request.path.startswith("/api/career-report/") or not _current_user():
        return None
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    try:
        for key in ("report_id", "snapshot_id", "continue_report_id"):
            for value in [request.args.get(key), body.get(key)]:
                _checked_report_identifier(value, allow_empty=True)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    return None


def _load_vite_manifest():
    if VITE_DEV_SERVER_URL:
        return {}
    try:
        mtime = os.path.getmtime(VITE_MANIFEST_FILE)
    except OSError:
        return {}
    if VITE_MANIFEST_CACHE["mtime"] == mtime and isinstance(VITE_MANIFEST_CACHE["payload"], dict):
        return VITE_MANIFEST_CACHE["payload"]
    with open(VITE_MANIFEST_FILE, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    VITE_MANIFEST_CACHE["mtime"] = mtime
    VITE_MANIFEST_CACHE["payload"] = payload
    return payload


@app.context_processor
def inject_vite_asset_tags():
    def vite_asset_tags(entry_name):
        safe_entry = str(entry_name or "").strip()
        if not safe_entry:
            return Markup("")
        if VITE_DEV_SERVER_URL:
            client = f'{VITE_DEV_SERVER_URL}/@vite/client'
            entry = f'{VITE_DEV_SERVER_URL}/{safe_entry}'
            return Markup(
                "\n".join(
                    [
                        f'<script type="module" src="{escape(client)}"></script>',
                        f'<script type="module" src="{escape(entry)}"></script>',
                    ]
                )
            )

        manifest = _load_vite_manifest()
        chunk = manifest.get(safe_entry)
        if not chunk:
            raise RuntimeError(f"Missing Vite manifest entry: {safe_entry}")

        tags = []
        for css_file in chunk.get("css", []):
            href = url_for("static", filename=f"dist/{css_file}")
            tags.append(f'<link rel="stylesheet" href="{escape(href)}">')
        script_src = url_for("static", filename=f"dist/{chunk['file']}")
        tags.append(f'<script type="module" src="{escape(script_src)}"></script>')
        return Markup("\n".join(tags))

    return {"vite_asset_tags": vite_asset_tags}


@app.after_request
def _inject_api_cors_headers(response):
    if not request.path.startswith("/api/"):
        return response
    allowed = normalize_origins([request.host_url, FRONTEND_ORIGIN, VITE_DEV_SERVER_URL])
    headers = cors_headers(request.headers.get("Origin"), allowed)
    if not headers:
        return response
    response.headers.update(headers)
    response.vary.add("Origin")
    return response


# 静态资源缓存 & gzip 压缩
_STATIC_EXTS_LONG = {".js", ".css", ".json", ".gif", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2"}
_GZIP_MIME = {"text/html", "text/css", "application/javascript", "application/json", "image/svg+xml", "text/javascript"}
_GZIP_MIN_SIZE = 1400  # bytes


@app.after_request
def _static_headers_and_gzip(response):
    path = request.path

    if response.mimetype == "text/html":
        response.headers.setdefault("Cache-Control", "no-cache")

    # 带内容指纹的构建产物长期缓存，原始脚本和样式使用条件请求更新。
    if os.path.normpath(path).replace("\\", "/").lower().startswith("/static/img/report/"):
        response.headers["Cache-Control"] = "no-store"
        response.vary.add("Cookie")
    elif path.startswith("/static/"):
        ext = os.path.splitext(path)[1].lower()
        if ext in _STATIC_EXTS_LONG:
            if path.startswith("/static/dist/assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif ext in {".js", ".css", ".json"}:
                response.headers["Cache-Control"] = "no-cache"
            else:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    # ── gzip 压缩 ──────────────────────────────────────
    accept_enc = request.headers.get("Accept-Encoding", "")
    if (
        "gzip" in accept_enc
        and response.status_code == 200
        and not response.direct_passthrough
        and (response.content_length is None or (response.content_length or 0) > _GZIP_MIN_SIZE)
    ):
        mime = (response.content_type or "").split(";")[0].strip()
        if mime in _GZIP_MIME:
            data = response.get_data()
            if len(data) > _GZIP_MIN_SIZE:
                buf = io.BytesIO()
                with gzip.GzipFile(mode="wb", fileobj=buf, compresslevel=6) as gz:
                    gz.write(data)
                compressed = buf.getvalue()
                response.set_data(compressed)
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = len(compressed)
                response.headers.add("Vary", "Accept-Encoding")

    return response




VALID_USER_STATE_SCOPES = {
    "career_interview",
    "assessment_hub",
    "deep_tests",
    "resume_profile",
    "career_report",
    "career_plans",
    "profile_portrait",
    "account_avatar",
    "profile_snapshot",
    "career_matching",
    "news_context",
}
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)



# 模型接口只从 .env 读取（AI_CHAT_BASE_URL / AI_CHAT_API_KEY / AI_CHAT_MODEL），数据库不保存密钥，
# 用户也不能选择或配置模型；下面这些函数保留旧名字，只是为了让原有调用点不用改。
def _get_active_provider_and_model(selection=None):
    return llm_env.chat_runtime()


def _get_chat_runtime(selection=None):
    return llm_env.chat_runtime()


def _get_resume_provider_and_model():
    return llm_env.chat_runtime()


def _ensure_app_storage():
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(USER_STATE_DIR, exist_ok=True)
    os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)
    os.makedirs(CAREER_REPORT_DIR, exist_ok=True)


def _load_assessment_knowledge():
    if not os.path.exists(ASSESSMENT_DATA_FILE):
        return {}

    stat = os.stat(ASSESSMENT_DATA_FILE)
    signature = (stat.st_mtime_ns, stat.st_size)
    with ASSESSMENT_DATA_LOCK:
        if ASSESSMENT_DATA_CACHE.get("signature") == signature:
            return ASSESSMENT_DATA_CACHE.get("payload") or {}

    with open(ASSESSMENT_DATA_FILE, "r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        payload = {}

    with ASSESSMENT_DATA_LOCK:
        ASSESSMENT_DATA_CACHE["signature"] = signature
        ASSESSMENT_DATA_CACHE["payload"] = payload
    return payload


def _read_json_file(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return fallback
    except json.JSONDecodeError:
        return fallback


def _write_json_file(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _normalize_login_identifier(value):
    raw = str(value or "").strip()
    if "@" in raw:
        return raw.lower()
    return raw


def _looks_like_email(value):
    return bool(EMAIL_PATTERN.match(str(value or "").strip()))


def _default_display_name(identifier):
    raw = str(identifier or "").strip()
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    cleaned = re.sub(r"[\W_]+", " ", raw, flags=re.UNICODE).strip()
    return (cleaned[:32] or str(identifier or "").strip())[:48]


def _normalize_display_name(value, fallback_identifier=""):
    raw = str(value or "").strip()
    if not raw:
        return _default_display_name(fallback_identifier)
    return raw[:48]


def _normalized_user_record(raw_user):
    raw = raw_user if isinstance(raw_user, dict) else {}
    username = _normalize_login_identifier(raw.get("username"))
    if not username:
        return None
    return {
        "username": username,
        "password_hash": str(raw.get("password_hash") or "").strip(),
        "role": str(raw.get("role") or "user").strip() or "user",
        "display_name": _normalize_display_name(raw.get("display_name") or raw.get("displayName") or username, username),
    }


def _load_users():
    return _app_db.load_users()


def _find_user(username):
    normalized_name = _normalize_login_identifier(username)
    if not normalized_name:
        return None
    return _app_db.find_user(normalized_name)


def _public_user(user):
    if not user:
        return None
    return {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "can_manage_configs": user["role"] == "super_admin",
    }


def _current_user():
    return _auth.current_user()


def _login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if not user:
            return jsonify({"message": "请先登录。"}), 401
        return view_func(*args, **kwargs)
    return wrapper


def _super_admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if not user:
            return jsonify({"message": "请先登录。"}), 401
        if user.get("role") != "super_admin":
            return jsonify({"message": "当前账号无权修改系统模型配置。"}), 403
        return view_func(*args, **kwargs)
    return wrapper


def _user_state_path(username):
    safe_name = re.sub(r"[^0-9A-Za-z_.-]", "_", str(username or "").strip())
    return os.path.join(USER_STATE_DIR, f"{safe_name}.json")


def _user_storage_key(username):
    value = str(username or "").strip()
    return "u_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legacy_storage_key(username):
    return re.sub(r"[^0-9A-Za-z_.-]", "_", str(username or "").strip())


def _unique_legacy_owner(username):
    legacy = _legacy_storage_key(username)
    owners = [str(user.get("username") or "") for user in _load_users()
              if _legacy_storage_key(user.get("username")) == legacy]
    return owners == [str(username)]


def _private_account_directory(base_dir, username):
    # 管理端可按未绑定账号的目录编号读取清单；真实账号名称始终单独计算哈希。
    if re.fullmatch(r"u_[a-f0-9]{64}", str(username or "")) and not any(user.get("username") == username for user in _load_users()):
        return os.path.join(base_dir, username)
    target = os.path.join(base_dir, _user_storage_key(username))
    legacy = os.path.join(base_dir, _legacy_storage_key(username))
    # 已有目录仅在旧名称唯一归属当前账号时沿用；冲突目录不猜测归属。
    if not os.path.exists(target) and os.path.isdir(legacy) and _unique_legacy_owner(username):
        return legacy
    return target


def _owned_resume_storage_path(username, path):
    if not path:
        return ""
    root = os.path.realpath(_user_upload_dir(username))
    resolved = os.path.realpath(path)
    try:
        if os.path.commonpath([root, resolved]) == root:
            return resolved
    except ValueError:
        pass
    return ""


def _chat_resume_source(username):
    state = _load_user_state(username)
    resume = state.get("resume_profile") or {}
    path = _owned_resume_storage_path(username, str(resume.get("storage_path") or ""))
    if not path or not os.path.isfile(path):
        return {}
    return {"structured_profile": resume.get("structured_resume") or {}, "selection": {},
            "path": path, "document_id": str(resume.get("document_id") or ""),
            "name": str(resume.get("original_file_name") or resume.get("file_name") or "简历"),
            "text": str(resume.get("resume_source_text") or "")}


def _load_user_state(username):
    state = _app_db.load_user_state(username)
    return state if isinstance(state, dict) else {}


def _save_user_state(username, payload):
    normalized = payload if isinstance(payload, dict) else {}
    _app_db.save_user_state(username, normalized)
    return normalized


def _saved_profile_snapshot_payload(raw_scope):
    scope = raw_scope if isinstance(raw_scope, dict) else {}
    payload = scope.get("profile") if isinstance(scope.get("profile"), dict) else {}
    return payload if isinstance(payload, dict) else {}


def _saved_matching_role_payload(raw_scope):
    scope = raw_scope if isinstance(raw_scope, dict) else {}
    items = scope.get("role_rankings") if isinstance(scope.get("role_rankings"), list) else []
    return [item for item in items if isinstance(item, dict) and item.get("matchSource") != "career_graph"]


def _build_career_report_agent_memory(state, profile_payload=None, role_payload=None):
    safe_state = state if isinstance(state, dict) else {}
    profile_scope = safe_state.get("profile_snapshot") if isinstance(safe_state.get("profile_snapshot"), dict) else {}
    matching_scope = safe_state.get("career_matching") if isinstance(safe_state.get("career_matching"), dict) else {}
    resume_scope = safe_state.get("resume_profile") if isinstance(safe_state.get("resume_profile"), dict) else {}
    portrait_scope = safe_state.get("profile_portrait") if isinstance(safe_state.get("profile_portrait"), dict) else {}
    news_scope = safe_state.get("news_context") if isinstance(safe_state.get("news_context"), dict) else {}

    effective_profile = profile_payload if isinstance(profile_payload, dict) and profile_payload else _saved_profile_snapshot_payload(profile_scope)
    effective_roles = role_payload if isinstance(role_payload, list) and role_payload else _saved_matching_role_payload(matching_scope)

    return {
        "profile_snapshot": effective_profile,
        "career_matching": {
            "focus_role_id": str(matching_scope.get("focus_role_id") or "").strip(),
            "role_rankings": effective_roles,
            "updated_at": str(matching_scope.get("updated_at") or "").strip(),
        },
        "resume_memory": {
            "file_name": str(resume_scope.get("file_name") or "").strip(),
            "status": str(resume_scope.get("status") or "").strip(),
            "job_description": str(resume_scope.get("job_description") or "").strip(),
            "resume_source_text": str(resume_scope.get("resume_source_text") or ""),
            "resume_text_char_count": int(resume_scope.get("resume_text_char_count") or 0),
            "structured_resume": resume_scope.get("structured_resume") if isinstance(resume_scope.get("structured_resume"), dict) else {},
            "structured_job": resume_scope.get("structured_job") if isinstance(resume_scope.get("structured_job"), dict) else {},
            "resume_highlight_deck": resume_scope.get("resume_highlight_deck") if isinstance(resume_scope.get("resume_highlight_deck"), dict) else {},
            "analysis_meta": resume_scope.get("analysis_meta") if isinstance(resume_scope.get("analysis_meta"), dict) else {},
        },
        "portrait_memory": {
            "status": str(portrait_scope.get("status") or "").strip(),
            "brief": portrait_scope.get("brief") if isinstance(portrait_scope.get("brief"), dict) else {},
            "context_snapshot": normalize_profile_portrait_context(portrait_scope.get("context_snapshot")),
            "prompt_summary": str(portrait_scope.get("prompt_summary") or "").strip(),
        },
        "news_memory": news_scope,
    }






























































def _career_report_user_dir(username):
    return _private_account_directory(CAREER_REPORT_DIR, username)


CAREER_REPORT_EXPORT_FORMATS = ["pdf", "docx", "md", "html"]


def _career_report_export_formats(raw_formats=None):
    ordered = []
    for item in list(raw_formats or []) + CAREER_REPORT_EXPORT_FORMATS:
        fmt = str(item or "").strip().lower()
        if fmt in {"html", "md", "docx", "pdf"} and fmt not in ordered:
            ordered.append(fmt)
    return ordered or list(CAREER_REPORT_EXPORT_FORMATS)


def _career_report_export_filename_stem(
    title: str,
    *,
    report_id: str = "",
    generated_at: str = "",
    version: str = "",
    snapshot_id: str = "",
) -> str:
    """Build download filename stem (no extension): keep CJK, strip path-forbidden characters."""
    text = str(title or "").strip() or "职业规划报告"
    text = text.replace("\u00b7", "-").replace("・", "-").replace("·", "-")
    text = re.sub(r'[\\/:*?"<>|\r\n\x00]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    extra = []
    ga = str(generated_at or "").strip()
    m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", ga)
    if m:
        extra.append(f"{m.group(1)}{m.group(2)}{m.group(3)}")
    elif str(version or "").strip():
        ver = re.sub(r"[^\w.\-]", "-", str(version))[:24].strip("-")
        if ver:
            extra.append(ver)
    if snapshot_id:
        snap = re.sub(r"[^a-zA-Z0-9._-]", "-", str(snapshot_id))[:24].strip("-")
        if snap:
            extra.append(f"snap-{snap}")
    suffix = ""
    if extra:
        suffix = "_" + "_".join(extra)
    max_text = max(32, 120 - len(suffix))
    if len(text) > max_text:
        text = text[:max_text].rstrip(" .")
    stem = f"{text}{suffix}".strip(" ._")
    if len(stem) > 180:
        stem = stem[:180].rstrip(" .")
    rid = re.sub(r"[^a-zA-Z0-9._-]", "-", str(report_id or ""))[:32].strip("-")
    if not stem or stem in {".", ".."}:
        stem = f"职业规划报告_{rid}" if rid else "职业规划报告"
    return stem


def _attachment_content_disposition(full_filename: str) -> str:
    """ASCII `filename` fallback plus RFC 5987 `filename*` for Unicode download names."""
    safe = secure_filename(full_filename)
    if not safe:
        base, ext = os.path.splitext(full_filename)
        safe = (secure_filename(base) or "career-report") + ext
    encoded = urllib.parse.quote(full_filename, safe="")
    if any(ord(c) > 127 for c in full_filename):
        return f'attachment; filename="{safe}"; filename*=UTF-8\'\'{encoded}'
    return f'attachment; filename="{full_filename}"'


def _career_report_file_paths(username):
    base_dir = _career_report_user_dir(username)
    return {
        "dir": base_dir,
        "json": os.path.join(base_dir, "latest.json"),
        "html": os.path.join(base_dir, "latest.html"),
        "md": os.path.join(base_dir, "latest.md"),
        "job": os.path.join(base_dir, "current_job.json"),
        "versions_dir": os.path.join(base_dir, "versions"),
        "drafts_dir": os.path.join(base_dir, "drafts"),
    }


def _read_career_report_bundle(username):
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        payload = _read_json_file(paths["json"], {})
    return payload if isinstance(payload, dict) else {}


def _read_career_report_bundle_by_id(username, report_id=""):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        if not safe_report_id:
            payload = _read_json_file(paths["json"], {})
            return payload if isinstance(payload, dict) else {}

        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")
        if os.path.isfile(archive_path):
            payload = _read_json_file(archive_path, {})
            return payload if isinstance(payload, dict) else {}

        latest = _read_json_file(paths["json"], {})
        latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
        if latest_id == safe_report_id:
            return latest if isinstance(latest, dict) else {}
    return {}


def _summarize_career_report_bundle(bundle):
    bundle = _refresh_career_report_role_resolution(bundle)
    if not isinstance(bundle, dict):
        return None

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_id = str(meta.get("report_id") or "").strip()
    if not report_id:
        return None

    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    gap_map = bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {}
    dashboard_summary = document.get("dashboard_summary") if isinstance(document.get("dashboard_summary"), dict) else {}
    evidence_health = document.get("evidence_health") if isinstance(document.get("evidence_health"), dict) else {}
    plan_board = document.get("plan_board") if isinstance(document.get("plan_board"), dict) else {}
    next_actions = document.get("next_actions") if isinstance(document.get("next_actions"), dict) else {}
    match_output = bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {}
    focus_role_name = (
        str(document.get("focus_role_name") or "")
        or str(meta.get("focus_role_name") or "")
        or str(gap_map.get("focus_role_name") or "")
    ).strip()
    summary_text = re.sub(
        r"\s+",
        " ",
        str(document.get("executive_summary") or meta.get("summary") or "").strip(),
    )
    fit_score = dashboard_summary.get("fit_score")
    try:
        fit_score = max(0, min(100, int(round(float(fit_score)))))
    except (TypeError, ValueError):
        fit_score = None
    fit_band = str(dashboard_summary.get("fit_band") or match_output.get("fit_band") or "").strip().lower()
    fit_band_label = str(dashboard_summary.get("fit_band_label") or "").strip()
    if not fit_band_label:
        fit_band_label = {
            "strong": "高匹配",
            "moderate": "中等匹配",
            "weak": "低匹配",
            "not_ready": "尚需准备",
        }.get(fit_band, "")

    strengths = evidence_health.get("strengths") if isinstance(evidence_health.get("strengths"), list) else []
    gap_items = []
    for key in ("hard_failures", "skill_gaps", "evidence_gaps", "missing_inputs"):
        values = evidence_health.get(key)
        if isinstance(values, list):
            gap_items.extend(values)
    action_items = plan_board.get("action_items") if isinstance(plan_board.get("action_items"), list) else []
    if not action_items:
        action_items = next_actions.get("action_items") if isinstance(next_actions.get("action_items"), list) else []
    role_cards = document.get("role_cards") if isinstance(document.get("role_cards"), list) else []
    role_rankings = bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else []
    sections = document.get("sections")
    if isinstance(sections, dict):
        section_count = len(sections)
    elif isinstance(sections, list):
        section_count = len(sections)
    else:
        section_count = 0

    return {
        "report_id": report_id,
        "title": str(meta.get("title") or document.get("title") or "职业规划报告").strip() or "职业规划报告",
        "version": str(meta.get("version") or "").strip(),
        "generated_at": str(meta.get("generated_at") or "").strip(),
        "focus_role_id": str(meta.get("focus_role_id") or "").strip(),
        "focus_role_name": focus_role_name,
        "summary_excerpt": summary_text[:117] + "..." if len(summary_text) > 120 else summary_text,
        "fit_score": fit_score,
        "fit_band": fit_band,
        "fit_band_label": fit_band_label,
        "strength_count": len(strengths),
        "gap_count": len(gap_items),
        "action_count": len(action_items),
        "role_count": len(role_cards or role_rankings),
        "section_count": section_count,
    }


def _refresh_career_report_role_resolution(raw_bundle):
    bundle = dict(raw_bundle) if isinstance(raw_bundle, dict) else {}
    meta = dict(bundle.get("meta") or {}) if isinstance(bundle.get("meta"), dict) else {}
    if not meta:
        return bundle

    role_rankings = bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else []
    match_output = bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {}
    if not role_rankings or not match_output:
        return bundle

    normalized_match = _normalize_match_output(match_output, role_rankings)
    resolved_match = _resolve_effective_match_output(
        normalized_match,
        role_rankings,
        str(meta.get("focus_role_id") or "").strip(),
    )
    focus_role_name = _resolve_focus_role_name("", role_rankings, resolved_match.get("target_role"))
    if not focus_role_name:
        return bundle

    previous_focus_role_name = str(meta.get("focus_role_name") or "").strip()
    meta["focus_role_name"] = focus_role_name
    title = str(meta.get("title") or "").strip()
    if title and previous_focus_role_name and previous_focus_role_name != focus_role_name:
        meta["title"] = title.replace(previous_focus_role_name, focus_role_name, 1)
    bundle["meta"] = meta
    bundle["match_output"] = resolved_match

    gap_map = dict(bundle.get("gap_map") or {}) if isinstance(bundle.get("gap_map"), dict) else {}
    gap_map["focus_role_name"] = focus_role_name
    bundle["gap_map"] = gap_map

    career_path = dict(bundle.get("career_path") or {}) if isinstance(bundle.get("career_path"), dict) else {}
    if career_path:
        career_path["target_role"] = focus_role_name
        bundle["career_path"] = career_path

    document = dict(bundle.get("report_document") or {}) if isinstance(bundle.get("report_document"), dict) else {}
    if document:
        document_title = str(document.get("title") or "").strip()
        if document_title and previous_focus_role_name and previous_focus_role_name != focus_role_name:
            document["title"] = document_title.replace(previous_focus_role_name, focus_role_name, 1)
        document["focus_role_name"] = focus_role_name
        document["dashboard_summary"] = _build_dashboard_summary(
            focus_role_name,
            resolved_match,
            bundle.get("positioning_output") if isinstance(bundle.get("positioning_output"), dict) else {},
            gap_map,
            bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
            bundle.get("industry_brief") if isinstance(bundle.get("industry_brief"), dict) else {},
        )
        document["role_cards"] = _build_role_cards(
            role_rankings,
            resolved_match,
            bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
        )
        bundle["report_document"] = document

    bundle["role_rankings"] = _build_role_rankings(role_rankings, resolved_match)
    return bundle


def _list_career_report_version_summaries(username, include_latest=True, lock=True):
    paths = _career_report_file_paths(username)

    def _collect():
        items = []

        if include_latest:
            latest_bundle = _read_json_file(paths["json"], {})
            summary = _summarize_career_report_bundle(latest_bundle)
            if summary:
                items.append(summary)

        versions_dir = paths["versions_dir"]
        if os.path.isdir(versions_dir):
            for name in os.listdir(versions_dir):
                if not name.lower().endswith(".json"):
                    continue
                payload = _read_json_file(os.path.join(versions_dir, name), {})
                summary = _summarize_career_report_bundle(payload)
                if summary:
                    items.append(summary)

        deduped = []
        seen = set()
        for item in sorted(
            items,
            key=lambda value: (str(value.get("generated_at") or ""), str(value.get("report_id") or "")),
            reverse=True,
        ):
            report_id = str(item.get("report_id") or "").strip()
            if not report_id or report_id in seen:
                continue
            seen.add(report_id)
            deduped.append(item)
        return deduped

    if not lock:
        return _collect()
    with APP_DATA_LOCK:
        return _collect()


def _prepare_career_report_bundle_payload(bundle):
    payload = dict(bundle) if isinstance(bundle, dict) else {}
    report_document = dict(payload.get("report_document") or {}) if isinstance(payload.get("report_document"), dict) else {}
    payload["report_document"] = report_document

    markdown_text = str(report_document.get("markdown") or "").strip()
    if not markdown_text:
        markdown_text = render_report_markdown(payload).strip()
    markdown_text = normalize_br_tags_in_markdown(markdown_text)
    report_document["markdown"] = markdown_text

    html_text = str(report_document.get("html") or "").strip()
    if not html_text:
        html_text = render_report_html(payload).strip()
        report_document["html"] = html_text

    return payload, markdown_text, html_text


def _write_current_career_report_files(paths, payload, markdown_text="", html_text=""):
    _write_json_file(paths["json"], payload)

    if markdown_text:
        with open(paths["md"], "w", encoding="utf-8") as fp:
            fp.write(markdown_text)
    elif os.path.isfile(paths["md"]):
        os.remove(paths["md"])

    if html_text:
        with open(paths["html"], "w", encoding="utf-8") as fp:
            fp.write(html_text)
    elif os.path.isfile(paths["html"]):
        os.remove(paths["html"])

    _write_json_file(paths["job"], {
        "report_id": str(payload.get("meta", {}).get("report_id") or ""),
        "generated_at": str(payload.get("meta", {}).get("generated_at") or ""),
        "title": str(payload.get("meta", {}).get("title") or ""),
    })


def _remove_current_career_report_files(paths):
    for key in ("json", "html", "md", "job"):
        target = paths.get(key)
        if target and os.path.isfile(target):
            os.remove(target)


def _delete_career_report_version(username, report_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        raise ValueError("缺少 report_id")

    paths = _career_report_file_paths(username)
    deleted_current = False
    replacement_report_id = ""
    replacement_title = ""

    with APP_DATA_LOCK:
        latest_bundle = _read_json_file(paths["json"], {})
        latest_id = str((latest_bundle.get("meta") or {}).get("report_id") or "").strip()
        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")

        if latest_id == safe_report_id:
            deleted_current = True
            replacement_candidates = []
            if os.path.isdir(paths["versions_dir"]):
                for name in os.listdir(paths["versions_dir"]):
                    if not name.lower().endswith(".json"):
                        continue
                    candidate_path = os.path.join(paths["versions_dir"], name)
                    payload = _read_json_file(candidate_path, {})
                    summary = _summarize_career_report_bundle(payload)
                    if summary:
                        replacement_candidates.append((summary, payload, candidate_path))

            replacement_candidates.sort(
                key=lambda item: (str(item[0].get("generated_at") or ""), str(item[0].get("report_id") or "")),
                reverse=True,
            )

            if replacement_candidates:
                summary, replacement_bundle, replacement_path = replacement_candidates[0]
                replacement_report_id = str(summary.get("report_id") or "").strip()
                replacement_title = str(summary.get("title") or "").strip()
                if os.path.isfile(replacement_path):
                    os.remove(replacement_path)
                prepared_bundle, markdown_text, html_text = _prepare_career_report_bundle_payload(replacement_bundle)
                _write_current_career_report_files(paths, prepared_bundle, markdown_text, html_text)
            else:
                _remove_current_career_report_files(paths)
        elif os.path.isfile(archive_path):
            os.remove(archive_path)
        else:
            raise FileNotFoundError("未找到对应的职业报告版本。")

        snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
        if os.path.isdir(snapshot_dir):
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    current_bundle = _read_career_report_bundle(username)
    if isinstance(current_bundle, dict) and current_bundle.get("meta"):
        _sync_career_report_tracker_state(username, current_bundle)
    else:
        state = _load_user_state(username)
        state["career_report"] = empty_report_state()
        _save_user_state(username, state)

    return {
        "deleted_current": deleted_current,
        "deleted_report_id": safe_report_id,
        "replacement_report_id": replacement_report_id,
        "replacement_title": replacement_title,
    }


def _clip_career_report_text(value, limit=140):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[:max(0, limit - 1)]}…"


def _career_report_section_title(section_id, section):
    if not isinstance(section, dict):
        return str(section_id or "章节")
    return str(
        section.get("label")
        or section.get("title")
        or section.get("kicker")
        or section_id
        or "章节"
    ).strip() or "章节"


def _build_career_report_section_map(bundle, markdown_text=""):
    report_document = bundle.get("report_document") if isinstance(bundle, dict) else {}
    report_document = report_document if isinstance(report_document, dict) else {}
    sections = report_document.get("sections")
    result = []
    if isinstance(sections, dict):
        ordered_keys = report_document.get("section_order") or [
            "industry_analysis",
            "career_positioning",
            "resume_evidence",
            "competency_profile",
            "role_match",
            "path_plan",
        ]
        seen = set()
        for key in ordered_keys + list(sections.keys()):
            if key in seen:
                continue
            seen.add(key)
            section = sections.get(key)
            if not isinstance(section, dict):
                continue
            result.append({
                "key": str(key),
                "label": _career_report_section_title(key, section),
                "markdown": str(section.get("markdown") or "").strip(),
            })
        return result
    if isinstance(sections, list):
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            result.append({
                "key": str(section.get("id") or f"section-{index + 1}"),
                "label": _career_report_section_title(section.get("id") or f"section-{index + 1}", section),
                "markdown": str(section.get("markdown") or section.get("summary") or "").strip(),
            })
        return result

    source_text = str(markdown_text or report_document.get("markdown") or "").strip()
    if not source_text:
        return []

    current = None
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if current:
                result.append(current)
            label = line[3:].strip()
            current = {"key": f"section-{len(result) + 1}", "label": label or "章节", "markdown": ""}
            continue
        if current is None:
            continue
        current["markdown"] = f"{current['markdown']}\n{raw_line}".strip()
    if current:
        result.append(current)
    return result


def _normalize_career_report_snapshot(raw_snapshot, bundle=None, report_id=""):
    raw = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_bundle = bundle if isinstance(bundle, dict) else {}
    meta = base_bundle.get("meta") if isinstance(base_bundle.get("meta"), dict) else {}
    markdown = str(raw.get("markdown") or "").strip()
    normalized = {
        "snapshot_id": str(raw.get("snapshot_id") or f"snapshot-{uuid.uuid4().hex[:10]}").strip(),
        "based_on_report_id": str(raw.get("based_on_report_id") or report_id or meta.get("report_id") or "").strip(),
        "source": str(raw.get("source") or "manual").strip() or "manual",
        "label": str(raw.get("label") or raw.get("title") or "编辑快照").strip() or "编辑快照",
        "title": str(raw.get("title") or raw.get("label") or "编辑快照").strip() or "编辑快照",
        "focus_role_name": str(raw.get("focus_role_name") or meta.get("focus_role_name") or "").strip(),
        "created_at": str(raw.get("created_at") or timestamp).strip(),
        "updated_at": str(raw.get("updated_at") or raw.get("created_at") or timestamp).strip(),
        "markdown": markdown,
        "section_map": raw.get("section_map") if isinstance(raw.get("section_map"), list) else _build_career_report_section_map(base_bundle, markdown),
        "diff_blocks": raw.get("diff_blocks") if isinstance(raw.get("diff_blocks"), list) else [],
        "completeness_check": raw.get("completeness_check") if isinstance(raw.get("completeness_check"), dict) else None,
    }
    normalized["summary"] = str(raw.get("summary") or _clip_career_report_text(markdown, 180)).strip()
    normalized["has_diff"] = bool(normalized["diff_blocks"])
    return normalized


def _public_career_report_snapshot(raw_snapshot, include_content=False):
    snapshot = _normalize_career_report_snapshot(raw_snapshot)
    public_data = {
        "snapshot_id": snapshot["snapshot_id"],
        "based_on_report_id": snapshot["based_on_report_id"],
        "source": snapshot["source"],
        "label": snapshot["label"],
        "title": snapshot["title"],
        "focus_role_name": snapshot["focus_role_name"],
        "created_at": snapshot["created_at"],
        "updated_at": snapshot["updated_at"],
        "summary": snapshot["summary"],
        "has_diff": snapshot["has_diff"],
    }
    if include_content:
        public_data.update({
            "markdown": snapshot["markdown"],
            "section_map": snapshot["section_map"],
            "diff_blocks": snapshot["diff_blocks"],
            "completeness_check": snapshot["completeness_check"],
        })
    return public_data


def _career_report_snapshot_dir(paths, report_id):
    safe_report_id = _checked_report_identifier(report_id)
    return os.path.join(paths["drafts_dir"], safe_report_id)


def _list_career_report_snapshots(username, report_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        return []
    paths = _career_report_file_paths(username)
    snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
    if not os.path.isdir(snapshot_dir):
        return []
    summaries = []
    with APP_DATA_LOCK:
        for name in os.listdir(snapshot_dir):
            if not name.lower().endswith(".json"):
                continue
            payload = _read_json_file(os.path.join(snapshot_dir, name), {})
            if not isinstance(payload, dict):
                continue
            summaries.append(_public_career_report_snapshot(payload))
    summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return summaries


def _read_career_report_snapshot(username, report_id, snapshot_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    safe_snapshot_id = _checked_report_identifier(snapshot_id, allow_empty=True)
    if not safe_snapshot_id:
        return None
    paths = _career_report_file_paths(username)
    candidates = []
    if safe_report_id:
        candidates.append(os.path.join(_career_report_snapshot_dir(paths, safe_report_id), f"{safe_snapshot_id}.json"))
    else:
        drafts_root = paths["drafts_dir"]
        if os.path.isdir(drafts_root):
            for child in os.listdir(drafts_root):
                candidates.append(os.path.join(drafts_root, child, f"{safe_snapshot_id}.json"))
    with APP_DATA_LOCK:
        for path in candidates:
            if not os.path.isfile(path):
                continue
            payload = _read_json_file(path, {})
            if isinstance(payload, dict) and payload:
                return payload
    return None


def _commit_career_report_markdown_to_store(username, report_id, markdown_text):
    """将润色后的 Markdown 写回已存储的职业报告正文（阅览室与后续加载同源）。"""
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    md = normalize_br_tags_in_markdown(str(markdown_text or "").strip())
    if not safe_report_id or not md:
        return False
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        bundle = _read_career_report_bundle_by_id(username, safe_report_id)
        if not isinstance(bundle, dict) or not bundle.get("meta"):
            return False
        report_document = dict(bundle.get("report_document") or {})
        report_document["markdown"] = md
        bundle["report_document"] = report_document
        prepared, md_out, html_out = _prepare_career_report_bundle_payload(bundle)
        latest = _read_json_file(paths["json"], {})
        latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
        if latest_id == safe_report_id:
            _write_current_career_report_files(paths, prepared, md_out, html_out)
            return True
        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")
        if os.path.isfile(archive_path):
            _write_json_file(archive_path, prepared)
            return True
    return False


def _save_career_report_snapshot(username, report_id, snapshot):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        raise ValueError("缺少 report_id")
    paths = _career_report_file_paths(username)
    snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
    normalized = _normalize_career_report_snapshot(snapshot, report_id=safe_report_id)
    os.makedirs(snapshot_dir, exist_ok=True)
    target_path = os.path.join(snapshot_dir, f"{normalized['snapshot_id']}.json")
    with APP_DATA_LOCK:
        _write_json_file(target_path, normalized)
    return normalized


_CAREER_REPORT_QUICK_POLISH = {
    "professional": "请将目标段落改写为更专业、偏职场与学术书面语的表达；保持事实与结论不变，不新增数据或承诺。",
    "concise": "请在保留关键信息的前提下删除冗余与重复表述，使行文更精炼。",
    "bullets": "请将段落改写为条理清晰的项目符号或编号要点（使用 Markdown 列表语法），便于扫读。",
    "evidence": "请在不杜撰量化数据的前提下强化论据：突出能力、经历与岗位/行业要求之间的对应关系。",
}


def _fallback_summary_career_quick_action(key: str) -> str:
    return {
        "professional": "已按「更专业」收紧措辞与论证语气，使之更符合职业报告书面表达；未新增事实。",
        "concise": "已删减重复表述并压缩句子，使信息更集中；关键结论未改。",
        "bullets": "已将段落改写为要点列表，便于快速扫读；原意保持不变。",
        "evidence": "已强化论点与经历、岗位之间的对应表述；未虚构数据。",
    }.get(key, "已完成本次润色，请对照 Diff 查看具体改动。")


def _split_career_polish_output(raw: str):
    """模型输出：先概括，再一行 <<<AI_BODY>>>，再润色正文。无标记时返回 ("", "")。"""
    s = str(raw or "").strip()
    mark = "<<<AI_BODY>>>"
    if mark not in s:
        return "", ""
    head, tail = s.split(mark, 1)
    body = tail.strip()
    summary = head.strip()
    if body:
        return summary, body
    return "", ""


def _build_career_report_diff_blocks(original_text, proposed_text):
    original_lines = str(original_text or "").splitlines()
    proposed_lines = str(proposed_text or "").splitlines()
    matcher = difflib.SequenceMatcher(a=original_lines, b=proposed_lines)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            if i1 != i2:
                blocks.append({"type": "delete", "lines": original_lines[i1:i2]})
            if j1 != j2:
                blocks.append({"type": "add", "lines": proposed_lines[j1:j2]})
            continue
        blocks.append({
            "type": "equal" if tag == "equal" else ("delete" if tag == "delete" else "add"),
            "lines": original_lines[i1:i2] if tag != "insert" else proposed_lines[j1:j2],
        })
    return [block for block in blocks if block.get("lines")]


def _run_career_report_completeness_check(bundle, markdown_text="", snapshot=None):
    safe_bundle = bundle if isinstance(bundle, dict) else {}
    report_document = safe_bundle.get("report_document") if isinstance(safe_bundle.get("report_document"), dict) else {}
    section_map = []
    if isinstance(snapshot, dict) and isinstance(snapshot.get("section_map"), list):
        section_map = snapshot.get("section_map") or []
    if not section_map:
        section_map = _build_career_report_section_map(safe_bundle, markdown_text)
    issues = []

    required_sections = {
        "industry_analysis": "行业现状",
        "career_positioning": "当前定位",
        "role_match": "目标岗位对比",
        "path_plan": "职业路径",
    }
    if report_document.get("reading_layout") in {"narrative-v1", "narrative-v2", "numbered-reader-v3"}:
        required_sections = {"executive_summary": "核心结论", "personal_traits": "简历分析",
                             "matching_decision": "岗位对照", "gap_action_plan": "成长规划",
                             "development_path": "总结与下一步", "appendix": "参考依据"}
    elif report_document.get("section_order"):
        required_sections = {"personal_traits": "个人画像", "target_job_analysis": "职业目标", "macro_environment": "就业市场",
                             "matching_decision": "岗位适配", "ability_gaps": "能力差距", "development_path": "成长路径",
                             "gap_action_plan": "行动计划", "risk_backup": "动态评估", "appendix": "参考依据"}
    section_keys = {str(item.get("key") or "").strip() for item in section_map if isinstance(item, dict)}
    for key, label in required_sections.items():
        if key not in section_keys or not any(item.get("key") == key and item.get("markdown") for item in section_map):
            issues.append({"level": "warning", "type": "missing_section", "message": f"缺少“{label}”章节。"})

    markdown_value = str(markdown_text or report_document.get("markdown") or "").strip()
    if report_document.get("reading_layout") not in {"narrative-v1", "narrative-v2", "numbered-reader-v3"} and len(markdown_value) < 600:
        issues.append({"level": "warning", "type": "content_length", "message": "报告正文偏短，请检查关键判断、依据和行动安排是否完整。"})

    explainability_summary = report_document.get("explainability_summary") if isinstance(report_document.get("explainability_summary"), dict) else {}
    because_items = explainability_summary.get("headline_because") if isinstance(explainability_summary.get("headline_because"), list) else []
    evidence_items = []
    if isinstance(snapshot, dict):
        completeness = snapshot.get("completeness_check")
        if isinstance(completeness, dict):
            evidence_items = completeness.get("evidence_trace") if isinstance(completeness.get("evidence_trace"), list) else []
    if not evidence_items:
        evidence_health = report_document.get("evidence_health") if isinstance(report_document.get("evidence_health"), dict) else {}
        evidence_items = evidence_health.get("evidence_trace") if isinstance(evidence_health.get("evidence_trace"), list) else []

    if not because_items:
        issues.append({"level": "warning", "type": "explainability", "message": "关键判断缺少“为什么”的解释链。"})
    if not evidence_items:
        issues.append({"level": "warning", "type": "evidence_trace", "message": "当前报告缺少简历证据回指，用户很难验证判断来源。"})

    plan_board = report_document.get("plan_board") if isinstance(report_document.get("plan_board"), dict) else {}
    action_items = plan_board.get("action_items") if isinstance(plan_board.get("action_items"), list) else []
    if not action_items:
        next_actions = report_document.get("next_actions") if isinstance(report_document.get("next_actions"), dict) else {}
        action_items = next_actions.get("action_items") if isinstance(next_actions.get("action_items"), list) else []
    if not action_items:
        issues.append({"level": "warning", "type": "action_plan", "message": "行动计划为空，无法形成从差距到执行的闭环。"})

    return {
        "status": "pass" if not issues else "attention",
        "issue_count": len(issues),
        "issues": issues,
        "section_count": len(section_map),
        "markdown_chars": len(markdown_value),
        "headline_because": because_items[:4],
        "evidence_trace": evidence_items[:4],
    }


def _save_career_report_bundle(username, bundle):
    paths = _career_report_file_paths(username)
    os.makedirs(paths["dir"], exist_ok=True)
    payload, markdown_text, html_text = _prepare_career_report_bundle_payload(bundle)
    new_meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    new_report_id = str(new_meta.get("report_id") or "").strip()
    versions_dir = paths["versions_dir"]
    with APP_DATA_LOCK:
        existing = _read_json_file(paths["json"], {})
        if (
            isinstance(existing, dict)
            and existing.get("meta")
            and new_report_id
            and isinstance(existing.get("meta"), dict)
        ):
            old_id = str(existing["meta"].get("report_id") or "").strip()
            if old_id and old_id != new_report_id and existing.get("report_document"):
                os.makedirs(versions_dir, exist_ok=True)
                archive_path = os.path.join(versions_dir, f"{old_id}.json")
                if not os.path.isfile(archive_path):
                    _write_json_file(archive_path, existing)
        _write_current_career_report_files(paths, payload, markdown_text, html_text)
    state = _load_user_state(username)
    profile_snapshot = payload.get("profile_snapshot") if isinstance(payload.get("profile_snapshot"), dict) else {}
    if profile_snapshot:
        state["profile_snapshot"] = {
            "version": "2026.04-profile-snapshot-v1",
            "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "profile": profile_snapshot,
            "source": "career_report_bundle",
        }
    role_rankings = payload.get("role_rankings") if isinstance(payload.get("role_rankings"), list) else []
    if role_rankings:
        matching_state = state.get("career_matching") if isinstance(state.get("career_matching"), dict) else {}
        focus_role_id = str(new_meta.get("focus_role_id") or matching_state.get("focus_role_id") or "").strip()
        focus_role_name = str(new_meta.get("focus_role_name") or matching_state.get("focus_role_name") or "").strip()
        matched_focus_role = next((role for role in role_rankings if str(role.get("id") or "").strip() == focus_role_id), None)
        if focus_role_name and matched_focus_role and str(matched_focus_role.get("name") or "").strip() != focus_role_name:
            matched_focus_role = next((role for role in role_rankings if str(role.get("name") or "").strip() == focus_role_name), None)
        if not matched_focus_role and focus_role_name:
            matched_focus_role = next((role for role in role_rankings if str(role.get("name") or "").strip() == focus_role_name), None)
        if not matched_focus_role and role_rankings:
            matched_focus_role = role_rankings[0] if isinstance(role_rankings[0], dict) else None
        if isinstance(matched_focus_role, dict):
            focus_role_id = str(matched_focus_role.get("id") or focus_role_id or "").strip()
            focus_role_name = str(matched_focus_role.get("name") or focus_role_name or "").strip()
        matching_state.update(
            {
                "version": "2026.04-career-matching-v1",
                "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "focus_role_id": focus_role_id,
                "focus_role_name": focus_role_name,
                "role_rankings": role_rankings,
                "source": "career_report_bundle",
            }
        )
        state["career_matching"] = matching_state
    diagnostics = payload.get("generation_diagnostics") if isinstance(payload.get("generation_diagnostics"), dict) else {}
    news_snapshot = diagnostics.get("news_context_snapshot") if isinstance(diagnostics.get("news_context_snapshot"), dict) else {}
    if news_snapshot:
        state["news_context"] = {
            "version": "2026.04-news-context-v1",
            "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "report_id": str(new_meta.get("report_id") or "").strip(),
            "item_count": int(news_snapshot.get("item_count") or 0),
            "char_count": int(news_snapshot.get("char_count") or 0),
            "source": str(news_snapshot.get("source") or "career_report_bundle").strip(),
            "text": str(news_snapshot.get("text") or ""),
        }
    _save_user_state(username, state)
    return payload


def _normalize_career_report_feedback(raw_feedback):
    return normalize_feedback_memory(raw_feedback)


def _append_career_report_feedback(raw_feedback, entry):
    normalized = _normalize_career_report_feedback(raw_feedback)
    entries = normalized.get("entries") if isinstance(normalized.get("entries"), list) else []
    entries.append(
        {
            "id": str(entry.get("id") or f"feedback-{uuid.uuid4().hex[:10]}").strip(),
            "report_id": str(entry.get("report_id") or "").strip(),
            "focus_role_id": str(entry.get("focus_role_id") or "").strip(),
            "focus_role_name": str(entry.get("focus_role_name") or "").strip(),
            "verdict": str(entry.get("verdict") or "partial").strip().lower(),
            "note": str(entry.get("note") or "").strip()[:320],
            "created_at": str(entry.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip(),
        }
    )
    return _normalize_career_report_feedback({
        "version": CAREER_FEEDBACK_VERSION,
        "entries": entries,
    })


def _public_career_report_state(raw_state):
    state = empty_report_state()
    if isinstance(raw_state, dict):
        state.update({
            "status": str(raw_state.get("status") or state["status"]),
            "job_id": str(raw_state.get("job_id") or ""),
            "report_id": str(raw_state.get("report_id") or ""),
            "generated_at": str(raw_state.get("generated_at") or ""),
            "stage": str(raw_state.get("stage") or ""),
            "stage_label": str(raw_state.get("stage_label") or ""),
            "stage_detail": str(raw_state.get("stage_detail") or ""),
            "error_message": str(raw_state.get("error_message") or ""),
            "progress": raw_state.get("progress") if isinstance(raw_state.get("progress"), list) else [],
            "agent_activity": raw_state.get("agent_activity") if isinstance(raw_state.get("agent_activity"), dict) else {},
            "model": str(raw_state.get("model") or ""),
            "generation_mode": str(raw_state.get("generation_mode") or ""),
            "focus_role_id": str(raw_state.get("focus_role_id") or ""),
            "title": str(raw_state.get("title") or ""),
            "summary": str(raw_state.get("summary") or ""),
            "export_formats": _career_report_export_formats(raw_state.get("export_formats")),
            "tracker": raw_state.get("tracker") if isinstance(raw_state.get("tracker"), dict) else None,
            "feedback": _normalize_career_report_feedback(raw_state.get("feedback")),
        })
    return state


def _sanitize_transient_career_report_state(username, raw_state, current_bundle=None):
    state = raw_state if isinstance(raw_state, dict) else {}
    status = str(state.get("status") or "").strip().lower()
    if status not in {"canceled", "cancelled"}:
        return state, False

    bundle = current_bundle if isinstance(current_bundle, dict) else _read_career_report_bundle(username)
    if isinstance(bundle, dict) and bundle.get("meta"):
        return state, False

    cleaned = empty_report_state()
    feedback = _normalize_career_report_feedback(state.get("feedback"))
    if feedback is not None:
        cleaned["feedback"] = feedback
    return cleaned, True


def _public_career_report_job(raw_job):
    job = empty_report_job()
    if isinstance(raw_job, dict):
        job.update({
            "job_id": str(raw_job.get("job_id") or ""),
            "username": str(raw_job.get("username") or ""),
            "status": str(raw_job.get("status") or job["status"]),
            "stage": str(raw_job.get("stage") or ""),
            "stage_label": str(raw_job.get("stage_label") or ""),
            "stage_detail": str(raw_job.get("stage_detail") or ""),
            "message": str(raw_job.get("message") or ""),
            "created_at": int(raw_job.get("created_at") or 0),
            "started_at": int(raw_job.get("started_at") or 0),
            "finished_at": int(raw_job.get("finished_at") or 0),
            "report_id": str(raw_job.get("report_id") or ""),
            "progress": raw_job.get("progress") if isinstance(raw_job.get("progress"), list) else [],
            "agent_activity": raw_job.get("agent_activity") if isinstance(raw_job.get("agent_activity"), dict) else {},
            "model": str(raw_job.get("model") or ""),
            "generation_mode": str(raw_job.get("generation_mode") or ""),
        })
    return job


def _public_career_report_bundle(raw_bundle):
    bundle = _refresh_career_report_role_resolution(raw_bundle)
    bundle = bundle if isinstance(bundle, dict) else {}
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    public_document = dict(document)
    public_document.pop("markdown", None)
    public_document.pop("html", None)
    report_id = str(meta.get("report_id") or "").strip()
    return {
        "meta": meta,
        "industry_brief": bundle.get("industry_brief") if isinstance(bundle.get("industry_brief"), dict) else {},
        "positioning_output": bundle.get("positioning_output") if isinstance(bundle.get("positioning_output"), dict) else {},
        "resume_evidence": bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
        "competency_profile": bundle.get("competency_profile") if isinstance(bundle.get("competency_profile"), dict) else {},
        "match_output": bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {},
        "path_plan": bundle.get("path_plan") if isinstance(bundle.get("path_plan"), dict) else {},
        "profile_snapshot": bundle.get("profile_snapshot") if isinstance(bundle.get("profile_snapshot"), dict) else {},
        "role_rankings": bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else [],
        "gap_map": bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {},
        "career_path": bundle.get("career_path") if isinstance(bundle.get("career_path"), dict) else {},
        "phase_plan": bundle.get("phase_plan") if isinstance(bundle.get("phase_plan"), dict) else {},
        "trend_brief": bundle.get("trend_brief") if isinstance(bundle.get("trend_brief"), dict) else {},
        "report_document": public_document,
        "draft_snapshots": _list_career_report_snapshots(meta.get("username") or meta.get("user") or "", report_id) if report_id and (meta.get("username") or meta.get("user")) else [],
        "generation_diagnostics": bundle.get("generation_diagnostics") if isinstance(bundle.get("generation_diagnostics"), dict) else {},
    }


def _career_tracker_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_tracker_score(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score != score:
        return None
    return max(0, min(100, int(round(score))))


def _normalize_tracker_status(raw_status, allow_doing=True):
    status = str(raw_status or "").strip().lower()
    if status in {"done", "completed", "complete", "checked"}:
        return "done"
    if allow_doing and status in {"doing", "active", "running", "in_progress", "progress"}:
        return "doing"
    return "pending"


def _slugify_tracker_id(raw_text):
    slug = re.sub(r"[^0-9A-Za-z_.-]+", "-", str(raw_text or "").strip()).strip("-").lower()
    return slug or "item"


def _normalize_tracker_history(raw_history):
    history = []
    if not isinstance(raw_history, list):
        return history
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        score = _normalize_tracker_score(item.get("score"))
        if score is None:
            continue
        history.append({
            "score": score,
            "at": str(item.get("at") or ""),
            "event": str(item.get("event") or "sync"),
        })
    return history[-8:]


def _append_tracker_history(history, score, timestamp, event):
    normalized = _normalize_tracker_history(history)
    safe_score = _normalize_tracker_score(score)
    if safe_score is None:
        return normalized
    if normalized and normalized[-1].get("score") == safe_score:
        return normalized
    normalized.append(
        {
            "score": safe_score,
            "at": str(timestamp or _career_tracker_now()),
            "event": str(event or "sync"),
        }
    )
    return normalized[-8:]


def _normalize_tracker_capability_payload(raw_items):
    payload = {}
    if not isinstance(raw_items, list):
        return payload
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        payload[key] = {
            "key": key,
            "label": str(item.get("label") or key).strip() or key,
            "score": _normalize_tracker_score(item.get("score")),
            "sources": [str(source).strip() for source in (item.get("sources") or []) if str(source).strip()],
        }
    return payload


def _build_career_report_tracker(bundle, existing_tracker=None, current_capabilities=None, version_summaries=None):
    if not isinstance(bundle, dict):
        return None

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_id = str(meta.get("report_id") or "").strip()
    if not report_id:
        return None

    existing = existing_tracker if isinstance(existing_tracker, dict) else {}
    if str(existing.get("report_id") or "") != report_id:
        existing = {}
    phase_plan = bundle.get("phase_plan") if isinstance(bundle.get("phase_plan"), dict) else {}
    profile_snapshot = bundle.get("profile_snapshot") if isinstance(bundle.get("profile_snapshot"), dict) else {}
    gap_map = bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}

    plan_state_map = {}
    for item in existing.get("plan_items") or []:
        if isinstance(item, dict) and item.get("id"):
            plan_state_map[str(item["id"])] = item

    checkpoint_state_map = {}
    for item in existing.get("checkpoints") or []:
        if isinstance(item, dict) and item.get("id"):
            checkpoint_state_map[str(item["id"])] = item

    ability_state_map = {}
    for item in existing.get("ability_growth") or []:
        if isinstance(item, dict) and item.get("key"):
            ability_state_map[str(item["key"])] = item

    generated_at = str(meta.get("generated_at") or existing.get("generated_at") or "")
    current_sync_time = _career_tracker_now()
    capability_payload = _normalize_tracker_capability_payload(current_capabilities)

    plan_items = []
    raw_plan_items = []
    for bucket, phase_key in (("short_term", "short"), ("mid_term", "mid"), ("long_term", "long")):
        raw_plan_items.extend({**item, "phase_key": phase_key} for item in (phase_plan.get(bucket) or []) if isinstance(item, dict))
    for index, item in enumerate(raw_plan_items):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"plan-{index + 1}").strip() or f"plan-{index + 1}"
        previous = plan_state_map.get(item_id, {})
        status = _normalize_tracker_status(previous.get("status"), allow_doing=True)
        started_at = str(previous.get("started_at") or "")
        completed_at = str(previous.get("completed_at") or "") if status == "done" else ""
        if status == "doing" and not started_at:
            started_at = current_sync_time
        if status == "done" and not completed_at:
            completed_at = current_sync_time
        plan_items.append(
            {
                "id": item_id,
                "phase": str(item.get("phase") or ""),
                "title": str(item.get("title") or "阶段任务"),
                "objective": str(item.get("objective") or ""),
                "focus_points": [str(point).strip() for point in (item.get("focus_points") or []) if str(point).strip()],
                "signals": [str(signal).strip() for signal in (item.get("signals") or []) if str(signal).strip()],
                "status": status,
                "started_at": started_at if status in {"doing", "done"} else "",
                "completed_at": completed_at,
                "note": str(previous.get("note") or ""),
                "updated_at": str(previous.get("updated_at") or ""),
                "is_phase": True,
                "phase_key": item.get("phase_key", "short"),
                "is_action": bool(item.get("is_action") or (item.get("task_id") and item.get("deliverable"))),
                "is_roadmap": bool(item.get("is_roadmap")),
                "deliverable": str(item.get("deliverable") or ""),
                "acceptance_criteria": str(item.get("acceptance_criteria") or ""),
                "deadline": str(item.get("due_date") or ""),
                "hours": item.get("hours"), "cost": item.get("cost"),
                "depends_on": item.get("depends_on") or [],
                "week": item.get("week"), "requirement": item.get("requirement") or "",
                "entry_conditions": item.get("entry_conditions") or "",
            }
        )
        # Also expand nested task items into top-level plan items
        for task in (item.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            task_text = str(task.get("text") or "").strip()
            if not task_id or not task_text:
                continue
            prev_task = plan_state_map.get(task_id, {})
            task_status = _normalize_tracker_status(prev_task.get("status"), allow_doing=False)
            task_completed = str(prev_task.get("completed_at") or "") if task_status == "done" else ""
            plan_items.append(
                {
                    "id": task_id,
                    "phase": str(item.get("phase") or ""),
                    "title": task_text,
                    "objective": task_text,
                    "focus_points": [],
                    "signals": [],
                    "parent_phase": item_id,
                    "status": task_status,
                    "started_at": "",
                    "completed_at": task_completed,
                    "note": str(prev_task.get("note") or ""),
                    "updated_at": str(prev_task.get("updated_at") or ""),
                    "is_task": True,
                    "phase_key": item.get("phase_key", "short"),
                    "deliverable": str(task.get("deliverable") or ""),
                    "acceptance_criteria": str(task.get("acceptance_criteria") or ""),
                    "requirement": task.get("requirement") or "",
                    "conditional": bool(task.get("conditional")),
                }
            )

    checkpoints = []
    for index, item in enumerate(phase_plan.get("checkpoints") or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or f"检查点 {index + 1}").strip() or f"检查点 {index + 1}"
        checkpoint_id = str(item.get("id") or f"checkpoint-{_slugify_tracker_id(label)}")
        previous = checkpoint_state_map.get(checkpoint_id, {})
        status = _normalize_tracker_status(previous.get("status"), allow_doing=False)
        completed_at = str(previous.get("completed_at") or "") if status == "done" else ""
        checkpoints.append(
            {
                "id": checkpoint_id,
                "label": label,
                "summary": str(item.get("summary") or ""),
                "due_date": str(item.get("due_date") or ""),
                "status": status,
                "completed_at": completed_at,
                "note": str(previous.get("note") or ""),
                "updated_at": str(previous.get("updated_at") or ""),
            }
        )

    baseline_map = {}
    for item in profile_snapshot.get("capability_vector") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        baseline_map[key] = {
            "key": key,
            "label": str(item.get("label") or key).strip() or key,
            "score": _normalize_tracker_score(item.get("score")),
            "sources": [str(source).strip() for source in (item.get("sources") or []) if str(source).strip()],
        }

    for key, item in capability_payload.items():
        if key not in baseline_map:
            baseline_map[key] = {
                "key": key,
                "label": item.get("label") or key,
                "score": None,
                "sources": [],
            }

    ability_growth = []
    for key, baseline in baseline_map.items():
        previous = ability_state_map.get(key, {})
        baseline_score = _normalize_tracker_score(baseline.get("score"))
        current_score = None
        if key in capability_payload:
            current_score = _normalize_tracker_score(capability_payload[key].get("score"))
        if current_score is None:
            current_score = _normalize_tracker_score(previous.get("current_score"))
        if current_score is None:
            current_score = baseline_score
        delta = None
        if baseline_score is not None and current_score is not None:
            delta = int(current_score - baseline_score)
        history = _normalize_tracker_history(previous.get("history"))
        if not history and baseline_score is not None:
            history = _append_tracker_history(history, baseline_score, generated_at or current_sync_time, "baseline")
        if current_capabilities is not None:
            history = _append_tracker_history(history, current_score, current_sync_time, "profile_sync")
        ability_growth.append(
            {
                "key": key,
                "label": str(baseline.get("label") or previous.get("label") or key),
                "baseline_score": baseline_score,
                "current_score": current_score,
                "delta": delta,
                "baseline_sources": baseline.get("sources") or [],
                "current_sources": capability_payload.get(key, {}).get("sources") or previous.get("current_sources") or baseline.get("sources") or [],
                "history": history,
            }
        )

    # Use task items for progress calculation (more granular); fall back to phase items
    parents_with_tasks = {item.get("parent_phase") for item in plan_items if item.get("is_task")}
    trackable = [item for item in plan_items if item.get("is_task") or item.get("is_action")
                 or (item.get("is_phase") and item["id"] not in parents_with_tasks and not item.get("is_roadmap"))]
    done_count = sum(1 for item in trackable if item.get("status") == "done") + sum(1 for item in checkpoints if item.get("status") == "done")
    doing_count = sum(1 for item in trackable if item.get("status") == "doing")
    total_count = len(trackable) + len(checkpoints)
    weighted_progress = (
        sum(1 for item in trackable if item.get("status") == "done")
        + sum(0.5 for item in trackable if item.get("status") == "doing")
        + sum(1 for item in checkpoints if item.get("status") == "done")
    )
    completion_rate = int(round(weighted_progress / total_count * 100)) if total_count else 0

    improved_count = sum(1 for item in ability_growth if isinstance(item.get("delta"), int) and item.get("delta") > 0)
    declined_count = sum(1 for item in ability_growth if isinstance(item.get("delta"), int) and item.get("delta") < 0)
    stable_count = sum(1 for item in ability_growth if item.get("delta") in {0, None})

    focus_role_name = (
        str(gap_map.get("focus_role_name") or "")
        or str(document.get("focus_role_name") or "")
        or str(meta.get("focus_role_name") or "")
        or "待识别方向"
    )
    focus_role_id = str(meta.get("focus_role_id") or existing.get("focus_role_id") or "")

    current_version = {
        "report_id": report_id,
        "title": str(meta.get("title") or document.get("title") or "职业规划报告"),
        "version": str(meta.get("version") or ""),
        "generated_at": generated_at,
        "focus_role_id": focus_role_id,
        "focus_role_name": focus_role_name,
    }
    versions = []
    versions.append(current_version)
    for item in existing.get("versions") or []:
        if not isinstance(item, dict):
            continue
        item_report_id = str(item.get("report_id") or "")
        if item_report_id and item_report_id == report_id:
            continue
        versions.append(
            {
                "report_id": item_report_id,
                "title": str(item.get("title") or "职业规划报告"),
                "version": str(item.get("version") or ""),
                "generated_at": str(item.get("generated_at") or ""),
                "focus_role_id": str(item.get("focus_role_id") or ""),
                "focus_role_name": str(item.get("focus_role_name") or ""),
            }
        )
    versions = versions[:6]

    next_focus = next((item.get("title") for item in trackable if item.get("status") != "done"), "")
    if not next_focus:
        next_focus = next((item.get("label") for item in checkpoints if item.get("status") != "done"), "")

    return {
        "report_id": report_id,
        "report_title": str(meta.get("title") or document.get("title") or "职业规划报告"),
        "report_version": str(meta.get("version") or ""),
        "focus_role_id": focus_role_id,
        "focus_role_name": focus_role_name,
        "generated_at": generated_at,
        "last_synced_at": current_sync_time if current_capabilities is not None else str(existing.get("last_synced_at") or generated_at),
        "completion_rate": completion_rate,
        "completed_count": done_count,
        "doing_count": doing_count,
        "total_count": total_count,
        "next_focus": str(next_focus or ""),
        "ability_summary": {
            "improved_count": improved_count,
            "declined_count": declined_count,
            "stable_count": stable_count,
        },
        "plan_items": plan_items,
        "checkpoints": checkpoints,
        "ability_growth": ability_growth,
        "versions": versions,
        "action_checklists": phase_plan.get("action_checklists") if isinstance(phase_plan.get("action_checklists"), dict) else {},
    }


def _sync_career_report_tracker_state(username, bundle, current_capabilities=None):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    tracker = _build_career_report_tracker(bundle, report_state.get("tracker"), current_capabilities)
    if isinstance(tracker, dict):
        tracker["versions"] = _list_career_report_version_summaries(username)[:6]
    meta = bundle.get("meta") if isinstance(bundle, dict) and isinstance(bundle.get("meta"), dict) else {}

    if meta and str(report_state.get("status") or "") not in {"running", "queued", "waiting_input", "failed"}:
        report_state.update(
            {
                "status": "ready",
                "report_id": str(meta.get("report_id") or report_state.get("report_id") or ""),
                "generated_at": str(meta.get("generated_at") or report_state.get("generated_at") or ""),
                "focus_role_id": str(meta.get("focus_role_id") or report_state.get("focus_role_id") or ""),
                "title": str(meta.get("title") or report_state.get("title") or ""),
                "summary": str(meta.get("summary") or report_state.get("summary") or ""),
                "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
            }
        )

    if tracker:
        report_state["tracker"] = tracker
        state["career_report"] = report_state
        _save_user_state(username, state)

    return state, report_state, tracker




def _update_career_report_job(job_id, **fields):
    with CAREER_REPORT_LOCK:
        job = CAREER_REPORT_JOBS.get(job_id)
        if not isinstance(job, dict):
            return
        job.update(fields)
        CAREER_REPORT_JOBS[job_id] = job


def _find_running_career_report_job(username):
    with CAREER_REPORT_LOCK:
        for job in CAREER_REPORT_JOBS.values():
            if (
                isinstance(job, dict)
                and str(job.get("username") or "") == str(username or "")
                and str(job.get("status") or "") in {"queued", "running"}
            ):
                return dict(job)
    return None


def _is_career_report_job_cancelled(job_id):
    with CAREER_REPORT_LOCK:
        job = CAREER_REPORT_JOBS.get(job_id)
        if not isinstance(job, dict):
            return False
        return bool(job.get("cancel_requested")) or str(job.get("status") or "") == "canceled"


def _save_career_report_progress(username, job_id, stage, stage_label, detail, **extra):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    with CAREER_REPORT_LOCK:
        live_job = CAREER_REPORT_JOBS.get(job_id)
        live_activity = dict(live_job.get("agent_activity") or {}) if live_job else report_state.get("agent_activity", {})
    report_state.update(
        {
            "status": extra.get("status") or "running",
            "job_id": job_id,
            "stage": stage,
            "stage_label": stage_label,
            "stage_detail": detail,
            "progress": build_stage_progress(stage),
            "agent_activity": dict(extra.get("agent_activity", live_activity)),
            "error_message": str(extra.get("error_message") or ""),
            "generated_at": str(extra.get("generated_at") or report_state.get("generated_at") or ""),
            "report_id": str(extra.get("report_id") or report_state.get("report_id") or ""),
            "model": str(extra.get("model") or report_state.get("model") or ""),
            "generation_mode": str(extra.get("generation_mode") or report_state.get("generation_mode") or ""),
            "focus_role_id": str(extra.get("focus_role_id") or report_state.get("focus_role_id") or ""),
            "title": str(extra.get("title") or report_state.get("title") or ""),
            "summary": str(extra.get("summary") or report_state.get("summary") or ""),
            "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
        }
    )
    state["career_report"] = report_state
    _save_user_state(username, state)




def _user_upload_dir(username):
    return _private_account_directory(RESUME_UPLOAD_DIR, username)


def _allowed_pdf(file_storage):
    filename = str(getattr(file_storage, "filename", "") or "")
    if not filename.lower().endswith(".pdf"):
        return False
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    current = stream.tell()
    head = stream.read(5)
    stream.seek(current)
    return bool(head.startswith(b"%PDF"))


def _allowed_resume_upload(file_storage):
    filename = str(getattr(file_storage, "filename", "") or "")
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in {".pdf", ".docx"}:
        return False
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    current = stream.tell()
    head = stream.read(8)
    stream.seek(current)
    if suffix == ".pdf":
        return bool(head.startswith(b"%PDF"))
    return bool(head.startswith(b"PK"))


def _save_resume_upload(file_storage, username):
    if not _allowed_resume_upload(file_storage):
        raise ValueError("仅支持 PDF 或 DOCX 简历文件上传。")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("上传文件为空。")
    if size > RESUME_MAX_FILE_SIZE:
        raise ValueError(f"简历文件过大，请控制在 {RESUME_MAX_FILE_SIZE // (1024 * 1024)}MB 内。")

    target_dir = _user_upload_dir(username)
    os.makedirs(target_dir, exist_ok=True)
    original_name = file_storage.filename or "resume.pdf"
    safe = secure_filename(original_name) or "resume.pdf"
    suffix = os.path.splitext(safe)[1].lower() or os.path.splitext(original_name)[1].lower()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError("仅支持 PDF 或 DOCX 简历文件上传。")
    if not safe.lower().endswith(suffix):
        safe += suffix
    saved_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}_{safe}"
    target_path = os.path.join(target_dir, saved_name)
    file_storage.save(target_path)
    return target_path, saved_name, size, suffix.lstrip(".")


def _save_resume_pdf(file_storage, username):
    if not _allowed_pdf(file_storage):
        raise ValueError("仅支持 PDF 文件上传。")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("上传文件为空。")
    if size > RESUME_MAX_FILE_SIZE:
        raise ValueError(f"PDF 文件过大，请控制在 {RESUME_MAX_FILE_SIZE // (1024 * 1024)}MB 内。")

    target_dir = _user_upload_dir(username)
    os.makedirs(target_dir, exist_ok=True)
    safe = secure_filename(file_storage.filename or "resume.pdf") or "resume.pdf"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    saved_name = f"{int(time.time())}_{safe}"
    target_path = os.path.join(target_dir, saved_name)
    file_storage.save(target_path)
    return target_path, saved_name, size


def _normalize_resume_text(raw_text):
    return re.sub(r"\s+", " ", str(raw_text or "")).strip()


def _resume_text_quality_score(raw_text):
    text = _normalize_resume_text(raw_text)
    if not text:
        return 0.0
    compact = re.sub(r"\s+", "", text)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    latin_count = len(re.findall(r"[A-Za-z]", compact))
    digit_count = len(re.findall(r"\d", compact))
    symbol_bonus = len(re.findall(r"[@:/.()%+\-]", compact))
    noise_penalty = len(re.findall(r"[=~`|_^<>*]", compact))
    return (
        len(compact) * 0.6
        + cjk_count * 1.8
        + latin_count * 0.25
        + digit_count * 0.2
        + symbol_bonus * 0.1
        - noise_penalty * 0.8
    )


def _resume_text_meaningful_ratio(raw_text):
    text = _normalize_resume_text(raw_text)
    if not text:
        return 0.0
    compact = re.sub(r"\s+", "", text)
    meaningful = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9@:/.()%+\-]", compact))
    return meaningful / max(len(compact), 1)


def _merge_resume_page_candidates(*candidate_groups):
    merged = {}
    for group in candidate_groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            page_no = int(item.get("page_no") or 0)
            if page_no <= 0:
                continue
            text = _normalize_resume_text(item.get("text") or item.get("content") or item.get("markdown") or "")
            if not text:
                continue
            score = _resume_text_quality_score(text)
            previous = merged.get(page_no)
            if previous is None or score > previous["score"]:
                merged[page_no] = {
                    "page_no": page_no,
                    "source": str(item.get("source") or "text"),
                    "text": text,
                    "score": score,
                }
    result = []
    for page_no in sorted(merged.keys())[:RESUME_MAX_PAGES]:
        payload = dict(merged[page_no])
        payload.pop("score", None)
        result.append(payload)
    return result


def _resolve_tesseract_executable():
    if pytesseract is None:
        return ""
    current = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or "").strip()
    candidates = [
        current,
        os.environ.get("TESSERACT_CMD", ""),
        "tesseract",
        r"D:\software\OCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _configure_tesseract_command():
    executable = _resolve_tesseract_executable()
    if executable and pytesseract is not None:
        pytesseract.pytesseract.tesseract_cmd = executable
    return executable


def _available_tesseract_languages():
    if pytesseract is None:
        return []
    _configure_tesseract_command()
    try:
        return [str(item or "").strip() for item in pytesseract.get_languages(config="") if str(item or "").strip()]
    except Exception as exc:
        logger.warning("无法读取 Tesseract 语言列表：%s", type(exc).__name__)
        return []


def _resolve_resume_ocr_lang():
    langs = {item.lower() for item in _available_tesseract_languages()}
    if {"chi_sim", "eng"}.issubset(langs):
        return "chi_sim+eng"
    if "chi_sim" in langs:
        return "chi_sim"
    if "eng" in langs:
        return "eng"
    return ""


def _prepare_resume_ocr_image(image):
    if image is None or Image is None:
        return image
    prepared = image.convert("L")
    if ImageOps is not None:
        prepared = ImageOps.autocontrast(prepared)
    if ImageFilter is not None:
        prepared = prepared.filter(ImageFilter.MedianFilter(size=3))
    return prepared


def _run_resume_ocr(image, lang):
    if pytesseract is None or image is None or not lang:
        return ""
    _configure_tesseract_command()
    primary_text = ""
    try:
        primary_text = pytesseract.image_to_string(image, lang=lang, config="--oem 3 --psm 6")
    except Exception as exc:
        logger.warning("OCR 首次识别失败：%s", type(exc).__name__)
        primary_text = ""
    primary_score = _resume_text_quality_score(primary_text)
    if primary_score >= 900:
        return _normalize_resume_text(primary_text)

    prepared_image = _prepare_resume_ocr_image(image)
    if prepared_image is image:
        return _normalize_resume_text(primary_text)

    try:
        fallback_text = pytesseract.image_to_string(prepared_image, lang=lang, config="--oem 3 --psm 6")
    except Exception as exc:
        logger.warning("OCR 预处理后识别失败：%s", type(exc).__name__)
        fallback_text = ""

    if _resume_text_quality_score(fallback_text) > primary_score:
        return _normalize_resume_text(fallback_text)
    return _normalize_resume_text(primary_text)


def _extract_pdf_text_pages(pdf_path):
    pypdf_pages = []
    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            for idx, page in enumerate(reader.pages[:RESUME_MAX_PAGES], start=1):
                text = _normalize_resume_text(page.extract_text() or "")
                if text:
                    pypdf_pages.append({"page_no": idx, "source": "pypdf", "text": text})
        except Exception as exc:
            logger.warning("pypdf 读取简历失败，改用其他引擎：%s", type(exc).__name__)

    plumber_pages = []
    if pdfplumber is not None:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for idx, page in enumerate(pdf.pages[:RESUME_MAX_PAGES], start=1):
                    variants = []
                    for kwargs in ({}, {"layout": True}):
                        try:
                            variants.append(page.extract_text(**kwargs) or "")
                        except TypeError:
                            variants.append(page.extract_text() or "")
                        except Exception as exc:
                            logger.debug("pdfplumber 页面解析失败：%s", type(exc).__name__)
                            continue
                    text = max(variants, key=_resume_text_quality_score, default="")
                    text = _normalize_resume_text(text)
                    if text:
                        plumber_pages.append({"page_no": idx, "source": "pdfplumber", "text": text})
        except Exception as exc:
            logger.warning("pdfplumber 读取简历失败，改用其他引擎：%s", type(exc).__name__)

    pymupdf_pages = []
    if fitz is not None:
        try:
            with fitz.open(pdf_path) as doc:
                for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                    text = _normalize_resume_text(doc[idx].get_text("text") or "")
                    if text:
                        pymupdf_pages.append({"page_no": idx + 1, "source": "pymupdf", "text": text})
        except Exception as exc:
            logger.warning("PyMuPDF 读取简历失败：%s", type(exc).__name__)

    return _merge_resume_page_candidates(pypdf_pages, plumber_pages, pymupdf_pages)


def _should_fallback_ocr(text_pages, *_):
    if not text_pages:
        return True
    total_chars = 0
    meaningful_chars = 0
    for item in text_pages:
        if isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("markdown") or ""
        else:
            text = item
        normalized = _normalize_resume_text(text)
        compact = re.sub(r"\s+", "", normalized)
        total_chars += len(compact)
        meaningful_chars += len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9@:/.()%+\-]", compact))
    meaningful_ratio = meaningful_chars / max(total_chars, 1)
    return total_chars < 240 or meaningful_ratio < 0.42


def _ocr_pdf_pages(pdf_path):
    if fitz is None or pytesseract is None or Image is None:
        return []
    ocr_lang = _resolve_resume_ocr_lang()
    if not ocr_lang:
        return []

    start_at = time.monotonic()
    pages = []
    try:
        with fitz.open(pdf_path) as doc:
            for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                if time.monotonic() - start_at > RESUME_OCR_TIMEOUT_SECONDS:
                    break
                pix = doc[idx].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = _run_resume_ocr(image, ocr_lang)
                if text:
                    pages.append({"page_no": idx + 1, "source": f"ocr:{ocr_lang}", "text": text})
    except Exception as exc:
        logger.warning("扫描件 OCR 中断，返回已识别的 %d 页：%s", len(pages), type(exc).__name__)
        return pages
    return pages


def _resume_text_bundle(text_pages):
    chunks = []
    for item in text_pages[:RESUME_MAX_PAGES]:
        content = str(item.get("text") or "").strip()
        if not content:
            continue
        chunks.append(f"[第{item.get('page_no')}页/{item.get('source')}]\n{content}")
    joined = "\n\n".join(chunks)
    return joined[:RESUME_MAX_TEXT_CHARS]


def _infer_resume_basics_from_text(text):
    compact = re.sub(r"\s+", " ", str(text or ""))
    basics = {
        "major": "",
        "education_level": "",
        "target_city": "",
        "target_direction": "",
    }
    if re.search(r"博士|phd", compact, re.IGNORECASE):
        basics["education_level"] = "博士"
    elif re.search(r"硕士|研究生|master", compact, re.IGNORECASE):
        basics["education_level"] = "硕士"
    elif re.search(r"本科|学士|bachelor", compact, re.IGNORECASE):
        basics["education_level"] = "本科"
    elif re.search(r"大专|专科|college diploma", compact, re.IGNORECASE):
        basics["education_level"] = "大专"

    major_match = re.search(r"(?:专业|主修)\s*[:：]?\s*([^\n，。；;]{2,30})", compact, re.IGNORECASE)
    if major_match:
        basics["major"] = str(major_match.group(1) or "").strip()

    city_match = re.search(r"(?:意向城市|求职意向|期望城市)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if city_match:
        basics["target_city"] = str(city_match.group(1) or "").strip()

    direction_match = re.search(r"(?:目标方向|意向岗位|求职方向|目标岗位)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if direction_match:
        basics["target_direction"] = str(direction_match.group(1) or "").strip()
    return basics


def _build_resume_extract_prompt():
    return "\n".join(
        [
            "你是中文简历结构化助手。请严格基于输入简历输出 JSON，不要输出任何额外说明。",
            "输出结构需包含 candidate_summary、basics（至少包含 major、education_level、target_city、target_direction、gender）、roles_detected、leadership_signals、project_highlights、skills、capability_scores、evidence_spans、confidence。",
            "- 严禁编造。",
            "- 缺失字段使用 unknown、空字符串或空数组。",
            "- 所有分数范围为 0-100，confidence 范围为 0-1。",
            "- 输出必须是 JSON 对象本身。",
        ]
    )


def _normalize_resume_profile(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    basics = payload.get("basics") if isinstance(payload.get("basics"), dict) else {}
    capability_scores = payload.get("capability_scores") if isinstance(payload.get("capability_scores"), dict) else {}
    return {
        "candidate_summary": str(payload.get("candidate_summary") or "unknown").strip() or "unknown",
        "basics": {
            "gender": str(basics.get("gender") or basics.get("sex") or "").strip(),
            "major": str(basics.get("major") or "").strip(),
            "education_level": str(basics.get("education_level") or basics.get("grade") or "").strip(),
            "target_city": str(basics.get("target_city") or basics.get("targetCity") or "").strip(),
            "target_direction": str(basics.get("target_direction") or basics.get("targetDirection") or "").strip(),
        },
        "roles_detected": payload.get("roles_detected") if isinstance(payload.get("roles_detected"), list) else [],
        "leadership_signals": payload.get("leadership_signals") if isinstance(payload.get("leadership_signals"), list) else [],
        "competition_records": payload.get("competition_records") if isinstance(payload.get("competition_records"), list) else [],
        "project_highlights": payload.get("project_highlights") if isinstance(payload.get("project_highlights"), list) else [],
        "skills": payload.get("skills") if isinstance(payload.get("skills"), list) else [],
        "evidence_spans": payload.get("evidence_spans") if isinstance(payload.get("evidence_spans"), list) else [],
        "capability_scores": {
            "communication": int(float(capability_scores.get("communication") or 0)),
            "execution": int(float(capability_scores.get("execution") or 0)),
            "stress_resilience": int(float(capability_scores.get("stress_resilience") or 0)),
            "innovation": int(float(capability_scores.get("innovation") or 0)),
            "collaboration": int(float(capability_scores.get("collaboration") or 0)),
            "leadership": int(float(capability_scores.get("leadership") or 0)),
        },
        "confidence": max(0.0, min(1.0, float(payload.get("confidence") or 0))),
    }


def _extract_resume_profile(pdf_path, progress_callback=None, runtime_llm=None):
    raise RuntimeError("Legacy resume profile extractor is disabled. Use matcher pipeline instead.")


RESUME_HIGHLIGHT_DECK_SYSTEM = """
你是**资深职业规划顾问 + 技术招聘负责人视角**的合体：对用户温暖清晰，对岗位门槛判断冷静。
任务：只阅读下方「系统信号」与「简历分析报告节选」，输出**一层**可被用户 10 秒内读完的 JSON，用于产品首屏；**禁止**输出 Markdown、代码块、注释或任何 JSON 外文字。

# 输出目标（必须满足）
- 用户应能直接回答：**我最强在哪、最大风险在哪、下一步改哪三处**；有 JD 时还应回答**现在投是否划算**。
- **信息密度高**：每句话都要有判断或证据，不写正确的废话（如「建议优化简历」而不说改什么）。
- **禁止**：堆砌字段名（如「structured_resume」「关键词」）；复述系统 JSON；空泛形容词（「较强」「不错」「丰富」若无证据支撑须改写为可核对表述）。
- **称呼**：`candidate_summary` 里若出现看似邮箱昵称的英文片段（如短串、全小写），**不要**照抄为句首称呼；可改为「你的简历…」或直接以判断起句，避免「Sime，已提取…」这类观感。

# 各字段细则

## core_conclusion（约 140～420 字，中文）
- **结构**：第 1～2 句给**总判断**；随后用「因为…」串起 **1～2 条**最关键依据（经历/项目/成果/匹配度），**不要**平均铺开报告里所有小节。
- **resume_review（无 JD）**：写清三件事的压缩版——**更像哪类候选人**、**主线是否集中**、**当前最大成长瓶颈**；可自然提到 1～2 个建议探索方向，但不要写成岗位承诺。
- **job_match（有 JD）**：**首句必须是投递态度**（用自然中文，例如「与目标岗位相比，当前简历属于…」），第二句起再写与**岗位核心门槛**（硬技能/年限/场景/成果类型）的关系；若报告认为有关键硬伤，必须在结论里点出**一个**最致命的，而不是罗列。

## identity_tag（≤20 字，可空字符串）
- 一句**画像标签**，像给人起外号但要专业：例如「工程实践驱动型」「项目强但叙事散」「转岗中·需对齐 JD 话术」。勿与 core_conclusion 完全重复。

## highlight_evidence（**最多 2 条**）
- 每条：`headline` = **可识别的经历锚点**（公司/项目名/角色，≤24 字）；`why` = **为何这条能支撑你的判断**（尽量含**可核对要素**：技术栈/职责/结果形态，避免纯形容词）。
- 若材料不足，宁可 **1 条写深**，也不要 2 条空洞。

## key_risks（**最多 3 条**）
- 按**杀伤力**排序：优先写会导致 **简历筛不过 / 面试一追就穿 / 与 JD 核心场景不符** 的问题。
- 每条一句，开头可用「风险：」或直接陈述；**不要**把「错别字」「格式」与「无岗位相关成果」并列——永远先写后者。

## next_actions（**最多 3 条**）
- **必须**以动词开头（「把…」「删掉…」「在…下补一行…」）。
- 每条指向**简历上可改的一处具体位置或一类表述**，避免「提升表达能力」「多学习」等不可执行句。
- 有 JD 时，至少 **1 条**应显式对齐 **missing_keywords 或岗位硬性要求**（用自然语言，不要机械堆词）。

## substitution_opportunities（**0～2 条**，数组）
- 仅当你判断：**能力/经历可能存在，但简历用语与岗位话术未对齐** 时填写；写清「可以把哪类经历改写成岗位听得懂的一句话」。
- 若不存在或不确定，输出 **[]**。

## apply_verdict 与 apply_verdict_label（仅 job_match 有意义）
- `not_applicable`：analysis_mode 为 resume_review 时**必须**使用；此时 `apply_verdict_label` 为 **空字符串**。
- `direct_ok`：核心门槛基本满足，缺的是**表达或锦上添花**，投递**可尝试**（仍可能有面试风险）。
- `revise_first`：**有明显缺口或证据不足**，但**改简历 1～2 轮**后值得投。
- `risky`：**硬门槛差太远**或**证据链断裂**，强投性价比低；用户应先换目标或补经历再投。
- `apply_verdict_label`：≤12 字中文，与 verdict 一致，例如「可尝试投递」「建议改后再投」「暂不建议硬投」。

# JSON Schema（键名与层级必须完全一致）
{
  "core_conclusion": "string",
  "identity_tag": "string",
  "highlight_evidence": [{"headline": "string", "why": "string"}],
  "key_risks": ["string"],
  "next_actions": ["string"],
  "substitution_opportunities": ["string"],
  "apply_verdict": "not_applicable|direct_ok|revise_first|risky",
  "apply_verdict_label": "string"
}
""".strip()


def _normalize_resume_highlight_deck(raw, profile, matcher, analysis_mode):
    fb = build_fallback_resume_highlight_deck(profile, matcher, analysis_mode)
    if not isinstance(raw, dict):
        return fb
    out = dict(fb)
    cc = str(raw.get("core_conclusion") or "").strip()
    if len(cc) >= 40:
        out["core_conclusion"] = cc[:900]
    it = str(raw.get("identity_tag") or "").strip()
    if it:
        out["identity_tag"] = it[:48]
    he = raw.get("highlight_evidence")
    cleaned_he = []
    if isinstance(he, list):
        for item in he[:2]:
            if not isinstance(item, dict):
                continue
            hl = str(item.get("headline") or item.get("title") or "").strip()
            why = str(item.get("why") or item.get("reason") or "").strip()
            if hl or why:
                cleaned_he.append({"headline": (hl or "亮点证据")[:120], "why": (why or hl)[:420]})
    if cleaned_he:
        out["highlight_evidence"] = cleaned_he
    kr = raw.get("key_risks")
    if isinstance(kr, list):
        kr2 = [str(x).strip() for x in kr if str(x).strip()][:3]
        if kr2:
            out["key_risks"] = kr2
    na = raw.get("next_actions")
    if isinstance(na, list):
        na2 = [str(x).strip() for x in na if str(x).strip()][:3]
        if na2:
            out["next_actions"] = na2
    so = raw.get("substitution_opportunities")
    if isinstance(so, list):
        so2 = [str(x).strip() for x in so if str(x).strip()][:2]
        if so2:
            out["substitution_opportunities"] = so2
    av = str(raw.get("apply_verdict") or "").strip()
    if av in {"not_applicable", "direct_ok", "revise_first", "risky"}:
        out["apply_verdict"] = av
    if analysis_mode == "resume_review":
        out["apply_verdict"] = "not_applicable"
        out["apply_verdict_label"] = ""
    lbl = str(raw.get("apply_verdict_label") or "").strip()
    if lbl and analysis_mode == "job_match":
        out["apply_verdict_label"] = lbl[:32]
    return out


def _extract_resume_highlight_deck_llm(base_url, api_key, model, matcher_state, analysis_mode):
    profile = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else {}
    matcher = matcher_state.get("matcher") if isinstance(matcher_state.get("matcher"), dict) else {}
    resume_ov = matcher.get("resume_overview") if isinstance(matcher.get("resume_overview"), dict) else {}
    caps = profile.get("capability_scores") if isinstance(profile.get("capability_scores"), dict) else {}
    cap_pairs = []
    if caps:
        try:
            ranked = sorted(
                ((str(k), int(float(v))) for k, v in caps.items() if str(k) != "matching"),
                key=lambda x: -x[1],
            )[:3]
            cap_pairs = [{"dimension": k, "score": v} for k, v in ranked]
        except (TypeError, ValueError):
            cap_pairs = []

    structured_job = matcher_state.get("structured_job") if isinstance(matcher_state.get("structured_job"), dict) else {}
    job_qual = structured_job.get("qualifications") if isinstance(structured_job.get("qualifications"), dict) else {}
    company_profile = structured_job.get("company_profile") if isinstance(structured_job.get("company_profile"), dict) else {}

    signals = {
        "analysis_mode": analysis_mode,
        "candidate_summary": str(profile.get("candidate_summary") or "")[:900],
        "roles_detected": [
            str(r.get("role") or "").strip()
            for r in (profile.get("roles_detected") or [])
            if isinstance(r, dict) and str(r.get("role") or "").strip()
        ][:8],
        "uncertainty_items": [
            {"item": str(u.get("item") or "").strip(), "reason": str(u.get("reason") or "").strip()[:200]}
            for u in (profile.get("uncertainty_layer") or [])
            if isinstance(u, dict) and str(u.get("item") or "").strip()
        ][:6],
        "capability_top": cap_pairs,
        "resume_experience_count": resume_ov.get("experience_count"),
        "resume_project_count": resume_ov.get("project_count"),
        "resume_skill_count": resume_ov.get("skill_count"),
        "matched_keywords": (matcher.get("matched_keywords") or [])[:22],
        "missing_keywords": (matcher.get("missing_keywords") or [])[:22],
        "job_title": (matcher.get("job_overview") or {}).get("job_title") or "",
        "job_company": str(company_profile.get("company_name") or "").strip()[:80],
        "job_summary_snippet": str(structured_job.get("job_summary") or "").strip()[:420],
        "job_required_snippets": [str(x).strip() for x in (job_qual.get("required") or []) if str(x).strip()][:8],
        "job_preferred_snippets": [str(x).strip() for x in (job_qual.get("preferred") or []) if str(x).strip()][:6],
        "recommended_directions": (matcher.get("recommended_directions") or [])[:8],
    }
    excerpt = str(matcher_state.get("analysis_result") or "")[:16000]
    user_body = (
        "请仅输出一个合法 JSON 对象，键名必须与 system 中的 Schema 完全一致，不要输出 ``` 代码围栏。\n\n"
        "【系统已提取信号（JSON）】\n"
        + json.dumps(signals, ensure_ascii=False)
        + "\n\n【简历分析报告节选】\n"
        + excerpt
    )
    return call_structured_chat(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": user_body}],
        system_prompt=RESUME_HIGHLIGHT_DECK_SYSTEM,
        max_tokens=2800,
    )


def _analyze_resume_matcher(storage_path, job_description, progress_callback=None, runtime_llm=None):
    def _report(stage, detail):
        if callable(progress_callback):
            try:
                progress_callback(stage, detail)
            except Exception as exc:
                logger.warning("简历分析进度回调失败：%s", type(exc).__name__)

    job_text = str(job_description or "").strip()
    analysis_mode = "job_match" if job_text else "resume_review"

    _report("extract_resume", "正在提取简历文本")
    text_payload = build_resume_text_payload(
        storage_path,
        extract_pdf_text_pages=_extract_pdf_text_pages,
        should_fallback_ocr=_should_fallback_ocr,
        ocr_pdf_pages=_ocr_pdf_pages,
        max_pages=RESUME_MAX_PAGES,
        max_chars=RESUME_MAX_TEXT_CHARS,
    )
    resume_text = str(text_payload.get("plain_text") or "").strip()
    if not resume_text:
        raise ValueError("未能从简历中提取到有效文本，请检查文件内容。")

    if isinstance(runtime_llm, (tuple, list)) and len(runtime_llm) >= 3:
        base_url = str(runtime_llm[0] or "").strip()
        api_key = str(runtime_llm[1] or "").strip()
        model = str(runtime_llm[2] or "").strip()
    else:
        base_url, api_key, model = _get_resume_provider_and_model()
    if not base_url or not api_key:
        raise ValueError("模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。")
    if not model:
        model = "gpt-4o-mini"

    _report("structured_resume", "正在提取结构化简历")
    resume_schema_json = json.dumps(STRUCTURED_RESUME_SCHEMA, ensure_ascii=False, indent=2)
    structured_resume = call_structured_chat(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": "请仅输出符合 schema 的 JSON。"}],
        system_prompt=STRUCTURED_RESUME_PROMPT.format(resume_schema_json, resume_text),
        max_tokens=2600,
    )

    structured_job = {}
    if analysis_mode == "job_match":
        _report("job_context", "正在理解岗位文本")
        structured_job = build_job_payload_from_text(job_text)
        _report("hr_judge", "正在生成岗位匹配分析（深度五步审计）")
        analysis_markdown = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": "请输出最终 Markdown 分析报告。"}],
            system_prompt=HR_JUDGE_PROMPT.format(
                datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                Job_Description=job_text,
                raw_resume=resume_text,
            ),
            max_tokens=6000,
        )
    else:
        _report("resume_review", "正在生成简历诊断")
        analysis_markdown = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": "请输出最终 Markdown 分析报告。"}],
            system_prompt=RESUME_REVIEW_PROMPT.format(
                datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                raw_resume=resume_text,
            ),
            max_tokens=3200,
        )

    matcher_state = build_matcher_state(
        structured_resume=structured_resume,
        structured_job=structured_job,
        analysis_markdown=analysis_markdown,
        job_description=job_text,
    )
    _report("highlight_deck", "正在提炼核心结论与亮点")
    try:
        raw_deck = _extract_resume_highlight_deck_llm(base_url, api_key, model, matcher_state, analysis_mode)
        matcher_state["resume_highlight_deck"] = _normalize_resume_highlight_deck(
            raw_deck,
            matcher_state.get("profile"),
            matcher_state.get("matcher"),
            analysis_mode,
        )
    except Exception as exc:
        app.logger.warning("resume highlight deck extraction failed: %s", exc)
        matcher_state["resume_highlight_deck"] = build_fallback_resume_highlight_deck(
            matcher_state.get("profile"),
            matcher_state.get("matcher"),
            analysis_mode,
        )

    _report("diagnosis_ui", "正在提炼深度审计结构化版面")
    try:
        profile_for_ui = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else {}
        basics_for_ui = profile_for_ui.get("basics") if isinstance(profile_for_ui.get("basics"), dict) else {}
        canonical_resume_name = str(basics_for_ui.get("name") or "").strip()
        cand_sum = str(profile_for_ui.get("candidate_summary") or "").strip()
        user_ui = build_diagnosis_ui_extract_prompt(
            matcher_state.get("analysis_result") or "",
            cand_sum,
            analysis_mode,
            candidate_legal_name=canonical_resume_name,
        )
        raw_diagnosis_ui = call_structured_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": user_ui}],
            system_prompt=DIAGNOSIS_UI_EXTRACT_SYSTEM,
            max_tokens=3800,
        )
        diagnosis_ui = normalize_diagnosis_ui(raw_diagnosis_ui, canonical_name=canonical_resume_name)
        if diagnosis_ui_non_empty(diagnosis_ui):
            matcher_state["matcher"]["diagnosis_ui"] = diagnosis_ui
    except Exception as exc:
        app.logger.warning("diagnosis_ui extract failed: %s", exc)

    analysis_meta = dict(text_payload.get("analysis_meta") or {})
    analysis_meta.update(
        {
            "parsed_at": int(time.time()),
            "job_description_length": len(job_text),
            "analysis_mode": analysis_mode,
            "model": model,
            "resume_keyword_count": len((matcher_state.get("matcher") or {}).get("resume_keywords") or []),
            "job_keyword_count": len((matcher_state.get("matcher") or {}).get("job_keywords") or []),
            "resume_text_char_count": len(resume_text),
        }
    )
    matcher_state["resume_source_text"] = resume_text
    matcher_state["resume_text_payload"] = text_payload
    return matcher_state, analysis_meta


def _public_resume_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    return {
        "file_name": state.get("file_name") or "",
        "original_file_name": state.get("original_file_name") or state.get("file_name") or "",
        "document_id": state.get("document_id") or "",
        "file_size": state.get("file_size") or 0,
        "file_type": state.get("file_type") or "",
        "uploaded_at": state.get("uploaded_at"),
        "analyzed_at": state.get("analyzed_at"),
        "status": state.get("status") or "empty",
        "analysis_meta": state.get("analysis_meta") or {},
        "profile": state.get("profile") if isinstance(state.get("profile"), dict) else None,
        "analysis_result": state.get("analysis_result") or "",
        "analysis_html": state.get("analysis_html") or "",
        "job_description": state.get("job_description") or "",
        "matcher": state.get("matcher") if isinstance(state.get("matcher"), dict) else {},
        "structured_resume": state.get("structured_resume") if isinstance(state.get("structured_resume"), dict) else None,
        "structured_job": state.get("structured_job") if isinstance(state.get("structured_job"), dict) else None,
        "resume_highlight_deck": state.get("resume_highlight_deck")
        if isinstance(state.get("resume_highlight_deck"), dict)
        else None,
        "resume_text_char_count": int(state.get("resume_text_char_count") or 0),
        "has_resume_source_text": bool(str(state.get("resume_source_text") or "").strip()),
        "error_message": state.get("error_message") or "",
    }


def _public_resume_job(raw_job):
    job = raw_job if isinstance(raw_job, dict) else {}
    return {
        "job_id": str(job.get("job_id") or "").strip(),
        "username": str(job.get("username") or "").strip(),
        "status": str(job.get("status") or "unknown"),
        "stage": str(job.get("stage") or ""),
        "stage_detail": str(job.get("stage_detail") or ""),
        "message": str(job.get("message") or ""),
        "created_at": int(job.get("created_at") or 0),
        "started_at": int(job.get("started_at") or 0),
        "finished_at": int(job.get("finished_at") or 0),
    }


def _update_resume_job(job_id, **fields):
    with RESUME_ANALYSIS_LOCK:
        job = RESUME_ANALYSIS_JOBS.get(job_id)
        if not isinstance(job, dict):
            return
        job.update(fields)
        RESUME_ANALYSIS_JOBS[job_id] = job


def _find_running_resume_job(username):
    with RESUME_ANALYSIS_LOCK:
        for job in RESUME_ANALYSIS_JOBS.values():
            if (
                isinstance(job, dict)
                and str(job.get("username") or "") == str(username or "")
                and str(job.get("status") or "") in {"queued", "running"}
            ):
                return dict(job)
    return None


def _save_resume_job_progress(username, job_id, stage, detail):
    state = _load_user_state(username)
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    resume_state["status"] = "analyzing"
    meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
    meta.update(
        {
            "running": True,
            "job_id": job_id,
            "stage": stage,
            "stage_detail": detail,
            "stage_updated_at": int(time.time()),
        }
    )
    resume_state["analysis_meta"] = meta
    state["resume_profile"] = resume_state
    _save_user_state(username, state)


def _run_resume_analysis_job(username, storage_path, job_id, runtime_llm, job_description):
    _update_resume_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="extract_resume",
        stage_detail="正在提取简历文本",
        message="",
    )

    def _on_progress(stage, detail):
        _update_resume_job(job_id, stage=stage, stage_detail=detail, message=detail)
        _save_resume_job_progress(username, job_id, stage, detail)

    try:
        storage_path = _owned_resume_storage_path(username, storage_path)
        if not storage_path:
            raise ValueError("简历文件不属于当前账号")
        matcher_state, analysis_meta = _analyze_resume_matcher(
            storage_path,
            job_description,
            progress_callback=_on_progress,
            runtime_llm=runtime_llm,
        )

        state = _load_user_state(username)
        resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
        resume_state["status"] = "analyzed"
        resume_state["analyzed_at"] = int(time.time())
        merged_meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
        merged_meta.update(analysis_meta)
        merged_meta.update(
            {
                "running": False,
                "job_id": job_id,
                "stage": "done",
                "stage_detail": "简历分析完成",
                "stage_updated_at": int(time.time()),
            }
        )
        resume_state["analysis_meta"] = merged_meta
        resume_state["profile"] = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else None
        resume_state["analysis_result"] = matcher_state.get("analysis_result") or ""
        resume_state["analysis_html"] = matcher_state.get("analysis_html") or ""
        resume_state["job_description"] = matcher_state.get("job_description") or str(job_description or "").strip()
        resume_state["matcher"] = matcher_state.get("matcher") if isinstance(matcher_state.get("matcher"), dict) else {}
        resume_state["structured_resume"] = matcher_state.get("structured_resume") if isinstance(matcher_state.get("structured_resume"), dict) else None
        resume_state["structured_job"] = matcher_state.get("structured_job") if isinstance(matcher_state.get("structured_job"), dict) else None
        resume_state["resume_source_text"] = str(matcher_state.get("resume_source_text") or "")
        resume_state["resume_text_char_count"] = int(len(str(matcher_state.get("resume_source_text") or "")))
        resume_state["resume_highlight_deck"] = (
            matcher_state.get("resume_highlight_deck")
            if isinstance(matcher_state.get("resume_highlight_deck"), dict)
            else None
        )
        resume_state["error_message"] = ""
        state["resume_profile"] = resume_state
        _save_user_state(username, state)
        _update_resume_job(
            job_id,
            status="success",
            stage="done",
            stage_detail="简历分析完成",
            message="简历分析已完成。",
            finished_at=int(time.time()),
        )
    except ValueError as exc:
        state = _load_user_state(username)
        resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
        resume_state["status"] = "failed"
        resume_state["error_message"] = str(exc)
        meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
        meta.update(
            {
                "running": False,
                "job_id": job_id,
                "stage": "failed",
                "stage_detail": str(exc),
                "stage_updated_at": int(time.time()),
            }
        )
        resume_state["analysis_meta"] = meta
        state["resume_profile"] = resume_state
        _save_user_state(username, state)
        _update_resume_job(
            job_id,
            status="failed",
            stage="failed",
            stage_detail=str(exc),
            message=str(exc),
            finished_at=int(time.time()),
        )
    except Exception as exc:
        app.logger.exception("resume async analyze failed")
        msg = f"简历匹配分析失败：{exc}"
        state = _load_user_state(username)
        resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
        resume_state["status"] = "failed"
        resume_state["error_message"] = msg
        meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
        meta.update(
            {
                "running": False,
                "job_id": job_id,
                "stage": "failed",
                "stage_detail": msg,
                "stage_updated_at": int(time.time()),
            }
        )
        resume_state["analysis_meta"] = meta
        state["resume_profile"] = resume_state
        _save_user_state(username, state)
        _update_resume_job(
            job_id,
            status="failed",
            stage="failed",
            stage_detail=msg,
            message=msg,
            finished_at=int(time.time()),
        )









































































# 页面与认证接口
@app.route("/")
@app.route("/main.html")
def index():
    user = _current_user()
    if not user:
        return render_template("login.html", initial_user=None)
    return render_template(
        "base.html",
        initial_user=_public_user(user),
        career_news=get_career_news_payload(),
    )


@app.route("/app_data/<path:filename>")
@_login_required
def app_data_asset(filename):
    safe_name = str(filename or "").strip()
    if not safe_name:
        return jsonify({"message": "文件不存在"}), 404
    normalized = os.path.normpath(safe_name).replace("\\", "/")
    username = _current_user()["username"]
    allowed_prefixes = (f"user_uploads/{os.path.basename(_user_upload_dir(username))}/",
                        f"career_reports/{os.path.basename(_career_report_user_dir(username))}/")
    if not normalized.startswith(allowed_prefixes):
        return jsonify({"message": "文件不存在"}), 404
    if normalized.startswith("../") or "/../" in normalized:
        return jsonify({"message": "非法路径"}), 400
    full_path = os.path.abspath(os.path.join(APP_DATA_DIR, normalized))
    app_data_root = os.path.abspath(APP_DATA_DIR)
    if not (full_path == app_data_root or full_path.startswith(app_data_root + os.sep)):
        return jsonify({"message": "非法路径"}), 400
    if not os.path.isfile(full_path):
        return jsonify({"message": "文件不存在"}), 404
    directory = os.path.dirname(full_path)
    name = os.path.basename(full_path)
    return send_from_directory(directory, name, conditional=True)
















@app.route("/api/auth/status")
def api_auth_status():
    user = _current_user()
    payload = {
        "authenticated": bool(user),
        "user": _public_user(user),
    }
    bootstrap_mode = str(request.args.get("bootstrap", "") or "").strip().lower() in {"1", "true", "yes"}
    if bootstrap_mode and user:
        state = _load_user_state(user["username"])
        resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
        career_report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
        career_report_bundle = _read_career_report_bundle(user["username"])
        career_report_state, career_report_state_changed = _sanitize_transient_career_report_state(
            user["username"],
            career_report_state,
            current_bundle=career_report_bundle,
        )
        if career_report_state_changed:
            state["career_report"] = career_report_state
            _save_user_state(user["username"], state)
        payload["llm"] = llm_env.status()
        payload["scoped_data"] = {
            "career_interview": state.get("career_interview"),
            "assessment_hub": state.get("assessment_hub"),
            "resume_profile": _public_resume_state(resume_state),
            "career_report": _public_career_report_state(career_report_state),
            "profile_portrait": public_profile_portrait_state(state.get("profile_portrait")),
            "account_avatar": state.get("account_avatar"),
            "profile_snapshot": state.get("profile_snapshot"),
            "career_matching": state.get("career_matching"),
            "news_context": state.get("news_context"),
        }
    return jsonify(payload)


@app.route("/api/llm-status")
@_login_required
def api_llm_status():
    """是否已配置模型以及模型名；不含任何密钥或接口地址。"""
    return jsonify(llm_env.status())


@app.route("/api/bootstrap")
def api_bootstrap():
    """Bootstrap current user, providers, and cached scoped data for the frontend."""
    user = _current_user()
    if not user:
        return jsonify({"authenticated": False, "user": None})

    state = _load_user_state(user["username"])
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    career_report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    career_report_bundle = _read_career_report_bundle(user["username"])
    career_report_state, career_report_state_changed = _sanitize_transient_career_report_state(
        user["username"],
        career_report_state,
        current_bundle=career_report_bundle,
    )
    if career_report_state_changed:
        state["career_report"] = career_report_state
        _save_user_state(user["username"], state)

    return jsonify({
        "authenticated": True,
        "user": _public_user(user),
        "llm": llm_env.status(),
        "scoped_data": {
            "career_interview": state.get("career_interview"),
            "assessment_hub": state.get("assessment_hub"),
            "resume_profile": _public_resume_state(resume_state),
            "career_report": _public_career_report_state(career_report_state),
            "profile_portrait": public_profile_portrait_state(state.get("profile_portrait")),
            "profile_snapshot": state.get("profile_snapshot"),
            "career_matching": state.get("career_matching"),
            "news_context": state.get("news_context"),
        },
    })










@app.route("/api/user-state/<scope>", methods=["GET", "PUT"])
@_login_required
def api_user_state(scope):
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in VALID_USER_STATE_SCOPES:
        return jsonify({"message": "未知的用户空间。"}), 404

    user = _current_user()
    state = _load_user_state(user["username"])
    if request.method == "GET":
        return jsonify({"scope": normalized_scope, "data": state.get(normalized_scope)})

    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    if data is not None and not isinstance(data, dict):
        return jsonify({"message": "用户空间数据必须是 JSON 对象。"}), 400
    if data is None:
        state.pop(normalized_scope, None)
    else:
        state[normalized_scope] = data
    _save_user_state(user["username"], state)
    return jsonify({"message": "用户空间已保存。", "scope": normalized_scope})





@app.route("/api/resume/upload", methods=["POST"])
@_login_required
def api_resume_upload():
    user = _current_user()
    if _find_running_resume_job(user["username"]) or _find_running_career_report_job(user["username"]):
        return jsonify({"message": "正在分析简历或生成报告，请等待任务结束后再更换简历。"}), 409
    file_storage = request.files.get("file")
    if file_storage is None:
        return jsonify({"message": "请上传 PDF 或 DOCX 简历文件（file 字段）。"}), 400

    try:
        saved_path, saved_name, file_size, file_type = _save_resume_upload(file_storage, user["username"])
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400

    state = _load_user_state(user["username"])
    prev = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    versions = state.get("resume_versions") if isinstance(state.get("resume_versions"), list) else []
    if prev.get("document_id") and not any(isinstance(item, dict) and item.get("document_id") == prev["document_id"] for item in versions):
        versions.append({key: prev.get(key) for key in ("document_id", "storage_path", "file_name", "original_file_name", "uploaded_at")})
    state["resume_versions"] = versions

    state["resume_profile"] = {
        "file_name": saved_name,
        "original_file_name": str(file_storage.filename or "resume").replace("\\", "/").rsplit("/", 1)[-1],
        "document_id": uuid.uuid4().hex,
        "file_size": file_size,
        "file_type": file_type,
        "storage_path": saved_path,
        "uploaded_at": int(time.time()),
        "analyzed_at": None,
        "status": "uploaded",
        "analysis_meta": {},
        "profile": None,
        "analysis_result": "",
        "analysis_html": "",
        "job_description": str(prev.get("job_description") or "").strip(),
        "matcher": {},
        "structured_resume": None,
        "structured_job": None,
        "resume_highlight_deck": None,
        "resume_source_text": "",
        "resume_text_char_count": 0,
        "error_message": "",
    }
    _save_user_state(user["username"], state)
    return jsonify({"message": "简历上传成功。", "data": _public_resume_state(state["resume_profile"])})


@app.route("/api/resume/analyze", methods=["POST"])
@_login_required
def api_resume_analyze():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    state = _load_user_state(user["username"])
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    storage_path = _owned_resume_storage_path(user["username"], str(resume_state.get("storage_path") or "").strip())
    if "job_description" in payload:
        job_description = str(payload.get("job_description") or "").strip()
    else:
        job_description = str(resume_state.get("job_description") or "").strip()
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"message": "未找到已上传简历，请先上传 PDF 或 DOCX。"}), 400

    try:
        matcher_state, analysis_meta = _analyze_resume_matcher(storage_path, job_description)
    except ValueError as exc:
        resume_state["status"] = "failed"
        resume_state["error_message"] = str(exc)
        resume_state["job_description"] = job_description
        state["resume_profile"] = resume_state
        _save_user_state(user["username"], state)
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("resume matcher analyze failed")
        resume_state["status"] = "failed"
        resume_state["error_message"] = f"简历匹配分析失败：{exc}"
        resume_state["job_description"] = job_description
        state["resume_profile"] = resume_state
        _save_user_state(user["username"], state)
        return jsonify({"message": "简历匹配分析失败，请稍后重试。"}), 502

    resume_state["status"] = "analyzed"
    resume_state["analyzed_at"] = int(time.time())
    resume_state["analysis_meta"] = analysis_meta
    resume_state["profile"] = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else None
    resume_state["analysis_result"] = matcher_state.get("analysis_result") or ""
    resume_state["analysis_html"] = matcher_state.get("analysis_html") or ""
    resume_state["job_description"] = matcher_state.get("job_description") or job_description
    resume_state["matcher"] = matcher_state.get("matcher") if isinstance(matcher_state.get("matcher"), dict) else {}
    resume_state["structured_resume"] = matcher_state.get("structured_resume") if isinstance(matcher_state.get("structured_resume"), dict) else None
    resume_state["structured_job"] = matcher_state.get("structured_job") if isinstance(matcher_state.get("structured_job"), dict) else None
    resume_state["resume_source_text"] = str(matcher_state.get("resume_source_text") or "")
    resume_state["resume_text_char_count"] = int(len(str(matcher_state.get("resume_source_text") or "")))
    resume_state["resume_highlight_deck"] = (
        matcher_state.get("resume_highlight_deck")
        if isinstance(matcher_state.get("resume_highlight_deck"), dict)
        else None
    )
    resume_state["error_message"] = ""
    state["resume_profile"] = resume_state
    _save_user_state(user["username"], state)
    return jsonify({"message": "简历分析完成。", "data": _public_resume_state(resume_state)})


@app.route("/api/resume/analyze/start", methods=["POST"])
@_login_required
def api_resume_analyze_start():
    user = _current_user()
    username = user["username"]
    payload = request.get_json(silent=True) or {}
    state = _load_user_state(username)
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    storage_path = _owned_resume_storage_path(user["username"], str(resume_state.get("storage_path") or "").strip())
    if "job_description" in payload:
        job_description = str(payload.get("job_description") or "").strip()
    else:
        job_description = str(resume_state.get("job_description") or "").strip()
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"message": "未找到已上传简历，请先上传 PDF 或 DOCX。"}), 400

    base_url, api_key, model = _get_resume_provider_and_model()
    if not base_url or not api_key:
        return jsonify({"message": "模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。"}), 400
    runtime_llm = (base_url, api_key, model or "gpt-4o-mini")

    running = _find_running_resume_job(username)
    if running:
        return jsonify(
            {
                "message": "已有简历分析任务正在运行中。",
                "job_id": str(running.get("job_id") or ""),
                "already_running": True,
            }
        )

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "username": username,
        "status": "queued",
        "stage": "queued",
        "stage_detail": "任务排队中",
        "message": "任务排队中",
        "created_at": int(time.time()),
        "started_at": 0,
        "finished_at": 0,
    }
    with RESUME_ANALYSIS_LOCK:
        RESUME_ANALYSIS_JOBS[job_id] = job

    resume_state["status"] = "analyzing"
    resume_state["profile"] = None
    resume_state["analysis_result"] = ""
    resume_state["analysis_html"] = ""
    resume_state["matcher"] = {}
    resume_state["structured_resume"] = None
    resume_state["structured_job"] = None
    resume_state["resume_highlight_deck"] = None
    resume_state["resume_source_text"] = ""
    resume_state["resume_text_char_count"] = 0
    resume_state["job_description"] = job_description
    meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
    meta.update(
        {
            "running": True,
            "job_id": job_id,
            "stage": "queued",
            "stage_detail": "任务排队中",
            "stage_updated_at": int(time.time()),
        }
    )
    resume_state["analysis_meta"] = meta
    resume_state["error_message"] = ""
    state["resume_profile"] = resume_state
    _save_user_state(username, state)

    thread = threading.Thread(
        target=_run_resume_analysis_job,
        args=(username, storage_path, job_id, runtime_llm, job_description),
        daemon=True,
        name=f"resume-analyze-{job_id[:8]}",
    )
    thread.start()

    return jsonify({"message": "分析任务已启动。", "job_id": job_id, "already_running": False})


@app.route("/api/resume/analyze/status", methods=["GET"])
@_login_required
def api_resume_analyze_status():
    user = _current_user()
    username = user["username"]
    job_id = str(request.args.get("job_id") or "").strip()

    selected = None
    with RESUME_ANALYSIS_LOCK:
        if job_id:
            candidate = RESUME_ANALYSIS_JOBS.get(job_id)
            if isinstance(candidate, dict) and str(candidate.get("username") or "") == username:
                selected = dict(candidate)
        else:
            jobs = [
                dict(item)
                for item in RESUME_ANALYSIS_JOBS.values()
                if isinstance(item, dict) and str(item.get("username") or "") == username
            ]
            jobs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            if jobs:
                selected = jobs[0]

    state = _load_user_state(username)
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    return jsonify({"job": _public_resume_job(selected), "resume": _public_resume_state(resume_state)})


@app.route("/api/resume/profile", methods=["GET", "DELETE"])
@_login_required
def api_resume_profile():
    user = _current_user()
    state = _load_user_state(user["username"])
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}

    if request.method == "GET":
        return jsonify({"data": _public_resume_state(resume_state)})

    versions = state.get("resume_versions") if isinstance(state.get("resume_versions"), list) else []
    for version in [resume_state, *versions]:
        if not isinstance(version, dict):
            continue
        storage_path = _owned_resume_storage_path(user["username"], str(version.get("storage_path") or "").strip())
        if storage_path and os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except OSError:
                pass
    state.pop("resume_profile", None)
    state.pop("resume_versions", None)
    _save_user_state(user["username"], state)
    app.extensions["chat_service"].documents.forget(user["username"])
    sync_career_sources(user["username"], state)
    return jsonify({"message": "简历与匹配分析结果已删除。"})


def _career_report_console_log(job_id, message, **fields):
    safe_fields = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        safe_fields.append(f"{key}={value}")
    suffix = f" | {' '.join(safe_fields)}" if safe_fields else ""
    print(f"[career-report][{job_id[:8]}] {datetime.now().strftime('%H:%M:%S')} {message}{suffix}", flush=True)




def _run_career_report_job(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm):
    stage_defs = {item["key"]: item["label"] for item in CAREER_REPORT_STAGE_DEFS}
    runtime_llm_payload = dict(runtime_llm or {}) if isinstance(runtime_llm, dict) else {}
    model_name = str(runtime_llm_payload.get("model") or "").strip()
    job_started = time.perf_counter()
    generation_mode = "langgraph"

    def _log(message, **fields):
        _career_report_console_log(job_id, message, **fields)

    generation_mode = "langgraph"
    model_name = str(runtime_llm_payload.get("model") or model_name)
    _log("后台任务开始", user=username, report_id=report_id, mode=generation_mode, model=model_name)

    def _ensure_not_cancelled():
        if _is_career_report_job_cancelled(job_id):
            raise CareerReportCanceled("职业报告生成已被用户取消。")

    runtime_llm_with_caller = dict(runtime_llm_payload)
    runtime_llm_with_caller["document_cache"] = app.extensions["chat_service"].documents
    _ensure_not_cancelled()
    _update_career_report_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="resume_analysis",
        stage_label=stage_defs.get("resume_analysis", "简历分析"),
        stage_detail="正在恢复工作流或分析简历证据",
        progress=build_stage_progress("resume_analysis"),
    )
    _save_career_report_progress(
        username,
        job_id,
        "resume_analysis",
        stage_defs.get("resume_analysis", "简历分析"),
        "正在恢复工作流或分析简历证据",
        model=model_name,
        generation_mode=generation_mode,
        report_id=report_id,
        status="running",
    )

    agent_activity = {}
    activity_lock = threading.Lock()

    def _agent_status_callback(agent, status, detail):
        if _is_career_report_job_cancelled(job_id):
            return
        with activity_lock:
            agent_activity[agent] = {"status": status, "message": str(detail)[:180],
                                     "updated_at": datetime.now().isoformat(timespec="seconds")}
            snapshot = {key: dict(value) for key, value in agent_activity.items()}
        _update_career_report_job(job_id, agent_activity=snapshot)

    def _stage_callback(stage_key, stage_label, detail):
        _ensure_not_cancelled()
        if stage_key in {item["key"] for item in CAREER_REPORT_STAGE_DEFS}:
            _agent_status_callback(stage_key, "active", detail)
        _log("阶段切换", stage=stage_key, label=stage_label, detail=detail)
        _update_career_report_job(
            job_id,
            status="running",
            stage=stage_key,
            stage_label=stage_label,
            stage_detail=detail,
            message=detail,
            progress=build_stage_progress(stage_key),
        )
        _save_career_report_progress(
            username,
            job_id,
            stage_key,
            stage_label,
            detail,
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
            status="running",
            agent_activity={key: dict(value) for key, value in agent_activity.items()},
        )

    try:
        _ensure_not_cancelled()
        bundle = generate_career_report_bundle(
            username=username,
            report_id=report_id,
            profile_payload=profile_payload,
            role_payload=role_payload,
            news_payload=None,
            focus_role_id=focus_role_id,
            stage_callback=_stage_callback,
            agent_status_callback=_agent_status_callback,
            runtime_llm=runtime_llm_with_caller,
            model_name=model_name,
        )
        _ensure_not_cancelled()
        _log("编排返回，开始写入报告文件")
        completed_profile = bundle.get("profile_snapshot") or {}
        city_memory = completed_profile.pop("report_city_memory", [])
        _save_career_report_bundle(username, bundle)
        submitted_preferences = (completed_profile.get("report_user_inputs") or {}).get("preferences", "")
        city = explicit_report_cities(submitted_preferences, (bundle.get("agent_results") or {}).get("recruitment_search") or {})
        if city:
            for previous in city_memory:
                if previous["value"] != city:
                    try:
                        app.extensions["chat_service"].memory.correct(
                            username, previous["id"], city, expected_value=previous["value"])
                    except Exception:
                        app.logger.exception("report city preference synchronization failed")
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
        final_stage = "report_writer"
        _update_career_report_job(
            job_id,
            status="completed",
            finished_at=int(time.time()),
            stage=final_stage,
            stage_label=stage_defs.get(final_stage, "报告合成"),
            stage_detail="报告生成完成",
            message="报告生成完成",
            report_id=str(meta.get("report_id") or report_id),
            progress=build_stage_progress(final_stage),
        )
        _save_career_report_progress(
            username,
            job_id,
            final_stage,
            stage_defs.get(final_stage, "报告合成"),
            "报告生成完成",
            status="ready",
            model=model_name,
            generation_mode=generation_mode,
            report_id=str(meta.get("report_id") or report_id),
            generated_at=str(meta.get("generated_at") or ""),
            focus_role_id=str(meta.get("focus_role_id") or ""),
            title=str(meta.get("title") or "职业规划报告"),
            summary=str(meta.get("summary") or ""),
        )
        _sync_career_report_tracker_state(username, bundle)
        _log(
            "后台任务完成",
            elapsed=f"{time.perf_counter() - job_started:.1f}s",
            report_id=str(meta.get("report_id") or report_id),
            mode=generation_mode,
        )
    except ReportNeedsInput as exc:
        if _is_career_report_job_cancelled(job_id):
            return
        _update_career_report_job(job_id, status="waiting_input", finished_at=int(time.time()),
                                  stage="review", stage_label="补充与确认", stage_detail=str(exc), message=str(exc))
        _save_career_report_progress(username, job_id, "review", "补充与确认", str(exc),
                                    status="waiting_input", model=model_name, generation_mode=generation_mode,
                                    report_id=report_id)
    except CareerReportCanceled as exc:
        _log("后台任务已取消", elapsed=f"{time.perf_counter() - job_started:.1f}s")
        _update_career_report_job(
            job_id,
            status="canceled",
            finished_at=int(time.time()),
            message=str(exc),
            stage_detail="用户已停止本次生成，旧任务不会写入报告。",
        )
        _save_career_report_progress(
            username,
            job_id,
            "report_writer",
            stage_defs.get("report_writer", "报告合成"),
            "用户已停止本次生成，旧任务不会写入报告。",
            status="canceled",
            error_message="",
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
        )
    except Exception as exc:
        app.logger.exception("career report generate failed")
        _log("后台任务失败", elapsed=f"{time.perf_counter() - job_started:.1f}s", error=str(exc)[:220])
        _update_career_report_job(
            job_id,
            status="failed",
            finished_at=int(time.time()),
            message=str(exc),
        )
        _save_career_report_progress(
            username,
            job_id,
            str((CAREER_REPORT_JOBS.get(job_id) or {}).get("stage") or "resume_analysis"),
            str((CAREER_REPORT_JOBS.get(job_id) or {}).get("stage_label") or "工作流执行"),
            "报告生成失败",
            status="failed",
            error_message=str(exc),
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
        )


@app.route("/api/career-report/generate/start", methods=["POST"])
@_login_required
def api_career_report_generate_start():
    user = _current_user()
    username = user["username"]
    running = _find_running_career_report_job(username)
    if running:
        return jsonify({
            "message": "已有职业规划报告任务在运行中。",
            "job_id": str(running.get("job_id") or ""),
            "already_running": True,
        }), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "请求必须是有效的 JSON 对象。"}), 400
    profile_payload = payload.get("profile_snapshot") if isinstance(payload.get("profile_snapshot"), dict) else {}
    role_payload = _saved_matching_role_payload({"role_rankings": payload.get("role_rankings")})
    focus_role_id = str(payload.get("focus_role_id") or "").strip()
    state = _load_user_state(username)
    if not profile_payload:
        profile_payload = _saved_profile_snapshot_payload(state.get("profile_snapshot"))
    if not role_payload:
        role_payload = _saved_matching_role_payload(state.get("career_matching"))
    if not focus_role_id and role_payload and isinstance(state.get("career_matching"), dict):
        focus_role_id = str((state.get("career_matching") or {}).get("focus_role_id") or "").strip()
    if not any(str(role.get("id") or "") == focus_role_id for role in role_payload):
        focus_role_id = ""
    if not profile_payload:
        profile_payload = {}
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    profile_portrait = state.get("profile_portrait") if isinstance(state.get("profile_portrait"), dict) else {}
    profile_payload = dict(profile_payload)
    profile_payload["feedback_memory"] = _normalize_career_report_feedback(report_state.get("feedback"))
    profile_payload["portrait_prompt_version"] = str(
        ((profile_portrait.get("prompt_pipeline") or {}).get("pipeline_version"))
        or PORTRAIT_PROMPT_PIPELINE_VERSION
    ).strip()
    profile_payload["agent_memory"] = _build_career_report_agent_memory(state, profile_payload, role_payload)

    continuation = None
    report_id = str(payload.get("continue_report_id") or "").strip()
    try:
        if report_id:
            snapshot = read_report_workflow(username, report_id)
            checkpoint_id = str(payload.get("checkpoint_id") or "")
            if not checkpoint_id or checkpoint_id != snapshot["checkpoint_id"]:
                return jsonify({"message": "工作流已有更新，请刷新后继续。"}), 409
            response = payload.get("response") or {}
            validate_report_continuation(response, snapshot)
            continuation = {"checkpoint_id": checkpoint_id, "response": response}
        else:
            report_id = f"report-{uuid.uuid4().hex[:12]}"
            resume_scope = state.get("resume_profile") or {}
            resume_path = _owned_resume_storage_path(username, str(resume_scope.get("storage_path") or ""))
            resume_path = resume_path if resume_path and os.path.isfile(resume_path) else ""
            raw_resume = str(resume_scope.get("resume_source_text") or "").strip()
            if not resume_path and not raw_resume:
                return jsonify({"message": "请先上传简历，再启动多智能体报告。"}), 400
            workflow_request = dict(payload.get("workflow") or {})
            profile_payload["report_user_inputs"] = {key: workflow_request.get(key, "")
                for key in ("preferences", "additional_evidence")}
            shared_memory = dict(app.extensions["chat_service"].career_context(username))
            shared_memory["personality"] = personality.describe(personality.collect(state))
            workflow_request = apply_report_memory(workflow_request, shared_memory)
            profile_payload["report_city_memory"] = [
                {"id": row["id"], "value": row["value"]}
                for row in app.extensions["chat_service"].store.memory_snapshot(username)[1]
                if row["kind"] == "preference" and row["key"] == "target_city" and row["status"] == "active"]
            availability, preferences = apply_availability(payload.get("availability"), workflow_request.get("preferences", ""))
            if availability:
                profile_payload["report_availability"] = availability
                workflow_request["preferences"] = preferences
                if isinstance(workflow_request.get("recruitment"), dict):
                    recruitment = dict(workflow_request["recruitment"])
                    schedule = "\n时间安排（用户选择）：" + availability["summary"]
                    recruitment["request"] = str(recruitment.get("request") or "")[:3000 - len(schedule)] + schedule
                    workflow_request["recruitment"] = recruitment
            profile_payload["agent_workflow"] = validate_report_request(workflow_request, raw_resume, file_path=resume_path)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"message": str(exc)}), 400
    except ImportError:
        return jsonify({"message": "请先安装 requirements.txt 中的 Agent 依赖。"}), 503

    selection_snapshot = {}
    base_url, api_key, model = _get_chat_runtime()
    if not (base_url and api_key and model):
        _career_report_console_log(report_id, "启动请求被拒绝", reason="model_not_configured")
        return jsonify({"message": "模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。"}), 400
    runtime_llm = {"model": model, "base_url": base_url, "api_key": api_key,
                   "selection": dict(selection_snapshot), "continuation": continuation}

    job_id = uuid.uuid4().hex
    stage_label = next((item["label"] for item in CAREER_REPORT_STAGE_DEFS if item["key"] == "resume_analysis"), "简历分析")
    job = {
        "job_id": job_id,
        "username": username,
        "status": "queued",
        "stage": "resume_analysis",
        "stage_label": stage_label,
        "stage_detail": "任务已创建，等待后台编排",
        "message": "",
        "created_at": int(time.time()),
        "started_at": 0,
        "finished_at": 0,
        "report_id": report_id,
        "progress": build_stage_progress("resume_analysis"),
        "model": str(runtime_llm.get("model") or ""),
        "generation_mode": "langgraph",
        "cancel_requested": False,
    }
    with CAREER_REPORT_LOCK:
        running = next((item for item in CAREER_REPORT_JOBS.values()
                        if item.get("username") == username and item.get("status") in {"queued", "running"}), None)
        if running:
            return jsonify({"message": "已有职业规划报告任务在运行中。",
                            "job_id": running["job_id"], "already_running": True}), 409
        CAREER_REPORT_JOBS[job_id] = job

    _career_report_console_log(
        job_id,
        "收到启动请求，任务入队",
        user=username,
        report_id=report_id,
        model=str(runtime_llm.get("model") or "none"),
        mode="langgraph",
        roles=len(role_payload or []),
        focus_role=focus_role_id or "auto",
    )

    _save_career_report_progress(
        username,
        job_id,
        "resume_analysis",
        stage_label,
        "任务已创建，等待后台编排",
        status="queued",
        report_id=report_id,
        model=str(runtime_llm.get("model") or ""),
        generation_mode="langgraph",
        focus_role_id=focus_role_id,
    )

    thread = threading.Thread(
        target=_run_career_report_job,
        args=(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm),
        daemon=True,
        name=f"career-report-{job_id[:8]}",
    )
    thread.start()

    return jsonify({
        "message": "职业规划报告任务已启动。",
        "job_id": job_id,
        "report_id": report_id,
        "already_running": False,
    })


@app.route("/api/career-report/workflow/<report_id>", methods=["GET"])
@_login_required
def api_career_report_workflow(report_id):
    try:
        snapshot = read_report_workflow(_current_user()["username"], report_id)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except ImportError:
        return jsonify({"message": "请安装 Agent 运行依赖。"}), 503
    if not snapshot["checkpoint_id"]:
        return jsonify({"message": "没有找到此账户的报告工作流。"}), 404
    return jsonify(snapshot)


@app.route("/api/career-report/generate/cancel", methods=["POST"])
@_login_required
def api_career_report_generate_cancel():
    user = _current_user()
    username = user["username"]
    payload = request.get_json(silent=True) or {}
    job_id = str(payload.get("job_id") or request.args.get("job_id") or "").strip()
    selected = None

    with CAREER_REPORT_LOCK:
        if job_id:
            candidate = CAREER_REPORT_JOBS.get(job_id)
            if isinstance(candidate, dict) and str(candidate.get("username") or "") == username:
                selected = candidate
        else:
            jobs = [
                item
                for item in CAREER_REPORT_JOBS.values()
                if isinstance(item, dict)
                and str(item.get("username") or "") == username
                and str(item.get("status") or "") in {"queued", "running"}
            ]
            jobs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            if jobs:
                selected = jobs[0]

        if not isinstance(selected, dict):
            return jsonify({"message": "当前没有可停止的职业报告生成任务。"}), 404

        status = str(selected.get("status") or "")
        if status not in {"queued", "running"}:
            return jsonify({
                "message": "该任务已经结束，无需停止。",
                "job": _public_career_report_job(dict(selected)),
            })

        selected["status"] = "canceled"
        CAREER_REPORT_JOBS.touch(str(selected.get("job_id") or ""))
        selected["cancel_requested"] = True
        selected["finished_at"] = int(time.time())
        selected["message"] = "用户已停止本次生成。"
        selected["stage_detail"] = "用户已停止本次生成，旧任务不会写入报告。"
        selected_job = dict(selected)

    _career_report_console_log(
        str(selected_job.get("job_id") or job_id),
        "收到停止请求",
        user=username,
        stage=str(selected_job.get("stage") or ""),
    )
    _save_career_report_progress(
        username,
        str(selected_job.get("job_id") or job_id),
        str(selected_job.get("stage") or "report_writer"),
        str(selected_job.get("stage_label") or "报告生成"),
        "用户已停止本次生成，旧任务不会写入报告。",
        status="canceled",
        error_message="",
        model=str(selected_job.get("model") or ""),
        generation_mode=str(selected_job.get("generation_mode") or ""),
        report_id=str(selected_job.get("report_id") or ""),
    )

    current_bundle = _read_career_report_bundle(username)
    if not (isinstance(current_bundle, dict) and current_bundle.get("meta")):
        state = _load_user_state(username)
        state["career_report"] = empty_report_state()
        _save_user_state(username, state)

    return jsonify({
        "message": "已停止本次职业报告生成。正在进行中的模型请求如果稍后返回，也不会写入报告。",
        "job": _public_career_report_job(selected_job),
    })


@app.route("/api/career-report/generate/status", methods=["GET"])
@_login_required
def api_career_report_generate_status():
    user = _current_user()
    username = user["username"]
    job_id = str(request.args.get("job_id") or "").strip()
    selected = None
    with CAREER_REPORT_LOCK:
        if job_id:
            candidate = CAREER_REPORT_JOBS.get(job_id)
            if isinstance(candidate, dict) and str(candidate.get("username") or "") == username:
                selected = dict(candidate)
        else:
            jobs = [
                dict(item)
                for item in CAREER_REPORT_JOBS.values()
                if isinstance(item, dict) and str(item.get("username") or "") == username
            ]
            jobs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            if jobs:
                selected = jobs[0]

    # 前端可能仍轮询「已取消/已结束」的旧 job_id；若已有更新的运行中任务，改为返回当前运行任务。
    if isinstance(selected, dict):
        sel_status = str(selected.get("status") or "")
        if sel_status not in {"queued", "running"}:
            running = _find_running_career_report_job(username)
            if (
                running
                and int(running.get("created_at") or 0) > int(selected.get("created_at") or 0)
            ):
                selected = dict(running)
    elif job_id:
        running = _find_running_career_report_job(username)
        if running:
            selected = dict(running)

    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    report_status = str(report_state.get("status") or "")
    current_bundle = _read_career_report_bundle(username)
    if not selected and report_status in {"queued", "running"}:
        report_state.update({
            "status": "failed",
            "stage_detail": "后台执行已中断，可从已保存的检查点继续。",
            "error_message": "",
        })
        state["career_report"] = report_state
        _save_user_state(username, state)

    merged_state = dict(report_state) if isinstance(report_state, dict) else {}
    if isinstance(selected, dict):
        jst = str(selected.get("status") or "")
        if jst in {"queued", "running"}:
            merged_state.update(
                {
                    "status": jst,
                    "job_id": str(selected.get("job_id") or merged_state.get("job_id") or ""),
                    "report_id": str(selected.get("report_id") or merged_state.get("report_id") or ""),
                    "stage": str(selected.get("stage") or merged_state.get("stage") or ""),
                    "stage_label": str(selected.get("stage_label") or merged_state.get("stage_label") or ""),
                    "stage_detail": str(
                        selected.get("stage_detail")
                        or selected.get("message")
                        or merged_state.get("stage_detail")
                        or ""
                    ),
                    "progress": selected.get("progress")
                    if isinstance(selected.get("progress"), list)
                    else merged_state.get("progress"),
                    "agent_activity": selected.get("agent_activity") or merged_state.get("agent_activity", {}),
                    "model": str(selected.get("model") or merged_state.get("model") or ""),
                    "generation_mode": str(selected.get("generation_mode") or merged_state.get("generation_mode") or ""),
                    "error_message": "",
                }
            )

    merged_state, merged_state_changed = _sanitize_transient_career_report_state(
        username,
        merged_state,
        current_bundle=current_bundle,
    )
    if merged_state_changed:
        state["career_report"] = merged_state
        _save_user_state(username, state)

    return jsonify({
        "job": _public_career_report_job(selected),
        "state": _public_career_report_state(merged_state),
    })


@app.route("/api/career-report/current", methods=["GET"])
@_login_required
def api_career_report_current():
    user = _current_user()
    bundle = _read_career_report_bundle(user["username"])
    bundle = _refresh_career_report_role_resolution(bundle)
    if isinstance(bundle, dict) and bundle.get("meta"):
        state, report_state, _ = _sync_career_report_tracker_state(user["username"], bundle)
    else:
        state = _load_user_state(user["username"])
        report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
        report_state, report_state_changed = _sanitize_transient_career_report_state(
            user["username"],
            report_state,
            current_bundle=bundle,
        )
        if report_state_changed:
            state["career_report"] = report_state
            _save_user_state(user["username"], state)
    data = _public_career_report_bundle(bundle) if isinstance(bundle, dict) and bundle.get("meta") else None
    return jsonify({
        "data": data,
        "state": _public_career_report_state(report_state),
    })


@app.route("/api/career-report/feedback", methods=["POST"])
@_login_required
def api_career_report_feedback():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"accurate", "partial", "off_target"}:
        return jsonify({"message": "请先选择反馈结论。"}), 400

    note = str(payload.get("note") or "").strip()[:320]
    bundle = _read_career_report_bundle(user["username"])
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}

    state = _load_user_state(user["username"])
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else empty_report_state()
    report_state["feedback"] = _append_career_report_feedback(
        report_state.get("feedback"),
        {
            "report_id": str(payload.get("report_id") or meta.get("report_id") or report_state.get("report_id") or "").strip(),
            "focus_role_id": str(payload.get("focus_role_id") or meta.get("focus_role_id") or report_state.get("focus_role_id") or "").strip(),
            "focus_role_name": str(
                payload.get("focus_role_name")
                or document.get("focus_role_name")
                or meta.get("focus_role_name")
                or ""
            ).strip(),
            "verdict": verdict,
            "note": note,
        },
    )
    state["career_report"] = report_state
    _save_user_state(user["username"], state)
    return jsonify({
        "message": "反馈已记录，下次生成会优先吸收。",
        "feedback": report_state.get("feedback"),
        "state": _public_career_report_state(report_state),
    })


@app.route("/api/career-report/polish", methods=["POST"])
@_login_required
def api_career_report_polish():
    payload = request.get_json(silent=True) or {}
    section_key = str(payload.get("section_key") or "").strip()[:80]
    text = str(payload.get("selection") or payload.get("text") or "").strip()
    instruction = str(payload.get("instruction") or "").strip()[:800]
    quick_action = str(payload.get("quick_action") or "").strip().lower()[:32]
    if quick_action in _CAREER_REPORT_QUICK_POLISH:
        preset = _CAREER_REPORT_QUICK_POLISH[quick_action]
        instruction = f"{preset}\n\n{instruction}".strip() if instruction else preset
        instruction = instruction[:800]
    want_ai_summary = (
        quick_action in _CAREER_REPORT_QUICK_POLISH
        or str(payload.get("want_ai_summary") or "").strip().lower() in ("1", "true", "yes")
    )
    model_override = str(payload.get("model") or "").strip()[:120]
    full_text = str(payload.get("full_text") or "").strip()
    try:
        selection_start = int(payload.get("selection_start")) if payload.get("selection_start") is not None else -1
        selection_end = int(payload.get("selection_end")) if payload.get("selection_end") is not None else -1
    except Exception:
        selection_start = -1
        selection_end = -1
    if not text:
        return jsonify({"message": "缺少需要润色的报告段落。"}), 400

    text = text[:6000]
    base_url, api_key, model = _get_active_provider_and_model()
    if model_override:
        model = model_override
    if not (base_url and api_key and model):
        return jsonify({"message": "请先配置可用的模型后再润色报告段落。"}), 400

    system_prompt = (
        "你是职业发展报告编辑。只润色用户提供的报告段落，不新增事实、不改变结论、不编造数据。"
        "保留 Markdown 结构，压缩重复表达，让语言更清晰、专业、适合学生职业规划报告。"
        "如果原文包含 JSON 或表格，只保留必要说明，不改动事实字段。"
        "需要注意段落连贯性，避免句子层面的孤立替换；若提供上下文，需与上下文语气、术语、叙事节奏一致。"
    )
    if want_ai_summary:
        system_prompt += (
            "\n\n输出格式（必须遵守）：先用 2-4 句中文概括本次润色侧重点与结构调整（不要复述润色后的正文）。"
            "然后单独一行输出分隔符 <<<AI_BODY>>>（仅此一行，勿加反引号），"
            "换行后只输出润色后的正文，可使用 Markdown。"
        )
    extra_instruction = f"\n\n用户额外要求：{instruction}" if instruction else ""
    context_hint = ""
    if full_text and selection_start >= 0 and selection_end > selection_start:
        safe_start = max(0, min(selection_start, len(full_text)))
        safe_end = max(safe_start, min(selection_end, len(full_text)))
        before = full_text[max(0, safe_start - 900):safe_start].strip()
        after = full_text[safe_end:min(len(full_text), safe_end + 900)].strip()
        if before or after:
            context_hint = (
                "\n\n上下文（仅用于保证连贯）：\n"
                f"--- 上文 ---\n{before or '（无）'}\n"
                f"--- 下文 ---\n{after or '（无）'}\n"
            )
    if want_ai_summary:
        user_msg = (
            f"模块：{section_key or '未指定'}{extra_instruction}{context_hint}\n\n"
            "请严格按系统提示的格式输出：先概括，再输出 <<<AI_BODY>>> 分隔符，最后给出润色后的正文。\n\n"
            "目标段落如下：\n\n"
            f"{text}"
        )
    else:
        user_msg = (
            f"模块：{section_key or '未指定'}{extra_instruction}{context_hint}\n\n"
            "请只输出润色后的目标段落文本（不要附加解释），并保持与上下文衔接自然：\n\n"
            f"{text}"
        )
    try:
        polished = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": user_msg}],
            system_prompt=system_prompt,
            max_tokens=2400 if want_ai_summary else 1800,
        )
    except Exception as exc:
        app.logger.exception("career report polish failed")
        return jsonify({"message": str(exc)[:300] or "润色失败。"}), 500

    action_summary = ""
    proposed_text = polished.strip()
    if want_ai_summary:
        summary_part, body_part = _split_career_polish_output(polished)
        if body_part:
            proposed_text = body_part.strip()
            action_summary = (summary_part or "").strip() or _fallback_summary_career_quick_action(quick_action)
        else:
            proposed_text = polished.strip()
            action_summary = (
                _fallback_summary_career_quick_action(quick_action)
                if quick_action
                else "已根据你的说明完成润色；未新增事实。请查看 Diff 了解具体修改。"
            )

    return jsonify({
        "section_key": section_key,
        "model": model,
        "original": text,
        "proposed": proposed_text,
        "polished": proposed_text,
        "action_summary": action_summary,
        "quick_action": quick_action or None,
        "diff_blocks": _build_career_report_diff_blocks(text, proposed_text),
    })


@app.route("/api/career-report/version", methods=["GET", "DELETE"])
@_login_required
def api_career_report_version():
    """按 report_id 读取已归档或当前 latest 的报告正文，不写入用户状态。"""
    user = _current_user()
    if request.method == "DELETE":
        payload = request.get_json(silent=True) or {}
        report_id = str(payload.get("report_id") or request.args.get("report_id") or "").strip()
        if not report_id:
            return jsonify({"message": "缺少 report_id"}), 400
        try:
            result = _delete_career_report_version(user["username"], report_id)
        except FileNotFoundError as exc:
            return jsonify({"message": str(exc) or "未找到对应的职业报告版本。"}), 404
        except ValueError as exc:
            return jsonify({"message": str(exc) or "删除职业报告失败。"}), 400

        bundle = _read_career_report_bundle(user["username"])
        state = _load_user_state(user["username"])
        report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else empty_report_state()
        data = _public_career_report_bundle(bundle) if isinstance(bundle, dict) and bundle.get("meta") else None

        message = "该职业报告卡片已删除。"
        if result.get("replacement_report_id"):
            replacement_title = str(result.get("replacement_title") or "上一份正式报告").strip()
            message = f"已删除当前卡片，并切换到 {replacement_title}。"
        elif result.get("deleted_current"):
            message = "已删除当前职业报告，卡片库已回到空状态。"

        return jsonify({
            "message": message,
            "deleted_report_id": result.get("deleted_report_id") or report_id,
            "replacement_report_id": result.get("replacement_report_id") or "",
            "data": data,
            "state": _public_career_report_state(report_state),
        })

    report_id = str(request.args.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"message": "缺少 report_id"}), 400
    paths = _career_report_file_paths(user["username"])
    versions_dir = os.path.join(paths["dir"], "versions")
    bundle = {}
    with APP_DATA_LOCK:
        archive_path = os.path.join(versions_dir, f"{report_id}.json")
        if os.path.isfile(archive_path):
            bundle = _read_json_file(archive_path, {})
        else:
            latest = _read_json_file(paths["json"], {})
            latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
            if latest_id == report_id:
                bundle = latest
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到该版本的完整报告（可能生成于版本归档功能之前）。"}), 404
    tracker = _build_career_report_tracker(bundle, None)
    return jsonify({
        "data": _public_career_report_bundle(bundle),
        "tracker": tracker,
    })


def _career_report_preview_context():
    from services.report.link_preview import public_preview_url, report_contains_url

    url = public_preview_url(request.args.get("url"))
    if not url:
        return None, (jsonify({"message": "仅支持公开网页链接。"}), 400)
    username = _current_user()["username"]
    report_id = str(request.args.get("report_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(username, report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return None, (jsonify({"message": "未找到对应的职业报告。"}), 404)
    resolved_id = str(bundle["meta"].get("report_id") or report_id)
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    snapshot = _read_career_report_snapshot(username, resolved_id, snapshot_id) if snapshot_id else None
    if snapshot_id and not snapshot:
        return None, (jsonify({"message": "未找到对应的编辑快照。"}), 404)
    if not report_contains_url(bundle, url, snapshot):
        return None, (jsonify({"message": "此链接不在当前报告中。"}), 404)
    return {"url": url, "report_id": resolved_id, "snapshot_id": snapshot_id}, None


@app.route("/api/career-report/link-preview", methods=["GET"])
@_login_required
def api_career_report_link_preview():
    from services.report.link_preview import get_link_preview

    context, error = _career_report_preview_context()
    if error is not None:
        return error
    preview = get_link_preview(context["url"])
    image = preview.pop("image", "")
    preview["image_url"] = url_for("api_career_report_link_preview_image", **context) if image else ""
    response = jsonify({"data": preview})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.route("/api/career-report/link-preview/image", methods=["GET"])
@_login_required
def api_career_report_link_preview_image():
    from services.report.link_preview import get_link_preview_image

    context, error = _career_report_preview_context()
    if error is not None:
        return error
    image = get_link_preview_image(context["url"])
    if image is None:
        return "", 404
    response = app.response_class(image[0], mimetype=image[1])
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.route("/api/career-report/source", methods=["GET"])
@_login_required
def api_career_report_source():
    user = _current_user()
    report_id = str(request.args.get("report_id") or "").strip()
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404
        normalized = _normalize_career_report_snapshot(snapshot, bundle=bundle, report_id=resolved_report_id)
        completeness = normalized.get("completeness_check") if isinstance(normalized.get("completeness_check"), dict) else _run_career_report_completeness_check(bundle, normalized.get("markdown"), normalized)
        return jsonify({
            "report_id": resolved_report_id,
            "snapshot_id": normalized["snapshot_id"],
            "source_type": normalized.get("source") or "snapshot",
            "title": normalized.get("title") or normalized.get("label") or "编辑快照",
            "markdown": normalized.get("markdown") or "",
            "section_map": normalized.get("section_map") or [],
            "diff_blocks": normalized.get("diff_blocks") or [],
            "completeness_check": completeness,
            "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
            "bundle": _public_career_report_bundle(bundle),
        })

    report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()
    return jsonify({
        "report_id": resolved_report_id,
        "snapshot_id": "",
        "source_type": "formal_report",
        "title": str(report_document.get("title") or (bundle.get("meta") or {}).get("title") or "职业发展报告").strip() or "职业发展报告",
        "markdown": markdown_text,
        "section_map": _build_career_report_section_map(bundle, markdown_text),
        "diff_blocks": [],
        "completeness_check": _run_career_report_completeness_check(bundle, markdown_text),
        "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
        "bundle": _public_career_report_bundle(bundle),
    })


@app.route("/api/career-report/snapshot/save", methods=["POST"])
@_login_required
def api_career_report_snapshot_save():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    report_id = str(payload.get("report_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    markdown_text = normalize_br_tags_in_markdown(str(payload.get("markdown") or "").strip())
    if not markdown_text:
        return jsonify({"message": "缺少快照 Markdown 内容。"}), 400

    section_map = _build_career_report_section_map(bundle, markdown_text)
    completeness_check = _run_career_report_completeness_check(bundle, markdown_text)
    snapshot = _save_career_report_snapshot(
        user["username"],
        resolved_report_id,
        {
            "snapshot_id": str(payload.get("snapshot_id") or "").strip(),
            "based_on_report_id": resolved_report_id,
            "source": str(payload.get("source") or "manual").strip() or "manual",
            "label": str(payload.get("label") or payload.get("title") or "编辑快照").strip() or "编辑快照",
            "title": str(payload.get("title") or payload.get("label") or "编辑快照").strip() or "编辑快照",
            "focus_role_name": str(payload.get("focus_role_name") or (bundle.get("meta") or {}).get("focus_role_name") or "").strip(),
            "markdown": markdown_text,
            "section_map": section_map,
            "diff_blocks": payload.get("diff_blocks") if isinstance(payload.get("diff_blocks"), list) else [],
            "completeness_check": completeness_check,
        },
    )
    # 从正式报告进入润色且未绑定旧快照时：保存同时写回该版本的报告正文，阅览室下次打开即为此稿。
    formal_report_updated = False
    if not str(payload.get("snapshot_id") or "").strip():
        formal_report_updated = _commit_career_report_markdown_to_store(
            user["username"], resolved_report_id, markdown_text
        )
    return jsonify({
        "message": "编辑快照已保存。",
        "snapshot": _public_career_report_snapshot(snapshot, include_content=True),
        "draft_snapshots": _list_career_report_snapshots(user["username"], resolved_report_id),
        "formal_report_updated": formal_report_updated,
    })


@app.route("/api/career-report/snapshot/check", methods=["POST"])
@_login_required
def api_career_report_snapshot_check():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    report_id = str(payload.get("report_id") or "").strip()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    snapshot = None
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404

    markdown_text = str(payload.get("markdown") or "").strip()
    if not markdown_text:
        if isinstance(snapshot, dict):
            markdown_text = str(snapshot.get("markdown") or "").strip()
        else:
            report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
            markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()

    return jsonify({
        "report_id": resolved_report_id,
        "snapshot_id": snapshot_id,
        "completeness_check": _run_career_report_completeness_check(bundle, markdown_text, snapshot),
    })


@app.route("/api/career-report/tracker/sync", methods=["POST"])
@_login_required
def api_career_report_tracker_sync():
    user = _current_user()
    bundle = _read_career_report_bundle(user["username"])
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可同步的职业规划报告。"}), 404

    payload = request.get_json(silent=True) or {}
    current_capabilities = payload.get("current_capabilities") if isinstance(payload.get("current_capabilities"), list) else []
    state, report_state, tracker = _sync_career_report_tracker_state(
        user["username"],
        bundle,
        current_capabilities=current_capabilities,
    )
    return jsonify(
        {
            "tracker": tracker,
            "state": _public_career_report_state(report_state),
            "data": _public_career_report_bundle(bundle),
        }
    )


@app.route("/api/career-report/tracker/item", methods=["POST"])
@_login_required
def api_career_report_tracker_item():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    item_type = str(payload.get("item_type") or "").strip().lower()
    item_id = str(payload.get("item_id") or "").strip()
    status = _normalize_tracker_status(payload.get("status"), allow_doing=item_type == "plan")
    if item_type not in {"plan", "checkpoint"} or not item_id:
        return jsonify({"message": "请指定 item_type 和 item_id。"}), 400

    bundle = _read_career_report_bundle(user["username"])
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可更新的职业规划报告。"}), 404

    state, report_state, tracker = _sync_career_report_tracker_state(user["username"], bundle)
    if not isinstance(tracker, dict):
        return jsonify({"message": "当前职业报告尚未完成初始化。"}), 409

    key = "plan_items" if item_type == "plan" else "checkpoints"
    allow_doing = item_type == "plan"
    safe_status = _normalize_tracker_status(status, allow_doing=allow_doing)
    items = tracker.get(key) if isinstance(tracker.get(key), list) else []
    matched = False
    now_text = _career_tracker_now()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != item_id:
            continue
        matched = True
        item["status"] = safe_status
        item["updated_at"] = now_text
        if safe_status == "doing":
            item["started_at"] = str(item.get("started_at") or now_text)
            item["completed_at"] = ""
        elif safe_status == "done":
            if allow_doing:
                item["started_at"] = str(item.get("started_at") or now_text)
            item["completed_at"] = str(item.get("completed_at") or now_text)
        else:
            if allow_doing:
                item["started_at"] = ""
            item["completed_at"] = ""
        break

    if not matched:
        return jsonify({"message": "未找到对应的职业档案条目。"}), 404

    tracker = _build_career_report_tracker(bundle, tracker)
    report_state["tracker"] = tracker
    state["career_report"] = report_state
    _save_user_state(user["username"], state)
    return jsonify({"tracker": tracker, "state": _public_career_report_state(report_state)})


@app.route("/api/career-report/export", methods=["GET"])
@_login_required
def api_career_report_export():
    user = _current_user()
    from services.report.html_layout import normalize_typography, typography_css
    try:
        typography = normalize_typography(json.loads(request.args.get("typography") or "{}"))
    except (ValueError, TypeError):
        return jsonify({"message": "报告字号参数无效。"}), 400
    export_format = str(request.args.get("format") or "pdf").strip().lower()
    if export_format not in {"html", "md", "docx", "pdf"}:
        return jsonify({"message": "仅支持 html / md / docx / pdf 导出。"}), 400

    report_id = str(request.args.get("report_id") or "").strip()
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可导出的职业规划报告。"}), 404

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    resolved_report_id = str(meta.get("report_id") or report_id or "").strip()
    source_label = str(meta.get("title") or "career-report").strip() or "career-report"
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404
        normalized = _normalize_career_report_snapshot(snapshot, bundle=bundle, report_id=resolved_report_id)
        markdown_text = str(normalized.get("markdown") or "").strip()
        source_label = str(normalized.get("title") or normalized.get("label") or source_label).strip() or source_label
    else:
        report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
        markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()

    markdown_text = normalize_br_tags_in_markdown(markdown_text)

    filename_stem = _career_report_export_filename_stem(
        source_label,
        report_id=resolved_report_id,
        generated_at=str(meta.get("generated_at") or ""),
        version=str(meta.get("version") or ""),
        snapshot_id=snapshot_id,
    )
    if export_format == "md":
        return app.response_class(
            markdown_text,
            mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition": _attachment_content_disposition(f"{filename_stem}.md")},
        )

    html_for_render = None
    if export_format == "html":
        html_for_render = (
            render_markdown_export_html(markdown_text, title=source_label)
            if snapshot_id
            else render_report_html(bundle)
        )

    if export_format == "html":
        if html_for_render and typography:
            html_for_render = html_for_render.replace("</style>", typography_css(typography) + "\n</style>")
        return app.response_class(
            html_for_render or "",
            mimetype="text/html; charset=utf-8",
            headers={"Content-Disposition": _attachment_content_disposition(f"{filename_stem}.html")},
        )

    if export_format == "pdf":
        try:
            pdf_bytes = export_markdown_to_pdf_bytes(markdown_text, title=source_label, typography=typography)
        except Exception as exc:
            app.logger.exception("career report pdf export failed")
            return jsonify({"message": str(exc)[:500] or "PDF 导出失败。"}), 500
        response = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{filename_stem}.pdf",
        )
        response.headers["X-Report-PDF-Engine"] = "pymupdf"
        return response

    try:
        docx_bytes = export_markdown_to_docx_bytes(markdown_text, title=source_label, typography=typography)
    except Exception as exc:
        app.logger.exception("career report docx export failed")
        return jsonify({"message": str(exc)[:500] or "DOCX 导出失败。"}), 500

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{filename_stem}.docx",
    )



















# 启动入口
def open_browser():
    import time
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")

def _prewarm_caches():
    """后台预热重载数据，避免首次请求阻塞。"""
    def _warm_news():
        try:
            get_career_news_payload()
        except Exception as exc:
            logger.warning("资讯预热失败：%s", type(exc).__name__)

    if os.environ.get("CAREER_PREWARM", "1").lower() in {"0", "false", "no"}:
        return
    threading.Thread(target=_warm_news, daemon=True, name="prewarm-news").start()


def _fail_interrupted_resume(job):
    username = str(job.get("username") or "")
    state = _load_user_state(username)
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    if resume_state.get("status") != "analyzing":
        return
    resume_state["status"] = "failed"
    resume_state["error_message"] = str(job.get("message") or "")
    meta = resume_state.get("analysis_meta") if isinstance(resume_state.get("analysis_meta"), dict) else {}
    meta.update({"running": False, "stage": "failed", "stage_detail": str(job.get("message") or ""),
                 "stage_updated_at": int(time.time())})
    resume_state["analysis_meta"] = meta
    state["resume_profile"] = resume_state
    _save_user_state(username, state)


def _fail_interrupted_report(job):
    username = str(job.get("username") or "")
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    if str(report_state.get("status") or "").lower() not in {"queued", "running"}:
        return
    _save_career_report_progress(
        username, str(job.get("job_id") or ""), str(job.get("stage") or "resume_analysis"),
        str(job.get("stage_label") or "工作流执行"), "报告生成被服务重启中断", status="failed",
        error_message=str(job.get("message") or ""), model=str(job.get("model") or ""),
        generation_mode=str(job.get("generation_mode") or ""), report_id=str(job.get("report_id") or ""))


def _restore_background_jobs():
    """Bring back recent jobs after a restart and fail the ones the restart interrupted, in the registry and in
    the user's saved state, so nobody waits on a task that no longer exists."""
    for registry, fail_state in ((RESUME_ANALYSIS_JOBS, _fail_interrupted_resume), (CAREER_REPORT_JOBS, _fail_interrupted_report)):
        for job in registry.restore():
            try:
                fail_state(job)
            except Exception:
                app.logger.exception("could not mark interrupted job %s", job.get("job_id"))


_ensure_app_storage()
_app_db.init_db()
_restore_background_jobs()
_auth.init_app(app)
app.register_blueprint(create_datasets_blueprint(_login_required))
app.register_blueprint(create_community_blueprint(_login_required, _super_admin_required, _current_user))
app.register_blueprint(create_interview_blueprint(_login_required, _get_active_provider_and_model))
app.register_blueprint(create_job_data_blueprint())
app.register_blueprint(create_portrait_blueprint(_login_required, _current_user, _load_user_state, _save_user_state))
app.register_blueprint(create_news_blueprint())
app.register_blueprint(create_pages_blueprint(_current_user))
_chat_blueprint = create_chat_blueprint(
    directory=APP_DATA_DIR / "assistant",
    current_user=_current_user,
    runtime_provider=_get_chat_runtime,
    profile_provider=lambda username: build_chat_background(_load_user_state(username), _read_career_report_bundle(username)),
    resume_provider=_chat_resume_source,
)
app.register_blueprint(_chat_blueprint)
app.extensions["chat_service"] = _chat_blueprint.chat_service


def _career_memory_records(username):
    records = _chat_blueprint.chat_service.store.memory_snapshot(username)[1]
    return [{key: item[key] for key in ("id", "key", "subject", "value", "status", "source_session", "updated_at")}
            for item in records if item["kind"] == "fact" and item["status"] in {"active", "conflict"}]


def _career_chat_background(username):
    """聊天只读基础画像：求职偏好、学校/专业/学历/毕业时间、所在城市与阶段、在进行的目标。

    职业档案里的经历、技能、证书、证据属于报告与岗位匹配，不进入聊天上下文。"""
    background = build_chat_background(_load_user_state(username), _read_career_report_bundle(username))
    data = career_snapshot(username)
    resume_enabled = _chat_blueprint.chat_service.store.privacy(username)["resume_enabled"]
    profile = data["profile"] or {}
    basics = {key: profile[key] for key in ("city", "stage", "headline") if profile.get(key)}
    education = [{"title": row["title"], "description": str(row.get("description") or "")[:200]}
                 for row in data["entries"]
                 if row["kind"] == "education" and (resume_enabled or row["source_type"] != "resume")][:10]
    goals = [{"title": row["title"], "status": row["status"], "target_date": row.get("target_date") or ""}
             for row in data["goals"] if row["status"] == "active"][:10]
    if basics or education or goals:
        background["用户维护的基础档案"] = {"基本信息": basics, "教育": education, "目标": goals}
    # 做过哪些测评就带哪些；一个都没做就不出现这一项。
    assessments = personality.for_chat(personality.collect(_load_user_state(username)))
    if assessments:
        background["性格与兴趣测评（用户自测的自评结果）"] = assessments
    return background


_chat_blueprint.chat_service.profile_provider = _career_chat_background
app.register_blueprint(create_career_blueprint(_login_required, _current_user, _load_user_state, _career_memory_records))
_job_market_collector = JobMarketCollector()
app.extensions["job_market"] = _job_market_collector
app.register_blueprint(create_job_market_blueprint(_job_market_collector, _login_required, _current_user))
if os.environ.get("JOB_MARKET_SCHEDULER", "1").lower() not in {"0", "false", "no"}:
    _job_market_collector.start_scheduler()
_load_users()
_prewarm_caches()

# Uvicorn serves chat with FastAPI; the rest of the site remains in Flask.
app.config.update(FRONTEND_ORIGIN=FRONTEND_ORIGIN, VITE_DEV_SERVER_URL=VITE_DEV_SERVER_URL)
asgi_app = create_chat_app(app, service=_chat_blueprint.chat_service, current_user=_current_user)

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("PORT", "8080"))
    auto_open_browser = os.environ.get("AUTO_OPEN_BROWSER", "").lower() in {"1", "true", "yes"}
    print("=" * 50)
    print("  职业规划智能体 · FastAPI + Flask 服务")
    print(f"  访问地址：http://{host}:{port}")
    print("  数据目录：", BOSS_INFO_DIR)
    print("  用户数据目录：", APP_DATA_DIR)
    print("  PDF 导出引擎：", f"PyMuPDF {fitz.VersionBind}" if fitz is not None else "PyMuPDF 未安装，请安装 requirements.txt")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    if auto_open_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(asgi_app, host=host, port=port)
