from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .schemas import REPORT_VERSION
from .provenance import report_provenance
from .development import HORIZONS, build_development_path, task_horizon
from .presentation import ReportPresentation, validate_reader_report
from .reader_sections import READER_LAYOUT, build_reader_sections
from .reading_format import number_report_headings


DECISIONS = {"recommended": "建议优先考虑", "conditional": "满足条件后考虑",
             "not_recommended": "暂不建议", "insufficient_information": "信息不足"}


def build_report_bundle(username, report_id, profile, state, model_name):
    from backend.advisor.telemetry import summarize_executions

    results = state["results"]
    decision = results["career_decision"].get("data", {})
    plan = results["action_planning"].get("data", {})
    review = state["review"]
    constraints = review["constraints"]
    student_stage = constraints.get("student_stage", "unspecified")
    presentation = ReportPresentation(state)
    selected = next(target for target in presentation.targets if target["target_id"] == review["target_id"])
    assessment = next((item for item in decision.get("assessments", []) if item["target_id"] == selected["target_id"]), {})
    checks = {item["check_id"]: item for item in assessment.get("checks", [])}
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    start = date.fromisoformat(constraints.get("start_date") or generated_at[:10])
    phases, checkpoints, _ = build_development_path(plan, checks, start)
    actions = []
    for task in plan.get("tasks", []):
        due = min(start + timedelta(days=task["week"] * 7 - 1), date.fromisoformat(constraints["deadline"]))
        requirement = checks.get(task["check_id"], {}).get("requirement", task["check_id"])
        horizon = task_horizon(start, due)
        phases[HORIZONS[horizon][2]].append({
            **task, "id": task["task_id"], "phase": f"{HORIZONS[horizon][0]} · 第{task['week']}周",
            "phase_key": horizon, "title": task["title"], "objective": task["deliverable"],
            "focus_points": [], "signals": [task["acceptance_criteria"]], "requirement": requirement,
            "is_action": True, "due_date": due.isoformat(),
        })
        actions.append({"id": task["task_id"], "title": task["title"], "deliverable": task["deliverable"],
                        "acceptance_criteria": task["acceptance_criteria"], "deadline": due.isoformat()})
    sections, order = build_reader_sections(state, profile, presentation, selected, assessment, checks, start)
    title = selected["title"]
    # Preserve the established document title while changing the reading layout.
    title += " · 职业生涯发展报告"
    markdown = f"# {title}\n\n" + "\n\n".join("## " + sections[key]["label"] + "\n\n" + sections[key]["markdown"] for key in order)
    markdown = number_report_headings(markdown)
    validate_reader_report(markdown)
    summary = presentation.clean(decision.get("summary", ""))
    strengths, gaps, traces, gap_rows = [], [], [], []
    for check in checks.values():
        (strengths if check["status"] == "supported" else gaps).append({"title": check["requirement"], "detail": check["reasoning"]})
        if check["status"] != "supported":
            priority = "P0 · 先核实准入条件" if check["kind"] == "hard_condition" else (
                "P1 · 必需能力" if check["importance"] == "required" else "P2 · 其他要求")
            gap_rows.append({"title": check["requirement"], "detail": check["reasoning"], "status": check["status"],
                             "priority": priority, "check_id": check["check_id"]})
        for evidence in check.get("job_evidence", []) + check.get("candidate_evidence", []):
            traces.append({"source": presentation.labels.get(evidence["source_id"], evidence["source_id"]),
                           "quote": evidence["quote"], "claim": presentation.clean(check["requirement"], target_id=selected["target_id"])})
    headline_because = [presentation.clean(item["reasoning"]) for item in list(checks.values())[:4]]
    meta = {"report_id": report_id, "username": username, "generated_at": generated_at, "status": "ready",
            "version": REPORT_VERSION, "pipeline_version": "experiments-langgraph-v5", "model": model_name,
            "provenance": report_provenance(state), "execution": summarize_executions(results),
            "content_validation": {"version": "reader-v3", "internal_references": "passed", "reading_layout": READER_LAYOUT},
            "generation_mode": "langgraph", "focus_role_id": selected["target_id"], "focus_role_name": selected["title"],
            "title": title, "summary": summary}
    return {"meta": meta, "profile_snapshot": {key: value for key, value in profile.items() if key not in {"agent_memory", "agent_workflow"}},
            "agent_results": results, "role_rankings": [], "match_output": {}, "career_path": {},
            "gap_map": presentation.data({"focus_role_name": selected["title"], "gaps": gap_rows}),
            "phase_plan": presentation.data({**phases, "checkpoints": checkpoints}),
            "report_document": {"title": title, "markdown": markdown, "sections": sections, "section_order": order,
                                "reading_layout": READER_LAYOUT, "executive_summary": summary,
                                "focus_role_id": selected["target_id"], "focus_role_name": selected["title"],
                                "student_stage": student_stage,
                                "explainability_summary": {"headline_because": headline_because},
                                "dashboard_summary": {"headline": summary, "fit_score": None,
                                                      "fit_band_label": DECISIONS.get(assessment.get("decision"), "")},
                                "evidence_health": presentation.data({"strengths": strengths, "evidence_gaps": gaps, "evidence_trace": traces}),
                                "plan_board": presentation.data({"action_items": actions}),
                                "next_actions": presentation.data({"action_items": actions})}}
