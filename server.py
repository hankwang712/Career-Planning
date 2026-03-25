#!/usr/bin/env python3
"""
职业规划智能体 Flask 服务。
运行方式：python server.py
访问地址：http://localhost:8080
"""

import json
import os
import re
import threading
import time
import urllib.parse
import uuid
import webbrowser
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, render_template, request, session
from openai import OpenAI
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from career_news import get_career_news_payload

# 鈹€鈹€ 璺緞閰嶇疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BOSS_INFO_DIR = os.path.join(BASE_DIR, "boss_info")
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")
USERS_FILE = os.path.join(APP_DATA_DIR, "users.json")
LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "llm_configs.json")
LLM_PROVIDERS_FILE = os.path.join(APP_DATA_DIR, "llm_providers.json")
RESUME_LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "resume_llm_config.json")
RESUME_UPLOAD_DIR = os.path.join(APP_DATA_DIR, "user_uploads")
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
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None

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


@app.before_request
def _handle_api_preflight():
    if request.method == "OPTIONS" and request.path.startswith("/api/"):
        return ("", 204)
    return None


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

CAREER_INTERVIEW_SYSTEM_PROMPT = """
你是一名中文职业兴趣访谈代理，需要结合 `career_explorer` 项目中的职业兴趣访谈框架来逐轮提问。
请优先覆盖以下六个维度：职业兴趣、工作价值观、学习方式、沟通风格、行动证据、职业成熟度。

请严格遵守下面的规则：
- 全程使用自然、简洁的中文。
- 每次只提一个问题，优先追问当前最缺的信息。
- 允许结合 RIASEC 视角理解用户，但不要机械解释理论。
- 至少完成 6 轮有效问答，最多不超过 10 个问题。
- 如果用户回答比较空泛，继续追问真实经历或具体例子。
- 不要输出 Markdown，不要输出额外说明，只输出 JSON。

JSON 结构必须严格如下：
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
你是一名中文 MBTI 澄清测评助手。你的任务是根据用户已经完成的 MBTI 主测结果，
针对分数最接近、最不确定的维度，生成少量高区分度的补充题，帮助最终确认 MBTI。

请严格遵守以下规则：
- 全程只使用简洁自然的中文。
- 只针对给定的 close_pairs 生成问题，不要扩展到无关维度。
- 每道题必须只对应一个维度对：EI、SN、TF、JP 之一。
- 问题要贴近日常学习、社交、任务推进和决策场景，避免空泛理论表述。
- 每道题都必须提供鲜明对立的 A / B 两端表述，便于前端渲染 5 档倾向选项。
- 一次返回 2-6 题；如果 close_pairs 只有 1 个，优先返回 2-3 题；如果有多个维度接近，均匀覆盖。
- 不要输出 Markdown，不要输出解释，不要输出代码块，只输出 JSON。

JSON 结构必须严格如下：
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

VALID_USER_STATE_SCOPES = {"career_interview", "assessment_hub", "resume_profile"}
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
    # 优先复用全局“API+模型选择”（头像/模型选择器），保证与其它模块一致
    base_url, api_key, model = _get_active_provider_and_model()
    if base_url and api_key and model:
        return base_url, api_key, model

    # 兼容旧版独立简历配置（迁移兜底）
    config = _load_resume_llm_config()
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip() or "gpt-4o-mini"
    return base_url, api_key, model


# ── 新的多 Provider 数据层 ────────────────────────────────────────────────────

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
    """加载 API 提供商列表，自动迁移旧格式。"""
    _ensure_app_storage()
    with APP_DATA_LOCK:
        # 优先读取独立 providers 文件
        stored = _read_json_file(LLM_PROVIDERS_FILE, None)
        if stored is None:
            # 兼容旧文件：可能存的是 {"providers": [...]} 或旧 scope 结构
            stored = _read_json_file(LLM_CONFIG_FILE, {})

    if not isinstance(stored, dict):
        return []

    # 旧格式迁移：有 career_interview 键说明是旧数据
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
    """从 session 获取用户选择的 provider + model，fallback 到第一个可用 provider。"""
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


def _ensure_app_storage():
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    os.makedirs(USER_STATE_DIR, exist_ok=True)
    os.makedirs(RESUME_UPLOAD_DIR, exist_ok=True)


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

        # 兼容旧数据：若某个 scope 已配置而另一个为空，自动同步，保持一致
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
            # 避免每次请求都做哈希校验，显著降低认证接口延迟。
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


def _save_resume_pdf(file_storage, username):
    if not _allowed_pdf(file_storage):
        raise ValueError("仅支持 PDF 文件上传。")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("上传文件为空。")
    if size > RESUME_MAX_FILE_SIZE:
        raise ValueError(f"PDF 过大，请控制在 {RESUME_MAX_FILE_SIZE // (1024 * 1024)}MB 内。")

    target_dir = _user_upload_dir(username)
    os.makedirs(target_dir, exist_ok=True)
    safe = secure_filename(file_storage.filename or "resume.pdf") or "resume.pdf"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    saved_name = f"{int(time.time())}_{safe}"
    target_path = os.path.join(target_dir, saved_name)
    file_storage.save(target_path)
    return target_path, saved_name, size


def _extract_pdf_text_pages(pdf_path):
    pages = []

    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            for idx, page in enumerate(reader.pages[:RESUME_MAX_PAGES], start=1):
                text = re.sub(r"\s+", " ", str(page.extract_text() or "")).strip()
                if text:
                    pages.append({"page_no": idx, "source": "text", "text": text})
        except Exception:
            pass

    if pages:
        return pages

    if fitz is not None:
        try:
            with fitz.open(pdf_path) as doc:
                for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                    text = re.sub(r"\s+", " ", str(doc[idx].get_text("text") or "")).strip()
                    if text:
                        pages.append({"page_no": idx + 1, "source": "text", "text": text})
        except Exception:
            return pages
    return pages


def _should_fallback_ocr(text_pages):
    if not text_pages:
        return True
    total_chars = sum(len(item.get("text", "")) for item in text_pages)
    return total_chars < 240


def _ocr_pdf_pages(pdf_path):
    if fitz is None or pytesseract is None or Image is None:
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
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
                text = re.sub(r"\s+", " ", str(text or "")).strip()
                if text:
                    pages.append({"page_no": idx + 1, "source": "ocr", "text": text})
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
    raw = str(text or "")
    compact = re.sub(r"\s+", " ", raw)

    def _clean(value):
        return str(value or "").strip().strip("，,。；;:：")

    basics = {
        "major": "",
        "education_level": "",
        "target_city": "",
        "target_direction": "",
    }

    # 专业
    m = re.search(r"(?:专业|主修)\s*[:：]?\s*([^\n，。；;]{2,30})", compact, re.IGNORECASE)
    if m:
        basics["major"] = _clean(m.group(1).replace("专业", ""))
    if not basics["major"]:
        m2 = re.search(r"(?:大学|学院)[^。;\n]{0,24}?([^\s，,。；;]{2,20})专业", compact)
        if m2:
            basics["major"] = _clean(m2.group(1))

    # 学历
    if re.search(r"博士|phd", compact, re.IGNORECASE):
        basics["education_level"] = "博士"
    elif re.search(r"硕士|研究生|master", compact, re.IGNORECASE):
        basics["education_level"] = "硕士"
    elif re.search(r"本科|学士|bachelor", compact, re.IGNORECASE):
        basics["education_level"] = "本科"
    elif re.search(r"大专|专科|college diploma", compact, re.IGNORECASE):
        basics["education_level"] = "大专"

    # 目标城市
    m3 = re.search(r"(?:意向城市|求职意向|期望城市)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if m3:
        basics["target_city"] = _clean(m3.group(1))

    # 目标方向
    m4 = re.search(r"(?:目标方向|意向岗位|求职方向|目标岗位)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if m4:
        basics["target_direction"] = _clean(m4.group(1))

    return basics


def _build_resume_extract_prompt():
    return """
你是“中文简历证据约束画像助手”。
输入是候选人的简历全文（可能来自 OCR），你的目标不是只总结“做过什么”，而是基于证据重建：
1) 他是什么样的人（能力结构）
2) 他做事方式（行为风格）
3) 强项与短板（含边界）
4) 每条结论证据
5) 哪些是推断、哪些待确认

输出必须是 JSON 对象，不要输出任何额外说明。
结构必须包含（兼容字段也必须保留）：
{
  "candidate_summary": "一句话总结（不空泛）",
  "basics": {
    "major": "",
    "education_level": "",
    "target_city": "",
    "target_direction": ""
  },
  "fact_layer": [
    {"fact": "", "category": "education/project/internship/award/certificate/research/organization/other", "evidence": "", "page_no": 1, "source": "text/ocr"}
  ],
  "capability_layer": [
    {
      "dimension": "学习成长/执行落地/责任层级/沟通协同/组织领导/成果影响/行为风格/发展潜力",
      "conclusion": "",
      "reasoning": "",
      "evidence": "",
      "confidence": 0.0,
      "evidence_strength": "high/medium/low",
      "boundary": "事实 or 推断边界"
    }
  ],
  "style_layer": [
    {"style": "", "conclusion": "", "evidence": "", "confidence": 0.0, "boundary": ""}
  ],
  "potential_layer": [
    {"direction": "", "conclusion": "", "evidence": "", "confidence": 0.0, "boundary": "", "suggest_roles": []}
  ],
  "uncertainty_layer": [
    {"item": "", "reason": "", "needed_evidence": "", "confidence": 0.0}
  ],
  "capability_matrix": {
    "learning_growth": 0,
    "execution_delivery": 0,
    "responsibility_scope": 0,
    "communication_coordination": 0,
    "leadership_influence": 0,
    "achievement_impact": 0,
    "behavior_consistency": 0,
    "development_potential": 0
  },
  "roles_detected": [{"role": "负责人/核心成员/成员", "project": "", "evidence": "", "page_no": 1}],
  "leadership_signals": [{"signal": "", "level": "high/medium/low", "evidence": "", "page_no": 1}],
  "competition_records": [{"name": "", "level": "", "ranking": "", "percentile": "", "role": "", "evidence": "", "page_no": 1}],
  "project_highlights": [{"project": "", "goal": "", "contribution": "", "impact": "", "role": "", "evidence": "", "page_no": 1}],
  "skills": [{"name": "", "proficiency": "high/medium/low", "evidence": "", "page_no": 1}],
  "capability_scores": {
    "communication": 0,
    "execution": 0,
    "stress_resilience": 0,
    "innovation": 0,
    "collaboration": 0,
    "leadership": 0
  },
  "evidence_spans": [{"quote": "", "page_no": 1, "source": "text/ocr"}],
  "confidence": 0
}

规则：
1) 严禁编造；缺失字段填 "unknown" 或空数组。
2) 每个结论都要证据绑定；没有证据不得高置信度。
3) 明确区分“事实”和“推断”，并在 boundary 写清楚结论边界。
4) 避免空泛词（如“综合素质高”），改为可验证表述。
5) capability_scores 与 capability_matrix 范围均为 0-100。
6) capability_scores 需保留兼容键：communication/execution/stress_resilience/innovation/collaboration/leadership。
7) 若证据不足，写入 uncertainty_layer，不要过度推断。
""".strip()


def _normalize_resume_profile(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}

    def _norm_basic_value(value):
        text = str(value or "").strip()
        if text.lower() in {"unknown", "n/a", "na", "暂无", "未知", "未提供", "无"}:
            return ""
        return text

    def _norm_items(items, keys):
        result = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            row = {}
            for key in keys:
                value = item.get(key)
                if key == "page_no":
                    try:
                        row[key] = max(1, int(value))
                    except (TypeError, ValueError):
                        row[key] = 1
                else:
                    row[key] = str(value or "").strip()
            result.append(row)
        return result[:20]

    def _norm_confidence(value):
        try:
            conf = float(value)
        except (TypeError, ValueError):
            return 0.0
        if conf > 1:
            conf = conf / 100.0
        return max(0.0, min(1.0, conf))

    def _norm_score(value):
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return 0

    def _pick_score(mapping, *keys):
        for key in keys:
            if key in mapping and str(mapping.get(key) or "").strip() != "":
                return _norm_score(mapping.get(key))
        return 0

    cap = payload.get("capability_scores") if isinstance(payload.get("capability_scores"), dict) else {}
    matrix_payload = payload.get("capability_matrix") if isinstance(payload.get("capability_matrix"), dict) else {}
    cap_merge = {**matrix_payload, **cap}
    capabilities = {}
    capabilities["communication"] = _pick_score(cap_merge, "communication", "communication_coordination")
    capabilities["execution"] = _pick_score(cap_merge, "execution", "execution_delivery")
    capabilities["stress_resilience"] = _pick_score(cap_merge, "stress_resilience", "behavior_consistency")
    capabilities["innovation"] = _pick_score(cap_merge, "innovation", "achievement_impact", "development_potential")
    capabilities["collaboration"] = _pick_score(cap_merge, "collaboration", "communication_coordination")
    capabilities["leadership"] = _pick_score(cap_merge, "leadership", "leadership_influence", "responsibility_scope")

    capability_matrix = {
        "learning_growth": _pick_score(cap_merge, "learning_growth"),
        "execution_delivery": _pick_score(cap_merge, "execution_delivery", "execution"),
        "responsibility_scope": _pick_score(cap_merge, "responsibility_scope", "leadership"),
        "communication_coordination": _pick_score(cap_merge, "communication_coordination", "communication", "collaboration"),
        "leadership_influence": _pick_score(cap_merge, "leadership_influence", "leadership"),
        "achievement_impact": _pick_score(cap_merge, "achievement_impact", "innovation"),
        "behavior_consistency": _pick_score(cap_merge, "behavior_consistency", "stress_resilience"),
        "development_potential": _pick_score(cap_merge, "development_potential", "innovation"),
    }

    try:
        confidence = float(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0

    basics_payload = payload.get("basics") if isinstance(payload.get("basics"), dict) else {}
    basics = {
        "major": _norm_basic_value(basics_payload.get("major")),
        "education_level": _norm_basic_value(basics_payload.get("education_level") or basics_payload.get("grade")),
        "target_city": _norm_basic_value(basics_payload.get("target_city") or basics_payload.get("targetCity")),
        "target_direction": _norm_basic_value(basics_payload.get("target_direction") or basics_payload.get("targetDirection")),
    }

    fact_layer = _norm_items(
        payload.get("fact_layer") or payload.get("facts"),
        ("fact", "category", "evidence", "page_no", "source"),
    )
    capability_layer_raw = payload.get("capability_layer") or payload.get("capability_dimensions")
    style_layer_raw = payload.get("style_layer") or payload.get("behavior_style_layer") or payload.get("behavior_styles")
    potential_layer_raw = payload.get("potential_layer") or payload.get("development_potential_layer")
    uncertainty_layer_raw = payload.get("uncertainty_layer") or payload.get("uncertainty_flags") or payload.get("pending_verification")

    capability_layer = []
    for item in capability_layer_raw or []:
        if not isinstance(item, dict):
            continue
        capability_layer.append(
            {
                "dimension": str(item.get("dimension") or item.get("name") or "").strip(),
                "conclusion": str(item.get("conclusion") or "").strip(),
                "reasoning": str(item.get("reasoning") or item.get("rationale") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "confidence": _norm_confidence(item.get("confidence")),
                "evidence_strength": str(item.get("evidence_strength") or item.get("strength") or "").strip(),
                "boundary": str(item.get("boundary") or "").strip(),
            }
        )
    capability_layer = capability_layer[:16]

    style_layer = []
    for item in style_layer_raw or []:
        if not isinstance(item, dict):
            continue
        style_layer.append(
            {
                "style": str(item.get("style") or item.get("name") or "").strip(),
                "conclusion": str(item.get("conclusion") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "confidence": _norm_confidence(item.get("confidence")),
                "boundary": str(item.get("boundary") or "").strip(),
            }
        )
    style_layer = style_layer[:12]

    potential_layer = []
    for item in potential_layer_raw or []:
        if not isinstance(item, dict):
            continue
        roles = item.get("suggest_roles")
        roles_list = [str(r).strip() for r in (roles if isinstance(roles, list) else []) if str(r).strip()][:6]
        potential_layer.append(
            {
                "direction": str(item.get("direction") or "").strip(),
                "conclusion": str(item.get("conclusion") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
                "confidence": _norm_confidence(item.get("confidence")),
                "boundary": str(item.get("boundary") or "").strip(),
                "suggest_roles": roles_list,
            }
        )
    potential_layer = potential_layer[:10]

    uncertainty_layer = []
    for item in uncertainty_layer_raw or []:
        if not isinstance(item, dict):
            continue
        uncertainty_layer.append(
            {
                "item": str(item.get("item") or item.get("name") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
                "needed_evidence": str(item.get("needed_evidence") or item.get("next_evidence") or "").strip(),
                "confidence": _norm_confidence(item.get("confidence")),
            }
        )
    uncertainty_layer = uncertainty_layer[:12]

    return {
        "candidate_summary": str(payload.get("candidate_summary") or "unknown").strip() or "unknown",
        "basics": basics,
        "fact_layer": fact_layer,
        "capability_layer": capability_layer,
        "style_layer": style_layer,
        "potential_layer": potential_layer,
        "uncertainty_layer": uncertainty_layer,
        "capability_matrix": capability_matrix,
        "roles_detected": _norm_items(payload.get("roles_detected"), ("role", "project", "evidence", "page_no")),
        "leadership_signals": _norm_items(payload.get("leadership_signals"), ("signal", "level", "evidence", "page_no")),
        "competition_records": _norm_items(payload.get("competition_records"), ("name", "level", "ranking", "percentile", "role", "evidence", "page_no")),
        "project_highlights": _norm_items(payload.get("project_highlights"), ("project", "goal", "contribution", "impact", "role", "evidence", "page_no")),
        "skills": _norm_items(payload.get("skills"), ("name", "proficiency", "evidence", "page_no")),
        "capability_scores": capabilities,
        "evidence_spans": _norm_items(payload.get("evidence_spans"), ("quote", "page_no", "source")),
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _extract_resume_profile(pdf_path, progress_callback=None, runtime_llm=None):
    def _report(stage, detail):
        if callable(progress_callback):
            try:
                progress_callback(stage, detail)
            except Exception:
                pass

    _report("extract_text", "正在提取 PDF 文本")
    text_pages = _extract_pdf_text_pages(pdf_path)
    ocr_used = False
    if _should_fallback_ocr(text_pages):
        _report("ocr_fallback", "文本不足，尝试 OCR 回退")
        ocr_pages = _ocr_pdf_pages(pdf_path)
        if ocr_pages:
            text_pages = ocr_pages
            ocr_used = True

    plain_text = _resume_text_bundle(text_pages)
    if not plain_text:
        raise ValueError("未能从 PDF 中提取到有效文本，请检查文件是否损坏或尝试更清晰的扫描件。")

    if (
        isinstance(runtime_llm, (tuple, list))
        and len(runtime_llm) >= 3
    ):
        base_url = str(runtime_llm[0] or "").strip()
        api_key = str(runtime_llm[1] or "").strip()
        model = str(runtime_llm[2] or "").strip()
    else:
        base_url, api_key, model = _get_resume_provider_and_model()
    if not base_url or not api_key:
        raise ValueError("模型尚未就绪，请先在顶部完成模型选择，或联系管理员检查 API 配置。")
    if not model:
        model = "gpt-4o-mini"

    _report("llm_call", "正在调用模型进行结构化提炼")
    messages = [{"role": "user", "content": plain_text}]
    try:
        parsed = _call_structured_chat(
            base_url,
            api_key,
            model,
            messages,
            system_prompt=_build_resume_extract_prompt(),
            max_tokens=2200,
        )
    except ValueError as exc:
        # 结构化输出/模型调用异常属于服务端依赖问题，不应归类为用户请求参数错误。
        raise RuntimeError(f"简历结构化提炼失败：{exc}") from exc
    _report("normalize", "正在校验与归一化分析结果")
    profile = _normalize_resume_profile(parsed)
    inferred = _infer_resume_basics_from_text(plain_text)
    basics = profile.get("basics") if isinstance(profile.get("basics"), dict) else {}
    for key in ("major", "education_level", "target_city", "target_direction"):
        if not str(basics.get(key) or "").strip() and str(inferred.get(key) or "").strip():
            basics[key] = str(inferred[key]).strip()
    profile["basics"] = basics

    return profile, {
        "ocr_used": ocr_used,
        "page_count": len(text_pages),
        "char_count": len(plain_text),
        "parsed_at": int(time.time()),
    }


def _public_resume_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    return {
        "file_name": state.get("file_name") or "",
        "file_size": state.get("file_size") or 0,
        "uploaded_at": state.get("uploaded_at"),
        "analyzed_at": state.get("analyzed_at"),
        "status": state.get("status") or "empty",
        "analysis_meta": state.get("analysis_meta") or {},
        "profile": state.get("profile") if isinstance(state.get("profile"), dict) else None,
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


def _run_resume_analysis_job(username, storage_path, job_id, runtime_llm):
    _update_resume_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="extract_text",
        stage_detail="正在提取 PDF 文本",
        message="",
    )

    def _on_progress(stage, detail):
        _update_resume_job(job_id, stage=stage, stage_detail=detail, message=detail)
        _save_resume_job_progress(username, job_id, stage, detail)

    try:
        profile, analysis_meta = _extract_resume_profile(
            storage_path,
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
                "stage_detail": "分析完成",
                "stage_updated_at": int(time.time()),
            }
        )
        resume_state["analysis_meta"] = merged_meta
        resume_state["profile"] = profile
        resume_state["error_message"] = ""
        state["resume_profile"] = resume_state
        _save_user_state(username, state)
        _update_resume_job(
            job_id,
            status="success",
            stage="done",
            stage_detail="分析完成",
            message="简历分析完成。",
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
        msg = f"简历分析失败：{exc}"
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
    knowledge = _load_assessment_knowledge()
    mbti_data = knowledge.get("mbti") if isinstance(knowledge.get("mbti"), dict) else {}
    dimension_explanations = mbti_data.get("dimension_explanations") if isinstance(mbti_data.get("dimension_explanations"), dict) else {}
    type_details = mbti_data.get("type_details") if isinstance(mbti_data.get("type_details"), dict) else {}

    notes = []
    for item in close_pairs[:4]:
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "").upper().replace("/", "").strip()
        if pair not in {"EI", "SN", "TF", "JP"}:
            continue
        detail = dimension_explanations.get(pair) or {}
        left_label = detail.get("left_label") or pair[0]
        right_label = detail.get("right_label") or pair[1]
        left_desc = _truncate_text(detail.get("left_desc"), 48)
        right_desc = _truncate_text(detail.get("right_desc"), 48)
        tip = _truncate_text(detail.get("development_tip"), 70)
        diff = item.get("diff")
        score_note = f"当前差值 {diff}" if diff is not None else "当前差值较小"
        notes.append(
            f"{pair}（{detail.get('title') or '临界维度'}，{score_note}）："
            f"{left_label}={left_desc}；{right_label}={right_desc}；出题提示：{tip}"
        )

    guessed_type = _guess_mbti_type_from_scores(score_snapshot)
    type_detail = type_details.get(guessed_type) if guessed_type else None
    if isinstance(type_detail, dict):
        strengths = "、".join(_compact_list(type_detail.get("strengths"), limit=3, item_limit=28))
        risks = "、".join(_compact_list(type_detail.get("risks"), limit=2, item_limit=28))
        notes.append(
            f"当前主测倾向 {guessed_type}（{type_detail.get('nickname') or ''}）："
            f"{_truncate_text(type_detail.get('summary'), 80)}"
            f"{' 可能优势：' + strengths if strengths else ''}"
            f"{'；提醒：' + risks if risks else ''}"
        )

    if not notes:
        return base_prompt
    return f"{base_prompt}\n\n补充知识（仅用于提高题目区分度，不要直接复述）：\n- " + "\n- ".join(notes)


def _build_career_interview_prompt(assessment_context):
    base_prompt = CAREER_INTERVIEW_SYSTEM_PROMPT
    context = _normalize_assessment_context(assessment_context)
    mbti = context["mbti"]
    holland = context["holland"]
    basics = context["basics"]

    knowledge = _load_assessment_knowledge()
    mbti_details = ((knowledge.get("mbti") or {}).get("type_details") or {}) if isinstance(knowledge.get("mbti"), dict) else {}
    holland_details = ((knowledge.get("holland") or {}).get("type_details") or {}) if isinstance(knowledge.get("holland"), dict) else {}

    notes = []
    if basics["major"] or basics["grade"] or basics["target_city"] or basics["target_direction"]:
        basics_text = "，".join(
            part for part in [
                f"专业 {basics['major']}" if basics["major"] else "",
                f"学历 {basics['grade']}" if basics["grade"] else "",
                f"目标城市 {basics['target_city']}" if basics["target_city"] else "",
                f"目标方向 {basics['target_direction']}" if basics["target_direction"] else "",
            ]
            if part
        )
        notes.append(f"用户基础信息：{basics_text}")

    mbti_type = mbti["final_type"] or mbti["raw_type"]
    mbti_detail = mbti_details.get(mbti_type) if mbti_type else None
    if isinstance(mbti_detail, dict):
        strengths = "、".join(_compact_list(mbti_detail.get("strengths"), limit=3, item_limit=28))
        risks = "、".join(_compact_list(mbti_detail.get("risks"), limit=2, item_limit=28))
        notes.append(
            f"MBTI 背景：{mbti_type}（{mbti_detail.get('nickname') or ''}），"
            f"{_truncate_text(mbti_detail.get('summary') or mbti['summary'], 90)}"
            f"{'；可能优势：' + strengths if strengths else ''}"
            f"{'；可能盲区：' + risks if risks else ''}"
        )
    elif mbti_type or mbti["summary"]:
        notes.append(f"MBTI 背景：{mbti_type or '已完成'}；{mbti['summary'] or '仅作辅助参考，不要机械贴标签。'}")

    holland_primary = holland["top_codes"][0] if holland["top_codes"] else (holland["code"][:1] if holland["code"] else "")
    holland_detail = holland_details.get(holland_primary) if holland_primary else None
    if isinstance(holland_detail, dict):
        environments = "、".join(_compact_list(holland_detail.get("typical_environment"), limit=3, item_limit=24))
        notes.append(
            f"Holland 背景：主导类型 {holland_primary}/{holland_detail.get('name') or ''}，"
            f"{_truncate_text(holland_detail.get('summary') or holland['summary'], 90)}"
            f"{'；偏好环境：' + environments if environments else ''}"
        )
    elif holland["code"] or holland["summary"]:
        notes.append(f"Holland 背景：{holland['code'] or '已完成'}；{holland['summary'] or '仅作辅助参考。'}")

    if not notes:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        "补充上下文（仅用于更快聚焦，不可替代真实追问，也不要把测评结果直接当作结论）：\n- "
        + "\n- ".join(notes)
    )


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
        raise ValueError("妯″瀷娌℃湁杩斿洖鍐呭")
    cleaned = str(text).strip()
    # 兼容 ```json ... ``` 包裹输出
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("模型返回中没有可解析的JSON对象")
    return match.group(0)


def _parse_structured_json(content):
    raw = str(content or "").strip()
    if not raw:
        raise ValueError("模型没有返回可解析内容。")
    # 1) 直接按 JSON 解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 2) 提取 JSON 对象后解析
    extracted = _extract_json_object(raw)
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        # 3) 本地轻度修复：去除对象/数组尾逗号后再试
        repaired = re.sub(r",(\s*[}\]])", r"\1", extracted)
        return json.loads(repaired)


def _safe_create_chat_completion(client, model, messages, temperature, max_tokens, force_json=False):
    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        return client.chat.completions.create(**kwargs)
    except Exception as exc:
        # 兼容不支持 response_format 的 OpenAI-compatible 服务
        if force_json:
            message = str(exc).lower()
            if "response_format" in message or "json_object" in message:
                kwargs.pop("response_format", None)
                return client.chat.completions.create(**kwargs)
        raise


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


def _call_structured_chat(base_url, api_key, model, messages, system_prompt, max_tokens=480):
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
        )
    except Exception as exc:
        raise ValueError(f"LLM 接口调用失败: {str(exc)[:300]}") from exc

    content = str((resp.choices[0].message.content or "") if resp.choices else "").strip()
    if not content:
        raise ValueError("模型没有返回可解析内容。")
    try:
        return _parse_structured_json(content)
    except Exception:
        # 第一次失败：让模型只做 JSON 修复，不做新推理
        repair_prompt = (
            "你是JSON修复器。请将下面文本修复为严格合法的 JSON 对象。"
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
            )
            repair_content = str((repair_resp.choices[0].message.content or "") if repair_resp.choices else "").strip()
            return _parse_structured_json(repair_content)
        except Exception:
            pass

        # 第二次失败：重新生成，附加强约束并增加 token 上限
        strict_system = (
            system_prompt
            + "\n\n严格要求：必须返回合法JSON对象；"
            + "不得出现注释、代码块、尾逗号、未转义换行。"
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
            )
            retry_content = str((retry_resp.choices[0].message.content or "") if retry_resp.choices else "").strip()
            return _parse_structured_json(retry_content)
        except Exception as exc:
            raise ValueError(f"结构化JSON解析失败: {str(exc)[:280]}") from exc


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

# 鈹€鈹€ 椤甸潰璺敱 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
@app.route("/")
@app.route("/main.html")
def index():
    return render_template("base.html", career_news=get_career_news_payload())


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
        }
    return jsonify(payload)


@app.route("/api/bootstrap")
def api_bootstrap():
    """
    前端首屏聚合接口：减少初始化阶段多次 HTTP 往返。
    未登录时仅返回 authenticated=False，避免 401 打断初始化流程。
    """
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
    """任意已登录用户可更新所有 scope 的模型选择。"""
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
    """使用已保存的凭据获取可用模型列表（所有已登录用户可调用）。"""
    configs = _load_llm_configs()
    config = configs.get("career_interview") or {}
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"models": [], "message": "API 尚未配置，请系统管理员先填写 Base URL 和 API Key。"}), 200
    return _do_fetch_models(base_url, api_key)


@app.route("/api/llm-models/preview", methods=["POST"])
@_super_admin_required
def api_llm_models_preview():
    """管理员用临时凭据预览可用模型（不保存配置）。"""
    payload = request.get_json(silent=True) or {}
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"message": "请先填写 Base URL 和 API Key。"}), 400
    return _do_fetch_models(base_url, api_key)


# ── API：多 Provider 管理 ──────────────────────────────────────────────────

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
        return jsonify({"message": "请填写 Base URL 和 API Key。"}), 400
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
    # 回写 session，保证后续请求一致
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
        return jsonify({"message": "请填写 base_url 与 api_key。"}), 400
    _save_resume_llm_config(current)
    return jsonify(_public_resume_llm_config(_current_user()))


@app.route("/api/resume-llm-models", methods=["GET"])
@_super_admin_required
def api_resume_llm_models():
    config = _load_resume_llm_config()
    base_url = str(config.get("base_url") or "").strip()
    api_key = str(config.get("api_key") or "").strip()
    if not base_url or not api_key:
        return jsonify({"models": [], "message": "请先配置简历模型 base_url 与 api_key。"}), 200
    return _do_fetch_models(base_url, api_key)


@app.route("/api/resume/upload", methods=["POST"])
@_login_required
def api_resume_upload():
    user = _current_user()
    file_storage = request.files.get("file")
    if file_storage is None:
        return jsonify({"message": "请上传 PDF 文件（file 字段）。"}), 400

    try:
        saved_path, saved_name, file_size = _save_resume_pdf(file_storage, user["username"])
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
        "storage_path": saved_path,
        "uploaded_at": int(time.time()),
        "analyzed_at": None,
        "status": "uploaded",
        "analysis_meta": {},
        "profile": None,
        "error_message": "",
    }
    _save_user_state(user["username"], state)
    return jsonify({"message": "简历上传成功。", "data": _public_resume_state(state["resume_profile"])})


@app.route("/api/resume/analyze", methods=["POST"])
@_login_required
def api_resume_analyze():
    user = _current_user()
    state = _load_user_state(user["username"])
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    storage_path = str(resume_state.get("storage_path") or "").strip()
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"message": "未找到已上传简历，请先上传 PDF。"}), 400

    try:
        profile, analysis_meta = _extract_resume_profile(storage_path)
    except ValueError as exc:
        resume_state["status"] = "failed"
        resume_state["error_message"] = str(exc)
        state["resume_profile"] = resume_state
        _save_user_state(user["username"], state)
        return jsonify({"message": str(exc)}), 400
    except RuntimeError as exc:
        app.logger.exception("resume structured extraction failed")
        resume_state["status"] = "failed"
        resume_state["error_message"] = str(exc)
        state["resume_profile"] = resume_state
        _save_user_state(user["username"], state)
        return jsonify({"message": "简历分析失败：模型响应格式异常或服务暂时不可用，请稍后重试。"}), 502
    except Exception as exc:
        app.logger.exception("resume analyze failed")
        resume_state["status"] = "failed"
        resume_state["error_message"] = f"简历分析失败：{exc}"
        state["resume_profile"] = resume_state
        _save_user_state(user["username"], state)
        return jsonify({"message": "简历分析失败，请稍后重试。"}), 502

    resume_state["status"] = "analyzed"
    resume_state["analyzed_at"] = int(time.time())
    resume_state["analysis_meta"] = analysis_meta
    resume_state["profile"] = profile
    resume_state["error_message"] = ""
    state["resume_profile"] = resume_state
    _save_user_state(user["username"], state)
    return jsonify({"message": "简历分析完成。", "data": _public_resume_state(resume_state)})


@app.route("/api/resume/analyze/start", methods=["POST"])
@_login_required
def api_resume_analyze_start():
    user = _current_user()
    username = user["username"]
    state = _load_user_state(username)
    resume_state = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    storage_path = str(resume_state.get("storage_path") or "").strip()
    if not storage_path or not os.path.exists(storage_path):
        return jsonify({"message": "未找到已上传简历，请先上传 PDF。"}), 400

    # 先在请求上下文中解析一次模型配置，避免后台线程访问 session。
    base_url, api_key, model = _get_resume_provider_and_model()
    if not base_url or not api_key:
        return jsonify({"message": "模型尚未就绪，请先在顶部完成模型选择，或联系管理员检查 API 配置。"}), 400
    runtime_llm = (base_url, api_key, model or "gpt-4o-mini")

    running = _find_running_resume_job(username)
    if running:
        return jsonify(
            {
                "message": "已有分析任务在运行中。",
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
        args=(username, storage_path, job_id, runtime_llm),
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
    return jsonify({"message": "简历与解析结果已删除。"})


# ── API：城市列表鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
@app.route("/api/cities")
def api_cities():
    cities = [fname[:-5] for fname in _list_city_files()]
    return _cache_json_response(cities, max_age=3600)


@app.route("/api/jobs/bootstrap")
def api_jobs_bootstrap():
    """
    岗位页聚合接口：一次返回城市列表 + 全量岗位摘要，减少并发请求排队。
    """
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


# ── API：岗位数据 ─────────────────────────────────────────────────────────────────────
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
        return _cache_json_response({"message": "job id 鏍煎紡閿欒"}, status=400)
    except FileNotFoundError:
        return _cache_json_response({"message": "鏈壘鍒板搴旂殑鍩庡競鏁版嵁"}, status=404)
    except IndexError:
        return _cache_json_response({"message": "鏈壘鍒板搴旂殑宀椾綅"}, status=404)

    return _cache_json_response(detail)

@app.route("/api/career-interview", methods=["POST"])
@_login_required
def api_career_interview():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    assessment_context = payload.get("assessment_context") if isinstance(payload.get("assessment_context"), dict) else {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先点击「选择模型」选择要使用的 API 和模型。"}), 400

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
        return jsonify({"message": f"鑱屼笟鍏磋叮璁胯皥璋冪敤澶辫触: {exc}"}), 502


@app.route("/api/mbti-clarifier", methods=["POST"])
@_login_required
def api_mbti_clarifier():
    payload = request.get_json(silent=True) or {}
    base_url, api_key, model = _get_active_provider_and_model()

    if not base_url or not api_key:
        return jsonify({"message": "请先点击「选择模型」选择要使用的 API 和模型。"}), 400

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

# 鈹€鈹€ 鍚姩 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
def open_browser():
    import time
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")

_ensure_app_storage()
_load_users()
_load_providers()   # 触发旧格式迁移

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
