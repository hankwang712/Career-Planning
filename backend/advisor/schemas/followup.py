from pydantic import BaseModel, ConfigDict, Field


class Clarification(BaseModel):
    """问题仅提供上下文；answer 才是用户补充的原文。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=10000)
