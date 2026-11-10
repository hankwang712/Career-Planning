"""Compose the reading edition around decisions and actions, rather than schema fields."""
from collections import defaultdict
from datetime import date, timedelta
import re
from urllib.parse import quote, urlsplit
from backend.advisor.utils.decision_grounding import model_attribution_questions

from .presentation import SCOPE_NOTE, profile_lines, reader_limitations, unique_text
from .reading_format import readable_markdown, short_report_heading


READER_LAYOUT = "numbered-reader-v3"
READER_SECTION_LABELS = {
    "executive_summary": "核心结论",
    "personal_traits": "简历分析与修改建议",
    "matching_decision": "近期招聘情况与岗位对照",
    "gap_action_plan": "后续成长规划",
    "development_path": "总结与下一步",
    "appendix": "参考依据与适用范围",
}


def sentence(text):
    text = str(text or "").strip()
    return text if not text or text[-1] in "。！？.!?" else text.rstrip("；;") + "。"


def paragraphs(items):
    """Collapse verbatim repeats without paraphrasing, guessing or changing evidence."""
    return readable_markdown("\n\n".join(unique_text(str(item).strip() if str(item).lstrip().startswith("#") else sentence(item) for item in items)))


def short_heading(text, limit=38):
    return short_report_heading(text, limit)


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


def report_link(url, label="查看岗位与投递入口"):
    """Render only web links; encode Markdown delimiters without changing the destination."""
    url = str(url or "").strip()
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or re.search(r"[\s\\\x00-\x1f]", url):
            return ""
    except ValueError:
        return ""
    return f"[{label}]({quote(url, safe=':/?#[]@!$&*+,;=%~-._')})"


def resume_review(resume, *, include_recommendations=True):
    # The profile and highlights already introduce the candidate; omit the repeated full summary.
    parts = []
    highlights = resume.get("highlights", [])
    if highlights:
        parts.append("### 值得保留和突出的优势")
        for item in highlights:
            text = sentence(item["strength"])
            evidence = unique_text(e.get("quote") for e in item.get("evidence", []) if e.get("quote"))
            if evidence:
                text += "\n\n原文依据：「" + "；".join(evidence) + "」。"
            if item.get("visibility") == "understated" and item.get("suggestion"):
                text += "\n\n突出建议：" + sentence(item["suggestion"])
            parts.append(text)
    else:
        strengths = [dim["assessment"] for dim in resume.get("dimensions", []) if dim.get("level", 0) >= 3 and any(e.get("quote") for e in dim.get("evidence", []))]
        if strengths:
            parts.extend(["### 已有材料中的亮点", paragraphs(strengths)])
    dimensions = [] if resume.get("issues") else [dim["assessment"] for dim in resume.get("dimensions", []) if dim.get("level", 0) < 3]
    if dimensions:
        parts.extend(["### 影响说服力的主要问题", paragraphs(dimensions)])

    def issues(items):
        for index, item in enumerate(items, 1):
            parts.append("#### " + short_heading(item["problem"]))
            text = "**问题：**" + sentence(item["problem"])
            evidence = unique_text(e.get("quote") for e in item.get("evidence", []) if e.get("quote"))
            if evidence:
                text += "\n\n原文依据：「" + "；".join(evidence) + "」。"
            text += "\n\n改进方式：" + sentence(item["suggestion"])
            if item.get("rewrite"):
                text += "\n\n基于已有事实的改写：「" + item["rewrite"] + "」"
            if item.get("missing_evidence"):
                text += "\n\n还需补充：" + "；".join(item["missing_evidence"]) + "。"
            parts.append(text)
    if resume.get("issues"):
        parts.append("### 整体简历问题")
        issues(resume["issues"])
    for experience in resume.get("experiences", []):
        parts.append("### " + experience["name"])
        # Keep one useful strength; concrete issues below replace the repeated six-dimension audit.
        useful = [dim["assessment"] for dim in experience.get("dimensions", []) if dim.get("level", 0) >= 3]
        if useful:
            parts.append(sentence(useful[0]))
        elif not experience.get("issues"):
            parts.append(paragraphs(dim["assessment"] for dim in experience.get("dimensions", [])))
        issues(experience.get("issues", []))
    if include_recommendations and resume.get("recommendations"):
        parts.append("### 优先修改顺序")
        has_independent_work = any("独立开发" in (item.get("source_quote", "") + " ".join(dim.get("assessment", "") for dim in item.get("dimensions", []))) for item in resume.get("experiences", []))
        for recommendation in unique_text(resume["recommendations"]):
            if has_independent_work:
                recommendation = re.sub(r"(?:所有|全部|[两二三四五六七八九十]+段)经历的个人分工", "团队经历的个人分工", recommendation)
            # Keep the action and its acceptance check, without repeating the problem background.
            pieces = re.split(r"[，；。]\s*完成标准[为是：:]", recommendation, maxsplit=1)
            action = pieces[0]
            title = short_heading(action)
            parts.append("#### " + title)
            detail = action[len(title):].lstrip("：:，,。；; ") if action.startswith(title) else action
            if detail and not re.match(r"^(?:便于|以便|从而)", detail):
                parts.append(sentence(detail))
            if len(pieces) > 1:
                parts.append("**验收要点：**" + sentence(pieces[1].lstrip("：: ")))
    return "\n\n".join(part for part in parts if part)


def recruitment_review(results, presentation):
    search = results.get("recruitment_search", {})
    if search.get("status") in {None, "skipped"}:
        return "本次未启用近期招聘检索。以下岗位对照来自已取得的岗位材料，不代表当前开放的职位。"
    data = search.get("data", {})
    if search.get("status") != "ok" or not data.get("findings"):
        return paragraphs([data.get("summary", ""), "本次未取得可列出的近期招聘线索，不能据此判断市场没有机会。以下对照仅依据已取得的岗位材料。"])
    sources = {source["source_id"]: source for source in search.get("sources", [])}
    parts = [data.get("summary", ""), "以下按本次检索结果列出岗位供你自行选择；读取了岗位原文也不等于目前仍接受投递，投递前需确认开放状态。"]
    for index, finding in enumerate(data["findings"], 1):
        source = sources.get(finding["source_id"], {})
        job = source.get("job") or {}
        title = source.get("title") or finding["summary"]
        # An employer's aggregate lists many unrelated vacancies; the relevance paragraph
        # identifies the actual opportunity without turning the full list into a heading.
        if job.get("company") and (len(title) > 60 or "\n" in title or len(re.findall(r"工程师|实习生|研究员|经理|助理|设计师", title)) >= 3):
            title = job["company"] + " · 招聘机会"
        parts.append(f"### {index}. " + title)
        metadata = []
        if source.get("origin") == "radar":
            kind = {"aggregate": "公开招聘汇总", "snapshot": "历史快照", "official_site": "企业官网或公告", "import": "导入记录", "jobhunter": "JobHunter 岗位库"}.get(source.get("source_type"), "招聘来源")
            metadata.append("来源：招聘雷达 · " + kind)
            origins = list(dict.fromkeys(row.get("source_name") for row in source.get("provenance", []) if row.get("source_name")))
            if origins:
                metadata.append("采集来源：" + "、".join(origins))
        if job.get("city"):
            metadata.append("地点：" + job["city"])
        if source.get("published_at"):
            metadata.append("公告发布日期：" + str(source["published_at"]))
        else:
            metadata.append("公告发布日期未核实")
        if source.get("updated_at") and not source.get("published_at"):
            metadata.append("来源更新：" + str(source["updated_at"]) + "（不是公告发布日期）")
        metadata.append("已读取岗位原文" if source.get("read_state") == "read" else "原文仅部分读取" if source.get("read_state") == "partial" else "仅有招聘线索，尚未读取岗位全文")
        parts.append("；".join(metadata) + "。")
        if finding.get("relevance"):
            parts.append("与求职需求的关系：" + sentence(finding["relevance"]))
        for label, url in (("查看岗位详情", source.get("url")), ("打开投递入口", job.get("url"))):
            link = report_link(url, label)
            if link and (label == "查看岗位详情" or url != source.get("url")):
                parts.append(link)
        if not report_link(source.get("url")) and not report_link(job.get("url")):
            parts.append("暂未取得可访问的岗位链接。")
        pending = [item for item in finding.get("unverified_conditions", []) if item not in {
            "未读取到官网岗位全文，当前依据为招聘汇总或导入记录",
            "本轮尚未读取岗位详情，仅作为相关招聘线索",
            "未取得公告发布日期，暂不能确认符合用户时间范围"}]
        if pending:
            parts.append("待确认：" + "；".join(pending) + "。")
        reference = "search:" + finding["source_id"]
        source_ids = {s["source_id"] for s in results["career_decision"].get("sources", []) if s.get("recruitment_reference") == reference}
        for assessment in results["career_decision"].get("data", {}).get("assessments", []):
            for check in assessment.get("checks", []):
                if any(e["source_id"] in source_ids for e in check.get("job_evidence", [])):
                    parts.append("**岗位要求：" + check["requirement"] + "。** " + sentence(check["reasoning"]))
    return "\n\n".join(parts)


def build_reader_sections(state, profile, presentation, selected, assessment, checks, start):
    results = state["results"]
    resume = results["resume_analysis"].get("data", {})
    decision = results["career_decision"].get("data", {})
    plan = results["action_planning"].get("data", {})
    tasks = plan.get("tasks", [])
    constraints = state["review"]["constraints"]
    sections = {}

    def add(key, text):
        text = presentation.clean(text, target_id=selected["target_id"],
                                  task_refs=key in {"gap_action_plan", "development_path"}).strip()
        text = readable_markdown(text)
        blocks = []
        seen_paragraphs = set()
        for block in text.split("\n\n"):
            if re.match(r"\s*#", block):
                # Identical time/requirements under another task belong to that task.
                # Never deduplicate across sections or heading-defined entities.
                seen_paragraphs.clear()
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
        # Keep the factual introduction; strengths, diagnoses and priorities have their own sections.
        personal.append(re.split(r"(?<=[。！？])", resume["summary"], maxsplit=1)[0])
    add("personal_traits", "\n\n".join(filter(None, [" ".join(sentence(item) for item in unique_text(personal)),
        resume_review(resume, include_recommendations=not bool(tasks))])))

    strengths, gaps = priority_checks(checks, tasks)
    fit = [assessment.get("conclusion", "")]
    if strengths:
        for item in strengths:
            fit.extend(["#### " + short_heading(item["requirement"]), "**岗位要求：**" + sentence(item["requirement"]),
                        "**对照判断：**" + sentence(item["reasoning"])])
    if gaps:
        for item in gaps:
            fit.extend(["#### " + short_heading(item["requirement"]), "**岗位要求：**" + sentence(item["requirement"]),
                        "**对照判断：**" + sentence(item["reasoning"])])
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
    add("matching_decision", recruitment_review(results, presentation) + "\n\n### 岗位要求与你的经历对照\n\n" + paragraphs(fit))

    # The reading edition cites the judgments it actually develops, not every retrieved requirement.
    sources = {source["source_id"]: source for source in results["career_decision"].get("sources", [])}
    for check in strengths + gaps:
        for evidence in check.get("job_evidence", []):
            source = sources.get(evidence["source_id"], {})
            if source.get("kind") == "job":
                presentation.cite(source.get("chunk_id") or source["source_id"], evidence["quote"], selected["target_id"])

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
            action_text += f"#### {task['title']}\n\n预计 {task['hours']:g} 小时，{due.isoformat()} 前完成。\n\n"
            detail = ["**交付物：**" + task["deliverable"], "**完成标准：**" + task["acceptance_criteria"]]
            check = checks.get(task["check_id"])
            if check:
                detail.insert(0, "**对应要求：**" + check["requirement"])
            if task.get("depends_on"):
                detail.append("先完成“" + "、".join(task_titles[key] for key in task["depends_on"]) + "”再开展本任务")
            if task.get("cost", 0) > 0:
                detail.append(f"预计支出 {task['cost']:g} 元")
            action_text += "\n\n".join(sentence(item) for item in unique_text(detail)) + "\n\n"
    growth, seen = [], set()
    for milestone in plan.get("development_roadmap", []):
        milestone_parts = [sentence(milestone["objective"])]
        for index, action in enumerate(milestone.get("actions", []), 1):
            milestone_parts.append(f"#### {action['title']}\n\n**交付物：**" + sentence(action["deliverable"]) + "\n\n**完成标准：**" + sentence(action["acceptance_criteria"]))
        if milestone.get("entry_conditions"):
            milestone_parts.append("**进入条件：**" + sentence(milestone["entry_conditions"]))
        if milestone.get("review_trigger"):
            milestone_parts.append("**复核与调整：**" + sentence(milestone["review_trigger"]))
        content = "\n\n".join(milestone_parts)
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
        growth.append(paragraphs(adjustments))
    if plan.get("deferred_actions"):
        growth.append("暂缓的事项及原因：" + "；".join(plan["deferred_actions"]))
    add("gap_action_plan", "\n\n".join(filter(None, [plan.get("summary", ""), action_text if tasks else "", *growth])))
    verdict = {"recommended": "目前值得优先尝试", "conditional": "核实关键条件后再推进", "not_recommended": "目前暂不建议推进", "insufficient_information": "还需要补充关键信息"}.get(assessment.get("decision"), "继续依据新材料调整")
    conclusion = [f"对于你选择的“{selected['title']}”，本次建议是{verdict}。"]
    if tasks:
        conclusion.append("下一步先完成“" + tasks[0]["title"] + "”，交付“" + tasks[0]["deliverable"] + "”。")
    hard_gaps = [item for item in gaps if item["kind"] == "hard_condition"]
    if hard_gaps:
        conclusion.append("投递前仍须核实：“" + "、".join(item["requirement"] for item in hard_gaps) + "”。")
    add("development_path", paragraphs(conclusion))

    appendix = SCOPE_NOTE
    document = results["resume_analysis"].get("document") or state.get("provenance", {}).get("resume_document", {})
    if document.get("status") == "partial":
        appendix += "\n\n简历仅成功读取部分内容，结论只覆盖已读取材料，未读取部分不能作为否定能力的依据。"
    citations = presentation.appendix_sources()
    if citations:
        appendix += "\n\n" + citations
    pending_materials = resume.get("missing_information", []) + model_attribution_questions(state.get("input", {}).get("raw_resume", ""))
    if pending_materials:
        appendix += "\n\n### 待补材料备查\n\n" + "\n".join(f"{index}. {item}" for index, item in enumerate(unique_text(pending_materials), 1))
    search = results.get("recruitment_search", {})
    if search.get("status") not in {None, "skipped", "ok"}:
        appendix += "\n\n招聘信息查询暂不可用，相关岗位的当前招聘状态需要另行核实。"
    add("appendix", appendix)
    return sections, [key for key in READER_SECTION_LABELS if key in sections]
