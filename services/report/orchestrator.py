"""
Career Report Orchestrator

Implements the 6-agent pipeline from career_pipeline_student_report.md:

  Step A (parallel-friendly):
    Agent 1: 行业分析师     — external trends & labor market
    Agent 3: 简历证据分析官 — resume evidence (first pass, no positioning yet)

  Step B (serial):
    Agent 2: 职业定位顾问   — direction hypotheses (uses industry brief)

  Step B' (optional second pass):
    Agent 3: 简历证据分析官 — re-run with positioning must_prove

  Step C (serial):
    Agent 4: 能力评估官     — employability profile

  Step D (serial):
    Agent 5: 岗位匹配官     — role fit analysis

  Step E (serial):
    Agent 6: 路径规划师     — time-layered career plan

LLM caller is injected from server.py via runtime_llm dict.
Falls back gracefully when no LLM is configured.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from .agents import (
    run_industry_analyst,
    run_career_positioning_advisor,
    run_resume_evidence_analyst,
    run_competency_assessor,
    run_role_match_officer,
    run_career_path_planner,
    LLMCaller,
)
from .schemas import REPORT_VERSION

PIPELINE_VERSION = "2026.04"

StageCallback = Callable[[str, str, str], None]


def _noop_callback(stage_key: str, stage_label: str, detail: str) -> None:
    pass


def _build_llm_caller(runtime_llm: dict[str, Any] | None) -> LLMCaller | None:
    """Build a LLMCaller from the runtime_llm dict provided by server.py."""
    if not isinstance(runtime_llm, dict):
        return None
    caller = runtime_llm.get("caller")
    if callable(caller):
        return caller
    # Legacy writer compatibility
    writer = runtime_llm.get("writer")
    if callable(writer):
        def _wrapped(messages, system_prompt, max_tokens):
            payload = {"messages": messages, "max_tokens": max_tokens}
            return writer(payload, system_prompt) or ""
        return _wrapped
    return None


# ---------------------------------------------------------------------------
# Fallback outputs when LLM is not configured
# ---------------------------------------------------------------------------

def _fallback_industry_brief(profile_payload: dict[str, Any]) -> dict[str, Any]:
    basics = profile_payload.get("basics") or {}
    direction = str(basics.get("targetDirection") or basics.get("target_direction") or "").strip()
    return {
        "markdown": f"（未配置LLM，行业分析跳过。目标方向：{direction or '未知'}）",
        "industry_summary": f"目标方向：{direction or '未提供'}",
        "hot_directions": [],
        "cooling_directions": [],
        "skill_priorities": [],
        "risk_signals": [],
        "verification_actions": [],
        "raw_json": {},
    }


def _fallback_positioning(profile_payload: dict[str, Any], role_payload: list[dict[str, Any]]) -> dict[str, Any]:
    top_roles = [str(r.get("name") or "") for r in role_payload[:3] if isinstance(r, dict)]
    basics = profile_payload.get("basics") or {}
    return {
        "markdown": "（未配置LLM，职业定位跳过）",
        "recommended_tracks": top_roles,
        "hypotheses_for_evidence": [],
        "constraints_hard": [],
        "user_intent_summary": str(basics.get("targetDirection") or basics.get("target_direction") or ""),
        "raw_json": {},
    }


def _fallback_resume_evidence(profile_payload: dict[str, Any]) -> dict[str, Any]:
    resume = profile_payload.get("resume") or {}
    status = str(resume.get("status") or "empty")
    return {
        "markdown": f"（未配置LLM，简历证据分析跳过。简历状态：{status}）",
        "technical_skills": [],
        "general_competencies": [],
        "hypothesis_support": [],
        "gaps": [],
        "raw_json": {},
    }


def _fallback_competency() -> dict[str, Any]:
    return {
        "markdown": "（未配置LLM，能力评估跳过）",
        "dimensions": {},
        "strengths": [],
        "gaps": [],
        "unknowns": [],
        "raw_json": {},
    }


def _fallback_match(role_payload: list[dict[str, Any]]) -> dict[str, Any]:
    top = role_payload[0] if role_payload else {}
    return {
        "markdown": "（未配置LLM，岗位匹配跳过）",
        "target_role": str(top.get("name") or ""),
        "fit_score": int(top.get("overallScore") or 0),
        "fit_band": "not_ready",
        "hard_failures": [],
        "partial_gaps": [],
        "weights_rationale": "",
        "consistency_with_user_tracks": "unknown",
        "raw_json": {},
    }


def _fallback_path_plan() -> dict[str, Any]:
    return {
        "markdown": "（未配置LLM，路径规划跳过）",
        "vision_roles": [],
        "milestones": [],
        "contingency": [],
        "dependencies": {},
        "raw_json": {},
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def generate_career_report_bundle(
    *,
    username: str,
    report_id: str,
    profile_payload: dict[str, Any],
    role_payload: list[dict[str, Any]],
    news_payload: dict[str, Any],
    focus_role_id: str = "",
    stage_callback: StageCallback | None = None,
    runtime_llm: dict[str, Any] | None = None,
    model_name: str = "",
) -> dict[str, Any]:
    """
    Run the 6-agent career report pipeline.
    Returns a bundle dict compatible with the report storage format.
    """
    notify = stage_callback or _noop_callback
    llm_caller = _build_llm_caller(runtime_llm)
    generation_mode = "llm" if llm_caller else "fallback"

    # Get news context for industry analyst
    news_context = ""
    try:
        from services.news.news_kb import get_recent_news_context
        news_context = get_recent_news_context(max_items=15, max_age_days=7)
    except Exception:
        items = news_payload.get("items") or []
        lines = []
        for item in items[:15]:
            title = str(item.get("title") or "")
            summary = str(item.get("summary") or "").strip()
            source = str(item.get("source") or "")
            if title:
                lines.append(f"- {title} [{source}]: {summary}" if summary else f"- {title} [{source}]")
        news_context = "\n".join(lines) if lines else "（无新闻数据）"

    # Sort roles, prioritize focus_role_id
    if focus_role_id:
        role_payload = sorted(
            role_payload,
            key=lambda r: str(r.get("id") or "") != focus_role_id,
        )

    # -------------------------------------------------------------------
    # Step A: 行业分析师 (+ first-pass 简历证据分析官, run in sequence)
    # -------------------------------------------------------------------
    notify("industry_analysis", "行业分析", "正在分析行业趋势与劳动力市场动态...")
    if llm_caller:
        industry_brief = run_industry_analyst(profile_payload, news_context, llm_caller)
    else:
        industry_brief = _fallback_industry_brief(profile_payload)

    notify("resume_evidence", "简历证据解析", "正在解析简历中的能力证据（第一遍）...")
    if llm_caller:
        resume_evidence_pass1 = run_resume_evidence_analyst(profile_payload, None, llm_caller)
    else:
        resume_evidence_pass1 = _fallback_resume_evidence(profile_payload)

    # -------------------------------------------------------------------
    # Step B: 职业定位顾问
    # -------------------------------------------------------------------
    notify("career_positioning", "职业定位", "正在结合测评与意愿生成职业方向假设...")
    if llm_caller:
        positioning_output = run_career_positioning_advisor(profile_payload, industry_brief, llm_caller)
    else:
        positioning_output = _fallback_positioning(profile_payload, role_payload)

    # -------------------------------------------------------------------
    # Step B': 简历证据分析官 — second pass with positioning must_prove
    # -------------------------------------------------------------------
    notify("resume_evidence_2", "证据对齐复核", "正在按照职业方向假设复核简历证据...")
    resume_evidence = resume_evidence_pass1  # default to first pass
    if llm_caller and positioning_output.get("hypotheses_for_evidence"):
        resume_evidence = run_resume_evidence_analyst(profile_payload, positioning_output, llm_caller)

    # -------------------------------------------------------------------
    # Step C: 能力评估官
    # -------------------------------------------------------------------
    notify("competency_assess", "能力评估", "正在构建就业能力画像...")
    if llm_caller:
        competency_profile = run_competency_assessor(
            resume_evidence, positioning_output, profile_payload, llm_caller
        )
    else:
        competency_profile = _fallback_competency()

    # -------------------------------------------------------------------
    # Step D: 岗位匹配官
    # -------------------------------------------------------------------
    notify("role_match", "岗位匹配", "正在比对能力画像与岗位要求...")
    if llm_caller:
        match_output = run_role_match_officer(
            competency_profile, positioning_output, role_payload, industry_brief, llm_caller
        )
    else:
        match_output = _fallback_match(role_payload)

    # -------------------------------------------------------------------
    # Step E: 路径规划师
    # -------------------------------------------------------------------
    notify("path_planning", "路径规划", "正在生成时间分层的职业成长路径...")
    if llm_caller:
        path_plan = run_career_path_planner(
            positioning_output,
            match_output,
            competency_profile,
            industry_brief,
            resume_evidence,
            profile_payload,
            llm_caller,
        )
    else:
        path_plan = _fallback_path_plan()

    # -------------------------------------------------------------------
    # Build report bundle
    # -------------------------------------------------------------------
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    basics = profile_payload.get("basics") or {}
    target_role_name = (
        match_output.get("target_role")
        or (role_payload[0].get("name") if role_payload else "待确定")
    )

    # Combined markdown document
    sections_md = [
        ("## 一、行业分析", industry_brief.get("markdown") or ""),
        ("## 二、职业定位", positioning_output.get("markdown") or ""),
        ("## 三、简历证据分析", resume_evidence.get("markdown") or ""),
        ("## 四、能力评估", competency_profile.get("markdown") or ""),
        ("## 五、岗位匹配分析", match_output.get("markdown") or ""),
        ("## 六、职业路径规划", path_plan.get("markdown") or ""),
    ]
    full_markdown = f"# 职业生涯发展报告\n\n生成时间：{generated_at}\n\n"
    full_markdown += "\n\n---\n\n".join(
        f"{heading}\n\n{content}"
        for heading, content in sections_md
        if content
    )

    bundle = {
        "meta": {
            "report_id": report_id,
            "username": username,
            "generated_at": generated_at,
            "status": "ready",
            "version": REPORT_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "model": model_name or "",
            "generation_mode": generation_mode,
            "focus_role_id": focus_role_id,
            "title": f"{str(basics.get('major') or '')} · {target_role_name} · 职业生涯发展报告",
            "summary": str(
                positioning_output.get("user_intent_summary")
                or industry_brief.get("industry_summary")
                or ""
            ),
            "confidence": _overall_confidence(match_output),
        },
        # Agent outputs
        "industry_brief": industry_brief,
        "positioning_output": positioning_output,
        "resume_evidence": resume_evidence,
        "competency_profile": competency_profile,
        "match_output": match_output,
        "path_plan": path_plan,
        # Legacy-compatible fields
        "profile_snapshot": _build_profile_snapshot(profile_payload, positioning_output, competency_profile),
        "role_rankings": _build_role_rankings(role_payload, match_output),
        "gap_map": _build_gap_map(match_output, competency_profile, resume_evidence),
        "career_path": _build_career_path(path_plan, match_output),
        "phase_plan": _build_phase_plan(path_plan),
        "trend_brief": _build_trend_brief(industry_brief),
        "report_document": {
            "markdown": full_markdown,
            "html": "",
            "title": f"{target_role_name} 职业生涯发展报告",
            "executive_summary": str(positioning_output.get("user_intent_summary") or ""),
            "confidence": _overall_confidence(match_output),
            "focus_role_id": focus_role_id,
            # Modular sections for frontend rendering
            "sections": {
                "industry_analysis": {
                    "label": "行业分析",
                    "icon": "industry",
                    "markdown": industry_brief.get("markdown") or "",
                    "data": {
                        "hot_directions": industry_brief.get("hot_directions") or [],
                        "cooling_directions": industry_brief.get("cooling_directions") or [],
                        "skill_priorities": industry_brief.get("skill_priorities") or [],
                        "risk_signals": industry_brief.get("risk_signals") or [],
                        "industry_summary": industry_brief.get("industry_summary") or "",
                    },
                },
                "career_positioning": {
                    "label": "职业定位",
                    "icon": "positioning",
                    "markdown": positioning_output.get("markdown") or "",
                    "data": {
                        "recommended_tracks": positioning_output.get("recommended_tracks") or [],
                        "hypotheses_for_evidence": positioning_output.get("hypotheses_for_evidence") or [],
                        "constraints_hard": positioning_output.get("constraints_hard") or [],
                        "user_intent_summary": positioning_output.get("user_intent_summary") or "",
                    },
                },
                "resume_evidence": {
                    "label": "简历证据",
                    "icon": "evidence",
                    "markdown": resume_evidence.get("markdown") or "",
                    "data": {
                        "technical_skills": resume_evidence.get("technical_skills") or [],
                        "general_competencies": resume_evidence.get("general_competencies") or [],
                        "hypothesis_support": resume_evidence.get("hypothesis_support") or [],
                        "gaps": resume_evidence.get("gaps") or [],
                    },
                },
                "competency_profile": {
                    "label": "能力评估",
                    "icon": "competency",
                    "markdown": competency_profile.get("markdown") or "",
                    "data": {
                        "dimensions": competency_profile.get("dimensions") or {},
                        "strengths": competency_profile.get("strengths") or [],
                        "gaps": competency_profile.get("gaps") or [],
                        "unknowns": competency_profile.get("unknowns") or [],
                    },
                },
                "role_match": {
                    "label": "岗位匹配",
                    "icon": "match",
                    "markdown": match_output.get("markdown") or "",
                    "data": {
                        "target_role": match_output.get("target_role") or "",
                        "fit_score": match_output.get("fit_score") or 0,
                        "fit_band": match_output.get("fit_band") or "not_ready",
                        "hard_failures": match_output.get("hard_failures") or [],
                        "partial_gaps": match_output.get("partial_gaps") or [],
                    },
                },
                "path_plan": {
                    "label": "路径规划",
                    "icon": "path",
                    "markdown": path_plan.get("markdown") or "",
                    "data": {
                        "vision_roles": path_plan.get("vision_roles") or [],
                        "milestones": path_plan.get("milestones") or [],
                        "contingency": path_plan.get("contingency") or [],
                        "dependencies": path_plan.get("dependencies") or {},
                    },
                },
            },
        },
    }

    return bundle


# ---------------------------------------------------------------------------
# Helpers to build legacy-compatible fields
# ---------------------------------------------------------------------------

def _overall_confidence(match_output: dict[str, Any]) -> str:
    fit_band = str(match_output.get("fit_band") or "not_ready")
    if fit_band == "strong":
        return "高"
    if fit_band == "moderate":
        return "中"
    return "低"


def _build_profile_snapshot(
    profile_payload: dict[str, Any],
    positioning: dict[str, Any],
    competency: dict[str, Any],
) -> dict[str, Any]:
    basics = profile_payload.get("basics") or {}
    assessment = profile_payload.get("assessment") or {}
    mbti = assessment.get("mbti") or {}
    holland = assessment.get("holland") or {}
    strengths = competency.get("strengths") or []
    return {
        "version": REPORT_VERSION,
        "summary": str(positioning.get("user_intent_summary") or ""),
        "core_thesis": str(positioning.get("user_intent_summary") or ""),
        "archetype": {
            "name": "综合发展型",
            "summary": str(positioning.get("user_intent_summary") or ""),
            "tags": positioning.get("recommended_tracks") or [],
            "confidence": "中",
        },
        "interest_profile": {
            "mbti": str(mbti.get("display_type") or mbti.get("final_type") or "待补充"),
            "holland": str(holland.get("code") or "待补充"),
            "recommended_roles": positioning.get("recommended_tracks") or [],
        },
        "capability_vector": _dims_to_vector(competency.get("dimensions") or {}),
        "work_values": profile_payload.get("workValues") or [],
        "basics": basics,
        "missing_items": profile_payload.get("missingItems") or [],
        "evidence_sources": ["LLM多智能体分析"],
        "strengths": strengths,
    }


def _dims_to_vector(dimensions: dict[str, Any]) -> list[dict[str, Any]]:
    label_map = {
        "professional_skills": "专业技能",
        "general_ability": "通用能力",
        "communication_collaboration": "沟通协作",
        "learning_agility": "学习能力",
        "execution": "执行交付",
        "practice_maturity": "实践积累",
    }
    grade_to_score = {"S": 95, "A": 85, "B": 70, "C": 55, "D": 40, "unknown": None}
    result = []
    for key, label in label_map.items():
        dim = dimensions.get(key) or {}
        level = str(dim.get("level") or "unknown")
        score = grade_to_score.get(level)
        result.append({"key": key, "label": label, "score": score, "sources": []})
    return result


def _build_role_rankings(
    role_payload: list[dict[str, Any]], match_output: dict[str, Any]
) -> list[dict[str, Any]]:
    target_role = match_output.get("target_role") or ""
    fit_score = match_output.get("fit_score") or 0
    results = []
    for i, role in enumerate(role_payload[:5]):
        is_target = str(role.get("name") or "") == target_role
        results.append({
            "id": str(role.get("id") or f"role-{i+1}"),
            "name": str(role.get("name") or ""),
            "category": str(role.get("category") or ""),
            "overall_score": fit_score if is_target else int(role.get("overallScore") or 0),
            "confidence": "高" if is_target and fit_score >= 70 else "中",
            "fit_summary": str(role.get("summary") or ""),
            "path": str(role.get("path") or ""),
            "required_skills": list(role.get("requiredSkills") or [])[:6],
        })
    return results


def _build_gap_map(
    match_output: dict[str, Any],
    competency: dict[str, Any],
    resume_evidence: dict[str, Any],
) -> dict[str, Any]:
    gaps = match_output.get("partial_gaps") or []
    hard_failures = match_output.get("hard_failures") or []
    comp_gaps = competency.get("gaps") or []
    return {
        "overview": f"发现 {len(hard_failures)} 个硬门槛缺口，{len(gaps)} 个待补强项。",
        "capability_gaps": [
            {
                "label": g.get("dimension") or str(g.get("id") or ""),
                "status": "需加强",
                "detail": str(g.get("notes") or ""),
            }
            for g in comp_gaps
        ],
        "skill_gaps": [str(f.get("requirement") or f) for f in gaps[:6]],
        "evidence_gaps": [
            str(g.get("claim_in_resume") or "")
            for g in (resume_evidence.get("gaps") or [])[:4]
        ],
        "risk_alerts": list(hard_failures)[:4],
    }


def _build_career_path(path_plan: dict[str, Any], match_output: dict[str, Any]) -> dict[str, Any]:
    milestones = path_plan.get("milestones") or []
    vision = path_plan.get("vision_roles") or []
    return {
        "target_role": match_output.get("target_role") or "",
        "vision_roles": vision,
        "milestones": milestones,
        "stages": [
            {
                "id": m.get("horizon") or f"stage-{i+1}",
                "phase": str(m.get("horizon") or ""),
                "title": str(m.get("title") or ""),
                "actions": list(m.get("actions") or []),
                "metrics": list(m.get("metrics") or []),
            }
            for i, m in enumerate(milestones)
        ],
    }


def _build_phase_plan(path_plan: dict[str, Any]) -> dict[str, Any]:
    milestones = path_plan.get("milestones") or []
    short_term = [
        m for m in milestones
        if "0-3" in str(m.get("horizon") or "") or "3m" in str(m.get("horizon") or "")
    ]
    long_term = [
        m for m in milestones
        if "1-3" in str(m.get("horizon") or "") or "year" in str(m.get("horizon") or "").lower()
    ]
    return {
        "short_term": [
            {
                "id": f"short-{i+1}",
                "phase": str(m.get("horizon") or "短期"),
                "title": str(m.get("title") or ""),
                "tasks": [{"id": f"t-{j}", "text": str(a)} for j, a in enumerate(m.get("actions") or [])],
                "signals": list(m.get("metrics") or []),
            }
            for i, m in enumerate(short_term)
        ],
        "long_term": [
            {
                "id": f"long-{i+1}",
                "phase": str(m.get("horizon") or "长期"),
                "title": str(m.get("title") or ""),
                "tasks": [{"id": f"t-{j}", "text": str(a)} for j, a in enumerate(m.get("actions") or [])],
                "signals": list(m.get("metrics") or []),
            }
            for i, m in enumerate(long_term)
        ],
        "checkpoints": [{"label": "阶段复查", "summary": "定期复盘并更新报告"}],
        "contingency": path_plan.get("contingency") or [],
    }


def _build_trend_brief(industry_brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "overview": str(industry_brief.get("industry_summary") or ""),
        "hot_directions": industry_brief.get("hot_directions") or [],
        "skill_focus": [
            s.get("skill") for s in (industry_brief.get("skill_priorities") or [])
            if isinstance(s, dict)
        ],
        "risk_signals": industry_brief.get("risk_signals") or [],
        "signals": [
            {"type": "机会信号", "text": d.get("name") or str(d)}
            for d in (industry_brief.get("hot_directions") or [])[:3]
        ],
    }
