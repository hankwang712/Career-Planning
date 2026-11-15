"""The personality and interest assessments a user has actually completed, packaged as profile context.

Only tests the user took appear here; nothing is inferred for the others. Results are self-reports, so every
rendering says so: they describe how the user answered on one day, they are not a diagnosis and they do not
prove ability. The chat assistant and the report agents receive the same wording.
"""
from datetime import datetime

NAMES = {
    "mbti": "MBTI 性格倾向",
    "holland": "霍兰德职业兴趣",
    "deep": "深层 MBTI",
    "friends": "老友记角色",
    "insideout": "情绪主导",
    "sbti": "SBTI 人格扩展",
}
EXTENDED = ("deep", "friends", "insideout", "sbti")
# 趣味测评（老友记、情绪主导、SBTI）的角色名和类型名不进入画像，只保留分析文字。
NAMELESS = {"friends", "insideout", "sbti"}
SUMMARY_LIMIT = 450
DISCLAIMER = "用户自己完成的性格与兴趣测评（自评结果，只反映作答时的自我认知；不是诊断，也不能证明能力）"


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit] if isinstance(value, (str, int, float)) else ""


def _date(milliseconds):
    try:
        value = float(milliseconds)
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d") if 0 < value < 253402300799000 else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _latest_run(scope):
    runs = scope.get("history_runs", scope.get("historyRuns", []))
    stamps = [run.get("recordedAt") for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
    return max((stamp for stamp in stamps if isinstance(stamp, (int, float))), default=0)


def collect(state):
    """Completed tests, in a fixed order. A test that was not taken is simply absent."""
    state = state if isinstance(state, dict) else {}
    hub = state.get("assessment_hub") if isinstance(state.get("assessment_hub"), dict) else {}
    entries = []

    mbti = hub.get("mbti") if isinstance(hub.get("mbti"), dict) else {}
    result = _text(mbti.get("display_type") or mbti.get("final_type") or mbti.get("raw_type"), 20)
    if mbti.get("completed") and result:
        entries.append({"test": "mbti", "result": result, "summary": _text(mbti.get("summary"), 200),
                        "date": _date(_latest_run(mbti))})

    holland = hub.get("holland") if isinstance(hub.get("holland"), dict) else {}
    code = _text(holland.get("code"), 10)
    if holland.get("completed") and code:
        primary = holland.get("primary") if isinstance(holland.get("primary"), dict) else {}
        name = _text(primary.get("name"), 20)
        entries.append({"test": "holland", "result": f"{code}（主导：{name}）" if name else code,
                        "summary": _text(holland.get("summary"), 200), "date": _date(_latest_run(holland))})

    extended = state.get("deep_tests") if isinstance(state.get("deep_tests"), dict) else {}
    for test in EXTENDED:
        item = extended.get(test) if isinstance(extended.get(test), dict) else {}
        result = "" if test in NAMELESS else _text(item.get("result"), 60)
        summary = _text(item.get("summary"), SUMMARY_LIMIT)
        if result or (test in NAMELESS and summary):
            entries.append({"test": test, "result": result, "summary": summary, "date": _date(item.get("completed_at"))})
    return [{**entry, "name": NAMES[entry["test"]]} for entry in entries]


def describe(entries, limit=2600):
    """Plain text for prompts. Empty when no test was taken, so callers can skip the block entirely."""
    if not entries:
        return ""
    lines = [DISCLAIMER + "："]
    for entry in entries:
        when = f"（{entry['date']}）" if entry["date"] else ""
        lines.append(f"- {entry['name']}{when}：" + "。".join(part for part in (entry["result"], entry["summary"]) if part))
    return "\n".join(lines)[:limit]


def for_chat(entries):
    """Structured form for the chat context JSON."""
    if not entries:
        return None
    return {"说明": DISCLAIMER + "。只作为沟通方式和职业兴趣的参考，不要当作事实性经历或能力证据。",
            "结果": [{"测评": entry["name"], **({"结果": entry["result"]} if entry["result"] else {}),
                      **({"分析": entry["summary"]} if entry["summary"] else {}),
                      **({"完成日期": entry["date"]} if entry["date"] else {})} for entry in entries]}
