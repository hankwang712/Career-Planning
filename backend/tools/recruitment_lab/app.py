"""Local UI for the shared Recruitment Radar agent and collection dashboard."""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import Field
from starlette.background import BackgroundTask

from backend.advisor.config import ENV_FILE, get_ai_config
from backend.advisor.schemas.recruitment_search import RecruitmentSearchInput

DIRECTORY = Path(__file__).resolve().parent
RADAR_TOOLS = {"search_recruitment_radar", "verify_recruitment_radar_candidates"}


class LabRequest(RecruitmentSearchInput):
    channel: Literal["radar"] = "radar"
    max_model_calls: int = Field(default=5, ge=1, le=10)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    timeout: int = Field(default=180, ge=10, le=300)

    def agent_input(self):
        return self.model_dump(mode="json", exclude={"max_model_calls", "max_tool_calls", "timeout"})


def decode_output(value):
    value = getattr(value, "content", value)
    if isinstance(value, str):
        with suppress(ValueError):
            return json.loads(value)
    return value if isinstance(value, dict) else {}


class Trace(AsyncCallbackHandler):
    """Show public tool activity and validation feedback; never stream private reasoning."""
    def __init__(self, publish):
        self.publish = publish
        self.calls = {}
        self.rounds = 0
        self.feedback = set()

    async def on_chat_model_start(self, serialized, messages, **kwargs):
        self.rounds += 1
        phase = (kwargs.get("metadata") or {}).get("recruitment_phase")
        repairing = False
        for group in messages:
            for message in group[-6:]:
                if getattr(message, "type", "") != "tool":
                    continue
                detail = str(getattr(message, "content", ""))
                if getattr(message, "status", "") == "error" or detail.lower().startswith("error:"):
                    if detail not in self.feedback:
                        self.feedback.add(detail)
                        repairing = True
                        self.publish({"type": "validation", "message": detail[:1800]})
        self.publish({"type": "model_start", "round": self.rounds,
            "message": {"planning": "理解用户需求并生成同义岗位查询计划", "reviewing": "批量核对所有候选的招聘内容、岗位方向和招聘类别"}.get(phase) or ("修正未通过校验的招聘结果" if repairing else
                "理解招聘需求，确定岗位和搜索条件" if self.rounds == 1 else "核对招聘证据与用户条件，整理结果或补查明确缺口")})

    async def on_custom_event(self, name, data, *, run_id, **kwargs):
        if name == "recruitment_progress" and isinstance(data, dict):
            self.publish({"type": "progress", **data})

    async def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        name = (serialized or {}).get("name", "")
        if name not in RADAR_TOOLS:
            return
        arguments = kwargs.get("inputs") or decode_output(input_str)
        if str(parent_run_id) in self.calls:
            # The wrapped tool invokes its raw tool with normalized arguments. Update the same row.
            self.publish({"type": "tool_arguments", "id": str(parent_run_id), "arguments": arguments})
            return
        self.calls[str(run_id)] = {"tool": name, "started": perf_counter()}
        self.publish({"type": "tool_start", "id": str(run_id), "tool": name, "arguments": arguments})

    async def on_tool_end(self, output, *, run_id, **kwargs):
        call = self.calls.pop(str(run_id), None)
        result = decode_output(output)
        if call:
            self.publish({"type": "tool_end", "id": str(run_id), "tool": call["tool"],
                "status": result.get("status", "unknown"), "error": result.get("error"),
                "source_count": len(result.get("sources", result.get("jobs", []))),
                "excluded_count": len(result.get("excluded_items", [])), "reused": result.get("reused", False),
                "elapsed_seconds": round(perf_counter() - call["started"], 2)})
        elif getattr(output, "status", None) == "error":
            # Structured-output errors are useful feedback, rather than a second search operation.
            self.publish({"type": "validation", "message": str(getattr(output, "content", ""))[:1800]})

    async def on_tool_error(self, error, *, run_id, **kwargs):
        call = self.calls.pop(str(run_id), None)
        if call:
            self.publish({"type": "tool_end", "id": str(run_id), "tool": call["tool"],
                          "status": "error", "error": type(error).__name__})


async def run_agent(request: LabRequest, publish):
    from langchain_openai import ChatOpenAI
    from openai import DefaultAsyncHttpxClient, DefaultHttpxClient
    from backend.advisor.agents.recruitment_search import RecruitmentSearchAgent

    settings = get_ai_config("chat")
    options = {"max_tokens": 8192}
    hostname = urlsplit(settings.base_url).hostname or ""
    if hostname == "deepseek.com" or hostname.endswith(".deepseek.com"):
        options = {"extra_body": {"thinking": {"type": "disabled"}, "max_tokens": 8192}}
    with DefaultHttpxClient() as sync_client:
        async with DefaultAsyncHttpxClient() as async_client:
            model = ChatOpenAI(api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
                temperature=0, timeout=request.timeout, max_retries=0, http_client=sync_client,
                http_async_client=async_client, http_socket_options=(), **options)
            agent = RecruitmentSearchAgent(model, max_model_calls=request.max_model_calls,
                                           max_tool_calls=request.max_tool_calls)
            return await agent.arun(request.agent_input(), config={"callbacks": [Trace(publish)]})


async def dependency_status():
    try:
        settings = get_ai_config("chat")
        model = {"ready": True, "name": settings.model, "message": "已读取模型配置"}
    except ValueError as error:
        model = {"ready": False, "name": "未配置", "message": str(error)}
    proxy = os.getenv("RADAR_BROWSER_PROXY_URL", os.getenv("WECHAT_BROWSER_PROXY_URL", "http://localhost:3456")).rstrip("/")
    browser = {"ready": False, "message": "浏览器未连接；请运行 README 中的连接命令，并在 Chrome 中允许连接。"}
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(proxy + "/targets")
            response.raise_for_status()
            data = response.json()
        if isinstance(data, list) or isinstance(data, dict) and isinstance(data.get("targets"), list):
            browser = {"ready": True, "message": "浏览器连接可用"}
    except (httpx.HTTPError, ValueError):
        pass
    from backend.advisor.radar.client import capabilities
    return {"model": model, "browser": browser, "radar": capabilities()}


def create_app(*, runner=run_agent, status_reader=dependency_status):
    app = FastAPI(title="招聘雷达 Agent 测试台", docs_url=None, redoc_url=None)
    slot = asyncio.Lock()
    from backend.advisor.radar.api import router as radar_router
    app.include_router(radar_router)

    @app.get("/")
    async def index():
        return FileResponse(DIRECTORY / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/app.js")
    async def javascript():
        return FileResponse(DIRECTORY / "app.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    async def status():
        return {**await status_reader(), "running": slot.locked()}

    @app.post("/api/run")
    async def run(request: LabRequest):
        if slot.locked():
            raise HTTPException(409, "已有测试正在执行，请等待完成或停止当前测试。")
        if len(request.clarifications) > 20:
            raise HTTPException(422, "补充回答最多保留 20 项，请开始新的测试。")
        dependencies = await status_reader()
        for name in ("model",):
            if not dependencies[name]["ready"]:
                raise HTTPException(503, dependencies[name]["message"])
        # Status checks can yield; another request may have taken the slot meanwhile.
        if slot.locked():
            raise HTTPException(409, "已有测试正在执行，请等待完成或停止当前测试。")
        await slot.acquire()
        released = False

        async def release_slot():
            nonlocal released
            if not released:
                released = True
                slot.release()

        async def stream():
            queue = asyncio.Queue()
            started = perf_counter()
            loop = asyncio.get_running_loop()

            def publish(event):
                event = {**event, "elapsed_seconds": event.get("elapsed_seconds", round(perf_counter() - started, 2))}
                loop.call_soon_threadsafe(queue.put_nowait, event)

            async def execute():
                try:
                    result = await asyncio.wait_for(runner(request, publish), timeout=900)
                    publish({"type": "result", "result": result, "input": request.agent_input(),
                        "settings": {"model": dependencies["model"]["name"], "max_model_calls": request.max_model_calls,
                                     "max_tool_calls": request.max_tool_calls, "timeout": request.timeout}})
                except asyncio.TimeoutError:
                    publish({"type": "error", "message": "本轮超过 15 分钟，已取消。请缩小搜索范围或减少调用次数。"})
                except Exception as error:
                    publish({"type": "error", "message": f"执行失败（{type(error).__name__}），请检查模型配置与浏览器连接。"})

            task = asyncio.create_task(execute())
            try:
                yield json.dumps({"type": "start", "message": "已启动招聘雷达 Agent"}, ensure_ascii=False) + "\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=10)
                    except asyncio.TimeoutError:
                        event = {"type": "heartbeat", "elapsed_seconds": round(perf_counter() - started, 1)}
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    if event["type"] in {"result", "error"}:
                        break
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                await release_slot()

        return StreamingResponse(stream(), media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}, background=BackgroundTask(release_slot))

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="启动招聘雷达 Agent 与数据工作台")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
    print(f"招聘雷达 Agent 测试台：http://127.0.0.1:{args.port}；数据工作台：/radar", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
