"""站点路由的冒烟与访问控制测试：拆分 server.py 后路由不能丢，也不能意外放开。"""
import re

import pytest

# 拆分前 server.py 的全部公开路由；任何一条消失都说明拆分漏了东西。
EXPECTED_ROUTES = {
    "/", "/main.html", "/user-center", "/user-center/career-report/polish", "/resume-report",
    "/test-result", "/test-runner", "/sbti", "/multi-agent-workflow", "/app_data/<path:filename>",
    "/api/auth/status", "/api/auth/login", "/api/auth/register", "/api/auth/logout",
    "/api/llm-status", "/api/bootstrap", "/api/user-state/<scope>",
    "/api/career-news", "/api/news-kb/stats", "/api/news-kb/search",
    "/api/community-feed", "/api/community-feed/posts", "/api/community-feed/posts/<post_id>",
    "/api/community-feed/posts/<post_id>/reply", "/api/community-feed/posts/<post_id>/like",
    "/api/community-feed/posts/<post_id>/view",
    "/api/profile-portrait/generate",
    "/api/resume/upload", "/api/resume/analyze", "/api/resume/analyze/start", "/api/resume/analyze/status",
    "/api/resume/profile",
    "/api/career-report/generate/start", "/api/career-report/generate/status", "/api/career-report/generate/cancel",
    "/api/career-report/current", "/api/career-report/polish", "/api/career-report/version",
    "/api/career-report/export", "/api/career-report/feedback", "/api/career-report/source",
    "/api/career-report/snapshot/save", "/api/career-report/snapshot/check",
    "/api/career-report/tracker/sync", "/api/career-report/tracker/item",
    "/api/cities", "/api/jobs", "/api/jobs/bootstrap", "/api/job-detail",
    "/api/career-interview", "/api/career-interview/finish", "/api/mbti-clarifier", "/api/deep-test-analysis",
}


def test_all_expected_routes_are_registered(server):
    registered = {rule.rule for rule in server.app.url_map.iter_rules()}
    assert EXPECTED_ROUTES - registered == set()


def test_route_endpoints_are_unique_per_rule_and_method(server):
    seen = {}
    for rule in server.app.url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            key = (rule.rule, method)
            assert key not in seen, f"路由被重复注册：{key} -> {seen[key]} / {rule.endpoint}"
            seen[key] = rule.endpoint


@pytest.mark.parametrize("path", ["/", "/api/auth/status", "/api/career-news", "/api/cities", "/api/jobs/bootstrap"])
def test_public_pages_and_data_are_reachable_without_login(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", [
    "/user-center", "/resume-report", "/test-result", "/test-runner", "/sbti", "/multi-agent-workflow",
    "/user-center/career-report/polish",
])
def test_private_pages_redirect_anonymous_visitors_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.headers["Location"].rsplit("/", 1)[-1] in {"", "main.html"}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/llm-status"), ("get", "/api/community-feed"), ("post", "/api/community-feed/posts"),
    ("get", "/api/user-state/career_report"), ("get", "/api/resume/profile"),
    ("get", "/api/career-report/current"), ("post", "/api/career-report/generate/start"),
    ("post", "/api/career-interview"), ("post", "/api/mbti-clarifier"), ("post", "/api/deep-test-analysis"),
    ("post", "/api/profile-portrait/generate"), ("get", "/api/career-report/export"),
])
def test_private_api_rejects_anonymous_requests(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401, (method, path, response.status_code)


def test_private_responses_are_not_cacheable(make_account):
    account = make_account()
    response = account.get("/api/community-feed")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_logged_in_user_can_open_private_pages(make_account):
    account = make_account()
    for path in ("/user-center", "/resume-report", "/test-result", "/test-runner", "/sbti"):
        assert account.get(path).status_code == 200, path


def test_polish_page_links_back_to_user_center(make_account):
    """页面蓝图改名后，模板里的 url_for 必须仍然能解析。"""
    account = make_account()
    html = account.get("/user-center/career-report/polish").get_data(as_text=True)
    assert re.search(r'__CAREER_REPORT_POLISH_RETURN__ = "/user-center(\.html)?#report-workspace"', html)


def test_jobs_api_serves_city_data(client):
    cities = client.get("/api/cities").get_json()
    assert cities and isinstance(cities, list)
    jobs = client.get(f"/api/jobs?city={cities[0]}&view=summary").get_json()
    assert jobs and "job_id" in jobs[0]
    detail = client.get(f"/api/job-detail?id={jobs[0]['job_id']}")
    assert detail.status_code == 200


@pytest.mark.parametrize("job_id,status", [("", 400), ("no-colon", 400), ("北京:abc", 400), ("不存在的城市:0", 404), ("北京:99999999", 404)])
def test_job_detail_rejects_bad_ids(client, job_id, status):
    assert client.get("/api/job-detail", query_string={"id": job_id}).status_code == status


def test_news_search_requires_a_query(client):
    assert client.get("/api/news-kb/search").status_code == 400


def test_model_endpoints_report_missing_configuration(make_account):
    """测试环境没有模型凭据：接口应明确提示未配置，而不是崩溃或误用真实密钥。"""
    account = make_account()
    assert account.get("/api/llm-status").get_json() == {"configured": False, "model": ""}
    response = account.post("/api/career-interview", json={"messages": []})
    assert response.status_code == 400
    assert "模型尚未配置" in response.get_json()["message"]
