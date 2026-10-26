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
from langgraph.errors import GraphRecursionError

logger = logging.getLogger(__name__)


@after_model(can_jump_to=["model"])
def check_model_output(state, runtime):
    message = state["messages"][-1]
    if not isinstance(message, AIMessage):
        return
    if message.response_metadata.get("finish_reason") == "length":
        raise ValueError("模型输出达到长度上限，结构化结果可能被截断。请精简输出或检查模型接口的输出 token 限制")
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

    def build_graph(self, prepared: dict):
        tools = self.get_tools(prepared) if self.use_tools else []

        return create_agent(
            model=self.model,
            tools=tools,
            system_prompt=self.system_prompt,
            response_format=self.get_output_schema(prepared),
            middleware=[
                check_model_output,
                ModelCallLimitMiddleware(
                    run_limit=self.max_model_calls,
                    exit_behavior="error"
                )
            ],
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
        if not self.should_run(prepared):
            return self.format_result()

        graph = self.build_graph(prepared)

        try:
            state = await graph.ainvoke(
                self.make_inputs(prepared),
                config=config
            )
            draft = state.get("structured_response")
            return self.format_result(draft)
        except Exception as error:
            logger.exception("Agent 执行失败：%s", self.name)
            return self.format_result(error=error)
