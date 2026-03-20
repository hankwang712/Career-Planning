from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "static" / "assessment-data.json"

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


def load_source_text() -> str:
    for path in sorted(ROOT.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "MBTI职业性格测试题" in text and "全套霍兰德职业兴趣测试题" in text:
            return text
    raise FileNotFoundError("未找到包含 MBTI 与霍兰德题库的 Markdown 文件")


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


def build_payload() -> dict:
    source_text = load_source_text()
    mbti_questions = parse_mbti_questions(source_text)
    holland_questions = parse_holland_questions(source_text)
    holland_groups = parse_holland_groups(source_text)
    holland_details = parse_holland_details(source_text)
    mbti_careers = parse_mbti_careers(source_text)

    return {
        "mbti": {
            "questions": mbti_questions,
            "tie_breakers": MBTI_TIE_BREAKERS,
            "pair_hints": MBTI_PAIR_HINTS,
            "type_overviews": MBTI_TYPE_OVERVIEWS,
            "career_examples": mbti_careers,
        },
        "holland": {
            "questions": holland_questions,
            "groups": holland_groups,
            "type_meta": {
                code: {
                    "name": holland_details[code]["name"],
                    "description": holland_details[code]["feature"] or HOLLAND_TYPE_META[code]["description"],
                    "careers": holland_details[code]["careers"],
                }
                for code in ["R", "I", "A", "S", "E", "C"]
            },
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
