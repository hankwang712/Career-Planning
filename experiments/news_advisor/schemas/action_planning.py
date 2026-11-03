from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .career_decision import CareerDecisionInput


class PlanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class PlanningConstraints(PlanRecord):
    student_stage: Literal["exploration", "employment", "unspecified"] = Field(
        default="unspecified", description="用户选择：大一大二职业探索 / 大三大四及研究生就业准备 / 尚未说明；不得从学历推断年级")
    weekly_hours: float = Field(gt=0, le=168)
    deadline: date
    start_date: date | None = None
    budget: float | None = Field(default=None, ge=0, description="本阶段可用预算，人民币；空值表示未知")
    completed_tasks: list[str] = Field(default_factory=list, description="用户自述已完成的任务，不自动视为能力证明")


class ActionPlanningInput(PlanRecord):
    decision_input: CareerDecisionInput
    decision_result: dict[str, Any] = Field(description="与 decision_input 对应的职业决策 Agent 完整结果")
    target_id: str = Field(min_length=1)
    constraints: PlanningConstraints


class PlanTask(PlanRecord):
    task_id: str = Field(min_length=1)
    check_id: str = Field(min_length=1, description="所选目标下的真实检查项")
    stage: str = Field(min_length=1)
    kind: Literal["clarify", "document", "practice", "apply"]
    title: str = Field(min_length=1)
    week: int = Field(ge=1, description="以 start_date 为起点的第几个七天周期")
    hours: float = Field(gt=0)
    cost: float = Field(default=0, ge=0, description="估算支出，不代表已核验的商品或课程价格")
    depends_on: list[str] = Field(default_factory=list)
    deliverable: str = Field(min_length=1)
    acceptance_criteria: str = Field(min_length=1)


class ReducedPlan(PlanRecord):
    weekly_hours: float = Field(gt=0, description="比原计划更少的每周可用时间")
    keep_task_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, description="保留什么、删减什么，以及暂缓的影响")


class DevelopmentAction(PlanRecord):
    check_id: str = Field(min_length=1)
    kind: Literal["clarify", "document", "practice", "apply"]
    title: str = Field(min_length=1, description="具体要准备或完成的事情，不能只写提升能力")
    deliverable: str = Field(min_length=1)
    acceptance_criteria: str = Field(min_length=1)


class DevelopmentMilestone(PlanRecord):
    horizon: Literal["short", "mid", "long"]
    objective: str = Field(min_length=1)
    actions: list[DevelopmentAction] = Field(min_length=1, max_length=4)
    entry_conditions: str = Field(min_length=1, description="进入阶段所需条件；未知资格核实后再推进，不默认满足")
    review_trigger: str = Field(min_length=1, description="何时复核、看哪些成果、什么情况下调整方向")


class ActionPlan(PlanRecord):
    summary: str = Field(min_length=1)
    tasks: list[PlanTask] = Field(min_length=1, max_length=30, description="按依赖执行顺序排列")
    reduced_plan: ReducedPlan
    deferred_actions: list[str] = Field(default_factory=list, description="期限或预算内未安排的行动及原因")
    limitations: list[str] = Field(default_factory=list)
    development_roadmap: list[DevelopmentMilestone] = Field(
        default_factory=list, max_length=3,
        description="短期1—3个月、中期3—12个月、长期1—3年的条件性成长路线；与已排工时的本阶段任务分开")
