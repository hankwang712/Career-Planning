from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .agents import (
    run_critic_agent,
    run_gap_analysis_agent,
    run_onet_enrichment_agent,
    run_career_path_agent,
    run_profile_fusion_agent,
    run_report_writer_agent,
    run_role_retrieval_agent,
    run_stage_planning_agent,
    run_trend_intelligence_agent,
)
from .exporters import render_report_html, render_report_markdown
from .schemas import CAREER_REPORT_STAGE_DEFS, REPORT_VERSION

StageCallback = Callable[[str, str, str], None]
MarkdownWriter = Callable[[dict[str, Any], str], str]


def generate_career_report_bundle(
    *,
    username: str,
    report_id: str,
    profile_payload: dict[str, Any],
    role_payload: list[dict[str, Any]],
    news_payload: dict[str, Any],
    focus_role_id: str = "",
    stage_callback: StageCallback | None = None,
    markdown_writer: MarkdownWriter | None = None,
    model_name: str = "",
    generation_mode: str = "template",
) -> dict[str, Any]:
    def notify(stage_key: str, detail: str) -> None:
        stage_label = next((item["label"] for item in CAREER_REPORT_STAGE_DEFS if item["key"] == stage_key), stage_key)
        if callable(stage_callback):
            stage_callback(stage_key, stage_label, detail)

    notify("profile_fusion", "正在汇总测评、访谈、简历与基础信息")
    profile_snapshot = run_profile_fusion_agent(profile_payload, role_payload)

    notify("role_retrieval", "正在确定目标职业方向与排序")
    role_candidates = run_role_retrieval_agent(profile_snapshot, role_payload)
    if focus_role_id:
        role_candidates = sorted(role_candidates, key=lambda item: str(item.get("id") or "") != focus_role_id)

    notify("onet_enrichment", "正在融合 O*NET 岗位数据库信息")
    role_candidates = run_onet_enrichment_agent(role_candidates)

    notify("trend_intelligence", "正在提炼职业趋势与现实约束")
    trend_brief = run_trend_intelligence_agent(news_payload)

    notify("gap_analysis", "正在比较当前能力与目标岗位要求")
    gap_map = run_gap_analysis_agent(profile_payload, profile_snapshot, role_candidates)

    notify("career_path", "正在构建职业发展路径")
    career_path = run_career_path_agent(profile_snapshot, role_candidates)

    notify("stage_planning", "正在生成分阶段成长路径与行动计划")
    phase_plan = run_stage_planning_agent(profile_snapshot, role_candidates, gap_map)

    notify("report_writer", "正在组织结构化职业规划报告")
    report_document = run_report_writer_agent(
        profile_snapshot,
        role_candidates,
        gap_map,
        phase_plan,
        trend_brief,
        career_path=career_path,
        markdown_writer=markdown_writer,
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bundle = {
        "meta": {
            "report_id": report_id,
            "username": username,
            "generated_at": generated_at,
            "status": "draft",
            "version": REPORT_VERSION,
            "model": model_name or "",
            "generation_mode": generation_mode,
            "focus_role_id": report_document.get("focus_role_id") or focus_role_id,
            "title": report_document.get("title") or "职业规划报告",
            "summary": report_document.get("executive_summary") or profile_snapshot.get("summary") or "",
            "confidence": report_document.get("confidence") or "中",
        },
        "profile_snapshot": profile_snapshot,
        "role_rankings": role_candidates,
        "gap_map": gap_map,
        "career_path": career_path,
        "phase_plan": phase_plan,
        "trend_brief": trend_brief,
        "report_document": report_document,
    }

    notify("critic", "正在检查报告一致性与信息完整度")
    bundle = run_critic_agent(bundle)
    bundle["meta"]["status"] = "ready"
    bundle["report_document"]["markdown"] = render_report_markdown(bundle)
    bundle["report_document"]["html"] = render_report_html(bundle)
    return bundle
