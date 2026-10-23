import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """与 BaseAgent.format_result() 对应的通用响应。"""

    model_config = ConfigDict(extra="allow")

    agent: str
    status: Literal[
        "ok", "insufficient_evidence", "execution_limit",
        "model_error", "validation_failed",
    ]
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

        if not isinstance(result, dict):
            logger.error("Agent 返回值不是字典")
            raise HTTPException(status_code=500, detail="Agent 返回格式错误")

        status = result.get("status")
        if status in ("ok", "insufficient_evidence"):
            return result

        errors = {
            "execution_limit": (503, "达到执行次数上限"),
            "model_error": (502, "模型执行失败"),
            "validation_failed": (502, "模型输出校验失败"),
        }
        # 未知状态也视为内部错误；响应不包含底层异常详情。
        if not isinstance(status, str):
            raise HTTPException(status_code=500, detail="Agent 返回状态错误")
        status_code, message = errors.get(status, (500, "Agent 返回状态错误"))
        raise HTTPException(
            status_code=status_code,
            detail={"status": status, "message": message},
        )
