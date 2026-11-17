"""多处共用的文本整理小工具。"""
import re


def truncate_text(value, limit=140):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def compact_list(items, limit=4, item_limit=60):
    values = []
    for item in items or []:
        text = truncate_text(item, item_limit)
        if text and text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def safe_score(value, default=0):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default
