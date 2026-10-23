from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "data"
OUTPUT_PATH = ROOT / "public" / "assessment-data.json"
SOURCE_BANK_MARKER = ("MBTI职业性格测试题", "全套霍兰德职业兴趣测试题")
MBTI_KNOWLEDGE_FILE = ROOT / "raw" / "MBTI知识.md"
HOLLAND_KNOWLEDGE_FILE = ROOT / "raw" / "霍兰德知识库.md"

MBTI_COLUMNS = ["E", "I", "S", "N", "T", "F", "J", "P"]
MBTI_PAIR_ORDER = [("E", "I"), ("S", "N"), ("T", "F"), ("J", "P")]
MBTI_TIE_BREAKERS = {"EI": "I", "SN": "N", "TF": "F", "JP": "P"}
MBTI_PAIR_HINTS = {
    "EI": {
        "title": "精力来源",
        "left_label": "外向 E",
        "right_label": "内向 I",
        "left_desc": "更容易从互动、表达和外部刺激中获得能量。",
        "right_desc": "更容易从独处、思考和内在世界中恢复能量。",
    },
    "SN": {
        "title": "信息获取",
        "left_label": "感觉 S",
        "right_label": "直觉 N",
        "left_desc": "更关注事实、细节、经验和当下可验证的信息。",
        "right_desc": "更关注趋势、模式、可能性和抽象概念。",
    },
    "TF": {
        "title": "决策偏好",
        "left_label": "思考 T",
        "right_label": "情感 F",
        "left_desc": "更倾向按逻辑、规则和客观标准做判断。",
        "right_desc": "更倾向兼顾价值、关系和他人感受做判断。",
    },
    "JP": {
        "title": "生活方式",
        "left_label": "判断 J",
        "right_label": "感知 P",
        "left_desc": "更喜欢计划、结构和可预期的推进节奏。",
        "right_desc": "更喜欢灵活、开放和边走边调整的节奏。",
    },
}
MBTI_PAIR_EXTRA = {
    "EI": {
        "plain_language": ["E 往往在交流中充电", "I 往往在独处和反思中恢复能量"],
        "workplace_focus": ["偏好协作、表达与外部反馈", "偏好独立思考、沉淀与深度处理"],
        "development_tip": "如果你在 E/I 之间接近，关键不是社交多少，而是高强度互动后你更容易被激活还是被消耗。",
    },
    "SN": {
        "plain_language": ["S 更看重现实细节", "N 更容易看到趋势与可能"],
        "workplace_focus": ["适合具体执行、经验沉淀和稳定流程", "适合概念建模、创新探索和远景推演"],
        "development_tip": "如果你在 S/N 之间接近，可以回看自己在做决策时，到底更依赖事实样本还是未来假设。",
    },
    "TF": {
        "plain_language": ["T 更重逻辑与原则", "F 更重价值与关系感受"],
        "workplace_focus": ["适合规则清晰、强调判断一致性的情境", "适合协作密集、需要理解他人动机的情境"],
        "development_tip": "如果你在 T/F 之间接近，重点看你在高压决策里更先问“是否合理”还是“是否合适”。",
    },
    "JP": {
        "plain_language": ["J 更偏计划和节奏控制", "P 更偏灵活探索和边走边调"],
        "workplace_focus": ["适合里程碑明确、收敛推进的任务", "适合试错迭代、信息不完整的任务"],
        "development_tip": "如果你在 J/P 之间接近，注意你面对截止日期时更倾向提前收口还是临场整合。",
    },
}
MBTI_TYPE_OVERVIEWS = {
    "ISTJ": "稳健务实，强调责任、秩序与执行落地。",
    "ISFJ": "细腻可靠，重视照顾他人与维持稳定。",
    "INFJ": "理想坚定，善于洞察人和长期愿景。",
    "INTJ": "独立深思，擅长系统规划与战略判断。",
    "ISTP": "冷静实操，善于拆解问题并快速修正。",
    "ISFP": "温和低调，注重体验、价值和真实感受。",
    "INFP": "理想主义，关注价值一致性与个人意义。",
    "INTP": "理性好奇，喜欢分析框架和概念建模。",
    "ESTP": "反应迅速，偏好行动、现场判断和结果。",
    "ESFP": "热情开放，擅长互动、体验和氛围带动。",
    "ENFP": "富有想象力，擅长连接机会与激励他人。",
    "ENTP": "点子密集，善于辩证思考与挑战常规。",
    "ESTJ": "讲求效率，擅长组织、管理与推动执行。",
    "ESFJ": "合作导向，重视关系、协作与具体支持。",
    "ENFJ": "善于带人，关注成长、共识与团队氛围。",
    "ENTJ": "目标明确，擅长统筹资源与战略推进。",
}
MBTI_TYPE_NAMES = {
    "INTJ": "建筑师",
    "INTP": "逻辑学家",
    "ENTJ": "指挥官",
    "ENTP": "辩论家",
    "INFJ": "提倡者",
    "INFP": "调停者",
    "ENFJ": "主人公",
    "ENFP": "竞选者",
    "ISTJ": "物流师",
    "ISFJ": "守卫者",
    "ESTJ": "总经理",
    "ESFJ": "执政官",
    "ISTP": "鉴赏家",
    "ISFP": "探险家",
    "ESTP": "企业家",
    "ESFP": "表演者",
}
MBTI_CATEGORY_PROFILES = {
    "NT": {
        "label": "分析师 NT",
        "strengths": ["抽象分析能力强", "擅长系统性拆解问题", "重视能力成长与长期竞争力"],
        "risks": ["容易显得过于理性", "对低效协作容忍度低", "如果缺少行动闭环，想法可能停留在概念层"],
        "advice": ["把复杂问题拆成阶段目标", "在表达观点时同时说明逻辑与行动方案", "主动补强沟通耐心和协作反馈"],
    },
    "NF": {
        "label": "外交家 NF",
        "strengths": ["善于理解人和动机", "通常有较强表达与感染力", "重视价值感、成长和意义"],
        "risks": ["容易理想化", "可能因顾及关系影响决断", "在高压或重复事务中容易消耗"],
        "advice": ["把热情落到明确成果物上", "建立稳定的任务节奏", "在理想与现实之间保留可执行方案"],
    },
    "SJ": {
        "label": "守护者 SJ",
        "strengths": ["稳定可靠", "重视规则、责任与秩序", "在流程执行和日常协同中表现稳健"],
        "risks": ["对不确定环境适应稍慢", "可能保守", "过度承担责任时容易内耗"],
        "advice": ["在稳定优势之外主动尝试新任务", "把经验沉淀为方法论", "练习在变化中做小步试错"],
    },
    "SP": {
        "label": "探险家 SP",
        "strengths": ["反应快、适应性强", "重视真实体验", "在现场问题处理与试错中有优势"],
        "risks": ["容易分散注意力", "若缺少结构支撑，长期规划可能不足", "对重复和约束场景耐受较低"],
        "advice": ["把灵活性与最小计划结合", "给关键任务设置检查点", "用作品或结果沉淀优势而不是只靠体验积累"],
    },
}
MBTI_LETTER_WORK_STYLE = {
    "E": {"style": "更容易在互动中形成想法并获取反馈", "risk": "可能在深度独处任务中分心", "advice": "把表达优势用于澄清目标和推动协作"},
    "I": {"style": "更适合先独立思考再输出结论", "risk": "可能延迟表达观点", "advice": "提前准备关键观点，降低公开表达门槛"},
    "S": {"style": "重视细节、经验和现实可行性", "risk": "可能低估新方向的可能性", "advice": "在事实判断后多追问一步“还有没有别的路径”"},
    "N": {"style": "擅长连接模式、趋势与可能性", "risk": "可能忽略落地细节", "advice": "让创意始终绑定可验证动作"},
    "T": {"style": "偏好依据逻辑和标准做判断", "risk": "可能忽略关系感受", "advice": "表达结论时同步说明对人的影响"},
    "F": {"style": "偏好兼顾价值感和关系状态", "risk": "可能为了和谐牺牲效率", "advice": "先确认底线标准，再讨论情感与关系"},
    "J": {"style": "偏好计划、结构和提前收口", "risk": "可能对变化过敏", "advice": "把计划分层，给变化留缓冲"},
    "P": {"style": "偏好开放、灵活和边做边调", "risk": "可能拖延或收口不足", "advice": "给探索设置明确的时间边界"},
}

HOLLAND_TYPE_META = {
    "R": {
        "name": "现实型",
        "description": "偏好动手、工具、设备和具体任务，通常更享受看得见、可操作的工作场景。",
    },
    "I": {
        "name": "研究型",
        "description": "偏好分析、探索、推理与求知，更容易被复杂问题和未知领域吸引。",
    },
    "A": {
        "name": "艺术型",
        "description": "偏好表达、创造、审美和新颖性，希望通过作品体现个性与想法。",
    },
    "S": {
        "name": "社会型",
        "description": "偏好助人、沟通、陪伴和支持，在人与人的连接中更容易获得价值感。",
    },
    "E": {
        "name": "企业型",
        "description": "偏好影响、说服、组织和推进，通常对目标、竞争和结果更敏感。",
    },
    "C": {
        "name": "常规型",
        "description": "偏好秩序、规则、结构和细节，擅长在清晰流程中稳定输出。",
    },
}
HOLLAND_TYPE_NAMES = {
    "现实型": "R",
    "研究型": "I",
    "艺术型": "A",
    "社会型": "S",
    "企业型": "E",
    "常规型": "C",
    "实际型": "R",
    "调研型": "I",
}
HOLLAND_TYPE_DETAILS = {
    "R": {
        "traits": ["重视动手与操作", "偏好具体任务", "喜欢工具、设备与现场感"],
        "typical_environment": ["设备/系统可操作", "任务目标明确", "更少纯概念讨论"],
        "risks": ["如果工作长期纯抽象，容易失去投入感", "在人际密集岗位上可能消耗较快"],
        "development_advice": ["把实践经验沉淀成方法", "补强沟通与复盘能力", "在技能提升中保留可见成果物"],
    },
    "I": {
        "traits": ["喜欢探索与分析", "擅长逻辑推理", "对知识和复杂问题敏感"],
        "typical_environment": ["允许研究和试验", "问题复杂但目标清晰", "可以持续学习与深挖"],
        "risks": ["可能停留在思考层", "若流程琐碎且重复，成就感下降较快"],
        "development_advice": ["让研究结果产品化或项目化", "主动连接业务场景", "通过作品证明分析深度"],
    },
    "A": {
        "traits": ["强调创造、表达和审美", "重视个性化产出", "对新颖性与表达空间敏感"],
        "typical_environment": ["允许创意表达", "评价标准不止一种", "鼓励作品和内容输出"],
        "risks": ["在过度流程化环境中容易受限", "可能忽视现实约束和执行边界"],
        "development_advice": ["让创意绑定明确目标", "积累作品集", "在审美表达之外补强协作落地能力"],
    },
    "S": {
        "traits": ["乐于助人", "重视人际互动", "对支持、培训、陪伴类工作更有感"],
        "typical_environment": ["高质量协作", "有助人成就感", "反馈来自真实的人际影响"],
        "risks": ["容易把他人需求置于自己之前", "在人际冲突环境中消耗明显"],
        "development_advice": ["建立边界感", "把沟通优势转成专业能力", "沉淀服务方法和支持流程"],
    },
    "E": {
        "traits": ["看重目标、推进和影响力", "愿意说服、组织和带动资源", "对竞争和结果较敏感"],
        "typical_environment": ["目标导向", "需要协调资源", "成果能被清晰评价"],
        "risks": ["可能急于推进而忽略细节", "在缺少自主空间时容易失去动力"],
        "development_advice": ["在推进之外保留复盘机制", "补强细节闭环", "让影响力建立在专业可信度上"],
    },
    "C": {
        "traits": ["重视秩序和结构", "擅长规则执行与信息整理", "在明确流程中稳定输出"],
        "typical_environment": ["规则清晰", "流程稳定", "标准化与准确性要求高"],
        "risks": ["对变化和模糊环境适应偏慢", "容易在过度重复中降低热情"],
        "development_advice": ["在稳定优势基础上增加小范围创新", "把细节能力转成可迁移方法", "练习在变化中保持结构感"],
    },
}


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_source_text() -> str:
    for path in sorted((ROOT / "raw").glob("*.md")):
        text = load_text(path)
        if all(marker in text for marker in SOURCE_BANK_MARKER):
            return text
    raise FileNotFoundError("未找到包含 MBTI 与霍兰德题库的 Markdown 文件")


def load_existing_payload() -> dict:
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError("未找到可回退的 assessment-data.json")
    payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("assessment-data.json 格式异常")
    return payload


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_markdown(text: str) -> str:
    value = html.unescape(text)
    value = value.replace("<br/>", "\n").replace("<br>", "\n")
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    return value.strip()


def split_question_and_options(raw_desc: str) -> tuple[str, str, str]:
    text = strip_markdown(raw_desc)
    normalized = normalize_spaces(text.replace("\n", " "))
    patterns = [
        r"^(?P<stem>.*?)(?:\s+)?A[\.．]?\s*(?P<a>.*?)[，,；;]?\s*B[\.．]?\s*(?P<b>.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            stem = match.group("stem").strip(" ：:")
            option_a = match.group("a").strip(" ，,；;")
            option_b = match.group("b").strip(" ，,；;")
            if not stem:
                stem = "以下哪一项更符合你？"
            return stem, option_a, option_b
    return text, "偏向前者", "偏向后者"


def parse_mbti_questions(text: str) -> list[dict]:
    start = text.index("# 一、")
    end = text.index("# 四、")
    section = text[start:end]
    questions: list[dict] = []
    pending: dict | None = None

    for line in section.splitlines():
        raw = line.strip()
        if not raw.startswith("|") or raw.startswith("| :---"):
            continue
        parts = [part.strip() for part in raw.split("|")[1:-1]]
        if len(parts) != 11 or parts[0] == "序号":
            continue

        markers = dict(zip(MBTI_COLUMNS, parts[3:11]))
        selected_letters = [letter for letter, marker in markers.items() if "○" in marker]
        if len(selected_letters) != 1:
            continue

        if parts[0].isdigit():
            pending = {
                "id": int(parts[0]),
                "raw_desc": parts[1],
                "left": selected_letters[0],
            }
            continue

        if pending is None:
            continue

        right = selected_letters[0]
        prompt, option_a, option_b = split_question_and_options(pending["raw_desc"])
        left = pending["left"]
        questions.append(
            {
                "id": pending["id"],
                "prompt": prompt,
                "option_a": option_a,
                "option_b": option_b,
                "a_letter": left,
                "b_letter": right,
            }
        )
        pending = None

    if len(questions) != 93:
        raise ValueError(f"MBTI 题目数异常，期望 93，实际 {len(questions)}")
    return questions


def parse_mbti_careers(text: str) -> dict[str, list[str]]:
    marker = "MBTI各种性格类型的常见适合职业举例"
    if marker not in text:
        return {}
    section = text.split(marker, 1)[1].split("全套霍兰德职业兴趣测试题", 1)[0]
    careers: dict[str, list[str]] = {}
    for line in section.splitlines():
        clean = normalize_spaces(strip_markdown(line))
        match = re.match(r"^(ISTJ|ISFJ|INFJ|INTJ|ISTP|ISFP|INFP|INTP|ESTP|ESFP|ENFP|ENTP|ESTJ|ESFJ|ENFJ|ENTJ)\s+(.+)$", clean)
        if not match:
            continue
        mbti_type = match.group(1)
        items = [
            item.strip(" .")
            for item in re.split(r"[，,、]", match.group(2))
            if item.strip(" .")
        ]
        careers[mbti_type] = items
    return careers


def parse_holland_questions(text: str) -> list[dict]:
    section = text.split("本问卷共90道题目", 1)[1].split("评分办法：", 1)[0]
    section = section.replace("\t", "\n")
    questions: list[dict] = []
    for line in section.splitlines():
        clean = line.strip()
        match = re.match(r"^(\d+)\.\s*(.+)$", clean)
        if not match:
            continue
        questions.append(
            {
                "id": int(match.group(1)),
                "prompt": match.group(2).strip(),
            }
        )
    questions.sort(key=lambda item: item["id"])
    if len(questions) != 90:
        raise ValueError(f"霍兰德题目数异常，期望 90，实际 {len(questions)}")
    return questions


def parse_holland_groups(text: str) -> dict[str, list[int]]:
    section = text.split("评分办法：", 1)[1].split("根据分数绘制雷达图", 1)[0]
    groups: dict[str, list[int]] = {}
    for line in section.splitlines():
        clean = normalize_spaces(line)
        if not clean:
            continue
        match = re.match(r"^(现实型|研究型|艺术型|社会型|企业型|常规型)\s+(.+)$", clean)
        if not match:
            continue
        code = HOLLAND_TYPE_NAMES[match.group(1)]
        numbers = [int(value) for value in re.findall(r"\d+", match.group(2))]
        groups[code] = numbers
    if set(groups) != {"R", "I", "A", "S", "E", "C"}:
        raise ValueError(f"霍兰德分组异常: {groups.keys()}")
    return groups


def parse_holland_details(text: str) -> dict[str, dict]:
    section = text.split("【六种类型内容】", 1)[1].split("正式进入答题环节", 1)[0]
    pattern = re.compile(
        r"\d+、(?P<name>社会型|企业型|常规型|实际型|调研型|艺术型)：\((?P<code>[A-Z])\)\s+共同特[征点]：(?P<feature>.+?)\s+典型职业：(?P<jobs>.+?)(?=\s+\d+、|\Z)",
        re.S,
    )
    details: dict[str, dict] = {}
    for match in pattern.finditer(section):
        code = match.group("code").strip()
        details[code] = {
            "name": match.group("name").strip(),
            "feature": normalize_spaces(match.group("feature")),
            "careers": [
                item.strip(" 。.")
                for item in re.split(r"[，,。；;]", normalize_spaces(match.group("jobs")))
                if item.strip(" 。.")
            ],
        }
    for code, base in HOLLAND_TYPE_META.items():
        details.setdefault(code, {"name": base["name"], "feature": base["description"], "careers": []})
    return details


def parse_holland_knowledge_profiles(text: str) -> dict[str, dict]:
    heading_pattern = re.compile(r"^(实际型|调研型|艺术型|社会型|企业型|常规型)\s*$", re.M)
    matches = list(heading_pattern.finditer(text))
    profiles: dict[str, dict] = {}
    for index, match in enumerate(matches):
        raw_name = match.group(1).strip()
        code = HOLLAND_TYPE_NAMES.get(raw_name)
        if not code:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        feature_match = re.search(r"共同特[点征]：\s*(.+?)(?:典型职业：|$)", block, re.S)
        jobs_match = re.search(r"典型职业：\s*(.+)$", block, re.S)
        alias_match = re.search(r"又称为[“\"]?([^”\"\n]+)", block)

        feature_text = normalize_spaces(strip_markdown(feature_match.group(1))) if feature_match else ""
        jobs_text = normalize_spaces(strip_markdown(jobs_match.group(1))) if jobs_match else ""
        careers = [
            item.strip(" 。.")
            for item in re.split(r"[，,、；;。]", jobs_text)
            if item.strip(" 。.")
        ]
        profiles[code] = {
            "alias": normalize_spaces(strip_markdown(alias_match.group(1))) if alias_match else "",
            "summary": feature_text,
            "career_examples": list(dict.fromkeys(careers))[:10],
        }
    return profiles


def parse_mbti_table_summaries(text: str) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^\|\s*(?:\*\*)?(INTJ|INTP|ENTJ|ENTP|INFJ|INFP|ENFJ|ENFP|ISTJ|ISFJ|ESTJ|ESFJ|ISTP|ISFP|ESTP|ESFP)(?:\*\*)?\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        type_code, nickname, summary = match.groups()
        results[type_code] = {
            "nickname": normalize_spaces(nickname),
            "summary": normalize_spaces(strip_markdown(summary)),
        }
    return results


def build_mbti_dimension_explanations() -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for pair, hint in MBTI_PAIR_HINTS.items():
        payload[pair] = {
            **hint,
            **MBTI_PAIR_EXTRA[pair],
        }
    return payload


def build_mbti_type_details(careers: dict[str, list[str]], mbti_knowledge_text: str) -> dict[str, dict]:
    table_data = parse_mbti_table_summaries(mbti_knowledge_text)
    details: dict[str, dict] = {}
    for mbti_type, overview in MBTI_TYPE_OVERVIEWS.items():
        group_key = mbti_type[1] + (mbti_type[2] if mbti_type[1] == "N" else mbti_type[3])
        category = MBTI_CATEGORY_PROFILES[group_key]
        nickname = table_data.get(mbti_type, {}).get("nickname") or MBTI_TYPE_NAMES[mbti_type]
        summary = table_data.get(mbti_type, {}).get("summary") or overview
        work_style = [
            MBTI_LETTER_WORK_STYLE[mbti_type[0]]["style"],
            MBTI_LETTER_WORK_STYLE[mbti_type[1]]["style"],
            MBTI_LETTER_WORK_STYLE[mbti_type[3]]["style"],
        ]
        strengths = list(dict.fromkeys(category["strengths"] + [
            MBTI_LETTER_WORK_STYLE[mbti_type[0]]["style"],
            MBTI_LETTER_WORK_STYLE[mbti_type[3]]["advice"].replace("把", "具备").replace("给", "具备"),
        ]))[:4]
        risks = list(dict.fromkeys(category["risks"] + [
            MBTI_LETTER_WORK_STYLE[mbti_type[0]]["risk"],
            MBTI_LETTER_WORK_STYLE[mbti_type[3]]["risk"],
        ]))[:4]
        advice = list(dict.fromkeys(category["advice"] + [
            MBTI_LETTER_WORK_STYLE[mbti_type[0]]["advice"],
            MBTI_LETTER_WORK_STYLE[mbti_type[3]]["advice"],
        ]))[:4]
        details[mbti_type] = {
            "nickname": nickname,
            "temperament": category["label"],
            "summary": summary,
            "strengths": strengths,
            "risks": risks,
            "work_style": work_style,
            "career_advice": advice,
            "career_examples": careers.get(mbti_type, []),
        }
    return details


def build_holland_type_details(type_meta: dict[str, dict], holland_knowledge_text: str) -> dict[str, dict]:
    extracted_profiles = parse_holland_knowledge_profiles(holland_knowledge_text)
    payload: dict[str, dict] = {}
    for code, meta in type_meta.items():
        extra = HOLLAND_TYPE_DETAILS.get(code, {})
        extracted = extracted_profiles.get(code, {})
        career_examples = list(dict.fromkeys((meta.get("careers") or []) + (extracted.get("career_examples") or [])))[:10]
        payload[code] = {
            "name": meta.get("name") or HOLLAND_TYPE_META[code]["name"],
            "alias": extracted.get("alias") or "",
            "summary": extracted.get("summary") or meta.get("description") or HOLLAND_TYPE_META[code]["description"],
            "traits": extra.get("traits", []),
            "typical_environment": extra.get("typical_environment", []),
            "risks": extra.get("risks", []),
            "development_advice": extra.get("development_advice", []),
            "career_examples": career_examples,
            "career_clues": career_examples[:5],
        }
    return payload


def build_payload() -> dict:
    try:
        source_text = load_source_text()
    except FileNotFoundError:
        source_text = ""

    existing_payload = load_existing_payload() if not source_text else {}
    existing_mbti = existing_payload.get("mbti") if isinstance(existing_payload.get("mbti"), dict) else {}
    existing_holland = existing_payload.get("holland") if isinstance(existing_payload.get("holland"), dict) else {}

    if source_text:
        mbti_questions = parse_mbti_questions(source_text)
        holland_questions = parse_holland_questions(source_text)
        holland_groups = parse_holland_groups(source_text)
        holland_details = parse_holland_details(source_text)
        mbti_careers = parse_mbti_careers(source_text)
    else:
        mbti_questions = existing_mbti.get("questions") or []
        holland_questions = existing_holland.get("questions") or []
        holland_groups = existing_holland.get("groups") or {}
        mbti_careers = existing_mbti.get("career_examples") or {}
        holland_meta = existing_holland.get("type_meta") or {}
        holland_details = {
            code: {
                "name": (holland_meta.get(code) or {}).get("name") or HOLLAND_TYPE_META[code]["name"],
                "feature": (holland_meta.get(code) or {}).get("description") or HOLLAND_TYPE_META[code]["description"],
                "careers": (holland_meta.get(code) or {}).get("careers") or [],
            }
            for code in ["R", "I", "A", "S", "E", "C"]
        }

    if len(mbti_questions) != 93:
        raise ValueError(f"MBTI 题目数异常，期望 93，实际 {len(mbti_questions)}")
    if len(holland_questions) != 90:
        raise ValueError(f"霍兰德题目数异常，期望 90，实际 {len(holland_questions)}")
    mbti_knowledge_text = load_text(MBTI_KNOWLEDGE_FILE)
    holland_knowledge_text = load_text(HOLLAND_KNOWLEDGE_FILE)

    holland_type_meta = {
        code: {
            "name": holland_details[code]["name"],
            "description": holland_details[code]["feature"] or HOLLAND_TYPE_META[code]["description"],
            "careers": holland_details[code]["careers"],
        }
        for code in ["R", "I", "A", "S", "E", "C"]
    }

    return {
        "knowledge_version": "20260321-route-align-v2",
        "mbti": {
            "questions": mbti_questions,
            "tie_breakers": MBTI_TIE_BREAKERS,
            "pair_hints": MBTI_PAIR_HINTS,
            "dimension_explanations": build_mbti_dimension_explanations(),
            "type_overviews": MBTI_TYPE_OVERVIEWS,
            "type_details": build_mbti_type_details(mbti_careers, mbti_knowledge_text),
            "career_examples": mbti_careers,
        },
        "holland": {
            "questions": holland_questions,
            "groups": holland_groups,
            "type_meta": holland_type_meta,
            "type_details": build_holland_type_details(holland_type_meta, holland_knowledge_text),
        },
    }


def main() -> None:
    payload = build_payload()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
