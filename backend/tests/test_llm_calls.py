"""大模型调用共用函数：JSON 解析与修复、瞬态错误重试、结构化输出的三级兜底。"""
from types import SimpleNamespace

import pytest

from services import llm_calls


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeCompletions:
    """按顺序返回脚本里的结果；Exception 实例会被抛出。"""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return reply(item)


class FakeClient:
    def __init__(self, script):
        self.completions = FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_calls.time, "sleep", lambda seconds: None)


@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('说明文字\n```json\n{"a": [1, 2]}\n```\n结尾', {"a": [1, 2]}),
    ('前缀 {"a": 1, "b": [1, 2,],} 后缀', {"a": 1, "b": [1, 2]}),
])
def test_parse_structured_json_accepts_common_model_output(raw, expected):
    assert llm_calls.parse_structured_json(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "没有任何 JSON"])
def test_parse_structured_json_rejects_unusable_output(raw):
    with pytest.raises(ValueError):
        llm_calls.parse_structured_json(raw)


@pytest.mark.parametrize("url,expected", [
    ("https://api.example.com", "https://api.example.com/v1"),
    ("https://api.example.com/", "https://api.example.com/v1"),
    ("https://api.example.com/v1", "https://api.example.com/v1"),
    ("https://api.example.com/v1/chat/completions", "https://api.example.com/v1"),
])
def test_normalize_sdk_base_url(url, expected):
    assert llm_calls.normalize_sdk_base_url(url) == expected


@pytest.mark.parametrize("url", ["", "api.example.com", "/v1"])
def test_normalize_sdk_base_url_requires_full_address(url):
    with pytest.raises(ValueError):
        llm_calls.normalize_sdk_base_url(url)


@pytest.mark.parametrize("message,transient", [
    ("Connection reset by peer", True), ("Error 503 Service Unavailable", True), ("429 too many requests", True),
    ("invalid api key", False), ("model not found", False),
])
def test_is_transient_error(message, transient):
    assert llm_calls.is_transient_error(RuntimeError(message)) is transient


def test_safe_create_retries_transient_errors_then_succeeds():
    client = FakeClient([RuntimeError("connection timeout"), RuntimeError("503"), "ok"])
    response = llm_calls.safe_create_chat_completion(client, "m", [], 0.1, 100)
    assert response.choices[0].message.content == "ok"
    assert len(client.completions.calls) == 3


def test_safe_create_raises_immediately_on_non_transient_errors():
    client = FakeClient([RuntimeError("invalid api key"), "never reached"])
    with pytest.raises(RuntimeError, match="invalid api key"):
        llm_calls.safe_create_chat_completion(client, "m", [], 0.1, 100)
    assert len(client.completions.calls) == 1


def test_safe_create_gives_up_after_max_retries():
    client = FakeClient([RuntimeError("timeout")] * 3)
    with pytest.raises(RuntimeError, match="timeout"):
        llm_calls.safe_create_chat_completion(client, "m", [], 0.1, 100, max_retries=2)
    assert len(client.completions.calls) == 3


def test_safe_create_drops_response_format_when_unsupported():
    client = FakeClient([RuntimeError("response_format json_object is not supported"), '{"a":1}'])
    response = llm_calls.safe_create_chat_completion(client, "m", [], 0.1, 100, force_json=True)
    assert response.choices[0].message.content == '{"a":1}'
    assert "response_format" in client.completions.calls[0]
    assert "response_format" not in client.completions.calls[1]


@pytest.fixture()
def fake_openai(monkeypatch):
    def factory(script):
        client = FakeClient(script)
        monkeypatch.setattr(llm_calls, "OpenAI", lambda **kwargs: client)
        return client

    return factory


def test_call_structured_chat_returns_parsed_json(fake_openai):
    client = fake_openai(['{"answer": 42}'])
    result = llm_calls.call_structured_chat("https://x.test", "key", "m", [{"role": "user", "content": "hi"}], "系统提示")
    assert result == {"answer": 42}
    assert client.completions.calls[0]["messages"][0] == {"role": "system", "content": "系统提示"}
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_call_structured_chat_repairs_invalid_json_with_a_second_call(fake_openai):
    client = fake_openai(["这不是 JSON", '{"fixed": true}'])
    assert llm_calls.call_structured_chat("https://x.test", "key", "m", [], "sys") == {"fixed": True}
    assert len(client.completions.calls) == 2
    assert "JSON 修复器" in client.completions.calls[1]["messages"][0]["content"]


def test_call_structured_chat_regenerates_when_repair_also_fails(fake_openai):
    client = fake_openai(["坏的", "还是坏的", '{"third": 1}'])
    assert llm_calls.call_structured_chat("https://x.test", "key", "m", [], "sys") == {"third": 1}
    assert "严格要求" in client.completions.calls[2]["messages"][0]["content"]


def test_call_structured_chat_reports_failure_after_all_attempts(fake_openai):
    fake_openai(["坏", "坏", "坏"])
    with pytest.raises(ValueError, match="结构化 JSON 解析失败"):
        llm_calls.call_structured_chat("https://x.test", "key", "m", [], "sys")


def test_call_structured_chat_wraps_api_errors(fake_openai):
    fake_openai([RuntimeError("invalid api key")])
    with pytest.raises(ValueError, match="LLM 接口调用失败"):
        llm_calls.call_structured_chat("https://x.test", "key", "m", [], "sys")


def test_call_structured_chat_rejects_empty_reply(fake_openai):
    fake_openai([""])
    with pytest.raises(ValueError, match="没有返回可解析内容"):
        llm_calls.call_structured_chat("https://x.test", "key", "m", [], "sys")


def test_call_markdown_chat_prepends_system_prompt(fake_openai):
    client = fake_openai(["## 标题\n正文"])
    text = llm_calls.call_markdown_chat("https://x.test", "key", "m", [{"role": "user", "content": "写点东西"}], system_prompt="你是编辑")
    assert text == "## 标题\n正文"
    assert client.completions.calls[0]["messages"][0]["role"] == "system"
    assert "response_format" not in client.completions.calls[0]
