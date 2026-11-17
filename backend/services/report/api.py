"""职业报告相关接口。"""

import io
import json
import os
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file, url_for

from services import llm_env, personality
from services.appctx import get_app
from services.llm_calls import call_markdown_chat
from services.report import build_stage_progress, CAREER_REPORT_STAGE_DEFS, empty_report_state
from services.report.context import apply_report_memory
from services.report.enhancements import PORTRAIT_PROMPT_PIPELINE_VERSION
from services.report.exporters import (
    export_markdown_to_docx_bytes,
    export_markdown_to_pdf_bytes,
    normalize_br_tags_in_markdown,
    render_markdown_export_html,
    render_report_html,
    render_report_markdown,
)
from services.report.writer import _delete_career_report_version
from services.report.jobs import (
    _build_career_report_agent_memory,
    _career_report_console_log,
    _find_running_career_report_job,
    _run_career_report_job,
    _save_career_report_progress,
    CAREER_REPORT_JOBS,
    CAREER_REPORT_LOCK,
)
from services.report.review import apply_availability
from services.report.store import (
    _checked_report_identifier,
    _append_career_report_feedback,
    _attachment_content_disposition,
    _build_career_report_diff_blocks,
    _build_career_report_section_map,
    _career_report_export_filename_stem,
    _career_report_file_paths,
    _CAREER_REPORT_QUICK_POLISH,
    _commit_career_report_markdown_to_store,
    _fallback_summary_career_quick_action,
    _list_career_report_snapshots,
    _normalize_career_report_feedback,
    _normalize_career_report_snapshot,
    _public_career_report_bundle,
    _public_career_report_job,
    _public_career_report_snapshot,
    _public_career_report_state,
    _read_career_report_bundle,
    _read_career_report_bundle_by_id,
    _read_career_report_snapshot,
    _refresh_career_report_role_resolution,
    _run_career_report_completeness_check,
    _sanitize_transient_career_report_state,
    _save_career_report_snapshot,
    _split_career_polish_output,
    CAREER_REPORT_EXPORT_FORMATS,
)
from services.report.tracker import (
    _build_career_report_tracker,
    _career_tracker_now,
    _normalize_tracker_status,
    _sync_career_report_tracker_state,
)
from services.report.workflow import (
    read_report_workflow,
    validate_report_continuation,
    validate_report_request,
)
from services.user_state import (
    _current_user,
    _load_user_state,
    _login_required,
    _owned_resume_storage_path,
    _read_json_file,
    _save_user_state,
    _saved_matching_role_payload,
    _saved_profile_snapshot_payload,
    APP_DATA_LOCK,
)


blueprint = Blueprint("report", __name__)


@blueprint.before_app_request
def _validate_private_report_identifiers():
    if not request.path.startswith("/api/career-report/") or not _current_user():
        return None
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    try:
        for key in ("report_id", "snapshot_id", "continue_report_id"):
            for value in [request.args.get(key), body.get(key)]:
                _checked_report_identifier(value, allow_empty=True)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    return None


@blueprint.route("/api/career-report/generate/start", methods=["POST"])
@_login_required
def api_career_report_generate_start():
    user = _current_user()
    username = user["username"]
    running = _find_running_career_report_job(username)
    if running:
        return jsonify({
            "message": "已有职业规划报告任务在运行中。",
            "job_id": str(running.get("job_id") or ""),
            "already_running": True,
        }), 409

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "请求必须是有效的 JSON 对象。"}), 400
    profile_payload = payload.get("profile_snapshot") if isinstance(payload.get("profile_snapshot"), dict) else {}
    role_payload = _saved_matching_role_payload({"role_rankings": payload.get("role_rankings")})
    focus_role_id = str(payload.get("focus_role_id") or "").strip()
    state = _load_user_state(username)
    if not profile_payload:
        profile_payload = _saved_profile_snapshot_payload(state.get("profile_snapshot"))
    if not role_payload:
        role_payload = _saved_matching_role_payload(state.get("career_matching"))
    if not focus_role_id and role_payload and isinstance(state.get("career_matching"), dict):
        focus_role_id = str((state.get("career_matching") or {}).get("focus_role_id") or "").strip()
    if not any(str(role.get("id") or "") == focus_role_id for role in role_payload):
        focus_role_id = ""
    if not profile_payload:
        profile_payload = {}
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    profile_portrait = state.get("profile_portrait") if isinstance(state.get("profile_portrait"), dict) else {}
    profile_payload = dict(profile_payload)
    profile_payload["feedback_memory"] = _normalize_career_report_feedback(report_state.get("feedback"))
    profile_payload["portrait_prompt_version"] = str(
        ((profile_portrait.get("prompt_pipeline") or {}).get("pipeline_version"))
        or PORTRAIT_PROMPT_PIPELINE_VERSION
    ).strip()
    profile_payload["agent_memory"] = _build_career_report_agent_memory(state, profile_payload, role_payload)

    continuation = None
    report_id = str(payload.get("continue_report_id") or "").strip()
    try:
        if report_id:
            snapshot = read_report_workflow(username, report_id)
            checkpoint_id = str(payload.get("checkpoint_id") or "")
            if not checkpoint_id or checkpoint_id != snapshot["checkpoint_id"]:
                return jsonify({"message": "工作流已有更新，请刷新后继续。"}), 409
            response = payload.get("response") or {}
            validate_report_continuation(response, snapshot)
            continuation = {"checkpoint_id": checkpoint_id, "response": response}
        else:
            report_id = f"report-{uuid.uuid4().hex[:12]}"
            resume_scope = state.get("resume_profile") or {}
            resume_path = _owned_resume_storage_path(username, str(resume_scope.get("storage_path") or ""))
            resume_path = resume_path if resume_path and os.path.isfile(resume_path) else ""
            raw_resume = str(resume_scope.get("resume_source_text") or "").strip()
            if not resume_path and not raw_resume:
                return jsonify({"message": "请先上传简历，再启动多智能体报告。"}), 400
            workflow_request = dict(payload.get("workflow") or {})
            profile_payload["report_user_inputs"] = {key: workflow_request.get(key, "")
                for key in ("preferences", "additional_evidence")}
            shared_memory = dict(get_app().extensions["chat_service"].career_context(username))
            shared_memory["personality"] = personality.describe(personality.collect(state))
            workflow_request = apply_report_memory(workflow_request, shared_memory)
            profile_payload["report_city_memory"] = [
                {"id": row["id"], "value": row["value"]}
                for row in get_app().extensions["chat_service"].store.memory_snapshot(username)[1]
                if row["kind"] == "preference" and row["key"] == "target_city" and row["status"] == "active"]
            availability, preferences = apply_availability(payload.get("availability"), workflow_request.get("preferences", ""))
            if availability:
                profile_payload["report_availability"] = availability
                workflow_request["preferences"] = preferences
                if isinstance(workflow_request.get("recruitment"), dict):
                    recruitment = dict(workflow_request["recruitment"])
                    schedule = "\n时间安排（用户选择）：" + availability["summary"]
                    recruitment["request"] = str(recruitment.get("request") or "")[:3000 - len(schedule)] + schedule
                    workflow_request["recruitment"] = recruitment
            profile_payload["agent_workflow"] = validate_report_request(workflow_request, raw_resume, file_path=resume_path)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"message": str(exc)}), 400
    except ImportError:
        return jsonify({"message": "请先安装 requirements.txt 中的 Agent 依赖。"}), 503

    selection_snapshot = {}
    base_url, api_key, model = llm_env.chat_runtime()
    if not (base_url and api_key and model):
        _career_report_console_log(report_id, "启动请求被拒绝", reason="model_not_configured")
        return jsonify({"message": "模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。"}), 400
    runtime_llm = {"model": model, "base_url": base_url, "api_key": api_key,
                   "selection": dict(selection_snapshot), "continuation": continuation}

    job_id = uuid.uuid4().hex
    stage_label = next((item["label"] for item in CAREER_REPORT_STAGE_DEFS if item["key"] == "resume_analysis"), "简历分析")
    job = {
        "job_id": job_id,
        "username": username,
        "status": "queued",
        "stage": "resume_analysis",
        "stage_label": stage_label,
        "stage_detail": "任务已创建，等待后台编排",
        "message": "",
        "created_at": int(time.time()),
        "started_at": 0,
        "finished_at": 0,
        "report_id": report_id,
        "progress": build_stage_progress("resume_analysis"),
        "model": str(runtime_llm.get("model") or ""),
        "generation_mode": "langgraph",
        "cancel_requested": False,
    }
    with CAREER_REPORT_LOCK:
        running = next((item for item in CAREER_REPORT_JOBS.values()
                        if item.get("username") == username and item.get("status") in {"queued", "running"}), None)
        if running:
            return jsonify({"message": "已有职业规划报告任务在运行中。",
                            "job_id": running["job_id"], "already_running": True}), 409
        CAREER_REPORT_JOBS[job_id] = job

    _career_report_console_log(
        job_id,
        "收到启动请求，任务入队",
        user=username,
        report_id=report_id,
        model=str(runtime_llm.get("model") or "none"),
        mode="langgraph",
        roles=len(role_payload or []),
        focus_role=focus_role_id or "auto",
    )

    _save_career_report_progress(
        username,
        job_id,
        "resume_analysis",
        stage_label,
        "任务已创建，等待后台编排",
        status="queued",
        report_id=report_id,
        model=str(runtime_llm.get("model") or ""),
        generation_mode="langgraph",
        focus_role_id=focus_role_id,
    )

    thread = threading.Thread(
        target=_run_career_report_job,
        args=(username, job_id, report_id, profile_payload, role_payload, focus_role_id, runtime_llm),
        daemon=True,
        name=f"career-report-{job_id[:8]}",
    )
    thread.start()

    return jsonify({
        "message": "职业规划报告任务已启动。",
        "job_id": job_id,
        "report_id": report_id,
        "already_running": False,
    })


@blueprint.route("/api/career-report/workflow/<report_id>", methods=["GET"])
@_login_required
def api_career_report_workflow(report_id):
    try:
        snapshot = read_report_workflow(_current_user()["username"], report_id)
    except ValueError as exc:
        return jsonify({"message": str(exc)}), 400
    except ImportError:
        return jsonify({"message": "请安装 Agent 运行依赖。"}), 503
    if not snapshot["checkpoint_id"]:
        return jsonify({"message": "没有找到此账户的报告工作流。"}), 404
    return jsonify(snapshot)


@blueprint.route("/api/career-report/generate/cancel", methods=["POST"])
@_login_required
def api_career_report_generate_cancel():
    user = _current_user()
    username = user["username"]
    payload = request.get_json(silent=True) or {}
    job_id = str(payload.get("job_id") or request.args.get("job_id") or "").strip()
    selected = None

    with CAREER_REPORT_LOCK:
        if job_id:
            candidate = CAREER_REPORT_JOBS.get(job_id)
            if isinstance(candidate, dict) and str(candidate.get("username") or "") == username:
                selected = candidate
        else:
            jobs = [
                item
                for item in CAREER_REPORT_JOBS.values()
                if isinstance(item, dict)
                and str(item.get("username") or "") == username
                and str(item.get("status") or "") in {"queued", "running"}
            ]
            jobs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            if jobs:
                selected = jobs[0]

        if not isinstance(selected, dict):
            return jsonify({"message": "当前没有可停止的职业报告生成任务。"}), 404

        status = str(selected.get("status") or "")
        if status not in {"queued", "running"}:
            return jsonify({
                "message": "该任务已经结束，无需停止。",
                "job": _public_career_report_job(dict(selected)),
            })

        selected["status"] = "canceled"
        CAREER_REPORT_JOBS.touch(str(selected.get("job_id") or ""))
        selected["cancel_requested"] = True
        selected["finished_at"] = int(time.time())
        selected["message"] = "用户已停止本次生成。"
        selected["stage_detail"] = "用户已停止本次生成，旧任务不会写入报告。"
        selected_job = dict(selected)

    _career_report_console_log(
        str(selected_job.get("job_id") or job_id),
        "收到停止请求",
        user=username,
        stage=str(selected_job.get("stage") or ""),
    )
    _save_career_report_progress(
        username,
        str(selected_job.get("job_id") or job_id),
        str(selected_job.get("stage") or "report_writer"),
        str(selected_job.get("stage_label") or "报告生成"),
        "用户已停止本次生成，旧任务不会写入报告。",
        status="canceled",
        error_message="",
        model=str(selected_job.get("model") or ""),
        generation_mode=str(selected_job.get("generation_mode") or ""),
        report_id=str(selected_job.get("report_id") or ""),
    )

    current_bundle = _read_career_report_bundle(username)
    if not (isinstance(current_bundle, dict) and current_bundle.get("meta")):
        state = _load_user_state(username)
        state["career_report"] = empty_report_state()
        _save_user_state(username, state)

    return jsonify({
        "message": "已停止本次职业报告生成。正在进行中的模型请求如果稍后返回，也不会写入报告。",
        "job": _public_career_report_job(selected_job),
    })


@blueprint.route("/api/career-report/generate/status", methods=["GET"])
@_login_required
def api_career_report_generate_status():
    user = _current_user()
    username = user["username"]
    job_id = str(request.args.get("job_id") or "").strip()
    selected = None
    with CAREER_REPORT_LOCK:
        if job_id:
            candidate = CAREER_REPORT_JOBS.get(job_id)
            if isinstance(candidate, dict) and str(candidate.get("username") or "") == username:
                selected = dict(candidate)
        else:
            jobs = [
                dict(item)
                for item in CAREER_REPORT_JOBS.values()
                if isinstance(item, dict) and str(item.get("username") or "") == username
            ]
            jobs.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
            if jobs:
                selected = jobs[0]

    # 前端可能仍轮询「已取消/已结束」的旧 job_id；若已有更新的运行中任务，改为返回当前运行任务。
    if isinstance(selected, dict):
        sel_status = str(selected.get("status") or "")
        if sel_status not in {"queued", "running"}:
            running = _find_running_career_report_job(username)
            if (
                running
                and int(running.get("created_at") or 0) > int(selected.get("created_at") or 0)
            ):
                selected = dict(running)
    elif job_id:
        running = _find_running_career_report_job(username)
        if running:
            selected = dict(running)

    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    report_status = str(report_state.get("status") or "")
    current_bundle = _read_career_report_bundle(username)
    if not selected and report_status in {"queued", "running"}:
        report_state.update({
            "status": "failed",
            "stage_detail": "后台执行已中断，可从已保存的检查点继续。",
            "error_message": "",
        })
        state["career_report"] = report_state
        _save_user_state(username, state)

    merged_state = dict(report_state) if isinstance(report_state, dict) else {}
    if isinstance(selected, dict):
        jst = str(selected.get("status") or "")
        if jst in {"queued", "running"}:
            merged_state.update(
                {
                    "status": jst,
                    "job_id": str(selected.get("job_id") or merged_state.get("job_id") or ""),
                    "report_id": str(selected.get("report_id") or merged_state.get("report_id") or ""),
                    "stage": str(selected.get("stage") or merged_state.get("stage") or ""),
                    "stage_label": str(selected.get("stage_label") or merged_state.get("stage_label") or ""),
                    "stage_detail": str(
                        selected.get("stage_detail")
                        or selected.get("message")
                        or merged_state.get("stage_detail")
                        or ""
                    ),
                    "progress": selected.get("progress")
                    if isinstance(selected.get("progress"), list)
                    else merged_state.get("progress"),
                    "agent_activity": selected.get("agent_activity") or merged_state.get("agent_activity", {}),
                    "model": str(selected.get("model") or merged_state.get("model") or ""),
                    "generation_mode": str(selected.get("generation_mode") or merged_state.get("generation_mode") or ""),
                    "error_message": "",
                }
            )

    merged_state, merged_state_changed = _sanitize_transient_career_report_state(
        username,
        merged_state,
        current_bundle=current_bundle,
    )
    if merged_state_changed:
        state["career_report"] = merged_state
        _save_user_state(username, state)

    return jsonify({
        "job": _public_career_report_job(selected),
        "state": _public_career_report_state(merged_state),
    })


@blueprint.route("/api/career-report/current", methods=["GET"])
@_login_required
def api_career_report_current():
    user = _current_user()
    bundle = _read_career_report_bundle(user["username"])
    bundle = _refresh_career_report_role_resolution(bundle)
    if isinstance(bundle, dict) and bundle.get("meta"):
        state, report_state, _ = _sync_career_report_tracker_state(user["username"], bundle)
    else:
        state = _load_user_state(user["username"])
        report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
        report_state, report_state_changed = _sanitize_transient_career_report_state(
            user["username"],
            report_state,
            current_bundle=bundle,
        )
        if report_state_changed:
            state["career_report"] = report_state
            _save_user_state(user["username"], state)
    data = _public_career_report_bundle(bundle) if isinstance(bundle, dict) and bundle.get("meta") else None
    return jsonify({
        "data": data,
        "state": _public_career_report_state(report_state),
    })


@blueprint.route("/api/career-report/feedback", methods=["POST"])
@_login_required
def api_career_report_feedback():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in {"accurate", "partial", "off_target"}:
        return jsonify({"message": "请先选择反馈结论。"}), 400

    note = str(payload.get("note") or "").strip()[:320]
    bundle = _read_career_report_bundle(user["username"])
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}

    state = _load_user_state(user["username"])
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else empty_report_state()
    report_state["feedback"] = _append_career_report_feedback(
        report_state.get("feedback"),
        {
            "report_id": str(payload.get("report_id") or meta.get("report_id") or report_state.get("report_id") or "").strip(),
            "focus_role_id": str(payload.get("focus_role_id") or meta.get("focus_role_id") or report_state.get("focus_role_id") or "").strip(),
            "focus_role_name": str(
                payload.get("focus_role_name")
                or document.get("focus_role_name")
                or meta.get("focus_role_name")
                or ""
            ).strip(),
            "verdict": verdict,
            "note": note,
        },
    )
    state["career_report"] = report_state
    _save_user_state(user["username"], state)
    return jsonify({
        "message": "反馈已记录，下次生成会优先吸收。",
        "feedback": report_state.get("feedback"),
        "state": _public_career_report_state(report_state),
    })


@blueprint.route("/api/career-report/polish", methods=["POST"])
@_login_required
def api_career_report_polish():
    payload = request.get_json(silent=True) or {}
    section_key = str(payload.get("section_key") or "").strip()[:80]
    text = str(payload.get("selection") or payload.get("text") or "").strip()
    instruction = str(payload.get("instruction") or "").strip()[:800]
    quick_action = str(payload.get("quick_action") or "").strip().lower()[:32]
    if quick_action in _CAREER_REPORT_QUICK_POLISH:
        preset = _CAREER_REPORT_QUICK_POLISH[quick_action]
        instruction = f"{preset}\n\n{instruction}".strip() if instruction else preset
        instruction = instruction[:800]
    want_ai_summary = (
        quick_action in _CAREER_REPORT_QUICK_POLISH
        or str(payload.get("want_ai_summary") or "").strip().lower() in ("1", "true", "yes")
    )
    model_override = str(payload.get("model") or "").strip()[:120]
    full_text = str(payload.get("full_text") or "").strip()
    try:
        selection_start = int(payload.get("selection_start")) if payload.get("selection_start") is not None else -1
        selection_end = int(payload.get("selection_end")) if payload.get("selection_end") is not None else -1
    except Exception:
        selection_start = -1
        selection_end = -1
    if not text:
        return jsonify({"message": "缺少需要润色的报告段落。"}), 400

    text = text[:6000]
    base_url, api_key, model = llm_env.chat_runtime()
    if model_override:
        model = model_override
    if not (base_url and api_key and model):
        return jsonify({"message": "请先配置可用的模型后再润色报告段落。"}), 400

    system_prompt = (
        "你是职业发展报告编辑。只润色用户提供的报告段落，不新增事实、不改变结论、不编造数据。"
        "保留 Markdown 结构，压缩重复表达，让语言更清晰、专业、适合学生职业规划报告。"
        "如果原文包含 JSON 或表格，只保留必要说明，不改动事实字段。"
        "需要注意段落连贯性，避免句子层面的孤立替换；若提供上下文，需与上下文语气、术语、叙事节奏一致。"
    )
    if want_ai_summary:
        system_prompt += (
            "\n\n输出格式（必须遵守）：先用 2-4 句中文概括本次润色侧重点与结构调整（不要复述润色后的正文）。"
            "然后单独一行输出分隔符 <<<AI_BODY>>>（仅此一行，勿加反引号），"
            "换行后只输出润色后的正文，可使用 Markdown。"
        )
    extra_instruction = f"\n\n用户额外要求：{instruction}" if instruction else ""
    context_hint = ""
    if full_text and selection_start >= 0 and selection_end > selection_start:
        safe_start = max(0, min(selection_start, len(full_text)))
        safe_end = max(safe_start, min(selection_end, len(full_text)))
        before = full_text[max(0, safe_start - 900):safe_start].strip()
        after = full_text[safe_end:min(len(full_text), safe_end + 900)].strip()
        if before or after:
            context_hint = (
                "\n\n上下文（仅用于保证连贯）：\n"
                f"--- 上文 ---\n{before or '（无）'}\n"
                f"--- 下文 ---\n{after or '（无）'}\n"
            )
    if want_ai_summary:
        user_msg = (
            f"模块：{section_key or '未指定'}{extra_instruction}{context_hint}\n\n"
            "请严格按系统提示的格式输出：先概括，再输出 <<<AI_BODY>>> 分隔符，最后给出润色后的正文。\n\n"
            "目标段落如下：\n\n"
            f"{text}"
        )
    else:
        user_msg = (
            f"模块：{section_key or '未指定'}{extra_instruction}{context_hint}\n\n"
            "请只输出润色后的目标段落文本（不要附加解释），并保持与上下文衔接自然：\n\n"
            f"{text}"
        )
    try:
        polished = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": user_msg}],
            system_prompt=system_prompt,
            max_tokens=2400 if want_ai_summary else 1800,
        )
    except Exception as exc:
        get_app().logger.exception("career report polish failed")
        return jsonify({"message": str(exc)[:300] or "润色失败。"}), 500

    action_summary = ""
    proposed_text = polished.strip()
    if want_ai_summary:
        summary_part, body_part = _split_career_polish_output(polished)
        if body_part:
            proposed_text = body_part.strip()
            action_summary = (summary_part or "").strip() or _fallback_summary_career_quick_action(quick_action)
        else:
            proposed_text = polished.strip()
            action_summary = (
                _fallback_summary_career_quick_action(quick_action)
                if quick_action
                else "已根据你的说明完成润色；未新增事实。请查看 Diff 了解具体修改。"
            )

    return jsonify({
        "section_key": section_key,
        "model": model,
        "original": text,
        "proposed": proposed_text,
        "polished": proposed_text,
        "action_summary": action_summary,
        "quick_action": quick_action or None,
        "diff_blocks": _build_career_report_diff_blocks(text, proposed_text),
    })


@blueprint.route("/api/career-report/version", methods=["GET", "DELETE"])
@_login_required
def api_career_report_version():
    """按 report_id 读取已归档或当前 latest 的报告正文，不写入用户状态。"""
    user = _current_user()
    if request.method == "DELETE":
        payload = request.get_json(silent=True) or {}
        report_id = str(payload.get("report_id") or request.args.get("report_id") or "").strip()
        if not report_id:
            return jsonify({"message": "缺少 report_id"}), 400
        try:
            result = _delete_career_report_version(user["username"], report_id)
        except FileNotFoundError as exc:
            return jsonify({"message": str(exc) or "未找到对应的职业报告版本。"}), 404
        except ValueError as exc:
            return jsonify({"message": str(exc) or "删除职业报告失败。"}), 400

        bundle = _read_career_report_bundle(user["username"])
        state = _load_user_state(user["username"])
        report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else empty_report_state()
        data = _public_career_report_bundle(bundle) if isinstance(bundle, dict) and bundle.get("meta") else None

        message = "该职业报告卡片已删除。"
        if result.get("replacement_report_id"):
            replacement_title = str(result.get("replacement_title") or "上一份正式报告").strip()
            message = f"已删除当前卡片，并切换到 {replacement_title}。"
        elif result.get("deleted_current"):
            message = "已删除当前职业报告，卡片库已回到空状态。"

        return jsonify({
            "message": message,
            "deleted_report_id": result.get("deleted_report_id") or report_id,
            "replacement_report_id": result.get("replacement_report_id") or "",
            "data": data,
            "state": _public_career_report_state(report_state),
        })

    report_id = str(request.args.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"message": "缺少 report_id"}), 400
    paths = _career_report_file_paths(user["username"])
    versions_dir = os.path.join(paths["dir"], "versions")
    bundle = {}
    with APP_DATA_LOCK:
        archive_path = os.path.join(versions_dir, f"{report_id}.json")
        if os.path.isfile(archive_path):
            bundle = _read_json_file(archive_path, {})
        else:
            latest = _read_json_file(paths["json"], {})
            latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
            if latest_id == report_id:
                bundle = latest
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到该版本的完整报告（可能生成于版本归档功能之前）。"}), 404
    tracker = _build_career_report_tracker(bundle, None)
    return jsonify({
        "data": _public_career_report_bundle(bundle),
        "tracker": tracker,
    })


def _career_report_preview_context():
    from services.report.link_preview import public_preview_url, report_contains_url

    url = public_preview_url(request.args.get("url"))
    if not url:
        return None, (jsonify({"message": "仅支持公开网页链接。"}), 400)
    username = _current_user()["username"]
    report_id = str(request.args.get("report_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(username, report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return None, (jsonify({"message": "未找到对应的职业报告。"}), 404)
    resolved_id = str(bundle["meta"].get("report_id") or report_id)
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    snapshot = _read_career_report_snapshot(username, resolved_id, snapshot_id) if snapshot_id else None
    if snapshot_id and not snapshot:
        return None, (jsonify({"message": "未找到对应的编辑快照。"}), 404)
    if not report_contains_url(bundle, url, snapshot):
        return None, (jsonify({"message": "此链接不在当前报告中。"}), 404)
    return {"url": url, "report_id": resolved_id, "snapshot_id": snapshot_id}, None


@blueprint.route("/api/career-report/link-preview", methods=["GET"])
@_login_required
def api_career_report_link_preview():
    from services.report.link_preview import get_link_preview

    context, error = _career_report_preview_context()
    if error is not None:
        return error
    preview = get_link_preview(context["url"])
    image = preview.pop("image", "")
    preview["image_url"] = url_for("report.api_career_report_link_preview_image", **context) if image else ""
    response = jsonify({"data": preview})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@blueprint.route("/api/career-report/link-preview/image", methods=["GET"])
@_login_required
def api_career_report_link_preview_image():
    from services.report.link_preview import get_link_preview_image

    context, error = _career_report_preview_context()
    if error is not None:
        return error
    image = get_link_preview_image(context["url"])
    if image is None:
        return "", 404
    response = current_app.response_class(image[0], mimetype=image[1])
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@blueprint.route("/api/career-report/source", methods=["GET"])
@_login_required
def api_career_report_source():
    user = _current_user()
    report_id = str(request.args.get("report_id") or "").strip()
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404
        normalized = _normalize_career_report_snapshot(snapshot, bundle=bundle, report_id=resolved_report_id)
        completeness = normalized.get("completeness_check") if isinstance(normalized.get("completeness_check"), dict) else _run_career_report_completeness_check(bundle, normalized.get("markdown"), normalized)
        return jsonify({
            "report_id": resolved_report_id,
            "snapshot_id": normalized["snapshot_id"],
            "source_type": normalized.get("source") or "snapshot",
            "title": normalized.get("title") or normalized.get("label") or "编辑快照",
            "markdown": normalized.get("markdown") or "",
            "section_map": normalized.get("section_map") or [],
            "diff_blocks": normalized.get("diff_blocks") or [],
            "completeness_check": completeness,
            "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
            "bundle": _public_career_report_bundle(bundle),
        })

    report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()
    return jsonify({
        "report_id": resolved_report_id,
        "snapshot_id": "",
        "source_type": "formal_report",
        "title": str(report_document.get("title") or (bundle.get("meta") or {}).get("title") or "职业发展报告").strip() or "职业发展报告",
        "markdown": markdown_text,
        "section_map": _build_career_report_section_map(bundle, markdown_text),
        "diff_blocks": [],
        "completeness_check": _run_career_report_completeness_check(bundle, markdown_text),
        "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
        "bundle": _public_career_report_bundle(bundle),
    })


@blueprint.route("/api/career-report/snapshot/save", methods=["POST"])
@_login_required
def api_career_report_snapshot_save():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    report_id = str(payload.get("report_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    markdown_text = normalize_br_tags_in_markdown(str(payload.get("markdown") or "").strip())
    if not markdown_text:
        return jsonify({"message": "缺少快照 Markdown 内容。"}), 400

    section_map = _build_career_report_section_map(bundle, markdown_text)
    completeness_check = _run_career_report_completeness_check(bundle, markdown_text)
    snapshot = _save_career_report_snapshot(
        user["username"],
        resolved_report_id,
        {
            "snapshot_id": str(payload.get("snapshot_id") or "").strip(),
            "based_on_report_id": resolved_report_id,
            "source": str(payload.get("source") or "manual").strip() or "manual",
            "label": str(payload.get("label") or payload.get("title") or "编辑快照").strip() or "编辑快照",
            "title": str(payload.get("title") or payload.get("label") or "编辑快照").strip() or "编辑快照",
            "focus_role_name": str(payload.get("focus_role_name") or (bundle.get("meta") or {}).get("focus_role_name") or "").strip(),
            "markdown": markdown_text,
            "section_map": section_map,
            "diff_blocks": payload.get("diff_blocks") if isinstance(payload.get("diff_blocks"), list) else [],
            "completeness_check": completeness_check,
        },
    )
    # 从正式报告进入润色且未绑定旧快照时：保存同时写回该版本的报告正文，阅览室下次打开即为此稿。
    formal_report_updated = False
    if not str(payload.get("snapshot_id") or "").strip():
        formal_report_updated = _commit_career_report_markdown_to_store(
            user["username"], resolved_report_id, markdown_text
        )
    return jsonify({
        "message": "编辑快照已保存。",
        "snapshot": _public_career_report_snapshot(snapshot, include_content=True),
        "draft_snapshots": _list_career_report_snapshots(user["username"], resolved_report_id),
        "formal_report_updated": formal_report_updated,
    })


@blueprint.route("/api/career-report/snapshot/check", methods=["POST"])
@_login_required
def api_career_report_snapshot_check():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    report_id = str(payload.get("report_id") or "").strip()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "未找到对应的职业报告。"}), 404

    resolved_report_id = str((bundle.get("meta") or {}).get("report_id") or report_id or "").strip()
    snapshot = None
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404

    markdown_text = str(payload.get("markdown") or "").strip()
    if not markdown_text:
        if isinstance(snapshot, dict):
            markdown_text = str(snapshot.get("markdown") or "").strip()
        else:
            report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
            markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()

    return jsonify({
        "report_id": resolved_report_id,
        "snapshot_id": snapshot_id,
        "completeness_check": _run_career_report_completeness_check(bundle, markdown_text, snapshot),
    })


@blueprint.route("/api/career-report/tracker/sync", methods=["POST"])
@_login_required
def api_career_report_tracker_sync():
    user = _current_user()
    bundle = _read_career_report_bundle(user["username"])
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可同步的职业规划报告。"}), 404

    payload = request.get_json(silent=True) or {}
    current_capabilities = payload.get("current_capabilities") if isinstance(payload.get("current_capabilities"), list) else []
    state, report_state, tracker = _sync_career_report_tracker_state(
        user["username"],
        bundle,
        current_capabilities=current_capabilities,
    )
    return jsonify(
        {
            "tracker": tracker,
            "state": _public_career_report_state(report_state),
            "data": _public_career_report_bundle(bundle),
        }
    )


@blueprint.route("/api/career-report/tracker/item", methods=["POST"])
@_login_required
def api_career_report_tracker_item():
    user = _current_user()
    payload = request.get_json(silent=True) or {}
    item_type = str(payload.get("item_type") or "").strip().lower()
    item_id = str(payload.get("item_id") or "").strip()
    status = _normalize_tracker_status(payload.get("status"), allow_doing=item_type == "plan")
    if item_type not in {"plan", "checkpoint"} or not item_id:
        return jsonify({"message": "请指定 item_type 和 item_id。"}), 400

    bundle = _read_career_report_bundle(user["username"])
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可更新的职业规划报告。"}), 404

    state, report_state, tracker = _sync_career_report_tracker_state(user["username"], bundle)
    if not isinstance(tracker, dict):
        return jsonify({"message": "当前职业报告尚未完成初始化。"}), 409

    key = "plan_items" if item_type == "plan" else "checkpoints"
    allow_doing = item_type == "plan"
    safe_status = _normalize_tracker_status(status, allow_doing=allow_doing)
    items = tracker.get(key) if isinstance(tracker.get(key), list) else []
    matched = False
    now_text = _career_tracker_now()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") != item_id:
            continue
        matched = True
        item["status"] = safe_status
        item["updated_at"] = now_text
        if safe_status == "doing":
            item["started_at"] = str(item.get("started_at") or now_text)
            item["completed_at"] = ""
        elif safe_status == "done":
            if allow_doing:
                item["started_at"] = str(item.get("started_at") or now_text)
            item["completed_at"] = str(item.get("completed_at") or now_text)
        else:
            if allow_doing:
                item["started_at"] = ""
            item["completed_at"] = ""
        break

    if not matched:
        return jsonify({"message": "未找到对应的职业档案条目。"}), 404

    tracker = _build_career_report_tracker(bundle, tracker)
    report_state["tracker"] = tracker
    state["career_report"] = report_state
    _save_user_state(user["username"], state)
    return jsonify({"tracker": tracker, "state": _public_career_report_state(report_state)})


@blueprint.route("/api/career-report/export", methods=["GET"])
@_login_required
def api_career_report_export():
    user = _current_user()
    from services.report.html_layout import normalize_typography, typography_css
    try:
        typography = normalize_typography(json.loads(request.args.get("typography") or "{}"))
    except (ValueError, TypeError):
        return jsonify({"message": "报告字号参数无效。"}), 400
    export_format = str(request.args.get("format") or "pdf").strip().lower()
    if export_format not in {"html", "md", "docx", "pdf"}:
        return jsonify({"message": "仅支持 html / md / docx / pdf 导出。"}), 400

    report_id = str(request.args.get("report_id") or "").strip()
    snapshot_id = str(request.args.get("snapshot_id") or "").strip()
    bundle = _read_career_report_bundle_by_id(user["username"], report_id)
    if not isinstance(bundle, dict) or not bundle.get("meta"):
        return jsonify({"message": "当前还没有可导出的职业规划报告。"}), 404

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    resolved_report_id = str(meta.get("report_id") or report_id or "").strip()
    source_label = str(meta.get("title") or "career-report").strip() or "career-report"
    if snapshot_id:
        snapshot = _read_career_report_snapshot(user["username"], resolved_report_id, snapshot_id)
        if not isinstance(snapshot, dict) or not snapshot:
            return jsonify({"message": "未找到对应的编辑快照。"}), 404
        normalized = _normalize_career_report_snapshot(snapshot, bundle=bundle, report_id=resolved_report_id)
        markdown_text = str(normalized.get("markdown") or "").strip()
        source_label = str(normalized.get("title") or normalized.get("label") or source_label).strip() or source_label
    else:
        report_document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
        markdown_text = str(report_document.get("markdown") or render_report_markdown(bundle)).strip()

    markdown_text = normalize_br_tags_in_markdown(markdown_text)

    filename_stem = _career_report_export_filename_stem(
        source_label,
        report_id=resolved_report_id,
        generated_at=str(meta.get("generated_at") or ""),
        version=str(meta.get("version") or ""),
        snapshot_id=snapshot_id,
    )
    if export_format == "md":
        return current_app.response_class(
            markdown_text,
            mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition": _attachment_content_disposition(f"{filename_stem}.md")},
        )

    html_for_render = None
    if export_format == "html":
        html_for_render = (
            render_markdown_export_html(markdown_text, title=source_label)
            if snapshot_id
            else render_report_html(bundle)
        )

    if export_format == "html":
        if html_for_render and typography:
            html_for_render = html_for_render.replace("</style>", typography_css(typography) + "\n</style>")
        return current_app.response_class(
            html_for_render or "",
            mimetype="text/html; charset=utf-8",
            headers={"Content-Disposition": _attachment_content_disposition(f"{filename_stem}.html")},
        )

    if export_format == "pdf":
        try:
            pdf_bytes = export_markdown_to_pdf_bytes(markdown_text, title=source_label, typography=typography)
        except Exception as exc:
            get_app().logger.exception("career report pdf export failed")
            return jsonify({"message": str(exc)[:500] or "PDF 导出失败。"}), 500
        response = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{filename_stem}.pdf",
        )
        response.headers["X-Report-PDF-Engine"] = "pymupdf"
        return response

    try:
        docx_bytes = export_markdown_to_docx_bytes(markdown_text, title=source_label, typography=typography)
    except Exception as exc:
        get_app().logger.exception("career report docx export failed")
        return jsonify({"message": str(exc)[:500] or "DOCX 导出失败。"}), 500

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{filename_stem}.docx",
    )
