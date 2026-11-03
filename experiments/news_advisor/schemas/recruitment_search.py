from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .followup import Clarification


Text = Annotated[str, Field(min_length=1)]
RecruitmentType = Literal["社招", "春招", "秋招", "实习", "校招"]


class SearchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecruitmentSearchInput(SearchRecord):
    request: Annotated[str, Field(min_length=1, max_length=3000)]
    channel: Literal["wechat", "web", "all"] = "wechat"
    days: Annotated[int, Field(ge=1, le=365)] | None = None
    limit: int = Field(default=5, ge=1, le=10)
    clarifications: list[Clarification] = Field(default_factory=list)


class SearchIntent(SearchRecord):
    direction: Text | None = Field(default=None, description="用户表达的职业方向，如大模型、智能驾驶；未表达时为空")
    companies: list[Text] = Field(default_factory=list)
    roles: list[Text] = Field(default_factory=list)
    cities: list[Text] = Field(default_factory=list)
    recruitment_types: list[RecruitmentType] = Field(default_factory=list)
    graduation_cohorts: list[Text] = Field(default_factory=list)
    industries: list[Text] = Field(default_factory=list, description="为发现企业而推导的相关行业，不是用户指定的硬限制")
    expanded_roles: list[Text] = Field(default_factory=list, description="从职业方向展开、用于实际搜索的岗位名称")
    expansion_reason: Text | None = Field(default=None, description="简要解释职业方向与推导行业、岗位的关联，不声称用户已具备这些能力")
    days: Annotated[int, Field(ge=1, le=365)] | None = Field(
        default=30, description="招聘时效窗口；用户未指定时用30天，非时效性流程资料可为空"
    )


class RecruitmentFinding(SearchRecord):
    source_id: Text
    match_status: Literal["matches_request", "needs_confirmation"]
    summary: Text
    relevance: Text
    evidence_quotes: list[Text] = Field(min_length=1, max_length=3)
    unverified_conditions: list[Text] = Field(default_factory=list)


class RecruitmentSearchResult(SearchRecord):
    outcome: Literal["found", "no_match", "needs_clarification", "unavailable"]
    summary: Text
    intent: SearchIntent
    findings: list[RecruitmentFinding] = Field(default_factory=list, max_length=10)
    followup_questions: list[Text] = Field(default_factory=list, max_length=3)
    limitations: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_outcome(self):
        if (self.outcome == "found") != bool(self.findings):
            raise ValueError("found 必须有结果，其他 outcome 不应包含推荐结果")
        if self.outcome == "needs_clarification" and not self.followup_questions:
            raise ValueError("需要澄清时必须给出具体问题")
        return self
