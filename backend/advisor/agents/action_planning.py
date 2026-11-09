from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from pydantic import model_validator

from ..prompt.action_planning import ACTION_PLANNING_PROMPT
from ..schemas.action_planning import ActionPlan, ActionPlanningInput
from ..schemas.career_decision import CareerDecision
from .base import BaseAgent
from .career_decision import CareerDecisionAgent, verify_career_decision


def verify_action_plan(plan: ActionPlan, prepared: dict) -> list[str]:
    """校验关联、依赖及资源约束；任务语义和工时合理性仍需业务复核。"""
    checks = {item["check_id"]: item for item in prepared["assessment"]["checks"]}
    weeks = {item["week"]: item for item in prepared["weeks"]}
    tasks, hours, errors = {}, {}, []
    blocked_job = prepared["target"]["target_type"] == "job" and any(
        check["kind"] == "hard_condition" and check["importance"] == "required"
        and check["status"] == "confirmed_gap" for check in checks.values()
    )
    for task in plan.tasks:
        if task.task_id in tasks:
            errors.append(f"task_id 重复：{task.task_id}")
        check = checks.get(task.check_id)
        if check is None:
            errors.append(f"任务 {task.task_id} 未关联所选目标的有效 check_id")
        elif check["kind"] == "hard_condition" and task.kind == "practice":
            errors.append(f"任务 {task.task_id} 不能用能力练习解决硬条件")
        if blocked_job and task.kind in {"practice", "apply"}:
            errors.append("具体岗位存在明确硬条件冲突，只能先核实或整理材料")
        if task.kind == "apply" and prepared["assessment"]["decision"] != "recommended":
            errors.append("当前决策不支持安排投递任务，请先核实条件")
        if task.week not in weeks:
            errors.append(f"任务 {task.task_id} 超出规划期限")
        for dependency in task.depends_on:
            if dependency not in tasks or tasks[dependency].week > task.week:
                errors.append(f"任务 {task.task_id} 的依赖 {dependency} 必须排列在前且不晚于本周期")
        if len(set(task.depends_on)) != len(task.depends_on):
            errors.append(f"任务 {task.task_id} 的依赖重复")
        tasks[task.task_id] = task
        hours[task.week] = hours.get(task.week, 0) + task.hours
    for week, total in hours.items():
        if week in weeks and total > weeks[week]["hours_capacity"] + 1e-6:
            errors.append(f"第 {week} 周工时超出可用时间")
    budget = prepared["constraints"]["budget"]
    if budget is not None and sum(task.cost for task in plan.tasks) > budget + 1e-6:
        errors.append("任务支出超出本阶段预算")

    reduced = plan.reduced_plan
    keep = set(reduced.keep_task_ids)
    if len(keep) != len(reduced.keep_task_ids) or not keep <= tasks.keys():
        errors.append("缩减方案必须保留非空、无重复的有效任务子集")
    if reduced.weekly_hours >= prepared["constraints"]["weekly_hours"]:
        errors.append("缩减方案每周工时必须小于原可用时间")
    reduced_hours = {}
    for task_id in keep & tasks.keys():
        task = tasks[task_id]
        if not set(task.depends_on) <= keep:
            errors.append(f"缩减方案遗漏了任务 {task_id} 的前置依赖")
        reduced_hours[task.week] = reduced_hours.get(task.week, 0) + task.hours
    for week, total in reduced_hours.items():
        if week in weeks and total > reduced.weekly_hours * weeks[week]["days"] / 7 + 1e-6:
            capacity = reduced.weekly_hours * weeks[week]["days"] / 7
            errors.append(f"缩减方案第 {week} 周工时超出可用时间：保留任务合计 {total:g} 小时，"
                          f"上限 {capacity:g} 小时（每周 {reduced.weekly_hours:g} 小时 × {weeks[week]['days']}/7）；"
                          "请删减 keep_task_ids 并保留依赖，或在小于原每周时间的范围内调整 weekly_hours")
    if plan.development_roadmap:
        if [item.horizon for item in plan.development_roadmap] != ["short", "mid", "long"]:
            errors.append("成长路线必须按 short、mid、long 顺序各提供一个阶段")
        for milestone in plan.development_roadmap:
            for action in milestone.actions:
                check = checks.get(action.check_id)
                if check is None:
                    errors.append("成长路线引用了无效 check_id")
                elif check["kind"] == "hard_condition" and action.kind == "practice":
                    errors.append("成长路线不能用能力练习解决硬条件")
                if blocked_job and action.kind in {"practice", "apply"}:
                    errors.append("具体岗位存在硬条件冲突，成长路线应先核实或重新选择目标")
                if action.kind == "apply" and prepared["assessment"]["decision"] != "recommended":
                    errors.append("当前决策不支持成长路线中的投递任务")
    return list(dict.fromkeys(errors))


class ActionPlanningAgent(BaseAgent):
    name = "action_planning"
    system_prompt = ACTION_PLANNING_PROMPT

    def prepare(self, payload: dict) -> dict:
        request = ActionPlanningInput.model_validate(payload)
        if request.decision_result.get("status") != "ok":
            raise ValueError("行动规划需要成功的职业决策结果")
        upstream = CareerDecisionAgent.prepare(request.decision_input.model_dump())
        decision = CareerDecision.model_validate(request.decision_result.get("data", {})).model_dump()
        errors = verify_career_decision(decision, upstream)
        if errors:
            raise ValueError("职业决策与原始输入不一致：" + "；".join(errors))
        target = next((item for item in upstream["targets"] if item["target_id"] == request.target_id), None)
        if target is None:
            raise ValueError("所选目标没有可用的岗位分析")
        assessment = next(item for item in decision["assessments"]
                          if item["target_id"] == request.target_id)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        start = request.constraints.start_date or today
        deadline = request.constraints.deadline
        if start < today or deadline < start:
            raise ValueError("规划起始日期不得早于今天，截止日期不得早于起始日期")
        if (deadline - start).days >= 366:
            raise ValueError("本阶段规划最多覆盖 366 天")
        constraints = request.constraints.model_dump(mode="json")
        constraints["start_date"] = start.isoformat()
        weeks = []
        cursor = start
        while cursor <= deadline:
            end = min(cursor + timedelta(days=6), deadline)
            days = (end - cursor).days + 1
            weeks.append({"week": len(weeks) + 1, "start_date": cursor.isoformat(),
                          "end_date": end.isoformat(), "days": days,
                          "hours_capacity": request.constraints.weekly_hours * days / 7})
            cursor = end + timedelta(days=1)
        return {
            "target": target, "assessment": assessment,
            "sources": [source for source in upstream["sources"]
                        if source["kind"] != "job" or source.get("target_id") == request.target_id],
            "constraints": constraints, "weeks": weeks,
            "education_timeline": upstream["education_timeline"],
            "resume_diagnostics": upstream["resume_analysis"].get("diagnostics", {}),
            "recruitment_context": upstream["recruitment_context"],
            "input_limitations": list(dict.fromkeys(
                upstream["input_limitations"] + decision["limitations"]
            )),
        }

    def get_output_schema(self, prepared: dict):
        class FeasibleActionPlan(ActionPlan):
            @model_validator(mode="after")
            def check_constraints(self):
                errors = verify_action_plan(self, prepared)
                if errors:
                    raise ValueError("；".join(errors))
                self.limitations = list(dict.fromkeys(prepared["input_limitations"] + self.limitations))
                return self

        return FeasibleActionPlan

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        prepared = self.prepare(payload)
        result = await self._arun_prepared(prepared, config=config)
        result.update(target_id=prepared["target"]["target_id"],
                      constraints=prepared["constraints"], weeks=prepared["weeks"])
        return result
