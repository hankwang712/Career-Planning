"""Check candidate facts and keep preparation capacity separate from job attendance."""
import re


def model_attribution_questions(raw):
    """Surface different model names in a project overview and personal contribution."""
    questions = []
    for section in re.split(r"(?m)(?=^#{1,6}\s)", raw):
        overview, separator, contribution = section.partition("本人贡献")
        if not separator:
            continue
        declared = re.findall(r"模型\s*[（(]\s*([A-Za-z][A-Za-z0-9._ -]{1,30})\s*[）)]", overview)
        implemented = re.findall(r"(?:微调|训练|部署)\s*([A-Za-z][A-Za-z0-9._-]*)", contribution)
        for first in declared:
            first = re.sub(r"\s+", "", first)
            for second in implemented:
                family = lambda name: re.sub(r"[-_.]?\d.*$", "", name).casefold()
                if family(first) != family(second):
                    questions.append(f"项目概述写到{first}，本人贡献写到{second}。请核实两者是否都使用、各自用途及本人实际微调的模型；未核实前不能合并归为个人实现。")
    return list(dict.fromkeys(questions))


def narrative_strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in {"quote", "source_quote", "sources", "evidence", "job_evidence", "candidate_evidence",
                           "followup_questions", "missing_information", "evidence_requests", "requirement"}:
                yield from narrative_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from narrative_strings(child)
    elif isinstance(value, str):
        yield value


def verify_candidate_boundaries(value, factual_text):
    errors = []
    levels = ("本科", "硕士", "博士", "专科", "学士")
    for text in narrative_strings(value):
        for question in model_attribution_questions(factual_text):
            first = re.search(r"项目概述写到([^，]+)", question)[1]
            if re.search(rf"(?:微调|训练|部署)\s*{re.escape(first)}", text, re.I) and not re.search(r"项目(?:概述|描述)|待核实|需.{0,8}核实|是否|两者|分别", text):
                errors.append(question)
        for level in levels:
            if level not in factual_text and re.search(rf"(?:(?:只|仅)?(?:显示|记录|列出)|只有|简历显示|材料显示){level}(?:阶段|教育|学习|就读|学段)|{level}阶段结束", text):
                errors.append(f"原文未明确{level}层次，不能将教育时间记录写成{level}阶段；请只引用学校、专业和日期")
        for sentence in re.split(r"[。；\n]", text):
            # Questions and explicitly conditional claims preserve uncertainty.
            uncertain = bool(re.search(r"是否|若|如果|尚未确认|尚不明确|未明确|未说明|没有说明|未补充|待核实|待确认|无法确认|计划(?:取得|获得)|需要?核实|不能(?:确定|推断|认定|证明)|不应(?:推断|认定)|不代表|不证明|不等于|未知|状态[：:]|哪一种|核实.{0,20}(?:学历|身份|状态)", sentence))
            if not uncertain:
                for level in levels:
                    if level not in factual_text and re.search(
                        rf"学历(?:层次)?(?:为|是){level}|(?:具备|拥有|取得|获得|已获)(?:了)?{level}(?:学历|学位)|{level}(?:学历|学位)(?:已|符合|满足)|(?:简历显示|材料显示|属于){level}阶段", sentence):
                        errors.append(f"用户材料未明确{level}学历/学位，不能断言已取得或满足；保留未知并单独核实专业相关性。请修正片段：{sentence[:200]!r}")
                if re.search(r"(?:已经|已)(?:本科|硕士|博士)?毕业(?!状态)|已取得.{0,6}学位", sentence) and not re.search(
                    r"已毕业|毕业证|学位证|已取得.{0,8}学位|已获得.{0,8}学位", factual_text):
                    errors.append(f"教育时间已经结束不证明已毕业或已取得学位，请保留身份与资格未知。请修正片段：{sentence[:200]!r}")
            preparation = re.search(r"准备(?:计划|时间|工时|投入)?|学习(?:时间|工时|投入)|预算", sentence)
            attendance = re.search(r"到岗|出勤|连续.{0,6}实习|长期.{0,6}实习", sentence)
            inference = re.search(r"不足以|无法满足|不能满足|难以满足|不满足|限制了|不适合|难以支撑", sentence)
            separates = re.search(r"不代表|不等于|不能据此|不可据此|不能推断|不构成|独立确认|单独确认|分别确认", sentence)
            if preparation and attendance and inference and not separates:
                errors.append("求职准备时间/预算不能推断工作出勤或实习时长；到岗能力须依据独立的用户事实")
    return list(dict.fromkeys(errors))


def preparation_only_attendance_quote(quote):
    return bool(re.search(r"准备|学习|预算", quote)) and not bool(re.search(
        r"(?:可以|可|能|只能|无法|不能|每周).{0,10}(?:到岗|出勤)|每周.{0,5}天.{0,8}(?:实习|工作)|连续.{0,5}个?月.{0,5}实习", quote))
