"""主站的简短确认策略；实验工作流仍保留原问题和原始证据。"""

import re


REVIEW_POLICY = """
主站交互要求：followup_questions 最多 2 条，只问会改变本次决策、且用户本人能够回答的未知信息。
先检查 raw_resume、preferences、additional_evidence、clarifications 和来源中的用户原文。
用户已经明确给出的城市、到岗时间、每周实习天数、工作时长接受度等，不得换一种说法重复询问。
优先询问与当前岗位要求有关的个人意愿，如是否接受已明确提及的较长工时、出差或异地工作。
每条只问一个具体问题，用简短日常语言；不要求用户再次长篇介绍项目，不为凑数量提问。
招聘批次、招聘方是否接受某届毕业生、投递窗口等应由招聘方核实，写入 limitations 或 next_actions，
不得把核实招聘信息的工作变成对用户的追问。没有必要的问题时返回空列表。
"""

ARRIVAL_OPTIONS = {
    "now": "随时到岗", "one_week": "一周内到岗", "two_weeks": "两周内到岗",
    "one_month": "一个月内到岗", "winter": "寒假开始实习", "summer": "暑假开始实习",
    "undecided": "到岗时间待确认",
}


def apply_availability(payload, preferences=""):
    """只保存用户明确选择的实习安排，不换算为学习/求职准备工时。"""
    if payload is None:
        return {}, preferences
    if not isinstance(payload, dict) or set(payload) - {"arrival", "days_per_week"}:
        raise ValueError("实习安排格式不正确")
    arrival = payload.get("arrival")
    days = payload.get("days_per_week")
    if arrival not in ARRIVAL_OPTIONS or type(days) is not int or not 0 <= days <= 7:
        raise ValueError("请选择到岗时间和每周可实习天数；尚未确定时请选择待确认")
    labels = [ARRIVAL_OPTIONS[arrival], f"每周可实习 {days} 天" if days else "每周实习天数待确认"]
    text = str(preferences or "").strip()
    return {"arrival": arrival, "days_per_week": days, "summary": "，".join(labels)}, "\n".join(filter(None, [text, "实习安排（用户选择）：" + "，".join(labels)]))


def known_availability(inputs, profile):
    structured = profile.get("report_availability") or {}
    if structured.get("summary"):
        return structured["summary"]
    text = str(inputs.get("preferences") or "")
    facts = []
    arrival = re.search(r"随时(?:到岗|入职|实习)|(?:一|两|二|三|[1-4])(?:周|个月|月)内(?:到岗|入职)|(?:寒假|暑假)(?:开始)?实习", text)
    days = re.search(r"(?:每周|一周|周)[^\n，。；]{0,8}?[1-7一二两三四五六七]\s*天(?:实习)?", text)
    if arrival:
        facts.append(arrival.group())
    if days:
        facts.append(days.group())
    return "，".join(facts)


def _already_known(question, known, preferences):
    # 学校/居住地不能自动当成用户的意向工作城市。
    if re.search(r"(?:哪个|哪些|什么|目标|意向|接受|希望).*(?:城市|地点)", question):
        return bool(re.search(r"上海|北京|杭州|深圳|广州|成都|南京|武汉|苏州|工作城市|意向城市", preferences)
                    or re.search(r"(?:意向城市|工作城市|求职地点)\s*[:：]\s*\S+", known))
    topics = (
        (r"到岗|何时.*实习|什么时候.*实习", r"随时到岗|到岗时间|(?:周|月)内到岗|假开始实习"),
        (r"(?:每周|一周|每星期).*(?:几天|多少天|实习天数)", r"(?:每周|一周|每星期)[^\n，。；]{0,10}[1-7一二两三四五六七]\s*天|每周实习天数待确认"),
        (r"加班|工作时长|工时|工作时间", r"(?:接受|不接受|可以|不能|不考虑|拒绝)[^\n，。；]{0,8}(?:加班|长工时)|(?:加班|工作时长)[^\n，。；]{0,8}(?:接受|不接受|可以|不能)"),
        (r"出差", r"(?:接受|不接受|可以|不能|拒绝)[^\n，。；]{0,5}出差"),
    )
    return any(re.search(topic, question) and re.search(evidence, known) for topic, evidence in topics)


def build_review_ui(review, inputs=None, profile=None):
    if not review:
        return None
    inputs, profile = inputs or {}, profile or {}
    known = "\n".join(str(inputs.get(key) or "") for key in ("raw_resume", "preferences", "additional_evidence"))
    preferences = "\n".join(str(inputs.get(key) or "") for key in ("preferences", "additional_evidence"))
    cards, seen = [], set()
    # 决策 Agent 已看到全部候选人材料；每段经历的诊断追问保留在报告中，不逐项拦截用户。
    for question in review.get("questions", {}).get("career_decision", []):
        question = str(question).strip()
        key = re.sub(r"[\s，。！？?、：:]", "", question)
        employer_only = re.search(r"(?:JD\d*|该岗位|该职位|这条|招聘方|公司).*(?:毕业批次|哪.*批次|投递窗口|投递时间|是否.*(?:毕业生|投递)|是否接受.*毕业)", question, re.I)
        if not key or key in seen or employer_only or _already_known(question, known, preferences):
            continue
        seen.add(key)
        choices = []
        if re.search(r"接受|愿意|能否.*(?:加班|出差)|是否.*(?:加班|出差)", question):
            choices = ["可以接受", "需要先了解具体安排", "不接受"]
        cards.append({"agent": "career_decision", "question": question, "choices": choices})
        if len(cards) == 2:
            break
    return {"questions": cards, "availability_summary": known_availability(inputs, profile)}
