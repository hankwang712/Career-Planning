"""Offline checks of resume provenance, job isolation and memory reconciliation."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat import ChatChecks, FakeClient
from services.chat.extraction import validate_candidates, EXTRACTION_PROMPT
from services.chat.policy import MemoryPolicy, estimate_tokens, message_windows
from services.chat.reconciliation import RELATION_PROMPT, validate_decision
from services.chat.service import ChatService
from services.chat.storage import ChatStore
from services.chat.vector import VectorMemory
from services.resume.repository import ResumeRepository


class PipelineChecks(unittest.TestCase):
    def setUp(self):
        self.case = ChatChecks(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.service = self.case.service
        self.store = self.service.store

    def candidate(self, job, *, value, key="target_city", kind="preference", subject="profile", operation="assert"):
        messages = self.store.analysis_messages(job)
        user = next(row for row in reversed(messages) if row["role"] == "user")
        result = validate_candidates({"memories": [{"kind": kind, "key": key, "subject": subject, "value": value,
            "operation": operation, "scope": "user", "confidence": .99,
            "evidence": [{"message_id": user["id"], "quote": user["content"]}]}]}, messages)
        return messages, result

    def save(self, text, **kwargs):
        sid = self.case.create()
        self.case.send(sid, text)
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.candidate(job, **kwargs)
        self.assertTrue(self.service.memory.commit_candidates(job, messages, candidates))
        return sid

    def decision(self, operation, value, target_id):
        original = self.service.client_factory
        calls = self.case.calls

        class Client(FakeClient):
            def create(self, **kwargs):
                if kwargs["messages"][0]["content"] == RELATION_PROMPT:
                    calls.append(kwargs)
                    from types import SimpleNamespace
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                        "operation": operation, "target_id": target_id, "value": value, "reason": "evidence-based test",
                        "requires_confirmation": operation == "CONFLICT"})))])
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: Client(calls)
        self.addCleanup(setattr, self.service, "client_factory", original)

    def test_duplicate_addition_enrichment_replacement_and_audit(self):
        self.save("我会Python。", value="Python", key="skill", kind="fact", subject="Python")
        self.save("我掌握Python。", value="Python", key="skill", kind="fact", subject="python")
        self.save("我还会PyTorch。", value="PyTorch", key="skill", kind="fact", subject="PyTorch")
        rows = self.store.memory_snapshot("alice")[1]
        self.assertEqual(len(rows), 2)
        python = next(row for row in rows if row["value"] == "Python")
        self.assertEqual(len(json.loads(python["evidence"])), 2)
        self.assertIn("NOOP", [row["operation"] for row in self.store.memory_events("alice")])
        self.save("我想去杭州。", value="杭州")
        target = next(row for row in self.store.memory_snapshot("alice")[1] if row["key"] == "target_city")
        self.decision("ENRICH", "杭州、上海", target["id"])
        self.save("上海也可以考虑。", value="上海")
        self.assertEqual(next(row for row in self.store.memory_snapshot("alice")[1] if row["key"] == "target_city")["value"], "杭州、上海")
        self.save("现在只考虑上海，不考虑杭州了。", value="上海", operation="correct")
        current = next(row for row in self.store.memory_snapshot("alice")[1] if row["key"] == "target_city")
        self.assertEqual((current["id"], current["value"]), (target["id"], "上海"))
        self.assertEqual(self.store.memory_events("alice")[0]["operation"], "REPLACE")

    def test_experience_enrichment_requires_supported_claims(self):
        self.save("我使用过LangGraph。", value="使用过LangGraph", key="experience", kind="fact", subject="Agent项目")
        old = self.store.memory_snapshot("alice")[1][0]
        self.decision("ENRICH", "使用过LangGraph，并独立开发过多Agent系统", old["id"])
        self.save("我还独立开发过多Agent系统。", value="独立开发过多Agent系统", key="experience", kind="fact", subject="Agent项目")
        self.assertEqual(len(self.store.memory_snapshot("alice")[1]), 1)
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "使用过LangGraph；独立开发过多Agent系统")
        self.assertEqual(self.store.memory_events("alice")[0]["operation"], "ENRICH")
        self.decision("ENRICH", "支持1000000用户的系统", old["id"])
        with self.assertRaises(ValueError):
            self.save("我增加了部署功能。", value="增加部署功能", key="experience", kind="fact", subject="Agent项目")

    def test_experience_alias_can_use_semantics_but_other_account_cannot(self):
        self.save("我使用过LangGraph。", value="使用过LangGraph", key="experience", kind="fact", subject="职业规划项目")
        old = self.store.memory_snapshot("alice")[1][0]
        self.service.memory.vector.search = MagicMock(return_value=[old["id"]])
        self.decision("ENRICH", "使用过LangGraph，增加了部署功能", old["id"])
        self.save("这个Agent项目增加了部署功能。", value="增加了部署功能", key="experience", kind="fact", subject="生涯Agent")
        rows = self.store.memory_snapshot("alice")[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], old["id"])
        self.assertEqual(rows[0]["subject"], "职业规划项目")
        self.service.memory.vector.search = MagicMock(return_value=["foreign-memory"])
        self.save("我新做了搜索工具。", value="开发搜索工具", key="experience", kind="fact", subject="搜索项目")
        self.assertEqual(len(self.store.memory_snapshot("alice")[1]), 2)

    def test_noop_cannot_swallow_a_negated_city_change(self):
        self.save("我想去杭州。", value="杭州")
        old = self.store.memory_snapshot("alice")[1][0]
        self.decision("NOOP", "杭州", old["id"])
        with self.assertRaises(ValueError):
            self.save("以后只考虑上海，不再考虑杭州。", value="上海")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "杭州")

    def test_additive_preference_cannot_replace_old_options(self):
        self.save("我想去杭州。", value="杭州")
        old = self.store.memory_snapshot("alice")[1][0]
        self.decision("REPLACE", "上海", old["id"])
        with self.assertRaises(ValueError):
            self.save("上海也可以考虑。", value="上海")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "杭州")
        message = {"id": "m", "role": "user", "content": "其实上海也可以考虑。"}
        candidate = validate_candidates({"memories": [{"kind": "preference", "key": "target_city", "subject": "profile",
            "value": "上海", "operation": "correct", "scope": "user", "confidence": .99,
            "evidence": [{"message_id": "m", "quote": message["content"]}]}]}, [message])[0]
        with self.assertRaises(ValueError):
            validate_decision({"operation": "REPLACE", "target_id": old["id"], "value": "上海"}, candidate, [old])

    def test_ambiguous_preference_is_a_conflict_that_requires_confirmation(self):
        self.save("我想去杭州。", value="杭州")
        self.save("我想去上海。", value="上海")
        rows = self.store.memory_snapshot("alice")[1]
        self.assertEqual({(row["value"], row["status"]) for row in rows}, {("杭州", "active"), ("上海", "conflict")})
        event = self.store.memory_events("alice")[0]
        self.assertTrue(json.loads(event["decision"])["requires_confirmation"])
        self.assertFalse(self.service.memory.confirmed(rows))

    def test_exclusive_preference_cannot_retain_a_negated_option(self):
        self.save("我想去杭州。", value="杭州")
        old = self.store.memory_snapshot("alice")[1][0]
        self.decision("ENRICH", "杭州、上海", old["id"])
        with self.assertRaises(ValueError):
            self.save("现在只考虑上海。", value="上海")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "杭州")

    def test_experience_enrichment_cannot_invent_non_numeric_claims(self):
        self.save("我使用过LangGraph。", value="使用过LangGraph", key="experience", kind="fact", subject="Agent项目")
        old = self.store.memory_snapshot("alice")[1][0]
        self.decision("ENRICH", "使用过LangGraph，并负责技术团队", old["id"])
        with self.assertRaises(ValueError):
            self.save("项目增加了部署功能。", value="增加了部署功能", key="experience", kind="fact", subject="Agent项目")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "使用过LangGraph")

    def test_extraction_cannot_cite_a_later_unseen_window(self):
        from types import SimpleNamespace
        sid = self.case.create()
        self.case.send(sid, "这是技术讨论。" * 700)
        self.case.send(sid, "以后只考虑上海。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        _, candidates = self.candidate(job, value="上海")

        class Client(FakeClient):
            def create(inner, **kwargs):
                if kwargs["messages"][0]["content"] == EXTRACTION_PROMPT:
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"memories": candidates})))])
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: Client(self.case.calls)
        with self.assertRaises(ValueError):
            self.service.memory.analyze(job)
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertEqual(self.store.session("alice", sid)["memory_seq"], 0)

    def test_strict_output_mode_uses_the_shared_schema(self):
        sid = self.case.create()
        self.case.send(sid, "你好。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        with patch.dict("os.environ", {"CHAT_MEMORY_OUTPUT_FORMAT": "json_schema"}):
            self.assertTrue(self.service.memory.analyze(job))
        output = self.case.calls[-1]["response_format"]
        self.assertEqual(output["type"], "json_schema")
        self.assertTrue(output["json_schema"]["strict"])
        schema = output["json_schema"]["schema"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["memories"]["maxItems"], 20)
        self.assertGreater(self.store.session("alice", sid)["memory_seq"], 0)

    def test_truncated_model_output_cannot_advance_progress(self):
        from types import SimpleNamespace
        sid = self.case.create()
        self.case.send(sid, "你好。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        for finish_reason, refusal in (("length", None), ("stop", "declined")):
            with self.subTest(finish_reason=finish_reason, refusal=refusal):
                client = MagicMock()
                client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason=finish_reason, message=SimpleNamespace(content='{"memories":[]}', refusal=refusal))])
                self.service.client_factory = lambda runtime: client
                with self.assertRaises(ValueError):
                    self.service.memory.analyze(job)
                client.close.assert_called_once()
                self.assertEqual(self.store.session("alice", sid)["memory_seq"], 0)

    def test_same_slot_facts_cannot_be_enriched_into_two_graduation_years(self):
        self.save("我2027年毕业。", value="2027", key="graduation", kind="fact")
        old = self.store.memory_snapshot("alice")[1][0]
        _, candidate = self.candidate_for_text("我2026年毕业。", value="2026", key="graduation", kind="fact")
        with self.assertRaises(ValueError):
            validate_decision({"operation": "ENRICH", "target_id": old["id"], "value": "2027、2026"}, candidate[0], [old])

    def candidate_for_text(self, text, **kwargs):
        sid = self.case.create()
        self.case.send(sid, text)
        self.store.enqueue("alice", sid, immediate=True)
        return self.candidate(self.store.claim_job(kind="memory"), **kwargs)

    def test_questions_and_unrelated_correction_are_not_profile_changes(self):
        message = {"id": "m", "role": "user", "content": "上海的工作机会怎么样？"}
        item = {"kind": "preference", "key": "target_city", "subject": "profile", "value": "上海", "operation": "assert",
                "scope": "user", "confidence": .99, "evidence": [{"message_id": "m", "quote": "上海"}]}
        self.assertFalse(validate_candidates({"memories": [item]}, [message]))
        message["content"] = "更正城市为上海。我2026年毕业。"
        item.update(kind="fact", key="graduation", value="2026", operation="correct",
                    evidence=[{"message_id": "m", "quote": "我2026年毕业"}])
        self.assertEqual(validate_candidates({"memories": [item]}, [message])[0]["operation"], "assert")

    def test_semantic_match_cannot_authorize_deleting_another_project(self):
        self.save("我使用过LangGraph。", value="使用过LangGraph", key="experience", kind="fact", subject="项目一")
        old = self.store.memory_snapshot("alice")[1][0]
        _, candidates = self.candidate_for_text("请忘记项目二的经历。", value="项目二", key="experience", kind="fact", subject="项目二", operation="retract")
        with self.assertRaises(ValueError):
            validate_decision({"operation": "RETRACT", "target_id": old["id"], "value": old["value"]}, candidates[0], [old])

    def test_oversized_user_message_is_extracted_through_its_last_window(self):
        sid = self.case.create()
        self.case.send(sid, "这是一段技术讨论。" * 600 + "以后只考虑上海。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        calls = self.case.calls

        class Client(FakeClient):
            def create(self, **kwargs):
                if kwargs["messages"][0]["content"] == EXTRACTION_PROMPT:
                    calls.append(kwargs)
                    from types import SimpleNamespace
                    window = json.loads(kwargs["messages"][1]["content"])["messages"]
                    user = next((row for row in window if "以后只考虑上海" in row["content"]), None)
                    candidates = [] if user is None else [{"kind": "preference", "key": "target_city", "subject": "profile", "value": "上海",
                        "operation": "assert", "confidence": .99, "scope": "user", "evidence": [{"message_id": user["id"], "quote": "以后只考虑上海"}]}]
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"memories": candidates})))])
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: Client(calls)
        self.service.memory.analyze(job)
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "上海")
        extraction_calls = [call for call in calls if call["messages"][0]["content"] == EXTRACTION_PROMPT]
        self.assertGreater(len(extraction_calls), 1)
        self.assertTrue(all(sum(estimate_tokens(row["content"]) for row in call["messages"]) <= self.store.policy.input_tokens for call in extraction_calls))

    def test_idle_is_based_on_last_activity_and_explicit_changes_are_prioritized(self):
        sid = self.case.create()
        baseline = time.time()
        with patch("time.time", return_value=baseline):
            self.case.send(sid, "你好")
        with patch("time.time", return_value=baseline + 100):
            self.case.send(sid, "谢谢")
        with self.store.connect() as conn:
            rows = list(conn.execute("SELECT * FROM memory_jobs WHERE session_id=?", (sid,)))
        self.assertTrue(all(row["due_at"] == baseline + 1000 for row in rows))
        with patch("time.time", return_value=baseline + 200):
            self.case.send(sid, "请记住我想去杭州")
            job = self.store.claim_job()
        self.assertEqual((job["kind"], job["priority"], job["reason"]), ("memory", 100, "explicit"))

    def test_conflict_then_explicit_correction_resolves_even_same_value(self):
        self.save("我2027年毕业。", value="2027", key="graduation", kind="fact")
        original = self.store.memory_snapshot("alice")[1][0]
        self.save("我2026年就毕业了。", value="2026", key="graduation", kind="fact")
        self.assertEqual({row["status"] for row in self.store.memory_snapshot("alice")[1]}, {"active", "conflict"})
        self.assertFalse(self.service.memory.career_context("alice")["evidence"])
        self.save("更正一下，2027年才是正确的毕业时间。", value="2027", key="graduation", kind="fact", operation="correct")
        rows = self.store.memory_snapshot("alice")[1]
        self.assertEqual([(row["id"], row["status"]) for row in rows], [(original["id"], "active")])

    def test_retract_no_silent_restore_and_explicit_restore(self):
        self.save("我想去杭州。", value="杭州")
        self.save("请忘记我的目标城市。", value="杭州", operation="retract")
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.save("我想去杭州。", value="杭州")
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.save("请重新记住我的目标城市是杭州。", value="杭州", operation="correct")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "杭州")

    def test_sql_changes_update_and_remove_the_vector_index(self):
        from types import SimpleNamespace
        self.save("我想去杭州。", value="杭州")
        original = self.store.memory_snapshot("alice")[1][0]
        index = VectorMemory(self.case.temp.name)
        index.collection = MagicMock()
        index.embeddings = MagicMock()
        index.embeddings.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1., 0.])])
        index.model = "offline-embedding"
        self.addCleanup(index.close)
        index.sync(self.store)
        self.assertEqual(index.collection.upsert.call_args.kwargs["ids"], [original["id"]])
        self.save("现在只考虑上海。", value="上海", operation="correct")
        index.sync(self.store)
        self.assertIn("上海", index.collection.upsert.call_args.kwargs["documents"][0])
        self.store.forget("alice", original["id"])
        index.sync(self.store)
        self.assertTrue(self.store.cleanup_pending("alice"))
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertFalse(self.store.index_pending())

    def test_summary_commits_when_memory_extraction_fails(self):
        sid = self.case.create()
        self.case.send(sid)
        self.store.enqueue("alice", sid, immediate=True)
        calls = self.case.calls

        class Client(FakeClient):
            def create(self, **kwargs):
                if kwargs["messages"][0]["content"] == EXTRACTION_PROMPT:
                    raise ValueError("bad candidate output")
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: Client(calls)
        self.assertTrue(self.service.memory.run_once())
        self.service.memory.analyze(self.store.claim_job(kind="summary"))
        session = self.store.session("alice", sid)
        self.assertGreater(session["analyzed_seq"], 0)
        self.assertEqual(session["memory_seq"], 0)
        self.assertEqual(self.store.memory_status("alice")["memory"]["queued"], 1)
        self.assertEqual(self.store.memory_status("alice")["summary"]["done"], 1)

    def test_foreign_target_rolls_back_whole_plan(self):
        sid = self.case.create()
        self.case.send(sid, "我会Python，也考虑上海。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, first = self.candidate(job, value="Python", key="skill", kind="fact", subject="Python")
        _, second = self.candidate(job, value="上海")
        decisions = [{"operation": "ADD", "target_id": None, "value": "Python"},
                     {"operation": "REPLACE", "target_id": "another-account-memory", "value": "上海"}]
        with self.assertRaises(ValueError):
            self.store.apply_memory_plan(job, messages, first + second, decisions, 0)
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertFalse(self.store.memory_events("alice"))
        self.assertEqual(self.store.session("alice", sid)["memory_seq"], 0)

    def test_hypothetical_and_unsubstantiated_correction_are_not_facts(self):
        messages = [{"id": "m", "role": "user", "content": "如果我2026年毕业，应该找什么工作？"}]
        candidate = {"kind": "fact", "key": "graduation", "subject": "profile", "value": "2026", "operation": "correct",
                     "confidence": .99, "scope": "user", "evidence": [{"message_id": "m", "quote": "我2026年毕业"}]}
        self.assertEqual(validate_candidates({"memories": [candidate]}, messages), [])
        messages[0]["content"] = "我2026年毕业"
        self.assertEqual(validate_candidates({"memories": [candidate]}, messages)[0]["operation"], "assert")

    def test_profile_reuses_resume_after_restart_and_merges_chat_skills(self):
        file = Path(self.case.temp.name) / "resume.docx"
        file.write_bytes(b"resume version one")
        source = {"path": str(file), "document_id": "doc-one", "name": "resume.docx"}
        self.service.resume_provider = lambda owner: source if owner == "alice" else {}
        self.service.documents.current_source = self.service.resume_provider
        self.service.documents.reader = MagicMock(return_value={"status": "ok", "markdown": "本科，2027年毕业，Python"})
        self.service.documents.profile_extractor = MagicMock(return_value=[
            {"key": "graduation", "subject": "profile", "value": "2027", "evidence": {"quote": "2027年毕业"}},
            {"key": "skill", "subject": "Python", "value": "Python", "evidence": {"quote": "Python"}}])
        self.service.background("alice", read_resume=True)
        # Chat consumes the text immediately; structured extraction is background work.
        with self.service.documents.guard:
            tasks = list(self.service.documents.tasks.values())
        for task in tasks:
            task.join(timeout=3)
        restarted = ChatService(Path(self.case.temp.name), lambda selection: self.case.runtime,
                                lambda owner: {}, resume_provider=self.service.resume_provider)
        restarted.memory.cache.retry_at = restarted.memory.vector.retry_at = float("inf")
        self.addCleanup(restarted.memory.close)
        restarted.documents.reader = MagicMock(side_effect=AssertionError("do not reread"))
        restarted.documents.profile_extractor = MagicMock(side_effect=AssertionError("do not reextract"))
        background, _ = restarted.background("alice", read_resume=True)
        self.assertIn("2027", json.dumps(background, ensure_ascii=False))
        restarted.documents.reader.assert_not_called()
        restarted.documents.profile_extractor.assert_not_called()
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.save("我最近学会了Kubernetes。", value="Kubernetes", key="skill", kind="fact", subject="Kubernetes")
        profile = self.case.client.get("/api/chat/profile").json()
        self.assertTrue(any(row["subject"] == "Kubernetes" for row in profile["facts"]))
        self.save("我2026年就毕业了。", value="2026", key="graduation", kind="fact")
        profile = self.case.client.get("/api/chat/profile").json()
        self.assertEqual({row["value"] for row in profile["conflicts"]}, {"2027", "2026"})
        self.assertEqual(self.service.documents.snapshot("alice", source)["facts"][0]["value"], "2027")
        self.service.memory.vector.search = MagicMock(side_effect=AssertionError("identity facts do not require vector search"))
        _, trace = self.service.context("alice", self.case.create(), "我的毕业时间", with_trace=True)
        self.service.memory.vector.search.assert_not_called()
        self.assertFalse(any(row["key"] == "graduation" for row in trace["memories"]))
        self.assertNotIn("2026", self.service.career_context("alice")["evidence"])
        self.case.login("bob")
        self.assertFalse(self.case.client.get("/api/chat/profile").json()["facts"])
        self.assertFalse(self.case.client.get("/api/chat/memories/events").json()["items"])

    def test_existing_structured_resume_needs_no_profile_llm(self):
        file = Path(self.case.temp.name) / "resume.docx"
        file.write_bytes(b"resume")
        source = {"path": str(file), "text": "本科，Python", "structured_profile": {
            "education": [{"degree": "本科", "field_of_study": "计算机", "end_date": "2027"}],
            "skills": [{"skill_name": "Python"}]}}
        self.service.documents.profile_extractor = MagicMock(side_effect=AssertionError("must reuse structured profile"))
        self.service.documents.read("alice", source)
        snapshot = self.service.documents.snapshot("alice", source)
        self.assertEqual(snapshot["profile_status"], "ready")
        self.assertEqual(len(snapshot["facts"]), 4)
        self.service.documents.profile_extractor.assert_not_called()


class PolicyChecks(unittest.TestCase):
    def test_token_windows_preserve_a_long_messages_tail_and_identity(self):
        text = "讨论技术问题。" * 1000 + "以后只考虑上海。"
        windows = list(message_windows([{"id": "original", "role": "user", "content": text}], 3000))
        self.assertGreater(len(windows), 1)
        self.assertEqual("".join(row["content"] for window in windows for row in window), text)
        self.assertTrue(all(sum(estimate_tokens(row["content"]) for row in window) <= 3000 for window in windows))
        self.assertTrue(all(row["id"] == "original" for window in windows for row in window))

    def test_triggers_distinguish_information_volume_and_urgent_changes(self):
        policy = MemoryPolicy()
        rows = lambda text: [{"role": "user", "content": text, "created_at": 100}]
        self.assertEqual(policy.trigger(rows("你好"), kind="memory", now=100), (1000, 0, "idle"))
        self.assertEqual(policy.trigger(rows("请记住我的目标城市是杭州"), kind="memory", now=100)[2], "explicit")
        self.assertEqual(policy.trigger(rows("以后只考虑上海"), kind="memory", now=100)[2], "critical_change")
        self.assertEqual(policy.trigger(rows("x" * 12000), kind="memory", now=100)[2], "tokens")
        self.assertEqual(policy.trigger(rows("假设我已经毕业了"), kind="memory", now=100)[2], "idle")
        self.assertEqual(policy.trigger(rows("请记住杭州"), kind="summary", now=100)[2], "idle")
        self.assertEqual(policy.trigger(rows("你好"), kind="memory", immediate=True, now=100)[2], "finish")
        with patch.dict("os.environ", {"CHAT_MEMORY_TOKEN_THRESHOLD": "2200"}):
            self.assertEqual(MemoryPolicy.from_env().token_threshold, 2200)

    def test_legacy_jobs_and_document_cache_migrate_without_loss(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            store = ChatStore(path)
            sid = store.create_session("alice")["id"]
            with store.connect(write=True) as conn:
                conn.execute("UPDATE sessions SET summary='old summary',analyzed_seq=7 WHERE id=?", (sid,))
                conn.execute("ALTER TABLE sessions DROP COLUMN memory_seq")
                conn.execute("DROP TABLE memory_jobs")
                conn.execute("""CREATE TABLE memory_jobs(session_id TEXT PRIMARY KEY,due_at REAL,status TEXT,
                    token TEXT,lease_until REAL,attempts INTEGER,requested_seq INTEGER)""")
                conn.execute("INSERT INTO memory_jobs VALUES(?,0,'running','old-token',100,2,9)", (sid,))
                conn.execute("""CREATE TABLE resume_documents(owner TEXT,fingerprint TEXT,status TEXT,content TEXT,
                    metadata TEXT,error TEXT,updated_at REAL,PRIMARY KEY(owner,fingerprint))""")
                conn.execute("INSERT INTO resume_documents VALUES('alice','hash','ready','saved resume','{}','',0)")
            upgraded = ChatStore(path)
            self.assertEqual(upgraded.session("alice", sid)["memory_seq"], 7)
            self.assertEqual(upgraded.session("alice", sid)["summary"], "old summary")
            self.assertEqual(upgraded.memory_status("alice")["queued"], 2)
            self.assertEqual(ResumeRepository(path).get("alice", "hash")["content"], "saved resume")
            self.assertEqual(ChatStore(path).session("alice", sid)["memory_seq"], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
