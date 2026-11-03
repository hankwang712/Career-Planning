from __future__ import annotations

import argparse
from collections import Counter
import re

from .common import DEFAULT_OUTPUT, digest, now, read_json, write_json
from .corpus import field, load_cases, load_corpus


def has(text, term):
    patterns = {"Kubernetes": r"(?:kubernetes|k8s)", "RAG": r"(?:rag|检索增强生成)",
                "Go": r"go(?:lang)?", "Docker": r"docker(?:file)?",
                "PostgreSQL": r"(?:postgresql|postgres)"}
    return bool(re.search(r"(?<![a-z0-9])" + patterns.get(term, re.escape(term)) + r"(?![a-z0-9])", text, re.I))


SKILL_RULES = {
    "graph_container": ("LangGraph", "Docker"), "rag_web": ("RAG", "Django"),
    "rag_orchestration": ("RAG", "Kubernetes"), "training_container": ("PyTorch", "Docker"),
    "chain_flask": ("LangChain", "Flask"), "dify_container": ("Dify", "Docker"),
    "api_database": ("FastAPI", "PostgreSQL"), "frontend_container": ("Vue", "Docker"),
    "training_database": ("Python", "TensorFlow", "MySQL"),
}


def time_three_months(row):
    lines = row["text"].splitlines()
    days = any(re.search(r"(?:每周|一周).{0,12}(?:3|三)\s*(?:个工作日|工作日|天)", line) for line in lines)
    months = any(re.search(r"(?:实习|持续).{0,15}(?:3|三)(?:\s*[-~～—]\s*6)?\s*个?月", line) for line in lines)
    # 本题要求最低周期不超过3个月；同时出现6个月硬性门槛的记录不因其他位置有3个月而入选。
    six_minimum = any(re.search(r"(?:实习期不少于|最少能实习|实习周期|实习.{0,8}至少|持续).{0,3}(?:6|六)\s*个?月", line) for line in lines)
    return has(row["text"], "Python") and days and months and not six_minimum


def explicit_remote(row):
    if not has(row["text"], "Python"):
        return False
    return any(re.search(r"全远程|可远程|支持远程|远程实习|远程办公|可居家办公", line)
        and not re.search(r"不接受|不支持|不可|不允许", line) for line in row["text"].splitlines())


def six_months_four_days(row):
    lines = row["text"].splitlines()
    days = any(re.search(r"每周.{0,12}(?:[45]|四|五)\s*天", line) for line in lines)
    months = any(re.search(r"(?:实习|持续).{0,15}(?:6|六)\s*个?月|(?:6|六)\s*个?月的实习", line)
        and not re.search(r"[345]\s*[-~～—]\s*6|为佳|优先|经验|未来", line) for line in lines)
    return has(row["text"], "Python") and days and months


def select(rows, rule):
    if rule in SKILL_RULES:
        terms = SKILL_RULES[rule]
        return [row for row in rows if all(has(row["text"], term) for term in terms)]
    predicates = {"three_days_three_months": time_three_months, "remote_python": explicit_remote,
        "six_months_four_days": six_months_four_days,
        "remote_mentions": lambda row: has(row["text"], "Python") and bool(re.search(r"远程|线上实习|居家办公", row["text"])),
        "six_months_three_days": lambda row: row["record"] in (14, 157, 203, 219, 271),
        "graduation_2027_plus": lambda row: has(row["text"], "Python") and "2027年及以后毕业" in row["text"]}
    return [row for row in rows if predicates[rule](row)]


def title(row):
    return f"{field(row['text'], '企业：')} / {field(row['text'], '岗位名称：')} [JD-{row['record']}]"


def evidence(row, terms=(), markers=(), schedules=False):
    result = []
    lines = row["text"].splitlines()
    wanted = set()
    for i, line in enumerate(lines):
        if (any(has(line, term) for term in terms) or any(marker in line for marker in markers)
                or schedules and re.search(r"(?:每周|一周|个月|半年|远程|线上实习|居家办公|2027年及以后)", line)):
            wanted.add(i)
            # 同时保留相邻标题，避免把“加分项”下的技术误读为必需。
            if i > 0 and re.search(r"加分|优先|任职|要求|职责|Must|Nice|Plus", lines[i - 1], re.I):
                wanted.add(i - 1)
    for i in sorted(wanted):
        quote = lines[i].strip()
        if quote and not quote.startswith("招聘记录内部键"):
            result.append({"record": row["record"], "quote": quote[:360]})
    return list({item["quote"]: item for item in result}.values())


def build(output=DEFAULT_OUTPUT):
    manifest, rows = load_corpus(output)
    if len(rows) != 300:
        raise ValueError("此版挑战集基于当前300条冻结JD；语料变化时需重新核对语义标注")
    by_id = {row["record"]: row for row in rows}
    cases = []
    selection_audit = {}

    def add(category, question, selected, reference, *, terms=(), markers=(), schedules=False, rule=None):
        quotes = [quote for row in selected for quote in evidence(row, terms, markers, schedules)]
        if selected and not quotes:
            raise ValueError("可回答题必须有问题相关的原文证据")
        cases.append({"id": f"H{len(cases) + 1:03d}", "category": category, "question": question,
            "ground_truth": reference, "answerable": bool(selected),
            "relevant_records": [row["record"] for row in selected], "evidence_quotes": quotes,
            "reviewed": False, "review_notes": "已进行全库条件扫描、原文引文校验及助手逐题准备复核；尚非人工金标准。",
            "selection_rule": rule, "cohort": "challenge_v1",
            "reference_policy": "只标注本题要求的事实，不将整篇JD作参考答案"})

    basics = [
        (10, "每周和每月的最低出勤分别是多少？日薪区间是多少？", "每周至少3天，每月至少15天；实习待遇100—150元/天。不能漏掉每月15天约束。", ("每周",)),
        (26, "办公方式与面试环节分别是什么？不要把其他公司的流程混入。", "国内全远程，可选择落地上海；面试仅包含一次编码测试和一次技术交流。", ("全远程", "面试流程")),
        (95, "Dockerfile与LangGraph经验分别属于必须还是加分？", "核心硬实力明确要求熟悉Linux并能独立编写Dockerfile；LangChain/LangGraph/AutoGen等框架的实战经验列在加分项，不是全部必须掌握。", ("Dockerfile", "Agent 开发经验", "核心硬实力", "加分项")),
        (157, "最低出勤、实习周期和Docker要求分别是什么？", "每周实习3天以上、实习期不少于6个月；Docker位于加分项的开发工具列表，不能按必备条件淘汰候选人。", ("每周", "Docker", "加分项")),
        (238, "有哪些地域、实习时间与年级条件？区分要求和优先项。", "要求上海在校学生、全日制本科及以上；稳定实习至少3个月、每周不少于3天；大四或研三是优先考虑，不能写成只接受这两个年级。", ("上海在校", "实习要求")),
        (269, "Dify对应什么工作，Docker是什么强度的要求，出勤周期是多少？", "使用Dify开发部署AI智能体/工作流属于岗位职责；了解Docker基础容器化为优先项；每周至少4天、实习至少4个月。", ("Dify平台", "Docker", "每周")),
        (270, "Docker、PyTorch与相关项目经历分别是什么要求？出勤周期是多少？", "要求熟练运用Docker进行容器化部署、熟悉PyTorch；深度学习模型部署/数据挖掘/大模型项目实践为优先；每周现场不少于4天、稳定3个月以上。", ("工程素养", "专业技能", "实习时间")),
        (296, "在读学历范围、实习周期、每周出勤与PyTorch要求是什么？", "相关专业在读本科生或研究生；6个月实习、每周至少4天；PyTorch在优先考虑项中，不能认定为所有候选人必备。", ("基本要求", "在读本科", "6个月", "优先考虑", "PyTorch")),
    ]
    for record, ask, facts, markers in basics:
        row = by_id[record]
        add("basic_lookup", f"资料中，{field(row['text'], '企业：')}的“{field(row['text'], '岗位名称：')}”{ask}",
            [row], title(row) + "：" + facts, markers=markers)

    for rule, terms in SKILL_RULES.items():
        selected = select(rows, rule)
        selection_audit[rule] = [row["record"] for row in selected]
        names = "、".join("Kubernetes/K8s" if term == "Kubernetes" else "Docker（含Dockerfile）" if term == "Docker" else term for term in terms)
        question = (f"请从岗位库找全原文明示同时提到{names}的招聘记录，列出公司、记录标题和分别支持每项技术的原句。"
            "仅提到其中一项不算；本题只判断原文提及，不把技术列表升级成全部必需；一条记录含多个子岗位时请注明。")
        reference = f"符合本题原文提及条件的招聘记录共{len(selected)}条：\n" + "\n".join(
            title(row) + "；" + "；".join(f"{term}见原文“{next(line.strip()[:240] for line in row['text'].splitlines() if has(line, term))}”" for term in terms)
            for row in selected)
        add("constraint_filter", question, selected, reference, terms=terms, rule=rule)

    schedule_rules = [
        ("three_days_three_months", "我只能每周到岗3天、连续实习3个月。请找全原文明确允许这一最低出勤与最短周期组合的Python招聘记录。未写明周期、要求4天或至少6个月的不要列为已满足。",
         "满足这两个明确时间下限的记录是：星河璨海3天/3个月；泓原投资每周最少3天、三个月起；上海企想每周不少于3天、至少3个月；喜岳投资每周不少于3个工作日、周期3—6个月。这里仅判断时间，不保证其他条件也满足。"),
        ("remote_python", "请找全原文明示支持远程办公或远程实习的Python招聘记录。只写远程协作、远程支持，或明确不接受远程的不能算。给出公司和支持原句。",
         "明确支持的记录是意果科技（国内全远程）、量霸科技（实习期可远程）、BigQuant（可以远程实习）、臻旷科技（支持远程办公）、灵宸智能（可远程办公/居家办公）。远程支持和协作不等于允许远程工作。"),
        ("six_months_four_days", "请找全原文明示Python、且明确要求至少6个月实习并每周最低出勤不少于4天的招聘记录。4—6个月范围不能直接当作最低6个月，6个月优先也不能当硬门槛。",
         "应包含上海楼智云信息科技（每周至少4天、持续6个月）、非凸科技（每周至少四天、至少6个月）、协赢（每周5天、至少6个月）、SSME（6个月、每周至少4天）。北京亚信4—6个月的最低端不是6个月，不能混入。"),
    ]
    expected_schedules = {"three_days_three_months": [28, 94, 238, 273], "remote_python": [26, 43, 56, 79, 171],
                          "six_months_four_days": [163, 174, 204, 296]}
    for rule, question, reference in schedule_rules:
        selected = select(rows, rule)
        selection_audit[rule] = [row["record"] for row in selected]
        if selection_audit[rule] != expected_schedules[rule]:
            raise ValueError(f"时间/远程规则扫描与逐条来源复核不一致：{rule} {selection_audit[rule]}")
        add("constraint_filter", question, selected, reference + "\n" + "\n".join(title(row) for row in selected),
            terms=("Python",), schedules=True, rule=rule)

    graph_facts = {95: "独立编写Dockerfile是必须；Agent框架实战经验是加分。",
        179: "任职要求是熟悉Docker/Kubernetes；Langgraph出现在跟踪技术生态的职责中，不能据此虚构必须有该框架项目。",
        218: "熟练使用Docker/Git/Linux，了解k8s部署；熟悉Agent框架；AI相关实习或开发经验佳。",
        269: "Docker基础容器化以及LangGraph等框架了解/使用经验属于优先，不得升级成统一硬门槛；出勤至少4天/4个月。"}
    training_facts = {17: "这是多个子岗位的集合。AI数据平台子岗位将PyTorch/TensorFlow熟悉列优先、Docker列加分，不能套用到推理引擎等其他子岗位。",
        26: "PyTorch与Docker出现在技术栈清单中，清单本身不能证明每项都是硬性资格。",
        107: "熟悉Docker/Kubernetes是任职要求；深度学习框架TensorFlow/PyTorch位于加分项。",
        181: "了解Docker等工具链；至少掌握一种深度学习框架，不等于必须同时掌握PyTorch和TensorFlow；LangChain/Dify/Coze经验优先。",
        270: "熟悉PyTorch、熟练Docker容器化部署是要求，相关项目经验优先；每周现场4天、至少3个月。"}
    def annotated(rule, question, annotations, *, schedules=False):
        selected = select(rows, rule)
        if set(row["record"] for row in selected) != set(annotations):
            raise ValueError(f"语义说明没有穷尽候选：{rule}")
        reference = "\n".join(title(row) + "：" + annotations[row["record"]] for row in selected)
        add("cross_job_reasoning", question, selected, reference, terms=SKILL_RULES.get(rule, ()),
            markers=("加分项", "优先考虑", "至少一种", "至少一门", "核心硬实力"), schedules=schedules, rule=rule)

    annotated("graph_container", "原文同时涉及LangGraph和Docker生态的招聘记录中，这两项分别属于必需、优先还是职责/技术清单？请逐条比较，不能统一成所有岗位都必须有项目经验。", graph_facts)
    annotated("training_container", "请比较原文同时提到PyTorch和Docker的招聘记录：它们是任职要求、加分项还是技术栈列示？同一记录含多个子岗位时，说明不能把条件混用。", training_facts)
    annotated("dify_container", "对同时提到Dify和Docker的招聘记录，比较Dify工作职责、Docker要求强度及出勤周期，哪些是硬条件，哪些是优先？",
        {181: "Docker为了解工具链要求，Dify等平台经验优先；每周4—5天、连续4—6个月以上。",
         269: "Dify工作流开发部署是职责；了解Dify等框架与Docker容器化优先；每周至少4天、至少4个月。"}, schedules=True)
    annotated("rag_orchestration", "对同时涉及RAG和Kubernetes/K8s的招聘记录，分别说明RAG、容器编排与语言要求；不能把Python/Go/Java任一语言改成三种都必须。",
        {30: "工作涉及RAG和Docker/K8s部署；语言是精通Python/Go/Java任一；LangChain/LlamaIndex深入使用经验为加分。",
         156: "有LangChain/LLM Agent/RAG学习或项目经历；了解Docker/K8s基础或者后端服务开发，存在择一关系，不能改成两者都必须。",
         218: "熟悉Agent框架、RAG和向量数据库；熟练Git/Docker/Linux，k8s部署要求了解，不能改为精通。"})
    candidate_graph = {key: value + (" 候选人每周仅3天、仅3个月，明确不满足这里的4天/4个月。" if key == 269 else
        " 原文未明确给出出勤和周期，须核实；候选人没提供Docker/LangGraph经历只能标缺少证据，不能直接认定不会。") for key, value in graph_facts.items()}
    annotated("graph_container", "候选人本科在读，只有Python/Flask课程项目，未提供Docker或LangGraph经历，每周仅3天、连续仅3个月。请对原文同时提到LangGraph与Docker的招聘记录逐条判断：哪些时间明确冲突、哪些经历缺少证据、哪些只是加分项未满足？不要把没写经历当不会。", candidate_graph, schedules=True)
    selected = select(rows, "six_months_four_days")
    add("cross_job_reasoning", "候选人本科在读、会Python和PyTorch，但每周最多3天且只能连续3个月。对库中明确要求Python、至少6个月并每周至少4天的招聘记录，逐条判断明确时间冲突；不要把学历符合等同于整体匹配，也不要把未提供其他技能当作已确认不会。",
        selected, "四条记录都存在明确出勤与周期冲突：候选人最多3天/3个月，低于以下要求；其他技能缺少材料时仍需核实。\n" + "\n".join(title(row) for row in selected), terms=("Python",), schedules=True, rule="six_months_four_days")
    selected = select(rows, "remote_python")
    add("cross_job_reasoning", "候选人只接受远程，每周3天、每天最多6小时，连续3个月。对明确支持远程的Python招聘记录，哪些时间条件有证据支持、哪些明确冲突、哪些尚未写明？不能因为可远程就推断出勤时间自由。",
        selected, "意果、量霸、臻旷明确支持远程，但未写明完整出勤周期，需核实；BigQuant至少3个月，与候选周期相容，但每周/每天要求未写明；灵宸每周不少于三天、每天不少于8小时，候选人每天最多6小时明确冲突，周期未明确。所有岗位均不能只凭远程福利推断整体匹配。\n" + "\n".join(title(row) for row in selected), terms=("Python",), schedules=True, rule="remote_python")
    selected = select(rows, "graduation_2027_plus")
    if [row["record"] for row in selected] != [141, 207]:
        raise ValueError("2027及以后毕业条件需重新复核")
    add("cross_job_reasoning", "候选人2026年已毕业，掌握Python与Docker。请找出库中原文明示2027年及以后毕业的Python招聘记录，逐条说明是否存在明确学历身份或毕业年份冲突。技能符合不能抵消身份硬条件。",
        selected, "雪山之巅要求2027年及以后毕业的在校本科生/研究生，且已毕业请勿投递；理想汽车要求计算机相关专业本科在读、2027年及以后毕业。2026年已毕业候选人均有明确身份/年份冲突，不能以会Python/Docker推断资格满足。\n" + "\n".join(title(row) for row in selected), terms=("Python",), schedules=True, rule="graduation_2027_plus")
    selected = select(rows, "remote_mentions")
    remote_ids = [row["record"] for row in selected]
    expected_remote = [26, 43, 56, 71, 79, 98, 149, 171, 208]
    if remote_ids != expected_remote:
        raise ValueError(f"远程正反例集合需重新复核：{remote_ids}")
    add("cross_job_reasoning", "请把Python招聘记录中涉及远程或线上实习的描述分为三组：明确支持远程、明确不接受远程、仅提远程协作/支持而无法确认办公方式。给出公司和依据，不能因城市上海就一律判线下。",
        selected, "明确支持：意果科技、量霸科技、BigQuant、臻旷科技、灵宸智能。明确不接受：盛大网络集团（线下、不接受远程）、上海鸣石（不支持线上实习）。无法仅据此确认：喜扑游戏仅提远程协作，cloudchef仅提项目远程支持。\n" + "\n".join(title(row) for row in selected), terms=("Python",), schedules=True, rule="remote_mentions")
    selected = select(rows, "six_months_three_days")
    add("cross_job_reasoning", "我每周可以3天，但只能实习3个月。请找出Python招聘记录中明确写每周最低3天、总周期至少6个月或半年的岗位，说明为什么不能只看周出勤就认为我满足时间条件。",
        selected, "九招、艾尔维、和鲸科技、振宁(无锡)、正泰集团研究院都同时写明每周最低3天和至少6个月/半年；候选人的周天数不能弥补仅3个月的周期差距。\n" + "\n".join(title(row) for row in selected), terms=("Python",), schedules=True, rule="six_months_three_days")
    row = by_id[17]
    add("cross_job_reasoning", "同一条校招集合资料包含“AI数据平台工程师”和“推理引擎开发工程师”。请仅比较这两个子岗位对PyTorch/TensorFlow与Docker的要求，不能把一个子岗位的加分项当成另一个的必需条件。",
        [row], "AI数据平台工程师：熟悉TensorFlow或PyTorch为优先；Docker容器化列加分。推理引擎开发工程师：要求熟悉一种或多种深度学习框架或AI编译框架底层原理，列表含PyTorch/TensorFlow等，不要求所有框架同时掌握；该子岗位未单列Docker要求，不能继承AI数据平台岗位的条件。",
        terms=("PyTorch", "Docker", "TensorFlow"), markers=("【2026校招】AI数据平台", "【2026校招】推理引擎", "AI 基础", "容器化技术"))
    annotated("rag_web", "比较原文同时提到RAG与Django的招聘记录：RAG实战经验、Web框架与模型训练分别是硬要求、加分还是不需要？兴趣、了解和实际落地经验不要混为一谈。",
        {21: "要求熟悉FastAPI/Flask/Django等Web框架，并有Agent/RAG等实战和落地经历；职责明确无需参与模型训练与微调。",
         200: "Python基础是要求；FastAPI/Flask/Django项目经验及接入AI/简单RAG尝试列加分/优先，不得硬化为必备实战。",
         285: "Python必备，Django等框架要求了解；RAG/Agent是感兴趣或者有相关经验，不能改为必须有商业化RAG项目。"})

    boundaries = [
        ("今天岗位库中哪些Python实习岗位仍实际开放投递？请给出经过实时核验的开放状态；只凭静态JD不能核验时明确说明。", "静态JD不能核验今天是否仍开放投递；不能把岗位记录存在、发布日期或可转正措辞当作实时状态。"),
        ("请给出明确支持远程的Python岗位今年实际实习人数、转正人数和由此计算的真实转正率。", "JD未提供真实实习人数和转正人数，无法计算实际转正率；优秀可转正只是条件性机会。"),
        ("对同时提到LangGraph和Docker的招聘记录，请给出最近三个月投递人数、offer人数及实际录取率。", "静态岗位说明没有这三个月的投递/offer统计，无法计算录取率，不能据要求推测。"),
        ("对同时提到FastAPI和PostgreSQL的招聘记录，请列出签约后的精确税后到手月薪及各自社保个税扣除明细。", "不能从技能要求或零散薪酬宣传推导精确税后月薪、社保和个税明细；缺少合同和个人计税条件。"),
        ("请列出同时提到PyTorch和Docker的各岗位已经核验的直属主管姓名、主管企业邮箱和手机，不能用招聘投递联系人代替。", "岗位库不能证明直属主管身份及经过核验的联系方式；招聘联系人或投递邮箱不等于直属主管。"),
        ("对每周最低3天且可连续实习3个月的岗位，请给出每位实习生明年必定转正的结果及保证签约年限。", "当前静态JD不能保证未来每位实习生转正，更没有全员未来签约年限；转正机会不是录用保证。"),
        ("对于要求至少6个月实习的Python岗位，请给出团队最近三个月真实的日均加班小时与每月强制周末加班次数。", "岗位说明或福利描述不能提供过去三个月实际加班统计，无法给出真实均值和频次。"),
        ("对同时提到Docker和LangGraph的岗位，请给出我下一轮面试的具体日期、实际面试官分配与最终录用结果。", "静态JD不包含该候选人的面试排期、面试官分配和最终录用结果；不能编造个人招聘进展。"),
    ]
    for question, reference in boundaries:
        add("boundary_unverifiable", question, [], reference, rule="static_corpus_cannot_verify_requested_fact")
    if len(cases) != 40 or Counter(case["category"] for case in cases) != {
            "basic_lookup": 8, "constraint_filter": 12, "cross_job_reasoning": 12, "boundary_unverifiable": 8}:
        raise ValueError("挑战集分层数量不符合8/12/12/8")
    target = output / "dataset.challenge40.draft.json"
    payload = {"schema_version": 2, "created_at": now(), "status": "draft_unreviewed", "source_records": len(rows),
        "source_corpus_revision": manifest["corpus_revision"], "test_cases": cases,
        "notes": ["全库条件扫描独立于LightRAG/Chroma结果；不按某组命中情况选题。",
            "语义分组与参考答案已由助手依据原文整理，尚需用户人工审核，不等同于人工金标准。",
            "同源招聘记录参与不同问题，题目之间并不独立，不能把40题当40个独立业务样本。",
            "以招聘记录为检索单位；多子岗位记录不能把各子岗位要求合并为统一资格。",
            "使用与旧题集相同的冻结语料和向量索引；较长回答统一采用4096输出token上限。"]}
    if target.exists():
        previous = read_json(target)
        if digest(previous["test_cases"]) != digest(cases):
            raise ValueError("挑战集已存在且内容不同，未覆盖已有标注")
    else:
        write_json(target, payload)
    loaded = load_cases(target, rows, allow_draft=True)
    write_json(output / "challenge40_preparation_audit.json", {"corpus_revision": manifest["corpus_revision"],
        "checked_at": now(), "selection_audit": selection_audit, "question_counts": dict(Counter(case["category"] for case in loaded)),
        "answerable_cases": sum(case["answerable"] for case in loaded), "evidence_quotes_validated": sum(len(case["evidence_quotes"]) for case in loaded),
        "human_reviewed": False})
    return {"dataset": str(target), "questions": len(loaded), "categories": dict(Counter(case["category"] for case in loaded))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Prepare the job retrieval challenge dataset.')
    parser.add_argument("--output", type=type(DEFAULT_OUTPUT), default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(build(args.output))
