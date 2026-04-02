from __future__ import annotations

from datetime import datetime
from typing import Any

from .schemas import REPORT_VERSION


CAPABILITY_LABELS = {
    "professional": "专业技能",
    "learning": "学习能力",
    "communication": "沟通协作",
    "innovation": "创新表达",
    "stress_tolerance": "抗压韧性",
    "internship": "实践积累",
    "execution": "执行交付",
}

TONE_SEQUENCE = ["indigo", "cyan", "emerald", "amber", "rose", "violet"]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _clamp_percent(value: Any) -> int:
    return max(0, min(100, _safe_int(value, 0)))


def _unique(values: list[Any], limit: int = 6) -> list[str]:
    seen = []
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.append(text)
        if len(seen) >= limit:
            break
    return seen


def _average(values: list[Any]) -> int | None:
    scores = [_safe_int(item) for item in values if item is not None and str(item) != ""]
    if not scores:
        return None
    return int(round(sum(scores) / len(scores)))


def _confidence_from_score(score: int | None) -> str:
    if score is None:
        return "低"
    if score >= 80:
        return "高"
    if score >= 60:
        return "中"
    return "低"


def _format_score_label(score: int | None) -> str:
    return "--" if score is None else f"{score}%"


def _guess_archetype(capability_vector: list[dict[str, Any]], work_values: list[str], roles: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    sorted_caps = sorted(capability_vector, key=lambda item: item.get("score") or 0, reverse=True)
    top_keys = [item.get("key") for item in sorted_caps[:2]]
    top_labels = [item.get("label") for item in sorted_caps[:3] if item.get("label")]
    role_names = [str(item.get("name") or "").strip() for item in roles[:2] if str(item.get("name") or "").strip()]

    if "communication" in top_keys and "execution" in top_keys:
        return (
            "协同推进型",
            "更擅长在明确目标下协调资源、推进任务落地，适合承担需要沟通、跟进和执行闭环的岗位。",
            _unique(top_labels + work_values + role_names, 5),
        )
    if "learning" in top_keys and "professional" in top_keys:
        return (
            "分析研判型",
            "偏向通过理解信息、拆解问题和持续学习形成判断，适合要求逻辑、分析和专业积累的岗位。",
            _unique(top_labels + work_values + role_names, 5),
        )
    if "innovation" in top_keys and "communication" in top_keys:
        return (
            "探索表达型",
            "擅长把新想法转成表达和互动，适合内容、运营、产品表达等需要洞察与沟通的场景。",
            _unique(top_labels + work_values + role_names, 5),
        )
    if "execution" in top_keys and "stress_tolerance" in top_keys:
        return (
            "稳态执行型",
            "更适合边界清晰、节奏稳定、强调持续交付与责任闭环的工作环境。",
            _unique(top_labels + work_values + role_names, 5),
        )
    return (
        "综合成长型",
        "当前画像呈现出多维度并行发展的状态，适合通过目标岗位进一步收束主线，再逐步强化证据。",
        _unique(top_labels + work_values + role_names, 5),
    )


def run_profile_fusion_agent(profile_payload: dict[str, Any], role_payload: list[dict[str, Any]]) -> dict[str, Any]:
    assessment = profile_payload.get("assessment") if isinstance(profile_payload.get("assessment"), dict) else {}
    basics = profile_payload.get("basics") if isinstance(profile_payload.get("basics"), dict) else {}
    interview = profile_payload.get("interview") if isinstance(profile_payload.get("interview"), dict) else {}
    resume = profile_payload.get("resume") if isinstance(profile_payload.get("resume"), dict) else {}
    capability_map = profile_payload.get("capabilities") if isinstance(profile_payload.get("capabilities"), dict) else {}
    work_values = _unique(profile_payload.get("workValues") or [])
    missing_items = _unique(profile_payload.get("missingItems") or [], 10)

    capability_vector = []
    for key, label in CAPABILITY_LABELS.items():
        item = capability_map.get(key) if isinstance(capability_map.get(key), dict) else {}
        capability_vector.append(
            {
                "key": key,
                "label": label,
                "score": _clamp_percent(item.get("score")) if item.get("score") is not None else None,
                "sources": _unique(item.get("sources") or []),
            }
        )

    capability_coverage = _clamp_percent(profile_payload.get("capabilityCoverage"))
    readiness_score = _average(
        [
            capability_coverage,
            100 if assessment.get("mbti", {}).get("completed") else 30,
            100 if assessment.get("holland", {}).get("completed") else 30,
            _clamp_percent(interview.get("completionScore")),
            100 if str(resume.get("status") or "") == "analyzed" else 35,
        ]
    ) or 0

    role_rankings = sorted(
        [item for item in role_payload if isinstance(item, dict)],
        key=lambda item: (_safe_int(item.get("overallScore"), -1), -len(str(item.get("name") or ""))),
        reverse=True,
    )
    archetype_name, archetype_summary, archetype_tags = _guess_archetype(capability_vector, work_values, role_rankings)
    mbti = assessment.get("mbti") if isinstance(assessment.get("mbti"), dict) else {}
    holland = assessment.get("holland") if isinstance(assessment.get("holland"), dict) else {}
    summary_text = str(profile_payload.get("summary") or "").strip() or "当前画像已汇集测评、访谈和简历信号，可用于职业规划报告生成。"
    evidence_sources = _unique(
        [
            "MBTI" if mbti.get("completed") else "",
            "霍兰德" if holland.get("completed") else "",
            "职业访谈" if interview.get("profile") else "",
            "简历分析" if resume.get("profile") else "",
            "基础信息" if any(basics.values()) else "",
        ],
        6,
    )

    return {
        "version": REPORT_VERSION,
        "core_thesis": (
            f"当前更适合以“{archetype_name}”的工作方式理解职业定位，"
            f"优先围绕 {role_rankings[0]['name']} 等相邻方向建立更强的能力与证据闭环。"
            if role_rankings
            else f"当前画像更接近“{archetype_name}”，但目标职业方向仍需要更多输入来收束。"
        ),
        "summary": summary_text,
        "archetype": {
            "name": archetype_name,
            "summary": archetype_summary,
            "tags": archetype_tags,
            "confidence": _confidence_from_score(readiness_score),
        },
        "interest_profile": {
            "mbti": str(mbti.get("display_type") or mbti.get("final_type") or "待补充"),
            "holland": str(holland.get("code") or "待补充"),
            "recommended_roles": _unique(profile_payload.get("recommendedRoles") or [], 6),
        },
        "capability_vector": capability_vector,
        "work_values": work_values,
        "readiness_score": readiness_score,
        "capability_coverage": capability_coverage,
        "basics": {
            "major": str(basics.get("major") or "").strip(),
            "grade": str(basics.get("grade") or "").strip(),
            "target_city": str(basics.get("target_city") or "").strip(),
            "target_direction": str(basics.get("target_direction") or "").strip(),
        },
        "resume_status": str(resume.get("status") or "empty"),
        "interview_completion": _clamp_percent(interview.get("completionScore")),
        "missing_items": missing_items,
        "evidence_sources": evidence_sources,
    }


def run_role_retrieval_agent(profile_snapshot: dict[str, Any], role_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    top_roles = sorted(
        [item for item in role_payload if isinstance(item, dict)],
        key=lambda item: _safe_int(item.get("overallScore"), -1),
        reverse=True,
    )[:5]
    results = []
    for index, item in enumerate(top_roles):
        breakdown = [
            {"label": "特质匹配", "score": item.get("trait", {}).get("score")},
            {"label": "能力匹配", "score": item.get("ability", {}).get("score")},
            {"label": "专业匹配", "score": item.get("major", {}).get("score")},
            {"label": "意愿匹配", "score": item.get("willingness", {}).get("score")},
        ]
        evidence_sources = _unique(
            [
                "MBTI" if item.get("trait", {}).get("score") is not None else "",
                "霍兰德" if item.get("trait", {}).get("score") is not None else "",
                "职业访谈" if item.get("willingness", {}).get("score") is not None else "",
                "基础信息" if item.get("major", {}).get("score") is not None else "",
                "简历分析" if item.get("ability", {}).get("score") is not None else "",
            ],
            5,
        )
        results.append(
            {
                "id": str(item.get("id") or f"role-{index + 1}"),
                "name": str(item.get("name") or "待识别方向"),
                "category": str(item.get("category") or "职业方向"),
                "overall_score": _safe_int(item.get("overallScore"), 0),
                "confidence": str(item.get("confidence") or _confidence_from_score(item.get("overallScore"))),
                "fit_summary": str(item.get("summary") or "").strip(),
                "path": str(item.get("path") or "").strip(),
                "required_skills": _unique(item.get("requiredSkills") or [], 6),
                "work_values": _unique(item.get("workValues") or [], 5),
                "breakdown": [
                    {
                        "label": entry["label"],
                        "score": _safe_int(entry.get("score"), 0) if entry.get("score") is not None else None,
                    }
                    for entry in breakdown
                ],
                "evidence_sources": evidence_sources or profile_snapshot.get("evidence_sources") or ["统一画像"],
                "reason_lines": _unique(
                    [
                        item.get("trait", {}).get("reason"),
                        item.get("ability", {}).get("reason"),
                        item.get("major", {}).get("reason"),
                        item.get("willingness", {}).get("reason"),
                    ],
                    4,
                ),
                "requirements": item.get("requirements") if isinstance(item.get("requirements"), dict) else {},
            }
        )
    return results


def run_trend_intelligence_agent(news_payload: dict[str, Any]) -> dict[str, Any]:
    items = news_payload.get("items") if isinstance(news_payload.get("items"), list) else []
    status = str(news_payload.get("status") or "empty")
    snapshot_label = str(news_payload.get("snapshot_label") or news_payload.get("window_snapshot_label") or "").strip()
    picked = []
    for index, item in enumerate(items[:4]):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or item.get("desc") or "").strip()
        source = str(item.get("source") or "新闻快照").strip()
        impact = "招聘信号"
        tone = TONE_SEQUENCE[index % len(TONE_SEQUENCE)]
        lowered = title.lower()
        if any(keyword in title for keyword in ["裁员", "收缩", "降薪"]) or any(keyword in lowered for keyword in ["layoff", "downturn"]):
            impact = "风险信号"
            tone = "rose"
        elif any(keyword in title for keyword in ["扩招", "增长", "需求"]) or any(keyword in lowered for keyword in ["hiring", "growth", "demand"]):
            impact = "机会信号"
            tone = "emerald"
        elif any(keyword in title for keyword in ["技能", "ai", "人工智能", "大模型"]) or any(keyword in lowered for keyword in ["skill", "ai", "model"]):
            impact = "技能信号"
            tone = "cyan"
        picked.append(
            {
                "title": title or f"趋势信号 {index + 1}",
                "summary": summary or "当前新闻快照提示行业环境正在变化，建议把它作为规划报告中的现实约束参考。",
                "impact": impact,
                "tone": tone,
                "source": source,
                "published_at": str(item.get("published_at") or item.get("publishedAt") or ""),
            }
        )

    if picked:
        headline = "已结合最近职业新闻快照，为报告补入招聘热度、技能变化与行业风险信号。"
    elif status == "stale":
        headline = "趋势快照暂未刷新成功，当前报告沿用最近一次可用快照。"
    else:
        headline = "当前没有稳定的外部趋势输入，报告将以用户画像和岗位适配为主。"

    constraints = []
    if status in {"empty", "error"}:
        constraints.append("外部趋势信号不足，本次建议更偏向内部画像与岗位要求。")
    if status == "stale":
        constraints.append("外部趋势数据不是今天的最新快照，需要结合后续刷新结果复核。")
    if not picked:
        constraints.append("建议后续接入更完整的招聘市场与技能热度数据。")

    return {
        "status": status,
        "snapshot_label": snapshot_label,
        "headline": headline,
        "signals": picked,
        "constraints": _unique(constraints, 4),
    }


def run_gap_analysis_agent(
    profile_payload: dict[str, Any],
    profile_snapshot: dict[str, Any],
    role_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    focus_role = role_candidates[0] if role_candidates else {}
    capability_vector = {
        item.get("key"): item
        for item in profile_snapshot.get("capability_vector") or []
        if isinstance(item, dict) and item.get("key")
    }
    requirements = focus_role.get("requirements") if isinstance(focus_role.get("requirements"), dict) else {}

    capability_gaps = []
    for key, label in CAPABILITY_LABELS.items():
        if key not in requirements:
            continue
        required = _clamp_percent(requirements.get(key))
        current = capability_vector.get(key, {}).get("score")
        current_value = current if current is not None else None
        status = "待补证" if current_value is None else ("已达标" if current_value >= required else "需加强")
        capability_gaps.append(
            {
                "key": key,
                "label": label,
                "current": current_value,
                "required": required,
                "status": status,
                "confidence": _confidence_from_score(current_value if current_value is not None else 35),
                "evidence_sources": capability_vector.get(key, {}).get("sources") or ["统一画像"],
                "note": (
                    f"当前已接近 {label} 要求。"
                    if status == "已达标"
                    else f"{label} 仍低于目标岗位要求，需要继续补足相关证据。"
                    if status == "需加强"
                    else f"{label} 缺少直接证据，当前主要依靠间接画像推断。"
                ),
            }
        )

    resume_profile = profile_payload.get("resume", {}).get("profile") if isinstance(profile_payload.get("resume"), dict) else {}
    resume_keywords = _unique(
        ((resume_profile.get("keywords") if isinstance(resume_profile, dict) else []) or [])
        + ((resume_profile.get("skills") if isinstance(resume_profile, dict) else []) or []),
        20,
    )
    skill_gaps = []
    for skill in focus_role.get("required_skills") or []:
        normalized_skill = str(skill or "").lower()
        matched = any(normalized_skill in str(item).lower() or str(item).lower() in normalized_skill for item in resume_keywords)
        if not matched:
            skill_gaps.append(f"目标岗位强调 {skill}，当前简历中缺少直接的技能或项目证据。")

    evidence_gaps = []
    for item in profile_snapshot.get("missing_items") or []:
        evidence_gaps.append(f"{item} 会降低报告判断置信度。")
    if str(profile_snapshot.get("resume_status") or "") != "analyzed":
        evidence_gaps.append("简历尚未完成解析，能力与经历证据的客观性不足。")

    risk_alerts = []
    if focus_role and _safe_int(focus_role.get("overall_score"), 0) < 60:
        risk_alerts.append(f"{focus_role.get('name')} 当前仅为中低匹配，报告建议更偏向过渡方案而非直接冲刺。")
    if any(item.get("status") == "待补证" for item in capability_gaps):
        risk_alerts.append("部分能力判断仍建立在间接信号上，后续需要用项目、实习或访谈补证。")
    if skill_gaps:
        risk_alerts.append("技能缺口主要集中在目标岗位的核心工具与方法论层面。")

    overview = (
        f"当前差距分析以 {focus_role.get('name') or '目标岗位'} 为主线，"
        f"重点关注 {len([item for item in capability_gaps if item.get('status') != '已达标'])} 个能力项与 {len(skill_gaps)} 个技能项。"
    )

    return {
        "focus_role_id": str(focus_role.get("id") or ""),
        "focus_role_name": str(focus_role.get("name") or "待识别方向"),
        "overview": overview,
        "capability_gaps": capability_gaps,
        "skill_gaps": _unique(skill_gaps, 6),
        "evidence_gaps": _unique(evidence_gaps, 6),
        "risk_alerts": _unique(risk_alerts, 4),
    }


def run_stage_planning_agent(
    profile_snapshot: dict[str, Any],
    role_candidates: list[dict[str, Any]],
    gap_map: dict[str, Any],
) -> dict[str, Any]:
    focus_role = role_candidates[0] if role_candidates else {}
    top_gap_labels = [
        item.get("label")
        for item in gap_map.get("capability_gaps") or []
        if item.get("status") in {"需加强", "待补证"}
    ][:3]
    skill_gaps = gap_map.get("skill_gaps") or []
    role_name = str(focus_role.get("name") or "目标方向")
    req_skills = list(focus_role.get("required_skills") or [])

    def _tasks(phase_id: str, items: list[str]) -> list[dict[str, str]]:
        return [
            {"id": f"{phase_id}-task-{i + 1}", "text": str(text).strip()}
            for i, text in enumerate(items)
            if str(text).strip()
        ]

    short_term = [
        {
            "id": "short-early",
            "phase": "短期 · 起步期",
            "title": "先补核心能力证据",
            "objective": f"围绕 {role_name} 建立一轮可被证明的核心能力证据，从间接画像推断走向直接成果证明。",
            "focus_points": _unique(top_gap_labels + skill_gaps[:1], 3) or ["梳理现有经历中的可验证成果"],
            "tasks": _tasks("short-early", [
                f"整理与 {top_gap_labels[0] if top_gap_labels else '目标岗位'} 相关的具体项目成果并加入简历",
                f"完成 {req_skills[0] if req_skills else '核心岗位技能'} 的系统学习或实践验证",
                f"向 2-3 家目标公司投递简历并记录反馈",
                "整理一份针对目标方向的求职作品集或案例集",
            ][:3]),
            "signals": ["优先解决低置信与待补证判断", "建立第一轮职业定位依据"],
        },
        {
            "id": "short-advance",
            "phase": "短期 · 进阶期",
            "title": "收束主线并稳定目标方向",
            "objective": "让目标岗位从兴趣判断逐步转为有证据支撑的方向判断，减少定位摇摆。",
            "focus_points": _unique(
                [role_name, *(req_skills[:2])],
                3,
            ) or ["明确主目标岗位与相邻方向"],
            "tasks": _tasks("short-advance", [
                f"完成 {req_skills[1] if len(req_skills) > 1 else '辅助核心技能'} 的实践应用并有可展示的成果",
                "完成至少一次完整的目标岗位面试流程（包括复盘和改进）",
                "更新简历，加入上一阶段的新成果与新经历",
                f"在目标城市或线上参加一次 {role_name} 相关的行业活动",
            ][:3]),
            "signals": ["减少定位摇摆", "增强岗位适配度稳定性"],
        },
    ]
    long_term = [
        {
            "id": "long-early",
            "phase": "长期 · 初期阶段",
            "title": "从岗位适配走向路径适配",
            "objective": "判断长期是否适合沿这条路径发展，不只关注能否进入目标岗位。",
            "focus_points": _unique(
                [*(focus_role.get("work_values") or [])[:2], "职业环境匹配"],
                3,
            ) or ["确认长期工作方式是否匹配"],
            "tasks": _tasks("long-early", [
                "评估当前工作环境与个人价值观的实际匹配程度",
                "完成首次职业阶段性复盘，更新画像数据并重新生成报告",
                "探索职业路径中期目标岗位的可达路径",
            ]),
            "signals": ["稳定产出", "工作价值观与环境更一致"],
        },
        {
            "id": "long-late",
            "phase": "长期 · 进阶阶段",
            "title": "建立动态复盘机制",
            "objective": "随着画像、岗位需求与行业趋势变化，周期性复查职业路径是否仍然成立。",
            "focus_points": _unique(
                [*(gap_map.get("risk_alerts") or [])[:1], "定期复核趋势变化", "复盘能力增量"],
                3,
            ),
            "tasks": _tasks("long-late", [
                "与目标路径的资深从业者进行一次深度职业访谈",
                "重新评估职业方向并更新规划报告（对比上一版本的差异）",
                "为下一阶段的能力增长设定量化指标",
            ]),
            "signals": ["保持职业规划可迭代", "及时修正过时假设"],
        },
    ]
    checkpoints = [
        {"label": "阶段复查", "summary": "每次画像输入有明显更新后，重新生成并对比新版报告。"},
        {"label": "趋势复查", "summary": "结合行业快照，观察目标岗位是否出现明显需求变化。"},
        {"label": "证据复查", "summary": "优先判断低置信结论是否已被新的经历、项目或访谈补证。"},
    ]
    return {
        "short_term": short_term,
        "long_term": long_term,
        "checkpoints": checkpoints,
    }


def _llm_markdown_to_sections(markdown_text: str) -> list[dict[str, Any]]:
    sections = []
    current = None
    for raw_line in str(markdown_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = {
                "id": f"section-{len(sections) + 1}",
                "kicker": "AI Summary",
                "title": line[3:].strip(),
                "summary": "",
                "cards": [],
            }
            continue
        if current is None:
            continue
        if line.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
            current["cards"].append(
                {
                    "title": "要点",
                    "body": line.lstrip("-*1234567890. ").strip(),
                    "tone": TONE_SEQUENCE[len(current["cards"]) % len(TONE_SEQUENCE)],
                    "confidence": "中",
                    "evidence_sources": ["报告写作代理"],
                }
            )
            continue
        if not current["summary"]:
            current["summary"] = line
        else:
            current["cards"].append(
                {
                    "title": "说明",
                    "body": line,
                    "tone": TONE_SEQUENCE[len(current["cards"]) % len(TONE_SEQUENCE)],
                    "confidence": "中",
                    "evidence_sources": ["报告写作代理"],
                }
            )
    if current:
        sections.append(current)
    return sections


def run_report_writer_agent(
    profile_snapshot: dict[str, Any],
    role_candidates: list[dict[str, Any]],
    gap_map: dict[str, Any],
    phase_plan: dict[str, Any],
    trend_brief: dict[str, Any],
    career_path: dict[str, Any] | None = None,
    markdown_writer=None,
) -> dict[str, Any]:
    top_role = role_candidates[0] if role_candidates else {}
    top_score = _safe_int(top_role.get("overall_score"), 0) if top_role else None
    top_confidence = str(top_role.get("confidence") or _confidence_from_score(top_score))
    title = f"{top_role.get('name') or '职业发展'}规划报告"
    executive_summary = (
        f"当前画像显示你更接近“{profile_snapshot.get('archetype', {}).get('name', '综合成长型')}”，"
        f"现阶段最值得优先验证的职业方向是 {top_role.get('name') or '待识别方向'}。"
    )
    _cp = career_path if isinstance(career_path, dict) else {}
    outline = [
        {"id": "profile-overview", "title": "职业画像概述", "kicker": "Profile Snapshot", "summary": profile_snapshot.get("summary") or profile_snapshot.get("core_thesis")},
        {"id": "role-rankings", "title": "目标职业方向与适配度排序", "kicker": "Role Ranking", "summary": top_role.get("fit_summary") or "系统已基于当前画像完成方向排序。"},
        {"id": "career-path", "title": f"职业发展路径：{_cp.get('focus_role_name') or top_role.get('name') or '目标方向'}", "kicker": "Career Path", "summary": _cp.get("path_summary") or "基于岗位特征构建的发展阶梯。"},
        {"id": "gap-analysis", "title": "差距分析", "kicker": "Gap Map", "summary": gap_map.get("overview") or "系统已识别当前画像与目标岗位之间的差距。"},
        {"id": "phase-plan", "title": "分阶段成长路径与行动计划", "kicker": "Action Plan", "summary": "可交互的短期行动任务列表，完成后在左侧点击更新状态。"},
        {"id": "trend-brief", "title": "行业趋势与现实约束", "kicker": "Trend Brief", "summary": trend_brief.get("headline") or "已纳入当前外部趋势信号。"},
        {"id": "evaluation", "title": "评估与动态调整机制", "kicker": "Review Loop", "summary": "通过周期性复查，保持职业规划与现实环境同步。"},
    ]

    sections = [
        {
            "id": "profile-overview",
            "kicker": "Profile Snapshot",
            "title": "职业画像概述",
            "summary": profile_snapshot.get("core_thesis") or profile_snapshot.get("summary"),
            "metrics": [
                {"label": "画像成熟度", "value": _format_score_label(profile_snapshot.get("readiness_score"))},
                {"label": "证据覆盖", "value": _format_score_label(profile_snapshot.get("capability_coverage"))},
                {"label": "主画像", "value": profile_snapshot.get("archetype", {}).get("name", "--")},
            ],
            "cards": [
                {
                    "title": "核心职业画像",
                    "body": profile_snapshot.get("archetype", {}).get("summary") or profile_snapshot.get("summary"),
                    "tone": "indigo",
                    "confidence": profile_snapshot.get("archetype", {}).get("confidence", "中"),
                    "evidence_sources": profile_snapshot.get("evidence_sources") or ["统一画像"],
                    "tags": profile_snapshot.get("archetype", {}).get("tags") or [],
                },
                {
                    "title": "兴趣与工作价值观",
                    "body": "这份画像综合了职业兴趣、性格偏好与工作价值观，用于判断更适合的工作方式与职业环境。",
                    "tone": "cyan",
                    "confidence": _confidence_from_score(profile_snapshot.get("readiness_score")),
                    "evidence_sources": profile_snapshot.get("evidence_sources") or ["统一画像"],
                    "tags": _unique(
                        [profile_snapshot.get("interest_profile", {}).get("mbti"), profile_snapshot.get("interest_profile", {}).get("holland")]
                        + (profile_snapshot.get("work_values") or []),
                        6,
                    ),
                },
                {
                    "title": "当前盲区",
                    "body": "未补齐的输入会直接影响画像判断的稳定性，后续需要优先关注这些低置信位置。",
                    "tone": "amber",
                    "confidence": "中",
                    "evidence_sources": ["统一画像"],
                    "tags": profile_snapshot.get("missing_items") or ["当前主要输入已基本齐备"],
                },
            ],
        },
        {
            "id": "role-rankings",
            "kicker": "Role Ranking",
            "title": "目标职业方向与适配度排序",
            "summary": f"当前 Top1 方向为 {top_role.get('name') or '待识别方向'}，系统同时保留其余相邻方向用于对照。",
            "cards": [
                {
                    "title": item.get("name") or "待识别方向",
                    "body": item.get("fit_summary") or "系统已根据当前画像完成方向判断。",
                    "tone": TONE_SEQUENCE[index % len(TONE_SEQUENCE)],
                    "confidence": item.get("confidence", "中"),
                    "evidence_sources": item.get("evidence_sources") or ["岗位匹配"],
                    "tags": _unique((item.get("required_skills") or [])[:3] + (item.get("work_values") or [])[:2], 5),
                    "score": _safe_int(item.get("overall_score"), 0),
                }
                for index, item in enumerate(role_candidates[:3])
            ],
            "visualization": {
                "type": "score-bars",
                "items": [
                    {
                        "label": item.get("name") or "待识别方向",
                        "value": _safe_int(item.get("overall_score"), 0),
                        "hint": f"置信度 {item.get('confidence', '中')}",
                    }
                    for item in role_candidates[:5]
                ],
            },
        },
        {
            "id": "career-path",
            "kicker": "Career Path",
            "title": f"职业发展路径：{_cp.get('focus_role_name') or top_role.get('name') or '目标方向'}",
            "summary": _cp.get("path_summary") or f"从 {top_role.get('name') or '目标岗位'} 出发，构建清晰的职业发展阶梯。",
            "cards": [
                {
                    "title": "O*NET 岗位画像",
                    "body": _cp.get("onet_description") or f"{top_role.get('name') or '目标岗位'} 是一个需要综合专业能力与实践积累的职业方向，O*NET 数据库提供了全面的岗位能力参考框架。",
                    "tone": "indigo",
                    "confidence": "高" if _cp.get("onet_soc") else "中",
                    "evidence_sources": ["O*NET 30.2" if _cp.get("onet_soc") else "岗位画像库"],
                    "tags": _unique((_cp.get("onet_supplement") or [])[:3] + [_cp.get("job_zone_label") or ""], 4),
                },
                {
                    "title": "发展阶梯概览",
                    "body": f"参考路径：{_cp.get('path_summary') or '暂无路径信息'}。每个阶段需要不同的能力组合与经历佐证，建议按阶段逐步积累。",
                    "tone": "emerald",
                    "confidence": "中",
                    "evidence_sources": ["岗位路径模型", "O*NET 30.2"],
                    "tags": [node.get("timeline") for node in (_cp.get("path_nodes") or [])],
                },
            ],
            "visualization": {
                "type": "career-path",
                "items": _cp.get("path_nodes") or [],
                "job_zone": _cp.get("job_zone"),
                "job_zone_label": _cp.get("job_zone_label") or "",
            },
        },
        {
            "id": "gap-analysis",
            "kicker": "Gap Map",
            "title": "差距分析",
            "summary": gap_map.get("overview") or "当前已识别目标岗位与现有画像之间的关键差距。",
            "cards": [
                {
                    "title": "能力差距",
                    "body": "系统将能力项拆成当前水平、目标要求与证据来源，用于判断哪些缺口是真缺口，哪些只是待补证。",
                    "tone": "rose",
                    "confidence": "中",
                    "evidence_sources": ["画像融合", "岗位匹配"],
                    "tags": _unique([item.get("label") for item in gap_map.get("capability_gaps") or [] if item.get("status") != "已达标"], 4),
                },
                {
                    "title": "技能缺口",
                    "body": "优先关注目标岗位反复强调、而当前简历与画像中缺少直接佐证的技能要求。",
                    "tone": "amber",
                    "confidence": "中",
                    "evidence_sources": ["简历分析", "岗位匹配"],
                    "tags": gap_map.get("skill_gaps") or ["当前没有明显新增技能缺口"],
                },
                {
                    "title": "证据不足项",
                    "body": "这类条目不是直接否定，而是说明系统目前缺少足够的输入来提高判断置信度。",
                    "tone": "violet",
                    "confidence": "低",
                    "evidence_sources": ["统一画像"],
                    "tags": gap_map.get("evidence_gaps") or ["当前没有显著证据盲区"],
                },
            ],
            "visualization": {
                "type": "gap-matrix",
                "items": [
                    {
                        "label": item.get("label") or "能力项",
                        "current": item.get("current"),
                        "required": item.get("required"),
                        "status": item.get("status") or "待补证",
                    }
                    for item in gap_map.get("capability_gaps") or []
                ],
            },
        },
        {
            "id": "phase-plan",
            "kicker": "Action Plan",
            "title": "分阶段成长路径与行动计划",
            "summary": "系统把规划拆成短期/长期与阶段递进两层，短期任务可在左侧档案面板中逐条标记完成状态。",
            "cards": [
                {
                    "title": item.get("title") or item.get("phase") or "阶段任务",
                    "body": item.get("objective") or "围绕目标岗位逐步补齐能力与证据。",
                    "tone": TONE_SEQUENCE[index % len(TONE_SEQUENCE)],
                    "confidence": "中",
                    "evidence_sources": ["阶段规划代理"],
                    "tags": item.get("focus_points") or [],
                    "score": None,
                }
                for index, item in enumerate((phase_plan.get("short_term") or []) + (phase_plan.get("long_term") or []))
            ],
            "visualization": {
                "type": "timeline",
                "items": [
                    {
                        "label": item.get("phase") or "阶段",
                        "title": item.get("title") or "成长节点",
                        "summary": item.get("objective") or "",
                        "phase_id": item.get("id") or "",
                        "tasks": item.get("tasks") or [],
                    }
                    for item in (phase_plan.get("short_term") or []) + (phase_plan.get("long_term") or [])
                ],
            },
        },
        {
            "id": "trend-brief",
            "kicker": "Trend Brief",
            "title": "行业趋势与现实约束",
            "summary": trend_brief.get("headline") or "系统已纳入当前外部趋势与现实约束。",
            "cards": [
                {
                    "title": signal.get("title") or "趋势信号",
                    "body": signal.get("summary") or "当前新闻快照提示外部职业环境正在变化。",
                    "tone": signal.get("tone") or "cyan",
                    "confidence": "中",
                    "evidence_sources": [signal.get("source") or "新闻快照"],
                    "tags": [signal.get("impact") or "趋势信号"],
                }
                for signal in trend_brief.get("signals") or []
            ] or [
                {
                    "title": "趋势输入不足",
                    "body": "当前没有足够稳定的外部趋势信号，报告暂以画像与岗位要求为主。",
                    "tone": "slate",
                    "confidence": "低",
                    "evidence_sources": ["职业新闻快照"],
                    "tags": trend_brief.get("constraints") or [],
                }
            ],
            "visualization": {
                "type": "signal-cards",
                "items": trend_brief.get("signals") or [],
            },
        },
        {
            "id": "evaluation",
            "kicker": "Review Loop",
            "title": "评估与动态调整机制",
            "summary": "职业规划报告不是一次性结论，而是需要随着画像输入、岗位市场与趋势信号更新而迭代。",
            "cards": [
                {
                    "title": item.get("label") or "复查节点",
                    "body": item.get("summary") or "建议在关键输入变化后重新生成并复核报告。",
                    "tone": TONE_SEQUENCE[index % len(TONE_SEQUENCE)],
                    "confidence": "中",
                    "evidence_sources": ["阶段规划代理", "趋势情报代理"],
                    "tags": [],
                }
                for index, item in enumerate(phase_plan.get("checkpoints") or [])
            ],
        },
    ]

    if callable(markdown_writer):
        llm_prompt = {
            "profile_snapshot": profile_snapshot,
            "role_candidates": role_candidates,
            "gap_map": gap_map,
            "phase_plan": phase_plan,
            "trend_brief": trend_brief,
        }
        system_prompt = (
            "你是一名中文职业规划报告写作代理。"
            "请基于给定 JSON，输出一份结构清晰、克制专业的 Markdown 摘要。"
            "必须使用以下二级标题：职业画像概述、目标职业方向与适配度排序、差距分析、分阶段成长路径、行业趋势与现实约束、评估与动态调整机制。"
            "不要捏造信息，每条结论要体现来源与置信度，不要出现 Markdown 代码块。"
        )
        llm_markdown = str(markdown_writer(llm_prompt, system_prompt) or "").strip()
        llm_sections = _llm_markdown_to_sections(llm_markdown)
        if llm_sections:
            for section in sections:
                matched = next((item for item in llm_sections if item.get("title") == section.get("title")), None)
                if matched and matched.get("summary"):
                    section["summary"] = matched["summary"]
                if matched and matched.get("cards"):
                    section["cards"] = section.get("cards", []) + matched["cards"][:2]

    return {
        "title": title,
        "executive_summary": executive_summary,
        "focus_role_id": str(top_role.get("id") or ""),
        "focus_role_name": str(top_role.get("name") or "待识别方向"),
        "confidence": top_confidence,
        "outline": outline,
        "sections": sections,
    }


def run_critic_agent(report_bundle: dict[str, Any]) -> dict[str, Any]:
    report = dict(report_bundle)
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    sections = []
    seen_ids = set()
    for index, section in enumerate(document.get("sections") or [], start=1):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("id") or f"section-{index}").strip() or f"section-{index}"
        if section_id in seen_ids:
            section_id = f"{section_id}-{index}"
        seen_ids.add(section_id)
        cards = []
        for card in section.get("cards") or []:
            if not isinstance(card, dict):
                continue
            cards.append(
                {
                    "title": str(card.get("title") or "要点").strip() or "要点",
                    "body": str(card.get("body") or "暂无补充说明。").strip() or "暂无补充说明。",
                    "tone": str(card.get("tone") or "indigo").strip() or "indigo",
                    "confidence": str(card.get("confidence") or "中").strip() or "中",
                    "evidence_sources": _unique(card.get("evidence_sources") or ["报告系统"], 4),
                    "tags": _unique(card.get("tags") or [], 6),
                    "score": card.get("score"),
                }
            )
        sections.append(
            {
                "id": section_id,
                "kicker": str(section.get("kicker") or "Career Report").strip() or "Career Report",
                "title": str(section.get("title") or f"章节 {index}").strip() or f"章节 {index}",
                "summary": str(section.get("summary") or "系统已整理该章节的关键信息。").strip() or "系统已整理该章节的关键信息。",
                "metrics": section.get("metrics") if isinstance(section.get("metrics"), list) else [],
                "cards": cards,
                "visualization": section.get("visualization") if isinstance(section.get("visualization"), dict) else None,
            }
        )
    document["sections"] = sections
    document["outline"] = [
        {
            "id": item.get("id") or section.get("id"),
            "title": item.get("title") or section.get("title"),
            "kicker": item.get("kicker") or section.get("kicker"),
            "summary": item.get("summary") or section.get("summary"),
        }
        for item, section in zip(document.get("outline") or sections, sections)
    ]
    if not document["outline"]:
        document["outline"] = [
            {
                "id": section.get("id"),
                "title": section.get("title"),
                "kicker": section.get("kicker"),
                "summary": section.get("summary"),
            }
            for section in sections
        ]
    report["report_document"] = document
    report.setdefault("meta", {})
    report["meta"]["critic_checked"] = True
    report["meta"]["critic_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return report


# ══════════════════════════════════════════════════════════════════════════
#  O*NET Enrichment Agent
# ══════════════════════════════════════════════════════════════════════════

def run_onet_enrichment_agent(role_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich role candidates with O*NET occupational data."""
    try:
        from services.onet.loader import enrich_role as _enrich
    except ImportError:
        return role_candidates
    enriched = []
    for role in role_candidates:
        role_id = str(role.get("id") or "")
        onet_data = {}
        try:
            onet_data = _enrich(role_id)
        except Exception:
            pass
        enriched_role = dict(role)
        if onet_data:
            enriched_role["onet_context"] = onet_data
        enriched.append(enriched_role)
    return enriched


# ══════════════════════════════════════════════════════════════════════════
#  Career Path Agent
# ══════════════════════════════════════════════════════════════════════════

def run_career_path_agent(
    profile_snapshot: dict[str, Any],
    role_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a structured career progression path for the focus role."""
    focus_role = role_candidates[0] if role_candidates else {}
    role_name = str(focus_role.get("name") or "目标方向")
    path_str = str(focus_role.get("path") or "")
    onet_ctx = focus_role.get("onet_context") if isinstance(focus_role.get("onet_context"), dict) else {}

    # Parse Chinese path string like "编辑 → 内容策划 → 内容负责人"
    steps = [s.strip() for s in path_str.split("→") if s.strip()] if path_str else []
    if not steps:
        steps = [role_name, f"高级{role_name}", f"{role_name}负责人"]

    timeline_labels = ["0-1 年（入门期）", "2-3 年（成长期）", "4-6 年（进阶期）", "7+ 年（资深期）"]
    required_skills = _unique((focus_role.get("required_skills") or [])[:3], 3)
    onet_skills = _unique((onet_ctx.get("onet_skills") or [])[:5], 5)

    path_nodes = []
    for i, step in enumerate(steps[:4]):
        if i == 0:
            stage_skills = required_skills
        elif i == 1:
            stage_skills = _unique(required_skills + onet_skills[:2], 4)
        elif i == 2:
            stage_skills = _unique(onet_skills[:4], 4)
        else:
            stage_skills = _unique(["战略规划", "团队管理", "跨部门协调"], 3)
        path_nodes.append({
            "level": i + 1,
            "title": step,
            "timeline": timeline_labels[i] if i < len(timeline_labels) else f"阶段 {i + 1}",
            "is_current_target": i == 0,
            "skills": stage_skills,
        })

    # Supplement with O*NET related occupation titles for additional context
    related = onet_ctx.get("related_occupations") or []
    onet_supplement = [item.get("title") for item in related[:3] if item.get("title")]

    onet_description = str(onet_ctx.get("description") or "")
    job_zone = onet_ctx.get("job_zone")
    job_zone_label = onet_ctx.get("job_zone_label") or ""

    return {
        "focus_role_id": str(focus_role.get("id") or ""),
        "focus_role_name": role_name,
        "path_summary": path_str or " → ".join(s["title"] for s in path_nodes),
        "path_nodes": path_nodes,
        "onet_soc": onet_ctx.get("soc_code") or "",
        "onet_description": onet_description[:300] if onet_description else "",
        "onet_supplement": onet_supplement,
        "job_zone": job_zone,
        "job_zone_label": job_zone_label,
    }
