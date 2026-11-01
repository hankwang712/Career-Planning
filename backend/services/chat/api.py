"""FastAPI chat routes, sharing the main site's signed cookie and auth checks."""

from dataclasses import dataclass
from contextlib import asynccontextmanager
import hmac
import json
import time
from typing import Annotated, Literal
from uuid import UUID

import anyio
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from flask import session
from pydantic import BaseModel, Field, StringConstraints
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.wsgi import WSGIMiddleware

from .storage import ChatError
from .privacy import SCOPE as CLEANUP_SCOPE


Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=80)]
Content = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=12000)]


class NewSession(BaseModel):
    title: Title = "新对话"


class RenameSession(BaseModel):
    title: Title


class NewMessage(BaseModel):
    content: Content
    request_id: UUID = Field(description="同一条消息重试时复用此 UUID，避免重复生成。")


class MemoryCorrection(BaseModel):
    value: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]


class SourceSettings(BaseModel):
    workspace_enabled: bool
    resume_enabled: bool


@dataclass
class Identity:
    owner: str
    display_name: str
    selection: dict


class ChatTransport:
    """Limit even chunked bodies and preserve private/CORS headers on chat errors."""

    def __init__(self, app, allowed_origins):
        self.app = app
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins if origin}

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/api/chat" or path.startswith("/api/chat/")):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        same_origin = f"{scope['scheme']}://{headers.get('host', '')}"

        async def private_send(message):
            if message["type"] == "http.response.start":
                outgoing = MutableHeaders(scope=message)
                outgoing["Cache-Control"] = "no-store"
                outgoing["X-Content-Type-Options"] = "nosniff"
                outgoing.add_vary_header("Cookie")
                outgoing.add_vary_header("Origin")
                if origin and origin in self.allowed_origins | {same_origin}:
                    outgoing["Access-Control-Allow-Origin"] = origin
                    outgoing["Access-Control-Allow-Credentials"] = "true"
                    outgoing["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
                    outgoing["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
            await send(message)

        if scope["method"] == "OPTIONS":
            return await Response(status_code=204)(scope, receive, private_send)

        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 65536:
                    return await JSONResponse({"message": "提交内容过大。"}, status_code=413)(scope, receive, private_send)
                if not message.get("more_body", False):
                    break
            delivered = False

            async def replay_body():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay_body, private_send)
        await self.app(scope, receive, private_send)


class ChatStreamingResponse(StreamingResponse):
    """Close the sync model iterator and release its lease on ASGI disconnects."""

    def __init__(self, iterator, cleanup):
        self.iterator = iterator
        self.cleanup = cleanup
        super().__init__(iterator, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await run_in_threadpool(self.iterator.close)
                finally:
                    await run_in_threadpool(self.cleanup)


def create_app(flask_app, *, service, current_user):
    """Serve chat natively in ASGI and delegate existing pages/APIs to Flask."""
    @asynccontextmanager
    async def lifespan(app):
        service.memory.start()
        try:
            yield
        finally:
            await run_in_threadpool(service.memory.close)

    api = FastAPI(title="智航生涯聊天 API",
                  description="先在主站登录。写操作的 X-CSRF-Token 使用 /api/auth/security 返回的 csrf_token；会话归属由登录用户决定。",
                  docs_url="/api/chat/docs", redoc_url=None,
                  openapi_url="/api/chat/openapi.json", lifespan=lifespan)
    api.state.chat_service = service
    api.add_middleware(ChatTransport, allowed_origins=[
        flask_app.config.get("FRONTEND_ORIGIN", ""), flask_app.config.get("VITE_DEV_SERVER_URL", "")])

    @api.exception_handler(ChatError)
    async def chat_error(request, error):
        return JSONResponse({"message": str(error)}, status_code=error.status)

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"message": "提交字段格式不正确，请检查内容长度、消息 UUID 和分页参数。"}, status_code=400)

    def authenticate(request: Request, csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None):
        # Only this short bridge needs Flask context; model calls and streams do not.
        # Use Flask's session interface and current_user() so revoked/disabled logins
        # are checked against auth_sessions, rather than trusting a username cookie.
        with flask_app.test_request_context(str(request.url), method=request.method,
                                           headers={"Cookie": request.headers.get("cookie", "")}):
            user = current_user()
            if not user:
                raise ChatError("请先登录。", 401)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                expected, supplied = session.get("csrf_token"), csrf_token or ""
                if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
                    raise ChatError("安全校验已过期，请刷新页面后重试。", 403)
            selected = session.get("llm_selection")
            selection = {key: value for key, value in (selected if isinstance(selected, dict) else {}).items()
                         if key in {"provider_id", "model"} and isinstance(value, str)}
            return Identity(user["username"], user.get("display_name", ""), selection)

    User = Annotated[Identity, Depends(authenticate)]

    @api.get("/api/chat/sessions")
    def list_sessions(user: User):
        runtime = service.runtime_provider(user.selection)
        return {"items": service.store.list_sessions(user.owner), "model": runtime[2] or "尚未配置模型",
                "configured": all(runtime), "display_name": user.display_name}

    @api.post("/api/chat/sessions", status_code=201)
    def create_session(data: NewSession, user: User):
        row = service.store.create_session(user.owner, data.title)
        return {"id": row["id"], "title": row["title"]}

    @api.patch("/api/chat/sessions/{session_id}")
    def rename_session(session_id: str, data: RenameSession, user: User):
        service.store.rename(user.owner, session_id, data.title)
        return {"ok": True}

    def receipt(owner, task_id):
        return {"status": "accepted", "task": service.store.cleanup_status(owner, task_id), "scope": CLEANUP_SCOPE,
                "status_url": "/api/chat/cleanup-tasks/" + task_id}

    @api.delete("/api/chat/sessions/{session_id}", status_code=202)
    def delete_session(session_id: str, user: User):
        return receipt(user.owner, service.memory.delete_session(user.owner, session_id))

    @api.get("/api/chat/sessions/{session_id}/messages")
    def list_messages(session_id: str, user: User, before: int | None = None):
        result = service.store.messages(user.owner, session_id, before=before)
        row = service.store.session(user.owner, session_id)
        return {**result, "title": row["title"], "generating": row["sending_until"] > time.time()}

    @api.post("/api/chat/sessions/{session_id}/messages", response_class=StreamingResponse,
              responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}})
    def send_message(session_id: str, data: NewMessage, user: User):
        request_id = str(data.request_id)
        runtime = service.runtime(user.selection)
        turn = service.store.begin_turn(user.owner, session_id, request_id, data.content, user.selection)

        def encoded():
            if "replay" in turn:
                if service.store.privacy(user.owner)["epoch"] != turn["privacy_epoch"]:
                    yield "data: " + json.dumps({"type": "error", "message": "记忆已变更，请重新发送。"}, ensure_ascii=False) + "\n\n"
                    return
                events = iter([{"type": "delta", "text": turn["replay"]["content"]},
                               {"type": "done", "session_id": session_id, "request_id": request_id}])
            else:
                events = service.stream(user.owner, session_id, request_id, turn["token"], data.content, runtime)
            try:
                for event in events:
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            finally:
                if "replay" not in turn:
                    events.close()

        def cleanup():
            if "replay" not in turn:
                # Also handles a disconnect before the iterator was first advanced.
                service.store.fail_turn(user.owner, session_id, request_id, turn["token"])

        return ChatStreamingResponse(encoded(), cleanup)

    @api.post("/api/chat/sessions/{session_id}/finish")
    def finish(session_id: str, user: User):
        service.memory.queue(user.owner, session_id, immediate=True)
        return {"ok": True, "message": "已安排整理本次对话中的有效信息。"}

    @api.get("/api/chat/memories")
    def memories(user: User, session_id: str | None = None):
        return service.memory_overview(user.owner, session_id)

    @api.get("/api/chat/profile")
    def profile(user: User):
        overview = service.memory_overview(user.owner)
        return {**overview["profile"], "resume_status": overview["resume"]["status"]}

    @api.get("/api/chat/memories/events")
    def memory_events(user: User):
        return {"items": service.store.memory_events(user.owner)}

    @api.post("/api/chat/sources/resume/sync", status_code=202)
    def sync_resume(user: User):
        if not service.store.privacy(user.owner)["resume_enabled"]:
            raise ChatError("请先启用聊天中的简历资料来源。", 409)
        try:
            service.documents.start(user.owner, service.resume_provider(user.owner))
        except ValueError as error:
            raise ChatError(str(error), 400) from None
        return {"ok": True, "message": "已安排读取当前简历，可在资料来源中查看进度。"}

    @api.patch("/api/chat/memories/{memory_id}", status_code=202)
    def correct(memory_id: str, data: MemoryCorrection, user: User):
        return receipt(user.owner, service.memory.correct(user.owner, memory_id, data.value))

    @api.delete("/api/chat/memories/{memory_id}", status_code=202)
    def forget(memory_id: str, user: User, mode: Literal["forget", "purge"] = "forget"):
        return receipt(user.owner, service.memory.forget(user.owner, memory_id, mode=mode))

    @api.delete("/api/chat/chat-data", status_code=202)
    def clear_chat_data(user: User):
        return receipt(user.owner, service.memory.delete_owner(user.owner))

    @api.get("/api/chat/cleanup-tasks/{task_id}")
    def cleanup_task(task_id: str, user: User):
        return {"task": service.store.cleanup_status(user.owner, task_id), "scope": CLEANUP_SCOPE}

    @api.patch("/api/chat/source-settings", status_code=202)
    def source_settings(data: SourceSettings, user: User):
        task = service.store.source_settings(user.owner, **data.model_dump())
        service.memory.start()
        return receipt(user.owner, task)

    api.mount("/", WSGIMiddleware(flask_app))
    return api
