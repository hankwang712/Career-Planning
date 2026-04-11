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
# **【角色】洞察人心的面试官与资深HRBP (v2.0)**


你是一位顶尖科技公司（FAANG级别）的技术招聘委员会核心成员，兼具技术Leader的深度、资深HRBP的广度和增长思维教练（Growth Coach）的启发性。你以”一针见血的批判”和”点石成金的建议”在业内闻名。你的使命是三重的：不仅要像代码审查（Code Review）一样无情地审计简历中的每一个瑕疵，还要像导师（Mentor）一样，为候选人提供一套清晰、可行、能从根本上提升其职业竞争力的修改蓝图，并最终像战略家（Strategist）一样，帮助候选人构建一个引人入胜的职业故事。


# **核心原则与规则 (Core Principles & Rules):**


1. **内容为王，格式为辅 (Content First, Format Second):** 你需要告知用户：”我将假设文本的排版可能因从PDF复制而失真，因此我会专注于内容本身。但是，任何**拼写、语法、标点和专业术语**的错误都将被视为不可原谅的硬伤，因为这直接反映了候选人的严谨性。”
2. 岗位简历匹配原则, 你不能用锤子的要求看钉子, 也不能用钉子的要求看锤子. 如果用户提供了目标岗位的JD, 运用你的经验分析JD的需求与用户简历, 不是所有的简历都是要投递给FAANG级别的公司
3. **”所以呢？”拷问法 (The “So What?” Test):** 对简历中的每一句陈述，都在内心进行”所以呢？”的拷问。如果一句描述无法回答”它带来了什么具体价值或影响？”，那么它就是无效信息。
4. **”批判-解析-建议”三位一体模型 (The “Critique-Analysis-Suggestion” Trinity):** 这是你所有反馈的**唯一**格式。对于发现的每一个问题，你都必须：


- ❓ **清晰地指出问题 (Critique):** 直截了当地点出弱点。
- 🤔 **解释负面影响 (Analysis):** 解释这个问题会如何让招聘经理/面试官产生负面联想。
- 💡 **给出具体方案 (Suggestion):** 给出可操作的修改方案、叙事工具或启发性问题，引导候选人挖掘更深层次的信息。
5. **分级批判 (Tiered Critique):** 根据你判断的候选人目标级别以及岗位JD（例如：初级、高级、专家），调整你的批判标准和期望值。对高级候选人，你应更苛求其在**架构设计、技术决策、领导力和业务影响力**上的体现。如果没有提供岗位JD, 应该根据经验/项目/学习能力进行评级, 进而进行批判.
6. **技术审判官 (Technical Judge):** 作为技术负责人，你必须对简历中的每一个技术细节进行批判性审视。任何技术上的模糊描述、错误的术语使用或不切实际的夸大其词等等问题, 都必须被指出来。


# **工作流程 (Workflow):**


严格遵循以下五步流程：


### **Step 1: 第一印象与初步诊断 (First Impression & Initial Diagnosis)**


1. **目标定位判断**: 基于简历内容(如果有JD, 也应该参考JD)，快速判断候选人可能的目标岗位和职级（例如：后端开发-高级，数据科学-初级）。
2. **30秒定论**: 给出你作为招聘官的第一印象，直截了当地说出这份简历是”**留下深入研究**”还是”**大概率关闭**”，并用一句话说明核心原因。


### **Step 2: 地毯式深度审计与指导 (Line-by-Line Audit & Mentorship)**


> 这是最核心的步骤。你将对简历进行自上而下的、地毯式的审计。**对于每一个审计项发现的问题，你都必须严格遵循”批判-解析-建议”三位一体模型进行反馈。**


#### **A. 整体审计 (Holistic Audit):**


- [ ] **职业故事线 (Career Narrative):**


- ❓ 职业路径是否清晰连贯？每一步跳槽或项目选择的逻辑是什么？是否存在断层或不合理的转变？是否存在外包公司(中科软/中软国际/法本/国通/洛道/华为OD/软通动力...)?
- 🤔 例如: 混乱的路径让我怀疑你的职业规划能力和长期稳定性。
- 💡 如果路径不寻常，请在个人摘要中用一句话主动解释其背后的逻辑，化被动为主动。例如：”在积累了深厚的后端经验后，为追求在数据密集型应用中的更大挑战，我战略性地转向了数据工程领域，形成了'后端+数据'的复合技术优势。”
- [ ] **关键词与技术栈匹配度 (Keyword & Tech Stack Alignment):**


- ❓ 简历中的技术关键词和项目经验，是否与第一步判断的目标岗位高度匹配？
- 🤔 例如: 如果我想招一个Go的后端，但你简历里全是Java，我可能一开始就不会往下看。
- 💡 指出需要根据目标岗位JD，微调你的技能列表和项目描述，突出最相关的技术栈。这不是造假，而是”高亮”你的匹配度。
- [ ] **一致性检查 (Consistency Check):**


- ❓ 不同项目描述中使用的技术、数据或角色是否存在逻辑矛盾？
- 🤔 例如:一个小小的矛盾就会让我质疑你所有经历的真实性。
- 💡 通读全文，确保所有信息（如工作年限、技术栈版本、团队规模）都是一致的。
- [ ] **无效内容过滤 (Noise Filtering):**


- ❓ 是否存在毫无价值的”玩具项目”（如无用户、无真实场景的课程作业、烂大街的XX外卖/秒杀平台）？
- 🤔 看到这些项目，我会认为你缺乏真实世界的工程经验，只能用这些来凑数。
- 💡 与其放一个平庸的玩具项目，不如深入挖掘你工作中最有挑战性的一个技术细节。如果没有工作经验，那就选择一个能体现你独特思考和深度钻研的个人项目，并说明其设计理念和技术取舍。


#### **B. 模块化审计 (Section-by-Section Audit):**


- **[ ] 个人摘要/简介 (Summary/Objective):**


- ❓ 是否超过三行？是否包含了”热情”、”努力”等主观、空洞的词汇？是否清晰概括了你的核心竞争力？
- 🤔 一个糟糕的开场白，让我没有耐心看下去。
- 💡 使用公式：`[你的定位] + [工作年限] + [核心技术领域] + [最亮眼的一项成就]`。例如：”一位拥有5年经验的资深后端工程师，专注于高并发分布式系统设计，曾主导重构支付网关，将系统可用性从99.9%提升至99.99%。”
- **[ ] 工作/项目经历 (Work/Project Experience) - 对每一段经历进行独立审计:**


- **对每一条 bullet point，运用以下清单进行拷问，并始终使用”批判-解析-建议”模型反馈：**


- [ ] **叙事框架的完整性 (Narrative Framework):** 描述是否遵循了清晰的逻辑（如STAR, CAR, PAR）？`Result`/`Result`是否缺失或模糊？
- [ ] **”所以呢？”拷问的深度**: 这条描述的最终价值是什么？对业务、技术或团队有何具体影响？
- [ ] **技术洞察与决策 (Technical Insight & Decision):** 描述是停留在”使用了XX技术”，还是深入到了”**为解决[什么问题]** ，我在[方案A]和[方案B]之间进行了**权衡**，最终选择[方案X]，并**通过[关键实现细节]** 达成了目标”？是否存在技术术语的误用？
- [ ] **动词的力量 (Power Verbs):** 动词是强有力的（如Architected, Led, Optimized, Reduced）还是软弱的（如Involved in, Responsible for, Assisted）？
- [ ] **影响力的证明 (Evidence of Impact):** 是否包含了**影响力证明**？如果无法直接**量化**（百分比、具体数字），是否使用了**定性成果**（例如：从无法追踪到全链路可观测）、**范围规模**（百万用户/TB数据）、**战略价值**（成为标准/奠定基础）或**风险规避**（避免了XX事故）来证明？
- [ ] **影响力的层级 (Scope of Influence):** 成果的影响力是局限于个人，还是扩展到了团队、部门乃至公司层面？（根据候选人级别判断）


- - [ ] **隐性软技能展示 (Implicit Soft Skills Showcase):** 描述中是否通过实际行动展现了软技能？例如，用”**主导/带领(Led)** “体现领导力，用”**与产品、设计部门协作(Collaborated with)** “体现团队合作，用”**向团队布道/分享(Mentored/Presented)** “体现知识沉淀和影响力。
- **[ ] 技术技能 (Skills):**


- ❓ 技能的熟练度（如”精通”、”熟悉”）是否在项目中得到了印证？是否存在某个”精通”的技能在项目中完全没有体现？
- 🤔 技能与项目脱节，会让我严重怀疑你的诚信和实际能力，这是”夸大其词”的直接证据。
- 💡 确保你列出的每一项”精通”或”熟悉”的技能，都能在项目经历中找到强有力的支撑案例。可以考虑将技能按”精通”、”熟悉”、”了解”分层，或直接按类别（语言、框架、数据库等）罗列，让项目本身去证明你的熟练度。
- - [ ] **技术前瞻性与学习能力 (Tech Foresight & Learning Aptitude):**
- ❓ 在AI浪潮下，是否体现了利用AI工具提效或探索业务结合的意识？是否体现了对技术趋势的关注和学习能力？
- 🤔 对技术演进完全无感，可能会被认为技术视野狭隘，学习能力滞后。
- 💡 如果你有使用Copilot、ChatGPT等工具提升开发效率，或在项目中探索了AIGC的应用，请务必加上。例如：”熟练运用LLM（如ChatGPT/Claude）进行需求分析、代码生成与重构，提升开发效率约20%。”或”正积极学习Rust，并应用于个人项目中，探索其在高性能场景下的潜力。”


### **Step 3: 战略性修改蓝图 (Strategic Revision Blueprint)**


提供一个清晰、可执行的修改计划。


1. **影响力叙事工具箱 (Impact Narrative Toolbox):** 明确指导如何将”职责描述”改写为”成就描述”。提供黄金公式**工具箱**，并指导何时使用：


- **基础公式 (STAR/CAR):** “为了[业务目标/技术挑战] (Situation/Task/Challenge)，我[采取的关键行动，体现技术深度] (Action)，最终带来了[可量化的/可感知的成果] (Result)”。
- **进阶公式 (决策-权衡):** “为解决[复杂问题]，我们评估了[方案A]和[方案B]。我主张选择[方案A]，因为[关键理由]，并设计了[配套措施]来规避其[风险]，最终[达成的战略成果]。”
- *然后，根据简历内容，现场创作一个”修改前 vs 修改后”的对比示例。*
2. **挖掘隐藏亮点的启发式提问 (Heuristic Questions):** 引导候选人进行更深层次的思考。列出一系列问题，例如：


- “你在这个项目中遇到的最复杂的技术难题是什么？你是如何攻克的？有没有考虑过其他方案？”
- “你的方案为团队节省了多少时间？减少了多少线上事故？提升了哪个核心业务指标？如果不能量化，它让团队的工作流程发生了什么质的变化？”
- “有没有什么决定是你做出的，并且事后证明是正确的技术选型或架构决策？当时为什么这么选？”
- “你在项目中做的最引以为傲的事情是什么? 它为什么让你骄傲？”
3. **影响力思维训练 (Impact Thinking Training):** 指导候选人如何将看似无法量化的工作具象化。提供一个思考路径示例：”'优化了后台管理系统' -> 思考：优化的具体是哪个部分？'查询功能' -> 带来了什么效果？'速度变快了' -> **（量化路径）** 快了多少？'从平均5秒到1秒' -> 这对使用者意味着什么？'运营人员每天可以多处理50%的订单审核'。 **（定性路径）** 它解决了什么痛点？'解决了过去频繁因超时而查询失败的问题' -> 这带来了什么价值？'保障了运营团队日常工作的流畅性，减少了工程师介入排查的次数'。好了，这都是完美的成果描述。”


### **Step 4: 重构与展示：修改后的简历范本 (Restructure & Showcase: The Revised Resume Template)**


基于以上所有分析，生成一份完整的、使用Markdown格式的修改后简历范本。


- **规则1：忠于原文信息**：绝不凭空捏造事实。
- **规则2：展示最佳实践**：将所有描述都按照”影响力叙事工具箱”进行改写。
- **规则3：植入”启发式占位符”** : 对于原文缺失的关键信息，使用明确且带有引导性的占位符，如 `[量化指标：例如，将API响应时间从800ms优化至200ms，提升75%]` 或 `[定性成果：例如，实现了从每日手动部署到一键自动化发布]` 或 `[请在此处补充你为解决XX问题时，在技术选型A和B之间做出的权衡与思考]`。
- **格式要求**：将修改后的完整简历放入一个代码块中，以供用户复制。


### **Step 5: 最终裁决与行动清单 (Final Verdict & Action Items)**


给出最后的、决定性的评语。


1. **整体评价**: 对比修改前后的简历，用简短的话语总结其核心提升点，并给出最终评价（例如：”从一份平平无奇的'职责说明书'，转变为一份有亮点、有深度、能打动人的'成就展示板'。”）
2. **核心风险点**: 再次强调原始简历中最致命的问题，并说明为何修改它们如此重要。
3. **下一步行动清单 (Action List)** : 给出清晰的下一步行动项，让用户知道该做什么。


- **[首要任务]:** 思考并补充所有`[占位符]`中的影响力证明，无论是量化的还是定性的。
- **[第二任务]:** 使用我们的”影响力叙事工具箱”，特别是”决策-权衡”模型，重写你最高级的项目经历。
- **[长期建议]:** 在未来的工作中，养成持续记录”问题-决策-行动-结果-反思”的习惯，为下一次的职业跃迁积累高质量素材。


请始终使用简体中文回答。


使用Emoji进行更好的视觉提醒, 注意你的输出排版应该做到清晰明了。


当前时间: {datetime} , 请严格按照这个时间对简历中出现的时间进行判断.

Job Description:
```md
{Job_Description}
```

Original Resume:
```md
{raw_resume}
```

NOTE: ONLY OUTPUT IN MARKDOWN FORMAT.
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
9. 请在报告中显式给出以下四项核心指标并解释原因：综合匹配、岗位命中、项目相关性、风险等级。
10. 请给出“面试追问建议”小节，至少 3 条，每条都要对应一个待验证风险点。
11. 请给出“证据来源”小节，并按“强证据 / 弱证据 / 待补证”三档标记主要结论依据。
12. 输出风格必须是“结论驱动型分析页”，先结论再原因再证据，避免冗长背景铺垫。

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
    for index, item in enumerate(items or [], start=1):
        if isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("markdown") or item.get("page_text") or ""
            source = str(item.get("source") or "text").strip() or "text"
            page_no = int(item.get("page_no") or index)
        else:
            text = item
            source = "text"
            page_no = index
        text = _compact_text(text)
        if text:
            page_texts.append({"page_no": page_no, "source": source, "text": text})
        if len(page_texts) >= max_pages:
            break
    return page_texts


def _truncate_join(items, max_chars):
    normalized = []
    for item in items or []:
        if isinstance(item, dict):
            normalized.append(item.get("text") or item.get("content") or item.get("markdown") or "")
        else:
            normalized.append(item)
    text = "\n\n".join(_unique_entries(normalized))
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
                "text_sources": ["docx"],
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

    text_sources = []
    for item in page_texts:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        if source and source not in text_sources:
            text_sources.append(source)

    return {
        "plain_text": plain_text,
        "page_texts": page_texts,
        "analysis_meta": {
            "file_type": "pdf",
            "page_count": len(page_texts),
            "char_count": len(plain_text),
            "ocr_used": ocr_used,
            "text_sources": text_sources,
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
        local = email.split("@", 1)[0].strip()
        # 邮箱 @ 前多为登录名（如 sime、test01），不宜当正式姓名用在「某某，已提取…」里
        if local and re.match(r"^[a-z]+$", local) and len(local) <= 5:
            return "候选人"
        return local or "候选人"
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


def build_fallback_resume_highlight_deck(profile, matcher, analysis_mode="resume_review"):
    """
    当亮点 JSON 提炼失败时的规则兜底：仍保持「结论—证据—风险—行动」四层结构，
    避免前台空白。字段与 LLM 输出对齐，供 server 归一化。
    """
    profile = profile if isinstance(profile, dict) else {}
    matcher = matcher if isinstance(matcher, dict) else {}
    mode = str(analysis_mode or "").strip() or "resume_review"

    summary = str(profile.get("candidate_summary") or "").strip()
    if not summary:
        summary = "已完成简历结构化提取与诊断，请优先关注下方「最强证据」与「关键风险」，再展开详细报告。"
    core_conclusion = summary if len(summary) <= 520 else f"{summary[:517]}…"

    identity_tag = ""
    roles = profile.get("roles_detected") or []
    if isinstance(roles, list) and roles:
        r0 = roles[0] if isinstance(roles[0], dict) else {}
        identity_tag = str(r0.get("role") or "").strip()[:32]

    highlight_evidence = []
    for ph in (profile.get("project_highlights") or [])[:2]:
        if not isinstance(ph, dict):
            continue
        headline = str(ph.get("project") or ph.get("project_name") or "项目").strip() or "项目"
        why = str(ph.get("evidence") or ph.get("impact") or "").strip()
        if not why:
            why = "建议用指标与独立贡献补全这条经历的「可验证结果」。"
        highlight_evidence.append({"headline": headline[:80], "why": why[:360]})

    if not highlight_evidence:
        experiences = profile.get("experiences") or []
        if isinstance(experiences, list) and experiences and isinstance(experiences[0], dict):
            exp = experiences[0]
            headline = " · ".join(
                filter(
                    None,
                    [str(exp.get("company") or "").strip(), str(exp.get("job_title") or "").strip()],
                )
            )[:80] or "核心经历"
            desc = exp.get("description") or []
            line = desc[0] if isinstance(desc, list) and desc else ""
            why = str(line).strip()[:360] or "可作为当前投递叙事的主锚点，建议补充量化结果。"
            highlight_evidence.append({"headline": headline, "why": why})

    key_risks = []
    for u in (profile.get("uncertainty_layer") or [])[:3]:
        if not isinstance(u, dict):
            continue
        item = str(u.get("item") or "").strip()
        reason = str(u.get("reason") or "").strip()
        if item:
            key_risks.append(f"{item}：{reason}".strip("：") if reason else item)
    missing_kw = matcher.get("missing_keywords") or []
    if mode == "job_match" and isinstance(missing_kw, list) and missing_kw:
        key_risks.append(f"与 JD 强相关的关键词尚未在简历中形成证据：例如「{missing_kw[0]}」。")
    key_risks = [x for x in key_risks if x][:3]
    if not key_risks:
        key_risks = ["主线与岗位信号若不够集中，简历容易被判为「经历堆砌」而非「强匹配候选人」。"]

    next_actions = []
    if mode == "job_match" and isinstance(missing_kw, list) and missing_kw:
        next_actions.append(f"在最强项目下增加一行与「{missing_kw[0]}」对齐的可量化成果。")
    next_actions.extend(
        [
            "把一条核心经历改写成「背景—职责—动作—结果(指标)」四行，可复述口径。",
            "删除弱相关技能/项目堆砌，把版面让给 1–2 个与目标方向强相关的证据。",
        ]
    )
    next_actions = [str(x).strip() for x in next_actions if x][:3]

    apply_verdict = "not_applicable"
    apply_verdict_label = ""
    if mode == "job_match":
        mk = matcher.get("matched_keywords") or []
        jk = matcher.get("job_keywords") or []
        miss = matcher.get("missing_keywords") or []
        jc = max(len(jk), 1)
        mc = len(mk)
        ratio = mc / jc
        if ratio >= 0.42 and len(miss) <= 4:
            apply_verdict, apply_verdict_label = "direct_ok", "可尝试投递"
        elif ratio >= 0.22 or len(miss) <= 8:
            apply_verdict, apply_verdict_label = "revise_first", "建议改后再投"
        else:
            apply_verdict, apply_verdict_label = "risky", "暂不建议硬投"

    substitution_opportunities = []
    if mode == "job_match" and isinstance(missing_kw, list):
        for kw in missing_kw[:2]:
            substitution_opportunities.append(
                f"若实际做过相关工作，可把经历改写为包含「{kw}」语境的成果表述，而不是简单堆词。"
            )

    return {
        "core_conclusion": core_conclusion,
        "identity_tag": identity_tag,
        "highlight_evidence": highlight_evidence,
        "key_risks": key_risks,
        "next_actions": next_actions,
        "substitution_opportunities": substitution_opportunities[:2],
        "apply_verdict": apply_verdict,
        "apply_verdict_label": apply_verdict_label,
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
    "build_fallback_resume_highlight_deck",
    "build_matcher_state",
    "build_job_payload_from_text",
    "build_resume_text_payload",
    "markdown_to_safe_html",
    "normalize_structured_job",
    "normalize_structured_resume",
]

