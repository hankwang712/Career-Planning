from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobAnalysisInput(JobRecord):
    target_role: str = Field(default="", max_length=300)
    question: str = Field(default="", max_length=2000)
    mode: Literal["mix", "hybrid", "local", "global", "naive"] = "mix"
    top_k: int = Field(default=20, ge=1, le=60)
    chunk_top_k: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="after")
    def require_query(self):
        if not self.target_role and not self.question:
            raise ValueError("请提供目标岗位或分析问题")
        return self

    def retrieval_query(self) -> str:
        parts = [self.target_role, self.question or "分析岗位职责、必备能力和加分条件"]
        return "\n".join(part for part in parts if part)


class JobSource(JobRecord):
    chunk_id: str = Field(min_length=1)
    file_path: str = "unknown_source"
    reference_id: str = ""
    content: str = Field(min_length=1)


class JobEvidence(JobRecord):
    chunk_id: str = Field(description="使用本次输入 sources 的短编号 chunk_id，例如 JD1、JD2")
    quote: str = Field(min_length=2, max_length=2000, description="该 chunk 的连续原文，不得改写或添加省略号")


class JobFinding(JobRecord):
    category: Literal["responsibility", "skill", "education", "experience", "other"]
    statement: str = Field(min_length=1, description="仅概括证据支持的岗位要求，保留任选、优先等限定")
    requirement: Literal["required", "preferred", "unspecified"]
    evidence: list[JobEvidence] = Field(min_length=1)


class JobSourceAssessment(JobRecord):
    chunk_id: str = Field(min_length=1)
    relevance: Literal["direct", "adjacent", "unrelated"]
    reason: str = Field(min_length=1, max_length=500,
                        description="按实际工作任务判断与目标的联系，相关技术名词重叠不等于岗位相关")
    quote: str = Field(min_length=2, max_length=1200,
                       description="足以判断实际职责的连续原文；不能只引Python等通用技能")


class RelatedRole(JobRecord):
    title: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="与目标岗位相近的职责或技能；不代表用户已胜任或存在晋升通道")
    evidence: list[JobEvidence] = Field(min_length=1)


class JobAnalysis(JobRecord):
    summary: str = Field(min_length=1, description="只总结下方已有证据的发现，明确这是检索样本分析")
    findings: list[JobFinding] = Field(min_length=1)
    related_roles: list[RelatedRole] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_assessments: list[JobSourceAssessment] = Field(default_factory=list,
        description="逐条覆盖本次召回来源；先审实际职责相关性，direct来源才能支持核心岗位要求")
