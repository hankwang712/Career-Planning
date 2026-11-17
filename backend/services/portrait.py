"""用户画像海报：根据测评、简历和目标方向生成职业定位简报与海报提示词，并调用图片模型渲染。"""
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from flask import Blueprint, jsonify, request

from . import llm_env
from .llm_calls import call_structured_chat, normalize_sdk_base_url
from .report.enhancements import (
    PORTRAIT_PROMPT_PIPELINE_VERSION,
    PORTRAIT_TEMPLATE_VERSION,
    build_portrait_prompt_layers,
    evaluate_portrait_prompt_packet,
)
from .textutil import safe_score

logger = logging.getLogger(__name__)

PROFILE_PORTRAIT_MODEL = os.environ.get("PROFILE_PORTRAIT_MODEL", "google/gemini-3-pro-image-preview").strip() or "google/gemini-3-pro-image-preview"
TEXT_TO_IMAGE_BASE_URL = os.environ.get("TEXT_TO_IMAGE_BASE_URL", "https://openrouter.ai/api/v1").strip() or "https://openrouter.ai/api/v1"


def _portrait_runtime():
    base_url, api_key, _ = llm_env.image_runtime(TEXT_TO_IMAGE_BASE_URL, PROFILE_PORTRAIT_MODEL)
    if not api_key:
        return None, None, PROFILE_PORTRAIT_MODEL
    return base_url, api_key, PROFILE_PORTRAIT_MODEL


def public_profile_portrait_state(raw_state):
    state = raw_state if isinstance(raw_state, dict) else {}
    image_url = str(state.get("image_url") or "").strip()
    brief = _normalize_profile_portrait_brief(state.get("brief"))
    context_snapshot = normalize_profile_portrait_context(state.get("context_snapshot"))
    if not image_url and not brief:
        return None
    return {
        "status": str(state.get("status") or ("ready" if image_url else "brief_ready")).strip() or "ready",
        "image_url": image_url,
        "created_at": int(state.get("created_at") or 0),
        "model": str(state.get("model") or PROFILE_PORTRAIT_MODEL).strip() or PROFILE_PORTRAIT_MODEL,
        "archetype_name": str(state.get("archetype_name") or "").strip(),
        "prompt_summary": str(state.get("prompt_summary") or "").strip(),
        # 完整图像渲染提示词：供「输入输出链路」折叠区展示完整叙事，不再只显示摘要句
        "prompt_text": str(state.get("prompt_text") or "").strip(),
        "prompt_mode": str(state.get("prompt_mode") or "").strip(),
        "prompt_writer_mode": str(state.get("prompt_writer_mode") or "").strip(),
        "prompt_writer_model": str(state.get("prompt_writer_model") or "").strip(),
        "brief_version": str(state.get("brief_version") or "").strip(),
        "prompt_pipeline": state.get("prompt_pipeline") if isinstance(state.get("prompt_pipeline"), dict) else None,
        "prompt_evaluation": state.get("prompt_evaluation") if isinstance(state.get("prompt_evaluation"), dict) else None,
        "image_error": str(state.get("image_error") or "").strip(),
        "brief": brief,
        "context_snapshot": context_snapshot,
    }


def normalize_profile_portrait_context(raw_context):
    context = raw_context if isinstance(raw_context, dict) else {}
    def _clean_text(value, limit=220):
        return str(value or "").strip()[:limit]

    def _clean_list(values, limit=5, item_limit=48):
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        result = []
        for item in values:
            text = _clean_text(item, item_limit)
            if text:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    module_outputs = context.get("module_outputs") if isinstance(context.get("module_outputs"), dict) else {}
    assessment_output = module_outputs.get("assessment") if isinstance(module_outputs.get("assessment"), dict) else {}
    resume_output = module_outputs.get("resume") if isinstance(module_outputs.get("resume"), dict) else {}
    interview_output = module_outputs.get("interview") if isinstance(module_outputs.get("interview"), dict) else {}
    prompt_request = context.get("prompt_request") if isinstance(context.get("prompt_request"), dict) else {}

    return {
        "gender": _clean_text(context.get("gender"), 16),
        "archetype_name": _clean_text(context.get("archetype_name"), 64),
        "archetype_scene": _clean_text(context.get("archetype_scene"), 64),
        "summary": _clean_text(context.get("summary"), 420),
        "mbti": _clean_text(context.get("mbti"), 32),
        "holland": _clean_text(context.get("holland"), 32),
        "holland_top_codes": _clean_list(context.get("holland_top_codes"), limit=3, item_limit=8),
        "major": _clean_text(context.get("major"), 64),
        "grade": _clean_text(context.get("grade"), 32),
        "target_city": _clean_text(context.get("target_city"), 32),
        "target_direction": _clean_text(context.get("target_direction"), 64),
        "role_cluster": _clean_list(context.get("role_cluster"), limit=4),
        "top_roles": _clean_list(context.get("top_roles"), limit=3),
        "work_values": _clean_list(context.get("work_values"), limit=4),
        "axis_traits": _clean_list(context.get("axis_traits"), limit=4, item_limit=48),
        "workstyle_traits": _clean_list(context.get("workstyle_traits"), limit=4, item_limit=48),
        "interview_summary": _clean_text(context.get("interview_summary"), 320),
        "interview_roles": _clean_list(context.get("interview_roles"), limit=4, item_limit=48),
        "interview_values": _clean_list(context.get("interview_values"), limit=5, item_limit=48),
        "interview_evidence": _clean_list(context.get("interview_evidence"), limit=4, item_limit=96),
        "resume_summary": _clean_text(context.get("resume_summary"), 320),
        "resume_roles": _clean_list(context.get("resume_roles"), limit=5, item_limit=48),
        "resume_signals": _clean_list(context.get("resume_signals"), limit=5, item_limit=48),
        "resume_projects": _clean_list(context.get("resume_projects"), limit=4, item_limit=120),
        "resume_experiences": _clean_list(context.get("resume_experiences"), limit=3, item_limit=96),
        "resume_skills": _clean_list(context.get("resume_skills"), limit=8, item_limit=32),
        "resume_competitions": _clean_list(context.get("resume_competitions"), limit=3, item_limit=64),
        "next_steps": _clean_list(context.get("next_steps"), limit=4, item_limit=72),
        "missing_items": _clean_list(context.get("missing_items"), limit=4, item_limit=72),
        "uncertainty": _clean_list(context.get("uncertainty"), limit=4, item_limit=72),
        "identity_narrative": _clean_text(context.get("identity_narrative"), 3600),
        "assessment_prose": _clean_text(context.get("assessment_prose"), 3600),
        "extended_tests_prose": _clean_text(context.get("extended_tests_prose"), 3600),
        "module_outputs": {
            "assessment": {
                "status": _clean_text(assessment_output.get("status"), 16),
                "summary": _clean_text(assessment_output.get("summary"), 520),
                "chips": _clean_list(assessment_output.get("chips"), limit=8, item_limit=48),
                "note": _clean_text(assessment_output.get("note"), 320),
                "detail_prose": _clean_text(assessment_output.get("detail_prose"), 3800),
            },
            "resume": {
                "status": _clean_text(resume_output.get("status"), 16),
                "summary": _clean_text(resume_output.get("summary"), 480),
                "chips": _clean_list(resume_output.get("chips"), limit=8, item_limit=64),
                "note": _clean_text(resume_output.get("note"), 220),
            },
            "interview": {
                "status": _clean_text(interview_output.get("status"), 16),
                "summary": _clean_text(interview_output.get("summary"), 2400),
                "chips": _clean_list(interview_output.get("chips"), limit=8, item_limit=64),
                "note": _clean_text(interview_output.get("note"), 420),
                "completion_score": safe_score(interview_output.get("completion_score"), 0),
                "usable_for_portrait": bool(interview_output.get("usable_for_portrait")),
                "missing_followups": _clean_list(interview_output.get("missing_followups"), limit=4, item_limit=72),
                "forced_supplement": _clean_text(interview_output.get("forced_supplement"), 2400),
            },
        },
        "prompt_request": {
            "card_style": _clean_text(prompt_request.get("card_style"), 48),
            "card_goal": _clean_text(prompt_request.get("card_goal"), 180),
            "visual_direction": _clean_text(prompt_request.get("visual_direction"), 180),
            "required_fields": _clean_list(prompt_request.get("required_fields"), limit=6, item_limit=40),
        },
    }


def _normalize_profile_portrait_brief(raw_brief):
    brief = raw_brief if isinstance(raw_brief, dict) else {}

    def _clean_text(value, limit=220):
        return str(value or "").strip()[:limit]

    def _clean_list(values, limit=5, item_limit=48):
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return []
        result = []
        for item in values:
            text = _clean_text(item, item_limit)
            if text:
                result.append(text)
            if len(result) >= limit:
                break
        return result

    visual_spec = brief.get("visual_spec") if isinstance(brief.get("visual_spec"), dict) else {}
    normalized = {
        "title": _clean_text(brief.get("title"), 40),
        "subtitle": _clean_text(brief.get("subtitle"), 96),
        "positioning": _clean_text(brief.get("positioning"), 180),
        "primary_role": _clean_text(brief.get("primary_role"), 48),
        "support_roles": _clean_list(brief.get("support_roles"), limit=2, item_limit=32),
        "mission_line": _clean_text(brief.get("mission_line"), 120),
        "evidence_tags": _clean_list(brief.get("evidence_tags"), limit=3, item_limit=40),
        "value_tags": _clean_list(brief.get("value_tags"), limit=3, item_limit=24),
        "risk_note": _clean_text(brief.get("risk_note"), 88),
        "next_action": _clean_text(brief.get("next_action"), 88),
        "confidence_band": _clean_text(brief.get("confidence_band"), 16),
        "visual_spec": {
            "style": _clean_text(visual_spec.get("style"), 72),
            "subject_age_hint": _clean_text(visual_spec.get("subject_age_hint"), 32),
            "subject_gender_hint": _clean_text(visual_spec.get("subject_gender_hint"), 16),
            "outfit": _clean_text(visual_spec.get("outfit"), 88),
            "props": _clean_text(visual_spec.get("props"), 88),
            "scene": _clean_text(visual_spec.get("scene"), 120),
            "mood": _clean_text(visual_spec.get("mood"), 48),
            "composition": _clean_text(visual_spec.get("composition"), 88),
            "palette": _clean_text(visual_spec.get("palette"), 56),
        },
    }
    return normalized if any(
        [
            normalized["title"],
            normalized["subtitle"],
            normalized["primary_role"],
            normalized["mission_line"],
        ]
    ) else None


def _normalize_profile_gender(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    mapping = {
        "男": "男性",
        "男性": "男性",
        "male": "男性",
        "man": "男性",
        "m": "男性",
        "女": "女性",
        "女性": "女性",
        "female": "女性",
        "woman": "女性",
        "f": "女性",
    }
    return mapping.get(text, str(value or "").strip())


def _join_unique_text(items, sep="、", limit=None):
    result = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(text)
        if limit and len(result) >= limit:
            break
    return sep.join(result)


def _infer_profile_portrait_age_hint(context):
    grade = str(context.get("grade") or "")
    if re.search(r"博士|phd", grade, re.IGNORECASE):
        return "24-30 岁"
    if re.search(r"硕士|研究生|研一|研二|研三|master", grade, re.IGNORECASE):
        return "23-27 岁"
    if re.search(r"大四|四年级|本科|本一|本二|本三|本四|senior", grade, re.IGNORECASE):
        return "21-25 岁"
    if re.search(r"大一|大二|大三|一年级|二年级|三年级|freshman|sophomore|junior", grade, re.IGNORECASE):
        return "18-23 岁"
    if context.get("resume_experiences") or context.get("resume_projects"):
        return "22-28 岁"
    return "20-26 岁"


def _describe_mbti_tendency(value):
    token = "".join(re.findall(r"[A-Za-z]", str(value or "").upper()))[:4]
    if len(token) != 4:
        return ""
    trait_map = {
        "E": "外向主动",
        "I": "内敛专注",
        "S": "务实细致",
        "N": "抽象探索",
        "T": "理性判断",
        "F": "共情敏锐",
        "J": "结构规划",
        "P": "灵活应变",
    }
    traits = [trait_map.get(letter, "") for letter in token if trait_map.get(letter)]
    if not traits:
        return token
    return f"{token} 倾向，整体更偏{_join_unique_text(traits, '、', 4)}"


def _describe_holland_tendency(code, top_codes=None):
    letters = []
    raw = "".join(re.findall(r"[A-Za-z]", str(code or "").upper()))
    for letter in raw:
        if letter not in letters:
            letters.append(letter)
    for item in top_codes or []:
        text = "".join(re.findall(r"[A-Za-z]", str(item or "").upper()))
        if text and text[0] not in letters:
            letters.append(text[0])
    letters = letters[:3]
    label_map = {
        "R": "动手实践",
        "I": "分析研究",
        "A": "创意表达",
        "S": "协作助人",
        "E": "组织推动",
        "C": "秩序执行",
    }
    labels = [label_map.get(letter, "") for letter in letters if label_map.get(letter)]
    if not letters and not labels:
        return ""
    joined_letters = "".join(letters)
    if not labels:
        return joined_letters
    return f"{joined_letters} 倾向，兴趣上更偏{_join_unique_text(labels, '、', 3)}"


def _infer_profile_portrait_visual_cues(context):
    combined = " ".join(
        [
            context.get("target_direction") or "",
            context.get("archetype_name") or "",
            context.get("archetype_scene") or "",
            _join_unique_text(context.get("top_roles"), " "),
            _join_unique_text(context.get("role_cluster"), " "),
            _join_unique_text(context.get("resume_roles"), " "),
            _join_unique_text(context.get("resume_skills"), " "),
        ]
    )
    if re.search(r"产品|项目|运营|行政|助理|协调|hr|人力|pm", combined, re.IGNORECASE):
        return {
            "outfit": "商务休闲穿搭，利落西装外套或针织叠穿",
            "props": "平板、笔记本、进度表或触控笔",
            "scene": "现代办公室、协作面板、轻度科技感管理界面",
            "mood": "沉稳、可靠、组织感强",
        }
    if re.search(r"数据|分析|财务|审计|研究|算法|开发|后端|测试|工程", combined, re.IGNORECASE):
        return {
            "outfit": "干净利落的职场穿搭，衬衫或简洁外套",
            "props": "笔记本电脑、数据报表、分析界面",
            "scene": "安静的办公桌面、数据图表屏幕、科技办公环境",
            "mood": "理性、专注、可信赖",
        }
    if re.search(r"设计|内容|新媒体|编辑|品牌|创意", combined, re.IGNORECASE):
        return {
            "outfit": "更有设计感的都市职业穿搭，简洁但有创意细节",
            "props": "数位板、便签、创意稿件或视觉素材",
            "scene": "创意工作台、品牌墙、轻量工作界面",
            "mood": "敏锐、清爽、有表达力",
        }
    if re.search(r"销售|客户|商务|市场", combined, re.IGNORECASE):
        return {
            "outfit": "偏正式的商务穿搭",
            "props": "手机、文件夹、演示资料",
            "scene": "会议室或商务洽谈空间",
            "mood": "自信、利落、有推进感",
        }
    return {
        "outfit": "清爽的职场青年穿搭，商务休闲风",
        "props": "平板或笔记本、工作记录工具",
        "scene": "现代办公空间与柔和科技感背景",
        "mood": "专业、克制、可信赖",
    }


def _infer_profile_portrait_role_group_v2(*values):
    combined = " ".join([str(value or "") for value in values])
    if re.search(r"产品|项目|运营|行政|助理|协调|人力|hr|pm", combined, re.IGNORECASE):
        return "coordination"
    if re.search(r"数据|分析|财务|审计|研究|算法|开发|后端|测试|工程", combined, re.IGNORECASE):
        return "analysis"
    if re.search(r"内容|新媒体|编辑|策划|设计|品牌|创意", combined, re.IGNORECASE):
        return "creative"
    if re.search(r"销售|商务|市场|客户|增长|bd", combined, re.IGNORECASE):
        return "growth"
    return "general"


def _build_profile_portrait_title_v2(group, archetype_name=""):
    title_map = {
        "coordination": "执行协调型推进者",
        "analysis": "分析洞察型构建者",
        "creative": "表达策划型连接者",
        "growth": "增长拓展型连接者",
        "general": "职业探索型支持者",
    }
    if archetype_name and archetype_name not in ("综合支持者", "职业探索中"):
        return archetype_name
    return title_map.get(group, title_map["general"])


def _build_profile_portrait_positioning_v2(group, primary_role, context):
    scene = primary_role or context.get("target_direction") or context.get("archetype_scene") or "当前职业方向"
    if group == "coordination":
        return f"你更像能在清晰目标下整合信息、推进协作并把任务落地到结果的人，最适合在 {scene} 相关场景发力。"
    if group == "analysis":
        return f"你更像能在高信息密度场景里建立判断、拆解问题并持续优化结果的人，最适合在 {scene} 相关场景发力。"
    if group == "creative":
        return f"你更像通过表达、内容和创意组织信息的人，适合在 {scene} 相关场景里承担策划与输出角色。"
    if group == "growth":
        return f"你更像能面向目标主动推进、连接资源并推动机会转化的人，适合在 {scene} 相关场景里承担前线角色。"
    return f"你当前更像一个具备适配性与执行力的职业新人，正在围绕 {scene} 收敛更稳定的职业定位。"


def _build_profile_portrait_mission_line_v2(group, primary_role):
    role = primary_role or "当前目标方向"
    if group == "coordination":
        return f"最适合承担 {role} 场景中的信息统筹、进度推进、任务闭环与跨角色协作工作。"
    if group == "analysis":
        return f"最适合承担 {role} 场景中的问题拆解、分析判断、结构搭建与持续优化工作。"
    if group == "creative":
        return f"最适合承担 {role} 场景中的内容组织、表达策划、创意整合与产出打磨工作。"
    if group == "growth":
        return f"最适合承担 {role} 场景中的机会推进、客户沟通、目标跟进与结果转化工作。"
    return f"最适合在 {role} 相关岗位中承担支持执行、快速学习与稳定交付类任务。"


def _build_profile_portrait_evidence_tags_v2(context, primary_role):
    evidence = []
    if context.get("mbti"):
        evidence.append(f"MBTI：{context.get('mbti')}")
    if context.get("holland"):
        evidence.append(f"霍兰德：{context.get('holland')}")
    if primary_role:
        evidence.append(f"岗位线索：{primary_role}")
    if context.get("resume_roles"):
        evidence.append(f"简历角色：{context['resume_roles'][0]}")
    if context.get("resume_projects"):
        evidence.append(f"项目经历：{context['resume_projects'][0][:22]}")
    if context.get("interview_roles"):
        evidence.append(f"访谈偏好：{context['interview_roles'][0]}")
    if context.get("interview_values"):
        evidence.append(f"价值观：{context['interview_values'][0]}")
    if context.get("target_direction"):
        evidence.append(f"目标方向：{context['target_direction']}")
    cleaned = []
    for item in evidence:
        text = str(item or "").strip()[:40]
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= 3:
            break
    return cleaned


def _estimate_profile_portrait_confidence_v2(context, primary_role):
    signal_count = sum(
        1
        for item in [
            context.get("mbti"),
            context.get("holland"),
            context.get("resume_summary"),
            context.get("interview_summary"),
            context.get("target_direction"),
            context.get("resume_projects"),
            context.get("resume_roles"),
        ]
        if item
    )
    target_direction = str(context.get("target_direction") or "").strip()
    matches_target = bool(target_direction and primary_role and (target_direction in primary_role or primary_role in target_direction))
    if signal_count >= 5 and (matches_target or context.get("resume_roles") or context.get("interview_roles")):
        return "高"
    if signal_count >= 3:
        return "中"
    return "待验证"


def _infer_profile_portrait_risk_note_v2(context, primary_role):
    for item in context.get("uncertainty") or []:
        if str(item or "").strip():
            return str(item).strip()
    for item in context.get("missing_items") or []:
        if str(item or "").strip():
            return f"当前仍需补充：{str(item).strip()}"
    target_direction = str(context.get("target_direction") or "").strip()
    if target_direction and primary_role and target_direction not in primary_role and primary_role not in target_direction:
        return "你填写的目标方向与当前最强证据并不完全一致，建议先以证据更强的角色做展示。"
    return "当前画像已可用于展示，但主导特征仍建议继续用新经历补强。"


def _infer_profile_portrait_next_action_v2(context, primary_role):
    for item in context.get("next_steps") or []:
        if str(item or "").strip():
            return str(item).strip()
    if context.get("missing_items"):
        return f"优先补齐 {str(context['missing_items'][0]).strip()}，让这张名片的证据更完整。"
    role = primary_role or context.get("target_direction") or "目标岗位"
    return f"围绕 {role} 补一条可量化项目成果，用结果指标强化这张任务名片。"


def _build_profile_portrait_palette_v2(group):
    palette_map = {
        "coordination": "雾蓝、深海军蓝、冰白",
        "analysis": "深蓝、青灰、冷白",
        "creative": "钴蓝、雾紫灰、纸白",
        "growth": "墨蓝、青绿、银灰白",
        "general": "石板蓝、雾灰、白色",
    }
    return palette_map.get(group, palette_map["general"])


def _build_profile_portrait_brief(context):
    primary_role = (
        (context.get("top_roles") or [""])[0]
        or (context.get("role_cluster") or [""])[0]
        or str(context.get("target_direction") or "").strip()
        or (context.get("resume_roles") or [""])[0]
        or (context.get("interview_roles") or [""])[0]
        or "职业探索中"
    )
    support_roles = []
    for item in (
        (context.get("top_roles") or [])[1:]
        + (context.get("role_cluster") or [])
        + (context.get("interview_roles") or [])
        + (context.get("resume_roles") or [])
    ):
        text = str(item or "").strip()
        if text and text != primary_role and text not in support_roles:
            support_roles.append(text)
        if len(support_roles) >= 2:
            break

    group = _infer_profile_portrait_role_group_v2(
        primary_role,
        context.get("target_direction"),
        context.get("archetype_name"),
        _join_unique_text(context.get("resume_roles"), " "),
        _join_unique_text(context.get("top_roles"), " "),
    )
    visual_cues = _infer_profile_portrait_visual_cues(context)
    title = _build_profile_portrait_title_v2(group, context.get("archetype_name") or "")
    subtitle = _build_profile_portrait_positioning_v2(group, primary_role, context)
    brief = {
        "title": title,
        "subtitle": subtitle[:88],
        "positioning": subtitle,
        "primary_role": primary_role,
        "support_roles": support_roles[:2],
        "mission_line": _build_profile_portrait_mission_line_v2(group, primary_role),
        "evidence_tags": _build_profile_portrait_evidence_tags_v2(context, primary_role),
        "value_tags": (context.get("work_values") or [])[:3] or ["稳定成长", "结果导向", "持续进步"],
        "risk_note": _infer_profile_portrait_risk_note_v2(context, primary_role),
        "next_action": _infer_profile_portrait_next_action_v2(context, primary_role),
        "confidence_band": _estimate_profile_portrait_confidence_v2(context, primary_role),
        "visual_spec": {
            "style": "半写实职业插画，白底页面兼容，适合做任务名片主视觉",
            "subject_age_hint": _infer_profile_portrait_age_hint(context),
            "subject_gender_hint": _normalize_profile_gender(context.get("gender")) or "未指定",
            "outfit": visual_cues["outfit"],
            "props": visual_cues["props"],
            "scene": visual_cues["scene"],
            "mood": visual_cues["mood"],
            "composition": "3:4 纵向构图，单人半身到 2/3 身，人物居中或略偏左，画面干净克制",
            "palette": _build_profile_portrait_palette_v2(group),
        },
    }
    return _normalize_profile_portrait_brief(brief)


def _build_profile_portrait_summary_from_brief(brief):
    normalized = _normalize_profile_portrait_brief(brief) or {}
    return str(normalized.get("subtitle") or normalized.get("positioning") or "").strip()


def _merge_profile_portrait_brief(primary, fallback):
    primary_brief = _normalize_profile_portrait_brief(primary) or {}
    fallback_brief = _normalize_profile_portrait_brief(fallback) or {}
    merged_visual = {}
    for key in ("style", "subject_age_hint", "subject_gender_hint", "outfit", "props", "scene", "mood", "composition", "palette"):
        merged_visual[key] = (
            (primary_brief.get("visual_spec") or {}).get(key)
            or (fallback_brief.get("visual_spec") or {}).get(key)
            or ""
        )
    merged = {
        "title": primary_brief.get("title") or fallback_brief.get("title") or "",
        "subtitle": primary_brief.get("subtitle") or fallback_brief.get("subtitle") or "",
        "positioning": primary_brief.get("positioning") or fallback_brief.get("positioning") or "",
        "primary_role": primary_brief.get("primary_role") or fallback_brief.get("primary_role") or "",
        "support_roles": (primary_brief.get("support_roles") or fallback_brief.get("support_roles") or [])[:2],
        "mission_line": primary_brief.get("mission_line") or fallback_brief.get("mission_line") or "",
        "evidence_tags": (primary_brief.get("evidence_tags") or fallback_brief.get("evidence_tags") or [])[:3],
        "value_tags": (primary_brief.get("value_tags") or fallback_brief.get("value_tags") or [])[:3],
        "risk_note": primary_brief.get("risk_note") or fallback_brief.get("risk_note") or "",
        "next_action": primary_brief.get("next_action") or fallback_brief.get("next_action") or "",
        "confidence_band": primary_brief.get("confidence_band") or fallback_brief.get("confidence_band") or "",
        "visual_spec": merged_visual,
    }
    return _normalize_profile_portrait_brief(merged) or fallback_brief or primary_brief or None


def _pipeline_interview_supplement(context: dict) -> str:
    """访谈弱信号时，用主画像与测评侧线索强制补一段可写入提示词的叙事。"""
    parts = []
    thesis = str(context.get("summary") or "").strip()
    if thesis:
        parts.append(f"主画像收敛：{thesis[:520]}")
    roles = context.get("top_roles") or []
    if roles:
        parts.append(f"岗位线索：{'、'.join([str(r) for r in roles[:3] if r])}")
    vals = context.get("work_values") or []
    if vals:
        parts.append(f"价值观：{'、'.join([str(v) for v in vals[:4] if v])}")
    mbti = str(context.get("mbti") or "").strip()
    hol = str(context.get("holland") or "").strip()
    if mbti or hol:
        parts.append(f"测评交叉：MBTI {mbti or '—'}；霍兰德 {hol or '—'}。")
    return "\n".join(parts)


def _build_profile_portrait_module_outputs(context):
    raw_modules = context.get("module_outputs") if isinstance(context.get("module_outputs"), dict) else {}
    assessment_raw = raw_modules.get("assessment") if isinstance(raw_modules.get("assessment"), dict) else {}
    resume_raw = raw_modules.get("resume") if isinstance(raw_modules.get("resume"), dict) else {}
    interview_raw = raw_modules.get("interview") if isinstance(raw_modules.get("interview"), dict) else {}

    assessment = {
        "status": str(assessment_raw.get("status") or ("complete" if (context.get("mbti") and context.get("holland")) else ("partial" if (context.get("mbti") or context.get("holland")) else "missing"))).strip(),
        "summary": str(assessment_raw.get("summary") or "｜".join([item for item in [f"MBTI {context.get('mbti')}" if context.get("mbti") else "", f"霍兰德 {context.get('holland')}" if context.get("holland") else ""] if item]) or "尚未形成稳定测评输出").strip(),
        "chips": (assessment_raw.get("chips") if isinstance(assessment_raw.get("chips"), list) else [item for item in [context.get("mbti"), context.get("holland")] if item])[:8],
        "note": str(assessment_raw.get("note") or ("提供人格倾向与职业兴趣的基础锚点。" if (context.get("mbti") or context.get("holland")) else "测评未完成时，人物画像只使用其它模块做弱收敛。")).strip(),
    }
    detail_merge = str(assessment_raw.get("detail_prose") or context.get("assessment_prose") or "").strip()
    if detail_merge:
        assessment["summary"] = f"{assessment['summary']}\n\n【测评长文本与类型补述】\n{detail_merge[:2400]}".strip()

    resume = {
        "status": str(resume_raw.get("status") or ("complete" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "missing")).strip(),
        "summary": str(resume_raw.get("summary") or context.get("resume_summary") or "尚未形成可用的简历证据").strip(),
        "chips": (resume_raw.get("chips") if isinstance(resume_raw.get("chips"), list) else ((context.get("resume_roles") or []) + (context.get("resume_skills") or [])[:3]))[:8],
        "note": str(resume_raw.get("note") or ("提供角色线索、项目证据与技能关键词。" if (context.get("resume_summary") or context.get("resume_roles") or context.get("resume_projects")) else "没有简历时，人物画像缺少经历证据，只能更多依赖测评和访谈。")).strip(),
    }
    interview_completion_score = safe_score(interview_raw.get("completion_score"), 0)
    interview = {
        "status": str(interview_raw.get("status") or ("complete" if interview_raw.get("usable_for_portrait") else ("partial" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "missing"))).strip(),
        "summary": str(interview_raw.get("summary") or context.get("interview_summary") or "尚未形成访谈摘要").strip(),
        "chips": (interview_raw.get("chips") if isinstance(interview_raw.get("chips"), list) else ((context.get("interview_values") or []) + (context.get("interview_roles") or []) + (context.get("interview_evidence") or [])))[:8],
        "note": str(interview_raw.get("note") or ("即使提前结束，只要已经形成价值观、经历或协作风格信号，就可以进入首版画像。" if (context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")) else "没有访谈信号时，画像更像静态推断。")).strip(),
        "completion_score": interview_completion_score,
        "usable_for_portrait": bool(interview_raw.get("usable_for_portrait") or context.get("interview_summary") or context.get("interview_values") or context.get("interview_evidence")),
        "missing_followups": (interview_raw.get("missing_followups") if isinstance(interview_raw.get("missing_followups"), list) else context.get("missing_items") or [])[:4],
    }
    forced = str(interview_raw.get("forced_supplement") or "").strip()
    iv_note = str(interview_raw.get("note") or interview.get("note") or "")
    weak_iv = len(interview["summary"]) < 36 or "弱信号" in iv_note
    if weak_iv:
        extra = forced or _pipeline_interview_supplement(context)
        if extra:
            interview["summary"] = f"{interview['summary']}\n\n【访谈强制补述】\n{extra}".strip()
            interview["usable_for_portrait"] = True
    return {"assessment": assessment, "resume": resume, "interview": interview}


def _normalize_profile_portrait_prompt_packet(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}

    def _clean_text(value, limit=2600):
        return str(value or "").strip()[:limit]

    return {
        "brief": _normalize_profile_portrait_brief(payload.get("brief")),
        "prompt_summary": _clean_text(payload.get("prompt_summary"), 360),
        "render_prompt": _clean_text(payload.get("render_prompt"), 8000),
        "prompt_pipeline": payload.get("prompt_pipeline") if isinstance(payload.get("prompt_pipeline"), dict) else None,
        "prompt_evaluation": payload.get("prompt_evaluation") if isinstance(payload.get("prompt_evaluation"), dict) else None,
    }


def _build_profile_portrait_prompt_packet(context, preset_brief=None):
    fallback_brief = _normalize_profile_portrait_brief(preset_brief) or _build_profile_portrait_brief(context)
    prompt_layers = build_portrait_prompt_layers(context, fallback_brief)
    packet = {
        "brief": fallback_brief,
        "prompt_summary": _build_profile_portrait_summary_from_brief(fallback_brief) or context.get("summary") or "",
        "render_prompt": _build_profile_portrait_render_prompt(context, fallback_brief),
        "mode": "heuristic",
        "writer_model": "",
        "prompt_pipeline": prompt_layers,
        "prompt_evaluation": None,
    }

    base_url, api_key, model = llm_env.chat_runtime()
    if not base_url or not api_key or not model:
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
        return packet

    module_outputs = _build_profile_portrait_module_outputs(context)
    prompt_request = context.get("prompt_request") if isinstance(context.get("prompt_request"), dict) else {}
    system_prompt = """
你是职业规划产品的画像提示词编辑器。请根据 3 个输入模块的标准化输出，生成一份“人物明信片 brief”和一段“给图像模型使用的渲染提示词”。

要求：
1. 先消化测评输出、简历输出、访谈输出，不要逐条机械复述，但要**把关键气质、岗位语境与证据写进叙事**。
2. 若访谈为弱信号或已合并「强制补述」，必须把补述当作可画面化的线索写进 render_prompt（协作风格、价值取向、推断性神态），并标明哪些是推断。
3. brief 必须用于白底产品页面，信息要清晰、克制、可展示；brief 本身不是长文，但 **render_prompt 必须是长而完整的叙事级提示词**（建议不少于 500 汉字），像美术指导写给插画师的分镜说明。
4. render_prompt 必须是给图像模型的**完整中文**提示词：明确 3:4 纵向、单人、半写实偏写实比例、电影感自然光、无文字无水印、适合人物明信片主视觉；写出**具体场景、机位、服装材质、道具、微表情与体态**。
5. 若输入不足，允许保守收敛，标注不确定性，但不要省略画面约束与气质描写。
6. global_context.identity_narrative、assessment_prose、extended_tests_prose 含「你是谁」级叙事与主测/扩展测评的文字描述；生成 render_prompt 时必须把这些**具体气质、场景、专业语境**融入画面，**禁止**只写 MBTI/霍兰德四字代码或标签堆砌。
7. 若 extended_tests_prose 非空，图像提示中应体现扩展测评里的角色气质或情绪隐喻（抽象转化为职业场景与光影），仍禁止在画面中出现文字。
8. 画风：偏「高端出版物插画 + 写实肤质与布料」、柔和窗光或阴天柔光、浅景深、干净背景；避免廉价滤镜、过度磨皮、赛博霓虹与 Q 版大头。

严格输出 JSON：
{
  "brief": {
    "title": "人物卡标题",
    "subtitle": "80字内副标题",
    "positioning": "140字内定位说明",
    "primary_role": "最像岗位",
    "support_roles": ["辅助岗位1", "辅助岗位2"],
    "mission_line": "一句任务描述",
    "evidence_tags": ["证据1", "证据2", "证据3"],
    "value_tags": ["价值观1", "价值观2", "价值观3"],
    "risk_note": "当前仍需注意的地方",
    "next_action": "下一步建议",
    "confidence_band": "高/中/待验证",
    "visual_spec": {
      "style": "视觉风格",
      "subject_age_hint": "年龄提示",
      "subject_gender_hint": "性别提示",
      "outfit": "穿搭",
      "props": "道具",
      "scene": "场景",
      "mood": "气质",
      "composition": "构图",
      "palette": "配色"
    }
  },
  "prompt_summary": "一句话说明 AI 最终如何收敛这个人物画像",
  "render_prompt": "写给图像模型的完整中文提示词"
}
""".strip()

    system_prompt += "如果 profile.target_cities 非空，必须优先选择这些城市内的候选；只有城市内候选不足时，才用其他城市补足。"
    user_payload = {
        "assessment_output": module_outputs.get("assessment") or {},
        "resume_output": module_outputs.get("resume") or {},
        "interview_output": module_outputs.get("interview") or {},
        "prompt_pipeline": prompt_layers,
        "global_context": {
            "summary": context.get("summary") or "",
            "archetype_name": context.get("archetype_name") or "",
            "archetype_scene": context.get("archetype_scene") or "",
            "top_roles": context.get("top_roles") or [],
            "role_cluster": context.get("role_cluster") or [],
            "work_values": context.get("work_values") or [],
            "axis_traits": context.get("axis_traits") or [],
            "workstyle_traits": context.get("workstyle_traits") or [],
            "target_direction": context.get("target_direction") or "",
            "target_city": context.get("target_city") or "",
            "major": context.get("major") or "",
            "grade": context.get("grade") or "",
            "gender": context.get("gender") or "",
            "uncertainty": context.get("uncertainty") or [],
            "missing_items": context.get("missing_items") or [],
            "identity_narrative": context.get("identity_narrative") or "",
            "assessment_prose": context.get("assessment_prose") or "",
            "extended_tests_prose": context.get("extended_tests_prose") or "",
        },
        "prompt_request": {
            "card_style": str(prompt_request.get("card_style") or "人物明信片").strip(),
            "card_goal": str(prompt_request.get("card_goal") or "美观清晰，一眼看懂这个人最像什么岗位、能做什么任务、下一步该补什么。").strip(),
            "visual_direction": str(prompt_request.get("visual_direction") or "适合白底页面展示，职业感明确，信息克制，避免花哨宣传海报感。").strip(),
            "required_fields": prompt_request.get("required_fields") or ["标题", "定位句", "主角色", "任务句", "证据标签", "下一步"],
        },
    }

    try:
        parsed = call_structured_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
            system_prompt=system_prompt,
            max_tokens=4200,
        )
        normalized_packet = _normalize_profile_portrait_prompt_packet(parsed)
        merged_brief = _merge_profile_portrait_brief(normalized_packet.get("brief"), fallback_brief)
        packet["brief"] = merged_brief or fallback_brief
        packet["prompt_summary"] = (
            normalized_packet.get("prompt_summary")
            or _build_profile_portrait_summary_from_brief(packet["brief"])
            or packet["prompt_summary"]
        )
        packet["render_prompt"] = (
            normalized_packet.get("render_prompt")
            or _build_profile_portrait_render_prompt(context, packet["brief"])
        )
        packet["mode"] = "llm"
        packet["writer_model"] = model
        packet["prompt_pipeline"] = prompt_layers
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
        if packet["prompt_evaluation"].get("needs_refinement"):
            refiner_payload = {
                "current_output": {
                    "brief": packet.get("brief"),
                    "prompt_summary": packet.get("prompt_summary"),
                    "render_prompt": packet.get("render_prompt"),
                },
                "evaluation": packet.get("prompt_evaluation"),
                "prompt_pipeline": prompt_layers,
                "target": "补齐缺失字段，强化角色-证据一致性，并保留 3:4、单人、半写实、无文字等视觉硬约束。",
            }
            refined = call_structured_chat(
                base_url,
                api_key,
                model,
                [{"role": "user", "content": json.dumps(refiner_payload, ensure_ascii=False)}],
                system_prompt=(
                    "你是职业画像提示词优化器。"
                    "请根据上一版输出和自动评分结果，修复缺失字段、增强证据一致性，并输出同样结构的 JSON。"
                    "尤其要把 render_prompt 扩写到叙事级完整度（画面、光影、道具、神态），不要删除已成立的角色判断。"
                ),
                max_tokens=3600,
            )
            refined_packet = _normalize_profile_portrait_prompt_packet(refined)
            packet["brief"] = _merge_profile_portrait_brief(refined_packet.get("brief"), packet["brief"]) or packet["brief"]
            packet["prompt_summary"] = (
                refined_packet.get("prompt_summary")
                or packet.get("prompt_summary")
                or _build_profile_portrait_summary_from_brief(packet["brief"])
            )
            packet["render_prompt"] = (
                refined_packet.get("render_prompt")
                or packet.get("render_prompt")
                or _build_profile_portrait_render_prompt(context, packet["brief"])
            )
            packet["mode"] = "llm_refined"
            packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
            if isinstance(packet.get("prompt_evaluation"), dict):
                packet["prompt_evaluation"]["rewrite_used"] = True
    except Exception:
        logger.exception("profile portrait prompt writer failed")

    if not isinstance(packet.get("prompt_evaluation"), dict):
        packet["prompt_evaluation"] = evaluate_portrait_prompt_packet(context, packet)
    if isinstance(packet.get("prompt_evaluation"), dict):
        packet["prompt_evaluation"].setdefault("rewrite_used", False)
    packet["prompt_pipeline"] = prompt_layers
    return packet


def _build_profile_portrait_render_prompt(context, brief=None):
    normalized_brief = _normalize_profile_portrait_brief(brief) or _build_profile_portrait_brief(context)
    visual_spec = normalized_brief.get("visual_spec") or {}
    gender = _normalize_profile_gender(context.get("gender")) or "未指定"
    title = normalized_brief.get("title") or context.get("archetype_name") or "职业任务名片"
    subtitle = normalized_brief.get("subtitle") or context.get("summary") or ""
    evidence_text = _join_unique_text(normalized_brief.get("evidence_tags"), "；", 3)
    value_text = _join_unique_text(normalized_brief.get("value_tags"), "、", 3)
    support_roles = _join_unique_text(normalized_brief.get("support_roles"), " / ", 2)
    identity_narrative = str(context.get("identity_narrative") or "").strip()
    assessment_prose = str(context.get("assessment_prose") or "").strip()
    extended_prose = str(context.get("extended_tests_prose") or "").strip()
    narrative_sections = []
    if identity_narrative:
        narrative_sections.append(f"【叙事·你是谁（访谈与收敛结论，用于气质与神态）】\n{identity_narrative}")
    if assessment_prose:
        narrative_sections.append(f"【主测评文字（MBTI/霍兰德的具体描述，勿仅当作四字代码）】\n{assessment_prose}")
    if extended_prose:
        narrative_sections.append(f"【扩展测评（深层 MBTI / 趣味测评 / SBTI 等详细描述）】\n{extended_prose}")
    narrative_block = "\n\n".join(narrative_sections)
    return (
        "请为职业规划产品生成一张 3:4 纵向单人半写实插画海报，用于白底页面里的任务名片主视觉。"
        "不要文字、不要水印、不要拼贴、不要多人、不要 UI 截图、不要夸张卡通。\n"
        "以下「叙事依据」用于推断人物气质、微表情、肢体语言、工作环境与道具；画面中不得出现任何可读文字。\n"
        + (f"{narrative_block}\n\n" if narrative_block else "")
        + "人物身份（卡片字段）：\n"
        f"- 标题：{title}\n"
        f"- 职业定位：{subtitle}\n"
        f"- 主角色：{normalized_brief.get('primary_role') or '职业探索中'}\n"
        f"- 辅助角色：{support_roles or '不强调'}\n"
        f"- 任务描述：{normalized_brief.get('mission_line') or ''}\n"
        f"- 证据关键词：{evidence_text or '职业新人、方向收敛'}\n"
        f"- 工作价值观：{value_text or '稳定成长、结果导向'}\n"
        f"- 性别提示：{gender}\n"
        f"- 年龄提示：{visual_spec.get('subject_age_hint') or _infer_profile_portrait_age_hint(context)}\n"
        "视觉与画风（须严格遵守）：\n"
        f"- 风格：{visual_spec.get('style') or '半写实职业插画，偏高端出版物/编辑插图质感，肤质与布料纹理清晰，避免塑料磨皮与廉价滤镜'}\n"
        f"- 气质：{visual_spec.get('mood') or '专业、可信赖、沉稳；微表情自然，目光有焦点，肢体语言放松但不松散'}\n"
        f"- 光效：自然窗光或阴天柔光，柔和体积光，适度 rim light；避免刺目顶光、霓虹赛博光、过度镜头光斑\n"
        f"- 穿搭：{visual_spec.get('outfit') or '商务休闲或工程师风职业穿搭，材质可见（棉、针织、夹克），避免夸张 logo'}\n"
        f"- 道具：{visual_spec.get('props') or '笔记本电脑、平板、记事本、中性水杯等职场道具，数量少而有序'}\n"
        f"- 场景：{visual_spec.get('scene') or '明亮现代办公或实验室风工作台，背景干净略虚化（浅景深）'}\n"
        f"- 构图：{visual_spec.get('composition') or '3:4 纵向，单人，胸像到 2/3 身，视线方向留白，主体居中偏三分线'}\n"
        f"- 配色：{visual_spec.get('palette') or '雾蓝、燕麦白、板岩灰与少量暖木色点缀，整体低饱和'}\n"
        "输出要求：人物主体明确，手部结构合理，画面信息密度适中，适合白底产品页左侧主视觉。"
        "负面要求：低清晰度、杂乱背景、比例失调、畸形手部、Q 版大头、贴纸海报风、可读文字、水印、多人同框。"
    )


def _build_profile_portrait_subject_summary(context):
    identity = []
    gender = _normalize_profile_gender(context.get("gender"))
    if gender:
        identity.append(gender)
    identity.append(_infer_profile_portrait_age_hint(context))
    identity.append("中国青年职场形象")
    role_focus = _join_unique_text(
        context.get("top_roles") or context.get("role_cluster") or [context.get("target_direction") or context.get("archetype_name")],
        " / ",
        3,
    )
    trait_parts = []
    if context.get("archetype_name"):
        trait_parts.append(context.get("archetype_name"))
    mbti_desc = _describe_mbti_tendency(context.get("mbti"))
    holland_desc = _describe_holland_tendency(context.get("holland"), context.get("holland_top_codes"))
    if mbti_desc:
        trait_parts.append(mbti_desc)
    if holland_desc:
        trait_parts.append(holland_desc)
    if context.get("work_values"):
        trait_parts.append(f"工作中看重{_join_unique_text(context.get('work_values'), '、', 4)}")
    if context.get("axis_traits"):
        trait_parts.append(f"工作方式偏向{_join_unique_text(context.get('axis_traits'), '；', 2)}")
    evidence_parts = []
    resume_summary = str(context.get("resume_summary") or "").strip()
    if resume_summary and resume_summary.lower() != "unknown":
        evidence_parts.append(f"简历显示{resume_summary}")
    if context.get("resume_projects"):
        evidence_parts.append(f"项目经历集中在{_join_unique_text(context.get('resume_projects'), '；', 2)}")
    if context.get("interview_summary"):
        evidence_parts.append(f"访谈体现出{context.get('interview_summary')}")
    elif context.get("interview_evidence"):
        evidence_parts.append(f"访谈证据包括{_join_unique_text(context.get('interview_evidence'), '；', 2)}")
    pieces = [
        "，".join([part for part in identity if part]),
        f"职业定位接近 {role_focus}" if role_focus else "",
        "；".join([part for part in trait_parts if part]),
        "；".join([part for part in evidence_parts if part]),
    ]
    return "。".join([piece for piece in pieces if piece])


def _has_profile_portrait_signal(context):
    return any(
        [
            context.get("summary"),
            context.get("archetype_name"),
            context.get("target_direction"),
            context.get("resume_summary"),
            context.get("interview_summary"),
            context.get("resume_projects"),
            context.get("resume_roles"),
            context.get("work_values"),
            context.get("identity_narrative"),
            context.get("assessment_prose"),
            context.get("extended_tests_prose"),
        ]
    )


def _build_profile_portrait_prompt(context):
    gender = _normalize_profile_gender(context.get("gender")) or "未指定"
    age_hint = _infer_profile_portrait_age_hint(context)
    archetype_name = context.get("archetype_name") or "综合支持者"
    role_focus = _join_unique_text(
        context.get("top_roles") or context.get("role_cluster") or [context.get("target_direction") or "职业探索方向"],
        " / ",
        3,
    )
    work_values = _join_unique_text(context.get("work_values"), "、", 4) or "成长、清晰感、执行落地"
    subject_summary = _build_profile_portrait_subject_summary(context)
    mbti_desc = _describe_mbti_tendency(context.get("mbti"))
    holland_desc = _describe_holland_tendency(context.get("holland"), context.get("holland_top_codes"))
    visual_cues = _infer_profile_portrait_visual_cues(context)
    detail_lines = [
        f"- 性别：{gender}",
        f"- 年龄感：{age_hint}",
        f"- 人物原型：{archetype_name}",
        f"- 目标职业场景：{role_focus}",
        f"- 综合摘要：{subject_summary or (context.get('summary') or '')}",
        f"- MBTI 信息：{mbti_desc}" if mbti_desc else "",
        f"- 霍兰德信息：{holland_desc}" if holland_desc else "",
        f"- 工作价值观：{work_values}",
        f"- 工作方式：{_join_unique_text(context.get('axis_traits'), '；', 3)}" if context.get("axis_traits") else "",
        f"- 工作风格拼图：{_join_unique_text(context.get('workstyle_traits'), '；', 3)}" if context.get("workstyle_traits") else "",
        f"- 访谈角色判断：{_join_unique_text(context.get('interview_roles'), '、', 3)}" if context.get("interview_roles") else "",
        f"- 访谈价值观证据：{_join_unique_text(context.get('interview_values'), '、', 4)}" if context.get("interview_values") else "",
        f"- 访谈关键证据：{_join_unique_text(context.get('interview_evidence'), '；', 2)}" if context.get("interview_evidence") else "",
        f"- 简历角色线索：{_join_unique_text(context.get('resume_roles'), '、', 4)}" if context.get("resume_roles") else "",
        f"- 简历项目线索：{_join_unique_text(context.get('resume_projects'), '；', 2)}" if context.get("resume_projects") else "",
        f"- 简历经历线索：{_join_unique_text(context.get('resume_experiences'), '；', 2)}" if context.get("resume_experiences") else "",
        f"- 简历技能关键词：{_join_unique_text(context.get('resume_skills'), '、', 6)}" if context.get("resume_skills") else "",
        f"- 专业：{context.get('major')}" if context.get("major") else "",
        f"- 学历：{context.get('grade')}" if context.get("grade") else "",
        f"- 目标城市：{context.get('target_city')}" if context.get("target_city") else "",
        f"- 目标方向：{context.get('target_direction')}" if context.get("target_direction") else "",
    ]
    detail_block = "\n".join([line for line in detail_lines if line])
    return (
        "请为职业规划仪表盘绘制一张 3:4 纵向人物画像插画，只出现 1 位人物，不要文字、不要水印、不要拼贴、不要重复面孔、不要多余手指。\n"
        "先把下面的人物信息融合成一个统一角色，再作画，不要机械堆叠标签，也不要把 MBTI、霍兰德字母直接画在画面里。\n"
        "人物信息：\n"
        f"{detail_block}\n"
        "视觉表达要求：\n"
        f"- 整体定位：中国年轻学生或职场新人，气质 {visual_cues['mood']}。\n"
        f"- 穿搭：{visual_cues['outfit']}。\n"
        f"- 道具：{visual_cues['props']}。\n"
        f"- 场景：{visual_cues['scene']}，可带轻度数据面板或协作界面氛围。\n"
        "- 构图：半身到三分之二身，人物居中或略偏左，主体突出。\n"
        "- 风格：精致数字插画，写实与动漫融合，光线柔和，高级企业海报质感，蓝白到青蓝渐变背景。\n"
        "- 氛围：冷静、聪明、可信赖，同时能让人看出其职业方向和工作方式。\n"
        "负面要求：低清晰度、背景杂乱、夸张卡通、过度赛博朋克、文字乱码、畸形手部、比例失衡。"
    )


def _generate_profile_portrait_image(base_url, api_key, model, prompt):
    if not base_url or not api_key:
        raise ValueError("系统中还没有可用的 OpenRouter 图片配置。")
    endpoint = f"{normalize_sdk_base_url(base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "3:4"},
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail or "{}")
            message = str(parsed.get("error", {}).get("message") or parsed.get("message") or "").strip()
        except Exception:
            message = ""
        raise ValueError(message or f"图片接口调用失败：HTTP {exc.code}") from exc
    except Exception as exc:
        raise ValueError(f"图片接口调用失败：{str(exc)[:240]}") from exc

    try:
        result = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("图片接口返回了无法解析的数据。") from exc

    choices = result.get("choices") if isinstance(result, dict) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    images = message.get("images") if isinstance(message, dict) else []
    if not images:
        raise ValueError("模型没有返回图片结果。")
    image_url = str((((images[0] or {}).get("image_url") or {}).get("url")) or "").strip()
    if not image_url:
        raise ValueError("图片结果为空。")
    return image_url


def create_blueprint(login_required, current_user, load_user_state, save_user_state):
    blueprint = Blueprint("portrait", __name__)

    @blueprint.route("/api/profile-portrait/generate", methods=["POST"])
    @login_required
    def api_profile_portrait_generate():
        user = current_user()
        payload = request.get_json(silent=True) or {}
        reuse_brief = bool(payload.get("reuse_brief"))
        context = normalize_profile_portrait_context(payload.get("context"))
        state = load_user_state(user["username"])
        saved_portrait = state.get("profile_portrait") if isinstance(state.get("profile_portrait"), dict) else {}
        saved_brief = _normalize_profile_portrait_brief(saved_portrait.get("brief"))
        if not _has_profile_portrait_signal(context) and not saved_brief:
            return jsonify({"message": "当前画像信息不足，先补充测评、简历或目标方向。"}), 400

        base_url, api_key, model = _portrait_runtime()
        if not base_url or not api_key:
            return jsonify({"message": "系统中未找到 OpenRouter 图片配置，请先在 system 账号里配置 OpenRouter Provider。"}), 400

        try:
            prompt_packet = _build_profile_portrait_prompt_packet(
                context,
                preset_brief=saved_brief if (reuse_brief and saved_brief) else None,
            )
            brief = prompt_packet.get("brief") or saved_brief or _build_profile_portrait_brief(context)
            prompt_summary = prompt_packet.get("prompt_summary") or _build_profile_portrait_summary_from_brief(brief) or context.get("summary") or ""
            prompt = prompt_packet.get("render_prompt") or _build_profile_portrait_render_prompt(context, brief)
            prompt_writer_mode = str(prompt_packet.get("mode") or "heuristic").strip() or "heuristic"
            prompt_writer_model = str(prompt_packet.get("writer_model") or "").strip()
            prompt_pipeline = prompt_packet.get("prompt_pipeline") if isinstance(prompt_packet.get("prompt_pipeline"), dict) else None
            prompt_evaluation = prompt_packet.get("prompt_evaluation") if isinstance(prompt_packet.get("prompt_evaluation"), dict) else None
        except ValueError as exc:
            return jsonify({"message": str(exc)}), 400
        except Exception:
            logger.exception("profile portrait brief generation failed")
            return jsonify({"message": "用户画像生成失败，请稍后重试。"}), 502

        image_url = str(saved_portrait.get("image_url") or "").strip() if reuse_brief else ""
        image_error = ""
        status = "ready"
        try:
            image_url = _generate_profile_portrait_image(base_url, api_key, model, prompt)
        except ValueError as exc:
            image_error = str(exc)
            status = "ready" if image_url else "brief_ready"
        except Exception:
            image_error = "鐢诲儚娴锋姤娓叉煋澶辫触锛岃绋嶅悗閲嶈瘯銆?"
            logger.exception("profile portrait generation failed")
            status = "ready" if image_url else "brief_ready"

        portrait_state = {
            "status": status,
            "image_url": image_url,
            "created_at": int(time.time()),
            "model": model,
            "archetype_name": context.get("archetype_name") or "",
            "prompt_summary": prompt_summary,
            "prompt_text": prompt,
            "prompt_mode": "reuse_brief" if (reuse_brief and saved_brief) else "rebuild_brief",
            "prompt_writer_mode": prompt_writer_mode,
            "prompt_writer_model": prompt_writer_model,
            "brief_version": PORTRAIT_TEMPLATE_VERSION,
            "prompt_pipeline": prompt_pipeline or {"pipeline_version": PORTRAIT_PROMPT_PIPELINE_VERSION},
            "prompt_evaluation": prompt_evaluation,
            "image_error": image_error,
            "brief": brief,
            "context_snapshot": context,
        }
        state["profile_portrait"] = portrait_state
        save_user_state(user["username"], state)
        if image_error and image_url:
            message = "已保留上一版海报，本次重绘失败，可稍后再试。"
        elif image_error:
            message = "职业定位已收敛，但海报渲染失败，可直接重试海报。"
        else:
            message = "用户画像已生成。"
        return jsonify({
            "message": message,
            "data": public_profile_portrait_state(portrait_state),
        })

    return blueprint
