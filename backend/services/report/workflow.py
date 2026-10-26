"""Flask 报告任务与实验 Agent 的边界：模型配置、原生检查点和报告适配。"""

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import re
import sys
import threading
from weakref import WeakValueDictionary

from ..paths import APP_DATA_DIR, PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ReportNeedsInput(Exception):
    pass


_locks = WeakValueDictionary()
_locks_guard = threading.Lock()


def _thread_id(username, report_id):
    if not re.fullmatch(r"report-[a-f0-9]{12}", report_id):
        raise ValueError("报告编号格式不正确")
    return sha256(username.encode("utf-8")).hexdigest() + ":" + report_id


def _lock_for(thread_id):
    with _locks_guard:
        lock = _locks.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _locks[thread_id] = lock
        return lock


@asynccontextmanager
async def _graph(runtime=None, stage_callback=None):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from experiments.news_advisor.report_workflow import build_report_graph

    def model_provider():
        from langchain_openai import ChatOpenAI
        config = runtime or {}
        if not all(config.get(key) for key in ("base_url", "api_key", "model")):
            raise ValueError("请先配置主系统的对话模型")
        from urllib.parse import urlsplit
        options = {}
        if (urlsplit(config["base_url"]).hostname or "").endswith(".deepseek.com") or urlsplit(config["base_url"]).hostname == "deepseek.com":
            options["extra_body"] = {"thinking": {"type": "disabled"}}
        return ChatOpenAI(base_url=config["base_url"], api_key=config["api_key"], model=config["model"],
                          timeout=180, max_retries=1, **options)

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(APP_DATA_DIR / "agent_checkpoints.sqlite3")) as saver:
        yield build_report_graph(model_provider, checkpointer=saver, stage_callback=stage_callback)


def _snapshot(snapshot):
    pending = [item.value for task in snapshot.tasks for item in task.interrupts]
    return {
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id", ""),
        "next": list(snapshot.next), "review": pending[0] if pending else None,
        "results": snapshot.values.get("results", {}),
        "errors": [str(task.error) for task in snapshot.tasks if task.error],
        "complete": bool(snapshot.values) and not snapshot.next,
    }


async def _read(username, report_id):
    async with _graph() as graph:
        return _snapshot(await graph.aget_state({"configurable": {"thread_id": _thread_id(username, report_id)}}))


def read_report_workflow(username, report_id):
    return asyncio.run(_read(username, report_id))


def validate_report_request(payload, raw_resume):
    from experiments.news_advisor.report_workflow import ReportInput
    supplied = dict(payload)
    # 简历原文只从当前账户已保存的简历中读取。
    supplied["raw_resume"] = raw_resume
    return ReportInput.model_validate(supplied).model_dump(mode="json")


def validate_report_continuation(payload, snapshot):
    from experiments.news_advisor.report_workflow import validate_review
    if not snapshot["checkpoint_id"]:
        raise ValueError("没有找到此账户的报告工作流")
    if snapshot["complete"]:
        if payload:
            raise ValueError("此报告已经生成，请重新启动新的报告")
        return None
    if snapshot["review"]:
        return validate_review(payload, snapshot["review"])
    if payload:
        raise ValueError("当前应重试失败步骤，不接受补充回答")
    return None


async def _execute(username, report_id, inputs, runtime, callback):
    from langgraph.types import Command

    config = {"configurable": {"thread_id": _thread_id(username, report_id)}, "recursion_limit": 100}
    async with _graph(runtime, callback) as graph:
        continuation = runtime.get("continuation")
        if continuation is not None:
            current = _snapshot(await graph.aget_state(config))
            if current["checkpoint_id"] != continuation["checkpoint_id"]:
                raise ValueError("工作流已有更新，请刷新后继续")
            response = validate_report_continuation(continuation.get("response", {}), current)
            if current["complete"]:
                return (await graph.aget_state(config)).values
            value = Command(resume=response) if current["review"] else None
        else:
            value = {"input": inputs}
        await graph.ainvoke(value, config, durability="sync")
        state = await graph.aget_state(config)
        if _snapshot(state)["review"]:
            raise ReportNeedsInput("请补充信息并确认目标与时间安排")
        if state.next:
            raise RuntimeError("工作流尚未完成")
        return state.values


def generate_career_report_bundle(*, username, report_id, profile_payload, runtime_llm, stage_callback=None,
                                  role_payload=None, news_payload=None, focus_role_id="", model_name=""):
    lock = _lock_for(_thread_id(username, report_id))
    if not lock.acquire(blocking=False):
        raise ValueError("此报告正在执行，请等待当前任务完成")
    try:
        state = asyncio.run(_execute(username, report_id, profile_payload.get("agent_workflow"), runtime_llm, stage_callback))
        if stage_callback:
            stage_callback("report_writer", "报告合成", "正在将已校验的 Agent 结果整理为报告")
        from .workflow_report import build_report_bundle
        return build_report_bundle(username, report_id, profile_payload, state, model_name)
    finally:
        lock.release()
