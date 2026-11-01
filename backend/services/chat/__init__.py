"""Flask-rendered assistant page; chat APIs are served by FastAPI."""

from pathlib import Path

from flask import Blueprint, redirect, render_template

from .service import ChatService


def create_blueprint(*, directory, current_user, runtime_provider, profile_provider, resume_provider=None):
    bp = Blueprint("assistant", __name__)
    bp.chat_service = ChatService(Path(directory), runtime_provider, profile_provider, resume_provider=resume_provider)

    @bp.after_request
    def private_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.vary.add("Cookie")
        return response

    @bp.get("/assistant")
    @bp.get("/assistant.html")
    def page():
        if not current_user():
            return redirect("/main.html")
        return render_template("assistant.html")

    return bp
