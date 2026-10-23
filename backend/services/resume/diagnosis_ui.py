# -*- coding: utf-8 -*-
"""
简历深度诊断「6.html 五步」结构化 UI 数据。
由 LLM 从 analysis_markdown 抽取，供前端按固定版式渲染。
"""
import json
from datetime import datetime

from services.resume.matcher import markdown_to_safe_html

DIAGNOSIS_UI_SCHEMA_HINT = """
必须只输出一个 JSON 对象（不要 Markdown 代码块），字段如下（均为字符串或数组；缺失可给空字符串或空数组）：

{
  "v": 1,
  "s1_positioning": "目标定位判断正文（纯文本，可含换行）",
  "s1_verdict": "30秒定论正文（纯文本）",
  "s2_subtitle": "Step02 标题下一句副标题，如：严格遵循「批判-解析-建议」三位一体模型对你的简历进行审计。",
  "s2_overall": [
    {"topic":"小标题如 职业故事线","detail":"分析段落","impact":"负面影响","suggestion":"建议","danger":false}
  ],
  "s2_modules": [
    {
      "heading":"如 [ ] 个人摘要/简介",
      "lead":"可选引导语",
      "audits":[{"topic":"问题标题","detail":"分析","impact":"负面影响","suggestion":"建议","danger":false}]
    }
  ],
  "s2_timeline": [
    {"heading":"如 1. 某公司实习 - 岗位","topic":"叙事框架与「所以呢？」","detail":"分析","impact":"负面影响","suggestion":"建议","comparisons":[{"before":"修改前例句","after":"修改后例句"}]}
  ],
  "s3": {
    "left_intro": "影响力叙事工具箱引导语",
    "formula": "针对JD的黄金公式长句",
    "compare_before": "修改前示例一句",
    "compare_after": "修改后示例一段",
    "questions": ["启发式问题1","问题2","问题3"],
    "thinking_intro": "影响力思维训练首段",
    "thinking_path": "思考路径段落",
    "action_line": "行动句"
  },
  "s4_resume_markdown": "修改后的简历全文，Markdown，含 # 姓名、## 各章节",
  "s5": {
    "evaluation": "整体评价段落",
    "risk1_title": "如 时间信息矛盾：",
    "risk1_body": "风险说明",
    "risk2_title": "如 价值叙事缺失：",
    "risk2_body": "风险说明",
    "actions": [
      {"label":"[首要任务]：修正与填充","body":"说明文字"},
      {"label":"[第二任务]：故事演练","body":"说明"},
      {"label":"[长期建议]：建立价值记录本","body":"说明"}
    ]
  }
}

danger 为 true 时该条审计卡片使用红色强调样式。comparisons 可为空数组。
不要编造简历中不存在的事实；信息不足时写「原文未提供…」类说明。
""".strip()

DIAGNOSIS_UI_EXTRACT_SYSTEM = (
    "你是信息抽取器。根据用户提供的「简历诊断 Markdown」与候选人摘要，归纳并填充前端「五步深度审计」看板所需的 JSON 字段。\n"
    "只能输出一个合法 JSON 对象：不要 Markdown 代码围栏，不要解释，不要注释。\n"
    "内容必须与输入一致；信息不足时用「原文未提及…」「待补充…」等占位说明，不要虚构经历与数据。\n"
    "字段 s4_resume_markdown 首行若为「# 姓名」，当输入里提供了非空的 candidate_legal_name 时，该姓名必须与 candidate_legal_name 完全一致；"
    "禁止照抄网页示例里的虚构英文名或邮箱昵称（如 Sime）。若 candidate_legal_name 为空，可用简历原文中的真实姓名，勿编造。\n\n"
    + DIAGNOSIS_UI_SCHEMA_HINT
)


def _inject_canonical_resume_name_into_s4_markdown(s4_md, canonical_name):
    """用结构化简历解析出的姓名覆盖首行 # 标题，避免模型套用示例里的占位名。"""
    name = _safe_str(canonical_name)
    md = str(s4_md or "")
    if not name:
        return md
    if not md.strip():
        return f"# {name}\n"
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return f"# {name}\n"
    first = lines[i].strip()
    if first.startswith("#") and not first.startswith("##"):
        lines[i] = f"# {name}"
        return "\n".join(lines)
    return f"# {name}\n\n" + md.strip()


def build_diagnosis_ui_extract_prompt(
    analysis_markdown, candidate_summary, analysis_mode, candidate_legal_name=""
):
    mode = str(analysis_mode or "resume_review").strip()
    return json.dumps(
        {
            "analysis_mode": mode,
            "candidate_summary": str(candidate_summary or "")[:1200],
            "analysis_markdown": str(analysis_markdown or "")[:14000],
            "candidate_legal_name": str(candidate_legal_name or "")[:120],
            "today": datetime.now().strftime("%Y-%m-%d"),
        },
        ensure_ascii=False,
    )


def _safe_str(x):
    return str(x or "").strip()


def _safe_bool(x):
    if x is True:
        return True
    if x is False:
        return False
    s = str(x or "").strip().lower()
    return s in ("1", "true", "yes", "danger")


def _norm_audit(item):
    if not isinstance(item, dict):
        return None
    return {
        "topic": _safe_str(item.get("topic")),
        "detail": _safe_str(item.get("detail")),
        "impact": _safe_str(item.get("impact")),
        "suggestion": _safe_str(item.get("suggestion")),
        "danger": _safe_bool(item.get("danger")),
    }


def _norm_module(item):
    if not isinstance(item, dict):
        return None
    audits = []
    for a in item.get("audits") or []:
        na = _norm_audit(a)
        if na and (na["topic"] or na["detail"] or na["impact"] or na["suggestion"]):
            audits.append(na)
    return {
        "heading": _safe_str(item.get("heading")),
        "lead": _safe_str(item.get("lead")),
        "audits": audits,
    }


def _norm_timeline(item):
    if not isinstance(item, dict):
        return None
    comps = []
    for c in item.get("comparisons") or []:
        if not isinstance(c, dict):
            continue
        before = _safe_str(c.get("before"))
        after = _safe_str(c.get("after"))
        if before or after:
            comps.append({"before": before, "after": after})
    return {
        "heading": _safe_str(item.get("heading")),
        "topic": _safe_str(item.get("topic")),
        "detail": _safe_str(item.get("detail")),
        "impact": _safe_str(item.get("impact")),
        "suggestion": _safe_str(item.get("suggestion")),
        "comparisons": comps,
    }


def normalize_diagnosis_ui(raw, canonical_name=None):
    """将模型返回归一为 v=1 结构，并生成 step4 的安全 HTML。"""
    data = raw if isinstance(raw, dict) else {}
    if int(data.get("v") or 0) != 1:
        data["v"] = 1

    overall = []
    for it in data.get("s2_overall") or []:
        na = _norm_audit(it)
        if na and (na["topic"] or na["detail"]):
            overall.append(na)

    modules = []
    for it in data.get("s2_modules") or []:
        nm = _norm_module(it)
        if nm and (nm["heading"] or nm["audits"]):
            modules.append(nm)

    timeline = []
    for it in data.get("s2_timeline") or []:
        nt = _norm_timeline(it)
        if nt and nt["heading"]:
            timeline.append(nt)

    s3 = data.get("s3") if isinstance(data.get("s3"), dict) else {}
    questions = [_safe_str(q) for q in (s3.get("questions") or []) if _safe_str(q)]
    while len(questions) < 3:
        questions.append("")
    questions = questions[:3]

    s5 = data.get("s5") if isinstance(data.get("s5"), dict) else {}
    actions = []
    for a in s5.get("actions") or []:
        if not isinstance(a, dict):
            continue
        label = _safe_str(a.get("label"))
        body = _safe_str(a.get("body"))
        if label or body:
            actions.append({"label": label, "body": body})
    while len(actions) < 3:
        actions.append({"label": "", "body": ""})
    actions = actions[:3]

    s4_md = _safe_str(data.get("s4_resume_markdown"))
    s4_md = _inject_canonical_resume_name_into_s4_markdown(s4_md, canonical_name)
    step4_html = ""
    if s4_md:
        try:
            step4_html = markdown_to_safe_html(s4_md)
        except Exception:
            step4_html = ""

    normalized = {
        "v": 1,
        "s1_positioning": _safe_str(data.get("s1_positioning")),
        "s1_verdict": _safe_str(data.get("s1_verdict")),
        "s2_subtitle": _safe_str(data.get("s2_subtitle")),
        "s2_overall": overall,
        "s2_modules": modules,
        "s2_timeline": timeline,
        "s3": {
            "left_intro": _safe_str(s3.get("left_intro")),
            "formula": _safe_str(s3.get("formula")),
            "compare_before": _safe_str(s3.get("compare_before")),
            "compare_after": _safe_str(s3.get("compare_after")),
            "questions": questions,
            "thinking_intro": _safe_str(s3.get("thinking_intro")),
            "thinking_path": _safe_str(s3.get("thinking_path")),
            "action_line": _safe_str(s3.get("action_line")),
        },
        "s4_resume_markdown": s4_md,
        "step4_html": step4_html,
        "s5": {
            "evaluation": _safe_str(s5.get("evaluation")),
            "risk1_title": _safe_str(s5.get("risk1_title")),
            "risk1_body": _safe_str(s5.get("risk1_body")),
            "risk2_title": _safe_str(s5.get("risk2_title")),
            "risk2_body": _safe_str(s5.get("risk2_body")),
            "actions": actions,
        },
    }
    return normalized


def diagnosis_ui_non_empty(ui):
    if not isinstance(ui, dict) or int(ui.get("v") or 0) != 1:
        return False
    if ui.get("s1_positioning") or ui.get("s1_verdict"):
        return True
    if ui.get("s2_overall") or ui.get("s2_modules") or ui.get("s2_timeline"):
        return True
    s3 = ui.get("s3") if isinstance(ui.get("s3"), dict) else {}
    if s3.get("left_intro") or s3.get("formula") or s3.get("compare_before") or s3.get("thinking_path"):
        return True
    if ui.get("step4_html") or ui.get("s4_resume_markdown"):
        return True
    s5 = ui.get("s5") or {}
    if s5.get("evaluation") or s5.get("risk1_body"):
        return True
    return False
