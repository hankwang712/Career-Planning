"""Check factual boundaries of resume diagnostics before their publication."""
import re
import unicodedata


def normalized(value):
    value = re.sub(r"([A-Za-z])([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda match: match[1] + "^" + unicodedata.normalize("NFKC", match[2]), str(value or ""))
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = re.sub(r"\\(?:mathrm|text|operatorname)\{([^{}]+)\}", r"\1", value)
    value = value.replace(r"\sim", "~").replace("∼", "~")
    value = re.sub(r"\\[()\[\]]|\\(?=[%_#&{}$])", "", value)
    return re.sub(r"\s+", "", value)


def extractive(value):
    return re.sub(r"[^\w\u3400-\u9fff%]", "", normalized(value)).casefold()


def experience_context(experience, raw_resume):
    sections = re.split(r"(?m)(?=^#{1,6}\s)", raw_resume)
    quote = normalized(experience.get("source_quote", ""))
    matches = [section for section in sections if quote and quote in normalized(section)]
    name = normalized(experience.get("name", "")).strip('“”"')
    named = [section for section in matches if name and name in normalized(section)]
    return min(named, key=len) if named else matches[0] if len(matches) == 1 else ""


def rewrite_errors(rewrite, evidence, materials):
    """Rewrites are a conservative rearrangement of cited user facts, never filled-in examples."""
    if not rewrite:
        return []
    if re.search(r"(?:团队|小组|提升|降低|负责).{0,12}(?:[XxＮNn]+|\?\?|待填写|待补充)|\[.{0,30}\]|【.{0,30}】", rewrite):
        return ["改写不能包含占位事实；未确认的信息留在追问，rewrite 应为 null"]
    quotes = []
    original_quotes = []
    for row in evidence:
        source = materials.get(row.get("source"), "")
        quote = row.get("quote", "")
        if row.get("source") in {"raw_resume", "additional_evidence"} and row.get("status") != "missing" and quote and normalized(quote) in normalized(source):
            quotes.append(extractive(quote))
            original_quotes.append(normalized(quote))
    if not quotes:
        return ["非空改写需要引用用户材料中的事实证据，否则 rewrite 为 null"]
    numeric = r"\d+(?:\.\d+)?(?:[~～至–—-]\d+(?:\.\d+)?)?%?"
    supported_numbers = set(re.findall(numeric, "\n".join(original_quotes)))
    if any(number not in supported_numbers for number in re.findall(numeric, normalized(rewrite))):
        return ["改写不得改变证据中的数字、小数、范围或百分比口径"]
    # Semantically novel assignments cannot be verified by a string-based validator.
    # Require an extractive reordering; suggestions may explain how to rewrite after confirmation.
    clauses = re.split(r"[。；;\n]+", rewrite.strip('「」“”"'))
    for clause in clauses:
        clause = re.sub(r"^\s*(?:[-*]|\d+[.、])\s*", "", clause).strip()
        clause = re.sub(r"^(?:项目目标|项目成果|本人贡献|主要工作|职责|成果|技术方案|项目概述)[：:]", "", clause)
        fragment = extractive(clause)
        if fragment and not any(fragment in quote for quote in quotes):
            return ["改写含证据不能逐项支持的新措辞或归属；仅摘录重组已引原句，无法可靠重组时 rewrite=null，建议补充内容另放 suggestion"]
    return []


def verify_resume_grounding(data, prepared):
    raw = prepared.get("raw_resume", "")
    materials = {name: prepared.get(name, "") for name in ("raw_resume", "additional_evidence", "education_context")}
    errors = []

    def narrative(item):
        if isinstance(item, dict):
            for key, value in item.items():
                if key not in {"quote", "source_quote", "evidence", "missing_evidence", "missing_information", "followup_questions"}:
                    yield from narrative(value)
        elif isinstance(item, list):
            for value in item:
                yield from narrative(value)
        elif isinstance(item, str):
            yield item

    factual = raw + "\n" + prepared.get("additional_evidence", "")
    work_sections = [section for section in re.split(r"(?m)(?=^#{1,6}\s)", raw)
                     if re.match(r"\s*#{1,6}\s*(?:实习|工作|兼职)", section)]
    has_qualitative_delivery = any(re.search(r"实现|完成|交付|部署|上线|发布|采纳", section) for section in work_sections)
    uncertain = r"是否|未知|未说明|待确认|待核实|不能|不代表|不证明|不等于|不能推断|尚需|需.{0,6}确认|未确认|补充当前状态|例如|示例|若|如果|如[“「\"]"
    for value in narrative(data):
        if re.search(r"(?:无法|不能|未能|没有).{0,12}确认.{0,35}(?:注明|标注|写).{0,8}单次实验", value):
            errors.append("实验次数未知不能改称单次实验；先回查记录，无法确认时标明验证口径待核实，不补造实验次数")
        analysis_date = prepared.get("analysis_date", "")
        for match in re.finditer(r"预计\s*(20\d{2})\s*年\s*(\d{1,2})\s*月.{0,4}毕业", value):
            if analysis_date and f"{match[1]}-{int(match[2]):02d}" < analysis_date[:7]:
                if not re.search(r"不(?:能|应|要|再)|避免", value[max(0, match.start()-15):match.start()]):
                    errors.append(f"当前日期{analysis_date}，错误建议：{value!r}。删除过去月份的预计毕业示例，不为身份未知编写任何具体状态；只要求核实真实毕业、延期或升学状态")
        for clause in re.split(r"[。；\n]", value):
            if has_qualitative_delivery and re.search(r"(?:实习|工作).{0,30}(?:无任何|没有任何|完全没有).{0,16}(?:产出|结果|交付)", clause):
                errors.append("实习已有功能、方案或部署等定性交付，不能笼统称完全没有结果；仅指出缺少的验证记录或量化口径")
            if re.search(r"编号(?:顺序)?(?:错乱|混乱)|排版混乱|排版错误|(?:存在|出现|有|为|是).{0,12}(?:错别字|笔误|错字)|[“「][^”」]{1,20}[”」].{0,4}(?:笔误|错字)", clause) and not re.search(r"OCR|文本提取|文档提取|解析|扫描|核对原稿|需核对|是否|可能|疑似|如果|若", clause):
                errors.append(f"不能从提取文本给原PDF排版、双栏编号或漏字定罪；请改为原稿核对疑点，且不据此扣分。错误片段：{clause[:160]}")
            if re.search(r"(?:论文|专利).{0,80}状态.{0,12}(?:混用|混乱|不一致|矛盾)", clause) and not re.search(r"未录用|尚未接收|未授权|尚未授权", factual):
                errors.append("投稿后录用、不同成果各有不同状态并不矛盾；只能报告同一成果互相排斥的真实状态证据")
            for label in ("本科", "硕士", "博士", "专科"):
                if label not in factual and re.search(rf"(?:学历(?:为|是)|拥有|具备|具有).{{0,4}}{label}|{label}(?:背景|毕业生|学历)", clause) and not re.search(uncertain, clause):
                    errors.append("不能从校名、专业或学段日期断言材料未写明的学历层次")
    if not re.search(r"已毕业|已取得.{0,8}(?:学位|学历)|已获.{0,8}学位", factual):
        for value in narrative(data):
            for clause in re.split(r"[。；\n]", value):
                if re.search(r"已毕业|已经毕业|已取得.{0,8}学位|已获.{0,8}学位", clause) and not re.search(uncertain, clause):
                    errors.append("学段结束日期不能证明已毕业或取得学位；此状态未明确时保留未知，不在summary中断言")

    def evidence(rows):
        for row in rows:
            quote = row.get("quote", "")
            if row.get("status") == "missing":
                if quote and normalized(quote) not in normalized(materials.get(row.get("source"), "")):
                    errors.append("missing 的定位上下文如非空也必须是真实原文，不能用问题假设作为事实")
            elif not quote or normalized(quote) not in normalized(materials.get(row.get("source"), "")):
                errors.append("维度和问题的 clear/weak 证据必须摘录对应材料的连续原文")

    def issue(item):
        evidence(item.get("evidence", []))
        errors.extend(f"问题‘{item.get('problem', '')[:38]}’：{error}" for error in
                      rewrite_errors(item.get("rewrite"), item.get("evidence", []), materials))
        problem = item.get("problem", "")
        if re.search(r"编号错乱|编号混乱|排版混乱|排版错误|错别字|笔误|错字", problem) and not re.search(r"OCR|文本提取|文档提取|解析|扫描|需核对|可能|疑似", problem):
            errors.append("文本提取不能确认原稿排版、编号或错字；如有疑点只提出原稿核对，不断言简历有误")
        if re.search(r"(?:论文|专利).{0,80}(?:状态混用|状态混乱|状态不一致|授权.*公开.*矛盾|录用.*投稿.*矛盾)", problem):
            errors.append("不同论文或专利可处于不同状态；必须定位同一成果的真正矛盾，不能以状态并存指控不一致")

    for dimension in data.get("dimensions", []):
        evidence(dimension.get("evidence", []))
    for item in data.get("issues", []):
        issue(item)
    for experience in data.get("experiences", []):
        quote = normalized(experience.get("source_quote", ""))
        if not quote or quote not in normalized(raw):
            supplied = experience.get("source_quote", "")
            prefix = supplied[:18]
            offset = raw.find(prefix)
            context = raw[offset:offset + 650] if offset >= 0 else "请重新定位原文"
            errors.append(f"经历‘{experience.get('name', '')}’的 source_quote 不是连续原文，不可省略中间编号或文字；只引用一两句连续原文即可。原文上下文：{context!r}")
        section = experience_context(experience, raw)
        if experience.get("experience_type") in {"internship", "work"} and re.search(r"实现|完成|交付|部署|上线|发布|采纳", section):
            for item in experience.get("issues", []):
                problem = item.get("problem", "")
                if re.search(r"缺少(?:结果|成果)|没有(?:任何)?(?:结果|成果)|无(?:结果|成果)", problem) and not re.search(r"量化|指标|记录|可核查|验证口径|反馈", problem):
                    errors.append("实习有定性功能或部署成果，不能笼统称缺少结果；应具体指出尚未给出的评测、反馈或归因记录")
        if re.search(r"奖|竞赛|比赛", section[:100]) and not re.search(r"负责|参与|实现|提出|构建|开发|设计了|担任|任务[：:]|方法[：:]|本人贡献[：:]", section):
            errors.append("仅有竞赛、证书或奖项列表不能创建独立经历和经历分数；放在整体教育成长维度评价")
        for dimension in experience.get("dimensions", []):
            evidence(dimension.get("evidence", []))
        for item in experience.get("issues", []):
            issue(item)
            for row in item.get("evidence", []):
                if section and row.get("source") == "raw_resume" and row.get("quote") and normalized(row["quote"]) not in normalized(section):
                    errors.append("经历内的问题不能引用另一段经历来补造本段事实；请使用本段原文或明确归属的补充说明")
    user_material = raw + "\n" + prepared.get("additional_evidence", "")
    for fact in data.get("career_profile", []):
        quote = normalized(fact.get("quote", "")).casefold()
        for term in ("会议", "专利", "论文", "第一作者", "第二作者", "授权", "录用", "投稿", "接收"):
            if term in fact.get("value", "") and term not in quote:
                errors.append(f"画像{fact.get('field')}的引文不含所声称的{term}成果；拆为各有直接引文的画像项或删去未由本条引文支持的主张")
        # Claims from several real projects still need evidence attached to this fact.
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+/#-]+", fact.get("value", ""))
        unsupported = [token for token in tokens if token.casefold() not in {"gpa", "sci", "cet"}
                       and normalized(token).casefold() not in quote]
        if unsupported:
            errors.append(f"画像 {fact.get('field')} 的quote未覆盖技术主张{','.join(unsupported)}；拆成分别有对应引文的画像项，不能把不同经历主张挂在一条课程/成绩引文上")
        if fact.get("field") == "education":
            for label in ("本科", "学士", "硕士", "博士", "专科"):
                if label in fact.get("value", "") and label not in user_material:
                    errors.append("教育画像不能从学校、专业和学段日期推断未明确写出的学历层次")
    preferences = prepared.get("preferences", "")
    for question in data.get("missing_information", []):
        supplied = re.search(r"(?:期望|求职)?城市是否(?:确为|为)([^？?（(]+)", question)
        if supplied and normalized(supplied[1]) in normalized(preferences):
            errors.append("本次 preferences 已明确该求职城市，不再作为缺失信息重复追问")
    return list(dict.fromkeys(errors))
