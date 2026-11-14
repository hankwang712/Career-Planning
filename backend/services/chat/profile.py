import json

from ..resume.documents import redact_contacts
from ..resume.facts import BASIC_KEYS
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
        if item["kind"] != "fact" or item["key"] not in BASIC_KEYS or item["status"] not in {"active", "conflict"}:
            continue
        same = [fact for fact in facts if fact["key"] == item["key"] and normalized(fact["subject"]) == normalized(item["subject"])]
        matching = next((fact for fact in same if normalized(fact["value"]) == normalized(item["value"])), None)
        source = {"type": "chat", "memory_id": item["id"], "source_session": item["source_session"],
                  "evidence": json.loads(item["evidence"])}
        status = "conflict" if item["status"] == "conflict" or any(fact["status"] == "conflict" for fact in same) or (
            same and not matching and item["key"] in BASIC_KEYS) else "confirmed"
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
    """聊天只读取用户自己填写的基础信息；画像分析、访谈、岗位排名、报告和简历细节属于报告 Agent，不进入聊天。"""
    report = report if isinstance(report, dict) else {}
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    profile = report.get("profile_snapshot") if isinstance(report.get("profile_snapshot"), dict) else {}
    form = profile.get("report_user_inputs") if isinstance(profile.get("report_user_inputs"), dict) else {}
    basics = {}
    if form.get("preferences"):
        basics["求职偏好（用户表单原文）"] = redact_contacts(form["preferences"])[:1200]
    if isinstance(profile.get("report_availability"), dict) and profile["report_availability"]:
        basics["实习安排（用户选择）"] = compact(profile["report_availability"])
    if document.get("focus_role_name"):
        basics["最近一次规划选择的目标岗位"] = str(document["focus_role_name"])[:120]
    return {"基础画像（历史提交，当前陈述优先）": basics} if basics else {}
