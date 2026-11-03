from __future__ import annotations

import re
from typing import Any

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


def _role_overall_score(role: Any) -> int:
    if not isinstance(role, dict):
        return 0
    try:
        score = int(role.get("overallScore") or role.get("overall_score") or 0)
    except Exception:
        score = 0
    return max(0, min(100, score))


def _fit_band_from_score(score: Any) -> str:
    try:
        safe_score = int(score or 0)
    except Exception:
        safe_score = 0
    safe_score = max(0, min(100, safe_score))
    if safe_score >= 75:
        return "strong"
    if safe_score >= 60:
        return "moderate"
    if safe_score > 0:
        return "weak"
    return "not_ready"


def _find_role_payload_entry(
    role_payload: list[dict[str, Any]],
    *,
    role_id: str = "",
    role_name: str = "",
) -> dict[str, Any]:
    safe_role_id = _clean_text(role_id)
    safe_role_name = _clean_text(role_name)
    if safe_role_id:
        for role in role_payload:
            if _clean_text(role.get("id")) == safe_role_id:
                return role
    if safe_role_name:
        for role in role_payload:
            candidate = _clean_text(role.get("name"))
            if not candidate:
                continue
            if candidate == safe_role_name or candidate in safe_role_name or safe_role_name in candidate:
                return role
    return {}


def _sorted_roles_by_effective_score(
    role_payload: list[dict[str, Any]],
    match_output: dict[str, Any],
) -> list[dict[str, Any]]:
    target_role = _clean_text(match_output.get("target_role"))
    target_fit_score = max(0, min(100, int(match_output.get("fit_score") or 0)))

    def _effective_score(role: dict[str, Any]) -> int:
        name = _clean_text(role.get("name"))
        if target_role and name == target_role:
            return target_fit_score
        return _role_overall_score(role)

    roles = [role for role in role_payload if isinstance(role, dict)]
    return sorted(
        roles,
        key=lambda role: (_effective_score(role), _clean_text(role.get("name"))),
        reverse=True,
    )


def _loose_fit_score(raw_score: int, has_hard_failures: bool) -> int:
    """把匹配分映射到 75–100 的基础区间，避免算得太死板。"""
    if raw_score <= 0:
        return 72 if has_hard_failures else 78
    # 将 1–100 映射到 75–100，保留相对差距
    mapped = 75 + int((raw_score / 100.0) * 25)
    if has_hard_failures:
        mapped = min(mapped, 88)
    return max(0, min(100, mapped))


def _resolve_effective_match_output(
    match_output: dict[str, Any],
    role_payload: list[dict[str, Any]],
    focus_role_id: str,
) -> dict[str, Any]:
    requested_target_role = _resolve_focus_role_name(
        focus_role_id,
        role_payload,
        match_output.get("target_role"),
    )
    requested_role = _find_role_payload_entry(
        role_payload,
        role_id=focus_role_id,
        role_name=requested_target_role,
    )
    requested_role_score = _role_overall_score(requested_role)
    current_fit_score = max(0, min(100, int(match_output.get("fit_score") or 0)))
    current_fit_band = _clean_text(match_output.get("fit_band") or "not_ready").lower()
    if current_fit_band not in {"strong", "moderate", "weak", "not_ready"}:
        current_fit_band = "not_ready"

    ranked_roles = sorted(
        [role for role in role_payload if isinstance(role, dict)],
        key=lambda role: _role_overall_score(role),
        reverse=True,
    )
    top_ranked_role = ranked_roles[0] if ranked_roles else {}
    top_ranked_name = _clean_text(top_ranked_role.get("name"))
    top_ranked_score = _role_overall_score(top_ranked_role)

    resolved = dict(match_output)
    resolved["requested_target_role"] = requested_target_role
    resolved["requested_focus_role_id"] = _clean_text(focus_role_id)
    resolved["requested_role_score"] = requested_role_score
    if top_ranked_name:
        resolved["top_ranked_role"] = top_ranked_name
        resolved["top_ranked_role_score"] = top_ranked_score

    has_hard_failures = bool(_normalize_text_list(match_output.get("hard_failures")))

    if (
        top_ranked_name
        and top_ranked_score > 0
        and top_ranked_name != requested_target_role
        and (current_fit_score <= 0 or current_fit_band == "not_ready" or requested_role_score <= 0)
    ):
        fallback_note = (
            f"原主岗位 {requested_target_role or '待识别方向'} 当前匹配度为 {current_fit_score}% ，"
            f"已回退到人岗匹配得分最高的 {top_ranked_name}（原始分 {top_ranked_score}%）。"
        )
        existing_rationale = _clean_text(match_output.get("weights_rationale"))
        resolved["target_role"] = top_ranked_name
        calibrated = _loose_fit_score(top_ranked_score, has_hard_failures)
        resolved["fit_score"] = calibrated
        resolved["fit_band"] = _fit_band_from_score(calibrated)
        resolved["weights_rationale"] = f"{fallback_note} {existing_rationale}".strip()
        resolved["role_resolution_mode"] = "fallback_to_role_rankings"
        return resolved

    if requested_target_role and current_fit_score <= 0 and requested_role_score > 0:
        align_note = f"当前主岗位 {requested_target_role} 的岗位推荐得分为 {requested_role_score}%（原始分），已用推荐分同步展示。"
        existing_rationale = _clean_text(match_output.get("weights_rationale"))
        resolved["target_role"] = requested_target_role
        calibrated = _loose_fit_score(requested_role_score, has_hard_failures)
        resolved["fit_score"] = calibrated
        resolved["fit_band"] = _fit_band_from_score(calibrated)
        resolved["weights_rationale"] = f"{align_note} {existing_rationale}".strip()
        resolved["role_resolution_mode"] = "align_requested_role_with_rankings"
        return resolved

    resolved["target_role"] = requested_target_role or _clean_text(match_output.get("target_role"))
    resolved["role_resolution_mode"] = "keep_requested_role"

    # 校准得分到 75–100 基础区间（用户要求不要算太死）
    calibrated_score = _loose_fit_score(int(resolved.get("fit_score") or 0), has_hard_failures)
    resolved["fit_score"] = calibrated_score
    resolved["fit_band"] = _fit_band_from_score(calibrated_score)
    return resolved


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
    display_roles = _sorted_roles_by_effective_score(role_payload, match_output)[:5]
    for index, role in enumerate(display_roles):
        if not isinstance(role, dict):
            continue
        name = _clean_text(role.get("name"))
        if not name:
            continue
        is_target = name == target_role or (not target_role and index == 0)
        fit_score = int(match_output.get("fit_score") or 0) if is_target else _role_overall_score(role)
        cards.append(
            {
                "role_name": name,
                "fit_score": max(0, min(100, fit_score)),
                "fit_band": _clean_text(match_output.get("fit_band") if is_target else ""),
                "why_fit": _unique_texts(
                    (match_output.get("why_match") or [])
                    if is_target
                    else [_clean_text(role.get("summary") or role.get("fit_summary"))]
                )[:3],
                "strengths": strengths,
                "hard_gaps": hard_failures if is_target else [],
                "partial_gaps": partial_gaps if is_target else [
                    item
                    for item in (
                        _normalize_text_list(role.get("requiredSkills") or role.get("required_skills"))[:4]
                    )
                    if item
                ],
                "switch_path": _clean_text(role.get("path")),
                "promotion_path": _clean_text(role.get("careerPath") or role.get("path")),
                "required_skills": _normalize_text_list(role.get("requiredSkills") or role.get("required_skills"))[:6],
                "fit_summary": _clean_text(role.get("summary") or role.get("fit_summary")),
            }
        )
    return cards


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
    display_roles = _sorted_roles_by_effective_score(role_payload, match_output)[:5]
    for i, role in enumerate(display_roles):
        is_target = str(role.get("name") or "") == target_role
        required_skills = list(role.get("requiredSkills") or role.get("required_skills") or [])[:6]
        results.append({
            "id": str(role.get("id") or f"role-{i+1}"),
            "name": str(role.get("name") or ""),
            "category": str(role.get("category") or ""),
            "overall_score": fit_score if is_target else _role_overall_score(role),
            "confidence": "高" if is_target and fit_score >= 70 else "中",
            "fit_summary": str(role.get("summary") or role.get("fit_summary") or ""),
            "path": str(role.get("path") or ""),
            "required_skills": required_skills,
            "because": _unique_texts(
                [
                    _clean_text(role.get("summary") or role.get("fit_summary")),
                    "核心技能：{}".format("、".join(required_skills[:3])) if required_skills else "",
                    "当前待补强：{}".format("、".join(partial_gaps[:2])) if is_target and partial_gaps else "",
                ]
            )[:3],
        })
    return results

