import re
from datetime import date


def resume_date_context(text: str, analysis_date: date) -> list[dict]:
    current_month = (analysis_date.year, analysis_date.month)
    periods = []
    pattern = r"(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])\s*[-—–~至]\s*(20\d{2})\s*[./-]\s*(0?[1-9]|1[0-2])(?!\d)"
    for match in re.finditer(pattern, text):
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
