import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables.config import merge_configs
from pydantic import ValidationError, model_validator

from experiments.news_advisor.agents.action_planning import ActionPlanningAgent
from experiments.news_advisor.telemetry import AgentMetrics

logger = logging.getLogger(__name__)


def validation_detail(error):
    """只返回字段与校验原因，不记录整份模型输出或用户材料。"""
    parts = []
    for item in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
        path = ".".join(str(key) for key in item["loc"]) or "plan"
        parts.append(f"{path}: {item['msg']}")
    return "；".join(parts)[:1600]


class ReportActionPlanningAgent(ActionPlanningAgent):
    def __init__(self, model, *, stage_callback=None, **kwargs):
        super().__init__(model, **kwargs)
        self.stage_callback = stage_callback

    def get_output_schema(self, prepared):
        parent = super().get_output_schema(prepared)

        class CareerDevelopmentPlan(parent):
            @model_validator(mode="after")
            def require_roadmap(self):
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
                    draft = schema.model_validate_json(content)
                except ValidationError as error:
                    detail = validation_detail(error)
                else:
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
        model_name = getattr(self.model, "model_name", None) or getattr(self.model, "model", None)
        if isinstance(model_name, str):
            result["execution"]["model"] = model_name
        return result
