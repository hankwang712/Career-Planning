import csv
from contextlib import nullcontext
from io import BytesIO, StringIO
import time

import pytest


LINKS = {
    "boss": "https://www.zhipin.com/job_detail/example.html",
    "51job": "https://jobs.51job.com/hangzhou/123456.html",
    "zhilian": "https://www.zhaopin.com/jobdetail/example",
    "liepin": "https://www.liepin.com/job/123.shtml",
    "xiaohongshu": "https://www.xiaohongshu.com/explore/example",
}
API = "/api/job-market/collection"


@pytest.mark.parametrize("source", LINKS)
def test_platform_urls_and_card_deduplication(source):
    from services.recruitment_sources import cards, listing_url, search_url

    class Page:
        url = search_url(source, "AI & Python", "杭州")

        def evaluate(self, script, options):
            assert options["limit"] == 5
            job = {"title": "AI 开发", "url": LINKS[source], "company": "", "salary": "", "location": "", "description": ""}
            return [job, {**job, "url": job["url"] + "?tracking=1"}, {**job, "url": "https://localhost/jobs/1"}]

    assert listing_url(source, LINKS[source] + "?tracking=1") == LINKS[source]
    assert listing_url(source, "javascript:alert(1)") == ""
    assert "AI+%26+Python" in Page.url
    assert [row["url"] for row in cards(Page(), source, 5)] == [LINKS[source]]


def test_collection_stores_each_platform_and_keeps_account_data_private(make_account, monkeypatch):
    from services import recruitment

    owner = make_account("collector")
    other = make_account("other-collector")
    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    monkeypatch.setattr(recruitment, "launch_browser", lambda _: nullcontext(object()))

    def collect(_browser, source, keyword, city, limit):
        assert (keyword, city, limit) == ("Agent", "杭州", 10)
        return "succeeded", "读取 1 条结果。", [{"title": "Agent 开发", "url": LINKS[source], "location": city}]

    monkeypatch.setattr(recruitment, "collect_source", collect)
    monkeypatch.setattr(recruitment, "collect_in_chrome", lambda source, keyword, city, limit, _update:
                        collect(None, source, keyword, city, limit))
    assert owner.get("/recruitment").status_code == 200
    assert owner.post(API + "/runs", json={"keyword": "Agent", "sources": ["unknown"]}).status_code == 400
    assert owner.post(API + "/runs", json={"keyword": "Agent", "sources": ["liepin"]}).status_code == 400
    auto = {"profile": "full_time", "rules": {"auto": True, "title_exclusions": ["Agent"]}}
    assert owner.post(API + "/cleaning/save", json=auto).status_code == 200
    active = [source for source in LINKS if source != "liepin"]
    response = owner.post(API + "/runs", json={"keyword": "Agent", "city": "杭州", "sources": active, "limit": 10,
                                               "chrome_local": True, "profile": "full_time"})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = owner.get(API + "/runs").get_json()["items"][0]
        if run["status"] != "running":
            break
        time.sleep(.05)
    assert run["status"] == "complete"
    assert set(run["progress"]) == set(active)
    assert all(item["count"] == 1 and item["cleaning"]["rejected"] == 1 for item in run["progress"].values())
    assert owner.get(API + "/jobs?source=51job").get_json()["total"] == 1
    assert run["profile"] == "full_time"
    assert owner.get(API + "/jobs?profile=full_time").get_json()["total"] == 4
    assert other.get(API + "/jobs").get_json()["total"] == 0
    assert other.get(API + "/runs").get_json()["items"] == []


def test_city_catalog_uses_each_platform_code():
    from urllib.parse import parse_qs, urlsplit
    from services.recruitment_sources import CITY_CATALOG, search_url

    groups = {city for group in CITY_CATALOG["groups"].values() for city in group}
    assert len(groups) > 100
    assert set(CITY_CATALOG["hot"]) <= groups
    for source, parameter, code in (("boss", "city", "101190400"), ("51job", "jobArea", "070300"),
                                    ("zhilian", "jl", "639")):
        query = parse_qs(urlsplit(search_url(source, "Agent", "苏州")).query)
        assert query[parameter] == [code]
    assert search_url("boss", "Agent", "泉州") == ""
    assert search_url("51job", "Agent", "远程") == ""
    query = parse_qs(urlsplit(search_url("xiaohongshu", "Agent", "远程")).query)
    assert query["keyword"] == ["远程 Agent 招聘"]


def test_collection_skips_platform_without_city_code(make_account, monkeypatch):
    from services import recruitment

    owner = make_account("city-coverage")
    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    called = []

    def collect(source, keyword, city, limit, _update):
        called.append((source, city))
        return "succeeded", "读取 1 条结果。", [{"title": "Agent 开发", "url": LINKS[source], "location": city}]

    monkeypatch.setattr(recruitment, "collect_in_chrome", collect)
    config = {"keyword": "Agent", "city": "泉州", "sources": ["boss"], "chrome_local": True}
    assert owner.post(API + "/runs", json=config).status_code == 400
    assert owner.post(API + "/runs", json={**config, "city": "不存在", "sources": ["xiaohongshu"]}).status_code == 400
    assert owner.post(API + "/runs", json={**config, "sources": ["boss", "51job"]}).status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = owner.get(API + "/runs").get_json()["items"][0]
        if run["status"] != "running":
            break
        time.sleep(.05)
    assert run["status"] == "complete"
    assert called == [("51job", "泉州")]
    assert run["progress"]["boss"]["status"] == "city_unsupported"
    assert run["progress"]["boss"]["search_url"] == ""


def test_upstream_csv_import_and_export_share_the_same_dedup_key(make_account):
    account = make_account("recruitment-csv")
    text = ("platform,job_title,company_name,city,jd_text,job_link\n"
            f"boss,=1+1,样本公司,杭州,岗位描述,{LINKS['boss']}?tracking=first\n"
            f"boss,重复的岗位,样本公司,杭州,岗位描述,{LINKS['boss']}?tracking=second\n"
            "boss,无效网址,样本公司,杭州,示例,https://example.invalid/job_detail/1\n")
    imported = account.post(API + "/import", data={"file": (BytesIO(text.encode("utf-8")), "jobs.csv")})
    assert imported.status_code == 200
    assert imported.get_json()["count"] == 1
    response = account.get(API + "/export?q=杭州")
    entries = list(csv.DictReader(StringIO(response.data.decode("utf-8-sig"))))
    assert len(entries) == 1
    assert entries[0]["title"] == "'=1+1"
    assert entries[0]["url"] == LINKS["boss"]


def test_local_boss_waits_in_account_profile_and_rejects_remote_launch(make_account, monkeypatch):
    from services import recruitment

    monkeypatch.setenv("CAREER_BOSS_USE_LOCAL_CHROME", "0")
    monkeypatch.delenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", raising=False)
    account = make_account("local-boss")
    seen_profiles = []

    def local_boss(_playwright, profile, keyword, city, limit, update):
        assert (keyword, city, limit) == ("Agent", "杭州", 10)
        seen_profiles.append(profile)
        update("waiting_user", "等待手动验证")
        return "succeeded", "读取 1 条岗位。", [{"title": "Agent 开发", "url": LINKS["boss"]}]

    monkeypatch.setattr(recruitment, "collect_local_boss", local_boss)
    config = {"keyword": "Agent", "city": "杭州", "limit": 10, "sources": ["boss"], "boss_local": True}
    denied = account.post(API + "/runs", json=config, environ_overrides={"REMOTE_ADDR": "192.0.2.15"})
    assert denied.status_code == 403
    forwarded = account.post(API + "/runs", json=config, headers={"X-Forwarded-For": "192.0.2.15"})
    assert forwarded.status_code == 403
    started = account.post(API + "/runs", json=config)
    assert started.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = account.get(API + "/runs").get_json()["items"][0]
        if run["status"] != "running":
            break
        time.sleep(.05)
    assert run["status"] == "complete"
    assert run["progress"]["boss"]["count"] == 1
    assert len(seen_profiles) == 1
    assert seen_profiles[0].parent.parent.name == "recruitment_profiles"
    assert account.email not in str(seen_profiles[0])


def test_boss_reads_search_page_only_after_manual_verification(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from services import recruitment_sources

    class Page:
        verified = False

        def goto(self, url, **_kwargs):
            self.url = url

        def title(self):
            return "职位搜索" if self.verified else "安全验证"

        def wait_for_timeout(self, _delay):
            self.verified = True

        def is_closed(self):
            return False

        def bring_to_front(self):
            pass

        def locator(self, _selector):
            return SimpleNamespace(first=SimpleNamespace(is_visible=lambda: False))

    page = Page()

    def read_cards(candidate, source, limit):
        assert candidate is page and page.verified and source == "boss" and limit == 10
        return [{"title": "Agent 开发", "url": LINKS["boss"]}]

    def open_window(profile, **settings):
        assert profile == tmp_path and settings["headless"] is False
        return nullcontext(SimpleNamespace(pages=[page]))

    monkeypatch.setattr(recruitment_sources, "cards", read_cards)
    playwright = SimpleNamespace(chromium=SimpleNamespace(
        executable_path=__file__, launch_persistent_context=open_window
    ))
    updates = []
    status, _, rows = recruitment_sources.collect_local_boss(
        playwright, tmp_path, "Agent", "杭州", 10, lambda state, _message: updates.append(state)
    )
    assert updates == ["opening", "waiting_user"]
    assert status == "succeeded" and len(rows) == 1


@pytest.mark.parametrize(("source", "host", "target", "route_url", "login"), [
    ("boss", "www.zhipin.com", "https://www.zhipin.com/web/geek/jobs?query=Agent&city=101210100",
     "https://www.zhipin.com/web/geek/jobs?query=Agent&city=101210100", "unknown"),
    ("zhilian", "www.zhaopin.com", "https://www.zhaopin.com/jobs?kw=Agent&jl=653",
     "https://www.zhaopin.com/jobs/?kw=Agent&jl=653", "ready"),
    ("zhilian", "www.zhaopin.com", "https://www.zhaopin.com/jobs?kw=Agent&jl=653",
     "https://www.zhaopin.com/jobs/?kw=Agent&jl=653", "not_logged_in"),
    ("zhilian", "www.zhaopin.com", "https://www.zhaopin.com/jobs?kw=Agent&jl=653",
     "https://www.zhaopin.com/jobs/?kw=Agent&jl=653", "after_login"),
])
def test_chrome_bridge_reads_and_closes_only_its_search_tab(monkeypatch, source, host, target, route_url, login):
    import json

    import httpx

    from services import recruitment_chrome

    tab_id = "3" * 32
    requests = []

    def route(request):
        path = request.url.path
        requests.append(path)
        if path == "/health":
            return httpx.Response(200, json={"connected": True})
        if path == "/new":
            assert request.url.params["url"] == "about:blank"
            return httpx.Response(200, json={"targetId": tab_id})
        assert request.url.params["target"] == tab_id
        if path == "/navigate":
            assert request.url.params["url"] == target
            return httpx.Response(200, json={})
        if path == "/close":
            return httpx.Response(200, json={"success": True})
        script = request.content.decode()
        if "verification:" in script:
            state = login if login != "after_login" else "ready" if requests.count("/eval") > 2 else "not_logged_in"
            value = {"url": route_url, "title": "岗位搜索", "verification": False, "zhilianLogin": state, "bossLogin": "ready"}
        else:
            assert f"location.origin === 'https://{host}'" in script
            value = [{"title": "Agent 开发", "url": LINKS[source]}]
        return httpx.Response(200, json={"value": json.dumps(value)})

    client = httpx.Client
    monkeypatch.setattr(recruitment_chrome.httpx, "Client",
                        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(route)))
    clock = [0]
    monkeypatch.setattr(recruitment_chrome, "monotonic", lambda: clock[0])
    monkeypatch.setattr(recruitment_chrome, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    state, _, rows = recruitment_chrome.collect_in_chrome(source, "Agent", "杭州", 20, lambda *_: None)
    if login == "not_logged_in":
        assert state == "login_timeout" and rows == []
        assert clock[0] == 120
        assert requests == ["/health", "/new", "/navigate"] + ["/eval"] * 120 + ["/close"]
    elif login == "after_login":
        assert state == "succeeded" and len(rows) == 1
        assert requests == ["/health", "/new", "/navigate"] + ["/eval"] * 4 + ["/close"]
    else:
        assert state == "succeeded" and len(rows) == 1
        assert requests == ["/health", "/new", "/navigate", "/eval", "/eval", "/close"]


@pytest.mark.parametrize(("source", "state", "label"), [
    ("boss", "ready", "已登录"),
    ("51job", "not_logged_in", "未登录"),
    ("zhilian", "verification_required", "需要安全验证"),
    ("xiaohongshu", "unknown", "未能确认"),
    ("boss", "unavailable", "检查失败"),
])
def test_platform_login_status_only_checks_authorized_local_browser(make_account, monkeypatch, source, state, label):
    from services import recruitment

    account = make_account("platform-login")
    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    checked = []

    def check(selected):
        checked.append(selected)
        return state

    monkeypatch.setattr(recruitment, "check_platform_login", check)
    url = API + "/session/" + source
    assert account.post(url, json={}, environ_overrides={"REMOTE_ADDR": "192.0.2.15"}).status_code == 403
    assert account.client.post(url, json={}).status_code == 403
    assert account.post(API + "/session/liepin", json={}).status_code == 404
    response = account.post(url, json={})
    assert response.status_code == 200
    assert response.get_json()["state"] == state
    assert response.get_json()["label"] == label
    assert checked == [source]


@pytest.mark.parametrize(("source", "url", "field", "state", "expected"), [
    ("boss", "https://www.zhipin.com/web/geek/jobs", "bossLogin", "ready", "ready"),
    ("51job", "https://we.51job.com/pc/search", "job51Login", "not_logged_in", "not_logged_in"),
    ("zhilian", "https://passport.zhaopin.com/", "zhilianLogin", "ready", "not_logged_in"),
    ("xiaohongshu", "https://www.xiaohongshu.com/explore", "xhsLogin", "ready", "ready"),
    ("xiaohongshu", "https://www.zhipin.com/", "xhsLogin", "ready", "unknown"),
])
def test_platform_session_uses_its_own_site_and_signal(source, url, field, state, expected):
    from services.recruitment_chrome import platform_session

    snapshot = {"url": url, "title": "", "verification": False, field: state}
    assert platform_session(source, snapshot) == expected


def test_zhilian_detail_is_verified_cached_and_included_in_csv(make_account, monkeypatch):
    from services import db, recruitment

    owner = make_account("zhilian-detail")
    other = make_account("other-zhilian-detail")
    url = LINKS["zhilian"]
    endpoint = API + "/jobs/zhilian/detail"
    with db._get_conn() as conn:
        recruitment.save_rows(conn, owner.email, "zhilian", [{"url": url, "title": "Agent 开发", "description": "卡片摘要"}])
    states = iter([("not_logged_in", ""), ("ready", "岗位职责\n开发 Agent 应用。\n任职要求\n熟悉 Python。")])
    calls = []

    def read(candidate):
        calls.append(candidate)
        return next(states)

    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    monkeypatch.setattr(recruitment, "read_zhilian_detail", read)
    assert other.post(endpoint, json={"url": url}).status_code == 404
    assert owner.post(endpoint, json={"url": url}, environ_overrides={"REMOTE_ADDR": "192.0.2.15"}).status_code == 403
    assert owner.post(endpoint, json={"url": url}).status_code == 422
    result = owner.post(endpoint, json={"url": url}).get_json()
    assert "任职要求" in result["description"]
    assert owner.post(endpoint, json={"url": url}, environ_overrides={"REMOTE_ADDR": "192.0.2.15"}).get_json() == result
    assert calls == [url, url]
    assert owner.get(API + "/jobs?source=zhilian").get_json()["items"][0]["description"] == result["description"]
    assert "开发 Agent 应用。" in owner.get(API + "/export?source=zhilian").data.decode("utf-8-sig")


def test_cleaning_preview_apply_filter_and_release_are_account_scoped(make_account):
    from services import db, recruitment

    owner = make_account("cleaning")
    other = make_account("cleaning-other")
    endpoint = API + "/cleaning"
    rows = [
        {"title": "工程师 A", "location": "杭州·西湖区", "salary": "8–12K", "url": "https://www.zhipin.com/job_detail/a.html"},
        {"title": "工程师 B", "location": "杭州", "salary": "5-8K", "url": "https://www.zhipin.com/job_detail/b.html"},
        {"title": "工程师 C", "location": "杭州市", "salary": "300元/天", "url": "https://www.zhipin.com/job_detail/c.html"},
        {"title": "电话销售", "location": "杭州", "salary": "10-20K", "url": "https://www.zhipin.com/job_detail/d.html"},
    ]
    with db._get_conn() as conn:
        recruitment.save_rows(conn, owner.email, "boss", rows)
        recruitment.save_rows(conn, other.email, "boss", rows[:1])
    assert owner.get(endpoint).get_json()["rules"]["auto"] is False
    rules = {"cities": ["杭州"], "min_salary_k": 10, "max_salary_k": 20, "title_exclusions": ["销售"]}
    preview = owner.post(endpoint + "/preview", json={"rules": rules}).get_json()
    assert preview["counts"] == {"passed": 1, "rejected": 2, "review": 1}
    assert owner.get(API + "/jobs?clean_status=unreviewed").get_json()["total"] == 4
    assert other.post(endpoint + "/apply", json={"rules": rules, "token": preview["token"]}).status_code == 409
    assert owner.post(endpoint + "/apply", json={"rules": rules, "token": preview["token"]}).status_code == 200
    rejected = owner.get(API + "/jobs?clean_status=rejected").get_json()["items"]
    assert {row["title"]: row["cleaning_reason"] for row in rejected} == {
        "工程师 B": "月薪「5-8K」与目标区间无交集", "电话销售": "标题命中排除词「销售」",
    }
    assert "工程师 B" in owner.get(API + "/export?clean_status=rejected").data.decode("utf-8-sig")
    release = {"source": "boss", "url": rows[1]["url"]}
    assert other.post(endpoint + "/release", json=release).status_code == 404
    assert owner.post(endpoint + "/release", json=release).get_json()["counts"]["passed"] == 2
    assert owner.post(endpoint + "/release", json=release).status_code == 200
    preview = owner.post(endpoint + "/preview", json={"rules": rules}).get_json()
    assert preview["counts"]["rejected"] == 1
    with db._get_conn() as conn:
        recruitment.save_rows(conn, owner.email, "boss", [{**rows[1], "salary": "7K"}])
    assert owner.post(endpoint + "/apply", json={"rules": rules, "token": preview["token"]}).status_code == 409
    passed = owner.get(API + "/jobs?clean_status=passed").get_json()["items"]
    assert any(row["cleaning_status"] == "released" and row["salary"] == "7K" for row in passed)
    assert other.get(endpoint).get_json()["counts"]["unreviewed"] == 1


def test_auto_cleaning_applies_to_imports_and_keeps_uncertain_fields(make_account, monkeypatch):
    from services import recruitment

    account = make_account("cleaning-auto")
    endpoint = API + "/cleaning"
    rules = {"min_salary_k": 10, "company_exclusions": ["猎头"], "auto": True}
    assert account.post(endpoint + "/save", json={"rules": rules}).status_code == 200
    csv = "source,title,company,salary,url\nboss,开发,甲,8千-10000元/月,https://www.zhipin.com/job_detail/csv.html\n"
    reply = account.post(API + "/import", data={"file": (BytesIO(csv.encode()), "jobs.csv")})
    assert reply.get_json()["cleaning"] == {"passed": 1, "rejected": 0, "review": 0}
    monkeypatch.setattr(recruitment, "read_saved_page", lambda *_: [
        {"title": "测试工程师", "company": "示例猎头", "url": LINKS["boss"]},
    ])
    reply = account.post(API + "/import-html", data={"source": "boss", "file": (BytesIO(b"<p>job</p>"), "jobs.html")})
    assert reply.get_json()["cleaning"]["rejected"] == 1
    assert account.post(endpoint + "/save", json={"rules": {"min_salary_k": 20, "max_salary_k": 10}}).status_code == 400
    assert account.get(endpoint).get_json()["rules"] == {
        **rules, "max_salary_k": None, "min_daily_salary": None, "max_daily_salary": None, "cities": [], "title_exclusions": [],
        "semantic_required": [], "semantic_excluded": [],
    }


def test_recruitment_ai_semantic_and_match_use_separate_models_and_preserve_evidence(make_account, monkeypatch):
    from services import db, recruitment

    account = make_account("ai-screen")
    other = make_account("ai-screen-other")
    cleaner = ("https://cleaner.example", "mock-key", "cleaner")
    main = ("https://main.example", "mock-key", "main")
    monkeypatch.setattr(recruitment.llm_env, "recruitment_cleaner_runtime", lambda: cleaner)
    monkeypatch.setattr(recruitment.llm_env, "chat_runtime", lambda: main)
    first = {"source": "boss", "url": LINKS["boss"], "profile": "internship"}
    second = {**first, "url": "https://www.zhipin.com/job_detail/another.html"}
    fabricated = {**first, "url": "https://www.zhipin.com/job_detail/fabricated.html"}
    assert account.post(API + "/cleaning/save", json={"profile": "internship", "rules": {
        "auto": True, "semantic_excluded": ["单休，包括大小周"],
    }}).status_code == 200
    with db._get_conn() as conn:
        recruitment.save_rows(conn, account.email, "boss", [
            {**first, "title": "实习甲", "description": "工作制度为大小周"},
            {**second, "title": "实习乙", "description": "使用Python开发数据接口"},
            {**fabricated, "title": "实习丙", "description": "描述没有休息安排"},
        ], profile="internship")

    def model(runtime, _prompt, payload, _images=()):
        if runtime == cleaner:
            if payload["job"]["title"] == "实习乙":
                return {"verdict": "passed"}
            return {"verdict": "rejected", "rule": "单休，包括大小周", "reason": "岗位采用大小周", "evidence": "大小周"}
        assert runtime == main
        evidence = {"score": 4, "reason": "项目经历匹配", "jd_evidence": "Python", "resume_evidence": "Python 项目"}
        return {"dimensions": {name: evidence for name in ("role", "skills", "experience")}}

    monkeypatch.setattr(recruitment.ai, "request_model", model)
    assert account.post(API + "/ai/run/semantic", json=first).get_json()["result"]["verdict"] == "rejected"
    assert account.post(API + "/ai/run/semantic", json=fabricated).get_json()["result"]["verdict"] == "review"
    assert account.post(API + "/ai/run/semantic", json=second).get_json()["result"]["verdict"] == "passed"
    assert account.get(API + "/jobs?profile=internship&clean_status=rejected").get_json()["total"] == 1
    assert account.post(API + "/ai/run/match", json=first).status_code == 409
    assert other.post(API + "/ai/details", json=second).status_code == 404
    assert account.post(API + "/ai/settings", json={"profile": "internship", "settings": {
        "resume": "两段 Python 项目经历", "weights": {"role": 5, "skills": 4, "experience": 1},
    }}).status_code == 200
    result = account.post(API + "/ai/run/match", json=second).get_json()["result"]
    assert result["score"] == 80 and result["coverage"] == 3
    assert result["dimensions"]["skills"]["jd_evidence"] == "Python"
    top = account.get(API + "/jobs?sort=match").get_json()["items"][0]
    assert top["url"] == second["url"] and top["ai_score"] == 80
    scored = account.get(API + "/jobs?profile=internship&clean_status=scored&compact=1").get_json()
    assert scored["view_counts"] == {"all": 3, "unreviewed": 0, "passed": 1, "review": 1, "rejected": 1, "scored": 1}
    assert scored["total"] == 1 and scored["items"][0]["url"] == second["url"]
    assert {"description", "cleaning_reason"}.isdisjoint(scored["items"][0])
    assert other.post(API + "/jobs/detail", json=second).status_code == 404
    detail = account.post(API + "/jobs/detail", json=first).get_json()
    assert detail["description"] == "工作制度为大小周"
    assert detail["cleaning_status"] == "rejected" and "大小周" in detail["cleaning_reason"]
    matched_search = account.get(API + "/jobs?compact=1&q=乙").get_json()
    assert matched_search["view_counts"]["all"] == 1 and matched_search["view_counts"]["scored"] == 1
    assert account.post(API + "/cleaning/release", json=first).status_code == 200
    assert account.get(API + "/jobs?profile=internship&clean_status=passed").get_json()["total"] == 2
    monkeypatch.setattr(recruitment.ai, "request_model", lambda *_: {"verdict": "invalid"})
    assert account.post(API + "/ai/run/match", json=second).status_code == 502
    assert account.post(API + "/ai/details", json=second).get_json()["results"]["match"]["score"] == 80


def test_recruitment_ai_extracts_multiple_jobs_from_uploaded_note_images(make_account, monkeypatch):
    from PIL import Image
    from services import db, recruitment

    account = make_account("vision-note")
    url = LINKS["xiaohongshu"]
    with db._get_conn() as conn:
        recruitment.save_rows(conn, account.email, "xiaohongshu", [{"title": "招聘图文", "url": url}])
    runtime = ("https://vision.example", "mock-key", "vision")
    monkeypatch.setattr(recruitment.llm_env, "recruitment_cleaner_runtime", lambda: runtime)

    def model(selected, _prompt, _payload, images):
        assert selected == runtime
        assert images[0].startswith("data:image/png;base64,")
        return {"jobs": [{"title": "实习岗位", "salary": "300元/天"}, {"title": "全职岗位", "salary": "20K"}]}

    monkeypatch.setattr(recruitment.ai, "request_model", model)
    image = BytesIO()
    Image.new("RGB", (20, 20)).save(image, format="PNG")
    image.seek(0)
    identity = {"source": "xiaohongshu", "url": url}
    route = API + "/ai/run/vision"
    assert account.post(route, data={**identity, "images": (BytesIO(b"not an image"), "note.png")}).status_code == 400
    result = account.post(route, data={**identity, "images": (image, "note.png")}).get_json()["result"]
    assert [item["title"] for item in result["jobs"]] == ["实习岗位", "全职岗位"]
    assert account.post(API + "/ai/details", json=identity).get_json()["results"]["vision"] == result

    seen = []
    note_link = url + "?xsec_token=example&xsec_source=pc_search"
    with db._get_conn() as conn:
        recruitment.save_rows(conn, account.email, "xiaohongshu", [{"title": "招聘图文", "url": url, "note_url": note_link}])
    monkeypatch.setenv("CAREER_RECRUITMENT_USE_LOCAL_CHROME", "1")
    monkeypatch.setattr(recruitment, "read_xiaohongshu_images", lambda note: seen.append(note) or ["https://sns-img.xhscdn.com/note.png"])
    monkeypatch.setattr(recruitment.ai, "request_model", lambda *_: {"jobs": [{"title": "图片岗位"}]})
    assert account.post(route, json=identity).get_json()["result"]["jobs"][0]["title"] == "图片岗位"
    assert seen == [note_link]
    assert account.get(API + "/jobs").get_json()["items"][0]["url"] == url


def test_cleaning_profiles_keep_rules_and_decisions_separate(make_account):
    account = make_account("profile-rules")
    other = make_account("profile-other")
    endpoint = API + "/cleaning"
    intern = {"min_daily_salary": 200, "max_daily_salary": 350, "auto": True}
    full_time = {"min_salary_k": 15, "title_exclusions": ["实习"], "auto": True}
    assert account.post(endpoint + "/save", json={"profile": "internship", "rules": intern}).status_code == 200
    assert account.post(endpoint + "/save", json={"profile": "full_time", "rules": full_time}).status_code == 200
    assert account.post(endpoint + "/save", json={"profile": "full_time", "rules": intern}).status_code == 400

    def import_job(profile, path, title, pay):
        csv = f"source,title,salary,url\nboss,{title},{pay},https://www.zhipin.com/job_detail/{path}.html\n"
        return account.post(API + "/import", data={"profile": profile, "file": (BytesIO(csv.encode()), "jobs.csv")}).get_json()

    assert import_job("internship", "a", "工程实习", "150–250元/天")["cleaning"]["passed"] == 1
    assert import_job("internship", "b", "工程实习", "150元/天")["cleaning"]["rejected"] == 1
    assert import_job("full_time", "c", "工程师", "12-18K")["cleaning"]["passed"] == 1
    assert import_job("full_time", "d", "工程师", "150–250元/天")["cleaning"]["review"] == 1
    assert import_job("general", "b", "工程实习", "150元/天")["cleaning"]["rejected"] == 1
    assert import_job("full_time", "b", "工程实习", "150元/天")["cleaning"]["rejected"] == 1
    assert account.get(endpoint + "?profile=internship").get_json()["counts"]["rejected"] == 1
    assert account.get(endpoint + "?profile=full_time").get_json()["counts"]["review"] == 1
    assert account.get(endpoint).get_json()["counts"]["rejected"] == 0
    assert account.get(API + "/jobs?profile=internship").get_json()["total"] == 2
    preview = account.post(endpoint + "/preview", json={"profile": "internship", "rules": intern}).get_json()
    assert preview["counts"] == {"passed": 1, "rejected": 1, "review": 0}
    assert account.post(endpoint + "/apply", json={"profile": "full_time", "rules": full_time, "token": preview["token"]}).status_code == 409

    item = {"source": "boss", "url": "https://www.zhipin.com/job_detail/b.html"}
    assert other.post(API + "/jobs/profile", json={**item, "profile": "full_time"}).status_code == 404
    assert account.post(endpoint + "/release", json={**item, "profile": "internship"}).status_code == 200
    assert account.post(API + "/jobs/profile", json={**item, "profile": "full_time"}).status_code == 200
    moved = account.get(API + "/jobs?profile=full_time&clean_status=rejected").get_json()["items"]
    assert len(moved) == 1 and moved[0]["cleaning_reason"] == "标题命中排除词「实习」"


def test_existing_cleaning_rules_and_listings_migrate_to_general():
    import sqlite3
    from services import recruitment

    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE users (username TEXT PRIMARY KEY);
            INSERT INTO users VALUES ('legacy');
            CREATE TABLE recruitment_cleaning_rules (owner TEXT PRIMARY KEY, rules TEXT NOT NULL);
            INSERT INTO recruitment_cleaning_rules VALUES ('legacy', '{"min_salary_k":12,"auto":true}');
            CREATE TABLE recruitment_listings (
                owner TEXT, source TEXT, url_key TEXT, title TEXT, company TEXT, location TEXT,
                salary TEXT, description TEXT, url TEXT, updated_at REAL, PRIMARY KEY(owner, source, url_key)
            );
            INSERT INTO recruitment_listings VALUES ('legacy','boss','url','title','','','9K','','url',0);
        """)
        recruitment.init_schema(conn)
        recruitment.init_schema(conn)
        rule = recruitment.cleaning.load_rules(conn, "legacy", "general")
        assert rule.auto and rule.min_salary_k == 12
        assert not recruitment.cleaning.load_rules(conn, "legacy", "internship").auto
        assert conn.execute("SELECT profile FROM recruitment_listings").fetchone()[0] == "general"


@pytest.mark.parametrize(("salary", "expected"), [
    ("8K–12K·13薪", (8000, 12000)), ("1.2-1.8万元/月", (12000, 18000)),
    ("8千-10000元/月", (8000, 10000)), ("8-12万/年", (None, None)),
    ("面议", (None, None)), ("300元/天", (None, None)), ("10K起", (None, None)),
])
def test_cleaning_only_compares_unambiguous_monthly_salary(salary, expected):
    from services.recruitment_cleaning import monthly_pay

    assert monthly_pay(salary) == expected


def test_encoded_salary_is_hidden_from_results_and_csv_without_erasing_a_known_value(make_account):
    from services import db, recruitment

    account = make_account("salary")
    connection = db._get_conn()
    encoded = "\ue032\ue031-\ue033K"
    with connection:
        connection.execute("""INSERT INTO recruitment_listings
                           (owner, source, url_key, title, company, location, salary, description, url, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           (account.email, "boss", LINKS["boss"], "开发", "示例公司", "杭州", encoded,
                            f"岗位说明\n{encoded}", LINKS["boss"], time.time()))
    legacy = account.get(API + "/jobs").get_json()["items"][0]
    assert legacy["salary"] == "" and legacy["description"] == "岗位说明"
    assert encoded not in account.get(API + "/export").data.decode("utf-8-sig")

    row = {"title": "开发", "url": LINKS["boss"]}
    with connection:
        recruitment.save_rows(connection, account.email, "boss", [{**row, "salary": "15-24K"}])
        recruitment.save_rows(connection, account.email, "boss", [{**row, "salary": encoded}])
    assert account.get(API + "/jobs").get_json()["items"][0]["salary"] == "15-24K"
