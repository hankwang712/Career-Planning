import re
from datetime import date


_DATE_RANGE = re.compile(r"(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])\s*[-—–~至]\s*(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])(?!\d)")


def resume_date_context(text: str, analysis_date: date) -> list[dict]:
    current_month = (analysis_date.year, analysis_date.month)
    periods = []
    for match in _DATE_RANGE.finditer(text):
        start_year, start_month, end_year, end_month = map(int, match.groups())
        start, end = (start_year, start_month), (end_year, end_month)
        relation = "past" if end < current_month else "current" if end == current_month else "future"
        periods.append({
            "source_quote": match.group(),
            "start_month": f"{start_year:04}-{start_month:02}",
            "end_month": f"{end_year:04}-{end_month:02}",
            "valid_order": start <= end,
            "end_relative_to_analysis_month": relation,
        })
    return periods


def education_timeline_context(text: str) -> list[dict]:
    """Compare stated study ranges with explicit enrollment months, including OCR-joined dates."""
    enrollments = [f"{int(match[1]):04}-{int(match[2]):02}" for match in re.finditer(
        r"(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])\s*入学", text)]
    result = []
    for match in _DATE_RANGE.finditer(text):
        start_year, start_month, end_year, end_month = map(int, match.groups())
        start, end = f"{start_year:04}-{start_month:02}", f"{end_year:04}-{end_month:02}"
        context = text[max(0, match.start() - 100):match.end() + 30]
        if not re.search(r"本科|硕士|博士|研究生|学历|教育经历|教育背景", context):
            continue
        for enrollment in enrollments:
            if start <= end:
                result.append({"study_period": match.group(), "study_end_month": end,
                               "enrollment_month": enrollment,
                               "overlaps": start <= enrollment <= end})
    return result


def verify_education_timeline_claims(value, raw_resume: str) -> list[str]:
    """Reject arithmetic contradictions; do not infer qualifications or judge genuine overlaps."""
    comparisons = [item for item in education_timeline_context(raw_resume) if not item["overlaps"]
                   and item["enrollment_month"] > item["study_end_month"]]
    errors = []

    def visit(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key not in {"quote", "source_quote", "evidence", "job_evidence", "candidate_evidence", "sources"}:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str) and re.search(r"本科|硕士|研究生|入学|教育", item):
            claim = re.sub(r"(?:不存在|不构成|没有|未出现|无).{0,8}?(?:重叠|冲突|矛盾)", "", item)
            if not re.search(r"(?:存在|出现|发生|时间|表述).{0,12}(?:重叠|冲突|矛盾)", claim):
                return
            for overlap in re.finditer(r"重叠|冲突|矛盾", claim):
                context = re.split(r"[。；\n]", claim[max(0, overlap.start() - 180):overlap.end()])[-1]
                if "入学" not in context or re.search(r"项目|实习|科研|兼职|工作", context):
                    continue
                months = {f"{int(match[1]):04}-{int(match[2]):02}" for match in re.finditer(
                    r"(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])(?!\d)", context)}
                for comparison in comparisons:
                    end, enrollment = comparison["study_end_month"], comparison["enrollment_month"]
                    if {end, enrollment} <= months:
                        errors.append(f"教育时间比较错误：{end} 结束早于 {enrollment} 入学，二者不重叠；请删除或修正该矛盾判断")
    visit(value)
    return list(dict.fromkeys(errors))
