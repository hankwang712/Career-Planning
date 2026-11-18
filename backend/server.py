#!/usr/bin/env python3
"""职业规划智能体的入口：创建 Flask 应用，注册各服务模块的蓝图，再由 FastAPI 包一层提供聊天流式接口。

业务代码都在 services/ 下：用户状态 user_state、站点页面 site、应用外壳 webshell、
职业报告 report/*、简历 resume/*，以及各自独立的蓝图模块。这里只负责装配和启动。
"""
import sys

# Windows 控制台默认 GBK，强制 stdout/stderr 使用 UTF-8，避免中文日志乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import logging
import mimetypes
import os
import threading
import time
import webbrowser

from flask import Flask

from services import appctx
from services import auth as _auth
from services import db as _app_db
from services import llm_env
from services import personality
from services.career import create_blueprint as create_career_blueprint, snapshot as career_snapshot
from services.chat import create_blueprint as create_chat_blueprint
from services.chat.api import create_app as create_chat_app
from services.chat.profile import build_background as build_chat_background
from services.community import create_blueprint as create_community_blueprint
from services.datasets import create_blueprint as create_datasets_blueprint
from services.interview import create_blueprint as create_interview_blueprint
from services.job_data import BOSS_INFO_DIR, create_blueprint as create_job_data_blueprint
from services.job_market.api import create_blueprint as create_job_market_blueprint
from services.job_market.collector import Collector as JobMarketCollector
from services.news import get_career_news_payload
from services.news.api import create_blueprint as create_news_blueprint
from services.pages import create_blueprint as create_pages_blueprint
from services.paths import APP_DATA_DIR, STATIC_DIR, TEMPLATE_DIR
from services.portrait import create_blueprint as create_portrait_blueprint
from services.report import api as report_api
from services.report.jobs import CAREER_REPORT_JOBS, _fail_interrupted_report
from services.report.store import _read_career_report_bundle
from services.resume import api as resume_api
from services.resume import editor as resume_editor
from services.resume.jobs import RESUME_ANALYSIS_JOBS, _fail_interrupted_resume
from services.resume.pipeline import fitz
from services import recruitment, site, webshell, workspace_tools
from services.user_state import (
    _chat_resume_source,
    _current_user,
    _ensure_app_storage,
    _load_user_state,
    _load_users,
    _login_required,
    _save_user_state,
    _super_admin_required,
)

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["TEMPLATES_AUTO_RELOAD"] = True
appctx.bind(app)
webshell.configure_app(app)


def _model_runtime(selection=None):
    """读取站点统一的对话模型配置。保留 selection 形参以兼容现有调用。"""
    return llm_env.chat_runtime()


# 启动入口
def open_browser():
    time.sleep(1.0)
    webbrowser.open("http://localhost:8080")


def _prewarm_caches():
    """后台预热重载数据，避免首次请求阻塞。"""
    def _warm_news():
        try:
            get_career_news_payload()
        except Exception as exc:
            logger.warning("资讯预热失败：%s", type(exc).__name__)

    if os.environ.get("CAREER_PREWARM", "1").lower() in {"0", "false", "no"}:
        return
    threading.Thread(target=_warm_news, daemon=True, name="prewarm-news").start()


def _restore_background_jobs():
    """Bring back recent jobs after a restart and fail the ones the restart interrupted, in the registry and in
    the user's saved state, so nobody waits on a task that no longer exists."""
    for registry, fail_state in ((RESUME_ANALYSIS_JOBS, _fail_interrupted_resume), (CAREER_REPORT_JOBS, _fail_interrupted_report)):
        for job in registry.restore():
            try:
                fail_state(job)
            except Exception:
                app.logger.exception("could not mark interrupted job %s", job.get("job_id"))


# 注册顺序决定 before/after 钩子的执行顺序：外壳与报告标识校验要排在登录钩子之前。
app.register_blueprint(webshell.blueprint)
app.register_blueprint(report_api.blueprint)
app.register_blueprint(resume_api.blueprint)
app.register_blueprint(resume_editor.blueprint)
app.register_blueprint(site.blueprint)
_ensure_app_storage()
_app_db.init_db()
_restore_background_jobs()
_auth.init_app(app)
app.register_blueprint(workspace_tools.blueprint)
app.register_blueprint(create_datasets_blueprint(_login_required))
app.register_blueprint(create_community_blueprint(_login_required, _super_admin_required, _current_user))
app.register_blueprint(create_interview_blueprint(_login_required, _model_runtime))
app.register_blueprint(create_job_data_blueprint())
app.register_blueprint(create_portrait_blueprint(_login_required, _current_user, _load_user_state, _save_user_state))
app.register_blueprint(create_news_blueprint())
app.register_blueprint(create_pages_blueprint(_current_user))
_chat_blueprint = create_chat_blueprint(
    directory=APP_DATA_DIR / "assistant",
    current_user=_current_user,
    runtime_provider=_model_runtime,
    profile_provider=lambda username: build_chat_background(_load_user_state(username), _read_career_report_bundle(username)),
    resume_provider=_chat_resume_source,
)
app.register_blueprint(_chat_blueprint)
app.extensions["chat_service"] = _chat_blueprint.chat_service


def _career_memory_records(username):
    records = _chat_blueprint.chat_service.store.memory_snapshot(username)[1]
    return [{key: item[key] for key in ("id", "key", "subject", "value", "status", "source_session", "updated_at")}
            for item in records if item["kind"] == "fact" and item["status"] in {"active", "conflict"}]


def _career_chat_background(username):
    """聊天只读基础画像：求职偏好、学校/专业/学历/毕业时间、所在城市与阶段、在进行的目标。

    职业档案里的经历、技能、证书、证据属于报告与岗位匹配，不进入聊天上下文。"""
    background = build_chat_background(_load_user_state(username), _read_career_report_bundle(username))
    data = career_snapshot(username)
    resume_enabled = _chat_blueprint.chat_service.store.privacy(username)["resume_enabled"]
    profile = data["profile"] or {}
    basics = {key: profile[key] for key in ("city", "stage", "headline") if profile.get(key)}
    education = [{"title": row["title"], "description": str(row.get("description") or "")[:200]}
                 for row in data["entries"]
                 if row["kind"] == "education" and (resume_enabled or row["source_type"] != "resume")][:10]
    goals = [{"title": row["title"], "status": row["status"], "target_date": row.get("target_date") or ""}
             for row in data["goals"] if row["status"] == "active"][:10]
    if basics or education or goals:
        background["用户维护的基础档案"] = {"基本信息": basics, "教育": education, "目标": goals}
    # 做过哪些测评就带哪些；一个都没做就不出现这一项。
    assessments = personality.for_chat(personality.collect(_load_user_state(username)))
    if assessments:
        background["性格与兴趣测评（用户自测的自评结果）"] = assessments
    return background


_chat_blueprint.chat_service.profile_provider = _career_chat_background
app.register_blueprint(create_career_blueprint(_login_required, _current_user, _load_user_state, _career_memory_records))
_job_market_collector = JobMarketCollector()
app.extensions["job_market"] = _job_market_collector
app.register_blueprint(create_job_market_blueprint(_job_market_collector, _login_required, _current_user))
app.register_blueprint(recruitment.blueprint)
if os.environ.get("JOB_MARKET_SCHEDULER", "1").lower() not in {"0", "false", "no"}:
    _job_market_collector.start_scheduler()
_load_users()
_prewarm_caches()

# Uvicorn serves chat with FastAPI; the rest of the site remains in Flask.
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
    print("  PDF 导出引擎：", f"PyMuPDF {fitz.VersionBind}" if fitz is not None else "PyMuPDF 未安装，请安装 requirements.txt")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    if auto_open_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(asgi_app, host=host, port=port)
