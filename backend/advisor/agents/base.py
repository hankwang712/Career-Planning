import json
import logging
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, after_model
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.structured_output import StructuredOutputError
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import merge_configs
from langgraph.errors import GraphRecursionError

from ..telemetry import AgentMetrics

logger = logging.getLogger(__name__)


class ModelOutputTruncatedError(ValueError):
    """模型达到输出上限，不能将可能不完整的结构化结果交给后续节点。"""


@after_model(can_jump_to=["model"])
def check_model_output(state, runtime):
    # 结构化输出解析器可能已在本次响应后追加 ToolMessage，仍需检查模型原始响应。
    message = next((item for item in reversed(state["messages"]) if isinstance(item, AIMessage)), None)
    if message is None:
        return
    if message.response_metadata.get("finish_reason") == "length":
        usage = message.usage_metadata or message.response_metadata.get("token_usage") or {}
        tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        detail = f"，本次输出 {tokens} token" if isinstance(tokens, int) and not isinstance(tokens, bool) else ""
        raise ModelOutputTruncatedError(
            f"模型输出达到长度上限（finish_reason=length{detail}），结构化结果可能被截断。"
            "请精简输出或检查模型接口的输出 token 限制"
        )
    if message.invalid_tool_calls:
        # 替换损坏的工具调用，避免下一次请求包含未配对的 tool_call；原始响应由调用方诊断记录保存。
        if not message.id:
            raise ValueError("模型返回了无法解析的工具参数 JSON，且消息缺少用于替换的 ID")
        return {
            "messages": [
                AIMessage(content="上一条结构化输出的工具参数不是有效 JSON，已拒绝执行。", id=message.id),
                HumanMessage(content="请重新提交完整的结构化工具参数，使用严格有效的 JSON。字符串内的引号、反斜杠和换行必须正确转义，不要添加 Markdown 围栏。保持原有事实和原文证据，不要为避免格式错误删减关键要求。"),
            ],
            "jump_to": "model",
        }


class BaseAgent(ABC):
    """通用 Agent 基类，负责模型执行、工具调用与结构化输出。"""

    name = "base"
    system_prompt = ""

    def __init__(self, model, *, use_tools=True, max_model_calls=5):
        if not 1 <= max_model_calls <= 10:
            raise ValueError("模型调用次数必须在 1~10 之间")

        self.model = model
        self.use_tools = use_tools
        self.max_model_calls = max_model_calls

    # ============== 子类接口 ==============

    @abstractmethod
    def prepare(self, payload: dict) -> dict:
        """预处理输入数据。"""

    @abstractmethod
    def get_output_schema(self, prepared: dict) -> type[BaseModel]:
        """返回 Pydantic 输出模型。"""

    def get_tools(self, prepared: dict) -> list:
        """返回当前 Agent 可使用的工具。"""
        return []

    def should_run(self, prepared: dict) -> bool:
        """判断是否需要执行模型。"""
        return True

    # ============== 工作流构建 ==============

    def get_middleware(self, prepared: dict):
        return [check_model_output, ModelCallLimitMiddleware(run_limit=self.max_model_calls, exit_behavior="error")]

    def build_graph(self, prepared: dict):
        tools = self.get_tools(prepared) if self.use_tools else []

        return create_agent(
            model=self.model,
            tools=tools,
            system_prompt=self.system_prompt,
            response_format=self.get_output_schema(prepared),
            # 外层报告图按完整 Agent 步骤持久化。内部图不继承检查点，否则外层
            # 重试会恢复到旧的 after_model 节点，永远不会重新请求模型。
            checkpointer=False,
            middleware=self.get_middleware(prepared),
        ).with_config(
            recursion_limit=6 * self.max_model_calls + 5
        )

    # ============== 结果处理 ==============

    def format_result(self, draft=None, error=None):
        if error is None:
            status = "ok" if draft is not None else "insufficient_evidence"
            message = None
        elif isinstance(error, (ModelCallLimitExceededError, GraphRecursionError)):
            status = "execution_limit"
            message = "达到执行次数上限"
        elif isinstance(error, ModelOutputTruncatedError):
            status = "model_error"
            message = str(error)
        elif isinstance(error, (StructuredOutputError, ValidationError)):
            status = "validation_failed"
            message = str(error)
        else:
            status = "model_error"
            message = f"执行失败：{type(error).__name__}"

        return {
            "agent": self.name,
            "status": status,
            "data": draft.model_dump(mode="json") if draft is not None else {},
            "error": message
        }

    def make_inputs(self, prepared: dict):
        return {
            "messages": [
                HumanMessage(
                    content=json.dumps(prepared, ensure_ascii=False)
                )
            ]
        }

    # ============== 异步调用 ==============

    async def arun(self, payload: dict, config: RunnableConfig | None = None) -> dict:
        return await self._arun_prepared(self.prepare(payload), config=config)

    async def _arun_prepared(self, prepared: dict, config: RunnableConfig | None = None) -> dict:
        """执行已整理的输入，供需要基于同一份材料校验结果的子类复用。"""
        metrics = AgentMetrics()
        if not self.should_run(prepared):
            return {**self.format_result(), "execution": metrics.summary()}

        try:
            graph = self.build_graph(prepared)
            state = await graph.ainvoke(
                self.make_inputs(prepared),
                config=merge_configs(config, {"callbacks": [metrics]}),
                # 不继承外层 durability="sync"：本图没有检查点，部分 LangGraph
                # 版本仍会等待不存在的 checkpoint future。外层继续同步保存步骤。
                durability="exit",
            )
            draft = state.get("structured_response")
            result = self.format_result(draft)
        except Exception as error:
            # 仅记录用量和额度，不记录简历正文、模型输出或密钥。
            budget = (getattr(self.model, "extra_body", None) or {}).get("max_tokens")
            if budget is None:
                budget = getattr(self.model, "max_tokens", None)
            logger.exception("Agent 执行失败：%s | max_output_tokens=%s execution=%s",
                             self.name, budget, metrics.summary())
            result = self.format_result(error=error)
        result["execution"] = metrics.summary()
        model = getattr(self.model, "model_name", None) or getattr(self.model, "model", None)
        if isinstance(model, str):
            result["execution"]["model"] = model
        return result
