"""岗位全链路流水线：临时库全链路 + 投递闸 + 漏斗口径 + 失败分诊 + 启发式校准。"""

import json
from pathlib import Path
import time

import pytest

API = "/api/job-market/collection"
PIPE = API + "/pipeline"

RESUME_TEXT = """求职意向：Python后端开发
工作经历
云杉科技 2021-2026 Python后端开发工程师（5年）
负责订单服务开发与维护，日常使用 Python、Flask、MySQL、Redis、Docker、Linux 交付服务。
从0到1搭建内部工具平台，覆盖率100%，上线后零事故。
精通Python异步编程，主导网关改造，人工智能方向数据处理经验丰富。
期望薪资：20k
"""

JOB_CUSTOM = {
    "title": "Python后端开发工程师", "company": "星河智能", "location": "北京",
    "salary": "25-40K", "experience": "3-5年", "education": "本科",
    "description": "负责后端服务开发。任职要求：Python、Flask、MySQL、Redis、Docker、Linux。提供技术培训与晋升通道。",
    "meta": {"skills": "Python, Flask, MySQL, Redis, Docker, Linux", "company_size": "20-99人",
             "funding": "天使轮", "industry": "人工智能", "category": "后端开发"},
}
JOB_MASS = {
    "title": "Java大数据工程师", "company": "云图数据", "location": "北京",
    "salary": "15-20K", "experience": "5-10年", "education": "本科",
    "description": "负责大数据平台建设。任职要求：Java、Spring、Kafka、Spark、Hadoop。",
    "meta": {"skills": "Java, Spring, Kafka, Spark, Hadoop", "company_size": "20-99人",
             "funding": "天使轮", "industry": "大数据", "category": "大数据"},
}
JOB_MASS_BIG = {**JOB_MASS, "company": "巨头网络", "meta": {**JOB_MASS["meta"], "company_size": "1000-9999人"}}
JOB_REJECTED = {
    "title": "销售代表", "company": "呼叫科技", "location": "北京", "salary": "8-10K",
    "experience": "1-3年", "education": "大专", "description": "负责电话销售与客户拓展。",
    "meta": {"company_size": "20-99人"},
}


def add_job(owner, key, spec):
    from services import db
    with db._get_conn() as conn:
        conn.execute("""
            INSERT INTO recruitment_listings
                (owner, source, url_key, title, company, location, salary, description, experience, education, url, updated_at, profile)
            VALUES (?, 'city_jobs', ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'general')
        """, (owner.email, key, spec["title"], spec["company"], spec["location"], spec["salary"],
              spec["description"], spec["experience"], spec["education"], time.time()))
        conn.execute("""
            INSERT INTO recruitment_pipeline (owner, source, url_key, stage, follow_status, meta, updated_at)
            VALUES (?, 'city_jobs', ?, 'collected', '新线索', ?, ?)
        """, (owner.email, key, json.dumps(spec.get("meta", {}), ensure_ascii=False), time.time()))
    return {"source": "city_jobs", "url_key": key}


def set_baseline(server, owner, text=RESUME_TEXT, fingerprint="fp-baseline"):
    repo = server.app.extensions["chat_service"].documents.repository
    repo.save(owner.email, fingerprint, status="ready", content=text, source={"name": "基准简历.txt"})
    return fingerprint


def setup_account(server, make_account, prefix, *, mass_greeting="您好，我对贵司岗位很感兴趣，期待进一步沟通。",
                  threshold="B", rules=None):
    owner = make_account(prefix)
    baseline = set_baseline(server, owner)
    response = owner.post(PIPE + "/config", json={"baseline_resume_id": baseline,
                                                  "mass_greeting": mass_greeting, "threshold": threshold})
    assert response.status_code == 200, response.get_json()
    if rules is not None:
        assert owner.post(API + "/cleaning/save", json={"profile": "general", "rules": rules}).status_code == 200
    return owner


def run(owner, stage, **extra):
    response = owner.post(PIPE + "/run", json={"stage": stage, **extra})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def job(owner, identity):
    response = owner.get(PIPE + "/job", query_string=identity)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_config_defaults_and_validation(make_account):
    owner = make_account("pipeline-config")
    settings = owner.get(PIPE + "/config").get_json()
    assert settings["settings"]["threshold"] == "B"
    assert settings["settings"]["auto_deliver_grades"] == ["C", "D", "F"]
    assert settings["settings"]["mass_apply_max_headcount"] == 1000
    assert settings["settings"]["dry_run"] is True
    assert settings["heuristic_active"] is True
    assert settings["resume_baseline"]["enabled"] is False
    assert owner.post(PIPE + "/config", json={"threshold": "D"}).status_code == 400
    assert owner.post(PIPE + "/config", json={"dry_run": False}).status_code == 400
    assert owner.post(PIPE + "/config", json={"auto_deliver_grades": []}).status_code == 400
    assert owner.post(PIPE + "/config", json={"baseline_resume_id": "missing"}).status_code == 400
    assert owner.post(PIPE + "/config", json={"mass_apply_max_headcount": 5000}).status_code == 200


def test_seed_idempotent_and_rail(make_account):
    owner = make_account("pipeline-seed")
    first = owner.post(PIPE + "/seed", json={"city": "北京", "limit": 5})
    assert first.status_code == 200
    assert first.get_json()["imported"] == 5
    again = owner.post(PIPE + "/seed", json={"city": "北京", "limit": 5})
    assert again.get_json()["imported"] == 5
    funnel = owner.get(PIPE + "/funnel").get_json()
    assert funnel["stages"][0]["count"] == 5
    rail = owner.get(PIPE + "/rail").get_json()
    scraping = next(step for step in rail["steps"] if step["key"] == "scraping")
    assert scraping["config_state"] == "configured"
    assert rail["resume_baseline"]["enabled"] is False
    jobs = owner.get(PIPE + "/jobs?tab=all").get_json()
    assert jobs["total"] == 5 and jobs["counts"]["all"] == 5
    assert all(item["source"] == "city_jobs" for item in jobs["items"])


def test_manual_clean_uses_saved_jd_criteria_and_continues_through_batches(make_account, monkeypatch):
    from services import recruitment_pipeline as pipeline

    owner = make_account("manual-clean")
    review = add_job(owner, "a-review", JOB_CUSTOM)
    rejected = add_job(owner, "b-rejected", JOB_CUSTOM)
    passed = add_job(owner, "c-passed", JOB_MASS)
    hard_rejected = add_job(owner, "d-hard-rejected", JOB_REJECTED)
    rule = {"keyword": "后端开发", "condition": "never", "desc": "服务端开发是岗位主要职责时命中"}
    assert owner.post(API + "/cleaning/save", json={"profile": "general", "rules": {
        "title_exclusions": ["销售"], "ai_scout_rules": [rule],
    }}).status_code == 200
    assert job(owner, rejected)["stage"] == "collected"
    runtime = ("https://example.test", "key", "cleaner")
    monkeypatch.setattr(pipeline.llm_env, "recruitment_cleaner_runtime", lambda: runtime)
    monkeypatch.setattr(pipeline, "LLM_BATCH_LIMIT", 1)
    verdicts = iter([
        {"verdict": "review", "reason": "职责待核实"},
        {"verdict": "rejected", "rule": "后端开发", "evidence": "负责后端服务开发"},
        {"verdict": "passed"},
    ])

    def screen(active_runtime, jd, rules):
        assert active_runtime == runtime
        assert jd["description"] and rules.ai_scout_rules[0].model_dump() == rule
        return next(verdicts)

    monkeypatch.setattr(pipeline.ai, "screen", screen)
    first = run(owner, "clean", use_cleaner=True)
    assert first["counts"]["review"] == 1 and first["next_cursor"] == ["city_jobs", "a-review"]
    second = run(owner, "clean", use_cleaner=True, after=first["next_cursor"])
    assert second["counts"]["rejected"] == 1 and second["next_cursor"] == ["city_jobs", "b-rejected"]
    third = run(owner, "clean", use_cleaner=True, after=second["next_cursor"])
    assert third["counts"]["passed"] == 1 and third["counts"]["rejected"] == 1
    assert third["next_cursor"] is None
    assert job(owner, review)["cleaning_status"] == "review"
    assert job(owner, rejected)["stage"] == job(owner, hard_rejected)["stage"] == "rejected"
    tally = {row["url_key"]: row["cleaning_reason"] for row in owner.get(PIPE + "/jobs?tab=rejected").get_json()["items"]}
    assert "负责后端服务开发" in tally[rejected["url_key"]]
    assert job(owner, passed)["stage"] == "cleaned"
    counts = {stage["key"]: stage["count"] for stage in owner.get(PIPE + "/funnel").get_json()["stages"]}
    assert counts["cleaned"] == 1 and counts["evaluated"] == 0

    assert owner.post(API + "/cleaning/save", json={"profile": "general", "rules": {}}).status_code == 200
    assert run(owner, "clean", use_cleaner=True)["counts"]["passed"] == 4
    assert job(owner, rejected)["stage"] == "cleaned"


def test_cleaning_releases_database_during_model_call_and_skips_changed_rules(make_account, monkeypatch):
    import sqlite3
    from services import db, recruitment_pipeline as pipeline

    owner = make_account("cleaning-concurrent")
    identity = add_job(owner, "concurrent", JOB_CUSTOM)
    assert owner.post(API + "/cleaning/save", json={"rules": {
        "ai_scout_rules": [{"keyword": "后端开发", "condition": "never"}],
    }}).status_code == 200
    assert owner.get(PIPE + "/cleaning/queue").get_json() == {"total": 1}
    monkeypatch.setattr(pipeline.llm_env, "recruitment_cleaner_runtime", lambda: ("https://example.test", "key", "cleaner"))
    updated = []

    def screen(*_):
        with sqlite3.connect(db.DB_PATH, timeout=0) as other, sqlite3.connect(db.DB_PATH, timeout=0) as reader:
            other.execute("BEGIN IMMEDIATE")
            other.execute("UPDATE recruitment_cleaning_profiles SET rules='{}' WHERE owner=?", (owner.email,))
            reader.row_factory = sqlite3.Row
            assert pipeline.funnel_payload(reader, owner.email)["stages"][0]["count"] == 1
        updated.append(True)
        return {"verdict": "rejected", "reason": "过时的结果"}

    monkeypatch.setattr(pipeline.ai, "screen", screen)
    result = run(owner, "clean", use_cleaner=True, limit=1)
    assert updated == [True] and result["counts"]["skipped"] == 1
    assert job(owner, identity)["stage"] == "collected"
    assert run(owner, "clean", use_cleaner=True, limit=1)["counts"]["passed"] == 1


def test_full_pipeline_heuristic_chain(server, make_account):
    owner = setup_account(server, make_account, "pipeline-full", rules={"title_exclusions": ["销售"]})
    custom = add_job(owner, "t:custom", JOB_CUSTOM)
    mass = add_job(owner, "t:mass", JOB_MASS)
    big = add_job(owner, "t:big", JOB_MASS_BIG)
    rejected = add_job(owner, "t:rejected", JOB_REJECTED)

    result = run(owner, "clean")
    assert result["counts"]["rejected"] == 1 and result["counts"]["passed"] == 3
    assert job(owner, rejected)["stage"] == "rejected"
    assert job(owner, rejected)["follow_status"] == "清洗淘汰"

    result = run(owner, "evaluate")
    assert result["mode"] == "heuristic" and result["counts"]["screened"] == 3 and result["counts"]["deep"] == 1
    custom_row, mass_row, big_row = job(owner, custom), job(owner, mass), job(owner, big)
    assert custom_row["grade"] in ("A", "B") and custom_row["review_type"] == "custom"
    assert mass_row["grade"] == "C" and mass_row["review_type"] == "mass"
    assert big_row["review_type"] == "mass"
    assert custom_row["stage"] == "deep"
    assert set(custom_row["screen_payload"]["scores"]) == {
        "role_match", "skills_align", "seniority", "compensation",
        "interview_prob", "company_stage", "market_fit", "growth"}
    assert custom_row["screen_payload"]["mode"] == "heuristic"
    funnel = owner.get(PIPE + "/funnel").get_json()
    by_key = {item["key"]: item["count"] for item in funnel["stages"]}
    assert by_key == {"crawled": 4, "cleaned": 3, "evaluated": 3, "pending": 0, "ready": 0, "delivered": 0}

    deep = custom_row["deep_payload"]
    assert set(deep) >= {"extracted_skills", "ats_ability_analysis", "resume_audit", "dream_picture",
                         "strong_fit_assessment", "risk_red_flags", "deep_action_plan"}
    assert deep["mode"] == "heuristic" and deep["missing_skills"] == []
    assert job(owner, mass)["stage"] == "screened"
    assert not mass_row["deep_payload"]

    result = run(owner, "rewrite")
    assert result["processed"] == 1
    rewrite = job(owner, custom)["rewrite_payload"]
    markdown = rewrite["markdown"]
    assert "云杉科技 2021-2026" in markdown
    assert "精通" not in markdown and "100%" not in markdown
    assert "从0到1搭建" not in markdown and "零事故" not in markdown
    assert "熟练掌握" in markdown and "99%+" in markdown and "参与搭建" in markdown and "极低事故率" in markdown
    assert rewrite["downgrades"] and rewrite["contract"]["experience_preserved"] is True
    assert job(owner, custom)["follow_status"] == "简历人工复核"

    result = run(owner, "greet")
    assert result["counts"]["queued"] == 1 and result["counts"]["approval"] == 2
    custom_row, mass_row, big_row = job(owner, custom), job(owner, mass), job(owner, big)
    assert custom_row["stage"] == "approval" and custom_row["follow_status"] == "简历人工复核"
    assert custom_row["delivery_payload"]["gate_ok"] is False
    greeting = custom_row["greeting_payload"]["text"]
    assert 150 <= len(greeting) <= 250 and custom_row["greeting_payload"]["legal"] is True
    assert mass_row["stage"] == "queued" and mass_row["follow_status"] == "待投递"
    assert mass_row["greeting_payload"]["mode"] == "manual"
    assert big_row["stage"] == "approval" and big_row["follow_status"] == "海投人工复核"
    assert "1000" in big_row["delivery_payload"]["reason"]

    tabs = owner.get(PIPE + "/jobs?tab=approval").get_json()
    assert tabs["total"] == 2 and tabs["counts"]["queued"] == 1
    assert owner.get(PIPE + "/jobs?tab=queued").get_json()["total"] == 1
    assert owner.get(PIPE + "/jobs?q=云图").get_json()["total"] == 1

    assert owner.post(PIPE + "/approve", json={**custom, "decision": "approve"}).get_json()["stage"] == "queued"
    assert job(owner, custom)["approval"] == "approved"

    response = owner.post(PIPE + "/deliver_dry", json={"ids": [custom, mass]})
    assert response.status_code == 200
    body = response.get_json()
    assert body["delivered"] == 2 and body["failed"] == 0
    assert len(body["packages"]) == 2
    package = next(item for item in body["packages"] if item["url_key"] == custom["url_key"])
    assert package["resume_markdown"] and package["greeting"] and package["mode"] == "dry-run"
    assert job(owner, custom)["stage"] == "delivered" and job(owner, custom)["follow_status"] == "已投递"
    assert job(owner, mass)["stage"] == "delivered"

    funnel = owner.get(PIPE + "/funnel").get_json()
    by_key = {item["key"]: item["count"] for item in funnel["stages"]}
    assert by_key["delivered"] == 2 and by_key["ready"] == 0 and by_key["pending"] == 1
    assert funnel["delivery_rate"] == round(2 / 3 * 100)
    counts = owner.get(PIPE + "/jobs").get_json()["counts"]
    assert sum(counts[tab] for tab in ("rejected", "in_progress", "reeval", "approval", "queued", "delivered", "failed")) == counts["all"]

    csv_response = owner.post(PIPE + "/deliver_dry", json={"ids": [], "format": "csv"})
    assert csv_response.status_code == 200 and csv_response.mimetype == "text/csv"


def test_mass_empty_master_goes_to_manual_review(server, make_account):
    owner = setup_account(server, make_account, "pipeline-mass-empty", mass_greeting="")
    identity = add_job(owner, "t:mass", JOB_MASS)
    run(owner, "clean")
    run(owner, "screen")
    result = run(owner, "greet")
    assert result["counts"]["mass_review"] == 1
    row = job(owner, identity)
    assert row["stage"] == "approval" and row["follow_status"] == "海投人工复核"
    assert row["greeting_payload"] == {}
    assert owner.post(PIPE + "/queue", json=identity).status_code == 409


def test_delivery_gate_units(make_account):
    from services.recruitment_pipeline import PipelineConfig, delivery_gate, grade_meets_threshold
    config = PipelineConfig()
    assert grade_meets_threshold("A", "B") and grade_meets_threshold("B", "B")
    assert not grade_meets_threshold("C", "B") and grade_meets_threshold("C", "C")
    assert not grade_meets_threshold("", "C")
    ok, reason = delivery_gate(config, "", "mass", "20-99人")
    assert not ok and "评级缺失" in reason
    ok, reason = delivery_gate(config, "C", "mass", "1000-9999人")
    assert not ok and "门槛" in reason
    ok, reason = delivery_gate(PipelineConfig(mass_apply_max_headcount=5000), "C", "mass", "1000-9999人")
    assert not ok, "规模区间必须按上限参与拦截"
    ok, _ = delivery_gate(config, "C", "mass", "20-99人")
    assert ok
    ok, reason = delivery_gate(config, "B", "custom", "20-99人")
    assert not ok and "白名单" in reason
    ok, reason = delivery_gate(config, "F", "mass", "", parse_failed=True)
    assert not ok and "解析失败" in reason


def test_threshold_routes_by_grade_only(server, make_account):
    owner = setup_account(server, make_account, "pipeline-threshold", threshold="B")
    identity = add_job(owner, "t:mass", JOB_MASS)
    run(owner, "clean")
    run(owner, "screen")
    assert job(owner, identity)["review_type"] == "mass"
    assert owner.post(PIPE + "/config", json={"threshold": "C"}).status_code == 200
    assert owner.post(PIPE + "/approve", json={**identity, "decision": "reeval"}).get_json()["stage"] == "reeval"
    assert job(owner, identity)["grade"] == ""
    run(owner, "screen")
    row = job(owner, identity)
    assert row["grade"] == "C" and row["review_type"] == "custom"


def test_combined_evaluation_finishes_previously_screened_jobs_within_batch_limit(server, make_account):
    owner = setup_account(server, make_account, "pipeline-evaluate-backlog")
    mass = add_job(owner, "t:mass", JOB_MASS)
    pending = add_job(owner, "t:pending", JOB_CUSTOM)
    run(owner, "clean")
    run(owner, "screen")
    assert job(owner, pending)["stage"] == "screened"
    fresh = add_job(owner, "t:fresh", JOB_CUSTOM)
    run(owner, "clean")

    result = run(owner, "evaluate", limit=1)
    assert result["processed"] == 1 and result["counts"]["screened"] == 0 and result["counts"]["deep"] == 1
    assert job(owner, pending)["stage"] == "deep"
    assert job(owner, mass)["stage"] == "screened"
    assert job(owner, fresh)["stage"] == "cleaned"

    result = run(owner, "evaluate", limit=1)
    assert result["processed"] == 1 and result["counts"]["screened"] == 1 and result["counts"]["deep"] == 1
    assert job(owner, fresh)["stage"] == "deep"
    assert run(owner, "evaluate")["processed"] == 0


def test_screen_parse_failed_never_fabricates_grade(server, make_account, monkeypatch):
    owner = setup_account(server, make_account, "pipeline-parse-fail")
    identity = add_job(owner, "t:custom", JOB_CUSTOM)
    run(owner, "clean")
    monkeypatch.setenv("AI_CHAT_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("AI_CHAT_API_KEY", "test-key")
    monkeypatch.setenv("AI_CHAT_MODEL", "test-model")
    # 启发式开关默认开启；本测试验证 LLM 解析失败路径，需显式切回模型模式
    assert owner.post(PIPE + "/config", json={"heuristic_mode": False}).status_code == 200
    from services import recruitment_pipeline as pipeline
    calls = []

    def broken(runtime, job, resume, config):
        calls.append(1)
        raise ValueError("模型输出不是合法 JSON")

    monkeypatch.setattr(pipeline, "_screen_llm", broken)
    result = run(owner, "evaluate")
    assert result["counts"]["parse_failed"] == 1 and result["counts"]["deep"] == 0
    assert len(calls) == 3, "解析失败应重试至多 2 次"
    row = job(owner, identity)
    assert row["stage"] == "failed" and row["follow_status"] == "AI评估失败"
    assert row["grade"] == "" and row["score"] is None
    assert row["screen_payload"]["parse_failed"] is True
    assert owner.post(PIPE + "/queue", json=identity).status_code == 409
    assert owner.get(PIPE + "/jobs?tab=failed").get_json()["total"] == 1
    assert owner.post(PIPE + "/retry", json=identity).get_json()["stage"] == "reeval"


def test_failure_triage_and_retry_limit(server, make_account):
    owner = setup_account(server, make_account, "pipeline-failure")
    identity = add_job(owner, "t:mass", JOB_MASS)
    run(owner, "clean")
    run(owner, "screen")
    run(owner, "greet")
    assert job(owner, identity)["stage"] == "queued"

    first = owner.post(PIPE + "/deliver_dry", json={"ids": [{**identity, "simulate": "transient"}]}).get_json()
    assert first["failed"] == 1
    row = job(owner, identity)
    assert row["stage"] == "queued" and row["failure_count"] == 1
    assert row["failure_payload"]["kind"] == "transient" and row["failure_payload"]["retryable"] is True

    second = owner.post(PIPE + "/deliver_dry", json={"ids": [{**identity, "simulate": "transient"}]}).get_json()
    assert second["results"][0]["failure"]["failure_count"] == 2
    row = job(owner, identity)
    assert row["stage"] == "failed" and row["follow_status"] == "投递失败"
    assert row["failure_payload"]["retryable"] is False

    assert owner.post(PIPE + "/retry", json=identity).get_json()["stage"] == "queued"
    persistent = owner.post(PIPE + "/deliver_dry", json={"ids": [{**identity, "simulate": "persistent"}]}).get_json()
    assert persistent["results"][0]["failure"]["kind"] == "persistent"
    row = job(owner, identity)
    assert row["stage"] == "failed" and row["failure_payload"]["retryable"] is False
    assert owner.post(PIPE + "/abandon", json=identity).get_json()["stage"] == "rejected"
    assert job(owner, identity)["follow_status"] == "已拒绝"


def test_delivery_lock_prevents_double_fire(server, make_account):
    owner = setup_account(server, make_account, "pipeline-lock")
    identity = add_job(owner, "t:mass", JOB_MASS)
    run(owner, "clean")
    run(owner, "screen")
    run(owner, "greet")
    from services import db
    with db._get_conn() as conn:
        conn.execute("UPDATE recruitment_pipeline SET delivery_lock=1 WHERE owner=? AND source=? AND url_key=?",
                     (owner.email, identity["source"], identity["url_key"]))
    body = owner.post(PIPE + "/deliver_dry", json={"ids": [identity]}).get_json()
    assert body["results"][0]["skipped"] is True and body["delivered"] == 0
    assert job(owner, identity)["stage"] == "queued"


def test_rewrite_requires_baseline_and_reject_flow(server, make_account):
    owner = make_account("pipeline-no-baseline")
    identity = add_job(owner, "t:custom", JOB_CUSTOM)
    run(owner, "clean")
    run(owner, "screen")
    run(owner, "deep")
    response = owner.post(PIPE + "/run", json={"stage": "rewrite"})
    assert response.status_code == 400 and "基准简历" in response.get_json()["message"]
    rail = owner.get(PIPE + "/rail").get_json()
    rewriting = next(step for step in rail["steps"] if step["key"] == "rewriting")
    assert rewriting["config_state"] == "required_missing" and "rewriting" in rail["warnings"]
    assert owner.post(PIPE + "/approve", json={**identity, "decision": "reject"}).get_json()["stage"] == "rejected"
    assert job(owner, identity)["follow_status"] == "已拒绝"


def test_stop_at_review_false_auto_delivers(server, make_account):
    owner = setup_account(server, make_account, "pipeline-auto")
    assert owner.post(PIPE + "/config", json={"stop_at_review": False}).status_code == 200
    identity = add_job(owner, "t:mass", JOB_MASS)
    run(owner, "clean")
    run(owner, "screen")
    result = run(owner, "greet")
    assert result["counts"]["delivered"] == 1
    assert job(owner, identity)["stage"] == "delivered"


def test_saved_view_and_bulk_purge(server, make_account):
    owner = setup_account(server, make_account, "pipeline-saved")
    keep = add_job(owner, "t:keep", JOB_CUSTOM)
    drop = add_job(owner, "t:drop", JOB_MASS)
    run(owner, "clean")
    assert owner.post(PIPE + "/save", json={**keep, "saved": "yes"}).status_code == 400
    assert owner.post(PIPE + "/save", json={"source": "city_jobs", "url_key": "t:none", "saved": True}).status_code == 404
    assert owner.post(PIPE + "/save", json={**keep, "saved": True}).get_json()["saved"] is True
    jobs = owner.get(PIPE + "/jobs?tab=all").get_json()
    assert jobs["counts"]["all"] == 1 and jobs["counts"]["saved"] == 1
    assert jobs["total"] == 1 and jobs["items"][0]["url_key"] == drop["url_key"]
    saved = owner.get(PIPE + "/jobs?tab=saved").get_json()
    assert saved["total"] == 1 and saved["items"][0]["url_key"] == keep["url_key"]
    assert saved["items"][0]["saved"] == 1 and saved["items"][0]["saved_at"] > 0
    # 已保存岗位继续流转，saved 视图标注当前阶段
    run(owner, "evaluate")
    saved = owner.get(PIPE + "/jobs?tab=saved").get_json()
    assert saved["items"][0]["stage"] in ("screened", "deep")
    assert owner.get(PIPE + "/jobs?tab=in_progress").get_json()["counts"]["saved"] == 1
    assert owner.post(PIPE + "/purge", json={}).status_code == 400
    other = add_job(owner, "t:other", JOB_MASS)
    body = owner.post(PIPE + "/purge", json={"all": False, "ids": [drop, keep]}).get_json()
    assert body["deleted"] == 1 and body["kept"] == 1
    assert owner.get(PIPE + "/job", query_string=other).status_code == 200
    body = owner.post(PIPE + "/purge", json={"all": True, "ids": [other]}).get_json()
    assert body["deleted"] == 0 and body["kept"] == 1
    body = owner.post(PIPE + "/purge", json={"all": True}).get_json()
    assert body["deleted"] == 1 and body["kept"] == 1
    assert owner.get(PIPE + "/jobs?tab=all").get_json()["total"] == 0
    assert owner.get(PIPE + "/job", query_string=drop).status_code == 404
    assert owner.get(PIPE + "/job", query_string=keep).status_code == 200
    from services import db
    with db._get_conn() as conn:
        for table in ("recruitment_pipeline", "recruitment_cleaning_results"):
            assert conn.execute(f"SELECT count(*) FROM {table} WHERE owner=? AND url_key=?",
                                (owner.email, drop["url_key"])).fetchone()[0] == 0
    assert owner.post(PIPE + "/save", json={**keep, "saved": False}).get_json()["saved"] is False
    back = owner.get(PIPE + "/jobs?tab=all").get_json()
    assert back["total"] == 1 and back["counts"]["saved"] == 0


def test_daily_cleanup_keeps_only_saved_jobs(server, make_account):
    from services import db, recruitment_pipeline as pipeline

    owner = make_account("pipeline-day")
    keep = add_job(owner, "t:keep", JOB_CUSTOM)
    old = add_job(owner, "t:old", JOB_MASS)
    assert owner.post(PIPE + "/save", json={**keep, "saved": True}).status_code == 200
    yesterday = pipeline.board_day_start() - 1
    with db._get_conn() as conn:
        conn.execute("UPDATE recruitment_listings SET updated_at=? WHERE owner=?", (yesterday, owner.email))
    assert owner.get(PIPE + "/funnel").get_json()["stages"][0]["count"] == 1
    jobs = owner.get(PIPE + "/jobs?tab=all").get_json()
    assert jobs["counts"]["all"] == 0 and jobs["counts"]["saved"] == 1
    assert owner.get(PIPE + "/job", query_string=old).status_code == 404
    saved = owner.get(PIPE + "/jobs?tab=saved").get_json()
    assert saved["total"] == 1 and saved["items"][0]["url_key"] == keep["url_key"]
    # 当天新获取的岗位不受跨天清理影响
    add_job(owner, "t:fresh", JOB_MASS)
    jobs = owner.get(PIPE + "/jobs?tab=all").get_json()
    assert jobs["counts"]["all"] == 1 and jobs["counts"]["saved"] == 1
    assert owner.post(PIPE + "/save", json={**keep, "saved": False}).get_json()["expired"] is True
    assert owner.get(PIPE + "/job", query_string=keep).status_code == 404
    assert owner.get(PIPE + "/jobs?tab=all").get_json()["total"] == 1


STUDENT_RESUME = """求职意向：Python/AI 应用开发（后端/Agent/AIGC 方向）
教育经历
华东某大学 计算机科学与技术 本科 2026 应届
项目经历
校园智能问答 Agent 2024-2025
使用 Python、Flask、MySQL、Redis 搭建后端服务，接入大模型 API 实现 RAG 检索问答。
负责 Docker 部署与 Linux 日常运维，编写 Pytest 自动化测试，熟悉 Git 协作。
技能清单：Python、Flask、MySQL、Redis、Docker、Linux、Git、RAG、LLM、Prompt 工程
期望薪资：8k
"""


def test_heuristic_matches_data_fixture_if_present(server, make_account):
    fixture = Path(__file__).parent / "fixtures" / "pipeline_sample.json"
    if not fixture.exists():
        pytest.skip("DATA agent fixture 尚未产出")
    from services.recruitment_pipeline import DEFAULT_WEIGHTS, GRADE_RANK, heuristic_screen
    data = json.loads(fixture.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    if not samples:
        pytest.skip("fixture 中没有样本")
    owner = make_account("pipeline-fixture")
    baseline = set_baseline(server, owner, text=STUDENT_RESUME, fingerprint="fp-student")
    assert owner.post(PIPE + "/config", json={"baseline_resume_id": baseline}).status_code == 200
    rules = {"semantic_excluded": ["外包", "驻场", "单休", "兼职", "销售"]}
    assert owner.post(API + "/cleaning/save", json={"profile": "general", "rules": rules}).status_code == 200
    identities = {}
    for sample in samples:
        source_row = sample["input"]
        spec = {"title": source_row.get("岗位名称", ""), "company": source_row.get("公司名称", ""),
                "location": source_row.get("城市", ""), "salary": source_row.get("薪资", ""),
                "experience": source_row.get("经验要求", ""), "education": source_row.get("学历要求", ""),
                "description": source_row.get("岗位描述", ""),
                "meta": {"skills": source_row.get("技能要求", ""), "company_size": source_row.get("公司规模", ""),
                         "funding": source_row.get("融资阶段", ""), "industry": source_row.get("公司行业", ""),
                         "category": source_row.get("职位类别", ""), "collected_city": source_row.get("采集城市", "")}}
        identities[sample["id"]] = add_job(owner, f"fixture:{sample['id']}", spec)
    run(owner, "clean", limit=2000)
    run(owner, "screen", limit=2000)
    for sample in samples:
        row = job(owner, identities[sample["id"]])
        expected_verdict = sample["expected_semantic"]["verdict"]
        assert row["cleaning_status"] == expected_verdict, (
            f"{sample['id']}: 启发式 verdict {row['cleaning_status']} != fixture {expected_verdict}"
            f"（{row.get('cleaning_reason') or ''}）")
        expected_grade = sample["expected_deep"]["grade"]
        if expected_verdict == "rejected":
            assert row["stage"] == "rejected", f"{sample['id']}: rejected 样本应被清洗淘汰（fixture 强制 D 级）"
            continue
        if expected_verdict == "review":
            fields = {key: str(sample["input"].get(label) or "") for key, label in
                      (("title", "岗位名称"), ("company", "公司名称"), ("location", "城市"), ("salary", "薪资"),
                       ("experience", "经验要求"), ("education", "学历要求"), ("description", "岗位描述"))}
            result = heuristic_screen(fields, row["meta"], STUDENT_RESUME, DEFAULT_WEIGHTS)
            actual_grade = result["grade"]
        else:
            actual_grade = row["grade"]
        assert abs(GRADE_RANK[actual_grade] - GRADE_RANK[expected_grade]) <= 1, (
            f"{sample['id']}: 启发式 {actual_grade} 与 fixture {expected_grade} 偏差超过 1 级")
