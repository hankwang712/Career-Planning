from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .followup import Clarification


AgentName = Literal["resume_analysis", "recruitment_search", "career_decision", "action_planning"]


class ThreadCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    checkpoint_id: str | None = Field(default=None, description="可选，提交前读取的检查点 ID，用于拒绝过期提交")


class AgentRequest(ThreadCheckpoint):
    agent: AgentName
    input: dict[str, Any] = Field(default_factory=dict, description="首次提供完整输入，后续只传需要更新的字段")
    answers: list[Clarification] = Field(default_factory=list, description="回答本线程中该 Agent 实际提出的问题")

    @model_validator(mode="after")
    def unique_questions(self):
        questions = [item.question for item in self.answers]
        if len(questions) != len(set(questions)):
            raise ValueError("同一次提交不能重复回答相同问题")
        return self
