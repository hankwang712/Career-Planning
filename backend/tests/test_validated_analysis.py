import unittest

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from backend.advisor.agents.base import BaseAgent


class Result(BaseModel):
    fact: str = Field(min_length=1)


class Analysis(BaseAgent):
    name = "test_analysis"
    system_prompt = "Return a supported fact."

    def prepare(self, payload):
        return payload

    def get_output_schema(self, prepared):
        return Result


class ValidatedAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_output_gets_schema_feedback_then_valid_output_returns(self):
        model = FakeMessagesListChatModel(responses=[AIMessage(content='{"fact":""}'), AIMessage(content='{"fact":"evidence"}')])
        result = await Analysis(model)._arun_validated_json({"source": "evidence"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["fact"], "evidence")
        self.assertEqual(result["execution"]["attempts"], 2)
        self.assertEqual(len(result["validation_feedback"]), 1)

    async def test_truncated_output_is_not_published(self):
        model = FakeMessagesListChatModel(responses=[AIMessage(content='{"fact":"truncated"}', response_metadata={"finish_reason": "length"})])
        result = await Analysis(model, max_model_calls=1)._arun_validated_json({"source": "evidence"})
        self.assertEqual(result["status"], "validation_failed")
        self.assertEqual(result["data"], {})

    async def test_exhausted_validation_returns_specific_error_not_tool_execution_limit(self):
        model = FakeMessagesListChatModel(responses=[AIMessage(content='{}')])
        result = await Analysis(model, max_model_calls=2)._arun_validated_json({"source": "evidence"})
        self.assertEqual(result["status"], "validation_failed")
        self.assertEqual(result["execution"]["attempts"], 2)
        self.assertIn("fact", result["error"])


if __name__ == "__main__":
    unittest.main()
