"""
Career Report Multi-Agent System

6 specialist agents following the pipeline defined in:
career_pipeline_student_report.md

Pipeline order:
  A (parallel-friendly): 行业分析师 + 简历证据分析官 (first pass)
  B (serial):            职业定位顾问
  B' (optional):         简历证据分析官 (second pass with positioning must_prove)
  C (serial):            能力评估官
  D (serial):            岗位匹配官
  E (serial):            路径规划师

System prompts are project-local Python constants from:
  services.report.career_development_prompts
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any, Callable

from . import career_development_prompts as prompt_texts

# LLM caller type: (messages, system_prompt, max_tokens) -> str
LLMCaller = Callable[[list[dict], str, int], str]


# ---------------------------------------------------------------------------
# Project-local prompt constants
# ---------------------------------------------------------------------------

_FV = getattr(prompt_texts, "FORMAL_MARKDOWN_VOICE", "")
SYSTEM_PROMPT_INDUSTRY_ANALYST = prompt_texts.SYSTEM_PROMPT_INDUSTRY_ANALYST + _FV
SYSTEM_PROMPT_CAREER_POSITIONING = prompt_texts.SYSTEM_PROMPT_CAREER_POSITIONING + _FV
SYSTEM_PROMPT_RESUME_EVIDENCE = prompt_texts.SYSTEM_PROMPT_RESUME_EVIDENCE + _FV
SYSTEM_PROMPT_COMPETENCY_ASSESSOR = prompt_texts.SYSTEM_PROMPT_COMPETENCY_ASSESSOR + _FV
SYSTEM_PROMPT_ROLE_MATCH = prompt_texts.SYSTEM_PROMPT_ROLE_MATCH + _FV
SYSTEM_PROMPT_CAREER_PATH_PLANNER = prompt_texts.SYSTEM_PROMPT_CAREER_PATH_PLANNER + _FV
SYSTEM_PROMPT_REPORT_EDITOR = getattr(prompt_texts, "SYSTEM_PROMPT_REPORT_EDITOR", "") + _FV
SECTION_WRITER_SYSTEM_PROMPT = getattr(prompt_texts, "SECTION_WRITER_SYSTEM_PROMPT", "") + _FV
CAREER_PIPELINE_PROMPT = prompt_texts.CAREER_PIPELINE_PROMPT
PROMPT_SOURCE_MODULE = prompt_texts.PROMPT_SOURCE_MODULE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_profile_resume_text(profile_payload: dict[str, Any], *, max_chars: int = 12000) -> str:
    """从画像与简历分析流水线中解析可用于 LLM 的简历纯文本。

    - 优先使用 ``profile_payload["resume"]`` 的 ``text`` / ``content`` / ``raw``（用户中心画像里填写的简历）。
    - 若为空，则回退到 ``agent_memory.resume_memory.resume_source_text``（简历上传/解析流程写入的全文，
      常见情况：用户已跑简历门诊但画像对象里未同步 ``resume.text``）。

    能力评估官 **不直接检索简历全文**，而是消费「简历证据分析官」的结构化输出；若上游拿不到正文，
    证据 JSON 会为空，能力维度往往全部为 unknown，看起来像「内容为空」。"""
    resume = profile_payload.get("resume") if isinstance(profile_payload.get("resume"), dict) else {}
    text = str(resume.get("text") or resume.get("content") or resume.get("raw") or "").strip()
    if text:
        return text[:max_chars]
    agent_memory = profile_payload.get("agent_memory") if isinstance(profile_payload.get("agent_memory"), dict) else {}
    rm = agent_memory.get("resume_memory") if isinstance(agent_memory.get("resume_memory"), dict) else {}
    alt = str(rm.get("resume_source_text") or "").strip()
    if alt:
        return alt[:max_chars]
    return ""


def _try_parse_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _find_balanced_json_objects(text: str) -> list[str]:
    source = str(text or "")
    if not source:
        return []
    matches: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(source):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                matches.append(source[start:index + 1])
                start = -1
    return matches


def _extract_json_block(text: str) -> dict[str, Any]:
    """Extract the last valid JSON object from LLM output."""
    source = str(text or "")
    if not source.strip():
        return {}

    candidates: list[str] = []
    candidates.extend(re.findall(r"```json\s*([\s\S]*?)```", source, re.IGNORECASE))
    candidates.extend(re.findall(r"```(?:javascript|js)?\s*([\s\S]*?)```", source, re.IGNORECASE))
    candidates.extend(_find_balanced_json_objects(source))
    candidates.append(source)

    seen: set[str] = set()
    for raw in reversed(candidates):
        candidate = str(raw or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        parsed = _try_parse_json_object(candidate)
        if parsed:
            return parsed
    return {}


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            result.extend(_coerce_text_list(item))
        deduped: list[str] = []
        for item in result:
            if item and item not in deduped:
                deduped.append(item)
        return deduped
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
            if isinstance(parsed, (list, tuple, set)):
                return _coerce_text_list(list(parsed))
        return [text]
    text = str(value).strip()
    return [text] if text else []


def _coerce_fit_score(value: Any, *, default: int = 0) -> int:
    """将岗位匹配 JSON 中的 fit_score 规范为 0–100 整数。

    模型有时输出嵌套对象（如 {{\"score\": 88}}）或非数字字符串，直接 int() 会报错。
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:  # NaN
            return default
        n = int(round(float(value)))
        return max(0, min(100, n))
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return default
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if m:
            return _coerce_fit_score(float(m.group(0)), default=default)
        return default
    if isinstance(value, dict):
        for key in ("fit_score", "score", "value", "overall", "total"):
            if key in value:
                return _coerce_fit_score(value.get(key), default=default)
        if len(value) == 1:
            return _coerce_fit_score(next(iter(value.values())), default=default)
        nums: list[float] = []
        for v in value.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                nums.append(float(v))
        if nums:
            return _coerce_fit_score(sum(nums) / len(nums), default=default)
        return default
    return default


def _canonical_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _normalize_target_role(value: Any, role_payload: list[dict[str, Any]]) -> str:
    role_names = [
        str(role.get("name") or role.get("title") or "").strip()
        for role in (role_payload or [])
        if isinstance(role, dict) and str(role.get("name") or role.get("title") or "").strip()
    ]
    requested = _coerce_text_list(value)

    if requested:
        for item in requested:
            canonical = _canonical_text(item)
            if not canonical:
                continue
            for role_name in role_names:
                if _canonical_text(role_name) == canonical:
                    return role_name
        return requested[0]

    return role_names[0] if role_names else ""


def _safe_call(llm: LLMCaller, messages: list[dict], system_prompt: str, max_tokens: int = 4096) -> str:
    """Call LLM with error handling, return empty string on failure."""
    try:
        result = llm(messages, system_prompt, max_tokens)
        return result or ""
    except Exception:
        return ""


def _profile_to_text(profile_payload: dict[str, Any]) -> str:
    """Convert profile payload to a readable text block."""
    basics = profile_payload.get("basics") or {}
    resume = profile_payload.get("resume") or {}
    assessment = profile_payload.get("assessment") or {}
    career_prefs = profile_payload.get("careerPreferences") or {}
    work_values = profile_payload.get("workValues") or []

    lines = []

    name = basics.get("name") or basics.get("username") or "（未填写）"
    major = basics.get("major") or "（未填写）"
    school = basics.get("school") or basics.get("university") or "（未填写）"
    grad_year = basics.get("graduationYear") or basics.get("grad_year") or "（未填写）"
    target_dir = basics.get("targetDirection") or basics.get("target_direction") or "（未填写）"
    target_city = basics.get("targetCity") or basics.get("target_city") or "（未填写）"

    lines.append(f"姓名/用户：{name}")
    lines.append(f"学校：{school}")
    lines.append(f"专业：{major}")
    lines.append(f"预计毕业年份：{grad_year}")
    lines.append(f"目标方向：{target_dir}")
    lines.append(f"目标城市：{target_city}")

    mbti = assessment.get("mbti") or {}
    holland = assessment.get("holland") or {}
    if mbti:
        mbti_type = mbti.get("display_type") or mbti.get("final_type") or mbti.get("type") or "未知"
        lines.append(f"MBTI：{mbti_type}")
    if holland:
        holland_code = holland.get("code") or "未知"
        lines.append(f"Holland 代码：{holland_code}")

    if career_prefs:
        want = career_prefs.get("want") or career_prefs.get("preferred_industries") or []
        avoid = career_prefs.get("avoid") or []
        if want:
            lines.append(f"倾向岗位/行业：{', '.join(str(x) for x in want[:5])}")
        if avoid:
            lines.append(f"不想从事：{', '.join(str(x) for x in avoid[:5])}")

    if work_values:
        lines.append(f"工作价值观：{', '.join(str(v) for v in work_values[:6])}")

    resume_text = resume.get("text") or resume.get("content") or resume.get("raw") or ""
    resume_status = resume.get("status") or "unknown"
    if resume_text:
        lines.append(f"\n--- 简历原文 ---\n{resume_text[:4000]}")
    else:
        lines.append(f"简历状态：{resume_status}（无原文）")

    return "\n".join(lines)


def _roles_to_text(role_payload: list[dict[str, Any]], max_roles: int = 5) -> str:
    """Convert role payload to a readable JD block."""
    if not role_payload:
        return "（未提供岗位数据）"
    lines = []
    for i, role in enumerate(role_payload[:max_roles]):
        name = role.get("name") or role.get("title") or f"岗位{i+1}"
        company = role.get("company") or role.get("org") or ""
        desc = role.get("description") or role.get("jd") or role.get("summary") or ""
        required = role.get("requiredSkills") or role.get("required_skills") or []
        preferred = role.get("preferredSkills") or role.get("preferred_skills") or []

        lines.append(f"\n### 岗位 {i+1}：{name}" + (f"（{company}）" if company else ""))
        if desc:
            lines.append(f"岗位描述：{str(desc)[:1000]}")
        if required:
            lines.append(f"必备要求：{', '.join(str(s) for s in required[:10])}")
        if preferred:
            lines.append(f"加分项：{', '.join(str(s) for s in preferred[:6])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent 1: 行业分析师
# ---------------------------------------------------------------------------

def run_industry_analyst(
    profile_payload: dict[str, Any],
    news_context: str,
    llm: LLMCaller,
) -> dict[str, Any]:
    basics = profile_payload.get("basics") or {}
    target_dir = basics.get("targetDirection") or basics.get("target_direction") or "（未指定）"
    target_city = basics.get("targetCity") or basics.get("target_city") or "（未指定）"
    major = basics.get("major") or "（未指定）"

    user_msg = f"""## 分析任务

决策目的：为该学生职业报告生成行业趋势与能力需求参照。

目标行业/岗位方向：{target_dir}
专业背景：{major}
目标地域：{target_city}
时间范围：近 1-3 年

## 近期新闻与行业动态（可参考）

{news_context or '（无新闻数据）'}

请按格式输出分析报告，包含所有章节（1-6），并在第 7 节输出机器可读 JSON 代码块。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_INDUSTRY_ANALYST, 4096)
    data = _extract_json_block(raw)

    return {
        "markdown": raw,
        "industry_summary": str(data.get("industry_summary") or ""),
        "hot_directions": data.get("hot_directions") or [],
        "cooling_directions": data.get("cooling_directions") or [],
        "skill_priorities": data.get("skill_priorities") or [],
        "risk_signals": data.get("risk_signals") or [],
        "verification_actions": data.get("verification_actions") or [],
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 2: 职业定位顾问
# ---------------------------------------------------------------------------

def run_career_positioning_advisor(
    profile_payload: dict[str, Any],
    industry_brief: dict[str, Any] | None,
    llm: LLMCaller,
    news_rag_context: str = "",
) -> dict[str, Any]:
    profile_text = _profile_to_text(profile_payload)
    industry_section = ""
    if industry_brief:
        industry_section = f"""
## 行业分析师摘要（外部环境参照）

{industry_brief.get('industry_summary') or ''}

升温方向：{', '.join(d.get('name', '') for d in (industry_brief.get('hot_directions') or [])[:4])}
能力优先级：{', '.join(s.get('skill', '') for s in (industry_brief.get('skill_priorities') or [])[:5])}
风险信号：{', '.join((industry_brief.get('risk_signals') or [])[:3])}
"""

    rag_section = ""
    if (news_rag_context or "").strip():
        rag_section = f"""
## 与画像可能相关的新闻摘录（向量检索，仅作交叉验证）

{news_rag_context.strip()}
"""

    user_msg = f"""## 用户信息包

{profile_text}
{industry_section}
{rag_section}

请按格式输出职业定位报告（1-5章），并在第 4 节输出 JSON 代码块（字段：recommended_tracks、hypotheses_for_evidence、constraints_hard、user_intent_summary）。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_CAREER_POSITIONING, 4096)
    data = _extract_json_block(raw)

    return {
        "markdown": raw,
        "recommended_tracks": data.get("recommended_tracks") or [],
        "hypotheses_for_evidence": data.get("hypotheses_for_evidence") or [],
        "constraints_hard": data.get("constraints_hard") or [],
        "user_intent_summary": str(data.get("user_intent_summary") or ""),
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 3: 简历证据分析官
# ---------------------------------------------------------------------------

def run_resume_evidence_analyst(
    profile_payload: dict[str, Any],
    positioning_output: dict[str, Any] | None,
    llm: LLMCaller,
) -> dict[str, Any]:
    resume_text = resolve_profile_resume_text(profile_payload, max_chars=5000)
    basics = profile_payload.get("basics") or {}
    target_dir = basics.get("targetDirection") or basics.get("target_direction") or "（未指定）"

    must_prove_section = ""
    if positioning_output and positioning_output.get("hypotheses_for_evidence"):
        hyps_json = json.dumps(positioning_output["hypotheses_for_evidence"], ensure_ascii=False, indent=2)
        must_prove_section = f"""
## 职业定位顾问 JSON（must_prove 对齐任务）

对以下每条方向假设，逐条在 hypothesis_support 中标注「已支持 / 部分支持 / 不支持 / 待核实」。

```json
{hyps_json}
```
"""

    user_msg = f"""## 分析任务

目标方向：{target_dir}

## 简历全文

{resume_text if resume_text else '（未提供简历原文：画像中无 resume 正文，且简历解析流水线中亦无 resume_source_text。请说明无法验证的原因）'}

{must_prove_section}

请按格式输出证据分析报告（证据总览表、深度解析、能力-证据映射 JSON）。JSON 中 evidence_ids 须与总览表 ID 一致。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_RESUME_EVIDENCE, 4096)
    data = _extract_json_block(raw)

    return {
        "markdown": raw,
        "technical_skills": data.get("technical_skills") or [],
        "general_competencies": data.get("general_competencies") or [],
        "hypothesis_support": data.get("hypothesis_support") or [],
        "gaps": data.get("gaps") or [],
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 4: 能力评估官
# ---------------------------------------------------------------------------

def run_competency_assessor(
    resume_evidence: dict[str, Any],
    positioning_output: dict[str, Any] | None,
    profile_payload: dict[str, Any],
    llm: LLMCaller,
) -> dict[str, Any]:
    evidence_json_obj = resume_evidence.get("raw_json") or {
        "technical_skills": resume_evidence.get("technical_skills") or [],
        "general_competencies": resume_evidence.get("general_competencies") or [],
        "gaps": resume_evidence.get("gaps") or [],
        "hypothesis_support": resume_evidence.get("hypothesis_support") or [],
    }
    evidence_json = json.dumps(evidence_json_obj, ensure_ascii=False, indent=2)

    tracks_section = ""
    if positioning_output and positioning_output.get("recommended_tracks"):
        tracks_section = f"\n推荐方向（维度加权参考）：{', '.join(positioning_output['recommended_tracks'])}"

    resume_fallback = ""
    if not (evidence_json_obj.get("technical_skills") or evidence_json_obj.get("general_competencies")):
        rt = resolve_profile_resume_text(profile_payload, max_chars=1500)
        if rt:
            resume_fallback = f"""

## 简历原文节选（证据 JSON 为空或未能解析时由系统补充，请保守评估）

{rt}
"""

    user_msg = f"""## 简历证据分析官 JSON（必填）

```json
{evidence_json[:3000]}
```

## 证据分析正文摘要

{(resume_evidence.get('markdown') or '（无正文）')[:1500]}
{tracks_section}
{resume_fallback}

请按格式输出能力评估报告（1-5章）。第 4 节必须输出机器可读画像 JSON。无证据的维度必须标为 unknown，不得在无证据情况下评为 A/S。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_COMPETENCY_ASSESSOR, 4096)
    data = _extract_json_block(raw)

    return {
        "markdown": raw,
        "dimensions": data.get("dimensions") or {},
        "strengths": data.get("strengths") or [],
        "gaps": data.get("gaps") or [],
        "unknowns": data.get("unknowns") or [],
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 5: 岗位匹配官
# ---------------------------------------------------------------------------

def run_role_match_officer(
    competency_profile: dict[str, Any],
    positioning_output: dict[str, Any] | None,
    role_payload: list[dict[str, Any]],
    industry_brief: dict[str, Any] | None,
    llm: LLMCaller,
) -> dict[str, Any]:
    competency_json_obj = competency_profile.get("raw_json") or {
        "dimensions": competency_profile.get("dimensions") or {},
        "strengths": competency_profile.get("strengths") or [],
        "gaps": competency_profile.get("gaps") or [],
        "unknowns": competency_profile.get("unknowns") or [],
    }
    competency_json = json.dumps(competency_json_obj, ensure_ascii=False, indent=2)

    roles_text = _roles_to_text(role_payload, max_roles=5)

    positioning_section = ""
    if positioning_output and positioning_output.get("recommended_tracks"):
        positioning_section = f"\n职业定位顾问推荐方向（一致性参考）：{', '.join(positioning_output['recommended_tracks'])}"
        if positioning_output.get("constraints_hard"):
            positioning_section += f"\n硬约束：{', '.join(positioning_output['constraints_hard'])}"

    industry_section = ""
    if industry_brief and industry_brief.get("industry_summary"):
        industry_section = f"\n行业分析师摘要（语境参考，不得替代 JD 判断）：{industry_brief['industry_summary']}"

    user_msg = f"""## 能力评估官 JSON（必填）

```json
{competency_json[:2500]}
```

## 能力评估正文摘要

{(competency_profile.get('markdown') or '（无正文）')[:1000]}

## 目标岗位 JD（必填）

本次需要分析的岗位共 {len(role_payload or [])} 个，请对每个岗位都给出简要分析，第一个岗位为主对标岗位做最详细展开。

{roles_text}
{positioning_section}
{industry_section}

请按格式输出匹配分析（1-6章）。第 6 节必须输出机器可读 JSON，每个分数须可由匹配矩阵追溯。注意：匹配得分不要太死板，正常基础分建议在 75–100 区间。JSON 代码块之后单独输出 MATCH_SUMMARY 行。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_ROLE_MATCH, 5120)
    data = _extract_json_block(raw)
    target_role = _normalize_target_role(data.get("target_role"), role_payload)

    return {
        "markdown": raw,
        "target_role": target_role,
        "fit_score": _coerce_fit_score(data.get("fit_score"), default=0),
        "fit_band": str(data.get("fit_band") or "not_ready"),
        "hard_failures": data.get("hard_failures") if isinstance(data.get("hard_failures"), list) else _coerce_text_list(data.get("hard_failures")),
        "partial_gaps": data.get("partial_gaps") if isinstance(data.get("partial_gaps"), list) else [],
        "weights_rationale": str(data.get("weights_rationale") or ""),
        "consistency_with_user_tracks": str(data.get("consistency_with_user_tracks") or "unknown"),
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 6: 路径规划师
# ---------------------------------------------------------------------------

def run_career_path_planner(
    positioning_output: dict[str, Any] | None,
    match_output: dict[str, Any],
    competency_profile: dict[str, Any],
    industry_brief: dict[str, Any] | None,
    resume_evidence: dict[str, Any] | None,
    profile_payload: dict[str, Any],
    llm: LLMCaller,
) -> dict[str, Any]:
    basics = profile_payload.get("basics") or {}
    grad_year = basics.get("graduationYear") or basics.get("grad_year") or "未知"

    match_json = json.dumps(match_output.get("raw_json") or {
        "target_role": match_output.get("target_role") or "",
        "fit_score": match_output.get("fit_score") or 0,
        "fit_band": match_output.get("fit_band") or "not_ready",
        "hard_failures": match_output.get("hard_failures") or [],
        "partial_gaps": match_output.get("partial_gaps") or [],
    }, ensure_ascii=False, indent=2)

    competency_json = json.dumps({
        "strengths": competency_profile.get("strengths") or [],
        "gaps": competency_profile.get("gaps") or [],
        "unknowns": competency_profile.get("unknowns") or [],
    }, ensure_ascii=False, indent=2)

    positioning_section = ""
    if positioning_output:
        pos_json = json.dumps({
            "recommended_tracks": positioning_output.get("recommended_tracks") or [],
            "constraints_hard": positioning_output.get("constraints_hard") or [],
            "user_intent_summary": positioning_output.get("user_intent_summary") or "",
        }, ensure_ascii=False, indent=2)
        positioning_section = f"\n## 职业定位顾问摘要\n```json\n{pos_json}\n```"

    industry_section = ""
    if industry_brief and industry_brief.get("industry_summary"):
        hot = ', '.join(d.get('name', '') for d in (industry_brief.get('hot_directions') or [])[:3])
        industry_section = f"\n## 行业分析师摘要\n{industry_brief['industry_summary']}\n升温方向：{hot}"

    evidence_section = ""
    if resume_evidence and resume_evidence.get("technical_skills"):
        skills = ', '.join(s.get('skill', '') for s in (resume_evidence['technical_skills'] or [])[:6])
        evidence_section = f"\n## 简历证据亮点\n已证明技能：{skills}"

    user_msg = f"""## 岗位匹配官 JSON（必填）

```json
{match_json[:2000]}
```

## 岗位匹配正文摘要

{(match_output.get('markdown') or '（无正文）')[:800]}

## 能力评估官摘要（必填）

```json
{competency_json[:1500]}
```
{positioning_section}
{industry_section}
{evidence_section}

## 用户信息

预计毕业年份：{grad_year}
每周可投入时间：假设约 10-15 小时（如用户另有说明请以用户为准）

请按格式输出路径规划（1-7章）。第 7 节必须输出机器可读 JSON。行动必须绑定匹配官差距项（partial_gaps / hard_failures）。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_CAREER_PATH_PLANNER, 5120)
    data = _extract_json_block(raw)

    return {
        "markdown": raw,
        "vision_roles": data.get("vision_roles") or [],
        "milestones": data.get("milestones") or [],
        "contingency": data.get("contingency") or [],
        "dependencies": data.get("dependencies") or {},
        "raw_json": data,
    }


# ---------------------------------------------------------------------------
# Agent 7: 报告总编辑（将6-agent输出汇编为8-section最终报告）
# ---------------------------------------------------------------------------

def run_report_editor(
    industry_brief: dict[str, Any],
    positioning_output: dict[str, Any],
    resume_evidence: dict[str, Any],
    competency_profile: dict[str, Any],
    match_output: dict[str, Any],
    path_plan: dict[str, Any],
    role_payload: list[dict[str, Any]],
    llm: LLMCaller,
) -> dict[str, Any]:
    """Assemble the final 8-section career report from upstream agent outputs."""

    def _dump_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    role_text = _roles_to_text(role_payload, max_roles=5)

    user_msg = f"""## 总编辑任务

请将以下6位上游智能体的输出重新编排为一份严格的8章职业报告。不得编造新信息，必须保持书面报告体。

---

### 1. 行业分析师输出

Markdown正文（节选）：
{str(industry_brief.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(industry_brief.get("raw_json") or {})}
```

---

### 2. 职业定位顾问输出

Markdown正文（节选）：
{str(positioning_output.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(positioning_output.get("raw_json") or {})}
```

---

### 3. 简历证据分析官输出

Markdown正文（节选）：
{str(resume_evidence.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(resume_evidence.get("raw_json") or {})}
```

---

### 4. 能力评估官输出

Markdown正文（节选）：
{str(competency_profile.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(competency_profile.get("raw_json") or {})}
```

---

### 5. 岗位匹配官输出

Markdown正文（节选）：
{str(match_output.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(match_output.get("raw_json") or {})}
```

---

### 6. 路径规划师输出

Markdown正文（节选）：
{str(path_plan.get("markdown") or "")[:4000]}

结构化JSON：
```json
{_dump_json(path_plan.get("raw_json") or {})}
```

---

### 岗位画像数据

{role_text}

---

请按格式输出完整的8章 Markdown 报告，并在最后提供一个合法 JSON 代码块（字段 `sections` 包含8个键：`executive_summary`, `macro_environment`, `personal_traits`, `target_job_analysis`, `matching_decision`, `gap_action_plan`, `risk_backup`, `appendix`）。
"""

    raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SYSTEM_PROMPT_REPORT_EDITOR, 8192)
    data = _extract_json_block(raw)
    sections_data = data.get("sections") if isinstance(data.get("sections"), dict) else {}

    return {
        "markdown": raw,
        "sections": {
            "executive_summary": str(sections_data.get("executive_summary", {}).get("markdown") or "").strip(),
            "macro_environment": str(sections_data.get("macro_environment", {}).get("markdown") or "").strip(),
            "personal_traits": str(sections_data.get("personal_traits", {}).get("markdown") or "").strip(),
            "target_job_analysis": str(sections_data.get("target_job_analysis", {}).get("markdown") or "").strip(),
            "matching_decision": str(sections_data.get("matching_decision", {}).get("markdown") or "").strip(),
            "gap_action_plan": str(sections_data.get("gap_action_plan", {}).get("markdown") or "").strip(),
            "risk_backup": str(sections_data.get("risk_backup", {}).get("markdown") or "").strip(),
            "appendix": str(sections_data.get("appendix", {}).get("markdown") or "").strip(),
        },
        "raw_json": data,
    }


def run_report_section_writer(
    industry_brief: dict[str, Any],
    positioning_output: dict[str, Any],
    resume_evidence: dict[str, Any],
    competency_profile: dict[str, Any],
    match_output: dict[str, Any],
    path_plan: dict[str, Any],
    role_payload: list[dict[str, Any]],
    llm: LLMCaller,
    progress_callback: Callable[[str, str], None] | None = None,
    phase_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the 8-section report one chapter at a time, carrying context forward."""

    def _dump_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    def _truncate(text: str, limit: int) -> str:
        t = str(text or "")
        return t if len(t) <= limit else t[:limit] + "\n...（已截断）"

    def _phase_plan_to_text(pp: dict[str, Any] | None) -> str:
        if not pp:
            return "（无分阶段计划数据）"
        lines: list[str] = []
        for key, label in [("short_term", "短期"), ("mid_term", "中期"), ("long_term", "长期")]:
            items = pp.get(key)
            if not isinstance(items, list) or not items:
                continue
            for item in items:
                phase_label = str(item.get("phase") or label)
                title = str(item.get("title") or "")
                objective = str(item.get("objective") or title)
                lines.append(f"### {label}（{phase_label}）：{title}")
                lines.append(f"核心目标：{objective}")
                focus_points = item.get("focus_points") or []
                if focus_points:
                    lines.append("关键行动焦点：")
                    for fp in focus_points:
                        lines.append(f"- {fp}")
                tasks = item.get("tasks") or []
                if tasks:
                    lines.append("具体任务：")
                    for t in tasks:
                        txt = str(t.get("text") or t.get("title") or "")
                        if txt:
                            lines.append(f"- {txt}")
                signals = item.get("signals") or []
                if signals:
                    lines.append("验证信号：")
                    for s in signals:
                        lines.append(f"- {s}")
                lines.append("")
        return "\n".join(lines) if lines else "（无分阶段计划数据）"

    role_text = _roles_to_text(role_payload, max_roles=5)

    # 预先准备各章节需要的上游材料摘要
    upstream_blocks = {
        "executive_summary": f"""
职业定位摘要：{str(positioning_output.get('user_intent_summary') or '')[:400]}
匹配结果：目标岗位 {str(match_output.get('target_role') or '')}，契合度 {match_output.get('fit_score') or 0}%（{match_output.get('fit_band') or 'unknown'}）
路径规划愿景：{', '.join(str(x) for x in (path_plan.get('vision_roles') or [])[:3])}
行业摘要：{str(industry_brief.get('industry_summary') or '')[:400]}
""",
        "macro_environment": f"""
行业分析师 Markdown（节选）：
{_truncate(industry_brief.get('markdown'), 2000)}

结构化JSON：
```json
{_dump_json(industry_brief.get('raw_json') or {})}
```
""",
        "personal_traits": f"""
职业定位顾问 Markdown（节选）：
{_truncate(positioning_output.get('markdown'), 1500)}

简历证据技术技能：{', '.join(str(s.get('skill')) for s in (resume_evidence.get('technical_skills') or [])[:6])}
能力维度JSON：
```json
{_dump_json(competency_profile.get('dimensions') or {})}
```
""",
        "target_job_analysis": f"""
岗位画像数据：
{role_text}

行业赛道补充：{str(industry_brief.get('industry_summary') or '')[:400]}
""",
        "matching_decision": f"""
岗位匹配官 Markdown（节选）：
{_truncate(match_output.get('markdown'), 2000)}

结构化JSON：
```json
{_dump_json(match_output.get('raw_json') or {})}
```
""",
        "gap_action_plan": f"""
路径规划师 Markdown（节选）：
{_truncate(path_plan.get('markdown'), 2000)}

分阶段计划（供学习路径模块消费，请将其转写成 6.6 节的表格与文字，严禁直接输出 JSON）：
{_phase_plan_to_text(phase_plan)}

差距项：{', '.join(str(g.get('requirement')) for g in (match_output.get('partial_gaps') or [])[:6])}
""",
        "risk_backup": f"""
行业风险信号：{', '.join(str(r) for r in (industry_brief.get('risk_signals') or [])[:4])}
硬门槛缺口：{', '.join(str(f) for f in (match_output.get('hard_failures') or [])[:4])}
路径风险：{', '.join(str(r) for r in (path_plan.get('path_risks') or [])[:4])}
备选方案：{', '.join(str(c) for c in (path_plan.get('contingency') or [])[:4])}
""",
        "appendix": f"""
简历证据技能映射：
{chr(10).join(f"- {s.get('skill')}（{s.get('strength')}）证据：{', '.join(str(x) for x in (s.get('evidence_ids') or [])[:3])}" for s in (resume_evidence.get('technical_skills') or [])[:6])}

验证建议：{', '.join(str(v) for v in (industry_brief.get('verification_actions') or [])[:6])}
""",
    }

    sections_order = [
        ("executive_summary", "一、执行摘要"),
        ("macro_environment", "二、宏观就业环境"),
        ("personal_traits", "三、个人特质与潜力"),
        ("target_job_analysis", "四、目标企业与岗位分析"),
        ("matching_decision", "五、人岗匹配与决策建议"),
        ("gap_action_plan", "六、差距分析与行动计划"),
        ("risk_backup", "七、风险管理与备选方案"),
        ("appendix", "八、附录"),
    ]

    generated: dict[str, str] = {}
    full_parts: list[str] = []

    for idx, (key, title) in enumerate(sections_order, start=1):
        if progress_callback:
            progress_callback(key, f"正在生成第 {idx} 章：{title}...")

        # 构建前面章节的上下文（取每章前 400 字作为摘要）
        previous_context = ""
        if generated:
            ctx_parts = []
            for prev_key, prev_title in sections_order[:idx - 1]:
                snippet = generated.get(prev_key, "")[:400]
                if snippet:
                    ctx_parts.append(f"### {prev_title}\n{snippet}")
            previous_context = "\n\n".join(ctx_parts)

        user_msg = f"""## 当前任务

请写报告的第 {idx} 章：{title}

## 前面已写章节的摘要（供你衔接上下文）

{previous_context or '（这是第一章，前面没有内容。请直接开篇，不要写元话语。）'}

## 本章应使用的上游材料

{upstream_blocks.get(key, '（无特定上游摘要）')}

---

请只输出本章的 Markdown 正文（**不要**输出 `## {title}` 这个一级标题，直接从三级标题或段落开始写）。如果信息严重不足，只写「本章节上游输出暂缺」。
"""

        raw = _safe_call(llm, [{"role": "user", "content": user_msg}], SECTION_WRITER_SYSTEM_PROMPT, 4096)
        content = str(raw or "").strip()
        generated[key] = content
        full_parts.append(f"## {title}\n\n{content}")

    full_markdown = "\n\n".join(full_parts)
    return {
        "markdown": full_markdown,
        "sections": generated,
        "raw_json": {},
    }
