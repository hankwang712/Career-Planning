import json

from ..resume.documents import redact_contacts
from .storage import normalized


def unified_facts(resume, memories):
    """Merge sources as a view; chat never silently mutates resume facts."""
    facts = []
    for item in resume.get("facts", []):
        facts.append({"key": item["key"], "subject": item["subject"], "value": item["value"],
                      "sources": [{"type": "resume", "fingerprint": resume.get("fingerprint"),
                                   "document_id": resume.get("document_id"), "evidence": item.get("evidence", {})}],
                      "status": "confirmed"})
    for item in memories:
        if item["kind"] != "fact" or item["status"] not in {"active", "conflict"}:
            continue
        same = [fact for fact in facts if fact["key"] == item["key"] and normalized(fact["subject"]) == normalized(item["subject"])]
        matching = next((fact for fact in same if normalized(fact["value"]) == normalized(item["value"])), None)
        source = {"type": "chat", "memory_id": item["id"], "source_session": item["source_session"],
                  "evidence": json.loads(item["evidence"])}
        status = "conflict" if item["status"] == "conflict" or any(fact["status"] == "conflict" for fact in same) or (
            same and not matching and item["key"] in {"education", "graduation", "major"}) else "confirmed"
        if matching:
            matching["sources"].append(source)
            if status == "conflict":
                matching["status"] = status
        else:
            facts.append({"key": item["key"], "subject": item["subject"], "value": item["value"],
                          "sources": [source], "status": status})
        if status == "conflict":
            for fact in same:
                fact["status"] = "conflict"
    return {"facts": facts, "conflicts": [fact for fact in facts if fact["status"] == "conflict"]}


def compact(value, depth=0):
    if depth > 5:
        return None
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return [compact(item, depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        excluded = {"api_key", "password", "password_hash", "email", "phone", "file_path", "file_name",
                    "agent_memory", "agent_workflow", "raw_resume", "resume_source_text", "document", "storage_path", "upload_path"}
        return {str(key)[:80]: compact(item, depth + 1) for key, item in list(value.items())[:35]
                if str(key).lower() not in excluded}
    return None


def build_background(state, report=None):
    state = state if isinstance(state, dict) else {}
    def scope(name):
        value = state.get(name)
        return value if isinstance(value, dict) else {}
    profile = scope("profile_snapshot").get("profile", {})
    resume = scope("resume_profile").get("structured_resume", {})
    interview = scope("career_interview").get("profile", {})
    matching = scope("career_matching")
    report = report if isinstance(report, dict) else {}
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    metadata = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    report_profile = report.get("profile_snapshot") if isinstance(report.get("profile_snapshot"), dict) else {}
    form = report_profile.get("report_user_inputs") if isinstance(report_profile.get("report_user_inputs"), dict) else {}
    submitted = {key: redact_contacts(form[key]) for key in ("preferences", "additional_evidence") if form.get(key)}
    if isinstance(report_profile.get("report_availability"), dict) and report_profile["report_availability"]:
        submitted["实习安排（用户选择）"] = report_profile["report_availability"]
    if submitted:
        submitted["关联报告生成时间"] = metadata.get("generated_at")
    report_context = {"生成时间": metadata.get("generated_at"), "目标方向": document.get("focus_role_name"),
                      "执行摘要": document.get("executive_summary"), "差距分析": report.get("gap_map"),
                      "行动安排": report.get("phase_plan")} if report else {}
    # Each section has an independent budget, so a large resume cannot crowd out preferences.
    import json
    result = {}
    for name, value in (("用户表单原文（历史提交，当前陈述优先）", submitted),
                        ("职业画像（历史分析）", profile), ("简历结构化信息", resume),
                        ("职业访谈（历史分析）", interview),
                        ("岗位探索", {key: matching[key] for key in ("focus_role_id", "role_rankings") if key in matching}),
                        ("最近规划报告（历史建议，需结合当前情况）", report_context)):
        reduced = compact(value)
        if reduced:
            serialized = json.dumps(reduced, ensure_ascii=False)
            result[name] = reduced if len(serialized) <= 5000 else {"已保存信息摘录": serialized[:4800]}
    return result
