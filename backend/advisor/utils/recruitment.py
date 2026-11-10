"""Conservative screening of recruitment evidence, rather than topical keyword relevance."""
import re


def explicit_recruitment_types(text):
    # Qualification caveats are not requests for a recruitment channel. Remove
    # their clauses before looking for positively mentioned categories.
    text = "，".join(clause for clause in re.split(r"[，,。；;\n]", str(text or ""))
        if not re.search(r"不(?:能|要)?(?:默认|假定)|未(?:确认|核实)|(?:资格|身份|届别).{0,10}(?:未知|未明|待确认)|不代表|不能证明", clause))
    category = r"(?:校招|校园招聘|社招|社会招聘|实习(?:生)?|春招|春季招聘|秋招|秋季招聘)"
    categories = category + r"(?:\s*(?:、|或|和|/|及|与)?\s*" + category + r")*"
    unrestricted = r"(?:没有限定|没有限制|未限定|不限定|不限制|不限于|不限)"
    text = re.sub(unrestricted + r"\s*(?:招聘类型|招聘类别|类型|类别)?\s*" + categories, "", text)
    text = re.sub(categories + r"\s*(?:均|都)?\s*" + unrestricted, "", text)
    patterns = {"校招":"校招|校园招聘", "社招":"社招|社会招聘", "实习":"实习(?:生)?", "春招":"春招|春季招聘", "秋招":"秋招|秋季招聘"}
    allowed = set()
    for category, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 12):match.start()]
            suffix = text[match.end():match.end() + 8]
            if re.search(r"(?:不要|不找|排除|不考虑|不包括|不限于|不限|未限定|不限定|没有限定|非)\s*$", prefix):
                continue
            if re.match(r"(?:不限|不限制|未限定|不限定)", suffix):
                continue
            allowed.add(category)
    return allowed


def normalize_recruitment_types(values):
    """Map source batch descriptions to channel categories; unknown stays unknown."""
    result = set()
    for value in values:
        value = str(value or "")
        if re.search(r"实习", value):
            result.add("实习")
            for season, pattern in (("春招", r"春招|春季招聘"), ("秋招", r"秋招|秋季招聘")):
                if re.search(pattern, value):
                    result.add(season)
            continue  # A cohort-specific internship is still not a graduate job.
        for kind, pattern in (("社招", r"社招|社会招聘"), ("校招", r"校招|校园|应届|\d{2,4}届"),
                              ("春招", r"春招|春季招聘"), ("秋招", r"秋招|秋季招聘")):
            if re.search(pattern, value):
                result.add(kind)
    return result


def recruitment_types_conflict(allowed, observed):
    observed = normalize_recruitment_types(observed)
    if not allowed or not observed:
        return False
    # Spring/autumn are seasons within graduate recruitment, not contradictory channels.
    compatible = set(observed)
    if observed & {"春招", "秋招"} and not observed & {"实习", "社招"}:
        compatible.add("校招")
    return not (set(allowed) & compatible)


def explicit_publication_window(text):
    """Detect an actual recency request, excluding truthfulness warnings and negations."""
    for clause in re.split(r"[，,。；;\n]", str(text or "")):
        if re.search(r"不要冒充|不能冒充|不应冒充|不得冒充|不要(?:只|仅)|不(?:只|仅)(?:找|限)|不(?:限|要求|限制)|无需|不必|日期未知|未核实", clause):
            continue
        if re.search(r"优先|尽量|最好", clause) and not re.search(r"只|仅|必须|限定|要求", clause):
            continue
        if re.search(r"最近|近期|近[一二三四五六七八九十两\d]+[天周月年]|本周|本月", clause):
            return True
        if re.search(r"发布|公告", clause) and re.search(r"20\d{2}(?:[-./年]\d{1,2})(?:[-./月]\d{1,2})?日?.{0,8}(?:起|之后|以后)|(?:起|之后|以后).{0,8}20\d{2}", clause):
            return True
    return False


HIRING = re.compile(r"招聘|诚聘|急招|热招|在招|招人|招募|招收|招实习|加入我们|欢迎加入|开放岗位|开放职位|扩招|内推|校招|社招|春招|秋招|\bhiring\b|job\s+openings?", re.I)
DETAIL = re.compile(r"岗位|职位|实习生|工程师|应届|毕业生|招聘对象|任职要求|工作地点|薪资|投递|网申|应聘|简历|careers?|apply", re.I)
NON_JOB = re.compile(r"学习路线|路线分享|学习路径|技术分享|实战教程|面试经验|面试复盘|面经|课程|培训|实训|招生|训练营|资料领取|资料合集|解决方案|合规落地实操|知识付费|付费社群|招聘.{0,8}(?:指南|趋势|报告|分析)|秋招信号|创造新岗位|人才.{0,8}吃香")
DIRECT_HIRING = re.compile(r"(?:我们|本公司|本团队|团队|公司|实验室|研究院).{0,16}(?:正在招聘|诚聘|急招|招聘|招募|招收)|招聘(?:岗位|职位|对象|人数)|(?:岗位|职位)(?:名称|职责|要求)|任职要求|投递(?:方式|邮箱|入口|链接)|简历.{0,12}(?:发送|投递|请发)|网申(?:地址|入口|链接)", re.I)
DIRECT_OPENING = re.compile(r"(?:我们|本公司|本团队|公司|团队|实验室|研究院).{0,12}(?:正在招聘|诚聘|急招|现招聘|现招募)|招聘(?:岗位|职位|对象|人数)[：:]|投递(?:邮箱|方式|入口)[：:]|简历.{0,12}(?:发送至|投递至)|网申(?:入口|地址)[：:]", re.I)
JOB_TITLE = re.compile(r"(?:招聘|诚聘|急招).{0,12}(?:讲师|教师|老师|顾问|工程师|研发|运营|销售|经理|主管|专员)|(?:讲师|教师|老师|顾问|工程师|研发|运营|销售|经理|主管|专员).{0,8}(?:招聘|诚聘|急招)")


def recruitment_source_quality(content: str, links=()) -> dict:
    """A hiring claim embedded in a lead-generation page is not an actionable vacancy."""
    promotional = re.search(r"扫码回复|领取.{0,12}(?:资料|题库|模板)|简历(?:修改|优化|服务)|求职(?:辅导|服务)|付费|培训报名", content)
    direct_email = re.search(r"(?:投递|简历|应聘)[^\n]{0,60}[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", content)
    direct_link = any(re.search(r"投递|应聘|网申|招聘入口", item.get("text", "")) and item.get("url", "").startswith("https://") for item in links)
    if promotional and not (direct_email or direct_link):
        return {"level": "lead", "reason": "包含资料领取或求职服务引流，未读到直接投递方式；仅作待核实线索，不计入有效岗位数量"}
    return {"level": "candidate", "reason": "需按用户方向、招聘类别与原文证据进行语义核对"}


def screen_recruitment(title: str, content: str | None = None) -> dict:
    """Reject obvious noise early; unknown titles still require reading and semantic review."""
    read = content is not None
    title, content = str(title or ""), str(content or "")
    text = title + "\n" + content
    if re.search(r"已招满|已满员|岗位已关闭|招聘已结束|停止招聘", title) and not re.search(r"部分|其他|其余|仍招|继续招", title):
        return {"kind": "excluded", "reason": "标题明确标注已招满或招聘结束，不作为当前招聘机会"}
    if NON_JOB.search(title) and not HIRING.search(title):
        return {"kind": "excluded", "reason": "标题为教程、学习分享或推广内容，未见招聘公告意图"}
    job_ad = JOB_TITLE.search(title) and not re.search(r"指南|分享|面经|招生|实训|训练营", title) and DIRECT_HIRING.search(content)
    if NON_JOB.search(title) and not (HIRING.search(text) and DIRECT_OPENING.search(content) or job_ad):
        return {"kind": "excluded", "reason": "文章以教程、培训或经验内容为主，未见可核对的岗位招聘说明"}
    if HIRING.search(text) and DETAIL.search(text):
        return {"kind": "recruitment", "reason": "原文包含招聘动作及岗位、应聘或投递信息，仍需核对用户条件"}
    if read:
        return {"kind": "unconfirmed", "reason": "未读到明确的招聘动作及岗位或应聘信息，不能作为招聘结果"}
    return {"kind": "unconfirmed", "reason": "仅凭标题无法确认，需读取原文"}
