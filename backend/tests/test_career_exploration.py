from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from backend.advisor.agents.career_decision import CareerDecisionAgent, verify_career_decision
from backend.advisor.agents.action_planning import ActionPlanningAgent, verify_action_plan
from backend.advisor.report_workflow import build_report_graph, validate_review
from backend.advisor.schemas.action_planning import ActionPlan
from backend.services.report.reader_sections import build_reader_sections


def job():
    return {"agent": "job_analysis", "status": "ok", "sources": [{"chunk_id": "s1",
        "content": "岗位职责：Python脚本开发。任职要求：熟悉Python。", "file_path": "jobs.txt#record=1"}],
        "data": {"summary": "Python岗位要求", "findings": [{"category": "skill", "statement": "熟悉Python",
            "requirement": "required", "evidence": [{"chunk_id": "s1", "quote": "熟悉Python"}]}]}}


def payload():
    return {"raw_resume": "学过Python，其余经历暂未提供。", "targets": [
        {"target_id": "T1", "title": "Python开发", "job_analysis": job()}]}


def exploration():
    return {"summary": "可以先验证Python实践能力，成果核对后再判断是否适合尝试岗位，不代表当前已经胜任。",
        "steps": [{"check_id": "C1", "if_already_done": "整理已有作业或脚本，说明本人完成的部分。",
            "if_not_done": "先尝试写一个读取文件并处理错误的Python脚本。",
            "deliverable": "可运行脚本和测试记录。", "acceptance_criteria": "正常输入可得到预期结果，错误输入有明确处理记录。"}]}


def decision():
    return {"summary": "材料较少，可以按岗位要求先验证能力。", "assessments": [{
        "target_id": "T1", "decision": "conditional", "conclusion": "先用已有成果或最小任务验证，投递条件另行核实。",
        "checks": [{"check_id": "C1", "requirement": "熟悉Python", "kind": "capability", "importance": "required",
            "status": "evidence_missing", "job_evidence": [{"source_id": "T1JD1", "quote": "熟悉Python"}],
            "candidate_evidence": [], "reasoning": "有学习自述，实际脚本开发能力仍需验证。"}],
        "exploration": exploration()}], "followup_questions": [], "evidence_requests": [], "limitations": []}


def plan():
    return ActionPlan.model_validate({"summary": "先验证已有基础，缺少成果再完成最小练习。",
        "tasks": [{"task_id": "A1", "check_id": "C1", "stage": "验证", "kind": "practice",
            "title": "先检查已有脚本，没有则完成最小验证", "week": 1, "hours": 2, "cost": 0,
            "depends_on": [], "deliverable": "已有脚本或新写的脚本及测试记录", "acceptance_criteria": "验证正常与错误输入处理"}],
        "reduced_plan": {"weekly_hours": 3, "keep_task_ids": ["A1"], "reason": "先保留一项验证"}})


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.prepared = CareerDecisionAgent.prepare(payload())
        self.schema = CareerDecisionAgent(None).get_output_schema(self.prepared)

    def test_sparse_candidate_gets_conditional_exploration(self):
        result = self.schema.model_validate(decision())
        self.assertEqual(result.assessments[0].decision, "conditional")
        self.assertEqual(verify_career_decision(result.model_dump(), self.prepared), [])

    def test_sparse_candidate_cannot_stop_at_missing_information(self):
        for label in ("insufficient_information", "recommended", "not_recommended"):
            item = decision()
            item["assessments"][0]["decision"] = label
            with self.subTest(label=label), self.assertRaises(ValidationError):
                self.schema.model_validate(item)

    def test_new_output_must_include_actionable_exploration(self):
        item = decision()
        item["assessments"][0].pop("exploration")
        with self.assertRaisesRegex(ValidationError, "exploration"):
            self.schema.model_validate(item)
        # Historic saved decisions are still readable and publishable.
        self.assertEqual(verify_career_decision(item, self.prepared), [])

    def test_exploration_cannot_reference_invented_or_hard_check(self):
        item = decision()
        item["assessments"][0]["exploration"]["steps"][0]["check_id"] = "invented"
        self.assertTrue(verify_career_decision(item, self.prepared))
        item = decision()
        item["assessments"][0]["checks"][0]["kind"] = "hard_condition"
        self.assertTrue(any("硬条件" in error or "学历" in error for error in verify_career_decision(item, self.prepared)))

    def test_exploration_does_not_promise_employment(self):
        item = decision()
        item["assessments"][0]["exploration"]["summary"] = "完成练习就能胜任。"
        self.assertTrue(any("承诺" in error for error in verify_career_decision(item, self.prepared)))

    def test_disclaimers_are_not_mistaken_for_promises(self):
        for text in ("验证后再判断，不保证录用。", "完成练习不意味着就能胜任。", "不能据此保证录用。"):
            item = decision()
            item["assessments"][0]["exploration"]["summary"] = text
            with self.subTest(text=text):
                self.assertEqual(verify_career_decision(item, self.prepared), [])

    def test_no_job_requirements_does_not_invent_a_learning_path(self):
        data = payload()
        data["targets"][0]["job_analysis"] = {"status": "insufficient_evidence", "sources": [], "data": {}}
        prepared = CareerDecisionAgent.prepare(data)
        item = decision()
        item["assessments"][0].update(decision="insufficient_information", checks=[], exploration=None)
        self.assertEqual(CareerDecisionAgent(None).get_output_schema(prepared).model_validate(item).assessments[0].checks, [])

    def test_candidate_gap_is_not_sent_to_job_lookup(self):
        item = decision()
        item["evidence_requests"] = [{"target_id": "T1", "question": "用户会不会独立编写Python脚本？", "reason": "简历材料少"}]
        self.assertTrue(any("个人材料不足" in error for error in verify_career_decision(item, self.prepared)))
        item["evidence_requests"][0]["question"] = "岗位要求的Python是必需还是优先条件？"
        self.assertEqual(verify_career_decision(item, self.prepared), [])

    def test_confirmed_hard_conflict_is_not_replaced_by_learning(self):
        item = decision()
        check = item["assessments"][0]["checks"][0]
        check.update(kind="hard_condition", status="confirmed_gap", requirement="每周到岗五天",
                     candidate_evidence=[{"source_id": "R1", "quote": "我只能每周到岗两天"}])
        prepared = deepcopy(self.prepared)
        prepared["targets"][0]["target_type"] = "job"
        prepared["sources"][0]["content"] = "我只能每周到岗两天"
        item["assessments"][0]["decision"] = "not_recommended"
        self.assertTrue(any("绕过资格" in error for error in verify_career_decision(item, prepared)))

    def test_user_may_confirm_target_without_answering_experience_questions(self):
        pending = {"targets": [{"target_id": "T1"}], "questions": {}, "assessments": decision()["assessments"]}
        reviewed = validate_review({"target_id": "T1", "constraints": {"weekly_hours": 6,
            "deadline": (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=30)).isoformat()}}, pending)
        self.assertEqual(reviewed["answers"], {})

    def test_planning_cannot_only_ask_for_more_information(self):
        prepared = {"assessment": decision()["assessments"][0], "target": {"target_type": "direction"},
            "weeks": [{"week": 1, "days": 7, "hours_capacity": 6}], "constraints": {"weekly_hours": 6, "budget": 0}, "sources": []}
        result = plan()
        self.assertEqual(verify_action_plan(result, prepared), [])
        result.tasks[0].kind = "clarify"
        self.assertTrue(any("不能只追问" in error for error in verify_action_plan(result, prepared)))

    def test_unknown_capability_task_keeps_both_branches(self):
        prepared = {"assessment": decision()["assessments"][0], "target": {"target_type": "direction"},
            "weeks": [{"week": 1, "days": 7, "hours_capacity": 6}], "constraints": {"weekly_hours": 6, "budget": 0}, "sources": []}
        result = plan()
        result.tasks[0].kind = "document"
        result.tasks[0].title = "整理已有项目"
        self.assertTrue(any("同时给出" in error for error in verify_action_plan(result, prepared)))

    def test_report_shows_branches_and_exploration_conclusion(self):
        assessment = decision()["assessments"][0]
        selected = payload()["targets"][0]
        tasks = plan().model_dump()["tasks"]
        state = {"input": {}, "results": {"resume_analysis": {"data": {}},
            "career_decision": {"data": decision(), "sources": []}, "action_planning": {"data": {"tasks": tasks}}},
            "review": {"constraints": {"deadline": "2026-11-16", "weekly_hours": 6}, "answers": {}}}
        presentation = SimpleNamespace(clean=lambda text, **kwargs: text, targets=[selected], cite=lambda *args: None, appendix_sources=lambda: "")
        sections, _ = build_reader_sections(state, {}, presentation, selected, assessment,
            {item["check_id"]: item for item in assessment["checks"]}, date(2026, 11, 10))
        matching = sections["matching_decision"]["markdown"]
        self.assertIn("如果已经做过", matching)
        self.assertIn("如果还没做过", matching)
        self.assertIn("验证标准", matching)
        self.assertIn("可以先验证能力", sections["development_path"]["markdown"])


class AgentAndWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_decision_agent_repairs_missing_path_without_retrieval(self):
        initial = decision()
        initial["assessments"][0].pop("exploration")
        model = FakeMessagesListChatModel(responses=[AIMessage(content=json.dumps(item, ensure_ascii=False)) for item in (initial, decision())])
        result = await CareerDecisionAgent(model).arun(payload())
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["execution"]["attempts"], 2)
        self.assertTrue(result["data"]["assessments"][0]["exploration"]["steps"])

    async def test_workflow_continues_without_more_candidate_information(self):
        for answer in (None, "不知道"):
            with self.subTest(answer=answer):
                calls, planning_inputs = [], []
                draft = decision()
                question = "你是否独立写过Python脚本？"
                draft["followup_questions"] = [question]
                model = FakeMessagesListChatModel(responses=[AIMessage(content=json.dumps(draft, ensure_ascii=False))])
                def factory(name):
                    if name == "career_decision":
                        return CareerDecisionAgent(model)
                    class Agent:
                        async def arun(self, value, config=None):
                            calls.append(name)
                            if name == "job_analysis":
                                return job()
                            if name == "action_planning":
                                planning_inputs.append(value)
                                return {"agent": name, "status": "ok", "data": plan().model_dump()}
                            return {"agent": name, "status": "ok", "data": {}}
                    return Agent()
                graph = build_report_graph(lambda: None, checkpointer=InMemorySaver(), agent_factory=factory)
                config = {"configurable": {"thread_id": "explore"}}
                await graph.ainvoke({"input": {"raw_resume": payload()["raw_resume"], "targets": ["Python开发"], "job_filters": {}}}, config)
                review = {"target_id": "T1", "constraints": {"weekly_hours": 6,
                    "deadline": (datetime.now(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=30)).isoformat()}}
                if answer:
                    review["answers"] = {"career_decision": [{"question": question, "answer": answer}]}
                result = await graph.ainvoke(Command(resume=review), config)
                self.assertFalse((await graph.aget_state(config)).next)
                self.assertEqual(calls.count("job_analysis"), 1)
                self.assertEqual(calls.count("action_planning"), 1)
                self.assertEqual(result.get("evidence_rounds", 0), 0)
                self.assertIsNotNone(planning_inputs[0]["decision_result"]["data"]["assessments"][0]["exploration"])


if __name__ == "__main__":
    unittest.main()
