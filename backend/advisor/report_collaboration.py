"""Bounded handoffs from career decisions to grounded job analysis."""
from copy import deepcopy
import json
import re

from .schemas.career_decision import JobEvidenceRequest


MAX_EVIDENCE_ROUNDS = 2


def request_key(request):
    return request["target_id"], "".join(request["question"].split()).casefold()


def pending_evidence_requests(state):
    if state.get("evidence_rounds", 0) >= MAX_EVIDENCE_ROUNDS:
        return []
    targets = {target["target_id"] for target in state["results"]["job_analysis"]["data"]["targets"]}
    seen = {request_key(item["request"]) for item in state.get("evidence_attempts", [])}
    pending = []
    for raw in state["results"]["career_decision"].get("data", {}).get("evidence_requests", []):
        request = JobEvidenceRequest.model_validate(raw).model_dump()
        if request["target_id"] not in targets:
            raise ValueError("岗位补查只能使用本次已分析的目标")
        key = request_key(request)
        if key not in seen:
            pending.append(request)
            seen.add(key)
    return pending[:3]


def merge_job_evidence(current, supplement):
    """Retain earlier evidence and reject conflicting versions of the same source."""
    if supplement.get("status") == "insufficient_evidence":
        return current, "no_new_evidence"
    if supplement.get("status") != "ok" or not supplement.get("sources"):
        return current, "unavailable"
    sources = {source["chunk_id"]: source for source in current.get("sources", [])}
    for source in supplement["sources"]:
        previous = sources.get(source["chunk_id"])
        if previous and any(previous.get(key) != source.get(key) for key in ("content", "file_path")):
            return current, "unavailable"
    merged = deepcopy(current)
    added = False
    for source in supplement["sources"]:
        if source["chunk_id"] not in sources:
            merged.setdefault("sources", []).append(deepcopy(source))
            sources[source["chunk_id"]] = source
            added = True
    for key in ("findings", "related_roles"):
        existing = merged["data"].setdefault(key, [])
        seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in existing}
        for item in supplement["data"].get(key, []):
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if identity not in seen:
                existing.append(deepcopy(item))
                seen.add(identity)
                added = True
    if not added:
        return current, "no_new_evidence"
    merged["data"]["summary"] = current["data"]["summary"] + "\n补查：" + supplement["data"]["summary"]
    merged["data"]["limitations"] = list(dict.fromkeys(
        current["data"].get("limitations", []) + supplement["data"].get("limitations", [])))
    paths = {source.get("file_path", "") for source in merged["sources"]
             if re.fullmatch(r".+\.txt#record=\d+", source.get("file_path", ""), flags=re.IGNORECASE)}
    scope = deepcopy(current.get("scope", {}))
    # 初次查询的统计不能继续表示合并后的查询范围。
    for key in ("retrieved_chunk_count", "entity_count", "relationship_count"):
        scope.pop(key, None)
    merged["scope"] = {
        **scope, "chunk_count": len(merged["sources"]), "jd_record_count": len(paths),
        "unidentified_source_count": sum(source.get("file_path", "") not in paths for source in merged["sources"]),
        "description": "初次检索与定向补查合并的岗位样本，不代表全库、全市场或实时招聘状态。",
    }
    return merged, "added"


def collaboration_summary(state):
    return {"round_limit": MAX_EVIDENCE_ROUNDS, "rounds_used": state.get("evidence_rounds", 0),
            "attempts": deepcopy(state.get("evidence_attempts", []))}
