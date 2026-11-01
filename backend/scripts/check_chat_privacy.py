"""Deletion controls, suppression, durable cleanup and in-flight work fences."""

import fnmatch
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat_pipeline import PipelineChecks
from services.chat.cache import RecentCache
from services.chat.storage import ChatError, ChatStore


class RedisStub:
    def __init__(self):
        self.data = {}
        self.failed = False

    def ping(self):
        if self.failed:
            raise ConnectionError("offline")
        return True

    def get(self, key):
        self.ping()
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.ping()
        self.data[key] = value

    def delete(self, *keys):
        self.ping()
        return sum(self.data.pop(key, None) is not None for key in keys)

    def scan_iter(self, match, count):
        self.ping()
        return iter([key for key in self.data if fnmatch.fnmatch(key, match)])

    def close(self):
        pass


class VectorStub:
    def __init__(self):
        self.records = {}
        self.failed = False

    def search(self, owner, query, *, epoch=0):
        return [key for key, row in self.records.items() if row["owner"] == owner and row["privacy_epoch"] == epoch]

    def sync(self, store):
        for row in store.index_pending():
            self.records[row["id"]] = row
            store.mark_indexed(row["id"], row["revision"])

    def delete_owner(self, owner):
        if self.failed:
            raise RuntimeError("offline vector index")
        self.records = {key: row for key, row in self.records.items() if row["owner"] != owner}

    def status(self):
        return {"state": "ready", "message": "offline fixture", "error_code": ""}

    def close(self):
        pass


class PrivacyChecks(unittest.TestCase):
    def setUp(self):
        self.pipeline = PipelineChecks(methodName="runTest")
        self.pipeline.setUp()
        self.addCleanup(self.pipeline.doCleanups)
        self.case = self.pipeline.case
        self.service = self.case.service
        self.store = self.service.store
        self.redis = RedisStub()
        self.vector = VectorStub()
        self.service.memory.cache = RecentCache(client=self.redis)
        self.service.memory.vector = self.vector

    def seed(self, text="我希望在杭州实习。"):
        sid = self.pipeline.save(text, value="杭州")
        memory = self.store.memory_snapshot("alice")[1][0]
        self.vector.sync(self.store)
        self.store.save_context_trace("alice", sid, "fixture", {"memories": [{"value": "杭州"}]}, epoch=self.store.privacy("alice")["epoch"])
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE sessions SET summary='用户想去杭州' WHERE id=?", (sid,))
        return sid, memory

    def ready_cleanup(self):
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE cleanup_jobs SET due_at=0 WHERE status IN ('queued','retrying')")

    def complete(self, task):
        self.ready_cleanup()
        self.assertTrue(self.service.memory.run_once())
        self.assertEqual(self.store.cleanup_status("alice", task)["status"], "completed")

    def dump(self):
        with self.store.connect() as conn:
            return "\n".join(conn.iterdump())

    def test_forget_immediately_excludes_old_history_and_scrubs_values(self):
        sid, memory = self.seed()
        response = self.case.api("DELETE", f"/api/chat/memories/{memory['id']}")
        self.assertEqual(response.status_code, 202)
        result = response.json()
        self.assertEqual(result["status"], "accepted")
        self.assertNotEqual(result["task"]["status"], "completed")
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertFalse(self.store.memory_events("alice"))
        self.assertIsNone(self.store.context_trace("alice", sid))
        self.assertEqual(self.store.session("alice", sid)["summary"], "")
        self.assertNotIn("杭州", json.dumps(self.service.context("alice", sid, "你记得什么"), ensure_ascii=False))
        self.assertIn("杭州", json.dumps(self.store.messages("alice", sid), ensure_ascii=False))
        with self.store.connect() as conn:
            suppression = dict(conn.execute("SELECT * FROM memory_suppressions WHERE owner='alice'").fetchone())
        self.assertNotIn("杭州", json.dumps(suppression, ensure_ascii=False))
        self.assertGreater(suppression["source_cutoff_seq"], 0)
        self.complete(result["task"]["id"])
        self.assertFalse(self.vector.records)

    def test_idempotent_delete_and_account_scoped_control_endpoints(self):
        sid, memory = self.seed()
        first = self.case.api("DELETE", f"/api/chat/memories/{memory['id']}").json()
        second = self.case.api("DELETE", f"/api/chat/memories/{memory['id']}").json()
        self.assertEqual(first["task"]["id"], second["task"]["id"])
        self.case.login("bob")
        self.assertEqual(self.case.api("DELETE", f"/api/chat/memories/{memory['id']}").status_code, 404)
        self.assertEqual(self.case.api("PATCH", f"/api/chat/memories/{memory['id']}", {"value": "上海"}).status_code, 404)
        self.assertEqual(self.case.client.get(first["status_url"]).status_code, 404)
        self.case.login("alice")
        self.assertEqual(self.case.client.delete("/api/chat/chat-data").status_code, 403)
        self.assertEqual(self.case.client.patch("/api/chat/source-settings", json={"workspace_enabled": True, "resume_enabled": True}).status_code, 403)
        self.case.login(None)
        self.assertEqual(self.case.api("DELETE", "/api/chat/chat-data").status_code, 401)

    def test_old_jobs_and_backfill_cannot_recreate_forgotten_values(self):
        sid, memory = self.seed()
        pending = self.case.create()
        self.case.send(pending, "我还是希望在杭州实习。")
        self.store.enqueue("alice", pending, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.pipeline.candidate(job, value="杭州")
        task = self.service.memory.forget("alice", memory["id"])
        self.assertFalse(self.store.apply_memory_plan(job, messages, candidates,
            [{"operation": "ADD", "target_id": None, "value": "杭州"}], self.store.memory_snapshot("alice")[0]))
        self.store.enqueue("alice", pending, immediate=True)
        self.assertIsNone(self.store.claim_job(kind="memory"))
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertFalse(self.store.memory_events("alice"))
        self.pipeline.save("我想去杭州。", value="杭州")
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.pipeline.save("请重新记住我的目标城市是上海。", value="上海", operation="correct")
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "上海")
        self.complete(task)
        self.vector.sync(self.store)
        self.assertEqual(next(iter(self.vector.records.values()))["value"], "上海")

    def test_purge_removes_original_evidence_reply_and_derived_records(self):
        sid, memory = self.seed("我会Python，希望在杭州实习。")
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE sessions SET memory_seq=0 WHERE id=?", (sid,))
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.pipeline.candidate(job, value="Python", key="skill", kind="fact", subject="Python")
        self.service.memory.commit_candidates(job, messages, candidates)
        self.assertEqual(len(self.store.memory_snapshot("alice")[1]), 2)
        result = self.case.api("DELETE", f"/api/chat/memories/{memory['id']}?mode=purge").json()
        self.assertFalse(self.store.messages("alice", sid)["items"])
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertNotIn("杭州", self.dump())
        self.complete(result["task"]["id"])
        self.assertNotIn("杭州", self.dump())

    def test_forget_can_be_escalated_to_purge_after_cleanup(self):
        sid, memory = self.seed()
        first = self.service.memory.forget("alice", memory["id"])
        self.complete(first)
        second = self.service.memory.forget("alice", memory["id"], mode="purge")
        self.assertNotEqual(first, second)
        self.assertFalse(self.store.messages("alice", sid)["items"])
        self.assertNotIn("杭州", self.dump())
        self.complete(second)

    def test_redis_and_vector_failures_remain_retryable_after_restart(self):
        sid, memory = self.seed()
        task = self.service.memory.forget("alice", memory["id"])
        self.vector.failed = True
        self.service.memory.run_once()
        self.assertEqual(self.store.cleanup_status("alice", task)["status"], "retrying")
        restarted = ChatStore(self.store.path)
        self.assertEqual(restarted.cleanup_status("alice", task)["status"], "retrying")
        self.assertNotIn("杭州", json.dumps(self.service.context("alice", sid, "回忆城市"), ensure_ascii=False))
        self.vector.failed = False
        self.redis.failed = True
        self.ready_cleanup()
        self.service.memory.run_once()
        self.assertEqual(self.store.cleanup_status("alice", task)["error_code"], "ConnectionError")
        self.redis.failed = False
        self.complete(task)

    def test_active_artifact_writes_are_fenced_and_cleanup_waits(self):
        sid, memory = self.seed()
        lease = self.store.begin_artifact("alice", "index")
        task = self.service.memory.forget("alice", memory["id"])
        self.assertFalse(self.store.artifact_valid(lease))
        self.assertIsNone(self.store.begin_artifact("alice", "cache"))
        self.service.memory.run_once()
        self.assertEqual(self.store.cleanup_status("alice", task)["error_code"], "CleanupBusy")
        self.store.end_artifact(lease)
        self.complete(task)
        new = self.store.begin_artifact("alice", "index")
        self.assertGreater(new["epoch"], lease["epoch"])
        self.store.end_artifact(new)

    def test_manual_correction_invalidates_old_jobs_and_preserves_slot_id(self):
        sid, memory = self.seed()
        other = self.case.create()
        self.case.send(other, "我想去北京。")
        self.store.enqueue("alice", other, immediate=True)
        old = self.store.claim_job(kind="memory")
        result = self.case.api("PATCH", f"/api/chat/memories/{memory['id']}", {"value": "上海", "owner": "bob"})
        self.assertEqual(result.status_code, 202)
        current = self.store.memory_snapshot("alice")[1][0]
        self.assertEqual((current["id"], current["value"]), (memory["id"], "上海"))
        self.assertEqual(self.case.api("PATCH", f"/api/chat/memories/{memory['id']}", {"value": "上海"}).json()["task"]["id"], result.json()["task"]["id"])
        with self.assertRaises(ChatError):
            self.store.renew_job(old)
        prompt = json.dumps(self.service.context("alice", sid, "我的目标"), ensure_ascii=False)
        self.assertIn("上海", prompt)
        self.assertNotIn("杭州", prompt)

    def test_session_delete_keeps_memory_and_is_idempotent(self):
        sid, memory = self.seed()
        first = self.case.api("DELETE", f"/api/chat/sessions/{sid}")
        self.assertEqual(first.status_code, 202)
        second = self.case.api("DELETE", f"/api/chat/sessions/{sid}")
        self.assertEqual(first.json()["task"]["id"], second.json()["task"]["id"])
        self.assertEqual(self.store.memory_snapshot("alice")[1][0]["value"], "杭州")
        self.complete(first.json()["task"]["id"])

    def test_clear_chat_is_owned_complete_and_preserves_independent_resume(self):
        sid, memory = self.seed()
        self.service.documents.repository.save("alice", "resume-hash", status="ready", content="独立简历")
        bob = self.store.create_session("bob")["id"]
        self.redis.data[RecentCache.key("bob", bob)] = "bob-cache"
        self.redis.data[RecentCache.legacy_key("alice", "orphan")] = json.dumps({"items": [{"session_id": "orphan", "content": "杭州"}]})
        result = self.case.api("DELETE", "/api/chat/chat-data").json()
        self.assertFalse(self.store.list_sessions("alice"))
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertEqual(len(self.store.list_sessions("bob")), 1)
        self.assertEqual(self.service.documents.repository.get("alice", "resume-hash")["content"], "独立简历")
        self.assertEqual(self.store.privacy("alice")["resume_enabled"], 0)
        self.assertEqual(self.case.api("DELETE", "/api/chat/chat-data").json()["task"]["id"], result["task"]["id"])
        self.complete(result["task"]["id"])
        self.assertEqual(list(self.redis.data), [RecentCache.key("bob", bob)])
        self.assertNotIn("杭州", self.dump())
        for table in ("memories", "memory_events", "memory_suppressions", "memory_sources"):
            with self.store.connect() as conn:
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE owner='alice'").fetchone()[0], 0)

    def test_stream_started_before_forget_cannot_finish_or_recreate_trace(self):
        sid, memory = self.seed()
        request_id = "11111111-1111-4111-8111-111111111111"
        turn = self.store.begin_turn("alice", sid, request_id, "你好", {})
        stream = self.service.stream("alice", sid, request_id, turn["token"], "你好", self.case.runtime)
        self.assertEqual(next(stream)["type"], "start")
        self.service.memory.forget("alice", memory["id"])
        remaining = list(stream)
        self.assertFalse(any(event["type"] == "delta" for event in remaining))
        self.assertIsNone(self.store.context_trace("alice", sid))
        with self.assertRaises(ChatError):
            self.store.finish_turn("alice", sid, request_id, turn["token"], "stale answer")

    def test_unidentifiable_legacy_cache_prevents_false_completion(self):
        sid, memory = self.seed()
        self.redis.data["career:chat:v1:unknown"] = "invalid legacy personal data"
        task = self.service.memory.forget("alice", memory["id"])
        self.service.memory.run_once()
        self.assertEqual(self.store.cleanup_status("alice", task)["error_code"], "LegacyCachePending")
        del self.redis.data["career:chat:v1:unknown"]  # Simulate its original TTL expiring.
        self.complete(task)

    def test_sources_only_resume_after_explicit_user_control(self):
        sid, memory = self.seed()
        task = self.service.memory.forget("alice", memory["id"])
        self.assertEqual(self.case.client.get("/api/chat/profile").json()["resume_status"], "paused")
        response = self.case.api("PATCH", "/api/chat/source-settings", {"workspace_enabled": True, "resume_enabled": True})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.store.privacy("alice")["workspace_enabled"], 1)

    def test_legacy_soft_retraction_is_upgraded_to_value_free_cleanup(self):
        sid, memory = self.seed()
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE memories SET status='retracted' WHERE id=?", (memory["id"],))
        upgraded = ChatStore(self.store.path)
        with upgraded.connect() as conn:
            self.assertFalse(conn.execute("SELECT 1 FROM memories WHERE id=?", (memory["id"],)).fetchone())
        self.assertEqual(upgraded.cleanup_count("alice"), 1)
        self.assertEqual(upgraded.privacy("alice")["resume_enabled"], 0)

    def test_usage_tracking_purges_later_replies_even_when_wording_differs(self):
        sid, memory = self.seed()
        later = self.case.create()
        request = "22222222-2222-4222-8222-222222222222"
        turn = self.store.begin_turn("alice", later, request, "我的偏好是什么？", {})
        self.store.save_context_trace("alice", later, request, {"supplied_memory_ids": [memory["id"]]}, epoch=0)
        self.store.finish_turn("alice", later, request, turn["token"], "你想去那座西湖边的城市。")
        self.service.memory.forget("alice", memory["id"], mode="purge")
        self.assertFalse(self.store.messages("alice", later)["items"])
        self.assertNotIn("西湖", self.dump())

    def test_memory_change_during_stream_prevents_later_chunks(self):
        sid, memory = self.seed()
        service = self.service

        class Stream:
            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="正常片段"))])
                service.memory.forget("alice", memory["id"])
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="杭州旧信息"))])

            def close(self):
                pass

        class Client:
            def __init__(self):
                self.chat = SimpleNamespace(completions=self)

            def create(self, **kwargs):
                return Stream()

            def close(self):
                pass

        self.service.client_factory = lambda runtime: Client()
        response = self.case.api("POST", f"/api/chat/sessions/{sid}/messages",
            {"content": "请回答", "request_id": "33333333-3333-4333-8333-333333333333"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("正常片段", response.text)
        self.assertNotIn("杭州旧信息", response.text)
        self.assertIn('"type": "error"', response.text)

    def test_user_can_resolve_a_conflicting_memory_directly(self):
        self.pipeline.save("我2027年毕业。", value="2027", key="graduation", kind="fact")
        self.pipeline.save("我2026年就毕业了。", value="2026", key="graduation", kind="fact")
        conflicting = next(row for row in self.store.memory_snapshot("alice")[1] if row["status"] == "conflict")
        result = self.case.api("PATCH", f"/api/chat/memories/{conflicting['id']}", {"value": "2026"})
        self.assertEqual(result.status_code, 202)
        rows = self.store.memory_snapshot("alice")[1]
        self.assertEqual([(row["value"], row["status"]) for row in rows], [("2026", "active")])

    def test_clear_preserves_another_accounts_identical_fact_and_artifacts(self):
        sid, memory = self.seed()
        self.case.login("bob")
        bob_sid = self.case.create()
        self.case.send(bob_sid, "我也希望在杭州实习。")
        self.store.enqueue("bob", bob_sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.pipeline.candidate(job, value="杭州")
        self.service.memory.commit_candidates(job, messages, candidates)
        self.service.context("bob", bob_sid, "我的目标城市")
        self.assertTrue(any(key.startswith(RecentCache.owner_prefix("bob")) for key in self.redis.data))
        self.vector.sync(self.store)
        self.case.login("alice")
        task = self.service.memory.delete_owner("alice")
        self.complete(task)
        self.assertEqual(self.store.memory_snapshot("bob")[1][0]["value"], "杭州")
        self.assertIn("杭州", json.dumps(self.store.messages("bob", bob_sid), ensure_ascii=False))
        self.assertTrue(any(row["owner"] == "bob" for row in self.vector.records.values()))
        self.assertTrue(any(key.startswith(RecentCache.owner_prefix("bob")) for key in self.redis.data))

    def test_expired_cleanup_ack_cannot_complete_a_newer_task(self):
        sid, memory = self.seed()
        first = self.service.memory.forget("alice", memory["id"])
        stale = self.store.claim_cleanup()
        with self.store.connect(write=True) as conn:
            conn.execute("UPDATE cleanup_jobs SET lease_until=0 WHERE id=?", (first,))
            conn.execute("UPDATE artifact_leases SET lease_until=0 WHERE token=?", (stale["token"],))
        newer = self.store.claim_cleanup()
        self.assertNotEqual(newer["token"], stale["token"])
        self.assertFalse(self.store.finish_cleanup(stale))
        self.assertEqual(self.store.cleanup_status("alice", first)["status"], "running")
        self.store.finish_cleanup(newer, error=ConnectionError())
        self.complete(first)

    def test_retract_before_first_extraction_also_creates_protection(self):
        sid = self.case.create()
        self.case.send(sid, "我想去杭州实习。")
        self.case.send(sid, "请忘记我的目标城市，杭州不再记录。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.pipeline.candidate(job, value="杭州", operation="retract")
        self.assertTrue(self.service.memory.commit_candidates(job, messages, candidates))
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertEqual(self.store.cleanup_count("alice"), 1)
        self.assertNotIn("杭州", json.dumps(self.service.context("alice", sid, "回忆目标"), ensure_ascii=False))

    def test_retraction_revokes_remaining_candidates_in_the_same_batch(self):
        sid, memory = self.seed()
        other = self.case.create()
        self.case.send(other, "请忘记我的目标城市。另外我会Python。")
        self.store.enqueue("alice", other, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, retract = self.pipeline.candidate(job, value="杭州", operation="retract")
        _, skill = self.pipeline.candidate(job, value="Python", key="skill", kind="fact", subject="Python")
        self.assertTrue(self.service.memory.commit_candidates(job, messages, retract + skill))
        self.assertFalse(self.store.memory_snapshot("alice")[1])
        self.assertFalse(self.store.memory_events("alice"))

    def test_restoration_does_not_allow_mixed_old_and_new_evidence(self):
        sid, memory = self.seed()
        old = next(row for row in self.store.messages("alice", sid)["items"] if row["role"] == "user")
        self.service.memory.forget("alice", memory["id"])
        self.case.send(sid, "请重新记住我的目标城市是上海。")
        self.store.enqueue("alice", sid, immediate=True)
        job = self.store.claim_job(kind="memory")
        messages, candidates = self.pipeline.candidate(job, value="上海", operation="correct")
        self.service.memory.commit_candidates(job, messages, candidates)
        candidate = {**candidates[0], "operation": "assert", "evidence": [
            {"message_id": old["id"], "quote": old["content"]}, *candidates[0]["evidence"]]}
        history = self.store.messages("alice", sid)["items"]
        self.assertFalse(self.store.candidate_allowed("alice", candidate, history))
        self.assertTrue(self.store.candidate_allowed("alice", candidates[0], history))


if __name__ == "__main__":
    unittest.main(verbosity=2)
