from __future__ import annotations

import re
from datetime import datetime
from typing import Any


PORTRAIT_PROMPT_PIPELINE_VERSION = "2026.04-portrait-pipeline-rich-v2"
PORTRAIT_TEMPLATE_VERSION = "2026.04-portrait-dsl-v1"
CAREER_FEEDBACK_VERSION = "2026.04-feedback-memory-v1"


PORTRAIT_REQUIRED_PHRASES = [
    "3:4",
    "单人",
    "半写实",
    "无文字",
    "职业",
]


VERDICT_LABELS = {
    "accurate": "基本准确",
    "partial": "部分准确",
    "off_target": "明显偏差",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _clamp(value: Any, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, _safe_int(value, minimum)))


def _clean_text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _unique_text(values: list[Any] | tuple[Any, ...] | None, limit: int = 6, item_limit: int = 80) -> list[str]:
    if not values:
        return []
    seen = set()
    items: list[str] = []
    for raw in values:
        text = _clean_text(raw, item_limit)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _split_feedback_note(text: str) -> list[str]:
    pieces = re.split(r"[；;。.!？?\n]+", str(text or "").strip())
    return _unique_text(pieces, limit=4, item_limit=72)


def _portrait_narrative_digest(text: Any, limit: int = 420) -> str:
    raw = str(text or "").strip().replace("\n", " ")
    return raw[:limit] if raw else ""


def build_portrait_prompt_layers(context: dict[str, Any], fallback_brief: dict[str, Any] | None) -> dict[str, Any]:
    brief = fallback_brief if isinstance(fallback_brief, dict) else {}
    visual = brief.get("visual_spec") if isinstance(brief.get("visual_spec"), dict) else {}
    id_digest = _portrait_narrative_digest(context.get("identity_narrative"), 380)
    assess_digest = _portrait_narrative_digest(context.get("assessment_prose"), 320)
    ext_digest = _portrait_narrative_digest(context.get("extended_tests_prose"), 320)
    evidence_pool = _unique_text(
        (brief.get("evidence_tags") or [])
        + (context.get("top_roles") or [])
        + (context.get("resume_roles") or [])
        + (context.get("interview_roles") or [])
        + (context.get("work_values") or []),
        limit=8,
        item_limit=40,
    )
    if id_digest:
        evidence_pool = ([id_digest[:96]] + evidence_pool)[:8]
    dsl_template = {
        "persona": f"{context.get('gender') or '未指定'} / {visual.get('subject_age_hint') or '20-26岁'}",
        "role": brief.get("primary_role") or context.get("target_direction") or context.get("archetype_name") or "职业探索者",
        "scene": visual.get("scene") or context.get("archetype_scene") or "现代办公场景",
        "traits": " / ".join(
            _unique_text(
                [
                    context.get("mbti"),
                    context.get("holland"),
                    *(context.get("work_values") or []),
                    *(context.get("axis_traits") or []),
                ],
                limit=4,
                item_limit=32,
            )
        ),
        "narrative_for_image": {
            "identity": id_digest,
            "main_assessment_text": assess_digest,
            "extended_tests": ext_digest,
        },
        "visual": {
            "outfit": visual.get("outfit") or "职业休闲穿搭",
            "props": visual.get("props") or "笔记本、工作记录工具",
            "composition": visual.get("composition") or "3:4 纵向、单人、半身到 2/3 身构图",
        },
        "style": visual.get("style") or "半写实出版物风插画，自然柔光，肤质与衣料纹理清晰",
        "exclude": ["文字", "水印", "多人", "夸张卡通", "海报贴纸感"],
    }
    return {
        "pipeline_version": PORTRAIT_PROMPT_PIPELINE_VERSION,
        "template_version": PORTRAIT_TEMPLATE_VERSION,
        "core_generation": {
            "identity": {
                "title": brief.get("title") or context.get("archetype_name") or "职业人物卡",
                "subtitle": brief.get("subtitle") or context.get("summary") or "",
                "primary_role": brief.get("primary_role") or context.get("target_direction") or "",
                "mission_line": brief.get("mission_line") or "",
            },
            "must_keep": [
                "面向白底产品页面展示",
                "信息克制，不写成长报告",
                "必须可读出主角色与下一步动作",
            ],
        },
        "supplemental_context": {
            "evidence_pool": evidence_pool,
            "work_values": _unique_text(context.get("work_values") or [], limit=4, item_limit=24),
            "support_roles": _unique_text(brief.get("support_roles") or context.get("role_cluster") or [], limit=3, item_limit=24),
            "uncertainty": _unique_text(context.get("uncertainty") or [], limit=3, item_limit=48),
            "identity_narrative_digest": id_digest,
            "assessment_prose_digest": assess_digest,
            "extended_tests_digest": ext_digest,
        },
        "repair_rules": {
            "required_fields": ["title", "subtitle", "primary_role", "mission_line", "evidence_tags", "next_action"],
            "required_visual_terms": PORTRAIT_REQUIRED_PHRASES,
            "render_constraints": [
                "3:4 纵向",
                "单人",
                "半写实职业插画",
                "无文字",
                "适合人物明信片主视觉",
            ],
        },
        "dsl_template": dsl_template,
        "layer_summary": _unique_text(
            [
                f"主角色：{dsl_template['role']}",
                f"场景：{dsl_template['scene']}",
                f"证据：{' / '.join(evidence_pool[:3]) if evidence_pool else '待补'}",
                f"叙事：{id_digest[:72]}…" if len(id_digest) > 72 else (f"叙事：{id_digest}" if id_digest else ""),
                f"视觉：{dsl_template['visual']['composition']}",
            ],
            limit=5,
            item_limit=96,
        ),
    }


def evaluate_portrait_prompt_packet(context: dict[str, Any], packet: dict[str, Any] | None) -> dict[str, Any]:
    payload = packet if isinstance(packet, dict) else {}
    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}
    visual = brief.get("visual_spec") if isinstance(brief.get("visual_spec"), dict) else {}
    prompt_summary = _clean_text(payload.get("prompt_summary"), 240)
    render_prompt = str(payload.get("render_prompt") or "").strip()
    combined_text = " ".join(
        [
            prompt_summary,
            render_prompt,
            _clean_text(brief.get("primary_role"), 64),
            " ".join(_unique_text(brief.get("evidence_tags") or [], limit=4)),
            _clean_text(context.get("identity_narrative"), 240),
            _clean_text(context.get("assessment_prose"), 200),
            _clean_text(context.get("extended_tests_prose"), 200),
        ]
    ).strip()

    field_checks = [
        ("标题", brief.get("title")),
        ("副标题", brief.get("subtitle")),
        ("定位句", brief.get("positioning")),
        ("主角色", brief.get("primary_role")),
        ("任务句", brief.get("mission_line")),
        ("证据标签", brief.get("evidence_tags")),
        ("下一步", brief.get("next_action")),
        ("视觉风格", visual.get("style")),
        ("服装", visual.get("outfit")),
        ("场景", visual.get("scene")),
        ("构图", visual.get("composition")),
        ("配色", visual.get("palette")),
    ]
    filled_fields = 0
    missing_fields: list[str] = []
    for label, value in field_checks:
        ok = bool(value if not isinstance(value, list) else _unique_text(value, limit=1))
        if ok:
            filled_fields += 1
        else:
            missing_fields.append(label)
    completeness = int(round((filled_fields / len(field_checks)) * 100)) if field_checks else 0

    evidence_signals = _unique_text(
        [
            brief.get("primary_role"),
            context.get("target_direction"),
            *(brief.get("evidence_tags") or []),
            *(context.get("top_roles") or []),
            *(context.get("resume_roles") or []),
            *(context.get("interview_roles") or []),
            context.get("mbti"),
            context.get("holland"),
        ],
        limit=10,
        item_limit=32,
    )
    matched_signals = sum(1 for item in evidence_signals if item and item.lower() in combined_text.lower())
    evidence_alignment = int(round((matched_signals / max(1, min(len(evidence_signals), 6))) * 100))

    visual_hits = sum(1 for phrase in PORTRAIT_REQUIRED_PHRASES if phrase.lower() in render_prompt.lower())
    visual_slots = sum(
        1 for item in [visual.get("style"), visual.get("outfit"), visual.get("scene"), visual.get("composition"), visual.get("palette")] if item
    )
    visual_completeness = _clamp((visual_hits * 12) + (visual_slots * 10))

    goal_checks = [
        "白底" in render_prompt or "白底" in prompt_summary,
        "职业" in render_prompt or "岗位" in render_prompt,
        "插画" in render_prompt or "海报" in render_prompt,
        bool(brief.get("risk_note")),
        bool(brief.get("next_action")),
    ]
    goal_alignment = int(round((sum(1 for item in goal_checks if item) / len(goal_checks)) * 100))

    overall = int(round((completeness * 0.35) + (evidence_alignment * 0.25) + (visual_completeness * 0.2) + (goal_alignment * 0.2)))

    improvement_focus = []
    if missing_fields:
        improvement_focus.append(f"补齐字段：{' / '.join(missing_fields[:4])}")
    if evidence_alignment < 70:
        improvement_focus.append("增强岗位与证据标签在摘要和渲染提示词中的一致性")
    if visual_completeness < 80:
        improvement_focus.append("强化 3:4、单人、半写实、无文字等视觉硬约束")
    if goal_alignment < 70:
        improvement_focus.append("明确产品页展示目标、风险提示和下一步动作")

    strengths = []
    if completeness >= 80:
        strengths.append("brief 字段较完整")
    if evidence_alignment >= 70:
        strengths.append("角色判断和证据线索基本一致")
    if visual_completeness >= 80:
        strengths.append("渲染提示词已覆盖核心视觉约束")

    return {
        "pipeline_version": PORTRAIT_PROMPT_PIPELINE_VERSION,
        "template_version": PORTRAIT_TEMPLATE_VERSION,
        "overall_score": overall,
        "needs_refinement": overall < 84 or bool(missing_fields),
        "scores": {
            "brief_completeness": completeness,
            "evidence_alignment": evidence_alignment,
            "visual_completeness": visual_completeness,
            "goal_alignment": goal_alignment,
        },
        "missing_fields": missing_fields,
        "improvement_focus": _unique_text(improvement_focus, limit=4, item_limit=88),
        "strengths": _unique_text(strengths, limit=3, item_limit=64),
    }


def normalize_feedback_memory(raw_feedback: Any, limit: int = 8) -> dict[str, Any]:
    raw = raw_feedback if isinstance(raw_feedback, dict) else {}
    raw_entries = raw.get("entries") if isinstance(raw.get("entries"), list) else []
    entries: list[dict[str, Any]] = []
    for item in raw_entries[-limit:]:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in VERDICT_LABELS:
            verdict = "partial"
        note = _clean_text(item.get("note"), 320)
        created_at = _clean_text(item.get("created_at"), 32) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entries.append(
            {
                "id": _clean_text(item.get("id"), 64) or f"feedback-{len(entries) + 1}",
                "report_id": _clean_text(item.get("report_id"), 64),
                "focus_role_id": _clean_text(item.get("focus_role_id"), 64),
                "focus_role_name": _clean_text(item.get("focus_role_name"), 64),
                "verdict": verdict,
                "verdict_label": VERDICT_LABELS[verdict],
                "note": note,
                "created_at": created_at,
            }
        )

    verdict_counts = {key: 0 for key in VERDICT_LABELS}
    for item in entries:
        verdict_counts[item["verdict"]] += 1

    latest = entries[-1] if entries else {}
    issue_snippets = _unique_text(
        [piece for item in entries if item.get("verdict") != "accurate" for piece in _split_feedback_note(item.get("note"))],
        limit=4,
        item_limit=72,
    )
    keep_signals = _unique_text(
        [piece for item in entries if item.get("verdict") == "accurate" for piece in _split_feedback_note(item.get("note"))],
        limit=3,
        item_limit=72,
    )

    if not entries:
        summary = "暂无用户纠偏反馈。"
    elif latest.get("verdict") == "accurate" and not issue_snippets:
        summary = "最近反馈认为整体方向基本准确，可以延续当前收敛策略。"
    elif issue_snippets:
        summary = f"最近反馈提示需要优先修正：{'；'.join(issue_snippets[:3])}。"
    else:
        summary = f"最近一次反馈为“{latest.get('verdict_label') or '部分准确'}”，建议下一版重新核对关键结论。"

    guidance = issue_snippets or keep_signals
    return {
        "version": CAREER_FEEDBACK_VERSION,
        "count": len(entries),
        "last_updated": latest.get("created_at") or "",
        "latest_verdict": latest.get("verdict") or "",
        "latest_verdict_label": latest.get("verdict_label") or "",
        "latest_note": latest.get("note") or "",
        "summary": summary,
        "verdict_counts": verdict_counts,
        "guidance": guidance,
        "entries": entries,
    }
