"""Conservative metadata filtering shared by offline/local retrieval.

Unknown or conflicting metadata is retained only when include_unknown is true.
No daily/annual/net salary conversion or inferred candidate qualifications.
"""
import re

DEGREES = {"中专": 0, "高中": 0, "大专": 1, "本科": 2, "硕士": 3, "博士": 4}
UNKNOWN = re.compile(r"未知|不限|未注明|未说明|面议|多地|全国|远程|^\s*$")


def monthly_salary(text):
    if re.search(r"[／/]天|元[／/]日|日薪|年薪|[／/]年|[／/]小时|时薪|税后|美元|美金|USD", text, re.I):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kK千万]?)\s*(?:[-~～—–至]\s*(\d+(?:\.\d+)?)\s*([kK千万]?))?\s*(?:元)?\s*(?:[/／]月|每月|月薪)?\s*(?:[·*×]\s*\d+薪)?\s*", text)
    if not match:
        return None
    scales = {"k": 1000, "千": 1000, "万": 10000, "": 1}
    low_unit, high_unit = match[2] or match[4] or "", match[4] or match[2] or ""
    low, high = float(match[1]) * scales[low_unit.lower()], float(match[3] or match[1]) * scales[high_unit.lower()]
    if not low_unit and "月" not in text:
        return None
    return (int(low), int(high)) if low <= high else None


def metadata(source):
    text = source["content"]
    def field(label):
        match = re.search(r"^(?:" + label + r")[：:]\s*([^\n]+)", text, re.M)
        return match[1].strip() if match else ""
    values = {**source.get("metadata", {})}
    for key, label in (("city", "城市|工作城市"), ("education", "学历"), ("salary", "薪资|薪酬|月薪|薪资范围")):
        values[key] = values.get(key) or field(label)
    locations = re.findall(r"(?:工作|实习|办公)地点\s*[：:]\s*([^\n。；;|]{2,100})", text)
    cities = [part.removesuffix("市") for part in re.split(r"[、/,，\s]+", values["city"]) if part]
    values["city_conflict"] = bool(values.get("city_conflict") or (locations and cities and not UNKNOWN.search(values["city"])
        and any(not any(city in location for city in cities) for location in locations)))
    values["monthly_salary_range"] = monthly_salary(values["salary"])
    return values


def filter_sources(sources, filters):
    result, excluded = [], 0
    for source in sources:
        values, unknown, allowed = metadata(source), [], True
        if filters.get("cities"):
            city = values["city"]
            if UNKNOWN.search(city) or values["city_conflict"]:
                unknown.append("city")
            elif not any(re.search(r"(?:^|[、/,，\s])" + re.escape(wanted.removesuffix("市")) + r"市?(?:区|$|[、/,，\s])", city)
                         for wanted in filters["cities"]):
                allowed = False
        if filters.get("candidate_education"):
            education = values["education"]
            levels = [level for degree, level in DEGREES.items() if degree in education]
            if education.strip() in {"不限", "学历不限", "无学历要求"}:
                pass
            elif not levels or re.search(r"优先|不限|未知|未注明|及以下|以下", education):
                unknown.append("education")
            elif DEGREES[filters["candidate_education"]] < min(levels):
                allowed = False
        low, high = filters.get("min_monthly_salary"), filters.get("max_monthly_salary")
        if low is not None or high is not None:
            salary = values["monthly_salary_range"]
            if salary is None:
                unknown.append("salary")
            elif (low is not None and salary[1] < low) or (high is not None and salary[0] > high):
                allowed = False
        if not allowed or (unknown and not filters.get("include_unknown", True)):
            excluded += 1
            continue
        values["unverified_conditions"] = unknown
        result.append({**source, "metadata": values})
    return result, excluded
