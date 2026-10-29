"""Offline assistant regression checks using temporary databases and a fake model.

Run: python backend/scripts/check_chat.py
"""

from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, session
from services.chat import create_blueprint
from services.chat.memory import validate_analysis
from services.chat.storage import ChatError, ChatStore


class FakeStream:
    def __iter__(self):
        for text in ("先给结论：", "可以从你的项目经历开始。"):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    def close(self):
        pass


class FakeClient:
    def __init__(self, calls):
        self.calls = calls
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return FakeStream()
        content = json.dumps({"summary": "用户讨论职业计划，助手建议从项目经历开始。", "memories": []})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    def close(self):
        pass


class ChatChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))
        self.app.secret_key = "offline-test-key"
        self.app.testing = True
        self.runtime = ("https://offline.invalid/v1", "not-a-real-key", "fake-model")
        self.calls = []
        self.bp = create_blueprint(directory=self.temp.name,
            current_user=lambda: {"username": session["user"], "display_name": "测试用户"} if session.get("user") else None,
            login_required=lambda view: view,
            runtime_provider=lambda selection: self.runtime,
            profile_provider=lambda owner: {"用户背景": owner + "的职业画像"})
        self.app.register_blueprint(self.bp)
        self.service = self.bp.chat_service
        self.service.start_worker = lambda: None
        self.service.cache.retry_at = float("inf")
        self.service.vector.retry_at = float("inf")
        self.service.client_factory = lambda runtime: FakeClient(self.calls)
        self.client = self.app.test_client()
        self.login("alice")

    def login(self, owner):
        with self.client.session_transaction() as state:
            state.clear()
            if owner:
                state["user"] = owner
                state["csrf_token"] = "test-csrf"

    def api(self, method, path, data=None):
        return self.client.open(path, method=method, json=data,
            headers={"X-CSRF-Token": "test-csrf"})

    def create(self):
        response = self.api("POST", "/api/chat/sessions", {})
        self.assertEqual(response.status_code, 201)
        return response.json["id"]

    def send(self, sid, content="我希望去杭州工作。", request_id=None):
        request_id = request_id or str(uuid4())
        response = self.api("POST", f"/api/chat/sessions/{sid}/messages", {"content": content, "request_id": request_id})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        return request_id

    def batch(self, sid, value="杭州", kind="preference", key="target_city", operation="assert"):
        self.service.store.enqueue("alice", sid, immediate=True)
        job = self.service.store.claim_job()
        self.assertIsNotNone(job)
        messages = self.service.store.analysis_messages(job)
        user = next(row for row in messages if row["role"] == "user")
        raw = {"summary": "讨论职业偏好。", "memories": [{"kind": kind, "key": key, "subject": "profile", "value": value,
            "operation": operation, "evidence": [{"message_id": user["id"], "quote": user["content"]}], "confidence": .99, "scope": "user"}]}
        return job, messages, validate_analysis(raw, messages)

    def test_auth_csrf_and_page(self):
        self.assertEqual(self.client.post("/api/chat/sessions", json={}).status_code, 403)
        self.assertEqual(self.client.get("/assistant.html").status_code, 200)
        self.login(None)
        self.assertEqual(self.client.get("/api/chat/sessions").status_code, 401)
        self.assertEqual(self.client.get("/assistant.html").status_code, 302)

    def test_session_crud_and_owner_isolation(self):
        sid = self.create()
        self.assertEqual(self.api("PATCH", f"/api/chat/sessions/{sid}", {"title": "面试准备"}).status_code, 200)
        self.assertEqual(self.client.get("/api/chat/sessions").json["items"][0]["title"], "面试准备")
        self.login("bob")
        self.assertEqual(self.client.get("/api/chat/sessions").json["items"], [])
        for method, suffix, data in (("GET", "/messages", None), ("DELETE", "", None), ("PATCH", "", {"title": "盗用"}), ("POST", "/finish", {})):
            self.assertEqual(self.api(method, f"/api/chat/sessions/{sid}{suffix}", data).status_code, 404)
        self.login("alice")
        self.assertEqual(self.api("DELETE", f"/api/chat/sessions/{sid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/chat/sessions/{sid}/messages").status_code, 404)

    def test_stream_replay_and_independent_context(self):
        first, second = self.create(), self.create()
        request_id = self.send(first, "只在第一个窗口讨论的独特内容。")
        self.send(second, "第二个窗口的问题。")
        prompt = json.dumps(self.calls[-1]["messages"], ensure_ascii=False)
        self.assertNotIn("独特内容", prompt)
        self.assertIn("alice的职业画像", prompt)
        before = len(self.calls)
        self.send(first, "只在第一个窗口讨论的独特内容。", request_id)
        self.assertEqual(len(self.calls), before)
        self.assertEqual(len(self.client.get(f"/api/chat/sessions/{first}/messages").json["items"]), 2)
        self.assertEqual(self.api("POST", f"/api/chat/sessions/{first}/messages", {"content": "不同内容", "request_id": request_id}).status_code, 409)

    def test_stream_disconnect_and_retry(self):
        sid, request_id = self.create(), str(uuid4())
        response = self.client.post(f"/api/chat/sessions/{sid}/messages", json={"content": "准备面试", "request_id": request_id},
                                    headers={"X-CSRF-Token": "test-csrf"}, buffered=False)
        next(iter(response.response))
        response.close()
        self.assertEqual(self.service.store.session("alice", sid)["sending_until"], 0)
        self.send(sid, "准备面试", request_id)
        self.assertEqual(len(self.service.store.messages("alice", sid)["items"]), 2)

    def test_same_session_lock_and_different_session_parallel(self):
        first, second = self.create(), self.create()
        self.service.store.begin_turn("alice", first, str(uuid4()), "一个问题", {})
        with self.assertRaises(ChatError):
            self.service.store.begin_turn("alice", first, str(uuid4()), "另一个问题", {})
        self.service.store.begin_turn("alice", second, str(uuid4()), "独立的问题", {})

    def test_memory_sharing_and_forgetting(self):
        first, second = self.create(), self.create()
        self.send(first)
        job, messages, result = self.batch(first)
        self.assertTrue(self.service.store.apply_analysis(job, messages, result, 0))
        prompt = self.service.context("alice", second, "我适合什么城市？")[0]["content"]
        self.assertIn('"value": "杭州"', prompt)
        self.assertNotIn("杭州", self.service.context("bob", self.service.store.create_session("bob")["id"], "城市")[0]["content"])
        memory = self.client.get("/api/chat/memories").json["items"][0]
        self.login("bob")
        self.assertEqual(self.api("DELETE", f"/api/chat/memories/{memory['id']}").status_code, 404)
        self.login("alice")
        self.assertEqual(self.api("DELETE", f"/api/chat/memories/{memory['id']}").status_code, 200)
        self.assertNotIn('"value": "杭州"', self.service.context("alice", second, "城市")[0]["content"])

    def test_summary_and_analysis_cursor(self):
        sid = self.create()
        self.send(sid)
        self.service.store.enqueue("alice", sid, immediate=True)
        self.service.analyze(self.service.store.claim_job())
        session_row = self.service.store.session("alice", sid)
        self.assertGreater(session_row["analyzed_seq"], 0)
        self.assertIn("用户讨论", session_row["summary"])
        self.send(sid, "继续讨论")
        self.assertIn("用户讨论", self.calls[-1]["messages"][0]["content"])
        self.assertEqual(self.calls[-1]["messages"][-1]["content"], "继续讨论")

    def test_memory_evidence_and_scope(self):
        sid = self.create()
        self.send(sid)
        _, messages, raw = self.batch(sid)
        wrong = deepcopy(raw)
        wrong["memories"][0]["evidence"][0]["quote"] = "这是模型编造的话"
        with self.assertRaises(ValueError):
            validate_analysis(wrong, messages)
        temporary = deepcopy(raw)
        temporary["memories"][0]["scope"] = "session"
        self.assertEqual(validate_analysis(temporary, messages)["memories"], [])

    def test_stale_analysis_does_not_overwrite_new_memory(self):
        first, second = self.create(), self.create()
        self.send(first)
        first_job, first_messages, first_result = self.batch(first)
        self.send(second, "我现在希望去上海工作。")
        second_job, second_messages, second_result = self.batch(second, "上海")
        self.assertTrue(self.service.store.apply_analysis(second_job, second_messages, second_result, 0))
        self.assertFalse(self.service.store.apply_analysis(first_job, first_messages, first_result, 0))
        self.assertEqual(self.service.store.memory_snapshot("alice")[1][0]["value"], "上海")
        self.assertEqual(self.service.store.session("alice", first)["analyzed_seq"], 0)
        # Even after re-reading the new revision, an old statement must not become current.
        retried = self.service.store.claim_job()
        current_revision = self.service.store.memory_snapshot("alice")[0]
        self.assertTrue(self.service.store.apply_analysis(retried, first_messages, first_result, current_revision))
        self.assertEqual(self.service.store.memory_snapshot("alice")[1][0]["value"], "上海")

    def test_job_failure_keeps_raw_messages_and_cursor(self):
        sid = self.create()
        self.send(sid)
        job, _, _ = self.batch(sid)
        self.service.store.fail_job(job)
        self.assertEqual(self.service.store.session("alice", sid)["analyzed_seq"], 0)
        self.assertEqual(len(self.service.store.messages("alice", sid)["items"]), 2)
        self.assertEqual(self.service.store.memory_status("alice")["queued"], 1)

    def test_restart_persistence_and_message_pagination(self):
        sid = self.create()
        self.send(sid)
        restarted = ChatStore(self.service.store.path)
        latest = restarted.messages("alice", sid, limit=1)
        self.assertTrue(latest["has_more"])
        earlier = restarted.messages("alice", sid, before=latest["items"][0]["seq"], limit=1)
        self.assertEqual(earlier["items"][0]["role"], "user")

    def test_model_unconfigured_retains_draft_without_creating_user_message(self):
        sid = self.create()
        self.runtime = (None, None, None)
        response = self.api("POST", f"/api/chat/sessions/{sid}/messages", {"content": "你好", "request_id": str(uuid4())})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.service.store.messages("alice", sid)["items"], [])

    def test_fact_conflicts_are_not_used_for_recall_or_reports(self):
        first = self.create()
        self.send(first, "我本科毕业。")
        job, messages, result = self.batch(first, "本科", "fact", "education")
        self.service.store.apply_analysis(job, messages, result, 0)
        second = self.create()
        self.send(second, "我是硕士。")
        job, messages, result = self.batch(second, "硕士", "fact", "education")
        self.service.store.apply_analysis(job, messages, result, 1)
        rows = self.service.store.memory_snapshot("alice")[1]
        self.assertEqual({row["status"] for row in rows}, {"active", "conflict"})
        self.assertEqual(self.service.career_context("alice")["evidence"], "")

    def test_duplicate_confirmation_prevents_an_older_change(self):
        first, middle, newest = self.create(), self.create(), self.create()
        self.send(first)
        job, messages, result = self.batch(first)
        self.service.store.apply_analysis(job, messages, result, 0)
        self.send(middle, "我想去上海工作。")
        middle_job, middle_messages, middle_result = self.batch(middle, "上海")
        self.send(newest, "我还是希望在杭州工作。")
        job, messages, result = self.batch(newest)
        self.service.store.apply_analysis(job, messages, result, 1)
        self.service.store.apply_analysis(middle_job, middle_messages, middle_result, 2)
        rows = self.service.store.memory_snapshot("alice")[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "杭州")

    def test_forgotten_memory_is_not_restored_by_a_queued_conversation(self):
        first, second = self.create(), self.create()
        self.send(first)
        job, messages, result = self.batch(first)
        self.service.store.apply_analysis(job, messages, result, 0)
        self.send(second)
        stale_job, stale_messages, stale_result = self.batch(second)
        memory = self.service.store.memory_snapshot("alice")[1][0]
        self.service.store.forget("alice", memory["id"])
        self.service.store.apply_analysis(stale_job, stale_messages, stale_result, 2)
        self.assertEqual(self.service.store.memory_snapshot("alice")[1], [])


class ChromaChecks(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("chromadb"), "Chroma dependency is not installed")
    def test_real_vector_write_query_and_owner_filter(self):
        # Use a separate process so Chroma releases all native index handles before cleanup on Windows.
        with tempfile.TemporaryDirectory() as folder:
            source = """
import sys
sys.path.insert(0, sys.argv[1])
import chromadb
from services.chat.memory import chroma_settings
client = chromadb.PersistentClient(path=sys.argv[2], settings=chroma_settings())
collection = client.get_or_create_collection('offline_assistant_check', embedding_function=None)
collection.upsert(ids=['a','b'], embeddings=[[1.,0.,0.],[1.,0.,0.]],
                  metadatas=[{'owner':'alice'},{'owner':'bob'}], documents=['a','b'])
assert collection.query(query_embeddings=[[1.,0.,0.]],where={'owner':'alice'},n_results=1)['ids'] == [['a']]
collection.delete(where={'owner':'alice'})
assert collection.get(where={'owner':'alice'})['ids'] == []
assert collection.get(where={'owner':'bob'})['ids'] == ['b']
"""
            result = subprocess.run([sys.executable, "-c", source, str(Path(__file__).resolve().parents[1]), folder],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
