"""应用外壳：静态资源、Vite 资源标签、CORS 与压缩响应头。"""

import gzip
import io
import json
import logging
import os
import re
from datetime import timedelta

from flask import Blueprint, current_app, jsonify, request, send_from_directory, url_for
from markupsafe import escape, Markup

from services.cors import cors_headers, normalize_origins
from services.paths import PUBLIC_DATA_DIR, STATIC_DIR
from services.report.store import _list_career_report_version_summaries
from services.user_state import _current_user


blueprint = Blueprint("shell", __name__)


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
    return current_app.send_static_file(filename)


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


FRONTEND_ORIGIN = str(os.environ.get("FRONTEND_ORIGIN") or "").strip()


VITE_DEV_SERVER_URL = str(os.environ.get("VITE_DEV_SERVER_URL") or "").strip().rstrip("/")


VITE_MANIFEST_FILE = os.path.join(STATIC_DIR, "dist", ".vite", "manifest.json")


VITE_MANIFEST_CACHE = {"mtime": None, "payload": None}


@blueprint.before_app_request
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


@blueprint.app_context_processor
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


@blueprint.after_app_request
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


@blueprint.after_app_request
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


def configure_app(app):
    """Session cookie policy, the static endpoint and the CORS origins the after-request hook reads."""
    logging.getLogger("werkzeug").addFilter(_QuietWerkzeugPollPathsFilter())
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
    app.config.update(FRONTEND_ORIGIN=FRONTEND_ORIGIN, VITE_DEV_SERVER_URL=VITE_DEV_SERVER_URL)
    app.view_functions["static"] = static_asset
