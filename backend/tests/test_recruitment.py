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
