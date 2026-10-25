from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Text = Annotated[str, Field(min_length=1)]


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CareerTarget(DecisionRecord):
    target_id: Text
    title: Text
    target_type: Literal["job", "direction"] = "direction"
    job_analysis: dict[str, Any] = Field(description="岗位 Agent 完整返回值，包含 status、data、sources、scope")


class CareerDecisionInput(DecisionRecord):
    raw_resume: str = ""
    additional_evidence: str = ""
    preferences: str = ""
    question: str = ""
    resume_analysis: dict[str, Any] = Field(default_factory=dict)
    targets: list[CareerTarget] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_targets(self):
        ids = [target.target_id for target in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("target_id 不得重复")
        return self


class CareerDirectionPlan(DecisionRecord):
    directions: list[Text] = Field(min_length=1, max_length=5, description="只拆分用户明确提出的职业方向，不把城市、时间或实习类型当作独立方向")


class DecisionEvidence(DecisionRecord):
    source_id: Text
    quote: Text


class RequirementCheck(DecisionRecord):
    check_id: Text
    requirement: Text
    kind: Literal["hard_condition", "capability"]
    importance: Literal["required", "preferred", "unspecified"]
    status: Literal["supported", "partial", "evidence_missing", "confirmed_gap", "unknown"]
    job_evidence: list[DecisionEvidence] = Field(min_length=1)
    candidate_evidence: list[DecisionEvidence] = Field(default_factory=list)
    reasoning: Text

    @model_validator(mode="after")
    def require_support(self):
        if self.status in {"supported", "partial", "confirmed_gap"} and not self.candidate_evidence:
            raise ValueError("已支持、部分支持和已确认差距必须提供学生原文证据")
        return self


class TargetAssessment(DecisionRecord):
    target_id: Text
    decision: Literal["recommended", "conditional", "not_recommended", "insufficient_information"]
    conclusion: Text
    checks: list[RequirementCheck] = Field(min_length=1)


class DecisionAction(DecisionRecord):
    target_id: Text
    check_id: Text
    kind: Literal["clarify", "document", "practice", "apply"]
    action: Text
    deliverable: Text
    acceptance_criteria: Text


class CareerDecision(DecisionRecord):
    summary: Text
    assessments: list[TargetAssessment] = Field(min_length=1)
    comparison: Text | None = None
    next_actions: list[DecisionAction] = Field(default_factory=list, max_length=3)
    followup_questions: list[Text] = Field(default_factory=list, max_length=3)
    limitations: list[Text] = Field(default_factory=list)
