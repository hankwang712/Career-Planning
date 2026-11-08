import json
import logging
import re
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables.config import merge_configs
from pydantic import ValidationError, model_validator

from backend.advisor.agents.action_planning import ActionPlanningAgent, verify_action_plan
from backend.advisor.schemas.action_planning import ActionPlan, PlanningConstraints
from backend.advisor.telemetry import AgentMetrics
from backend.advisor.utils.dates import verify_education_timeline_claims

logger = logging.getLogger(__name__)


def validation_detail(error):
    """只返回字段与校验原因，不记录整份模型输出或用户材料。"""
    parts = []
    for item in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
        path = ".".join(str(key) for key in item["loc"]) or "plan"
        parts.append(f"{path}: {item['msg']}")
    return "；".join(parts)[:1600]


def repair_reduced_dependencies(plan, prepared):
    """Repair only a reduced subset; never change task content, evidence or resource limits."""
    errors = verify_action_plan(plan, prepared)
    if not any(error.startswith("缩减方案遗漏") for error in errors):
        return None
    if any(not error.startswith(("缩减方案遗漏", "缩减方案第 ")) for error in errors):
        return None

    tasks = {task.task_id: task for task in plan.tasks}
    before = list(plan.reduced_plan.keep_task_ids)
    required = set(before)
    pending = list(before)
    while pending:
        for dependency in tasks[pending.pop()].depends_on:
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)

    weeks = {week["week"]: week for week in prepared["weeks"]}
    kept, hours = set(), {}
    for task in plan.tasks:
        if task.task_id not in required or not set(task.depends_on) <= kept:
            continue
        capacity = plan.reduced_plan.weekly_hours * weeks[task.week]["days"] / 7
        if hours.get(task.week, 0) + task.hours <= capacity + 1e-6:
            kept.add(task.task_id)
            hours[task.week] = hours.get(task.week, 0) + task.hours
    if not kept:
        return None

    after = [task.task_id for task in plan.tasks if task.task_id in kept]
    deferred = [task for task in plan.tasks if task.task_id in set(before) - kept]
    added = [task for task in plan.tasks if task.task_id in kept - set(before)]
    explanation = f"每周按 {plan.reduced_plan.weekly_hours:g} 小时安排，保留任务及其必要的前置准备。"
    if added:
        explanation += "补入前置任务：" + "、".join(task.title for task in added) + "。"
    if deferred:
        explanation += "缩减时间下暂缓：" + "、".join(task.title for task in deferred) + "。"
    repaired = plan.model_copy(deep=True)
    repaired.reduced_plan.keep_task_ids = after
    repaired.reduced_plan.reason = explanation
    if verify_action_plan(repaired, prepared):
        return None
    plan.reduced_plan = repaired.reduced_plan
    return {"requested_task_ids": before, "kept_task_ids": after,
            "added_dependency_ids": [task.task_id for task in added],
            "deferred_task_ids": [task.task_id for task in deferred]}


class ReportActionPlanningAgent(ActionPlanningAgent):
    def __init__(self, model, *, stage_callback=None, resume_planning=False, **kwargs):
        super().__init__(model, **kwargs)
        self.stage_callback = stage_callback
        self.resume_planning = resume_planning

    def prepare(self, payload):
        supplied = deepcopy(payload)
        constraints = PlanningConstraints.model_validate(supplied["constraints"])
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        adjustment = None
        if self.resume_planning and constraints.start_date and constraints.start_date < today:
            if constraints.deadline < today:
                raise ValueError("原行动规划的截止日期已过去，请重新确认规划日期后再生成")
            adjustment = {"requested_start_date": constraints.start_date.isoformat(),
                          "effective_start_date": today.isoformat(), "deadline": constraints.deadline.isoformat()}
            supplied["constraints"] = {**constraints.model_dump(mode="json"), "start_date": today.isoformat()}
        prepared = super().prepare(supplied)
        if adjustment:
            prepared["start_date_adjustment"] = adjustment
            prepared["input_limitations"].append(
                f"原计划起点 {adjustment['requested_start_date']} 已过去，恢复时从 {today.isoformat()} 起安排剩余任务；"
                "截止日期、每周可用时间和预算保持不变。")
            self.notify("原计划开始日期已过去，正在从今天起重算剩余时间，截止日期不变")
        return prepared

    def get_output_schema(self, prepared):
        parent = super().get_output_schema(prepared)

        class CareerDevelopmentPlan(parent):
            @model_validator(mode="after")
            def require_roadmap(self):
                errors = verify_education_timeline_claims(self.model_dump(), "\n".join(
                    source["content"] for source in prepared.get("sources", []) if source["kind"] == "resume"))
                if errors:
                    raise ValueError("；".join(errors))
                if len(self.development_roadmap) != 3:
                    raise ValueError("请提供 short、mid、long 三阶段成长路线，每阶段包含具体准备事项、交付物、验收标准和调整条件")
                return self

        return CareerDevelopmentPlan

    def notify(self, message):
        if self.stage_callback:
            self.stage_callback("action_planning", "行动规划", message)

    async def _arun_prepared(self, prepared, config=None):
        schema = self.get_output_schema(prepared)
        metrics = AgentMetrics()
        contract = json.dumps(schema.model_json_schema(mode="validation"), ensure_ascii=False)
        messages = [SystemMessage(content=self.system_prompt + "\n\n直接返回一个符合以下 JSON Schema 的 JSON 对象，不调用工具，不使用 Markdown 围栏：\n" + contract),
                    *self.make_inputs(prepared)["messages"]]
        attempts = min(self.max_model_calls, 3)
        result = None
        accepted_adjustment = None
        for attempt in range(1, attempts + 1):
            self.notify(f"正在生成行动计划（第 {attempt}/{attempts} 次），随后校验工时、预算与依赖")
            try:
                # 该 Agent 无外部工具。JSON 模式避免 provider 未提交结构化工具调用时空转。
                model = self.model.bind(response_format={"type": "json_object"}, temperature=0)
                message = await model.ainvoke(messages, config=merge_configs(config, {"callbacks": [metrics]}))
            except Exception as error:
                logger.warning("行动规划模型请求失败：%s", type(error).__name__)
                result = self.format_result(error=error)
                break

            content = message.content
            if isinstance(content, list):
                content = "".join(block if isinstance(block, str) else block.get("text", "")
                                  for block in content if isinstance(block, (str, dict)))
            if not isinstance(content, str):
                content = ""
            fenced = re.fullmatch(r"\s*```(?:json)?\s*([\s\S]*?)\s*```\s*", content)
            if fenced:
                content = fenced[1]
            if (message.response_metadata or {}).get("finish_reason") == "length":
                detail = "输出被截断，请减少任务数量、精简说明，同时保留所有必填字段与约束。"
            else:
                try:
                    candidate = ActionPlan.model_validate_json(content)
                    adjustment = repair_reduced_dependencies(candidate, prepared)
                    draft = schema.model_validate(candidate.model_dump(mode="json"))
                except ValidationError as error:
                    detail = validation_detail(error)
                else:
                    accepted_adjustment = adjustment
                    if adjustment:
                        self.notify("已核对缩减方案的前置依赖，并按缩减工时保留可执行任务")
                    self.notify("行动计划已通过结构、工时、预算与依赖校验")
                    result = self.format_result(draft)
                    break

            logger.warning("行动规划校验未通过（%s/%s）：%s", attempt, attempts, detail)
            action = "正在修正" if attempt < attempts else "已停止本次生成"
            self.notify(f"行动计划未通过校验，{action}（第 {attempt}/{attempts} 次）：{detail[:400]}")
            result = {"agent": self.name, "status": "validation_failed", "data": {},
                      "error": f"行动规划结果在 {attempt} 次尝试后仍未通过校验：{detail}"}
            if attempt < attempts:
                messages.extend([AIMessage(content=content), HumanMessage(content=
                    "上次 JSON 未通过校验，原因如下：\n" + detail +
                    "\n请返回修正后的完整 JSON。保持原始证据和 check_id，不增加用户时间或预算，无法安排的任务放入 deferred_actions。")])

        result["execution"] = {**metrics.summary(), "output_mode": "validated_json", "attempts": attempt}
        if accepted_adjustment:
            result["execution"]["reduced_plan_adjustment"] = accepted_adjustment
        if prepared.get("start_date_adjustment"):
            result["execution"]["start_date_adjustment"] = prepared["start_date_adjustment"]
        model_name = getattr(self.model, "model_name", None) or getattr(self.model, "model", None)
        if isinstance(model_name, str):
            result["execution"]["model"] = model_name
        return result
