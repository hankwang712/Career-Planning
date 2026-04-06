from __future__ import annotations

from typing import Any

REPORT_VERSION = "2026.04-v3"

# v2 pipeline: 6-agent system
CAREER_REPORT_STAGE_DEFS = [
    {"key": "industry_analysis",  "label": "行业分析",     "agent": "行业分析师"},
    {"key": "resume_evidence",    "label": "简历证据解析", "agent": "简历证据分析官"},
    {"key": "career_positioning", "label": "职业定位",     "agent": "职业定位顾问"},
    {"key": "resume_evidence_2",  "label": "证据对齐复核", "agent": "简历证据分析官(复核)"},
    {"key": "competency_assess",  "label": "能力评估",     "agent": "能力评估官"},
    {"key": "role_match",         "label": "岗位匹配",     "agent": "岗位匹配官"},
    {"key": "path_planning",      "label": "路径规划",     "agent": "路径规划师"},
]

# Legacy stage defs kept for backward compatibility with old reports
CAREER_REPORT_STAGE_DEFS_LEGACY = [
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
    }
