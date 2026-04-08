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
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
import random

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from services.news import (
    get_career_news_payload,
    get_kb_stats,
    search_news_kb,
    search_news_for_agent,
    format_rag_context,
)
from services.report import (
    CAREER_REPORT_STAGE_DEFS,
    REPORT_VERSION,
    build_stage_progress,
    empty_report_job,
    empty_report_state,
    generate_career_report_bundle,
)
from services.report.enhancements import (
    CAREER_FEEDBACK_VERSION,
    CAREER_REPORT_PIPELINE_VERSION,
    PORTRAIT_PROMPT_PIPELINE_VERSION,
    PORTRAIT_TEMPLATE_VERSION,
    build_portrait_prompt_layers,
    evaluate_portrait_prompt_packet,
    normalize_feedback_memory,
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
COMMUNITY_FORUM_FILE = os.path.join(APP_DATA_DIR, "community_forum.json")
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
COMMUNITY_FORUM_LOCK = threading.Lock()
JOB_CACHE_MAX_AGE_SECONDS = 900
RESUME_MAX_FILE_SIZE = 12 * 1024 * 1024
RESUME_MAX_PAGES = 20
RESUME_OCR_TIMEOUT_SECONDS = 35
RESUME_MAX_TEXT_CHARS = 24000
CAREER_GRAPH_FILE = os.path.join(BASE_DIR, "data", "career_graph.json")
CAREER_GRAPH_LOCK = threading.Lock()
CAREER_GRAPH_CACHE = {
    "mtime": None,
    "graph": None,
    "node_map": None,
    "cluster_map": None,
    "adjacency": None,
    "bootstrap": None,
}
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
你是一名中文职业规划咨询师，正在进行一对一深度访谈。

【你的风格】
- 像一位温和但专业的心理咨询师，引导用户探索自我
- 每次只问一个开放性问题，不连续追问
- 尊重用户的节奏，用户可以随时说"够了"或"我想停下来"
- 当用户给出模糊回答时，用具体例子引导；当用户给出具体例子时，深挖感受和收获

【四大探索主题】（不需要全部覆盖，用户聊到哪算哪）

1. 角色模型（Role Model）
   - 你从小到大有没有特别崇拜的人？可以是名人、老师、家长、朋友
   - 这个人做了什么让你如此钦佩？
   - 有没有在生活中尝试学习他/她的某种做法？结果怎样了？

2. 生活故事（Life Story）
   - 回想一下，有没有一件事你做得比大多数人都好？（即使很小）
   - 那件事是什么情况下发生的？你当时做了什么？
   - 有没有一段经历，虽然结果不太好，但你学到了很多？

3. 工作价值观（Work Values）
   - 假设三年后你找到了理想工作，典型的一天你会做什么？
   - 那份工作最吸引你的是什么？
   - 有什么样的工作内容会让你觉得"这不值得我做"？

4. 情境应对（Situational Response）
   - 如果你在团队项目中遇到意见分歧，你会怎么处理？
   - 如果 deadline 很紧但任务很重，你会怎么安排？
   - 当你不确定该怎么做时，你通常会怎么做？

【访谈规则】
- 用户没说"够了"或"完成了"之前，不要主动结束访谈
- 至少完成 3 轮对话后再考虑收尾
- 如果某个主题已经探索充分，可以自然转向其他主题
- 用自然对话的方式，不要像机器人一样列问题清单

【输出格式】（严格 JSON）
{
  "next_question": "下一轮问题，如果用户说完成了就填'__FINISH__'",
  "focus_dimension": "必须是以下之一（一字不差）：职业兴趣、工作价值观、学习方式、沟通风格、行动证据、职业成熟度。表示下一轮主要在为哪一维度收集信息。若系统消息里给出了各维度已答/目标数，已答满的维度不得再作为 focus_dimension，必须切换到下一个未答满的维度。",
  "completion_score": 0,
  "topic": "当前主题，如'角色模型'或'生活故事'等",
  "topic_progress": "当前主题的探索进度描述",
  "profile": {
    "summary": "一段50字左右的叙事性画像描述",
    "role_model": "用户钦佩的人及原因（从对话中提取）",
    "work_values": ["价值观1", "价值观2", "价值观3"],
    "key_experience": "用户提到的最具体的经历（用于证据）",
    "leadership_style": "从对话推断的领导/协作风格",
    "growth_mindset": "成长型思维的体现",
    "recommended_exploration": ["还可以探索的方向1", "还可以探索的方向2"]
  }
}
completion_score 按六维整体信息完整度估算 0-100；六维未覆盖时不超过 40。
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
COMMUNITY_FORUM_BOARD_OPTIONS = ("面经互助", "简历门诊", "实习内推", "选岗热议", "职场日常")


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


def _forum_clean_text(value, limit=800):
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _forum_slug(seed):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(seed or "").lower())
    return safe[:24] or uuid.uuid4().hex[:10]


def _forum_normalize_tags(raw_tags, limit=4):
    values = raw_tags if isinstance(raw_tags, list) else re.split(r"[#，,、/\s]+", str(raw_tags or ""))
    result = []
    for item in values:
        tag = _forum_clean_text(item, 16)
        if not tag or tag in result:
            continue
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def _forum_normalize_author(raw_author, fallback_username="", fallback_display="匿名同学"):
    author = raw_author if isinstance(raw_author, dict) else {}
    username = _forum_clean_text(author.get("username") or fallback_username, 32) or "guest"
    display_name = _forum_clean_text(author.get("display_name") or author.get("displayName") or fallback_display, 32) or "匿名同学"
    return {
        "username": username,
        "display_name": display_name,
    }


def _forum_normalize_reply(raw_reply):
    reply = raw_reply if isinstance(raw_reply, dict) else {}
    content = _forum_clean_text(reply.get("content"), 1200)
    if not content:
        return None
    created_at = int(reply.get("created_at") or time.time())
    return {
        "id": _forum_clean_text(reply.get("id") or f"reply_{uuid.uuid4().hex[:10]}", 32),
        "content": content,
        "created_at": created_at,
        "author": _forum_normalize_author(reply.get("author")),
    }


def _forum_normalize_post(raw_post):
    post = raw_post if isinstance(raw_post, dict) else {}
    title = _forum_clean_text(post.get("title"), 80)
    content = _forum_clean_text(post.get("content"), 2400)
    if not title or not content:
        return None
    board = _forum_clean_text(post.get("board"), 16)
    if board not in COMMUNITY_FORUM_BOARD_OPTIONS:
        board = "选岗热议"
    replies = []
    for item in post.get("replies") or []:
        normalized_reply = _forum_normalize_reply(item)
        if normalized_reply:
            replies.append(normalized_reply)
    replies.sort(key=lambda item: int(item.get("created_at") or 0))
    liked_by = []
    for value in post.get("liked_by") or []:
        username = _forum_clean_text(value, 32)
        if username and username not in liked_by:
            liked_by.append(username)
    created_at = int(post.get("created_at") or time.time())
    updated_at = int(post.get("updated_at") or created_at)
    last_reply_at = int(replies[-1]["created_at"]) if replies else int(post.get("last_reply_at") or updated_at)
    last_reply_user = ""
    if replies:
        last_reply_user = _forum_clean_text(replies[-1].get("author", {}).get("display_name"), 32)
    elif post.get("last_reply_user"):
        last_reply_user = _forum_clean_text(post.get("last_reply_user"), 32)
    return {
        "id": _forum_clean_text(post.get("id") or f"post_{uuid.uuid4().hex[:10]}", 32),
        "title": title,
        "content": content,
        "board": board,
        "tags": _forum_normalize_tags(post.get("tags") or []),
        "author": _forum_normalize_author(post.get("author")),
        "created_at": created_at,
        "updated_at": updated_at,
        "pinned": bool(post.get("pinned")),
        "views": max(0, int(post.get("views") or 0)),
        "liked_by": liked_by,
        "replies": replies,
        "last_reply_at": last_reply_at,
        "last_reply_user": last_reply_user,
    }


def _default_community_forum_payload():
    now = int(time.time())

    def reply(seed, content, author_name, minutes_ago):
        return {
            "id": f"reply_{_forum_slug(seed)}",
            "content": content,
            "created_at": now - minutes_ago * 60,
            "author": {"username": _forum_slug(author_name), "display_name": author_name},
        }

    posts = [
        {
            "id": "post_offer_schedule",
            "title": "暑期实习太晚准备还来得及吗？现在补项目和刷题应该怎么排优先级",
            "content": "我现在大三，前面主要把课上项目做完了，算法和面试准备比较弱。想请教大家，如果目标是暑期实习，接下来两个月应该先补项目包装、刷算法题，还是先把简历改到能投的状态？",
            "board": "面经互助",
            "tags": ["暑期实习", "投递节奏", "项目包装"],
            "author": {"username": "offer_lab", "display_name": "上岸学长"},
            "created_at": now - 5 * 3600,
            "updated_at": now - 35 * 60,
            "pinned": True,
            "views": 286,
            "liked_by": ["system", "23030134", "24110403", "24151007"],
            "replies": [
                reply("offer_schedule_1", "先把简历打磨到可投，再并行补一个能讲清楚指标的项目，这样反馈会更快。", "求职教练", 52),
                reply("offer_schedule_2", "如果算法很薄弱，建议每天固定一小时刷高频题，不要等项目全部做完才开始。", "后端实习生", 35),
            ],
        },
        {
            "id": "post_resume_story",
            "title": "简历里的项目经历怎么写，才能让面试官一眼看到亮点",
            "content": "我发现自己写项目时总是堆技术栈，结果看起来像流水账。有没有比较好的表达结构，比如背景、动作、结果怎么分配篇幅，尤其是实习和课程项目混合在一起的时候。",
            "board": "简历门诊",
            "tags": ["简历修改", "项目经历", "STAR"],
            "author": {"username": "resume_clinic", "display_name": "简历门诊官"},
            "created_at": now - 9 * 3600,
            "updated_at": now - 68 * 60,
            "pinned": False,
            "views": 198,
            "liked_by": ["system", "24110403"],
            "replies": [
                reply("resume_story_1", "把“做了什么”改成“解决了什么问题、怎么做、结果如何”，项目自然就立起来了。", "产品转码同学", 102),
            ],
        },
        {
            "id": "post_city_choice",
            "title": "同样是 AI 产品岗，留在新一线还是去上海北京更合适",
            "content": "目前拿到了两个方向接近的机会，一个在杭州，一个在上海。薪资差距不算特别大，但我更纠结成长密度、导师带教和岗位后续发展空间，想听听大家怎么判断。",
            "board": "选岗热议",
            "tags": ["城市选择", "AI产品", "offer对比"],
            "author": {"username": "decision_lab", "display_name": "Offer 观察员"},
            "created_at": now - 18 * 3600,
            "updated_at": now - 2 * 3600,
            "pinned": False,
            "views": 324,
            "liked_by": ["system", "23030134", "24030115"],
            "replies": [
                reply("city_choice_1", "如果你现在更缺方法论，优先看团队带教和业务密度；城市本身反而是第二层因素。", "AI产品新人", 205),
                reply("city_choice_2", "同薪资区间下，先比较岗位能不能让你讲出更强的成长故事。", "运营转产品", 126),
            ],
        },
        {
            "id": "post_referral_tips",
            "title": "找内推时，私信应该怎么写才不会让人觉得唐突",
            "content": "最近想主动联系校友和脉脉上的前辈争取内推，但总担心表达太生硬。大家一般会怎么写第一条消息，既礼貌又能让对方快速判断是否愿意帮忙？",
            "board": "实习内推",
            "tags": ["内推", "私信模板", "校友"],
            "author": {"username": "network_helper", "display_name": "求职小助手"},
            "created_at": now - 27 * 3600,
            "updated_at": now - 11 * 3600,
            "pinned": False,
            "views": 154,
            "liked_by": ["system"],
            "replies": [],
        },
    ]
    return {"posts": posts}


def _load_community_forum_store():
    _ensure_app_storage()
    with COMMUNITY_FORUM_LOCK:
        stored = _read_json_file(COMMUNITY_FORUM_FILE, None)
        created = not isinstance(stored, dict)
        payload = stored if isinstance(stored, dict) else _default_community_forum_payload()
        posts = []
        for item in payload.get("posts") or []:
            normalized_post = _forum_normalize_post(item)
            if normalized_post:
                posts.append(normalized_post)
        normalized = {"posts": posts}
        if created:
            _write_json_file(COMMUNITY_FORUM_FILE, normalized)
        return normalized


def _save_community_forum_store(payload):
    _ensure_app_storage()
    normalized = {"posts": []}
    for item in (payload or {}).get("posts") or []:
        normalized_post = _forum_normalize_post(item)
        if normalized_post:
            normalized["posts"].append(normalized_post)
    with COMMUNITY_FORUM_LOCK:
        _write_json_file(COMMUNITY_FORUM_FILE, normalized)
    return normalized


def _find_community_forum_post(payload, post_id):
    normalized_id = _forum_clean_text(post_id, 32)
    for item in (payload or {}).get("posts") or []:
        if item.get("id") == normalized_id:
            return item
    return None


def _public_community_forum_reply(raw_reply):
    reply = _forum_normalize_reply(raw_reply) or {}
    return {
        "id": str(reply.get("id") or ""),
        "content": str(reply.get("content") or ""),
        "created_at": int(reply.get("created_at") or 0),
        "author": reply.get("author") or {"username": "", "display_name": "匿名同学"},
    }


def _public_community_forum_post(raw_post, user=None):
    post = _forum_normalize_post(raw_post) or {}
    replies = [_public_community_forum_reply(item) for item in post.get("replies") or []]
    current_username = str((user or {}).get("username") or "").strip()
    liked_by = post.get("liked_by") or []
    return {
        "id": str(post.get("id") or ""),
        "title": str(post.get("title") or ""),
        "content": str(post.get("content") or ""),
        "board": str(post.get("board") or ""),
        "tags": post.get("tags") or [],
        "author": post.get("author") or {"username": "", "display_name": "匿名同学"},
        "created_at": int(post.get("created_at") or 0),
        "updated_at": int(post.get("updated_at") or 0),
        "pinned": bool(post.get("pinned")),
        "views": int(post.get("views") or 0),
        "likes": len(liked_by),
        "liked": bool(current_username and current_username in liked_by),
        "reply_count": len(replies),
        "replies": replies,
        "last_reply_at": int(post.get("last_reply_at") or post.get("updated_at") or 0),
        "last_reply_user": str(post.get("last_reply_user") or ""),
    }


def _community_forum_payload(user=None):
    store = _load_community_forum_store()
    posts = [_public_community_forum_post(item, user) for item in store.get("posts") or []]
    posts.sort(key=lambda item: (not item.get("pinned"), -int(item.get("updated_at") or 0), -int(item.get("created_at") or 0)))
    board_counts = {"all": len(posts)}
    tag_counts = {}
    for post in posts:
        board = str(post.get("board") or "选岗热议")
        board_counts[board] = board_counts.get(board, 0) + 1
        for tag in post.get("tags") or []:
            if tag:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    hot_tags = [
        {"tag": key, "count": value}
        for key, value in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    now = int(time.time())
    stats = {
        "threads": len(posts),
        "today_posts": sum(1 for item in posts if now - int(item.get("created_at") or 0) <= 24 * 3600),
        "active_users": len({str((item.get("author") or {}).get("username") or "") for item in posts if (item.get("author") or {}).get("username")}),
        "unanswered": sum(1 for item in posts if not int(item.get("reply_count") or 0)),
    }
    boards = [{"key": "all", "label": "全部", "count": board_counts.get("all", 0)}]
    for board in COMMUNITY_FORUM_BOARD_OPTIONS:
        boards.append({"key": board, "label": board, "count": board_counts.get(board, 0)})
    return {
        "boards": boards,
        "hot_tags": hot_tags,
        "stats": stats,
        "posts": posts,
    }


def _public_profile_portrait_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    image_url = str(state.get("image_url") or "").strip()
    brief = _normalize_profile_portrait_brief(state.get("brief"))
    if not image_url and not brief:
        return None
    return {
        "status": str(state.get("status") or ("ready" if image_url else "brief_ready")).strip() or "ready",
        "image_url": image_url,
        "created_at": int(state.get("created_at") or 0),
        "model": str(state.get("model") or PROFILE_PORTRAIT_MODEL).strip() or PROFILE_PORTRAIT_MODEL,
        "archetype_name": str(state.get("archetype_name") or "").strip(),
        "prompt_summary": str(state.get("prompt_summary") or "").strip(),
        "prompt_text": str(state.get("prompt_text") or "").strip(),
        "prompt_mode": str(state.get("prompt_mode") or "").strip(),
        "prompt_writer_mode": str(state.get("prompt_writer_mode") or "").strip(),
        "prompt_writer_model": str(state.get("prompt_writer_model") or "").strip(),
        "brief_version": str(state.get("brief_version") or "").strip(),
        "prompt_pipeline": state.get("prompt_pipeline") if isinstance(state.get("prompt_pipeline"), dict) else None,
        "prompt_evaluation": state.get("prompt_evaluation") if isinstance(state.get("prompt_evaluation"), dict) else None,
        "image_error": str(state.get("image_error") or "").strip(),
        "brief": brief,
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

    module_outputs = context.get("module_outputs") if isinstance(context.get("module_outputs"), dict) else {}
    assessment_output = module_outputs.get("assessment") if isinstance(module_outputs.get("assessment"), dict) else {}
    resume_output = module_outputs.get("resume") if isinstance(module_outputs.get("resume"), dict) else {}
    interview_output = module_outputs.get("interview") if isinstance(module_outputs.get("interview"), dict) else {}
    prompt_request = context.get("prompt_request") if isinstance(context.get("prompt_request"), dict) else {}

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
        "next_steps": _clean_list(context.get("next_steps"), limit=4, item_limit=72),
        "missing_items": _clean_list(context.get("missing_items"), limit=4, item_limit=72),
        "uncertainty": _clean_list(context.get("uncertainty"), limit=4, item_limit=72),
        "module_outputs": {
            "assessment": {
                "status": _clean_text(assessment_output.get("status"), 16),
                "summary": _clean_text(assessment_output.get("summary"), 240),
                "chips": _clean_list(assessment_output.get("chips"), limit=6, item_limit=48),
                "note": _clean_text(assessment_output.get("note"), 220),
            },
            "resume": {
                "status": _clean_text(resume_output.get("status"), 16),
                "summary": _clean_text(resume_output.get("summary"), 240),
                "chips": _clean_list(resume_output.get("chips"), limit=6, item_limit=64),
                "note": _clean_text(resume_output.get("note"), 220),
            },
            "interview": {
                "status": _clean_text(interview_output.get("status"), 16),
                "summary": _clean_text(interview_output.get("summary"), 260),
                "chips": _clean_list(interview_output.get("chips"), limit=6, item_limit=64),
                "note": _clean_text(interview_output.get("note"), 220),
                "completion_score": _safe_score(interview_output.get("completion_score"), 0),
                "usable_for_portrait": bool(interview_output.get("usable_for_portrait")),
                "missing_followups": _clean_list(interview_output.get("missing_followups"), limit=4, item_limit=72),
            },
        },
        "prompt_request": {
            "card_style": _clean_text(prompt_request.get("card_style"), 48),
            "card_goal": _clean_text(prompt_request.get("card_goal"), 180),
            "visual_direction": _clean_text(prompt_request.get("visual_direction"), 180),
            "required_fields": _clean_list(prompt_request.get("required_fields"), limit=6, item_limit=40),
        },
    }


def _normalize_profile_portrait_brief(raw_brief):
    brief = raw_brief if isinstance(raw_brief, dict) else {}

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

    visual_spec = brief.get("visual_spec") if isinstance(brief.get("visual_spec"), dict) else {}
    normalized = {
        "title": _clean_text(brief.get("title"), 40),
        "subtitle": _clean_text(brief.get("subtitle"), 96),
        "positioning": _clean_text(brief.get("positioning"), 180),
        "primary_role": _clean_text(brief.get("primary_role"), 48),
        "support_roles": _clean_list(brief.get("support_roles"), limit=2, item_limit=32),
        "mission_line": _clean_text(brief.get("mission_line"), 120),
        "evidence_tags": _clean_list(brief.get("evidence_tags"), limit=3, item_limit=40),
        "value_tags": _clean_list(brief.get("value_tags"), limit=3, item_limit=24),
        "risk_note": _clean_text(brief.get("risk_note"), 88),
        "next_action": _clean_text(brief.get("next_action"), 88),
        "confidence_band": _clean_text(brief.get("confidence_band"), 16),
        "visual_spec": {
            "style": _clean_text(visual_spec.get("style"), 72),
            "subject_age_hint": _clean_text(visual_spec.get("subject_age_hint"), 32),
            "subject_gender_hint": _clean_text(visual_spec.get("subject_gender_hint"), 16),
            "outfit": _clean_text(visual_spec.get("outfit"), 88),
            "props": _clean_text(visual_spec.get("props"), 88),
            "scene": _clean_text(visual_spec.get("scene"), 120),
            "mood": _clean_text(visual_spec.get("mood"), 48),
            "composition": _clean_text(visual_spec.get("composition"), 88),
            "palette": _clean_text(visual_spec.get("palette"), 56),
        },
    }
    return normalized if any(
        [
            normalized["title"],
            normalized["subtitle"],
            normalized["primary_role"],
            normalized["mission_line"],
        ]
    ) else None


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


def _infer_profile_portrait_role_group_v2(*values):
    combined = " ".join([str(value or "") for value in values])
    if re.search(r"产品|项目|运营|行政|助理|协调|人力|hr|pm", combined, re.IGNORECASE):
        return "coordination"
    if re.search(r"数据|分析|财务|审计|研究|算法|开发|后端|测试|工程", combined, re.IGNORECASE):
        return "analysis"
    if re.search(r"内容|新媒体|编辑|策划|设计|品牌|创意", combined, re.IGNORECASE):
        return "creative"
    if re.search(r"销售|商务|市场|客户|增长|bd", combined, re.IGNORECASE):
        return "growth"
    return "general"


def _build_profile_portrait_title_v2(group, archetype_name=""):
    title_map = {
        "coordination": "执行协调型推进者",
        "analysis": "分析洞察型构建者",
        "creative": "表达策划型连接者",
        "growth": "增长拓展型连接者",
        "general": "职业探索型支持者",
    }
    if archetype_name and archetype_name not in ("综合支持者", "职业探索中"):
        return archetype_name
    return title_map.get(group, title_map["general"])


def _build_profile_portrait_positioning_v2(group, primary_role, context):
    scene = primary_role or context.get("target_direction") or context.get("archetype_scene") or "当前职业方向"
    if group == "coordination":
        return f"你更像能在清晰目标下整合信息、推进协作并把任务落地到结果的人，最适合在 {scene} 相关场景发力。"
    if group == "analysis":
        return f"你更像能在高信息密度场景里建立判断、拆解问题并持续优化结果的人，最适合在 {scene} 相关场景发力。"
    if group == "creative":
        return f"你更像通过表达、内容和创意组织信息的人，适合在 {scene} 相关场景里承担策划与输出角色。"
    if group == "growth":
        return f"你更像能面向目标主动推进、连接资源并推动机会转化的人，适合在 {scene} 相关场景里承担前线角色。"
    return f"你当前更像一个具备适配性与执行力的职业新人，正在围绕 {scene} 收敛更稳定的职业定位。"


def _build_profile_portrait_mission_line_v2(group, primary_role):
    role = primary_role or "当前目标方向"
    if group == "coordination":
        return f"最适合承担 {role} 场景中的信息统筹、进度推进、任务闭环与跨角色协作工作。"
    if group == "analysis":
        return f"最适合承担 {role} 场景中的问题拆解、分析判断、结构搭建与持续优化工作。"
    if group == "creative":
        return f"最适合承担 {role} 场景中的内容组织、表达策划、创意整合与产出打磨工作。"
    if group == "growth":
        return f"最适合承担 {role} 场景中的机会推进、客户沟通、目标跟进与结果转化工作。"
    return f"最适合在 {role} 相关岗位中承担支持执行、快速学习与稳定交付类任务。"


def _build_profile_portrait_evidence_tags_v2(context, primary_role):
    evidence = []
    if context.get("mbti"):
        evidence.append(f"MBTI：{context.get('mbti')}")
    if context.get("holland"):
        evidence.append(f"霍兰德：{context.get('holland')}")
    if primary_role:
        evidence.append(f"岗位线索：{primary_role}")
    if context.get("resume_roles"):
        evidence.append(f"简历角色：{context['resume_roles'][0]}")
    if context.get("resume_projects"):
        evidence.append(f"项目经历：{context['resume_projects'][0][:22]}")
    if context.get("interview_roles"):
        evidence.append(f"访谈偏好：{context['interview_roles'][0]}")
    if context.get("interview_values"):
        evidence.append(f"价值观：{context['interview_values'][0]}")
    if context.get("target_direction"):
        evidence.append(f"目标方向：{context['target_direction']}")
    cleaned = []
    for item in evidence:
        text = str(item or "").strip()[:40]
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= 3:
            break
    return cleaned


def _estimate_profile_portrait_confidence_v2(context, primary_role):
    signal_count = sum(
        1
        for item in [
            context.get("mbti"),
            context.get("holland"),
            context.get("resume_summary"),
            context.get("interview_summary"),
            context.get("target_direction"),
            context.get("resume_projects"),
            context.get("resume_roles"),
        ]
        if item
    )
    target_direction = str(context.get("target_direction") or "").strip()
    matches_target = bool(target_direction and primary_role and (target_direction in primary_role or primary_role in target_direction))
    if signal_count >= 5 and (matches_target or context.get("resume_roles") or context.get("interview_roles")):
        return "高"
    if signal_count >= 3:
        return "中"
    return "待验证"


def _infer_profile_portrait_risk_note_v2(context, primary_role):
    for item in context.get("uncertainty") or []:
        if str(item or "").strip():
            return str(item).strip()
    for item in context.get("missing_items") or []:
        if str(item or "").strip():
            return f"当前仍需补充：{str(item).strip()}"
    target_direction = str(context.get("target_direction") or "").strip()
    if target_direction and primary_role and target_direction not in primary_role and primary_role not in target_direction:
        return "你填写的目标方向与当前最强证据并不完全一致，建议先以证据更强的角色做展示。"
    return "当前画像已可用于展示，但主导特征仍建议继续用新经历补强。"


def _infer_profile_portrait_next_action_v2(context, primary_role):
    for item in context.get("next_steps") or []:
        if str(item or "").strip():
            return str(item).strip()
    if context.get("missing_items"):
        return f"优先补齐 {str(context['missing_items'][0]).strip()}，让这张名片的证据更完整。"
    role = primary_role or context.get("target_direction") or "目标岗位"
    return f"围绕 {role} 补一条可量化项目成果，用结果指标强化这张任务名片。"


def _build_profile_portrait_palette_v2(group):
    palette_map = {
        "coordination": "雾蓝、深海军蓝、冰白",
        "analysis": "深蓝、青灰、冷白",
        "creative": "钴蓝、雾紫灰、纸白",
        "growth": "墨蓝、青绿、银灰白",
        "general": "石板蓝、雾灰、白色",
    }
    return palette_map.get(group, palette_map["general"])


def _build_profile_portrait_brief(context):
    primary_role = (
        (context.get("top_roles") or [""])[0]
        or (context.get("role_cluster") or [""])[0]
        or str(context.get("target_direction") or "").strip()
        or (context.get("resume_roles") or [""])[0]
        or (context.get("interview_roles") or [""])[0]
        or "职业探索中"
    )
    support_roles = []
    for item in (
        (context.get("top_roles") or [])[1:]
        + (context.get("role_cluster") or [])
        + (context.get("interview_roles") or [])
        + (context.get("resume_roles") or [])
    ):
        text = str(item or "").strip()
        if text and text != primary_role and text not in support_roles:
            support_roles.append(text)
        if len(support_roles) >= 2:
            break

    group = _infer_profile_portrait_role_group_v2(
        primary_role,
        context.get("target_direction"),
        context.get("archetype_name"),
        _join_unique_text(context.get("resume_roles"), " "),
        _join_unique_text(context.get("top_roles"), " "),
    )
    visual_cues = _infer_profile_portrait_visual_cues(context)
    title = _build_profile_portrait_title_v2(group, context.get("archetype_name") or "")
    subtitle = _build_profile_portrait_positioning_v2(group, primary_role, context)
    brief = {
        "title": title,
        "subtitle": subtitle[:88],
        "positioning": subtitle,
        "primary_role": primary_role,
        "support_roles": support_roles[:2],
        "mission_line": _build_profile_portrait_mission_line_v2(group, primary_role),
        "evidence_tags": _build_profile_portrait_evidence_tags_v2(context, primary_role),
        "value_tags": (context.get("work_values") or [])[:3] or ["稳定成长", "结果导向", "持续进步"],
        "risk_note": _infer_profile_portrait_risk_note_v2(context, primary_role),
        "next_action": _infer_profile_portrait_next_action_v2(context, primary_role),
        "confidence_band": _estimate_profile_portrait_confidence_v2(context, primary_role),
        "visual_spec": {
            "style": "半写实职业插画，白底页面兼容，适合做任务名片主视觉",
            "subject_age_hint": _infer_profile_portrait_age_hint(context),
            "subject_gender_hint": _normalize_profile_gender(context.get("gender")) or "未指定",
            "outfit": visual_cues["outfit"],
            "props": visual_cues["props"],
            "scene": visual_cues["scene"],
            "mood": visual_cues["mood"],
            "composition": "3:4 纵向构图，单人半身到 2/3 身，人物居中或略偏左，画面干净克制",
            "palette": _build_profile_portrait_palette_v2(group),
        },
    }
    return _normalize_profile_portrait_brief(brief)


def _build_profile_portrait_summary_from_brief(brief):
    normalized = _normalize_profile_portrait_brief(brief) or {}
    return str(normalized.get("subtitle") or normalized.get("positioning") or "").strip()


def _merge_profile_portrait_brief(primary, fallback):
    primary_brief = _normalize_profile_portrait_brief(primary) or {}
    fallback_brief = _normalize_profile_portrait_brief(fallback) or {}
    merged_visual = {}
    for key in ("style", "subject_age_hint", "subject_gender_hint", "outfit", "props", "scene", "mood", "composition", "palette"):
        merged_visual[key] = (
            (primary_brief.get("visual_spec") or {}).get(key)
            or (fallback_brief.get("visual_spec") or {}).get(key)
            or ""
        )
    merged = {
        "title": primary_brief.get("title") or fallback_brief.get("title") or "",
        "subtitle": primary_brief.get("subtitle") or fallback_brief.get("subtitle") or "",
        "positioning": primary_brief.get("positioning") or fallback_brief.get("positioning") or "",
        "primary_role": primary_brief.get("primary_role") or fallback_brief.get("primary_role") or "",
        "support_roles": (primary_brief.get("support_roles") or fallback_brief.get("support_roles") or [])[:2],
        "mission_line": primary_brief.get("mission_line") or fallback_brief.get("mission_line") or "",
        "evidence_tags": (primary_brief.get("evidence_tags") or fallback_brief.get("evidence_tags") or [])[:3],
        "value_tags": (primary_brief.get("value_tags") or fallback_brief.get("value_tags") or [])[:3],
        "risk_note": primary_brief.get("risk_note") or fallback_brief.get("risk_note") or "",
        "next_action": primary_brief.get("next_action") or fallback_brief.get("next_action") or "",
        "confidence_band": primary_brief.get("confidence_band") or fallback_brief.get("confidence_band") or "",
        "visual_spec": merged_visual,
    }
    return _normalize_profile_portrait_brief(merged) or fallback_brief or primary_brief or None


def _build_profile_portrait_module_outputs(context):
    raw_modules = context.get("module_outputs") if isinstance(context.get("module_outputs"), dict) else {}
    assessment_raw = raw_modules.get("assessment") if isinstance(raw_modules.get("assessment"), dict) else {}
    resume_raw = raw_modules.get("resume") if isinstance(raw_modules.get("resume"), dict) else {}
    interview_raw = raw_modules.get("interview") if isinstance(raw_modules.get("interview"), dict) else {}

    assessment = {
        "status": str(assessment_raw.get("status") or ("complete" if (context.get("mbti") and context.get("holland")) else ("partial" if (context.get("mbti") or context.get("holland")) else "missing"))).strip(),
        "summary": str(assessment_raw.get("summary") or "｜".join([item for item in [f"MBTI {context.get('mbti')}" if context.get("mbti") else "", f"霍兰德 {context.get('holland')}" if context.get("holland") else ""] if item]) or "尚未形成稳定测评输出").strip(),
        "chips": (assessment_raw.get("chips") if isinstance(assessment_raw.get("chips"), list) else [item for item in [context.get("mbti"), context.get("holland")] if item])[:6],
        "note": str(assessment_raw.get("note") or ("提供人格倾向与职业兴趣的基础锚点。" if (context.get("mbti") or context.get("holland")) else "测评未完成时，人物画像只使用其它模块做弱收敛。")).strip(),
    }
    resume = {
        "status": str(resume_raw.get("status") or ("complete" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "missing")).strip(),
        "summary": str(resume_raw.get("summary") or context.get("resume_summary") or "尚未形成可用的简历证据").strip(),
        "chips": (resume_raw.get("chips") if isinstance(resume_raw.get("chips"), list) else ((context.get("resume_roles") or []) + (context.get("resume_skills") or [])[:3]))[:6],
        "note": str(resume_raw.get("note") or ("提供角色线索、项目证据与技能关键词。" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "没有简历时，人物画像缺少经历证据，只能更多依赖测评和访谈。")).strip(),
    }
    interview_completion_score = _safe_score(interview_raw.get("completion_score"), 0)
    interview = {
        "status": str(interview_raw.get("status") or ("complete" if interview_raw.get("usable_for_portrait") else ("partial" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "missing"))).strip(),
        "summary": str(interview_raw.get("summary") or context.get("interview_summary") or "尚未形成访谈摘要").strip(),
        "chips": (interview_raw.get("chips") if isinstance(interview_raw.get("chips"), list) else ((context.get("interview_values") or []) + (context.get("interview_roles") or []) + (context.get("interview_evidence") or [])))[:6],
        "note": str(interview_raw.get("note") or ("即使提前结束，只要已经形成价值观、经历或协作风格信号，就可以进入首版画像。" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "没有访谈信号时，画像更像静态推断。")).strip(),
        "completion_score": interview_completion_score,
        "usable_for_portrait": bool(interview_raw.get("usable_for_portrait") or context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")),
        "missing_followups": (interview_raw.get("missing_followups") if isinstance(interview_raw.get("missing_followups"), list) else context.get("missing_items") or [])[:4],
    }
    return {"assessment": assessment, "resume": resume, "interview": interview}


def _normalize_profile_portrait_prompt_packet(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}

    def _clean_text(value, limit=2600):
        return str(value or "").strip()[:limit]

    return {
        "brief": _normalize_profile_portrait_brief(payload.get("brief")),
        "prompt_summary": _clean_text(payload.get("prompt_summary"), 180),
        "render_prompt": _clean_text(payload.get("render_prompt"), 2600),
        "prompt_pipeline": payload.get("prompt_pipeline") if isinstance(payload.get("prompt_pipeline"), dict) else None,
        "prompt_evaluation": payload.get("prompt_evaluation") if isinstance(payload.get("prompt_evaluation"), dict) else None,
    }


def _build_profile_portrait_prompt_packet(context, preset_brief=None):
    fallback_brief = _normalize_profile_portrait_brief(preset_brief) or _build_profile_portrait_brief(context)
    prompt_layers = build_portrait_prompt_layers(context, fallback_brief)
    packet = {
        "brief": fallback_brief,
        "prompt_summary": _build_profile_portrait_summary_from_brief(fallback_brief) or context.get("summary") or "",
        "render_prompt": _build_profile_portrait_render_prompt(context, fallback_brief),
        "mode": "heuristic",
        "writer_model": "",
        "prompt_pipeline": prompt_layers,
        "prompt_evaluation": None,
    }

    base_url, api_key, model = _get_active_provider_and_model()
    if not base_url or not api_key or not model:
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
        return packet

    module_outputs = _build_profile_portrait_module_outputs(context)
    prompt_request = context.get("prompt_request") if isinstance(context.get("prompt_request"), dict) else {}
    system_prompt = """
你是职业规划产品的画像提示词编辑器。请根据 3 个输入模块的标准化输出，生成一份“人物明信片 brief”和一段“给图像模型使用的渲染提示词”。

要求：
1. 先消化测评输出、简历输出、访谈输出，不要逐条复述输入。
2. 如果访谈只是提前结束但已经有稳定信号，也要给出可用于首版人物明信片的结论。
3. brief 必须用于白底产品页面，信息要清晰、克制、可展示，不能写成长报告。
4. render_prompt 必须是给图像模型的完整中文提示词，强调 3:4 纵向、单人、半写实职业插画、无文字、适合人物明信片主视觉。
5. 如果输入不足，允许保守收敛，但不要伪造过强结论。

严格输出 JSON：
{
  "brief": {
    "title": "人物卡标题",
    "subtitle": "80字内副标题",
    "positioning": "140字内定位说明",
    "primary_role": "最像岗位",
    "support_roles": ["辅助岗位1", "辅助岗位2"],
    "mission_line": "一句任务描述",
    "evidence_tags": ["证据1", "证据2", "证据3"],
    "value_tags": ["价值观1", "价值观2", "价值观3"],
    "risk_note": "当前仍需注意的地方",
    "next_action": "下一步建议",
    "confidence_band": "高/中/待验证",
    "visual_spec": {
      "style": "视觉风格",
      "subject_age_hint": "年龄提示",
      "subject_gender_hint": "性别提示",
      "outfit": "穿搭",
      "props": "道具",
      "scene": "场景",
      "mood": "气质",
      "composition": "构图",
      "palette": "配色"
    }
  },
  "prompt_summary": "一句话说明 AI 最终如何收敛这个人物画像",
  "render_prompt": "写给图像模型的完整中文提示词"
}
""".strip()

    user_payload = {
        "assessment_output": module_outputs.get("assessment") or {},
        "resume_output": module_outputs.get("resume") or {},
        "interview_output": module_outputs.get("interview") or {},
        "prompt_pipeline": prompt_layers,
        "global_context": {
            "summary": context.get("summary") or "",
            "archetype_name": context.get("archetype_name") or "",
            "archetype_scene": context.get("archetype_scene") or "",
            "top_roles": context.get("top_roles") or [],
            "role_cluster": context.get("role_cluster") or [],
            "work_values": context.get("work_values") or [],
            "axis_traits": context.get("axis_traits") or [],
            "workstyle_traits": context.get("workstyle_traits") or [],
            "target_direction": context.get("target_direction") or "",
            "target_city": context.get("target_city") or "",
            "major": context.get("major") or "",
            "grade": context.get("grade") or "",
            "gender": context.get("gender") or "",
            "uncertainty": context.get("uncertainty") or [],
            "missing_items": context.get("missing_items") or [],
        },
        "prompt_request": {
            "card_style": str(prompt_request.get("card_style") or "人物明信片").strip(),
            "card_goal": str(prompt_request.get("card_goal") or "美观清晰，一眼看懂这个人最像什么岗位、能做什么任务、下一步该补什么。").strip(),
            "visual_direction": str(prompt_request.get("visual_direction") or "适合白底页面展示，职业感明确，信息克制，避免花哨宣传海报感。").strip(),
            "required_fields": prompt_request.get("required_fields") or ["标题", "定位句", "主角色", "任务句", "证据标签", "下一步"],
        },
    }

    try:
        parsed = _call_structured_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
            system_prompt=system_prompt,
            max_tokens=1600,
        )
        normalized_packet = _normalize_profile_portrait_prompt_packet(parsed)
        merged_brief = _merge_profile_portrait_brief(normalized_packet.get("brief"), fallback_brief)
        packet["brief"] = merged_brief or fallback_brief
        packet["prompt_summary"] = (
            normalized_packet.get("prompt_summary")
            or _build_profile_portrait_summary_from_brief(packet["brief"])
            or packet["prompt_summary"]
        )
        packet["render_prompt"] = (
            normalized_packet.get("render_prompt")
            or _build_profile_portrait_render_prompt(context, packet["brief"])
        )
        packet["mode"] = "llm"
        packet["writer_model"] = model
        packet["prompt_pipeline"] = prompt_layers
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
        if packet["prompt_evaluation"].get("needs_refinement"):
            refiner_payload = {
                "current_output": {
                    "brief": packet.get("brief"),
                    "prompt_summary": packet.get("prompt_summary"),
                    "render_prompt": packet.get("render_prompt"),
                },
                "evaluation": packet.get("prompt_evaluation"),
                "prompt_pipeline": prompt_layers,
                "target": "补齐缺失字段，强化角色-证据一致性，并保留 3:4、单人、半写实、无文字等视觉硬约束。",
            }
            refined = _call_structured_chat(
                base_url,
                api_key,
                model,
                [{"role": "user", "content": json.dumps(refiner_payload, ensure_ascii=False)}],
                system_prompt=(
                    "你是职业画像提示词优化器。"
                    "请根据上一版输出和自动评分结果，修复缺失字段、增强证据一致性，并输出同样结构的 JSON。"
                    "不要扩写成报告，不要删除已经成立的角色判断。"
                ),
                max_tokens=1400,
            )
            refined_packet = _normalize_profile_portrait_prompt_packet(refined)
            packet["brief"] = _merge_profile_portrait_brief(refined_packet.get("brief"), packet["brief"]) or packet["brief"]
            packet["prompt_summary"] = (
                refined_packet.get("prompt_summary")
                or packet.get("prompt_summary")
                or _build_profile_portrait_summary_from_brief(packet["brief"])
            )
            packet["render_prompt"] = (
                refined_packet.get("render_prompt")
                or packet.get("render_prompt")
                or _build_profile_portrait_render_prompt(context, packet["brief"])
            )
            packet["mode"] = "llm_refined"
            packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
            if isinstance(packet.get("prompt_evaluation"), dict):
                packet["prompt_evaluation"]["rewrite_used"] = True
    except Exception:
        app.logger.exception("profile portrait prompt writer failed")

    if not isinstance(packet.get("prompt_evaluation"), dict):
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
    if isinstance(packet.get("prompt_evaluation"), dict):
        packet["prompt_evaluation"].setdefault("rewrite_used", False)
    packet["prompt_pipeline"] = prompt_layers
    return packet


def _build_profile_portrait_render_prompt(context, brief=None):
    normalized_brief = _normalize_profile_portrait_brief(brief) or _build_profile_portrait_brief(context)
    visual_spec = normalized_brief.get("visual_spec") or {}
    gender = _normalize_profile_gender(context.get("gender")) or "未指定"
    title = normalized_brief.get("title") or context.get("archetype_name") or "职业任务名片"
    subtitle = normalized_brief.get("subtitle") or context.get("summary") or ""
    evidence_text = _join_unique_text(normalized_brief.get("evidence_tags"), "；", 3)
    value_text = _join_unique_text(normalized_brief.get("value_tags"), "、", 3)
    support_roles = _join_unique_text(normalized_brief.get("support_roles"), " / ", 2)
    return (
        "请为职业规划产品生成一张 3:4 纵向单人半写实插画海报，用于白底页面里的任务名片主视觉。"
        "不要文字、不要水印、不要拼贴、不要多人、不要 UI 截图、不要夸张卡通。\n"
        "人物身份：\n"
        f"- 标题：{title}\n"
        f"- 职业定位：{subtitle}\n"
        f"- 主角色：{normalized_brief.get('primary_role') or '职业探索中'}\n"
        f"- 辅助角色：{support_roles or '不强调'}\n"
        f"- 任务描述：{normalized_brief.get('mission_line') or ''}\n"
        f"- 证据关键词：{evidence_text or '职业新人、方向收敛'}\n"
        f"- 工作价值观：{value_text or '稳定成长、结果导向'}\n"
        f"- 性别提示：{gender}\n"
        f"- 年龄提示：{visual_spec.get('subject_age_hint') or _infer_profile_portrait_age_hint(context)}\n"
        "视觉要求：\n"
        f"- 风格：{visual_spec.get('style') or '半写实职业插画'}\n"
        f"- 气质：{visual_spec.get('mood') or '专业、可信赖、克制'}\n"
        f"- 穿搭：{visual_spec.get('outfit') or '商务休闲职业穿搭'}\n"
        f"- 道具：{visual_spec.get('props') or '平板、笔记本、工作记录工具'}\n"
        f"- 场景：{visual_spec.get('scene') or '现代办公空间'}\n"
        f"- 构图：{visual_spec.get('composition') or '单人半身到 2/3 身构图'}\n"
        f"- 配色：{visual_spec.get('palette') or '石板蓝、白色、雾灰'}\n"
        "输出要求：人物主体明确，画面简洁，适合放在产品页面左侧做职业推广海报。"
        "负面要求：低清晰度、背景杂乱、比例错误、畸形手部、过度赛博朋克、漫画分镜、文字乱码。"
    )


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
            "model": str(raw_state.get("model") or ""),
            "generation_mode": str(raw_state.get("generation_mode") or ""),
            "focus_role_id": str(raw_state.get("focus_role_id") or ""),
            "title": str(raw_state.get("title") or ""),
            "summary": str(raw_state.get("summary") or ""),
            "export_formats": raw_state.get("export_formats") if isinstance(raw_state.get("export_formats"), list) else ["html", "md"],
            "tracker": raw_state.get("tracker") if isinstance(raw_state.get("tracker"), dict) else None,
            "feedback": _normalize_career_report_feedback(raw_state.get("feedback")),
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


def _infer_career_interview_focus_from_topic(topic: str) -> str:
    """当模型未返回 focus_dimension 时，用 topic 粗映射到六维之一。"""
    t = str(topic or "").strip()
    if not t:
        return ""
    if "工作价值观" in t:
        return "工作价值观"
    if "角色模型" in t or "榜样" in t:
        return "职业成熟度"
    if "生活故事" in t:
        return "行动证据"
    if "情境应对" in t or t == "情境":
        return "沟通风格"
    if "学习方式" in t or "学习" in t and "风格" in t:
        return "学习方式"
    return ""


def _coerce_career_interview_focus_dimension(payload: dict) -> str:
    raw = str(payload.get("focus_dimension") or "").strip()
    if raw in DEFAULT_CAREER_DIMENSIONS:
        return raw
    inferred = _infer_career_interview_focus_from_topic(payload.get("topic"))
    if inferred in DEFAULT_CAREER_DIMENSIONS:
        return inferred
    for name in DEFAULT_CAREER_DIMENSIONS:
        if name and name in raw:
            return name
    return "职业兴趣"


def _career_interview_progress_system_suffix(focus_dimension: str, progress: list) -> str:
    """把前端维度进度注入系统提示，避免模型永远在「职业兴趣」上打转。"""
    if not isinstance(progress, list) or not progress:
        return ""
    lines = []
    for item in progress:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            answered = int(item.get("answered") or 0)
            target = int(item.get("target") or 0)
        except (TypeError, ValueError):
            answered, target = 0, 0
        lines.append(f"- {name}：已答 {answered} / 目标 {target}" + ("（已满，勿再作为 focus_dimension）" if target > 0 and answered >= target else ""))
    if not lines:
        return ""
    fd = str(focus_dimension or "").strip() or "（请根据下表选择下一未完成维度）"
    return (
        "\n\n【维度进度快照】（必须遵守；next_question 与 focus_dimension 要与下一未完成维度一致）\n"
        + "\n".join(lines)
        + f"\n前端当前聚焦维度参考：{fd}"
    )


def _merge_career_interview_focus_with_progress(normalized: dict, client_progress: list) -> None:
    """若模型仍把 focus 指到已答满维度，强制改为按顺序第一个未答满维度。"""
    if not isinstance(normalized, dict):
        return
    if not isinstance(client_progress, list) or not client_progress:
        return

    def answered_target(dim_name: str) -> tuple[int, int]:
        for item in client_progress:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != dim_name:
                continue
            try:
                return int(item.get("answered") or 0), int(item.get("target") or 0)
            except (TypeError, ValueError):
                return 0, 0
        return 0, 0

    focus = str(normalized.get("focus_dimension") or "").strip()
    if focus in DEFAULT_CAREER_DIMENSIONS:
        a, t = answered_target(focus)
        if t <= 0 or a < t:
            return

    for name in DEFAULT_CAREER_DIMENSIONS:
        a, t = answered_target(name)
        if t > 0 and a < t:
            normalized["focus_dimension"] = name
            return


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
        "focus_dimension": _coerce_career_interview_focus_dimension(payload),
        "is_complete": bool(payload.get("is_complete")),
        "completion_score": _safe_score(payload.get("completion_score"), 0),
        "profile": {
            "summary": str(profile.get("summary") or "").strip(),
            "role_model": str(profile.get("role_model") or "").strip(),
            "key_experience": str(profile.get("key_experience") or "").strip(),
            "leadership_style": str(profile.get("leadership_style") or "").strip(),
            "growth_mindset": str(profile.get("growth_mindset") or "").strip(),
            "career_interests": [str(item).strip() for item in (profile.get("career_interests") or []) if str(item).strip()][:6],
            "work_values": [str(item).strip() for item in (profile.get("work_values") or []) if str(item).strip()][:6],
            "recommended_roles": [str(item).strip() for item in (profile.get("recommended_roles") or []) if str(item).strip()][:6],
            "recommended_exploration": [str(item).strip() for item in (profile.get("recommended_exploration") or []) if str(item).strip()][:6],
            "evidence_highlights": [str(item).strip() for item in (profile.get("evidence_highlights") or []) if str(item).strip()][:6],
            "next_steps": [str(item).strip() for item in (profile.get("next_steps") or []) if str(item).strip()][:6],
            "missing_followups": [str(item).strip() for item in (profile.get("missing_followups") or []) if str(item).strip()][:4],
            "portrait_ready": bool(profile.get("portrait_ready")),
            "output_scope": str(profile.get("output_scope") or "").strip(),
            "coverage_note": str(profile.get("coverage_note") or "").strip(),
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

    if not normalized["profile"]["recommended_roles"]:
        normalized["profile"]["recommended_roles"] = normalized["profile"]["career_interests"][:4]

    if not normalized["profile"]["recommended_exploration"]:
        normalized["profile"]["recommended_exploration"] = normalized["profile"]["next_steps"][:4]

    if not normalized["profile"]["next_steps"]:
        normalized["profile"]["next_steps"] = normalized["profile"]["recommended_exploration"][:4]

    if not normalized["profile"]["evidence_highlights"]:
        evidence_seed = [
            normalized["profile"]["key_experience"],
            normalized["profile"]["growth_mindset"],
            normalized["profile"]["role_model"],
        ]
        normalized["profile"]["evidence_highlights"] = [item for item in evidence_seed if item][:4]

    if not normalized["profile"]["missing_followups"]:
        missing_followups = []
        if not normalized["profile"]["key_experience"]:
            missing_followups.append("补一个最能证明方向选择的真实经历")
        if not normalized["profile"]["work_values"]:
            missing_followups.append("补充你最看重的工作价值观")
        if not normalized["profile"]["leadership_style"]:
            missing_followups.append("补充你在协作中的自然角色")
        normalized["profile"]["missing_followups"] = missing_followups[:4]

    signal_count = sum(
        1
        for item in [
            normalized["profile"]["summary"],
            normalized["profile"]["role_model"],
            normalized["profile"]["key_experience"],
            normalized["profile"]["leadership_style"],
            normalized["profile"]["work_values"],
            normalized["profile"]["recommended_exploration"],
        ]
        if item
    )

    if not normalized["profile"]["output_scope"]:
        if normalized["is_complete"] and signal_count >= 4:
            normalized["profile"]["output_scope"] = "full"
        elif signal_count >= 2:
            normalized["profile"]["output_scope"] = "usable"
        else:
            normalized["profile"]["output_scope"] = "partial"

    if not normalized["profile"]["coverage_note"]:
        if normalized["profile"]["output_scope"] == "full":
            normalized["profile"]["coverage_note"] = "访谈信息已经足够支持完整画像与人物明信片展示。"
        elif normalized["profile"]["output_scope"] == "usable":
            normalized["profile"]["coverage_note"] = "当前访谈基于有限对话已形成首版画像，可直接进入人物明信片生成。"
        else:
            normalized["profile"]["coverage_note"] = "当前访谈只形成了弱信号，适合继续追问后再强化画像。"

    if not normalized["profile"]["portrait_ready"]:
        normalized["profile"]["portrait_ready"] = normalized["profile"]["output_scope"] in {"full", "usable"}

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
        max_tokens=900,
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


def _career_graph_safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _career_graph_edge_confidence(source_id: str, target_id: str, raw_value: float) -> float:
    """
    返回边的置信度，范围 [0.40, 0.95]，服从正态分布 N(0.67, 0.11)。
    - 若原始数据已有有效置信度（>0）：直接裁剪到 [0.40, 0.95]。
    - 若原始数据缺失或为 0：基于 source+target 生成确定性伪随机正态值，
      同一条边每次调用结果一致，不依赖随机种子。
    """
    import hashlib
    import math
    import struct

    if raw_value > 0:
        return round(max(0.40, min(0.95, raw_value)), 3)

    # Box-Muller 变换：用边端点的 SHA-256 哈希生成两个均匀分布随机数
    seed = hashlib.sha256(f"{source_id}|{target_id}".encode()).digest()
    u1_raw, u2_raw = struct.unpack(">II", seed[:8])
    u1 = (u1_raw + 1) / (2 ** 32 + 1)   # (0, 1) 开区间，避免 log(0)
    u2 = (u2_raw + 1) / (2 ** 32 + 1)
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    # N(0.67, 0.11)：均值 0.67 对应区间中点，std=0.11 使 95% 值落在 [0.45, 0.89]
    value = 0.67 + 0.11 * z
    return round(max(0.40, min(0.95, value)), 3)


def _career_graph_level_number(level):
    match = re.search(r"(\d+)", str(level or ""))
    return int(match.group(1)) if match else 1


def _career_graph_unique_values(items, limit=None):
    values = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in values:
            continue
        values.append(text)
        if limit and len(values) >= limit:
            break
    return values


def _career_graph_iter_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _career_graph_iter_values(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _career_graph_iter_values(item)
        return
    text = str(value or "").strip()
    if text:
        yield text


def _career_graph_blob(*values):
    return " ".join(
        part.lower()
        for value in values
        for part in _career_graph_iter_values(value)
    )


def _career_graph_tokens(*values):
    tokens = []
    for value in values:
        for text in _career_graph_iter_values(value):
            normalized = (
                str(text)
                .replace("_", " ")
                .replace("/", " ")
                .replace("-", " ")
                .strip()
            )
            for token in re.findall(r"[A-Za-z0-9#+.]+|[\u4e00-\u9fff]{2,}", normalized.lower()):
                if token and token not in tokens:
                    tokens.append(token)
    return tokens


def _career_graph_overlap(terms, *text_values):
    blob = _career_graph_blob(*text_values)
    tokens = set(_career_graph_tokens(*text_values))
    matches = []
    for raw_term in terms or []:
        term = str(raw_term or "").strip().lower()
        if not term:
            continue
        term_tokens = _career_graph_tokens(term)
        matched = False
        if term in blob:
            matched = True
        elif term_tokens and all(token in tokens or token in blob for token in term_tokens):
            matched = True
        elif len(term) >= 2 and any(part in blob for part in term.split()):
            matched = True
        if matched and raw_term not in matches:
            matches.append(str(raw_term).strip())
    return matches


def _career_graph_major_fit(major, node):
    major_text = str(major or "").strip()
    if not major_text:
        return 60

    family_blob = _career_graph_blob(
        node.get("title"),
        node.get("cluster_name"),
        node.get("career_family"),
        node.get("sub_domain"),
    )
    tech_terms = ["计算机", "软件", "智能", "数据", "数学", "电子", "信息", "自动化", "网络"]
    design_terms = ["设计", "美术", "数字媒体", "交互"]
    product_terms = ["管理", "工业工程", "经济", "统计", "市场", "金融"]
    people_terms = ["人力", "心理", "社会", "法学", "工商"]

    def has_any(source, keywords):
        return any(keyword in source for keyword in keywords)

    if has_any(family_blob, ["后端", "前端", "测试", "算法", "运维", "移动"]):
        if has_any(major_text, tech_terms):
            return 95
        if has_any(major_text, ["统计", "数学", "物理"]):
            return 84
        return 58
    if has_any(family_blob, ["产品"]):
        if has_any(major_text, product_terms + tech_terms):
            return 88
        return 68
    if has_any(family_blob, ["设计"]):
        if has_any(major_text, design_terms):
            return 94
        if has_any(major_text, tech_terms):
            return 76
        return 60
    if has_any(family_blob, ["销售", "HR", "人力"]):
        if has_any(major_text, people_terms + product_terms):
            return 88
        return 70
    return 72


def _career_graph_estimate_requirements(node):
    level_num = _career_graph_level_number(node.get("level"))
    requirements = {
        "professional": 34 + level_num * 11,
        "learning": 48 + level_num * 6,
        "communication": 36 + level_num * 7,
        "innovation": 28 + level_num * 6,
        "stress_tolerance": 34 + level_num * 6,
        "internship": 30 + level_num * 6,
        "execution": 40 + level_num * 7,
    }

    work_scope = str(node.get("work_scope") or "")
    decision_scope = str(node.get("decision_scope") or "")
    collaboration_scope = str(node.get("collaboration_scope") or "")
    people_scope = str(node.get("people_scope") or "")

    if "项目" in work_scope:
        requirements["professional"] += 6
        requirements["execution"] += 5
    if "方向" in work_scope or "模块" in work_scope:
        requirements["innovation"] += 5
        requirements["learning"] += 3
    if decision_scope == "中":
        requirements["innovation"] += 6
        requirements["communication"] += 4
    elif decision_scope == "高":
        requirements["innovation"] += 10
        requirements["communication"] += 8
        requirements["stress_tolerance"] += 6
    if collaboration_scope and collaboration_scope not in {"组内", "无"}:
        requirements["communication"] += 8
    if people_scope and people_scope not in {"无", "0", "零"}:
        requirements["communication"] += 6
        requirements["stress_tolerance"] += 5
        requirements["execution"] += 4

    return {
        key: max(32, min(95, int(value)))
        for key, value in requirements.items()
    }


def _career_graph_capability_fit(capabilities, requirements):
    used = 0
    weighted = 0.0
    gaps = []
    weights = {
        "professional": 0.24,
        "learning": 0.15,
        "communication": 0.17,
        "innovation": 0.12,
        "stress_tolerance": 0.12,
        "internship": 0.08,
        "execution": 0.12,
    }
    labels = {
        "professional": "专业技能",
        "learning": "学习能力",
        "communication": "沟通能力",
        "innovation": "创新能力",
        "stress_tolerance": "抗压能力",
        "internship": "实践能力",
        "execution": "执行能力",
    }
    for key, weight in weights.items():
        score = capabilities.get(key)
        need = requirements.get(key)
        if score is None or need is None:
            continue
        used += 1
        fit = min(112.0, max(28.0, (float(score) / max(float(need), 1.0)) * 100.0))
        weighted += fit * weight
        if float(score) + 8 < float(need):
            gaps.append(f"{labels[key]} {int(score)}/{int(need)}")
    if not used:
        return 58, []
    return int(round(weighted)), gaps[:4]


def _career_graph_collect_profile_inputs(profile_payload):
    payload = profile_payload if isinstance(profile_payload, dict) else {}
    basics = payload.get("basics") if isinstance(payload.get("basics"), dict) else {}
    assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
    interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
    interview_profile = interview.get("profile") if isinstance(interview.get("profile"), dict) else {}
    resume_state = payload.get("resume") if isinstance(payload.get("resume"), dict) else {}
    resume_public = resume_state.get("profile") if isinstance(resume_state.get("profile"), dict) else {}
    resume_profile = resume_public.get("profile") if isinstance(resume_public.get("profile"), dict) else {}
    resume_matcher = resume_public.get("matcher") if isinstance(resume_public.get("matcher"), dict) else {}
    structured_resume = resume_public.get("structured_resume") if isinstance(resume_public.get("structured_resume"), dict) else {}

    capabilities = {}
    for key in ["professional", "learning", "communication", "innovation", "stress_tolerance", "internship", "execution"]:
        item = payload.get("capabilities", {}).get(key) if isinstance(payload.get("capabilities"), dict) else None
        if isinstance(item, dict) and item.get("score") is not None:
            capabilities[key] = int(_career_graph_safe_float(item.get("score")))
        else:
            capabilities[key] = None

    structured_skills = []
    for item in structured_resume.get("skills") or []:
        if isinstance(item, dict):
            structured_skills.append(item.get("skill_name") or item.get("skillName") or "")
        else:
            structured_skills.append(item)

    experience_titles = []
    for item in structured_resume.get("experiences") or []:
        if isinstance(item, dict):
            experience_titles.append(item.get("job_title") or item.get("jobTitle") or "")
            experience_titles.extend(item.get("technologies_used") or item.get("technologiesUsed") or [])

    project_terms = []
    for item in structured_resume.get("projects") or []:
        if isinstance(item, dict):
            project_terms.append(item.get("project_name") or item.get("projectName") or "")
            project_terms.extend(item.get("technologies_used") or item.get("technologiesUsed") or [])

    roles_detected = [
        item.get("role") or item.get("job_title") or ""
        for item in (resume_profile.get("roles_detected") or [])
        if isinstance(item, dict)
    ]

    direction_terms = _career_graph_unique_values(
        [
            basics.get("target_direction"),
            *(payload.get("recommendedRoles") or []),
            *(interview_profile.get("recommended_roles") or []),
            *(resume_matcher.get("recommended_directions") or []),
            *roles_detected,
        ],
        limit=18,
    )

    skill_terms = _career_graph_unique_values(
        [
            *(resume_matcher.get("resume_keywords") or []),
            *structured_skills,
            *experience_titles,
            *project_terms,
        ],
        limit=36,
    )

    mbti = ""
    holland_codes = []
    mbti_state = assessment.get("mbti") if isinstance(assessment.get("mbti"), dict) else {}
    holland_state = assessment.get("holland") if isinstance(assessment.get("holland"), dict) else {}
    if mbti_state.get("completed"):
        mbti = str(
            mbti_state.get("final_type")
            or mbti_state.get("display_type")
            or mbti_state.get("raw_type")
            or ""
        ).strip()
    if holland_state.get("completed"):
        holland_codes = _career_graph_unique_values(
            holland_state.get("top_codes") or holland_state.get("code") or [],
            limit=3,
        )

    return {
        "summary": str(payload.get("summary") or "").strip(),
        "major": str(basics.get("major") or "").strip(),
        "grade": str(basics.get("grade") or basics.get("education_level") or "").strip(),
        "target_city": str(basics.get("target_city") or basics.get("targetCity") or "").strip(),
        "direction_terms": direction_terms,
        "skill_terms": skill_terms,
        "work_values": _career_graph_unique_values(
            [
                *(payload.get("workValues") or []),
                *(interview_profile.get("work_values") or []),
            ],
            limit=8,
        ),
        "mbti": mbti,
        "holland_codes": holland_codes,
        "capabilities": capabilities,
        "missing_items": _career_graph_unique_values(payload.get("missingItems") or [], limit=6),
    }


def _career_graph_compact_node(node, degree=0):
    salary = node.get("salary_range") if isinstance(node.get("salary_range"), dict) else {}
    return {
        "id": str(node.get("node_id") or "").strip(),
        "title": str(node.get("title") or "").strip(),
        "clusterId": str(node.get("cluster_id") or "").strip(),
        "cluster": str(node.get("cluster_name") or "").strip(),
        "family": str(node.get("career_family") or "").strip(),
        "subDomain": str(node.get("sub_domain") or "").strip(),
        "level": str(node.get("level") or "").strip(),
        "skills": _career_graph_unique_values(node.get("skills") or [], limit=12),
        "city": str(node.get("city") or "").strip(),
        "industry": str(node.get("company_industry") or "").strip(),
        "track": str(node.get("track") or "").strip(),
        "years": _career_graph_safe_float(node.get("years_required"), 0),
        "salaryMin": _career_graph_safe_float(salary.get("min"), 0),
        "salaryMax": _career_graph_safe_float(salary.get("max"), 0),
        "workScope": str(node.get("work_scope") or "").strip(),
        "decisionScope": str(node.get("decision_scope") or "").strip(),
        "collaborationScope": str(node.get("collaboration_scope") or "").strip(),
        "peopleScope": str(node.get("people_scope") or "").strip(),
        "nodeType": str(node.get("node_type") or "").strip(),
        "degree": int(degree or 0),
    }


def _load_career_graph_index():
    try:
        mtime = os.path.getmtime(CAREER_GRAPH_FILE)
    except OSError as exc:
        raise FileNotFoundError(CAREER_GRAPH_FILE) from exc

    with CAREER_GRAPH_LOCK:
        if CAREER_GRAPH_CACHE["mtime"] == mtime and CAREER_GRAPH_CACHE["graph"] is not None:
            return CAREER_GRAPH_CACHE

        with open(CAREER_GRAPH_FILE, "r", encoding="utf-8") as fp:
            graph = json.load(fp)

        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        clusters = graph.get("clusters") if isinstance(graph.get("clusters"), list) else []

        node_map = {}
        cluster_map = {}
        adjacency = defaultdict(lambda: {"promotion_out": [], "promotion_in": [], "substitution": []})
        degree_map = defaultdict(int)

        for node in nodes:
            node_id = str(node.get("node_id") or "").strip()
            if node_id:
                node_map[node_id] = node

        for cluster in clusters:
            cluster_id = str(cluster.get("cluster_id") or "").strip()
            if cluster_id:
                cluster_map[cluster_id] = cluster

        compact_edges = []
        for edge in edges:
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            relation = str(edge.get("relation") or "related").strip() or "related"
            if not source or not target or source not in node_map or target not in node_map:
                continue
            normalized_edge = {
                "source": source,
                "target": target,
                "relation": relation,
                "confidence": _career_graph_edge_confidence(
                    source, target, _career_graph_safe_float(edge.get("confidence"), 0)
                ),
                "continuity_score": round(_career_graph_safe_float(edge.get("continuity_score"), 0), 3),
                "uplift_score": round(_career_graph_safe_float(edge.get("uplift_score"), 0), 3),
                "reason": _career_graph_unique_values(edge.get("reason") or [], limit=4),
            }
            compact_edges.append(normalized_edge)
            degree_map[source] += 1
            degree_map[target] += 1
            if relation == "promotion":
                adjacency[source]["promotion_out"].append(normalized_edge)
                adjacency[target]["promotion_in"].append(normalized_edge)
            else:
                adjacency[source]["substitution"].append(normalized_edge)
                adjacency[target]["substitution"].append(normalized_edge)

        cluster_summary = [
            {
                "clusterId": str(item.get("cluster_id") or "").strip(),
                "cluster": str(item.get("cluster_name") or "").strip(),
                "count": int(item.get("count") or len(item.get("member_ids") or [])),
            }
            for item in clusters
        ]
        cluster_summary.sort(key=lambda item: (-item["count"], item["cluster"]))

        bootstrap = {
            "metadata": graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {},
            "filters": {
                "careerFamilies": sorted(
                    {
                        str(node.get("career_family") or "").strip()
                        for node in nodes
                        if str(node.get("career_family") or "").strip()
                    }
                ),
                "levels": sorted(
                    {
                        str(node.get("level") or "").strip()
                        for node in nodes
                        if str(node.get("level") or "").strip()
                    }
                ),
                "clusters": cluster_summary,
            },
            "nodes": [
                _career_graph_compact_node(node, degree_map.get(str(node.get("node_id") or "").strip(), 0))
                for node in nodes
                if str(node.get("node_id") or "").strip()
            ],
            "edges": compact_edges,
        }

        CAREER_GRAPH_CACHE.update(
            {
                "mtime": mtime,
                "graph": graph,
                "node_map": node_map,
                "cluster_map": cluster_map,
                "adjacency": adjacency,
                "bootstrap": bootstrap,
            }
        )
        return CAREER_GRAPH_CACHE


def _career_graph_path_summary(node_id, node_map, adjacency, max_hops=3):
    titles = []
    current_id = str(node_id or "").strip()
    hops = 0
    visited = set()
    while current_id and current_id not in visited and hops < max_hops:
        visited.add(current_id)
        current_node = node_map.get(current_id) or {}
        title = str(current_node.get("title") or "").strip()
        if title:
            titles.append(title)
        promotion_edges = adjacency.get(current_id, {}).get("promotion_out") or []
        current_level = _career_graph_level_number(current_node.get("level"))
        promotion_edges = [
            item for item in promotion_edges
            if _career_graph_level_number((node_map.get(str(item.get("target") or "").strip()) or {}).get("level")) >= current_level
        ] or promotion_edges
        if not promotion_edges:
            break
        next_edge = sorted(
            promotion_edges,
            key=lambda item: (
                -_career_graph_safe_float(item.get("confidence"), 0),
                -_career_graph_safe_float(item.get("uplift_score"), 0),
            ),
        )[0]
        current_id = str(next_edge.get("target") or "").strip()
        hops += 1
    return " → ".join(titles)


def _career_graph_score_candidate(node, profile_inputs, node_map, adjacency):
    node_blob = _career_graph_blob(
        node.get("title"),
        node.get("cluster_name"),
        node.get("career_family"),
        node.get("sub_domain"),
        node.get("skills"),
        node.get("company_industry"),
    )
    node_skill_blob = _career_graph_blob(node.get("skills"))

    direction_hits = _career_graph_overlap(profile_inputs.get("direction_terms"), node_blob)
    skill_hits = _career_graph_overlap(profile_inputs.get("skill_terms"), node_skill_blob)
    target_city = str(profile_inputs.get("target_city") or "").strip()
    city = str(node.get("city") or "").strip()

    direction_score = 58 if not profile_inputs.get("direction_terms") else min(100, 44 + len(direction_hits) * 18)
    if profile_inputs.get("direction_terms") and not direction_hits:
        direction_score = 38

    node_skills = _career_graph_unique_values(node.get("skills") or [], limit=12)
    if node_skills:
        skill_score = 34 + int(round(min(1.0, len(skill_hits) / max(len(node_skills), 1)) * 66))
    else:
        skill_score = 56

    major_score = _career_graph_major_fit(profile_inputs.get("major"), node)

    estimated_years = 0.0
    if "硕" in str(profile_inputs.get("grade") or ""):
        estimated_years = 0.5
    elif "博" in str(profile_inputs.get("grade") or ""):
        estimated_years = 1.0
    target_years = _career_graph_safe_float(node.get("years_required"), 0)
    experience_score = max(40, 100 - int(abs(target_years - estimated_years) * 26))
    if target_years <= 1.0 and _career_graph_level_number(node.get("level")) <= 2:
        experience_score = min(100, experience_score + 8)

    city_score = 62
    if target_city and city:
        city_score = 100 if target_city == city else 46
    elif city:
        city_score = 66

    requirements = _career_graph_estimate_requirements(node)
    capability_score, capability_gaps = _career_graph_capability_fit(profile_inputs.get("capabilities") or {}, requirements)

    overall_score = int(round(
        direction_score * 0.31
        + skill_score * 0.28
        + capability_score * 0.17
        + experience_score * 0.11
        + major_score * 0.08
        + city_score * 0.05
    ))

    missing_skills = [skill for skill in node_skills if skill not in skill_hits][:4]
    reason_lines = []
    if direction_hits:
        reason_lines.append(f"方向信号命中：{'、'.join(direction_hits[:3])}")
    if skill_hits:
        reason_lines.append(f"技能重合：{'、'.join(skill_hits[:4])}")
    if target_city and city and target_city == city:
        reason_lines.append(f"目标城市匹配：{city}")
    if not reason_lines:
        reason_lines.append("当前画像信号有限，本次推荐更依赖岗位图谱结构与基础门槛。")
    if capability_gaps:
        reason_lines.append(f"关键能力缺口：{'、'.join(capability_gaps[:2])}")

    path_summary = _career_graph_path_summary(node.get("node_id"), node_map, adjacency, max_hops=3)
    confidence_inputs = 0
    confidence_inputs += 1 if profile_inputs.get("direction_terms") else 0
    confidence_inputs += 1 if profile_inputs.get("skill_terms") else 0
    confidence_inputs += 1 if any(value is not None for value in (profile_inputs.get("capabilities") or {}).values()) else 0
    confidence_inputs += 1 if profile_inputs.get("major") else 0
    confidence_inputs += 1 if target_city else 0
    confidence_ratio = confidence_inputs / 5.0
    confidence_text = "高" if confidence_ratio >= 0.8 else "中" if confidence_ratio >= 0.5 else "低"

    next_actions = _career_graph_unique_values(
        [
            *(f"补足 {skill} 相关证据或项目" for skill in missing_skills[:2]),
            *(f"提升 {gap}" for gap in capability_gaps[:2]),
            f"优先验证 {node.get('title') or '目标岗位'} 的真实职责与面试要求",
        ],
        limit=4,
    )

    compact_node = _career_graph_compact_node(node)
    compact_node.update(
        {
            "overallScore": max(0, min(100, overall_score)),
            "directionScore": max(0, min(100, direction_score)),
            "skillScore": max(0, min(100, skill_score)),
            "capabilityScore": max(0, min(100, capability_score)),
            "experienceScore": max(0, min(100, experience_score)),
            "majorScore": max(0, min(100, major_score)),
            "cityScore": max(0, min(100, city_score)),
            "confidence": confidence_text,
            "reasonLines": reason_lines[:4],
            "skillHits": skill_hits[:6],
            "missingSkills": missing_skills,
            "capabilityGaps": capability_gaps,
            "path": path_summary or compact_node.get("title") or "",
            "directionLabel": compact_node.get("cluster") or compact_node.get("family") or "",
            "nextActions": next_actions,
        }
    )
    return compact_node


def _career_graph_pick_diverse(candidates, limit):
    selected = []
    selected_ids = set()
    used_clusters = set()

    for item in candidates:
        cluster = str(item.get("cluster") or "").strip()
        node_id = str(item.get("id") or "").strip()
        if not node_id or node_id in selected_ids:
            continue
        if cluster and cluster in used_clusters:
            continue
        selected.append(item)
        selected_ids.add(node_id)
        if cluster:
            used_clusters.add(cluster)
        if len(selected) >= limit:
            return selected

    for item in candidates:
        node_id = str(item.get("id") or "").strip()
        if not node_id or node_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(node_id)
        if len(selected) >= limit:
            break
    return selected


def _career_graph_llm_rerank(profile_inputs, candidates, limit=5):
    base_url, api_key, model = _get_active_provider_and_model()
    if not base_url or not api_key or not candidates:
        return None

    shortlist = []
    for item in candidates[:12]:
        shortlist.append(
            {
                "node_id": item.get("id"),
                "title": item.get("title"),
                "cluster": item.get("cluster"),
                "level": item.get("level"),
                "city": item.get("city"),
                "years_required": item.get("years"),
                "skills": item.get("skills"),
                "score": item.get("overallScore"),
                "reason_lines": item.get("reasonLines"),
                "missing_skills": item.get("missingSkills"),
                "path": item.get("path"),
            }
        )

    system_prompt = (
        "你是职业匹配顾问。请根据用户画像，从候选岗位中挑选最适合的 5 条不同职业方向。"
        "必须兼顾匹配度与方向差异，不要返回 5 个几乎相同的岗位。"
        "只输出 JSON："
        '{"recommendations":[{"node_id":"岗位ID","fit_reason":"不超过60字","direction_label":"方向标签","next_step":"一个具体下一步"}]}'
    )
    user_payload = {
        "profile": {
            "summary": profile_inputs.get("summary"),
            "major": profile_inputs.get("major"),
            "grade": profile_inputs.get("grade"),
            "target_city": profile_inputs.get("target_city"),
            "direction_terms": profile_inputs.get("direction_terms"),
            "skill_terms": profile_inputs.get("skill_terms"),
            "work_values": profile_inputs.get("work_values"),
            "mbti": profile_inputs.get("mbti"),
            "holland_codes": profile_inputs.get("holland_codes"),
            "missing_items": profile_inputs.get("missing_items"),
        },
        "candidates": shortlist,
    }

    try:
        parsed = _call_structured_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
            system_prompt=system_prompt,
            max_tokens=1000,
        )
    except Exception:
        app.logger.exception("career graph llm rerank failed")
        return None

    recommendations = parsed.get("recommendations") if isinstance(parsed, dict) else []
    if not isinstance(recommendations, list):
        return None

    candidate_map = {
        str(item.get("id") or "").strip(): dict(item)
        for item in candidates
        if str(item.get("id") or "").strip()
    }
    selected = []
    selected_ids = set()
    used_clusters = set()
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "").strip()
        if not node_id or node_id not in candidate_map or node_id in selected_ids:
            continue
        candidate = candidate_map[node_id]
        cluster = str(candidate.get("cluster") or "").strip()
        if cluster and cluster in used_clusters:
            continue
        candidate["fitReason"] = str(item.get("fit_reason") or "").strip() or "模型认为该岗位与当前画像较匹配。"
        candidate["directionLabel"] = str(item.get("direction_label") or "").strip() or candidate.get("directionLabel") or ""
        llm_next = str(item.get("next_step") or "").strip()
        if llm_next:
            candidate["nextActions"] = _career_graph_unique_values([llm_next, *(candidate.get("nextActions") or [])], limit=4)
        selected.append(candidate)
        selected_ids.add(node_id)
        if cluster:
            used_clusters.add(cluster)
        if len(selected) >= limit:
            break

    if not selected:
        return None

    return {
        "mode": "llm_reranked",
        "model": model,
        "recommendations": selected,
    }


def _career_graph_node_detail_payload(node_id):
    graph_cache = _load_career_graph_index()
    node_map = graph_cache.get("node_map") or {}
    adjacency = graph_cache.get("adjacency") or {}
    node = node_map.get(str(node_id or "").strip())
    if not node:
        return None

    compact_node = _career_graph_compact_node(node)
    relation_payload = {}
    for bucket_name in ["promotion_out", "promotion_in", "substitution"]:
        items = []
        for edge in sorted(
            adjacency.get(compact_node["id"], {}).get(bucket_name) or [],
            key=lambda item: (-_career_graph_safe_float(item.get("confidence"), 0), item.get("target") or ""),
        )[:10]:
            related_id = edge.get("target") if bucket_name != "promotion_in" else edge.get("source")
            if bucket_name == "substitution":
                related_id = edge.get("target") if edge.get("source") == compact_node["id"] else edge.get("source")
            related_node = node_map.get(str(related_id or "").strip())
            if not related_node:
                continue
            items.append(
                {
                    "edge": edge,
                    "node": _career_graph_compact_node(related_node),
                }
            )
        relation_payload[bucket_name] = items

    detail = dict(node)
    detail["node_id"] = compact_node["id"]
    return {
        "node": detail,
        "summary": compact_node,
        "relations": relation_payload,
        "path": _career_graph_path_summary(compact_node["id"], node_map, adjacency, max_hops=4),
    }


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


@app.route("/api/news-kb/stats")
def api_news_kb_stats():
    try:
        stats = get_kb_stats()
        return jsonify({"data": stats})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/news-kb/search")
def api_news_kb_search():
    query = str(request.args.get("q") or "").strip()
    if not query:
        return jsonify({"message": "请提供查询关键词 q"}), 400
    top_k = min(int(request.args.get("k") or 8), 20)
    try:
        results = search_news_kb(query, top_k=top_k)
        return jsonify({"data": results, "total": len(results)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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


@app.route("/api/community-feed", methods=["GET"])
@_login_required
def api_community_feed():
    return jsonify(_community_forum_payload(_current_user()))


@app.route("/api/community-feed/posts", methods=["POST"])
@_login_required
def api_community_feed_create_post():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    title = _forum_clean_text(payload.get("title"), 80)
    content = _forum_clean_text(payload.get("content"), 2400)
    board = _forum_clean_text(payload.get("board"), 16)
    tags = _forum_normalize_tags(payload.get("tags") or [])
    if len(title) < 4:
        return jsonify({"message": "帖子标题至少需要 4 个字。"}), 400
    if len(content) < 10:
        return jsonify({"message": "帖子内容至少需要 10 个字。"}), 400
    if board not in COMMUNITY_FORUM_BOARD_OPTIONS:
        board = "选岗热议"

    store = _load_community_forum_store()
    now = int(time.time())
    store.setdefault("posts", []).insert(0, {
        "id": f"post_{uuid.uuid4().hex[:10]}",
        "title": title,
        "content": content,
        "board": board,
        "tags": tags,
        "author": {
            "username": user["username"],
            "display_name": user.get("display_name") or user.get("displayName") or user["username"],
        },
        "created_at": now,
        "updated_at": now,
        "pinned": False,
        "views": 1,
        "liked_by": [],
        "replies": [],
        "last_reply_at": now,
        "last_reply_user": "",
    })
    store = _save_community_forum_store(store)
    created_post = _public_community_forum_post(store["posts"][0], user)
    return jsonify({"message": "帖子已发布。", "post": created_post, "feed": _community_forum_payload(user)})


@app.route("/api/community-feed/posts/<post_id>/reply", methods=["POST"])
@_login_required
def api_community_feed_reply(post_id):
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    content = _forum_clean_text(payload.get("content"), 1200)
    if len(content) < 4:
        return jsonify({"message": "回复内容至少需要 4 个字。"}), 400

    store = _load_community_forum_store()
    post = _find_community_forum_post(store, post_id)
    if not post:
        return jsonify({"message": "未找到对应帖子。"}), 404

    now = int(time.time())
    post.setdefault("replies", []).append({
        "id": f"reply_{uuid.uuid4().hex[:10]}",
        "content": content,
        "created_at": now,
        "author": {
            "username": user["username"],
            "display_name": user.get("display_name") or user.get("displayName") or user["username"],
        },
    })
    post["updated_at"] = now
    post["last_reply_at"] = now
    post["last_reply_user"] = user.get("display_name") or user.get("displayName") or user["username"]
    store = _save_community_forum_store(store)
    refreshed = _find_community_forum_post(store, post_id)
    return jsonify({"message": "回复已发送。", "post": _public_community_forum_post(refreshed, user), "feed": _community_forum_payload(user)})


@app.route("/api/community-feed/posts/<post_id>/like", methods=["POST"])
@_login_required
def api_community_feed_like(post_id):
    user = _current_user()
    store = _load_community_forum_store()
    post = _find_community_forum_post(store, post_id)
    if not post:
        return jsonify({"message": "未找到对应帖子。"}), 404

    username = user["username"]
    liked_by = post.setdefault("liked_by", [])
    if username in liked_by:
        liked_by = [item for item in liked_by if item != username]
        post["liked_by"] = liked_by
        liked = False
    else:
        liked_by.append(username)
        post["liked_by"] = liked_by
        liked = True
    post["updated_at"] = int(time.time())
    store = _save_community_forum_store(store)
    refreshed = _find_community_forum_post(store, post_id)
    public_post = _public_community_forum_post(refreshed, user)
    return jsonify({"message": "已更新点赞状态。", "liked": liked, "post": public_post})


@app.route("/api/community-feed/posts/<post_id>/view", methods=["POST"])
@_login_required
def api_community_feed_view(post_id):
    user = _current_user()
    store = _load_community_forum_store()
    post = _find_community_forum_post(store, post_id)
    if not post:
        return jsonify({"message": "未找到对应帖子。"}), 404
    post["views"] = max(0, int(post.get("views") or 0)) + 1
    store = _save_community_forum_store(store)
    refreshed = _find_community_forum_post(store, post_id)
    return jsonify({"message": "浏览次数已记录。", "post": _public_community_forum_post(refreshed, user)})


@app.route("/api/profile-portrait/generate", methods=["POST"])
@_login_required
def api_profile_portrait_generate():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    reuse_brief = bool(payload.get("reuse_brief"))
    context = _normalize_profile_portrait_context(payload.get("context"))
    state = _load_user_state(user["username"])
    saved_portrait = state.get("profile_portrait") if isinstance(state.get("profile_portrait"), dict) else {}
    saved_brief = _normalize_profile_portrait_brief(saved_portrait.get("brief"))
    if not _has_profile_portrait_signal(context) and not saved_brief:
        return jsonify({"message": "当前画像信息不足，先补充测评、简历或目标方向。"}), 400

    base_url, api_key, model = _get_profile_portrait_runtime()
    if not base_url or not api_key:
        return jsonify({"message": "系统中未找到 OpenRouter 图片配置，请先在 system 账号里配置 OpenRouter Provider。"}), 400

    try:
        prompt_packet = _build_profile_portrait_prompt_packet(
            context,
            preset_brief=saved_brief if (reuse_brief and saved_brief) else None,
        )
        brief = prompt_packet.get("brief") or saved_brief or _build_profile_portrait_brief(context)
        prompt_summary = prompt_packet.get("prompt_summary") or _build_profile_portrait_summary_from_brief(brief) or context.get("summary") or ""
        prompt = prompt_packet.get("render_prompt") or _build_profile_portrait_render_prompt(context, brief)
        prompt_writer_mode = str(prompt_packet.get("mode") or "heuristic").strip() or "heuristic"
        prompt_writer_model = str(prompt_packet.get("writer_model") or "").strip()
        prompt_pipeline = prompt_packet.get("prompt_pipeline") if isinstance(prompt_packet.get("prompt_pipeline"), dict) else None
        prompt_evaluation = prompt_packet.get("prompt_evaluation") if isinstance(prompt_packet.get("prompt_evaluation"), dict) else None
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception:
        app.logger.exception("profile portrait brief generation failed")
        return jsonify({"message": "用户画像生成失败，请稍后重试。"}), 502

    image_url = str(saved_portrait.get("image_url") or "").strip() if reuse_brief else ""
    image_error = ""
    status = "ready"
    try:
        image_url = _generate_profile_portrait_image(base_url, api_key, model, prompt)
    except ValueError as exc:
        image_error = str(exc)
        status = "ready" if image_url else "brief_ready"
    except Exception:
        image_error = "鐢诲儚娴锋姤娓叉煋澶辫触锛岃绋嶅悗閲嶈瘯銆?"
        app.logger.exception("profile portrait generation failed")
        status = "ready" if image_url else "brief_ready"

    portrait_state = {
        "status": status,
        "image_url": image_url,
        "created_at": int(time.time()),
        "model": model,
        "archetype_name": context.get("archetype_name") or "",
        "prompt_summary": prompt_summary,
        "prompt_text": prompt,
        "prompt_mode": "reuse_brief" if (reuse_brief and saved_brief) else "rebuild_brief",
        "prompt_writer_mode": prompt_writer_mode,
        "prompt_writer_model": prompt_writer_model,
        "brief_version": PORTRAIT_TEMPLATE_VERSION,
        "prompt_pipeline": prompt_pipeline or {"pipeline_version": PORTRAIT_PROMPT_PIPELINE_VERSION},
        "prompt_evaluation": prompt_evaluation,
        "image_error": image_error,
        "brief": brief,
    }
    state["profile_portrait"] = portrait_state
    _save_user_state(user["username"], state)
    if image_error and image_url:
        message = "已保留上一版海报，本次重绘失败，可稍后再试。"
    elif image_error:
        message = "职业定位已收敛，但海报渲染失败，可直接重试海报。"
    else:
        message = "用户画像已生成。"
    return jsonify({
        "message": "用户画像已生成。",
        "message": message,
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


def _build_llm_caller_for_report(base_url, api_key, model):
    """Build an LLMCaller for the career report agents."""
    if not (base_url and api_key and model):
        return None

    def _caller(messages, system_prompt, max_tokens=3500):
        return _call_markdown_chat(
            base_url,
            api_key,
            model,
            messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    return _caller


def _run_career_report_job(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm):
    stage_defs = {item["key"]: item["label"] for item in CAREER_REPORT_STAGE_DEFS}
    model_name = str(runtime_llm.get("model") or "") if isinstance(runtime_llm, dict) else ""

    # Build LLM caller for agents
    base_url, api_key, _model = _get_active_provider_and_model()
    llm_caller = _build_llm_caller_for_report(base_url, api_key, model_name or _model)
    generation_mode = "llm" if llm_caller else "fallback"

    # Attach caller to runtime_llm
    runtime_llm_with_caller = dict(runtime_llm or {})
    runtime_llm_with_caller["caller"] = llm_caller

    _update_career_report_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="industry_analysis",
        stage_label=stage_defs.get("industry_analysis", "行业分析"),
        stage_detail="正在分析行业趋势与劳动力市场动态",
        progress=build_stage_progress("industry_analysis"),
    )
    _save_career_report_progress(
        username,
        job_id,
        "industry_analysis",
        stage_defs.get("industry_analysis", "行业分析"),
        "正在分析行业趋势与劳动力市场动态",
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
            runtime_llm=runtime_llm_with_caller,
            model_name=model_name,
        )
        _save_career_report_bundle(username, bundle)
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
        _update_career_report_job(
            job_id,
            status="completed",
            finished_at=int(time.time()),
            stage="path_planning",
            stage_label=stage_defs.get("path_planning", "路径规划"),
            stage_detail="报告生成完成",
            message="报告生成完成",
            report_id=str(meta.get("report_id") or report_id),
            progress=build_stage_progress("path_planning"),
        )
        _save_career_report_progress(
            username,
            job_id,
            "path_planning",
            stage_defs.get("path_planning", "路径规划"),
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
            "path_planning",
            stage_defs.get("path_planning", "路径规划"),
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

    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    profile_portrait = state.get("profile_portrait") if isinstance(state.get("profile_portrait"), dict) else {}
    profile_payload = dict(profile_payload)
    profile_payload["feedback_memory"] = _normalize_career_report_feedback(report_state.get("feedback"))
    profile_payload["portrait_prompt_version"] = str(
        ((profile_portrait.get("prompt_pipeline") or {}).get("pipeline_version"))
        or PORTRAIT_PROMPT_PIPELINE_VERSION
    ).strip()

    base_url, api_key, model = _get_active_provider_and_model()
    runtime_llm = {
        "writer": _build_report_markdown_writer(base_url, api_key, model),
        "model": model or "",
    } if (base_url and api_key and model) else {"writer": None, "model": ""}

    job_id = uuid.uuid4().hex
    report_id = f"report-{uuid.uuid4().hex[:12]}"
    stage_label = next((item["label"] for item in CAREER_REPORT_STAGE_DEFS if item["key"] == "industry_analysis"), "行业分析")
    job = {
        "job_id": job_id,
        "username": username,
        "status": "queued",
        "stage": "industry_analysis",
        "stage_label": stage_label,
        "stage_detail": "任务已创建，等待后台编排",
        "message": "",
        "created_at": int(time.time()),
        "started_at": 0,
        "finished_at": 0,
        "report_id": report_id,
        "progress": build_stage_progress("industry_analysis"),
    }
    with CAREER_REPORT_LOCK:
        CAREER_REPORT_JOBS[job_id] = job

    _save_career_report_progress(
        username,
        job_id,
        "industry_analysis",
        stage_label,
        "任务已创建，等待后台编排",
        status="queued",
        report_id=report_id,
        model=str(runtime_llm.get("model") or ""),
        generation_mode="llm",
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
    text = str(payload.get("text") or "").strip()
    if not text:
        return jsonify({"message": "缺少需要润色的报告段落。"}), 400

    text = text[:6000]
    base_url, api_key, model = _get_active_provider_and_model()
    if not (base_url and api_key and model):
        return jsonify({"message": "请先配置可用的模型后再润色报告段落。"}), 400

    system_prompt = (
        "你是职业发展报告编辑。只润色用户提供的报告段落，不新增事实、不改变结论、不编造数据。"
        "保留 Markdown 结构，压缩重复表达，让语言更清晰、专业、适合学生职业规划报告。"
        "如果原文包含 JSON 或表格，只保留必要说明，不改动事实字段。"
    )
    user_msg = f"模块：{section_key or '未指定'}\n\n请润色以下报告段落：\n\n{text}"
    try:
        polished = _call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": user_msg}],
            system_prompt=system_prompt,
            max_tokens=1800,
        )
    except Exception as exc:
        app.logger.exception("career report polish failed")
        return jsonify({"message": str(exc)[:300] or "润色失败。"}), 500

    return jsonify({
        "polished": polished,
        "section_key": section_key,
        "model": model,
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


@app.route("/api/career-graph/bootstrap")
@_login_required
def api_career_graph_bootstrap():
    try:
        payload = _load_career_graph_index().get("bootstrap") or {}
    except FileNotFoundError:
        return jsonify({"message": "职业图谱数据文件不存在。"}), 404
    except Exception:
        app.logger.exception("career graph bootstrap failed")
        return jsonify({"message": "职业图谱加载失败。"}), 500
    return _cache_json_response(payload, max_age=600)


@app.route("/api/career-graph/node/<node_id>")
@_login_required
def api_career_graph_node_detail(node_id):
    try:
        payload = _career_graph_node_detail_payload(node_id)
    except FileNotFoundError:
        return jsonify({"message": "职业图谱数据文件不存在。"}), 404
    except Exception:
        app.logger.exception("career graph node detail failed")
        return jsonify({"message": "岗位详情加载失败。"}), 500
    if not payload:
        return jsonify({"message": "未找到对应岗位节点。"}), 404
    return _cache_json_response(payload, max_age=600)


@app.route("/api/career-graph/match", methods=["POST"])
@_login_required
def api_career_graph_match():
    payload = request.get_json(silent=True) or {}
    profile_payload = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    limit = max(1, min(int(payload.get("limit") or 5), 8))

    try:
        graph_cache = _load_career_graph_index()
    except FileNotFoundError:
        return jsonify({"message": "职业图谱数据文件不存在。"}), 404
    except Exception:
        app.logger.exception("career graph match bootstrap failed")
        return jsonify({"message": "职业图谱加载失败。"}), 500

    profile_inputs = _career_graph_collect_profile_inputs(profile_payload)
    node_map = graph_cache.get("node_map") or {}
    adjacency = graph_cache.get("adjacency") or {}

    candidates = [
        _career_graph_score_candidate(node, profile_inputs, node_map, adjacency)
        for node in node_map.values()
    ]
    candidates.sort(
        key=lambda item: (
            -int(item.get("overallScore") or 0),
            -int(item.get("directionScore") or 0),
            -int(item.get("skillScore") or 0),
            str(item.get("title") or ""),
        )
    )

    deterministic_pool = _career_graph_pick_diverse(candidates, max(limit * 3, 12))
    llm_result = _career_graph_llm_rerank(profile_inputs, deterministic_pool, limit=limit)
    recommendations = llm_result.get("recommendations") if llm_result else deterministic_pool[:limit]
    if not llm_result:
        recommendations = _career_graph_pick_diverse(candidates, limit)

    return jsonify(
        {
            "mode": llm_result.get("mode") if llm_result else "deterministic",
            "model": llm_result.get("model") if llm_result else "",
            "recommendations": recommendations,
            "profileEcho": {
                "targetCity": profile_inputs.get("target_city") or "",
                "targetDirection": (profile_inputs.get("direction_terms") or [""])[0],
                "major": profile_inputs.get("major") or "",
                "missingItems": profile_inputs.get("missing_items") or [],
            },
            "diagnostics": {
                "candidateCount": len(candidates),
                "directionSignals": len(profile_inputs.get("direction_terms") or []),
                "skillSignals": len(profile_inputs.get("skill_terms") or []),
            },
        }
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
    client_focus = str(payload.get("focus_dimension") or "").strip()
    client_progress = payload.get("progress") if isinstance(payload.get("progress"), list) else []
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

    system_prompt = _build_career_interview_prompt(assessment_context) + _career_interview_progress_system_suffix(
        client_focus, client_progress
    )

    try:
        result = _call_openai_compatible_chat(
            base_url,
            api_key,
            model,
            normalized_messages,
            system_prompt=system_prompt,
        )
        _merge_career_interview_focus_with_progress(result, client_progress)
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("career interview failed")
        return jsonify({"message": f"职业访谈生成失败: {exc}"}), 502


@app.route("/api/career-interview/finish", methods=["POST"])
@_login_required
def api_career_interview_finish():
    """用户点击'完成访谈'按钮时调用，生成最终叙事性摘要"""
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    assessment_context = payload.get("assessment_context") if isinstance(payload.get("assessment_context"), dict) else {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

    normalized_messages = []
    for item in messages[-20:]:  # 保留更多历史用于生成摘要
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized_messages.append({"role": role, "content": content[:1600]})

    # 生成叙事性摘要的系统提示词
    finish_prompt = """你是一名职业规划咨询师。用户已点击完成访谈，请根据对话历史生成一份可直接进入统一画像与人物明信片的结构化摘要。

【输出要求】（严格 JSON 格式）
{
  "summary": "一段80字左右的叙事性画像，用第一人称描述用户的职业特征、价值观和潜在优势",
  "role_model": "用户钦佩的人及其原因（从对话提取）",
  "work_values": ["价值观1", "价值观2", "价值观3"],
  "key_experience": "用户提到的最具体的经历或成就",
  "leadership_style": "从对话推断的协作/领导风格",
  "growth_mindset": "成长型思维的体现",
  "recommended_roles": ["最像岗位1", "最像岗位2"],
  "recommended_exploration": ["还可以进一步探索的方向1", "还可以进一步探索的方向2"],
  "evidence_highlights": ["证据1", "证据2", "证据3"],
  "next_steps": ["下一步动作1", "下一步动作2"],
  "missing_followups": ["如果继续访谈，最值得补问的问题1", "问题2"],
  "portrait_ready": true,
  "output_scope": "full 或 usable 或 partial",
  "coverage_note": "说明当前结果是否足够支持首版人物明信片"
}

规则：
1. 如果用户提前结束，但已经形成稳定价值观、经历证据或协作风格，也要给出 usable 级输出。
2. 只有在信号非常少时，才给 partial。
3. 不要泛泛而谈，尽量把摘要压缩成可以直接进入人物画像的材料。
4. 如果某些信息未涉及，可以基于已有内容保守推断，但不要编造。"""

    try:
        result = _call_openai_compatible_chat(
            base_url,
            api_key,
            model,
            normalized_messages,
            system_prompt=_build_career_interview_prompt(assessment_context) + "\n\n" + finish_prompt,
        )
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("career interview finish failed")
        return jsonify({"message": f"生成访谈摘要失败: {exc}"}), 502


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
