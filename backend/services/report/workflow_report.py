"""把实际 Agent 结果映射为主系统现有的报告、导出和任务跟踪结构。"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .schemas import REPORT_VERSION


DECISIONS = {"recommended": "建议优先考虑", "conditional": "满足条件后考虑",
             "not_recommended": "暂不建议", "insufficient_information": "信息不足"}
CHECKS = {"supported": "已有证据支持", "partial": "部分支持", "evidence_missing": "缺少证据",
          "confirmed_gap": "已确认差距", "unknown": "待核实"}


def _bullets(items):
    return "\n".join(f"- {item}" for item in items if item)


def build_report_bundle(username, report_id, profile, state, model_name):
    results = state["results"]
    resume = results["resume_analysis"].get("data", {})
    decision = results["career_decision"].get("data", {})
    plan = results["action_planning"].get("data", {})
    targets = results["job_analysis"]["data"]["targets"]
    review = state["review"]
    selected = next(target for target in targets if target["target_id"] == review["target_id"])
    title = selected["title"] + " · 职业生涯发展报告"
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    sections = {}

    def section(key, label, markdown):
        sections[key] = {"label": label, "markdown": markdown, "data": {}}

    section("executive_summary", "执行摘要", decision.get("summary", "当前证据不足") + "\n\n" + (decision.get("comparison") or ""))
    resume_text = resume.get("summary", "未获得有效简历分析")
    if resume.get("score") is not None:
        resume_text += f"\n\n简历内容质量评分：{resume['score']}（不代表岗位匹配率）。"
    for experience in resume.get("experiences", []):
        resume_text += f"\n\n### {experience['name']}\n\n> {experience['source_quote']}\n\n"
        resume_text += _bullets(issue["problem"] + "；" + issue["suggestion"] for issue in experience.get("issues", []))
    resume_text += "\n\n" + _bullets(resume.get("recommendations", []))
    section("personal_traits", "简历证据与改进", resume_text)
    job_parts, source_parts = [], []
    for target in targets:
        analysis = target["job_analysis"]
        data = analysis.get("data", {})
        text = f"### {target['title']}\n\n{data.get('summary', '当前检索样本不足')}\n\n"
        for finding in data.get("findings", []):
            text += f"- {finding['statement']}（{finding['requirement']}）\n"
            for evidence in finding.get("evidence", []):
                text += f"  - [{evidence['chunk_id']}] {evidence['quote']}\n"
        text += "\n" + _bullets(data.get("limitations", []))
        job_parts.append(text)
        for source in analysis.get("sources", []):
            source_parts.append(f"- {target['target_id']} / {source['chunk_id']}：{source.get('file_path', '')}\n\n> {source['content']}")
    section("target_job_analysis", "目标岗位要求与来源", "\n\n".join(job_parts))
    recruitment = results.get("recruitment_search", {})
    search = recruitment.get("data", {})
    search_text = search.get("summary") or "本次未请求招聘搜索。"
    for finding in search.get("findings", []):
        search_text += f"\n\n- {finding['summary']} [{finding['source_id']}]\n" + _bullets(finding.get("evidence_quotes", []))
        search_text += "\n" + _bullets(finding.get("unverified_conditions", []))
    for source in recruitment.get("sources", []):
        source_parts.append("- " + str(source.get("source_id", "")) + "：" + str(source.get("url", source.get("title", ""))))
    section("macro_environment", "招聘信息与待核实条件", search_text + "\n\n" + _bullets(search.get("limitations", [])))
    match_parts, strengths, gaps, traces = [], [], [], []
    for assessment in decision.get("assessments", []):
        target = next(target for target in targets if target["target_id"] == assessment["target_id"])
        text = f"### {target['title']}：{DECISIONS[assessment['decision']]}\n\n{assessment['conclusion']}\n\n"
        for check in assessment.get("checks", []):
            text += f"- {check['check_id']} / {check['requirement']}：{CHECKS[check['status']]}。{check['reasoning']}\n"
            for evidence in check["job_evidence"] + check["candidate_evidence"]:
                text += f"  - [{evidence['source_id']}] {evidence['quote']}\n"
                traces.append({"source": evidence["source_id"], "quote": evidence["quote"], "claim": check["requirement"]})
            if target["target_id"] == review["target_id"]:
                (strengths if check["status"] == "supported" else gaps).append({"title": check["requirement"], "detail": check["reasoning"]})
        match_parts.append(text)
    section("matching_decision", "职业决策与差距判断", "\n\n".join(match_parts))
    constraints = review["constraints"]
    plan_text = plan.get("summary", "") + f"\n\n每周 {constraints['weekly_hours']} 小时，截止 {constraints['deadline']}。"
    if constraints.get("budget") is not None:
        plan_text += f"预算 {constraints['budget']} 元。"
    phases, action_items = [], []
    start = date.fromisoformat(constraints.get("start_date") or generated_at[:10])
    for task in plan.get("tasks", []):
        due = min(start + timedelta(days=task["week"] * 7 - 1), date.fromisoformat(constraints["deadline"]))
        plan_text += f"\n\n### 第 {task['week']} 周 · {task['task_id']} {task['title']}\n\n"
        plan_text += _bullets([f"岗位要求：{task['check_id']}；阶段：{task['stage']}",
                              f"工作量：{task['hours']} 小时；支出：{task['cost']} 元",
                              "前置任务：" + ("、".join(task["depends_on"]) or "无"),
                              "交付物：" + task["deliverable"], "验收标准：" + task["acceptance_criteria"]])
        phases.append({"id": task["task_id"], "phase": task["stage"], "title": task["title"],
                       "objective": task["deliverable"], "focus_points": [task["check_id"]],
                       "signals": [task["acceptance_criteria"]], **task, "due_date": due.isoformat()})
        action_items.append({"id": task["task_id"], "title": task["title"], "deliverable": task["deliverable"],
                             "acceptance_criteria": task["acceptance_criteria"], "deadline": due.isoformat()})
    section("gap_action_plan", "行动计划与验收", plan_text)
    reduced = plan.get("reduced_plan", {})
    risk = f"每周时间减至 {reduced.get('weekly_hours', '--')} 小时时：{reduced.get('reason', '')}\n\n"
    risk += "保留任务：" + "、".join(reduced.get("keep_task_ids", [])) + "\n\n"
    risk += _bullets(plan.get("deferred_actions", []) + plan.get("limitations", []) + decision.get("limitations", []))
    unanswered = [item for name, result in results.items() if name != "job_analysis"
                  for item in result.get("data", {}).get("followup_questions", [])]
    risk += "\n\n" + _bullets("待核实：" + question for question in unanswered)
    section("risk_backup", "时间删减与限制", risk)
    clarifications = state["decision_input"].get("clarifications", [])
    for source in results["career_decision"].get("sources", []):
        origin = source.get("file_path") or {"resume": "简历原文", "additional_evidence": "用户补充", "preferences": "求职偏好"}.get(source["kind"], source["kind"])
        source_parts.append(f"- 决策来源 [{source['source_id']}]：{origin}" +
                            (f"；对应岗位片段 {source['chunk_id']}" if source.get("chunk_id") else ""))
    source_parts += [f"- 用户补充问题：{item['question']}\n  - 回答：{item['answer']}" for item in clarifications]
    section("appendix", "证据来源与补充记录", "\n\n".join(source_parts))
    order = ["executive_summary", "personal_traits", "target_job_analysis", "macro_environment",
             "matching_decision", "gap_action_plan", "risk_backup", "appendix"]
    markdown = f"# {title}\n\n生成时间：{generated_at}\n\n" + "\n\n".join(
        "## " + sections[key]["label"] + "\n\n" + sections[key]["markdown"] for key in order)
    selected_assessment = next((item for item in decision.get("assessments", []) if item["target_id"] == selected["target_id"]), {})
    summary = decision.get("summary", "")
    meta = {"report_id": report_id, "username": username, "generated_at": generated_at, "status": "ready",
            "version": REPORT_VERSION, "pipeline_version": "experiments-langgraph-v1", "model": model_name,
            "generation_mode": "langgraph", "focus_role_id": selected["target_id"], "focus_role_name": selected["title"],
            "title": title, "summary": summary}
    # 沿用主系统展示协议；数值匹配率没有可靠来源，保持为空。
    return {"meta": meta, "profile_snapshot": {key: value for key, value in profile.items() if key not in {"agent_memory", "agent_workflow"}},
            "agent_results": results, "role_rankings": [], "match_output": {}, "career_path": {},
            "gap_map": {"focus_role_name": selected["title"], "gaps": gaps},
            "phase_plan": {"short_term": phases, "mid_term": [], "long_term": [], "checkpoints": []},
            "report_document": {"title": title, "markdown": markdown, "sections": sections, "executive_summary": summary,
                                "focus_role_id": selected["target_id"], "focus_role_name": selected["title"],
                                "dashboard_summary": {"headline": summary, "fit_score": None,
                                                      "fit_band_label": DECISIONS.get(selected_assessment.get("decision"), "信息不足")},
                                "evidence_health": {"strengths": strengths, "evidence_gaps": gaps, "evidence_trace": traces},
                                "plan_board": {"action_items": action_items}, "next_actions": {"action_items": action_items}}}
