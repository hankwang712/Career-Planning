from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .schemas import REPORT_VERSION
from .provenance import report_provenance
from .development import HORIZONS, STUDENT_STAGES, build_development_path, task_horizon


DECISIONS = {"recommended": "建议优先考虑", "conditional": "满足条件后考虑",
             "not_recommended": "暂不建议", "insufficient_information": "信息不足"}
CHECKS = {"supported": "已有证据支持", "partial": "部分支持", "evidence_missing": "缺少证据",
          "confirmed_gap": "已确认差距", "unknown": "待核实"}
REQUIREMENTS = {"required": "必需要求", "preferred": "优先条件", "unspecified": "未标明优先级"}


def _bullets(items):
    return "\n".join(f"- {item}" for item in items if item)


def build_report_bundle(username, report_id, profile, state, model_name):
    from experiments.news_advisor.telemetry import summarize_executions

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
    constraints = review["constraints"]
    student_stage = constraints.get("student_stage", "unspecified")
    selected_assessment = next((item for item in decision.get("assessments", []) if item["target_id"] == selected["target_id"]), {})
    selected_checks = {item["check_id"]: item for item in selected_assessment.get("checks", [])}

    def section(key, label, markdown):
        sections[key] = {"label": label, "markdown": markdown, "data": {}}

    section("executive_summary", "执行摘要", decision.get("summary", "当前证据不足") + "\n\n" + (decision.get("comparison") or ""))
    basics = profile.get("basics") or {}
    resume_text = "规划侧重：" + STUDENT_STAGES[student_stage] + "。\n\n"
    resume_text += _bullets(f"{label}：{basics.get(key) or '未提供'}" for key, label in
                            [("grade", "学历"), ("major", "专业"), ("graduation_year", "毕业年份"), ("city", "所在城市")])
    resume_text += "\n\n以上为用户资料快照，不单独作为能力或岗位适配判断依据。\n\n"
    resume_text += "兴趣与职业偏好（用户自述）：" + (state.get("input", {}).get("preferences") or "未明确提供") + "\n\n"
    resume_text += resume.get("summary", "未获得有效简历分析")
    profile_labels = {"education": "学历", "major": "专业", "graduation_year": "毕业年份", "current_city": "所在城市",
                      "interests": "兴趣偏好", "skills": "专业技能", "strengths": "已有优势", "development_needs": "待发展方面"}
    if resume.get("career_profile"):
        resume_text += "\n\n### 材料中的职业画像\n\n" + _bullets(
            f"{profile_labels[item['field']]}：{item['value']}；依据：{item['quote']}" for item in resume["career_profile"])
    if resume.get("score") is not None:
        resume_text += f"\n\n简历内容质量评分：{resume['score']}（不代表岗位匹配率）。"
    for experience in resume.get("experiences", []):
        resume_text += f"\n\n### {experience['name']}\n\n> {experience['source_quote']}\n\n"
        resume_text += _bullets(issue["problem"] + "；" + issue["suggestion"] for issue in experience.get("issues", []))
    resume_text += "\n\n" + _bullets(resume.get("recommendations", []))
    resume_text += "\n\n### 尚需补充的信息\n\n" + (_bullets(resume.get("missing_information", [])) or "以原始材料和后续核实为准。")
    section("personal_traits", "一、个人基本情况与职业画像", resume_text)
    job_parts, source_parts = [], []
    for target in targets:
        analysis = target["job_analysis"]
        data = analysis.get("data", {})
        text = f"### {target['title']}\n\n{data.get('summary', '当前检索样本不足')}\n\n"
        for finding in data.get("findings", []):
            text += f"- {finding['statement']}（{REQUIREMENTS[finding['requirement']]}）\n"
            for evidence in finding.get("evidence", []):
                text += f"  - [{evidence['chunk_id']}] {evidence['quote']}\n"
        text += "\n" + _bullets(data.get("limitations", []))
        job_parts.append(text)
        for source in analysis.get("sources", []):
            source_parts.append(f"- {target['target_id']} / {source['chunk_id']}：{source.get('file_path', '')}\n\n> {source['content']}")
    alternatives = [target["title"] for target in targets if target["target_id"] != selected["target_id"]][:2]
    positioning = f"本次选定主目标：{selected['title']}。这代表用户的选择，能否推进以资格和能力证据为准。\n\n"
    positioning += "目标选择依据：" + selected_assessment.get("conclusion", "待补充证据") + "\n\n"
    positioning += "备选方向：" + ("、".join(alternatives) if alternatives else "本次未分析其他方向，暂不凭空推荐。") + "\n\n"
    positioning += (decision.get("comparison") or "") + "\n\n具体职责、工作场景和技能要求以以下岗位样本为依据；未出现的内容保留为未知。\n\n"
    positioning += "\n\n" + _bullets(f"{HORIZONS[item['horizon']][0]}目标（{HORIZONS[item['horizon']][1]}）：{item['objective']}"
                                    for item in plan.get("development_roadmap", []))
    section("target_job_analysis", "二、职业方向与目标定位", positioning)
    recruitment = results.get("recruitment_search", {})
    search = recruitment.get("data", {})
    search_text = search.get("summary") or (
        "本次未请求招聘搜索。" if recruitment.get("status", "skipped") == "skipped"
        else "本次招聘搜索未获得可核实结果，请核实后再使用。"
    )
    for finding in search.get("findings", []):
        search_text += f"\n\n- {finding['summary']} [{finding['source_id']}]\n" + _bullets(finding.get("evidence_quotes", []))
        search_text += "\n" + _bullets(finding.get("unverified_conditions", []))
    for source in recruitment.get("sources", []):
        source_parts.append("- " + str(source.get("source_id", "")) + "：" + str(source.get("url", source.get("title", ""))))
    market_scope = ("本报告的岗位知识库是检索样本，不是全市场招聘统计。样本量和检索排序不能用于推算招聘规模、城市占比或薪资分布。"
                    "本次未接入可核验的行业统计或行业报告时，不对行业增速、薪资趋势和企业当前招聘状态作结论。")
    section("macro_environment", "三、行业与就业市场分析", "### 岗位样本中的职责与能力要求\n\n" + "\n\n".join(job_parts)
            + "\n\n### 招聘线索与时效\n\n" + search_text + "\n\n### 分析范围\n\n" + market_scope + "\n\n" + _bullets(search.get("limitations", [])))
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
    counts = {status: sum(check["status"] == status for check in selected_checks.values()) for status in CHECKS}
    coverage = "；".join(f"{CHECKS[status]} {count} 项" for status, count in counts.items())
    section("matching_decision", "四、职业能力与岗位适配度分析", coverage + "。这些是检查项数量，不是录用概率或匹配百分比。\n\n" + "\n\n".join(match_parts))
    gap_parts = ["区分能力差距与材料缺失：缺少证据不等于没有能力。先处理硬性条件和必需技能，再处理优先技能。"]
    gap_rows = []
    status_order = {"confirmed_gap": 0, "partial": 1, "unknown": 2, "evidence_missing": 3, "supported": 4}
    for check in sorted(selected_checks.values(), key=lambda item: (item["kind"] != "hard_condition", item["importance"] != "required", status_order[item["status"]])):
        if check["status"] == "supported":
            continue
        priority = "P0 · 先核实准入条件" if check["kind"] == "hard_condition" else ("P1 · 必需能力" if check["importance"] == "required" else "P2 · 其他要求")
        advice = "先补充原始材料或完成小型诊断，确认后再决定是否需要练习。" if check["status"] in {"unknown", "evidence_missing"} else "结合已有成果，按行动计划补齐并保留可检验产出。"
        if check["kind"] == "hard_condition":
            advice = "先核实学历、届别或到岗安排等准入条件；明确不符合时比较可行的其他岗位，学习任务不能替代资格条件。"
        gap_parts += [f"### {priority}：{check['requirement']}", CHECKS[check["status"]] + "。" + check["reasoning"], advice]
        gap_rows.append({"title": check["requirement"], "detail": check["reasoning"], "status": check["status"], "priority": priority, "check_id": check["check_id"]})
    if not gap_rows:
        gap_parts.append("当前检查项未发现待补齐要求；这不代表覆盖了所有岗位要求。")
    section("ability_gaps", "五、职业能力差距与提升优先级", "\n\n".join(gap_parts))
    plan_text = plan.get("summary", "") + f"\n\n每周 {constraints['weekly_hours']} 小时，截止 {constraints['deadline']}。"
    if constraints.get("budget") is not None:
        plan_text += f"预算 {constraints['budget']} 元。"
    action_items = []
    start = date.fromisoformat(constraints.get("start_date") or generated_at[:10])
    phase_plan, checkpoints, development_text = build_development_path(plan, selected_checks, start)
    section("development_path", "六、职业发展与成长路径", development_text)
    for task in plan.get("tasks", []):
        due = min(start + timedelta(days=task["week"] * 7 - 1), date.fromisoformat(constraints["deadline"]))
        plan_text += f"\n\n### 第 {task['week']} 周 · {task['task_id']} {task['title']}\n\n"
        requirement = selected_checks.get(task["check_id"], {}).get("requirement", task["check_id"])
        plan_text += _bullets([f"岗位要求：{requirement}；阶段：{task['stage']}；完成日期：{due.isoformat()}",
                              f"工作量：{task['hours']} 小时；支出：{task['cost']} 元",
                              "前置任务：" + ("、".join(task["depends_on"]) or "无"),
                              "交付物：" + task["deliverable"], "验收标准：" + task["acceptance_criteria"]])
        horizon = task_horizon(start, due)
        phase_plan[HORIZONS[horizon][2]].append({**task, "id": task["task_id"], "phase": f"{HORIZONS[horizon][0]} · 第{task['week']}周",
                       "phase_key": horizon, "title": task["title"], "objective": task["deliverable"],
                       "focus_points": [], "signals": [task["acceptance_criteria"]], "requirement": requirement,
                       "is_action": True, "due_date": due.isoformat()})
        action_items.append({"id": task["task_id"], "title": task["title"], "deliverable": task["deliverable"],
                             "acceptance_criteria": task["acceptance_criteria"], "deadline": due.isoformat()})
    section("gap_action_plan", "七、具体行动计划", plan_text)
    reduced = plan.get("reduced_plan", {})
    risk = f"每周时间减至 {reduced.get('weekly_hours', '--')} 小时时：{reduced.get('reason', '')}\n\n"
    risk += "保留任务：" + "、".join(reduced.get("keep_task_ids", [])) + "\n\n"
    risk += _bullets(plan.get("deferred_actions", []) + plan.get("limitations", []) + decision.get("limitations", []))
    unanswered = [item for name, result in results.items() if name != "job_analysis"
                  for item in result.get("data", {}).get("followup_questions", [])]
    risk += "\n\n" + _bullets("待核实：" + question for question in unanswered)
    evaluation = ("每月复核一次，并在完成项目、获得实习或改变职业意向后重新评估。记录已完成任务、交付物链接、测试/演示记录、面试反馈和新增经历；"
                  "勾选任务或打卡只代表进度，不自动证明能力达标，也不自动提高匹配分。\n\n"
                  "若关键成果未通过验收，先缩小项目范围或延长练习；若准入条件不满足、兴趣改变或目标岗位需求改变，重新比较主目标与备选方向。"
                  "更新简历与证据后重新生成报告，保留旧版本进行对照。\n\n")
    evaluation += _bullets(f"{item['label']}（建议复核日期 {item['due_date']}）：{item['summary']}" for item in checkpoints)
    section("risk_backup", "八、职业规划评估与动态调整", evaluation + "\n\n### 时间不足与风险处理\n\n" + risk)
    clarifications = state["decision_input"].get("clarifications", [])
    for source in results["career_decision"].get("sources", []):
        origin = source.get("file_path") or {"resume": "简历原文", "additional_evidence": "用户补充", "preferences": "求职偏好"}.get(source["kind"], source["kind"])
        source_parts.append(f"- 决策来源 [{source['source_id']}]：{origin}" +
                            (f"；对应岗位片段 {source['chunk_id']}" if source.get("chunk_id") else ""))
    source_parts += [f"- 用户补充问题：{item['question']}\n  - 回答：{item['answer']}" for item in clarifications]
    source_parts += [f"- 招聘搜索补充问题：{item['question']}\n  - 回答：{item['answer']}"
                     for item in review.get("answers", {}).get("recruitment_search", [])]
    method = (f"报告生成时间：{generated_at}。岗位资料的采集日期、行业统计口径和实时招聘状态未标明时，应视为未知。\n\n"
              "结论依据简历及用户补充原文、岗位片段和招聘来源逐项核对，保留支持、部分支持、证据缺失、已确认差距与未知五种状态。"
              "简历质量评分只反映材料质量；本报告不虚构岗位匹配率。工时与成本是计划估算，中长期路线需复核后执行。\n\n")
    section("appendix", "九、参考依据与报告说明", method + "\n\n".join(source_parts))
    order = ["executive_summary", "personal_traits", "target_job_analysis", "macro_environment",
             "matching_decision", "ability_gaps", "development_path", "gap_action_plan", "risk_backup", "appendix"]
    markdown = f"# {title}\n\n生成时间：{generated_at}\n\n" + "\n\n".join(
        "## " + sections[key]["label"] + "\n\n" + sections[key]["markdown"] for key in order)
    summary = decision.get("summary", "")
    meta = {"report_id": report_id, "username": username, "generated_at": generated_at, "status": "ready",
            "version": REPORT_VERSION, "pipeline_version": "experiments-langgraph-v2", "model": model_name,
            "provenance": report_provenance(state), "execution": summarize_executions(results),
            "generation_mode": "langgraph", "focus_role_id": selected["target_id"], "focus_role_name": selected["title"],
            "title": title, "summary": summary}
    # 沿用主系统展示协议；数值匹配率没有可靠来源，保持为空。
    return {"meta": meta, "profile_snapshot": {key: value for key, value in profile.items() if key not in {"agent_memory", "agent_workflow"}},
            "agent_results": results, "role_rankings": [], "match_output": {}, "career_path": {},
            "gap_map": {"focus_role_name": selected["title"], "gaps": gap_rows},
            "phase_plan": {**phase_plan, "checkpoints": checkpoints},
            "report_document": {"title": title, "markdown": markdown, "sections": sections, "executive_summary": summary,
                                "focus_role_id": selected["target_id"], "focus_role_name": selected["title"], "section_order": order,
                                "student_stage": student_stage,
                                "explainability_summary": {"headline_because": [
                                    f"{item['requirement']}：{CHECKS[item['status']]}。{item['reasoning']}"
                                    for item in list(selected_checks.values())[:4]]},
                                "dashboard_summary": {"headline": summary, "fit_score": None,
                                                      "fit_band_label": DECISIONS.get(selected_assessment.get("decision"), "信息不足")},
                                "evidence_health": {"strengths": strengths, "evidence_gaps": gaps, "evidence_trace": traces},
                                "plan_board": {"action_items": action_items}, "next_actions": {"action_items": action_items}}}
