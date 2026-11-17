// 简历诊断：进度与加载状态、报告块与六维图渲染
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function emptyResumeProfile() {
  return {
    status: "empty",
    profile: null,
    file_name: "",
    file_size: 0,
    file_type: "",
    uploaded_at: null,
    analyzed_at: null,
    analysis_meta: {},
    analysis_result: "",
    analysis_html: "",
    job_description: "",
    matcher: {},
    structured_resume: null,
    structured_job: null,
    resume_highlight_deck: null,
    error_message: ""
  };
}

function setResumeProgress(kind, percent, label = "", active = false) {
  const wrap = document.getElementById(kind === "upload" ? "resumeUploadProgressWrap" : "resumeAnalyzeProgressWrap");
  const bar = document.getElementById(kind === "upload" ? "resumeUploadProgressBar" : "resumeAnalyzeProgressBar");
  const text = document.getElementById(kind === "upload" ? "resumeUploadProgressText" : "resumeAnalyzeProgressText");
  if (!wrap || !bar || !text) return;
  const safePercent = Math.max(0, Math.min(100, Number(percent || 0)));
  wrap.classList.remove("hidden");
  bar.style.width = `${safePercent}%`;
  text.textContent = label || `${Math.round(safePercent)}%`;
  if (active) {
    bar.classList.add("animate-pulse");
  } else {
    bar.classList.remove("animate-pulse");
  }
}

function setResumeLoadingText(text) {
  const el = document.getElementById("resumeJudgeLoadingText");
  if (!el) return;
  el.textContent = String(text || "系统正在提取简历文本并组织诊断结构，请稍候。");
}

function hideResumeProgress(kind) {
  const wrap = document.getElementById(kind === "upload" ? "resumeUploadProgressWrap" : "resumeAnalyzeProgressWrap");
  if (wrap) wrap.classList.add("hidden");
}

function setResumeLoadingStage(stage) {
  const stageMap = {
    queued: 0,
    extract_resume: 0,
    structured_resume: 1,
    job_context: 2,
    resume_review: 3,
    hr_judge: 3,
    highlight_deck: 3,
    done: 3,
    failed: 3
  };
  const parsedIndex = typeof stage === "number" ? stage : (stageMap[String(stage || "").trim()] ?? 0);
  const safeIndex = Math.max(0, Math.min(3, Number(parsedIndex || 0)));
  const activeIndex = Math.max(resumeTaskState.lastLoadingStageIndex, safeIndex);
  resumeTaskState.lastLoadingStageIndex = activeIndex;
  document.querySelectorAll(".resume-judge-loading-step").forEach((node) => {
    const index = Number(node.dataset.stepIndex || 0);
    node.classList.toggle("active", index === activeIndex);
    node.classList.toggle("done", index < activeIndex);
  });
}

function syncResumeJudgeFlow(state) {
  const inputSection = document.getElementById("resumeJudgeInputSection");
  const loadingSection = document.getElementById("resumeJudgeLoadingSection");
  const reportSection = document.getElementById("resumeJudgeReportSection");
  if (!inputSection || !loadingSection || !reportSection) return;
  const status = String(state?.status || "").trim();
  const hasReport = status === "analyzed" && (String(state?.analysis_result || "").trim() || String(state?.analysis_html || "").trim());
  const showLoading = resumeTaskState.analyzeInFlight || status === "analyzing";
  const showReport = !showLoading && hasReport && !resumeTaskState.forceInputView;
  const showInput = !showLoading && !showReport;
  inputSection.classList.toggle("hidden", !showInput);
  loadingSection.classList.toggle("hidden", !showLoading);
  reportSection.classList.toggle("hidden", !showReport);
  syncResumeStudioTabs(showInput, showLoading, showReport);
}

function syncResumeStudioTabs(showInput, showLoading, showReport) {
  const tabInput = document.getElementById("resumeStudioTabInput");
  const tabLoading = document.getElementById("resumeStudioTabLoading");
  const tabReport = document.getElementById("resumeStudioTabReport");
  const live = document.getElementById("resumeStudioLiveStatus");
  if (!tabInput || !tabLoading || !tabReport) return;
  tabInput.classList.toggle("active", Boolean(showInput));
  tabLoading.classList.toggle("active", Boolean(showLoading));
  tabReport.classList.toggle("active", Boolean(showReport));
  if (live) {
    live.textContent = showLoading ? "分析阶段" : (showReport ? "报告阶段" : "输入阶段");
  }
}

function showResumeJudgeInputView() {
  resumeTaskState.forceInputView = true;
  syncResumeJudgeFlow(getResumeProfileFromCache());
}

function updateResumeActionButtons() {
  const uploadBtn = document.getElementById("resumeUploadBtn");
  const analyzeBtn = document.getElementById("resumeAnalyzeBtn");
  const deleteBtn = document.getElementById("resumeDeleteBtn");
  const busy = resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight;
  if (uploadBtn) uploadBtn.disabled = busy;
  if (analyzeBtn) analyzeBtn.disabled = busy;
  if (deleteBtn) deleteBtn.disabled = busy;
  renderReportResumePanel();
}

function syncResumeJobInputFrame() {
  const input = document.getElementById("resumeJobDescriptionInput");
  const button = document.getElementById("resumeJobInputToggleBtn");
  const expanded = Boolean(resumeTaskState.jobInputExpanded);
  if (input) {
    input.rows = expanded ? 12 : 7;
    input.classList.toggle("expanded", expanded);
  }
  if (button) {
    button.textContent = expanded ? "收起输入区" : "展开输入区";
  }
}

function toggleResumeJobInput(forceExpanded = null) {
  if (typeof forceExpanded === "boolean") {
    resumeTaskState.jobInputExpanded = forceExpanded;
  } else {
    resumeTaskState.jobInputExpanded = !resumeTaskState.jobInputExpanded;
  }
  syncResumeJobInputFrame();
}

function startAnalyzeProgressTicker() {
  stopAnalyzeProgressTicker();
  resumeTaskState.analyzeStartedAt = Date.now();
  resumeTaskState.analyzeFrameIndex = 0;
  resumeTaskState.lastLoadingStageIndex = -1;
  setResumeProgress("analyze", 100, "正在启动简历分析 · 0s", true);
  setResumeLoadingText("系统正在提取简历文本并组织诊断结构，请稍候。");
  setResumeLoadingStage("queued");
  resumeTaskState.analyzeTimer = setInterval(() => {
    if (!resumeTaskState.analyzeInFlight) return;
    const elapsedSec = Math.max(0, Math.floor((Date.now() - resumeTaskState.analyzeStartedAt) / 1000));
    const stageLabels = ["提取简历文本", "结构化简历", "理解岗位文本", "生成分析结论"];
    const stage = stageLabels[Math.max(0, resumeTaskState.lastLoadingStageIndex)];
    setResumeProgress("analyze", 100, `${stage} · ${elapsedSec}s`, true);
    setResumeLoadingText(`${stage} · 已运行 ${elapsedSec}s`);
  }, 900);
}

function stopAnalyzeProgressTicker() {
  if (resumeTaskState.analyzeTimer) {
    clearInterval(resumeTaskState.analyzeTimer);
    resumeTaskState.analyzeTimer = null;
  }
}

function sleepMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function applyResumeAnalyzeRuntimeStatus(job, elapsedSec) {
  const analyzeStatus = document.getElementById("resumeAnalyzeStatus");
  const analyzeMeta = document.getElementById("resumeAnalyzeMeta");
  const stage = String(job?.stage || "").trim();
  const detail = String(job?.stage_detail || "").trim();
  const stageLabelMap = {
    queued: "任务排队中",
    extract_resume: "提取简历文本",
    structured_resume: "结构化简历",
    job_context: "理解岗位文本",
    resume_review: "生成简历诊断",
    hr_judge: "生成分析结论",
    done: "分析完成",
    failed: "分析失败"
  };
  const stageLabel = detail || stageLabelMap[stage] || "分析中";
  if (analyzeStatus) analyzeStatus.textContent = stage === "queued" ? "排队中" : "分析中";
  if (analyzeMeta) analyzeMeta.textContent = `${stageLabel} · 已运行 ${elapsedSec}s`;
  setResumeProgress("analyze", 100, `${stageLabel} · ${elapsedSec}s`, true);
  setResumeLoadingText(`${stageLabel} · 已运行 ${elapsedSec}s`);
  setResumeLoadingStage(stage);
}

function getResumeProfileFromCache() {
  return userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
}

async function loadResumeProfile(force = false) {
  if (!isAuthenticatedUser()) return emptyResumeProfile();
  if (!force && userWorkspaceState.scopedDataLoaded.resume_profile) {
    return userWorkspaceState.scopedData.resume_profile || emptyResumeProfile();
  }
  const payload = await requestJson("/api/resume/profile");
  const data = payload.data || emptyResumeProfile();
  userWorkspaceState.scopedData.resume_profile = data;
  userWorkspaceState.scopedDataLoaded.resume_profile = true;
  return data;
}

function setResumeJobDescription(value) {
  const input = document.getElementById("resumeJobDescriptionInput");
  if (!input) return;
  if (document.activeElement === input) return;
  input.value = String(value || "");
}

function getResumeJobDescription() {
  return String(document.getElementById("resumeJobDescriptionInput")?.value || "").trim();
}

function fillResumeJobSuggestion(text) {
  const input = document.getElementById("resumeJobDescriptionInput");
  if (!input) return;
  input.value = String(text || "").trim();
  resumeTaskState.jobInputExpanded = true;
  syncResumeJobInputFrame();
  input.focus();
}

function resumeInlineMarkupHtml(value) {
  const escaped = escHtml(String(value || "").trim());
  if (!escaped) return "";
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function decodeHtmlEntities(raw) {
  if (typeof document === "undefined") return String(raw || "");
  const textarea = document.createElement("textarea");
  textarea.innerHTML = String(raw || "");
  return textarea.value;
}

function resumeAnalysisHtmlToText(raw) {
  const html = String(raw || "").trim();
  if (!html) return "";
  const normalized = html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|section|article|h1|h2|h3|h4|h5|h6)>/gi, "\n")
    .replace(/<li[^>]*>/gi, "- ")
    .replace(/<\/(li|ul|ol)>/gi, "\n")
    .replace(/<pre[^>]*><code[^>]*>/gi, "")
    .replace(/<\/code><\/pre>/gi, "");
  return decodeHtmlEntities(normalized.replace(/<[^>]+>/g, ""))
    .replace(/\u00a0/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function resumeReportBlocksPartition(blocks) {
  const leadBlocks = [];
  const groups = [];
  let currentGroup = null;
  blocks.forEach((block) => {
    if (block.type === "heading") {
      currentGroup = {
        title: block.html,
        blocks: []
      };
      groups.push(currentGroup);
      return;
    }
    if (currentGroup) {
      currentGroup.blocks.push(block);
      return;
    }
    leadBlocks.push(block);
  });
  return { leadBlocks, groups };
}

function resumeReportListHtml(block) {
  const ordered = block.listType === "ol";
  return `
    <div class="resume-report-list-grid ${ordered ? "ordered" : "unordered"}">
      ${block.items.map((item, index) => `
        <article class="resume-report-list-card${ordered ? "" : " resume-report-list-card--text-only"}">
          ${ordered ? `<span class="resume-report-list-badge">${String(index + 1).padStart(2, "0")}</span>` : ""}
          <p class="resume-report-list-copy">${item}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function resumeReportBlocksHtml(blocks) {
  return blocks.map((block) => {
    if (block.type === "paragraph") {
      return `<p class="resume-report-paragraph">${block.html}</p>`;
    }
    if (block.type === "divider") {
      return `<div class="resume-report-divider"></div>`;
    }
    if (block.type === "list") {
      return resumeReportListHtml(block);
    }
    if (block.type === "codeblock") {
      const id = `rcb-${Math.random().toString(36).slice(2, 9)}`;
      return `
        <div class="resume-report-code-block">
          <div class="resume-report-code-toolbar">
            <span class="resume-report-code-label">📄 修改后简历范本</span>
            <button type="button" class="resume-report-code-copy" onclick="copyResumeCodeBlock('${id}')">复制</button>
          </div>
          <pre id="${id}" class="resume-report-code-pre"><code>${escHtml(block.code)}</code></pre>
        </div>
      `;
    }
    return "";
  }).join("");
}

function copyResumeCodeBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.innerText || el.textContent || "";
  navigator.clipboard.writeText(text).then(() => {
    const btn = el.closest(".resume-report-code-block")?.querySelector(".resume-report-code-copy");
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = "已复制 ✓";
      setTimeout(() => { btn.textContent = prev; }, 2000);
    }
  }).catch(() => {});
}

function copyPlainText(text, successTitle = "已复制", successMessage = "内容已复制到剪贴板。") {
  const raw = String(text || "").trim();
  if (!raw) {
    showToast("没有可复制内容", "先生成任务名片后再复制。", "warning", 1800);
    return Promise.resolve(false);
  }
  return navigator.clipboard.writeText(raw).then(() => {
    showToast(successTitle, successMessage, "success", 1600);
    return true;
  }).catch(() => {
    showToast("复制失败", "当前环境不允许直接写入剪贴板。", "error", 1800);
    return false;
  });
}

function resumeSixPlainTextFromHtml(html) {
  return decodeHtmlEntities(String(html || "").replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

function resumeSixSectionTitle(rawTitle, fallback) {
  const plain = String(rawTitle || "").trim();
  if (!plain) return fallback || "分析内容";
  return plain
    .replace(/^step\s*\d+\s*[:：\-]?\s*/i, "")
    .replace(/^第\s*\d+\s*步[:：\-]?\s*/i, "")
    .replace(/\s*\([^)]*\)\s*$/, "")
    .trim() || fallback || "分析内容";
}

function resumeSixMetricCardsHtml(state) {
  const profile = state?.profile || null;
  const matcher = state?.matcher && typeof state.matcher === "object" ? state.matcher : {};
  const analysisMode = String(matcher.analysis_mode || state?.analysis_meta?.analysis_mode || "").trim();
  const recommendedDirections = Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions : [];
  if (!profile) return "";

  const overall = resumeJudgeOverallScore(profile, matcher, analysisMode, recommendedDirections);
  const match = resumeJudgeMatchScore(profile, matcher, analysisMode, recommendedDirections);
  const story = resumeJudgeStoryScore(profile, matcher);
  const tech = resumeJudgeTechScore(profile);
  const cards = [
    { label: "学术背景评分", value: overall, cls: "a" },
    { label: "技能证据覆盖", value: match, cls: "b" },
    { label: "项目推进能力", value: story, cls: "c" },
    { label: "软技能展示", value: tech, cls: "d" }
  ];

  return `
    <div class="dashboard-grid fade-in fade-in-delay-1">
      ${cards.map((item) => `
        <div class="metric-card">
          <div class="metric-value">${escHtml(resumeScoreLabel(item.value))}</div>
          <div class="metric-label">${escHtml(item.label)}</div>
          <div class="metric-bar"><div class="metric-bar-fill" style="width:${Math.max(0, Math.min(100, Number(item.value || 0)))}%"></div></div>
        </div>
      `).join("")}
    </div>
  `;
}

function initResume6htmlScopeEffects(root) {
  if (!root || !root.classList.contains("resume-6html-scope")) return;
  root.querySelectorAll(".liquid-card").forEach((card) => {
    card.addEventListener("mousemove", (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      card.style.background = `radial-gradient(circle at ${x}px ${y}px, rgba(255, 255, 255, 0.88), rgba(255, 255, 255, 0.62))`;
    });
    card.addEventListener("mouseleave", () => {
      card.style.background = "";
    });
  });
  setTimeout(() => {
    root.querySelectorAll(".metric-bar-fill").forEach((bar) => {
      const w = bar.style.width;
      if (w) bar.style.width = w;
    });
  }, 280);
}

function resume6htmlRadarChartHtml() {
  return `<div class="liquid-card"><h3>能力验证</h3><p>学习力、沟通协作与项目推进能力待验证。技能证据覆盖率单独展示，不用固定雷达图代替能力测量。</p></div>`;
}

function switchResumeReportSectionTab(reportId, index) {
  const root = document.getElementById(String(reportId || "").trim());
  if (!root) return;
  const panels = Array.from(root.querySelectorAll(".resume-6html-main-area > .tab-panel"));
  if (!panels.length) return;
  const safeIndex = Math.max(0, Math.min(panels.length - 1, Number(index || 0)));
  root.querySelectorAll(".resume-6html-toolbar .nav-tab").forEach((tab, tabIndex) => {
    tab.classList.toggle("active", tabIndex === safeIndex);
  });
  panels.forEach((panel, panelIndex) => {
    panel.classList.toggle("active", panelIndex === safeIndex);
  });
}

function diagnosisUiNonEmpty(ui) {
  if (!ui || typeof ui !== "object" || Number(ui.v) !== 1) return false;
  if (String(ui.s1_positioning || "").trim() || String(ui.s1_verdict || "").trim()) return true;
  if (Array.isArray(ui.s2_overall) && ui.s2_overall.length) return true;
  if (Array.isArray(ui.s2_modules) && ui.s2_modules.length) return true;
  if (Array.isArray(ui.s2_timeline) && ui.s2_timeline.length) return true;
  const s3 = ui.s3 && typeof ui.s3 === "object" ? ui.s3 : {};
  if (String(s3.left_intro || "").trim() || String(s3.formula || "").trim() || String(s3.compare_before || "").trim() || String(s3.thinking_path || "").trim()) {
    return true;
  }
  if (String(ui.step4_html || "").trim() || String(ui.s4_resume_markdown || "").trim()) return true;
  const s5 = ui.s5 || {};
  if (String(s5.evaluation || "").trim() || String(s5.risk1_body || "").trim()) return true;
  return false;
}

function resumeDiagnosisPlainHtml(text) {
  return escHtml(String(text || "").trim()).replace(/\n/g, "<br>");
}

function renderDiagnosisAuditInner(audit, nested) {
  const danger = Boolean(audit && audit.danger);
  const borderAttr = nested ? ' style="border-left: none; padding-left: 0;"' : "";
  const impactExtra = danger
    ? ' style="background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.2);"'
    : "";
  const impactLabelExtra = danger ? ' style="color: var(--accent-red);"' : "";
  const impactBlock = audit.impact
    ? `<div class="audit-impact"${impactExtra}>
        <span class="audit-impact-label"${impactLabelExtra}>🤔 负面影响</span>
        ${resumeDiagnosisPlainHtml(audit.impact)}
      </div>`
    : "";
  const sugBlock = audit.suggestion
    ? `<div class="audit-suggestion">
        <span class="audit-suggestion-label">💡 建议</span>
        ${resumeDiagnosisPlainHtml(audit.suggestion)}
      </div>`
    : "";
  return `
    <div class="audit-item"${borderAttr}>
      <div class="audit-question">
        <span class="audit-icon">❓</span>
        <span>${escHtml(String(audit.topic || "审计项"))}</span>
      </div>
      ${audit.detail ? `<p style="color: var(--text-secondary); margin-bottom: 10px;">${resumeDiagnosisPlainHtml(audit.detail)}</p>` : ""}
      ${impactBlock}
      ${sugBlock}
    </div>
  `;
}

function renderDiagnosisAuditCard(audit) {
  const danger = Boolean(audit && audit.danger);
  return `
    <div class="liquid-card fade-item"${danger ? ' style="border-color: rgba(239, 68, 68, 0.3);"' : ""}>
      ${renderDiagnosisAuditInner(audit, false)}
    </div>
  `;
}

function renderDiagnosisComparisonPair(before, after, labelBefore, labelAfter) {
  const b = String(before || "").trim();
  const a = String(after || "").trim();
  if (!b && !a) return "";
  const lb = labelBefore || "前";
  const la = labelAfter || "后";
  return `
    <div class="comparison-grid">
      <div class="comparison-item before">
        <span class="comparison-label">${escHtml(lb)}</span>
        ${resumeDiagnosisPlainHtml(b || "（空）")}
      </div>
      <div class="comparison-item after">
        <span class="comparison-label">${escHtml(la)}</span>
        ${resumeDiagnosisPlainHtml(a || "（空）")}
      </div>
    </div>
  `;
}

function renderDiagnosisUiV1(ui, state) {
  const profile = state?.profile || {};
  const fallbackSummary = String(profile.candidate_summary || "").trim();
  const s1Pos = String(ui.s1_positioning || "").trim() || fallbackSummary.slice(0, 1200) || "已完成结构化提取与诊断，请结合下方各步建议逐项优化简历。";
  const s1Ver = String(ui.s1_verdict || "").trim() || "建议优先处理风险与时间线一致性，再强化「业务价值」叙事。";
  const s2Sub = String(ui.s2_subtitle || "").trim() || "严格遵循「批判-解析-建议」三位一体模型对你的简历进行审计。";
  const s3 = ui.s3 && typeof ui.s3 === "object" ? ui.s3 : {};
  const s5 = ui.s5 && typeof ui.s5 === "object" ? ui.s5 : {};

  resumeTaskState.reportTabSerial = Number(resumeTaskState.reportTabSerial || 0) + 1;
  const reportId = `resume-six-report-${resumeTaskState.reportTabSerial}`;
  const metricHtml = resumeSixMetricCardsHtml(state);

  const tabs = [
    { n: "01", label: "第一印象与初步诊断" },
    { n: "02", label: "地毯式深度审计" },
    { n: "03", label: "战略性修改蓝图" },
    { n: "04", label: "修改后的简历范本" },
    { n: "05", label: "最终裁决与行动清单" }
  ];

  const overallBlocks = (Array.isArray(ui.s2_overall) ? ui.s2_overall : [])
    .filter((a) => a && (a.topic || a.detail || a.impact || a.suggestion))
    .map((a) => renderDiagnosisAuditCard(a))
    .join("");
  const overallSection = overallBlocks
    || `<div class="liquid-card fade-item"><p class="resume-report-paragraph">原文未拆出独立「整体审计」条目，请结合 Step 01 与完整 Markdown 报告查看结论。</p></div>`;

  const modulesHtml = (Array.isArray(ui.s2_modules) ? ui.s2_modules : [])
    .map((mod) => {
      const heading = String(mod.heading || "").trim() || "模块";
      const lead = String(mod.lead || "").trim();
      const audits = Array.isArray(mod.audits) ? mod.audits : [];
      const inner = audits
        .filter((a) => a && (a.topic || a.detail || a.impact || a.suggestion))
        .map((a) => renderDiagnosisAuditInner(a, true))
        .join("");
      return `
        <div class="liquid-card fade-item" style="margin-bottom: 24px;">
          <h3 style="font-size: 1.05rem; margin-bottom: 14px; color: var(--accent-cyan);">${escHtml(heading)}</h3>
          ${lead ? `<p style="color: var(--text-secondary); margin-bottom: 16px; font-size: 0.9rem;">${resumeDiagnosisPlainHtml(lead)}</p>` : ""}
          ${inner || `<p class="resume-report-paragraph">本模块暂无细分审计条目。</p>`}
        </div>
      `;
    })
    .join("");

  const modulesBlock = modulesHtml
    || `<p class="resume-report-paragraph">暂无模块化拆分条目，请查看完整 Markdown 报告中的分节内容。</p>`;

  const timelineHtml = (Array.isArray(ui.s2_timeline) ? ui.s2_timeline : [])
    .filter((t) => t && String(t.heading || "").trim())
    .map((t) => {
      const comps = Array.isArray(t.comparisons) ? t.comparisons : [];
      const compHtml = comps
        .map((c) => renderDiagnosisComparisonPair(c.before, c.after, "修改前", "修改后"))
        .join("");
      const auditBits = {
        topic: t.topic || "叙事与价值",
        detail: t.detail,
        impact: t.impact,
        suggestion: t.suggestion,
        danger: false
      };
      return `
        <div class="timeline-item">
          <h4 style="font-size: 1rem; margin-bottom: 12px; color: var(--accent-purple);">${escHtml(String(t.heading))}</h4>
          ${renderDiagnosisAuditInner(auditBits, true)}
          ${compHtml}
        </div>
      `;
    })
    .join("");

  const s3Compare = renderDiagnosisComparisonPair(s3.compare_before, s3.compare_after, "前", "后");

  const step4Inner = String(ui.step4_html || "").trim()
    ? `<div class="resume-html-inject">${ui.step4_html}</div>`
    : `<p class="resume-report-paragraph">模型未输出「修改后简历」Markdown，请根据 Step 02–03 建议自行改写并粘贴至简历正文。</p>`;

  const qs = Array.isArray(s3.questions) ? s3.questions : ["", "", ""];
  const qRows = [0, 1, 2].map((i) => {
    const q = String(qs[i] || "").trim();
    if (!q) return "";
    const tag = `Q${i + 1}`;
    const border = i < 2 ? "border-bottom: 1px solid rgba(0,0,0,0.05);" : "";
    return `
      <li style="padding: 14px 0; ${border} color: var(--text-secondary); font-size: 0.9rem; line-height: 1.7; list-style: none;">
        <span style="color: var(--accent-cyan); margin-right: 8px; font-weight: 700;">${tag}</span>
        ${resumeDiagnosisPlainHtml(q)}
      </li>
    `;
  }).join("");

  const actions = Array.isArray(s5.actions) ? s5.actions : [];
  const actionRows = [0, 1, 2].map((i) => {
    const a = actions[i] || {};
    const label = String(a.label || "").trim();
    const body = String(a.body || "").trim();
    if (!label && !body) return "";
    const num = i + 1;
    return `
      <li class="checklist-item checklist-item--plain">
        <span class="checklist-ordinal">${num}</span>
        <div class="check-text">
          ${label ? `<span class="check-label">${escHtml(label)}</span>` : ""}
          ${body ? `<span class="check-body">${resumeDiagnosisPlainHtml(body)}</span>` : ""}
        </div>
      </li>
    `;
  }).join("");

  const risk1 = String(s5.risk1_body || "").trim();
  const risk2 = String(s5.risk2_body || "").trim();
  const r1t = String(s5.risk1_title || "风险点：").trim();
  const r2t = String(s5.risk2_title || "风险点：").trim();

  const panel0 = `
    <div id="resume-report-section-d1" class="tab-panel active" role="tabpanel">
      <div class="float-element"></div>
      <div class="float-element"></div>
      <div class="section-header fade-in">
        <div class="section-step">Step 01</div>
        <h2 class="section-title">第一印象与初步诊断</h2>
      </div>
      ${metricHtml || ""}
      <div class="two-col">
        <div class="liquid-card liquid-border fade-in fade-in-delay-2">
          <h3 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.3rem;">🎯</span> 目标定位判断
          </h3>
          <div style="color: var(--text-secondary); line-height: 1.8;">${resumeDiagnosisPlainHtml(s1Pos)}</div>
        </div>
        <div class="liquid-card fade-in fade-in-delay-3" style="border-left: 4px solid var(--accent-green);">
          <h3 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--accent-green); display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 1.3rem;">⚡</span> 30秒定论
          </h3>
          <div style="color: var(--text-secondary); font-size: 1rem; line-height: 1.8;">${resumeDiagnosisPlainHtml(s1Ver)}</div>
        </div>
      </div>
      ${resume6htmlRadarChartHtml()}
    </div>
  `;

  const panel1 = `
    <div id="resume-report-section-d2" class="tab-panel" role="tabpanel">
      <div class="float-element"></div>
      <div class="float-element"></div>
      <div class="section-header fade-in">
        <div class="section-step">Step 02</div>
        <h2 class="section-title">地毯式深度审计与指导</h2>
        <p style="color: var(--text-secondary); margin-top: 6px; font-size: 0.95rem;">${escHtml(s2Sub)}</p>
      </div>
      <div class="subsection fade-in fade-in-delay-1">
        <h3 class="subsection-title">A. 整体审计</h3>
        ${overallSection}
      </div>
      <div class="subsection fade-in fade-in-delay-2">
        <h3 class="subsection-title">B. 模块化审计</h3>
        ${modulesBlock}
        ${timelineHtml ? `<div class="liquid-card fade-item"><h3 style="font-size: 1.05rem; margin-bottom: 20px; color: var(--accent-cyan);">[ ] 工作/项目经历</h3>
          <p style="color: var(--text-secondary); margin-bottom: 20px; font-size: 0.9rem;">按时间线逐项审计（含修改前后对照示例）。</p>
          <div class="timeline">${timelineHtml}</div>
        </div>` : ""}
      </div>
    </div>
  `;

  const panel2 = `
    <div id="resume-report-section-d3" class="tab-panel" role="tabpanel">
      <div class="float-element"></div>
      <div class="float-element"></div>
      <div class="section-header fade-in">
        <div class="section-step">Step 03</div>
        <h2 class="section-title">战略性修改蓝图</h2>
      </div>
      <div class="two-col">
        <div>
          <div class="liquid-card liquid-border fade-in fade-in-delay-1">
            <h3 style="font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">🛠️</span> 影响力叙事工具箱
            </h3>
            <p style="color: var(--text-secondary); margin-bottom: 16px; font-size: 0.95rem;">${resumeDiagnosisPlainHtml(s3.left_intro || "从「研究者叙事」转向「工程师 / 推进者叙事」，用业务语言包装技术结果。")}</p>
            ${s3.formula ? `<div class="formula-box"><strong>针对 JD 的黄金公式：</strong>${resumeDiagnosisPlainHtml(s3.formula)}</div>` : ""}
            <h4 style="margin: 20px 0 12px; color: var(--text-primary); font-size: 0.95rem;">「修改前 vs 修改后」对比示例：</h4>
            ${s3Compare || `<p class="resume-report-paragraph" style="font-size:0.9rem;">暂无修改前后对照示例，可根据黄金公式自行改写一条经历。</p>`}
          </div>
        </div>
        <div>
          <div class="liquid-card fade-in fade-in-delay-2">
            <h3 style="font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">💡</span> 挖掘隐藏亮点的启发式提问
            </h3>
            <ul style="list-style: none; padding: 0; margin: 0;">${qRows || `<li class="resume-report-paragraph">暂无启发式问题，请回顾实习/项目中的协作与反馈数据。</li>`}</ul>
          </div>
          <div class="liquid-card fade-in fade-in-delay-3" style="margin-top: 20px;">
            <h3 style="font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">📊</span> 影响力思维训练
            </h3>
            <p style="color: var(--text-secondary); margin-bottom: 14px; font-size: 0.9rem;">${resumeDiagnosisPlainHtml(s3.thinking_intro || "为每个技术指标补充业务意义：它降低了什么成本、规避了什么风险、带来了什么可感知的结果。")}</p>
            <div style="padding: 18px; background: rgba(14, 165, 233, 0.08); border: 1px solid rgba(14, 165, 233, 0.2); border-radius: 10px; margin-bottom: 14px;">
              <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 8px;"><strong style="color: var(--accent-cyan);">思考路径：</strong></p>
              <p style="color: var(--text-secondary); font-size: 0.9rem; line-height: 1.7;">${resumeDiagnosisPlainHtml(s3.thinking_path || "指标 → 业务含义 → 风险/收益 → 一句话外在价值。")}</p>
            </div>
            <p style="color: var(--accent-green); font-weight: 700; font-size: 0.9rem;">${resumeDiagnosisPlainHtml(s3.action_line || "行动：为每一条技术成果补上一句「外在价值」。")}</p>
          </div>
        </div>
      </div>
    </div>
  `;

  const panel3 = `
    <div id="resume-report-section-d4" class="tab-panel" role="tabpanel">
      <div class="float-element"></div>
      <div class="float-element"></div>
      <div class="section-header fade-in">
        <div class="section-step">Step 04</div>
        <h2 class="section-title">重构与展示：修改后的简历范本</h2>
      </div>
      <div class="resume-template fade-in fade-in-delay-1">
        ${step4Inner}
      </div>
    </div>
  `;

  const panel4 = `
    <div id="resume-report-section-d5" class="tab-panel" role="tabpanel">
      <div class="float-element"></div>
      <div class="float-element"></div>
      <div class="section-header fade-in">
        <div class="section-step">Step 05</div>
        <h2 class="section-title">最终裁决与行动清单</h2>
      </div>
      <div class="two-col">
        <div>
          <div class="liquid-card fade-in fade-in-delay-1">
            <h3 style="font-size: 1.1rem; margin-bottom: 14px; color: var(--accent-cyan); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">🏆</span> 整体评价
            </h3>
            <p style="color: var(--text-secondary); font-size: 1rem; line-height: 1.8;">${resumeDiagnosisPlainHtml(s5.evaluation || "请结合前述审计结论，优先修正事实与时间线，再系统性升级叙事。")}</p>
          </div>
          <div class="liquid-card fade-in fade-in-delay-2" style="margin-top: 20px;">
            <h3 style="font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-pink); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">⚠️</span> 核心风险点
            </h3>
            ${risk1 ? `<div style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 10px; margin-bottom: 12px;">
              <p style="color: var(--text-secondary); font-size: 0.9rem; line-height: 1.7;"><span class="highlight-pink">${escHtml(r1t)}</span> ${resumeDiagnosisPlainHtml(risk1)}</p>
            </div>` : ""}
            ${risk2 ? `<div style="padding: 14px; background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.2); border-radius: 10px;">
              <p style="color: var(--text-secondary); font-size: 0.9rem; line-height: 1.7;"><span style="color: var(--accent-orange); font-weight: 700;">${escHtml(r2t)}</span> ${resumeDiagnosisPlainHtml(risk2)}</p>
            </div>` : ""}
            ${!risk1 && !risk2 ? `<p class="resume-report-paragraph">未发现单独归纳的风险条目。</p>` : ""}
          </div>
        </div>
        <div>
          <div class="liquid-card fade-in fade-in-delay-3">
            <h3 style="font-size: 1.1rem; margin-bottom: 16px; color: var(--accent-green); display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 1.3rem;">✅</span> 下一步行动清单
            </h3>
            <ul class="checklist checklist--plain">${actionRows || `<li class="resume-report-paragraph">暂无行动条目，请从修正时间线与量化指标开始。</li>`}</ul>
          </div>
        </div>
      </div>
    </div>
  `;

  return `
    <div id="${reportId}" class="resume-6html-scope resume-six-report">
      <div class="resume-6html-toolbar">
        <span class="resume-6html-kicker">简历深度审计</span>
        <div class="nav-tabs" role="tablist">
        ${tabs.map((t, index) => `
          <button type="button" class="nav-tab ${index === 0 ? "active" : ""}" role="tab" onclick="switchResumeReportSectionTab('${reportId}', ${index})">
            <span class="tab-num">${t.n}</span>${escHtml(t.label)}
          </button>
        `).join("")}
        </div>
      </div>
      <div class="resume-6html-main-area">
        ${panel0}
        ${panel1}
        ${panel2}
        ${panel3}
        ${panel4}
      </div>
    </div>
  `;
}
