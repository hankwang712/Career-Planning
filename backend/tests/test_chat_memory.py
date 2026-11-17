"""三层记忆：① 已确认的长期记忆 ② 会话笔记/摘要 ③ 参考聊天记录（背景摘要）。

模型用脚本替身，后台任务通过 run_once 手动推进，保证测试确定、离线、不起线程。
"""
import json
from types import SimpleNamespace

import pytest

from services.chat import history
from services.chat.extraction import EXTRACTION_PROMPT, NOTE_PROMPT, merge_note, render_note, validate_candidates
from services.chat.history import DIGEST_PROMPT, choose_fallback, needs_history, title_terms
from services.chat.service import ChatService

OWNER = "memory-user"
RUNTIME = ("https://llm.test/v1", "key", "test-model")
INTRO = "我是上海交通大学软件工程专业的本科生，只考虑上海的后端岗位。"


class FakeStream(list):
    def close(self):
        pass


class ScriptedModel:
    """聊天回复走流式；后台记忆任务按系统提示分派到对应的处理函数。"""

    def __init__(self):
        self.handlers, self.calls = {}, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            delta = SimpleNamespace(content="好的，我记下了。")
            return FakeStream([SimpleNamespace(choices=[SimpleNamespace(delta=delta)])])
        system, payload = kwargs["messages"][0]["content"], json.loads(kwargs["messages"][1]["content"])
        output = self.handlers[system](payload)
        message = SimpleNamespace(content=json.dumps(output, ensure_ascii=False), refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(total_tokens=100))

    def close(self):
        pass


def user_message(payload, text=None):
    return next(row for row in payload["messages"] if row["role"] == "user" and (text is None or text in row["content"]))


def extraction(payload):
    message = user_message(payload, "上海交通大学")
    evidence = lambda quote: [{"message_id": message["id"], "quote": quote}]
    return {"memories": [
        {"kind": "fact", "key": "school", "subject": "profile", "value": "上海交通大学", "operation": "assert",
         "evidence": evidence("上海交通大学"), "confidence": 0.95, "scope": "user"},
        {"kind": "fact", "key": "major", "subject": "profile", "value": "软件工程", "operation": "assert",
         "evidence": evidence("软件工程"), "confidence": 0.95, "scope": "user"},
        {"kind": "preference", "key": "target_city", "subject": "profile", "value": "上海", "operation": "assert",
         "evidence": evidence("只考虑上海"), "confidence": 0.9, "scope": "user"},
    ]}


def note(payload):
    return {"title": "后端岗位方向", "gist": "确定只看上海的后端岗位", "goal": "找到上海的后端实习",
            "decisions": ["只考虑上海"], "corrections": [], "open_questions": [], "advice": []}


@pytest.fixture()
def model():
    scripted = ScriptedModel()
    scripted.handlers = {EXTRACTION_PROMPT: extraction, NOTE_PROMPT: note,
                         DIGEST_PROMPT: lambda payload: {"goals": "目标：上海的后端岗位", "focus": "准备后端面试"}}
    return scripted


@pytest.fixture()
def service(tmp_path, model):
    chat = ChatService(tmp_path, lambda selection: RUNTIME, lambda owner: {}, client_factory=lambda runtime: model)
    chat.memory.start = lambda: None  # 不启动后台线程，由测试手动推进
    return chat


def talk(service, session_id, request_id, text):
    turn = service.store.begin_turn(OWNER, session_id, request_id, text, {})
    events = list(service.stream(OWNER, session_id, request_id, turn["token"], text, RUNTIME))
    assert events[-1]["type"] == "done", events
    return events


def settle(service, lane="urgent"):
    """跑完该通道里所有到期任务。"""
    guard = 0
    while service.memory.run_once(lane):
        guard += 1
        assert guard < 20, "后台任务没有收敛"


def supplied(service, session_id, query):
    """聊天真正发给模型的"用户背景 JSON"。"""
    system = service.context(OWNER, session_id, query)[0]["content"]
    return json.loads(system.split("用户背景 JSON：\n", 1)[1])


def learn(service, request_id="r1", text=INTRO, incognito=False):
    session = service.store.create_session(OWNER, incognito=incognito)
    talk(service, session["id"], request_id, text)
    service.store.enqueue(OWNER, session["id"], immediate=True)
    settle(service)
    return session


# ---------- ① 长期记忆 ----------

def test_saved_memories_are_extracted_and_reach_the_next_conversation(service):
    learn(service)
    _, rows = service.store.memory_snapshot(OWNER)
    saved = {row["key"]: row["value"] for row in rows}
    assert saved == {"school": "上海交通大学", "major": "软件工程", "target_city": "上海"}
    assert all(row["status"] == "active" for row in rows)

    other = service.store.create_session(OWNER)
    context = supplied(service, other["id"], "帮我看看简历")
    assert {row["key"] for row in context["memories"]} == {"school", "major", "target_city"}
    assert all("updated_days_ago" in row for row in context["memories"])


def test_every_saved_memory_keeps_verbatim_evidence(service):
    learn(service)
    _, rows = service.store.memory_snapshot(OWNER)
    for row in rows:
        quotes = [item["quote"] for item in json.loads(row["evidence"])]
        assert quotes and all(quote in INTRO for quote in quotes)


def test_incognito_conversations_create_no_long_term_memory(service):
    learn(service, incognito=True)
    assert service.store.memory_snapshot(OWNER)[1] == []


def test_turning_saved_memory_off_stops_extraction_and_hides_existing_memories(service):
    learn(service)
    service.store.set_features(OWNER, saved_enabled=False, history_enabled=True)
    fresh = service.store.create_session(OWNER)
    assert supplied(service, fresh["id"], "你好")["memories"] == []
    assert service.memory.career_context(OWNER) == {"preferences": "", "evidence": ""}

    later = service.store.create_session(OWNER)
    talk(service, later["id"], "r2", "我的学校是复旦大学，请记住。")
    service.store.enqueue(OWNER, later["id"], immediate=True)
    settle(service)
    service.store.set_features(OWNER, saved_enabled=True, history_enabled=True)
    assert {row["value"] for row in service.store.memory_snapshot(OWNER)[1]} == {"上海交通大学", "软件工程", "上海"}


def test_report_agents_get_confirmed_facts_and_preferences_only(service):
    learn(service)
    career = service.memory.career_context(OWNER)
    assert career["preferences"] == "上海"
    assert set(career["evidence"].splitlines()) == {"上海交通大学", "软件工程"}


def test_forgotten_memories_leave_the_context(service):
    learn(service)
    school = next(row for row in service.store.memory_snapshot(OWNER)[1] if row["key"] == "school")
    service.store.request_memory_deletion(OWNER, school["id"], mode="forget")
    settle(service)
    keys = {row["key"] for row in service.store.memory_snapshot(OWNER)[1]}
    assert "school" not in keys and {"major", "target_city"} <= keys
    fresh = service.store.create_session(OWNER)
    assert "school" not in {row["key"] for row in supplied(service, fresh["id"], "你好")["memories"]}


def test_memories_are_private_to_their_owner(service):
    learn(service)
    assert service.store.memory_snapshot("someone-else") == (0, [])
    assert service.memory.career_context("someone-else") == {"preferences": "", "evidence": ""}


# ---------- 候选记忆校验：宁可不记，也不能记错 ----------

def messages(*texts):
    return [{"id": f"m{i}", "role": "user", "content": text} for i, text in enumerate(texts)]


def candidate(message_id="m0", quote="上海交通大学", value="上海交通大学", key="school", kind="fact",
              confidence=0.95, operation="assert", scope="user"):
    return {"kind": kind, "key": key, "subject": "profile", "value": value, "operation": operation,
            "evidence": [{"message_id": message_id, "quote": quote}], "confidence": confidence, "scope": scope}


def test_grounded_candidates_are_accepted():
    result = validate_candidates({"memories": [candidate()]}, messages("我在上海交通大学读书"))
    assert [(row["key"], row["value"]) for row in result] == [("school", "上海交通大学")]


def test_invented_quotes_fail_the_whole_batch():
    with pytest.raises(ValueError):
        validate_candidates({"memories": [candidate(quote="清华大学", value="清华大学")]}, messages("我在上海交通大学读书"))


def test_quotes_must_come_from_user_messages_that_exist():
    with pytest.raises(ValueError):
        validate_candidates({"memories": [candidate(message_id="nope")]}, messages("我在上海交通大学读书"))


@pytest.mark.parametrize("text", [
    "如果我是上海交通大学的学生会怎样", "假设我在上海交通大学读书", "他说他在上海交通大学读书", "上海交通大学怎么样？",
])
def test_hypotheticals_and_questions_are_not_stored(text):
    assert validate_candidates({"memories": [candidate()]}, messages(text)) == []


def test_low_confidence_and_session_scoped_candidates_are_dropped():
    source = messages("我在上海交通大学读书")
    assert validate_candidates({"memories": [candidate(confidence=0.5)]}, source) == []
    assert validate_candidates({"memories": [candidate(scope="session")]}, source) == []


def test_attributes_outside_the_basic_profile_are_ignored():
    source = messages("我擅长 Python 和 Django")
    skill = candidate(quote="Python", value="Python", key="skill")
    assert validate_candidates({"memories": [skill]}, source) == []


def test_relative_dates_are_not_stored_as_graduation_time():
    source = messages("我明年毕业")
    assert validate_candidates({"memories": [candidate(quote="明年毕业", value="明年毕业", key="graduation")]}, source) == []
    absolute = candidate(quote="2027年6月毕业", value="2027-06", key="graduation")
    assert validate_candidates({"memories": [absolute]}, messages("我2027年6月毕业"))[0]["value"] == "2027-06"


def test_duplicate_slots_in_one_batch_are_rejected():
    with pytest.raises(ValueError):
        validate_candidates({"memories": [candidate(), candidate()]}, messages("我在上海交通大学读书"))


def test_correction_without_correction_wording_is_downgraded_to_assert():
    result = validate_candidates({"memories": [candidate(operation="correct")]}, messages("我在上海交通大学读书"))
    assert result[0]["operation"] == "assert"
    spoken = messages("记错了，其实我在上海交通大学读书")
    assert validate_candidates({"memories": [candidate(quote="其实我在上海交通大学", operation="correct")]}, spoken)[0]["operation"] == "correct"


@pytest.mark.parametrize("bad", [None, [], {"memories": "x"}, {"memories": [{}] * 21}])
def test_malformed_model_output_is_rejected(bad):
    with pytest.raises(Exception):
        validate_candidates(bad, messages("x"))


# ---------- ② 会话笔记 ----------

def test_session_note_summarises_and_replaces_covered_messages(service):
    session = service.store.create_session(OWNER)
    talk(service, session["id"], "r1", INTRO)
    before = service.context(OWNER, session["id"], "继续")
    assert before[0]["content"] and [m["role"] for m in before[1:]] == ["user", "assistant"]

    service.store.enqueue(OWNER, session["id"], immediate=True)
    settle(service)
    stored = service.store.session(OWNER, session["id"])
    assert stored["summary"] and "只考虑上海" in stored["summary"]
    assert stored["note_title"] == "后端岗位方向"
    after = service.context(OWNER, session["id"], "继续")
    # 已被笔记覆盖的消息不再原样发送；笔记作为"conversation_summary"进入上下文
    assert [m for m in after[1:] if m["role"] != "system"] == []
    assert supplied(service, session["id"], "继续")["conversation_summary"] == stored["summary"]


def test_new_messages_after_a_note_stay_in_the_recent_window(service):
    session = service.store.create_session(OWNER)
    talk(service, session["id"], "r1", INTRO)
    service.store.enqueue(OWNER, session["id"], immediate=True)
    settle(service)
    talk(service, session["id"], "r2", "那我下一步该做什么？")
    recent = [m["content"] for m in service.context(OWNER, session["id"], "继续")[1:]]
    assert recent[0] == "那我下一步该做什么？" and len(recent) == 2


def test_note_merging_clamps_oversized_sections_and_dedupes():
    merged = merge_note({"title": "标" * 200, "gist": "概" * 400, "goal": "目标",
                         "decisions": [f"决定{i}" * 30 for i in range(20)]}, {})
    assert len(merged["title"]) == 24 and len(merged["gist"]) == 60
    assert len(merged["notes"]["decisions"]) == 5
    assert all(len(item) <= 100 for item in merged["notes"]["decisions"])
    assert "已确认的决定" in merged["summary"]
    assert merged["summary"] == render_note(merged["notes"])
    duplicated = merge_note({"title": "t", "gist": "g", "decisions": ["同一个决定"] * 5}, {})
    assert duplicated["notes"]["decisions"] == ["同一个决定"]


# ---------- ③ 参考聊天记录 ----------

def test_reference_history_is_used_only_when_the_question_points_to_the_past(service):
    learn(service)
    settle(service, "bulk")  # 重建用户级背景摘要
    digest = service.store.digest(OWNER)
    assert digest["summary"] and digest["topics"]

    fresh = service.store.create_session(OWNER)
    relevant = supplied(service, fresh["id"], "上次我们聊过的后端岗位方向，继续")
    block = relevant["参考聊天记录（仅供参考，不是用户确认的事实）"]
    assert "上海的后端岗位" in block["背景摘要"]
    assert block["相关旧会话笔记"][0]["title"] == "后端岗位方向"
    assert "参考聊天记录（仅供参考，不是用户确认的事实）" not in supplied(service, fresh["id"], "今天天气怎么样")


def test_reference_history_can_be_switched_off(service):
    learn(service)
    settle(service, "bulk")
    service.store.set_features(OWNER, saved_enabled=True, history_enabled=False)
    fresh = service.store.create_session(OWNER)
    assert "参考聊天记录（仅供参考，不是用户确认的事实）" not in supplied(service, fresh["id"], "上次我们聊过什么")


def test_incognito_notes_never_enter_the_shared_digest(service):
    learn(service, incognito=True)
    settle(service, "bulk")
    digest = service.store.digest(OWNER)
    assert digest["summary"] == "" and digest["topics"] == []


def test_history_is_private_to_each_owner(service):
    learn(service)
    settle(service, "bulk")
    assert service.store.digest("someone-else")["summary"] == ""


@pytest.mark.parametrize("query", ["上次聊的那个继续", "还记得我之前说的吗", "我们聊过简历"])
def test_cue_words_trigger_history(query):
    assert needs_history(query, []) == "cue"


def test_topic_titles_trigger_history_but_generic_career_words_do_not():
    topics = [{"title": "前端框架选择"}, {"title": "职业规划"}]
    assert needs_history("React 和前端框架怎么比", topics) == "topic"
    assert needs_history("帮我做一下职业规划", topics) == ""
    assert needs_history("今天吃什么", topics) == ""


def test_title_terms_skip_generic_words():
    assert "职业规划" not in title_terms("职业规划")
    assert title_terms("Python 后端岗位") >= {"python"}


def test_fallback_selection_prefers_matching_titles_then_recency():
    rows = [{"id": "a", "note_title": "简历修改", "note_gist": "", "updated_at": 1},
            {"id": "b", "note_title": "前端框架选择", "note_gist": "比较 React", "updated_at": 2},
            {"id": "c", "note_title": "实习面试", "note_gist": "", "updated_at": 3},
            {"id": "d", "note_title": "城市选择", "note_gist": "", "updated_at": 4}]
    assert choose_fallback("前端框架怎么选", rows)[0] == "b"
    assert len(choose_fallback("无关问题", rows)) == history.MAX_NOTES
