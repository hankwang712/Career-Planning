"""分层记忆实验入口：python -m experiments.run_memory_advisor --start-redis。

仅供本机实验。接入主站时 user_id 必须取自服务端已验证的登录态。
"""

import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
import json
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from redis.exceptions import RedisError

from .news_advisor.api.base_api import ensure_agent_result
from .news_advisor.config import get_ai_config
from .news_advisor.graph import AGENTS, AgentExecutionError, build_advisor_graph, followup_questions
from .news_advisor.memory.config import get_memory_config
from .news_advisor.memory.recent import MemoryBusyError, digest
from .news_advisor.memory.service import open_memory_service
from .news_advisor.schemas.workflow import AgentRequest, ThreadCheckpoint

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_model():
    settings = get_ai_config("chat")
    return ChatOpenAI(api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
                      extra_body={"thinking": {"type": "disabled"}}, timeout=90, max_retries=1)


class MemorySubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=2, max_length=12000)
    session_id: str = Field(default="profile", min_length=1, max_length=200)
    event_id: UUID = Field(default_factory=uuid4, description="重试同一次提交时复用此 UUID")


def create_memory_app(model_provider=get_model, *, config=None, memory_factory=open_memory_service):
    config = config or get_memory_config()

    @asynccontextmanager
    async def lifespan(app):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        async with memory_factory(model_provider, config) as memory:
            async with AsyncSqliteSaver.from_conn_string(str(config.data_dir / "checkpoints.sqlite3")) as saver:
                app.state.memory = memory
                app.state.graph = build_advisor_graph(model_provider, checkpointer=saver, memory=memory)
                yield

    app = FastAPI(title="职业多智能体与分层记忆实验", lifespan=lifespan,
                  description="本机实验接口，5 类 Agent 共享用户长期记忆。user_id 为演示分区标识，尚未接入登录鉴权。")

    @app.exception_handler(MemoryBusyError)
    async def memory_busy(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(RedisError)
    async def redis_unavailable(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"detail": "Redis 不可用，请检查 Docker 记忆服务"})

    @app.get("/", include_in_schema=False)
    async def index():
        return RedirectResponse("/docs")

    @app.get("/health")
    async def health():
        await app.state.memory.recent.redis.ping()
        await asyncio.to_thread(app.state.memory.long_term.collection.count)
        return {"status": "ok", "agents": list(AGENTS), "redis": "ok", "chroma": "ok"}

    def graph_config(user_id, thread_id):
        if not 1 <= len(user_id) <= 200 or not 1 <= len(thread_id) <= 200:
            raise HTTPException(422, "用户和会话标识长度应为 1~200")
        # JSON 元组避免分隔符拼接碰撞；客户端不能指定底层 checkpoint thread_id。
        thread_key = digest(json.dumps([user_id, thread_id], ensure_ascii=False))
        return {"configurable": {"thread_id": thread_key, "user_id": user_id, "session_id": thread_id}}

    async def snapshot(user_id, thread_id):
        state = await app.state.graph.aget_state(graph_config(user_id, thread_id))
        if not state.values:
            raise HTTPException(404, "线程不存在")
        return {
            "user_id": user_id, "thread_id": thread_id,
            "checkpoint_id": state.config["configurable"].get("checkpoint_id"),
            "values": state.values, "next": list(state.next),
            "errors": [{"node": task.name, "error": "执行失败，可重试"} for task in state.tasks if task.error],
            "followup_questions": {name: followup_questions(result)
                                   for name, result in state.values.get("results", {}).items()},
        }

    async def invoke(user_id, thread_id, request):
        invocation_config = graph_config(user_id, thread_id)
        # 整次调用按用户串行，防止不同线程并行修改相同偏好及读取过期状态。
        async with app.state.memory.recent.lock(user_id, scope="invocation"):
            graph = app.state.graph
            state = await graph.aget_state(invocation_config)
            checkpoint = state.config["configurable"].get("checkpoint_id")
            if request.checkpoint_id is not None and request.checkpoint_id != checkpoint:
                raise HTTPException(409, "检查点已更新，请读取最新状态")
            if isinstance(request, AgentRequest):
                if state.next and state.next != ("prepare",):
                    raise HTTPException(409, "存在未完成节点，请先重试；新咨询可使用其他会话 ID")
                inputs = {"request": request.model_dump(mode="json")}
            else:
                if not state.next:
                    raise HTTPException(422, "没有待恢复的节点")
                inputs = None
            try:
                await graph.ainvoke(inputs, invocation_config, durability="sync")
            except (MemoryBusyError, RedisError):
                raise
            except ValidationError as error:
                raise HTTPException(422, error.errors(include_context=False, include_input=False)) from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            except AgentExecutionError as error:
                ensure_agent_result(error.result)
            except Exception:
                logger.exception("分层记忆工作流执行失败")
                raise HTTPException(502, "记忆提取、向量服务或摘要执行失败，可从当前线程重试") from None
            return await snapshot(user_id, thread_id)

    base = "/api/memory-advisor/users/{user_id}"

    @app.post(base + "/threads/{thread_id}")
    async def run(user_id: str, thread_id: str, request: AgentRequest):
        return await invoke(user_id, thread_id, request)

    @app.get(base + "/threads/{thread_id}")
    async def get_thread(user_id: str, thread_id: str):
        return await snapshot(user_id, thread_id)

    @app.post(base + "/threads/{thread_id}/retry")
    async def retry(user_id: str, thread_id: str, request: ThreadCheckpoint):
        return await invoke(user_id, thread_id, request)

    @app.get(base + "/memories")
    async def memories(user_id: str, status: Literal["active", "conflict", "superseded", "retracted", "resolved"] = "active"):
        return {"items": await app.state.memory.long_term.records(user_id, status=status)}

    @app.get(base + "/memories/search")
    async def search(user_id: str, q: str = Query(min_length=1, max_length=2000)):
        return {"items": await app.state.memory.long_term.recall(user_id, q)}

    @app.post(base + "/memories")
    async def submit(user_id: str, request: MemorySubmission):
        async with app.state.memory.recent.lock(user_id, scope="invocation"):
            try:
                context = await app.state.memory.prepare(user_id, request.session_id, request.text,
                                                         request.text, str(request.event_id))
                await app.state.memory.finish(user_id, request.session_id, str(request.event_id), request.text,
                                              "用户记忆已更新；冲突事实需进一步确认。")
            except (MemoryBusyError, RedisError):
                raise
            except Exception:
                logger.exception("用户记忆更新失败")
                raise HTTPException(502, "用户记忆更新失败，可复用 event_id 重试") from None
            return context

    @app.get(base + "/sessions/{session_id}")
    async def recent(user_id: str, session_id: str):
        return await app.state.memory.recent.load(user_id, session_id)

    return app


app = create_memory_app()
