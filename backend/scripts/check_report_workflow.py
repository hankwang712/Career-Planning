"""离线回归检查：使用临时 SQLite 与确定性替身，不调用模型、网页或业务数据库。

运行：python backend/scripts/check_report_workflow.py
"""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from backend.services.report import workflow
from backend.services.report.provenance import content_revision, freeze_profile
from experiments.news_advisor.agents.action_planning import ActionPlanningAgent, verify_action_plan
from experiments.news_advisor.agents.base import BaseAgent
from experiments.news_advisor.agents.career_decision import CareerDecisionAgent, recruitment_context, verify_career_decision
from experiments.news_advisor.agents.job import verify_job_evidence
from experiments.news_advisor.report_workflow import build_report_graph
from experiments.news_advisor.schemas.action_planning import ActionPlan
from experiments.news_advisor.telemetry import AgentMetrics, summarize_executions


RESUME = "我已使用 Python 开发一个 API 服务。"
JOB = "岗位要求：熟悉 Python。"
QUESTION = "希望在哪个城市实习？"


def search_result():
    return {"agent": "recruitment_search", "status": "ok", "data": {
        "outcome": "found", "summary": "发现招聘线索", "intent": {},
        "findings": [{"source_id": "S1", "match_status": "needs_confirmation", "summary": "Python 实习",
                      "relevance": "方向相关", "evidence_quotes": ["招聘 Python 实习生"],
                      "unverified_conditions": ["到岗时间待核实"]}], "followup_questions": [QUESTION]},
        "sources": [{"source_id": "S1", "title": "实习公告", "content": "招聘 Python 实习生。",
                     "read_state": "read", "url": "https://example.invalid/jobs/1"}]}


def job_result():
    return {"agent": "job_analysis", "status": "ok", "data": {
        "summary": "样本要求熟悉 Python", "findings": [{"category": "skill", "statement": "熟悉 Python",
        "requirement": "required", "evidence": [{"chunk_id": "chunk-1", "quote": "熟悉 Python"}]}],
        "related_roles": [], "limitations": []},
        "sources": [{"chunk_id": "chunk-1", "file_path": "offline.txt#record=1", "content": JOB}], "scope": {}}


def decision_result(payload):
    prepared = CareerDecisionAgent.prepare(payload)
    assessments = [{"target_id": target["target_id"], "decision": "conditional", "conclusion": "需进一步核实实践深度",
        "checks": [{"check_id": f"C{index}", "requirement": "熟悉 Python", "kind": "capability",
        "importance": "required", "status": "partial", "reasoning": "有 API 项目，尚需核实熟练程度",
        "job_evidence": [{"source_id": target["source_ids"][0], "quote": "熟悉 Python"}],
        "candidate_evidence": [{"source_id": "R1", "quote": RESUME}]}]}
        for index, target in enumerate(prepared["targets"], 1)]
    data = {"summary": "先核实再选择", "assessments": assessments, "next_actions": [],
            "limitations": prepared["input_limitations"], "followup_questions": []}
    assert not verify_career_decision(data, prepared)
    return {"agent": "career_decision", "status": "ok", "data": data, "sources": prepared["sources"]}


def action_result(payload):
    prepared = ActionPlanningAgent(None).prepare(payload)
    plan = {"summary": "先确认项目贡献", "tasks": [{"task_id": "A1", "check_id": "C1", "stage": "核实",
        "kind": "clarify", "title": "确认项目贡献", "week": 1, "hours": 1, "cost": 0, "depends_on": [],
        "deliverable": "项目贡献清单", "acceptance_criteria": "列出个人完成的 API 和验证方式"}],
        "reduced_plan": {"weekly_hours": 2, "keep_task_ids": ["A1"], "reason": "保留核实任务"},
        "deferred_actions": [], "limitations": []}
    assert not verify_action_plan(ActionPlan.model_validate(plan), prepared)
    return {"agent": "action_planning", "status": "ok", "data": plan}


class WorkflowChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        database = str(Path(self.directory.name) / "checkpoints.sqlite3")
        self.calls = []
        self.fail_plan = False
        owner = self

        def factory(name):
            class OfflineAgent:
                async def arun(self, payload, config=None):
                    owner.calls.append((name, deepcopy(payload)))
                    if name == "resume_analysis":
                        return {"agent": name, "status": "ok", "data": {"summary": "简历原文已提供"}}
                    if name == "job_analysis":
                        return job_result()
                    if name == "recruitment_search":
                        result = search_result()
                        if payload.get("clarifications"):
                            result["data"]["followup_questions"] = []
                        return result
                    if name == "career_decision":
                        return decision_result(payload)
                    if owner.fail_plan:
                        owner.fail_plan = False
                        return {"agent": name, "status": "model_error", "error": "offline simulated failure"}
                    return action_result(payload)
            return OfflineAgent()

        @asynccontextmanager
        async def offline_graph(runtime=None, stage_callback=None):
            async with AsyncSqliteSaver.from_conn_string(database) as saver:
                yield build_report_graph(lambda: None, checkpointer=saver, stage_callback=stage_callback, agent_factory=factory)

        self.patch = patch.object(workflow, "_graph", offline_graph)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.report_id = "report-012345abcdef"
        self.input = workflow.validate_report_request({"targets": ["后端实习", "数据实习"],
            "preferences": "希望核实不同方向", "recruitment": {"request": "寻找 Python 实习", "channel": "web"}}, RESUME)
        self.profile = {"basics": {"city": "上海"}, "agent_workflow": self.input}
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        self.review = {"target_id": "T1", "constraints": {"start_date": today.isoformat(),
            "deadline": (today + timedelta(days=13)).isoformat(), "weekly_hours": 8, "budget": 0},
            "answers": {"recruitment_search": [{"question": QUESTION, "answer": "上海"}]}}

    def generate(self, continuation=None, profile=None):
        return workflow.generate_career_report_bundle(username="offline-user", report_id=self.report_id,
            profile_payload=self.profile if profile is None else profile,
            runtime_llm={"model": "offline-model", "continuation": continuation}, model_name="offline-model")

    def begin(self):
        with self.assertRaises(workflow.ReportNeedsInput):
            self.generate()
        snapshot = workflow.read_report_workflow("offline-user", self.report_id)
        self.assertEqual(snapshot["next"], ["review"])
        self.assertTrue(snapshot["provenance"]["input_revision"])
        return snapshot

    def test_resume_uses_frozen_profile_and_revised_search(self):
        snapshot = self.begin()
        changed = {"basics": {"city": "杭州"}}
        bundle = self.generate({"checkpoint_id": snapshot["checkpoint_id"], "response": self.review}, changed)
        self.assertEqual(bundle["profile_snapshot"]["basics"]["city"], "上海")
        self.assertEqual(bundle["meta"]["provenance"]["profile_revision"], content_revision(freeze_profile(self.profile)))
        self.assertEqual(bundle["meta"]["provenance"]["snapshot_status"], "frozen")
        decisions = [payload for name, payload in self.calls if name == "career_decision"]
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[-1]["recruitment_search"]["sources"][0]["source_id"], "S1")
        self.assertEqual([name for name, _ in self.calls].count("resume_analysis"), 1)
        self.assertNotIn("待核实：" + QUESTION, bundle["report_document"]["sections"]["risk_backup"]["markdown"])
        self.assertEqual(len(bundle["report_document"]["sections"]), 8)
        self.assertEqual(len(bundle["phase_plan"]["short_term"]), 1)
        self.assertIn("offline.txt#record=1", bundle["report_document"]["markdown"])
        self.assertEqual(len(bundle["meta"]["provenance"]["job_source_revisions"]), 2)
        self.assertTrue(workflow.read_report_workflow("offline-user", self.report_id)["complete"])
        self.assertFalse(workflow.read_report_workflow("another-user", self.report_id)["checkpoint_id"])

    def test_failed_planning_resumes_without_repeating_upstream(self):
        snapshot = self.begin()
        self.fail_plan = True
        with self.assertRaises(Exception) as caught:
            self.generate({"checkpoint_id": snapshot["checkpoint_id"], "response": self.review})
        self.assertIn("offline simulated failure", str(caught.exception))
        failed = workflow.read_report_workflow("offline-user", self.report_id)
        self.assertEqual(failed["next"], ["action_planning"])
        previous = len(self.calls)
        bundle = self.generate({"checkpoint_id": failed["checkpoint_id"], "response": {}})
        self.assertEqual([name for name, _ in self.calls[previous:]], ["action_planning"])
        self.assertEqual(bundle["meta"]["status"], "ready")

    def test_stale_and_unrelated_answers_are_rejected(self):
        snapshot = self.begin()
        with self.assertRaisesRegex(ValueError, "工作流已有更新"):
            self.generate({"checkpoint_id": "obsolete", "response": self.review})
        invalid = deepcopy(self.review)
        invalid["answers"]["recruitment_search"][0]["question"] = "不是当前追问"
        with self.assertRaises(ValueError):
            workflow.validate_report_continuation(invalid, snapshot)
        invalid = deepcopy(self.review)
        invalid["target_id"] = "T99"
        with self.assertRaises(ValueError):
            workflow.validate_report_continuation(invalid, snapshot)

    def test_only_current_accounts_resume_text_is_used(self):
        payload = {"targets": ["后端实习"], "raw_resume": "另一份简历"}
        self.assertEqual(workflow.validate_report_request(payload, RESUME)["raw_resume"], RESUME)

    def test_optional_search_can_be_skipped(self):
        self.input["recruitment"] = None
        self.review["answers"] = {}
        snapshot = self.begin()
        bundle = self.generate({"checkpoint_id": snapshot["checkpoint_id"], "response": self.review})
        self.assertEqual(bundle["agent_results"]["recruitment_search"]["status"], "skipped")
        self.assertNotIn("recruitment_search", [name for name, _ in self.calls])

    def test_uploaded_file_uses_existing_document_tool_once(self):
        supplied = {key: value for key, value in self.input.items() if key != "raw_resume"}
        self.input = workflow.validate_report_request(supplied, file_path="server-owned-resume.docx")
        self.profile["agent_workflow"] = self.input
        reader = AsyncMock(return_value={
            "status": "ok", "markdown": RESUME, "warnings": [],
        })
        with patch("experiments.news_advisor.tools.document.read_document", SimpleNamespace(ainvoke=reader)):
            snapshot = self.begin()
            resume_input = next(payload for name, payload in self.calls if name == "resume_analysis")
            self.assertEqual(resume_input["raw_resume"], RESUME)
            self.generate({"checkpoint_id": snapshot["checkpoint_id"], "response": self.review})
        reader.assert_awaited_once_with({"file_path": "server-owned-resume.docx", "max_pages": 20})

    def test_legacy_checkpoint_does_not_attach_current_profile(self):
        async def legacy_start():
            async with workflow._graph() as graph:
                await graph.ainvoke({"input": self.input}, {
                    "configurable": {"thread_id": workflow._thread_id("offline-user", self.report_id)}}, durability="sync")
        asyncio.run(legacy_start())
        snapshot = workflow.read_report_workflow("offline-user", self.report_id)
        bundle = self.generate({"checkpoint_id": snapshot["checkpoint_id"], "response": self.review},
                               {"basics": {"city": "杭州"}})
        self.assertEqual(bundle["profile_snapshot"], {})
        self.assertEqual(bundle["meta"]["provenance"]["snapshot_status"], "legacy_unavailable")


class EvidenceChecks(unittest.TestCase):
    def test_profile_freeze_excludes_circular_runtime_memory(self):
        profile = {"basics": {"city": "上海"}}
        profile["agent_memory"] = {"profile_snapshot": profile}
        frozen = freeze_profile(profile)
        profile["basics"]["city"] = "杭州"
        self.assertEqual(frozen, {"basics": {"city": "上海"}})

    def test_search_previews_images_and_fabricated_quotes_are_excluded(self):
        for mode in ("preview", "image_only", "forged"):
            result = search_result()
            if mode == "forged":
                result["data"]["findings"][0]["evidence_quotes"] = ["保证录用"]
            else:
                result["sources"][0]["read_state"] = mode
            self.assertFalse(recruitment_context(result)["findings"])
        result = recruitment_context(search_result())
        self.assertEqual(result["findings"][0]["match_status"], "needs_confirmation")
        self.assertTrue(recruitment_context({"status": "model_error"})["limitations"])

    def test_invalid_job_quotes_and_evidence_sides_are_rejected(self):
        job = job_result()
        broken = deepcopy(job["data"])
        broken["findings"][0]["evidence"][0]["quote"] = "必须精通 Java"
        self.assertTrue(verify_job_evidence(broken, job["sources"]))
        payload = {"raw_resume": RESUME, "targets": [{"target_id": "T1", "title": "后端实习", "job_analysis": job}]}
        result = decision_result(payload)
        result["data"]["assessments"][0]["checks"][0]["candidate_evidence"][0] = {
            "source_id": "T1JD1", "quote": "熟悉 Python"}
        self.assertTrue(verify_career_decision(result["data"], CareerDecisionAgent.prepare(payload)))

    def test_action_budget_and_dependencies_are_checked(self):
        payload = {"raw_resume": RESUME, "targets": [{"target_id": "T1", "title": "后端实习", "job_analysis": job_result()}]}
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        planning = {"decision_input": payload, "decision_result": decision_result(payload), "target_id": "T1",
                    "constraints": {"weekly_hours": 8, "budget": 0, "deadline": (today + timedelta(days=13)).isoformat()}}
        prepared = ActionPlanningAgent(None).prepare(planning)
        valid = action_result(planning)["data"]
        for change in ({"hours": 9}, {"cost": 1}, {"depends_on": ["missing"]}):
            invalid = deepcopy(valid)
            invalid["tasks"][0].update(change)
            self.assertTrue(verify_action_plan(ActionPlan.model_validate(invalid), prepared))


class MetricsChecks(unittest.TestCase):
    def test_real_agent_graph_propagates_usage_callbacks(self):
        class CheckOutput(BaseModel):
            summary: str

        class OfflineModel(BaseChatModel):
            @property
            def _llm_type(self):
                return "offline-structured-model"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                    "name": "CheckOutput", "args": {"summary": "offline"}, "id": "call-check", "type": "tool_call"}],
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))])

        class CheckAgent(BaseAgent):
            def prepare(self, payload):
                return payload

            def get_output_schema(self, prepared):
                return CheckOutput

        result = asyncio.run(CheckAgent(OfflineModel()).arun({"request": "check"}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["execution"]["model_calls"], 1)
        self.assertEqual(result["execution"]["total_tokens"], 15)
        self.assertEqual(result["execution"]["usage_status"], "reported")

    def test_usage_missing_partial_and_duplicate_callbacks(self):
        async def check():
            metrics = AgentMetrics()
            self.assertIsNone(metrics.summary()["total_tokens"])
            first, second = uuid4(), uuid4()
            await metrics.on_chat_model_start({}, [], run_id=first)
            message = AIMessage(content="ok", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
            response = LLMResult(generations=[[ChatGeneration(message=message)]])
            await metrics.on_llm_end(response, run_id=first)
            await metrics.on_llm_end(response, run_id=first)
            self.assertEqual(metrics.summary()["total_tokens"], 15)
            self.assertEqual(metrics.summary()["usage_status"], "reported")
            await metrics.on_chat_model_start({}, [], run_id=second)
            await metrics.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="no usage"))]]), run_id=second)
            self.assertEqual(metrics.summary()["usage_status"], "partial")
            summary = summarize_executions({"career_decision": {"execution": metrics.summary()}})
            self.assertFalse(summary["usage_complete"])
            self.assertEqual(summary["total_tokens"], 15)
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
