// 简历诊断：Markdown 渲染、章节大纲与报告弹层
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function resumeMarkdownBlocksHtml(raw, state = null) {
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

    // Inside a fenced code block — collect lines until closing fence
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
    // Checklist items: - [ ] or - [x]
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
  // flush any open code block
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
    if (block.type === "heading" && block.level <= 3) {
      const headingText = resumeSixPlainTextFromHtml(block.html);
      const isStepHeading = /\bstep\s*\d+\b/i.test(headingText) || /第\s*\d+\s*步/i.test(headingText);
      const canStartSection = isStepHeading || block.level <= 2;
      if (!canStartSection) {
        if (!currentSection) {
          currentSection = {
            title: "分析内容",
            intro: "",
            content: []
          };
        }
        currentSection.content.push(block);
        return;
      }
      pushCurrentSection();
      currentSection = {
        title: headingText,
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

  if (!sectionParts.length && currentSection) {
    sectionParts.push(currentSection);
  }

  const normalizedSections = (sectionParts.length ? sectionParts : [{
    title: "分析内容",
    intro: "",
    content: blocks
  }]).map((section, index) => {
    const title = resumeSixSectionTitle(section.title, `分析内容 ${index + 1}`);
    const stepMatch = String(section.title || "").match(/step\s*(\d+)/i) || String(section.title || "").match(/第\s*(\d+)\s*步/i);
    const step = stepMatch ? Number(stepMatch[1]) : index + 1;
    const partition = resumeReportBlocksPartition(section.content);
    return {
      step,
      title,
      intro: section.intro || "",
      leadBlocks: partition.leadBlocks,
      groups: partition.groups,
      content: section.content
    };
  });

  resumeTaskState.reportTabSerial = Number(resumeTaskState.reportTabSerial || 0) + 1;
  const reportId = `resume-six-report-${resumeTaskState.reportTabSerial}`;
  const metricHtml = resumeSixMetricCardsHtml(state);

  return `
    <div id="${reportId}" class="resume-6html-scope resume-six-report">
      <div class="resume-6html-toolbar">
        <span class="resume-6html-kicker">01 分析内容</span>
        <div class="nav-tabs" role="tablist">
        ${normalizedSections.map((section, index) => `
          <button type="button" class="nav-tab ${index === 0 ? "active" : ""}" role="tab" onclick="switchResumeReportSectionTab('${reportId}', ${index})">
            <span class="tab-num">${String(section.step).padStart(2, "0")}</span>${escHtml(section.title)}
          </button>
        `).join("")}
        </div>
      </div>
      <div class="resume-6html-main-area">
      ${normalizedSections.map((section, index) => {
        const paras = section.leadBlocks.filter((item) => item.type === "paragraph");
        const firstPara = paras[0];
        const secondPara = paras[1];
        const leadTexts = paras.map((item) => resumeSixPlainTextFromHtml(item.html)).filter(Boolean);
        const firstLead = leadTexts[0] || resumeSixPlainTextFromHtml(section.intro) || "请结合完整报告逐项查看诊断结果。";
        const secondLead = leadTexts[1] || "建议先看本页结论，再进入后续模块做逐项修改。";
        const firstLeadHtml = firstPara ? firstPara.html : (section.intro || escHtml(firstLead));
        const secondLeadHtml = secondPara ? secondPara.html : escHtml(secondLead);
        const hasCodeBlock = section.content.some((item) => item.type === "codeblock");
        const stepStr = String(section.step).padStart(2, "0");
        const headerIntro = index > 0 && section.intro
          ? `<p style="color: var(--text-secondary); margin-top: 6px; font-size: 0.95rem;">${section.intro}</p>`
          : "";
        const bodyPrimary = hasCodeBlock ? `
            <div class="liquid-card">
              ${resumeReportBlocksHtml(section.content)}
            </div>
          ` : `
            <div class="liquid-card">
              <div class="resume-report-body">
                ${section.leadBlocks.length ? `<div class="resume-report-lead">${resumeReportBlocksHtml(section.leadBlocks)}</div>` : ""}
              </div>
            </div>
            ${section.groups.length ? section.groups.map((group) => `
            <div class="subsection">
              <h3 class="subsection-title">${group.title}</h3>
              <div class="liquid-card">
                <div class="resume-report-subcontent">
                  ${resumeReportBlocksHtml(group.blocks)}
                </div>
              </div>
            </div>
            `).join("") : ""}
          `;
        const fallbackBody = (!section.leadBlocks.length && !section.groups.length && !hasCodeBlock)
          ? `<div class="liquid-card"><div class="resume-report-body">${resumeReportBlocksHtml(section.content)}</div></div>`
          : "";
        return `
        <div id="resume-report-section-${index + 1}" class="tab-panel ${index === 0 ? "active" : ""}" role="tabpanel">
          <div class="float-element"></div>
          <div class="float-element"></div>
          <div class="section-header fade-in">
            <div class="section-step">Step ${stepStr}</div>
            <h2 class="section-title">${escHtml(section.title)}</h2>
            ${headerIntro}
          </div>
          ${index === 0 && metricHtml ? metricHtml : ""}
          ${index === 0 ? `
            <div class="two-col">
              <div class="liquid-card liquid-border fade-in fade-in-delay-2">
                <h3 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 1.3rem;">🎯</span> 目标定位判断
                </h3>
                <div style="color: var(--text-secondary); line-height: 1.8;">${firstLeadHtml}</div>
              </div>
              <div class="liquid-card fade-in fade-in-delay-3" style="border-left: 4px solid var(--accent-green);">
                <h3 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--accent-green); display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 1.3rem;">⚡</span> 30秒定论
                </h3>
                <div style="color: var(--text-secondary); font-size: 1rem; line-height: 1.8;">${secondLeadHtml}</div>
              </div>
            </div>
          ` : ""}
          ${bodyPrimary}
          ${index === 0 ? resume6htmlRadarChartHtml() : ""}
          ${fallbackBody}
        </div>
      `;
      }).join("")}
      </div>
    </div>
  `;
}

function resumeMarkdownInjectHeadingAnchors(html) {
  let n = 0;
  return String(html || "").replace(/<h2\b[^>]*>/gi, (tag) => {
    if (/\bid\s*=/.test(tag)) return tag;
    n += 1;
    return tag.replace("<h2", `<h2 id="resume-report-section-${n}"`);
  });
}

function resumeDetailedReportHtml(state) {
  const matcher = state?.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const ui = matcher.diagnosis_ui;
  if (ui && diagnosisUiNonEmpty(ui)) {
    return renderDiagnosisUiV1(ui, state);
  }
  const markdown = String(state.analysis_result || "").trim();
  if (markdown) {
    return resumeMarkdownBlocksHtml(markdown, state);
  }
  const htmlText = resumeAnalysisHtmlToText(state.analysis_html);
  if (htmlText) return resumeMarkdownBlocksHtml(htmlText, state);
  if (state.analysis_html) return `<div class="resume-report-doc html"><article class="resume-report-html-fallback">${state.analysis_html}</article></div>`;
  return `<div class="career-list-empty">等待生成简历分析结果</div>`;
}

function extractResumeReportTitles(reportHtml) {
  const html = String(reportHtml || "");
  let titles = Array.from(html.matchAll(/<p class="resume-report-title">([\s\S]*?)<\/p>/g))
    .map((match) => decodeHtmlEntities(String(match[1] || "").replace(/<[^>]+>/g, "")).trim())
    .filter(Boolean);
  if (!titles.length) {
    titles = Array.from(html.matchAll(/<h2[^>]*>([\s\S]*?)<\/h2>/gi))
      .map((match) => decodeHtmlEntities(String(match[1] || "").replace(/<[^>]+>/g, "")).trim())
      .filter(Boolean);
  }
  return titles;
}

function buildResumeReportPreviewItems(titles) {
  return titles.slice(0, 4);
}

function clearResumeReportObserver() {
  if (resumeTaskState.reportObserver) {
    resumeTaskState.reportObserver.disconnect();
    resumeTaskState.reportObserver = null;
  }
}

function setActiveResumeReportOutline(index) {
  document.querySelectorAll(".resume-report-outline-btn").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.sectionIndex || 0) === Number(index || 0));
  });
}

function bindResumeReportOutlineTracking() {
  clearResumeReportObserver();
  const root = document.getElementById("resumeReportModalContent");
  if (!root) return;
  const sixReport = root.querySelector(".resume-six-report");
  if (sixReport) {
    setActiveResumeReportOutline(1);
    return;
  }
  if (typeof IntersectionObserver === "undefined") return;
  const sections = Array.from(root.querySelectorAll(".resume-report-section[id]"));
  if (!sections.length) return;
  resumeTaskState.reportObserver = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    const matched = String(visible.target.id || "").match(/(\d+)$/);
    if (!matched) return;
    setActiveResumeReportOutline(Number(matched[1]));
  }, {
    root,
    threshold: [0.2, 0.35, 0.55, 0.75]
  });
  sections.forEach((section) => resumeTaskState.reportObserver.observe(section));
  setActiveResumeReportOutline(1);
}

function resumeReportLauncherHtml(state, profile, matcher, analysisMode, recommendedDirections) {
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const reportHtml = hasReport ? resumeDetailedReportHtml(state) : "";
  const titles = hasReport ? extractResumeReportTitles(reportHtml) : [];
  const previewItems = buildResumeReportPreviewItems(titles);
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;
  const summaryText = profile?.candidate_summary || (
    String(state?.status || "").trim() === "failed"
      ? (humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "") || "这份简历暂时没有生成可阅读的完整报告。")
      : (analysisMode === "resume_review"
        ? "完整报告会收纳方向建议、优势短板、风险边界和下一步修改建议。"
        : "完整报告会收纳匹配结论、命中缺口、风险边界和可执行修改建议。")
  );
  return `
    <section class="resume-bento-card resume-bento-span-12 resume-details-card resume-report-entry ${hasReport ? "" : "is-placeholder"}">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Full Report</p>
          <p class="resume-bento-title">${analysisMode === "resume_review" ? "完整诊断报告" : "完整匹配报告"}</p>
        </div>
        <button type="button" class="resume-report-open-btn" onclick="openResumeReportModal()" ${hasReport ? "" : "disabled"}>${hasReport ? "查看完整诊断" : (String(state?.status || "").trim() === "failed" ? "分析失败，暂无报告" : "等待分析完成")}</button>
      </div>
      <div class="resume-report-entry-grid">
        <div class="resume-report-entry-summary">
          <p class="resume-report-entry-copy">${escHtml(shortenResumeText(summaryText, 168))}</p>
          <div class="resume-report-entry-metrics">
            <article class="resume-report-entry-metric">
              <span>综合判断</span>
              <strong>${profile ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>阅读模式</span>
              <strong>${analysisMode === "resume_review" ? "简历诊断" : "岗位匹配"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>章节数</span>
              <strong>${hasReport ? titles.length || 1 : "--"}</strong>
            </article>
            <article class="resume-report-entry-metric">
              <span>${analysisMode === "resume_review" ? "建议方向" : "命中情况"}</span>
              <strong>${analysisMode === "resume_review" ? `${recommendedDirections.length || 0} 个` : `${matchedCount}/${jobCount || 0}`}</strong>
            </article>
          </div>
        </div>
        <div class="resume-report-entry-outline">
          <p class="resume-report-entry-label">报告包含</p>
          <div class="resume-report-entry-tags">
            ${previewItems.length ? previewItems.map((title, index) => `
              <span class="resume-report-entry-tag"><b>${String(index + 1).padStart(2, "0")}</b>${escHtml(title)}</span>
            `).join("") : `<span class="resume-radar-pill">分析完成后可查看完整报告</span>`}
          </div>
        </div>
      </div>
    </section>
  `;
}

function resolveResumeCapabilityScore(profile, key) {
  const scores = profile?.capability_scores && typeof profile.capability_scores === "object"
    ? profile.capability_scores
    : {};
  const raw = scores[key];
  const num = Number(raw);
  return Number.isFinite(num) ? normalizeResumeScore(num) : 0;
}

function resumeJudgeStoryScore(profile, matcher) {
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const experienceCount = Number(overview.experience_count || 0);
  const projectCount = Number(overview.project_count || 0);
  const evidenceCount = Array.isArray(profile?.evidence_spans) ? profile.evidence_spans.length : 0;
  const summaryBonus = profile?.candidate_summary ? 10 : 0;
  return normalizeResumeScore(42 + experienceCount * 14 + projectCount * 9 + evidenceCount * 4 + summaryBonus);
}

function resumeJudgeTechScore(profile) {
  const professional = resolveResumeCapabilityScore(profile, "professional");
  const learning = resolveResumeCapabilityScore(profile, "learning");
  const execution = resolveResumeCapabilityScore(profile, "execution");
  return averageResumeScores([professional, learning, execution]);
}

function resumeJudgeFormatScore(profile, matcher) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const overview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const baseScore = 44
    + (basics.major ? 10 : 0)
    + (basics.grade ? 10 : 0)
    + (profile?.candidate_summary ? 10 : 0)
    + Math.min(Number(overview.skill_count || 0) * 3, 16)
    + Math.min(Number(overview.project_count || 0) * 3, 10);
  return normalizeResumeScore(baseScore);
}

function resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections) {
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;
  if (analysisMode === "resume_review") {
    const matching = resolveResumeCapabilityScore(profile, "matching");
    return matching || normalizeResumeScore((recommendedDirections.length ? 72 : 58) + Math.min(recommendedDirections.length * 6, 18));
  }
  if (jobCount > 0) {
    return normalizeResumeScore((matchedCount / jobCount) * 100);
  }
  return resolveResumeCapabilityScore(profile, "matching") || normalizeResumeScore(Number(profile?.confidence || 0) * 100);
}

function resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections) {
  return averageResumeScores([
    normalizeResumeScore(Number(profile?.confidence || 0) * 100),
    resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections),
    resumeJudgeStoryScore(profile, matcher),
    resumeJudgeTechScore(profile),
    resumeJudgeFormatScore(profile, matcher)
  ]);
}

function switchResumeJudgeTab(index) {
  const shell = document.getElementById("resumeJudgeShell");
  if (!shell) return;
  const safeIndex = Number(index || 1);
  shell.querySelectorAll(".resume-judge-tab-btn, .resume-hj-tab-btn").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.sectionIndex || 0) === safeIndex);
  });
  shell.querySelectorAll(".resume-judge-tab-panel, .resume-hj-panel").forEach((panel) => {
    panel.classList.toggle("active", Number(panel.dataset.sectionIndex || 0) === safeIndex);
  });
}

function switchResumeJudgeEvidenceView(view) {
  const structured = document.getElementById("resumeJudgeStructuredResumeView");
  const raw = document.getElementById("resumeJudgeRawResumeView");
  const tabStructured = document.getElementById("resumeJudgeEvidenceTabStructured");
  const tabRaw = document.getElementById("resumeJudgeEvidenceTabRaw");
  if (!structured || !raw || !tabStructured || !tabRaw) return;
  const isRaw = String(view || "") === "raw";
  structured.classList.toggle("hidden", isRaw);
  raw.classList.toggle("hidden", !isRaw);
  tabStructured.classList.toggle("active", !isRaw);
  tabRaw.classList.toggle("active", isRaw);
}

function openResumeReportPage() {
  const state = userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  if (!hasReport) {
    showToast("完整报告未生成", "请先完成简历分析。", "warning", 1800);
    return;
  }
  window.location.href = "/resume-report.html";
}

function renderResumeReportHeroMetrics(profile, matcher, analysisMode, recommendedDirections) {
  const overall = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  const match = resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections);
  const story = resumeJudgeStoryScore(profile, matcher);
  const tech = resumeJudgeTechScore(profile);
  const cards = [
    { label: "综合判断", value: `${overall}%`, tone: "primary" },
    { label: analysisMode === "resume_review" ? "方向命中" : "岗位命中", value: `${match}%`, tone: "warm" },
    { label: "叙事完成度", value: `${story}%`, tone: "danger" },
    { label: "技术证据", value: `${tech}%`, tone: "positive" }
  ];
  return `
    <div class="resume-report-hero-metrics">
      ${cards.map((item) => `
        <article class="resume-report-hero-metric ${item.tone}">
          <p>${escHtml(item.label)}</p>
          <strong>${escHtml(item.value)}</strong>
          <div class="resume-report-hero-metric-bar"><span style="width:${Number(String(item.value).replace('%', '')) || 0}%"></span></div>
        </article>
      `).join("")}
    </div>
  `;
}

function renderResumeReportHeroTabs(titles) {
  if (!titles.length) return "";
  return `
    <div class="resume-report-top-tabs">
      ${titles.map((item, index) => `
        <button type="button" class="resume-report-top-tab" onclick="jumpResumeReportSection(${index + 1})">
          <span>${String(index + 1).padStart(2, "0")}</span>
          <strong>${escHtml(item)}</strong>
        </button>
      `).join("")}
    </div>
  `;
}

function renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections) {
  const eyebrow = document.getElementById("resumeReportModalEyebrow");
  const title = document.getElementById("resumeReportModalTitle");
  const subtitle = document.getElementById("resumeReportModalSubtitle");
  const aside = document.getElementById("resumeReportModalAside");
  const content = document.getElementById("resumeReportModalContent");
  if (!eyebrow || !title || !subtitle || !aside || !content) return;
  clearResumeReportObserver();

  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const reportHtml = hasReport ? resumeDetailedReportHtml(state) : "";
  const titles = hasReport ? extractResumeReportTitles(reportHtml) : [];
  const score = profile ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--";
  const modeLabel = analysisMode === "resume_review" ? "简历诊断" : "岗位匹配";
  const docTitle = analysisMode === "resume_review" ? "完整诊断报告" : "完整匹配报告";
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const roles = previewTagValues((profile?.roles_detected || []).map((item) => item.role), 4);
  const focusTags = analysisMode === "resume_review"
    ? previewTagValues(recommendedDirections, 4)
    : previewTagValues(matcher?.matched_keywords || [], 4);
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords.length : 0;

  eyebrow.textContent = modeLabel;
  title.textContent = docTitle;
  subtitle.textContent = hasReport
    ? `${formatUnixTime(state.analyzed_at)}`
    : "分析完成后将在此处打开。";

  if (!hasReport) {
    aside.innerHTML = `
      <div class="resume-report-side-card muted">
        <p class="resume-report-side-kicker">准备中</p>
        <p class="resume-report-side-title">完整报告尚未生成</p>
        <p class="resume-report-side-copy">上传简历并完成分析后，这里会显示报告摘要、章节目录和阅读导航。</p>
      </div>
    `;
    content.innerHTML = `<div class="resume-report-modal-empty">完整报告会在分析完成后出现在这里。</div>`;
    return;
  }

  aside.innerHTML = `
    <div class="resume-report-side-card primary">
      <p class="resume-report-side-kicker">诊断概览</p>
      <p class="resume-report-side-title">${escHtml(profile?.candidate_summary || "系统已生成完整阅读报告")}</p>
      <div class="resume-report-side-metrics">
        <article><span>综合判断</span><strong>${escHtml(score)}</strong></article>
        <article><span>阅读模式</span><strong>${analysisMode === "resume_review" ? "简历诊断" : "岗位匹配"}</strong></article>
        <article><span>${analysisMode === "resume_review" ? "建议方向" : "匹配结果"}</span><strong>${analysisMode === "resume_review" ? `${recommendedDirections.length || 0} 个` : `${matchedCount}/${jobCount || 0}`}</strong></article>
        <article><span>岗位焦点</span><strong>${escHtml(analysisMode === "resume_review" ? (recommendedDirections[0] || "待探索") : (jobOverview.job_title || "未识别"))}</strong></article>
      </div>
    </div>
    <div class="resume-report-side-card">
      <p class="resume-report-side-kicker">目录</p>
      <div class="resume-report-outline">
        ${titles.length ? titles.map((item, index) => `
          <button type="button" class="resume-report-outline-btn" data-section-index="${index + 1}" onclick="jumpResumeReportSection(${index + 1})">
            <span>${String(index + 1).padStart(2, "0")}</span>
            <strong>${escHtml(item)}</strong>
          </button>
        `).join("") : `<div class="career-list-empty">暂无章节目录</div>`}
      </div>
    </div>
    <div class="resume-report-side-card">
      <p class="resume-report-side-kicker">阅读提示</p>
      <div class="resume-report-side-tags">
        ${roles.length ? roles.map((item) => `<span class="resume-report-side-tag">${escHtml(item)}</span>`).join("") : ""}
        ${focusTags.length ? focusTags.map((item) => `<span class="resume-report-side-tag accent">${escHtml(item)}</span>`).join("") : ""}
      </div>
      <p class="resume-report-side-copy">可先浏览目录，点击跳转到对应章节。</p>
    </div>
  `;

  content.innerHTML = `
    <div class="resume-report-reading-canvas">
      <div class="resume-report-modal-hero">
        <div>
          <p class="resume-report-modal-hero-kicker">${analysisMode === "resume_review" ? "简历诊断" : "岗位匹配"}</p>
          <h4 class="resume-report-modal-hero-title">${escHtml(docTitle)}</h4>
          <p class="resume-report-modal-hero-copy">${escHtml(profile?.candidate_summary || "系统已根据简历与岗位文本生成完整报告。")}</p>
        </div>
        <div class="resume-report-modal-hero-tags">
          ${focusTags.length ? focusTags.map((item) => `<span class="resume-report-side-tag accent">${escHtml(item)}</span>`).join("") : `<span class="resume-report-side-tag">完整章节阅读模式</span>`}
        </div>
      </div>
      ${renderResumeReportHeroMetrics(profile, matcher, analysisMode, recommendedDirections)}
      ${renderResumeReportHeroTabs(titles)}
      <div class="resume-report-modal-reader">
        ${reportHtml}
      </div>
    </div>
  `;
  bindResumeReportOutlineTracking();
  const sixScope = content.querySelector(".resume-6html-scope");
  if (sixScope) initResume6htmlScopeEffects(sixScope);
}

function openResumeReportModal() {
  openResumeReportPage();
  return;
  const state = userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  const profile = state.profile || null;
  const matcher = state.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const analysisMode = String(matcher.analysis_mode || state.analysis_meta?.analysis_mode || "").trim();
  const recommendedDirections = Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions : [];
  const hasReport = state?.status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  if (!hasReport) {
    showToast("完整报告未生成", "请先完成简历分析。", "warning", 1800);
    return;
  }
  renderResumeReportModal(state, profile, matcher, analysisMode, recommendedDirections);
  const modal = document.getElementById("resumeReportModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

function closeResumeReportModal() {
  clearResumeReportObserver();
  const modal = document.getElementById("resumeReportModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

function handleResumeReportOverlayClick(event) {
  if (event.target?.id === "resumeReportModal") {
    closeResumeReportModal();
  }
}

function jumpResumeReportSection(index) {
  setActiveResumeReportOutline(index);
  const root = document.getElementById("resumeReportModalContent");
  const sixReport = root?.querySelector(".resume-six-report");
  if (sixReport?.id) {
    switchResumeReportSectionTab(sixReport.id, Number(index || 1) - 1);
    return;
  }
  const target = document.getElementById(`resume-report-section-${Number(index || 0)}`);
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function resumeJobAssistHtml(jobDescription, analysisMode, recommendedDirections) {
  const text = String(jobDescription || "").trim();
  if (!text) {
    const suggestions = [
      {
        label: "留空直接诊断",
        title: "还没想清岗位也可以直接分析",
        copy: "系统会先基于简历本身判断优势、短板、风险点和更适合的职业方向。",
        action: ""
      },
      {
        label: "写一句方向",
        title: "只写模糊方向也能匹配",
        copy: "例如：我想尝试产品运营、项目助理、HR 或数据分析相关岗位。",
        action: "我想先看看自己更适合产品运营、项目助理、HR 还是数据分析方向。"
      },
      {
        label: "粘贴完整 JD",
        title: "有明确岗位时再贴完整要求",
        copy: "系统会提炼岗位重点，并用简历证据去判断匹配程度和待补强项。",
        action: "工作地点：上海\n岗位职责：\n1. 负责用户运营和数据复盘。\n2. 协调跨团队推进活动落地。\n任职要求：\n1. 具备数据分析和内容运营能力。\n2. 有项目推进或活动执行经历。"
      }
    ];
    return `
      <div class="resume-job-assist-panel empty">
        <div class="resume-job-assist-head">
          <div>
            <p class="resume-job-assist-kicker">未填岗位</p>
            <p class="resume-job-assist-title">未指定岗位时，默认进入简历诊断模式</p>
          </div>
          <span class="resume-score-chip muted">无 JD 也可分析</span>
        </div>
        <div class="resume-job-assist-grid">
          ${suggestions.map((item) => {
            const encodedAction = encodeURIComponent(item.action || "");
            return `
            <article class="resume-job-assist-card">
              <span class="resume-job-assist-tag">${escHtml(item.label)}</span>
              <p class="resume-job-assist-card-title">${escHtml(item.title)}</p>
              <p class="resume-job-assist-copy">${escHtml(item.copy)}</p>
              ${item.action ? `<button type="button" class="resume-job-assist-action" onclick="fillResumeJobSuggestion(decodeURIComponent('${encodedAction}'))">填入示例</button>` : `<span class="resume-job-assist-hint">保持留空即可</span>`}
            </article>
          `;
          }).join("")}
        </div>
      </div>
    `;
  }

  const focusTags = analysisMode === "resume_review"
    ? previewTagValues(recommendedDirections, 4)
    : previewTagValues(text.split(/[，。；;、\n]/).map((item) => item.trim()).filter(Boolean), 4);
  return `
    <div class="resume-job-assist-panel filled">
      <div class="resume-job-assist-head">
        <div>
          <p class="resume-job-assist-kicker">已输入内容</p>
          <p class="resume-job-assist-title">系统会直接理解这段文本，不要求固定 JD 格式</p>
        </div>
        <span class="resume-score-chip brand">${analysisMode === "resume_review" ? "方向描述" : "岗位文本"}</span>
      </div>
      <div class="resume-analysis-tag-row">
        ${focusTags.length ? focusTags.map((item) => `<span class="resume-analysis-tag">${escHtml(shortenResumeText(item, 24))}</span>`).join("") : `<span class="resume-radar-pill">已输入 ${text.length} 字</span>`}
      </div>
    </div>
  `;
}
