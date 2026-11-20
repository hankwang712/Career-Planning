"""Single local workspace and browser request protection."""

from ipaddress import ip_address
import hmac
import os
import secrets
from urllib.parse import quote, urlsplit

from flask import Blueprint, current_app, g, jsonify, request, session

from . import db


blueprint = Blueprint("workspace_security", __name__)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def local_request(host, peer, origin=None):
    try:
        authority = urlsplit("//" + host)
        address = ip_address(peer or "")
        if (authority.hostname not in LOCAL_HOSTS or authority.username is not None
                or authority.path or authority.query or authority.fragment):
            return False
        if not address.is_loopback and not (os.environ.get("CAREER_CONTAINER") == "1" and address.is_private):
            return False
        if origin:
            source = urlsplit(origin)
            if source.scheme not in {"http", "https"} or source.hostname not in LOCAL_HOSTS:
                return False
        return True
    except ValueError:
        return False


def select_workspace(conn):
    with conn:
        # Keep the original storage key so uploaded files, reports and chat history stay accessible.
        chosen = conn.execute("SELECT value FROM auth_settings WHERE name='workspace_owner'").fetchone()
        if chosen is None:
            previous = conn.execute("""
                SELECT username FROM users WHERE disabled=0
                ORDER BY last_login_at DESC NULLS LAST, (role='super_admin') DESC, created_at, username LIMIT 1
            """).fetchone()
            username = previous["username"] if previous else "local-workspace"
            conn.execute("""
                INSERT OR IGNORE INTO users (username, password_hash, role, display_name)
                VALUES (?, '', 'super_admin', '个人工作区')
            """, (username,))
            conn.execute("INSERT OR IGNORE INTO auth_settings VALUES ('workspace_owner', ?)", (username,))
            chosen = conn.execute("SELECT value FROM auth_settings WHERE name='workspace_owner'").fetchone()
    return {"username": chosen["value"], "display_name": "个人工作区", "role": "super_admin"}


def current_user():
    return current_app.config["WORKSPACE_IDENTITY"]


@blueprint.get("/api/workspace/security")
def security():
    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify(csrf_token=token)


def init_app(app):
    conn = db._get_conn()
    app.config["WORKSPACE_IDENTITY"] = select_workspace(conn)
    with conn:
        conn.execute("INSERT OR IGNORE INTO auth_settings VALUES ('session_secret', ?)", (secrets.token_hex(32),))
    app.secret_key = os.environ.get("APP_SECRET_KEY") or os.environ.get("SECRET_KEY") or conn.execute(
        "SELECT value FROM auth_settings WHERE name='session_secret'").fetchone()[0]

    @app.before_request
    def protect_workspace():
        g.workspace_local = local_request(request.host, request.remote_addr, request.headers.get("Origin"))
        if not g.workspace_local:
            return jsonify(message="个人工作区仅接受本机访问。"), 403
        if request.method not in WRITES:
            return None
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return jsonify(message="请求来源不受支持。"), 403
        path = request.path
        if not path.startswith(("/api/career-profile", "/api/job-market", "/api/system-settings/", "/api/resume-editor/")):
            return None
        limit = {
            "/api/resume-editor/import": 13 * 1024 * 1024,
            "/api/job-market/collection/import": 2_010_000,
            "/api/job-market/collection/import-html": 5_010_000,
            "/api/job-market/collection/pipeline/purge": 2_000_000,
        }.get(path, 256 * 1024 if path.startswith("/api/resume-editor/") else 65536)
        if request.content_length and request.content_length > limit:
            return jsonify(message="提交的内容过大。"), 413
        expected, supplied = session.get("csrf_token"), request.headers.get("X-CSRF-Token", "")
        if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
            return jsonify(message="安全校验已过期，请刷新页面后重试。"), 403
        return None

    @app.after_request
    def protect_workspace_responses(response):
        private_prefixes = ("/api/workspace", "/api/bootstrap", "/api/user-state/", "/api/resume/", "/api/career-report/",
                            "/api/career-profile", "/api/job-market", "/api/profile-portrait", "/api/system-settings/",
                            "/api/resume-editor/", "/user-center/resumes", "/recruitment", "/app_data/")
        if request.path.startswith(private_prefixes):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            if g.get("workspace_local"):
                response.headers["X-Workspace-Owner"] = quote(current_user()["username"], safe="")
                response.headers["Access-Control-Expose-Headers"] = "X-Workspace-Owner"
        return response

    app.register_blueprint(blueprint)
