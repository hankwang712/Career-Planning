"""简历分析的输入和输出结构；内容判断由 Agent 完成。"""

from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, computed_field, model_validator,
)

from ..resume_rubric import RESUME_WEIGHTS, experience_weights
from .followup import Clarification

Text = Annotated[str, Field(min_length=1)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResumeInput(Record):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    file_path: str = ""
    max_pages: int = Field(default=20, ge=1, le=100)
    raw_resume: str = ""
    target_role: str = ""
    job_description: str = Field(default="", description="可选，仅作为简历诊断背景，不执行岗位匹配")
    candidate_level: str = ""
    education_context: str = ""
    additional_evidence: str = ""
    clarifications: list[Clarification] = Field(default_factory=list)
    document: dict = Field(default_factory=dict, description="文档读取状态与警告，不属于经历事实")

    @model_validator(mode="after")
    def require_single_source(self):
        if self.file_path and self.raw_resume:
            raise ValueError("file_path 和 raw_resume 只需提供一个")
        return self


class Evidence(Record):
    source: Literal["raw_resume", "additional_evidence", "education_context"]
    status: Literal["clear", "weak", "missing"]
    quote: str = ""

class Dimension(Record):
    key: Text
    level: Annotated[int, Field(ge=0, le=4, strict=True)]
    assessment: Text
    evidence: list[Evidence]


def calculate_score(dimensions: list[Dimension], weights: dict[str, int]) -> float | None:
    # 维度不完整时保留分析、不生成总分，避免静默补零或重复计分。
    if len(dimensions) != len(weights) or {item.key for item in dimensions} != set(weights):
        return None
    return round(sum(item.level * weights[item.key] / 4 for item in dimensions), 1)


class Issue(Record):
    problem: Text = Field(description="具体问题及其对理解简历的影响")
    evidence: list[Evidence]
    suggestion: Text
    rewrite: Text | None = Field(default=None, description="只重组已有事实，证据不足时为空")
    missing_evidence: list[Text] = Field(default_factory=list)


class ExperienceReview(Record):
    name: Text
    experience_type: Text = Field(description="使用固定规则中的类型；其他经历使用通用规则")
    source_quote: Text
    dimensions: list[Dimension]
    issues: list[Issue]
    followup_questions: list[Text]

    @computed_field
    @property
    def score(self) -> float | None:
        return calculate_score(self.dimensions, experience_weights(self.experience_type))


class ResumeAnalysis(Record):
    summary: Text
    dimensions: list[Dimension]
    experiences: list[ExperienceReview]
    issues: list[Issue]
    recommendations: list[Text]
    missing_information: list[Text]

    @computed_field
    @property
    def score(self) -> float | None:
        return calculate_score(self.dimensions, RESUME_WEIGHTS)
