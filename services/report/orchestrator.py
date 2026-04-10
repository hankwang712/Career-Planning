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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import perf_counter
from typing import Any, Callable

from .agents import (
    CAREER_PIPELINE_PROMPT,
    run_industry_analyst,
    run_career_positioning_advisor,
    run_resume_evidence_analyst,
    run_competency_assessor,
    run_role_match_officer,
    run_career_path_planner,
    LLMCaller,
    PROMPT_SOURCE_MODULE,
)
from .schemas import REPORT_VERSION

PIPELINE_VERSION = "2026.04"

StageCallback = Callable[[str, str, str], None]
LogCallback = Callable[[str], None]


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


def _build_logger(runtime_llm: dict[str, Any] | None) -> Callable[..., None]:
    if isinstance(runtime_llm, dict) and callable(runtime_llm.get("logger")):
        return runtime_llm["logger"]
    return lambda message, **fields: None


def _run_logged_step(logger: Callable[..., None], label: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = perf_counter()
    logger("Agent 开始", agent=label)
    try:
        result = fn()
    except Exception as exc:
        logger("Agent 失败", agent=label, elapsed=f"{perf_counter() - started:.1f}s", error=str(exc)[:160])
        raise
    markdown_chars = len(str((result or {}).get("markdown") or ""))
    logger("Agent 完成", agent=label, elapsed=f"{perf_counter() - started:.1f}s", markdown_chars=markdown_chars)
    return result


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


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _unique_texts(items: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items = value
    elif value in (None, ""):
        items = []
    else:
        items = [value]
    return _unique_texts(items)


def _fit_band_label(fit_band: str) -> str:
    band = _clean_text(fit_band).lower()
    return {
        "strong": "强匹配",
        "moderate": "中等匹配",
        "weak": "弱匹配",
        "not_ready": "尚需准备",
    }.get(band, "尚需准备")


def _normalize_target_role_value(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
        return ""

    text = _clean_text(value)
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        for loader in (
            lambda raw: json.loads(raw),
            lambda raw: json.loads(raw.replace("'", '"')),
        ):
            try:
                parsed = loader(text)
            except Exception:
                continue
            normalized = _normalize_target_role_value(parsed)
            if normalized:
                return normalized
    return text


def _resolve_focus_role_name(
    focus_role_id: str,
    role_payload: list[dict[str, Any]],
    candidate: Any,
) -> str:
    safe_focus_role_id = _clean_text(focus_role_id)
    if safe_focus_role_id:
        for role in role_payload:
            if _clean_text(role.get("id")) == safe_focus_role_id:
                name = _clean_text(role.get("name"))
                if name:
                    return name

    resolved_candidate = _normalize_target_role_value(candidate)
    if resolved_candidate:
        return resolved_candidate

    for role in role_payload:
        name = _clean_text(role.get("name"))
        if name:
            return name
    return ""


def _normalize_hot_directions(bright_spots: Any, raw_json: dict[str, Any]) -> list[dict[str, Any]]:
    confidence = _clean_text(raw_json.get("confidence_level")) or "中"
    analysis_context = raw_json.get("analysis_context") if isinstance(raw_json.get("analysis_context"), dict) else {}
    time_horizon = _clean_text(analysis_context.get("time_frame")) or "近 1-3 年"
    validation_actions = _normalize_text_list(raw_json.get("validation_advice"))
    source = (
        bright_spots if isinstance(bright_spots, list) and bright_spots
        else raw_json.get("trend_signals")
        or raw_json.get("core_trends")
        or []
    )
    result: list[dict[str, Any]] = []
    for item in source:
        if isinstance(item, dict):
            name = _clean_text(item.get("name") or item.get("direction") or item.get("title") or item.get("text"))
            if not name:
                continue
            result.append({
                "name": name,
                "confidence": _clean_text(item.get("confidence")) or confidence,
                "summary": _clean_text(item.get("summary") or item.get("reason") or item.get("note")),
                "source_type": _clean_text(item.get("source_type")) or "行业公开信号 / 用户提供新闻摘要",
                "time_horizon": _clean_text(item.get("time_horizon")) or time_horizon,
                "why_important": _clean_text(item.get("why_it_matters") or item.get("impact") or item.get("reason") or item.get("summary") or item.get("note")),
                "validation_action": _clean_text(item.get("validation_action")) or (validation_actions[0] if validation_actions else ""),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({
                "name": text,
                "confidence": confidence,
                "summary": "",
                "source_type": "行业公开信号 / 用户提供新闻摘要",
                "time_horizon": time_horizon,
                "why_important": text,
                "validation_action": validation_actions[0] if validation_actions else "",
            })
    return result[:6]


def _normalize_skill_priorities(value: Any, raw_json: dict[str, Any]) -> list[dict[str, Any]]:
    analysis_context = raw_json.get("analysis_context") if isinstance(raw_json.get("analysis_context"), dict) else {}
    time_horizon = _clean_text(analysis_context.get("time_frame")) or "近 1-3 年"
    source = value if isinstance(value, list) and value else raw_json.get("skill_priority") or []
    result: list[dict[str, Any]] = []
    for item in source:
        if isinstance(item, dict):
            skill = _clean_text(item.get("skill") or item.get("name") or item.get("title"))
            if not skill:
                continue
            importance = _clean_text(item.get("importance") or item.get("priority")) or "中"
            result.append({
                "skill": skill,
                "importance": importance,
                "reason": _clean_text(item.get("reason") or item.get("summary") or item.get("note")),
                "source_type": _clean_text(item.get("source_type")) or "岗位能力投资建议",
                "time_horizon": _clean_text(item.get("time_horizon")) or time_horizon,
                "priority_reason": _clean_text(item.get("priority_reason") or item.get("reason") or item.get("summary") or item.get("note")),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({
                "skill": text,
                "importance": "中",
                "reason": "",
                "source_type": "岗位能力投资建议",
                "time_horizon": time_horizon,
                "priority_reason": "",
            })
    return result[:8]


def _normalize_hypotheses(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            result.append({
                "track": _clean_text(item.get("track") or item.get("role") or item.get("name")),
                "must_prove": _normalize_text_list(item.get("must_prove") or item.get("items")),
                "reason": _clean_text(item.get("reason") or item.get("summary") or item.get("note")),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({"track": text, "must_prove": [], "reason": ""})
    return [item for item in result if item.get("track")][:6]


def _normalize_resume_items(value: Any, key_name: str, fallback_note_key: str = "note") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            label = _clean_text(item.get(key_name) or item.get("name") or item.get("title"))
            if not label:
                continue
            result.append({
                key_name: label,
                "strength": _clean_text(item.get("strength")) or "unknown",
                "note": _clean_text(item.get(fallback_note_key) or item.get("reason") or item.get("summary")),
                "evidence_ids": list(item.get("evidence_ids") or []),
                "why_counts_as_evidence": _clean_text(item.get("why_counts_as_evidence") or item.get("note") or item.get("reason") or item.get("summary")),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({key_name: text, "strength": "unknown", "note": "", "evidence_ids": [], "why_counts_as_evidence": ""})
    return result


def _normalize_resume_gaps(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            claim = _clean_text(item.get("claim_in_resume") or item.get("claim") or item.get("title") or "简历证据")
            result.append({
                "claim_in_resume": claim,
                "issue": _clean_text(item.get("issue") or item.get("gap_type") or "missing_evidence"),
                "suggestion": _clean_text(item.get("suggestion") or item.get("recommendation") or item.get("note")),
                "why_it_matters": _clean_text(item.get("why_it_matters") or item.get("impact") or item.get("reason")),
                "evidence_hint": _clean_text(item.get("evidence_hint") or item.get("quote_or_fact")),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({
                "claim_in_resume": text,
                "issue": "missing_evidence",
                "suggestion": "",
                "why_it_matters": "",
                "evidence_hint": "",
            })
    return result[:8]


def _normalize_partial_gaps(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            requirement = _clean_text(item.get("requirement") or item.get("title") or item.get("name"))
            if not requirement:
                continue
            result.append({
                "requirement": requirement,
                "gap_id": _clean_text(item.get("gap_id") or item.get("id")),
                "remediation_type": _clean_text(item.get("remediation_type") or item.get("type") or "general"),
                "note": _clean_text(item.get("note") or item.get("summary") or item.get("reason")),
                "reason": _clean_text(item.get("reason") or item.get("note") or item.get("summary")),
                "evidence_basis": _clean_text(item.get("evidence_basis") or item.get("evidence") or item.get("source")),
                "priority_reason": _clean_text(item.get("priority_reason") or item.get("impact") or item.get("why_it_matters")),
            })
            continue
        text = _clean_text(item)
        if text:
            result.append({
                "requirement": text,
                "gap_id": "",
                "remediation_type": "general",
                "note": "",
                "reason": "",
                "evidence_basis": "",
                "priority_reason": "",
            })
    return result[:8]


def _normalize_milestones(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            text = _clean_text(item)
            if text:
                result.append({
                    "horizon": "",
                    "title": text,
                    "actions": [],
                    "metrics": [],
                })
            continue
        result.append({
            "horizon": _clean_text(item.get("horizon") or item.get("phase") or item.get("period")),
            "title": _clean_text(item.get("title") or item.get("goal") or item.get("objective")),
            "actions": _normalize_text_list(item.get("actions") or item.get("tasks")),
            "metrics": _normalize_text_list(item.get("metrics") or item.get("signals") or item.get("outcomes")),
            "reason": _clean_text(item.get("reason") or item.get("why_now") or item.get("summary")),
            "linked_gap": _clean_text(item.get("linked_gap") or item.get("dependency") or item.get("gap_id")),
            "priority_reason": _clean_text(item.get("priority_reason") or item.get("why_first")),
        })
    return result[:8]


def _normalize_industry_brief(industry_brief: dict[str, Any]) -> dict[str, Any]:
    raw_json = industry_brief.get("raw_json") if isinstance(industry_brief.get("raw_json"), dict) else {}
    hot_directions = _normalize_hot_directions(industry_brief.get("hot_directions"), raw_json)
    skill_priorities = _normalize_skill_priorities(industry_brief.get("skill_priorities"), raw_json)
    risk_signals = _normalize_text_list(industry_brief.get("risk_signals") or raw_json.get("major_risk_note"))
    verification_actions = _normalize_text_list(industry_brief.get("verification_actions") or raw_json.get("validation_advice"))
    summary = _clean_text(industry_brief.get("industry_summary"))
    if not summary and hot_directions:
        summary = _clean_text(hot_directions[0].get("name"))
    return {
        **industry_brief,
        "industry_summary": summary,
        "hot_directions": hot_directions,
        "cooling_directions": industry_brief.get("cooling_directions") if isinstance(industry_brief.get("cooling_directions"), list) else [],
        "skill_priorities": skill_priorities,
        "risk_signals": risk_signals[:6],
        "verification_actions": verification_actions[:6],
        "raw_json": raw_json,
    }


def _normalize_positioning_output(positioning_output: dict[str, Any]) -> dict[str, Any]:
    raw_json = positioning_output.get("raw_json") if isinstance(positioning_output.get("raw_json"), dict) else {}
    recommended_tracks = _normalize_text_list(positioning_output.get("recommended_tracks") or raw_json.get("recommended_tracks"))
    hypotheses = _normalize_hypotheses(positioning_output.get("hypotheses_for_evidence") or raw_json.get("hypotheses_for_evidence"))
    constraints = _normalize_text_list(positioning_output.get("constraints_hard") or raw_json.get("constraints_hard"))
    return {
        **positioning_output,
        "recommended_tracks": recommended_tracks[:6],
        "hypotheses_for_evidence": hypotheses,
        "constraints_hard": constraints[:6],
        "user_intent_summary": _clean_text(positioning_output.get("user_intent_summary") or raw_json.get("user_intent_summary")),
        "track_reasons": raw_json.get("track_reasons") if isinstance(raw_json.get("track_reasons"), list) else [],
        "decision_rules": _normalize_text_list(raw_json.get("decision_rules"))[:6],
        "raw_json": raw_json,
    }


def _normalize_resume_evidence_output(resume_evidence: dict[str, Any]) -> dict[str, Any]:
    raw_json = resume_evidence.get("raw_json") if isinstance(resume_evidence.get("raw_json"), dict) else {}
    return {
        **resume_evidence,
        "technical_skills": _normalize_resume_items(
            resume_evidence.get("technical_skills") or raw_json.get("technical_skills"),
            "skill",
        ),
        "general_competencies": _normalize_resume_items(
            resume_evidence.get("general_competencies") or raw_json.get("general_competencies"),
            "competency",
        ),
        "hypothesis_support": resume_evidence.get("hypothesis_support") if isinstance(resume_evidence.get("hypothesis_support"), list) and resume_evidence.get("hypothesis_support") else raw_json.get("hypothesis_support") or [],
        "gaps": _normalize_resume_gaps(resume_evidence.get("gaps") or raw_json.get("gaps")),
        "raw_json": raw_json,
    }


def _normalize_competency_profile(competency_profile: dict[str, Any]) -> dict[str, Any]:
    raw_json = competency_profile.get("raw_json") if isinstance(competency_profile.get("raw_json"), dict) else {}
    return {
        **competency_profile,
        "dimensions": competency_profile.get("dimensions") if isinstance(competency_profile.get("dimensions"), dict) and competency_profile.get("dimensions") else raw_json.get("dimensions") or {},
        "strengths": competency_profile.get("strengths") if isinstance(competency_profile.get("strengths"), list) and competency_profile.get("strengths") else raw_json.get("strengths") or [],
        "gaps": competency_profile.get("gaps") if isinstance(competency_profile.get("gaps"), list) and competency_profile.get("gaps") else raw_json.get("gaps") or [],
        "unknowns": competency_profile.get("unknowns") if isinstance(competency_profile.get("unknowns"), list) and competency_profile.get("unknowns") else raw_json.get("unknowns") or [],
        "raw_json": raw_json,
    }


def _normalize_match_output(match_output: dict[str, Any], role_payload: list[dict[str, Any]]) -> dict[str, Any]:
    raw_json = match_output.get("raw_json") if isinstance(match_output.get("raw_json"), dict) else {}
    target_role = _resolve_focus_role_name("", role_payload, match_output.get("target_role") or raw_json.get("target_role"))
    fit_band = _clean_text(match_output.get("fit_band") or raw_json.get("fit_band") or "not_ready").lower()
    if fit_band not in {"strong", "moderate", "weak", "not_ready"}:
        fit_band = "not_ready"
    fit_score = int(match_output.get("fit_score") or raw_json.get("fit_score") or 0)
    fit_score = max(0, min(100, fit_score))
    return {
        **match_output,
        "target_role": target_role,
        "fit_score": fit_score,
        "fit_band": fit_band,
        "hard_failures": _normalize_text_list(match_output.get("hard_failures") or raw_json.get("hard_failures"))[:6],
        "partial_gaps": _normalize_partial_gaps(match_output.get("partial_gaps") or raw_json.get("partial_gaps")),
        "weights_rationale": _clean_text(match_output.get("weights_rationale") or raw_json.get("weights_rationale")),
        "consistency_with_user_tracks": _clean_text(match_output.get("consistency_with_user_tracks") or raw_json.get("consistency_with_user_tracks")),
        "why_match": _normalize_text_list(match_output.get("why_match") or raw_json.get("why_match"))[:6],
        "why_not_yet": _normalize_text_list(match_output.get("why_not_yet") or raw_json.get("why_not_yet"))[:6],
        "raw_json": raw_json,
    }


def _normalize_path_plan(path_plan: dict[str, Any]) -> dict[str, Any]:
    raw_json = path_plan.get("raw_json") if isinstance(path_plan.get("raw_json"), dict) else {}
    return {
        **path_plan,
        "vision_roles": _normalize_text_list(path_plan.get("vision_roles") or raw_json.get("vision_roles"))[:5],
        "milestones": _normalize_milestones(path_plan.get("milestones") or raw_json.get("milestones")),
        "contingency": _normalize_text_list(path_plan.get("contingency") or raw_json.get("contingency"))[:6],
        "dependencies": path_plan.get("dependencies") if isinstance(path_plan.get("dependencies"), dict) and path_plan.get("dependencies") else raw_json.get("dependencies") or {},
        "path_rationale": _normalize_text_list(path_plan.get("path_rationale") or raw_json.get("path_rationale"))[:6],
        "path_risks": _normalize_text_list(path_plan.get("path_risks") or raw_json.get("path_risks"))[:6],
        "raw_json": raw_json,
    }


def _format_evidence_ids(value: Any) -> str:
    ids = [str(item).strip() for item in (value if isinstance(value, list) else []) if str(item).strip()]
    return "、".join(ids[:4])


def _issue_label(issue: str) -> str:
    mapping = {
        "no_evidence_provided": "未提供原始经历",
        "missing_evidence": "缺少可回溯证据",
        "no_metrics": "缺少量化结果",
        "unclear_role": "角色贡献不清",
        "unverifiable": "缺少可验证痕迹",
    }
    safe_issue = _clean_text(issue)
    return mapping.get(safe_issue, safe_issue or "待补充")


def _strength_label(strength: str) -> str:
    mapping = {
        "strong": "强证据",
        "medium": "中等证据",
        "weak": "弱证据",
        "unknown": "待确认",
    }
    safe_strength = _clean_text(strength).lower()
    return mapping.get(safe_strength, safe_strength or "待确认")


def _dimension_label(key: str) -> str:
    mapping = {
        "professional_skills": "专业技能",
        "general_ability": "通用能力",
        "communication_collaboration": "沟通协作",
        "learning_agility": "学习力",
        "execution": "执行力",
        "practice_maturity": "实践力",
    }
    safe_key = _clean_text(key)
    return mapping.get(safe_key, safe_key or "能力维度")


def _find_track_hypothesis(positioning_output: dict[str, Any], focus_role_name: str) -> dict[str, Any]:
    focus = _clean_text(focus_role_name)
    hypotheses = positioning_output.get("hypotheses_for_evidence") or []
    for item in hypotheses:
        if not isinstance(item, dict):
            continue
        track = _clean_text(item.get("track"))
        if focus and track and (focus in track or track in focus):
            return item
    return hypotheses[0] if hypotheses and isinstance(hypotheses[0], dict) else {}


def _build_industry_explainability(industry_brief: dict[str, Any]) -> dict[str, Any]:
    hot_directions = industry_brief.get("hot_directions") or []
    skill_priorities = industry_brief.get("skill_priorities") or []
    top_direction = hot_directions[0] if hot_directions and isinstance(hot_directions[0], dict) else {}
    top_skill = skill_priorities[0] if skill_priorities and isinstance(skill_priorities[0], dict) else {}
    judgement = (
        _clean_text(industry_brief.get("industry_summary"))
        or _clean_text(top_direction.get("name"))
        or "行业趋势判断待补充"
    )
    because = _unique_texts(
        [
            _clean_text(top_direction.get("why_important") or top_direction.get("summary")),
            _clean_text(top_skill.get("reason") or top_skill.get("priority_reason")),
            *(_normalize_text_list(industry_brief.get("risk_signals"))[:1]),
        ]
    )[:4]
    evidence = _unique_texts(
        [
            "来源类型：{}".format(_clean_text(top_direction.get("source_type"))) if _clean_text(top_direction.get("source_type")) else "",
            "时效范围：{}".format(_clean_text(top_direction.get("time_horizon"))) if _clean_text(top_direction.get("time_horizon")) else "",
            "能力投资依据：{}".format(_clean_text(top_skill.get("reason"))) if _clean_text(top_skill.get("reason")) else "",
        ]
    )[:4]
    validate = _unique_texts(
        [
            _clean_text(top_direction.get("validation_action")),
            *(_normalize_text_list(industry_brief.get("verification_actions"))[:3]),
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_positioning_explainability(
    positioning_output: dict[str, Any],
    focus_role_name: str,
) -> dict[str, Any]:
    recommended_tracks = _normalize_text_list(positioning_output.get("recommended_tracks"))
    focus_hypothesis = _find_track_hypothesis(positioning_output, focus_role_name)
    must_prove = _normalize_text_list(focus_hypothesis.get("must_prove"))
    primary_track = recommended_tracks[0] if recommended_tracks else _clean_text(focus_role_name)
    judgement = f"当前优先探索方向是 {primary_track or '待识别方向'}。"
    because = _unique_texts(
        [
            _clean_text(positioning_output.get("user_intent_summary")),
            _clean_text(focus_hypothesis.get("reason")),
            "主推荐方向需要先证明：{}".format("、".join(must_prove[:2])) if must_prove else "",
        ]
    )[:4]
    evidence = _unique_texts(
        [
            "推荐序列：{}".format("、".join(recommended_tracks[:3])) if recommended_tracks else "",
            "硬约束：{}".format("、".join(_normalize_text_list(positioning_output.get("constraints_hard"))[:3])) if positioning_output.get("constraints_hard") else "",
            "排序调整规则：{}".format("；".join(_normalize_text_list(positioning_output.get("decision_rules"))[:2])) if positioning_output.get("decision_rules") else "",
        ]
    )[:4]
    validate = _unique_texts(
        [
            "回到简历验证：{}".format(item) for item in must_prove[:3]
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_resume_explainability(resume_evidence: dict[str, Any]) -> dict[str, Any]:
    gaps = resume_evidence.get("gaps") or []
    technical = resume_evidence.get("technical_skills") or []
    first_gap = gaps[0] if gaps and isinstance(gaps[0], dict) else {}
    first_skill = technical[0] if technical and isinstance(technical[0], dict) else {}
    evidence_ids = _format_evidence_ids(first_skill.get("evidence_ids"))
    if gaps:
        judgement = "当前简历证据链不完整，部分关键判断仍缺少可回溯经历。"
    else:
        judgement = "当前简历证据链可支撑主要职业判断。"
    because = _unique_texts(
        [
            _clean_text(first_skill.get("note") or first_skill.get("why_counts_as_evidence")),
            _clean_text(first_gap.get("why_it_matters") or first_gap.get("suggestion")),
        ]
    )[:4]
    evidence = _unique_texts(
        [
            "{}：{}".format(_clean_text(first_skill.get("skill")), evidence_ids or _strength_label(first_skill.get("strength")))
            if _clean_text(first_skill.get("skill")) else "",
            "{}：{}".format(_clean_text(first_gap.get("claim_in_resume")), _issue_label(first_gap.get("issue")))
            if _clean_text(first_gap.get("claim_in_resume")) else "",
        ]
    )[:4]
    validate = _unique_texts(
        [
            _clean_text(first_gap.get("suggestion")),
            "补充证据 ID 对应的项目结果与量化指标" if not evidence_ids else "",
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_competency_explainability(competency_profile: dict[str, Any]) -> dict[str, Any]:
    dimensions = competency_profile.get("dimensions") or {}
    strengths = _normalize_text_list(competency_profile.get("strengths"))
    gaps = competency_profile.get("gaps") or []
    important_dims = []
    for key, payload in dimensions.items():
        if not isinstance(payload, dict):
            continue
        level = _clean_text(payload.get("level")).upper()
        if level and level != "UNKNOWN":
            important_dims.append(f"{_dimension_label(key)}：{level}（{_clean_text(payload.get('confidence')) or '低'}置信）")
    first_gap = gaps[0] if gaps and isinstance(gaps[0], dict) else {}
    judgement = "能力画像以证据支持强度为主，不把自评直接当结论。"
    because = _unique_texts([*strengths[:2], _clean_text(first_gap.get("notes"))])[:4]
    evidence = _unique_texts(important_dims[:4])
    validate = _unique_texts(
        [
            "补齐未知维度对应的项目/实习证据" if competency_profile.get("unknowns") else "",
            "优先补齐：{}".format(_dimension_label(first_gap.get("dimension"))) if _clean_text(first_gap.get("dimension")) else "",
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_match_explainability(
    match_output: dict[str, Any],
    resume_evidence: dict[str, Any],
) -> dict[str, Any]:
    fit_score = int(match_output.get("fit_score") or 0)
    fit_band_label = _fit_band_label(match_output.get("fit_band") or "not_ready")
    hard_failures = _normalize_text_list(match_output.get("hard_failures"))[:3]
    partial_gaps = match_output.get("partial_gaps") or []
    first_gap = partial_gaps[0] if partial_gaps and isinstance(partial_gaps[0], dict) else {}
    resume_gaps = resume_evidence.get("gaps") or []
    first_resume_gap = resume_gaps[0] if resume_gaps and isinstance(resume_gaps[0], dict) else {}
    judgement = f"当前目标岗位匹配结果为 {fit_band_label}（{fit_score}%）。"
    because = _unique_texts(
        [
            _clean_text(match_output.get("weights_rationale")),
            *(_normalize_text_list(match_output.get("why_match"))[:2]),
            *hard_failures[:2],
            _clean_text(first_gap.get("reason") or first_gap.get("note")),
        ]
    )[:4]
    evidence = _unique_texts(
        [
            "待补强：{}".format(_clean_text(first_gap.get("requirement"))) if _clean_text(first_gap.get("requirement")) else "",
            "依据：{}".format(_clean_text(first_gap.get("evidence_basis"))) if _clean_text(first_gap.get("evidence_basis")) else "",
            "简历缺口：{}".format(_clean_text(first_resume_gap.get("claim_in_resume"))) if _clean_text(first_resume_gap.get("claim_in_resume")) else "",
        ]
    )[:4]
    validate = _unique_texts(
        [
            "优先补齐：{}".format(_clean_text(first_gap.get("requirement"))) if _clean_text(first_gap.get("requirement")) else "",
            _clean_text(first_resume_gap.get("suggestion")),
            *(_normalize_text_list(match_output.get("why_not_yet"))[:1]),
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_path_explainability(
    path_plan: dict[str, Any],
    match_output: dict[str, Any],
) -> dict[str, Any]:
    milestones = path_plan.get("milestones") or []
    first_milestone = milestones[0] if milestones and isinstance(milestones[0], dict) else {}
    target_role = _clean_text(match_output.get("target_role"))
    judgement = f"路径规划默认围绕 {target_role or '主岗位'} 展开，并按短中长期拆解。"
    because = _unique_texts(
        [
            *(_normalize_text_list(path_plan.get("path_rationale"))[:2]),
            _clean_text(first_milestone.get("reason")),
            "先解决硬门槛，再进入投递和升级路径" if match_output.get("hard_failures") else "",
            "主路径与岗位匹配结果保持一致" if target_role else "",
        ]
    )[:4]
    evidence = _unique_texts(
        [
            "首个阶段：{}".format(_clean_text(first_milestone.get("title"))) if _clean_text(first_milestone.get("title")) else "",
            "关联缺口：{}".format(_clean_text(first_milestone.get("linked_gap"))) if _clean_text(first_milestone.get("linked_gap")) else "",
            "必须先解决：{}".format("、".join(_normalize_text_list((path_plan.get("dependencies") or {}).get("must_resolve_hard_failures"))[:3]))
            if (path_plan.get("dependencies") or {}).get("must_resolve_hard_failures") else "",
        ]
    )[:4]
    validate = _unique_texts(
        [
            *(_normalize_text_list(first_milestone.get("metrics"))[:2]),
            *(_normalize_text_list(path_plan.get("contingency"))[:2]),
            *(_normalize_text_list(path_plan.get("path_risks"))[:1]),
        ]
    )[:4]
    return {
        "judgement": judgement,
        "because": because,
        "evidence": evidence,
        "validate": validate,
    }


def _build_dashboard_summary(
    focus_role_name: str,
    match_output: dict[str, Any],
    positioning_output: dict[str, Any],
    gap_map: dict[str, Any],
    resume_evidence: dict[str, Any],
    industry_brief: dict[str, Any],
) -> dict[str, Any]:
    fit_score = int(match_output.get("fit_score") or 0)
    fit_band = _clean_text(match_output.get("fit_band") or "not_ready").lower()
    fit_band_label = _fit_band_label(fit_band)
    recommended_tracks = _normalize_text_list(positioning_output.get("recommended_tracks"))[:3]
    risk_alerts = _normalize_text_list(gap_map.get("risk_alerts"))[:3]
    hard_failures = _normalize_text_list(match_output.get("hard_failures"))[:3]
    evidence_gaps = _normalize_text_list(gap_map.get("evidence_gaps"))[:3]
    focus_hypothesis = _find_track_hypothesis(positioning_output, focus_role_name)
    must_prove = _normalize_text_list(focus_hypothesis.get("must_prove"))[:3]
    hot_direction = (industry_brief.get("hot_directions") or [{}])[0] if industry_brief.get("hot_directions") else {}
    if fit_band == "strong":
        headline = f"当前最值得优先冲刺的方向是 {focus_role_name}。"
    elif fit_band == "moderate":
        headline = f"{focus_role_name} 可以作为主线推进，但要先补齐关键能力和证据缺口。"
    else:
        headline = f"现阶段不建议直接冲刺 {focus_role_name}，先补证据与硬门槛更稳。"
    recommend_summary = _clean_text(positioning_output.get("user_intent_summary")) or f"优先围绕 {focus_role_name} 组织你的求职主线。"
    partial_gap_items = [
        _clean_text(item.get("requirement") or item.get("title"))
        for item in (match_output.get("partial_gaps") or [])
        if isinstance(item, dict)
    ]
    observe_items = recommended_tracks[1:] or _unique_texts(partial_gap_items)[:2]
    defer_items = hard_failures or risk_alerts
    headline_because = _unique_texts(
        [
            f"岗位匹配结果为 {fit_band_label}（{fit_score}%）",
            "职业定位把该方向放在推荐序列前列" if recommended_tracks else "",
            "当前简历仍缺少：{}".format("、".join(evidence_gaps[:2])) if evidence_gaps else "",
            "行业侧仍在升温：{}".format(_clean_text(hot_direction.get("name"))) if _clean_text(hot_direction.get("name")) else "",
        ]
    )[:4]
    confidence_sources = _unique_texts(
        [
            _clean_text(match_output.get("weights_rationale")),
            "职业定位依据：{}".format(_clean_text(positioning_output.get("user_intent_summary"))) if positioning_output.get("user_intent_summary") else "",
            "简历证据状态：{}".format("存在待补证据项" if resume_evidence.get("gaps") else "当前证据链较完整"),
        ]
    )[:4]
    return {
        "headline": headline,
        "headline_because": headline_because,
        "focus_role_name": focus_role_name,
        "fit_score": fit_score,
        "fit_band": fit_band,
        "fit_band_label": fit_band_label,
        "rationale": _clean_text(match_output.get("weights_rationale")) or recommend_summary,
        "confidence_sources": confidence_sources,
        "decision_cards": [
            {
                "key": "recommend",
                "label": "推荐方向",
                "tone": "positive",
                "title": focus_role_name,
                "summary": recommend_summary,
                "items": [focus_role_name, *recommended_tracks[1:2]] if focus_role_name else recommended_tracks[:2],
                "because": _unique_texts(
                    [
                        f"当前目标岗位匹配为 {fit_band_label}",
                        "职业定位中的主推荐方向与当前主岗位一致" if focus_role_name and focus_role_name in "".join(recommended_tracks) else "",
                        _clean_text(match_output.get("weights_rationale")),
                    ]
                )[:3],
                "evidence": _unique_texts(must_prove[:3]),
                "validate": _unique_texts(
                    [
                        f"回到简历核对是否能证明：{item}" for item in must_prove[:2]
                    ]
                )[:3],
            },
            {
                "key": "observe",
                "label": "保留观察",
                "tone": "neutral",
                "title": "次选方向",
                "summary": "这些方向可以保留关注，但不应分散当前的主线投入。",
                "items": observe_items[:3],
                "because": _unique_texts(
                    [
                        "和当前兴趣或岗位族有交集",
                        "但当前证据和匹配度仍不如主线集中",
                        "可以作为主线受阻时的平行探索",
                    ]
                )[:3],
                "evidence": _unique_texts(observe_items[:3]),
                "validate": _unique_texts(
                    [f"仅在完成主线补强后再验证：{item}" for item in observe_items[:2]]
                )[:3],
            },
            {
                "key": "defer",
                "label": "暂不建议",
                "tone": "risk",
                "title": "先不要直接投递",
                "summary": "下面这些问题如果不先补齐，会直接影响投递反馈和面试通过率。",
                "items": defer_items[:3],
                "because": _unique_texts(
                    [
                        "这些问题属于硬门槛或明显风险",
                        "如果不先解决，会直接拉低岗位匹配判断",
                    ]
                )[:3],
                "evidence": _unique_texts([*hard_failures[:2], *evidence_gaps[:2]])[:3],
                "validate": _unique_texts(
                    [
                        "优先把这些问题转成可验证的项目、指标或材料",
                        *[
                            _clean_text(item.get("suggestion"))
                            for item in (resume_evidence.get("gaps") or [])
                            if isinstance(item, dict) and _clean_text(item.get("suggestion"))
                        ][:2],
                    ]
                )[:3],
            },
        ],
    }


def _build_next_actions(
    phase_plan: dict[str, Any],
    match_output: dict[str, Any],
    gap_map: dict[str, Any],
) -> dict[str, Any]:
    short_term = phase_plan.get("short_term") or []
    first_phase = short_term[0] if short_term else {}
    first_tasks = [str(task.get("text") or task.get("title") or "").strip() for task in (first_phase.get("tasks") or [])]
    first_tasks = [item for item in first_tasks if item]
    checkpoints = []
    for item in phase_plan.get("checkpoints") or []:
        label = _clean_text(item.get("label") or item.get("title"))
        summary = _clean_text(item.get("summary") or item.get("detail"))
        if label or summary:
            checkpoints.append({"label": label or "复查节点", "summary": summary})
    contingency = _normalize_text_list(phase_plan.get("contingency"))
    drivers = _unique_texts(
        [
            *(_normalize_text_list(match_output.get("hard_failures"))[:2]),
            *(_normalize_text_list(gap_map.get("skill_gaps"))[:2]),
            *(_normalize_text_list(gap_map.get("evidence_gaps"))[:2]),
        ]
    )
    action_items = []
    for index, task in enumerate(first_tasks[:4]):
        driver = drivers[index] if index < len(drivers) else ""
        action_items.append(
            {
                "title": task,
                "window": "本周" if index < 2 else "30 天",
                "reason": f"对应前面判断的“{driver}”" if driver else "用于补齐当前主线岗位的可验证成果。",
                "linked_judgement": driver,
                "priority_reason": (
                    "因为它直接影响当前目标岗位的硬门槛或首轮筛选。"
                    if index == 0 and _normalize_text_list(match_output.get("hard_failures"))
                    else "因为它能最快把模糊判断转成可验证证据。"
                ),
                "validate": checkpoints[0]["summary"] if checkpoints else "",
            }
        )
    return {
        "this_week": first_tasks[:2],
        "next_30_days": {
            "title": _clean_text(first_phase.get("title") or first_phase.get("phase") or "短期推进"),
            "tasks": first_tasks[:4],
            "signals": _normalize_text_list(first_phase.get("signals"))[:3],
        },
        "plan_b": contingency[0] if contingency else "",
        "priority_logic": _unique_texts(
            [
                "先处理硬门槛，再处理证据缺口，最后扩展备选路径。"
                if _normalize_text_list(match_output.get("hard_failures"))
                else "先补能最快提升说服力的证据，再扩展长期路径。",
                "优先级高的动作优先对应主岗位门槛和面试可追问项。",
            ]
        )[:3],
        "action_items": action_items,
        "checkpoints": checkpoints[:3],
        "contingency": contingency[:3],
    }


def _build_evidence_health(
    gap_map: dict[str, Any],
    profile_snapshot: dict[str, Any],
    resume_evidence: dict[str, Any],
) -> dict[str, Any]:
    hard_failures = _normalize_text_list(gap_map.get("risk_alerts"))[:4]
    skill_gaps = _normalize_text_list(gap_map.get("skill_gaps"))[:4]
    evidence_gaps = _normalize_text_list(gap_map.get("evidence_gaps"))[:4]
    missing_inputs = _normalize_text_list(profile_snapshot.get("missing_items"))[:4]
    strengths: list[str] = []
    for item in profile_snapshot.get("strengths") or []:
        if isinstance(item, dict):
            strengths.extend(_normalize_text_list([item.get("name"), item.get("title"), item.get("summary")]))
        else:
            strengths.extend(_normalize_text_list([item]))
    if hard_failures:
        summary = "当前证据健康度偏弱，存在会直接影响投递的硬门槛缺口。"
    elif evidence_gaps or missing_inputs:
        summary = "当前证据覆盖不完整，建议优先补项目结果、量化成果和缺失输入。"
    else:
        summary = "当前证据链基本完整，可以进入更具体的岗位优化与投递验证。"
    trace_items = []
    for item in (resume_evidence.get("technical_skills") or [])[:3]:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("skill"))
        if not label:
            continue
        evidence_ids = _format_evidence_ids(item.get("evidence_ids"))
        trace_items.append(
            {
                "label": label,
                "status": "已识别证据" if evidence_ids else "待补证据",
                "because": _clean_text(item.get("why_counts_as_evidence") or item.get("note"))
                or ("当前未提供可回溯经历。" if not evidence_ids else ""),
                "evidence": f"证据 ID：{evidence_ids}" if evidence_ids else "未发现明确证据 ID",
                "validate": "补充项目结果、角色贡献和量化指标" if not evidence_ids else "回看原经历，确认这条证据是否能支撑目标岗位追问",
            }
        )
    for item in (resume_evidence.get("general_competencies") or [])[:2]:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("competency"))
        if not label:
            continue
        evidence_ids = _format_evidence_ids(item.get("evidence_ids"))
        trace_items.append(
            {
                "label": label,
                "status": "已识别证据" if evidence_ids else "待补证据",
                "because": _clean_text(item.get("why_counts_as_evidence") or item.get("note"))
                or ("当前未提供可回溯经历。" if not evidence_ids else ""),
                "evidence": f"证据 ID：{evidence_ids}" if evidence_ids else "未发现明确证据 ID",
                "validate": "补充可验证场景、跨角色协作过程或结果" if not evidence_ids else "确认面试时能否讲出具体案例",
            }
        )
    return {
        "summary": summary,
        "hard_failures": hard_failures,
        "skill_gaps": skill_gaps,
        "evidence_gaps": evidence_gaps,
        "missing_inputs": missing_inputs,
        "strengths": _unique_texts(strengths)[:4],
        "evidence_trace": trace_items[:5],
    }


def _build_market_signals(trend_brief: dict[str, Any], industry_brief: dict[str, Any]) -> dict[str, Any]:
    hot_directions = industry_brief.get("hot_directions") or []
    skill_priorities = industry_brief.get("skill_priorities") or []
    return {
        "overview": _clean_text(trend_brief.get("overview") or industry_brief.get("industry_summary")),
        "hot_directions": hot_directions[:4],
        "skill_priorities": skill_priorities[:5],
        "risk_signals": _normalize_text_list(trend_brief.get("risk_signals") or industry_brief.get("risk_signals"))[:4],
        "verification_actions": _normalize_text_list(trend_brief.get("verification_actions") or industry_brief.get("verification_actions"))[:4],
        "signal_cards": [
            {
                "title": _clean_text(item.get("name") or item.get("skill")),
                "summary": _clean_text(item.get("why_important") or item.get("reason") or item.get("summary")),
                "source_type": _clean_text(item.get("source_type")),
                "time_horizon": _clean_text(item.get("time_horizon")),
                "validate": _clean_text(item.get("validation_action") or item.get("priority_reason")),
            }
            for item in [*hot_directions[:2], *skill_priorities[:2]]
            if isinstance(item, dict) and _clean_text(item.get("name") or item.get("skill"))
        ],
    }


def _build_industry_story(industry_brief: dict[str, Any], news_payload: dict[str, Any]) -> dict[str, Any]:
    story = _clean_text(industry_brief.get("industry_summary"))
    snapshot_label = _clean_text(news_payload.get("snapshot_label") or news_payload.get("window_snapshot_label"))
    refresh_rule = _clean_text(news_payload.get("refresh_rule"))
    highlights = []
    for item in (news_payload.get("items") if isinstance(news_payload.get("items"), list) else [])[:4]:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        if not title:
            continue
        highlights.append(
            {
                "title": title,
                "source": _clean_text(item.get("source")),
                "published_label": _clean_text(item.get("published_label") or item.get("published_at")),
                "summary": _clean_text(item.get("summary")),
                "topic": _clean_text(item.get("topic")),
            }
        )
    return {
        "narrative": story,
        "snapshot_label": snapshot_label,
        "refresh_rule": refresh_rule,
        "highlight_items": highlights,
    }


def _build_role_cards(
    role_payload: list[dict[str, Any]],
    match_output: dict[str, Any],
    resume_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    target_role = _clean_text(match_output.get("target_role"))
    strengths = []
    for item in (resume_evidence.get("technical_skills") or [])[:3]:
        if isinstance(item, dict):
            label = _clean_text(item.get("skill") or item.get("name"))
        else:
            label = _clean_text(item)
        if label:
            strengths.append(label)
    for item in (resume_evidence.get("general_competencies") or [])[:2]:
        if isinstance(item, dict):
            label = _clean_text(item.get("name") or item.get("skill"))
        else:
            label = _clean_text(item)
        if label:
            strengths.append(label)
    strengths = _unique_texts(strengths)[:4]
    hard_failures = []
    for item in (match_output.get("hard_failures") or [])[:4]:
        if isinstance(item, dict):
            label = _clean_text(item.get("requirement") or item.get("gap") or item.get("title"))
        else:
            label = _clean_text(item)
        if label:
            hard_failures.append(label)
    partial_gaps = []
    for item in (match_output.get("partial_gaps") or [])[:4]:
        if isinstance(item, dict):
            label = _clean_text(item.get("requirement") or item.get("gap") or item.get("title"))
        else:
            label = _clean_text(item)
        if label:
            partial_gaps.append(label)
    hard_failures = _unique_texts(hard_failures)[:4]
    partial_gaps = _unique_texts(partial_gaps)[:4]
    cards = []
    for index, role in enumerate(role_payload[:3]):
        if not isinstance(role, dict):
            continue
        name = _clean_text(role.get("name"))
        if not name:
            continue
        is_target = name == target_role or (not target_role and index == 0)
        fit_score = int(match_output.get("fit_score") or 0) if is_target else int(role.get("overallScore") or role.get("overall_score") or 0)
        cards.append(
            {
                "role_name": name,
                "fit_score": max(0, min(100, fit_score)),
                "fit_band": _clean_text(match_output.get("fit_band") if is_target else ""),
                "why_fit": _unique_texts((match_output.get("why_match") or []) if is_target else [_clean_text(role.get("summary"))])[:3],
                "strengths": strengths,
                "hard_gaps": hard_failures if is_target else [],
                "partial_gaps": partial_gaps if is_target else [
                    item for item in (_normalize_text_list(role.get("requiredSkills"))[:4]) if item
                ],
                "switch_path": _clean_text(role.get("path")),
                "promotion_path": _clean_text(role.get("careerPath") or role.get("path")),
                "required_skills": _normalize_text_list(role.get("requiredSkills"))[:6],
                "fit_summary": _clean_text(role.get("summary")),
            }
        )
    return cards


def _build_path_graph(career_path: dict[str, Any], path_plan: dict[str, Any], focus_role_name: str) -> dict[str, Any]:
    nodes = [
        {
            "id": "current",
            "phase": "当前",
            "title": focus_role_name or _clean_text(career_path.get("target_role")) or "当前主线",
            "summary": "当前优先围绕主推荐岗位补硬门槛和证据缺口。",
        }
    ]
    for index, item in enumerate(career_path.get("stages") or []):
        if not isinstance(item, dict):
            continue
        nodes.append(
            {
                "id": _clean_text(item.get("id")) or f"stage-{index + 1}",
                "phase": _clean_text(item.get("phase")) or f"阶段 {index + 1}",
                "title": _clean_text(item.get("title")) or f"阶段 {index + 1}",
                "summary": _clean_text("；".join(_normalize_text_list(item.get("actions"))[:2])),
                "metrics": _normalize_text_list(item.get("metrics"))[:3],
            }
        )
    return {
        "target_role": _clean_text(career_path.get("target_role")) or focus_role_name,
        "nodes": nodes,
        "contingency": _normalize_text_list(path_plan.get("contingency"))[:3],
    }


def _build_plan_board(phase_plan: dict[str, Any], next_actions: dict[str, Any]) -> dict[str, Any]:
    horizons = []
    for key, label in (("short_term", "短期"), ("mid_term", "中期"), ("long_term", "长期")):
        items = phase_plan.get(key) if isinstance(phase_plan.get(key), list) else []
        horizons.append(
            {
                "key": key,
                "label": label,
                "items": items,
            }
        )
    return {
        "horizons": horizons,
        "action_items": next_actions.get("action_items") if isinstance(next_actions.get("action_items"), list) else [],
        "checkpoints": next_actions.get("checkpoints") if isinstance(next_actions.get("checkpoints"), list) else [],
        "plan_b": _clean_text(next_actions.get("plan_b")),
        "priority_logic": _normalize_text_list(next_actions.get("priority_logic"))[:4],
    }


def _build_explainability_summary(
    dashboard_summary: dict[str, Any],
    evidence_health: dict[str, Any],
    market_signals: dict[str, Any],
) -> dict[str, Any]:
    return {
        "headline_because": _normalize_text_list(dashboard_summary.get("headline_because"))[:4],
        "evidence_trace": evidence_health.get("evidence_trace") if isinstance(evidence_health.get("evidence_trace"), list) else [],
        "signal_cards": market_signals.get("signal_cards") if isinstance(market_signals.get("signal_cards"), list) else [],
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
    logger = _build_logger(runtime_llm)
    generation_mode = "llm" if llm_caller else "fallback"
    pipeline_started = perf_counter()
    shared_pool: dict[str, Any] = {
        "inputs": {
            "profile": profile_payload,
            "roles": role_payload,
            "focus_role_id": focus_role_id,
        },
        "outputs": {},
        "diagnostics": {
            "mode": generation_mode,
            "events": [],
        },
    }
    logger("编排开始", mode=generation_mode, roles=len(role_payload or []), focus_role=focus_role_id or "auto")

    # -----------------------------------------------------------------------
    # 获取新闻上下文：报告生成主链路不能被 embedding 构建阻塞，因此这里使用
    # 轻量新闻摘要；深度 RAG 检索仍保留在新闻知识库接口中按需调用。
    # -----------------------------------------------------------------------
    news_context = ""
    news_started = perf_counter()
    logger("准备新闻上下文")
    try:
        from services.news.news_kb import get_recent_news_context

        basics = profile_payload.get("basics") or {}
        _target_dir = str(basics.get("targetDirection") or basics.get("target_direction") or "")
        _major = str(basics.get("major") or "")
        _city = str(basics.get("targetCity") or basics.get("target_city") or "")
        news_context = get_recent_news_context(
            topics=[item for item in [_target_dir, _major, _city] if item],
            max_items=12,
            max_age_days=7,
        )
        logger("新闻上下文完成", elapsed=f"{perf_counter() - news_started:.1f}s", chars=len(news_context or ""))
    except Exception:
        # 回退：直接用 news_payload 里的标题列表
        items = news_payload.get("items") or []
        lines = []
        for item in items[:15]:
            title = str(item.get("title") or "")
            summary = str(item.get("summary") or "").strip()
            source = str(item.get("source") or "")
            if title:
                lines.append(f"- {title} [{source}]: {summary}" if summary else f"- {title} [{source}]")
        news_context = "\n".join(lines) if lines else "（无新闻数据）"
        logger("新闻上下文回退完成", elapsed=f"{perf_counter() - news_started:.1f}s", chars=len(news_context or ""))
    shared_pool["inputs"]["news_context"] = news_context

    # Sort roles, prioritize focus_role_id
    if focus_role_id:
        role_payload = sorted(
            role_payload,
            key=lambda r: str(r.get("id") or "") != focus_role_id,
        )

    # -------------------------------------------------------------------
    # Step A: 行业分析师 + 简历证据分析官初筛
    # 这两步只依赖输入画像/简历，可以并行；后续阶段有明确数据依赖，保持串行。
    # -------------------------------------------------------------------
    def _run_industry_step() -> dict[str, Any]:
        notify("industry_analysis", "行业分析", "正在分析行业趋势与劳动力市场动态...")
        if llm_caller:
            return run_industry_analyst(profile_payload, news_context, llm_caller)
        return _fallback_industry_brief(profile_payload)

    def _run_resume_pass1_step() -> dict[str, Any]:
        notify("resume_evidence", "简历证据解析", "正在解析简历中的能力证据（第一遍）...")
        if llm_caller:
            return run_resume_evidence_analyst(profile_payload, None, llm_caller)
        return _fallback_resume_evidence(profile_payload)

    if llm_caller:
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="career-report-a")
        try:
            logger("并行阶段启动", parallel_agents="行业分析师,简历证据分析官")
            industry_future = executor.submit(
                _run_logged_step,
                logger,
                "行业分析师",
                _run_industry_step,
            )
            resume_future = executor.submit(
                _run_logged_step,
                logger,
                "简历证据分析官-初筛",
                _run_resume_pass1_step,
            )
            industry_brief = industry_future.result()
            shared_pool["outputs"]["industry_analysis"] = industry_brief

            # Step B only needs industry_brief + profile. Keep resume pass1 running
            # in parallel when it is slower than industry analysis.
            notify("career_positioning", "职业定位", "正在结合测评与意愿生成职业方向假设...")
            positioning_output = _run_logged_step(
                logger,
                "职业定位顾问",
                lambda: run_career_positioning_advisor(
                    profile_payload,
                    shared_pool["outputs"]["industry_analysis"],
                    llm_caller,
                ),
            )
            resume_evidence_pass1 = resume_future.result()
            shared_pool["outputs"]["career_positioning"] = positioning_output
            shared_pool["outputs"]["resume_evidence_pass1"] = resume_evidence_pass1
            logger("并行阶段汇合")
        finally:
            executor.shutdown(wait=True)
    else:
        industry_brief = _run_logged_step(logger, "行业分析师-fallback", _run_industry_step)
        resume_evidence_pass1 = _run_logged_step(logger, "简历证据分析官-初筛-fallback", _run_resume_pass1_step)
        positioning_output = _run_logged_step(
            logger,
            "职业定位顾问-fallback",
            lambda: _fallback_positioning(profile_payload, role_payload),
        )
        shared_pool["outputs"]["industry_analysis"] = industry_brief
        shared_pool["outputs"]["resume_evidence_pass1"] = resume_evidence_pass1
        shared_pool["outputs"]["career_positioning"] = positioning_output

    # -------------------------------------------------------------------
    # Step B': 简历证据分析官 — second pass with positioning must_prove
    # -------------------------------------------------------------------
    notify("resume_evidence_2", "证据对齐复核", "正在按照职业方向假设复核简历证据...")
    resume_evidence = resume_evidence_pass1  # default to first pass
    if llm_caller and positioning_output.get("hypotheses_for_evidence"):
        resume_evidence = _run_logged_step(
            logger,
            "简历证据分析官-复核",
            lambda: run_resume_evidence_analyst(
                profile_payload,
                shared_pool["outputs"]["career_positioning"],
                llm_caller,
            ),
        )
    else:
        logger(
            "Agent 跳过",
            agent="简历证据分析官-复核",
            reason="没有定位假设或当前为 fallback",
        )
    shared_pool["outputs"]["resume_evidence"] = resume_evidence

    # -------------------------------------------------------------------
    # Step C: 能力评估官
    # -------------------------------------------------------------------
    notify("competency_assess", "能力评估", "正在构建就业能力画像...")
    if llm_caller:
        competency_profile = _run_logged_step(
            logger,
            "能力评估官",
            lambda: run_competency_assessor(
                shared_pool["outputs"]["resume_evidence"],
                shared_pool["outputs"]["career_positioning"],
                profile_payload,
                llm_caller,
            ),
        )
    else:
        competency_profile = _run_logged_step(logger, "能力评估官-fallback", _fallback_competency)
    shared_pool["outputs"]["competency_profile"] = competency_profile

    # -------------------------------------------------------------------
    # Step D: 岗位匹配官
    # -------------------------------------------------------------------
    notify("role_match", "岗位匹配", "正在比对能力画像与岗位要求...")
    if llm_caller:
        match_output = _run_logged_step(
            logger,
            "岗位匹配官",
            lambda: run_role_match_officer(
                shared_pool["outputs"]["competency_profile"],
                shared_pool["outputs"]["career_positioning"],
                role_payload,
                shared_pool["outputs"]["industry_analysis"],
                llm_caller,
            ),
        )
    else:
        match_output = _run_logged_step(logger, "岗位匹配官-fallback", lambda: _fallback_match(role_payload))
    shared_pool["outputs"]["role_match"] = match_output

    # -------------------------------------------------------------------
    # Step E: 路径规划师
    # -------------------------------------------------------------------
    notify("path_planning", "路径规划", "正在生成时间分层的职业成长路径...")
    if llm_caller:
        path_plan = _run_logged_step(
            logger,
            "路径规划师",
            lambda: run_career_path_planner(
                shared_pool["outputs"]["career_positioning"],
                shared_pool["outputs"]["role_match"],
                shared_pool["outputs"]["competency_profile"],
                shared_pool["outputs"]["industry_analysis"],
                shared_pool["outputs"]["resume_evidence"],
                profile_payload,
                llm_caller,
            ),
        )
    else:
        path_plan = _run_logged_step(logger, "路径规划师-fallback", _fallback_path_plan)
    shared_pool["outputs"]["path_plan"] = path_plan

    industry_brief = _normalize_industry_brief(industry_brief)
    positioning_output = _normalize_positioning_output(positioning_output)
    resume_evidence = _normalize_resume_evidence_output(resume_evidence)
    competency_profile = _normalize_competency_profile(competency_profile)
    match_output = _normalize_match_output(match_output, role_payload)
    path_plan = _normalize_path_plan(path_plan)
    shared_pool["outputs"]["industry_analysis"] = industry_brief
    shared_pool["outputs"]["career_positioning"] = positioning_output
    shared_pool["outputs"]["resume_evidence"] = resume_evidence
    shared_pool["outputs"]["competency_profile"] = competency_profile
    shared_pool["outputs"]["role_match"] = match_output
    shared_pool["outputs"]["path_plan"] = path_plan

    # -------------------------------------------------------------------
    # Build report bundle
    # -------------------------------------------------------------------
    notify("report_writer", "报告合成", "正在合成可阅读职业报告并写入报告中心...")
    report_writer_started = perf_counter()
    logger("Agent 开始", agent="报告合成器")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    basics = profile_payload.get("basics") or {}
    focus_role_name = _resolve_focus_role_name(focus_role_id, role_payload, match_output.get("target_role"))
    match_output["target_role"] = focus_role_name
    profile_snapshot = _build_profile_snapshot(profile_payload, positioning_output, competency_profile)
    gap_map = _build_gap_map(match_output, competency_profile, resume_evidence)
    gap_map["focus_role_name"] = focus_role_name
    career_path = _build_career_path(path_plan, match_output)
    phase_plan = _build_phase_plan(path_plan)
    trend_brief = _build_trend_brief(industry_brief)
    industry_explainability = _build_industry_explainability(industry_brief)
    positioning_explainability = _build_positioning_explainability(positioning_output, focus_role_name)
    resume_explainability = _build_resume_explainability(resume_evidence)
    competency_explainability = _build_competency_explainability(competency_profile)
    match_explainability = _build_match_explainability(match_output, resume_evidence)
    path_explainability = _build_path_explainability(path_plan, match_output)
    dashboard_summary = _build_dashboard_summary(
        focus_role_name,
        match_output,
        positioning_output,
        gap_map,
        resume_evidence,
        industry_brief,
    )
    next_actions = _build_next_actions(phase_plan, match_output, gap_map)
    evidence_health = _build_evidence_health(gap_map, profile_snapshot, resume_evidence)
    market_signals = _build_market_signals(trend_brief, industry_brief)
    industry_story = _build_industry_story(industry_brief, news_payload)
    role_cards = _build_role_cards(role_payload, match_output, resume_evidence)
    path_graph = _build_path_graph(career_path, path_plan, focus_role_name)
    plan_board = _build_plan_board(phase_plan, next_actions)
    explainability_summary = _build_explainability_summary(dashboard_summary, evidence_health, market_signals)
    executive_summary = str(positioning_output.get("user_intent_summary") or industry_brief.get("industry_summary") or "")
    target_role_name = (
        focus_role_name
        or match_output.get("target_role")
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
            "prompt_source_module": PROMPT_SOURCE_MODULE,
            "pipeline_prompt_loaded": bool(CAREER_PIPELINE_PROMPT),
            "model": model_name or "",
            "generation_mode": generation_mode,
            "focus_role_id": focus_role_id,
            "focus_role_name": focus_role_name,
            "title": f"{str(basics.get('major') or '')} · {target_role_name} · 职业生涯发展报告",
            "summary": executive_summary,
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
        "profile_snapshot": profile_snapshot,
        "role_rankings": _build_role_rankings(role_payload, match_output),
        "gap_map": gap_map,
        "career_path": career_path,
        "phase_plan": phase_plan,
        "trend_brief": trend_brief,
        "report_document": {
            "markdown": full_markdown,
            "html": "",
            "title": f"{target_role_name} 职业生涯发展报告",
            "executive_summary": executive_summary,
            "confidence": _overall_confidence(match_output),
            "focus_role_id": focus_role_id,
            "focus_role_name": focus_role_name,
            "dashboard_summary": dashboard_summary,
            "next_actions": next_actions,
            "evidence_health": evidence_health,
            "market_signals": market_signals,
            "industry_story": industry_story,
            "role_cards": role_cards,
            "path_graph": path_graph,
            "plan_board": plan_board,
            "explainability_summary": explainability_summary,
            "explainability_overview": {
                "industry": industry_explainability,
                "positioning": positioning_explainability,
                "resume": resume_explainability,
                "competency": competency_explainability,
                "match": match_explainability,
                "path": path_explainability,
            },
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
                        "verification_actions": industry_brief.get("verification_actions") or [],
                        "industry_summary": industry_brief.get("industry_summary") or "",
                        "explainability": industry_explainability,
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
                        "decision_rules": positioning_output.get("decision_rules") or [],
                        "user_intent_summary": positioning_output.get("user_intent_summary") or "",
                        "explainability": positioning_explainability,
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
                        "explainability": resume_explainability,
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
                        "explainability": competency_explainability,
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
                        "weights_rationale": match_output.get("weights_rationale") or "",
                        "why_match": match_output.get("why_match") or [],
                        "why_not_yet": match_output.get("why_not_yet") or [],
                        "explainability": match_explainability,
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
                        "path_rationale": path_plan.get("path_rationale") or [],
                        "path_risks": path_plan.get("path_risks") or [],
                        "explainability": path_explainability,
                    },
                },
            },
        },
        "generation_diagnostics": {
            "context_pool": {
                "input_keys": sorted(shared_pool["inputs"].keys()),
                "output_keys": sorted(shared_pool["outputs"].keys()),
                "mode": generation_mode,
            },
        },
    }

    logger(
        "Agent 完成",
        agent="报告合成器",
        elapsed=f"{perf_counter() - report_writer_started:.1f}s",
        markdown_chars=len(full_markdown or ""),
    )
    logger("编排完成", elapsed=f"{perf_counter() - pipeline_started:.1f}s", mode=generation_mode)
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
    partial_gaps = [
        _clean_text(item.get("requirement"))
        for item in (match_output.get("partial_gaps") or [])
        if isinstance(item, dict) and _clean_text(item.get("requirement"))
    ]
    results = []
    for i, role in enumerate(role_payload[:5]):
        is_target = str(role.get("name") or "") == target_role
        required_skills = list(role.get("requiredSkills") or [])[:6]
        results.append({
            "id": str(role.get("id") or f"role-{i+1}"),
            "name": str(role.get("name") or ""),
            "category": str(role.get("category") or ""),
            "overall_score": fit_score if is_target else int(role.get("overallScore") or 0),
            "confidence": "高" if is_target and fit_score >= 70 else "中",
            "fit_summary": str(role.get("summary") or ""),
            "path": str(role.get("path") or ""),
            "required_skills": required_skills,
            "because": _unique_texts(
                [
                    _clean_text(role.get("summary")),
                    "核心技能：{}".format("、".join(required_skills[:3])) if required_skills else "",
                    "当前待补强：{}".format("、".join(partial_gaps[:2])) if is_target and partial_gaps else "",
                ]
            )[:3],
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
        "verification_actions": industry_brief.get("verification_actions") or [],
        "signals": [
            {
                "type": "机会信号",
                "text": d.get("name") or str(d),
                "source_type": d.get("source_type") or "",
                "time_horizon": d.get("time_horizon") or "",
            }
            for d in (industry_brief.get("hot_directions") or [])[:3]
        ],
    }
