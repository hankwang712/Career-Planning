import logging
from abc import ABC, abstractmethod
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agents.base import BaseAgent

logger = logging.getLogger(__name__)


def ensure_agent_result(result: dict) -> dict:
    """统一 HTTP 状态映射；不向客户端透出底层异常详情。"""
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Agent 返回格式错误")
    status = result.get("status")
    if status in ("ok", "insufficient_evidence"):
        return result
    errors = {
        "execution_limit": (503, "达到执行次数上限"),
        "model_error": (502, "模型执行失败"),
        "validation_failed": (502, "模型输出校验失败"),
    }
    if not isinstance(status, str) or not status.strip():
        raise HTTPException(status_code=500, detail="Agent 返回状态错误")
    status_code, message = errors.get(status, (502, "Agent 执行失败"))
    raise HTTPException(status_code=status_code, detail={"status": status, "message": message})


class AgentResponse(BaseModel):
    """与 BaseAgent.format_result() 对应的通用响应。"""

    model_config = ConfigDict(extra="allow")

    agent: str
    status: str = Field(min_length=1, description="由 Agent 定义状态，API 对未单独分类的失败统一处理")
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BaseAgentAPI(ABC):
    """封装 Router、异步 Agent 调用和 HTTP 错误处理。"""

    def __init__(self, agent: BaseAgent, *, prefix: str = "", tags: list[str] | None = None,):
        self.agent = agent
        self.router = APIRouter(prefix=prefix, tags=tags or [])
        self.register_routes()

    @abstractmethod
    def register_routes(self) -> None:
        """子类定义请求模型、路由，并通过 execute() 调用 Agent。"""

    async def execute(self, request: BaseModel) -> dict:
        try:
            result = await self.agent.arun(request.model_dump(mode="json"))
        except Exception as exc:
            logger.exception("Agent 执行异常")
            raise HTTPException(status_code=500, detail="Agent 服务内部错误") from exc

        return ensure_agent_result(result)
