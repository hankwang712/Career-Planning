"""Offline regression checks; no model requests, servers or business data writes."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.report import workflow
from backend.services.report.review import apply_availability, build_review_ui, REVIEW_POLICY


class ReviewChecks(unittest.TestCase):
    def test_explicit_internship_choices_are_saved_as_preferences(self):
        availability, text = apply_availability({"arrival": "now", "days_per_week": 5}, "杭州或上海")
        self.assertEqual(availability["days_per_week"], 5)
        self.assertIn("随时到岗", text)
        self.assertIn("每周可实习 5 天", text)
        self.assertIn("杭州或上海", text)
        self.assertNotIn("40", text)

    def test_undecided_choices_remain_unknown_and_bad_choices_rejected(self):
        availability, text = apply_availability({"arrival": "undecided", "days_per_week": 0})
        self.assertEqual(availability["days_per_week"], 0)
        self.assertIn("待确认", text)
        for payload in ({"arrival": "now", "days_per_week": 40}, {"arrival": "now", "days_per_week": True},
                        {"arrival": "made-up-date", "days_per_week": 5}, {"arrival": "now", "days_per_week": 5, "hours": 40}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                apply_availability(payload)

    def test_known_arrival_days_and_employer_questions_are_not_asked(self):
        questions = ["什么时候可以开始实习？", "每周能实习几天？",
                     "JD1 这条招聘记录面向哪个毕业批次，投递窗口是什么时间？",
                     "是否接受岗位明确要求的加班安排？", "是否愿意短期出差？", "项目中还有哪些未说明的贡献？"]
        ui = build_review_ui({"questions": {"career_decision": questions, "resume_analysis": ["重复介绍项目"]}},
                             {"preferences": "杭州上海，随时到岗，每周可以5天实习"})
        self.assertEqual([card["question"] for card in ui["questions"]], questions[3:5])
        self.assertEqual(len(ui["questions"][0]["choices"]), 3)
        self.assertIn("随时到岗", ui["availability_summary"])

    def test_already_declared_overtime_and_travel_preferences_are_not_asked(self):
        ui = build_review_ui({"questions": {"career_decision": ["是否接受加班？", "是否接受出差？"]}},
                             {"preferences": "不接受加班，可以出差"})
        self.assertFalse(ui["questions"])

    def test_school_city_is_not_mistaken_for_a_work_location_preference(self):
        pending = {"questions": {"career_decision": ["希望在哪个城市实习？"]}}
        self.assertEqual(len(build_review_ui(pending, {"raw_resume": "在杭州的学校就读"})["questions"]), 1)
        self.assertFalse(build_review_ui(pending, {"preferences": "杭州或上海"})["questions"])

    def test_undecided_is_not_repeated_and_empty_questions_are_allowed(self):
        _, preferences = apply_availability({"arrival": "undecided", "days_per_week": 0})
        ui = build_review_ui({"questions": {"career_decision": ["什么时候可以实习？", "每周可以实习几天？"]}},
                             {"preferences": preferences})
        self.assertFalse(ui["questions"])
        self.assertFalse(build_review_ui({"questions": {}}, {}, {})["questions"])

    def test_original_questions_are_preserved_for_native_review_validation(self):
        from experiments.news_advisor.report_workflow import validate_review
        question = "是否接受每周一次出差？"
        pending = {"targets": [{"target_id": "T1"}], "questions": {"career_decision": [question]}}
        card = build_review_ui(pending)["questions"][0]
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        response = {"target_id": "T1", "answers": {card["agent"]: [{"question": card["question"], "answer": card["choices"][0]}]},
                    "constraints": {"weekly_hours": 6, "start_date": today.isoformat(),
                                    "deadline": (today + timedelta(days=27)).isoformat(), "budget": None}}
        self.assertEqual(validate_review(response, pending)["answers"]["career_decision"][0]["question"], question)


class ClientLifecycleChecks(unittest.TestCase):
    def test_real_sdk_requests_can_resume_across_loops_with_mock_transport(self):
        import openai
        import langchain_openai  # Import SDK subclasses before replacing the client constructor.
        from openai import _base_client
        sdk_httpx = getattr(_base_client, "httpx2", None) or _base_client.httpx
        import experiments.news_advisor.report_workflow as native

        original = openai.DefaultAsyncHttpxClient
        clients = []

        def client_factory():
            def respond(request):
                return sdk_httpx.Response(200, json={"id": "offline", "object": "chat.completion", "created": 0,
                    "model": "offline", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "offline response"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}})
            client = original(transport=sdk_httpx.MockTransport(respond))
            clients.append(client)
            return client

        async def invoke():
            async with workflow._graph({"base_url": "https://offline.invalid/v1", "api_key": "offline", "model": "offline"}) as model:
                self.assertEqual((await model.ainvoke("offline check")).content, "offline response")

        with tempfile.TemporaryDirectory() as directory, patch.object(workflow, "APP_DATA_DIR", Path(directory)), \
                patch.object(openai, "DefaultAsyncHttpxClient", client_factory), \
                patch.object(native, "build_report_graph", lambda provider, **kwargs: provider()):
            asyncio.run(invoke())
            asyncio.run(invoke())
        self.assertIsNot(clients[0], clients[1])
        self.assertTrue(all(client.is_closed for client in clients))

    def test_resume_in_two_event_loops_never_reuses_http_clients(self):
        import experiments.news_advisor.report_workflow as native
        import langchain_openai

        clients = []
        loops = []
        configs = []
        agents = []

        def model(**kwargs):
            clients.append((kwargs["http_client"], kwargs["http_async_client"]))
            configs.append(kwargs)
            loops.append(asyncio.get_running_loop())
            return object()

        def graph_builder(provider, **kwargs):
            # Construct the exact agent which previously failed on continuation.
            agents.append(kwargs["agent_factory"]("action_planning"))
            decision = kwargs["agent_factory"]("career_decision")
            self.assertTrue(decision.system_prompt.endswith(REVIEW_POLICY))
            return object()

        async def once(fail=False):
            async with workflow._graph({"base_url": "https://offline.invalid/v1", "api_key": "offline", "model": "offline"}):
                self.assertFalse(clients[-1][1].is_closed)
                if fail:
                    raise RuntimeError("offline interruption")

        with tempfile.TemporaryDirectory() as directory, patch.object(workflow, "APP_DATA_DIR", Path(directory)), \
                patch.object(native, "build_report_graph", graph_builder), patch.object(langchain_openai, "ChatOpenAI", model):
            asyncio.run(once())
            with self.assertRaisesRegex(RuntimeError, "offline interruption"):
                asyncio.run(once(fail=True))

        # Two models inside one invocation can share clients; a later invocation cannot.
        self.assertIs(clients[0][1], clients[1][1])
        self.assertIsNot(clients[0][1], clients[2][1])
        self.assertIsNot(loops[0], loops[2])
        self.assertTrue(all(sync.is_closed and asynchronous.is_closed for sync, asynchronous in clients))
        self.assertTrue(all(config["http_socket_options"] == () for config in configs))
        from experiments.news_advisor.agents import CareerDecisionAgent
        self.assertFalse(CareerDecisionAgent.system_prompt.endswith(REVIEW_POLICY))


if __name__ == "__main__":
    unittest.main(verbosity=2)
