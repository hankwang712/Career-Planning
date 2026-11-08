"""Compose the reading edition around decisions and actions, rather than schema fields."""
from collections import defaultdict
from datetime import date, timedelta
import re

from .presentation import SCOPE_NOTE, profile_lines, reader_limitations, unique_text


READER_LAYOUT = "narrative-v1"
READER_SECTION_LABELS = {
    "executive_summary": "核心结论",
    "personal_traits": "个人经历与求职方向",
    "matching_decision": "岗位适配与准备重点",
    "gap_action_plan": "近期行动安排",
    "development_path": "后续成长与调整",
    "appendix": "参考依据与适用范围",
}


def sentence(text):
    text = str(text or "").strip()
    return text if not text or text[-1] in "。！？.!?" else text.rstrip("；;") + "。"


def paragraphs(items):
    """Collapse verbatim repeats without paraphrasing, guessing or changing evidence."""
    return "\n\n".join(unique_text(sentence(item) for item in items))


def priority_checks(checks, tasks):
    ordered = list(checks.values())
    linked = {task["check_id"] for task in tasks}
    strengths = [item for item in ordered if item["status"] == "supported"][:2]
    critical = [item for item in ordered if item["kind"] == "hard_condition" and item["status"] != "supported"]
    gaps = [item for item in ordered if item["kind"] != "hard_condition" and item["status"] != "supported"]
    gaps.sort(key=lambda item: (item["check_id"] not in linked, item["importance"] != "required",
                                item["status"] != "confirmed_gap"))
    # Qualification conflicts are never hidden by the preparation-priority limit.
    return strengths, critical + gaps[:3]


def build_reader_sections(state, profile, presentation, selected, assessment, checks, start):
    results = state["results"]
    resume = results["resume_analysis"].get("data", {})
    decision = results["career_decision"].get("data", {})
    plan = results["action_planning"].get("data", {})
    tasks = plan.get("tasks", [])
    constraints = state["review"]["constraints"]
    sections = {}
    seen_paragraphs = set()

    def add(key, text):
        text = presentation.clean(text, target_id=selected["target_id"],
                                  task_refs=key in {"gap_action_plan", "development_path"}).strip()
        blocks = []
        for block in text.split("\n\n"):
            identity = re.sub(r"\s+", "", block)
            narrative = len(identity) >= 20 and not re.match(r"\s*(?:#|>|[-*] |\d+\.)", block)
            if narrative and identity in seen_paragraphs:
                continue
            if narrative:
                seen_paragraphs.add(identity)
            blocks.append(block)
        text = "\n\n".join(blocks).strip()
        if text:
            sections[key] = {"label": READER_SECTION_LABELS[key], "markdown": text, "data": {}}

    add("executive_summary", decision.get("summary") or assessment.get("conclusion", ""))

    # Education and location are facts, not an empty form; the diagnostic score belongs to resume analysis.
    facts = profile_lines(resume, profile)
    facts = [re.sub(r"^([^：]+)：", r"\1为", item) for item in facts]
    personal = []
    if facts:
        personal.append("；".join(facts))
    if state.get("input", {}).get("preferences"):
        personal.append("你明确的求职偏好是：" + state["input"]["preferences"])
    if not facts and resume.get("summary"):
        personal.append(resume["summary"])
    add("personal_traits", " ".join(sentence(item) for item in unique_text(personal)))

    strengths, gaps = priority_checks(checks, tasks)
    fit = [assessment.get("conclusion", "")]
    if strengths:
        fit.append(" ".join(sentence(item["reasoning"]) for item in strengths))
    if gaps:
        fit.append(" ".join(sentence("对于岗位提出的“" + item["requirement"] + "”，" + item["reasoning"]) for item in gaps))
    if len(presentation.targets) > 1 and decision.get("comparison"):
        fit.append(decision["comparison"])
    for target in presentation.targets:
        if target["target_id"] != selected["target_id"]:
            continue
        for finding in target["job_analysis"].get("data", {}).get("findings", []):
            if finding["category"] == "other" and finding["requirement"] == "required" and not re.search(
                    r"相关性较弱|与目标不符|无关样本|不宜.*并入", finding["statement"]):
                fit.append("岗位材料还明确了这一条件：" + presentation.clean(finding["statement"], target_id=target["target_id"]))
                for evidence in finding.get("evidence", []):
                    presentation.cite(evidence["chunk_id"], evidence["quote"], target["target_id"])
    add("matching_decision", paragraphs(fit))

    # The reading edition cites the judgments it actually develops, not every retrieved requirement.
    sources = {source["source_id"]: source for source in results["career_decision"].get("sources", [])}
    for check in strengths + gaps:
        for evidence in check.get("job_evidence", []):
            source = sources.get(evidence["source_id"], {})
            if source.get("chunk_id"):
                presentation.cite(source["chunk_id"], evidence["quote"], selected["target_id"])

    action_text = f"本阶段截至 {constraints['deadline']}，每周可投入 {constraints['weekly_hours']:g} 小时。"
    if constraints.get("budget") and constraints["budget"] > 0:
        action_text += f"可用预算为 {constraints['budget']:g} 元。"
    by_week = defaultdict(list)
    task_titles = {task["task_id"]: task["title"] for task in tasks}
    for task in tasks:
        by_week[task["week"]].append(task)
    for week, week_tasks in sorted(by_week.items()):
        due = min(start + timedelta(days=week * 7 - 1), date.fromisoformat(constraints["deadline"]))
        action_text += f"\n\n### 第 {week} 周\n\n"
        for index, task in enumerate(week_tasks, 1):
            action_text += f"{index}. **{task['title']}**（预计 {task['hours']:g} 小时，{due.isoformat()} 前完成）\n\n"
            detail = ["完成后保留" + task["deliverable"], task["acceptance_criteria"]]
            if task.get("depends_on"):
                detail.append("先完成“" + "、".join(task_titles[key] for key in task["depends_on"]) + "”再开展本任务")
            if task.get("cost", 0) > 0:
                detail.append(f"预计支出 {task['cost']:g} 元")
            action_text += "   " + " ".join(sentence(item) for item in unique_text(detail)) + "\n\n"
    if tasks:
        add("gap_action_plan", action_text)

    growth, seen = [], set()
    for milestone in plan.get("development_roadmap", []):
        content = " ".join(sentence(item) for item in unique_text([milestone["objective"],
                              "后续重点包括：" + "；".join(action["title"] for action in milestone.get("actions", []))
                              if milestone.get("actions") else "",
                              milestone.get("review_trigger", "")]))
        if content and content not in seen:
            label = {"short": "未来一至三个月", "mid": "三至十二个月", "long": "更长期的成长方向"}[milestone["horizon"]]
            growth.append(f"### {label}\n\n" + content)
            seen.add(content)
    reduced = plan.get("reduced_plan", {})
    keep = [task_titles[key] for key in reduced.get("keep_task_ids", []) if key in task_titles]
    adjustments = []
    if keep:
        adjustments.append(f"如果每周只能投入 {reduced['weekly_hours']:g} 小时，优先保留“" + "、".join(keep) + "”。")
    limits = reader_limitations(plan.get("limitations", []) + decision.get("limitations", []))
    if limits:
        adjustments.extend(limits)
    answered = {item["question"] for answers in state["review"].get("answers", {}).values() for item in answers}
    unanswered = unique_text(item for item in decision.get("followup_questions", []) if item not in answered)
    if unanswered:
        adjustments.append("后续仍需确认：" + "；".join(unanswered[:2]))
    if adjustments:
        growth.append(" ".join(sentence(item) for item in unique_text(adjustments)))
    add("development_path", "\n\n".join(growth))

    appendix = SCOPE_NOTE
    document = results["resume_analysis"].get("document") or state.get("provenance", {}).get("resume_document", {})
    if document.get("status") == "partial":
        appendix += "\n\n简历仅成功读取部分内容，结论只覆盖已读取材料，未读取部分不能作为否定能力的依据。"
    citations = presentation.appendix_sources()
    if citations:
        appendix += "\n\n" + citations
    search = results.get("recruitment_search", {})
    if search.get("status") not in {None, "skipped", "ok"}:
        appendix += "\n\n招聘信息查询暂不可用，相关岗位的当前招聘状态需要另行核实。"
    elif search.get("status") == "ok":
        for finding in search.get("data", {}).get("findings", []):
            source = next((source for source in search.get("sources", []) if source.get("source_id") == finding["source_id"]), {})
            appendix += "\n\n" + sentence(finding["summary"])
            kind = {"aggregate": "公开招聘汇总", "snapshot": "历史快照", "official_site": "企业官网或公告", "import": "导入记录"}.get(source.get("source_type"), "招聘来源")
            if source.get("origin") == "radar":
                appendix += "\n\n来源：招聘雷达 · " + kind
                if source.get("published_at"):
                    appendix += "；公告日期：" + str(source["published_at"])
                if source.get("updated_at"):
                    appendix += "；来源更新：" + str(source["updated_at"]) + "（不等于公告发布日期）"
                if finding.get("unverified_conditions"):
                    appendix += "\n\n待确认：" + "；".join(finding["unverified_conditions"][:3])
            if source.get("url"):
                appendix += "\n\n" + source["url"]
    add("appendix", appendix)
    return sections, [key for key in READER_SECTION_LABELS if key in sections]
