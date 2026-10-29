"""Offline checks for direct JSON planning; no API requests or business data writes."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from backend.services.report.planning import ReportActionPlanningAgent
from backend.scripts.check_report_workflow import RESUME, job_result, decision_result, action_result


class ScriptedModel(BaseChatModel):
    responses: list[str]
    reasons: list[str] = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    parameters: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "offline-planning-json"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        index = len(self.seen)
        self.seen.append(list(messages))
        self.parameters.append(kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.responses[min(index, len(self.responses) - 1)],
            response_metadata={"finish_reason": self.reasons[index] if index < len(self.reasons) else "stop"},
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))])


class PlanningChecks(unittest.TestCase):
    def setUp(self):
        decision_input = {"raw_resume": RESUME, "targets": [{"target_id": "T1", "title": "Python 实习", "job_analysis": job_result()}]}
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        self.payload = {"decision_input": decision_input, "decision_result": decision_result(decision_input), "target_id": "T1",
                        "constraints": {"weekly_hours": 8, "start_date": today.isoformat(), "deadline": (today + timedelta(days=13)).isoformat(), "budget": 0}}
        self.valid = action_result(self.payload)["data"]

    def run_agent(self, outputs, reasons=None):
        model = ScriptedModel(responses=[json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item for item in outputs], reasons=reasons or [])
        progress = []
        agent = ReportActionPlanningAgent(model, stage_callback=lambda *args: progress.append(args[-1]))
        result = asyncio.run(agent.arun(self.payload))
        return result, model, progress

    def test_plain_json_without_tool_calls_succeeds_once(self):
        result, model, progress = self.run_agent([self.valid])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(model.seen), 1)
        self.assertEqual(model.parameters[0]["response_format"], {"type": "json_object"})
        self.assertEqual(result["execution"]["model_calls"], 1)
        self.assertEqual(result["execution"]["total_tokens"], 15)
        self.assertEqual(result["constraints"]["weekly_hours"], 8)
        self.assertIn("通过", progress[-1])

    def test_hours_and_budget_errors_are_returned_to_model_for_repair(self):
        invalid = deepcopy(self.valid)
        invalid["tasks"][0].update(hours=9, cost=1)
        result, model, progress = self.run_agent([invalid, self.valid])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(model.seen), 2)
        feedback = model.seen[1][-1].content
        self.assertIn("工时超出", feedback)
        self.assertIn("超出本阶段预算", feedback)
        self.assertTrue(any("正在修正" in item for item in progress))

    def test_invalid_check_ids_and_dependencies_never_become_a_success(self):
        invalid = deepcopy(self.valid)
        invalid["tasks"][0].update(check_id="invented", depends_on=["missing"])
        result, model, progress = self.run_agent([invalid])
        self.assertEqual(result["status"], "validation_failed")
        self.assertFalse(result["data"])
        self.assertEqual(len(model.seen), 3)
        self.assertIn("check_id", result["error"])
        self.assertIn("依赖", result["error"])
        self.assertIn("已停止", progress[-1])

    def test_conditional_decision_still_forbids_apply_tasks(self):
        invalid = deepcopy(self.valid)
        invalid["tasks"][0]["kind"] = "apply"
        result, _, _ = self.run_agent([invalid])
        self.assertEqual(result["status"], "validation_failed")
        self.assertIn("不支持安排投递", result["error"])

    def test_malformed_json_can_be_repaired_and_repeated_failures_are_bounded(self):
        result, model, _ = self.run_agent(["{not json}", self.valid])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(model.seen), 2)
        result, model, _ = self.run_agent(["{}"])
        self.assertEqual(result["status"], "validation_failed")
        self.assertEqual(len(model.seen), 3)
        self.assertIn("tasks", result["error"])

    def test_truncated_output_is_not_accepted_even_when_json_parses(self):
        result, model, _ = self.run_agent([self.valid, self.valid], reasons=["length", "stop"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(model.seen), 2)
        self.assertIn("截断", model.seen[1][-1].content)

    def test_cancellation_before_model_request_propagates(self):
        class Canceled(Exception):
            pass

        def cancel(*args):
            raise Canceled()

        model = ScriptedModel(responses=[json.dumps(self.valid)])
        agent = ReportActionPlanningAgent(model, stage_callback=cancel)
        with self.assertRaises(Canceled):
            asyncio.run(agent.arun(self.payload))
        self.assertFalse(model.seen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
