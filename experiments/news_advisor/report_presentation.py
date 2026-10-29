"""将报告状态整理为面向求职者的阅读稿；原始执行状态和证据保持独立。"""

from collections import defaultdict
from datetime import date
from html import escape
import json
from pathlib import Path
import re
from string import Template


TEMPLATE = Path(__file__).with_name("templates") / "career_report.html"
STATUS = {
    "supported": ("已有材料支撑", "positive"),
    "partial": ("建议补充说明", "attention"),
    "evidence_missing": ("尚缺直接材料", "neutral"),
    "confirmed_gap": ("当前条件不符", "negative"),
    "unknown": ("需要逐岗核实", "attention"),
}
DECISIONS = {
    "recommended": "建议优先推进", "conditional": "有条件推进",
    "not_recommended": "当前暂缓", "insufficient_information": "补充材料后评估",
}


def h(value):
    return escape(str(value), quote=True)


def prose(value):
    """正文只保留读者需要的语言；原始引用另行保留。"""
    text = str(value or "")
    for source, target in {"conditional": "有条件推进", "recommended": "建议优先推进",
                           "required": "岗位要求", "preferred": "优先条件",
                           "unknown": "待核实", "evidence_missing": "尚缺直接材料"}.items():
        text = re.sub(r"\b" + source + r"\b", target, text)
    text = re.sub(r"\bT\d+(?:-C\d+|-T\d+|JD\d+)?\b", "", text)
    text = re.sub(r"\bJD\d+\b", "该岗位", text)
    return re.sub(r"\s+", " ", text).strip(" ：:；;")


def source_fields(source):
    content = source.get("content", "")
    def field(label):
        found = re.search(r"^" + label + r"[：:]\s*(.+)$", content, re.M)
        return found.group(1).strip() if found else ""
    return {"title": field("岗位名称") or "岗位样本", "company": field("企业") or "企业信息未提供",
            "city": field("城市") or "地点未提供", "content": content}


def build_view(state, metadata, facts, editorial):
    selected_id = state["review"]["target_id"]
    targets = state["results"]["job_analysis"]["data"]["targets"]
    selected = next(item for item in targets if item["target_id"] == selected_id)
    decision = state["results"]["career_decision"]
    assessment = next(item for item in decision["data"]["assessments"] if item["target_id"] == selected_id)
    checks = {item["check_id"]: item for item in assessment["checks"]}
    raw_tasks = state["results"]["action_planning"]["data"]["tasks"]
    overrides = editorial.get("task_edits", {})
    if set(overrides) - {item["task_id"] for item in raw_tasks}:
        raise ValueError("阅读稿引用了不存在的计划任务")
    tasks = []
    for original in raw_tasks:
        item = dict(original)
        edit = overrides.get(item["task_id"], {})
        # 工时、周期、依赖及关联要求均来自原始计划，不允许版式层改变。
        item.update({key: value for key, value in edit.items()
                     if key in {"title", "deliverable", "acceptance_criteria", "scope_note"}})
        tasks.append(item)
    capability_rows = editorial.get("capabilities") or [
        {"title": prose(item["requirement"]), "status": item["status"],
         "evidence": prose(item["reasoning"]), "next": "结合目标岗位补充对应材料。",
         "check_ids": [item["check_id"]]} for item in checks.values() if item["kind"] == "capability"
    ]
    for row in capability_rows:
        if not set(row.get("check_ids", [])) <= checks.keys():
            raise ValueError("阅读稿引用了不存在的能力检查项")
        if row["status"] not in STATUS:
            raise ValueError("未知的证据状态")
    sources = [source_fields(source) for source in selected["job_analysis"].get("sources", [])]
    opportunities = editorial.get("opportunities", [])
    for item in opportunities:
        if not 1 <= item["source_index"] <= len(sources):
            raise ValueError("阅读稿引用了不存在的岗位样本")
    if not opportunities:
        used = []
        for check in checks.values():
            for quote in check["job_evidence"]:
                match = re.search(r"JD(\d+)$", quote["source_id"])
                if match and int(match.group(1)) not in used:
                    used.append(int(match.group(1)))
        opportunities = [{"source_index": index, "label": "先核实条件", "tone": "attention",
                          "reason": "结合岗位职责与已有项目材料判断适配程度。",
                          "action": "核实学历口径、工作地点、实习周期和当前招聘状态。"}
                         for index in used[:3] if index <= len(sources)]
    constraints = state["review"]["constraints"]
    days = (date.fromisoformat(constraints["deadline"]) - date.fromisoformat(constraints["start_date"])).days + 1
    limits = {week: float(constraints["weekly_hours"]) * min(7, max(0, days - (week - 1) * 7)) / 7
              for week in range(1, (days + 6) // 7 + 1)}
    cities = list(dict.fromkeys(source["city"] for source in sources if source["city"] != "地点未提供"))
    city_note = ("这份样本集中在" + cities[0] + "。" if len(cities) == 1
                 else "样本地区只是本次检索覆盖的范围。")
    experiences = state["results"]["resume_analysis"].get("data", {}).get("experiences", [])
    default_projects = [{
        "label": "已有项目材料", "title": item["name"],
        "summary": prose(item.get("source_quote", "")),
        "focus": prose(" ".join(issue.get("suggestion", "") for issue in item.get("issues", [])[:2]))
                 or "整理个人分工、实现过程和可复核的结果。",
    } for item in experiences]
    return {
        "name": editorial.get("person_name") or state.get("profile_snapshot", {}).get("name") or "个人",
        "target": selected["title"], "date": metadata["started_at"][:10],
        "decision": DECISIONS.get(assessment["decision"], "需要进一步评估"),
        "headline": editorial.get("headline") or "把已有项目转化为可核验的求职证据",
        "lead": editorial.get("lead") or prose(decision["data"].get("summary", "")),
        "positioning": editorial.get("positioning") or [prose(assessment.get("conclusion", ""))],
        "profile": editorial.get("profile", []),
        "priorities": editorial.get("priorities", []),
        "projects": editorial.get("projects") or default_projects,
        "capabilities": capability_rows, "opportunities": opportunities,
        "sources": sources, "checks": checks, "tasks": tasks,
        "facts": facts, "constraints": constraints, "week_limits": limits,
        "period_weeks": len(limits), "city_note": city_note,
        "resume_edits": editorial.get("resume_edits", []),
        "scope": editorial.get("scope") or [
            "岗位样本用于对照要求，招聘是否仍开放需通过当前有效渠道核实。",
            "经历与成果依据所提供材料整理，没有材料不等于不具备能力。",
            "工作地点、实习周期及岗位资格应按具体机会分别确认。",
        ],
        "plan_intro": editorial.get("plan_intro") or "先核实影响求职的条件，再整理材料并安排针对性准备。",
        "reduced_intro": editorial.get("reduced_intro") or "时间减少时，优先保留条件核实、项目证据和定制简历。",
        "next_steps": editorial.get("next_steps", []),
    }


def proof_link(check_id):
    return f'<a class="proof-link" href="#proof-{h(check_id)}" aria-label="查看这一判断的证据">查看依据 <span>↗</span></a>'


def render_body(view):
    facts, constraints = view["facts"], view["constraints"]
    hours = defaultdict(float)
    for task in view["tasks"]:
        hours[task["week"]] += task["hours"]
    total = sum(hours.values())
    parts = []
    parts.append(f'''<section class="cover" id="overview">
      <div class="report-meta"><span>CAREER RESEARCH / 职业发展评估</span><span>{h(view["date"].replace("-", "."))} · 个人报告</span></div>
      <div class="cover-grid"><div><p class="eyebrow">{h(view["name"])} · {h(view["target"])}</p>
      <h1>{h(view["headline"])}</h1><p class="cover-lead">{h(view["lead"])}</p></div>
      <div class="verdict"><span>当前建议</span><strong>{h(view["decision"])}</strong><p>以已有证据为基础，<br>逐岗确认关键条件。</p></div></div>
      <div class="fact-strip"><div><span>求职安排</span><strong>{h(facts.get("employment_type", "待确认"))} · {h(facts.get("can_start", "到岗时间待确认"))}</strong></div>
      <div><span>每周到岗</span><strong>{h(facts.get("onsite_days_per_week", "待确认"))}<small> 天</small></strong></div>
      <div><span>每周准备</span><strong>{constraints["weekly_hours"]:g}<small> 小时</small></strong></div>
      <div><span>本阶段安排</span><strong>{total:g}<small> 小时 / {view["period_weeks"]} 周</small></strong></div></div>
    </section>''')
    if view["priorities"]:
        cards = "".join(f'<li><span class="priority-number">0{i}</span><div><strong>{h(item["title"])}</strong><p>{h(item["detail"])}</p></div></li>'
                        for i, item in enumerate(view["priorities"], 1))
        parts.append(f'<section class="reading-guide"><p class="eyebrow">先抓住这三件事</p><ol>{cards}</ol></section>')
    parts.append('<section class="chapter" id="positioning"><div class="chapter-heading"><span>01</span><div><p>POSITIONING</p><h2>你的职业定位</h2></div></div>')
    for paragraph in view["positioning"]:
        parts.append(f'<p class="narrative">{h(paragraph)}</p>')
    if view["profile"]:
        parts.append('<dl class="profile-lines">' + "".join(f'<div><dt>{h(item["label"])}</dt><dd>{h(item["value"])}</dd></div>' for item in view["profile"]) + '</dl>')
    parts.append('<div class="project-list">')
    for index, project in enumerate(view["projects"], 1):
        parts.append(f'<article class="project"><div class="project-index">0{index}</div><div><p class="eyebrow">{h(project["label"])}</p><h3>{h(project["title"])}</h3><p>{h(project["summary"])}</p><div class="editor-note"><strong>简历与面试重点</strong><p>{h(project["focus"])}</p></div></div></article>')
    parts.append('</div></section>')
    parts.append('<section class="chapter" id="evidence"><div class="chapter-heading"><span>02</span><div><p>EVIDENCE & GAPS</p><h2>优势在哪里，还要补什么</h2></div></div><p class="section-intro">这里评估的是当前材料的覆盖程度。“尚缺材料”保留为待补充项，不能据此断定你不会。</p><div class="capability-list">')
    for row in view["capabilities"]:
        label, tone = STATUS[row["status"]]
        refs = "".join(proof_link(key) for key in row.get("check_ids", [])[:1])
        parts.append(f'<article class="capability"><div class="capability-heading"><h3>{h(row["title"])}</h3><span class="status {tone}">{label}</span></div><div class="capability-body"><div><span class="small-label">现有证据</span><p>{h(row["evidence"])}</p></div><div><span class="small-label">下一步</span><p>{h(row["next"])}</p></div></div>{refs}</article>')
    parts.append('</div></section>')
    parts.append('<section class="chapter" id="opportunities"><div class="chapter-heading"><span>03</span><div><p>OPPORTUNITY REVIEW</p><h2>如何选择下一批岗位</h2></div></div><p class="section-intro">以下是本次岗位样本的选择顺序，用于建立投递判断。它们的当前开放状态仍需核实。</p>')
    for item in view["opportunities"]:
        source = view["sources"][item["source_index"] - 1]
        parts.append(f'<article class="opportunity"><div class="opportunity-top"><div><span class="company">{h(source["company"])} · {h(source["city"])}</span><h3>{h(source["title"])}</h3></div><span class="status {h(item["tone"])}">{h(item["label"])}</span></div><p>{h(item["reason"])}</p><div class="opportunity-action"><strong>核实重点</strong><span>{h(item["action"])}</span></div><a class="proof-link" href="#sample-{item["source_index"]}">查看该岗位原文 ↗</a></article>')
    parts.append('<div class="scope-note"><span>阅读范围</span><p>' + h(view["city_note"]) + '工作地点仍应以你的选择为准；相邻岗位的要求只用于各自岗位，不能合并为整个方向的统一门槛。</p></div></section>')
    period = "未来两周" if view["period_weeks"] == 2 else f'接下来的{view["period_weeks"]}周'
    parts.append(f'<section class="chapter" id="plan"><div class="chapter-heading"><span>04</span><div><p>ACTION PLAN</p><h2>把准备落到{period}</h2></div></div><p class="section-intro">{h(view["plan_intro"])}</p><div class="plan-caption"><span>{h(constraints["start_date"])} — {h(constraints["deadline"])}</span><span>每周上限 {constraints["weekly_hours"]:g} 小时 · 总安排 {total:g} 小时</span></div>')
    for week in sorted(hours):
        limit = view["week_limits"][week]
        percent = min(100, hours[week] / limit * 100)
        tasks = [task for task in view["tasks"] if task["week"] == week]
        parts.append(f'<section class="week"><div class="week-label"><div><span class="eyebrow">WEEK {week:02d}</span><h3>第{week}周</h3></div><div class="hours"><strong>{hours[week]:g}</strong><span> / {limit:g} 小时</span></div></div><div class="time-bar" role="img" aria-label="第{week}周安排{hours[week]:g}小时，上限{limit:g}小时"><span style="width:{percent:g}%"></span></div>')
        for index, task in enumerate(tasks, 1):
            detail = prose(task["deliverable"])
            acceptance = prose(task["acceptance_criteria"])
            note = f'<p class="scope-adjustment">{h(task["scope_note"])}</p>' if task.get("scope_note") else ""
            parts.append(f'<article class="task"><span class="task-number">{index:02d}</span><div><div class="task-title"><h4>{h(prose(task["title"]))}</h4><span>{task["hours"]:g}h</span></div><p><strong>交付物</strong>{h(detail)}</p><details class="acceptance"><summary>怎样算完成</summary><p>{h(acceptance)}</p></details>{note}</div></article>')
        remaining = max(0, limit - hours[week])
        if remaining:
            parts.append(f'<p class="week-buffer">预留 {remaining:g} 小时，供岗位核实、临时沟通和任务调整使用。</p>')
        parts.append('</section>')
    budget_note = "预算暂未确定。" if constraints.get("budget") is None else f'本阶段预算为 {constraints["budget"]:g} 元。'
    parts.append(f'<div class="scope-note"><span>时间不足时</span><p>{h(view["reduced_intro"])}</p></div><p class="quiet">{h(budget_note)}涉及新训练或算力时，应先核实可用资源与实际耗时。</p></section>')
    parts.append('<section class="chapter" id="materials"><div class="chapter-heading"><span>05</span><div><p>APPLICATION MATERIALS</p><h2>让简历讲清楚你的工作</h2></div></div><div class="resume-edits">')
    for item in view["resume_edits"]:
        parts.append(f'<article><h3>{h(item["title"])}</h3><p>{h(item["detail"])}</p></article>')
    parts.append('</div>')
    if view["next_steps"]:
        parts.append('<div class="closing"><p class="eyebrow">下一步，从这里开始</p><ul>' + "".join(f'<li>{h(item)}</li>' for item in view["next_steps"]) + '</ul></div>')
    parts.append('</section>')
    parts.append('<section class="chapter appendix" id="sources"><div class="chapter-heading"><span>06</span><div><p>SOURCES & SCOPE</p><h2>依据与评估范围</h2></div></div><ul class="scope-list">' + "".join(f'<li>{h(item)}</li>' for item in view["scope"]) + '</ul><details class="appendix-group"><summary><span>查看判断所依据的原文</span><small>简历材料与岗位要求对照</small></summary>')
    used = list(dict.fromkeys(key for row in view["capabilities"] for key in row.get("check_ids", [])))
    for index, key in enumerate(used, 1):
        check = view["checks"][key]
        parts.append(f'<article class="proof" id="proof-{h(key)}"><h3>依据 {index:02d} · {h(prose(check["requirement"]))}</h3>')
        for label, field in [("岗位原文", "job_evidence"), ("简历或补充说明", "candidate_evidence")]:
            parts.append(f'<p class="small-label">{label}</p>')
            for item in check.get(field, []):
                parts.append('<blockquote>' + h(item["quote"]) + '</blockquote>')
        parts.append('</article>')
    parts.append('</details><details class="appendix-group"><summary><span>查看本次岗位样本</span><small>保留原文，便于逐岗核实</small></summary>')
    for index, source in enumerate(view["sources"], 1):
        parts.append(f'<details class="sample" id="sample-{index}"><summary>{index:02d} · {h(source["company"])} / {h(source["title"])}</summary><pre>{h(source["content"])}</pre></details>')
    parts.append('</details><p class="archive-link">需要了解系统执行过程？<a href="pipeline-run.html">查看流程实跑记录 ↗</a></p></section>')
    return "".join(parts)


def render_markdown(view):
    """与阅读版共用相同的编辑内容，适合保存与后续导出。"""
    lines = [f'# {view["name"]} · {view["target"]}职业评估', "", f'评估日期：{view["date"]}', "",
             "## 核心结论", "", view["headline"], "", view["lead"], "",
             "## 职业定位", "", *view["positioning"], ""]
    for project in view["projects"]:
        lines.extend(["### " + project["title"], "", project["summary"], "", "表达重点：" + project["focus"], ""])
    lines.extend(["## 优势与待补材料", ""])
    for row in view["capabilities"]:
        lines.extend(["### " + row["title"] + " · " + STATUS[row["status"]][0], "",
                      row["evidence"], "", "下一步：" + row["next"], ""])
    lines.extend(["## 岗位选择", ""])
    for item in view["opportunities"]:
        source = view["sources"][item["source_index"] - 1]
        lines.extend(["### " + source["company"] + " / " + source["title"], "", item["label"] + "。" + item["reason"],
                      "", "核实重点：" + item["action"], ""])
    lines.extend(["## 两周行动计划", "", view["plan_intro"], ""])
    for task in view["tasks"]:
        lines.extend([f'### 第{task["week"]}周 · {prose(task["title"])}（{task["hours"]:g}小时）', "",
                      "交付物：" + prose(task["deliverable"]), "", "验收：" + prose(task["acceptance_criteria"]), ""])
    lines.extend(["## 简历调整", ""])
    for item in view["resume_edits"]:
        lines.extend(["### " + item["title"], "", item["detail"], ""])
    lines.extend(["## 评估范围", "", *("- " + item for item in view["scope"])])
    return "\n".join(lines) + "\n"


def write_reader_report(output, state, metadata):
    output = Path(output)
    def optional(name):
        path = output / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    editorial = optional("report-editorial.json")
    view = build_view(state, metadata, optional("user-constraints.json"), editorial)
    body = render_body(view)
    html = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        title=h(view["name"] + " · " + view["target"] + "职业评估"),
        report_body=body, person=h(view["name"]), report_date=h(view["date"]),
    )
    (output / "career-report.html").write_text(html, encoding="utf-8")
    (output / "career-report.md").write_text(render_markdown(view), encoding="utf-8")
    export = {key: value for key, value in view.items() if key not in {"sources", "checks"}}
    export["editorial_scope"] = "阅读稿可调整叙事和任务实施范围；原始结论、引用、工时、依赖与状态保留在原执行文件。"
    (output / "report-reader-data.json").write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
