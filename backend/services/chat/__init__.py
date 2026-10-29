"""Authenticated assistant pages and API routes for the main application."""

import hmac
import json
from pathlib import Path
from uuid import UUID

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, stream_with_context

from .service import ChatService
from .storage import ChatError


def create_blueprint(*, directory, current_user, login_required, runtime_provider, profile_provider, resume_provider=None):
    service = ChatService(Path(directory), runtime_provider, profile_provider, resume_provider=resume_provider)
    bp = Blueprint("assistant", __name__)
    bp.chat_service = service

    @bp.errorhandler(ChatError)
    def chat_error(error):
        return jsonify(message=str(error)), error.status

    @bp.before_request
    def protect_mutations():
        if not request.path.startswith("/api/chat/"):
            return
        if not current_user():
            raise ChatError("请先登录。", 401)
        if request.method in {"POST", "PATCH", "DELETE"}:
            if request.content_length and request.content_length > 65536:
                raise ChatError("提交内容过大。", 413)
            expected, supplied = session.get("csrf_token"), request.headers.get("X-CSRF-Token", "")
            if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), supplied.encode()):
                raise ChatError("安全校验已过期，请刷新页面后重试。", 403)

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.vary.add("Cookie")
        return response

    def owner():
        return current_user()["username"]

    def payload():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ChatError("请提交有效的 JSON 对象。")
        return value

    def text(value, maximum):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
            raise ChatError(f"请输入 1～{maximum} 字的内容。")
        return value.strip()

    @bp.get("/assistant")
    @bp.get("/assistant.html")
    def page():
        if not current_user():
            return redirect("/main.html")
        return render_template("assistant.html")

    @bp.get("/api/chat/sessions")
    @login_required
    def list_sessions():
        service.start_worker()
        runtime = runtime_provider(session.get("llm_selection") or {})
        return jsonify(items=service.store.list_sessions(owner()), model=runtime[2] or "尚未配置模型", configured=all(runtime),
                       display_name=current_user().get("display_name", ""))

    @bp.post("/api/chat/sessions")
    @login_required
    def create_session():
        title = text(payload().get("title", "新对话"), 80)
        row = service.store.create_session(owner(), title)
        return jsonify(id=row["id"], title=row["title"]), 201

    @bp.patch("/api/chat/sessions/<session_id>")
    @login_required
    def rename_session(session_id):
        service.store.rename(owner(), session_id, text(payload().get("title"), 80))
        return jsonify(ok=True)

    @bp.delete("/api/chat/sessions/<session_id>")
    @login_required
    def delete_session(session_id):
        service.store.delete_session(owner(), session_id)
        service.cache.delete(owner(), session_id)
        return jsonify(ok=True)

    @bp.get("/api/chat/sessions/<session_id>/messages")
    @login_required
    def list_messages(session_id):
        before = request.args.get("before", type=int)
        result = service.store.messages(owner(), session_id, before=before)
        row = service.store.session(owner(), session_id)
        import time
        return jsonify(**result, title=row["title"], generating=row["sending_until"] > time.time())

    @bp.post("/api/chat/sessions/<session_id>/messages")
    @login_required
    def send_message(session_id):
        data = payload()
        content = text(data.get("content"), 12000)
        try:
            request_id = str(UUID(data.get("request_id", "")))
        except (ValueError, TypeError, AttributeError):
            raise ChatError("消息编号必须是 UUID。") from None
        selection = {key: value for key, value in (session.get("llm_selection") or {}).items() if key in {"provider_id", "model"} and isinstance(value, str)}
        runtime = service.runtime(selection)
        username = owner()
        turn = service.store.begin_turn(username, session_id, request_id, content, selection)

        def events():
            if "replay" in turn:
                yield {"type": "delta", "text": turn["replay"]["content"]}
                yield {"type": "done", "session_id": session_id, "request_id": request_id}
            else:
                yield from service.stream(username, session_id, request_id, turn["token"], content, runtime)

        def encoded():
            for event in events():
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        return Response(stream_with_context(encoded()), mimetype="text/event-stream",
                        headers={"X-Accel-Buffering": "no"})

    @bp.post("/api/chat/sessions/<session_id>/finish")
    @login_required
    def finish(session_id):
        service.store.enqueue(owner(), session_id, immediate=True)
        service.start_worker()
        return jsonify(ok=True, message="已安排整理本次对话中的有效信息。")

    @bp.get("/api/chat/memories")
    @login_required
    def memories():
        return jsonify(service.memory_overview(owner(), request.args.get("session_id")))

    @bp.post("/api/chat/sources/resume/sync")
    @login_required
    def sync_resume():
        try:
            service.documents.start(owner(), service.resume_provider(owner()))
        except ValueError as error:
            raise ChatError(str(error), 400) from None
        return jsonify(ok=True, message="已安排读取当前简历，可在资料来源中查看进度。"), 202

    @bp.delete("/api/chat/memories/<memory_id>")
    @login_required
    def forget(memory_id):
        service.store.forget(owner(), memory_id)
        service.start_worker()
        return jsonify(ok=True)

    return bp
