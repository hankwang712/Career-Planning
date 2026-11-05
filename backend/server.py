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
import random

from flask import Flask, has_request_context, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
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
from services.report.workflow import (
    ReportNeedsInput, read_report_workflow, validate_report_request, validate_report_continuation,
)
from services.report.review import apply_availability
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
    export_markdown_to_pdf_via_docx_bytes,
    normalize_br_tags_in_markdown,
    render_markdown_export_html,
    render_report_html,
    render_report_markdown,
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
from services.tools import generate_text_to_image, get_text_to_image_runtime
from services import db as _app_db
from services import auth as _auth
from services.datasets import create_blueprint as create_datasets_blueprint
from services.chat import create_blueprint as create_chat_blueprint
from services.chat.api import create_app as create_chat_app
from services.chat.profile import build_background as build_chat_background
from services.paths import (
    APP_DATA_DIR,
    DATA_DIR,
    PROJECT_ROOT,
    PUBLIC_DATA_DIR,
    STATIC_DIR,
    TEMPLATE_DIR,
)

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")

# 路径配置
BASE_DIR = str(PROJECT_ROOT)
BOSS_INFO_DIR = os.path.join(DATA_DIR, "jobs")
OTHER_CITY_BOSS_JOBS_FILE = os.path.join(DATA_DIR, "cleaned", "other_city_boss_format.json")
# 仅出现在补充数据中的城市：样本数低于该阈值的不进入下拉列表，避免一次性加载过多城市拖慢 bootstrap。
SUPPLEMENT_EXTRA_CITY_MIN_JOBS = int(os.environ.get("SUPPLEMENT_EXTRA_CITY_MIN_JOBS", "5"))
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")
USERS_FILE = os.path.join(APP_DATA_DIR, "users.json")
LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "llm_configs.json")
LLM_PROVIDERS_FILE = os.path.join(APP_DATA_DIR, "llm_providers.json")
RESUME_LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "resume_llm_config.json")
RESUME_UPLOAD_DIR = os.path.join(APP_DATA_DIR, "user_uploads")
CAREER_REPORT_DIR = os.path.join(APP_DATA_DIR, "career_reports")
COMMUNITY_FORUM_FILE = os.path.join(APP_DATA_DIR, "community_forum.json")
PROFILE_PORTRAIT_MODEL = os.environ.get("PROFILE_PORTRAIT_MODEL", "google/gemini-3-pro-image-preview").strip() or "google/gemini-3-pro-image-preview"
TEXT_TO_IMAGE_BASE_URL = os.environ.get("TEXT_TO_IMAGE_BASE_URL", "https://openrouter.ai/api/v1").strip() or "https://openrouter.ai/api/v1"
TEXT_TO_IMAGE_MODEL = os.environ.get("TEXT_TO_IMAGE_MODEL", "google/gemini-3.1-flash-image-preview").strip() or "google/gemini-3.1-flash-image-preview"
TEXT_TO_IMAGE_API_KEY = os.environ.get("TEXT_TO_IMAGE_API_KEY", "").strip()
ASSESSMENT_DATA_FILE = os.path.join(PUBLIC_DATA_DIR, "assessment-data.json")
JOB_CACHE_LOCK = threading.Lock()
APP_DATA_LOCK = threading.Lock()
USER_STATE_LOCK = threading.Lock()
ASSESSMENT_DATA_LOCK = threading.Lock()
JOB_FILE_CACHE = {}
SUPPLEMENT_JOBS_CACHE = {"signature": None, "by_city": None}
ASSESSMENT_DATA_CACHE = {"signature": None, "payload": {}}
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
CAREER_REPORT_LLM_TIMEOUT_SECONDS = max(
    30,
    int(os.environ.get("CAREER_REPORT_LLM_TIMEOUT_SECONDS", "180")),
)
JOB_DETAIL_ONLY_FIELDS = {
    "岗位描述",
    "公司简介",
    "公司福利",
}


class CareerReportCanceled(RuntimeError):
    """Raised inside a background report job when the user cancels it."""


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
    origin = str(request.headers.get("Origin") or "").strip()
    allowed_origins = {request.host_url.rstrip("/"), FRONTEND_ORIGIN.rstrip("/"), VITE_DEV_SERVER_URL}
    if not origin or origin not in allowed_origins:
        return response
    allow_origin = origin
    response.headers["Access-Control-Allow-Origin"] = allow_origin
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
    response.vary.add("Origin")
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
  "readiness_score": 0,
  "topic": "当前主题，如'角色模型'或'生活故事'等",
  "topic_progress": "当前主题的探索进度描述",
  "next_question_policy": {
    "strategy": "fact_example | motive_reason | value_tradeoff | behavior_pref | conflict_clarify | micro_scenario",
    "target_dimension": "职业兴趣",
    "rationale": "为何现在优先追问这一维度（一句话）",
    "expected_information_gain": 0.0
  },
  "dimension_metrics": {
    "职业兴趣": {
      "coverage": 0.0,
      "specificity": 0.0,
      "confidence": 0.0,
      "evidence_count": 0,
      "consistency": 0.0,
      "saturated": false,
      "missing_slots": ["仍缺的具体证据槽位，可为空数组"]
    }
  },
  "profile_hypothesis": {
    "top_roles": [{"name": "产品经理", "score": 0.35}],
    "stable_traits": ["结构化表达强"],
    "unresolved_conflicts": ["若用户既强调自由又强调流程稳定，可写一条待澄清张力"]
  },
  "evidence_cards": [
    {"category": "偏好证据", "bullets": ["从对话可支撑的判断1", "判断2"]},
    {"category": "能力证据", "bullets": []}
  ],
  "conflict_points": [
    {"summary": "自由探索 vs 稳定流程", "clarify_prompt": "可选：用于反证追问的一句话"}
  ],
  "profile": {
    "summary": "一段50字左右的叙事性画像描述",
    "role_model": "用户钦佩的人及原因（从对话中提取）",
    "work_values": ["价值观1", "价值观2", "价值观3"],
    "key_experience": "用户提到的最具体的经历（用于证据）",
    "leadership_style": "从对话推断的领导/协作风格",
    "growth_mindset": "成长型思维的体现",
    "recommended_exploration": ["还可以探索的方向1", "还可以探索的方向2"],
    "missing_followups": ["若继续访谈，最影响职业判断的分歧点还没澄清的一句话（不要只说缺字段）"]
  }
}
规则补充：
- completion_score：仍表示「对话覆盖度」0-100；readiness_score 表示「职业建议可决策度」0-100（证据够具体、冲突已澄清、方向可区分时更高）。
- dimension_metrics：必须为六个维度键各给一份对象；coverage/specificity/confidence/consistency 为 0-1 小数；saturated=true 表示该维证据已够，不必再为凑题数追问。
- 若用户一句话里已同时暴露多维度信息，应同步提高相关维度的 coverage/evidence_count，并在 next_question_policy 里选择「信息增益最大」的追问，而不是死板按顺序。
- conflict_points：当检测到表述张力时填写，用于后续反证追问。
- evidence_cards：用短句沉淀可引用证据，便于前端展示与推荐解释。
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

VALID_USER_STATE_SCOPES = {
    "career_interview",
    "assessment_hub",
    "resume_profile",
    "career_report",
    "career_plans",
    "profile_portrait",
    "account_avatar",
    "profile_snapshot",
    "career_matching",
    "news_context",
}
VALID_LLM_CONFIG_SCOPES = {"career_interview", "assessment_hub"}
COMMUNITY_FORUM_BOARD_OPTIONS = ("面经互助", "简历门诊", "实习内推", "选岗热议", "职场日常")
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


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
    raw = _app_db.load_resume_llm_config()
    if not raw:
        raw = _default_resume_llm_config()
    return _normalized_resume_llm_config(raw)


def _save_resume_llm_config(config):
    normalized = _normalized_resume_llm_config(config)
    _app_db.save_resume_llm_config(normalized)
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
    providers = _app_db.load_providers()
    return [_normalized_provider(p) for p in providers if isinstance(p, dict) and p.get("id")]


def _save_providers(providers):
    normalized = [_normalized_provider(p) for p in providers if isinstance(p, dict) and p.get("id")]
    _app_db.save_providers(normalized)
    return normalized
def _get_active_provider_and_model(selection=None):
    """Read provider/model from an explicit selection or the current session."""
    if isinstance(selection, dict):
        active_selection = selection
    elif has_request_context():
        active_selection = session.get("llm_selection") or {}
    else:
        active_selection = {}
    provider_id = str(active_selection.get("provider_id") or "").strip()
    model = str(active_selection.get("model") or "").strip()

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


def _get_chat_runtime(selection=None):
    runtime = _get_active_provider_and_model(selection)
    if all(runtime):
        return runtime
    from services.chat.config import fallback_chat_runtime
    return fallback_chat_runtime()


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


def _get_text_to_image_runtime(payload=None):
    return get_text_to_image_runtime(
        payload=payload,
        env_api_key=TEXT_TO_IMAGE_API_KEY,
        default_base_url=TEXT_TO_IMAGE_BASE_URL,
        default_model=TEXT_TO_IMAGE_MODEL,
        providers=_load_providers(),
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
    stored = _app_db.load_llm_configs()
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
            _app_db.save_llm_configs(configs)

    if stored != configs:
        _app_db.save_llm_configs(configs)
    return configs


def _save_llm_configs(configs):
    normalized = _default_llm_configs()
    for scope in VALID_LLM_CONFIG_SCOPES:
        normalized[scope] = _normalized_llm_config(configs.get(scope))
    _app_db.save_llm_configs(normalized)
    return normalized


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


def _admin_storage_key(value):
    raw = str(value or "").strip()
    for user in _load_users():
        if raw in {user.get("username"), _user_storage_key(user.get("username"))}:
            return _user_storage_key(user.get("username"))
        if raw == _legacy_storage_key(user.get("username")) and _unique_legacy_owner(user.get("username")):
            return _user_storage_key(user.get("username"))
    return _legacy_storage_key(raw)


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
    return {"structured_profile": resume.get("structured_resume") or {}, "selection": state.get("llm_selection") or {},
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


def _account_storage_paths(storage_key):
    safe_key = _admin_storage_key(storage_key)
    owner = next((item.get("username") for item in _load_users()
                  if _user_storage_key(item.get("username")) == safe_key), None)
    return {
        "storage_key": safe_key,
        "state": os.path.join(USER_STATE_DIR, f"{safe_key}.json"),
        "reports": _private_account_directory(CAREER_REPORT_DIR, owner) if owner else os.path.join(CAREER_REPORT_DIR, safe_key),
        "uploads": _private_account_directory(RESUME_UPLOAD_DIR, owner) if owner else os.path.join(RESUME_UPLOAD_DIR, safe_key),
    }


def _iter_known_account_storage_keys():
    keys = set()
    for user in _load_users():
        keys.add(_user_storage_key(user.get("username")))

    if os.path.isdir(USER_STATE_DIR):
        for name in os.listdir(USER_STATE_DIR):
            if not name.lower().endswith(".json"):
                continue
            keys.add(_admin_storage_key(os.path.splitext(name)[0]))

    for base_dir in (CAREER_REPORT_DIR, RESUME_UPLOAD_DIR):
        if not os.path.isdir(base_dir):
            continue
        for name in os.listdir(base_dir):
            if not name:
                continue
            full_path = os.path.join(base_dir, name)
            if os.path.isdir(full_path):
                keys.add(_admin_storage_key(name))

    return sorted(key for key in keys if key)


def _safe_int_values(*values):
    result = []
    for value in values:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.append(parsed)
    return result


def _max_timestamp_label(*values):
    candidates = _safe_int_values(*values)
    if not candidates:
        return ""
    try:
        return datetime.fromtimestamp(max(candidates)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _build_admin_account_completion(user=None, storage_key=""):
    registered_user = user if isinstance(user, dict) else None
    safe_storage_key = _admin_storage_key(storage_key or (registered_user or {}).get("username"))
    lookup_name = (registered_user or {}).get("username") or safe_storage_key

    state = _load_user_state(lookup_name)
    bundle = _read_career_report_bundle(lookup_name)
    report_state, _ = _sanitize_transient_career_report_state(
        lookup_name,
        state.get("career_report"),
        bundle,
    )
    report_versions = _list_career_report_version_summaries(lookup_name, include_latest=True)
    upload_dir = _user_upload_dir(lookup_name)

    profile_scope = state.get("profile_snapshot") if isinstance(state.get("profile_snapshot"), dict) else {}
    profile_payload = _saved_profile_snapshot_payload(profile_scope)
    profile_ready = bool(profile_payload)

    resume_scope = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    resume_status = str(resume_scope.get("status") or "").strip().lower()
    resume_ready = resume_status in {"analyzed", "ready", "completed"}

    matching_scope = state.get("career_matching") if isinstance(state.get("career_matching"), dict) else {}
    matching_roles = _saved_matching_role_payload(matching_scope)
    matching_ready = bool(matching_roles or bundle.get("match_output"))

    report_meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    report_generated = bool(str(report_meta.get("report_id") or "").strip() and report_document)
    report_runtime_status = str(report_state.get("status") or "").strip().lower()
    report_running = report_runtime_status in {"queued", "running"}
    report_failed = report_runtime_status in {"failed", "error"}

    uploads_count = 0
    if os.path.isdir(upload_dir):
        try:
            uploads_count = sum(1 for name in os.listdir(upload_dir) if os.path.isfile(os.path.join(upload_dir, name)))
        except OSError:
            uploads_count = 0

    milestones = [
        {
            "key": "profile",
            "label": "档案画像",
            "done": profile_ready,
            "status": "completed" if profile_ready else "empty",
        },
        {
            "key": "resume",
            "label": "简历解析",
            "done": resume_ready,
            "status": resume_status or ("uploaded" if uploads_count else "empty"),
        },
        {
            "key": "matching",
            "label": "岗位匹配",
            "done": matching_ready,
            "status": "completed" if matching_ready else "empty",
        },
        {
            "key": "report",
            "label": "正式报告",
            "done": report_generated,
            "status": "running" if report_running else "failed" if report_failed else "completed" if report_generated else report_runtime_status or "empty",
        },
    ]

    completed_count = sum(1 for item in milestones if item["done"])
    completion_percent = int(round((completed_count / max(len(milestones), 1)) * 100))
    if report_running:
        overall_status = "running"
    elif report_failed:
        overall_status = "failed"
    elif completion_percent >= 100:
        overall_status = "completed"
    elif completion_percent <= 0:
        overall_status = "empty"
    else:
        overall_status = "partial"

    last_activity_at = _max_timestamp_label(
        profile_scope.get("updated_at"),
        resume_scope.get("uploaded_at"),
        resume_scope.get("analyzed_at"),
        matching_scope.get("updated_at"),
        report_state.get("updated_at"),
        report_meta.get("generated_at"),
    )

    data_paths = _account_storage_paths(safe_storage_key)
    has_state = os.path.isfile(data_paths["state"])
    has_reports = os.path.isdir(data_paths["reports"]) and any(os.scandir(data_paths["reports"]))
    has_uploads = os.path.isdir(data_paths["uploads"]) and any(os.scandir(data_paths["uploads"]))

    return {
        "account_key": safe_storage_key,
        "username": str((registered_user or {}).get("username") or "").strip(),
        "display_name": str((registered_user or {}).get("display_name") or safe_storage_key).strip() or safe_storage_key,
        "role": str((registered_user or {}).get("role") or "data_only").strip() or "data_only",
        "registered": bool(registered_user),
        "data_only": not bool(registered_user),
        "data_flags": {
            "has_state": bool(has_state),
            "has_reports": bool(has_reports),
            "has_uploads": bool(has_uploads),
            "uploads_count": uploads_count,
            "report_versions": len(report_versions),
        },
        "completion": {
            "percent": completion_percent,
            "completed_count": completed_count,
            "total_count": len(milestones),
            "status": overall_status,
            "milestones": milestones,
        },
        "report_status": {
            "status": report_runtime_status or ("completed" if report_generated else "empty"),
            "stage": str(report_state.get("stage") or "").strip(),
            "detail": str(report_state.get("stage_detail") or report_state.get("detail") or "").strip(),
            "generated": report_generated,
            "generated_at": str(report_meta.get("generated_at") or "").strip(),
            "report_id": str(report_meta.get("report_id") or "").strip(),
        },
        "last_activity_at": last_activity_at,
    }


def _list_admin_accounts():
    users_by_key = {
        _user_storage_key(item.get("username")): item
        for item in _load_users()
        if isinstance(item, dict)
    }
    accounts = []
    for storage_key in _iter_known_account_storage_keys():
        entry = _build_admin_account_completion(users_by_key.get(storage_key), storage_key)
        accounts.append(entry)

    def _sort_key(item):
        return (
            item.get("role") != "super_admin",
            item.get("data_only"),
            -(item.get("completion", {}) or {}).get("percent", 0),
            str(item.get("username") or item.get("account_key") or ""),
        )

    accounts.sort(key=_sort_key)
    summary = {
        "total_accounts": len(accounts),
        "registered_accounts": sum(1 for item in accounts if item.get("registered")),
        "data_only_accounts": sum(1 for item in accounts if item.get("data_only")),
        "completed_reports": sum(1 for item in accounts if (item.get("report_status") or {}).get("generated")),
        "running_reports": sum(1 for item in accounts if (item.get("report_status") or {}).get("status") in {"queued", "running"}),
    }
    return {"accounts": accounts, "summary": summary}


def _remove_account_runtime_jobs(lookup_name):
    lookup_names = {str(lookup_name or "").strip(), _user_storage_key(lookup_name)}
    lookup_names.discard("")

    with RESUME_ANALYSIS_LOCK:
        stale_resume_jobs = [
            job_id
            for job_id, job in RESUME_ANALYSIS_JOBS.items()
            if str((job or {}).get("username") or "").strip() in lookup_names
        ]
        for job_id in stale_resume_jobs:
            RESUME_ANALYSIS_JOBS.pop(job_id, None)

    with CAREER_REPORT_LOCK:
        stale_report_jobs = [
            job_id
            for job_id, job in CAREER_REPORT_JOBS.items()
            if str((job or {}).get("username") or "").strip() in lookup_names
        ]
        for job_id in stale_report_jobs:
            CAREER_REPORT_JOBS.pop(job_id, None)


def _delete_admin_account(account_key, acting_username=""):
    safe_key = _admin_storage_key(account_key)
    if not safe_key:
        raise ValueError("缺少账号标识")

    users = list(_load_users())
    registered_user = next((item for item in users if _user_storage_key(item.get("username")) == safe_key), None)
    registered_username = str((registered_user or {}).get("username") or "").strip()

    if registered_username == "system":
        raise PermissionError("system 账号不能删除")
    if registered_username and registered_username == str(acting_username or "").strip():
        raise PermissionError("不能删除当前登录账号")

    if registered_user:
        chat_service = app.extensions.get("chat_service")
        if chat_service:
            chat_service.memory.delete_owner(registered_username)
            chat_service.documents.forget(registered_username)
        _app_db.delete_user(registered_username)

    lookup_name = registered_username or safe_key
    paths = _account_storage_paths(safe_key)
    for target in (paths["state"],):
        if os.path.isfile(target):
            os.remove(target)
    for target in (paths["reports"], paths["uploads"]):
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)

    _remove_account_runtime_jobs(lookup_name)
    return _build_admin_account_completion(None, safe_key)

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
            "context_snapshot": _normalize_profile_portrait_context(portrait_scope.get("context_snapshot")),
            "prompt_summary": str(portrait_scope.get("prompt_summary") or "").strip(),
        },
        "news_memory": news_scope,
    }


def _forum_clean_text(value, limit=800):
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _forum_clean_content(value, limit):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()[:limit]


def _forum_transaction(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        with COMMUNITY_FORUM_LOCK:
            return view_func(*args, **kwargs)
    return wrapped


def _public_forum_author(author):
    author = author if isinstance(author, dict) else {}
    display = str(author.get("display_name") or "匿名同学")
    if "@" in display and display == author.get("username"):
        display = "同学"
    return {"display_name": display,
            "is_system": author.get("username") == "system"}


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
    username = _forum_clean_text(author.get("username") or fallback_username, 256) or "guest"
    display_name = _forum_clean_text(author.get("display_name") or author.get("displayName") or fallback_display, 32) or "匿名同学"
    return {
        "username": username,
        "display_name": display_name,
    }


def _forum_normalize_reply(raw_reply):
    reply = raw_reply if isinstance(raw_reply, dict) else {}
    content = _forum_clean_content(reply.get("content"), 1200)
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
    content = _forum_clean_content(post.get("content"), 2400)
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
        username = _forum_clean_text(value, 256)
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
    stored = _app_db.load_community_forum()
    created = not isinstance(stored, dict)
    payload = stored if isinstance(stored, dict) else _default_community_forum_payload()
    posts = []
    for item in payload.get("posts") or []:
        normalized_post = _forum_normalize_post(item)
        if normalized_post:
            posts.append(normalized_post)
    normalized = {"posts": posts}
    if created:
        _app_db.save_community_forum(normalized)
    return normalized


def _save_community_forum_store(payload):
    normalized = {"posts": []}
    for item in (payload or {}).get("posts") or []:
        normalized_post = _forum_normalize_post(item)
        if normalized_post:
            normalized["posts"].append(normalized_post)
    _app_db.save_community_forum(normalized)
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
        "author": _public_forum_author(reply.get("author")),
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
        "author": _public_forum_author(post.get("author")),
        "created_at": int(post.get("created_at") or 0),
        "updated_at": int(post.get("updated_at") or 0),
        "pinned": bool(post.get("pinned")),
        "views": int(post.get("views") or 0),
        "likes": len(liked_by),
        "liked": bool(current_username and current_username in liked_by),
        "reply_count": len(replies),
        "replies": replies,
        "last_reply_at": int(post.get("last_reply_at") or post.get("updated_at") or 0),
        "last_reply_user": replies[-1]["author"]["display_name"] if replies else "",
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
        "active_users": len({str(item["author"]["username"]) for post in store.get("posts", [])
                             for item in [post, *(post.get("replies") or [])]
                             if (item.get("author") or {}).get("username")}),
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
    context_snapshot = _normalize_profile_portrait_context(state.get("context_snapshot"))
    if not image_url and not brief:
        return None
    return {
        "status": str(state.get("status") or ("ready" if image_url else "brief_ready")).strip() or "ready",
        "image_url": image_url,
        "created_at": int(state.get("created_at") or 0),
        "model": str(state.get("model") or PROFILE_PORTRAIT_MODEL).strip() or PROFILE_PORTRAIT_MODEL,
        "archetype_name": str(state.get("archetype_name") or "").strip(),
        "prompt_summary": str(state.get("prompt_summary") or "").strip(),
        # 完整图像渲染提示词：供「输入输出链路」折叠区展示完整叙事，不再只显示摘要句
        "prompt_text": str(state.get("prompt_text") or "").strip(),
        "prompt_mode": str(state.get("prompt_mode") or "").strip(),
        "prompt_writer_mode": str(state.get("prompt_writer_mode") or "").strip(),
        "prompt_writer_model": str(state.get("prompt_writer_model") or "").strip(),
        "brief_version": str(state.get("brief_version") or "").strip(),
        "prompt_pipeline": state.get("prompt_pipeline") if isinstance(state.get("prompt_pipeline"), dict) else None,
        "prompt_evaluation": state.get("prompt_evaluation") if isinstance(state.get("prompt_evaluation"), dict) else None,
        "image_error": str(state.get("image_error") or "").strip(),
        "brief": brief,
        "context_snapshot": context_snapshot,
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
        "identity_narrative": _clean_text(context.get("identity_narrative"), 3600),
        "assessment_prose": _clean_text(context.get("assessment_prose"), 3600),
        "extended_tests_prose": _clean_text(context.get("extended_tests_prose"), 3600),
        "module_outputs": {
            "assessment": {
                "status": _clean_text(assessment_output.get("status"), 16),
                "summary": _clean_text(assessment_output.get("summary"), 520),
                "chips": _clean_list(assessment_output.get("chips"), limit=8, item_limit=48),
                "note": _clean_text(assessment_output.get("note"), 320),
                "detail_prose": _clean_text(assessment_output.get("detail_prose"), 3800),
            },
            "resume": {
                "status": _clean_text(resume_output.get("status"), 16),
                "summary": _clean_text(resume_output.get("summary"), 480),
                "chips": _clean_list(resume_output.get("chips"), limit=8, item_limit=64),
                "note": _clean_text(resume_output.get("note"), 220),
            },
            "interview": {
                "status": _clean_text(interview_output.get("status"), 16),
                "summary": _clean_text(interview_output.get("summary"), 2400),
                "chips": _clean_list(interview_output.get("chips"), limit=8, item_limit=64),
                "note": _clean_text(interview_output.get("note"), 420),
                "completion_score": _safe_score(interview_output.get("completion_score"), 0),
                "usable_for_portrait": bool(interview_output.get("usable_for_portrait")),
                "missing_followups": _clean_list(interview_output.get("missing_followups"), limit=4, item_limit=72),
                "forced_supplement": _clean_text(interview_output.get("forced_supplement"), 2400),
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


def _pipeline_interview_supplement(context: dict) -> str:
    """访谈弱信号时，用主画像与测评侧线索强制补一段可写入提示词的叙事。"""
    parts = []
    thesis = str(context.get("summary") or "").strip()
    if thesis:
        parts.append(f"主画像收敛：{thesis[:520]}")
    roles = context.get("top_roles") or []
    if roles:
        parts.append(f"岗位线索：{'、'.join([str(r) for r in roles[:3] if r])}")
    vals = context.get("work_values") or []
    if vals:
        parts.append(f"价值观：{'、'.join([str(v) for v in vals[:4] if v])}")
    mbti = str(context.get("mbti") or "").strip()
    hol = str(context.get("holland") or "").strip()
    if mbti or hol:
        parts.append(f"测评交叉：MBTI {mbti or '—'}；霍兰德 {hol or '—'}。")
    return "\n".join(parts)


def _build_profile_portrait_module_outputs(context):
    raw_modules = context.get("module_outputs") if isinstance(context.get("module_outputs"), dict) else {}
    assessment_raw = raw_modules.get("assessment") if isinstance(raw_modules.get("assessment"), dict) else {}
    resume_raw = raw_modules.get("resume") if isinstance(raw_modules.get("resume"), dict) else {}
    interview_raw = raw_modules.get("interview") if isinstance(raw_modules.get("interview"), dict) else {}

    assessment = {
        "status": str(assessment_raw.get("status") or ("complete" if (context.get("mbti") and context.get("holland")) else ("partial" if (context.get("mbti") or context.get("holland")) else "missing"))).strip(),
        "summary": str(assessment_raw.get("summary") or "｜".join([item for item in [f"MBTI {context.get('mbti')}" if context.get("mbti") else "", f"霍兰德 {context.get('holland')}" if context.get("holland") else ""] if item]) or "尚未形成稳定测评输出").strip(),
        "chips": (assessment_raw.get("chips") if isinstance(assessment_raw.get("chips"), list) else [item for item in [context.get("mbti"), context.get("holland")] if item])[:8],
        "note": str(assessment_raw.get("note") or ("提供人格倾向与职业兴趣的基础锚点。" if (context.get("mbti") or context.get("holland")) else "测评未完成时，人物画像只使用其它模块做弱收敛。")).strip(),
    }
    detail_merge = str(assessment_raw.get("detail_prose") or context.get("assessment_prose") or "").strip()
    if detail_merge:
        assessment["summary"] = f"{assessment['summary']}\n\n【测评长文本与类型补述】\n{detail_merge[:2400]}".strip()

    resume = {
        "status": str(resume_raw.get("status") or ("complete" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "missing")).strip(),
        "summary": str(resume_raw.get("summary") or context.get("resume_summary") or "尚未形成可用的简历证据").strip(),
        "chips": (resume_raw.get("chips") if isinstance(resume_raw.get("chips"), list) else ((context.get("resume_roles") or []) + (context.get("resume_skills") or [])[:3]))[:8],
        "note": str(resume_raw.get("note") or ("提供角色线索、项目证据与技能关键词。" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "没有简历时，人物画像缺少经历证据，只能更多依赖测评和访谈。")).strip(),
    }
    interview_completion_score = _safe_score(interview_raw.get("completion_score"), 0)
    interview = {
        "status": str(interview_raw.get("status") or ("complete" if interview_raw.get("usable_for_portrait") else ("partial" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "missing"))).strip(),
        "summary": str(interview_raw.get("summary") or context.get("interview_summary") or "尚未形成访谈摘要").strip(),
        "chips": (interview_raw.get("chips") if isinstance(interview_raw.get("chips"), list) else ((context.get("interview_values") or []) + (context.get("interview_roles") or []) + (context.get("interview_evidence") or [])))[:8],
        "note": str(interview_raw.get("note") or ("即使提前结束，只要已经形成价值观、经历或协作风格信号，就可以进入首版画像。" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "没有访谈信号时，画像更像静态推断。")).strip(),
        "completion_score": interview_completion_score,
        "usable_for_portrait": bool(interview_raw.get("usable_for_portrait") or context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")),
        "missing_followups": (interview_raw.get("missing_followups") if isinstance(interview_raw.get("missing_followups"), list) else context.get("missing_items") or [])[:4],
    }
    forced = str(interview_raw.get("forced_supplement") or "").strip()
    iv_note = str(interview_raw.get("note") or interview.get("note") or "")
    weak_iv = len(interview["summary"]) < 36 or "弱信号" in iv_note
    if weak_iv:
        extra = forced or _pipeline_interview_supplement(context)
        if extra:
            interview["summary"] = f"{interview['summary']}\n\n【访谈强制补述】\n{extra}".strip()
            interview["usable_for_portrait"] = True
    return {"assessment": assessment, "resume": resume, "interview": interview}


def _normalize_profile_portrait_prompt_packet(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}

    def _clean_text(value, limit=2600):
        return str(value or "").strip()[:limit]

    return {
        "brief": _normalize_profile_portrait_brief(payload.get("brief")),
        "prompt_summary": _clean_text(payload.get("prompt_summary"), 360),
        "render_prompt": _clean_text(payload.get("render_prompt"), 8000),
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
1. 先消化测评输出、简历输出、访谈输出，不要逐条机械复述，但要**把关键气质、岗位语境与证据写进叙事**。
2. 若访谈为弱信号或已合并「强制补述」，必须把补述当作可画面化的线索写进 render_prompt（协作风格、价值取向、推断性神态），并标明哪些是推断。
3. brief 必须用于白底产品页面，信息要清晰、克制、可展示；brief 本身不是长文，但 **render_prompt 必须是长而完整的叙事级提示词**（建议不少于 500 汉字），像美术指导写给插画师的分镜说明。
4. render_prompt 必须是给图像模型的**完整中文**提示词：明确 3:4 纵向、单人、半写实偏写实比例、电影感自然光、无文字无水印、适合人物明信片主视觉；写出**具体场景、机位、服装材质、道具、微表情与体态**。
5. 若输入不足，允许保守收敛，标注不确定性，但不要省略画面约束与气质描写。
6. global_context.identity_narrative、assessment_prose、extended_tests_prose 含「你是谁」级叙事与主测/扩展测评的文字描述；生成 render_prompt 时必须把这些**具体气质、场景、专业语境**融入画面，**禁止**只写 MBTI/霍兰德四字代码或标签堆砌。
7. 若 extended_tests_prose 非空，图像提示中应体现扩展测评里的角色气质或情绪隐喻（抽象转化为职业场景与光影），仍禁止在画面中出现文字。
8. 画风：偏「高端出版物插画 + 写实肤质与布料」、柔和窗光或阴天柔光、浅景深、干净背景；避免廉价滤镜、过度磨皮、赛博霓虹与 Q 版大头。

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

    system_prompt += "如果 profile.target_cities 非空，必须优先选择这些城市内的候选；只有城市内候选不足时，才用其他城市补足。"
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
            "identity_narrative": context.get("identity_narrative") or "",
            "assessment_prose": context.get("assessment_prose") or "",
            "extended_tests_prose": context.get("extended_tests_prose") or "",
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
            max_tokens=4200,
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
                    "尤其要把 render_prompt 扩写到叙事级完整度（画面、光影、道具、神态），不要删除已成立的角色判断。"
                ),
                max_tokens=3600,
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
    identity_narrative = str(context.get("identity_narrative") or "").strip()
    assessment_prose = str(context.get("assessment_prose") or "").strip()
    extended_prose = str(context.get("extended_tests_prose") or "").strip()
    narrative_sections = []
    if identity_narrative:
        narrative_sections.append(f"【叙事·你是谁（访谈与收敛结论，用于气质与神态）】\n{identity_narrative}")
    if assessment_prose:
        narrative_sections.append(f"【主测评文字（MBTI/霍兰德的具体描述，勿仅当作四字代码）】\n{assessment_prose}")
    if extended_prose:
        narrative_sections.append(f"【扩展测评（深层 MBTI / 趣味测评 / SBTI 等详细描述）】\n{extended_prose}")
    narrative_block = "\n\n".join(narrative_sections)
    return (
        "请为职业规划产品生成一张 3:4 纵向单人半写实插画海报，用于白底页面里的任务名片主视觉。"
        "不要文字、不要水印、不要拼贴、不要多人、不要 UI 截图、不要夸张卡通。\n"
        "以下「叙事依据」用于推断人物气质、微表情、肢体语言、工作环境与道具；画面中不得出现任何可读文字。\n"
        + (f"{narrative_block}\n\n" if narrative_block else "")
        + "人物身份（卡片字段）：\n"
        f"- 标题：{title}\n"
        f"- 职业定位：{subtitle}\n"
        f"- 主角色：{normalized_brief.get('primary_role') or '职业探索中'}\n"
        f"- 辅助角色：{support_roles or '不强调'}\n"
        f"- 任务描述：{normalized_brief.get('mission_line') or ''}\n"
        f"- 证据关键词：{evidence_text or '职业新人、方向收敛'}\n"
        f"- 工作价值观：{value_text or '稳定成长、结果导向'}\n"
        f"- 性别提示：{gender}\n"
        f"- 年龄提示：{visual_spec.get('subject_age_hint') or _infer_profile_portrait_age_hint(context)}\n"
        "视觉与画风（须严格遵守）：\n"
        f"- 风格：{visual_spec.get('style') or '半写实职业插画，偏高端出版物/编辑插图质感，肤质与布料纹理清晰，避免塑料磨皮与廉价滤镜'}\n"
        f"- 气质：{visual_spec.get('mood') or '专业、可信赖、沉稳；微表情自然，目光有焦点，肢体语言放松但不松散'}\n"
        f"- 光效：自然窗光或阴天柔光，柔和体积光，适度 rim light；避免刺目顶光、霓虹赛博光、过度镜头光斑\n"
        f"- 穿搭：{visual_spec.get('outfit') or '商务休闲或工程师风职业穿搭，材质可见（棉、针织、夹克），避免夸张 logo'}\n"
        f"- 道具：{visual_spec.get('props') or '笔记本电脑、平板、记事本、中性水杯等职场道具，数量少而有序'}\n"
        f"- 场景：{visual_spec.get('scene') or '明亮现代办公或实验室风工作台，背景干净略虚化（浅景深）'}\n"
        f"- 构图：{visual_spec.get('composition') or '3:4 纵向，单人，胸像到 2/3 身，视线方向留白，主体居中偏三分线'}\n"
        f"- 配色：{visual_spec.get('palette') or '雾蓝、燕麦白、板岩灰与少量暖木色点缀，整体低饱和'}\n"
        "输出要求：人物主体明确，手部结构合理，画面信息密度适中，适合白底产品页左侧主视觉。"
        "负面要求：低清晰度、杂乱背景、比例失调、畸形手部、Q 版大头、贴纸海报风、可读文字、水印、多人同框。"
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
            context.get("identity_narrative"),
            context.get("assessment_prose"),
            context.get("extended_tests_prose"),
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
    if report_document.get("section_order"):
        required_sections = {"personal_traits": "个人画像", "target_job_analysis": "职业目标", "macro_environment": "就业市场",
                             "matching_decision": "岗位适配", "ability_gaps": "能力差距", "development_path": "成长路径",
                             "gap_action_plan": "行动计划", "risk_backup": "动态评估", "appendix": "参考依据"}
    section_keys = {str(item.get("key") or "").strip() for item in section_map if isinstance(item, dict)}
    for key, label in required_sections.items():
        if key not in section_keys or not any(item.get("key") == key and item.get("markdown") for item in section_map):
            issues.append({"level": "warning", "type": "missing_section", "message": f"缺少“{label}”章节。"})

    markdown_value = str(markdown_text or report_document.get("markdown") or "").strip()
    if len(markdown_value) < 600:
        issues.append({"level": "warning", "type": "content_length", "message": "完整报告正文偏短，建议补充行业、差距和行动计划说明。"})

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
    return _call_structured_chat(
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
        raw_diagnosis_ui = _call_structured_chat(
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


def _other_city_jobs_file_signature():
    """用于缓存失效：补充岗位文件不存在时返回稳定占位签名。"""
    if not os.path.isfile(OTHER_CITY_BOSS_JOBS_FILE):
        return ("missing", 0, 0)
    stat = os.stat(OTHER_CITY_BOSS_JOBS_FILE)
    return ("ok", stat.st_mtime_ns, stat.st_size)


def _load_supplement_jobs_by_city():
    """读取 other_city 清洗结果，按城市分组；整文件解析结果带签名缓存。"""
    sig = _other_city_jobs_file_signature()
    with JOB_CACHE_LOCK:
        if SUPPLEMENT_JOBS_CACHE.get("signature") == sig and SUPPLEMENT_JOBS_CACHE.get("by_city") is not None:
            return SUPPLEMENT_JOBS_CACHE["by_city"]
    if sig[0] == "missing":
        empty = {}
        with JOB_CACHE_LOCK:
            SUPPLEMENT_JOBS_CACHE["signature"] = sig
            SUPPLEMENT_JOBS_CACHE["by_city"] = empty
        return empty
    try:
        with open(OTHER_CITY_BOSS_JOBS_FILE, "r", encoding="utf-8") as fp:
            all_jobs = json.load(fp)
    except Exception as exc:
        app.logger.warning("读取补充岗位文件失败 %s：%s", OTHER_CITY_BOSS_JOBS_FILE, exc)
        empty = {}
        with JOB_CACHE_LOCK:
            SUPPLEMENT_JOBS_CACHE["signature"] = sig
            SUPPLEMENT_JOBS_CACHE["by_city"] = empty
        return empty
    if not isinstance(all_jobs, list):
        all_jobs = []
    by_city = {}
    for job in all_jobs:
        if not isinstance(job, dict):
            continue
        c = str(job.get("城市") or job.get("采集城市") or "").strip()
        if not c:
            continue
        by_city.setdefault(c, []).append(job)
    with JOB_CACHE_LOCK:
        SUPPLEMENT_JOBS_CACHE["signature"] = sig
        SUPPLEMENT_JOBS_CACHE["by_city"] = by_city
    return by_city


def _merge_job_records_dedupe(base_jobs, extra_jobs):
    """合并 boss 与补充数据，按公司与岗位等简单指纹去重。

    返回值第二项为「来自补充文件且未被指纹判重剔除」的条数，用于前端标注热门城市。
    """
    seen = set()
    out = []
    supplement_appended = 0

    def fingerprint(job):
        if not isinstance(job, dict):
            return None
        return (
            str(job.get("公司名称") or ""),
            str(job.get("岗位名称") or ""),
            str(job.get("薪资") or ""),
            str(job.get("城市") or job.get("采集城市") or ""),
        )

    for job in base_jobs or []:
        fp = fingerprint(job)
        if fp is None or fp in seen:
            continue
        seen.add(fp)
        out.append(job)
    for job in extra_jobs or []:
        fp = fingerprint(job)
        if fp is None or fp in seen:
            continue
        seen.add(fp)
        out.append(job)
        supplement_appended += 1
    return out, supplement_appended


def _list_job_cities():
    """岗位 API 使用的城市列表：boss_info 文件名 + 补充数据中样本足够的非重复城市。"""
    base = [fname[:-5] for fname in _list_city_files()]
    base_set = set(base)
    try:
        supplement = _load_supplement_jobs_by_city()
    except Exception as exc:
        app.logger.warning("分组补充岗位数据失败：%s", exc)
        supplement = {}
    extra = [
        name
        for name, rows in supplement.items()
        if rows and name not in base_set and len(rows) >= SUPPLEMENT_EXTRA_CITY_MIN_JOBS
    ]
    return sorted(set(base) | set(extra))


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
    boss_exists = os.path.isfile(fpath)
    supplement_sig = _other_city_jobs_file_signature()
    supplement_by_city = _load_supplement_jobs_by_city()
    supplement_rows = supplement_by_city.get(city_name, [])

    if not boss_exists and not supplement_rows:
        raise FileNotFoundError(fname)

    boss_sig = None
    if boss_exists:
        stat = os.stat(fpath)
        boss_sig = (stat.st_mtime_ns, stat.st_size)
    combined_signature = (city_name, boss_sig, supplement_sig)

    with JOB_CACHE_LOCK:
        cached = JOB_FILE_CACHE.get(city_name)
        if cached and cached.get("signature") == combined_signature:
            return cached

    jobs_boss = []
    if boss_exists:
        with open(fpath, "r", encoding="utf-8") as fp:
            jobs_boss = json.load(fp)
        if not isinstance(jobs_boss, list):
            jobs_boss = []

    jobs, supplement_added = _merge_job_records_dedupe(jobs_boss, supplement_rows)

    entry = {
        "signature": combined_signature,
        "jobs": jobs,
        "summaries": None,
        "supplement_added_count": supplement_added,
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
        "\n\n【维度进度快照】（必须遵守）\n"
        "- 完成条件以「证据饱和」为主，不以凑满题数为目标：若某维已在对话中获得足够具体证据，可将 dimension_metrics 中该维 saturated 置为 true。\n"
        "- 用户一句话可能同时覆盖多维：应同步提高相关维度的 coverage / evidence_count，并用 next_question_policy 选择信息增益最大的下一问。\n"
        "- next_question 与 focus_dimension 应优先服务「最大缺口维度」或「冲突澄清」，而非死板按顺序；已答满 target 的维度不得再作为 focus_dimension。\n"
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


def _career_interview_answered_target(client_progress: list, dim_name: str) -> tuple[int, int]:
    for item in client_progress or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != dim_name:
            continue
        try:
            return int(item.get("answered") or 0), int(item.get("target") or 0)
        except (TypeError, ValueError):
            return 0, 0
    return 0, 0


def _apply_next_question_policy_focus(normalized: dict, client_progress: list) -> None:
    """在合法前提下，优先采用模型给出的 next_question_policy.target_dimension（动态选路）。"""
    if not isinstance(normalized, dict):
        return
    pol = normalized.get("next_question_policy") if isinstance(normalized.get("next_question_policy"), dict) else {}
    td = str(pol.get("target_dimension") or "").strip()
    if td not in DEFAULT_CAREER_DIMENSIONS:
        return
    answered, target = _career_interview_answered_target(client_progress, td)
    if target <= 0 or answered >= target:
        return
    normalized["focus_dimension"] = td


def _clamp_unit_float(value, default=0.0):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _attach_career_interview_engine_fields(raw_payload: dict, normalized: dict) -> None:
    """归一化访谈引擎扩展字段：证据指标、假设分布、证据卡与冲突点。"""
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    rs = payload.get("readiness_score")
    if rs is not None:
        normalized["readiness_score"] = _safe_score(rs, 0)
    else:
        normalized["readiness_score"] = _safe_score(normalized.get("completion_score"), 0)

    pol = payload.get("next_question_policy") if isinstance(payload.get("next_question_policy"), dict) else {}
    normalized["next_question_policy"] = {
        "strategy": str(pol.get("strategy") or "").strip()[:56],
        "target_dimension": str(pol.get("target_dimension") or "").strip(),
        "rationale": str(pol.get("rationale") or "").strip()[:320],
        "expected_information_gain": _clamp_unit_float(pol.get("expected_information_gain"), 0.0),
    }

    raw_dm = payload.get("dimension_metrics") if isinstance(payload.get("dimension_metrics"), dict) else {}
    dim_metrics = {}
    for name in DEFAULT_CAREER_DIMENSIONS:
        block = raw_dm.get(name) if isinstance(raw_dm.get(name), dict) else {}
        slots = [str(x).strip() for x in (block.get("missing_slots") or []) if str(x).strip()][:6]
        try:
            evc = int(block.get("evidence_count") or 0)
        except (TypeError, ValueError):
            evc = 0
        evc = max(0, min(12, evc))
        dim_metrics[name] = {
            "coverage": _clamp_unit_float(block.get("coverage")),
            "specificity": _clamp_unit_float(block.get("specificity")),
            "confidence": _clamp_unit_float(block.get("confidence")),
            "consistency": _clamp_unit_float(block.get("consistency")),
            "evidence_count": evc,
            "saturated": bool(block.get("saturated")),
            "missing_slots": slots,
        }
    normalized["dimension_metrics"] = dim_metrics

    ph = payload.get("profile_hypothesis") if isinstance(payload.get("profile_hypothesis"), dict) else {}
    top_roles = []
    for r in ph.get("top_roles") or []:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("name") or "").strip()
        if not nm:
            continue
        top_roles.append({"name": nm[:48], "score": _clamp_unit_float(r.get("score"))})
    normalized["profile_hypothesis"] = {
        "top_roles": top_roles[:8],
        "stable_traits": [str(x).strip() for x in (ph.get("stable_traits") or []) if str(x).strip()][:8],
        "unresolved_conflicts": [str(x).strip() for x in (ph.get("unresolved_conflicts") or []) if str(x).strip()][:6],
    }

    cards = []
    for c in payload.get("evidence_cards") or []:
        if not isinstance(c, dict):
            continue
        cat = str(c.get("category") or "").strip()[:36]
        if not cat:
            continue
        bullets = [str(x).strip() for x in (c.get("bullets") or []) if str(x).strip()][:10]
        if bullets:
            cards.append({"category": cat, "bullets": bullets})
    normalized["evidence_cards"] = cards[:12]

    cps = []
    for cp in payload.get("conflict_points") or []:
        if not isinstance(cp, dict):
            continue
        sm = str(cp.get("summary") or "").strip()
        cq = str(cp.get("clarify_prompt") or "").strip()
        if not sm and not cq:
            continue
        cps.append({"summary": sm[:220], "clarify_prompt": cq[:320]})
    normalized["conflict_points"] = cps[:8]


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

    _attach_career_interview_engine_fields(payload, normalized)

    normalized["assistant_reply"] = (
        normalized["next_question"]
        if not normalized["is_complete"]
        else "访谈完成，我已经整理出你的职业兴趣画像。"
    )
    return normalized


def _call_structured_chat(base_url, api_key, model, messages, system_prompt, max_tokens=480,
                          max_retries=3, base_delay=1.5):
    base = _normalize_sdk_base_url(base_url)
    client = OpenAI(
        api_key=api_key,
        base_url=base,
        timeout=CAREER_REPORT_LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
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
    client = OpenAI(
        api_key=api_key,
        base_url=base,
        timeout=CAREER_REPORT_LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
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
        max_tokens=1400,
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


@app.route("/multi-agent-workflow")
@app.route("/multi-agent-workflow.html")
def multi_agent_workflow_page():
    if not _current_user():
        return redirect(url_for("index"))
    return send_from_directory(
        STATIC_DIR,
        "multi-agent-workflow.html",
        mimetype="text/html"
    )


@app.route("/user-center")
@app.route("/user-center.html")
def user_center_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("user_center.html")


@app.route("/user-center/career-report/polish")
@app.route("/user-center/career-report/polish.html")
def career_report_polish_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("career_report_polish.html")


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


@app.route("/sbti")
@app.route("/sbti.html")
def sbti_page():
    if not _current_user():
        return redirect(url_for("index"))
    return render_template("sbti.html")


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
        career_report_bundle = _read_career_report_bundle(user["username"])
        career_report_state, career_report_state_changed = _sanitize_transient_career_report_state(
            user["username"],
            career_report_state,
            current_bundle=career_report_bundle,
        )
        if career_report_state_changed:
            state["career_report"] = career_report_state
            _save_user_state(user["username"], state)
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
            "profile_portrait": _public_profile_portrait_state(state.get("profile_portrait")),
            "account_avatar": state.get("account_avatar"),
            "profile_snapshot": state.get("profile_snapshot"),
            "career_matching": state.get("career_matching"),
            "news_context": state.get("news_context"),
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
            "profile_portrait": _public_profile_portrait_state(state.get("profile_portrait")),
            "profile_snapshot": state.get("profile_snapshot"),
            "career_matching": state.get("career_matching"),
            "news_context": state.get("news_context"),
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




@app.route("/api/admin/accounts", methods=["GET"])
@_super_admin_required
def api_admin_accounts():
    return jsonify(_list_admin_accounts())


@app.route("/api/admin/accounts/<path:account_key>", methods=["DELETE"])
@_super_admin_required
def api_admin_account_delete(account_key):
    acting_user = _current_user() or {}
    try:
        deleted = _delete_admin_account(account_key, acting_username=acting_user.get("username"))
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"message": str(exc)}), 403
    return jsonify(
        {
            "message": "账号及关联数据已删除。",
            "deleted": deleted,
            **_list_admin_accounts(),
        }
    )


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
@_forum_transaction
def api_community_feed():
    return jsonify(_community_forum_payload(_current_user()))


@app.route("/api/community-feed/posts", methods=["POST"])
@_login_required
@_forum_transaction
def api_community_feed_create_post():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    title = _forum_clean_text(payload.get("title"), 80)
    content = _forum_clean_content(payload.get("content"), 2400)
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
@_forum_transaction
def api_community_feed_reply(post_id):
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    content = _forum_clean_content(payload.get("content"), 1200)
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
@_forum_transaction
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
@_forum_transaction
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


@app.route("/api/tools/text-to-image", methods=["POST"])
@_login_required
def api_tools_text_to_image():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or payload.get("text") or "").strip()
    if not prompt:
        return jsonify({"message": "请传入 prompt。"}), 400

    aspect_ratio = str(payload.get("aspect_ratio") or "").strip()
    base_url, api_key, model = _get_text_to_image_runtime(payload)
    if not api_key:
        return jsonify({
            "message": "未找到可用的 OpenRouter key。你可以在请求体中传 api_key，或配置 TEXT_TO_IMAGE_API_KEY / 系统 OpenRouter Provider。"
        }), 400

    try:
        result = generate_text_to_image(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
        )
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 502
    except Exception:
        app.logger.exception("text to image generation failed")
        return jsonify({"message": "图片生成失败，请稍后再试。"}), 502

    return jsonify({
        "message": "图片已生成。",
        "data": {
            "prompt": prompt,
            "model": model,
            "base_url": _normalize_sdk_base_url(base_url),
            "aspect_ratio": aspect_ratio,
            **result,
        },
    })


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
        "context_snapshot": context,
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

    def _stage_callback(stage_key, stage_label, detail):
        _ensure_not_cancelled()
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
            runtime_llm=runtime_llm_with_caller,
            model_name=model_name,
        )
        _ensure_not_cancelled()
        _log("编排返回，开始写入报告文件")
        _save_career_report_bundle(username, bundle)
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
            shared_memory = app.extensions["chat_service"].career_context(username)
            if not workflow_request.get("preferences") and shared_memory["preferences"]:
                workflow_request["preferences"] = shared_memory["preferences"]
            availability, preferences = apply_availability(payload.get("availability"), workflow_request.get("preferences", ""))
            if availability:
                profile_payload["report_availability"] = availability
                workflow_request["preferences"] = preferences
            historical_context = "\n".join(filter(None, [shared_memory["evidence"],
                "历史偏好（当前用户输入优先）：" + shared_memory["preferences"] if shared_memory["preferences"] else ""]))
            if historical_context:
                evidence = str(workflow_request.get("additional_evidence") or "")
                prefix = "\n历史用户原文（当前简历和当前输入优先）：\n"
                remaining = 20000 - len(evidence) - len(prefix)
                if remaining > 0:
                    workflow_request["additional_evidence"] = evidence + prefix + historical_context[:remaining]
            profile_payload["agent_workflow"] = validate_report_request(workflow_request, raw_resume, file_path=resume_path)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"message": str(exc)}), 400
    except ImportError:
        return jsonify({"message": "请先安装 backend/requirements.txt 中的 Agent 依赖。"}), 503

    selection_snapshot = session.get("llm_selection") if isinstance(session.get("llm_selection"), dict) else {}
    # The report and assistant both reuse experiments/.env when no UI provider is configured.
    base_url, api_key, model = _get_chat_runtime(selection_snapshot)
    if not (base_url and api_key and model):
        _career_report_console_log(report_id, "启动请求被拒绝", reason="model_not_configured")
        return jsonify({"message": "未找到可用的对话模型，请在主系统配置模型，或补全 experiments/.env 中的 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL。"}), 400
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
        polished = _call_markdown_chat(
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
        return app.response_class(
            html_for_render or "",
            mimetype="text/html; charset=utf-8",
            headers={"Content-Disposition": _attachment_content_disposition(f"{filename_stem}.html")},
        )

    if export_format == "pdf":
        try:
            pdf_bytes = export_markdown_to_pdf_via_docx_bytes(markdown_text, title=source_label)
        except Exception as exc:
            app.logger.exception("career report pdf export failed")
            return jsonify({"message": str(exc)[:500] or "PDF 导出失败。"}), 500
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{filename_stem}.pdf",
        )

    try:
        docx_bytes = export_markdown_to_docx_bytes(markdown_text, title=source_label)
    except Exception as exc:
        app.logger.exception("career report docx export failed")
        return jsonify({"message": str(exc)[:500] or "DOCX 导出失败。"}), 500

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{filename_stem}.docx",
    )


@app.route("/api/cities")
def api_cities():
    cities = _list_job_cities()
    return _cache_json_response(cities, max_age=3600)


def _jobs_bootstrap_payload():
    """聚合 bootstrap 岗位摘要，并附带 boss_info 城市列表与补充数据热度信息。"""
    cities = _list_job_cities()
    boss_cities = [fname[:-5] for fname in _list_city_files()]
    jobs = []
    city_supplement_extra_count = {}
    boss_city_set = set(boss_cities)
    for city_name in cities:
        try:
            summaries = _get_city_job_summaries(city_name)
            jobs.extend(summaries)
            if city_name in boss_city_set:
                entry = _get_city_cache_entry(city_name)
                n = int(entry.get("supplement_added_count") or 0)
                if n > 0:
                    city_supplement_extra_count[city_name] = n
        except FileNotFoundError:
            continue
        except Exception as exc:
            app.logger.warning("读取 %s 失败：%s", city_name, exc)
    return {
        "cities": cities,
        "boss_cities": boss_cities,
        "city_supplement_extra_count": city_supplement_extra_count,
        "jobs": jobs,
    }


@app.route("/api/jobs/bootstrap")
def api_jobs_bootstrap():
    """Return cities and job summaries in one payload for bootstrap usage."""
    return _cache_json_response(_jobs_bootstrap_payload())


# API：岗位数据
@app.route("/api/jobs")
def api_jobs():
    city = str(request.args.get("city", "all") or "all").strip() or "all"
    view = str(request.args.get("view", "full") or "full").strip().lower()
    if view == "bootstrap":
        return _cache_json_response(_jobs_bootstrap_payload())
    jobs = []

    cities = _list_job_cities() if city == "all" else [city]

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
        _apply_next_question_policy_focus(result, client_progress)
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

def _prewarm_caches():
    """后台预热重载数据，避免首次请求阻塞。"""
    def _warm_news():
        try:
            get_career_news_payload()
        except Exception:
            pass

    threading.Thread(target=_warm_news, daemon=True, name="prewarm-news").start()


_ensure_app_storage()
_app_db.init_db()
_auth.init_app(app)
app.register_blueprint(create_datasets_blueprint(_login_required))
_chat_blueprint = create_chat_blueprint(
    directory=APP_DATA_DIR / "assistant",
    current_user=_current_user,
    runtime_provider=_get_chat_runtime,
    profile_provider=lambda username: build_chat_background(_load_user_state(username), _read_career_report_bundle(username)),
    resume_provider=_chat_resume_source,
)
app.register_blueprint(_chat_blueprint)
app.extensions["chat_service"] = _chat_blueprint.chat_service
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
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    if auto_open_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(asgi_app, host=host, port=port)
