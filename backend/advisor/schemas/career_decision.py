from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .followup import Clarification


Text = Annotated[str, Field(min_length=1)]


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CareerTarget(DecisionRecord):
    target_id: Text
    title: Text
    target_type: Literal["job", "direction"] = "direction"
    job_analysis: dict[str, Any] = Field(description="岗位 Agent 完整返回值，包含 status、data、sources、scope")


class JobEvidenceRequest(DecisionRecord):
    target_id: Text
    question: str = Field(min_length=1, max_length=1000, description="交给岗位 Agent 补查的公开岗位要求，不含用户经历或个人资料")
    reason: str = Field(min_length=1, max_length=500, description="缺少哪项岗位证据，以及它如何影响当前判断")


class JobEvidenceFeedback(DecisionRecord):
    target_id: Text
    question: str = Field(min_length=1, max_length=1000)
    outcome: Literal["added", "no_new_evidence", "unavailable"]


class CareerDecisionInput(DecisionRecord):
    raw_resume: str = ""
    additional_evidence: str = ""
    preferences: str = ""
    question: str = ""
    resume_analysis: dict[str, Any] = Field(default_factory=dict)
    recruitment_search: dict[str, Any] = Field(default_factory=dict, description="招聘搜索的完整结果；已读原文可补充方向要求对照，汇总线索保留待核实性质")
    clarifications: list[Clarification] = Field(default_factory=list)
    targets: list[CareerTarget] = Field(min_length=1, max_length=5)
    evidence_rounds_remaining: int = Field(default=0, ge=0, le=2)
    evidence_feedback: list[JobEvidenceFeedback] = Field(default_factory=list, max_length=6)

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
    checks: list[RequirementCheck] = Field(default_factory=list, description="仅对有目标相关岗位证据的要求作检查；没有相关证据时为空并使用insufficient_information")


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
    evidence_requests: list[JobEvidenceRequest] = Field(default_factory=list, max_length=3,
        description="需要岗位 Agent 定向补查的证据缺口；用户经历、意愿等问题仍放入 followup_questions")
