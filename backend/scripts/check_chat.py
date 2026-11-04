from copy import deepcopy
import asyncio
import json
import importlib.util
from pathlib import Path
import sys
import subprocess
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, session
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect
from services.chat import create_blueprint
from services.chat.api import create_app
from services.chat.extraction import EXTRACTION_PROMPT, SUMMARY_PROMPT, SUMMARY_TEXT_PROMPT, validate_analysis
from services.chat.cache import RecentCache
from services.chat.memory import MemoryManager, analysis_error_detail
from services.chat.reconciliation import RELATION_PROMPT, REPLACEMENT_CUE
from services.resume.facts import PROFILE_PROMPT
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
        result = {"summary": "用户讨论职业计划，助手建议从项目经历开始。", "memories": []}
        if kwargs["messages"][0]["content"] == RELATION_PROMPT:
            import re
            payload = json.loads(kwargs["messages"][1]["content"])
            candidate, old = payload["candidate"], payload["existing"][0]
            operation = "REPLACE" if re.search(REPLACEMENT_CUE, " ".join(item["quote"] for item in candidate["evidence"]), re.I) else "CONFLICT"
            result = {"operation": operation, "target_id": old["id"], "value": candidate["value"], "reason": "offline relation",
                      "requires_confirmation": operation == "CONFLICT"}
        elif kwargs["messages"][0]["content"] == EXTRACTION_PROMPT:
            result = {"memories": []}
        elif kwargs["messages"][0]["content"] == SUMMARY_PROMPT:
            result = {"summary": result["summary"]}
        elif kwargs["messages"][0]["content"] == PROFILE_PROMPT:
            result = {"facts": []}
        content = json.dumps(result)
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
        self.current_user = lambda: {"username": session["user"], "display_name": "测试用户"} if session.get("user") else None
        self.bp = create_blueprint(directory=self.temp.name,
            current_user=self.current_user,
            runtime_provider=lambda selection: self.runtime,
            profile_provider=lambda owner: {"用户背景": owner + "的职业画像"})
        self.app.register_blueprint(self.bp)
        self.service = self.bp.chat_service
        self.service.memory.start = lambda: None
        self.service.memory.cache.retry_at = float("inf")
        self.service.memory.vector.retry_at = float("inf")
        self.service.client_factory = lambda runtime: FakeClient(self.calls)
        self.flask_client = self.app.test_client()
        self.asgi_app = create_app(self.app, service=self.service, current_user=self.current_user)
        self.client = TestClient(self.asgi_app, follow_redirects=False)
        self.addCleanup(self.client.close)
        self.login("alice")

    def login(self, owner):
        with self.flask_client.session_transaction() as state:
            state.clear()
            if owner:
                state["user"] = owner
                state["csrf_token"] = "test-csrf"
        self.client.cookies.clear()
        name = self.app.config["SESSION_COOKIE_NAME"]
        cookie = self.flask_client.get_cookie(name)
        if cookie:
            self.client.cookies.set(name, cookie.value)

    def api(self, method, path, data=None):
        return self.client.request(method, path, json=data,
            headers={"X-CSRF-Token": "test-csrf"})

    def create(self):
        response = self.api("POST", "/api/chat/sessions", {})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def send(self, sid, content="我希望去杭州工作。", request_id=None):
        request_id = request_id or str(uuid4())
        response = self.api("POST", f"/api/chat/sessions/{sid}/messages", {"content": content, "request_id": request_id})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events[-1]["type"], "done")
        return request_id

    def batch(self, sid, value="杭州", kind="preference", key="target_city", operation="assert"):
        self.service.store.enqueue("alice", sid, immediate=True)
        job = self.service.store.claim_job(kind="memory")
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

    def test_fastapi_validation_docs_and_transport(self):
        schema = self.client.get("/api/chat/openapi.json").json()
        path = "/api/chat/sessions/{session_id}/messages"
        self.assertIn("text/event-stream", schema["paths"][path]["post"]["responses"]["200"]["content"])
        self.assertEqual(self.client.get("/api/chat/docs").status_code, 200)
        for data in ({"title": " "}, {"title": "x" * 81}, {"title": 123}):
            response = self.api("POST", "/api/chat/sessions", data)
            self.assertEqual(response.status_code, 400)
            self.assertIn("message", response.json())
            self.assertEqual(response.headers["cache-control"], "no-store")
        sid = self.create()
        for data in ({"content": "你好", "request_id": "bad"},
                     {"content": " ", "request_id": str(uuid4())},
                     {"content": "x" * 12001, "request_id": str(uuid4())}):
            self.assertEqual(self.api("POST", f"/api/chat/sessions/{sid}/messages", data).status_code, 400)
        self.assertEqual(self.service.store.messages("alice", sid)["items"], [])
        oversized = self.client.post("/api/chat/sessions", content=b"x" * 65537,
                                     headers={"X-CSRF-Token": "test-csrf", "Content-Type": "application/json"})
        self.assertEqual(oversized.status_code, 413)
        # No content-length is supplied for this streaming request.
        chunked = self.client.post("/api/chat/sessions", content=iter([b"x" * 32768] * 3),
                                   headers={"X-CSRF-Token": "test-csrf", "Content-Type": "application/json"})
        self.assertEqual(chunked.status_code, 413)
        preflight = self.client.options("/api/chat/sessions/anything",
            headers={"Origin": "http://testserver", "Access-Control-Request-Method": "PATCH",
                     "Access-Control-Request-Headers": "X-CSRF-Token, Content-Type"})
        self.assertEqual(preflight.status_code, 204)
        self.assertIn("PATCH", preflight.headers["access-control-allow-methods"])
        self.assertEqual(preflight.headers["access-control-allow-credentials"], "true")
        self.assertEqual(preflight.content, b"")
        foreign = self.client.get("/api/chat/sessions", headers={"Origin": "https://untrusted.invalid"})
        self.assertNotIn("access-control-allow-origin", foreign.headers)

    def test_flask_login_cookie_and_revoked_or_disabled_auth(self):
        from services import auth, db

        # Exercise the production auth callback against an isolated auth database.
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE users(username TEXT PRIMARY KEY, display_name TEXT, role TEXT, disabled INTEGER);
            CREATE TABLE auth_sessions(token_hash TEXT, username TEXT, expires_at REAL);
            INSERT INTO users VALUES ('alice', 'Alice', 'user', 0);
        """)
        token = "offline-auth-token"
        with self.app.app_context():
            digest = auth.digest(token)
        conn.execute("INSERT INTO auth_sessions VALUES (?, 'alice', ?)", (digest, time.time() + 3600))
        conn.commit()

        @self.app.post("/fixture/login")
        def fixture_login():
            session.clear()
            session.update(auth_token=token, csrf_token="bridge-csrf",
                           llm_selection={"provider_id": "offline-provider", "model": "chosen-model"})
            return {"ok": True}

        selections = []
        self.service.runtime_provider = lambda selection: selections.append(selection) or self.runtime
        application = create_app(self.app, service=self.service, current_user=auth.current_user)
        with patch.object(db, "_get_conn", return_value=conn), TestClient(application) as client:
            self.assertEqual(client.get("/api/chat/sessions").status_code, 401)
            # Login travels through the mounted Flask app and sets the signed cookie.
            self.assertEqual(client.post("/fixture/login").status_code, 200)
            self.assertEqual(client.get("/api/chat/sessions").status_code, 200)
            self.assertEqual(selections[-1], {"provider_id": "offline-provider", "model": "chosen-model"})
            self.assertEqual(client.post("/api/chat/sessions", json={}).status_code, 403)
            created = client.post("/api/chat/sessions", json={"owner": "bob"}, headers={"X-CSRF-Token": "bridge-csrf"})
            self.assertEqual(created.status_code, 201)
            self.assertEqual(self.service.store.session("alice", created.json()["id"])["owner"], "alice")
            conn.execute("UPDATE users SET disabled=1")
            conn.commit()
            self.assertEqual(client.get("/api/chat/sessions").status_code, 401)
            conn.execute("UPDATE users SET disabled=0")
            conn.execute("UPDATE auth_sessions SET expires_at=0")
            conn.commit()
            self.assertEqual(client.get("/api/chat/sessions").status_code, 401)
            conn.execute("DELETE FROM auth_sessions")
            conn.commit()
            self.assertEqual(client.get("/api/chat/sessions").status_code, 401)

    def test_session_crud_and_owner_isolation(self):
        sid = self.create()
        self.assertEqual(self.api("PATCH", f"/api/chat/sessions/{sid}", {"title": "面试准备"}).status_code, 200)
        self.assertEqual(self.client.get("/api/chat/sessions").json()["items"][0]["title"], "面试准备")
        self.login("bob")
        self.assertEqual(self.client.get("/api/chat/sessions").json()["items"], [])
        for method, suffix, data in (("GET", "/messages", None), ("DELETE", "", None), ("PATCH", "", {"title": "盗用"}), ("POST", "/finish", {})):
            self.assertEqual(self.api(method, f"/api/chat/sessions/{sid}{suffix}", data).status_code, 404)
        self.login("alice")
        self.assertEqual(self.api("DELETE", f"/api/chat/sessions/{sid}").status_code, 202)
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
        self.assertEqual(len(self.client.get(f"/api/chat/sessions/{first}/messages").json()["items"]), 2)
        self.assertEqual(self.api("POST", f"/api/chat/sessions/{first}/messages", {"content": "不同内容", "request_id": request_id}).status_code, 409)

    def test_stream_disconnect_and_retry(self):
        sid, request_id = self.create(), str(uuid4())
        # TestClient buffers SSE. Exercise a real ASGI send failure instead.
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": f"/api/chat/sessions/{sid}/messages", "query_string": b"",
                 "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                             (b"x-csrf-token", b"test-csrf"),
                             (b"cookie", ("session=" + self.client.cookies.get("session")).encode())],
                 "server": ("testserver", 80), "client": ("127.0.0.1", 1234)}

        async def receive():
            return {"type": "http.request", "body": json.dumps({"content": "准备面试", "request_id": request_id}).encode()}

        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")

        with self.assertRaises(ClientDisconnect):
            asyncio.run(self.asgi_app(scope, receive, send))
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
        self.assertTrue(self.service.memory.commit_candidates(job, messages, result["memories"], 0))
        prompt = self.service.context("alice", second, "我适合什么城市？")[0]["content"]
        self.assertIn('"value": "杭州"', prompt)
        self.assertNotIn("杭州", self.service.context("bob", self.service.store.create_session("bob")["id"], "城市")[0]["content"])
        memory = self.client.get("/api/chat/memories").json()["items"][0]
        self.login("bob")
        self.assertEqual(self.api("DELETE", f"/api/chat/memories/{memory['id']}").status_code, 404)
        self.login("alice")
        self.assertEqual(self.api("DELETE", f"/api/chat/memories/{memory['id']}").status_code, 202)
        self.assertNotIn('"value": "杭州"', self.service.context("alice", second, "城市")[0]["content"])

    def test_summary_and_analysis_cursor(self):
        sid = self.create()
        self.send(sid)
        self.service.store.enqueue("alice", sid, immediate=True)
        self.service.memory.analyze(self.service.store.claim_job(kind="summary"))
        session_row = self.service.store.session("alice", sid)
        self.assertGreater(session_row["analyzed_seq"], 0)
        self.assertEqual(session_row["memory_seq"], 0)
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
        self.assertTrue(self.service.memory.commit_candidates(second_job, second_messages, second_result["memories"], 0))
        self.assertFalse(self.service.memory.commit_candidates(first_job, first_messages, first_result["memories"], 0))
        self.assertEqual(self.service.store.memory_snapshot("alice")[1][0]["value"], "上海")
        self.assertEqual(self.service.store.session("alice", first)["memory_seq"], 0)
        # Even after re-reading the new revision, an old statement must not become current.
        retried = self.service.store.claim_job(kind="memory")
        current_revision = self.service.store.memory_snapshot("alice")[0]
        self.assertTrue(self.service.memory.commit_candidates(retried, first_messages, first_result["memories"], current_revision))
        self.assertEqual(self.service.store.memory_snapshot("alice")[1][0]["value"], "上海")

    def test_job_failure_keeps_raw_messages_and_cursor(self):
        sid = self.create()
        self.send(sid)
        job, _, _ = self.batch(sid)
        self.service.store.fail_job(job)
        self.assertEqual(self.service.store.session("alice", sid)["memory_seq"], 0)
        self.assertEqual(len(self.service.store.messages("alice", sid)["items"]), 2)
        self.assertEqual(self.service.store.memory_status("alice")["memory"]["queued"], 1)

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
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        second = self.create()
        self.send(second, "我是硕士。")
        job, messages, result = self.batch(second, "硕士", "fact", "education")
        self.service.memory.commit_candidates(job, messages, result["memories"], 1)
        rows = self.service.store.memory_snapshot("alice")[1]
        self.assertEqual({row["status"] for row in rows}, {"active", "conflict"})
        self.assertEqual(self.service.memory.career_context("alice")["evidence"], "")

    def test_duplicate_confirmation_prevents_an_older_change(self):
        first, middle, newest = self.create(), self.create(), self.create()
        self.send(first)
        job, messages, result = self.batch(first)
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        self.send(middle, "我想去上海工作。")
        middle_job, middle_messages, middle_result = self.batch(middle, "上海")
        self.send(newest, "我还是希望在杭州工作。")
        job, messages, result = self.batch(newest)
        self.service.memory.commit_candidates(job, messages, result["memories"], 1)
        self.service.memory.commit_candidates(middle_job, middle_messages, middle_result["memories"], 2)
        rows = self.service.store.memory_snapshot("alice")[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["value"], "杭州")

    def test_forgotten_memory_is_not_restored_by_a_queued_conversation(self):
        first, second = self.create(), self.create()
        self.send(first)
        job, messages, result = self.batch(first)
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        self.send(second)
        stale_job, stale_messages, stale_result = self.batch(second)
        memory = self.service.store.memory_snapshot("alice")[1][0]
        self.service.store.forget("alice", memory["id"])
        self.service.memory.commit_candidates(stale_job, stale_messages, stale_result["memories"], 2)
        self.assertEqual(self.service.store.memory_snapshot("alice")[1], [])


class MemoryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ChatStore(Path(self.temp.name) / "memory.sqlite3")
        self.cache, self.vector = MagicMock(), MagicMock()
        self.cache.get.return_value = None
        self.vector.search.return_value = []
        self.calls = []
        self.client = FakeClient(self.calls)
        self.client.close = MagicMock()
        self.memory = MemoryManager(self.store, self.temp.name,
            runtime=lambda selection: ("https://offline.invalid/v1", "offline", "fake-model"),
            client_factory=lambda runtime: self.client, cache=self.cache, vector=self.vector)
        self.addCleanup(self.memory.close)
        self.sid = self.store.create_session("alice")["id"]

    def turn(self):
        request_id = str(uuid4())
        turn = self.store.begin_turn("alice", self.sid, request_id, "记住这个问题", {})
        self.store.finish_turn("alice", self.sid, request_id, turn["token"], "收到")

    @staticmethod
    def model_response(content, finish_reason="stop", refusal=None):
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason,
            message=SimpleNamespace(content=content, refusal=refusal))])

    def test_invalid_summary_json_regenerates_text_from_original_messages(self):
        self.turn()
        self.store.enqueue("alice", self.sid, immediate=True)
        job = self.store.claim_job(kind="summary")
        summary = '用户说：“保留引号和路径 C:\\work”。\n助手建议稍后核实。'
        with patch.object(self.client, "create", side_effect=[
                self.model_response('{"summary":"未转义的"引号"}'), self.model_response(summary)]) as create:
            self.assertTrue(self.memory.analyze(job))
        self.assertEqual(self.store.session("alice", self.sid)["summary"], summary)
        self.assertGreater(self.store.session("alice", self.sid)["analyzed_seq"], 0)
        first, fallback = [call.kwargs for call in create.call_args_list]
        self.assertEqual(first["messages"][1], fallback["messages"][1])
        self.assertEqual(fallback["messages"][0]["content"], SUMMARY_TEXT_PROMPT)
        self.assertNotIn("response_format", fallback)
        self.assertEqual(self.client.close.call_count, 2)

    def test_invalid_text_fallback_preserves_summary_cursor_and_history(self):
        self.turn()
        self.store.enqueue("alice", self.sid, immediate=True)
        job = self.store.claim_job(kind="summary")
        for response in (self.model_response(""), self.model_response(" " * 10),
                         self.model_response("摘" * 2501), self.model_response('{"summary":"broken'),
                         self.model_response("```text\n摘要\n```"),
                         self.model_response("不完整摘要", "length"),
                         self.model_response(None, "stop", "declined")):
            with self.subTest(response=response), patch.object(self.client, "create", side_effect=[
                    self.model_response('{"summary":"broken'), response]):
                with self.assertRaises(ValueError):
                    self.memory.analyze(job)
                session = self.store.session("alice", self.sid)
                self.assertEqual((session["summary"], session["analyzed_seq"]), ("", 0))
                self.assertEqual(len(self.store.messages("alice", self.sid)["items"]), 2)

    def test_long_summary_keeps_every_window_and_previous_summary_on_fallback(self):
        from dataclasses import replace
        self.memory.policy = replace(self.memory.policy, batch_tokens=1000)
        text = "长期会话中的用户背景与未决事项。" * 100
        request_id = str(uuid4())
        turn = self.store.begin_turn("alice", self.sid, request_id, text, {})
        self.store.finish_turn("alice", self.sid, request_id, turn["token"], "收到")
        self.store.enqueue("alice", self.sid, immediate=True)
        job = self.store.claim_job(kind="summary")
        windows = []

        def generate(**kwargs):
            if kwargs["messages"][0]["content"] == SUMMARY_PROMPT:
                return self.model_response('{"summary":"bad"quote"}')
            payload = json.loads(kwargs["messages"][1]["content"])
            self.assertEqual(payload["previous_summary"], "" if not windows else f"累计摘要{len(windows)}")
            windows.append(payload["messages"])
            return self.model_response(f"累计摘要{len(windows)}")

        with patch.object(self.client, "create", side_effect=generate):
            self.assertTrue(self.memory.analyze(job))
        self.assertGreater(len(windows), 1)
        self.assertEqual("".join(row["content"] for window in windows for row in window if row["role"] == "user"), text)
        session = self.store.session("alice", self.sid)
        self.assertEqual(session["summary"], f"累计摘要{len(windows)}")
        self.assertEqual(session["analyzed_seq"], 2)

    def test_invalid_memory_json_does_not_use_summary_fallback(self):
        self.turn()
        self.store.enqueue("alice", self.sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        with patch.object(self.client, "create", return_value=self.model_response('{"memories":[')) as create:
            with self.assertRaises(json.JSONDecodeError):
                self.memory.analyze(job)
        create.assert_called_once()
        self.assertEqual(self.store.session("alice", self.sid)["memory_seq"], 0)

    def test_corrupt_or_stale_cache_falls_back_to_durable_messages(self):
        self.turn()
        session = self.store.session("alice", self.sid)
        version = [session["updated_at"], session["analyzed_seq"]]
        bad_rows = [None, {}, {"version": version, "items": "invalid"},
                    {"version": version, "items": [None]},
                    {"version": version, "items": [{"seq": 1, "role": [], "content": "x", "status": "complete"}]},
                    {"version": version, "items": [{"seq": 1, "role": "system", "content": "x", "status": "complete"}]},
                    {"version": [0, 0], "items": []}]
        for cached in bad_rows:
            with self.subTest(cached=cached):
                self.cache.get.return_value = cached
                result = self.memory.context("alice", self.sid, "你好")
                self.assertEqual([item["content"] for item in result.recent], ["记住这个问题", "收到"])
        with self.assertRaises(ChatError):
            self.memory.context("bob", self.sid, "你好")
        self.assertEqual(self.cache.get.call_count, len(bad_rows))

    def test_vector_similarity_order_takes_priority_over_recency(self):
        rows = [{"id": identifier, "kind": "fact", "key": "skill", "subject": identifier,
                 "value": identifier, "status": "active", "updated_at": updated}
                for identifier, updated in (("near", 1), ("far", 100))]
        self.vector.search.return_value = ["near", "far"]
        with patch.object(self.store, "memory_snapshot", return_value=(0, rows)):
            context = self.memory.context("alice", self.sid, "技能")
        self.assertEqual([row["id"] for row in context.memories], ["near", "far"])

    def test_failed_extraction_preserves_history_and_retries_then_closes_client(self):
        self.turn()
        self.store.enqueue("alice", self.sid, immediate=True)
        with patch.object(self.client, "create", side_effect=RuntimeError("offline model failed")):
            self.assertTrue(self.memory.run_once())
        self.assertEqual(self.store.session("alice", self.sid)["memory_seq"], 0)
        self.assertEqual(len(self.store.messages("alice", self.sid)["items"]), 2)
        self.assertEqual(self.store.memory_status("alice")["memory"]["queued"], 1)
        self.client.close.assert_called_once()

    def test_failure_logs_are_specific_without_private_model_content(self):
        from services.chat.schemas import SummaryOutput
        private = "private-chat-and-api-key"
        try:
            SummaryOutput.model_validate({"summary": private * 200})
        except ValueError as error:
            validation = error
        self.turn()
        self.store.enqueue("alice", self.sid, immediate=True)
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE memory_jobs SET attempts=2 WHERE session_id=? AND kind='summary'", (self.sid,))
        job = self.store.claim_job(kind="summary")
        with patch.object(self.store, "claim_job", return_value=job), patch.object(self.memory, "analyze", side_effect=validation):
            with self.assertLogs("services.chat.memory", level="WARNING") as captured:
                self.memory.run_once()
        message = " ".join(captured.output)
        self.assertIn("会话摘要", message)
        self.assertIn("summary:string_too_long", message)
        self.assertIn("ValidationError", message)
        self.assertIn("3/3", message)
        self.assertIn("停止自动重试", message)
        self.assertNotIn(private, message)
        self.assertEqual(self.store.memory_status("alice")["summary"]["error"], 1)
        self.assertNotIn(private, analysis_error_detail(RuntimeError(private)))
        with self.assertRaises(ValueError) as malformed:
            SummaryOutput.model_validate({"summary": "", private: "secret"})
        self.assertNotIn(private, analysis_error_detail(malformed.exception))

    def test_worker_shutdown_releases_clients_once(self):
        entered = threading.Event()
        self.memory.run_once = lambda: entered.set() or False
        self.memory.start()
        self.assertTrue(entered.wait(timeout=2))
        self.memory.close()
        self.memory.close()
        self.assertFalse(self.memory._worker.is_alive())
        self.cache.close.assert_called_once()
        self.vector.close.assert_called_once()

    def test_fastapi_lifespan_owns_memory_worker(self):
        app = Flask(__name__)
        application = create_app(app, service=SimpleNamespace(memory=self.memory), current_user=lambda: None)
        with TestClient(application) as client:
            self.assertTrue(self.memory._worker.is_alive())
            self.assertEqual(client.get("/api/chat/docs").status_code, 200)
        self.assertFalse(self.memory._worker.is_alive())
        self.cache.close.assert_called_once()
        self.vector.close.assert_called_once()

    def test_redis_failure_uses_sqlite_during_backoff(self):
        self.turn()
        redis = MagicMock()
        redis.get.side_effect = ConnectionError("offline redis")
        self.memory.cache = RecentCache(client=redis)
        for _ in range(2):
            context = self.memory.context("alice", self.sid, "你好")
            self.assertEqual(len(context.recent), 2)
        redis.get.assert_called_once()

    def test_malformed_model_fields_are_validation_errors(self):
        messages = [{"id": "user-1", "role": "user", "content": "我想去杭州"}]
        item = {"kind": "preference", "key": "target_city", "subject": "profile", "value": "杭州",
                "operation": "assert", "scope": "user", "confidence": .99,
                "evidence": [{"message_id": "user-1", "quote": "我想去杭州"}]}
        for field in ("kind", "key", "operation"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_analysis({"summary": "偏好", "memories": [{**item, field: []}]}, messages)
        item["evidence"][0]["message_id"] = []
        with self.assertRaises(ValueError):
            validate_analysis({"summary": "偏好", "memories": [item]}, messages)


class ChromaChecks(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("chromadb"), "Chroma dependency is not installed")
    def test_real_vector_write_query_and_owner_filter(self):
        # Use a separate process so Chroma releases all native index handles before cleanup on Windows.
        with tempfile.TemporaryDirectory() as folder:
            source = """
import sys
sys.path.insert(0, sys.argv[1])
import chromadb
from types import SimpleNamespace
from services.chat.vector import VectorMemory, chroma_settings
client = chromadb.PersistentClient(path=sys.argv[2], settings=chroma_settings())
collection = client.get_or_create_collection('offline_assistant_check', embedding_function=None)
collection.upsert(ids=['a','b'], embeddings=[[1.,0.,0.],[1.,0.,0.]],
                  metadatas=[{'owner':'alice','status':'active','privacy_epoch':0},{'owner':'bob','status':'active','privacy_epoch':0}], documents=['a','b'])
assert collection.query(query_embeddings=[[1.,0.,0.]],where={'owner':'alice'},n_results=1)['ids'] == [['a']]
index = VectorMemory(sys.argv[2])
index.collection = collection
index.model = 'offline-embedding'
index.embeddings = SimpleNamespace(embeddings=SimpleNamespace(create=lambda **kwargs:
    SimpleNamespace(data=[SimpleNamespace(embedding=[1.,0.,0.])])))
assert index.search('alice', 'skill') == ['a']
collection.delete(where={'owner':'alice'})
assert collection.get(where={'owner':'alice'})['ids'] == []
assert collection.get(where={'owner':'bob'})['ids'] == ['b']
disk = chromadb.PersistentClient(path=str(index.directory), settings=chroma_settings())
for name in ('model_namespace_one', 'model_namespace_two'):
    namespace = disk.get_or_create_collection(name, embedding_function=None)
    namespace.upsert(ids=['alice-record','bob-record'], embeddings=[[1.,0.,0.],[1.,0.,0.]],
        metadatas=[{'owner':'alice'},{'owner':'bob'}],documents=['alice','bob'])
index.delete_owner('alice')
for name in ('model_namespace_one', 'model_namespace_two'):
    namespace = disk.get_collection(name, embedding_function=None)
    assert namespace.get(where={'owner':'alice'})['ids'] == []
    assert namespace.get(where={'owner':'bob'})['ids'] == ['bob-record']
"""
            result = subprocess.run([sys.executable, "-c", source, str(Path(__file__).resolve().parents[1]), folder],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
