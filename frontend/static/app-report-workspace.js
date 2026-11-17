// 职业报告向导、智能体控制台、生成任务与统一体验状态
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function renderReportWizard() {
  const publicationStart = document.getElementById("reportWorkflowPublishedAfter");
  if (publicationStart) publicationStart.max = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const state = getReportRuntimeState();
  const runtimeKey = state?.job_id || state?.report_id || "";
  if (runtimeKey && runtimeKey !== reportWizardUiState.runtimeKey) {
    reportWizardUiState.runtimeKey = runtimeKey;
    if (isCareerReportRunningStatus(state?.status)
      || (!reportWizardUiState.manual && !isCareerReportReadyStatus(state?.status))) reportWizardUiState.stage = 3;
    reportWizardUiState.started = true;
  }
  const stage = reportWizardUiState.stage;
  const executionTitle = document.getElementById("reportExecutionTitle");
  if (executionTitle) executionTitle.textContent = isCareerReportReadyStatus(state?.status) ? "这一站，已经为你梳理好了。"
    : state?.status === "waiting_input" ? "聊聊你的想法，再继续规划。"
    : ["failed", "canceled"].includes(state?.status) ? "进度已保留，可以接着完成。" : "Agent 团队，正在一起探索。";
  const ready = Boolean(getResumeProfileFromCache()?.file_name);
  const locked = reportGenerationStarting || reportResumeUiState.pending || resumeTaskState.uploadInFlight
    || resumeTaskState.analyzeInFlight || isCareerReportRunningStatus(state?.status);
  const panels = ["reportResumePanel", "reportWorkflowInput", "reportExecutionPanel"];
  panels.forEach((id, index) => {
    const element = document.getElementById(id);
    if (element) element.hidden = stage !== index + 1;
  });
  document.querySelectorAll("[data-report-step]").forEach((button) => {
    const step = Number(button.dataset.reportStep);
    button.disabled = step === 2 ? !ready : step === 3 ? !reportWizardUiState.started : false;
    button.classList.toggle("is-current", step === stage);
    button.classList.toggle("is-complete", step === 1 ? ready : step === 2 ? reportWizardUiState.started : isCareerReportReadyStatus(state?.status));
    if (step === stage) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  const hint = document.getElementById("reportStepResumeHint");
  if (hint) hint.textContent = ready ? "简历已准备好" : "从你的经历开始";
  const next = document.getElementById("reportResumeNext");
  if (next) next.disabled = !ready || reportResumeUiState.pending || resumeTaskState.uploadInFlight;
  const start = document.getElementById("reportStageStart");
  if (start) {
    start.disabled = locked || !ready;
    start.textContent = reportGenerationStarting ? "正在启动…" : "启动多智能体 ↗";
  }
  const primary = document.getElementById("reportLaunchBtn");
  if (primary && !reportGenerationStarting) {
    primary.disabled = stage === 1 ? !ready || reportResumeUiState.pending : locked;
    primary.textContent = isCareerReportRunningStatus(state?.status) ? "生成中…"
      : stage === 1 ? "下一步：填写目标" : stage === 2 ? "启动多智能体" : "重新设定目标";
  }
  const form = document.getElementById("reportWorkflowInput");
  if (form && !form.dataset.wizardBound) {
    form.dataset.wizardBound = "1";
    form.addEventListener("input", () => {
      reportGenerationError = "";
      const feedback = document.getElementById("reportLaunchFeedback");
      if (feedback && !reportGenerationStarting) feedback.hidden = true;
    });
  }
}

function showReportWizardStage(stage) {
  if (stage === 2 && !getResumeProfileFromCache()?.file_name) return;
  if (stage === 3 && !reportWizardUiState.started) return;
  reportWizardUiState.stage = stage;
  reportWizardUiState.manual = true;
  renderReportWizard();
  if (stage !== 3) window.ReportReview?.close();
  else renderReportWorkflowReview(getReportRuntimeState());
  const target = document.getElementById(stage === 1 ? "reportResumeSelectBtn" : stage === 2 ? "reportWorkflowTargets" : "reportStatusTitle");
  requestAnimationFrame(() => {
    if (target && stage !== 3) target.focus({ preventScroll: true });
  });
}

function reportWizardPrimaryAction() {
  if (reportWizardUiState.stage === 1) showReportWizardStage(2);
  else if (reportWizardUiState.stage === 2) void startCareerReportGeneration();
  else showReportWizardStage(getResumeProfileFromCache()?.file_name ? 2 : 1);
}

function reportAgentCurrentMessage(item, state) {
  if (["canceled", "cancelled"].includes(state?.status) && item.nodeStatus !== "done") return "本次任务已停止，进度已保留";
  if (item.nodeStatus === "skipped") return "本次没有启用招聘雷达";
  if (item.key === "review" && item.nodeStatus === "active") return "轮到你了：确认方向与时间，让规划继续";
  const activity = state?.agent_activity?.[item.key];
  if (activity?.message && item.nodeStatus !== "pending" && !(item.nodeStatus === "done" && activity.status !== "done")) return String(activity.message).slice(0, 180);
  if (item.nodeStatus === "done") return ({ resume_analysis: "经历与技能已梳理，交给职业顾问综合判断", job_analysis: "岗位要求已整理，接下来一起比较方向", recruitment_search: "机会筛选已结束，来源与待确认项已整理", career_decision: "职业方向已完成分析，进入确认与规划", review: "方向与时间已确认，开始安排下一步", action_planning: "行动与学习计划已整理，交给报告合成", report_writer: "报告已准备好，可以阅读与导出" })[item.key];
  if (item.nodeStatus === "failed") return "这一步暂未完成，可以从保存处重试";
  if (item.nodeStatus === "active") {
    if (state?.stage === item.key && state.stage_detail) return state.stage_detail;
    return ({ resume_analysis: "正在梳理你的经历与技能证据", job_analysis: "正在对照目标岗位，查找能力要求", recruitment_search: "正在筛选匹配的招聘机会", career_decision: "正在汇总各方分析，比较职业方向", action_planning: "正在安排任务、时间与交付成果", report_writer: "正在整理最终报告与参考依据" })[item.key];
  }
  return item.key === "career_decision" ? "等待前面的分析汇合，再一起判断方向" : item.key === "review" ? "分析完成后，我们会请你确认几个问题" : "等前一步准备好，就由我来接棒";
}

function getReportRuntimeState() {
  const state = typeof window.getCareerReportStateSafe === "function"
    ? (window.getCareerReportStateSafe() || null)
    : (appState.careerReportState || null);
  const status = String(state?.status || "").trim().toLowerCase();
  return ["queued", "running", "waiting_input", "ready", "completed", "failed", "error", "canceled", "cancelled"].includes(status) ? state : null;
}

function getReportProgressMap(state) {
  const map = new Map();
  const progress = Array.isArray(state?.progress) ? state.progress : [];
  progress.forEach((item) => {
    const key = String(item?.key || item?.stage || "").trim();
    if (key) map.set(key, String(item.status || "").trim().toLowerCase());
  });
  return map;
}

function reportMaLegendStatusText(nodeStatus) {
  if (nodeStatus === "waiting") return "需要你的确认";
  if (nodeStatus === "skipped") return "本次跳过";
  if (nodeStatus === "done") return "已完成";
  if (nodeStatus === "active") return "处理中";
  if (nodeStatus === "failed") return "失败";
  if (nodeStatus === "canceled") return "已停止";
  return "待启动";
}

function reportAgentPortraitHtml(item) {
  if (item.key === "review") return `<div class="report-ma-portrait report-ma-portrait--img"><img src="/static/img/multi-agent/competency-assessor.png" alt="补充与确认" decoding="async" /></div>`;
  const url = REPORT_AGENT_IMAGE_URL[item.key];
  if (url) {
    return `<div class="report-ma-portrait report-ma-portrait--img"><img src="${escHtml(url)}" alt="${escHtml(item.title)}" loading="lazy" decoding="async" /></div>`;
  }
  return `<div class="report-ma-portrait report-ma-portrait--svg">${reportAgentIconSvg(item.icon)}</div>`;
}

function reportAgentIconSvg(icon) {
  const paths = {
    profile: `<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>`,
    trend: `<path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-4 3 3 5-7"/>`,
    file: `<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/><path d="M9.5 12h5"/><path d="M9.5 16h7"/>`,
    target: `<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3"/><path d="M22 12h-3"/><path d="M12 22v-3"/><path d="M2 12h3"/>`,
    radar: `<path d="M12 3 4 20h16L12 3Z"/><path d="m12 8 3.6 8H8.4L12 8Z"/><path d="M12 3v17"/>`,
    verify: `<path d="M12 3 5 6v5c0 4.4 2.8 8.4 7 10 4.2-1.6 7-5.6 7-10V6l-7-3Z"/><path d="m8.5 12.5 2.2 2.2 4.8-5"/>`,
    match: `<path d="M8 7a4 4 0 0 1 8 0c0 4-4 7-4 7s-4-3-4-7Z"/><path d="M12 7h.01"/><path d="M5 21h14"/><path d="m7 17 10-4"/>`,
    route: `<path d="M5 6h4a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h11"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="18" r="2"/>`,
    report: `<path d="M6 3h9l3 3v15H6z"/><path d="M15 3v4h4"/><path d="M9 12h6"/><path d="M9 16h6"/><path d="M9 8h3"/>`
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[icon] || paths.report}</svg>`;
}

function getReportUserAvatarHtml() {
  const avatarState = typeof window.getAccountAvatarState === "function" ? window.getAccountAvatarState() : null;
  const imageUrl = String(avatarState?.image_url || "").trim();
  const user = typeof getCurrentUser === "function" ? getCurrentUser() : userWorkspaceState.currentUser;
  const displayName = user?.display_name || user?.displayName || user?.username || "用户";
  if (imageUrl) {
    return `<span class="report-agent-user-avatar"><img src="${escHtml(imageUrl)}" alt="${escHtml(displayName)}"></span>`;
  }
  return `<span class="report-agent-user-avatar fallback">${escHtml(displayName.charAt(0).toUpperCase() || "用")}</span>`;
}

function reportAgentConsoleResult(key) {
  const state = getReportRuntimeState();
  const snapshot = reportAgentConsoleState.snapshot;
  const report = appState.careerReport;
  const stored = report?.meta?.report_id === state?.report_id ? report?.agent_results : null;
  if (key === "review") return snapshot?.review || snapshot?.results?.action_planning?.data?.constraints || null;
  // 新账号还没有报告时 report 与 state 都为空，两个 report_id 同为 undefined 会判等，不能再取 report 的属性。
  if (key === "report_writer") return report && report.meta?.report_id === state?.report_id ? report.report_document : null;
  return snapshot?.results?.[key] || stored?.[key] || null;
}

function reportAgentConsoleSummary(item, state) {
  if (item.nodeStatus === "waiting") return "请确认目标方向与时间安排";
  const result = reportAgentConsoleResult(item.key);
  if (item.nodeStatus === "failed") return String(result?.error || state?.agent_activity?.[item.key]?.message || state?.error_message || "执行未完成，点击查看原因");
  const data = result?.data || result;
  if (item.nodeStatus === "done" && data) {
    if (typeof data.summary === "string" && data.summary) return data.summary;
    if (Array.isArray(data.targets)) return `已整理 ${data.targets.length} 个目标岗位的分析结果`;
    if (Array.isArray(data.tasks)) return `已生成 ${data.tasks.length} 项行动任务`;
    if (Array.isArray(data.assessments)) return `已完成 ${data.assessments.length} 个方向的决策评估`;
  }
  return reportAgentCurrentMessage(item, state);
}

function reportAgentMetrics(item) {
  const execution = reportAgentConsoleResult(item.key)?.execution || {};
  const unknown = "未提供";
  const seconds = execution.stage_elapsed_seconds ?? execution.elapsed_seconds;
  return [
    ["耗时", typeof seconds === "number" ? `${seconds.toFixed(1)} 秒` : unknown],
    ["模型", execution.model || (item.key === "review" ? "人工确认" : unknown)],
    ["Token", typeof execution.total_tokens === "number" ? `${execution.total_tokens}${execution.usage_status === "partial" ? "（部分）" : ""}` : unknown],
    ["工具调用", typeof execution.tool_calls === "number" ? `${execution.tool_calls} 次` : unknown]
  ];
}

function reportAgentNextStep(item) {
  if (["resume_analysis", "job_analysis", "recruitment_search"].includes(item.key)) return "三路分析汇合后交给职业决策";
  if (item.key === "career_decision") return "按决策结果进入补充确认或直接规划";
  if (item.key === "review") return "确认后复核决策，再进入行动规划";
  if (item.key === "action_planning") return "交给报告合成，整理并保存报告";
  return "前往报告中心阅读与导出";
}

function reportAgentHoverHtml(item, state) {
  return `<div class="report-agent-hover" role="tooltip"><strong>${escHtml(item.title)} · ${reportMaLegendStatusText(item.nodeStatus)}</strong><p>${escHtml(reportAgentConsoleSummary(item, state))}</p><dl>${reportAgentMetrics(item).slice(0, 2).map(([label, value]) => `<div><dt>${label}</dt><dd>${escHtml(value)}</dd></div>`).join("")}</dl><p>输入：${escHtml(REPORT_AGENT_INPUTS[item.key][0])}</p><p>下一步：${escHtml(reportAgentNextStep(item))}</p><small>点击查看完整输入、输出与执行记录</small></div>`;
}

function updateReportAgentInspectorLayout(mapEl) {
  const ui = reportAgentConsoleState;
  const expanded = Boolean(ui.selected && !ui.collapsed);
  mapEl.querySelector(".report-agent-console")?.classList.toggle("has-selection", expanded);
  const panel = mapEl.querySelector(".report-agent-inspector");
  if (panel) panel.hidden = !expanded;
  const toggle = mapEl.querySelector("[data-agent-toggle]");
  if (toggle) {
    toggle.hidden = !ui.selected;
    toggle.classList.toggle("is-collapsed", ui.collapsed);
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.setAttribute("aria-label", expanded ? "收起执行详情" : "展开执行详情");
    toggle.title = expanded ? "收起执行详情" : "展开执行详情";
    toggle.textContent = expanded ? "›" : "‹ 详情";
  }
}

function renderReportAgentInspector(mapEl) {
  const panel = mapEl.querySelector(".report-agent-inspector");
  const ui = reportAgentConsoleState;
  const item = ui.nodes.find((node) => node.key === ui.selected);
  if (!panel || !item) return;
  const focusedTab = panel.contains(document.activeElement) ? document.activeElement?.dataset?.agentTab : null;
  const scrollTop = panel.scrollTop;
  const outputScroll = panel.querySelector("pre")?.scrollTop || 0;
  const state = getReportRuntimeState();
  const result = reportAgentConsoleResult(item.key);
  const snapshot = ui.snapshot;
  const tabs = [["overview", "概览"], ["input", "输入"], ["output", "输出"], ["logs", "记录"]];
  const json = (value, empty) => value == null ? `<p class="report-inspector-empty">${empty}</p>` : `<pre>${escHtml(JSON.stringify(value, null, 2))}</pre>`;
  let content;
  if (ui.tab === "input") {
    const upstream = Object.fromEntries(REPORT_AGENT_INPUTS[item.key][1].map((key) => [key, reportAgentConsoleResult(key)]).filter(([, value]) => value != null));
    content = `<h4>输入来源</h4><p>${escHtml(REPORT_AGENT_INPUTS[item.key][0])}</p>${json(Object.keys(upstream).length ? upstream : null, "此节点的原始输入暂不可查看。")}`;
  } else if (ui.tab === "output") {
    content = `<h4>${item.nodeStatus === "waiting" ? "待确认内容" : "已保存的输出"}</h4>${json(result, item.nodeStatus === "pending" ? "尚未执行，暂无输出。" : "暂无已保存的输出，执行结果保存后可在此查看。")}`;
  } else if (ui.tab === "logs") {
    const activity = state?.agent_activity?.[item.key];
    content = `<h4>最新执行记录</h4><p>状态：${reportMaLegendStatusText(item.nodeStatus)}</p>${activity ? `<p>${escHtml(activity.updated_at || "")}</p><p>${escHtml(activity.message || "")}</p>` : `<p>暂无节点执行记录。</p>`}${result?.error ? `<p class="report-inspector-error">${escHtml(String(result.error))}</p>` : ""}${item.nodeStatus === "failed" ? json(snapshot?.errors?.length ? snapshot.errors : null, "暂无额外错误记录。") : ""}<small>这里展示服务端最新记录；完整日志流尚未接入。</small>`;
  } else {
    content = `<div class="report-inspector-summary"><span>${reportMaLegendStatusText(item.nodeStatus)}</span><p>${escHtml(reportAgentConsoleSummary(item, state))}</p></div><dl class="report-inspector-metrics">${reportAgentMetrics(item).map(([label, value]) => `<div><dt>${label}</dt><dd>${escHtml(value)}</dd></div>`).join("")}</dl><h4>输入来源</h4><p>${escHtml(REPORT_AGENT_INPUTS[item.key][0])}</p><h4>下一步</h4><p>${escHtml(reportAgentNextStep(item))}</p>`;
  }
  panel.hidden = Boolean(ui.collapsed);
  const html = `<header><div><small>AGENT 执行详情</small><h3>${escHtml(item.title)}</h3><p>${escHtml(item.detail)}</p></div><button type="button" data-agent-close aria-label="关闭执行详情">×</button></header><div class="report-inspector-tabs" role="tablist" aria-label="执行详情分类">${tabs.map(([key, title]) => `<button type="button" role="tab" data-agent-tab="${key}" aria-selected="${ui.tab === key}" aria-controls="reportAgentInspectorContent" id="reportAgentTab-${key}">${title}</button>`).join("")}</div><div class="report-inspector-content" id="reportAgentInspectorContent" role="tabpanel" aria-labelledby="reportAgentTab-${ui.tab}">${ui.loading && !ui.snapshot ? '<p class="report-inspector-loading" role="status">正在读取已保存的执行结果…</p>' : ""}${ui.error ? `<p class="report-inspector-error" role="alert">${escHtml(ui.error)}</p><button type="button" data-agent-refresh>重新读取</button>` : ""}${content}</div>${item.nodeStatus === "failed" && snapshot?.checkpoint_id && state?.status === "failed" ? `<button type="button" class="report-inspector-action" data-agent-retry ${ui.retrying ? "disabled" : ""}>${ui.retrying ? "正在恢复…" : "从已保存进度重试流程"}</button>` : item.nodeStatus === "waiting" ? '<button type="button" class="report-inspector-action" data-agent-confirm>补充信息并确认</button>' : ""}`;
  // Polls often carry no visible changes. Keep focus, scroll and DOM intact.
  if (panel._reportInspectorHtml !== html) {
    panel.innerHTML = html;
    panel._reportInspectorHtml = html;
  }
  mapEl.querySelectorAll("[data-agent-key]").forEach((node) => {
    node.classList.toggle("is-selected", node.dataset.agentKey === ui.selected);
    node.setAttribute("aria-expanded", String(node.dataset.agentKey === ui.selected && !ui.collapsed));
  });
  updateReportAgentInspectorLayout(mapEl);
  panel.scrollTop = scrollTop;
  const output = panel.querySelector("pre");
  if (output) output.scrollTop = outputScroll;
  if (focusedTab) panel.querySelector(`[data-agent-tab="${focusedTab}"]`)?.focus({ preventScroll: true });
}

async function loadReportAgentSnapshot(mapEl, force = false) {
  const ui = reportAgentConsoleState;
  const state = getReportRuntimeState();
  if (!state?.report_id || ui.loading) return;
  const version = `${state.report_id}:${state.updated_at || ""}:${state.stage}:${state.status}`;
  if (!force && ui.loadedVersion === version) return;
  const epoch = accountRequestEpoch, scope = ui.scope;
  ui.loading = true;
  ui.error = "";
  renderReportAgentInspector(mapEl);
  try {
    const snapshot = await requestJson(`/api/career-report/workflow/${encodeURIComponent(state.report_id)}`);
    if (epoch !== accountRequestEpoch || ui.scope !== scope) return;
    ui.snapshot = snapshot;
    ui.loadedVersion = version;
  } catch (error) {
    if (epoch === accountRequestEpoch && ui.scope === scope) ui.error = error.message || "读取执行结果失败";
  } finally {
    if (epoch === accountRequestEpoch && ui.scope === scope) {
      ui.loading = false;
      renderReportAgentInspector(mapEl);
      ui.nodes.forEach((item) => {
        const node = mapEl.querySelector(`[data-agent-key="${item.key}"]`);
        const speech = node?.querySelector(".report-agent-speech p");
        if (speech) speech.textContent = reportAgentConsoleSummary(item, getReportRuntimeState());
        const hover = node?.querySelector(".report-agent-hover");
        if (hover) hover.outerHTML = reportAgentHoverHtml(item, getReportRuntimeState());
      });
    }
  }
}

function applyReportAgentCamera(mapEl) {
  const world = mapEl.querySelector(".report-board-world");
  if (!world || !reportAgentCamera.initialized) return;
  const { x, y, scale } = reportAgentCamera;
  world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  world.style.visibility = "visible";
  const output = mapEl.querySelector("[data-board-scale]");
  if (output) output.textContent = `${Math.round(scale * 100)}%`;
}

function fitReportAgentBoard(mapEl) {
  const canvas = mapEl.querySelector(".report-console-canvas");
  const world = mapEl.querySelector(".report-board-world");
  if (!canvas?.clientWidth || !canvas.clientHeight || !world?.offsetHeight) return;
  const camera = reportAgentCamera;
  camera.scale = Math.min((canvas.clientWidth - 40) / world.offsetWidth, (canvas.clientHeight - 40) / world.offsetHeight, 1);
  camera.x = (canvas.clientWidth - world.offsetWidth * camera.scale) / 2;
  camera.y = (canvas.clientHeight - world.offsetHeight * camera.scale) / 2;
  camera.width = canvas.clientWidth;
  camera.height = canvas.clientHeight;
  camera.initialized = true;
  camera.autoFit = true;
  applyReportAgentCamera(mapEl);
}

function resizeReportAgentBoard(mapEl) {
  const canvas = mapEl.querySelector(".report-console-canvas");
  if (!canvas?.clientWidth || !canvas.clientHeight) return;
  const camera = reportAgentCamera;
  if (!camera.initialized || camera.autoFit) return fitReportAgentBoard(mapEl);
  // Keep the viewed area centered when the inspector opens or the window changes size.
  camera.x += (canvas.clientWidth - camera.width) / 2;
  camera.y += (canvas.clientHeight - camera.height) / 2;
  camera.width = canvas.clientWidth;
  camera.height = canvas.clientHeight;
  applyReportAgentCamera(mapEl);
}

function zoomReportAgentBoard(mapEl, factor, anchor) {
  const canvas = mapEl.querySelector(".report-console-canvas");
  if (!canvas?.clientWidth) return;
  if (!reportAgentCamera.initialized) fitReportAgentBoard(mapEl);
  const camera = reportAgentCamera;
  const nextScale = Math.max(.08, Math.min(3, camera.scale * factor));
  const x = anchor?.x ?? canvas.clientWidth / 2;
  const y = anchor?.y ?? canvas.clientHeight / 2;
  camera.x = x - (x - camera.x) * nextScale / camera.scale;
  camera.y = y - (y - camera.y) * nextScale / camera.scale;
  camera.scale = nextScale;
  camera.autoFit = false;
  applyReportAgentCamera(mapEl);
}

function bindReportAgentBoard(mapEl) {
  if (mapEl.dataset.boardBound) return;
  mapEl.dataset.boardBound = "1";
  mapEl.addEventListener("wheel", (event) => {
    const canvas = event.target.closest(".report-console-canvas");
    if (!canvas) return;
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1);
    zoomReportAgentBoard(mapEl, Math.exp(-Math.max(-600, Math.min(600, delta)) * .0015), {
      x: event.clientX - rect.left - canvas.clientLeft, y: event.clientY - rect.top - canvas.clientTop
    });
  }, { passive: false });
  mapEl.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || ![0, 1].includes(event.button) || !event.target.closest(".report-console-canvas") || event.target.closest("button, a, input, .report-agent-hover")) return;
    if (event.button === 1) event.preventDefault();
    reportAgentCamera.drag = { pointerId: event.pointerId, scope: reportAgentCamera.scope, startX: event.clientX, startY: event.clientY, x: reportAgentCamera.x, y: reportAgentCamera.y, moved: false };
  });
  window.addEventListener("pointermove", (event) => {
    const camera = reportAgentCamera, drag = camera.drag;
    if (!drag || drag.pointerId !== event.pointerId || drag.scope !== camera.scope) return;
    const dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 5) return;
    if (!drag.moved) {
      drag.moved = true;
      mapEl.setPointerCapture(event.pointerId);
    }
    event.preventDefault();
    camera.x = drag.x + dx;
    camera.y = drag.y + dy;
    camera.autoFit = false;
    mapEl.querySelector(".report-console-canvas")?.classList.add("is-panning");
    applyReportAgentCamera(mapEl);
  }, { passive: false });
  const endDrag = (event) => {
    const camera = reportAgentCamera, drag = camera.drag;
    if (!drag || (event.pointerId !== undefined && drag.pointerId !== event.pointerId)) return;
    if (drag.moved) camera.suppressClickUntil = Date.now() + 350;
    if (mapEl.hasPointerCapture(drag.pointerId)) mapEl.releasePointerCapture(drag.pointerId);
    camera.drag = null;
    mapEl.querySelector(".report-console-canvas")?.classList.remove("is-panning");
  };
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);
  window.addEventListener("blur", endDrag);
  mapEl.addEventListener("dragstart", (event) => {
    if (event.target.closest(".report-console-canvas")) event.preventDefault();
  });
  mapEl.addEventListener("click", (event) => {
    const control = event.target.closest("[data-board-action]");
    if (!control) return;
    const action = control.dataset.boardAction;
    if (action === "fit") fitReportAgentBoard(mapEl);
    else zoomReportAgentBoard(mapEl, action === "in" ? 1.2 : 1 / 1.2);
  });
  mapEl.addEventListener("keydown", (event) => {
    if (!event.target.matches(".report-console-canvas")) return;
    const camera = reportAgentCamera;
    if (["+", "=", "-", "0", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) event.preventDefault();
    if (["+", "="].includes(event.key)) zoomReportAgentBoard(mapEl, 1.2);
    else if (event.key === "-") zoomReportAgentBoard(mapEl, 1 / 1.2);
    else if (event.key === "0") fitReportAgentBoard(mapEl);
    else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      camera.x += event.key === "ArrowLeft" ? 40 : event.key === "ArrowRight" ? -40 : 0;
      camera.y += event.key === "ArrowUp" ? 40 : event.key === "ArrowDown" ? -40 : 0;
      camera.autoFit = false;
      applyReportAgentCamera(mapEl);
    }
  });
}

function bindReportAgentConsole(mapEl) {
  if (mapEl.dataset.consoleBound) return;
  mapEl.dataset.consoleBound = "1";
  let hoverTimer;
  mapEl.addEventListener("pointerover", (event) => {
    const node = event.target.closest("[data-agent-key]");
    if (!node || node.contains(event.relatedTarget)) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => {
      if (node.isConnected && node.matches(":hover")) void loadReportAgentSnapshot(mapEl);
    }, 300);
  });
  mapEl.addEventListener("focusin", (event) => {
    if (event.target.matches("[data-agent-key]")) void loadReportAgentSnapshot(mapEl);
  });
  const close = () => {
    const selected = reportAgentConsoleState.selected;
    reportAgentConsoleState.selected = "";
    reportAgentConsoleState.collapsed = false;
    updateReportAgentInspectorLayout(mapEl);
    requestAnimationFrame(() => fitReportAgentBoard(mapEl));
    const node = mapEl.querySelector(`[data-agent-key="${selected}"]`);
    node?.classList.remove("is-selected");
    node?.setAttribute("aria-expanded", "false");
    node?.focus({ preventScroll: true });
  };
  mapEl.addEventListener("click", async (event) => {
    if (event.detail && Date.now() < reportAgentCamera.suppressClickUntil) return;
    const node = event.target.closest("[data-agent-key]");
    if (node) {
      reportAgentConsoleState.selected = node.dataset.agentKey;
      reportAgentConsoleState.collapsed = false;
      reportAgentConsoleState.tab = "overview";
      mapEl.querySelector(".report-agent-console").classList.add("has-selection");
      renderReportAgentInspector(mapEl);
      requestAnimationFrame(() => resizeReportAgentBoard(mapEl));
      void loadReportAgentSnapshot(mapEl);
    } else if (event.target.closest("[data-agent-toggle]")) {
      reportAgentConsoleState.collapsed = !reportAgentConsoleState.collapsed;
      renderReportAgentInspector(mapEl);
      requestAnimationFrame(() => reportAgentConsoleState.collapsed ? fitReportAgentBoard(mapEl) : resizeReportAgentBoard(mapEl));
    } else if (event.target.closest("[data-agent-close]")) close();
    else if (event.target.closest("[data-agent-tab]")) {
      reportAgentConsoleState.tab = event.target.closest("[data-agent-tab]").dataset.agentTab;
      renderReportAgentInspector(mapEl);
      mapEl.querySelector(`[data-agent-tab="${reportAgentConsoleState.tab}"]`)?.focus({ preventScroll: true });
    } else if (event.target.closest("[data-agent-refresh]")) void loadReportAgentSnapshot(mapEl, true);
    else if (event.target.closest("[data-agent-confirm]")) window.ReportReview?.autoOpen(true);
    else if (event.target.closest("[data-agent-retry]") && !reportAgentConsoleState.retrying) {
      const snapshot = reportAgentConsoleState.snapshot, state = getReportRuntimeState();
      if (!snapshot?.checkpoint_id || state?.status !== "failed") return;
      reportAgentConsoleState.retrying = true;
      renderReportAgentInspector(mapEl);
      try {
        await submitCareerReportWorkflow({ continue_report_id: state.report_id, checkpoint_id: snapshot.checkpoint_id, response: {} });
      } catch (error) {
        reportAgentConsoleState.error = error.message || "重试失败";
      } finally {
        reportAgentConsoleState.retrying = false;
        renderReportAgentInspector(mapEl);
      }
    }
  });
  mapEl.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && reportAgentConsoleState.selected) { event.preventDefault(); close(); }
    const node = event.target.closest("[data-agent-key]");
    if (node && ["Enter", " "].includes(event.key)) { event.preventDefault(); node.click(); }
    const tab = event.target.closest("[data-agent-tab]");
    if (tab && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      const tabs = [...mapEl.querySelectorAll("[data-agent-tab]")];
      tabs[(tabs.indexOf(tab) + (event.key === "ArrowRight" ? 1 : 3)) % 4].click();
    }
  });
}

function renderReportAgentMap(profile, roles) {
  const state = getReportRuntimeState();
  const scope = `${accountRequestEpoch}:${state?.report_id || state?.job_id || "idle"}`;
  if (reportAgentConsoleState.scope !== scope) Object.assign(reportAgentConsoleState, { scope, selected: "", collapsed: false, tab: "overview", snapshot: null, loading: false, loadedVersion: "", error: "" });
  if (reportAgentCamera.scope !== scope) Object.assign(reportAgentCamera, { scope, initialized: false, autoFit: true, scale: 1, x: 0, y: 0, width: 0, height: 0, drag: null, suppressClickUntil: 0 });
  const progressMap = getReportProgressMap(state);
  const status = String(state?.status || "").trim().toLowerCase();
  const activeStage = String(state?.stage || state?.stage_key || "").trim();
  const running = ["queued", "running", "waiting_input"].includes(status);
  const completed = !running && ["ready", "done", "success", "completed"].includes(status);
  const activeIndex = REPORT_AGENT_FLOW.findIndex((item) => item.key === activeStage);
  const inputReady = Boolean(
    profile?.assessment?.mbti?.completed
    || profile?.assessment?.holland?.completed
    || profile?.resume?.status === "analyzed"
    || roles?.length
  );

  const nodes = REPORT_AGENT_FLOW.map((item, index) => {
    const keys = [item.key, ...(item.aliases || [])];
    const progressStatus = keys.map((key) => progressMap.get(key)).find(Boolean) || "";
    let nodeStatus = "pending";
    
    const isBeforeActive = activeIndex >= 0 && index < activeIndex;
    if (completed || progressStatus === "done" || (running && isBeforeActive && activeIndex >= 3)) {
      nodeStatus = "done";
    } else if (progressStatus === "failed" || (index === activeIndex && ["failed", "error"].includes(status))) {
      nodeStatus = "failed";
    } else if ((running && index === activeIndex) || progressStatus === "active") {
      nodeStatus = "active";
    }
    const activity = state?.agent_activity?.[item.key];
    if (!completed && ["queued", "running"].includes(status) && activity?.status) nodeStatus = activity.status;
    if (activity?.status === "skipped") nodeStatus = "skipped";
    if (["failed", "error", "canceled", "cancelled"].includes(status) && activity?.status === "failed") nodeStatus = "failed";
    else if (["failed", "error", "canceled", "cancelled"].includes(status) && nodeStatus === "active") nodeStatus = "pending";
    if (item.key === "review" && status === "waiting_input") nodeStatus = "waiting";
    return { ...item, nodeStatus };
  });
  const nodeHtml = nodes
    .map((item, index) => {
      const step = String(index + 1).padStart(2, "0");
      const hub = item.key === "career_decision" ? " hub" : "";
      return `
    <article class="report-agent-node report-task-card is-${escHtml(item.nodeStatus)}${hub}" data-agent-key="${escHtml(item.key)}" role="button" tabindex="0" aria-label="查看${escHtml(item.title)}执行详情" aria-expanded="${reportAgentConsoleState.selected === item.key && !reportAgentConsoleState.collapsed}">
      <div class="report-agent-identity">
      <div class="report-agent-character">
      ${reportAgentPortraitHtml(item)}
      <span class="report-agent-state-mark" aria-hidden="true">${item.nodeStatus === "done" ? "✓" : item.nodeStatus === "failed" ? "!" : item.nodeStatus === "waiting" ? "?" : item.nodeStatus === "active" ? "◔" : "○"}</span>
      <div class="report-agent-speech" role="status"><span class="report-speech-label"><i aria-hidden="true"></i>${item.nodeStatus === "skipped" ? "本次跳过" : reportMaLegendStatusText(item.nodeStatus)}</span><p>${escHtml(reportAgentConsoleSummary(item, state))}</p></div>
      </div>
      <div class="report-ma-name"><span class="report-agent-step">${step}</span>${escHtml(item.title)}</div>
      </div>
      ${reportAgentHoverHtml(item, state)}
    </article>`;
    });

  reportAgentConsoleState.nodes = nodes;
  return `<div class="report-agent-console${reportAgentConsoleState.selected && !reportAgentConsoleState.collapsed ? " has-selection" : ""}"><button type="button" class="report-inspector-toggle" data-agent-toggle aria-controls="reportAgentInspector" aria-label="执行详情" ${reportAgentConsoleState.selected ? "" : "hidden"}></button><div class="report-console-stage"><div class="report-board-header"><div class="report-lane-heading"><span>一起探索</span><p>简历、岗位与招聘机会，可以同时分析。</p><span class="report-lane-chip">并行协作</span></div><div class="report-board-toolbar" role="toolbar" aria-label="白板视图"><button type="button" data-board-action="out" aria-label="缩小白板">−</button><output data-board-scale aria-label="当前缩放比例">100%</output><button type="button" data-board-action="in" aria-label="放大白板">+</button><button type="button" data-board-action="fit" class="report-board-fit">查看全部</button></div></div><div class="report-console-canvas" tabindex="0" role="region" aria-label="智能体白板，可用滚轮缩放，拖拽移动，按 0 查看全部"><div class="report-board-world"><div class="report-collaboration-board"><div class="report-agent-origin">任务启动 · 并行分析</div><svg class="report-agent-connections" aria-hidden="true"></svg><div class="report-parallel-team">${nodeHtml.slice(0, 3).join("")}</div><div class="report-sequential-team">${nodeHtml.slice(3).join("")}</div></div></div></div><p class="report-console-help">滚轮缩放 · 拖拽移动 · 点击角色查看详情 · 查看全部可还原视图</p></div><aside id="reportAgentInspector" class="report-agent-inspector" aria-label="Agent 执行详情" ${reportAgentConsoleState.selected && !reportAgentConsoleState.collapsed ? "" : "hidden"}></aside></div>`;
}

// Keep the board, inspector and hovered cards mounted between progress polls.
function updateReportAgentMap(mapEl, profile, roles) {
  const previousScope = reportAgentConsoleState.scope;
  const html = renderReportAgentMap(profile, roles);
  if (!mapEl.querySelector(".report-agent-console") || previousScope !== reportAgentConsoleState.scope) {
    mapEl.innerHTML = html;
    return;
  }
  const template = document.createElement("template");
  template.innerHTML = html;
  template.content.querySelectorAll("[data-agent-key]").forEach((next) => {
    const current = mapEl.querySelector(`[data-agent-key="${next.dataset.agentKey}"]`);
    if (!current) return;
    const selected = next.dataset.agentKey === reportAgentConsoleState.selected;
    const className = next.className + (selected ? " is-selected" : "");
    if (current.className !== className) current.className = className;
    current.classList.toggle("is-selected", selected);
    current.setAttribute("aria-expanded", next.getAttribute("aria-expanded"));
    // Preserve the portrait and speech container so animations and hover don't restart.
    for (const selector of [".report-ma-portrait", ".report-agent-state-mark", ".report-speech-label", ".report-agent-speech p", ".report-agent-hover"]) {
      const target = current.querySelector(selector), source = next.querySelector(selector);
      if (target && source && target.innerHTML !== source.innerHTML) target.innerHTML = source.innerHTML;
    }
  });
  updateReportAgentInspectorLayout(mapEl);
}

// Draw only actual dependencies; the three analysis agents run in parallel.
function drawReportAgentConnections(mapEl) {
  const board = mapEl.querySelector(".report-collaboration-board");
  const svg = board?.querySelector(".report-agent-connections");
  if (!svg || !board.offsetWidth) return;
  const bounds = board.getBoundingClientRect();
  const scale = bounds.width / board.offsetWidth || 1;
  const width = board.offsetWidth, height = board.offsetHeight;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const edges = [
    ["resume_analysis", "career_decision"], ["job_analysis", "career_decision"],
    ["recruitment_search", "career_decision"], ["career_decision", "review"],
    ["review", "action_planning"], ["action_planning", "report_writer"]
  ];
  const point = (key) => {
    const node = board.querySelector(`[data-agent-key="${key}"]`);
    const rect = node.querySelector(".report-agent-character").getBoundingClientRect();
    return { node, x: (rect.left - bounds.left) / scale, y: (rect.top - bounds.top) / scale, w: rect.width / scale, h: rect.height / scale };
  };
  const stacked = Math.abs(point("resume_analysis").x - point("job_analysis").x) < 20;
  const origin = board.querySelector(".report-agent-origin");
  const originRect = origin.getBoundingClientRect();
  const originX = (originRect.left + originRect.width / 2 - bounds.left) / scale;
  const originY = (originRect.bottom - bounds.top) / scale;
  const branches = ["resume_analysis", "job_analysis", "recruitment_search"].map((key) => {
    const b = point(key);
    if (b.node.classList.contains("is-skipped")) return "";
    const x = b.x + b.w / 2, y = b.y - 44;
    const path = stacked ? `M ${originX} ${originY} H 2 V ${b.y + b.h / 2} H ${b.x - 6}` : `M ${originX} ${originY} V ${originY + 14} H ${x} V ${y}`;
    const dispatched = b.node.classList.contains("is-active") || b.node.classList.contains("is-done");
    return `<path class="report-agent-link${dispatched ? " is-done" : ""}" d="${path}" />`;
  }).join("");
  svg.innerHTML = branches + edges.map(([from, to]) => {
    const a = point(from), b = point(to);
    if (a.node.classList.contains("is-skipped") || b.node.classList.contains("is-skipped")) return "";
    const done = a.node.classList.contains("is-done") && (b.node.classList.contains("is-active") || b.node.classList.contains("is-done") || b.node.classList.contains("is-waiting"));
    let path;
    if (stacked && to === "career_decision") {
      const gutter = width - 8;
      path = `M ${a.x + a.w + 8} ${a.y + a.h / 2} H ${gutter} V ${b.y + b.h / 2} H ${b.x + b.w + 8}`;
    } else if (Math.abs(a.y - b.y) < 20) {
      path = `M ${a.x + a.w + 8} ${a.y + a.h / 2} H ${b.x - 8}`;
    } else {
      const startX = a.x + a.w / 2, endX = b.x + b.w / 2;
      const startY = a.y + a.h + 38, endY = b.y - 12;
      const midY = (startY + endY) / 2;
      path = `M ${startX} ${startY} V ${midY} H ${endX} V ${endY}`;
    }
    const label = to === "career_decision" ? "分析结果 → 职业决策" : from === "review" ? "确认信息 → 决策复核 → 行动规划" : from === "action_planning" ? "行动计划 → 报告整理" : "职业决策 → 补充与确认";
    return `<path class="report-agent-link${done ? " is-done" : ""}" d="${path}"><title>${label} · ${done ? "下游已开始接收" : "等待交付"}</title></path>`;
  }).join("");
}

function observeReportAgentMap(mapEl) {
  if (!reportAgentMapResizeObserver) {
    reportAgentMapResizeObserver = new ResizeObserver(() => { resizeReportAgentBoard(mapEl); drawReportAgentConnections(mapEl); });
    reportAgentMapResizeObserver.observe(mapEl);
  }
  const canvas = mapEl.querySelector(".report-console-canvas");
  if (mapEl._reportObservedCanvas) reportAgentMapResizeObserver.unobserve(mapEl._reportObservedCanvas);
  if (canvas) reportAgentMapResizeObserver.observe(canvas);
  mapEl._reportObservedCanvas = canvas;
  bindReportAgentBoard(mapEl);
  requestAnimationFrame(() => { resizeReportAgentBoard(mapEl); drawReportAgentConnections(mapEl); });
}

function renderReportWorkspace(profile, roles) {
  const safeRoles = (Array.isArray(roles) ? roles : []).filter((role) => role && role.matchSource !== "career_graph");
  const state = getReportRuntimeState();
  const status = String(state?.status || "").trim().toLowerCase();
  const running = ["queued", "running"].includes(status);
  const failed = status === "failed";
  const waiting = status === "waiting_input";
  // 检查是否有正式报告：状态为 ready/done 或 appState.reportGenerated 为 true
  const hasReport = appState.reportGenerated || isCareerReportReadyStatus(status) || Boolean(appState.careerReport);
  const selected = safeRoles.find((item) => item.id === appState.focusedRoleId) || safeRoles[0] || null;
  const statusTitle = document.getElementById("reportStatusTitle");
  const statusHint = document.getElementById("reportStatusHint");
  const generatedTime = document.getElementById("reportGeneratedTime");
  const launchBtn = document.getElementById("reportLaunchBtn");
  const cancelBtn = document.getElementById("reportCancelBtn");
  const mapEl = document.getElementById("reportAgentMap");
  const missingCount = Array.isArray(profile?.missingItems) ? profile.missingItems.length : 0;
  const focusText = selected?.name ? `当前主线岗位：${selected.name}` : "当前还没有锁定主线岗位";
  const gapCount = Array.isArray(selected?.ability?.gaps) ? selected.ability.gaps.length : 0;

  if (statusTitle) {
    statusTitle.textContent = waiting ? "等待补充与确认" : failed
      ? "多智能体流程启动失败"
      : running
        ? "多智能体正在协作"
        : status === "canceled"
          ? "本次生成已停止"
          : isCareerReportReadyStatus(status) ? "职业报告已生成" : "等待启动多智能体流程";
  }
  if (statusHint) {
    statusHint.textContent = waiting ? "下方已保存职业决策，请确认目标和时间后继续。" : failed
      ? (state?.error_message || "请检查画像输入和模型配置后重试。")
      : running
        ? (state?.stage_detail || "正在生成职业报告…")
        : status === "canceled"
          ? "旧任务已停止，不会写入报告；可以重新启动一次新的多智能体生成。"
        : isCareerReportReadyStatus(status) ? "报告已保存，可前往报告中心阅读或导出。" : missingCount
          ? `${focusText}；仍有 ${missingCount} 项画像信息可补充。`
          : "根据简历与目标方向生成职业决策，确认后生成行动计划；完成后到报告中心阅读。";
  }
  if (generatedTime) {
    generatedTime.textContent = state?.updated_at || state?.finished_at || state?.created_at || new Date().toLocaleString("zh-CN", { hour12: false });
  }
  if (launchBtn) {
    launchBtn.disabled = running;
    const isReady = isCareerReportReadyStatus(status);
    launchBtn.textContent = waiting ? "重新开始" : running
      ? "生成中"
        : (isReady || hasReport)
          ? "重新生成"
            : "启动生成";
  }
  if (cancelBtn) {
    cancelBtn.classList.toggle("hidden", !running);
    cancelBtn.disabled = !running;
  }
  const inputForm = document.getElementById("reportWorkflowInput");
  if (inputForm) inputForm.querySelectorAll("input, textarea, select").forEach((input) => { input.disabled = running; });
  renderReportResumePanel();
  renderReportWorkflowReview(state);
  if (mapEl) {
    updateReportAgentMap(mapEl, profile, safeRoles);
    observeReportAgentMap(mapEl);
    bindReportAgentConsole(mapEl);
    renderReportAgentInspector(mapEl);
    if (reportAgentConsoleState.selected) void loadReportAgentSnapshot(mapEl);
  }
  renderReportWizard();
}

function getCareerReportStateSafe() {
  return appState.careerReportState || userWorkspaceState.scopedData.career_report || null;
}

function setScopedCareerReportState(state) {
  userWorkspaceState.scopedData.career_report = state || null;
  userWorkspaceState.scopedDataLoaded.career_report = Boolean(state);
}

function isCareerReportReadyStatus(status) {
  return ["ready", "done", "success", "completed"].includes(String(status || "").trim().toLowerCase());
}

function isCareerReportRunningStatus(status) {
  return ["queued", "running"].includes(String(status || "").trim().toLowerCase());
}

function applyCareerReportRuntimeState(state) {
  if (state && typeof state === "object") {
    appState.careerReportState = state;
    setScopedCareerReportState(state);
    if (isCareerReportReadyStatus(state.status)) {
      appState.reportGenerated = true;
    } else if (!appState.careerReport) {
      appState.reportGenerated = false;
    }
  }
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  updateDashboardMetrics();
}

function mergeCareerReportStatusPayload(payload) {
  const state = payload?.state && typeof payload.state === "object" ? payload.state : {};
  const job = payload?.job && typeof payload.job === "object" ? payload.job : {};
  const jobStatus = String(job.status || "").trim().toLowerCase();
  const normalizedJobStatus = jobStatus === "completed" ? "ready" : jobStatus;
  const merged = {
    ...state,
    status: normalizedJobStatus && normalizedJobStatus !== "idle" ? normalizedJobStatus : (state.status || ""),
    job_id: job.job_id || state.job_id || "",
    report_id: job.report_id || state.report_id || "",
    stage: job.stage || state.stage || "",
    stage_label: job.stage_label || state.stage_label || "",
    stage_detail: job.stage_detail || job.message || state.stage_detail || "",
    progress: Array.isArray(job.progress) && job.progress.length ? job.progress : (Array.isArray(state.progress) ? state.progress : []),
    agent_activity: job.agent_activity && Object.keys(job.agent_activity).length ? job.agent_activity : (state.agent_activity || {}),
    generated_at: state.generated_at || "",
    updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
    model: job.model || state.model || "",
    generation_mode: job.generation_mode || state.generation_mode || "",
    focus_role_id: state.focus_role_id || appState.focusedRoleId || "",
    title: state.title || "",
    summary: state.summary || "",
    error_message: state.error_message || (normalizedJobStatus === "failed" ? job.message || "" : "")
  };
  applyCareerReportRuntimeState(merged);
  return merged;
}

/**
 * 职业报告岗位匹配章节：提交「当前聚焦岗 + 至多 4 个对照岗」（共 5 个）。
 */
function buildReportRoleRankingsForPayload(roles, focusRoleId) {
  const full = Array.isArray(roles) ? roles : [];
  const fid = String(focusRoleId || "").trim();
  const focus = full.find((r) => r && String(r.id) === fid) || full[0];
  if (!focus) return [];
  const rest = full.filter((r) => r && String(r.id) !== String(focus.id));
  return [focus, ...rest.slice(0, 4)];
}

function buildCareerReportGenerationPayload() {
  const savedProfile = userWorkspaceState.scopedData?.profile_snapshot?.profile
    && typeof userWorkspaceState.scopedData.profile_snapshot.profile === "object"
      ? userWorkspaceState.scopedData.profile_snapshot.profile
      : null;
  const savedRoles = Array.isArray(userWorkspaceState.scopedData?.career_matching?.role_rankings)
    ? userWorkspaceState.scopedData.career_matching.role_rankings.filter((role) => role && role.matchSource !== "career_graph")
    : [];
  const profile = appState.derivedProfile && typeof appState.derivedProfile === "object"
    ? appState.derivedProfile
    : (savedProfile || deriveUnifiedProfile());
  const roles = Array.isArray(appState.matchingRoles) && appState.matchingRoles.length
    ? appState.matchingRoles
    : (savedRoles.length ? savedRoles : computeRoleMatches(profile));
  if (!profile || typeof profile !== "object") return null;
  appState.derivedProfile = profile;
  appState.matchingRoles = roles;
  if (!roles.some((item) => item.id === appState.focusedRoleId)) {
    const savedFocus = String(userWorkspaceState.scopedData?.career_matching?.focus_role_id || "").trim();
    appState.focusedRoleId = roles.some((item) => item.id === savedFocus) ? savedFocus : (roles[0]?.id || "");
  }
  const focusId = String(appState.focusedRoleId || roles[0]?.id || "").trim();
  const role_rankings = buildReportRoleRankingsForPayload(roles, focusId);
  return {
    profile_snapshot: profile,
    role_rankings: role_rankings,
    focus_role_id: focusId,
    availability: {
      arrival: document.getElementById("reportWorkflowArrival")?.value || "undecided",
      days_per_week: Number(document.getElementById("reportWorkflowDays")?.value || 0)
    },
    workflow: {
      targets: String(document.getElementById("reportWorkflowTargets")?.value || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      preferences: String(document.getElementById("reportWorkflowPreferences")?.value || "").trim(),
      additional_evidence: "",
      recruitment: {
        request: `寻找近期招聘机会。目标方向：${document.getElementById("reportWorkflowTargets")?.value || ""}。求职偏好：${document.getElementById("reportWorkflowPreferences")?.value || "未额外指定"}`.slice(0, 3000),
        channel: "radar", limit: 12,
        published_after: document.getElementById("reportWorkflowPublishedAfter")?.value || null
      }
    }
  };
}

function stopCareerReportPolling() {
  if (careerReportPollTimer) {
    clearTimeout(careerReportPollTimer);
    careerReportPollTimer = null;
  }
  careerReportPollJobId = "";
}

async function loadCurrentCareerReportForMain() {
  const payload = await requestJson("/api/career-report/current");
  if (payload.state) {
    applyCareerReportRuntimeState(payload.state);
  }
  if (payload.data && payload.data.meta) {
    appState.careerReport = payload.data;
    appState.reportGenerated = Boolean(payload.data.report_document);
    appState.careerReportTracker = payload.state?.tracker || appState.careerReportTracker || null;
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
    updateDashboardMetrics();
  }
  return payload;
}

async function syncCareerReportRuntimeStatus(jobId = "") {
  const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
  const payload = await requestJson(`/api/career-report/generate/status${suffix}`);
  return mergeCareerReportStatusPayload(payload);
}

async function pollCareerReportJob(jobId) {
  const safeJobId = String(jobId || careerReportPollJobId || "").trim();
  if (!safeJobId) return null;
  stopCareerReportPolling();
  careerReportPollJobId = safeJobId;
  try {
    const state = await syncCareerReportRuntimeStatus(safeJobId);
    const followId = String(state.job_id || safeJobId || "").trim();
    if (followId) {
      careerReportPollJobId = followId;
    }
    const status = String(state.status || "").trim().toLowerCase();

    // 立即更新 UI（流程图、按钮状态等）
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);

    if (isCareerReportRunningStatus(status)) {
      careerReportPollTimer = window.setTimeout(() => {
        void pollCareerReportJob(followId || safeJobId);
      }, CAREER_REPORT_POLL_MS);
      return state;
    }
    if (isCareerReportReadyStatus(status)) {
      stopCareerReportPolling();
      await loadCurrentCareerReportForMain();
      showToast("职业报告已生成", "可前往个人中心查看。", "success", 2200);
      window.dispatchEvent(new CustomEvent("career-report:updated"));
      return state;
    }
    if (status === "failed") {
      stopCareerReportPolling();
      showToast("职业报告生成失败", state.error_message || state.stage_detail || "请检查模型配置后重试。", "error", 2600);
    } else if (status === "canceled") {
      stopCareerReportPolling();
      showToast("已停止生成", "旧任务不会写入报告，可以重新生成。", "info", 2200);
    }
    return state;
  } catch (error) {
    careerReportPollTimer = window.setTimeout(() => {
      void pollCareerReportJob(safeJobId);
    }, CAREER_REPORT_POLL_MS * 2);
    console.warn("career report status poll failed", error);
    return null;
  }
}

async function cancelCareerReportGeneration() {
  const state = getCareerReportStateSafe();
  const jobId = String(state?.job_id || careerReportPollJobId || "").trim();
  if (!jobId) {
    stopCareerReportPolling();
    applyCareerReportRuntimeState({
      ...(state || {}),
      status: "canceled",
      stage_detail: "当前没有正在生成的报告。",
      updated_at: new Date().toLocaleString("zh-CN", { hour12: false })
    });
    showToast("已停止等待", "当前没有正在生成的报告。", "warning", 2000);
    return;
  }

  const cancelBtn = document.getElementById("reportCancelBtn");
  if (cancelBtn) {
    cancelBtn.disabled = true;
    cancelBtn.textContent = "停止中";
  }
  try {
    const payload = await requestJson("/api/career-report/generate/cancel", {
      method: "POST",
      body: { job_id: jobId }
    });
    stopCareerReportPolling();
    const canceledState = mergeCareerReportStatusPayload({
      job: payload.job || { job_id: jobId, status: "canceled" },
      state: {
        ...(getCareerReportStateSafe() || {}),
        status: "canceled",
        job_id: jobId,
        stage_detail: payload.message || "用户已停止本次生成，旧任务不会写入报告。"
      }
    });
    applyCareerReportRuntimeState(canceledState);
    showToast("已停止生成", "现在可以重新启动一次新的多智能体流程。", "success", 2200);
  } catch (error) {
    showToast("停止失败", error.message || "请稍后重试。", "error", 2400);
  } finally {
    if (cancelBtn) {
      cancelBtn.textContent = "停止生成";
    }
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  }
}

async function resumeCareerReportRuntime() {
  if (!isAuthenticatedUser()) return;
  try {
    const state = await syncCareerReportRuntimeStatus();
    const jobId = String(state.job_id || "").trim();
    if (isCareerReportRunningStatus(state.status) && jobId) {
      void pollCareerReportJob(jobId);
    } else if (isCareerReportReadyStatus(state.status)) {
      void loadCurrentCareerReportForMain().catch(() => {});
    }
  } catch (error) {
    console.warn("career report status sync failed", error);
  }
}

function renderReportResumePanel(data = getResumeProfileFromCache()) {
  const panel = document.getElementById("reportResumePanel");
  if (!panel) return;
  const hasFile = Boolean(data?.file_name);
  const ready = hasFile;
  const running = isCareerReportRunningStatus(getCareerReportStateSafe()?.status);
  const busy = reportResumeUiState.pending || resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight;
  const locked = running || busy || reportGenerationStarting;
  const title = document.getElementById("reportResumeFileName");
  const meta = document.getElementById("reportResumeFileMeta");
  const badge = document.getElementById("reportResumeStatus");
  const hint = document.getElementById("reportResumeHint");
  const select = document.getElementById("reportResumeSelectBtn");
  const input = document.getElementById("reportResumeFileInput");
  panel.dataset.state = reportResumeUiState.error ? "error" : busy ? "busy" : ready ? "ready" : "empty";
  panel.setAttribute("aria-busy", String(busy));
  if (title) title.textContent = hasFile ? (data.original_file_name || data.file_name) : "选择简历文件，或拖拽到这里";
  if (meta) meta.textContent = hasFile
    ? `${String(data.file_type || "文件").toUpperCase()} · ${(Number(data.file_size || 0) / 1024).toFixed(0)} KB`
    : "支持 PDF、DOCX，单个文件不超过 12 MB。";
  if (badge) badge.textContent = busy ? (reportResumeUiState.phase || "正在处理") : ready ? "已上传" : "未上传";
  if (hint) hint.textContent = reportResumeUiState.error || (busy
    ? "当前任务正在处理，请稍候。"
    : ready ? "简历已准备好。点击下一步，填写目标与偏好。"
    : "先上传简历，再填写目标岗位，点击“启动生成”开始多智能体分析。");
  if (select) { select.disabled = locked; select.textContent = hasFile ? "更换简历" : "上传简历"; }
  if (input) input.disabled = locked;
  document.getElementById("reportWorkflowInput")?.querySelectorAll("input, textarea, select").forEach((field) => {
    field.disabled = running || reportGenerationStarting;
  });
  const launch = document.getElementById("reportLaunchBtn");
  if (launch) {
    launch.disabled = locked || !hasFile;
    launch.title = !hasFile ? "请先在下方上传简历" : busy ? "当前任务正在处理，请稍候" : "使用当前简历启动多智能体分析";
    if (reportGenerationStarting) launch.textContent = "正在启动";
  }
  const feedback = document.getElementById("reportLaunchFeedback");
  if (feedback) {
    feedback.hidden = !reportGenerationStarting && !reportGenerationError;
    feedback.dataset.state = reportGenerationError ? "error" : "starting";
    feedback.textContent = reportGenerationError
      ? `启动失败：${reportGenerationError}`
      : "正在提交简历和分析目标，等待创建任务…";
  }
  if (reportGenerationStarting || reportGenerationError) {
    const statusTitle = document.getElementById("reportStatusTitle");
    const statusHint = document.getElementById("reportStatusHint");
    if (statusTitle) statusTitle.textContent = reportGenerationError ? "多智能体流程未启动" : "正在启动多智能体流程";
    if (statusHint) statusHint.textContent = reportGenerationError || "正在提交简历和分析目标，任务创建后将在下方显示执行进度。";
  }
  renderReportWizard();
}

async function refreshReportResumePanel(force = true) {
  if (reportResumeUiState.pending) return;
  try {
    const data = await loadResumeProfile(force);
    if (data.file_name) reportResumeUiState.error = "";
    renderReportResumePanel(data);
  } catch (error) {
    if (error.code === "ACCOUNT_CHANGED") return;
    reportResumeUiState.error = error.message || "简历状态加载失败，请刷新页面重试。";
    renderReportResumePanel();
  }
}

function pickReportResumeFile() {
  if (!isAuthenticatedUser()) return showToast("请先登录", "请登录后上传简历。", "warning", 2000);
  if (!reportResumeUiState.pending && !resumeTaskState.uploadInFlight && !resumeTaskState.analyzeInFlight && !reportGenerationStarting && !isCareerReportRunningStatus(getCareerReportStateSafe()?.status)) {
    document.getElementById("reportResumeFileInput")?.click();
  }
}

async function uploadReportResumeFile(file) {
  if (!file) return;
  if (!isAuthenticatedUser()) return showToast("请先登录", "请登录后上传简历。", "warning", 2000);
  if (reportResumeUiState.pending || resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight || reportGenerationStarting || isCareerReportRunningStatus(getCareerReportStateSafe()?.status)) {
    return showToast("请稍候", "当前有上传或分析任务正在进行，请完成后再更换简历。", "warning", 2500);
  }
  if (!/\.(pdf|docx)$/i.test(file.name) || file.size <= 0 || file.size > 12 * 1024 * 1024) {
    reportResumeUiState.error = "请选择不超过 12 MB 的非空 PDF 或 DOCX 简历文件。";
    renderReportResumePanel();
    return;
  }
  const epoch = accountRequestEpoch;
  reportResumeUiState.pending = true;
  reportResumeUiState.error = "";
  reportResumeUiState.phase = "上传中";
  resumeTaskState.uploadInFlight = true;
  updateResumeActionButtons();
  try {
    const body = new FormData();
    body.append("file", file);
    const payload = await requestJson("/api/resume/upload", { method: "POST", body });
    const uploaded = payload.data || emptyResumeProfile();
    userWorkspaceState.scopedData.resume_profile = uploaded;
    userWorkspaceState.scopedDataLoaded.resume_profile = true;
    renderResumeProfileSection(uploaded);
    showToast("上传成功", "文件已保存。点击“启动生成”，由现有分析流程读取并分析简历。", "success", 2800);
    refreshUnifiedExperience();
  } catch (error) {
    if (error.code !== "ACCOUNT_CHANGED" && epoch === accountRequestEpoch) {
      reportResumeUiState.error = error.message || "简历上传失败，请重试。";
      showToast("简历上传失败", reportResumeUiState.error, "error", 3200);
    }
  } finally {
    if (epoch === accountRequestEpoch) {
      reportResumeUiState.pending = false;
      reportResumeUiState.phase = "";
      resumeTaskState.uploadInFlight = false;
      updateResumeActionButtons();
    }
  }
}

async function onReportResumeSelected(event) {
  try { await uploadReportResumeFile(event?.target?.files?.[0]); }
  finally { if (event?.target) event.target.value = ""; }
}

function onReportResumeDrop(event) {
  event.preventDefault();
  event.currentTarget?.classList.remove("is-dragging");
  if (event.dataTransfer?.files?.length !== 1) return showToast("请选择一个文件", "一次上传一份用于当前分析的简历。", "warning", 2000);
  void uploadReportResumeFile(event.dataTransfer.files[0]);
}

async function startCareerReportGeneration() {
  if (!document.getElementById("reportWorkflowInput")) {
    window.location.href = "/#report";
    return;
  }
  if (!isAuthenticatedUser()) {
    showToast("请先登录", "请登录后生成职业报告。", "warning", 1800);
    return;
  }
  if (reportWizardUiState.stage !== 2) {
    showReportWizardStage(getResumeProfileFromCache()?.file_name ? 2 : 1);
    return;
  }
  if (reportGenerationStarting || reportResumeUiState.pending || resumeTaskState.uploadInFlight || resumeTaskState.analyzeInFlight || isCareerReportRunningStatus(getCareerReportStateSafe()?.status)) {
    return showToast("请稍候", "简历或报告任务正在执行中。", "warning", 2000);
  }
  if (document.getElementById("reportWorkflowInput")?.reportValidity?.() === false) return;
  const payload = buildCareerReportGenerationPayload();
  if (!payload) {
    showSection("profile");
    showToast("画像或岗位数据不足", "请先完成画像，再启动职业报告。", "warning", 2400);
    return;
  }

  const epoch = accountRequestEpoch;
  reportGenerationError = "";
  reportGenerationStarting = true;
  const launchBtn = document.getElementById("reportLaunchBtn");
  if (launchBtn) {
    launchBtn.disabled = true;
    launchBtn.textContent = "启动中";
  }
  renderReportResumePanel();

  try {
    if (!payload.workflow.targets.length || payload.workflow.targets.length > 5) {
      throw new Error("请填写 1 到 5 个目标岗位或方向，每行一个。");
    }
    const resume = await loadResumeProfile(true);
    if (!resume.file_name) {
      showReportWizardStage(1);
      document.getElementById("reportResumePanel")?.scrollIntoView({ behavior: "smooth", block: "center" });
      throw new Error("请先在上方上传 PDF 或 DOCX 简历。");
    }
    await submitCareerReportWorkflow(payload);
  } catch (error) {
    if (error.code !== "ACCOUNT_CHANGED" && epoch === accountRequestEpoch) {
      reportGenerationError = error.message || "请稍后重试。";
      showToast("启动失败", reportGenerationError, "error", 3200);
    }
  } finally {
    if (epoch === accountRequestEpoch) {
      reportGenerationStarting = false;
      renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
    }
  }
}

async function submitCareerReportWorkflow(payload) {
  const result = await requestJson("/api/career-report/generate/start", { method: "POST", body: payload });
  reportGenerationError = "";
  window.ReportReview?.reset();
  reportWorkflowSnapshot = null;
  reportWizardUiState.stage = 3;
  reportWizardUiState.started = true;
  reportWizardUiState.manual = false;
  applyCareerReportRuntimeState({ status: "queued", job_id: result.job_id, report_id: result.report_id,
    stage: "resume_analysis", stage_detail: "任务已提交，正在执行 Agent。", progress: [] });
  void pollCareerReportJob(result.job_id);
}

function renderReportWorkflowReview(state) {
  const container = document.getElementById("reportWorkflowReview");
  if (!container) return;
  const reportId = String(state?.report_id || "");
  const visible = ["waiting_input", "failed"].includes(state?.status) && reportId;
  container.classList.toggle("hidden", !visible);
  if (!visible) { window.ReportReview?.close(); return; }
  const active = reportWizardUiState.stage === 3 && !document.getElementById("report")?.classList.contains("hidden");
  if (reportWorkflowSnapshot?.reportId === reportId) {
    window.ReportReview?.autoOpen(active && state.status === "waiting_input");
    return;
  }
  if (reportWorkflowLoading === reportId) return;
  reportWorkflowLoading = reportId;
  const epoch = accountRequestEpoch;
  container.textContent = "正在读取已保存的分析结果…";
  requestJson(`/api/career-report/workflow/${encodeURIComponent(reportId)}`).then((snapshot) => {
    if (epoch !== accountRequestEpoch || getCareerReportStateSafe()?.report_id !== reportId) return;
    reportWorkflowSnapshot = { ...snapshot, reportId };
    const review = snapshot.review;
    if (!review) {
      container.innerHTML = `<p>执行进度已保存，可重试失败步骤。</p><button type="button" class="report-launch-primary" onclick="continueCareerReportWorkflow()">${snapshot.complete ? "重试报告整理" : "从保存处重试"}</button>`;
      return;
    }
    window.ReportReview.mount(container, reportWorkflowSnapshot, {
      onSubmit: continueCareerReportWorkflow,
      active: reportWizardUiState.stage === 3 && !document.getElementById("report")?.classList.contains("hidden") && getCareerReportStateSafe()?.status === "waiting_input"
    });
  }).catch((error) => {
    if (epoch === accountRequestEpoch) container.textContent = error.message || "读取失败，请刷新页面重试。";
  }).finally(() => { if (epoch === accountRequestEpoch) reportWorkflowLoading = ""; });
}

async function continueCareerReportWorkflow(response = {}) {
  const snapshot = reportWorkflowSnapshot;
  if (!snapshot) return false;
  const container = document.getElementById("reportWorkflowReview");
  const epoch = accountRequestEpoch;
  const buttons = container.querySelectorAll("button");
  buttons.forEach((button) => { button.disabled = true; });
  try {
    await submitCareerReportWorkflow({ continue_report_id: snapshot.reportId, checkpoint_id: snapshot.checkpoint_id, response });
    return true;
  } catch (error) {
    if (error.code === "ACCOUNT_CHANGED" || epoch !== accountRequestEpoch) return false;
    const message = error.message || "请稍后重试。";
    showToast("继续失败", message, "error", 3600);
    window.ReportReview?.showError(message);
    if (String(error.message || "").includes("刷新")) reportWorkflowSnapshot = null;
    return false;
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

function refreshUnifiedExperience() {
  if (unifiedRefreshRunning) {
    unifiedRefreshPending = true;
    return;
  }
  if (unifiedRefreshScheduled) return;
  unifiedRefreshScheduled = true;
  const runner = () => {
    unifiedRefreshScheduled = false;
    unifiedRefreshRunning = true;
    try {
      refreshUnifiedExperienceNow();
    } finally {
      unifiedRefreshRunning = false;
      if (unifiedRefreshPending) {
        unifiedRefreshPending = false;
        refreshUnifiedExperience();
      }
    }
  };
  if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(runner);
  } else {
    setTimeout(runner, 0);
  }
}

function buildProfileSnapshotScope(profile) {
  return {
    version: "2026.04-profile-snapshot-v1",
    updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
    source: "unified_experience",
    profile: profile && typeof profile === "object" ? profile : null
  };
}

function buildCareerMatchingScope(profile, roles) {
  const role_rankings = Array.isArray(roles) ? roles : [];
  const scoped = userWorkspaceState.scopedData?.career_matching;
  const focusFallback = String(
    appState.focusedRoleId || role_rankings[0]?.id || scoped?.focus_role_id || ""
  ).trim();
  return {
    version: "2026.04-career-matching-v1",
    updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
    source: "unified_experience",
    focus_role_id: focusFallback,
    profile_summary: String(profile?.summary || "").trim(),
    role_rankings: role_rankings
  };
}

async function persistUnifiedExperienceState(profile, roles) {
  if (!isAuthenticatedUser()) return;
  try {
    await Promise.allSettled([
      saveScopedUserState("profile_snapshot", buildProfileSnapshotScope(profile)),
      mergeScopedUserState("career_matching", buildCareerMatchingScope(profile, roles))
    ]);
  } catch (error) {
    console.warn("persist unified experience failed", error);
  }
}

function applyUnifiedExperienceState(profile, roles, options = {}) {
  const safeProfile = profile && typeof profile === "object" ? profile : deriveUnifiedProfile();
  const safeRoles = (Array.isArray(roles) ? roles : []).filter((role) => role && role.matchSource !== "career_graph");
  const requestedFocusRoleId = String(options.focusRoleId || "").trim();

  appState.derivedProfile = safeProfile;
  appState.matchingRoles = safeRoles;
  if (safeRoles.some((item) => item.id === requestedFocusRoleId)) {
    appState.focusedRoleId = requestedFocusRoleId;
  } else if (!safeRoles.some((item) => item.id === appState.focusedRoleId)) {
    appState.focusedRoleId = safeRoles[0]?.id || "";
  }
  appState.profileCompletion = Math.round(
    (safeProfile.assessment?.mbti?.completed ? 15 : 0)
    + (safeProfile.assessment?.holland?.completed ? 15 : 0)
    + (PROFILE_BASIC_FIELDS.filter((key) => safeProfile.basics?.[key]).length / PROFILE_BASIC_FIELDS.length) * 30
    + clampPercent(safeProfile.interview?.completionScore) * 0.3
    + (safeProfile.resume?.status === "analyzed" ? 10 : 0)
  );
  appState.profileComplete = Boolean(
    safeProfile.assessment?.mbti?.completed
    && safeProfile.assessment?.holland?.completed
    && PROFILE_BASIC_FIELDS.every((key) => safeProfile.basics?.[key])
  );
  appState.score = safeRoles[0]?.overallScore || safeRoles[0]?.trait?.score || appState.profileCompletion;

  renderProfileWorkspace(safeProfile, safeRoles);
  renderReportWorkspace(safeProfile, safeRoles);
  updateDashboardMetrics();

  if (options.persist) {
    void persistUnifiedExperienceState(safeProfile, safeRoles);
  }
}

function restoreUnifiedExperienceFromSavedScopes() {
  const profileScope = userWorkspaceState.scopedData?.profile_snapshot;
  const matchingScope = userWorkspaceState.scopedData?.career_matching;
  const profile = profileScope && typeof profileScope === "object" && profileScope.profile && typeof profileScope.profile === "object"
    ? profileScope.profile
    : null;
  const roles = matchingScope && typeof matchingScope === "object" && Array.isArray(matchingScope.role_rankings)
    ? matchingScope.role_rankings.filter((role) => role && role.matchSource !== "career_graph")
    : [];
  const focusRoleId = matchingScope && typeof matchingScope === "object"
    ? String(matchingScope.focus_role_id || "").trim()
    : "";
  if (!profile && !roles.length) return false;
  applyUnifiedExperienceState(profile || deriveUnifiedProfile(), roles, { focusRoleId, persist: false });
  return true;
}

function refreshUnifiedExperienceNow() {
  const profile = deriveUnifiedProfile();
  const roles = computeRoleMatches(profile);
  profile.recommendedRoles = uniqueValues([...profile.recommendedRoles, ...roles.slice(0, 3).map((item) => item.name)], 6);
  profile.nextSteps = uniqueValues([...profile.nextSteps, ...(roles[0]?.nextActions || [])], 6);
  profile.moduleStates = buildAgentModuleStates(profile, roles);
  applyUnifiedExperienceState(profile, roles, { persist: true });
}
