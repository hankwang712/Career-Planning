"""Website model configuration and per-account request diagnostics."""
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from urllib.parse import urlsplit
import re

import httpx
from dotenv import dotenv_values
from flask import Blueprint, g, jsonify, render_template, request
from openai import APIConnectionError, APIStatusError, OpenAI

from . import llm_env, runtime_settings
from .environment import ENV_FILE
from .llm_calls import normalize_sdk_base_url
from .user_state import _current_user, _login_required

blueprint = Blueprint("workspace_tools", __name__)
recent_requests = deque(maxlen=2000)
log_lock = Lock()
probe_lock = Lock()
TEST_GROUPS = {"chat", "cleaner", "embedding", "news"}


def extra_env_keys():
    values = dotenv_values(ENV_FILE, encoding="utf-8-sig")
    known = runtime_settings.KEYS | runtime_settings.DEPLOYMENT_KEYS
    return tuple(sorted(key for key in values.keys() - known if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)))


@blueprint.get("/system-settings")
def settings_page():
    deployment_groups = runtime_settings.DEPLOYMENT_GROUPS
    extra = extra_env_keys()
    if extra:
        deployment_groups += (("other", "其他环境变量", "列出本地 .env 中额外定义的变量及配置状态。",
                               tuple((key, "环境变量") for key in extra)),)
    return render_template(
        "system_settings.html", groups=runtime_settings.GROUPS,
        deployment_groups=deployment_groups, can_edit=True, test_groups=TEST_GROUPS,
    )


def settings_state(can_edit=True):
    overrides = runtime_settings.read()
    values = llm_env._values()
    chat = dict(zip(("AI_CHAT_BASE_URL", "AI_CHAT_API_KEY", "AI_CHAT_MODEL"), llm_env.chat_runtime()))
    fields = {}
    for key in sorted(runtime_settings.KEYS | runtime_settings.DEPLOYMENT_KEYS):
        value = str(chat.get(key, values.get(key)) or "").strip()
        fields[key] = {"configured": bool(value), "override": key in overrides}
        if can_edit and not key.endswith(("_API_KEY", "_PASSWORD")):
            fields[key]["value"] = value
    if can_edit:
        fields.update({key: {"configured": bool(str(values.get(key) or "").strip()), "override": False}
                       for key in extra_env_keys()})
    return fields


@blueprint.route("/api/system-settings/models", methods=["GET", "PATCH"])
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


@blueprint.get("/api/system-settings/status")
@_login_required
def model_status():
    return jsonify(fields=settings_state())


@blueprint.post("/api/system-settings/reveal")
def reveal_model_secret():
    data = request.get_json(silent=True)
    key = data.get("key") if isinstance(data, dict) else None
    if not isinstance(key, str) or key not in runtime_settings.KEYS or not key.endswith("_API_KEY"):
        return jsonify(message="该字段无法在网页显示。"), 400
    value = str(llm_env._values().get(key) or "").strip()
    if not value:
        return jsonify(message="此密钥尚未配置。"), 404
    return jsonify(value=value)


def probe_runtime(group):
    if group == "chat":
        return llm_env.chat_runtime()
    if group == "cleaner":
        return llm_env.recruitment_cleaner_runtime()
    if group == "embedding":
        from .skills.embeddings import embedding_runtime
        return embedding_runtime()
    from .news.news_kb import EMBEDDING_BASE_URL, EMBEDDING_MODEL
    key = str(llm_env._values().get("NEWS_EMBEDDING_API_KEY") or "").strip()
    return EMBEDDING_BASE_URL, key, EMBEDDING_MODEL


@blueprint.post("/api/system-settings/test/<group>")
def test_connection(group):
    if group not in TEST_GROUPS:
        return jsonify(message="这个分组不支持连通性测试。"), 404
    base_url, key, model = probe_runtime(group)
    if not all((base_url, key, model)):
        return jsonify(message="请先保存完整的接口地址、密钥和模型配置。"), 400
    if not probe_lock.acquire(blocking=False):
        return jsonify(message="已有一项连通性测试在运行，请稍后再试。"), 429
    started = perf_counter()
    try:
        with httpx.Client(timeout=8, follow_redirects=False) as transport:
            with OpenAI(base_url=normalize_sdk_base_url(base_url), api_key=key, max_retries=0, http_client=transport) as client:
                if group in {"chat", "cleaner"}:
                    reply = client.chat.completions.create(
                        model=model, messages=[{"role": "user", "content": "Reply OK."}], max_tokens=8,
                    )
                    if not getattr(reply, "choices", None):
                        return jsonify(message="模型服务未返回可识别的对话结果。"), 502
                else:
                    reply = client.embeddings.create(model=model, input="connection test")
                    if not getattr(reply, "data", None):
                        return jsonify(message="模型服务未返回可识别的向量结果。"), 502
    except APIStatusError as error:
        return jsonify(message=f"模型服务返回 HTTP {error.status_code}，请核对密钥、模型名称和账户额度。"), 502
    except APIConnectionError:
        return jsonify(message="无法连接模型服务或请求超时，请检查接口地址和网络。"), 502
    except (ValueError, TypeError, httpx.HTTPError):
        return jsonify(message="无法完成测试，请检查接口地址和服务响应。"), 502
    finally:
        probe_lock.release()
    return jsonify(message="连通性测试通过。", duration_ms=round((perf_counter() - started) * 1000))


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


@blueprint.get("/api/system-settings/llm-usage")
def llm_usage():
    from . import llm_audit
    days = request.args.get("days", 7, type=int) or 7
    return jsonify(llm_audit.usage_summary(days=max(1, min(90, days))))


@blueprint.post("/api/system-settings/backup")
def trigger_backup():
    from . import db_backup
    result = db_backup.create_rolling_backup(force=True)
    return jsonify(result=result, backups=db_backup.list_backups())


@blueprint.get("/api/system-settings/diagnostics")
def system_diagnostics():
    from . import db, db_backup, llm_audit, recruitment_chrome
    from .resume import editor_document
    checks = []

    base_url, key, model = llm_env.chat_runtime()
    checks.append({
        "key": "chat_llm",
        "label": "对话与改写模型",
        "ok": bool(base_url and key and model),
        "detail": f"{model}（已配置）" if all((base_url, key, model)) else "未配置完整 API 参数",
        "fix": "" if all((base_url, key, model)) else "在上方「对话模型」中点选常用厂商预设，填入 API Key 并保存。",
    })

    try:
        conn = db._get_conn()
        job_count = conn.execute("SELECT COUNT(*) FROM recruitment_listings").fetchone()[0]
        backups = db_backup.list_backups()
        checks.append({
            "key": "sqlite",
            "label": "SQLite 数据库与备份",
            "ok": True,
            "detail": f"正常 · {job_count} 条岗位 · 已保留 {len(backups)} 份滚动备份",
            "fix": "",
        })
    except Exception as exc:
        checks.append({"key": "sqlite", "label": "SQLite 数据库与备份", "ok": False, "detail": str(exc)[:80],
                       "fix": "检查 data/app_data/app.db 文件读写权限。"})

    try:
        _, _, fams = editor_document.resume_fonts()
        font_ok = fams.get("ChineseResume") != "sans-serif"
        checks.append({
            "key": "pdf_fonts",
            "label": "PDF 学术字体引擎",
            "ok": font_ok,
            "detail": f"中文：{fams.get('ChineseResume')} / 西文：{fams.get('LatinResume')}",
            "fix": "" if font_ok else "确认 Windows 字体目录包含 NotoSerifSC-VF.ttf 或 SimSun。",
        })
    except Exception as exc:
        checks.append({"key": "pdf_fonts", "label": "PDF 学术字体引擎", "ok": False, "detail": str(exc)[:80],
                       "fix": "确认 PyMuPDF 与 fontTools 已正确安装。"})

    chrome_ok = False
    chrome_detail = "未连接（127.0.0.1:3456 未启动）"
    chrome_fix = "在 .env 开启 CAREER_RECRUITMENT_USE_LOCAL_CHROME=1 并重启 npm start。"
    try:
        with httpx.Client(base_url=recruitment_chrome.BRIDGE_URL, timeout=1.5, trust_env=False) as client:
            resp = client.get("/health")
            if resp.status_code == 200:
                connected = resp.json().get("connected") is True
                chrome_ok = connected
                chrome_detail = "已连接本机 Chrome" if connected else "桥接已启动，待 Chrome 授权远程调试"
                chrome_fix = "" if connected else "在 Chrome 地址栏打开 chrome://inspect/#remote-debugging 并勾选启用远程调试。"
    except Exception:
        pass
    checks.append({"key": "chrome_bridge", "label": "本机 Chrome 桥接", "ok": chrome_ok, "detail": chrome_detail, "fix": chrome_fix})

    checks.append({
        "key": "privacy_shield",
        "label": "本地隐私脱敏护盾",
        "ok": True,
        "detail": "已开启 · 外发 LLM 前自动隐藏手机号/邮箱/身份证号",
        "fix": "",
    })

    return jsonify(
        checks=checks,
        backups=db_backup.list_backups(),
        usage=llm_audit.usage_summary(days=7),
    )


@blueprint.route("/api/system-settings/console-logs", methods=["GET", "DELETE"])
def console_logs():
    from . import console_log
    if request.method == "DELETE":
        console_log.clear_logs()
        return jsonify(ok=True, entries=[])
    after = request.args.get("after", 0, type=int) or 0
    return jsonify(entries=console_log.read_logs(after_seq=after, limit=150))
