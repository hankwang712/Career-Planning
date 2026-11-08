import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import re
import sys
import threading
from weakref import WeakValueDictionary

from ..paths import APP_DATA_DIR, PROJECT_ROOT
from .provenance import capture_provenance, freeze_profile
from .review import REVIEW_POLICY, build_review_ui

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
async def _graph(runtime=None, stage_callback=None, agent_status_callback=None):
    from openai import DefaultAsyncHttpxClient, DefaultHttpxClient
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from backend.advisor.report_workflow import build_report_graph
    from backend.advisor.agents import CareerDecisionAgent, RecruitmentSearchAgent, ResumeAnalysisAgent
    from backend.advisor.agents.job import JobAnalysisAgent
    from .planning import ReportActionPlanningAgent

    def model_provider():
        from langchain_openai import ChatOpenAI
        config = runtime or {}
        if not all(config.get(key) for key in ("base_url", "api_key", "model")):
            raise ValueError("请先配置主系统的对话模型")
        from urllib.parse import urlsplit
        options = {}
        if (urlsplit(config["base_url"]).hostname or "").endswith(".deepseek.com") or urlsplit(config["base_url"]).hostname == "deepseek.com":
            # 与独立报告脚本保持一致；兼容接口需要原始 max_tokens 字段，
            # 顶层参数会被 ChatOpenAI 改写为 max_completion_tokens。
            options["extra_body"] = {"thinking": {"type": "disabled"}, "max_tokens": 16384}
        return ChatOpenAI(base_url=config["base_url"], api_key=config["api_key"], model=config["model"],
                          temperature=0, timeout=180, max_retries=1, http_client=sync_client,
                          # Own clients preserve the SDK's default system/environment proxy handling.
                          http_async_client=async_client, http_socket_options=(), **options)

    classes = {"resume_analysis": ResumeAnalysisAgent, "job_analysis": JobAnalysisAgent,
               "recruitment_search": RecruitmentSearchAgent, "career_decision": CareerDecisionAgent}

    def agent_factory(name):
        if name == "action_planning":
            return ReportActionPlanningAgent(model_provider(), stage_callback=stage_callback,
                                             resume_planning=bool(runtime and runtime.get("continuation") is not None))
        agent = classes[name](model_provider())
        if name == "career_decision":
            agent.system_prompt += "\n" + REVIEW_POLICY
        return agent

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Flask 每次恢复都有独立的 asyncio.run；连接不得从已关闭的 loop 缓存中复用。
    with DefaultHttpxClient() as sync_client:
        async with DefaultAsyncHttpxClient() as async_client:
            async with AsyncSqliteSaver.from_conn_string(str(APP_DATA_DIR / "agent_checkpoints.sqlite3")) as saver:
                yield build_report_graph(model_provider, checkpointer=saver, stage_callback=stage_callback,
                                         agent_factory=agent_factory, agent_status_callback=agent_status_callback)


def _snapshot(snapshot):
    from backend.advisor.report_collaboration import collaboration_summary

    pending = [item.value for task in snapshot.tasks for item in task.interrupts]
    return {
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id", ""),
        "next": list(snapshot.next), "review": pending[0] if pending else None,
        "results": snapshot.values.get("results", {}),
        "errors": [str(task.error) for task in snapshot.tasks if task.error],
        "complete": bool(snapshot.values) and not snapshot.next,
        "provenance": snapshot.values.get("provenance", {}),
        "collaboration": collaboration_summary(snapshot.values),
        "review_ui": build_review_ui(pending[0] if pending else None, snapshot.values.get("input"),
                                    snapshot.values.get("profile_snapshot")),
    }


async def _read(username, report_id):
    async with _graph() as graph:
        return _snapshot(await graph.aget_state({"configurable": {"thread_id": _thread_id(username, report_id)}}))


def read_report_workflow(username, report_id):
    return asyncio.run(_read(username, report_id))


def validate_report_request(payload, raw_resume="", *, file_path=""):
    from backend.advisor.report_workflow import ReportInput
    supplied = dict(payload)
    # Only the server selects the account's uploaded file; the browser cannot supply paths or resume text.
    supplied["raw_resume"] = "" if file_path else raw_resume
    schema = ReportInput
    if file_path:
        from pydantic import create_model
        schema = create_model("UploadedReportInput", __base__=ReportInput, raw_resume=(str, ""))
    validated = schema.model_validate(supplied).model_dump(mode="json")
    if file_path:
        validated["file_path"] = str(file_path)
    return validated


def validate_report_continuation(payload, snapshot):
    from backend.advisor.report_workflow import validate_review
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


async def _execute(username, report_id, inputs, runtime, callback, profile=None, agent_status_callback=None):
    from langgraph.types import Command

    document_metadata = None
    if runtime.get("continuation") is None and inputs.get("file_path"):
        from backend.advisor.tools.document import read_document
        if callback:
            callback("resume_analysis", "简历分析", "正在使用文档工具读取上传的简历")
        if agent_status_callback:
            agent_status_callback("resume_analysis", "active", "正在读取上传的简历文档")
        supplied = dict(inputs)
        file_path = supplied.pop("file_path")
        if runtime.get("document_cache") is not None:
            document = await asyncio.to_thread(runtime["document_cache"].read, username, {"path": file_path})
        else:
            document = await read_document.ainvoke({"file_path": file_path, "max_pages": 20})
        markdown = str(document.get("markdown") or "").strip()
        if document.get("status") not in {"ok", "partial"} or not markdown:
            raise ValueError(document.get("error") or "简历文档读取失败，请检查上传文件后重试")
        inputs = validate_report_request(supplied, markdown)
        document_metadata = {key: document[key] for key in ("status", "warnings", "processed_pages", "total_pages") if key in document}

    config = {"configurable": {"thread_id": _thread_id(username, report_id)}, "recursion_limit": 100}
    activity_options = {"agent_status_callback": agent_status_callback} if agent_status_callback else {}
    async with _graph(runtime, callback, **activity_options) as graph:
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
            frozen = freeze_profile(profile)
            value = {"input": inputs, "profile_snapshot": frozen,
                     "provenance": capture_provenance(inputs, frozen, runtime.get("model", ""))}
            value["provenance"]["review_policy_revision"] = sha256(REVIEW_POLICY.encode("utf-8")).hexdigest()
            value["provenance"]["action_planning_output_mode"] = "validated_json_v1"
            if document_metadata is not None:
                value["provenance"]["resume_document"] = document_metadata
        await graph.ainvoke(value, config, durability="sync")
        state = await graph.aget_state(config)
        if _snapshot(state)["review"]:
            raise ReportNeedsInput("请补充信息并确认目标与时间安排")
        if state.next:
            raise RuntimeError("工作流尚未完成")
        return state.values


def generate_career_report_bundle(*, username, report_id, profile_payload, runtime_llm, stage_callback=None,
                                  role_payload=None, news_payload=None, focus_role_id="", model_name="", agent_status_callback=None):
    lock = _lock_for(_thread_id(username, report_id))
    if not lock.acquire(blocking=False):
        raise ValueError("此报告正在执行，请等待当前任务完成")
    try:
        state = asyncio.run(_execute(username, report_id, profile_payload.get("agent_workflow"), runtime_llm,
                                     stage_callback, profile_payload, agent_status_callback))
        if stage_callback:
            stage_callback("report_writer", "报告合成", "正在将已校验的 Agent 结果整理为报告")
        from .workflow_report import build_report_bundle
        return build_report_bundle(username, report_id, state.get("profile_snapshot", {}), state, model_name)
    finally:
        lock.release()
