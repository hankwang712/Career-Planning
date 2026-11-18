"""报告存储与接口：保存、读取、历史版本、导出、快照、行动追踪与删除（不需要模型）。"""
import pytest


def make_bundle(report_id, title="职业发展报告"):
    return {
        "meta": {"report_id": report_id, "title": title, "generated_at": "2026-01-01 10:00:00", "version": "v1",
                 "generation_mode": "test"},
        "report_document": {
            "title": title,
            "markdown": f"# {title}\n\n## 方向建议\n\n补强系统设计。\n\n## 行动计划\n\n- 准备项目讲述\n",
        },
    }


@pytest.fixture()
def seeded(make_account):
    from services.report.writer import _save_career_report_bundle

    account = make_account("report")
    _save_career_report_bundle(account.email, make_bundle("r-first"))
    return account, _save_career_report_bundle


def test_new_account_has_no_report(make_account):
    account = make_account("empty")
    response = account.get("/api/career-report/current")
    assert response.status_code == 200
    assert response.get_json()["data"] is None


def test_saved_report_is_returned_as_current(seeded):
    account, _ = seeded
    data = account.get("/api/career-report/current").get_json()["data"]
    assert data["meta"]["report_id"] == "r-first"
    # 对外返回的报告不带整份 Markdown / HTML，避免每次轮询都传一大段正文。
    assert "markdown" not in data["report_document"] and "html" not in data["report_document"]


def test_saving_a_second_report_archives_the_first(seeded):
    account, save = seeded
    save(account.email, make_bundle("r-second", "第二份报告"))
    assert account.get("/api/career-report/current").get_json()["data"]["meta"]["report_id"] == "r-second"
    old = account.get("/api/career-report/version", query_string={"report_id": "r-first"})
    assert old.status_code == 200, old.get_data(as_text=True)[:300]
    assert old.get_json()["data"]["meta"]["report_id"] == "r-first"


def test_report_identifiers_are_validated_before_any_lookup(seeded):
    account, _ = seeded
    for bad in ("../secret", "a/b", "x" * 200, "has space"):
        response = account.get("/api/career-report/version", query_string={"report_id": bad})
        assert response.status_code == 400, bad


@pytest.mark.parametrize("fmt,marker", [("md", b"# "), ("html", b"<"), ("docx", b"PK"), ("pdf", b"%PDF-")])
def test_report_exports(seeded, fmt, marker):
    account, _ = seeded
    response = account.get("/api/career-report/export", query_string={"format": fmt, "report_id": "r-first"})
    assert response.status_code == 200, response.get_data(as_text=True)[:200]
    assert marker in response.data[:400]
    assert "attachment" in response.headers.get("Content-Disposition", "")


def test_export_rejects_an_unknown_format(seeded):
    account, _ = seeded
    assert account.get("/api/career-report/export", query_string={"format": "exe"}).status_code == 400


def test_export_of_a_missing_report_is_404(make_account):
    account = make_account("noreport")
    assert account.get("/api/career-report/export", query_string={"format": "md"}).status_code == 404


def test_feedback_is_recorded_and_validated(seeded):
    account, _ = seeded
    assert account.post("/api/career-report/feedback", json={"verdict": "meh"}).status_code == 400
    response = account.post("/api/career-report/feedback", json={"verdict": "accurate", "note": "有帮助"})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert response.get_json()["feedback"]


def test_snapshot_can_be_saved_and_checked(seeded):
    account, _ = seeded
    assert account.post("/api/career-report/snapshot/save", json={"report_id": "r-first"}).status_code == 400
    saved = account.post("/api/career-report/snapshot/save", json={"report_id": "r-first", "markdown": "# 快照\n\n内容"})
    assert saved.status_code == 200, saved.get_data(as_text=True)[:300]
    checked = account.post("/api/career-report/snapshot/check", json={"report_id": "r-first"})
    assert checked.status_code == 200 and checked.get_json()["report_id"] == "r-first"
    assert account.post("/api/career-report/snapshot/save", json={"report_id": "nope", "markdown": "x"}).status_code == 404


def test_tracker_sync_builds_a_tracker_for_the_report(seeded):
    account, _ = seeded
    response = account.post("/api/career-report/tracker/sync", json={})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert isinstance(response.get_json()["tracker"], dict)


def test_tracker_requires_a_report(make_account):
    account = make_account("notracker")
    assert account.post("/api/career-report/tracker/sync", json={}).status_code == 404
    assert account.post("/api/career-report/tracker/item", json={"item_type": "plan", "item_id": "x"}).status_code == 404


def test_polish_without_a_configured_model_reports_it(seeded):
    account, _ = seeded
    response = account.post("/api/career-report/polish", json={"report_id": "r-first", "markdown": "# 草稿\n内容", "instruction": "更简洁"})
    assert response.status_code in {400, 503}, response.get_data(as_text=True)[:200]
    assert response.get_json()["message"]


def test_generation_status_is_readable_for_a_new_account(make_account):
    account = make_account("idle")
    response = account.get("/api/career-report/generate/status")
    assert response.status_code == 200, response.get_data(as_text=True)[:300]


def test_generation_requires_a_model(make_account):
    account = make_account("nomodel")
    response = account.post("/api/career-report/generate/start", json={})
    assert response.status_code in {400, 503}
    assert response.get_json()["message"]


def test_generation_uses_latest_nonempty_resume_draft(make_account, monkeypatch):
    from services.report import api
    from services.user_state import _save_user_state

    account = make_account("report-draft")
    other = make_account("other-draft")
    source_url = "/api/career-report/resume-source"
    start_url = "/api/career-report/generate/start"
    drafts_url = "/api/resume-editor/drafts"
    assert account.get(source_url).get_json() == {"source": None}
    assert "个人中心" in account.post(start_url, json={}).get_json()["message"]

    _save_user_state(account.email, {"resume_profile": {"file_name": "old.pdf", "resume_source_text": "旧版内容"}})
    assert account.get(source_url).get_json() == {"source": {"kind": "upload", "title": "old.pdf"}}
    section = {"title": "项目经历", "content": "开发简历分析工具"}
    assert account.post(drafts_url, json={"title": "历史版本", "sections": [{**section, "content": "旧项目"}]}).status_code == 201
    assert account.post(drafts_url, json={"title": "求职版", "sections": [section],
                                          "contact": {"email": "private@example.com"}}).status_code == 201
    assert account.post(drafts_url, json={"title": "空白版"}).status_code == 201
    assert account.get(source_url).get_json() == {"source": {"kind": "draft", "title": "求职版"}}
    assert other.get(source_url).get_json() == {"source": None}

    def validate(_workflow, raw_resume, *, file_path):
        assert raw_resume == "## 项目经历\n开发简历分析工具"
        assert not file_path
        raise ValueError("validated")

    monkeypatch.setattr(api, "validate_report_request", validate)
    response = account.post(start_url, json={"workflow": {"targets": ["开发工程师"], "raw_resume": "客户端替代内容"}})
    assert response.status_code == 400
    assert response.get_json()["message"] == "validated"


def test_deleting_the_current_version_promotes_the_archived_one(seeded):
    account, save = seeded
    save(account.email, make_bundle("r-second", "第二份"))
    deleted = account.delete("/api/career-report/version", json={"report_id": "r-second"})
    assert deleted.status_code == 200, deleted.get_data(as_text=True)[:300]
    assert deleted.get_json()["replacement_report_id"] == "r-first"
    assert account.get("/api/career-report/current").get_json()["data"]["meta"]["report_id"] == "r-first"
    account.delete("/api/career-report/version", json={"report_id": "r-first"})
    assert account.get("/api/career-report/current").get_json()["data"] is None
    assert account.delete("/api/career-report/version", json={"report_id": "r-first"}).status_code == 404
