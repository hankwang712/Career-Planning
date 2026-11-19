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
              "CLEANER_LLM_BASE_URL", "CLEANER_LLM_API_KEY", "CLEANER_LLM_MODEL", "CLEANER_VISION_MODEL", "USE_MAIN_LLM_FOR_CLEANER",
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
    from services import site as site_module
    from services.news import api as news_api

    module.app.config.update(TESTING=True)
    # 资讯接口平时会联网抓取 RSS；测试里换成固定数据，保证离线且快速。
    offline_news = {"items": [], "updated_at": "", "source": "test"}
    patcher = pytest.MonkeyPatch()
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


def reset_rate_limits():
    from services import db

    with db._get_conn() as conn:
        conn.execute("DELETE FROM auth_rate_limits")


def issue_captcha(server, client, purpose, answer="ABCDE"):
    """直接写入一条已知答案的验证码，绕开随机图片验证码。"""
    from services import auth, db

    security = client.get("/api/auth/security")
    csrf = security.get_json()["csrf_token"]
    with client.session_transaction() as session:
        owner = session["captcha_owner"]
    with server.app.app_context():
        owner_hash = auth.digest(owner)
        answer_hash = auth.digest(answer)
    challenge_id = f"test-{purpose}-{time.time_ns()}"
    with db._get_conn() as conn:
        conn.execute("INSERT INTO auth_challenges VALUES (?, ?, ?, ?, ?)",
                     (challenge_id, owner_hash, purpose, answer_hash, time.time() + 120))
    return csrf, {"captcha_id": challenge_id, "captcha_answer": answer}


@pytest.fixture()
def make_account(server):
    counter = {"n": 0}

    def make(prefix="user", password="correct-horse-battery"):
        counter["n"] += 1
        # 所有测试账号都来自同一个本机 IP，先清掉限流计数，避免被注册限流（每小时 10 次）拦住。
        reset_rate_limits()
        email = f"{prefix}{counter['n']}-{time.time_ns()}@example.com"
        client = server.app.test_client()
        csrf, captcha = issue_captcha(server, client, "register")
        response = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf}, json={
            "email": email, "password": password, "confirm_password": password,
            "display_name": prefix, **captcha})
        assert response.status_code == 201, response.get_json()
        account = Account(server, client, email)
        account.password = password
        account.csrf = client.get("/api/auth/security").get_json()["csrf_token"]
        return account

    return make
