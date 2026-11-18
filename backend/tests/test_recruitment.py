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
    monkeypatch.setattr(recruitment, "launch_browser", lambda _: nullcontext(object()))

    def collect(_browser, source, keyword, city, limit):
        assert (keyword, city, limit) == ("Agent", "杭州", 10)
        return "succeeded", "读取 1 条结果。", [{"title": "Agent 开发", "url": LINKS[source], "location": city}]

    monkeypatch.setattr(recruitment, "collect_source", collect)
    assert owner.get("/recruitment").status_code == 200
    assert owner.post(API + "/runs", json={"keyword": "Agent", "sources": ["unknown"]}).status_code == 400
    response = owner.post(API + "/runs", json={"keyword": "Agent", "city": "杭州", "sources": list(LINKS), "limit": 10})
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = owner.get(API + "/runs").get_json()["items"][0]
        if run["status"] != "running":
            break
        time.sleep(.05)
    assert run["status"] == "complete"
    assert set(run["progress"]) == set(LINKS)
    assert owner.get(API + "/jobs?source=51job").get_json()["total"] == 1
    assert owner.get(API + "/jobs").get_json()["total"] == 5
    assert other.get(API + "/jobs").get_json()["total"] == 0
    assert other.get(API + "/runs").get_json()["items"] == []


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


@pytest.mark.parametrize(("source", "host", "target", "route_url"), [
    ("boss", "www.zhipin.com", "https://www.zhipin.com/web/geek/jobs?query=Agent&city=101210100",
     "https://www.zhipin.com/web/geek/jobs?query=Agent&city=101210100"),
    ("zhilian", "www.zhaopin.com", "https://www.zhaopin.com/jobs?kw=Agent&jl=653",
     "https://www.zhaopin.com/jobs/?kw=Agent&jl=653"),
])
def test_chrome_bridge_reads_and_closes_only_its_search_tab(monkeypatch, source, host, target, route_url):
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
            assert request.url.params["url"] == target
            return httpx.Response(200, json={"targetId": tab_id})
        assert request.url.params["target"] == tab_id
        if path == "/close":
            return httpx.Response(200, json={"success": True})
        script = request.content.decode()
        if "verification:" in script:
            value = {"url": route_url, "title": "岗位搜索", "verification": False}
        else:
            assert f"location.origin === 'https://{host}'" in script
            value = [{"title": "Agent 开发", "url": LINKS[source]}]
        return httpx.Response(200, json={"value": json.dumps(value)})

    client = httpx.Client
    monkeypatch.setattr(recruitment_chrome.httpx, "Client",
                        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(route)))
    state, _, rows = recruitment_chrome.collect_in_chrome(source, "Agent", "杭州", 20, lambda *_: None)
    assert state == "succeeded" and len(rows) == 1
    assert requests == ["/health", "/new", "/eval", "/eval", "/close"]


def test_encoded_salary_is_hidden_from_results_and_csv_without_erasing_a_known_value(make_account):
    from services import db, recruitment

    account = make_account("salary")
    connection = db._get_conn()
    encoded = "\ue032\ue031-\ue033K"
    with connection:
        connection.execute("INSERT INTO recruitment_listings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
