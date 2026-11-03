from calendar import monthrange
from datetime import date


HORIZONS = {"short": ("短期", "1—3个月", "short_term", 3),
            "mid": ("中期", "3—12个月", "mid_term", 12),
            "long": ("长期", "1—3年", "long_term", 36)}
STUDENT_STAGES = {"exploration": "职业探索（大一、大二）", "employment": "就业准备（大三、大四及研究生）",
                  "unspecified": "学习阶段尚未说明"}


def months_after(start: date, months: int) -> date:
    total = start.year * 12 + start.month - 1 + months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(start.day, monthrange(year, month + 1)[1]))


def task_horizon(start: date, due: date) -> str:
    if due <= months_after(start, 3):
        return "short"
    return "mid" if due <= months_after(start, 12) else "long"


def build_development_path(plan, checks, start):
    phases = {value[2]: [] for value in HORIZONS.values()}
    checkpoints = []
    paragraphs = ["近期任务按已确认的时间和预算执行。以下路线是条件性发展目标，后续需结合课程、项目成果、实习进展和岗位需求重新确认。"]
    for milestone in plan.get("development_roadmap", []):
        key = milestone["horizon"]
        label, period, bucket, months = HORIZONS[key]
        paragraphs += [f"### {label}：{period}", milestone["objective"],
                       "进入条件：" + milestone["entry_conditions"]]
        actions = []
        for index, action in enumerate(milestone["actions"], 1):
            requirement = checks.get(action["check_id"], {}).get("requirement", action["check_id"])
            paragraphs += [f"- {action['title']}（对应要求：{requirement}）",
                           "  - 交付成果：" + action["deliverable"], "  - 验收标准：" + action["acceptance_criteria"]]
            actions.append({**action, "id": f"roadmap-{key}-{index}", "text": action["title"],
                            "requirement": requirement, "conditional": True})
        paragraphs += ["复核与调整：" + milestone["review_trigger"]]
        due = months_after(start, months).isoformat()
        phases[bucket].append({"id": f"roadmap-{key}", "phase": f"{label} · {period}", "phase_key": key,
                               "title": milestone["objective"], "objective": milestone["objective"],
                               "entry_conditions": milestone["entry_conditions"], "tasks": actions,
                               "review_trigger": milestone["review_trigger"], "due_date": due,
                               "is_roadmap": True, "focus_points": [], "signals": []})
        checkpoints.append({"id": f"review-{key}", "label": f"{label}阶段评估", "due_date": due,
                            "summary": milestone["review_trigger"]})
    if not plan.get("development_roadmap"):
        paragraphs.append("这份历史报告只有本阶段任务，尚未生成三阶段成长路线。可重新生成报告补充；不把近期任务自动当作长期规划。")
    return phases, checkpoints, "\n\n".join(paragraphs)
