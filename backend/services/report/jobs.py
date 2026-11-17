"""职业报告的后台生成任务：登记、取消、进度与重启恢复。"""

import threading
import time
from datetime import datetime

from services.appctx import get_app
from services.job_registry import JobRegistry
from services.portrait import normalize_profile_portrait_context
from services.report import build_stage_progress, CAREER_REPORT_STAGE_DEFS, generate_career_report_bundle
from services.report.context import explicit_report_cities
from services.report.store import CAREER_REPORT_EXPORT_FORMATS
from services.report.writer import _save_career_report_bundle
from services.report.tracker import _sync_career_report_tracker_state
from services.report.workflow import ReportNeedsInput
from services.user_state import (
    _load_user_state,
    _save_user_state,
    _saved_matching_role_payload,
    _saved_profile_snapshot_payload,
)


CAREER_REPORT_LOCK = threading.Lock()


CAREER_REPORT_JOBS = JobRegistry("career_report")


class CareerReportCanceled(RuntimeError):
    """Raised inside a background report job when the user cancels it."""


def _build_career_report_agent_memory(state, profile_payload=None, role_payload=None):
    safe_state = state if isinstance(state, dict) else {}
    profile_scope = safe_state.get("profile_snapshot") if isinstance(safe_state.get("profile_snapshot"), dict) else {}
    matching_scope = safe_state.get("career_matching") if isinstance(safe_state.get("career_matching"), dict) else {}
    resume_scope = safe_state.get("resume_profile") if isinstance(safe_state.get("resume_profile"), dict) else {}
    portrait_scope = safe_state.get("profile_portrait") if isinstance(safe_state.get("profile_portrait"), dict) else {}
    news_scope = safe_state.get("news_context") if isinstance(safe_state.get("news_context"), dict) else {}

    effective_profile = profile_payload if isinstance(profile_payload, dict) and profile_payload else _saved_profile_snapshot_payload(profile_scope)
    effective_roles = role_payload if isinstance(role_payload, list) and role_payload else _saved_matching_role_payload(matching_scope)

    return {
        "profile_snapshot": effective_profile,
        "career_matching": {
            "focus_role_id": str(matching_scope.get("focus_role_id") or "").strip(),
            "role_rankings": effective_roles,
            "updated_at": str(matching_scope.get("updated_at") or "").strip(),
        },
        "resume_memory": {
            "file_name": str(resume_scope.get("file_name") or "").strip(),
            "status": str(resume_scope.get("status") or "").strip(),
            "job_description": str(resume_scope.get("job_description") or "").strip(),
            "resume_source_text": str(resume_scope.get("resume_source_text") or ""),
            "resume_text_char_count": int(resume_scope.get("resume_text_char_count") or 0),
            "structured_resume": resume_scope.get("structured_resume") if isinstance(resume_scope.get("structured_resume"), dict) else {},
            "structured_job": resume_scope.get("structured_job") if isinstance(resume_scope.get("structured_job"), dict) else {},
            "resume_highlight_deck": resume_scope.get("resume_highlight_deck") if isinstance(resume_scope.get("resume_highlight_deck"), dict) else {},
            "analysis_meta": resume_scope.get("analysis_meta") if isinstance(resume_scope.get("analysis_meta"), dict) else {},
        },
        "portrait_memory": {
            "status": str(portrait_scope.get("status") or "").strip(),
            "brief": portrait_scope.get("brief") if isinstance(portrait_scope.get("brief"), dict) else {},
            "context_snapshot": normalize_profile_portrait_context(portrait_scope.get("context_snapshot")),
            "prompt_summary": str(portrait_scope.get("prompt_summary") or "").strip(),
        },
        "news_memory": news_scope,
    }


def _update_career_report_job(job_id, **fields):
    with CAREER_REPORT_LOCK:
        job = CAREER_REPORT_JOBS.get(job_id)
        if not isinstance(job, dict):
            return
        job.update(fields)
        CAREER_REPORT_JOBS[job_id] = job


def _find_running_career_report_job(username):
    with CAREER_REPORT_LOCK:
        for job in CAREER_REPORT_JOBS.values():
            if (
                isinstance(job, dict)
                and str(job.get("username") or "") == str(username or "")
                and str(job.get("status") or "") in {"queued", "running"}
            ):
                return dict(job)
    return None


def _is_career_report_job_cancelled(job_id):
    with CAREER_REPORT_LOCK:
        job = CAREER_REPORT_JOBS.get(job_id)
        if not isinstance(job, dict):
            return False
        return bool(job.get("cancel_requested")) or str(job.get("status") or "") == "canceled"


def _save_career_report_progress(username, job_id, stage, stage_label, detail, **extra):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    with CAREER_REPORT_LOCK:
        live_job = CAREER_REPORT_JOBS.get(job_id)
        live_activity = dict(live_job.get("agent_activity") or {}) if live_job else report_state.get("agent_activity", {})
    report_state.update(
        {
            "status": extra.get("status") or "running",
            "job_id": job_id,
            "stage": stage,
            "stage_label": stage_label,
            "stage_detail": detail,
            "progress": build_stage_progress(stage),
            "agent_activity": dict(extra.get("agent_activity", live_activity)),
            "error_message": str(extra.get("error_message") or ""),
            "generated_at": str(extra.get("generated_at") or report_state.get("generated_at") or ""),
            "report_id": str(extra.get("report_id") or report_state.get("report_id") or ""),
            "model": str(extra.get("model") or report_state.get("model") or ""),
            "generation_mode": str(extra.get("generation_mode") or report_state.get("generation_mode") or ""),
            "focus_role_id": str(extra.get("focus_role_id") or report_state.get("focus_role_id") or ""),
            "title": str(extra.get("title") or report_state.get("title") or ""),
            "summary": str(extra.get("summary") or report_state.get("summary") or ""),
            "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
        }
    )
    state["career_report"] = report_state
    _save_user_state(username, state)


def _career_report_console_log(job_id, message, **fields):
    safe_fields = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        safe_fields.append(f"{key}={value}")
    suffix = f" | {' '.join(safe_fields)}" if safe_fields else ""
    print(f"[career-report][{job_id[:8]}] {datetime.now().strftime('%H:%M:%S')} {message}{suffix}", flush=True)


def _run_career_report_job(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm):
    stage_defs = {item["key"]: item["label"] for item in CAREER_REPORT_STAGE_DEFS}
    runtime_llm_payload = dict(runtime_llm or {}) if isinstance(runtime_llm, dict) else {}
    model_name = str(runtime_llm_payload.get("model") or "").strip()
    job_started = time.perf_counter()
    generation_mode = "langgraph"

    def _log(message, **fields):
        _career_report_console_log(job_id, message, **fields)

    generation_mode = "langgraph"
    model_name = str(runtime_llm_payload.get("model") or model_name)
    _log("后台任务开始", user=username, report_id=report_id, mode=generation_mode, model=model_name)

    def _ensure_not_cancelled():
        if _is_career_report_job_cancelled(job_id):
            raise CareerReportCanceled("职业报告生成已被用户取消。")

    runtime_llm_with_caller = dict(runtime_llm_payload)
    runtime_llm_with_caller["document_cache"] = get_app().extensions["chat_service"].documents
    _ensure_not_cancelled()
    _update_career_report_job(
        job_id,
        status="running",
        started_at=int(time.time()),
        stage="resume_analysis",
        stage_label=stage_defs.get("resume_analysis", "简历分析"),
        stage_detail="正在恢复工作流或分析简历证据",
        progress=build_stage_progress("resume_analysis"),
    )
    _save_career_report_progress(
        username,
        job_id,
        "resume_analysis",
        stage_defs.get("resume_analysis", "简历分析"),
        "正在恢复工作流或分析简历证据",
        model=model_name,
        generation_mode=generation_mode,
        report_id=report_id,
        status="running",
    )

    agent_activity = {}
    activity_lock = threading.Lock()

    def _agent_status_callback(agent, status, detail):
        if _is_career_report_job_cancelled(job_id):
            return
        with activity_lock:
            agent_activity[agent] = {"status": status, "message": str(detail)[:180],
                                     "updated_at": datetime.now().isoformat(timespec="seconds")}
            snapshot = {key: dict(value) for key, value in agent_activity.items()}
        _update_career_report_job(job_id, agent_activity=snapshot)

    def _stage_callback(stage_key, stage_label, detail):
        _ensure_not_cancelled()
        if stage_key in {item["key"] for item in CAREER_REPORT_STAGE_DEFS}:
            _agent_status_callback(stage_key, "active", detail)
        _log("阶段切换", stage=stage_key, label=stage_label, detail=detail)
        _update_career_report_job(
            job_id,
            status="running",
            stage=stage_key,
            stage_label=stage_label,
            stage_detail=detail,
            message=detail,
            progress=build_stage_progress(stage_key),
        )
        _save_career_report_progress(
            username,
            job_id,
            stage_key,
            stage_label,
            detail,
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
            status="running",
            agent_activity={key: dict(value) for key, value in agent_activity.items()},
        )

    try:
        _ensure_not_cancelled()
        bundle = generate_career_report_bundle(
            username=username,
            report_id=report_id,
            profile_payload=profile_payload,
            role_payload=role_payload,
            news_payload=None,
            focus_role_id=focus_role_id,
            stage_callback=_stage_callback,
            agent_status_callback=_agent_status_callback,
            runtime_llm=runtime_llm_with_caller,
            model_name=model_name,
        )
        _ensure_not_cancelled()
        _log("编排返回，开始写入报告文件")
        completed_profile = bundle.get("profile_snapshot") or {}
        city_memory = completed_profile.pop("report_city_memory", [])
        _save_career_report_bundle(username, bundle)
        submitted_preferences = (completed_profile.get("report_user_inputs") or {}).get("preferences", "")
        city = explicit_report_cities(submitted_preferences, (bundle.get("agent_results") or {}).get("recruitment_search") or {})
        if city:
            for previous in city_memory:
                if previous["value"] != city:
                    try:
                        get_app().extensions["chat_service"].memory.correct(
                            username, previous["id"], city, expected_value=previous["value"])
                    except Exception:
                        get_app().logger.exception("report city preference synchronization failed")
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
        final_stage = "report_writer"
        _update_career_report_job(
            job_id,
            status="completed",
            finished_at=int(time.time()),
            stage=final_stage,
            stage_label=stage_defs.get(final_stage, "报告合成"),
            stage_detail="报告生成完成",
            message="报告生成完成",
            report_id=str(meta.get("report_id") or report_id),
            progress=build_stage_progress(final_stage),
        )
        _save_career_report_progress(
            username,
            job_id,
            final_stage,
            stage_defs.get(final_stage, "报告合成"),
            "报告生成完成",
            status="ready",
            model=model_name,
            generation_mode=generation_mode,
            report_id=str(meta.get("report_id") or report_id),
            generated_at=str(meta.get("generated_at") or ""),
            focus_role_id=str(meta.get("focus_role_id") or ""),
            title=str(meta.get("title") or "职业规划报告"),
            summary=str(meta.get("summary") or ""),
        )
        _sync_career_report_tracker_state(username, bundle)
        _log(
            "后台任务完成",
            elapsed=f"{time.perf_counter() - job_started:.1f}s",
            report_id=str(meta.get("report_id") or report_id),
            mode=generation_mode,
        )
    except ReportNeedsInput as exc:
        if _is_career_report_job_cancelled(job_id):
            return
        _update_career_report_job(job_id, status="waiting_input", finished_at=int(time.time()),
                                  stage="review", stage_label="补充与确认", stage_detail=str(exc), message=str(exc))
        _save_career_report_progress(username, job_id, "review", "补充与确认", str(exc),
                                    status="waiting_input", model=model_name, generation_mode=generation_mode,
                                    report_id=report_id)
    except CareerReportCanceled as exc:
        _log("后台任务已取消", elapsed=f"{time.perf_counter() - job_started:.1f}s")
        _update_career_report_job(
            job_id,
            status="canceled",
            finished_at=int(time.time()),
            message=str(exc),
            stage_detail="用户已停止本次生成，旧任务不会写入报告。",
        )
        _save_career_report_progress(
            username,
            job_id,
            "report_writer",
            stage_defs.get("report_writer", "报告合成"),
            "用户已停止本次生成，旧任务不会写入报告。",
            status="canceled",
            error_message="",
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
        )
    except Exception as exc:
        get_app().logger.exception("career report generate failed")
        _log("后台任务失败", elapsed=f"{time.perf_counter() - job_started:.1f}s", error=str(exc)[:220])
        _update_career_report_job(
            job_id,
            status="failed",
            finished_at=int(time.time()),
            message=str(exc),
        )
        _save_career_report_progress(
            username,
            job_id,
            str((CAREER_REPORT_JOBS.get(job_id) or {}).get("stage") or "resume_analysis"),
            str((CAREER_REPORT_JOBS.get(job_id) or {}).get("stage_label") or "工作流执行"),
            "报告生成失败",
            status="failed",
            error_message=str(exc),
            model=model_name,
            generation_mode=generation_mode,
            report_id=report_id,
        )


def _fail_interrupted_report(job):
    username = str(job.get("username") or "")
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    if str(report_state.get("status") or "").lower() not in {"queued", "running"}:
        return
    _save_career_report_progress(
        username, str(job.get("job_id") or ""), str(job.get("stage") or "resume_analysis"),
        str(job.get("stage_label") or "工作流执行"), "报告生成被服务重启中断", status="failed",
        error_message=str(job.get("message") or ""), model=str(job.get("model") or ""),
        generation_mode=str(job.get("generation_mode") or ""), report_id=str(job.get("report_id") or ""))
