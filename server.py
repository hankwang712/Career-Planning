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
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

# 鈹€鈹€ 璺緞閰嶇疆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BOSS_INFO_DIR = os.path.join(BASE_DIR, "boss_info")
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")
USERS_FILE = os.path.join(APP_DATA_DIR, "users.json")
LLM_CONFIG_FILE = os.path.join(APP_DATA_DIR, "llm_configs.json")
ASSESSMENT_DATA_FILE = os.path.join(BASE_DIR, "static", "assessment-data.json")
JOB_CACHE_LOCK = threading.Lock()
APP_DATA_LOCK = threading.Lock()
ASSESSMENT_DATA_LOCK = threading.Lock()
JOB_FILE_CACHE = {}
ASSESSMENT_DATA_CACHE = {"signature": None, "payload": {}}
JOB_CACHE_MAX_AGE_SECONDS = 900
JOB_DETAIL_ONLY_FIELDS = {
    "岗位描述",
    "公司简介",
    "公司福利",
}

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

VALID_USER_STATE_SCOPES = {"career_interview", "assessment_hub"}
VALID_LLM_CONFIG_SCOPES = {"career_interview", "assessment_hub"}


def _default_llm_configs():
    return {
        "career_interview": {"base_url": "", "api_key": "", "model": "gpt-4o-mini"},
        "assessment_hub": {"base_url": "", "api_key": "", "model": "gpt-4o-mini"},
    }


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
            _write_json_file(LLM_CONFIG_FILE, {"providers": providers})
        return providers

    raw_list = stored.get("providers") or []
    if not isinstance(raw_list, list):
        return []
    return [_normalized_provider(p) for p in raw_list if isinstance(p, dict) and p.get("id")]


def _save_providers(providers):
    normalized = [_normalized_provider(p) for p in providers if isinstance(p, dict) and p.get("id")]
    with APP_DATA_LOCK:
        _write_json_file(LLM_CONFIG_FILE, {"providers": normalized})
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
            if not password_hash or not check_password_hash(password_hash, spec["password"]):
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
        return users


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
    with APP_DATA_LOCK:
        state = _read_json_file(path, {})
        return state if isinstance(state, dict) else {}


def _save_user_state(username, payload):
    _ensure_app_storage()
    normalized = payload if isinstance(payload, dict) else {}
    path = _user_state_path(username)
    with APP_DATA_LOCK:
        _write_json_file(path, normalized)
    return normalized


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
            "grade": _truncate_text(basics_raw.get("grade") or "", 20),
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
                f"年级 {basics['grade']}" if basics["grade"] else "",
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


def _normalize_chat_base_url(base_url):
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url 蹇呴』鏄畬鏁寸殑 http(s) 鍦板潃")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    if cleaned.endswith("/v1"):
        return f"{cleaned}/chat/completions"
    return f"{cleaned}/v1/chat/completions"


def _extract_json_object(text):
    if not text:
        raise ValueError("妯″瀷娌℃湁杩斿洖鍐呭")
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("模型返回中没有可解析的JSON对象")
    return match.group(0)


def _response_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("妯″瀷鍝嶅簲缂哄皯 choices")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content or "").strip()


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
    endpoint = _normalize_chat_base_url(base_url)
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
    }
    request_obj = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"LLM 鎺ュ彛杩斿洖 HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"鏃犳硶杩炴帴鍒伴厤缃殑 LLM 鎺ュ彛: {exc.reason}") from exc

    raw = json.loads(body)
    content = _response_text(raw)
    return json.loads(_extract_json_object(content))


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
    return render_template("base.html")


@app.route("/api/auth/status")
def api_auth_status():
    user = _current_user()
    return jsonify({
        "authenticated": bool(user),
        "user": _public_user(user),
    })


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


def _models_endpoint_url(base_url):
    """从配置的 base_url 推断出 /models 接口地址。"""
    cleaned = str(base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url 必须是完整的 http(s) 地址")
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]
    if cleaned.endswith("/v1"):
        return f"{cleaned}/models"
    return f"{cleaned}/v1/models"


def _do_fetch_models(base_url, api_key):
    try:
        models_url = _models_endpoint_url(base_url)
    except ValueError as exc:
        return jsonify({"models": [], "message": str(exc)}), 200

    req = urllib.request.Request(
        models_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
        models = []
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            models = [str(item["id"]) for item in data["data"] if isinstance(item, dict) and item.get("id")]
        elif isinstance(data, list):
            models = [str(item["id"]) if isinstance(item, dict) else str(item) for item in data]
        return jsonify({"models": sorted(set(m for m in models if m))})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:300]
        return jsonify({"models": [], "message": f"HTTP {exc.code}: {detail}"}), 200
    except Exception as exc:
        return jsonify({"models": [], "message": f"获取模型列表失败: {str(exc)[:200]}"}), 200


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
    if selection.get("provider_id"):
        if not any(p.get("id") == selection["provider_id"] for p in providers):
            selection = {}
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
    session["llm_selection"] = {"provider_id": provider_id, "model": model}
    session.modified = True
    return jsonify({
        "selection": session["llm_selection"],
        "provider_name": provider.get("name"),
        "message": f"已选择：{provider.get('name')} · {model}"
    })


# ── API：城市列表鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
@app.route("/api/cities")
def api_cities():
    cities = [fname[:-5] for fname in _list_city_files()]
    return _cache_json_response(cities, max_age=3600)

# ── API：岗位数据 ─────────────────────────────────────────────────────────────────────
@app.route("/api/jobs")
def api_jobs():
    city = str(request.args.get("city", "all") or "all").strip() or "all"
    view = str(request.args.get("view", "full") or "full").strip().lower()
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

    app.run(host=host, port=port, debug=False)

