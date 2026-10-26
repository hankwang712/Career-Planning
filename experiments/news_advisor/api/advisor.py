import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from weakref import WeakValueDictionary

from fastapi import APIRouter, HTTPException
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from ..graph import AgentExecutionError, build_advisor_graph, followup_questions
from ..schemas.workflow import AgentRequest, ThreadCheckpoint
from .base_api import ensure_agent_result


def create_advisor_router(model_provider, *, checkpoint_path: str | Path | None = None) -> APIRouter:
    database = Path(checkpoint_path) if checkpoint_path is not None else (
        Path(__file__).resolve().parents[2] / "output" / "news_advisor" / "checkpoints.sqlite3"
    )
    graph = None
    locks = WeakValueDictionary()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal graph
        database.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(database)) as checkpointer:
            graph = build_advisor_graph(model_provider, checkpointer=checkpointer)
            try:
                yield
            finally:
                graph = None

    router = APIRouter(prefix="/api/advisor", tags=["职业助手"], lifespan=lifespan)

    def current_graph():
        if graph is None:
            raise HTTPException(status_code=503, detail="LangGraph 尚未启动")
        return graph

    def config(thread_id):
        return {"configurable": {"thread_id": thread_id}}

    async def snapshot(thread_id):
        state = await current_graph().aget_state(config(thread_id))
        if not state.values:
            raise HTTPException(status_code=404, detail="线程不存在")
        return {
            "thread_id": thread_id, "checkpoint_id": state.config["configurable"].get("checkpoint_id"),
            "values": state.values, "next": list(state.next),
            "errors": [{"node": task.name, "error": task.error} for task in state.tasks if task.error],
            "followup_questions": {name: followup_questions(result) for name, result in state.values.get("results", {}).items()},
        }

    async def invoke(thread_id: str, request: AgentRequest | ThreadCheckpoint):
        lock = locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[thread_id] = lock
        if lock.locked():
            raise HTTPException(status_code=409, detail="该线程正在执行，请稍后读取最新状态")
        async with lock:
            compiled = current_graph()
            state = await compiled.aget_state(config(thread_id))
            checkpoint_id = state.config["configurable"].get("checkpoint_id")
            if request.checkpoint_id is not None and request.checkpoint_id != checkpoint_id:
                raise HTTPException(status_code=409, detail="检查点已更新，请读取最新状态后提交")
            if isinstance(request, AgentRequest):
                inputs = {"request": request.model_dump(mode="json")}
            else:
                if not state.next:
                    raise HTTPException(status_code=422, detail="没有待恢复的执行节点")
                inputs = None
            try:
                await compiled.ainvoke(inputs, config(thread_id), durability="sync")
            except ValidationError as error:
                raise HTTPException(status_code=422, detail=error.errors(include_context=False, include_input=False)) from None
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
            except AgentExecutionError as error:
                try:
                    ensure_agent_result(error.result)
                except HTTPException as failure:
                    saved = await snapshot(thread_id)
                    failure.detail = {"thread_id": thread_id, "checkpoint_id": saved["checkpoint_id"], "error": failure.detail}
                    raise failure from None
            return await snapshot(thread_id)

    @router.post("/threads/{thread_id}")
    async def run(thread_id: str, request: AgentRequest):
        return await invoke(thread_id, request)

    @router.get("/threads/{thread_id}")
    async def get(thread_id: str):
        return await snapshot(thread_id)

    @router.post("/threads/{thread_id}/retry")
    async def retry(thread_id: str, request: ThreadCheckpoint):
        return await invoke(thread_id, request)

    return router
