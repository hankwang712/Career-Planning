"""职业报告里的行动追踪（成长看板）状态，以及保存报告包时对它的同步。"""

import re
from datetime import datetime

from services.report.store import _list_career_report_version_summaries, CAREER_REPORT_EXPORT_FORMATS
from services.user_state import _load_user_state, _save_user_state


def _career_tracker_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_tracker_score(value):
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score != score:
        return None
    return max(0, min(100, int(round(score))))


def _normalize_tracker_status(raw_status, allow_doing=True):
    status = str(raw_status or "").strip().lower()
    if status in {"done", "completed", "complete", "checked"}:
        return "done"
    if allow_doing and status in {"doing", "active", "running", "in_progress", "progress"}:
        return "doing"
    return "pending"


def _slugify_tracker_id(raw_text):
    slug = re.sub(r"[^0-9A-Za-z_.-]+", "-", str(raw_text or "").strip()).strip("-").lower()
    return slug or "item"


def _normalize_tracker_history(raw_history):
    history = []
    if not isinstance(raw_history, list):
        return history
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        score = _normalize_tracker_score(item.get("score"))
        if score is None:
            continue
        history.append({
            "score": score,
            "at": str(item.get("at") or ""),
            "event": str(item.get("event") or "sync"),
        })
    return history[-8:]


def _append_tracker_history(history, score, timestamp, event):
    normalized = _normalize_tracker_history(history)
    safe_score = _normalize_tracker_score(score)
    if safe_score is None:
        return normalized
    if normalized and normalized[-1].get("score") == safe_score:
        return normalized
    normalized.append(
        {
            "score": safe_score,
            "at": str(timestamp or _career_tracker_now()),
            "event": str(event or "sync"),
        }
    )
    return normalized[-8:]


def _normalize_tracker_capability_payload(raw_items):
    payload = {}
    if not isinstance(raw_items, list):
        return payload
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        payload[key] = {
            "key": key,
            "label": str(item.get("label") or key).strip() or key,
            "score": _normalize_tracker_score(item.get("score")),
            "sources": [str(source).strip() for source in (item.get("sources") or []) if str(source).strip()],
        }
    return payload


def _build_career_report_tracker(bundle, existing_tracker=None, current_capabilities=None, version_summaries=None):
    if not isinstance(bundle, dict):
        return None

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_id = str(meta.get("report_id") or "").strip()
    if not report_id:
        return None

    existing = existing_tracker if isinstance(existing_tracker, dict) else {}
    if str(existing.get("report_id") or "") != report_id:
        existing = {}
    phase_plan = bundle.get("phase_plan") if isinstance(bundle.get("phase_plan"), dict) else {}
    profile_snapshot = bundle.get("profile_snapshot") if isinstance(bundle.get("profile_snapshot"), dict) else {}
    gap_map = bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}

    plan_state_map = {}
    for item in existing.get("plan_items") or []:
        if isinstance(item, dict) and item.get("id"):
            plan_state_map[str(item["id"])] = item

    checkpoint_state_map = {}
    for item in existing.get("checkpoints") or []:
        if isinstance(item, dict) and item.get("id"):
            checkpoint_state_map[str(item["id"])] = item

    ability_state_map = {}
    for item in existing.get("ability_growth") or []:
        if isinstance(item, dict) and item.get("key"):
            ability_state_map[str(item["key"])] = item

    generated_at = str(meta.get("generated_at") or existing.get("generated_at") or "")
    current_sync_time = _career_tracker_now()
    capability_payload = _normalize_tracker_capability_payload(current_capabilities)

    plan_items = []
    raw_plan_items = []
    for bucket, phase_key in (("short_term", "short"), ("mid_term", "mid"), ("long_term", "long")):
        raw_plan_items.extend({**item, "phase_key": phase_key} for item in (phase_plan.get(bucket) or []) if isinstance(item, dict))
    for index, item in enumerate(raw_plan_items):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"plan-{index + 1}").strip() or f"plan-{index + 1}"
        previous = plan_state_map.get(item_id, {})
        status = _normalize_tracker_status(previous.get("status"), allow_doing=True)
        started_at = str(previous.get("started_at") or "")
        completed_at = str(previous.get("completed_at") or "") if status == "done" else ""
        if status == "doing" and not started_at:
            started_at = current_sync_time
        if status == "done" and not completed_at:
            completed_at = current_sync_time
        plan_items.append(
            {
                "id": item_id,
                "phase": str(item.get("phase") or ""),
                "title": str(item.get("title") or "阶段任务"),
                "objective": str(item.get("objective") or ""),
                "focus_points": [str(point).strip() for point in (item.get("focus_points") or []) if str(point).strip()],
                "signals": [str(signal).strip() for signal in (item.get("signals") or []) if str(signal).strip()],
                "status": status,
                "started_at": started_at if status in {"doing", "done"} else "",
                "completed_at": completed_at,
                "note": str(previous.get("note") or ""),
                "updated_at": str(previous.get("updated_at") or ""),
                "is_phase": True,
                "phase_key": item.get("phase_key", "short"),
                "is_action": bool(item.get("is_action") or (item.get("task_id") and item.get("deliverable"))),
                "is_roadmap": bool(item.get("is_roadmap")),
                "deliverable": str(item.get("deliverable") or ""),
                "acceptance_criteria": str(item.get("acceptance_criteria") or ""),
                "deadline": str(item.get("due_date") or ""),
                "hours": item.get("hours"), "cost": item.get("cost"),
                "depends_on": item.get("depends_on") or [],
                "week": item.get("week"), "requirement": item.get("requirement") or "",
                "entry_conditions": item.get("entry_conditions") or "",
            }
        )
        # Also expand nested task items into top-level plan items
        for task in (item.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "").strip()
            task_text = str(task.get("text") or "").strip()
            if not task_id or not task_text:
                continue
            prev_task = plan_state_map.get(task_id, {})
            task_status = _normalize_tracker_status(prev_task.get("status"), allow_doing=False)
            task_completed = str(prev_task.get("completed_at") or "") if task_status == "done" else ""
            plan_items.append(
                {
                    "id": task_id,
                    "phase": str(item.get("phase") or ""),
                    "title": task_text,
                    "objective": task_text,
                    "focus_points": [],
                    "signals": [],
                    "parent_phase": item_id,
                    "status": task_status,
                    "started_at": "",
                    "completed_at": task_completed,
                    "note": str(prev_task.get("note") or ""),
                    "updated_at": str(prev_task.get("updated_at") or ""),
                    "is_task": True,
                    "phase_key": item.get("phase_key", "short"),
                    "deliverable": str(task.get("deliverable") or ""),
                    "acceptance_criteria": str(task.get("acceptance_criteria") or ""),
                    "requirement": task.get("requirement") or "",
                    "conditional": bool(task.get("conditional")),
                }
            )

    checkpoints = []
    for index, item in enumerate(phase_plan.get("checkpoints") or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or f"检查点 {index + 1}").strip() or f"检查点 {index + 1}"
        checkpoint_id = str(item.get("id") or f"checkpoint-{_slugify_tracker_id(label)}")
        previous = checkpoint_state_map.get(checkpoint_id, {})
        status = _normalize_tracker_status(previous.get("status"), allow_doing=False)
        completed_at = str(previous.get("completed_at") or "") if status == "done" else ""
        checkpoints.append(
            {
                "id": checkpoint_id,
                "label": label,
                "summary": str(item.get("summary") or ""),
                "due_date": str(item.get("due_date") or ""),
                "status": status,
                "completed_at": completed_at,
                "note": str(previous.get("note") or ""),
                "updated_at": str(previous.get("updated_at") or ""),
            }
        )

    baseline_map = {}
    for item in profile_snapshot.get("capability_vector") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        baseline_map[key] = {
            "key": key,
            "label": str(item.get("label") or key).strip() or key,
            "score": _normalize_tracker_score(item.get("score")),
            "sources": [str(source).strip() for source in (item.get("sources") or []) if str(source).strip()],
        }

    for key, item in capability_payload.items():
        if key not in baseline_map:
            baseline_map[key] = {
                "key": key,
                "label": item.get("label") or key,
                "score": None,
                "sources": [],
            }

    ability_growth = []
    for key, baseline in baseline_map.items():
        previous = ability_state_map.get(key, {})
        baseline_score = _normalize_tracker_score(baseline.get("score"))
        current_score = None
        if key in capability_payload:
            current_score = _normalize_tracker_score(capability_payload[key].get("score"))
        if current_score is None:
            current_score = _normalize_tracker_score(previous.get("current_score"))
        if current_score is None:
            current_score = baseline_score
        delta = None
        if baseline_score is not None and current_score is not None:
            delta = int(current_score - baseline_score)
        history = _normalize_tracker_history(previous.get("history"))
        if not history and baseline_score is not None:
            history = _append_tracker_history(history, baseline_score, generated_at or current_sync_time, "baseline")
        if current_capabilities is not None:
            history = _append_tracker_history(history, current_score, current_sync_time, "profile_sync")
        ability_growth.append(
            {
                "key": key,
                "label": str(baseline.get("label") or previous.get("label") or key),
                "baseline_score": baseline_score,
                "current_score": current_score,
                "delta": delta,
                "baseline_sources": baseline.get("sources") or [],
                "current_sources": capability_payload.get(key, {}).get("sources") or previous.get("current_sources") or baseline.get("sources") or [],
                "history": history,
            }
        )

    # Use task items for progress calculation (more granular); fall back to phase items
    parents_with_tasks = {item.get("parent_phase") for item in plan_items if item.get("is_task")}
    trackable = [item for item in plan_items if item.get("is_task") or item.get("is_action")
                 or (item.get("is_phase") and item["id"] not in parents_with_tasks and not item.get("is_roadmap"))]
    done_count = sum(1 for item in trackable if item.get("status") == "done") + sum(1 for item in checkpoints if item.get("status") == "done")
    doing_count = sum(1 for item in trackable if item.get("status") == "doing")
    total_count = len(trackable) + len(checkpoints)
    weighted_progress = (
        sum(1 for item in trackable if item.get("status") == "done")
        + sum(0.5 for item in trackable if item.get("status") == "doing")
        + sum(1 for item in checkpoints if item.get("status") == "done")
    )
    completion_rate = int(round(weighted_progress / total_count * 100)) if total_count else 0

    improved_count = sum(1 for item in ability_growth if isinstance(item.get("delta"), int) and item.get("delta") > 0)
    declined_count = sum(1 for item in ability_growth if isinstance(item.get("delta"), int) and item.get("delta") < 0)
    stable_count = sum(1 for item in ability_growth if item.get("delta") in {0, None})

    focus_role_name = (
        str(gap_map.get("focus_role_name") or "")
        or str(document.get("focus_role_name") or "")
        or str(meta.get("focus_role_name") or "")
        or "待识别方向"
    )
    focus_role_id = str(meta.get("focus_role_id") or existing.get("focus_role_id") or "")

    current_version = {
        "report_id": report_id,
        "title": str(meta.get("title") or document.get("title") or "职业规划报告"),
        "version": str(meta.get("version") or ""),
        "generated_at": generated_at,
        "focus_role_id": focus_role_id,
        "focus_role_name": focus_role_name,
    }
    versions = []
    versions.append(current_version)
    for item in existing.get("versions") or []:
        if not isinstance(item, dict):
            continue
        item_report_id = str(item.get("report_id") or "")
        if item_report_id and item_report_id == report_id:
            continue
        versions.append(
            {
                "report_id": item_report_id,
                "title": str(item.get("title") or "职业规划报告"),
                "version": str(item.get("version") or ""),
                "generated_at": str(item.get("generated_at") or ""),
                "focus_role_id": str(item.get("focus_role_id") or ""),
                "focus_role_name": str(item.get("focus_role_name") or ""),
            }
        )
    versions = versions[:6]

    next_focus = next((item.get("title") for item in trackable if item.get("status") != "done"), "")
    if not next_focus:
        next_focus = next((item.get("label") for item in checkpoints if item.get("status") != "done"), "")

    return {
        "report_id": report_id,
        "report_title": str(meta.get("title") or document.get("title") or "职业规划报告"),
        "report_version": str(meta.get("version") or ""),
        "focus_role_id": focus_role_id,
        "focus_role_name": focus_role_name,
        "generated_at": generated_at,
        "last_synced_at": current_sync_time if current_capabilities is not None else str(existing.get("last_synced_at") or generated_at),
        "completion_rate": completion_rate,
        "completed_count": done_count,
        "doing_count": doing_count,
        "total_count": total_count,
        "next_focus": str(next_focus or ""),
        "ability_summary": {
            "improved_count": improved_count,
            "declined_count": declined_count,
            "stable_count": stable_count,
        },
        "plan_items": plan_items,
        "checkpoints": checkpoints,
        "ability_growth": ability_growth,
        "versions": versions,
        "action_checklists": phase_plan.get("action_checklists") if isinstance(phase_plan.get("action_checklists"), dict) else {},
    }


def _sync_career_report_tracker_state(username, bundle, current_capabilities=None):
    state = _load_user_state(username)
    report_state = state.get("career_report") if isinstance(state.get("career_report"), dict) else {}
    tracker = _build_career_report_tracker(bundle, report_state.get("tracker"), current_capabilities)
    if isinstance(tracker, dict):
        tracker["versions"] = _list_career_report_version_summaries(username)[:6]
    meta = bundle.get("meta") if isinstance(bundle, dict) and isinstance(bundle.get("meta"), dict) else {}

    if meta and str(report_state.get("status") or "") not in {"running", "queued", "waiting_input", "failed"}:
        report_state.update(
            {
                "status": "ready",
                "report_id": str(meta.get("report_id") or report_state.get("report_id") or ""),
                "generated_at": str(meta.get("generated_at") or report_state.get("generated_at") or ""),
                "focus_role_id": str(meta.get("focus_role_id") or report_state.get("focus_role_id") or ""),
                "title": str(meta.get("title") or report_state.get("title") or ""),
                "summary": str(meta.get("summary") or report_state.get("summary") or ""),
                "export_formats": list(CAREER_REPORT_EXPORT_FORMATS),
            }
        )

    if tracker:
        report_state["tracker"] = tracker
        state["career_report"] = report_state
        _save_user_state(username, state)

    return state, report_state, tracker
