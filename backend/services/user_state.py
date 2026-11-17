"""用户状态层：账号标识、登录装饰器、每个用户的状态文件与私有目录。"""

import hashlib
import json
import os
import re
import threading
from functools import wraps

from flask import jsonify

from services import auth as _auth, db as _app_db
from services.paths import APP_DATA_DIR, PUBLIC_DATA_DIR


# 路径配置
USER_STATE_DIR = os.path.join(APP_DATA_DIR, "user_state")


RESUME_UPLOAD_DIR = os.path.join(APP_DATA_DIR, "user_uploads")


CAREER_REPORT_DIR = os.path.join(APP_DATA_DIR, "career_reports")


ASSESSMENT_DATA_FILE = os.path.join(PUBLIC_DATA_DIR, "assessment-data.json")


# 可重入：保存快照等操作在持锁期间还会调用同样加锁的读取函数，普通锁会把请求永久卡住。
APP_DATA_LOCK = threading.RLock()


ASSESSMENT_DATA_LOCK = threading.Lock()


ASSESSMENT_DATA_CACHE = {"signature": None, "payload": {}}


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


def _user_upload_dir(username):
    return _private_account_directory(RESUME_UPLOAD_DIR, username)
