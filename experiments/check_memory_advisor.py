"""真实 Redis + Chroma 的本地回归检查，不调用收费模型。

先在项目根目录运行 docker compose up -d redis，再运行 python -m experiments.check_memory_advisor。
仅删除本次检查专用的 Redis 前缀；Chroma 检查数据位于 experiments/output/memory_checks。
"""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import chromadb
from chromadb.config import Settings
import httpx
from langgraph.checkpoint.memory import InMemorySaver
from redis.asyncio import Redis

from .memory_app import create_memory_app
from .news_advisor.graph import AGENTS, AgentExecutionError, build_advisor_graph
from .news_advisor.memory.config import MemoryConfig, get_memory_config
from .news_advisor.memory.llm import MemoryLLM
from .news_advisor.memory.long_term import LongTermMemory
from .news_advisor.memory.recent import MemoryBusyError, RecentMemory
from .news_advisor.memory.schemas import MemoryCandidate, MemoryExtraction
from .news_advisor.memory.service import MemoryService, user_material
from .news_advisor.schemas.career_decision import CareerDecisionInput
from .news_advisor.schemas.job import JobAnalysisInput
from .news_advisor.schemas.resume import ResumeInput


class FixedEmbeddings:
    async def aembed_documents(self, texts):
        return [[1., 0., 0.] for _ in texts]

    async def aembed_query(self, text):
        return [1., 0., 0.]


class FixtureLLM:
    def __init__(self):
        self.summaries = 0
        self.fail_summary = False

    async def extract(self, text, existing):
        if "杭州" in text:
            return [MemoryCandidate(kind="preference", key="target_city", value="杭州", evidence="杭州")]
        if "上海" in text:
            return [MemoryCandidate(kind="preference", key="target_city", value="上海", evidence="上海")]
        return []

    async def summarize(self, previous, turns):
        if self.fail_summary:
            raise RuntimeError("模拟摘要服务故障")
        self.summaries += 1
        return previous + "|" + ";".join(turn["user"] for turn in turns)


class MemoryChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.run_id = uuid4().hex
        self.config = MemoryConfig(data_dir=Path(__file__).resolve().parent / "output" / "memory_checks" / self.run_id,
                                   recent_turns=2)
        self.config.data_dir.mkdir(parents=True)
        self.redis = Redis.from_url(get_memory_config().redis_url, decode_responses=True)
        await self.redis.ping()
        client = chromadb.PersistentClient(path=str(self.config.data_dir / "chroma"),
                                           settings=Settings(anonymized_telemetry=False))
        self.collection = client.create_collection("memory_checks", embedding_function=None,
                                                   metadata={"hnsw:space": "cosine"})
        self.recent = RecentMemory(self.redis, ttl=300, recent_turns=2, prefix="career:memory:check:" + self.run_id)
        self.now = 1800000000.
        self.long = LongTermMemory(self.collection, FixedEmbeddings(), clock=lambda: self.now)
        self.llm = FixtureLLM()
        self.service = MemoryService(self.recent, self.long, self.llm)

    async def asyncTearDown(self):
        keys = [key async for key in self.redis.scan_iter(match=self.recent.prefix + ":*")]
        if keys:
            await self.redis.delete(*keys)
        await self.redis.aclose()

    def candidate(self, value, *, kind="preference", key="target_city", operation="assert"):
        return MemoryCandidate(kind=kind, key=key, value=value, evidence="用户明确陈述：" + value, operation=operation)

    async def write(self, candidate, *, user="alice", session="one", event=None):
        async with self.recent.lock(user):
            return await self.long.apply(user, session, [candidate], event or uuid4().hex)

    async def test_preference_update_dedup_and_history(self):
        await self.write(self.candidate("上海"))
        change = await self.write(self.candidate("上海"))
        self.assertEqual(change[0]["action"], "duplicate")
        self.assertEqual((await self.long.records("alice"))[0]["revision"], 1)
        change = await self.write(self.candidate("杭州"), session="two")
        self.assertEqual(change[0]["action"], "updated")
        self.assertEqual((await self.long.records("alice"))[0]["value"], "杭州")
        self.assertEqual((await self.long.records("alice", status="superseded"))[0]["value"], "上海")

    async def test_fact_conflict_requires_correction(self):
        await self.write(self.candidate("2027", kind="fact", key="graduation"))
        change = await self.write(self.candidate("2028", kind="fact", key="graduation"))
        self.assertEqual(change[0]["action"], "conflict")
        context = await self.service.prepare("alice", "two", "", "毕业", "read-conflict")
        self.assertTrue(context["conflicts"])
        self.assertFalse(context["recalled"])
        await self.write(self.candidate("2028", kind="fact", key="graduation", operation="correct"))
        self.assertEqual((await self.long.records("alice"))[0]["value"], "2028")
        self.assertFalse(await self.long.records("alice", status="conflict"))
        self.assertTrue(await self.long.records("alice", status="resolved"))

    async def test_user_isolation_and_cross_session_recall(self):
        await self.write(self.candidate("上海"))
        await self.write(self.candidate("北京"), user="bob")
        recalled = await self.long.recall("alice", "职业城市偏好")
        self.assertEqual([row["value"] for row in recalled], ["上海"])
        context = await self.service.prepare("alice", "new-session", "", "城市", "new-turn")
        self.assertEqual(context["preferences"][0]["value"], "上海")
        self.assertFalse(await self.long.recall("unknown", "城市"))
        self.assertNotEqual(self.recent.key("a:b", "c"), self.recent.key("a", "b:c"))

    async def test_old_event_replay_cannot_roll_back_new_memory(self):
        first = await self.write(self.candidate("上海"), event="old-event")
        await self.write(self.candidate("杭州"), event="new-event")
        replay = await self.write(self.candidate("上海"), event="old-event")
        self.assertEqual(first, replay)
        self.assertEqual((await self.long.records("alice"))[0]["value"], "杭州")

    async def test_time_decay_ranking(self):
        await self.write(self.candidate("上海"))
        self.now += 180 * 86400
        await self.write(self.candidate("远程", key="work_style"))
        recalled = await self.long.recall("alice", "工作偏好")
        self.assertEqual(recalled[0]["key"], "work_style")
        self.assertAlmostEqual(recalled[1]["recency"], .25)

    async def test_retraction_not_recalled(self):
        await self.write(self.candidate("上海"))
        await self.write(self.candidate("上海", operation="retract"))
        self.assertFalse(await self.long.recall("alice", "城市"))
        self.assertTrue(await self.long.records("alice", status="retracted"))

    async def test_recent_summary_ttl_and_idempotence(self):
        for index in range(4):
            await self.service.finish("alice", "one", str(index), f"user-{index}", "建议")
        await self.service.finish("alice", "one", "3", "user-3", "建议")
        stored = await self.recent.load("alice", "one")
        self.assertEqual([turn["user"] for turn in stored["turns"]], ["user-2", "user-3"])
        self.assertIn("user-0", stored["summary"])
        self.assertEqual(self.llm.summaries, 2)
        self.assertGreater(await self.redis.ttl(self.recent.key("alice", "one")), 0)
        self.assertFalse((await self.recent.load("bob", "one"))["turns"])

    async def test_summary_failure_preserves_history_and_retries(self):
        for index in range(2):
            await self.service.finish("alice", "one", str(index), str(index), "建议")
        self.llm.fail_summary = True
        with self.assertRaises(RuntimeError):
            await self.service.finish("alice", "one", "2", "2", "建议")
        self.assertEqual(len((await self.recent.load("alice", "one"))["turns"]), 2)
        self.llm.fail_summary = False
        await self.service.finish("alice", "one", "2", "2", "建议")
        self.assertEqual(self.llm.summaries, 1)

    async def test_lock_rejects_concurrent_writer(self):
        async with self.recent.lock("alice"):
            with self.assertRaises(MemoryBusyError):
                async with self.recent.lock("alice"):
                    self.fail("不能进入重叠锁")
        async with self.recent.lock("alice"):
            pass

    async def test_ungrounded_llm_memory_is_rejected(self):
        class BadModel:
            def with_structured_output(self, *args, **kwargs):
                return self

            async def ainvoke(self, messages):
                return MemoryExtraction(memories=[MemoryCandidate(kind="fact", key="education", value="硕士", evidence="不存在的证据")])

        with self.assertRaisesRegex(ValueError, "证据"):
            await MemoryLLM(BadModel).extract("我喜欢上海", [])
        text = user_material({"input": {"job_description": "要求博士", "raw_resume": "本科毕业", "decision_result": "擅长Python"}})
        self.assertIn("本科毕业", text)
        self.assertNotIn("博士", text)
        self.assertNotIn("Python", text)

    async def test_graph_memory_injection_and_retry(self):
        attempts = []

        class FakeAgent:
            system_prompt = "简历分析"

            def __init__(self, model):
                pass

            async def arun(agent, payload, config=None):
                attempts.append((payload, agent.system_prompt))
                if len(attempts) == 1:
                    return {"agent": "resume_analysis", "status": "model_error", "data": {}}
                return {"agent": "resume_analysis", "status": "ok", "data": {"summary": "完成"}}

        self.assertEqual(len(AGENTS), 5)
        cfg = {"configurable": {"thread_id": "graph-check", "user_id": "alice", "session_id": "one"}}
        with patch.dict(AGENTS, {"resume_analysis": (ResumeInput, FakeAgent)}):
            graph = build_advisor_graph(lambda: None, checkpointer=InMemorySaver(), memory=self.service)
            with self.assertRaises(AgentExecutionError):
                await graph.ainvoke({"request": {"agent": "resume_analysis", "input": {"raw_resume": "本科毕业"},
                                                 "message": "我想去上海"}}, cfg)
            self.assertEqual((await graph.aget_state(cfg)).next, ("resume_analysis",))
            await graph.ainvoke(None, cfg)
        self.assertIn("上海", attempts[1][1])
        self.assertIn("我想去上海", attempts[1][0]["additional_evidence"])
        self.assertEqual(len((await self.recent.load("alice", "one"))["turns"]), 1)

    async def test_new_preference_does_not_reuse_injected_old_input(self):
        seen = []

        class FakeAgent:
            system_prompt = "职业决策"

            def __init__(self, model):
                pass

            async def arun(agent, payload, config=None):
                seen.append(payload)
                return {"agent": "career_decision", "status": "ok", "data": {"summary": "完成"}}

        cfg = {"configurable": {"thread_id": "preference-check", "user_id": "alice", "session_id": "one"}}
        with patch.dict(AGENTS, {"career_decision": (CareerDecisionInput, FakeAgent)}):
            graph = build_advisor_graph(lambda: None, checkpointer=InMemorySaver(), memory=self.service)
            await graph.ainvoke({"request": {"agent": "career_decision", "message": "我想去上海",
                                             "input": {"targets": [{"target_id": "backend", "title": "后端", "job_analysis": {}}]}}}, cfg)
            await graph.ainvoke({"request": {"agent": "career_decision", "message": "现在只考虑杭州", "input": {}}}, cfg)
        self.assertEqual([payload["preferences"] for payload in seen], ["上海", "杭州"])
        state = await graph.aget_state(cfg)
        self.assertEqual(state.values["inputs"]["career_decision"]["preferences"], "")
        self.assertEqual(state.values["executed_inputs"]["career_decision"]["preferences"], "杭州")

    async def test_job_node_and_original_graph_without_memory(self):
        class FakeAgent:
            def __init__(self, model):
                pass

            async def arun(agent, payload, config=None):
                return {"agent": "job_analysis", "status": "ok", "data": {"summary": payload["target_role"]}}

        with patch.dict(AGENTS, {"job_analysis": (JobAnalysisInput, FakeAgent)}):
            graph = build_advisor_graph(lambda: None, checkpointer=InMemorySaver())
            result = await graph.ainvoke({"request": {"agent": "job_analysis", "input": {"target_role": "后端"}}},
                                         {"configurable": {"thread_id": "original"}})
        self.assertEqual(result["results"]["job_analysis"]["data"]["summary"], "后端")

    async def test_api_thread_scoping_and_checkpoint_conflicts(self):
        class FakeAgent:
            system_prompt = "简历分析"

            def __init__(self, model):
                pass

            async def arun(agent, payload, config=None):
                return {"agent": "resume_analysis", "status": "ok", "data": {"summary": "完成"}}

        @asynccontextmanager
        async def factory(provider, config):
            yield self.service

        app = create_memory_app(lambda: None, config=self.config, memory_factory=factory)
        with patch.dict(AGENTS, {"resume_analysis": (ResumeInput, FakeAgent)}):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                    base = "/api/memory-advisor/users"
                    response = await client.post(base + "/alice/threads/same", json={
                        "agent": "resume_analysis", "input": {"raw_resume": "本科毕业"}, "message": "想去上海",
                    })
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual((await client.get(base + "/bob/threads/same")).status_code, 404)
                    response = await client.post(base + "/alice/threads/same", json={
                        "agent": "resume_analysis", "checkpoint_id": "stale", "input": {},
                    })
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual((await client.get("/health")).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
