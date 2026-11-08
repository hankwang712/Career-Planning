from __future__ import annotations

from typing import Any

REPORT_VERSION = "2026.11-career-development-v3"

CAREER_REPORT_STAGE_DEFS = [
    {"key": "resume_analysis", "label": "简历分析", "agent": "ResumeAnalysisAgent"},
    {"key": "job_analysis", "label": "岗位分析", "agent": "JobAnalysisAgent"},
    {"key": "recruitment_search", "label": "招聘雷达", "agent": "RecruitmentSearchAgent"},
    {"key": "career_decision", "label": "职业决策", "agent": "CareerDecisionAgent"},
    {"key": "review", "label": "补充与确认", "agent": "用户确认"},
    {"key": "action_planning", "label": "行动规划", "agent": "ActionPlanningAgent"},
    {"key": "report_writer", "label": "报告合成", "agent": "报告合成器"},
]


def build_stage_progress(stage_key: str) -> list[dict[str, Any]]:
    # 历史报告编辑阶段仍映射到合成节点。
    key = str(stage_key or "").strip()
    if key == "report_editor":
        key = "report_writer"
    active_index = 0
    for index, item in enumerate(CAREER_REPORT_STAGE_DEFS):
        if item["key"] == key:
            active_index = index
            break
    progress = []
    for index, item in enumerate(CAREER_REPORT_STAGE_DEFS):
        if key == "parallel_analysis":
            status = "active" if index < 3 else "pending"
        elif index < active_index:
            status = "done"
        elif index == active_index:
            status = "active"
        else:
            status = "pending"
        progress.append(
            {
                "key": item["key"],
                "label": item["label"],
                "agent": item["agent"],
                "status": status,
            }
        )
    return progress


def empty_report_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "job_id": "",
        "report_id": "",
        "generated_at": "",
        "stage": "",
        "stage_label": "",
        "stage_detail": "",
        "error_message": "",
        "progress": [],
        "agent_activity": {},
        "model": "",
        "generation_mode": "",
        "focus_role_id": "",
        "title": "",
        "summary": "",
        "export_formats": ["pdf", "docx", "md", "html"],
        "tracker": None,
        "feedback": None,
    }


def empty_report_job() -> dict[str, Any]:
    return {
        "job_id": "",
        "username": "",
        "status": "idle",
        "stage": "",
        "stage_label": "",
        "stage_detail": "",
        "message": "",
        "created_at": 0,
        "started_at": 0,
        "finished_at": 0,
        "report_id": "",
        "progress": [],
        "agent_activity": {},
    }
