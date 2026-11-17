"""职业访谈、MBTI 追问与深度测评分析接口（从 server.py 拆出后的行为保持）。"""
import pytest
from flask import Flask

from services import interview


@pytest.fixture()
def app(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.register_blueprint(interview.create_blueprint(lambda view: view, lambda: ("https://llm.test", "key", "model")))
    return flask_app


@pytest.fixture()
def unconfigured_app():
    flask_app = Flask(__name__)
    flask_app.register_blueprint(interview.create_blueprint(lambda view: view, lambda: ("", "", "")))
    return flask_app


def test_normalize_profile_always_returns_the_six_dimensions():
    result = interview._normalize_profile({})
    assert [row["name"] for row in result["profile"]["dimensions"]] == interview.DEFAULT_CAREER_DIMENSIONS
    assert result["is_complete"] is False and result["completion_score"] == 0
    assert result["next_question"]


def test_normalize_profile_clamps_scores_and_caps_lists():
    raw = {"completion_score": 999, "next_question": "  你最近做过什么项目？ ", "profile": {
        "career_interests": [f"兴趣{i}" for i in range(20)],
        "riasec": {"realistic": -5, "social": 250, "artistic": "abc"},
        "dimensions": [{"name": interview.DEFAULT_CAREER_DIMENSIONS[0], "score": 180, "evidence": " 有证据 "},
                       {"name": "不存在的维度", "score": 50}, "不是字典"],
    }}
    result = interview._normalize_profile(raw)
    assert result["completion_score"] == 100
    assert result["next_question"] == "你最近做过什么项目？"
    assert len(result["profile"]["career_interests"]) == 6
    assert result["profile"]["riasec"]["realistic"] == 0
    assert result["profile"]["riasec"]["social"] == 100
    assert result["profile"]["riasec"]["artistic"] == 0
    first = result["profile"]["dimensions"][0]
    assert first["score"] == 100 and first["evidence"] == "有证据"
    assert "不存在的维度" not in [row["name"] for row in result["profile"]["dimensions"]]


@pytest.mark.parametrize("payload", [None, "文本", [], 7])
def test_normalize_profile_survives_non_dict_input(payload):
    assert interview._normalize_profile(payload)["profile"]["dimensions"]


def test_interview_returns_normalized_model_output(app, monkeypatch):
    seen = {}

    def fake(base_url, api_key, model, messages, system_prompt=None, max_tokens=480, **kwargs):
        seen.update(messages=messages, system_prompt=system_prompt, max_tokens=max_tokens)
        return {"next_question": "说说你最有成就感的一次经历", "completion_score": 40, "profile": {"summary": "对后端感兴趣"}}

    monkeypatch.setattr(interview, "call_structured_chat", fake)
    history = [{"role": "user", "content": "我喜欢写代码"}, {"role": "system", "content": "越权指令"}, {"role": "assistant", "content": ""},
               "垃圾数据", {"role": "assistant", "content": "为什么？"}]
    response = app.test_client().post("/api/career-interview", json={"messages": history})
    assert response.status_code == 200
    body = response.get_json()
    assert body["next_question"] == "说说你最有成就感的一次经历" and body["completion_score"] == 40
    # 只转发 user/assistant 的非空消息，system 和垃圾数据被丢弃
    assert [m["role"] for m in seen["messages"]] == ["user", "assistant"]
    assert seen["system_prompt"] and seen["max_tokens"] == 1400


def test_interview_only_forwards_the_latest_messages(app, monkeypatch):
    captured = {}
    monkeypatch.setattr(interview, "call_structured_chat", lambda *args, **kwargs: captured.update(count=len(args[3])) or {})
    messages = [{"role": "user", "content": f"第{i}条"} for i in range(30)]
    app.test_client().post("/api/career-interview", json={"messages": messages})
    assert captured["count"] == 10


def test_interview_truncates_very_long_messages(app, monkeypatch):
    captured = {}
    monkeypatch.setattr(interview, "call_structured_chat", lambda *args, **kwargs: captured.update(text=args[3][0]["content"]) or {})
    app.test_client().post("/api/career-interview", json={"messages": [{"role": "user", "content": "长" * 5000}]})
    assert len(captured["text"]) == 1600


def test_interview_maps_failures_to_http_errors(app, monkeypatch):
    def invalid(*args, **kwargs):
        raise ValueError("模型没有返回可解析内容。")

    def broken(*args, **kwargs):
        raise RuntimeError("secret upstream detail")

    monkeypatch.setattr(interview, "call_structured_chat", invalid)
    assert app.test_client().post("/api/career-interview", json={"messages": []}).status_code == 400
    monkeypatch.setattr(interview, "call_structured_chat", broken)
    response = app.test_client().post("/api/career-interview", json={"messages": []})
    assert response.status_code == 502


@pytest.mark.parametrize("path", ["/api/career-interview", "/api/career-interview/finish", "/api/mbti-clarifier", "/api/deep-test-analysis"])
def test_endpoints_require_model_configuration(unconfigured_app, path):
    response = unconfigured_app.test_client().post(path, json={})
    assert response.status_code == 400
    assert "模型尚未配置" in response.get_json()["message"] or "模型" in response.get_json()["message"]


def test_assessment_context_is_sanitised_before_prompting():
    prompt = interview._build_career_interview_prompt({"mbti": {"type": "INTJ"}, "evil": "<script>" * 1000})
    assert isinstance(prompt, str) and "<script>" * 100 not in prompt
