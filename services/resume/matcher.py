import html
import os
import re
from datetime import datetime

try:
    from docx import Document
except Exception:  # pragma: no cover - optional dependency
    Document = None


STRUCTURED_RESUME_SCHEMA = {
    "UUID": "string",
    "Personal Data": {
        "firstName": "string",
        "lastName": "string",
        "email": "string",
        "phone": "string",
        "linkedin": "string",
        "portfolio": "string",
        "location": {"city": "string", "country": "string"},
    },
    "Experiences": [
        {
            "jobTitle": "string",
            "company": "string",
            "location": "string",
            "startDate": "YYYY-MM-DD",
            "endDate": "YYYY-MM-DD or Present",
            "description": ["string", "..."],
            "technologiesUsed": ["string", "..."],
        }
    ],
    "Projects": [
        {
            "projectName": "string",
            "description": "string",
            "technologiesUsed": ["string", "..."],
            "link": "string",
            "startDate": "YYYY-MM-DD",
            "endDate": "YYYY-MM-DD",
        }
    ],
    "Skills": [{"category": "string", "skillName": "string"}],
    "Research Work": [
        {
            "title": "string | null",
            "publication": "string | null",
            "date": "YYYY-MM-DD | null",
            "link": "string | null",
            "description": "string | null",
        }
    ],
    "Achievements": ["string", "..."],
    "Education": [
        {
            "institution": "string",
            "degree": "string",
            "fieldOfStudy": "string | null",
            "startDate": "YYYY-MM-DD",
            "endDate": "YYYY-MM-DD",
            "grade": "string",
            "description": "string",
        }
    ],
    "Extracted Keywords": ["string", "..."],
}

STRUCTURED_JOB_SCHEMA = {
    "jobId": "string",
    "jobTitle": "string",
    "companyProfile": {
        "companyName": "string",
        "industry": "Optional[string]",
        "website": "Optional[string]",
        "description": "Optional[string]",
    },
    "location": {
        "city": "string",
        "state": "string",
        "country": "string",
        "remoteStatus": "Fully Remote | Hybrid | On-site | Remote | Not Specified | Multiple Locations",
    },
    "datePosted": "YYYY-MM-DD",
    "employmentType": "Full-time | Full time | Part-time | Part time | Contract | Internship | Temporary | Not Specified",
    "jobSummary": "string",
    "keyResponsibilities": ["string", "..."],
    "qualifications": {
        "required": ["string", "..."],
        "preferred": ["string", "..."],
    },
    "compensationAndBenefits": {
        "salaryRange": "string",
        "benefits": ["string", "..."],
    },
    "applicationInfo": {
        "howToApply": "string",
        "applyLink": "string",
        "contactEmail": "Optional[string]",
    },
    "extractedKeywords": ["string", "..."],
}

STRUCTURED_RESUME_PROMPT = """
You are a JSON extraction engine. Convert the following resume text into precisely the JSON schema specified below.
- Do not compose any extra fields or commentary.
- Do not make up values for any fields.
- Use "Present" if an end date is ongoing.
- Make sure dates are in YYYY-MM-DD.
- Do not format the response in Markdown or any other format. Just output raw JSON.

Schema:
```json
{0}
```

Resume:
```text
{1}
```

NOTE: Please output only a valid JSON matching the EXACT schema.
""".strip()

STRUCTURED_JOB_PROMPT = """
You are a JSON-extraction engine. Convert the following raw job posting text into exactly the JSON schema below:
- Do not add any extra fields or prose.
- Use YYYY-MM-DD for all dates.
- Ensure any URLs conform to URI format.
- Do not change the structure or key names.
- Do not format the response in Markdown or any other format. Just output raw JSON.

Schema:
```json
{0}
```

Job Posting:
{1}

Note: Please output only a valid JSON matching the EXACT schema with no surrounding commentary.
""".strip()

HR_JUDGE_PROMPT = """
# 角色

你是一位资深招聘官和 HRBP。请严格基于岗位描述与原始简历内容，输出一份简体中文 Markdown 分析报告。

# 输出要求

1. 先给出 30 秒结论：建议继续推进还是暂缓。
2. 必须围绕岗位 JD 分析简历的匹配度，不要脱离岗位空谈。
3. 对每个主要问题使用“问题 / 影响 / 建议”的结构。
4. 不得捏造简历中不存在的经历、数据或成果。
5. 如果信息不足，要明确指出缺口以及需要补充的证据。
6. 最后给出可执行的修改清单。
7. 只输出 Markdown。

当前时间: {datetime}

Job Description:
```md
{Job_Description}
```

Original Resume:
```md
{raw_resume}
```
""".strip()

FLEXIBLE_MATCH_ANALYSIS_PROMPT = """
# 角色

你是一位资深招聘官和职业判断顾问。请先读懂原始岗位文本，再结合原始简历内容输出一份简体中文 Markdown 分析报告。

# 输出要求

1. 先给出 30 秒结论：是否建议继续推进，并给出整体匹配判断。
2. 先用 3-6 条 bullet 提炼岗位真正关注的核心能力，不要机械复述原文。
3. 再围绕“匹配点 / 风险点 / 修改建议”展开分析。
4. 如果岗位文本写得比较散、混杂或不标准，要明确说明你是如何理解岗位重点的。
5. 不得捏造简历中不存在的经历、数据或成果。
6. 如果信息不足，要明确指出缺口以及需要补充的证据。
7. 最后给出可执行的修改清单。
8. 只输出 Markdown。

当前时间: {datetime}

Raw Job Posting:
```md
{job_description}
```

Original Resume:
```md
{raw_resume}
```
""".strip()

RESUME_REVIEW_PROMPT = """
# 角色

你是一位资深招聘官和职业规划顾问。用户暂时没有提供明确岗位 JD，请仅基于原始简历内容输出一份简体中文 Markdown 诊断报告。

# 输出要求

1. 先给出 30 秒结论：这份简历当前最突出的优势、最明显的短板，以及最适合优先尝试的 2-3 个职业方向。
2. 不要求绑定某一个固定岗位，而是做通用竞争力判断和方向建议。
3. 使用“优势 / 风险 / 建议”的结构。
4. 不得捏造简历中不存在的经历、数据或成果。
5. 如果信息不足，要明确指出缺口以及需要补充的证据。
6. 最后给出 3-6 条可执行的简历优化建议。
7. 只输出 Markdown。

当前时间: {datetime}

Original Resume:
```md
{raw_resume}
```
""".strip()


def _compact_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_list(value):
    return value if isinstance(value, list) else []


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _pick(mapping, *keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value is not None and str(value).strip():
            return _compact_text(value)
    return ""


def _unique_entries(items, limit=None):
    result = []
    seen = set()
    for item in items or []:
        text = _compact_text(item)
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(text)
        if limit and len(result) >= limit:
            break
    return result


def _normalize_keyword(text):
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "")).lower()


def _keyword_overlap(left_items, right_items):
    left_map = {}
    for item in left_items or []:
        key = _normalize_keyword(item)
        if key and key not in left_map:
            left_map[key] = _compact_text(item)
    right_map = {}
    for item in right_items or []:
        key = _normalize_keyword(item)
        if key and key not in right_map:
            right_map[key] = _compact_text(item)

    matched = []
    missing = []
    for key, value in right_map.items():
        if key in left_map:
            matched.append(value)
        else:
            missing.append(value)
    return matched[:16], missing[:16]


def _coerce_page_texts(items, max_pages):
    page_texts = []
    for item in items or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("markdown") or item.get("page_text") or ""
        else:
            text = item
        text = _compact_text(text)
        if text:
            page_texts.append(text)
        if len(page_texts) >= max_pages:
            break
    return page_texts


def _truncate_join(items, max_chars):
    text = "\n\n".join(_unique_entries(items))
    return text[:max_chars].strip()


def _extract_docx_text(file_path):
    if Document is None:
        raise ValueError("当前环境缺少 DOCX 解析依赖 `python-docx`。")

    document = Document(file_path)
    chunks = []
    for paragraph in document.paragraphs:
        text = _compact_text(paragraph.text)
        if text:
            chunks.append(text)

    for table in document.tables:
        for row in table.rows:
            row_text = " | ".join([text for text in (_compact_text(cell.text) for cell in row.cells) if text])
            if row_text:
                chunks.append(row_text)
    return chunks

def build_resume_text_payload(
    file_path,
    extract_pdf_text_pages,
    should_fallback_ocr,
    ocr_pdf_pages,
    max_pages=12,
    max_chars=20000,
):
    suffix = str(os.path.splitext(file_path)[1] or "").lower()
    if suffix == ".docx":
        page_texts = _coerce_page_texts(_extract_docx_text(file_path), max_pages)
        plain_text = _truncate_join(page_texts, max_chars)
        if not plain_text:
            raise ValueError("未能从简历中提取到有效文本，请检查文件内容。")
        return {
            "plain_text": plain_text,
            "page_texts": page_texts,
            "analysis_meta": {
                "file_type": "docx",
                "page_count": len(page_texts),
                "char_count": len(plain_text),
                "ocr_used": False,
            },
        }

    if suffix != ".pdf":
        raise ValueError("仅支持 PDF 或 DOCX 简历文件。")

    page_texts = _coerce_page_texts(extract_pdf_text_pages(file_path), max_pages)
    plain_text = _truncate_join(page_texts, max_chars)
    ocr_used = False

    try:
        needs_ocr = should_fallback_ocr(page_texts)
    except TypeError:
        try:
            needs_ocr = should_fallback_ocr(file_path, page_texts)
        except TypeError:
            needs_ocr = should_fallback_ocr(file_path)

    if needs_ocr or not plain_text:
        ocr_pages = _coerce_page_texts(ocr_pdf_pages(file_path), max_pages)
        ocr_text = _truncate_join(ocr_pages, max_chars)
        if ocr_text:
            page_texts = ocr_pages
            plain_text = ocr_text
            ocr_used = True

    if not plain_text:
        raise ValueError("未能从简历中提取到有效文本，请检查文件内容。")

    return {
        "plain_text": plain_text,
        "page_texts": page_texts,
        "analysis_meta": {
            "file_type": "pdf",
            "page_count": len(page_texts),
            "char_count": len(plain_text),
            "ocr_used": ocr_used,
        },
    }


COMMON_JOB_KEYWORD_PATTERNS = (
    (r"\bpython\b", "Python"),
    (r"\bjava\b", "Java"),
    (r"\bc\+\+\b", "C++"),
    (r"\bjavascript\b|\bjs\b", "JavaScript"),
    (r"\btypescript\b|\bts\b", "TypeScript"),
    (r"\breact\b", "React"),
    (r"\bvue\b", "Vue"),
    (r"\bnode(?:\.js)?\b", "Node.js"),
    (r"\bfastapi\b", "FastAPI"),
    (r"\bdjango\b", "Django"),
    (r"\bspring\s*boot\b", "Spring Boot"),
    (r"\bsql\b|\bmysql\b|\bpostgres(?:ql)?\b", "SQL"),
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\baws\b", "AWS"),
    (r"\bgcp\b", "GCP"),
    (r"\blinux\b", "Linux"),
    (r"\bgit\b", "Git"),
    (r"\bai\b|人工智能|大模型|llm|agent", "AI"),
    (r"机器学习|machine learning", "机器学习"),
    (r"深度学习|deep learning", "深度学习"),
    (r"数据分析|数据复盘|报表分析", "数据分析"),
    (r"产品运营|运营策略", "产品运营"),
    (r"内容运营", "内容运营"),
    (r"用户增长|增长运营", "用户增长"),
    (r"用户研究|用户调研", "用户研究"),
    (r"竞品分析", "竞品分析"),
    (r"需求分析|需求拆解", "需求分析"),
    (r"项目管理|推进落地|跨团队", "项目推进"),
    (r"excel", "Excel"),
    (r"\bppt\b|powerpoint", "PPT"),
)

CAREER_DIRECTION_RULES = (
    ("AI 产品运营", (r"\bai\b|人工智能|llm|大模型", r"产品运营|内容运营|增长运营|用户运营")),
    ("产品经理", (r"产品|需求分析|用户研究|竞品分析|路线图|roadmap",)),
    ("数据分析", (r"数据分析|sql|excel|报表|可视化|数据复盘",)),
    ("后端开发", (r"\bpython\b|\bjava\b|后端|服务端|api|fastapi|django|spring|mysql|redis",)),
    ("前端开发", (r"前端|javascript|typescript|react|vue|html|css",)),
    ("算法 / AI 应用", (r"\bai\b|机器学习|深度学习|llm|pytorch|tensorflow|nlp|推荐系统",)),
    ("测试 / QA", (r"测试|qa|自动化测试|selenium|pytest",)),
    ("项目协调 / 运营支持", (r"协调|推进|落地|跨团队|项目管理|排期|复盘",)),
)

GENERIC_JOB_KEYWORD_STOPWORDS = {
    "本科及以上学历",
    "专业不限",
    "逻辑清晰",
    "表达能力好",
    "沟通能力",
    "团队合作",
    "责任心强",
    "抗压能力",
    "有相关经验者优先",
}


def _split_multiline_text(value):
    lines = []
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        text = _compact_text(raw_line)
        if text:
            lines.append(text)
    return lines


def _strip_list_prefix(value):
    return re.sub(
        r"^\s*(?:[-*•·]+|[0-9]{1,2}[\.、\)]|[（(]?[0-9一二三四五六七八九十]+[）)\.、])\s*",
        "",
        str(value or ""),
    ).strip()


def _classify_job_section(line):
    raw = str(line or "").strip()
    normalized = raw.rstrip(":：").lower()
    if len(normalized) > 18 and not re.match(r"^[^:：]{0,12}[:：]", raw) and not re.search(r"[:：]$", raw):
        return ""
    if any(token in normalized for token in ("岗位职责", "职位描述", "工作职责", "工作内容", "职责说明")):
        return "responsibilities"
    if any(token in normalized for token in ("任职要求", "岗位要求", "职位要求", "任职资格", "职位资格")):
        return "required"
    if any(token in normalized for token in ("加分项", "优先条件", "优先考虑", "preferred", "bonus")):
        return "preferred"
    return ""


def _collect_job_sections(lines):
    sections = {"general": [], "responsibilities": [], "required": [], "preferred": []}
    current = "general"
    for line in lines:
        section = _classify_job_section(line)
        if section:
            current = section
            inline = re.sub(r"^[^:：]+[:：]\s*", "", line).strip()
            if inline and inline != line:
                sections[current].append(_strip_list_prefix(inline))
            continue

        cleaned = _strip_list_prefix(line)
        if cleaned:
            sections[current].append(cleaned)
    return sections


def _extract_job_title(job_text, lines):
    patterns = (
        r"(?:职位名称|岗位名称|招聘岗位|应聘岗位)\s*[:：]\s*([^\n，。；;]{2,40})",
        r"(?:岗位|职位)\s*[:：]\s*([^\n，。；;]{2,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, str(job_text or ""), flags=re.IGNORECASE)
        if match:
            return _compact_text(match.group(1))

    for line in lines[:5]:
        cleaned = _strip_list_prefix(line)
        if 2 <= len(cleaned) <= 32 and re.search(
            r"工程师|开发|产品|运营|分析|经理|设计|算法|测试|研究|实习|专员|策划|顾问",
            cleaned,
            flags=re.IGNORECASE,
        ):
            return cleaned
    return ""


def _extract_company_name(job_text):
    patterns = (
        r"(?:公司名称|招聘公司|所属公司)\s*[:：]\s*([^\n，。；;]{2,40})",
        r"(?:公司|企业)\s*[:：]\s*([^\n，。；;]{2,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, str(job_text or ""), flags=re.IGNORECASE)
        if match:
            return _compact_text(match.group(1))
    return ""


def _extract_job_city(job_text):
    patterns = (
        r"(?:工作地点|工作城市|办公地点|base|城市|地点)\s*[:：]\s*([^\n，。；;]{2,30})",
        r"(上海|北京|深圳|广州|杭州|成都|武汉|南京|苏州|西安|长沙|厦门|香港|中国香港)",
    )
    for pattern in patterns:
        match = re.search(pattern, str(job_text or ""), flags=re.IGNORECASE)
        if match:
            return _compact_text(match.group(1))
    return ""


def _extract_employment_type(job_text, job_title):
    source = f"{job_title}\n{job_text}"
    if re.search(r"实习|intern", source, flags=re.IGNORECASE):
        return "Internship"
    if re.search(r"兼职|part[- ]?time", source, flags=re.IGNORECASE):
        return "Part-time"
    if re.search(r"合同|contract", source, flags=re.IGNORECASE):
        return "Contract"
    if re.search(r"全职|full[- ]?time", source, flags=re.IGNORECASE):
        return "Full-time"
    return "Not Specified"


def _extract_remote_status(job_text):
    text = str(job_text or "")
    if re.search(r"远程|remote", text, flags=re.IGNORECASE):
        return "Remote"
    if re.search(r"混合办公|hybrid", text, flags=re.IGNORECASE):
        return "Hybrid"
    if re.search(r"现场|onsite|到岗办公", text, flags=re.IGNORECASE):
        return "On-site"
    return "Not Specified"


def _extract_job_summary(lines):
    summary = []
    for line in lines:
        if re.match(r"^(?:职位名称|岗位名称|招聘岗位|工作地点|工作城市|办公地点|base|城市|地点)\s*[:：]", line, flags=re.IGNORECASE):
            continue
        if _classify_job_section(line):
            continue
        cleaned = _strip_list_prefix(line)
        if len(cleaned) < 4:
            continue
        summary.append(cleaned)
        if len(summary) >= 3:
            break
    return " ".join(summary)[:220]


def _extract_job_keywords(job_title, sections, job_text):
    keywords = []
    source_texts = [job_title]
    source_texts.extend(sections.get("responsibilities") or [])
    source_texts.extend(sections.get("required") or [])
    source_texts.extend(sections.get("preferred") or [])
    source_texts.append(str(job_text or ""))

    for pattern, label in COMMON_JOB_KEYWORD_PATTERNS:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for text in source_texts):
            keywords.append(label)

    for line in (sections.get("responsibilities") or []) + (sections.get("required") or []) + (sections.get("preferred") or []):
        cleaned = _strip_list_prefix(line)
        cleaned = re.sub(r"^(?:熟悉|了解|具备|负责|参与|协助|能够|有|对|掌握|优先考虑|优先)\s*", "", cleaned)
        for chunk in re.split(r"[，,；;。/|]", cleaned):
            phrase = _compact_text(chunk)
            if not phrase or phrase in GENERIC_JOB_KEYWORD_STOPWORDS:
                continue
            if 2 <= len(phrase) <= 18:
                keywords.append(phrase)

    return _unique_entries([job_title, *keywords], 24)


def build_job_payload_from_text(job_text):
    text = str(job_text or "").strip()
    if not text:
        return {}

    lines = _split_multiline_text(text)
    sections = _collect_job_sections(lines)
    job_title = _extract_job_title(text, lines)
    company_name = _extract_company_name(text)
    city = _extract_job_city(text)
    employment_type = _extract_employment_type(text, job_title)
    remote_status = _extract_remote_status(text)
    job_summary = _extract_job_summary(lines)
    extracted_keywords = _extract_job_keywords(job_title, sections, text)

    return {
        "jobTitle": job_title,
        "companyProfile": {
            "companyName": company_name,
            "industry": "",
            "website": "",
            "description": "",
        },
        "location": {
            "city": city,
            "state": "",
            "country": "中国" if city else "",
            "remoteStatus": remote_status,
        },
        "datePosted": "",
        "employmentType": employment_type,
        "jobSummary": job_summary,
        "keyResponsibilities": _unique_entries(sections.get("responsibilities"), 10),
        "qualifications": {
            "required": _unique_entries(sections.get("required"), 10),
            "preferred": _unique_entries(sections.get("preferred"), 8),
        },
        "compensationAndBenefits": {
            "salaryRange": "",
            "benefits": [],
        },
        "applicationInfo": {
            "howToApply": "",
            "applyLink": "",
            "contactEmail": "",
        },
        "extractedKeywords": extracted_keywords,
    }

def normalize_structured_resume(payload):
    data = _safe_dict(payload)
    personal = _safe_dict(data.get("Personal Data") or data.get("personal_data"))
    personal_location = _safe_dict(personal.get("location"))

    experiences = []
    for item in _safe_list(data.get("Experiences") or data.get("experiences")):
        entry = _safe_dict(item)
        experiences.append(
            {
                "job_title": _pick(entry, "jobTitle", "job_title", "title", "role"),
                "company": _pick(entry, "company", "companyName"),
                "location": _pick(entry, "location"),
                "start_date": _pick(entry, "startDate", "start_date"),
                "end_date": _pick(entry, "endDate", "end_date"),
                "description": _unique_entries(entry.get("description")),
                "technologies_used": _unique_entries(entry.get("technologiesUsed") or entry.get("technologies_used")),
            }
        )

    projects = []
    for item in _safe_list(data.get("Projects") or data.get("projects")):
        entry = _safe_dict(item)
        projects.append(
            {
                "project_name": _pick(entry, "projectName", "project_name", "name"),
                "description": _pick(entry, "description", "summary"),
                "technologies_used": _unique_entries(entry.get("technologiesUsed") or entry.get("technologies_used")),
                "link": _pick(entry, "link", "url"),
                "start_date": _pick(entry, "startDate", "start_date"),
                "end_date": _pick(entry, "endDate", "end_date"),
            }
        )

    skills = []
    for item in _safe_list(data.get("Skills") or data.get("skills")):
        entry = _safe_dict(item)
        skills.append(
            {
                "category": _pick(entry, "category", "type"),
                "skill_name": _pick(entry, "skillName", "skill_name", "name"),
            }
        )

    education = []
    for item in _safe_list(data.get("Education") or data.get("education")):
        entry = _safe_dict(item)
        education.append(
            {
                "institution": _pick(entry, "institution", "school"),
                "degree": _pick(entry, "degree"),
                "field_of_study": _pick(entry, "fieldOfStudy", "field_of_study", "major"),
                "start_date": _pick(entry, "startDate", "start_date"),
                "end_date": _pick(entry, "endDate", "end_date"),
                "grade": _pick(entry, "grade", "gpa"),
                "description": _pick(entry, "description"),
            }
        )

    return {
        "uuid": _pick(data, "UUID", "uuid"),
        "personal_data": {
            "first_name": _pick(personal, "firstName", "first_name"),
            "last_name": _pick(personal, "lastName", "last_name"),
            "email": _pick(personal, "email"),
            "phone": _pick(personal, "phone"),
            "linkedin": _pick(personal, "linkedin"),
            "portfolio": _pick(personal, "portfolio"),
            "location": {
                "city": _pick(personal_location, "city"),
                "country": _pick(personal_location, "country"),
            },
        },
        "experiences": experiences,
        "projects": projects,
        "skills": skills,
        "research_work": _safe_list(data.get("Research Work") or data.get("research_work")),
        "achievements": _unique_entries(data.get("Achievements") or data.get("achievements")),
        "education": education,
        "extracted_keywords": _unique_entries(data.get("Extracted Keywords") or data.get("extracted_keywords")),
    }


def normalize_structured_job(payload):
    data = _safe_dict(payload)
    company = _safe_dict(data.get("companyProfile") or data.get("company_profile"))
    location = _safe_dict(data.get("location"))
    qualifications = _safe_dict(data.get("qualifications"))
    benefits = _safe_dict(data.get("compensationAndBenefits") or data.get("compensation_and_benefits"))
    application = _safe_dict(data.get("applicationInfo") or data.get("application_info"))
    return {
        "job_id": _pick(data, "jobId", "job_id"),
        "job_title": _pick(data, "jobTitle", "job_title", "title"),
        "company_profile": {
            "company_name": _pick(company, "companyName", "company_name"),
            "industry": _pick(company, "industry"),
            "website": _pick(company, "website"),
            "description": _pick(company, "description"),
        },
        "location": {
            "city": _pick(location, "city"),
            "state": _pick(location, "state"),
            "country": _pick(location, "country"),
            "remote_status": _pick(location, "remoteStatus", "remote_status"),
        },
        "date_posted": _pick(data, "datePosted", "date_posted"),
        "employment_type": _pick(data, "employmentType", "employment_type"),
        "job_summary": _pick(data, "jobSummary", "job_summary", "summary"),
        "key_responsibilities": _unique_entries(data.get("keyResponsibilities") or data.get("key_responsibilities")),
        "qualifications": {
            "required": _unique_entries(qualifications.get("required")),
            "preferred": _unique_entries(qualifications.get("preferred")),
        },
        "compensation_and_benefits": {
            "salary_range": _pick(benefits, "salaryRange", "salary_range"),
            "benefits": _unique_entries(benefits.get("benefits")),
        },
        "application_info": {
            "how_to_apply": _pick(application, "howToApply", "how_to_apply"),
            "apply_link": _pick(application, "applyLink", "apply_link"),
            "contact_email": _pick(application, "contactEmail", "contact_email"),
        },
        "extracted_keywords": _unique_entries(data.get("extractedKeywords") or data.get("extracted_keywords")),
    }


def _collect_resume_keywords(resume):
    keywords = list(resume.get("extracted_keywords") or [])
    keywords.extend(skill.get("skill_name") for skill in resume.get("skills") or [])
    for item in resume.get("experiences") or []:
        keywords.extend(item.get("technologies_used") or [])
        keywords.append(item.get("job_title"))
    for item in resume.get("projects") or []:
        keywords.extend(item.get("technologies_used") or [])
        keywords.append(item.get("project_name"))
    return _unique_entries(keywords, 24)


def _collect_job_keywords(job):
    keywords = list(job.get("extracted_keywords") or [])
    keywords.extend(job.get("qualifications", {}).get("required") or [])
    keywords.extend(job.get("qualifications", {}).get("preferred") or [])
    keywords.extend(job.get("key_responsibilities") or [])
    keywords.append(job.get("job_title"))
    return _unique_entries(keywords, 24)


def _count_text_matches(texts, pattern):
    count = 0
    for text in texts:
        if re.search(pattern, str(text or ""), flags=re.IGNORECASE):
            count += 1
    return count


def _derive_candidate_name(resume):
    personal = resume.get("personal_data") or {}
    first_name = personal.get("first_name") or ""
    last_name = personal.get("last_name") or ""
    full_name = _compact_text(f"{last_name}{first_name}") or _compact_text(f"{first_name} {last_name}")
    if full_name:
        return full_name
    email = personal.get("email") or ""
    if "@" in email:
        return email.split("@", 1)[0]
    return "候选人"

def _build_resume_overview(resume):
    name = _derive_candidate_name(resume)
    experiences = resume.get("experiences") or []
    projects = resume.get("projects") or []
    skills = resume.get("skills") or []
    headline = experiences[0].get("job_title") if experiences else ""
    return {
        "candidate_name": name,
        "headline": headline,
        "experience_count": len(experiences),
        "project_count": len(projects),
        "skill_count": len([item for item in skills if item.get("skill_name")]),
    }


def _build_job_overview(job):
    location = job.get("location") or {}
    parts = [location.get("city"), location.get("state"), location.get("country")]
    return {
        "job_title": job.get("job_title") or "",
        "company_name": (job.get("company_profile") or {}).get("company_name") or "",
        "location": " / ".join([part for part in parts if part]),
        "employment_type": job.get("employment_type") or "",
    }


def _infer_recommended_directions(resume):
    source_parts = []
    for item in resume.get("experiences") or []:
        source_parts.append(item.get("job_title") or "")
        source_parts.extend(item.get("description") or [])
        source_parts.extend(item.get("technologies_used") or [])
    for item in resume.get("projects") or []:
        source_parts.append(item.get("project_name") or "")
        source_parts.append(item.get("description") or "")
        source_parts.extend(item.get("technologies_used") or [])
    for item in resume.get("skills") or []:
        source_parts.append(item.get("skill_name") or "")

    source_text = " ".join(_unique_entries(source_parts)).lower()
    ranked = []
    for label, patterns in CAREER_DIRECTION_RULES:
        score = 0
        for pattern in patterns:
            if re.search(pattern, source_text, flags=re.IGNORECASE):
                score += 1
        if score:
            ranked.append((score, label))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    directions = [label for _, label in ranked]
    if not directions:
        directions.extend(item.get("job_title") for item in resume.get("experiences") or [])
    return _unique_entries(directions, 4)


def _build_roles_detected(resume):
    roles = []
    for item in resume.get("experiences") or []:
        role = item.get("job_title")
        if role:
            roles.append({"role": role, "company": item.get("company") or "", "confidence": 0.82})
    if not roles:
        for item in resume.get("projects") or []:
            project = item.get("project_name")
            if project:
                roles.append({"role": project, "company": "", "confidence": 0.6})
    return roles[:8]


def _build_project_highlights(resume):
    highlights = []
    for item in resume.get("projects") or []:
        highlights.append(
            {
                "project": item.get("project_name") or "项目",
                "role": "",
                "impact": "、".join(item.get("technologies_used") or []),
                "evidence": item.get("description") or "",
            }
        )
    if not highlights:
        for item in resume.get("experiences") or []:
            highlights.append(
                {
                    "project": item.get("company") or item.get("job_title") or "经历",
                    "role": item.get("job_title") or "",
                    "impact": "、".join(item.get("technologies_used") or []),
                    "evidence": "；".join((item.get("description") or [])[:2]),
                }
            )
    return highlights[:6]

def _build_evidence_spans(resume):
    items = []
    for exp in resume.get("experiences") or []:
        for text in exp.get("description") or []:
            items.append({"quote": text, "page_no": 1})
    for project in resume.get("projects") or []:
        if project.get("description"):
            items.append({"quote": project.get("description"), "page_no": 1})
    return items[:6]


def _build_leadership_signals(resume):
    keywords = r"主导|负责|带领|协调|协同|mentor|lead|owner|manage|推动|组织"
    signals = []
    for exp in resume.get("experiences") or []:
        descriptions = exp.get("description") or []
        if _count_text_matches(descriptions, keywords):
            signals.append({"signal": f"在 {exp.get('company') or exp.get('job_title') or '相关经历'} 中承担推进职责"})
    return signals[:4]


def _build_uncertainty_layer(resume, missing_keywords, job, analysis_mode="job_match"):
    issues = []
    if not (resume.get("experiences") or []):
        issues.append(
            {
                "item": "工作经历不足",
                "reason": "简历中缺少可识别的工作经历条目。",
                "needed_evidence": "补充岗位、公司、时间和关键成果。",
            }
        )
    if analysis_mode != "job_match":
        issues.append(
            {
                "item": "未提供目标岗位",
                "reason": "当前无法做定向岗位匹配，本次分析更偏向通用竞争力和职业方向判断。",
                "needed_evidence": "如后续确定岗位，可补充 JD 再做针对性匹配。",
            }
        )
    elif missing_keywords:
        issues.append(
            {
                "item": "JD 关键词缺口",
                "reason": "岗位要求中的部分关键词尚未在简历结构化结果中命中。",
                "needed_evidence": "补充对应项目、职责或成果证据。",
            }
        )
    if analysis_mode == "job_match" and not (job.get("job_title") or ""):
        issues.append(
            {
                "item": "岗位标题缺失",
                "reason": "岗位描述未解析出明确岗位名称。",
                "needed_evidence": "补充标准化 JD 标题或岗位级别。",
            }
        )
    return issues[:3]


def _build_capability_scores(resume, matched_keywords, missing_keywords, analysis_mode="job_match"):
    experiences = resume.get("experiences") or []
    projects = resume.get("projects") or []
    skills = resume.get("skills") or []
    descriptions = []
    for item in experiences:
        descriptions.extend(item.get("description") or [])

    quantified_hits = _count_text_matches(descriptions, r"\d+%|\d+\+?|\d+ms|\d+天|\d+周|\d+月")
    collaboration_hits = _count_text_matches(descriptions, r"协作|协同|沟通|合作|cross-functional|cross functional|跨团队")
    leadership_hits = _count_text_matches(descriptions, r"主导|带领|负责|推动|owner|lead|manage")

    professional = min(95, 52 + len(matched_keywords) * 8 + len(experiences) * 5 + len(projects) * 3)
    learning = min(95, 50 + len(skills) * 4 + len(projects) * 5 + len(resume.get("achievements") or []) * 2)
    execution = min(95, 48 + quantified_hits * 10 + len(experiences) * 4)
    communication = min(95, 45 + collaboration_hits * 10 + leadership_hits * 6)
    if analysis_mode == "job_match":
        gap_penalty = min(25, len(missing_keywords) * 4)
        matching = max(40, min(95, 60 + len(matched_keywords) * 8 - gap_penalty))
    else:
        matching = max(48, min(92, 54 + len(experiences) * 6 + len(projects) * 5 + len(skills) * 2 + quantified_hits * 6))

    return {
        "professional": professional,
        "learning": learning,
        "execution": execution,
        "communication": communication,
        "matching": matching,
    }


def _build_capability_layer(capability_scores, matched_keywords, missing_keywords, analysis_mode="job_match", recommended_directions=None):
    if analysis_mode != "job_match":
        direction_text = "、".join(recommended_directions or []) or "待进一步探索"
        return [
            {
                "dimension": "执行与交付",
                "conclusion": "经历与项目条目足以支撑基础执行力判断。",
                "reasoning": "结合工作经历数量、项目数量与量化表达进行估计。",
                "evidence": "已提取结构化经历与项目条目。",
                "confidence": round(capability_scores.get("execution", 0) / 100, 2),
                "boundary": "基于简历文本推断，未经过面试验证。",
            },
            {
                "dimension": "方向建议",
                "conclusion": f"当前更适合优先探索：{direction_text}。",
                "reasoning": "综合经历标题、项目主题、技能栈和高频动作词进行归纳。",
                "evidence": "来自简历中的角色、项目与技能关键词。",
                "confidence": round(capability_scores.get("matching", 0) / 100, 2),
                "boundary": "未结合具体 JD，因此这是方向性判断，不是定向录用结论。",
            },
            {
                "dimension": "沟通协作",
                "conclusion": f"沟通协作得分 {capability_scores.get('communication', 0)} / 100。",
                "reasoning": "依据协作、沟通、跨团队等表述估算。",
                "evidence": "简历中的协作性动作词与上下文。",
                "confidence": round(capability_scores.get("communication", 0) / 100, 2),
                "boundary": "若缺少行为案例，得分偏保守。",
            },
        ]
    return [
        {
            "dimension": "执行与交付",
            "conclusion": "经历与项目条目足以支撑基础执行力判断。",
            "reasoning": "结合工作经历数量、项目数量与量化表达进行估计。",
            "evidence": "已提取结构化经历与项目条目。",
            "confidence": round(capability_scores.get("execution", 0) / 100, 2),
            "boundary": "基于简历文本推断，未经过面试验证。",
        },
        {
            "dimension": "岗位匹配度",
            "conclusion": f"当前已命中 {len(matched_keywords)} 个岗位关键词，仍有 {len(missing_keywords)} 个待补强。",
            "reasoning": "对结构化简历关键词与结构化 JD 关键词做归一化比对。",
            "evidence": "关键词交集与缺口列表。",
            "confidence": round(capability_scores.get("matching", 0) / 100, 2),
            "boundary": "仅代表文本命中，不等于真实深度。",
        },
        {
            "dimension": "沟通协作",
            "conclusion": f"沟通协作得分 {capability_scores.get('communication', 0)} / 100。",
            "reasoning": "依据协作、沟通、跨团队等表述估算。",
            "evidence": "简历中的协作性动作词与上下文。",
            "confidence": round(capability_scores.get("communication", 0) / 100, 2),
            "boundary": "若缺少行为案例，得分偏保守。",
        },
    ]


def _build_candidate_summary(name, resume, job, matched_keywords, missing_keywords, analysis_mode="job_match", recommended_directions=None):
    experiences = resume.get("experiences") or []
    projects = resume.get("projects") or []
    job_title = job.get("job_title") or "目标岗位"
    current_focus = experiences[0].get("job_title") if experiences else (projects[0].get("project_name") if projects else "综合能力")
    if analysis_mode != "job_match":
        direction_text = "、".join(recommended_directions or []) or current_focus
        return (
            f"{name}，已提取 {len(experiences)} 段经历和 {len(projects)} 个项目，当前优势更偏向 {current_focus}，"
            f"如果你还没确定职业方向，可以优先尝试 {direction_text}。"
        )
    if not missing_keywords:
        return (
            f"{name}，已提取 {len(experiences)} 段经历，当前能力重点是 {current_focus}，"
            f"与“{job_title}”岗位关键词基本对齐。"
        )
    return (
        f"{name}，已提取 {len(experiences)} 段经历，当前能力重点是 {current_focus}，"
        f"与“{job_title}”岗位已命中 {len(matched_keywords)} 个关键词，仍有 {len(missing_keywords)} 个待补强。"
    )

def _inline_markdown(text):
    value = html.escape(str(text or ""))
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    return value


def markdown_to_safe_html(markdown_text):
    lines = str(markdown_text or "").replace("\r\n", "\n").split("\n")
    result = []
    list_items = []
    in_code = False
    code_buffer = []

    def flush_list():
        nonlocal list_items
        if list_items:
            result.append("<ul>" + "".join(f"<li>{_inline_markdown(item)}</li>" for item in list_items) + "</ul>")
            list_items = []

    def flush_code():
        nonlocal code_buffer
        if code_buffer:
            result.append(f"<pre><code>{html.escape(chr(10).join(code_buffer))}</code></pre>")
            code_buffer = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_list()
            if in_code:
                flush_code()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_buffer.append(raw_line)
            continue
        if not stripped:
            flush_list()
            continue
        if stripped.startswith(("- ", "* ")):
            list_items.append(stripped[2:].strip())
            continue

        flush_list()
        if stripped.startswith("### "):
            result.append(f"<h4>{_inline_markdown(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            result.append(f"<h3>{_inline_markdown(stripped[3:])}</h3>")
        elif stripped.startswith("# "):
            result.append(f"<h2>{_inline_markdown(stripped[2:])}</h2>")
        else:
            result.append(f"<p>{_inline_markdown(stripped)}</p>")

    flush_list()
    flush_code()
    if not result:
        return '<div class="career-list-empty">等待生成简历分析结果</div>'
    return "".join(result)

def build_matcher_state(structured_resume, structured_job, analysis_markdown, job_description):
    resume = normalize_structured_resume(structured_resume)
    job = normalize_structured_job(structured_job)
    analysis_mode = "job_match" if _compact_text(job_description) else "resume_review"

    resume_keywords = _collect_resume_keywords(resume)
    recommended_directions = _infer_recommended_directions(resume)
    if analysis_mode == "job_match":
        job_keywords = _collect_job_keywords(job)
        matched_keywords, missing_keywords = _keyword_overlap(resume_keywords, job_keywords)
    else:
        job_keywords = []
        matched_keywords = []
        missing_keywords = []

    capability_scores = _build_capability_scores(resume, matched_keywords, missing_keywords, analysis_mode=analysis_mode)
    name = _derive_candidate_name(resume)
    basics_education = (resume.get("education") or [{}])[0]
    basics_location = (resume.get("personal_data") or {}).get("location") or {}
    job_overview = _build_job_overview(job)

    profile = {
        "confidence": round(
            max(0.55 if analysis_mode == "job_match" else 0.58, capability_scores.get("matching", 0) / 100),
            2,
        ),
        "candidate_summary": _build_candidate_summary(
            name,
            resume,
            job,
            matched_keywords,
            missing_keywords,
            analysis_mode=analysis_mode,
            recommended_directions=recommended_directions,
        ),
        "basics": {
            "name": name,
            "major": basics_education.get("field_of_study") or "",
            "grade": basics_education.get("degree") or "",
            "target_city": basics_location.get("city") or job_overview.get("location") or "",
            "target_direction": job.get("job_title") or (recommended_directions[0] if recommended_directions else ""),
        },
        "roles_detected": _build_roles_detected(resume),
        "leadership_signals": _build_leadership_signals(resume),
        "project_highlights": _build_project_highlights(resume),
        "evidence_spans": _build_evidence_spans(resume),
        "uncertainty_layer": _build_uncertainty_layer(resume, missing_keywords, job, analysis_mode=analysis_mode),
        "capability_scores": capability_scores,
        "capability_layer": _build_capability_layer(
            capability_scores,
            matched_keywords,
            missing_keywords,
            analysis_mode=analysis_mode,
            recommended_directions=recommended_directions,
        ),
        "style_layer": [],
    }

    matcher = {
        "analysis_mode": analysis_mode,
        "resume_keywords": resume_keywords,
        "job_keywords": job_keywords,
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "recommended_directions": recommended_directions,
        "resume_overview": _build_resume_overview(resume),
        "job_overview": job_overview,
        "analysis_markdown": str(analysis_markdown or "").strip(),
    }

    return {
        "analysis_result": str(analysis_markdown or "").strip(),
        "analysis_html": markdown_to_safe_html(analysis_markdown),
        "job_description": _compact_text(job_description),
        "matcher": matcher,
        "profile": profile,
        "structured_resume": resume,
        "structured_job": job,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


__all__ = [
    "Document",
    "FLEXIBLE_MATCH_ANALYSIS_PROMPT",
    "HR_JUDGE_PROMPT",
    "RESUME_REVIEW_PROMPT",
    "STRUCTURED_JOB_PROMPT",
    "STRUCTURED_JOB_SCHEMA",
    "STRUCTURED_RESUME_PROMPT",
    "STRUCTURED_RESUME_SCHEMA",
    "build_matcher_state",
    "build_job_payload_from_text",
    "build_resume_text_payload",
    "markdown_to_safe_html",
    "normalize_structured_job",
    "normalize_structured_resume",
]

