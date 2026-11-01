"""Offline regression checks for resume context and memory visibility. No model/OCR calls."""

from pathlib import Path
import asyncio
from contextlib import asynccontextmanager
import json
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat import ChatChecks


class ContextChecks(unittest.TestCase):
    def setUp(self):
        self.case = ChatChecks(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.service = self.case.service
        self.file = Path(self.case.temp.name) / "resume.docx"
        self.file.write_bytes(b"offline resume version one")
        self.sources = {"alice": {"path": str(self.file), "name": "resume.docx"}}
        self.service.resume_provider = lambda owner: self.sources.get(owner, {})
        self.service.documents.current_source = self.service.resume_provider
        self.reads = []
        def read(path):
            self.reads.append(path)
            return {"status": "ok", "markdown": "姓名：林禾\n学校：示例大学\n专业：计算机科学\n项目：RAG 助手\n电话：13912345678\n邮箱：sample@example.invalid"}
        self.service.documents.reader = read

    def finish_document_tasks(self):
        with self.service.documents.guard:
            tasks = list(self.service.documents.tasks.values())
        for task in tasks:
            task.join(timeout=3)

    def test_general_first_question_does_not_wait_for_a_slow_resume_reader(self):
        started, release, answered = threading.Event(), threading.Event(), threading.Event()
        reader = self.service.documents.reader

        def slow_reader(path):
            started.set()
            release.wait(5)
            return reader(path)

        self.service.documents.reader = slow_reader
        sid = self.case.create()
        errors = []

        def send():
            try:
                self.case.send(sid, "AI岗位有哪些类别？")
            except BaseException as error:
                errors.append(error)
            finally:
                answered.set()

        request = threading.Thread(target=send)
        request.start()
        try:
            self.assertTrue(started.wait(2))
            self.assertTrue(answered.wait(2), "The answer waited for document parsing")
            self.assertFalse(release.is_set())
            self.assertFalse(errors)
        finally:
            release.set()
            request.join(timeout=3)
            self.finish_document_tasks()

    def test_ready_resume_text_does_not_wait_for_structured_profile_model(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def slow_profile(*args):
            started.set()
            release.wait(5)
            finished.set()
            return []

        self.service.documents.profile_extractor = slow_profile
        try:
            self.service.documents.start("alice", self.sources["alice"])
            self.service.prepare_resume("alice", wait_seconds=1)
            self.assertTrue(started.wait(2))
            sid = self.case.create()
            self.case.send(sid, "我的专业是什么？")
            self.assertFalse(finished.is_set(), "The answer waited for the profile model")
            prompt = next(call for call in reversed(self.case.calls) if call.get("stream"))["messages"][0]["content"]
            self.assertIn("林禾", prompt)
            self.assertIn("计算机科学", prompt)
        finally:
            release.set()
            self.finish_document_tasks()

    def test_first_answer_has_priority_over_resume_profile_model(self):
        from check_chat import FakeClient
        order = []

        class Client(FakeClient):
            def create(inner, **kwargs):
                if kwargs.get("stream"):
                    order.append("answer")
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: Client(self.case.calls)
        self.service.documents.profile_extractor = lambda *args: order.append("profile") or []
        self.case.send(self.case.create(), "AI岗位有哪些类别？")
        self.finish_document_tasks()
        self.assertEqual(order, ["answer", "profile"])

    def test_stalled_semantic_recall_falls_back_without_queuing_more_calls(self):
        sid = self.case.create()
        self.case.send(sid)
        job, messages, result = self.case.batch(sid)
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        identifier = self.service.store.memory_snapshot("alice")[1][0]["id"]
        started, release = threading.Event(), threading.Event()

        def stalled(*args, **kwargs):
            started.set()
            release.wait(5)
            return [identifier]

        memory = self.service.memory
        memory.VECTOR_WAIT_SECONDS = .01
        memory.vector.search = MagicMock(side_effect=stalled)
        try:
            for _ in range(3):
                context, trace = self.service.context("alice", sid, "推荐一个城市", with_trace=True, read_resume=False)
                self.assertIn("杭州", context[0]["content"])
                self.assertEqual(trace["retrieval"], "saved_memory")
            self.assertTrue(started.is_set())
            self.assertEqual(memory.vector.search.call_count, 2)
        finally:
            release.set()

    def test_reply_trace_reports_context_and_model_latency_separately(self):
        sid = self.case.create()
        self.case.send(sid, "你好")
        trace = self.service.store.context_trace("alice", sid)
        self.assertEqual(trace["status"], "complete")
        for key in ("context_ms", "model_connect_ms", "first_token_ms", "total_ms"):
            self.assertGreaterEqual(trace["timings"][key], 0)
        self.assertGreaterEqual(trace["timings"]["total_ms"], trace["timings"]["context_ms"])
        self.finish_document_tasks()

    def test_uploaded_resume_is_in_chat_context_as_user_source_and_read_once(self):
        sid = self.case.create()
        data = self.case.client.get("/api/chat/memories").json()
        self.assertEqual(data["resume"]["status"], "uploaded")
        self.assertFalse(self.reads)  # Inspecting memory must not invoke OCR.
        prompt = self.service.context("alice", sid, "我是谁")[0]["content"]
        self.assertIn("当前简历（用户上传的原文）", prompt)
        self.assertIn("林禾", prompt)
        self.assertIn("示例大学", prompt)
        self.assertNotIn("13912345678", prompt)
        self.assertNotIn("sample@example.invalid", prompt)
        self.service.context("alice", self.case.create(), "我的学校是什么？")
        self.assertEqual(len(self.reads), 1)
        self.assertEqual(self.case.client.get("/api/chat/memories").json()["resume"]["status"], "ready")

    def test_original_form_preferences_are_not_labeled_as_model_analysis(self):
        from services.chat.profile import build_background
        background = build_background({}, {"meta": {"generated_at": "2026-10-29"}, "profile_snapshot": {
            "report_user_inputs": {"preferences": "杭州或上海", "additional_evidence": ""},
            "report_availability": {"arrival": "now", "days_per_week": 5, "summary": "随时到岗，每周实习5天"}}})
        self.service.profile_provider = lambda owner: background
        data = self.service.memory_overview("alice")
        source = next(row for row in data["sources"] if row["kind"] == "user_statement")
        self.assertIn("杭州或上海", source["preview"])
        self.assertIn("随时到岗", source["preview"])

    def test_context_snapshot_reflects_exact_supplied_sources_and_is_owner_scoped(self):
        sid = self.case.create()
        self.case.send(sid, "我是谁？")
        data = self.case.client.get(f"/api/chat/memories?session_id={sid}").json()
        self.assertEqual(data["context"]["status"], "complete")
        self.assertIn("当前简历（用户上传的原文）", data["context"]["source_titles"])
        self.assertEqual(data["context"]["resume_status"], "ready")
        self.assertIn("林禾", next(source["preview"] for source in data["sources"] if source["kind"] == "user_upload"))
        self.case.login("bob")
        self.assertEqual(self.case.client.get(f"/api/chat/memories?session_id={sid}").status_code, 404)
        other = self.case.client.get("/api/chat/memories").json()
        self.assertEqual(other["resume"]["status"], "missing")
        self.assertNotIn("林禾", str(other))

    def test_memory_evidence_is_visible_and_forgetting_changes_future_context(self):
        sid = self.case.create()
        self.case.send(sid)
        job, messages, result = self.case.batch(sid)
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        next_session = self.case.create()
        self.case.send(next_session, "我希望在哪个城市工作？")
        data = self.case.client.get(f"/api/chat/memories?session_id={next_session}").json()
        memory = data["items"][0]
        self.assertIn("杭州", memory["evidence"][0]["quote"])
        self.assertEqual(data["context"]["memories"][0]["id"], memory["id"])
        self.case.api("DELETE", f"/api/chat/memories/{memory['id']}")
        _, trace = self.service.context("alice", self.case.create(), "我的偏好？", with_trace=True)
        self.assertFalse(trace["memories"])

    def test_report_reuses_the_same_cached_document_without_another_reader_call(self):
        from services.report import workflow
        from experiments.news_advisor.tools import document
        self.service.context("alice", self.case.create(), "我是谁")
        class Graph:
            async def ainvoke(self, value, config, **kwargs):
                self.value = value
            async def aget_state(self, config):
                return SimpleNamespace(values=self.value, tasks=[], config=config, next=[])
        graph = Graph()
        @asynccontextmanager
        async def fake_graph(*args):
            yield graph
        async def no_reader(*args, **kwargs):
            raise AssertionError("Must use cached document")
        with patch.object(workflow, "_graph", fake_graph), patch.object(document, "read_document", SimpleNamespace(ainvoke=no_reader)):
            result = asyncio.run(workflow._execute("alice", "report-012345abcdef",
                {"file_path": str(self.file), "targets": ["应用开发实习"]},
                {"document_cache": self.service.documents}, None))
        self.assertIn("林禾", result["input"]["raw_resume"])
        self.assertEqual(len(self.reads), 1)

    def test_index_degradation_explains_missing_dependency_without_blocking_resume(self):
        self.service.memory.vector.unavailable(ModuleNotFoundError("not installed", name="hnswlib"))
        sid = self.case.create()
        self.case.send(sid, "我是谁？")
        data = self.case.client.get(f"/api/chat/memories?session_id={sid}").json()
        self.assertEqual(data["index"]["state"], "degraded")
        self.assertEqual(data["index"]["error_code"], "missing_hnswlib")
        self.assertIn("hnswlib", data["index"]["message"])
        self.assertEqual(data["context"]["resume_status"], "ready")
        self.service.memory.vector.collection = object()
        self.service.memory.vector.retry_at = 0
        self.assertEqual(self.service.memory.vector.status()["state"], "degraded")

    def test_index_degradation_identifies_the_incompatible_hnswlib_variant(self):
        class OrdinaryIndex:
            pass

        try:
            OrdinaryIndex.file_handle_count
        except AttributeError as error:
            self.service.memory.vector.unavailable(error)
        data = self.case.client.get("/api/chat/memories").json()
        self.assertEqual(data["index"]["state"], "degraded")
        self.assertEqual(data["index"]["error_code"], "incompatible_hnswlib")
        self.assertIn("chroma-hnswlib", data["index"]["message"])
        self.assertIn("重启", data["index"]["message"])

    def test_replacing_resume_does_not_reuse_previous_file_content(self):
        self.service.context("alice", self.case.create(), "我是谁")
        self.file.write_bytes(b"offline resume version two")
        self.service.documents.reader = lambda path: {"status": "ok", "markdown": "姓名：江岚\n学校：另一所学校"}
        prompt = self.service.context("alice", self.case.create(), "我是谁")[0]["content"]
        self.assertIn("江岚", prompt)
        self.assertNotIn("林禾", prompt)

    def test_reader_failure_is_visible_and_does_not_expose_paths_or_invent_a_resume(self):
        def fail(path):
            self.reads.append(path)
            raise RuntimeError("/private/path/secret")
        self.service.documents.reader = fail
        prompt = self.service.context("alice", self.case.create(), "我是谁")[0]["content"]
        data = self.case.client.get("/api/chat/memories").json()
        self.assertEqual(data["resume"]["status"], "failed")
        self.assertNotIn("/private/path/secret", str(data))
        self.assertNotIn("林禾", prompt)
        self.assertIn("当前简历读取状态", prompt)
        self.service.context("alice", self.case.create(), "你好")
        self.assertEqual(len(self.reads), 1)

    def test_removed_account_is_not_recreated_by_inflight_resume_read(self):
        def read_and_delete(path):
            self.sources.clear()
            self.service.store.delete_owner("alice")
            self.service.documents.forget("alice")
            return {"status": "ok", "markdown": "不得在账户删除后重新写入的原文"}
        self.service.documents.reader = read_and_delete
        fingerprint = self.service.documents.fingerprint(self.sources["alice"])
        with self.assertRaises(ValueError):
            self.service.documents.read("alice", dict(self.sources["alice"]))
        self.assertIsNone(self.service.documents.repository.get("alice", fingerprint))

    def test_document_source_removal_stops_it_being_injected(self):
        self.service.context("alice", self.case.create(), "我是谁")
        self.sources.clear()
        self.service.documents.forget("alice")
        prompt = self.service.context("alice", self.case.create(), "我是谁")[0]["content"]
        self.assertNotIn("林禾", prompt)
        self.assertNotIn("当前简历（用户上传的原文）", json.loads(prompt.split("用户背景 JSON：\n", 1)[1])["background"])

    def test_sync_endpoint_requires_login_and_csrf_and_never_accepts_a_client_path(self):
        self.case.login(None)
        self.assertEqual(self.case.api("POST", "/api/chat/sources/resume/sync").status_code, 401)
        self.case.login("alice")
        self.assertEqual(self.case.client.post("/api/chat/sources/resume/sync").status_code, 403)
        seen = []
        self.service.documents.start = lambda owner, source, **options: seen.append((owner, source, options))
        result = self.case.api("POST", "/api/chat/sources/resume/sync", {"path": "/other/account/private"})
        self.assertEqual(result.status_code, 202)
        self.assertEqual(seen[0][1]["path"], str(self.file))
        self.assertTrue(seen[0][2]["retry"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
