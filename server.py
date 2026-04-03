#!/usr/bin/env python3
"""
职业规划智能体 Flask 服务。
运行方式：python server.py
访问地址：http://localhost:8080
"""

import gzip
import io
import json
import mimetypes
import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
import webbrowser
from datetime import datetime, timedelta
from functools import wraps
import random

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from services.news import get_career_news_payload
from services.report import (
    CAREER_REPORT_STAGE_DEFS,
    REPORT_VERSION,
    build_stage_progress,
    empty_report_job,
    empty_report_state,
    generate_career_report_bundle,
)
from services.resume import (
    FLEXIBLE_MATCH_ANALYSIS_PROMPT,
    HR_JUDGE_PROMPT,
    RESUME_REVIEW_PROMPT,
    STRUCTURED_RESUME_PROMPT,
    STRUCTURED_RESUME_SCHEMA,
    build_matcher_state,
    build_job_payload_from_text,
    build_resume_text_payload,
)

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")

# 路径配置
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BOSS_INFO_DIR = os.path.join(BASE_DIR, "boss_info")
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")
USERS_FILE = os.path.join(APP_DATA_DIR, "users.json")
LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "llm_configs.json")
LLM_PROVIDERS_FILE = os.path.join(APP_DATA_DIR, "llm_providers.json")
RESUME_LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "resume_llm_config.json")
RESUME_UPLOAD_DIR = os.path.join(APP_DATA_DIR, "user_uploads")
CAREER_REPORT_DIR = os.path.join(APP_DATA_DIR, "career_reports")
PROFILE_PORTRAIT_MODEL = os.environ.get("PROFILE_PORTRAIT_MODEL", "google/gemini-3.1-flash-image-preview").strip() or "google/gemini-3.1-flash-image-preview"
ASSESSMENT_DATA_FILE = os.path.join(BASE_DIR, "static", "assessment-data.json")
JOB_CACHE_LOCK = threading.Lock()
APP_DATA_LOCK = threading.Lock()
USER_STATE_LOCK = threading.Lock()
ASSESSMENT_DATA_LOCK = threading.Lock()
JOB_FILE_CACHE = {}
ASSESSMENT_DATA_CACHE = {"signature": None, "payload": {}}
USERS_CACHE = None
RESUME_ANALYSIS_LOCK = threading.Lock()
RESUME_ANALYSIS_JOBS = {}
CAREER_REPORT_LOCK = threading.Lock()
CAREER_REPORT_JOBS = {}
JOB_CACHE_MAX_AGE_SECONDS = 900
RESUME_MAX_FILE_SIZE = 12 * 1024 * 1024
RESUME_MAX_PAGES = 20
RESUME_OCR_TIMEOUT_SECONDS = 35
RESUME_MAX_TEXT_CHARS = 24000
JOB_DETAIL_ONLY_FIELDS = {
    "岗位描述",
    "公司简介",
    "公司福利",
}

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    import fitz  # PyMuPDF
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

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("APP_SECRET_KEY") or os.environ.get("SECRET_KEY") or "career-planner-dev-secret"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
FRONTEND_ORIGIN = str(os.environ.get("FRONTEND_ORIGIN") or "").strip()
VITE_DEV_SERVER_URL = str(os.environ.get("VITE_DEV_SERVER_URL") or "").strip().rstrip("/")
VITE_MANIFEST_FILE = os.path.join(BASE_DIR, "static", "dist", ".vite", "manifest.json")
VITE_MANIFEST_CACHE = {"mtime": None, "payload": None}


@app.before_request
def _handle_api_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return ("", 204)
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
    origin = str(request.headers.get("Origin") or "").strip()
    allow_origin = FRONTEND_ORIGIN or origin or "*"
    response.headers["Access-Control-Allow-Origin"] = allow_origin
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Vary"] = "Origin"
    if allow_origin != "*":
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# 静态资源缓存 & gzip 压缩
_STATIC_EXTS_LONG = {".js", ".css", ".json", ".gif", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2"}
_GZIP_MIME = {"text/html", "text/css", "application/javascript", "application/json", "image/svg+xml", "text/javascript"}
_GZIP_MIN_SIZE = 1400  # bytes


@app.after_request
def _static_headers_and_gzip(response):
    path = request.path

    # ── 静态文件长效缓存 ──────────────────────────────
    if path.startswith("/static/"):
        ext = os.path.splitext(path)[1].lower()
        if ext in _STATIC_EXTS_LONG:
            # 版本号通过 ?v=xxx 实现，可以安全地设置 1 年
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

CAREER_INTERVIEW_SYSTEM_PROMPT = """
你是一名中文职业兴趣访谈助手，需要围绕职业兴趣、工作价值观、学习方式、沟通风格、行动证据、职业成熟度六个维度进行追问。
规则：
- 全程使用自然、简洁的中文。
- 每次只提一个问题，优先追问当前最缺失的信息。
- 至少完成 6 轮有效问答，最多不超过 10 轮。
- 如果用户回答比较空泛，继续追问真实经历或具体例子。
- 不要输出 Markdown，不要输出额外说明，只输出 JSON。
JSON 结构必须如下：
{
  "next_question": "下一轮问题，若已完成可为空字符串",
  "focus_dimension": "当前追问维度",
  "is_complete": false,
  "completion_score": 0,
  "profile": {
    "summary": "2-4 句中文总结",
    "career_interests": ["职业兴趣1", "职业兴趣2"],
    "work_values": ["价值观1", "价值观2"],
    "recommended_roles": ["岗位1", "岗位2"],
    "evidence_highlights": ["证据1", "证据2", "证据3"],
    "next_steps": ["建议1", "建议2", "建议3"],
    "riasec": {
      "realistic": 0,
      "investigative": 0,
      "artistic": 0,
      "social": 0,
      "enterprising": 0,
      "conventional": 0
    },
    "dimensions": [
      { "name": "职业兴趣", "score": 0, "evidence": "..." },
      { "name": "工作价值观", "score": 0, "evidence": "..." },
      { "name": "学习方式", "score": 0, "evidence": "..." },
      { "name": "沟通风格", "score": 0, "evidence": "..." },
      { "name": "行动证据", "score": 0, "evidence": "..." },
      { "name": "职业成熟度", "score": 0, "evidence": "..." }
    ]
  }
}
"""

MBTI_CLARIFIER_SYSTEM_PROMPT = """
你是一名中文 MBTI 澄清测评助手。请根据用户主测结果中的 close_pairs 生成少量高区分度补充题，帮助确认临界维度。
规则：
- 只使用简洁自然的中文。
- 每道题只对应 EI、SN、TF、JP 之一。
- 题目贴近日常学习、社交、任务推进和决策场景。
- 每道题都要提供鲜明对立的 option_a / option_b。
- 一次返回 2-6 题。
- 只输出 JSON。
JSON 结构必须如下：
{
  "summary": "本轮主要澄清的维度说明",
  "questions": [
    {
      "id": "q1",
      "pair": "EI",
      "question": "题目正文",
      "option_a": "偏向左侧字母的描述",
      "option_b": "偏向右侧字母的描述",
      "weight": 2
    }
  ]
}
"""

DEFAULT_CAREER_DIMENSIONS = [
    "职业兴趣",
    "工作价值观",
    "学习方式",
    "沟通风格",
    "行动证据",
    "职业成熟度",
]

DEFAULT_USER_SPECS = [
    {"username": "system", "password": "123456", "role": "super_admin", "display_name": "System Admin"},
    {"username": "23030134", "password": "123456", "role": "user", "display_name": "23030134"},
    {"username": "24110403", "password": "123456", "role": "user", "display_name": "24110403"},
    {"username": "24030115", "password": "123456", "role": "user", "display_name": "24030115"},
    {"username": "24151007", "password": "123456", "role": "user", "display_name": "24151007"},
]

VALID_USER_STATE_SCOPES = {"career_interview", "assessment_hub", "resume_profile", "career_report", "career_plans", "profile_portrait", "account_avatar"}
VALID_LLM_CONFIG_SCOPES = {"career_interview", "assessment_hub"}


def _default_llm_configs():
    return {
        "career_interview": {"base_url": "", "api_key": "", "model": "gpt-4o-mini"},
        "assessment_hub": {"base_url": "", "api_key": "", "model": "gpt-4o-mini"},
    }


def _default_resume_llm_config():
    return {"base_url": "", "api_key": "", "model": "gpt-4o-mini"}


def _normalized_resume_llm_config(raw_config):
    raw = raw_config if isinstance(raw_config, dict) else {}
    return {
        "base_url": str(raw.get("base_url") or raw.get("baseUrl") or "").strip(),
        "api_key": str(raw.get("api_key") or raw.get("apiKey") or "").strip(),
        "model": str(raw.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini",
    }


def _load_resume_llm_config():
    _ensure_app_storage()
    with APP_DATA_LOCK:
        raw = _read_json_file(RESUME_LLM_CONFIG_FILE, _default_resume_llm_config())
    return _normalized_resume_llm_config(raw)


def _save_resume_llm_config(config):
    _ensure_app_storage()
    normalized = _normalized_resume_llm_config(config)
    with APP_DATA_LOCK:
        _write_json_file(RESUME_LLM_CONFIG_FILE, normalized)
    return normalized


def _public_resume_llm_config(user):
    config = _load_resume_llm_config()
    api_key = str(config.get("api_key") or "")
    masked = (api_key[:4] + "****" + api_key[-4:]) if len(api_key) > 8 else ("已配置" if api_key else "")
    payload = {
        "editable": bool(user and user.get("role") == "super_admin"),
        "configured": bool(config.get("base_url") and api_key),
        "base_url": config.get("base_url") or "",
        "api_key_masked": masked,
        "model": config.get("model") or "gpt-4o-mini",
    }
    if user and user.get("role") == "super_admin":
        payload["api_key"] = api_key
    return payload


def _get_resume_provider_and_model():
    # 优先复用全局“API + 模型选择”，保证与其它模块一致。
    base_url, api_key, model = _get_active_provider_and_model()
    if base_url and api_key and model:
        return base_url, api_key, model

    # 兼容旧版独立简历配置，作为迁移兜底。
    config = _load_resume_llm_config()
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip() or "gpt-4o-mini"
    return base_url, api_key, model


# 新的多 Provider 数据层

def _normalized_provider(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": str(raw.get("id") or "").strip(),
        "name": str(raw.get("name") or "未命名").strip() or "未命名",
        "base_url": str(raw.get("base_url") or raw.get("baseUrl") or "").strip(),
        "api_key": str(raw.get("api_key") or raw.get("apiKey") or "").strip(),
    }


def _public_provider(provider, is_admin=False):
    api_key = str(provider.get("api_key") or "")
    masked = (api_key[:4] + "****" + api_key[-4:]) if len(api_key) > 8 else ("已配置" if api_key else "")
    result = {
        "id": provider.get("id"),
        "name": provider.get("name"),
        "base_url": provider.get("base_url"),
        "api_key_masked": masked,
        "configured": bool(provider.get("base_url") and api_key),
    }
    if is_admin:
        result["api_key"] = api_key
    return result


def _load_providers():
    """Load provider configs and transparently migrate legacy storage."""
    _ensure_app_storage()
    with APP_DATA_LOCK:
        # 优先读取独立 providers 文件。
        stored = _read_json_file(LLM_PROVIDERS_FILE, None)
        if stored is None:
            # 兼容旧文件：可能存的是 {"providers": [...]} 或旧 scope 结构。
            stored = _read_json_file(LLM_CONFIG_FILE, {})

    if not isinstance(stored, dict):
        return []

    # 旧格式迁移：如果有 career_interview 键，说明是旧数据。
    if "career_interview" in stored or "assessment_hub" in stored:
        ref = stored.get("career_interview") or stored.get("assessment_hub") or {}
        base_url = str(ref.get("base_url") or "").strip()
        api_key = str(ref.get("api_key") or "").strip()
        providers = []
        if base_url and api_key:
            providers.append({
                "id": str(uuid.uuid4())[:8],
                "name": "默认 API",
                "base_url": base_url,
                "api_key": api_key,
            })
        with APP_DATA_LOCK:
            _write_json_file(LLM_PROVIDERS_FILE, {"providers": providers})
        return providers

    raw_list = stored.get("providers") or []
    if not isinstance(raw_list, list):
        return []
    return [_normalized_provider(p) for p in raw_list if isinstance(p, dict) and p.get("id")]


def _save_providers(providers):
    normalized = [_normalized_provider(p) for p in providers if isinstance(p, dict) and p.get("id")]
    with APP_DATA_LOCK:
        _write_json_file(LLM_PROVIDERS_FILE, {"providers": normalized})
    return normalized
def _get_active_provider_and_model():
    """Read provider/model from session and fall back to the first configured provider."""
    selection = session.get("llm_selection") or {}
    provider_id = str(selection.get("provider_id") or "").strip()
    model = str(selection.get("model") or "").strip()

    providers = _load_providers()
    provider = None
    if provider_id:
        provider = next((p for p in providers if p.get("id") == provider_id), None)
    if not provider:
        provider = next((p for p in providers if p.get("base_url") and p.get("api_key")), None)
    if not provider:
        return None, None, None

    base_url = str(provider.get("base_url") or "").strip()
    api_key = str(provider.get("api_key") or "").strip()
    if not model:
        model = "deepseek-chat" if "deepseek" in base_url.lower() else "gpt-4o-mini"
    return base_url, api_key, model


def _get_profile_portrait_runtime():
    providers = _load_providers()
    provider = next(
        (
            item for item in providers
            if "openrouter.ai" in str(item.get("base_url") or "").strip().lower()
            and str(item.get("api_key") or "").strip()
        ),
        None,
    )
    if not provider:
        return None, None, PROFILE_PORTRAIT_MODEL
    return (
        str(provider.get("base_url") or "").strip(),
        str(provider.get("api_key") or "").strip(),
        PROFILE_PORTRAIT_MODEL,
    )


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


def _normalized_llm_config(raw_config):
    raw = raw_config if isinstance(raw_config, dict) else {}
    return {
        "base_url": str(raw.get("base_url") or raw.get("baseUrl") or "").strip(),
        "api_key": str(raw.get("api_key") or raw.get("apiKey") or "").strip(),
        "model": str(raw.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini",
    }


def _load_llm_configs():
    _ensure_app_storage()
    with APP_DATA_LOCK:
        stored = _read_json_file(LLM_CONFIG_FILE, {})
        configs = _default_llm_configs()
        if isinstance(stored, dict):
            for scope in VALID_LLM_CONFIG_SCOPES:
                configs[scope] = _normalized_llm_config(stored.get(scope))

        # If one scope is configured and the other is empty, keep them aligned.
        reference = next(
            (c for c in configs.values() if c.get("base_url") and c.get("api_key")),
            None,
        )
        if reference:
            changed = False
            for scope in VALID_LLM_CONFIG_SCOPES:
                c = configs[scope]
                if not (c.get("base_url") and c.get("api_key")):
                    c["base_url"] = reference["base_url"]
                    c["api_key"] = reference["api_key"]
                    if not c.get("model") or c["model"] in ("gpt-4o-mini",):
                        c["model"] = reference["model"]
                    changed = True
            if changed:
                _write_json_file(LLM_CONFIG_FILE, configs)

        if stored != configs:
            _write_json_file(LLM_CONFIG_FILE, configs)
        return configs


def _save_llm_configs(configs):
    _ensure_app_storage()
    normalized = _default_llm_configs()
    for scope in VALID_LLM_CONFIG_SCOPES:
        normalized[scope] = _normalized_llm_config(configs.get(scope))
    with APP_DATA_LOCK:
        _write_json_file(LLM_CONFIG_FILE, normalized)
    return normalized


def _normalized_user_record(raw_user):
    raw = raw_user if isinstance(raw_user, dict) else {}
    username = str(raw.get("username") or "").strip()
    if not username:
        return None
    return {
        "username": username,
        "password_hash": str(raw.get("password_hash") or "").strip(),
        "role": str(raw.get("role") or "user").strip() or "user",
        "display_name": str(raw.get("display_name") or raw.get("displayName") or username).strip() or username,
    }


def _load_users():
    global USERS_CACHE
    if USERS_CACHE is not None:
        return USERS_CACHE
    _ensure_app_storage()
    with APP_DATA_LOCK:
        raw_users = _read_json_file(USERS_FILE, [])
        merged = {}
        if isinstance(raw_users, list):
            for item in raw_users:
                normalized = _normalized_user_record(item)
                if normalized:
                    merged[normalized["username"]] = normalized

        for spec in DEFAULT_USER_SPECS:
            existing = merged.get(spec["username"]) or {}
            password_hash = str(existing.get("password_hash") or "").strip()
            # Avoid recomputing password hashes on every request.
            if not password_hash:
                password_hash = generate_password_hash(spec["password"])
            merged[spec["username"]] = {
                "username": spec["username"],
                "password_hash": password_hash,
                "role": spec["role"],
                "display_name": spec["display_name"],
            }

        users = sorted(merged.values(), key=lambda item: (item["role"] != "super_admin", item["username"]))
        if raw_users != users:
            _write_json_file(USERS_FILE, users)
        USERS_CACHE = users
        return USERS_CACHE


def _save_users(users):
    global USERS_CACHE
    normalized_users = []
    seen = set()
    for item in users if isinstance(users, list) else []:
        normalized = _normalized_user_record(item)
        if not normalized:
            continue
        username = normalized["username"]
        if username in seen:
            continue
        seen.add(username)
        normalized_users.append(normalized)
    normalized_users.sort(key=lambda item: (item["role"] != "super_admin", item["username"]))
    _ensure_app_storage()
    with APP_DATA_LOCK:
        _write_json_file(USERS_FILE, normalized_users)
    USERS_CACHE = normalized_users
    return USERS_CACHE


def _find_user(username):
    normalized_name = str(username or "").strip()
    if not normalized_name:
        return None
    for user in _load_users():
        if user["username"] == normalized_name:
            return user
    return None


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
    return _find_user(session.get("username"))


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


def _load_user_state(username):
    _ensure_app_storage()
    path = _user_state_path(username)
    with USER_STATE_LOCK:
        state = _read_json_file(path, {})
        return state if isinstance(state, dict) else {}


def _save_user_state(username, payload):
    _ensure_app_storage()
    normalized = payload if isinstance(payload, dict) else {}
    path = _user_state_path(username)
    with USER_STATE_LOCK:
        _write_json_file(path, normalized)
    return normalized


def _public_profile_portrait_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    image_url = str(state.get("image_url") or "").strip()
    if not image_url:
        return None
    return {
        "status": "ready",
        "image_url": image_url,
        "created_at": int(state.get("created_at") or 0),
        "model": str(state.get("model") or PROFILE_PORTRAIT_MODEL).strip() or PROFILE_PORTRAIT_MODEL,
        "archetype_name": str(state.get("archetype_name") or "").strip(),
        "prompt_summary": str(state.get("prompt_summary") or "").strip(),
        "prompt_text": str(state.get("prompt_text") or "").strip(),
    }


def _normalize_profile_portrait_context(raw_context):
    context = raw_context if isinstance(raw_context, dict) else {}
    def _clean_text(value, limit=220):
        return str(value or "").strip()[:limit]

    def _clean_list(values, limit=5, item_limit=48):
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        result = []
        for item in values:
            text = _clean_text(item, item_limit)
            if text:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    return {
        "gender": _clean_text(context.get("gender"), 16),
        "archetype_name": _clean_text(context.get("archetype_name"), 64),
        "archetype_scene": _clean_text(context.get("archetype_scene"), 64),
        "summary": _clean_text(context.get("summary"), 420),
        "mbti": _clean_text(context.get("mbti"), 32),
        "holland": _clean_text(context.get("holland"), 32),
        "holland_top_codes": _clean_list(context.get("holland_top_codes"), limit=3, item_limit=8),
        "major": _clean_text(context.get("major"), 64),
        "grade": _clean_text(context.get("grade"), 32),
        "target_city": _clean_text(context.get("target_city"), 32),
        "target_direction": _clean_text(context.get("target_direction"), 64),
        "role_cluster": _clean_list(context.get("role_cluster"), limit=4),
        "top_roles": _clean_list(context.get("top_roles"), limit=3),
        "work_values": _clean_list(context.get("work_values"), limit=4),
        "axis_traits": _clean_list(context.get("axis_traits"), limit=4, item_limit=48),
        "workstyle_traits": _clean_list(context.get("workstyle_traits"), limit=4, item_limit=48),
        "interview_summary": _clean_text(context.get("interview_summary"), 320),
        "interview_roles": _clean_list(context.get("interview_roles"), limit=4, item_limit=48),
        "interview_values": _clean_list(context.get("interview_values"), limit=5, item_limit=48),
        "interview_evidence": _clean_list(context.get("interview_evidence"), limit=4, item_limit=96),
        "resume_summary": _clean_text(context.get("resume_summary"), 320),
        "resume_roles": _clean_list(context.get("resume_roles"), limit=5, item_limit=48),
        "resume_signals": _clean_list(context.get("resume_signals"), limit=5, item_limit=48),
        "resume_projects": _clean_list(context.get("resume_projects"), limit=4, item_limit=120),
        "resume_experiences": _clean_list(context.get("resume_experiences"), limit=3, item_limit=96),
        "resume_skills": _clean_list(context.get("resume_skills"), limit=8, item_limit=32),
        "resume_competitions": _clean_list(context.get("resume_competitions"), limit=3, item_limit=64),
    }


def _normalize_profile_gender(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    mapping = {
        "男": "男性",
        "男性": "男性",
        "male": "男性",
        "man": "男性",
        "m": "男性",
        "女": "女性",
        "女性": "女性",
        "female": "女性",
        "woman": "女性",
        "f": "女性",
    }
    return mapping.get(text, str(value or "").strip())


def _join_unique_text(items, sep="、", limit=None):
    result = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(text)
        if limit and len(result) >= limit:
            break
    return sep.join(result)


def _infer_profile_portrait_age_hint(context):
    grade = str(context.get("grade") or "")
    if re.search(r"博士|phd", grade, re.IGNORECASE):
        return "24-30 岁"
    if re.search(r"硕士|研究生|研一|研二|研三|master", grade, re.IGNORECASE):
        return "23-27 岁"
    if re.search(r"大四|四年级|本科|本一|本二|本三|本四|senior", grade, re.IGNORECASE):
        return "21-25 岁"
    if re.search(r"大一|大二|大三|一年级|二年级|三年级|freshman|sophomore|junior", grade, re.IGNORECASE):
        return "18-23 岁"
    if context.get("resume_experiences") or context.get("resume_projects"):
        return "22-28 岁"
    return "20-26 岁"


def _describe_mbti_tendency(value):
    token = "".join(re.findall(r"[A-Za-z]", str(value or "").upper()))[:4]
    if len(token) != 4:
        return ""
    trait_map = {
        "E": "外向主动",
        "I": "内敛专注",
        "S": "务实细致",
        "N": "抽象探索",
        "T": "理性判断",
        "F": "共情敏锐",
        "J": "结构规划",
        "P": "灵活应变",
    }
    traits = [trait_map.get(letter, "") for letter in token if trait_map.get(letter)]
    if not traits:
        return token
    return f"{token} 倾向，整体更偏{_join_unique_text(traits, '、', 4)}"


def _describe_holland_tendency(code, top_codes=None):
    letters = []
    raw = "".join(re.findall(r"[A-Za-z]", str(code or "").upper()))
    for letter in raw:
        if letter not in letters:
            letters.append(letter)
    for item in top_codes or []:
        text = "".join(re.findall(r"[A-Za-z]", str(item or "").upper()))
        if text and text[0] not in letters:
            letters.append(text[0])
    letters = letters[:3]
    label_map = {
        "R": "动手实践",
        "I": "分析研究",
        "A": "创意表达",
        "S": "协作助人",
        "E": "组织推动",
        "C": "秩序执行",
    }
    labels = [label_map.get(letter, "") for letter in letters if label_map.get(letter)]
    if not letters and not labels:
        return ""
    joined_letters = "".join(letters)
    if not labels:
        return joined_letters
    return f"{joined_letters} 倾向，兴趣上更偏{_join_unique_text(labels, '、', 3)}"


def _infer_profile_portrait_visual_cues(context):
    combined = " ".join(
        [
            context.get("target_direction") or "",
            context.get("archetype_name") or "",
            context.get("archetype_scene") or "",
            _join_unique_text(context.get("top_roles"), " "),
            _join_unique_text(context.get("role_cluster"), " "),
            _join_unique_text(context.get("resume_roles"), " "),
            _join_unique_text(context.get("resume_skills"), " "),
        ]
    )
    if re.search(r"产品|项目|运营|行政|助理|协调|hr|人力|pm", combined, re.IGNORECASE):
        return {
            "outfit": "商务休闲穿搭，利落西装外套或针织叠穿",
            "props": "平板、笔记本、进度表或触控笔",
            "scene": "现代办公室、协作面板、轻度科技感管理界面",
            "mood": "沉稳、可靠、组织感强",
        }
    if re.search(r"数据|分析|财务|审计|研究|算法|开发|后端|测试|工程", combined, re.IGNORECASE):
        return {
            "outfit": "干净利落的职场穿搭，衬衫或简洁外套",
            "props": "笔记本电脑、数据报表、分析界面",
            "scene": "安静的办公桌面、数据图表屏幕、科技办公环境",
            "mood": "理性、专注、可信赖",
        }
    if re.search(r"设计|内容|新媒体|编辑|品牌|创意", combined, re.IGNORECASE):
        return {
            "outfit": "更有设计感的都市职业穿搭，简洁但有创意细节",
            "props": "数位板、便签、创意稿件或视觉素材",
            "scene": "创意工作台、品牌墙、轻量工作界面",
            "mood": "敏锐、清爽、有表达力",
        }
    if re.search(r"销售|客户|商务|市场", combined, re.IGNORECASE):
        return {
            "outfit": "偏正式的商务穿搭",
            "props": "手机、文件夹、演示资料",
            "scene": "会议室或商务洽谈空间",
            "mood": "自信、利落、有推进感",
        }
    return {
        "outfit": "清爽的职场青年穿搭，商务休闲风",
        "props": "平板或笔记本、工作记录工具",
        "scene": "现代办公空间与柔和科技感背景",
        "mood": "专业、克制、可信赖",
    }


def _build_profile_portrait_subject_summary(context):
    identity = []
    gender = _normalize_profile_gender(context.get("gender"))
    if gender:
        identity.append(gender)
    identity.append(_infer_profile_portrait_age_hint(context))
    identity.append("中国青年职场形象")
    role_focus = _join_unique_text(
        context.get("top_roles") or context.get("role_cluster") or [context.get("target_direction") or context.get("archetype_name")],
        " / ",
        3,
    )
    trait_parts = []
    if context.get("archetype_name"):
        trait_parts.append(context.get("archetype_name"))
    mbti_desc = _describe_mbti_tendency(context.get("mbti"))
    holland_desc = _describe_holland_tendency(context.get("holland"), context.get("holland_top_codes"))
    if mbti_desc:
        trait_parts.append(mbti_desc)
    if holland_desc:
        trait_parts.append(holland_desc)
    if context.get("work_values"):
        trait_parts.append(f"工作中看重{_join_unique_text(context.get('work_values'), '、', 4)}")
    if context.get("axis_traits"):
        trait_parts.append(f"工作方式偏向{_join_unique_text(context.get('axis_traits'), '；', 2)}")
    evidence_parts = []
    resume_summary = str(context.get("resume_summary") or "").strip()
    if resume_summary and resume_summary.lower() != "unknown":
        evidence_parts.append(f"简历显示{resume_summary}")
    if context.get("resume_projects"):
        evidence_parts.append(f"项目经历集中在{_join_unique_text(context.get('resume_projects'), '；', 2)}")
    if context.get("interview_summary"):
        evidence_parts.append(f"访谈体现出{context.get('interview_summary')}")
    elif context.get("interview_evidence"):
        evidence_parts.append(f"访谈证据包括{_join_unique_text(context.get('interview_evidence'), '；', 2)}")
    pieces = [
        "，".join([part for part in identity if part]),
        f"职业定位接近 {role_focus}" if role_focus else "",
        "；".join([part for part in trait_parts if part]),
        "；".join([part for part in evidence_parts if part]),
    ]
    return "。".join([piece for piece in pieces if piece])


def _has_profile_portrait_signal(context):
    return any(
        [
            context.get("summary"),
            context.get("archetype_name"),
            context.get("target_direction"),
            context.get("resume_summary"),
            context.get("interview_summary"),
            context.get("resume_projects"),
            context.get("resume_roles"),
            context.get("work_values"),
        ]
    )


def _build_profile_portrait_prompt(context):
    gender = _normalize_profile_gender(context.get("gender")) or "未指定"
    age_hint = _infer_profile_portrait_age_hint(context)
    archetype_name = context.get("archetype_name") or "综合支持者"
    role_focus = _join_unique_text(
        context.get("top_roles") or context.get("role_cluster") or [context.get("target_direction") or "职业探索方向"],
        " / ",
        3,
    )
    work_values = _join_unique_text(context.get("work_values"), "、", 4) or "成长、清晰感、执行落地"
    subject_summary = _build_profile_portrait_subject_summary(context)
    mbti_desc = _describe_mbti_tendency(context.get("mbti"))
    holland_desc = _describe_holland_tendency(context.get("holland"), context.get("holland_top_codes"))
    visual_cues = _infer_profile_portrait_visual_cues(context)
    detail_lines = [
        f"- 性别：{gender}",
        f"- 年龄感：{age_hint}",
        f"- 人物原型：{archetype_name}",
        f"- 目标职业场景：{role_focus}",
        f"- 综合摘要：{subject_summary or (context.get('summary') or '')}",
        f"- MBTI 信息：{mbti_desc}" if mbti_desc else "",
        f"- 霍兰德信息：{holland_desc}" if holland_desc else "",
        f"- 工作价值观：{work_values}",
        f"- 工作方式：{_join_unique_text(context.get('axis_traits'), '；', 3)}" if context.get("axis_traits") else "",
        f"- 工作风格拼图：{_join_unique_text(context.get('workstyle_traits'), '；', 3)}" if context.get("workstyle_traits") else "",
        f"- 访谈角色判断：{_join_unique_text(context.get('interview_roles'), '、', 3)}" if context.get("interview_roles") else "",
        f"- 访谈价值观证据：{_join_unique_text(context.get('interview_values'), '、', 4)}" if context.get("interview_values") else "",
        f"- 访谈关键证据：{_join_unique_text(context.get('interview_evidence'), '；', 2)}" if context.get("interview_evidence") else "",
        f"- 简历角色线索：{_join_unique_text(context.get('resume_roles'), '、', 4)}" if context.get("resume_roles") else "",
        f"- 简历项目线索：{_join_unique_text(context.get('resume_projects'), '；', 2)}" if context.get("resume_projects") else "",
        f"- 简历经历线索：{_join_unique_text(context.get('resume_experiences'), '；', 2)}" if context.get("resume_experiences") else "",
        f"- 简历技能关键词：{_join_unique_text(context.get('resume_skills'), '、', 6)}" if context.get("resume_skills") else "",
        f"- 专业：{context.get('major')}" if context.get("major") else "",
        f"- 学历：{context.get('grade')}" if context.get("grade") else "",
        f"- 目标城市：{context.get('target_city')}" if context.get("target_city") else "",
        f"- 目标方向：{context.get('target_direction')}" if context.get("target_direction") else "",
    ]
    detail_block = "\n".join([line for line in detail_lines if line])
    return (
        "请为职业规划仪表盘绘制一张 3:4 纵向人物画像插画，只出现 1 位人物，不要文字、不要水印、不要拼贴、不要重复面孔、不要多余手指。\n"
        "先把下面的人物信息融合成一个统一角色，再作画，不要机械堆叠标签，也不要把 MBTI、霍兰德字母直接画在画面里。\n"
        "人物信息：\n"
        f"{detail_block}\n"
        "视觉表达要求：\n"
        f"- 整体定位：中国年轻学生或职场新人，气质 {visual_cues['mood']}。\n"
        f"- 穿搭：{visual_cues['outfit']}。\n"
        f"- 道具：{visual_cues['props']}。\n"
        f"- 场景：{visual_cues['scene']}，可带轻度数据面板或协作界面氛围。\n"
        "- 构图：半身到三分之二身，人物居中或略偏左，主体突出。\n"
        "- 风格：精致数字插画，写实与动漫融合，光线柔和，高级企业海报质感，蓝白到青蓝渐变背景。\n"
        "- 氛围：冷静、聪明、可信赖，同时能让人看出其职业方向和工作方式。\n"
        "负面要求：低清晰度、背景杂乱、夸张卡通、过度赛博朋克、文字乱码、畸形手部、比例失衡。"
    )


def _generate_profile_portrait_image(base_url, api_key, model, prompt):
    if not base_url or not api_key:
        raise ValueError("系统中还没有可用的 OpenRouter 图片配置。")
    endpoint = f"{_normalize_sdk_base_url(base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "3:4"},
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail or "{}")
            message = str(parsed.get("error", {}).get("message") or parsed.get("message") or "").strip()
        except Exception:
            message = ""
        raise ValueError(message or f"图片接口调用失败：HTTP {exc.code}") from exc
    except Exception as exc:
        raise ValueError(f"图片接口调用失败：{str(exc)[:240]}") from exc

    try:
        result = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("图片接口返回了无法解析的数据。") from exc

    choices = result.get("choices") if isinstance(result, dict) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    images = message.get("images") if isinstance(message, dict) else []
    if not images:
        raise ValueError("模型没有返回图片结果。")
    image_url = str((((images[0] or {}).get("image_url") or {}).get("url")) or "").strip()
    if not image_url:
        raise ValueError("图片结果为空。")
    return image_url


def _career_report_user_dir(username):
    safe_name = re.sub(r"[^0-9A-Za-z_.-]", "_", str(username or "").strip())
    return os.path.join(CAREER_REPORT_DIR, safe_name)


def _career_report_file_paths(username):
    base_dir = _career_report_user_dir(username)
    return {
        "dir": base_dir,
        "json": os.path.join(base_dir, "latest.json"),
        "html": os.path.join(base_dir, "latest.html"),
        "md": os.path.join(base_dir, "latest.md"),
        "job": os.path.join(base_dir, "current_job.json"),
    }


def _read_career_report_bundle(username):
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        payload = _read_json_file(paths["json"], {})
    return payload if isinstance(payload, dict) else {}


def _save_career_report_bundle(username, bundle):
    paths = _career_report_file_paths(username)
    os.makedirs(paths["dir"], exist_ok=True)
    payload = bundle if isinstance(bundle, dict) else {}
    report_document = payload.get("report_document") if isinstance(payload.get("report_document"), dict) else {}
    markdown_text = str(report_document.get("markdown") or "")
    html_text = str(report_document.get("html") or "")
    new_meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    new_report_id = str(new_meta.get("report_id") or "").strip()
    versions_dir = os.path.join(paths["dir"], "versions")
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
        _write_json_file(paths["json"], payload)
        if markdown_text:
            with open(paths["md"], "w", encoding="utf-8") as fp:
                fp.write(markdown_text)
        if html_text:
            with open(paths["html"], "w", encoding="utf-8") as fp:
                fp.write(html_text)
        _write_json_file(paths["job"], {
            "report_id": str(payload.get("meta", {}).get("report_id") or ""),
            "generated_at": str(payload.get("meta", {}).get("generated_at") or ""),
            "title": str(payload.get("meta", {}).get("title") or ""),
        })
    return payload


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
            "model": str(raw_state.get("model") or ""),
            "generation_mode": str(raw_state.get("generation_mode") or ""),
            "focus_role_id": str(raw_state.get("focus_role_id") or ""),
            "title": str(raw_state.get("title") or ""),
            "summary": str(raw_state.get("summary") or ""),
            "export_formats": raw_state.get("export_formats") if isinstance(raw_state.get("export_formats"), list) else ["html", "md"],
            "tracker": raw_state.get("tracker") if isinstance(raw_state.get("tracker"), dict) else None,
        })
    return state


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
        })
    return job


def _public_career_report_bundle(raw_bundle):
    bundle = raw_bundle if isinstance(raw_bundle, dict) else {}
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    public_document = dict(document)
    public_document.pop("markdown", None)
    public_document.pop("html", None)
    return {
        "meta": meta,
        "profile_snapshot": bundle.get("profile_snapshot") if isinstance(bundle.get("profile_snapshot"), dict) else {},
        "role_rankings": bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else [],
        "gap_map": bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {},
        "phase_plan": bundle.get("phase_plan") if isinstance(bundle.get("phase_plan"), dict) else {},
        "trend_brief": bundle.get("trend_brief") if isinstance(bundle.get("trend_brief"), dict) else {},
        "report_document": public_document,
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


def _build_career_report_tracker(bundle, existing_tracker=None, current_capabilities=None):
    if not isinstance(bundle, dict):
        return None

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_id = str(meta.get("report_id") or "").strip()
    if not report_id:
        return None

    existing = existing_tracker if isinstance(existing_tracker, dict) else {}
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
    raw_plan_items.extend(phase_plan.get("short_term") or [])
    raw_plan_items.extend(phase_plan.get("long_term") or [])
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
    task_items = [item for item in plan_items if item.get("is_task")]
    phase_items = [item for item in plan_items if item.get("is_phase")]
    trackable = task_items if task_items else phase_items
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
        or str(existing.get("focus_role_name") or "")
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

    next_focus = next((item.get("title") for item in plan_items if item.get("status") != "done"), "")
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
    }


def _sync_career_report_tracker_state(username, bundle, current_capabilities=None):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    tracker = _build_career_report_tracker(bundle, report_state.get("tracker"), current_capabilities)
    meta = bundle.get("meta") if isinstance(bundle, dict) and isinstance(bundle.get("meta"), dict) else {}

    if meta and str(report_state.get("status") or "") not in {"running", "queued"}:
        report_state.update(
            {
                "status": "ready",
                "report_id": str(meta.get("report_id") or report_state.get("report_id") or ""),
                "generated_at": str(meta.get("generated_at") or report_state.get("generated_at") or ""),
                "focus_role_id": str(meta.get("focus_role_id") or report_state.get("focus_role_id") or ""),
                "title": str(meta.get("title") or report_state.get("title") or ""),
                "summary": str(meta.get("summary") or report_state.get("summary") or ""),
                "export_formats": ["html", "md"],
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


def _save_career_report_progress(username, job_id, stage, stage_label, detail, **extra):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    report_state.update(
        {
            "status": extra.get("status") or "running",
            "job_id": job_id,
            "stage": stage,
            "stage_label": stage_label,
            "stage_detail": detail,
            "progress": build_stage_progress(stage),
            "error_message": str(extra.get("error_message") or ""),
            "generated_at": str(extra.get("generated_at") or report_state.get("generated_at") or ""),
            "report_id": str(extra.get("report_id") or report_state.get("report_id") or ""),
            "model": str(extra.get("model") or report_state.get("model") or ""),
            "generation_mode": str(extra.get("generation_mode") or report_state.get("generation_mode") or ""),
            "focus_role_id": str(extra.get("focus_role_id") or report_state.get("focus_role_id") or ""),
            "title": str(extra.get("title") or report_state.get("title") or ""),
            "summary": str(extra.get("summary") or report_state.get("summary") or ""),
            "export_formats": ["html", "md"],
        }
    )
    state["career_report"] = report_state
    _save_user_state(username, state)


def _build_report_markdown_writer(base_url, api_key, model):
    if not (base_url and api_key and model):
        return None

    def _writer(payload, system_prompt):
        message = [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        return _call_markdown_chat(
            base_url,
            api_key,
            model,
            message,
            system_prompt=system_prompt,
            max_tokens=2200,
        )

    return _writer


def _user_upload_dir(username):
    safe_name = re.sub(r"[^0-9A-Za-z_.-]", "_", str(username or "").strip())
    return os.path.join(RESUME_UPLOAD_DIR, safe_name)


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
    saved_name = f"{int(time.time())}_{safe}"
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
    except Exception:
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
    except Exception:
        primary_text = ""
    primary_score = _resume_text_quality_score(primary_text)
    if primary_score >= 900:
        return _normalize_resume_text(primary_text)

    prepared_image = _prepare_resume_ocr_image(image)
    if prepared_image is image:
        return _normalize_resume_text(primary_text)

    try:
        fallback_text = pytesseract.image_to_string(prepared_image, lang=lang, config="--oem 3 --psm 6")
    except Exception:
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
        except Exception:
            pass

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
                        except Exception:
                            continue
                    text = max(variants, key=_resume_text_quality_score, default="")
                    text = _normalize_resume_text(text)
                    if text:
                        plumber_pages.append({"page_no": idx, "source": "pdfplumber", "text": text})
        except Exception:
            pass

    pymupdf_pages = []
    if fitz is not None:
        try:
            with fitz.open(pdf_path) as doc:
                for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                    text = _normalize_resume_text(doc[idx].get_text("text") or "")
                    if text:
                        pymupdf_pages.append({"page_no": idx + 1, "source": "pymupdf", "text": text})
        except Exception:
            pass

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
    except Exception:
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


def _analyze_resume_matcher(storage_path, job_description, progress_callback=None, runtime_llm=None):
    def _report(stage, detail):
        if callable(progress_callback):
            try:
                progress_callback(stage, detail)
            except Exception:
                pass

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
        raise ValueError("模型尚未就绪，请先完成接口配置和模型选择。")
    if not model:
        model = "gpt-4o-mini"

    _report("structured_resume", "正在提取结构化简历")
    resume_schema_json = json.dumps(STRUCTURED_RESUME_SCHEMA, ensure_ascii=False, indent=2)
    structured_resume = _call_structured_chat(
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
        analysis_markdown = _call_markdown_chat(
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
        analysis_markdown = _call_markdown_chat(
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
    analysis_meta = dict(text_payload.get("analysis_meta") or {})
    analysis_meta.update(
        {
            "parsed_at": int(time.time()),
            "job_description_length": len(job_text),
            "analysis_mode": analysis_mode,
            "model": model,
            "resume_keyword_count": len((matcher_state.get("matcher") or {}).get("resume_keywords") or []),
            "job_keyword_count": len((matcher_state.get("matcher") or {}).get("job_keywords") or []),
        }
    )
    return matcher_state, analysis_meta


def _public_resume_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    return {
        "file_name": state.get("file_name") or "",
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


def _public_llm_config(scope, user):
    configs = _load_llm_configs()
    config = configs.get(scope) or {}
    configured = bool(config.get("base_url") and config.get("api_key"))
    payload = {
        "scope": scope,
        "editable": bool(user and user.get("role") == "super_admin"),
        "configured": configured,
        "model": config.get("model") or "gpt-4o-mini",
        "api_key_masked": "",
    }
    api_key = str(config.get("api_key") or "")
    if api_key:
        payload["api_key_masked"] = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "已配置"
    if user and user.get("role") == "super_admin":
        payload["base_url"] = config.get("base_url") or ""
        payload["api_key"] = api_key
    return payload

def _list_city_files():
    if not os.path.isdir(BOSS_INFO_DIR):
        return []
    return sorted(f for f in os.listdir(BOSS_INFO_DIR) if f.endswith(".json"))


def _job_id(city, index):
    return f"{city}:{index}"


def _cache_json_response(payload, max_age=JOB_CACHE_MAX_AGE_SECONDS, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response


def _get_city_cache_entry(city):
    city_name = str(city or "").strip()
    if not city_name:
        raise FileNotFoundError("city is required")

    fname = f"{city_name}.json"
    fpath = os.path.join(BOSS_INFO_DIR, fname)
    if not os.path.exists(fpath):
        raise FileNotFoundError(fname)

    stat = os.stat(fpath)
    signature = (stat.st_mtime_ns, stat.st_size)

    with JOB_CACHE_LOCK:
        cached = JOB_FILE_CACHE.get(city_name)
        if cached and cached.get("signature") == signature:
            return cached

    with open(fpath, "r", encoding="utf-8") as fp:
        jobs = json.load(fp)

    entry = {
        "signature": signature,
        "jobs": jobs,
        "summaries": None,
    }
    with JOB_CACHE_LOCK:
        JOB_FILE_CACHE[city_name] = entry
    return entry


def _summarize_job(job, city, index):
    summary = {
        key: value
        for key, value in job.items()
        if key not in JOB_DETAIL_ONLY_FIELDS
    }
    summary["job_id"] = _job_id(city, index)
    return summary


def _get_city_job_summaries(city):
    entry = _get_city_cache_entry(city)
    if entry.get("summaries") is None:
        entry["summaries"] = [
            _summarize_job(job, city, index)
            for index, job in enumerate(entry["jobs"])
        ]
    return entry["summaries"]


def _get_city_job_detail(city, index):
    entry = _get_city_cache_entry(city)
    if index < 0 or index >= len(entry["jobs"]):
        raise IndexError(index)
    detail = dict(entry["jobs"][index])
    detail["job_id"] = _job_id(city, index)
    return detail


def _truncate_text(value, limit=140):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _compact_list(items, limit=4, item_limit=60):
    values = []
    for item in items or []:
        text = _truncate_text(item, item_limit)
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _guess_mbti_type_from_scores(score_snapshot):
    if not isinstance(score_snapshot, dict):
        return ""
    pairs = [("E", "I", "EI"), ("S", "N", "SN"), ("T", "F", "TF"), ("J", "P", "JP")]
    decided = []
    for left, right, pair_key in pairs:
        left_score = float(score_snapshot.get(left) or 0)
        right_score = float(score_snapshot.get(right) or 0)
        if left_score > right_score:
            decided.append(left)
        elif right_score > left_score:
            decided.append(right)
        else:
            decided.append({"EI": "I", "SN": "N", "TF": "F", "JP": "P"}[pair_key])
    return "".join(decided)


def _normalize_assessment_context(raw_context):
    raw = raw_context if isinstance(raw_context, dict) else {}
    mbti_raw = raw.get("mbti") if isinstance(raw.get("mbti"), dict) else {}
    holland_raw = raw.get("holland") if isinstance(raw.get("holland"), dict) else {}
    basics_raw = raw.get("basics") if isinstance(raw.get("basics"), dict) else {}
    return {
        "mbti": {
            "raw_type": _truncate_text(mbti_raw.get("raw_type") or mbti_raw.get("rawType") or "", 16),
            "final_type": _truncate_text(mbti_raw.get("final_type") or mbti_raw.get("finalType") or "", 16),
            "summary": _truncate_text(mbti_raw.get("summary") or "", 160),
            "top_strengths": _compact_list(mbti_raw.get("top_strengths") or mbti_raw.get("topStrengths"), limit=3, item_limit=40),
            "top_risks": _compact_list(mbti_raw.get("top_risks") or mbti_raw.get("topRisks"), limit=3, item_limit=40),
        },
        "holland": {
            "code": _truncate_text(holland_raw.get("code") or "", 12),
            "top_codes": _compact_list(holland_raw.get("top_codes") or holland_raw.get("topCodes"), limit=3, item_limit=8),
            "summary": _truncate_text(holland_raw.get("summary") or "", 160),
            "interests": _compact_list(holland_raw.get("interests"), limit=4, item_limit=40),
        },
        "basics": {
            "major": _truncate_text(basics_raw.get("major") or "", 40),
            "grade": _truncate_text(basics_raw.get("grade") or basics_raw.get("education_level") or "", 20),
            "target_city": _truncate_text(basics_raw.get("target_city") or basics_raw.get("targetCity") or "", 20),
            "target_direction": _truncate_text(basics_raw.get("target_direction") or basics_raw.get("targetDirection") or "", 30),
        },
    }


def _build_mbti_clarifier_prompt(close_pairs, score_snapshot):
    base_prompt = MBTI_CLARIFIER_SYSTEM_PROMPT
    pairs = close_pairs if isinstance(close_pairs, list) else []
    notes = []
    for item in pairs[:4]:
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "").upper().strip()
        diff = item.get("diff")
        if not pair:
            continue
        if diff is None:
            notes.append(f"临界维度：{pair}")
        else:
            notes.append(f"临界维度：{pair}，当前差值 {diff}")
    if not notes:
        return base_prompt
    return f"{base_prompt}\n\n补充上下文：\n- " + "\n- ".join(notes)


def _build_career_interview_prompt(assessment_context):
    base_prompt = CAREER_INTERVIEW_SYSTEM_PROMPT
    context = _normalize_assessment_context(assessment_context)
    mbti = context["mbti"]
    holland = context["holland"]
    basics = context["basics"]
    notes = []

    basics_parts = [
        f"专业 {basics['major']}" if basics["major"] else "",
        f"学历 {basics['grade']}" if basics["grade"] else "",
        f"目标城市 {basics['target_city']}" if basics["target_city"] else "",
        f"目标方向 {basics['target_direction']}" if basics["target_direction"] else "",
    ]
    basics_parts = [part for part in basics_parts if part]
    if basics_parts:
        notes.append("基础信息：" + "，".join(basics_parts))

    mbti_type = mbti["final_type"] or mbti["raw_type"]
    if mbti_type:
        notes.append(f"MBTI：{mbti_type}")
    if mbti.get("summary"):
        notes.append(f"MBTI 摘要：{_truncate_text(mbti.get('summary'), 80)}")

    holland_code = holland["code"] or ("".join(holland["top_codes"]) if holland["top_codes"] else "")
    if holland_code:
        notes.append(f"Holland：{holland_code}")
    if holland.get("summary"):
        notes.append(f"Holland 摘要：{_truncate_text(holland.get('summary'), 80)}")

    if not notes:
        return base_prompt
    return f"{base_prompt}\n\n补充上下文：\n- " + "\n- ".join(notes)


def _safe_score(value, default=0):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _normalize_sdk_base_url(base_url):
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url 必须是完整的 http(s) 地址")
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]
    if cleaned.endswith("/v1"):
        return cleaned
    return f"{cleaned}/v1"


def _extract_json_object(text):
    if not text:
        raise ValueError("模型没有返回可解析内容。")
    cleaned = str(text).strip()
    # 兼容 ```json ... ``` 包裹输出。
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("模型返回中没有可解析的 JSON 对象。")
    return match.group(0)


def _parse_structured_json(content):
    raw = str(content or "").strip()
    if not raw:
        raise ValueError("模型没有返回可解析内容。")
    # 1) 直接按 JSON 解析。
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 2) 提取 JSON 对象后再解析。
    extracted = _extract_json_object(raw)
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        # 3) 本地轻度修复：去掉对象/数组尾逗号后再试。
        repaired = re.sub(r",(\s*[}\]])", r"\1", extracted)
        return json.loads(repaired)


# 网络级瞬态错误关键字，命中则触发重试（不含业务错误如鉴权失败）。
_TRANSIENT_ERROR_KEYWORDS = (
    "connection", "timeout", "timed out", "reset", "broken pipe",
    "eof", "remote end closed", "server disconnected", "read timeout",
    "connect timeout", "service unavailable", "502", "503", "504",
    "overloaded", "rate limit", "too many requests", "429",
)

def _is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in _TRANSIENT_ERROR_KEYWORDS)

def _safe_create_chat_completion(
    client, model, messages, temperature, max_tokens,
    force_json=False,
    max_retries=3,
    base_delay=1.5,
):
    """
    调用 chat.completions.create，对瞬态网络错误做指数退避重试。
    - max_retries: 最多额外重试次数（首次调用不计）
    - base_delay:  首次重试前的基础等待秒数，每次翻倍并加随机抖动
    """
    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()

            # response_format 不兼容 — 只重试一次，不计入重试次数
            if force_json and ("response_format" in msg or "json_object" in msg):
                kwargs.pop("response_format", None)
                try:
                    return client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    last_exc = exc2
                    msg = str(exc2).lower()

            # 非瞬态错误（如鉴权、模型不存在）直接抛出，不重试
            if not _is_transient_error(last_exc):
                raise

            # 最后一次也失败了
            if attempt >= max_retries:
                break

            delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.8)
            time.sleep(delay)

    raise last_exc


def _normalize_profile(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}

    dimension_map = {}
    for item in profile.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        dimension_map[name] = {
            "name": name,
            "score": _safe_score(item.get("score"), 0),
            "evidence": str(item.get("evidence") or "").strip(),
        }

    dimensions = []
    for name in DEFAULT_CAREER_DIMENSIONS:
        dimensions.append(
            dimension_map.get(name)
            or {
                "name": name,
                "score": 0,
                "evidence": "",
            }
        )

    riasec = profile.get("riasec") if isinstance(profile.get("riasec"), dict) else {}
    normalized = {
        "next_question": str(payload.get("next_question") or "").strip(),
        "focus_dimension": str(payload.get("focus_dimension") or "职业兴趣").strip() or "职业兴趣",
        "is_complete": bool(payload.get("is_complete")),
        "completion_score": _safe_score(payload.get("completion_score"), 0),
        "profile": {
            "summary": str(profile.get("summary") or "").strip(),
            "career_interests": [str(item).strip() for item in (profile.get("career_interests") or []) if str(item).strip()][:6],
            "work_values": [str(item).strip() for item in (profile.get("work_values") or []) if str(item).strip()][:6],
            "recommended_roles": [str(item).strip() for item in (profile.get("recommended_roles") or []) if str(item).strip()][:6],
            "evidence_highlights": [str(item).strip() for item in (profile.get("evidence_highlights") or []) if str(item).strip()][:6],
            "next_steps": [str(item).strip() for item in (profile.get("next_steps") or []) if str(item).strip()][:6],
            "riasec": {
                "realistic": _safe_score(riasec.get("realistic"), 0),
                "investigative": _safe_score(riasec.get("investigative"), 0),
                "artistic": _safe_score(riasec.get("artistic"), 0),
                "social": _safe_score(riasec.get("social"), 0),
                "enterprising": _safe_score(riasec.get("enterprising"), 0),
                "conventional": _safe_score(riasec.get("conventional"), 0),
            },
            "dimensions": dimensions,
        },
    }

    if not normalized["profile"]["summary"]:
        normalized["profile"]["summary"] = "访谈已启动，系统正在根据回答逐步生成职业兴趣画像。"

    if not normalized["next_question"] and not normalized["is_complete"]:
        normalized["next_question"] = "请继续补充一个能体现你职业兴趣或偏好的真实经历。"

    if normalized["is_complete"] and not normalized["completion_score"]:
        normalized["completion_score"] = 100

    normalized["assistant_reply"] = (
        normalized["next_question"]
        if not normalized["is_complete"]
        else "访谈完成，我已经整理出你的职业兴趣画像。"
    )
    return normalized


def _call_structured_chat(base_url, api_key, model, messages, system_prompt, max_tokens=480,
                          max_retries=3, base_delay=1.5):
    base = _normalize_sdk_base_url(base_url)
    client = OpenAI(api_key=api_key, base_url=base)
    try:
        merged_messages = [{"role": "system", "content": system_prompt}] + messages
        resp = _safe_create_chat_completion(
            client=client,
            model=model,
            messages=merged_messages,
            temperature=0.1,
            max_tokens=max_tokens,
            force_json=True,
            max_retries=max_retries,
            base_delay=base_delay,
        )
    except Exception as exc:
        raise ValueError(f"LLM 接口调用失败: {str(exc)[:300]}") from exc

    content = str((resp.choices[0].message.content or "") if resp.choices else "").strip()
    if not content:
        raise ValueError("模型没有返回可解析内容。")
    try:
        return _parse_structured_json(content)
    except Exception:
        # 第一次失败：让模型只做 JSON 修复，不做新推理。
        repair_prompt = (
            "你是 JSON 修复器。请把下面的文本修复为严格合法的 JSON 对象。"
            "只能输出 JSON 对象本身，不要解释，不要 Markdown。"
        )
        repair_messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": content},
        ]
        try:
            repair_resp = _safe_create_chat_completion(
                client=client,
                model=model,
                messages=repair_messages,
                temperature=0,
                max_tokens=min(max_tokens + 600, 3800),
                force_json=True,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            repair_content = str((repair_resp.choices[0].message.content or "") if repair_resp.choices else "").strip()
            return _parse_structured_json(repair_content)
        except Exception:
            pass

        # 第二次失败：重新生成，并附加强约束和更高 token 上限。
        strict_system = (
            system_prompt
            + "\n\n严格要求：必须返回合法 JSON 对象。"
            + "不要输出注释、代码块、尾逗号或未转义换行。"
        )
        retry_messages = [{"role": "system", "content": strict_system}] + messages
        try:
            retry_resp = _safe_create_chat_completion(
                client=client,
                model=model,
                messages=retry_messages,
                temperature=0.05,
                max_tokens=min(max_tokens + 800, 4096),
                force_json=True,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            retry_content = str((retry_resp.choices[0].message.content or "") if retry_resp.choices else "").strip()
            return _parse_structured_json(retry_content)
        except Exception as exc:
            raise ValueError(f"结构化 JSON 解析失败: {str(exc)[:280]}") from exc


def _call_markdown_chat(base_url, api_key, model, messages, system_prompt=None, max_tokens=3200,
                        max_retries=3, base_delay=1.5):
    base = _normalize_sdk_base_url(base_url)
    client = OpenAI(api_key=api_key, base_url=base)
    merged_messages = list(messages or [])
    if system_prompt:
        merged_messages = [{"role": "system", "content": system_prompt}] + merged_messages
    try:
        resp = _safe_create_chat_completion(
            client=client,
            model=model,
            messages=merged_messages,
            temperature=0.2,
            max_tokens=max_tokens,
            force_json=False,
            max_retries=max_retries,
            base_delay=base_delay,
        )
    except Exception as exc:
        raise ValueError(f"LLM 接口调用失败: {str(exc)[:300]}") from exc

    content = str((resp.choices[0].message.content or "") if resp.choices else "").strip()
    if not content:
        raise ValueError("模型没有返回可解析内容。")
    return content


def _call_openai_compatible_chat(base_url, api_key, model, messages, system_prompt=None):
    parsed = _call_structured_chat(
        base_url,
        api_key,
        model,
        messages,
        system_prompt=system_prompt or CAREER_INTERVIEW_SYSTEM_PROMPT,
        max_tokens=480,
    )
    return _normalize_profile(parsed)


def _normalize_mbti_clarifier_payload(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    questions = []
    for index, item in enumerate(payload.get("questions") or [], start=1):
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "").upper().replace("/", "").strip()
        if pair not in {"EI", "SN", "TF", "JP"}:
            continue
        question = str(item.get("question") or "").strip()
        option_a = str(item.get("option_a") or "").strip()
        option_b = str(item.get("option_b") or "").strip()
        if not question or not option_a or not option_b:
            continue
        weight = _safe_score(item.get("weight"), 2)
        weight = max(1, min(3, weight))
        questions.append(
            {
                "id": str(item.get("id") or f"q{index}").strip() or f"q{index}",
                "pair": pair,
                "question": question,
                "option_a": option_a,
                "option_b": option_b,
                "weight": weight,
            }
        )

    if not questions:
        raise ValueError("模型未返回可用的 MBTI 澄清题目。")

    return {
        "summary": str(payload.get("summary") or "本轮补充题将帮助确认临界维度。").strip()
        or "本轮补充题将帮助确认临界维度。",
        "questions": questions[:6],
    }

# 页面与认证接口
@app.route("/")
@app.route("/main.html")
def index():
    user = _current_user()
    return render_template(
        "base.html",
        career_news=get_career_news_payload(),
        initial_user=_public_user(user),
    )


@app.route("/user-center")
@app.route("/user-center.html")
def user_center_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("user_center.html")


@app.route("/resume-report")
@app.route("/resume-report.html")
def resume_report_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("resume_report.html")


@app.route("/test-result")
@app.route("/test-result.html")
def test_result_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("test_result.html")


@app.route("/test-runner")
@app.route("/test-runner.html")
def test_runner_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("test_runner.html")


@app.route("/api/auth/status")
def api_auth_status():
    user = _current_user()
    payload = {
        "authenticated": bool(user),
        "user": _public_user(user),
    }
    bootstrap_mode = str(request.args.get("bootstrap", "") or "").strip().lower() in {"1", "true", "yes"}
    if bootstrap_mode and user:
        providers = _load_providers()
        is_admin = user.get("role") == "super_admin"
        selection = session.get("llm_selection") or {}
        if not selection:
            state_for_selection = _load_user_state(user["username"])
            persisted = state_for_selection.get("llm_selection") if isinstance(state_for_selection.get("llm_selection"), dict) else {}
            selection = persisted or {}
        if selection.get("provider_id") and not any(p.get("id") == selection["provider_id"] for p in providers):
            selection = {}
        session["llm_selection"] = selection
        session.modified = True

        state = _load_user_state(user["username"])
        resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
        career_report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
        payload["llm"] = {
            "selection": selection,
            "providers": [_public_provider(p, is_admin) for p in providers],
            "configs": {
                "career_interview": _public_llm_config("career_interview", user),
            },
        }
        payload["scoped_data"] = {
            "career_interview": state.get("career_interview"),
            "assessment_hub": state.get("assessment_hub"),
            "resume_profile": _public_resume_state(resume_state),
            "career_report": _public_career_report_state(career_report_state),
        }
    return jsonify(payload)


@app.route("/api/bootstrap")
def api_bootstrap():
    """Bootstrap current user, providers, and cached scoped data for the frontend."""
    user = _current_user()
    if not user:
        return jsonify({"authenticated": False, "user": None})

    providers = _load_providers()
    is_admin = user.get("role") == "super_admin"
    selection = session.get("llm_selection") or {}
    if not selection:
        state_for_selection = _load_user_state(user["username"])
        persisted = state_for_selection.get("llm_selection") if isinstance(state_for_selection.get("llm_selection"), dict) else {}
        selection = persisted or {}
    if selection.get("provider_id") and not any(p.get("id") == selection["provider_id"] for p in providers):
        selection = {}
    session["llm_selection"] = selection
    session.modified = True

    state = _load_user_state(user["username"])
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    career_report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}

    return jsonify({
        "authenticated": True,
        "user": _public_user(user),
        "llm": {
            "selection": selection,
            "providers": [_public_provider(p, is_admin) for p in providers],
            "configs": {
                "career_interview": _public_llm_config("career_interview", user),
            },
        },
        "scoped_data": {
            "career_interview": state.get("career_interview"),
            "assessment_hub": state.get("assessment_hub"),
            "resume_profile": _public_resume_state(resume_state),
            "career_report": _public_career_report_state(career_report_state),
        },
    })


@app.route("/api/career-news")
def api_career_news():
    force_refresh = str(request.args.get("refresh", "") or "").strip().lower() in {"1", "true", "yes"}
    payload = get_career_news_payload(force_refresh=force_refresh)
    return _cache_json_response(payload, max_age=300)


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return jsonify({"message": "请输入用户名和密码。"}), 400

    user = _find_user(username)
    if not user or not check_password_hash(user.get("password_hash") or "", password):
        return jsonify({"message": "用户名或密码错误。"}), 401

    session.clear()
    session.permanent = True
    session["username"] = user["username"]
    return jsonify({
        "message": "登录成功",
        "user": _public_user(user),
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"message": "已退出登录。"})


@app.route("/api/auth/password", methods=["PUT"])
@_login_required
def api_auth_password():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")
    confirm_password = str(payload.get("confirm_password") or "")

    if not current_password or not new_password or not confirm_password:
        return jsonify({"message": "请完整填写当前密码、新密码和确认密码。"}), 400
    if not check_password_hash(user.get("password_hash") or "", current_password):
        return jsonify({"message": "当前密码不正确。"}), 400
    if len(new_password) < 6:
        return jsonify({"message": "新密码至少需要 6 位。"}), 400
    if new_password != confirm_password:
        return jsonify({"message": "两次输入的新密码不一致。"}), 400
    if new_password == current_password:
        return jsonify({"message": "新密码不能与当前密码相同。"}), 400

    users = _load_users()
    updated_users = []
    for item in users:
        next_item = dict(item)
        if item.get("username") == user["username"]:
            next_item["password_hash"] = generate_password_hash(new_password)
        updated_users.append(next_item)
    _save_users(updated_users)
    return jsonify({"message": "密码已更新。"})


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


@app.route("/api/profile-portrait/generate", methods=["POST"])
@_login_required
def api_profile_portrait_generate():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    context = _normalize_profile_portrait_context(payload.get("context"))
    if not _has_profile_portrait_signal(context):
        return jsonify({"message": "当前画像信息不足，先补充测评、简历或目标方向。"}), 400

    base_url, api_key, model = _get_profile_portrait_runtime()
    if not base_url or not api_key:
        return jsonify({"message": "系统中未找到 OpenRouter 图片配置，请先在 system 账号里配置 OpenRouter Provider。"}), 400

    try:
        prompt_summary = _build_profile_portrait_subject_summary(context) or context.get("summary") or ""
        prompt = _build_profile_portrait_prompt(context)
        image_url = _generate_profile_portrait_image(base_url, api_key, model, prompt)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception:
        app.logger.exception("profile portrait generation failed")
        return jsonify({"message": "用户画像生成失败，请稍后重试。"}), 502

    portrait_state = {
        "status": "ready",
        "image_url": image_url,
        "created_at": int(time.time()),
        "model": model,
        "archetype_name": context.get("archetype_name") or "",
        "prompt_summary": prompt_summary,
        "prompt_text": prompt,
    }
    state = _load_user_state(user["username"])
    state["profile_portrait"] = portrait_state
    _save_user_state(user["username"], state)
    return jsonify({
        "message": "用户画像已生成。",
        "data": _public_profile_portrait_state(portrait_state),
    })


@app.route("/api/llm-config/<scope>", methods=["GET"])
@_login_required
def api_llm_config(scope):
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in VALID_LLM_CONFIG_SCOPES:
        return jsonify({"message": "未知的模型配置类型。"}), 404
    return jsonify(_public_llm_config(normalized_scope, _current_user()))


@app.route("/api/llm-config/<scope>", methods=["PUT"])
@_super_admin_required
def api_update_llm_config(scope):
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in VALID_LLM_CONFIG_SCOPES:
        return jsonify({"message": "未知的模型配置类型。"}), 404

    payload = request.get_json(silent=True) or {}
    configs = _load_llm_configs()
    configs[normalized_scope] = _normalized_llm_config(payload)
    _save_llm_configs(configs)
    return jsonify(_public_llm_config(normalized_scope, _current_user()))


@app.route("/api/llm-config/model", methods=["PUT"])
@_login_required
def api_update_llm_model():
    """Update the selected model for all editable LLM config scopes."""
    payload = request.get_json(silent=True) or {}
    model = str(payload.get("model") or "").strip()
    if not model:
        return jsonify({"message": "请指定模型名称。"}), 400
    configs = _load_llm_configs()
    for scope in VALID_LLM_CONFIG_SCOPES:
        configs[scope]["model"] = model
    _save_llm_configs(configs)
    return jsonify({"model": model, "message": "模型已更新。"})


def _do_fetch_models(base_url, api_key):
    try:
        base = _normalize_sdk_base_url(base_url)
    except ValueError as exc:
        return jsonify({"models": [], "message": str(exc)}), 200

    try:
        client = OpenAI(api_key=api_key, base_url=base)
        data = client.models.list()
        models = [str(item.id) for item in getattr(data, "data", []) if getattr(item, "id", None)]
        return jsonify({"models": sorted(set(m for m in models if m))})
    except Exception as exc:
        return jsonify({"models": [], "message": f"获取模型列表失败: {str(exc)[:300]}"}), 200


@app.route("/api/llm-models", methods=["GET"])
@_login_required
def api_llm_models():
    """Fetch models using the currently stored provider credentials."""
    configs = _load_llm_configs()
    config = configs.get("career_interview") or {}
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"models": [], "message": "API 尚未配置，请先填写 Base URL 和 API Key。"}), 200
    return _do_fetch_models(base_url, api_key)


@app.route("/api/llm-models/preview", methods=["POST"])
@_super_admin_required
def api_llm_models_preview():
    """Preview models for a temporary provider config without saving it."""
    payload = request.get_json(silent=True) or {}
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"message": "请先填写 Base URL 和 API Key。"}), 400
    return _do_fetch_models(base_url, api_key)


# API：Provider 管理

@app.route("/api/llm-providers", methods=["GET"])
@_login_required
def api_list_providers():
    providers = _load_providers()
    is_admin = (_current_user() or {}).get("role") == "super_admin"
    return jsonify({
        "providers": [_public_provider(p, is_admin) for p in providers],
        "selection": session.get("llm_selection") or {}
    })


@app.route("/api/llm-providers", methods=["POST"])
@_super_admin_required
def api_add_provider():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "未命名").strip() or "未命名"
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"message": "请先填写 Base URL 和 API Key。"}), 400
    providers = _load_providers()
    new_p = {"id": str(uuid.uuid4())[:8], "name": name, "base_url": base_url, "api_key": api_key}
    providers.append(new_p)
    _save_providers(providers)
    is_admin = (_current_user() or {}).get("role") == "super_admin"
    return jsonify({"provider": _public_provider(new_p, is_admin), "message": "API 已添加。"})


@app.route("/api/llm-providers/<provider_id>", methods=["PUT"])
@_super_admin_required
def api_update_provider(provider_id):
    payload = request.get_json(silent=True) or {}
    providers = _load_providers()
    idx = next((i for i, p in enumerate(providers) if p.get("id") == provider_id), None)
    if idx is None:
        return jsonify({"message": "未找到该 API 配置。"}), 404
    p = dict(providers[idx])
    for key in ("name", "base_url", "api_key"):
        if payload.get(key):
            p[key] = str(payload[key]).strip()
    providers[idx] = p
    _save_providers(providers)
    is_admin = (_current_user() or {}).get("role") == "super_admin"
    return jsonify({"provider": _public_provider(p, is_admin), "message": "API 已更新。"})


@app.route("/api/llm-providers/<provider_id>", methods=["DELETE"])
@_super_admin_required
def api_delete_provider(provider_id):
    providers = _load_providers()
    providers = [p for p in providers if p.get("id") != provider_id]
    _save_providers(providers)
    return jsonify({"message": "API 已删除。"})


@app.route("/api/llm-providers/<provider_id>/models", methods=["GET"])
@_login_required
def api_provider_models(provider_id):
    providers = _load_providers()
    provider = next((p for p in providers if p.get("id") == provider_id), None)
    if not provider:
        return jsonify({"models": [], "message": "未找到该 API 配置。"}), 404
    base_url = str(provider.get("base_url") or "").strip()
    api_key = str(provider.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"models": [], "message": "该 API 配置不完整。"}), 200
    return _do_fetch_models(base_url, api_key)


@app.route("/api/llm-selection", methods=["GET"])
@_login_required
def api_get_llm_selection():
    providers = _load_providers()
    is_admin = (_current_user() or {}).get("role") == "super_admin"
    selection = session.get("llm_selection") or {}
    if not selection:
        user = _current_user()
        state = _load_user_state(user["username"]) if user else {}
        persisted = state.get("llm_selection") if isinstance(state.get("llm_selection"), dict) else {}
        selection = persisted or {}
    if selection.get("provider_id"):
        if not any(p.get("id") == selection["provider_id"] for p in providers):
            selection = {}
    # 回写 session，保证后续请求一致。
    session["llm_selection"] = selection
    session.modified = True
    return jsonify({
        "selection": selection,
        "providers": [_public_provider(p, is_admin) for p in providers]
    })


@app.route("/api/llm-selection", methods=["PUT"])
@_login_required
def api_set_llm_selection():
    payload = request.get_json(silent=True) or {}
    provider_id = str(payload.get("provider_id") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not provider_id or not model:
        return jsonify({"message": "请指定 provider_id 和 model。"}), 400
    providers = _load_providers()
    provider = next((p for p in providers if p.get("id") == provider_id), None)
    if not provider:
        return jsonify({"message": "未找到该 API 配置。"}), 404
    selection = {"provider_id": provider_id, "model": model}
    session["llm_selection"] = selection
    session.modified = True
    user = _current_user()
    if user:
        state = _load_user_state(user["username"])
        state["llm_selection"] = selection
        _save_user_state(user["username"], state)
    return jsonify({
        "selection": selection,
        "provider_name": provider.get("name"),
        "message": f"已选择：{provider.get('name')} · {model}"
    })


@app.route("/api/resume-llm-config", methods=["GET", "PUT"])
@_super_admin_required
def api_resume_llm_config():
    if request.method == "GET":
        return jsonify(_public_resume_llm_config(_current_user()))

    payload = request.get_json(silent=True) or {}
    current = _load_resume_llm_config()
    current["base_url"] = str(payload.get("base_url") or current.get("base_url") or "").strip()
    current["api_key"] = str(payload.get("api_key") or current.get("api_key") or "").strip()
    current["model"] = str(payload.get("model") or current.get("model") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    if not current["base_url"] or not current["api_key"]:
        return jsonify({"message": "请填写 base_url 和 api_key。"}), 400
    _save_resume_llm_config(current)
    return jsonify(_public_resume_llm_config(_current_user()))


@app.route("/api/resume-llm-models", methods=["GET"])
@_super_admin_required
def api_resume_llm_models():
    config = _load_resume_llm_config()
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"models": [], "message": "请先配置简历模型的 base_url 和 api_key。"}), 200
    return _do_fetch_models(base_url, api_key)


@app.route("/api/resume/upload", methods=["POST"])
@_login_required
def api_resume_upload():
    user = _current_user()
    file_storage = request.files.get("file")
    if file_storage is None:
        return jsonify({"message": "请上传 PDF 或 DOCX 简历文件（file 字段）。"}), 400

    try:
        saved_path, saved_name, file_size, file_type = _save_resume_upload(file_storage, user["username"])
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400

    state = _load_user_state(user["username"])
    prev = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    old_path = str(prev.get("storage_path") or "").strip()
    if old_path and old_path != saved_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass

    state["resume_profile"] = {
        "file_name": saved_name,
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
    storage_path = str(resume_state.get("storage_path") or "").strip()
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
    storage_path = str(resume_state.get("storage_path") or "").strip()
    if "job_description" in payload:
        job_description = str(payload.get("job_description") or "").strip()
    else:
        job_description = str(resume_state.get("job_description") or "").strip()
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"message": "未找到已上传简历，请先上传 PDF 或 DOCX。"}), 400

    base_url, api_key, model = _get_resume_provider_and_model()
    if not base_url or not api_key:
        return jsonify({"message": "模型尚未就绪，请先完成接口配置和模型选择。"}), 400
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

    storage_path = str(resume_state.get("storage_path") or "").strip()
    if storage_path and os.path.exists(storage_path):
        try:
            os.remove(storage_path)
        except OSError:
            pass
    state.pop("resume_profile", None)
    _save_user_state(user["username"], state)
    return jsonify({"message": "简历与匹配分析结果已删除。"})


def _run_career_report_job(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm):
    stage_defs = {item["key"]: item["label"] for item in CAREER_REPORT_STAGE_DEFS}
    generation_mode = "llm_orchestrated" if runtime_llm and runtime_llm.get("writer") else "template_orchestrated"
    model_name = str(runtime_llm.get("model") or "") if isinstance(runtime_llm, dict) else ""

    _update_career_report_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="profile_fusion",
        stage_label=stage_defs.get("profile_fusion", "画像融合"),
        stage_detail="正在汇总测评、访谈、简历与基础信息",
        progress=build_stage_progress("profile_fusion"),
    )
    _save_career_report_progress(
        username,
        job_id,
        "profile_fusion",
        stage_defs.get("profile_fusion", "画像融合"),
        "正在汇总测评、访谈、简历与基础信息",
        model=model_name,
        generation_mode=generation_mode,
        report_id=report_id,
        status="running",
    )

    def _stage_callback(stage_key, stage_label, detail):
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
        )

    try:
        bundle = generate_career_report_bundle(
            username=username,
            report_id=report_id,
            profile_payload=profile_payload,
            role_payload=role_payload,
            news_payload=get_career_news_payload(),
            focus_role_id=focus_role_id,
            stage_callback=_stage_callback,
            markdown_writer=(runtime_llm or {}).get("writer"),
            model_name=model_name,
            generation_mode=generation_mode,
        )
        _save_career_report_bundle(username, bundle)
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
        _update_career_report_job(
            job_id,
            status="completed",
            finished_at=int(time.time()),
            stage="critic",
            stage_label=stage_defs.get("critic", "一致性校验"),
            stage_detail="报告生成完成",
            message="报告生成完成",
            report_id=str(meta.get("report_id") or report_id),
            progress=build_stage_progress("critic"),
        )
        _save_career_report_progress(
            username,
            job_id,
            "critic",
            stage_defs.get("critic", "一致性校验"),
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
    except Exception as exc:
        app.logger.exception("career report generate failed")
        _update_career_report_job(
            job_id,
            status="failed",
            finished_at=int(time.time()),
            message=str(exc),
        )
        _save_career_report_progress(
            username,
            job_id,
            "critic",
            stage_defs.get("critic", "一致性校验"),
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

    payload = request.get_json(silent=True) or {}
    profile_payload = payload.get("profile_snapshot") if isinstance(payload.get("profile_snapshot"), dict) else {}
    role_payload = payload.get("role_rankings") if isinstance(payload.get("role_rankings"), list) else []
    focus_role_id = str(payload.get("focus_role_id") or "").strip()
    if not profile_payload:
        return jsonify({"message": "请先完成画像步骤后再生成职业规划报告。"}), 400

    base_url, api_key, model = _get_active_provider_and_model()
    runtime_llm = {
        "writer": _build_report_markdown_writer(base_url, api_key, model),
        "model": model or "",
    } if (base_url and api_key and model) else {"writer": None, "model": ""}

    job_id = uuid.uuid4().hex
    report_id = f"report-{uuid.uuid4().hex[:12]}"
    stage_label = next((item["label"] for item in CAREER_REPORT_STAGE_DEFS if item["key"] == "profile_fusion"), "画像融合")
    job = {
        "job_id": job_id,
        "username": username,
        "status": "queued",
        "stage": "profile_fusion",
        "stage_label": stage_label,
        "stage_detail": "任务已创建，等待后台编排",
        "message": "",
        "created_at": int(time.time()),
        "started_at": 0,
        "finished_at": 0,
        "report_id": report_id,
        "progress": build_stage_progress("profile_fusion"),
    }
    with CAREER_REPORT_LOCK:
        CAREER_REPORT_JOBS[job_id] = job

    _save_career_report_progress(
        username,
        job_id,
        "profile_fusion",
        stage_label,
        "任务已创建，等待后台编排",
        status="queued",
        report_id=report_id,
        model=str(runtime_llm.get("model") or ""),
        generation_mode="llm_orchestrated" if runtime_llm.get("writer") else "template_orchestrated",
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

    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    return jsonify({
        "job": _public_career_report_job(selected),
        "state": _public_career_report_state(report_state),
    })


@app.route("/api/career-report/current", methods=["GET"])
@_login_required
def api_career_report_current():
    user = _current_user()
    bundle = _read_career_report_bundle(user["username"])
    if isinstance(bundle, dict) and bundle.get("meta"):
        state, report_state, _ = _sync_career_report_tracker_state(user["username"], bundle)
    else:
        state = _load_user_state(user["username"])
        report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    data = _public_career_report_bundle(bundle) if isinstance(bundle, dict) and bundle.get("meta") else None
    return jsonify({
        "data": data,
        "state": _public_career_report_state(report_state),
    })


@app.route("/api/career-report/version", methods=["GET"])
@_login_required
def api_career_report_version():
    """按 report_id 读取已归档或当前 latest 的报告正文，不写入用户状态。"""
    user = _current_user()
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
    export_format = str(request.args.get("format") or "html").strip().lower()
    if export_format not in {"html", "md"}:
        return jsonify({"message": "仅支持导出 html 或 md 格式。"}), 400
    paths = _career_report_file_paths(user["username"])
    target_path = paths["html"] if export_format == "html" else paths["md"]
    if not os.path.exists(target_path):
        return jsonify({"message": "当前还没有可导出的职业规划报告。"}), 404
    with open(target_path, "r", encoding="utf-8") as fp:
        content = fp.read()
    mimetype = "text/html; charset=utf-8" if export_format == "html" else "text/markdown; charset=utf-8"
    filename = f"career-report-{user['username']}.{export_format}"
    return app.response_class(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/cities")
def api_cities():
    cities = [fname[:-5] for fname in _list_city_files()]
    return _cache_json_response(cities, max_age=3600)


@app.route("/api/jobs/bootstrap")
def api_jobs_bootstrap():
    """Return cities and job summaries in one payload for bootstrap usage."""
    cities = [fname[:-5] for fname in _list_city_files()]
    jobs = []
    for city_name in cities:
        try:
            jobs.extend(_get_city_job_summaries(city_name))
        except FileNotFoundError:
            continue
        except Exception as exc:
            app.logger.warning("读取 %s 失败：%s", city_name, exc)
    return _cache_json_response({"cities": cities, "jobs": jobs})


# API：岗位数据
@app.route("/api/jobs")
def api_jobs():
    city = str(request.args.get("city", "all") or "all").strip() or "all"
    view = str(request.args.get("view", "full") or "full").strip().lower()
    if view == "bootstrap":
        cities = [fname[:-5] for fname in _list_city_files()]
        jobs = []
        for city_name in cities:
            try:
                jobs.extend(_get_city_job_summaries(city_name))
            except FileNotFoundError:
                continue
            except Exception as exc:
                app.logger.warning("读取 %s 失败：%s", city_name, exc)
        return _cache_json_response({"cities": cities, "jobs": jobs})
    jobs = []

    cities = [fname[:-5] for fname in _list_city_files()] if city == "all" else [city]

    for city_name in cities:
        try:
            if view == "summary":
                jobs.extend(_get_city_job_summaries(city_name))
            else:
                city_jobs = _get_city_cache_entry(city_name)["jobs"]
                jobs.extend(
                    {
                        **job,
                        "job_id": _job_id(city_name, index),
                    }
                    for index, job in enumerate(city_jobs)
                )
        except FileNotFoundError:
            continue
        except Exception as exc:
            app.logger.warning("读取 %s 失败：%s", city_name, exc)

    return _cache_json_response(jobs)


@app.route("/api/job-detail")
def api_job_detail():
    raw_job_id = str(request.args.get("id", "") or "").strip()
    if ":" not in raw_job_id:
        return _cache_json_response({"message": "job id 缺失或格式错误"}, status=400)

    city_name, index_text = raw_job_id.split(":", 1)
    try:
        detail = _get_city_job_detail(city_name, int(index_text))
    except (TypeError, ValueError):
        return _cache_json_response({"message": "job id 参数格式错误"}, status=400)
    except FileNotFoundError:
        return _cache_json_response({"message": "未找到对应城市数据"}, status=404)
    except IndexError:
        return _cache_json_response({"message": "未找到对应岗位记录"}, status=404)

    return _cache_json_response(detail)

@app.route("/api/career-interview", methods=["POST"])
@_login_required
def api_career_interview():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    assessment_context = payload.get("assessment_context") if isinstance(payload.get("assessment_context"), dict) else {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

    normalized_messages = []
    for item in messages[-10:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized_messages.append({"role": role, "content": content[:1600]})

    try:
        result = _call_openai_compatible_chat(
            base_url,
            api_key,
            model,
            normalized_messages,
            system_prompt=_build_career_interview_prompt(assessment_context),
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("career interview failed")
        return jsonify({"message": f"职业访谈生成失败: {exc}"}), 502


@app.route("/api/mbti-clarifier", methods=["POST"])
@_login_required
def api_mbti_clarifier():
    payload = request.get_json(silent=True) or {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

    close_pairs = payload.get("close_pairs") if isinstance(payload.get("close_pairs"), list) else []
    score_snapshot = payload.get("score_snapshot") if isinstance(payload.get("score_snapshot"), dict) else {}
    answer_highlights = payload.get("answer_highlights") if isinstance(payload.get("answer_highlights"), list) else []

    user_payload = {
        "close_pairs": close_pairs[:4],
        "score_snapshot": score_snapshot,
        "answer_highlights": answer_highlights[:12],
    }
    messages = [
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        }
    ]

    try:
        parsed = _call_structured_chat(
            base_url,
            api_key,
            model,
            messages,
            system_prompt=_build_mbti_clarifier_prompt(close_pairs, score_snapshot),
            max_tokens=700,
        )
        result = _normalize_mbti_clarifier_payload(parsed)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("mbti clarifier failed")
        return jsonify({"message": f"MBTI 澄清题生成失败: {exc}"}), 502


@app.route("/api/deep-test-analysis", methods=["POST"])
@_login_required
def api_deep_test_analysis():
    payload = request.get_json(silent=True) or {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

    mbti_type = str(payload.get("mbti_type", "")).strip()
    scores = payload.get("scores", {})
    dimension_details = payload.get("dimension_details", [])

    if not mbti_type:
        return jsonify({"message": "请先完成深层测试。"}), 400

    system_prompt = f"""你是一位经验丰富的心理咨询师和职业规划专家，擅长基于MBTI性格类型进行深度分析。
请根据用户的深层MBTI测试结果，给出个性化的心理分析和成长建议。

分析要求：
1. 深入解读该性格类型的核心心理特征（约100字）
2. 分析该类型在人际关系、工作、学习中的独特优势（约80字）
3. 指出需要注意和成长的方向（约80字）
4. 给出2-3条具体可操作的个人发展建议

风格要求：
- 语气温和、鼓励性，避免过于笼统
- 结合用户具体的分数分布进行个性化分析
- 用中文回答，语言流畅自然

MBTI类型：{mbti_type}
各维度原始得分：{json.dumps(scores, ensure_ascii=False)}"""

    messages = [{"role": "user", "content": f"请分析我的深层MBTI测试结果。类型：{mbti_type}，维度分布：{json.dumps(dimension_details, ensure_ascii=False)}"}]

    try:
        analysis = _call_markdown_chat(
            base_url,
            api_key,
            model,
            messages,
            system_prompt=system_prompt,
            max_tokens=800,
        )
        return jsonify({"analysis": analysis, "mbti_type": mbti_type})
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("deep test analysis failed")
        return jsonify({"message": f"AI 分析生成失败: {exc}"}), 502


# 启动入口
def open_browser():
    import time
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")

_ensure_app_storage()
_load_users()
_load_providers()   # 触发旧格式迁移。
if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.environ.get("PORT", "8080"))
    auto_open_browser = os.environ.get("AUTO_OPEN_BROWSER", "").lower() in {"1", "true", "yes"}
    print("=" * 50)
    print("  职业规划智能体 · Flask 服务")
    print(f"  访问地址：http://{host}:{port}")
    print("  数据目录：", BOSS_INFO_DIR)
    print("  用户数据目录：", APP_DATA_DIR)
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    if auto_open_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host=host, port=port, debug=False, threaded=True)
