"""Contract checks between source relevance, requirement strength and cited text."""
import re


PREFERRED = re.compile(r"优先|加分|优选|更佳|preferred|nice[- ]to[- ]have|a plus", re.I)
EXCLUSION = re.compile(r"不(?:宜|应|能|可).{0,10}(?:并入|作为|等同)|与目标不符|无关样本|相关性较弱|非.{0,10}目标岗位")


def asserts_preference(statement):
    return bool(PREFERRED.search(re.sub(r"(?:而非|并非|不是|非)优先条件", "", statement)))


def preferred_condition_promoted(statement, quotes):
    """A quote may include an adjacent preference without promoting it.

    E.g. '本科在读，研究生优先' supports a required undergraduate/enrolled
    condition. Reject only preferred-only evidence or a claim using terms found
    exclusively in the preference, rather than blindly rejecting the whole quote.
    """
    clauses = [clause for quote in quotes for clause in re.split(r"[，,；;。\n]+", quote) if clause.strip()]
    preferred = [clause for clause in clauses if PREFERRED.search(clause)]
    ordinary = " ".join(clause for clause in clauses if not PREFERRED.search(clause))
    if not preferred:
        return False
    if not ordinary:
        return True
    for clause in preferred:
        stem = PREFERRED.split(clause)[0]
        stem = re.sub(r"^(?:\d+[.、\s]*|[-•]\s*)", "", stem)
        stem = re.sub(r"有过|具备|熟悉|掌握|了解|经验者|经验|相关|专业|背景|者|有", " ", stem)
        terms = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*|[\u4e00-\u9fff]{2,}", stem)
        if any(term.casefold() in statement.casefold() and term.casefold() not in ordinary.casefold() for term in terms):
            return True
    return False


def split_mixed_requirements(findings):
    """Split an explicitly mixed finding using only its literal evidence clauses.

    This changes neither facts nor source membership. It avoids repeatedly asking
    a model to split e.g. '本科在读，研究生优先' when the clauses already state the
    two strengths unambiguously.
    """
    result = []
    for finding in findings:
        if finding["category"] == "other" or finding["requirement"] != "required":
            result.append(finding)
            continue
        quotes = [item["quote"] for item in finding["evidence"]]
        if not (asserts_preference(finding["statement"]) or preferred_condition_promoted(finding["statement"], quotes)):
            result.append(finding)
            continue
        ordinary, preferred = [], []
        for evidence in finding["evidence"]:
            for clause in re.split(r"[，,；;。\n]+", evidence["quote"]):
                clause = clause.strip()
                if len(clause) < 2:
                    continue
                (preferred if PREFERRED.search(clause) else ordinary).append({**evidence, "quote": clause})
        if not preferred:
            # A preference in the statement without source support is still rejected.
            result.append(finding)
            continue
        for strength, evidence in (("required", ordinary), ("preferred", preferred)):
            if evidence:
                result.append({**finding, "requirement": strength, "statement": "；".join(item["quote"] for item in evidence),
                               "evidence": evidence})
    return result


def verify_job_grounding(data, sources, *, require_assessments=True):
    errors = []
    assessments = data.get("source_assessments", [])
    expected = {source["chunk_id"] for source in sources}
    classified = [item["chunk_id"] for item in assessments]
    if require_assessments and (set(classified) != expected or len(classified) != len(expected)):
        errors.append("source_assessments 必须恰好逐条覆盖本次所有来源，不得遗漏、重复或使用其他编号")
    direct = {item["chunk_id"] for item in assessments if item["relevance"] == "direct"}
    for index, finding in enumerate(data.get("findings", []), 1):
        if finding["category"] == "other":
            if finding["requirement"] != "unspecified":
                errors.append(f"findings[{index}] 的排除/范围说明必须是 other + unspecified，不能充当资格或能力门槛")
            continue
        if EXCLUSION.search(finding["statement"]):
            errors.append(f"findings[{index}] 承认与目标不符或不能并入，请移为 other/unspecified，不得同时输出核心要求")
        if require_assessments and any(item["chunk_id"] not in direct for item in finding["evidence"]):
            errors.append(f"findings[{index}] 核心要求只能引用职责直接相关的 direct 来源；相邻或无关样本只能作范围说明")
        if finding["requirement"] == "required" and preferred_condition_promoted(finding["statement"], [item["quote"] for item in finding["evidence"]]):
            errors.append(f"findings[{index}] 引文含优先/加分限定，不能整体作为 required；请拆分不同强制程度并分别给出原文")
        if finding["requirement"] == "required" and asserts_preference(finding["statement"]):
            errors.append(f"findings[{index}] 同一条不能合并明确要求和优先条件；请拆项而非删掉原文限定")
    return list(dict.fromkeys(errors))


def requirement_source_ids(data):
    """Only validated direct core findings can supply downstream requirement evidence."""
    direct = {item["chunk_id"] for item in data.get("source_assessments", []) if item["relevance"] == "direct"}
    return sorted({evidence["chunk_id"] for finding in data.get("findings", [])
                   if finding["category"] != "other" for evidence in finding["evidence"]
                   if evidence["chunk_id"] in direct})


def source_location_conflicts(sources):
    """Surface explicit header/body disagreements; do not infer cities from company names."""
    conflicts = []
    for source in sources:
        content = source["content"]
        header = re.search(r"^城市[：:]\s*([^\n]+)", content, re.M)
        if not header or re.search(r"未知|全国|多地|不限", header[1]):
            continue
        metadata = [part.strip() for part in re.split(r"[、,/，\s]+", header[1]) if part.strip()]
        body = content.partition("岗位描述：")[2]
        for match in re.finditer(r"(?:实习|工作|办公)地点\s*[：:]\s*([^\n。；;]{2,60})", body):
            if not any(city.removesuffix("市") in match[1] for city in metadata):
                conflicts.append({"chunk_id": source["chunk_id"], "metadata_city": header[1],
                                  "body_location": match[1], "quote": match[0]})
    return conflicts
