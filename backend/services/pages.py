"""登录后才能访问的独立页面（用户中心、报告优化、测评结果等）。"""
from flask import Blueprint, redirect, render_template, send_from_directory, url_for

from .paths import STATIC_DIR


def create_blueprint(current_user):
    blueprint = Blueprint("pages", __name__)

    @blueprint.route("/healthz")
    def healthz():
        """存活探针：不访问数据库也不要求登录，供容器和反向代理使用。"""
        return {"status": "ok"}

    @blueprint.route("/multi-agent-workflow")
    @blueprint.route("/multi-agent-workflow.html")
    def multi_agent_workflow_page():
        if not current_user():
            return redirect(url_for("index"))
        return send_from_directory(
            STATIC_DIR,
            "multi-agent-workflow.html",
            mimetype="text/html"
        )

    @blueprint.route("/user-center")
    @blueprint.route("/user-center.html")
    def user_center_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("user_center.html")

    @blueprint.route("/user-center/career-report/polish")
    @blueprint.route("/user-center/career-report/polish.html")
    def career_report_polish_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("career_report_polish.html")

    @blueprint.route("/resume-report")
    @blueprint.route("/resume-report.html")
    def resume_report_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("resume_report.html")

    @blueprint.route("/test-result")
    @blueprint.route("/test-result.html")
    def test_result_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("test_result.html")

    @blueprint.route("/test-runner")
    @blueprint.route("/test-runner.html")
    def test_runner_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("test_runner.html")

    @blueprint.route("/sbti")
    @blueprint.route("/sbti.html")
    def sbti_page():
        if not current_user():
            return redirect(url_for("index"))
        return render_template("sbti.html")

    return blueprint
