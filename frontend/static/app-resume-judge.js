// 简历诊断：章节解析与评审看板
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function resumeMarkdownSections(raw) {
  const lines = String(raw || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let listType = "";
  let inCodeBlock = false;
  let codeBlockLines = [];

  function flushParagraph() {
    if (!paragraphLines.length) return;
    blocks.push({
      type: "paragraph",
      html: resumeInlineMarkupHtml(paragraphLines.join(" "))
    });
    paragraphLines = [];
  }

  function flushList() {
    if (!listItems.length) return;
    blocks.push({
      type: "list",
      listType,
      items: [...listItems]
    });
    listItems = [];
    listType = "";
  }

  lines.forEach((rawLine) => {
    const line = String(rawLine || "").trim();
    if (inCodeBlock) {
      if (/^```/.test(line)) {
        inCodeBlock = false;
        blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
        codeBlockLines = [];
      } else {
        codeBlockLines.push(rawLine);
      }
      return;
    }
    if (!line) {
      flushParagraph();
      flushList();
      return;
    }
    if (/^```/.test(line)) {
      flushParagraph();
      flushList();
      inCodeBlock = true;
      codeBlockLines = [];
      return;
    }
    if (/^-{3,}$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "divider" });
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        html: resumeInlineMarkupHtml(heading[2])
      });
      return;
    }
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(resumeInlineMarkupHtml(ordered[1]));
      return;
    }
    const checklist = line.match(/^[-*]\s+\[( |x)\]\s+(.+)$/i);
    if (checklist) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      const checked = checklist[1].toLowerCase() === "x";
      listItems.push(`<span class="resume-checklist-icon">${checked ? "✅" : "⬜"}</span> ${resumeInlineMarkupHtml(checklist[2])}`);
      return;
    }
    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(resumeInlineMarkupHtml(unordered[1]));
      return;
    }
    flushList();
    paragraphLines.push(line);
  });

  if (inCodeBlock && codeBlockLines.length) {
    blocks.push({ type: "codeblock", code: codeBlockLines.join("\n") });
  }

  flushParagraph();
  flushList();

  const sectionParts = [];
  let currentSection = null;

  function pushCurrentSection() {
    if (!currentSection) return;
    if (!currentSection.intro && !currentSection.content.length) return;
    sectionParts.push(currentSection);
  }

  blocks.forEach((block) => {
    if (block.type === "heading" && block.level <= 2) {
      pushCurrentSection();
      currentSection = {
        title: block.html,
        intro: "",
        content: []
      };
      return;
    }
    if (!currentSection) {
      currentSection = {
        title: "分析内容",
        intro: "",
        content: []
      };
    }
    if (block.type === "paragraph" && !currentSection.intro) {
      currentSection.intro = block.html;
      return;
    }
    currentSection.content.push(block);
  });

  pushCurrentSection();
  return sectionParts;
}

function resumeSectionsFromState(state) {
  const markdown = String(state?.analysis_result || "").trim();
  if (markdown) return resumeMarkdownSections(markdown);
  const htmlText = resumeAnalysisHtmlToText(state?.analysis_html);
  if (htmlText) return resumeMarkdownSections(htmlText);
  return [];
}

function resumeFindSectionByKeywords(sections, keywords, fallbackIndex = 0) {
  const patterns = (keywords || []).map((item) => String(item || "").toLowerCase()).filter(Boolean);
  const matched = (sections || []).find((section) => {
    const title = resumePlainText(section?.title || "").toLowerCase();
    return patterns.some((pattern) => title.includes(pattern));
  });
  if (matched) return matched;
  return sections?.[fallbackIndex] || null;
}

function resumeFindGroupByKeywords(section, keywords) {
  const patterns = (keywords || []).map((item) => String(item || "").toLowerCase()).filter(Boolean);
  const groups = resumeReportBlocksPartition(section?.content || []).groups;
  return groups.find((group) => {
    const title = resumePlainText(group?.title || "").toLowerCase();
    return patterns.some((pattern) => title.includes(pattern));
  }) || null;
}

function resumeFlattenBlocks(blocks) {
  const items = [];
  (blocks || []).forEach((block) => {
    if (block.type === "paragraph") {
      const text = resumePlainText(block.html);
      if (text) items.push(text);
      return;
    }
    if (block.type === "list") {
      block.items.forEach((item) => {
        const text = resumePlainText(item);
        if (text) items.push(text);
      });
      return;
    }
    if (block.type === "codeblock") {
      const text = String(block.code || "").trim();
      if (text) items.push(text);
    }
  });
  return items;
}

function resumeJudgeVerdictPayload(state, profile, matcher, analysisMode, recommendedDirections, conclusionItems) {
  const overall = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  let tone = "brand";
  let icon = "→";
  let title = "建议进入下一轮";
  if (overall >= 86) {
    tone = "success";
    icon = "✓";
    title = "建议优先推进";
  } else if (overall < 70) {
    tone = "danger";
    icon = "!";
    title = "建议补强后再投递";
  }
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  return {
    tone,
    icon,
    title,
    role: overview.headline || profile?.basics?.target_direction || "待识别方向",
    reason: conclusionItems[1] || profile?.candidate_summary || "系统已根据当前简历生成结构化判断。",
    summary: conclusionItems[0] || profile?.candidate_summary || "等待生成总结。"
  };
}

function resumeJudgeQuickStatItems(state, profile, matcher, analysisMode, recommendedDirections) {
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  return [
    ["综合评分", `${resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections)}%`],
    ["识别角色", overview.headline || "待识别"],
    ["经历段数", `${Number(overview.experience_count || 0)} 段`],
    ["项目数量", `${Number(overview.project_count || 0)} 个`],
    ["技能覆盖", `${Number(overview.skill_count || 0)} 项`]
  ];
}

function resumeJudgeRiskItems(detailSection, matcher, profile) {
  const riskGroup = resumeFindGroupByKeywords(detailSection, ["风险", "缺口", "risk", "gap"]);
  const groupItems = resumeFlattenBlocks(riskGroup?.blocks || []);
  if (groupItems.length) return groupItems.slice(0, 4);
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  if (uncertainty.length) {
    return uncertainty.slice(0, 4).map((item) => String(item?.reason || item?.item || "").trim()).filter(Boolean);
  }
  const missing = previewTagValues(matcher?.missing_keywords || [], 4);
  if (missing.length) {
    return missing.map((item) => `缺少与目标岗位强相关的关键词：${item}`);
  }
  return ["当前结果里没有结构化风险项，建议重点补充业务背景、量化结果和个人独立贡献。"];
}

function resumeJudgeModuleAuditItems(state, profile, matcher) {
  const structured = state?.structured_resume && typeof state.structured_resume === "object" ? state.structured_resume : {};
  const education = Array.isArray(structured.education) ? structured.education : [];
  const experiences = Array.isArray(structured.experiences) ? structured.experiences : [];
  const projects = Array.isArray(structured.projects) ? structured.projects : [];
  const skills = Array.isArray(structured.skills) ? structured.skills : [];
  const research = Array.isArray(structured.research_work) ? structured.research_work : [];

  const educationDetails = education.map((item) => {
    const parts = [resumePlainText(item.institution), resumePlainText(item.field_of_study), resumePlainText(item.degree)].filter(Boolean);
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    return {
      main: parts.join(" · "),
      meta: [dateRange, item.grade ? resumePlainText(item.grade) : ""].filter(Boolean).join(" | "),
      desc: []
    };
  });

  const experienceDetails = experiences.map((item) => {
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    const descItems = Array.isArray(item.description) ? item.description : [];
    return {
      main: [resumePlainText(item.company), resumePlainText(item.job_title)].filter(Boolean).join(" | "),
      meta: dateRange,
      desc: descItems.slice(0, 2).map((d) => shortenResumeText(resumePlainText(d), 90)).filter(Boolean)
    };
  });

  const projectDetails = projects.map((item) => {
    const dateRange = [resumePlainText(item.start_date), resumePlainText(item.end_date)].filter(Boolean).join(" - ");
    return {
      main: resumePlainText(item.project_name),
      meta: dateRange,
      desc: item.description ? [shortenResumeText(resumePlainText(item.description), 90)] : []
    };
  });

  const skillsByCategory = skills.reduce((acc, item) => {
    const cat = resumePlainText(item.category || "其他");
    if (!acc[cat]) acc[cat] = [];
    const skillName = resumePlainText(item.skill_name);
    if (skillName) acc[cat].push(skillName);
    return acc;
  }, {});
  const skillDetails = Object.entries(skillsByCategory).map(([cat, items]) => ({
    main: cat,
    meta: items.join("、"),
    desc: []
  }));

  const items = [
    {
      title: "教育背景",
      text: education.length
        ? `已识别 ${education.length} 段教育信息。学术项较强，建议把排名、绩点、论文与专利放在更靠前的位置。`
        : "当前没有识别到清晰教育信息，建议补齐学校、专业、时间与核心成绩。",
      details: educationDetails
    },
    {
      title: "实习经历",
      text: experiences.length
        ? `已识别 ${experiences.length} 段实习/工作经历。当前最大的短板通常在于业务背景、个人贡献和结果量化表达不足。`
        : "当前没有识别到稳定的实习或工作经历模块，建议至少补一段真实项目或实习经历。",
      details: experienceDetails
    },
    {
      title: "项目经历",
      text: projects.length
        ? `已识别 ${projects.length} 个项目。项目题材足够强，但需要再向"业务价值、技术决策、可验证结果"三件事收口。`
        : "项目经历过少，难以支撑岗位判断，建议补齐 2 到 3 个高质量项目。",
      details: projectDetails
    },
    {
      title: "技能模块",
      text: skills.length
        ? `已识别 ${skills.length} 项技能。建议按"语言 / 框架 / 技术方向 / 工具"分组，而不是一行平铺。`
        : '技能项过少，建议拆出独立"专业技能"模块并做分组呈现。',
      details: skillDetails
    }
  ];

  if (research.length) {
    const researchDetails = research.map((item) => ({
      main: resumePlainText(item.title),
      meta: resumePlainText(item.publication || item.description || ""),
      desc: []
    }));
    items.push({
      title: "论文 / 专利",
      text: `已识别 ${research.length} 项学术成果。学术背景是竞争优势，建议在简历顶部或教育模块后单独列出。`,
      details: researchDetails
    });
  }

  return items;
}

function resumeJudgeEvidenceAuditItems(profile) {
  const evidence = Array.isArray(profile?.evidence_spans) ? profile.evidence_spans : [];
  if (!evidence.length) {
    return [{
      quote: "等待生成证据片段",
      note: "分析完成后，这里会引用简历原文并指出每条描述还缺什么。",
      tags: []
    }];
  }
  return evidence.map((item) => {
    const quote = String(item?.quote || "").trim();
    const tags = [];
    const notes = [];
    if (!/\d/.test(quote)) { notes.push("建议补充量化结果"); tags.push("缺数据"); }
    if (/负责|协助|参与/.test(quote)) { notes.push("动词偏弱，建议改成主导 / 设计 / 实现"); tags.push("动词弱"); }
    if (!notes.length) { notes.push("建议补充业务背景或边界条件"); tags.push("缺背景"); }
    return {
      quote,
      note: notes.join("；"),
      tags
    };
  });
}

function resumeJudgeQuestionItems(state, profile, riskItems) {
  const questions = [];
  const highlights = Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 2) : [];
  highlights.forEach((item) => {
    const project = String(item?.project || "").trim();
    if (project) {
      questions.push(`围绕“${project}”，准备一句 STAR 表达：问题背景、你的动作、可验证结果分别是什么？`);
    }
  });
  if (riskItems[0]) questions.push(`如果面试官追问“${riskItems[0]}”，你准备用哪组数据回应？`);
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  uncertainty.slice(0, 2).forEach((item) => {
    const title = String(item?.item || "").trim();
    if (title) questions.push(`针对“${title}”，你还能补充哪些证据来降低面试官的不确定感？`);
  });
  return questions.slice(0, 6);
}

function resumeJudgeQuantTips() {
  return [
    ["性能类", "把“优化性能”改成“响应时间从 Xms 降到 Yms，P99 下降 Z%”。"],
    ["规模类", "把“大量数据”改成“日均处理 N 条记录 / 支撑 N 次请求”。"],
    ["效率类", "把“提升开发效率”改成“发布时间从 X 小时缩短到 Y 分钟”。"],
    ["质量类", "把“系统更稳定”改成“MTTR 降低 X%，可用性提升到 Y%”。"]
  ];
}

function resumeJudgeTemplateText(state, profile, matcher) {
  const structured = state?.structured_resume && typeof state.structured_resume === "object" ? state.structured_resume : {};
  const personal = structured.personal_data && typeof structured.personal_data === "object" ? structured.personal_data : {};
  const name = [personal.first_name, personal.last_name].filter(Boolean).join(" ") || profile?.basics?.name || matcher?.resume_overview?.candidate_name || "候选人";
  const contacts = [personal.phone, personal.email, personal.linkedin, personal.portfolio].filter(Boolean);
  const lines = [name];
  if (contacts.length) lines.push(contacts.join(" | "));
  if (profile?.candidate_summary) {
    lines.push("", "【个人摘要】", resumePlainText(profile.candidate_summary));
  }
  const education = Array.isArray(structured.education) ? structured.education : [];
  if (education.length) {
    lines.push("", "【教育背景】");
    education.slice(0, 2).forEach((item) => {
      lines.push(`${resumePlainText(item.institution)} | ${resumePlainText(item.field_of_study)} | ${resumePlainText(item.degree)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      if (item.grade) lines.push(`- ${resumePlainText(item.grade)}`);
      if (item.description) lines.push(`- ${shortenResumeText(resumePlainText(item.description), 180)}`);
    });
  }
  const experiences = Array.isArray(structured.experiences) ? structured.experiences : [];
  if (experiences.length) {
    lines.push("", "【实习 / 工作经历】");
    experiences.slice(0, 3).forEach((item) => {
      lines.push(`${resumePlainText(item.company)} | ${resumePlainText(item.job_title)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      (Array.isArray(item.description) ? item.description : []).slice(0, 3).forEach((desc) => {
        lines.push(`- ${shortenResumeText(resumePlainText(desc), 160)}`);
      });
    });
  }
  const projects = Array.isArray(structured.projects) ? structured.projects : [];
  if (projects.length) {
    lines.push("", "【项目经历】");
    projects.slice(0, 3).forEach((item) => {
      lines.push(`${resumePlainText(item.project_name)} | ${resumePlainText(item.start_date)} - ${resumePlainText(item.end_date)}`);
      lines.push(`- ${shortenResumeText(resumePlainText(item.description), 180)}`);
    });
  }
  const research = Array.isArray(structured.research_work) ? structured.research_work : [];
  if (research.length) {
    lines.push("", "【论文 / 专利】");
    research.slice(0, 4).forEach((item) => {
      lines.push(`- ${resumePlainText(item.title)} | ${resumePlainText(item.publication || item.description)}`);
    });
  }
  const skills = Array.isArray(structured.skills) ? structured.skills : [];
  if (skills.length) {
    const byCategory = skills.reduce((acc, item) => {
      const category = resumePlainText(item.category || "技能");
      if (!acc[category]) acc[category] = [];
      acc[category].push(resumePlainText(item.skill_name));
      return acc;
    }, {});
    lines.push("", "【专业技能】");
    Object.entries(byCategory).forEach(([category, items]) => {
      lines.push(`${category}：${items.filter(Boolean).join("、")}`);
    });
  }
  const achievements = Array.isArray(structured.achievements) ? structured.achievements : [];
  if (achievements.length) {
    lines.push("", "【荣誉与获奖】");
    achievements.slice(0, 6).forEach((item) => lines.push(`- ${resumePlainText(item)}`));
  }
  return lines.join("\n");
}

function resumeJudgeComparisonItems(profile, matcher, analysisMode, recommendedDirections) {
  return [
    ["综合评分", resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections), 88],
    ["岗位匹配", resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections), 85],
    ["故事线", resumeJudgeStoryScore(profile, matcher), 82],
    ["技术深度", resumeJudgeTechScore(profile), 84],
    ["格式规范", resumeJudgeFormatScore(profile, matcher), 80]
  ];
}

function resumeJudgeDecisionFlowHtml(deck, matcher, profile, analysisMode, verdict, riskItems, recommendedDirections) {
  const core = String(deck?.core_conclusion || "").trim();
  const idTag = String(deck?.identity_tag || "").trim();
  const evid = Array.isArray(deck?.highlight_evidence) ? deck.highlight_evidence : [];
  const keyRisks = Array.isArray(deck?.key_risks) ? deck.key_risks : [];
  const acts = Array.isArray(deck?.next_actions) ? deck.next_actions : [];
  const directions = (recommendedDirections || []).filter(Boolean);
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const resumeOverview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};

  const verdictCode = deck?.apply_verdict || "not_applicable";
  const vLabel = String(deck?.apply_verdict_label || "").trim();
  const showVerdict = analysisMode === "job_match" && verdictCode !== "not_applicable" && vLabel;
  const verdictClass = verdictCode === "direct_ok" ? "success" : (verdictCode === "risky" ? "danger" : "warn");

  const concl1 = idTag || (core ? core.split(/[。！？\n]/)[0].trim() : "") || shortenResumeText(String(verdict.summary || profile?.candidate_summary || ""), 80) || "画像与主线尚在归纳中";
  const expl1 = shortenResumeText((idTag && core) ? core : (core || String(verdict.reason || verdict.summary || "").trim() || "—"), 360);

  const ev0 = evid[0] || {};
  const concl2 = String(ev0.headline || ev0.title || "").trim() || "可量化成果与独立贡献";
  const expl2 = String(ev0.why || ev0.reason || "").trim() || "请从项目中提炼可复述指标、边界条件与个人职责。";

  const r0 = String(keyRisks[0] || riskItems[0] || "").trim();
  const concl3 = r0 ? shortenResumeText(r0, 72) : "风险点尚未完全结构化";
  const expl3 = String(keyRisks[1] || riskItems[1] || "").trim() || "建议把相互打架的信号收束到 1～2 条叙事主线，并补齐证据链。";

  let concl4;
  let expl4;
  if (analysisMode === "job_match") {
    concl4 = vLabel || verdict.title || "投递策略";
    const jobLine = jobOverview.job_title || resumeOverview.headline || "目标岗位";
    expl4 = `${jobLine} · ${shortenResumeText(String(verdict.summary || verdict.reason || ""), 200) || "结合上方证据与 JD 贴合度做投递决策。"}`;
  } else {
    concl4 = directions.slice(0, 2).join(" · ") || "方向建议生成中";
    expl4 = directions.length > 1 ? "多方向并存时，先收敛到 1～2 条主线，再扩投递面。" : "把经历顺序与技能分组对齐到目标叙事。";
  }

  const concl5 = acts[0] ? shortenResumeText(acts[0], 96) : "下一步优先级";
  const expl5 = acts.length > 1
    ? acts.slice(1, 4).map((a) => shortenResumeText(a, 140)).join("；")
    : (acts[0] ? "把这一条做完，再扩展到其余模块。" : "可先完成一条「背景—动作—结果」强叙事，再处理篇幅与格式。");

  const steps = [
    { label: "你的当前状态", conclusion: concl1, explain: expl1 },
    { label: "你最强的优势", conclusion: concl2, explain: expl2 },
    { label: "最可能的问题", conclusion: concl3, explain: expl3 },
    { label: analysisMode === "job_match" ? "适合方向 / 投递结论" : "更适合的发力方向", conclusion: concl4, explain: expl4 },
    { label: "下一步应该做什么", conclusion: concl5, explain: expl5 }
  ];

  return `
    <div class="resume-df-flow">
      ${showVerdict ? `<div class="resume-df-verdict"><span class="resume-hj-verdict-chip ${verdictClass}">${escHtml(vLabel)}</span></div>` : ""}
      ${steps.map((s, i) => `
        <div class="resume-df-step">
          <div class="resume-df-step-meta">
            <span class="resume-df-step-n">${String(i + 1).padStart(2, "0")}</span>
            <span class="resume-df-step-label">${escHtml(s.label)}</span>
          </div>
          <p class="resume-df-step-conclusion">${escHtml(s.conclusion)}</p>
          <p class="resume-df-step-explain">${escHtml(s.explain)}</p>
        </div>
        ${i < steps.length - 1 ? `<div class="resume-df-arrow" aria-hidden="true"><span>↓</span></div>` : ""}
      `).join("")}
    </div>
  `;
}

function resumeJudgeEvidenceRailHtml(deck, profile, highlightLines) {
  const evid = Array.isArray(deck?.highlight_evidence) ? deck.highlight_evidence.slice(0, 5) : [];
  const rows = [];
  if (evid.length) {
    evid.forEach((e) => rows.push({
      title: String(e?.headline || e?.title || "亮点").trim() || "亮点",
      sub: String(e?.why || e?.reason || "").trim()
    }));
  } else if ((highlightLines || []).length) {
    (highlightLines || []).slice(0, 4).forEach((h) => {
      if (h) rows.push({ title: "优势信号", sub: h });
    });
  } else {
    (Array.isArray(profile?.project_highlights) ? profile.project_highlights : []).slice(0, 4).forEach((p) => {
      rows.push({
        title: String(p?.project || "项目").trim() || "项目",
        sub: String(p?.highlight || p?.evidence || p?.impact || "").trim()
      });
    });
  }
  if (!rows.length) {
    rows.push({ title: "证据待提炼", sub: "分析完成后会把项目与指标映射到可复述证据。" });
  }
  return `
    <div class="resume-df-rail">
      ${rows.map((r, i) => `
        <div class="resume-df-rail-row">
          <span class="resume-df-rail-idx">${String(i + 1).padStart(2, "0")}</span>
          <div class="resume-df-rail-body">
            <p class="resume-df-rail-title">${escHtml(r.title)}</p>
            <p class="resume-df-rail-sub">${escHtml(shortenResumeText(r.sub, 240))}</p>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function resumeJudgeGapCompareHtml(analysisMode, profile, matcher, recommendedDirections, matchScore) {
  if (analysisMode !== "job_match") return "";
  const resumeOv = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const jobOv = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const mk = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jk = mk + (Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords.length : 0);
  const miss = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const gapSummary = miss.length
    ? `最关键差距：与岗位强相关的「${miss.slice(0, 2).join("、")}」在简历中证据仍偏弱。`
    : (matchScore == null ? "技能要求尚待核实。" : matchScore < 60 ? "关键词命中一般，建议把经历写法向 JD 用语靠拢。" : "关键词层面暂无显著缺口，仍建议核对业务结果表达。");

  const rows = [
    [resumeOv.headline || profile?.basics?.target_direction || "经历与项目呈现", jobOv.job_title || "目标岗位"],
    [`结构化证据：约 ${resumeOv.skill_count || 0} 项技能 · ${resumeOv.project_count || 0} 个项目`, jk ? `已识别岗位技能 ${jk} 项（简历体现 ${mk}）` : "JD 关键词解析偏少"],
    [(recommendedDirections[0] || "叙事主线"), miss[0] ? `岗位强调：${miss[0]}` : "核心要求已有初步对应"]
  ];

  return `
    <section class="resume-df-section resume-df-gap-wrap">
      <p class="resume-df-section-kicker">对比视图 · 你现在 vs 目标要求</p>
      <div class="resume-df-gap-table" role="group" aria-label="简历与 JD 对比">
        <div class="resume-df-gap-head">
          <span>简历信号</span><span>目标 / JD</span>
        </div>
        ${rows.map(([a, b]) => `
          <div class="resume-df-gap-row">
            <div class="resume-df-gap-cell">${escHtml(a)}</div>
            <div class="resume-df-gap-cell accent">${escHtml(b)}</div>
          </div>
        `).join("")}
      </div>
      <p class="resume-df-gap-foot">${escHtml(gapSummary)}</p>
    </section>
  `;
}

function resumeJudgeRiskRadarHtml(profile, matcher, analysisMode, deck, matchScore, recommendedDirections) {
  const missing = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const unknown = matcher?.skill_alignment?.unmatched_job_terms || [];
  return `<div class="resume-risk-bars">
    <p class="resume-risk-bars-legend">未体现不等于不会；以下项目需要补充成果或核实，不能换算为风险概率。</p>
    <p>待补技能证据：${escHtml(missing.join("、") || "已识别技能暂无未体现项")}</p>
    <p>尚未对齐的岗位短语：${escHtml(unknown.join("、") || "暂无")}</p>
    <p>执行力、沟通力及项目深度：待验证。</p>
  </div>`;
}

function resumeJudgeExactEmptyDashboardHtml(state) {
  const hasFile = Boolean(state?.file_name);
  const copy = hasFile
    ? "简历已上传，开始匹配后即可查看诊断结论与建议。"
    : "先上传 PDF 或 DOCX，然后开始匹配即可。";
  const ph = [
    ["你的当前状态", "—"],
    ["你最强的优势", "—"],
    ["最可能的问题", "—"],
    ["适合方向 / 投递结论", "—"],
    ["下一步应该做什么", "—"]
  ];
  return `
    <div id="resumeJudgeShell" class="resume-hj-shell">
      <section class="resume-hj-header-card">
        <div class="resume-hj-header-top">
          <div>
            <div class="resume-hj-badge-row">
              <span class="resume-hj-badge">诊断报告</span>
              <span class="resume-hj-mode">待生成</span>
            </div>
            <h3 class="resume-hj-title">简历诊断报告</h3>
            <p class="resume-hj-subtitle">${escHtml(copy)}</p>
          </div>
          <div class="resume-hj-header-actions">
            <button type="button" class="resume-hj-action-btn primary" onclick="pickResumeFile()">上传简历</button>
            <button type="button" class="resume-hj-action-btn" onclick="analyzeResumeMatch()" ${hasFile ? "" : "disabled"}>开始匹配</button>
          </div>
        </div>
        <div class="resume-hj-score-grid">
          ${[
            { label: "综合匹配", tone: "primary", desc: "需要成果与任务验证" },
            { label: "技能证据覆盖", tone: "warn", desc: "已识别技能的文本证据比例" },
            { label: "项目相关性", tone: "brand", desc: "项目与目标方向一致性" },
            { label: "风险等级", tone: "success", desc: "风险可控，可直接推进" }
          ].map((item) => `
            <article class="resume-hj-score-card ${item.tone}">
              <div class="resume-hj-score-value">--</div>
              <div class="resume-hj-score-label">${item.label}</div>
              <div class="resume-hj-score-desc">${item.desc}</div>
            </article>
          `).join("")}
        </div>
      </section>
      <section class="resume-df-section">
        <p class="resume-df-section-kicker">结论流</p>
        <div class="resume-df-flow muted placeholder-flow">
          ${ph.map(([label, text], i) => `
            <div class="resume-df-step">
              <div class="resume-df-step-meta">
                <span class="resume-df-step-n">${String(i + 1).padStart(2, "0")}</span>
                <span class="resume-df-step-label">${escHtml(label)}</span>
              </div>
              <p class="resume-df-step-conclusion">${escHtml(text)}</p>
              <p class="resume-df-step-explain">分析完成后显示。</p>
            </div>
            ${i < ph.length - 1 ? `<div class="resume-df-arrow" aria-hidden="true"><span>↓</span></div>` : ""}
          `).join("")}
        </div>
      </section>
    </div>
  `;
}

function resumeJudgeFallbackDeckClient(profile, matcher, analysisMode, verdict) {
  const core = String(verdict?.summary || profile?.candidate_summary || "").trim() || "系统已完成分析。请查看下方结论与下一步建议。";
  const risks = (Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : []).slice(0, 3).map((u) => {
    const item = String(u?.item || "").trim();
    const reason = String(u?.reason || "").trim();
    if (!item) return "";
    return reason ? `${item}：${reason}` : item;
  }).filter(Boolean);
  const highlights = (Array.isArray(profile?.project_highlights) ? profile.project_highlights : []).slice(0, 2).map((p) => ({
    headline: String(p?.project || p?.project_name || "项目").trim() || "项目",
    why: String(p?.evidence || p?.impact || "").trim() || "建议补充可量化结果与独立贡献。"
  })).filter((x) => x.headline);
  return {
    core_conclusion: core,
    identity_tag: "",
    highlight_evidence: highlights,
    key_risks: risks.length ? risks : ["建议自查：主线是否集中、成果是否可量化、岗位信号是否清晰。"],
    next_actions: [
      "把一条最强经历改写成「背景—职责—动作—结果(指标)」四行，可复述口径。",
      "删除弱相关堆砌，把版面让给 1～2 个与目标方向强相关的证据。",
      "用目标岗位/方向的关键词重排项目顺序与技能分组。"
    ],
    substitution_opportunities: [],
    apply_verdict: analysisMode === "job_match" ? "revise_first" : "not_applicable",
    apply_verdict_label: analysisMode === "job_match" ? "建议改后再投" : ""
  };
}

function resumeJudgeResolveDeck(state, profile, matcher, analysisMode, verdict) {
  const d = state?.resume_highlight_deck;
  if (d && typeof d === "object" && String(d.core_conclusion || "").trim().length >= 24) {
    return d;
  }
  return resumeJudgeFallbackDeckClient(profile, matcher, analysisMode, verdict);
}

function resumeJudgeSpotlightBoardHtml(deck, state, analysisMode) {
  const meta = state?.analysis_meta && typeof state.analysis_meta === "object" ? state.analysis_meta : {};
  const ocrNote = meta.ocr_used
    ? "本次分析基于 OCR 提取文本，版式可能影响判断；建议核对关键项目描述是否完整。"
    : "";
  const verdict = deck?.apply_verdict || "not_applicable";
  const vLabel = String(deck?.apply_verdict_label || "").trim();
  const showVerdict = analysisMode === "job_match" && verdict !== "not_applicable";
  const verdictClass = verdict === "direct_ok" ? "success" : (verdict === "risky" ? "danger" : "warn");
  const evid = Array.isArray(deck?.highlight_evidence) ? deck.highlight_evidence.slice(0, 2) : [];
  const risks = Array.isArray(deck?.key_risks) ? deck.key_risks.slice(0, 3) : [];
  const acts = Array.isArray(deck?.next_actions) ? deck.next_actions.slice(0, 3) : [];
  const subs = Array.isArray(deck?.substitution_opportunities) ? deck.substitution_opportunities.slice(0, 2) : [];
  const idTag = String(deck?.identity_tag || "").trim();

  return `
    <section class="resume-hj-spotlight" aria-label="核心结论与亮点">
      <div class="resume-hj-spotlight-main">
        <p class="resume-hj-spotlight-kicker">核心结论</p>
        ${idTag ? `<p class="resume-hj-spotlight-id">${escHtml(idTag)}</p>` : ""}
        <p class="resume-hj-spotlight-lead">${escHtml(String(deck?.core_conclusion || "").trim() || "—")}</p>
        <div class="resume-hj-spotlight-meta">
          ${showVerdict && vLabel ? `<span class="resume-hj-verdict-chip ${verdictClass}">${escHtml(vLabel)}</span>` : ""}
          ${ocrNote ? `<span class="resume-hj-spotlight-ocr">${escHtml(ocrNote)}</span>` : ""}
        </div>
      </div>
      <div class="resume-hj-spotlight-columns">
        <article class="resume-hj-spotlight-col">
          <p class="resume-hj-spotlight-col-kicker">最强证据（≤2）</p>
          <div class="resume-hj-spotlight-items">
            ${evid.length ? evid.map((e) => `
              <div class="resume-hj-spotlight-item">
                <strong>${escHtml(String(e?.headline || e?.title || "亮点").trim())}</strong>
                <p>${escHtml(String(e?.why || e?.reason || "").trim() || "—")}</p>
              </div>
            `).join("") : `<p class="resume-hj-spotlight-empty">等待提炼</p>`}
          </div>
        </article>
        <article class="resume-hj-spotlight-col danger-soft">
          <p class="resume-hj-spotlight-col-kicker">关键风险（≤3）</p>
          <ul class="resume-hj-spotlight-ul">
            ${risks.length ? risks.map((r) => `<li>${escHtml(String(r))}</li>`).join("") : `<li>—</li>`}
          </ul>
        </article>
        <article class="resume-hj-spotlight-col action">
          <p class="resume-hj-spotlight-col-kicker">下一步（≤3）</p>
          <ol class="resume-hj-spotlight-ol">
            ${acts.length ? acts.map((a) => `<li>${escHtml(String(a))}</li>`).join("") : `<li>—</li>`}
          </ol>
          ${subs.length ? `
            <p class="resume-hj-spotlight-subkicker">可补救的表达机会</p>
            <ul class="resume-hj-spotlight-ul small">
              ${subs.map((s) => `<li>${escHtml(String(s))}</li>`).join("")}
            </ul>
          ` : ""}
        </article>
      </div>
    </section>
  `;
}

function resumeJudgeExactDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  const sections = resumeSectionsFromState(state);
  const conclusionSection = resumeFindSectionByKeywords(sections, ["30 秒结论", "30秒结论", "30 绉掔粨璁"], 1);
  const detailSection = resumeFindSectionByKeywords(sections, ["详细诊断", "璇︾粏"], 2);
  const conclusionItems = resumeFlattenBlocks(conclusionSection?.content || []);
  const riskItems = resumeJudgeRiskItems(detailSection, matcher, profile);
  const strengthGroup = resumeFindGroupByKeywords(detailSection, ["优势", "strength"]);
  const verdict = resumeJudgeVerdictPayload(state, profile, matcher, analysisMode, recommendedDirections, conclusionItems);
  const highlightDeck = resumeJudgeResolveDeck(state, profile, matcher, analysisMode, verdict);
  const quickStats = resumeJudgeQuickStatItems(state, profile, matcher, analysisMode, recommendedDirections);
  const modeLabel = analysisMode === "resume_review" ? "简历诊断模式" : "岗位匹配模式";
  const subtitle = state?.analyzed_at
    ? `最近生成于 ${formatUnixTime(state.analyzed_at)}`
    : "等待分析";
  const overallScore = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  const matchScore = resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections);
  const projectScore = averageResumeScores([resumeJudgeStoryScore(profile, matcher), resumeJudgeTechScore(profile)]);
  const riskLevel = { label: "待验证", tone: "muted", desc: "根据具体证据逐项核实，暂不量化风险" };
  const scoreCards = [
    { label: "综合匹配", value: resumeScoreLabel(overallScore), tone: "primary", desc: "需要成果与任务验证" },
    { label: "技能证据覆盖", value: resumeScoreLabel(matchScore), tone: matchScore < 45 ? "danger" : (matchScore < 70 ? "warn" : "success"), desc: "已识别技能的文本证据比例" },
    { label: "项目相关性", value: resumeScoreLabel(projectScore), tone: projectScore >= 75 ? "success" : "brand", desc: "项目与目标方向一致性" },
    { label: "风险等级", value: riskLevel.label, tone: riskLevel.tone, desc: riskLevel.desc }
  ];
  const highlights = (resumeFlattenBlocks(strengthGroup?.blocks || []).slice(0, 4).length
    ? resumeFlattenBlocks(strengthGroup?.blocks || []).slice(0, 4)
    : (Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 4).map((item) => item?.highlight || item?.project || "") : [])
  ).filter(Boolean);

  const decisionFlowHtml = resumeJudgeDecisionFlowHtml(highlightDeck, matcher, profile, analysisMode, verdict, riskItems, recommendedDirections);
  const evidenceRailHtml = resumeJudgeEvidenceRailHtml(highlightDeck, profile, highlights);
  const gapCompareHtml = resumeJudgeGapCompareHtml(analysisMode, profile, matcher, recommendedDirections, matchScore);
  const riskRadarHtml = resumeJudgeRiskRadarHtml(profile, matcher, analysisMode, highlightDeck, matchScore, recommendedDirections);
  const hasDeepReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());

  return `
    <div id="resumeJudgeShell" class="resume-hj-shell">
      <section class="resume-hj-header-card">
        <div class="resume-hj-header-top">
          <div>
            <div class="resume-hj-badge-row">
              <span class="resume-hj-badge">诊断报告</span>
              <span class="resume-hj-mode">${modeLabel}</span>
            </div>
            <h3 class="resume-hj-title">简历诊断报告</h3>
            <p class="resume-hj-subtitle">${escHtml(subtitle)}</p>
            <div class="resume-df-stat-strip">
              ${quickStats.map((item) => `
                <span class="resume-df-stat-pill"><em>${item[0]}</em><strong>${escHtml(String(item[1]))}</strong></span>
              `).join("")}
              <span class="resume-df-stat-pill warn-soft"><em>风险</em><strong>${escHtml(riskLevel.label)}</strong></span>
            </div>
          </div>
          <div class="resume-hj-header-actions">
            <button type="button" class="resume-hj-action-btn primary" onclick="openResumeReportModal()">查看完整诊断</button>
            <button type="button" class="resume-hj-action-btn" onclick="analyzeResumeMatch()">重新匹配</button>
          </div>
        </div>
        <div class="resume-hj-score-grid">
          ${scoreCards.map((item) => `
            <article class="resume-hj-score-card ${item.tone || ""}">
              <div class="resume-hj-score-value">${escHtml(item.value)}</div>
              <div class="resume-hj-score-label">${escHtml(item.label)}</div>
              <div class="resume-hj-score-desc">${escHtml(item.desc)}</div>
            </article>
          `).join("")}
        </div>
      </section>

      <section class="resume-df-section">
        <p class="resume-df-section-kicker">结论流</p>
        ${decisionFlowHtml}
      </section>

      <section class="resume-df-section">
        <p class="resume-df-section-kicker">证据与优势来源</p>
        ${evidenceRailHtml}
      </section>

      ${gapCompareHtml}

      <section class="resume-df-section">
        <p class="resume-df-section-kicker">风险雷达</p>
        ${riskRadarHtml}
      </section>

      <section class="resume-df-section resume-md-fusion resume-deep-launch-section">
        <p class="resume-df-section-kicker">完整深度诊断</p>
        <button
          type="button"
          class="resume-deep-launch-card ${hasDeepReport ? "is-ready" : "is-locked"}"
          onclick="openResumeReportPage()"
          ${hasDeepReport ? "" : "disabled"}
          aria-label="${hasDeepReport ? "进入完整深度诊断全屏工作台" : "完整深度诊断需等待简历分析完成"}"
        >
          <div class="resume-deep-launch-visual" aria-hidden="true">
            <span class="resume-deep-launch-icon">◆</span>
          </div>
          <div class="resume-deep-launch-main">
            <div class="resume-deep-launch-row">
              <span class="resume-deep-launch-pill">全屏工作台</span>
            </div>
            <h4 class="resume-deep-launch-title">${hasDeepReport ? "进入深度诊断工作台" : "深度诊断将在分析完成后解锁"}</h4>
            <ul class="resume-deep-launch-features">
              <li>步骤化阅读</li>
              <li>指标与证据卡</li>
              <li>风险雷达与对照</li>
            </ul>
          </div>
          <div class="resume-deep-launch-aside">
            <span class="resume-deep-launch-cta-label">${hasDeepReport ? "进入" : "锁定"}</span>
            <span class="resume-deep-launch-arrow" aria-hidden="true">→</span>
          </div>
        </button>
      </section>
    </div>
  `;
}

function resumeAnalysisDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  if (!profile) {
    return resumeJudgeExactEmptyDashboardHtml(state);
  }
  return resumeJudgeExactDashboardHtml(state, profile, matcher, analysisMode, recommendedDirections);
}
