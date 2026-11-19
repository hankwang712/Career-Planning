"""测试公共环境。

必须在导入任何业务模块之前完成：
- 运行数据写入临时目录，绝不触碰 data/app_data 里的真实数据；
- 关闭后台任务（岗位采集调度、资讯预热），测试期间不访问网络；
- 清空模型凭据，保证没有测试会误用 .env 里的真实密钥。
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

_DATA_DIR = tempfile.mkdtemp(prefix="career-agent-tests-")
os.environ["CAREER_APP_DATA_DIR"] = _DATA_DIR
os.environ["JOB_MARKET_SCHEDULER"] = "0"
os.environ["CAREER_PREWARM"] = "0"
os.environ["SESSION_COOKIE_SECURE"] = ""
for _name in ("AI_CHAT_BASE_URL", "AI_CHAT_API_KEY", "AI_CHAT_MODEL", "AI_OCR_BASE_URL", "AI_OCR_API_KEY", "AI_OCR_MODEL",
              "CLEANER_LLM_BASE_URL", "CLEANER_LLM_API_KEY", "CLEANER_LLM_MODEL",
              "AI_EMBEDDING_BASE_URL", "AI_EMBEDDING_API_KEY", "AI_EMBEDDING_MODEL",
              "EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "EMBEDDING_MODEL"):
    os.environ[_name] = ""

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def server():
    """导入一次完整的站点（Flask 应用 + 全部蓝图）。"""
    import server as module
    from flask import session
    from services import auth, db
    from services import site as site_module
    from services.news import api as news_api

    module.app.config.update(TESTING=True)
    # 资讯接口平时会联网抓取 RSS；测试里换成固定数据，保证离线且快速。
    offline_news = {"items": [], "updated_at": "", "source": "test"}
    patcher = pytest.MonkeyPatch()
    local_identity = auth.current_user

    def isolated_identity():
        owner = session.get("test_workspace")
        return db.find_user(owner) if owner else local_identity()

    patcher.setattr(auth, "current_user", isolated_identity)
    patcher.setattr(module, "get_career_news_payload", lambda force_refresh=False: dict(offline_news))
    patcher.setattr(site_module, "get_career_news_payload", lambda force_refresh=False: dict(offline_news))
    patcher.setattr(news_api, "get_career_news_payload", lambda force_refresh=False: dict(offline_news))
    yield module
    patcher.undo()


@pytest.fixture()
def client(server):
    return server.app.test_client()


class Account:
    """已登录的测试账号：带 CSRF 头的请求辅助。"""

    def __init__(self, server, client, email):
        self.server, self.client, self.email = server, client, email
        self.csrf = ""

    def request(self, method, path, **kwargs):
        headers = {"X-CSRF-Token": self.csrf, **kwargs.pop("headers", {})}
        return getattr(self.client, method)(path, headers=headers, **kwargs)

    def get(self, path, **kwargs):
        return self.request("get", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("post", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("put", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("delete", path, **kwargs)


@pytest.fixture()
def make_account(server):
    from services import db

    def make(prefix="user", password="unused"):
        email = f"{prefix}-{time.time_ns()}@example.com"
        with db._get_conn() as conn:
            conn.execute("INSERT INTO users (username, password_hash, display_name) VALUES (?, '', ?)", (email, prefix))
        client = server.app.test_client()
        with client.session_transaction() as session:
            session["test_workspace"] = email
        account = Account(server, client, email)
        account.csrf = client.get("/api/workspace/security").get_json()["csrf_token"]
        return account

    return make
