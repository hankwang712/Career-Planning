"""Website model configuration and per-account request diagnostics."""
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from urllib.parse import urlsplit

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from . import llm_env, runtime_settings
from .user_state import _current_user, _login_required, _super_admin_required

blueprint = Blueprint("workspace_tools", __name__)
recent_requests = deque(maxlen=2000)
log_lock = Lock()


@blueprint.get("/system-settings")
def settings_page():
    if not _current_user():
        return redirect(url_for("site.index"))
    return _settings_page()


@_super_admin_required
def _settings_page():
    return render_template("system_settings.html", groups=runtime_settings.GROUPS)


def settings_state():
    overrides = runtime_settings.read()
    values = llm_env._values()
    chat = dict(zip(("AI_CHAT_BASE_URL", "AI_CHAT_API_KEY", "AI_CHAT_MODEL"), llm_env.chat_runtime()))
    fields = {}
    for key in sorted(runtime_settings.KEYS):
        value = str(chat.get(key, values.get(key)) or "").strip()
        fields[key] = {"configured": bool(value), "override": key in overrides}
        if not key.endswith("_API_KEY"):
            fields[key]["value"] = value
    return fields


@blueprint.route("/api/system-settings/models", methods=["GET", "PATCH"])
@_super_admin_required
def models():
    if request.method == "PATCH":
        changes = request.get_json(silent=True)
        if not isinstance(changes, dict) or not changes.keys() <= runtime_settings.KEYS:
            return jsonify(message="配置字段无效。"), 400
        for key, value in changes.items():
            if not isinstance(value, str) or len(value) > 2048 or any(ord(char) < 32 for char in value):
                return jsonify(message="配置值无效。"), 400
            value = value.strip()
            if key.endswith("_BASE_URL") and value:
                try:
                    url = urlsplit(value)
                    valid = url.scheme in {"http", "https"} and url.hostname and not (
                        url.username or url.password or url.query or url.fragment or any(c.isspace() for c in value)
                    )
                    _ = url.port
                except ValueError:
                    valid = False
                if not valid:
                    return jsonify(message="接口地址应为 HTTP 或 HTTPS URL，请去掉凭据、查询参数和片段。"), 400
            changes[key] = value
        runtime_settings.save(changes)
    return jsonify(fields=settings_state())


def record_request(owner, route, method, status, started):
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "method": method,
        "status": status,
        "duration_ms": round((perf_counter() - started) * 1000),
    }
    with log_lock:
        recent_requests.append((owner, entry))


@blueprint.before_app_request
def start_request():
    rule = request.url_rule
    if rule and rule.rule.startswith("/api/") and rule.endpoint != "workspace_tools.logs" and request.method != "OPTIONS":
        user = _current_user()
        if user:
            g.workspace_request = (user["username"], rule.rule, request.method, perf_counter())


@blueprint.after_app_request
def finish_request(response):
    details = getattr(g, "workspace_request", None)
    if details:
        owner, route, method, started = details
        record_request(owner, route, method, response.status_code, started)
    return response


@blueprint.get("/api/workspace-logs")
@_login_required
def logs():
    owner = _current_user()["username"]
    with log_lock:
        entries = [entry for username, entry in recent_requests if username == owner][-100:]
    return jsonify(entries=entries)
