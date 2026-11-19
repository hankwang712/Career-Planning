"""站点路由的冒烟与访问控制测试：拆分 server.py 后路由不能丢，也不能意外放开。"""
import re

import pytest

# 当前保留的站点路由。
EXPECTED_ROUTES = {
    "/", "/main.html", "/user-center", "/user-center/career-report/polish", "/resume-report",
    "/test-result", "/test-runner", "/sbti", "/multi-agent-workflow", "/app_data/<path:filename>",
    "/api/workspace/security",
    "/api/llm-status", "/api/bootstrap", "/api/user-state/<scope>",
    "/api/career-news", "/api/news-kb/stats", "/api/news-kb/search",
    "/api/profile-portrait/generate",
    "/api/resume/upload", "/api/resume/analyze", "/api/resume/analyze/start", "/api/resume/analyze/status",
    "/api/resume/profile",
    "/api/career-report/generate/start", "/api/career-report/generate/status", "/api/career-report/generate/cancel",
    "/api/career-report/current", "/api/career-report/polish", "/api/career-report/version",
    "/api/career-report/export", "/api/career-report/feedback", "/api/career-report/source",
    "/api/career-report/snapshot/save", "/api/career-report/snapshot/check",
    "/api/career-report/tracker/sync", "/api/career-report/tracker/item",
    "/api/career-interview", "/api/career-interview/finish", "/api/mbti-clarifier", "/api/deep-test-analysis",
}


def test_all_expected_routes_are_registered(server):
    registered = {rule.rule for rule in server.app.url_map.iter_rules()}
    assert EXPECTED_ROUTES - registered == set()
    assert not any(path.startswith("/api/community-feed") for path in registered)


def test_route_endpoints_are_unique_per_rule_and_method(server):
    seen = {}
    for rule in server.app.url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (rule.rule, method)
            assert key not in seen, f"路由被重复注册：{key} -> {seen[key]} / {rule.endpoint}"
            seen[key] = rule.endpoint


@pytest.mark.parametrize("path", ["/", "/api/bootstrap", "/api/career-news"])
def test_public_pages_and_data_are_reachable_without_login(client, path):
    assert client.get(path, follow_redirects=True).status_code == 200


def test_workspace_home_opens_recruitment(client):
    assert client.get("/").location == "/recruitment"


def test_healthz_is_a_login_free_liveness_probe(client):
    response = client.get("/healthz")
    assert response.status_code == 200 and response.get_json() == {"status": "ok"}


@pytest.mark.parametrize("path", [
    "/user-center", "/user-center/workspace", "/user-center/resumes", "/resume-report", "/test-result", "/test-runner", "/sbti", "/multi-agent-workflow",
    "/user-center/career-report/polish",
])
def test_workspace_pages_open_without_login(client, path):
    assert client.get(path, follow_redirects=True).status_code == 200


@pytest.mark.parametrize("method,path", [
    ("get", "/api/llm-status"),
    ("get", "/api/user-state/career_report"), ("get", "/api/resume/profile"),
    ("get", "/api/career-report/current"), ("post", "/api/career-report/generate/start"),
    ("post", "/api/career-interview"), ("post", "/api/mbti-clarifier"), ("post", "/api/deep-test-analysis"),
    ("post", "/api/profile-portrait/generate"), ("get", "/api/career-report/export"),
])
def test_workspace_api_rejects_remote_requests(client, method, path):
    response = getattr(client, method)(path, environ_overrides={"REMOTE_ADDR": "192.0.2.15"})
    assert response.status_code == 403, (method, path, response.status_code)


def test_private_responses_are_not_cacheable(make_account):
    account = make_account()
    response = account.get("/api/bootstrap")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_startup_removes_legacy_community_and_system_account(make_account):
    from werkzeug.security import generate_password_hash

    from services import db

    account = make_account("community-retirement")
    with db._get_conn() as conn:
        conn.execute("CREATE TABLE community_forum (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO community_forum VALUES (1, '{}')")
        conn.execute("INSERT INTO users (username, password_hash, role, display_name) VALUES ('system', 'unused', 'super_admin', 'System')")
        conn.execute("INSERT INTO user_state_sections (username, section, payload) VALUES ('system', 'profile', '{}')")
        conn.executemany("INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, 'Legacy')", [
            ("23030134", generate_password_hash("123456")),
            ("24110403", generate_password_hash("changed-password")),
        ])

    db.init_db()
    db.init_db()

    with db._get_conn() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='community_forum'").fetchone() is None
        assert conn.execute("SELECT 1 FROM user_state_sections WHERE username='system'").fetchone() is None
    assert db.find_user("system") is None
    assert db.find_user("23030134") is None
    assert db.find_user("24110403") is not None
    assert db.find_user(account.email) is not None
    assert account.get("/api/community-feed").status_code == 404


def test_logged_in_user_can_open_private_pages(make_account):
    account = make_account()
    for path in ("/user-center", "/resume-report", "/test-result", "/test-runner", "/sbti"):
        assert account.get(path).status_code == 200, path


def test_polish_page_links_back_to_user_center(make_account):
    """页面蓝图改名后，模板里的 url_for 必须仍然能解析。"""
    account = make_account()
    html = account.get("/user-center/career-report/polish").get_data(as_text=True)
    assert re.search(r'__CAREER_REPORT_POLISH_RETURN__ = "/user-center/workspace#report-workspace"', html)


def test_news_search_requires_a_query(client):
    assert client.get("/api/news-kb/search").status_code == 400


def test_model_endpoints_report_missing_configuration(make_account):
    """测试环境没有模型凭据：接口应明确提示未配置，而不是崩溃或误用真实密钥。"""
    account = make_account()
    assert account.get("/api/llm-status").get_json() == {"configured": False, "model": ""}
    response = account.post("/api/career-interview", json={"messages": []})
    assert response.status_code == 400
    assert "模型尚未配置" in response.get_json()["message"]
