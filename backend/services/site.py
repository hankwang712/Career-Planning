"""站点首页与登录态、启动数据、用户状态读写接口。"""

import os

from flask import Blueprint, jsonify, render_template, request, send_from_directory

from services import llm_env
from services.news import get_career_news_payload
from services.paths import APP_DATA_DIR
from services.portrait import public_profile_portrait_state
from services.report.store import (
    _career_report_user_dir,
    _public_career_report_state,
    _read_career_report_bundle,
    _sanitize_transient_career_report_state,
)
from services.resume.jobs import _public_resume_state
from services.user_state import (
    _current_user,
    _load_user_state,
    _login_required,
    _public_user,
    _save_user_state,
    _user_upload_dir,
    VALID_USER_STATE_SCOPES,
)


blueprint = Blueprint("site", __name__)


# 页面与认证接口
@blueprint.route("/")
@blueprint.route("/main.html")
def index():
    user = _current_user()
    if not user:
        return render_template("login.html", initial_user=None)
    return render_template(
        "base.html",
        initial_user=_public_user(user),
        career_news=get_career_news_payload(),
    )


@blueprint.route("/app_data/<path:filename>")
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


@blueprint.route("/api/auth/status")
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


@blueprint.route("/api/llm-status")
@_login_required
def api_llm_status():
    """是否已配置模型以及模型名；不含任何密钥或接口地址。"""
    return jsonify(llm_env.status())


@blueprint.route("/api/bootstrap")
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


@blueprint.route("/api/user-state/<scope>", methods=["GET", "PUT"])
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
