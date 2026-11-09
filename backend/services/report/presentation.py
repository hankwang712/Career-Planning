"""Reader-facing wording and source labels; agent evidence remains unchanged."""
from copy import deepcopy
import re


SCOPE_NOTE = "岗位分析依据本次取得的招聘材料，不是全市场招聘统计；未核实的招聘状态与任职条件，投递前仍需向招聘方确认。"


def unique_text(items, limit=None):
    result, seen = [], set()
    for item in items:
        text = str(item or "").strip()
        key = re.sub(r"[\W_]+", "", text).casefold()
        if key and key not in seen:
            result.append(text)
            seen.add(key)
    return result if limit is None else result[:limit]


def _source_metadata(content):
    fields = {}
    for key, labels in (("title", "岗位名称|职位名称"), ("company", "企业|公司名称|公司"), ("city", "城市|工作地点")):
        match = re.search(rf"(?:{labels})\s*[:：]\s*(.*?)(?=\s*(?:岗位名称|职位名称|企业|公司名称|公司|城市|工作地点|学历|薪资|岗位描述|岗位职责|任职要求)\s*[:：]|\n|$)", content)
        if match:
            fields[key] = match[1].strip()
    return fields


class ReportPresentation:
    def __init__(self, state):
        self.state = state
        self.labels = {"R1": "简历原文", "U1": "补充材料", "P1": "求职偏好"}
        self.sources = []
        self.targets = state["results"]["job_analysis"]["data"]["targets"]
        self.target_names = {item["target_id"]: item["title"] for item in self.targets}
        for target in self.targets:
            for index, source in enumerate(target["job_analysis"].get("sources", []), 1):
                fields = _source_metadata(source.get("content", ""))
                label = " · ".join(filter(None, [fields.get("company"), fields.get("title")]))
                if not label:
                    label = self.labels.get(source["chunk_id"]) or f"岗位样本 {len({item['chunk_id'] for item in self.sources}) + 1}"
                if fields.get("city"):
                    label += f"（{fields['city']}）"
                self.labels[source["chunk_id"]] = label
                if source.get("file_path") and source["file_path"] != "unknown_source":
                    self.labels[source["file_path"]] = label
                self.sources.append({"target_id": target["target_id"], "chunk_id": source["chunk_id"],
                                     "label": label, "quotes": []})
        decision = state["results"]["career_decision"]
        for source in decision.get("sources", []):
            self.labels[source["source_id"]] = self.labels.get(source.get("chunk_id"),
                source.get("title") or {"resume": "简历原文", "additional_evidence": "补充说明", "preferences": "求职偏好"}.get(source.get("kind"), "参考材料"))
            if source.get("recruitment_reference"):
                self.sources.append({"target_id": source["target_id"], "chunk_id": source["source_id"],
                                     "label": self.labels[source["source_id"]], "quotes": []})
        self.task_labels = {task["task_id"]: f"任务 {index}" for index, task in enumerate(
            state["results"]["action_planning"].get("data", {}).get("tasks", []), 1)}
        for assessment in decision.get("data", {}).get("assessments", []):
            for index, check in enumerate(assessment.get("checks", []), 1):
                self.labels[check["check_id"]] = f"要求 {index}"
        # JD1 等短号只在相应目标的段落中解释，避免多个方向的同号样本串位。
        self.jd_labels = {target["target_id"]: {f"JD{index}": self.labels[source["chunk_id"]]
            for index, source in enumerate(target["job_analysis"].get("sources", []), 1)} for target in self.targets}

    def clean(self, text, *, target_id=None, task_refs=False):
        text = str(text or "").strip()
        text = re.sub(r"\[([RUP]\d+|T\d+JD\d+)\]", lambda match: self.labels.get(match[1], "参考材料"), text)
        labels = {key: value for key, value in self.labels.items() if not re.fullmatch(r"[RUP]\d+|C\d+", key)}
        if target_id in self.jd_labels:
            labels.update(self.jd_labels[target_id])
        elif len(self.targets) == 1:
            labels.update(next(iter(self.jd_labels.values())))
        for target, title in self.target_names.items():
            text = re.sub(rf"(目标|方向)\s*{re.escape(target)}(?![\w-])", lambda match: match[1] + "「" + title + "」", text)
        # 任务与职业目标可能同为 T1；先处理有明确“目标/方向”上下文的标记。
        if task_refs:
            labels.update(self.task_labels)
        if labels:
            tokens = "|".join(re.escape(key) for key in sorted(labels, key=len, reverse=True))
            text = re.sub(rf"(?<![\w-])(?:{tokens})(?![\w-])", lambda match: labels[match[0]], text)
        text = re.sub(r"(?:assessment\.)?decision\s*=\s*(recommended|conditional|not_recommended|insufficient_information)",
            lambda match: {"recommended": "建议优先尝试", "conditional": "满足条件后尝试", "not_recommended": "暂不建议推进",
                           "insufficient_information": "仍需补充信息"}[match[1]], text)
        text = re.sub(r"\[(?:chunk-[\w-]+|[RUP]\d+|T\d+JD\d+)\]", "", text)
        return text.strip()

    def data(self, value):
        if isinstance(value, dict):
            return {key: deepcopy(child) if key in {"id", "task_id", "check_id", "target_id", "depends_on", "kind", "status", "phase_key", "quote", "source_quote"}
                    else self.data(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.data(child) for child in value]
        return self.clean(value, target_id=self.state["review"]["target_id"], task_refs=True) if isinstance(value, str) else value

    def cite(self, chunk_id, quote, target_id):
        source = next((item for item in self.sources if item["target_id"] == target_id and item["chunk_id"] == chunk_id), None)
        if source is not None and quote and not re.search(r"招聘记录内部键|chunk-[a-f0-9]{16,}", quote):
            source["quotes"] = unique_text(source["quotes"] + [quote])

    def appendix_sources(self):
        parts = []
        for source in self.sources:
            if source["quotes"]:
                # One representative excerpt per source; complete citations remain in agent_results.
                quote = source["quotes"][0]
                excerpt = quote if len(quote) <= 180 else quote[:180] + "…"
                parts.append("**" + source["label"] + "**：「" + excerpt + "」")
        return "\n\n".join(parts)


def profile_lines(resume, profile):
    facts = {item["field"]: item["value"] for item in resume.get("career_profile", [])}
    basics = profile.get("basics") or {}
    lines = []
    for label, fact, field in (("学历与在读状态", "education", "education"), ("专业", "major", "major"),
                               ("毕业时间", "graduation_year", "graduation_year"), ("所在城市", "current_city", "city")):
        value = facts.get(fact) or basics.get(field)
        if value and str(value).strip() not in {"未提供", "未知", "--"}:
            lines.append(f"{label}：{value}")
    if not facts.get("education") and not basics.get("education") and basics.get("grade"):
        lines.insert(0, "学习阶段：" + str(basics["grade"]))
    if facts.get("skills"):
        lines.append("技能与实践方向：" + facts["skills"])
    return lines


def reader_limitations(items):
    """Keep actionable limits while consolidating retrieval mechanics into one scope note."""
    result = []
    sentences = [sentence.strip() for item in items for sentence in re.findall(r"[^。；]+[。；]?", str(item or ""))]
    for text in unique_text(sentences):
        # 这些是检索阶段的执行说明，不能与最终报告的用户信息混为一谈。
        if re.search(r"chunk|\brecord\b|source_id|分块方式|接口返回|未提供用户个人|未接收简历|晋升路径证据", text, re.I):
            continue
        if re.search(r"不代表.*(?:市场|全库|整个方向)|(?:仅|基于|检索).{0,12}(?:JD|岗位|招聘)?\s*样本|发布时间|招聘状态.*(?:未知|无法|核实)|未(?:执行|请求)招聘", text):
            continue
        result.append(text)
    return unique_text(result, 5)


def validate_reader_report(markdown):
    if re.search(r"chunk-[a-f0-9]{16,}|招聘记录内部键|#record=|\bT\d+JD\d+\b|\bassessment\.decision\b|(?<![A-Za-z])[A-Za-z]:[/\\]", markdown):
        raise ValueError("报告正文仍含内部追踪标记或本机路径，请重新生成报告；原始分析已保留。")
