from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MemoryKey = Literal[
    "education", "graduation", "experience", "skill", "target_role", "target_city",
    "salary", "work_style", "industry", "availability", "constraint",
]


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["fact", "preference"]
    key: MemoryKey
    subject: str = Field(default="profile", min_length=1, max_length=100,
                         description="同一属性使用固定 subject；技能/经历按具体对象分开")
    value: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=2, max_length=2000, description="本轮用户材料中的连续原文")
    operation: Literal["assert", "correct", "retract"] = "assert"

    @model_validator(mode="after")
    def stable_kind(self):
        expected = "fact" if self.key in {"education", "graduation", "experience", "skill"} else "preference"
        if self.kind != expected:
            raise ValueError(f"{self.key} 的 kind 必须为 {expected}")
        if self.key not in {"skill", "experience", "constraint"}:
            self.subject = "profile"
        return self


class MemoryExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[MemoryCandidate] = Field(default_factory=list, max_length=30)


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=2500, description="压缩历史；区分用户陈述与助手建议，保留待确认问题")
