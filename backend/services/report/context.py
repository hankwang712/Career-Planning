"""Keep current form preferences separate from historical experience facts."""


def apply_report_memory(request, memory):
    request = dict(request)
    # An explicitly empty field is a user choice, not a request to restore history.
    if "preferences" not in request:
        request["preferences"] = memory.get("preferences", "")
    facts = memory.get("evidence", "")
    if facts:
        evidence = str(request.get("additional_evidence") or "")
        prefix = "\n记忆中的已确认经历事实（当前简历和当前输入优先；不代表当前求职偏好）：\n"
        remaining = 20000 - len(evidence) - len(prefix)
        if remaining > 0:
            request["additional_evidence"] = evidence + prefix + facts[:remaining]
    return request


def explicit_report_cities(preferences, search):
    """Only accept parsed cities actually named in the newly submitted field."""
    intent = (search.get("search_plan") or {}).get("intent") or {}
    cities = intent.get("cities") or []
    if not preferences or not cities or not all(isinstance(city, str) and city and city in preferences for city in cities):
        return ""
    # An additive statement is not permission to remove existing destinations.
    if any(word in preferences for word in ("也考虑", "也可以", "还考虑", "同时考虑", "不考虑", "不去", "排除")):
        return ""
    return "、".join(dict.fromkeys(cities))
