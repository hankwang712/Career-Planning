"""职业访谈、MBTI 追问与深度测评分析：提示词、对话规整和对应的接口。"""
import json
import logging

from flask import Blueprint, jsonify, request

from .llm_calls import call_markdown_chat, call_structured_chat
from .textutil import compact_list, safe_score, truncate_text

logger = logging.getLogger(__name__)

CAREER_INTERVIEW_SYSTEM_PROMPT = """
你是一名中文职业规划咨询师，正在进行一对一深度访谈。

【你的风格】
- 像一位温和但专业的心理咨询师，引导用户探索自我
- 每次只问一个开放性问题，不连续追问
- 尊重用户的节奏，用户可以随时说"够了"或"我想停下来"
- 当用户给出模糊回答时，用具体例子引导；当用户给出具体例子时，深挖感受和收获

【四大探索主题】（不需要全部覆盖，用户聊到哪算哪）

1. 角色模型（Role Model）
   - 你从小到大有没有特别崇拜的人？可以是名人、老师、家长、朋友
   - 这个人做了什么让你如此钦佩？
   - 有没有在生活中尝试学习他/她的某种做法？结果怎样了？

2. 生活故事（Life Story）
   - 回想一下，有没有一件事你做得比大多数人都好？（即使很小）
   - 那件事是什么情况下发生的？你当时做了什么？
   - 有没有一段经历，虽然结果不太好，但你学到了很多？

3. 工作价值观（Work Values）
   - 假设三年后你找到了理想工作，典型的一天你会做什么？
   - 那份工作最吸引你的是什么？
   - 有什么样的工作内容会让你觉得"这不值得我做"？

4. 情境应对（Situational Response）
   - 如果你在团队项目中遇到意见分歧，你会怎么处理？
   - 如果 deadline 很紧但任务很重，你会怎么安排？
   - 当你不确定该怎么做时，你通常会怎么做？

【访谈规则】
- 用户没说"够了"或"完成了"之前，不要主动结束访谈
- 至少完成 3 轮对话后再考虑收尾
- 如果某个主题已经探索充分，可以自然转向其他主题
- 用自然对话的方式，不要像机器人一样列问题清单

【输出格式】（严格 JSON）
{
  "next_question": "下一轮问题，如果用户说完成了就填'__FINISH__'",
  "focus_dimension": "必须是以下之一（一字不差）：职业兴趣、工作价值观、学习方式、沟通风格、行动证据、职业成熟度。表示下一轮主要在为哪一维度收集信息。若系统消息里给出了各维度已答/目标数，已答满的维度不得再作为 focus_dimension，必须切换到下一个未答满的维度。",
  "completion_score": 0,
  "readiness_score": 0,
  "topic": "当前主题，如'角色模型'或'生活故事'等",
  "topic_progress": "当前主题的探索进度描述",
  "next_question_policy": {
    "strategy": "fact_example | motive_reason | value_tradeoff | behavior_pref | conflict_clarify | micro_scenario",
    "target_dimension": "职业兴趣",
    "rationale": "为何现在优先追问这一维度（一句话）",
    "expected_information_gain": 0.0
  },
  "dimension_metrics": {
    "职业兴趣": {
      "coverage": 0.0,
      "specificity": 0.0,
      "confidence": 0.0,
      "evidence_count": 0,
      "consistency": 0.0,
      "saturated": false,
      "missing_slots": ["仍缺的具体证据槽位，可为空数组"]
    }
  },
  "profile_hypothesis": {
    "top_roles": [{"name": "产品经理", "score": 0.35}],
    "stable_traits": ["结构化表达强"],
    "unresolved_conflicts": ["若用户既强调自由又强调流程稳定，可写一条待澄清张力"]
  },
  "evidence_cards": [
    {"category": "偏好证据", "bullets": ["从对话可支撑的判断1", "判断2"]},
    {"category": "能力证据", "bullets": []}
  ],
  "conflict_points": [
    {"summary": "自由探索 vs 稳定流程", "clarify_prompt": "可选：用于反证追问的一句话"}
  ],
  "profile": {
    "summary": "一段50字左右的叙事性画像描述",
    "role_model": "用户钦佩的人及原因（从对话中提取）",
    "work_values": ["价值观1", "价值观2", "价值观3"],
    "key_experience": "用户提到的最具体的经历（用于证据）",
    "leadership_style": "从对话推断的领导/协作风格",
    "growth_mindset": "成长型思维的体现",
    "recommended_exploration": ["还可以探索的方向1", "还可以探索的方向2"],
    "missing_followups": ["若继续访谈，最影响职业判断的分歧点还没澄清的一句话（不要只说缺字段）"]
  }
}
规则补充：
- completion_score：仍表示「对话覆盖度」0-100；readiness_score 表示「职业建议可决策度」0-100（证据够具体、冲突已澄清、方向可区分时更高）。
- dimension_metrics：必须为六个维度键各给一份对象；coverage/specificity/confidence/consistency 为 0-1 小数；saturated=true 表示该维证据已够，不必再为凑题数追问。
- 若用户一句话里已同时暴露多维度信息，应同步提高相关维度的 coverage/evidence_count，并在 next_question_policy 里选择「信息增益最大」的追问，而不是死板按顺序。
- conflict_points：当检测到表述张力时填写，用于后续反证追问。
- evidence_cards：用短句沉淀可引用证据，便于前端展示与推荐解释。
"""


MBTI_CLARIFIER_SYSTEM_PROMPT = """
你是一名中文 MBTI 澄清测评助手。请根据用户主测结果中的 close_pairs 生成少量高区分度补充题，帮助确认临界维度。
规则：
- 只使用简洁自然的中文。
- 每道题只对应 EI、SN、TF、JP 之一。
- 题目贴近日常学习、社交、任务推进和决策场景。
- 每道题都要提供鲜明对立的 option_a / option_b。
- 一次返回 2-6 题。
- 只输出 JSON。
JSON 结构必须如下：
{
  "summary": "本轮主要澄清的维度说明",
  "questions": [
    {
      "id": "q1",
      "pair": "EI",
      "question": "题目正文",
      "option_a": "偏向左侧字母的描述",
      "option_b": "偏向右侧字母的描述",
      "weight": 2
    }
  ]
}
"""


DEFAULT_CAREER_DIMENSIONS = [
    "职业兴趣",
    "工作价值观",
    "学习方式",
    "沟通风格",
    "行动证据",
    "职业成熟度",
]


def _guess_mbti_type_from_scores(score_snapshot):
    if not isinstance(score_snapshot, dict):
        return ""
    pairs = [("E", "I", "EI"), ("S", "N", "SN"), ("T", "F", "TF"), ("J", "P", "JP")]
    decided = []
    for left, right, pair_key in pairs:
        left_score = float(score_snapshot.get(left) or 0)
        right_score = float(score_snapshot.get(right) or 0)
        if left_score > right_score:
            decided.append(left)
        elif right_score > left_score:
            decided.append(right)
        else:
            decided.append({"EI": "I", "SN": "N", "TF": "F", "JP": "P"}[pair_key])
    return "".join(decided)


def _normalize_assessment_context(raw_context):
    raw = raw_context if isinstance(raw_context, dict) else {}
    mbti_raw = raw.get("mbti") if isinstance(raw.get("mbti"), dict) else {}
    holland_raw = raw.get("holland") if isinstance(raw.get("holland"), dict) else {}
    basics_raw = raw.get("basics") if isinstance(raw.get("basics"), dict) else {}
    return {
        "mbti": {
            "raw_type": truncate_text(mbti_raw.get("raw_type") or mbti_raw.get("rawType") or "", 16),
            "final_type": truncate_text(mbti_raw.get("final_type") or mbti_raw.get("finalType") or "", 16),
            "summary": truncate_text(mbti_raw.get("summary") or "", 160),
            "top_strengths": compact_list(mbti_raw.get("top_strengths") or mbti_raw.get("topStrengths"), limit=3, item_limit=40),
            "top_risks": compact_list(mbti_raw.get("top_risks") or mbti_raw.get("topRisks"), limit=3, item_limit=40),
        },
        "holland": {
            "code": truncate_text(holland_raw.get("code") or "", 12),
            "top_codes": compact_list(holland_raw.get("top_codes") or holland_raw.get("topCodes"), limit=3, item_limit=8),
            "summary": truncate_text(holland_raw.get("summary") or "", 160),
            "interests": compact_list(holland_raw.get("interests"), limit=4, item_limit=40),
        },
        "basics": {
            "major": truncate_text(basics_raw.get("major") or "", 40),
            "grade": truncate_text(basics_raw.get("grade") or basics_raw.get("education_level") or "", 20),
            "target_city": truncate_text(basics_raw.get("target_city") or basics_raw.get("targetCity") or "", 20),
            "target_direction": truncate_text(basics_raw.get("target_direction") or basics_raw.get("targetDirection") or "", 30),
        },
    }


def _build_mbti_clarifier_prompt(close_pairs, score_snapshot):
    base_prompt = MBTI_CLARIFIER_SYSTEM_PROMPT
    pairs = close_pairs if isinstance(close_pairs, list) else []
    notes = []
    for item in pairs[:4]:
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "").upper().strip()
        diff = item.get("diff")
        if not pair:
            continue
        if diff is None:
            notes.append(f"临界维度：{pair}")
        else:
            notes.append(f"临界维度：{pair}，当前差值 {diff}")
    if not notes:
        return base_prompt
    return f"{base_prompt}\n\n补充上下文：\n- " + "\n- ".join(notes)


def _build_career_interview_prompt(assessment_context):
    base_prompt = CAREER_INTERVIEW_SYSTEM_PROMPT
    context = _normalize_assessment_context(assessment_context)
    mbti = context["mbti"]
    holland = context["holland"]
    basics = context["basics"]
    notes = []

    basics_parts = [
        f"专业 {basics['major']}" if basics["major"] else "",
        f"学历 {basics['grade']}" if basics["grade"] else "",
        f"目标城市 {basics['target_city']}" if basics["target_city"] else "",
        f"目标方向 {basics['target_direction']}" if basics["target_direction"] else "",
    ]
    basics_parts = [part for part in basics_parts if part]
    if basics_parts:
        notes.append("基础信息：" + "，".join(basics_parts))

    mbti_type = mbti["final_type"] or mbti["raw_type"]
    if mbti_type:
        notes.append(f"MBTI：{mbti_type}")
    if mbti.get("summary"):
        notes.append(f"MBTI 摘要：{truncate_text(mbti.get('summary'), 80)}")

    holland_code = holland["code"] or ("".join(holland["top_codes"]) if holland["top_codes"] else "")
    if holland_code:
        notes.append(f"Holland：{holland_code}")
    if holland.get("summary"):
        notes.append(f"Holland 摘要：{truncate_text(holland.get('summary'), 80)}")

    if not notes:
        return base_prompt
    return f"{base_prompt}\n\n补充上下文：\n- " + "\n- ".join(notes)


def _infer_career_interview_focus_from_topic(topic: str) -> str:
    """当模型未返回 focus_dimension 时，用 topic 粗映射到六维之一。"""
    t = str(topic or "").strip()
    if not t:
        return ""
    if "工作价值观" in t:
        return "工作价值观"
    if "角色模型" in t or "榜样" in t:
        return "职业成熟度"
    if "生活故事" in t:
        return "行动证据"
    if "情境应对" in t or t == "情境":
        return "沟通风格"
    if "学习方式" in t or "学习" in t and "风格" in t:
        return "学习方式"
    return ""


def _coerce_career_interview_focus_dimension(payload: dict) -> str:
    raw = str(payload.get("focus_dimension") or "").strip()
    if raw in DEFAULT_CAREER_DIMENSIONS:
        return raw
    inferred = _infer_career_interview_focus_from_topic(payload.get("topic"))
    if inferred in DEFAULT_CAREER_DIMENSIONS:
        return inferred
    for name in DEFAULT_CAREER_DIMENSIONS:
        if name and name in raw:
            return name
    return "职业兴趣"


def _career_interview_progress_system_suffix(focus_dimension: str, progress: list) -> str:
    """把前端维度进度注入系统提示，避免模型永远在「职业兴趣」上打转。"""
    if not isinstance(progress, list) or not progress:
        return ""
    lines = []
    for item in progress:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            answered = int(item.get("answered") or 0)
            target = int(item.get("target") or 0)
        except (TypeError, ValueError):
            answered, target = 0, 0
        lines.append(f"- {name}：已答 {answered} / 目标 {target}" + ("（已满，勿再作为 focus_dimension）" if target > 0 and answered >= target else ""))
    if not lines:
        return ""
    fd = str(focus_dimension or "").strip() or "（请根据下表选择下一未完成维度）"
    return (
        "\n\n【维度进度快照】（必须遵守）\n"
        "- 完成条件以「证据饱和」为主，不以凑满题数为目标：若某维已在对话中获得足够具体证据，可将 dimension_metrics 中该维 saturated 置为 true。\n"
        "- 用户一句话可能同时覆盖多维：应同步提高相关维度的 coverage / evidence_count，并用 next_question_policy 选择信息增益最大的下一问。\n"
        "- next_question 与 focus_dimension 应优先服务「最大缺口维度」或「冲突澄清」，而非死板按顺序；已答满 target 的维度不得再作为 focus_dimension。\n"
        + "\n".join(lines)
        + f"\n前端当前聚焦维度参考：{fd}"
    )


def _merge_career_interview_focus_with_progress(normalized: dict, client_progress: list) -> None:
    """若模型仍把 focus 指到已答满维度，强制改为按顺序第一个未答满维度。"""
    if not isinstance(normalized, dict):
        return
    if not isinstance(client_progress, list) or not client_progress:
        return

    def answered_target(dim_name: str) -> tuple[int, int]:
        for item in client_progress:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != dim_name:
                continue
            try:
                return int(item.get("answered") or 0), int(item.get("target") or 0)
            except (TypeError, ValueError):
                return 0, 0
        return 0, 0

    focus = str(normalized.get("focus_dimension") or "").strip()
    if focus in DEFAULT_CAREER_DIMENSIONS:
        a, t = answered_target(focus)
        if t <= 0 or a < t:
            return

    for name in DEFAULT_CAREER_DIMENSIONS:
        a, t = answered_target(name)
        if t > 0 and a < t:
            normalized["focus_dimension"] = name
            return


def _career_interview_answered_target(client_progress: list, dim_name: str) -> tuple[int, int]:
    for item in client_progress or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != dim_name:
            continue
        try:
            return int(item.get("answered") or 0), int(item.get("target") or 0)
        except (TypeError, ValueError):
            return 0, 0
    return 0, 0


def _apply_next_question_policy_focus(normalized: dict, client_progress: list) -> None:
    """在合法前提下，优先采用模型给出的 next_question_policy.target_dimension（动态选路）。"""
    if not isinstance(normalized, dict):
        return
    pol = normalized.get("next_question_policy") if isinstance(normalized.get("next_question_policy"), dict) else {}
    td = str(pol.get("target_dimension") or "").strip()
    if td not in DEFAULT_CAREER_DIMENSIONS:
        return
    answered, target = _career_interview_answered_target(client_progress, td)
    if target <= 0 or answered >= target:
        return
    normalized["focus_dimension"] = td


def _clamp_unit_float(value, default=0.0):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _attach_career_interview_engine_fields(raw_payload: dict, normalized: dict) -> None:
    """归一化访谈引擎扩展字段：证据指标、假设分布、证据卡与冲突点。"""
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    rs = payload.get("readiness_score")
    if rs is not None:
        normalized["readiness_score"] = safe_score(rs, 0)
    else:
        normalized["readiness_score"] = safe_score(normalized.get("completion_score"), 0)

    pol = payload.get("next_question_policy") if isinstance(payload.get("next_question_policy"), dict) else {}
    normalized["next_question_policy"] = {
        "strategy": str(pol.get("strategy") or "").strip()[:56],
        "target_dimension": str(pol.get("target_dimension") or "").strip(),
        "rationale": str(pol.get("rationale") or "").strip()[:320],
        "expected_information_gain": _clamp_unit_float(pol.get("expected_information_gain"), 0.0),
    }

    raw_dm = payload.get("dimension_metrics") if isinstance(payload.get("dimension_metrics"), dict) else {}
    dim_metrics = {}
    for name in DEFAULT_CAREER_DIMENSIONS:
        block = raw_dm.get(name) if isinstance(raw_dm.get(name), dict) else {}
        slots = [str(x).strip() for x in (block.get("missing_slots") or []) if str(x).strip()][:6]
        try:
            evc = int(block.get("evidence_count") or 0)
        except (TypeError, ValueError):
            evc = 0
        evc = max(0, min(12, evc))
        dim_metrics[name] = {
            "coverage": _clamp_unit_float(block.get("coverage")),
            "specificity": _clamp_unit_float(block.get("specificity")),
            "confidence": _clamp_unit_float(block.get("confidence")),
            "consistency": _clamp_unit_float(block.get("consistency")),
            "evidence_count": evc,
            "saturated": bool(block.get("saturated")),
            "missing_slots": slots,
        }
    normalized["dimension_metrics"] = dim_metrics

    ph = payload.get("profile_hypothesis") if isinstance(payload.get("profile_hypothesis"), dict) else {}
    top_roles = []
    for r in ph.get("top_roles") or []:
        if not isinstance(r, dict):
            continue
        nm = str(r.get("name") or "").strip()
        if not nm:
            continue
        top_roles.append({"name": nm[:48], "score": _clamp_unit_float(r.get("score"))})
    normalized["profile_hypothesis"] = {
        "top_roles": top_roles[:8],
        "stable_traits": [str(x).strip() for x in (ph.get("stable_traits") or []) if str(x).strip()][:8],
        "unresolved_conflicts": [str(x).strip() for x in (ph.get("unresolved_conflicts") or []) if str(x).strip()][:6],
    }

    cards = []
    for c in payload.get("evidence_cards") or []:
        if not isinstance(c, dict):
            continue
        cat = str(c.get("category") or "").strip()[:36]
        if not cat:
            continue
        bullets = [str(x).strip() for x in (c.get("bullets") or []) if str(x).strip()][:10]
        if bullets:
            cards.append({"category": cat, "bullets": bullets})
    normalized["evidence_cards"] = cards[:12]

    cps = []
    for cp in payload.get("conflict_points") or []:
        if not isinstance(cp, dict):
            continue
        sm = str(cp.get("summary") or "").strip()
        cq = str(cp.get("clarify_prompt") or "").strip()
        if not sm and not cq:
            continue
        cps.append({"summary": sm[:220], "clarify_prompt": cq[:320]})
    normalized["conflict_points"] = cps[:8]


def _normalize_profile(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}

    dimension_map = {}
    for item in profile.get("dimensions") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        dimension_map[name] = {
            "name": name,
            "score": safe_score(item.get("score"), 0),
            "evidence": str(item.get("evidence") or "").strip(),
        }

    dimensions = []
    for name in DEFAULT_CAREER_DIMENSIONS:
        dimensions.append(
            dimension_map.get(name)
            or {
                "name": name,
                "score": 0,
                "evidence": "",
            }
        )

    riasec = profile.get("riasec") if isinstance(profile.get("riasec"), dict) else {}
    normalized = {
        "next_question": str(payload.get("next_question") or "").strip(),
        "focus_dimension": _coerce_career_interview_focus_dimension(payload),
        "is_complete": bool(payload.get("is_complete")),
        "completion_score": safe_score(payload.get("completion_score"), 0),
        "profile": {
            "summary": str(profile.get("summary") or "").strip(),
            "role_model": str(profile.get("role_model") or "").strip(),
            "key_experience": str(profile.get("key_experience") or "").strip(),
            "leadership_style": str(profile.get("leadership_style") or "").strip(),
            "growth_mindset": str(profile.get("growth_mindset") or "").strip(),
            "career_interests": [str(item).strip() for item in (profile.get("career_interests") or []) if str(item).strip()][:6],
            "work_values": [str(item).strip() for item in (profile.get("work_values") or []) if str(item).strip()][:6],
            "recommended_roles": [str(item).strip() for item in (profile.get("recommended_roles") or []) if str(item).strip()][:6],
            "recommended_exploration": [str(item).strip() for item in (profile.get("recommended_exploration") or []) if str(item).strip()][:6],
            "evidence_highlights": [str(item).strip() for item in (profile.get("evidence_highlights") or []) if str(item).strip()][:6],
            "next_steps": [str(item).strip() for item in (profile.get("next_steps") or []) if str(item).strip()][:6],
            "missing_followups": [str(item).strip() for item in (profile.get("missing_followups") or []) if str(item).strip()][:4],
            "portrait_ready": bool(profile.get("portrait_ready")),
            "output_scope": str(profile.get("output_scope") or "").strip(),
            "coverage_note": str(profile.get("coverage_note") or "").strip(),
            "riasec": {
                "realistic": safe_score(riasec.get("realistic"), 0),
                "investigative": safe_score(riasec.get("investigative"), 0),
                "artistic": safe_score(riasec.get("artistic"), 0),
                "social": safe_score(riasec.get("social"), 0),
                "enterprising": safe_score(riasec.get("enterprising"), 0),
                "conventional": safe_score(riasec.get("conventional"), 0),
            },
            "dimensions": dimensions,
        },
    }

    if not normalized["profile"]["summary"]:
        normalized["profile"]["summary"] = "访谈已启动，系统正在根据回答逐步生成职业兴趣画像。"

    if not normalized["profile"]["recommended_roles"]:
        normalized["profile"]["recommended_roles"] = normalized["profile"]["career_interests"][:4]

    if not normalized["profile"]["recommended_exploration"]:
        normalized["profile"]["recommended_exploration"] = normalized["profile"]["next_steps"][:4]

    if not normalized["profile"]["next_steps"]:
        normalized["profile"]["next_steps"] = normalized["profile"]["recommended_exploration"][:4]

    if not normalized["profile"]["evidence_highlights"]:
        evidence_seed = [
            normalized["profile"]["key_experience"],
            normalized["profile"]["growth_mindset"],
            normalized["profile"]["role_model"],
        ]
        normalized["profile"]["evidence_highlights"] = [item for item in evidence_seed if item][:4]

    if not normalized["profile"]["missing_followups"]:
        missing_followups = []
        if not normalized["profile"]["key_experience"]:
            missing_followups.append("补一个最能证明方向选择的真实经历")
        if not normalized["profile"]["work_values"]:
            missing_followups.append("补充你最看重的工作价值观")
        if not normalized["profile"]["leadership_style"]:
            missing_followups.append("补充你在协作中的自然角色")
        normalized["profile"]["missing_followups"] = missing_followups[:4]

    signal_count = sum(
        1
        for item in [
            normalized["profile"]["summary"],
            normalized["profile"]["role_model"],
            normalized["profile"]["key_experience"],
            normalized["profile"]["leadership_style"],
            normalized["profile"]["work_values"],
            normalized["profile"]["recommended_exploration"],
        ]
        if item
    )

    if not normalized["profile"]["output_scope"]:
        if normalized["is_complete"] and signal_count >= 4:
            normalized["profile"]["output_scope"] = "full"
        elif signal_count >= 2:
            normalized["profile"]["output_scope"] = "usable"
        else:
            normalized["profile"]["output_scope"] = "partial"

    if not normalized["profile"]["coverage_note"]:
        if normalized["profile"]["output_scope"] == "full":
            normalized["profile"]["coverage_note"] = "访谈信息已经足够支持完整画像与人物明信片展示。"
        elif normalized["profile"]["output_scope"] == "usable":
            normalized["profile"]["coverage_note"] = "当前访谈基于有限对话已形成首版画像，可直接进入人物明信片生成。"
        else:
            normalized["profile"]["coverage_note"] = "当前访谈只形成了弱信号，适合继续追问后再强化画像。"

    if not normalized["profile"]["portrait_ready"]:
        normalized["profile"]["portrait_ready"] = normalized["profile"]["output_scope"] in {"full", "usable"}

    if not normalized["next_question"] and not normalized["is_complete"]:
        normalized["next_question"] = "请继续补充一个能体现你职业兴趣或偏好的真实经历。"

    if normalized["is_complete"] and not normalized["completion_score"]:
        normalized["completion_score"] = 100

    _attach_career_interview_engine_fields(payload, normalized)

    normalized["assistant_reply"] = (
        normalized["next_question"]
        if not normalized["is_complete"]
        else "访谈完成，我已经整理出你的职业兴趣画像。"
    )
    return normalized


def _call_openai_compatible_chat(base_url, api_key, model, messages, system_prompt=None):
    parsed = call_structured_chat(
        base_url,
        api_key,
        model,
        messages,
        system_prompt=system_prompt or CAREER_INTERVIEW_SYSTEM_PROMPT,
        max_tokens=1400,
    )
    return _normalize_profile(parsed)


def _normalize_mbti_clarifier_payload(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    questions = []
    for index, item in enumerate(payload.get("questions") or [], start=1):
        if not isinstance(item, dict):
            continue
        pair = str(item.get("pair") or "").upper().replace("/", "").strip()
        if pair not in {"EI", "SN", "TF", "JP"}:
            continue
        question = str(item.get("question") or "").strip()
        option_a = str(item.get("option_a") or "").strip()
        option_b = str(item.get("option_b") or "").strip()
        if not question or not option_a or not option_b:
            continue
        weight = safe_score(item.get("weight"), 2)
        weight = max(1, min(3, weight))
        questions.append(
            {
                "id": str(item.get("id") or f"q{index}").strip() or f"q{index}",
                "pair": pair,
                "question": question,
                "option_a": option_a,
                "option_b": option_b,
                "weight": weight,
            }
        )

    if not questions:
        raise ValueError("模型未返回可用的 MBTI 澄清题目。")

    return {
        "summary": str(payload.get("summary") or "本轮补充题将帮助确认临界维度。").strip()
        or "本轮补充题将帮助确认临界维度。",
        "questions": questions[:6],
    }


def create_blueprint(login_required, active_provider):
    """active_provider() 返回 (base_url, api_key, model)。"""
    blueprint = Blueprint("interview", __name__)

    @blueprint.route("/api/career-interview", methods=["POST"])
    @login_required
    def api_career_interview():
        payload = request.get_json(silent=True) or {}
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        assessment_context = payload.get("assessment_context") if isinstance(payload.get("assessment_context"), dict) else {}
        client_focus = str(payload.get("focus_dimension") or "").strip()
        client_progress = payload.get("progress") if isinstance(payload.get("progress"), list) else []
        base_url, api_key, model = active_provider()

        if not base_url or not api_key:
            return jsonify({"message": "模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。"}), 400

        normalized_messages = []
        for item in messages[-10:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized_messages.append({"role": role, "content": content[:1600]})

        system_prompt = _build_career_interview_prompt(assessment_context) + _career_interview_progress_system_suffix(
            client_focus, client_progress
        )

        try:
            result = _call_openai_compatible_chat(
                base_url,
                api_key,
                model,
                normalized_messages,
                system_prompt=system_prompt,
            )
            _merge_career_interview_focus_with_progress(result, client_progress)
            _apply_next_question_policy_focus(result, client_progress)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            logger.exception("career interview failed")
            return jsonify({"message": f"职业访谈生成失败: {exc}"}), 502

    @blueprint.route("/api/career-interview/finish", methods=["POST"])
    @login_required
    def api_career_interview_finish():
        """用户点击'完成访谈'按钮时调用，生成最终叙事性摘要"""
        payload = request.get_json(silent=True) or {}
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        assessment_context = payload.get("assessment_context") if isinstance(payload.get("assessment_context"), dict) else {}
        base_url, api_key, model = active_provider()

        if not base_url or not api_key:
            return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

        normalized_messages = []
        for item in messages[-20:]:  # 保留更多历史用于生成摘要
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized_messages.append({"role": role, "content": content[:1600]})

        # 生成叙事性摘要的系统提示词
        finish_prompt = """你是一名职业规划咨询师。用户已点击完成访谈，请根据对话历史生成一份可直接进入统一画像与人物明信片的结构化摘要。

    【输出要求】（严格 JSON 格式）
    {
      "summary": "一段80字左右的叙事性画像，用第一人称描述用户的职业特征、价值观和潜在优势",
      "role_model": "用户钦佩的人及其原因（从对话提取）",
      "work_values": ["价值观1", "价值观2", "价值观3"],
      "key_experience": "用户提到的最具体的经历或成就",
      "leadership_style": "从对话推断的协作/领导风格",
      "growth_mindset": "成长型思维的体现",
      "recommended_roles": ["最像岗位1", "最像岗位2"],
      "recommended_exploration": ["还可以进一步探索的方向1", "还可以进一步探索的方向2"],
      "evidence_highlights": ["证据1", "证据2", "证据3"],
      "next_steps": ["下一步动作1", "下一步动作2"],
      "missing_followups": ["如果继续访谈，最值得补问的问题1", "问题2"],
      "portrait_ready": true,
      "output_scope": "full 或 usable 或 partial",
      "coverage_note": "说明当前结果是否足够支持首版人物明信片"
    }

    规则：
    1. 如果用户提前结束，但已经形成稳定价值观、经历证据或协作风格，也要给出 usable 级输出。
    2. 只有在信号非常少时，才给 partial。
    3. 不要泛泛而谈，尽量把摘要压缩成可以直接进入人物画像的材料。
    4. 如果某些信息未涉及，可以基于已有内容保守推断，但不要编造。"""

        try:
            result = _call_openai_compatible_chat(
                base_url,
                api_key,
                model,
                normalized_messages,
                system_prompt=_build_career_interview_prompt(assessment_context) + "\n\n" + finish_prompt,
            )
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            logger.exception("career interview finish failed")
            return jsonify({"message": f"生成访谈摘要失败: {exc}"}), 502

    @blueprint.route("/api/mbti-clarifier", methods=["POST"])
    @login_required
    def api_mbti_clarifier():
        payload = request.get_json(silent=True) or {}
        base_url, api_key, model = active_provider()

        if not base_url or not api_key:
            return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

        close_pairs = payload.get("close_pairs") if isinstance(payload.get("close_pairs"), list) else []
        score_snapshot = payload.get("score_snapshot") if isinstance(payload.get("score_snapshot"), dict) else {}
        answer_highlights = payload.get("answer_highlights") if isinstance(payload.get("answer_highlights"), list) else []

        user_payload = {
            "close_pairs": close_pairs[:4],
            "score_snapshot": score_snapshot,
            "answer_highlights": answer_highlights[:12],
        }
        messages = [
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            }
        ]

        try:
            parsed = call_structured_chat(
                base_url,
                api_key,
                model,
                messages,
                system_prompt=_build_mbti_clarifier_prompt(close_pairs, score_snapshot),
                max_tokens=700,
            )
            result = _normalize_mbti_clarifier_payload(parsed)
            return jsonify(result)
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            logger.exception("mbti clarifier failed")
            return jsonify({"message": f"MBTI 澄清题生成失败: {exc}"}), 502

    @blueprint.route("/api/deep-test-analysis", methods=["POST"])
    @login_required
    def api_deep_test_analysis():
        payload = request.get_json(silent=True) or {}
        base_url, api_key, model = active_provider()

        if not base_url or not api_key:
            return jsonify({"message": "请先通过模型选择器选择要使用的 API 和模型。"}), 400

        mbti_type = str(payload.get("mbti_type", "")).strip()
        scores = payload.get("scores", {})
        dimension_details = payload.get("dimension_details", [])

        if not mbti_type:
            return jsonify({"message": "请先完成深层测试。"}), 400

        system_prompt = f"""你是一位经验丰富的心理咨询师和职业规划专家，擅长基于MBTI性格类型进行深度分析。
    请根据用户的深层MBTI测试结果，给出个性化的心理分析和成长建议。

    分析要求：
    1. 深入解读该性格类型的核心心理特征（约100字）
    2. 分析该类型在人际关系、工作、学习中的独特优势（约80字）
    3. 指出需要注意和成长的方向（约80字）
    4. 给出2-3条具体可操作的个人发展建议

    风格要求：
    - 语气温和、鼓励性，避免过于笼统
    - 结合用户具体的分数分布进行个性化分析
    - 用中文回答，语言流畅自然

    MBTI类型：{mbti_type}
    各维度原始得分：{json.dumps(scores, ensure_ascii=False)}"""

        messages = [{"role": "user", "content": f"请分析我的深层MBTI测试结果。类型：{mbti_type}，维度分布：{json.dumps(dimension_details, ensure_ascii=False)}"}]

        try:
            analysis = call_markdown_chat(
                base_url,
                api_key,
                model,
                messages,
                system_prompt=system_prompt,
                max_tokens=800,
            )
            return jsonify({"analysis": analysis, "mbti_type": mbti_type})
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception as exc:
            logger.exception("deep test analysis failed")
            return jsonify({"message": f"AI 分析生成失败: {exc}"}), 502

    return blueprint
