from __future__ import annotations

from typing import Any

REPORT_VERSION = "2026.03-v1"

CAREER_REPORT_STAGE_DEFS = [
    {"key": "profile_fusion", "label": "画像融合", "agent": "Profile Fusion Agent"},
    {"key": "role_retrieval", "label": "目标职业提取", "agent": "Role Retrieval Agent"},
    {"key": "onet_enrichment", "label": "O*NET岗位数据融合", "agent": "O*NET Enrichment Agent"},
    {"key": "trend_intelligence", "label": "趋势情报提炼", "agent": "Trend Intelligence Agent"},
    {"key": "gap_analysis", "label": "差距分析", "agent": "Gap Analysis Agent"},
    {"key": "career_path", "label": "职业路径构建", "agent": "Career Path Agent"},
    {"key": "stage_planning", "label": "阶段规划", "agent": "Stage Planning Agent"},
    {"key": "report_writer", "label": "报告撰写", "agent": "Report Writer Agent"},
    {"key": "critic", "label": "一致性校验", "agent": "Critic Agent"},
]


def build_stage_progress(stage_key: str) -> list[dict[str, Any]]:
    active_index = 0
    for index, item in enumerate(CAREER_REPORT_STAGE_DEFS):
        if item["key"] == stage_key:
            active_index = index
            break
    progress = []
    for index, item in enumerate(CAREER_REPORT_STAGE_DEFS):
        if index < active_index:
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
        "model": "",
        "generation_mode": "",
        "focus_role_id": "",
        "title": "",
        "summary": "",
        "export_formats": ["html", "md"],
        "tracker": None,
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
    }
