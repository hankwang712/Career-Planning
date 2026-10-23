"""简历诊断的输出约束：原文证据、评分锚点，以及三种分析模式。"""

from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, ValidationInfo, computed_field,
    field_validator, model_validator,
)

Text = Annotated[str, Field(min_length=1)]
RESUME_KEYS = {
    "experience_quality", "skills_evidence", "positioning",
    "education_growth", "expression", "completeness",
}
CORE_EXPERIENCE_KEYS = {"contribution", "execution", "outcomes"}


def check_quote(quote: str, source: str, context: dict | None) -> None:
    # 只容忍换行和连续空白差异，不做模糊匹配，避免伪造或拼接原句。
    if context is not None and " ".join(quote.split()) not in " ".join(context[source].split()):
        raise ValueError(f"引用必须来自输入的 {source} 原文")


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Record):
    source: Literal["raw_resume", "additional_evidence"]
    status: Literal["clear", "weak", "missing"]
    quote: str = ""

    @model_validator(mode="after")
    def validate_quote(self, info: ValidationInfo):
        if self.status == "missing":
            if self.quote:
                raise ValueError("待补证据的 quote 必须为空")
        elif not self.quote:
            raise ValueError("已有证据必须引用原文")
        else:
            check_quote(self.quote, self.source, info.context)
        return self


class Assessment(Record):
    assessment: Text = Field(description="基于证据的判断；缺失信息不能表述为能力不足")
    evidence: list[Evidence] = Field(min_length=1)


class Dimension(Assessment):
    key: Text
    applicable: bool = Field(default=True, description="不适用须说明原因，不能用来回避应有的证据缺口")
    level: Annotated[int, Field(ge=0, le=4, strict=True)] | None
    weight: Annotated[int, Field(ge=0, le=100, strict=True)]
    evidence: list[Evidence] = Field(description="适用维度必须提供证据对象；不适用时可为空")

    @model_validator(mode="after")
    def require_scoring_evidence(self):
        if not self.applicable:
            if self.level is not None or self.weight != 0:
                raise ValueError("不适用维度的 level 必须为 null，weight 必须为 0")
            return self
        if self.level is None or not self.evidence:
            raise ValueError("适用维度必须有等级和证据对象，信息缺失使用 missing")
        if self.level > 0 and all(item.status == "missing" for item in self.evidence):
            raise ValueError("没有证据的维度只能评为 0 级")
        return self


class ResumeDimension(Dimension):
    key: Literal[
        "experience_quality", "skills_evidence", "positioning",
        "education_growth", "expression", "completeness",
    ]


class ExperienceDimension(Dimension):
    key: Literal[
        "background", "contribution", "execution", "outcomes",
        "transferability", "expression", "decision",
    ]


def check_dimensions(dimensions: Sequence[Dimension], required: set[str]) -> None:
    keys = {item.key for item in dimensions}
    if len(keys) != len(dimensions) or not required <= keys:
        raise ValueError("评分维度不能重复，且必须包含核心维度")
    if sum(item.weight for item in dimensions) != 100:
        raise ValueError("评分权重之和必须为 100")


def evidence_score(dimensions: Sequence[Dimension]) -> float:
    return round(sum((item.level or 0) * item.weight / 4 for item in dimensions), 1)


class OverallReview(Record):
    first_impression: Assessment
    evaluation_basis: Text = Field(description="候选人阶段、评价范围、权重选择及调整原因")
    dimensions: list[ResumeDimension] = Field(min_length=6, max_length=6)
    score_type: Literal["resume_evidence_quality"] = "resume_evidence_quality"

    @model_validator(mode="after")
    def validate_dimensions(self):
        check_dimensions(self.dimensions, RESUME_KEYS)
        return self

    @computed_field
    @property
    def score(self) -> float:
        """按等级和权重计算，不接受模型凭印象给出的总分。"""
        return evidence_score(self.dimensions)


class Issue(Record):
    kind: Literal["contradiction", "missing_evidence", "unclear_contribution", "expression"]
    evidence: list[Evidence] = Field(min_length=1)
    problem: Text
    impact: Text
    suggestion: Text
    rewrite: Text | None = Field(description="只使用已提供事实；无法可靠改写时为 null")
    missing_evidence: list[Text]


class SkillReview(Assessment):
    skill: Text


class ReviewPoint(Assessment):
    focus: Text = Field(description="该经历实际适用的审查点，如客户沟通、研究方法、方案取舍")


class ExperienceReview(Record):
    name: Text = Field(description="使用简历中的经历名称或原文短语，不虚构项目名")
    experience_type: Literal[
        "work", "internship", "project", "coursework", "research",
        "competition", "campus", "volunteering", "portfolio", "other",
    ]
    source_quote: Text = Field(description="该经历在简历中的连续原文片段，不能拼接")
    contribution: Assessment
    actions: Assessment
    outcomes: Assessment
    transferable_skills: list[SkillReview]
    specific_review: list[ReviewPoint] = Field(description="按实际内容选择审查点，不适用时为空列表")
    rubric_reason: Text = Field(description="按经历性质和候选人阶段选择维度与权重的原因")
    dimensions: list[ExperienceDimension] = Field(min_length=3, max_length=7)
    issues: list[Issue]
    followup_questions: list[Text] = Field(max_length=4)
    score_type: Literal["experience_evidence_quality"] = "experience_evidence_quality"

    @field_validator("source_quote")
    @classmethod
    def validate_source(cls, value: str, info: ValidationInfo) -> str:
        check_quote(value, "raw_resume", info.context)
        return value

    @model_validator(mode="after")
    def validate_dimensions(self):
        check_dimensions(self.dimensions, CORE_EXPERIENCE_KEYS)
        if any(not item.applicable for item in self.dimensions if item.key in CORE_EXPERIENCE_KEYS):
            raise ValueError("个人贡献、实际行动和产出是经历的核心维度，不能标记为不适用")
        return self

    @computed_field
    @property
    def score(self) -> float:
        return evidence_score(self.dimensions)


class SectionReview(Assessment):
    section: Literal["education", "awards", "certifications", "publications", "summary", "other"]
    section_name: Text
    issues: list[Issue]

    @model_validator(mode="after")
    def require_existing_section(self):
        if all(item.status == "missing" for item in self.evidence):
            raise ValueError("只分析简历中实际存在的模块，必须提供对应原文")
        return self


class RoleCriterion(Assessment):
    expectation: Text = Field(description="一般岗位预期，属于待确认假设，不是某家公司的招聘要求")


class RoleAlignment(Record):
    basis: Literal["role_expectations"] = "role_expectations"
    summary: Text
    criteria: list[RoleCriterion] = Field(min_length=1)
    missing_information: list[Text] = Field(description="需要补充的岗位级别、具体 JD 等信息")


class RequirementMatch(Assessment):
    requirement: Text
    jd_quote: Text
    category: Literal["required", "preferred", "responsibility"]
    status: Literal["supported", "partial", "not_evidenced", "conflict"]
    action: Text

    @field_validator("jd_quote")
    @classmethod
    def validate_source(cls, value: str, info: ValidationInfo) -> str:
        check_quote(value, "job_description", info.context)
        return value

    @model_validator(mode="after")
    def require_support(self):
        if self.status != "not_evidenced" and all(item.status == "missing" for item in self.evidence):
            raise ValueError("匹配、部分匹配或冲突的判断必须有简历证据")
        return self


class JobMatch(Record):
    basis: Literal["provided_jd"] = "provided_jd"
    summary: Text
    requirements: list[RequirementMatch] = Field(min_length=1)
    missing_information: list[Text]


class ResumeAnalysis(Record):
    overall: OverallReview
    experiences: list[ExperienceReview]
    sections: list[SectionReview]
    skills: list[SkillReview]
    strengths: list[Assessment] = Field(max_length=3)
    priority_issues: list[Issue] = Field(max_length=3)
    revision_tasks: list[Text] = Field(max_length=5)
    missing_information: list[Text]


class ResumeReview(ResumeAnalysis):
    mode: Literal["resume_review"] = "resume_review"
    matching: None = None


class RoleAnalysis(ResumeAnalysis):
    mode: Literal["role_alignment"] = "role_alignment"
    matching: RoleAlignment


class JobAnalysis(ResumeAnalysis):
    mode: Literal["job_match"] = "job_match"
    matching: JobMatch
