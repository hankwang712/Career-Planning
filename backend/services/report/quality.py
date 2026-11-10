"""Final publication checks for facts and lossless rendering of scheduled tasks."""
from datetime import date, timedelta
from datetime import datetime
from zoneinfo import ZoneInfo
import re


def validate_analysis_for_publication(state):
    from backend.advisor.utils.resume_grounding import verify_resume_grounding
    from backend.advisor.utils.decision_grounding import verify_candidate_boundaries
    inputs = state.get("input", {})
    materials = dict(inputs)
    materials["analysis_date"] = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    answers = state.get("review", {}).get("answers", {})
    materials["additional_evidence"] = "\n".join(filter(None, [inputs.get("additional_evidence", ""),
        *(answer["answer"] for rows in answers.values() for answer in rows)]))
    results = state["results"]
    errors = verify_resume_grounding(results["resume_analysis"].get("data", {}), materials)
    factual = inputs.get("raw_resume", "") + "\n" + materials["additional_evidence"]
    for name in ("career_decision", "action_planning"):
        errors.extend(verify_candidate_boundaries(results[name].get("data", {}), factual))
    if state.get("decision_input"):
        from backend.advisor.agents.career_decision import CareerDecisionAgent, verify_career_decision
        errors.extend(verify_career_decision(results["career_decision"]["data"], CareerDecisionAgent.prepare(state["decision_input"])))
        from backend.advisor.agents.action_planning import ActionPlanningAgent, verify_action_plan
        from backend.advisor.schemas.action_planning import ActionPlan
        review = state["review"]
        prepared_plan = ActionPlanningAgent(None).prepare({"decision_input": state["decision_input"],
            "decision_result": results["career_decision"], "target_id": review["target_id"], "constraints": review["constraints"]})
        errors.extend(verify_action_plan(ActionPlan.model_validate(results["action_planning"]["data"]), prepared_plan))
    if errors:
        raise ValueError("报告事实校验未通过，需重新分析而不是直接发布：" + "；".join(dict.fromkeys(errors)))


def validate_rendered_tasks(text, tasks, start, deadline):
    normalize = lambda value: re.sub(r"\s+", "", value)
    # Check within each task, so another task's identical line cannot hide a missing field.
    blocks = re.split(r"(?m)^####\s+", text)
    end = date.fromisoformat(deadline)
    for task in tasks:
        block = next((block for block in blocks if block.split("\n", 1)[0].strip() == task["title"].strip()), "")
        due = min(start + timedelta(days=task["week"] * 7 - 1), end)
        required = [f"预计 {task['hours']:g} 小时，{due.isoformat()} 前完成", task["deliverable"], task["acceptance_criteria"]]
        if not block or any(normalize(value) not in normalize(block) for value in required):
            raise ValueError(f"报告任务 {task['task_id']} 的时间、交付物或验收标准未完整呈现，请重新整理报告")
