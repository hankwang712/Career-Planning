(function () {
  const REPORT_POLL_INTERVAL_MS = 1800;
  const PLAN_STORAGE_PREFIX = "dp_overlay_plans_v1_";
  const PLAN_PROGRESS_PREFIX = "dp_plan_progress_v1_";
  const DEFAULT_STAGE_PROGRESS = [
    { key: "profile_fusion", label: "画像融合", status: "pending" },
    { key: "role_retrieval", label: "目标职业提取", status: "pending" },
    { key: "trend_intelligence", label: "趋势情报提炼", status: "pending" },
    { key: "gap_analysis", label: "差距分析", status: "pending" },
    { key: "stage_planning", label: "阶段规划", status: "pending" },
    { key: "report_writer", label: "报告撰写", status: "pending" },
    { key: "critic", label: "一致性校验", status: "pending" }
  ];

  const reportRuntime = {
    pollTimer: 0,
    renderQueued: false,
    planWrapped: false,
    eventsBound: false,
    previousBodyOverflow: ""
  };

  const avatarRuntime = {
    username: "",
    state: null
  };

  function ensureAppState() {
    if (!window.appState || typeof window.appState !== "object") {
      window.appState = {};
    }
    Object.assign(window.appState, {
      careerReport: window.appState.careerReport || null,
      careerReportState: window.appState.careerReportState || null,
      careerReportTracker: window.appState.careerReportTracker || null,
      careerReportVersions: Array.isArray(window.appState.careerReportVersions) ? window.appState.careerReportVersions : [],
      careerReportCanonicalId: String(window.appState.careerReportCanonicalId || "").trim(),
      careerReportViewingHistorical: Boolean(window.appState.careerReportViewingHistorical),
      reportGenerated: Boolean(window.appState.reportGenerated),
      reportReady: Boolean(window.appState.reportReady)
    });
  }

  function esc(value) {
    if (typeof window.escHtml === "function") return window.escHtml(value);
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatText(value) {
    return esc(String(value || "").trim()).replace(/\n/g, "<br>");
  }

  function escapeSelectorId(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
      return CSS.escape(value);
    }
    return String(value || "").replace(/[^a-zA-Z0-9_-]+/g, "\\$&");
  }

  function toast(title, text = "", tone = "info", duration = 2200) {
    if (typeof window.showToast === "function") {
      window.showToast(title, text, tone, duration);
    }
  }

  function currentUser() {
    if (typeof window.getCurrentUser === "function") return window.getCurrentUser();
    return null;
  }

  function isAuthenticated() {
    if (typeof window.isAuthenticatedUser === "function") return window.isAuthenticatedUser();
    return Boolean(currentUser());
  }

  function resolveUrl(path) {
    if (typeof window.resolveApiUrl === "function") {
      return window.resolveApiUrl(path);
    }
    return String(path || "");
  }

  async function requestJsonSafe(path, options = {}) {
    if (typeof window.requestJson === "function") {
      return window.requestJson(path, options);
    }

    const method = String(options.method || "GET").toUpperCase();
    const headers = { ...(options.headers || {}) };
    const init = {
      method,
      headers,
      credentials: options.credentials || "include"
    };

    if (options.body !== undefined) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
      init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
    }

    const response = await fetch(resolveUrl(path), init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.message || `请求失败：${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function scheduleRender(withUserCenterRefresh = false) {
    if (reportRuntime.renderQueued) return;
    reportRuntime.renderQueued = true;
    const run = () => {
      reportRuntime.renderQueued = false;
      renderCareerReportPanels();
      if (withUserCenterRefresh && typeof window.renderUserCenterDashboard === "function") {
        window.renderUserCenterDashboard();
      }
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 0);
    }
  }

  function setScopedCareerReportState(state) {
    if (!window.userWorkspaceState || typeof window.userWorkspaceState !== "object") return;
    if (!window.userWorkspaceState.scopedData || typeof window.userWorkspaceState.scopedData !== "object") return;
    window.userWorkspaceState.scopedData.career_report = state || null;
    if (window.userWorkspaceState.scopedDataLoaded && typeof window.userWorkspaceState.scopedDataLoaded === "object") {
      window.userWorkspaceState.scopedDataLoaded.career_report = Boolean(state);
    }
  }

  function getCareerReportStateSafe() {
    ensureAppState();
    return window.appState.careerReportState || window.userWorkspaceState?.scopedData?.career_report || null;
  }

  function getCareerReportTracker() {
    ensureAppState();
    const scopedTracker = getCareerReportStateSafe()?.tracker;
    return window.appState.careerReportTracker || scopedTracker || null;
  }

  function normalizeVersions(tracker, bundle) {
    const trackerVersions = Array.isArray(tracker?.versions) ? tracker.versions : [];
    const versions = trackerVersions.slice();
    const reportId = String(bundle?.meta?.report_id || "").trim();
    if (reportId && !versions.some((item) => String(item?.report_id || "").trim() === reportId)) {
      versions.unshift({
        report_id: reportId,
        title: bundle?.meta?.title || "职业规划报告",
        generated_at: bundle?.meta?.generated_at || "",
        focus_role_id: bundle?.meta?.focus_role_id || "",
        focus_role_name: bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || "",
        version: bundle?.meta?.version || ""
      });
    }
    return versions;
  }

  function applyCareerReportState(bundle, tracker, state, options = {}) {
    ensureAppState();

    if (state && typeof state === "object") {
      window.appState.careerReportState = state;
      setScopedCareerReportState(state);
    } else if (state === null && !options.keepState) {
      window.appState.careerReportState = null;
      setScopedCareerReportState(null);
    }

    if (tracker && typeof tracker === "object") {
      window.appState.careerReportTracker = tracker;
    } else if (tracker === null && !options.keepTracker) {
      window.appState.careerReportTracker = null;
    }

    if (bundle && typeof bundle === "object" && bundle.meta) {
      window.appState.careerReport = bundle;
      window.appState.reportReady = Boolean(bundle.report_document);
      window.appState.reportGenerated = Boolean(bundle.report_document);
      if (!options.historical && bundle.meta.focus_role_id) {
        window.appState.focusedRoleId = String(bundle.meta.focus_role_id || "").trim();
      }
    } else if (bundle === null && !options.keepBundle) {
      window.appState.careerReport = null;
      window.appState.reportReady = false;
      window.appState.reportGenerated = false;
    }

    const resolvedTracker = window.appState.careerReportTracker || tracker || state?.tracker || null;
    window.appState.careerReportVersions = normalizeVersions(resolvedTracker, window.appState.careerReport);

    const canonicalId = String(
      options.canonicalReportId
      || window.appState.careerReportCanonicalId
      || state?.report_id
      || resolvedTracker?.report_id
      || window.appState.careerReport?.meta?.report_id
      || ""
    ).trim();
    window.appState.careerReportCanonicalId = canonicalId;
    window.appState.careerReportViewingHistorical = Boolean(options.historical);
    scheduleRender(Boolean(options.userCenterRefresh));
  }

  function primeCareerReportStateFromBootstrap() {
    const scoped = window.userWorkspaceState?.scopedData?.career_report;
    if (!scoped || typeof scoped !== "object") return;
    applyCareerReportState(undefined, scoped.tracker || null, scoped, {
      keepBundle: true,
      userCenterRefresh: false
    });
  }

  function stopCareerReportPolling() {
    if (reportRuntime.pollTimer) {
      clearTimeout(reportRuntime.pollTimer);
      reportRuntime.pollTimer = 0;
    }
  }

  async function loadCurrentCareerReport(options = {}) {
    const payload = await requestJsonSafe("/api/career-report/current");
    applyCareerReportState(payload.data || null, payload.state?.tracker || null, payload.state || null, {
      historical: false,
      canonicalReportId: payload.data?.meta?.report_id || payload.state?.report_id || "",
      userCenterRefresh: options.userCenterRefresh !== false
    });
    return payload;
  }

  async function syncCareerReportStatus(jobId = "") {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
    const payload = await requestJsonSafe(`/api/career-report/generate/status${suffix}`);
    applyCareerReportState(undefined, payload.state?.tracker || null, payload.state || null, {
      keepBundle: true,
      historical: window.appState?.careerReportViewingHistorical,
      userCenterRefresh: true
    });
    return payload;
  }

  async function pollCareerReportJob(jobId) {
    stopCareerReportPolling();
    if (!jobId) return;

    try {
      const payload = await syncCareerReportStatus(jobId);
      const status = String(payload.state?.status || payload.job?.status || "").trim().toLowerCase();
      if (status === "queued" || status === "running") {
        reportRuntime.pollTimer = setTimeout(() => {
          void pollCareerReportJob(jobId);
        }, REPORT_POLL_INTERVAL_MS);
        return;
      }
      if (status === "ready") {
        await loadCurrentCareerReport({ userCenterRefresh: true });
        toast("职业报告已完成", "新的报告版本已经生成并同步到报告中心。", "success", 2200);
        return;
      }
      if (status === "failed") {
        toast("职业报告生成失败", payload.state?.error_message || "请稍后重试。", "error", 2600);
      }
    } catch (error) {
      reportRuntime.pollTimer = setTimeout(() => {
        void pollCareerReportJob(jobId);
      }, REPORT_POLL_INTERVAL_MS * 2);
      console.warn("career report status poll failed", error);
    }
  }

  function getCareerReportVersionList() {
    ensureAppState();
    return {
      versions: Array.isArray(window.appState.careerReportVersions) ? window.appState.careerReportVersions : [],
      reportState: getCareerReportStateSafe(),
      canonicalReportId: String(window.appState.careerReportCanonicalId || "").trim()
    };
  }

  function getDefaultStageProgress() {
    return DEFAULT_STAGE_PROGRESS.map((item) => ({ ...item }));
  }

  function renderReportProgressCards(progress) {
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    return `
      <div class="career-report-stage-board">
        ${items.map((item) => {
          const isActive = item.status === "active" || item.status === "running";
          const statusText = item.status === "done"
            ? "已完成"
            : isActive
              ? "进行中"
              : item.status === "failed"
                ? "失败"
                : "待处理";
          return `
            <article class="career-report-stage-card${isActive ? " active" : ""}">
              <span>${esc(statusText)}</span>
              <strong>${esc(item.label || item.key || "阶段")}</strong>
            </article>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderMetricRow(metrics) {
    if (!Array.isArray(metrics) || !metrics.length) return "";
    return `
      <div class="career-report-metric-row">
        ${metrics.map((item) => `
          <div class="career-report-mini-metric">
            <span>${esc(item.label || "指标")}</span>
            <strong>${esc(item.value || "--")}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderVisualization(visualization) {
    if (!visualization || typeof visualization !== "object") return "";
    const type = String(visualization.type || "").trim();
    const items = Array.isArray(visualization.items) ? visualization.items : [];
    if (!items.length) return "";

    if (type === "score-bars") {
      return `
        <div class="career-report-viz">
          ${items.map((item) => {
            const value = Math.max(0, Math.min(100, Number(item.value || 0)));
            return `
              <div class="career-report-score-row">
                <div class="career-report-score-meta">
                  <strong>${esc(item.label || "候选方向")}</strong>
                  <span>${esc(item.hint || "")}</span>
                </div>
                <div class="career-report-score-track">
                  <div class="career-report-score-fill" style="width:${value}%"></div>
                </div>
                <em>${value}%</em>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    if (type === "gap-matrix") {
      return `
        <div class="career-report-viz career-report-gap-grid">
          ${items.map((item) => `
            <article class="career-report-gap-card">
              <span>${esc(item.status || "差距项")}</span>
              <strong>${esc(item.label || "能力维度")}</strong>
              <em>${esc(`${Number(item.current || 0)}/${Number(item.required || 0)}`)}</em>
            </article>
          `).join("")}
        </div>
      `;
    }

    if (type === "timeline") {
      return `
        <div class="career-report-viz career-report-timeline">
          ${items.map((item) => `
            <article class="career-report-timeline-item">
              <span>${esc(item.label || item.phase || "阶段")}</span>
              <strong>${esc(item.title || "行动阶段")}</strong>
              <p>${formatText(item.summary || "")}</p>
            </article>
          `).join("")}
        </div>
      `;
    }

    if (type === "signal-cards") {
      return `
        <div class="career-report-viz career-report-signal-grid">
          ${items.map((item) => `
            <article class="career-report-signal-card">
              <span>${esc(item.source || item.label || "趋势信号")}</span>
              <strong>${esc(item.title || item.label || "观察点")}</strong>
              <p>${formatText(item.summary || item.body || item.hint || "")}</p>
            </article>
          `).join("")}
        </div>
      `;
    }

    return `
      <div class="career-report-viz career-report-signal-grid">
        ${items.map((item) => `
          <article class="career-report-signal-card">
            <span>${esc(item.label || item.phase || "信息")}</span>
            <strong>${esc(item.title || "内容")}</strong>
            <p>${formatText(item.summary || item.body || "")}</p>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderCardGrid(cards) {
    if (!Array.isArray(cards) || !cards.length) return "";
    return `
      <div class="career-report-card-grid">
        ${cards.map((card) => `
          <article class="career-report-content-card tone-${esc(card.tone || "indigo")}">
            <div class="career-report-content-top">
              <h4>${esc(card.title || "内容卡片")}</h4>
              <span>${esc(card.confidence || card.score || "信息")}</span>
            </div>
            <p>${formatText(card.body || "")}</p>
            ${(Array.isArray(card.tags) && card.tags.length) ? `
              <div class="career-report-content-meta">
                <div class="career-report-chip-row">
                  ${card.tags.slice(0, 8).map((item) => `<span class="career-report-chip">${esc(item)}</span>`).join("")}
                </div>
                ${(Array.isArray(card.evidence_sources) && card.evidence_sources.length) ? `
                  <div class="career-report-chip-row">
                    ${card.evidence_sources.slice(0, 4).map((item) => `<span class="career-report-chip">${esc(item)}</span>`).join("")}
                  </div>
                ` : ""}
              </div>
            ` : ""}
          </article>
        `).join("")}
      </div>
    `;
  }

  function getReportSectionDomId(section, index) {
    const raw = String(section?.id || `section-${index + 1}`).trim() || `section-${index + 1}`;
    return `career-report-section-${raw.replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
  }

  function renderReportSections(bundle) {
    const sections = Array.isArray(bundle?.report_document?.sections) ? bundle.report_document.sections : [];
    if (!sections.length) {
      return `
        <div class="career-report-empty-grid">
          <article class="career-report-empty-card">
            <strong>报告结构尚未就绪</strong>
            <p>当前版本缺少可展示的报告章节，请重新生成职业报告。</p>
          </article>
        </div>
      `;
    }

    return `
      <div class="career-report-sections">
        ${sections.map((section, index) => `
          <section id="${getReportSectionDomId(section, index)}" class="career-report-section-card">
            <div class="career-report-section-head">
              <div>
                <p class="career-report-section-kicker">${esc(section.kicker || `Section ${index + 1}`)}</p>
                <h3 class="career-report-section-title">${esc(section.title || "章节")}</h3>
                <p class="career-report-section-summary">${formatText(section.summary || "")}</p>
              </div>
            </div>
            ${renderMetricRow(section.metrics)}
            ${renderVisualization(section.visualization)}
            ${renderCardGrid(section.cards)}
          </section>
        `).join("")}
      </div>
    `;
  }

  function renderHistoricalNotice() {
    if (!window.appState?.careerReportViewingHistorical) return "";
    return `
      <div class="career-report-viewing-historical">
        <span>当前正在查看历史版本，进度更新和任务打勾不会写回服务器。</span>
        <button type="button" class="career-report-back-latest-btn" data-report-action="back-latest">返回最新版本</button>
      </div>
    `;
  }

  function renderReportHero(bundle, tracker) {
    const meta = bundle?.meta || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_id || "待识别";
    return `
      <section class="career-report-reader-hero">
        <p class="career-report-reader-kicker">Career Report</p>
        <h2 class="career-report-reader-title">${esc(meta.title || "职业规划报告")}</h2>
        <p class="career-report-reader-copy">${formatText(bundle?.report_document?.executive_summary || meta.summary || "当前报告会根据画像、岗位匹配和职业访谈结果综合输出。")}</p>
        <div class="career-report-reader-meta">
          <span>主岗位：${esc(focusRole)}</span>
          <span>版本：${esc(meta.version || "--")}</span>
          <span>生成时间：${esc(meta.generated_at || "--")}</span>
        </div>
      </section>
    `;
  }

  function renderEmptyReportMain() {
    const focusRole = window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "先锁定目标岗位";
    const completion = Number(window.appState?.profileCompletion || 0);
    return `
      <div class="career-report-empty-grid">
        <article class="career-report-empty-card">
          <strong>先补齐画像，再生成职业报告</strong>
          <p>当前系统已经恢复职业报告后端，但还没有可展示的新报告版本。建议先完成测评、简历和访谈输入，然后再生成。</p>
        </article>
        <article class="career-report-empty-card">
          <strong>当前主线</strong>
          <p>候选主岗位：${esc(focusRole)}</p>
        </article>
        <article class="career-report-empty-card">
          <strong>画像完成度</strong>
          <p>当前完成度约 ${Math.max(0, Math.min(100, Math.round(completion)))}%。补齐关键输入后，报告会自动拉起完整版本链路。</p>
        </article>
      </div>
    `;
  }

  function renderStatusBanner() {
    const host = document.getElementById("careerReportStatusBanner");
    if (!host) return;

    const state = getCareerReportStateSafe();
    const bundle = window.appState?.careerReport || null;
    const historical = Boolean(window.appState?.careerReportViewingHistorical);
    const status = String(state?.status || "").trim().toLowerCase();

    if (!bundle && status !== "queued" && status !== "running" && status !== "failed") {
      host.innerHTML = `
        <div class="career-report-banner-main">
          <div>
            <h3 class="career-report-banner-title">职业报告中心已恢复</h3>
            <p class="career-report-banner-copy">后端报告接口已接回。现在可以基于当前画像和岗位匹配结果重新生成完整职业报告。</p>
          </div>
          <div class="career-report-banner-meta">
            <span>状态：待生成</span>
          </div>
        </div>
      `;
      return;
    }

    const toneClass = status === "failed" ? "failed" : (status === "queued" || status === "running" ? "running" : "");
    const title = status === "failed"
      ? "职业报告生成失败"
      : (status === "queued" || status === "running")
        ? "职业报告正在生成"
        : historical
          ? "当前正在查看历史报告版本"
          : "当前报告已同步到最新版本";
    const copy = status === "failed"
      ? (state?.error_message || "请检查画像输入和模型配置后重试。")
      : (status === "queued" || status === "running")
        ? (state?.stage_detail || state?.summary || "后台正在按阶段生成职业报告，请稍候。")
        : (bundle?.meta?.summary || state?.summary || "当前展示的是已完成的职业报告。");

    host.innerHTML = `
      <div class="career-report-banner-main ${toneClass}">
        <div>
          <h3 class="career-report-banner-title">${esc(title)}</h3>
          <p class="career-report-banner-copy">${formatText(copy)}</p>
        </div>
        <div class="career-report-banner-meta">
          <span>阶段：${esc(state?.stage_label || "已完成")}</span>
          <span>主岗位：${esc(bundle?.report_document?.focus_role_name || state?.tracker?.focus_role_name || state?.focus_role_id || "待识别")}</span>
          <span>版本：${esc(bundle?.meta?.version || state?.tracker?.report_version || "--")}</span>
        </div>
      </div>
    `;
  }

  function renderReportAside() {
    const aside = document.getElementById("careerReportAside");
    if (!aside) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const state = getCareerReportStateSafe();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const outline = Array.isArray(bundle?.report_document?.outline) ? bundle.report_document.outline : [];
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "待识别";

    aside.innerHTML = `
      <section class="career-report-side-card primary">
        <p class="career-report-side-kicker">Current Snapshot</p>
        <h3 class="career-report-side-title">${esc(bundle?.meta?.title || "职业报告待生成")}</h3>
        <p class="career-report-side-copy">${formatText(bundle?.meta?.summary || "先锁定一条主线岗位，再用最新画像生成完整职业规划报告。")}</p>
        <div class="career-report-side-metrics">
          <article>
            <span>主线岗位</span>
            <strong>${esc(focusRole)}</strong>
          </article>
          <article>
            <span>报告版本</span>
            <strong>${esc(bundle?.meta?.version || tracker?.report_version || "--")}</strong>
          </article>
          <article>
            <span>完成度</span>
            <strong>${esc(`${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`)}</strong>
          </article>
        </div>
      </section>
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Pipeline</p>
        <h3 class="career-report-side-title">生成进度</h3>
        <div class="career-report-stage-list">
          ${progress.map((item) => {
            const active = item.status === "active" || item.status === "running";
            return `
              <div class="career-report-stage-item${active ? " active" : ""}">
                <strong>${esc(item.label || item.key || "阶段")}</strong>
                <span>${esc(item.status === "done" ? "已完成" : active ? "进行中" : item.status === "failed" ? "失败" : "待处理")}</span>
              </div>
            `;
          }).join("")}
        </div>
      </section>
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Outline</p>
        <h3 class="career-report-side-title">章节导航</h3>
        <div class="career-report-outline-list">
          ${outline.length ? outline.map((item, index) => `
            <button type="button" class="career-report-outline-btn" data-report-scroll-target="${esc(getReportSectionDomId(item, index))}">
              <strong>${esc(item.title || item.kicker || `章节 ${index + 1}`)}</strong>
              <span>${esc(item.summary || item.kicker || "")}</span>
            </button>
          `).join("") : `
            <div class="career-report-stage-item">
              <strong>等待报告生成</strong>
              <span>生成完成后这里会出现完整章节导航。</span>
            </div>
          `}
        </div>
      </section>
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Top Roles</p>
        <h3 class="career-report-side-title">当前候选岗位</h3>
        <div class="career-report-role-chip-list">
          ${(roleRankings.length ? roleRankings : [{ id: window.appState?.focusedRoleId || "", name: focusRole }]).map((item) => `
            <button type="button" class="career-report-role-chip${String(item.id || "") === String(window.appState?.focusedRoleId || "") ? " active" : ""}" data-report-focus-role="${esc(item.id || "")}">
              ${esc(item.name || item.title || "候选岗位")}
            </button>
          `).join("")}
        </div>
      </section>
    `;

    aside.querySelectorAll("[data-report-scroll-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = String(button.dataset.reportScrollTarget || "").trim();
        if (!targetId) return;
        document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    aside.querySelectorAll("[data-report-focus-role]").forEach((button) => {
      button.addEventListener("click", () => {
        const roleId = String(button.dataset.reportFocusRole || "").trim();
        if (!roleId) return;
        window.setCareerReportFocusRole(roleId);
      });
    });
  }

  function renderReportMain() {
    const main = document.getElementById("careerReportMain");
    if (!main) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const state = getCareerReportStateSafe();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();

    if (!bundle || !bundle.report_document) {
      main.innerHTML = renderEmptyReportMain();
      return;
    }

    main.innerHTML = `
      ${renderHistoricalNotice()}
      ${renderReportHero(bundle, tracker)}
      ${renderReportProgressCards(progress)}
      ${renderReportSections(bundle)}
    `;

    main.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
  }

  function cycleTrackerStatus(itemType, currentStatus) {
    const status = String(currentStatus || "").trim().toLowerCase();
    if (itemType === "checkpoint") {
      return status === "done" ? "pending" : "done";
    }
    if (status === "pending") return "doing";
    if (status === "doing") return "done";
    return "pending";
  }

  async function updateTrackerItem(itemType, itemId, currentStatus) {
    if (window.appState?.careerReportViewingHistorical) {
      toast("历史版本只读", "请先切回最新版本，再更新任务进度。", "warning", 2000);
      return;
    }

    const payload = await requestJsonSafe("/api/career-report/tracker/item", {
      method: "POST",
      body: {
        item_type: itemType,
        item_id: itemId,
        status: cycleTrackerStatus(itemType, currentStatus)
      }
    });
    applyCareerReportState(undefined, payload.tracker || null, payload.state || getCareerReportStateSafe(), {
      keepBundle: true,
      historical: false,
      userCenterRefresh: true
    });
  }

  function renderReportViewerTasks(tracker) {
    const items = [];
    const planItems = Array.isArray(tracker?.plan_items) ? tracker.plan_items : [];
    const checkpoints = Array.isArray(tracker?.checkpoints) ? tracker.checkpoints : [];

    if (planItems.length) {
      items.push('<div class="rv-task-phase">行动计划</div>');
      planItems.forEach((item) => {
        items.push(`
          <button type="button" class="rv-task-item ${esc(item.status || "pending")}" data-report-task-type="plan" data-report-task-id="${esc(item.id || "")}" data-report-task-status="${esc(item.status || "pending")}">
            <span class="rv-task-check">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 5.2 3.8 7.5 8.5 2.5" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            <span class="rv-task-text">${esc(item.title || item.objective || "行动项")}</span>
          </button>
        `);
      });
    }

    if (checkpoints.length) {
      items.push('<div class="rv-task-phase">复查节点</div>');
      checkpoints.forEach((item) => {
        items.push(`
          <button type="button" class="rv-task-item ${esc(item.status || "pending")}" data-report-task-type="checkpoint" data-report-task-id="${esc(item.id || "")}" data-report-task-status="${esc(item.status || "pending")}">
            <span class="rv-task-check">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 5.2 3.8 7.5 8.5 2.5" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            <span class="rv-task-text">${esc(item.label || item.title || "复查项")}</span>
          </button>
        `);
      });
    }

    return items.join("") || '<div class="rv-task-phase">暂无可跟踪任务</div>';
  }

  function renderReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const sections = Array.isArray(bundle?.report_document?.sections) ? bundle.report_document.sections : [];
    const metaTitle = document.getElementById("rvMetaTitle");
    const progressFill = document.getElementById("rvProgressFill");
    const progressLabel = document.getElementById("rvProgressLabel");
    const statDone = document.getElementById("rvStatDone");
    const statTotal = document.getElementById("rvStatTotal");
    const toc = document.getElementById("rvToc");
    const taskList = document.getElementById("rvTaskList");
    const main = document.getElementById("rvMain");

    if (metaTitle) metaTitle.textContent = bundle?.meta?.title || "职业规划报告";
    if (progressFill) progressFill.style.width = `${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`;
    if (progressLabel) progressLabel.textContent = `${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`;
    if (statDone) statDone.textContent = `已完成 ${Number(tracker?.completed_count || 0)} 项`;
    if (statTotal) statTotal.textContent = `共 ${Number(tracker?.total_count || 0)} 项任务`;

    if (toc) {
      toc.innerHTML = `
        <div class="report-viewer-toc-label">目录</div>
        ${sections.map((section, index) => `
          <button type="button" class="rv-toc-item${index === 0 ? " active" : ""}" data-rv-target="${esc(getReportSectionDomId(section, index))}">
            <span class="rv-toc-num">${String(index + 1).padStart(2, "0")}</span>
            <span>${esc(section.title || section.kicker || `章节 ${index + 1}`)}</span>
          </button>
        `).join("")}
      `;
    }

    if (taskList) {
      taskList.innerHTML = renderReportViewerTasks(tracker);
      taskList.querySelectorAll("[data-report-task-type]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemType = String(button.dataset.reportTaskType || "").trim();
          const itemId = String(button.dataset.reportTaskId || "").trim();
          const status = String(button.dataset.reportTaskStatus || "").trim();
          if (!itemType || !itemId) return;
          void updateTrackerItem(itemType, itemId, status).catch((error) => {
            toast("任务状态更新失败", error.message || "请稍后重试。", "error", 2200);
          });
        });
      });
    }

    if (main) {
      main.innerHTML = bundle && bundle.report_document
        ? `${renderHistoricalNotice()}${renderReportHero(bundle, tracker)}${renderReportSections(bundle)}`
        : renderEmptyReportMain();
    }

    overlay.querySelectorAll("[data-rv-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = String(button.dataset.rvTarget || "").trim();
        if (!targetId) return;
        overlay.querySelectorAll(".rv-toc-item").forEach((item) => item.classList.toggle("active", item === button));
        const target = main?.querySelector(`#${escapeSelectorId(targetId)}`);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    overlay.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
  }

  function renderCareerReportPanels() {
    renderStatusBanner();
    renderReportAside();
    renderReportMain();
    renderReportViewer();
  }

  function openReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) {
      window.openUserCenterPage?.("report-workspace");
      return;
    }
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无完整报告", "请先生成职业报告，再查看完整版本。", "warning", 2200);
      return;
    }
    renderReportViewer();
    reportRuntime.previousBodyOverflow = document.body.style.overflow || "";
    document.body.style.overflow = "hidden";
    overlay.classList.remove("hidden");
  }

  function closeReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
    document.body.style.overflow = reportRuntime.previousBodyOverflow;
  }

  async function fetchCareerReportVersion(reportId) {
    const safeId = String(reportId || "").trim();
    if (!safeId) return null;
    const payload = await requestJsonSafe(`/api/career-report/version?report_id=${encodeURIComponent(safeId)}`);
    applyCareerReportState(payload.data || null, payload.tracker || null, getCareerReportStateSafe(), {
      historical: true,
      canonicalReportId: window.appState?.careerReportCanonicalId || getCareerReportVersionList().canonicalReportId,
      userCenterRefresh: true
    });
    return payload;
  }

  async function restoreLatestCareerReportView() {
    const payload = await loadCurrentCareerReport({ userCenterRefresh: true });
    renderReportViewer();
    return payload;
  }

  function setCareerReportFocusRole(roleId) {
    const safeRoleId = String(roleId || "").trim();
    if (!safeRoleId) return;
    ensureAppState();
    window.appState.focusedRoleId = safeRoleId;
    scheduleRender(true);
    const roleName = window.jobNameMap?.[safeRoleId] || safeRoleId;
    toast("已切换主岗位", `下次生成职业报告时将优先使用 ${roleName}。`, "success", 1800);
  }

  function buildCareerReportPayload() {
    ensureAppState();
    const profile = window.appState?.derivedProfile && typeof window.appState.derivedProfile === "object"
      ? window.appState.derivedProfile
      : null;
    const roles = Array.isArray(window.appState?.matchingRoles) ? window.appState.matchingRoles : [];
    if (!profile || !roles.length) return null;
    return {
      profile_snapshot: profile,
      role_rankings: roles,
      focus_role_id: String(window.appState?.focusedRoleId || roles[0]?.id || "").trim()
    };
  }

  async function startCareerReportGeneration() {
    if (!isAuthenticated()) {
      toast("请先登录", "登录后才能生成职业报告。", "warning", 1800);
      return;
    }

    const payload = buildCareerReportPayload();
    if (!payload) {
      if (typeof window.showSection === "function") {
        window.showSection("profile");
      }
      toast("画像还不完整", "请先完成测评、基础信息或岗位匹配，再生成职业报告。", "warning", 2200);
      return;
    }

    try {
      const response = await requestJsonSafe("/api/career-report/generate/start", {
        method: "POST",
        body: payload
      });
      applyCareerReportState(undefined, getCareerReportTracker(), {
        ...(getCareerReportStateSafe() || {}),
        job_id: response.job_id,
        report_id: response.report_id,
        status: "queued",
        stage: "profile_fusion",
        stage_label: "画像融合",
        stage_detail: "任务已创建，等待后台编排"
      }, {
        keepBundle: true,
        historical: false,
        userCenterRefresh: true
      });
      toast("职业报告任务已启动", "系统正在后台生成新的职业报告版本。", "success", 2200);
      await pollCareerReportJob(response.job_id);
    } catch (error) {
      if (error.status === 409) {
        toast("已有报告任务在运行", "正在同步当前生成进度。", "warning", 1800);
        const statusPayload = await syncCareerReportStatus();
        const jobId = statusPayload?.state?.job_id || statusPayload?.job?.job_id || "";
        if (jobId) {
          await pollCareerReportJob(jobId);
        }
        return;
      }
      toast("职业报告启动失败", error.message || "请稍后重试。", "error", 2600);
    }
  }

  function saveReport() {
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无可保存报告", "请先生成完整职业报告。", "warning", 1800);
      return;
    }
    if (window.appState?.careerReportViewingHistorical) {
      toast("历史版本已归档", "当前查看的是历史报告，系统已自动保存该版本。", "info", 1800);
      return;
    }
    toast("报告已自动保存", "每次生成完成后，系统都会自动写入新的报告版本。", "success", 2000);
  }

  function exportReport(format = "html") {
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无可导出报告", "请先生成完整职业报告。", "warning", 1800);
      return;
    }
    const exportFormat = String(format || "html").trim().toLowerCase() === "md" ? "md" : "html";
    const reportId = String(window.appState?.careerReport?.meta?.report_id || "").trim();
    const url = new URL(resolveUrl("/api/career-report/export"), window.location.origin);
    url.searchParams.set("format", exportFormat);
    if (reportId) url.searchParams.set("report_id", reportId);
    const anchor = document.createElement("a");
    anchor.href = url.toString();
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  function normalizeAvatarState(raw) {
    if (!raw || typeof raw !== "object") return null;
    const imageUrl = String(raw.image_url || "").trim();
    if (!imageUrl) return null;
    return {
      source: "uploaded",
      image_url: imageUrl,
      file_name: String(raw.file_name || "").trim(),
      updated_at: String(raw.updated_at || "").trim()
    };
  }

  function applyAvatarToElement(element, avatarState, user) {
    if (!element) return;
    const displayName = user?.display_name || user?.displayName || user?.username || "U";
    const fallback = avatarState ? displayName.charAt(0).toUpperCase() : (user?.role === "super_admin" ? "管" : displayName.charAt(0).toUpperCase());

    if (avatarState?.image_url) {
      element.textContent = "";
      element.style.backgroundImage = `url("${avatarState.image_url.replace(/"/g, "%22")}")`;
      element.style.backgroundSize = "cover";
      element.style.backgroundPosition = "center";
      element.style.color = "transparent";
      return;
    }

    element.textContent = fallback;
    element.style.backgroundImage = "";
    element.style.backgroundSize = "";
    element.style.backgroundPosition = "";
    element.style.color = "";
  }

  function renderTopbarAvatar() {
    const user = currentUser();
    const avatar = avatarRuntime.state;
    applyAvatarToElement(document.getElementById("currentUserAvatar"), avatar, user);
  }

  function getAccountAvatarState() {
    return avatarRuntime.state;
  }

  async function loadAccountAvatarState(force = false) {
    if (!isAuthenticated()) {
      avatarRuntime.username = "";
      avatarRuntime.state = null;
      renderTopbarAvatar();
      return null;
    }

    const user = currentUser();
    const username = String(user?.username || "").trim();
    if (!force && avatarRuntime.username === username) {
      renderTopbarAvatar();
      return avatarRuntime.state;
    }

    try {
      const data = typeof window.fetchScopedUserState === "function"
        ? await window.fetchScopedUserState("account_avatar", force)
        : null;
      avatarRuntime.username = username;
      avatarRuntime.state = normalizeAvatarState(data);
    } catch (error) {
      console.warn("load account avatar failed", error);
      avatarRuntime.username = username;
      avatarRuntime.state = null;
    }

    renderTopbarAvatar();
    return avatarRuntime.state;
  }

  function getPlanStorageKey() {
    const username = String(currentUser()?.username || "guest").trim().toLowerCase() || "guest";
    return `${PLAN_STORAGE_PREFIX}${username}`;
  }

  function getPlanProgressStorageKey() {
    const username = String(currentUser()?.username || "guest").trim().toLowerCase() || "guest";
    return `${PLAN_PROGRESS_PREFIX}${username}`;
  }

  function readPlans() {
    try {
      const parsed = JSON.parse(localStorage.getItem(getPlanStorageKey()) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  function readPlanProgress() {
    const fallback = {
      streak: 0,
      best_streak: 0,
      xp: 0,
      last_checkin: "",
      active_days: {}
    };
    try {
      const parsed = JSON.parse(localStorage.getItem(getPlanProgressStorageKey()) || "null");
      if (!parsed || typeof parsed !== "object") return fallback;
      return {
        streak: Math.max(0, Number(parsed.streak || 0)),
        best_streak: Math.max(0, Number(parsed.best_streak || 0)),
        xp: Math.max(0, Number(parsed.xp || 0)),
        last_checkin: String(parsed.last_checkin || "").trim(),
        active_days: parsed.active_days && typeof parsed.active_days === "object" ? parsed.active_days : {}
      };
    } catch (_) {
      return fallback;
    }
  }

  function writePlanProgress(progress) {
    try {
      localStorage.setItem(getPlanProgressStorageKey(), JSON.stringify(progress));
    } catch (_) {
      // ignore storage failures
    }
  }

  function dayKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function parseDayKey(value) {
    if (!value) return null;
    const safe = String(value || "").trim();
    const parsed = new Date(`${safe}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function isSameDay(left, right) {
    return left && right && dayKey(left) === dayKey(right);
  }

  function addDays(date, delta) {
    const next = new Date(date);
    next.setDate(next.getDate() + delta);
    return next;
  }

  function computePlanTaskStats() {
    const plans = readPlans();
    let total = 0;
    let done = 0;
    plans.forEach((plan) => {
      const items = Array.isArray(plan?.items) ? plan.items : [];
      total += items.length;
      done += items.filter((item) => item?.done).length;
    });
    return { total, done };
  }

  function computeUnlockedBadges(progress, doneCount) {
    return [
      { id: "start", name: "开始行动", unlocked: doneCount >= 1 },
      { id: "streak3", name: "连击 3 天", unlocked: progress.streak >= 3 },
      { id: "streak7", name: "连击 7 天", unlocked: progress.best_streak >= 7 },
      { id: "xp100", name: "累计 100 XP", unlocked: progress.xp >= 100 }
    ];
  }

  function renderWeekStrip(progress) {
    const host = document.getElementById("lpWeekStrip");
    if (!host) return;
    const labels = ["一", "二", "三", "四", "五", "六", "日"];
    const today = new Date();
    const monday = addDays(today, 1 - (today.getDay() || 7));
    host.innerHTML = labels.map((label, index) => {
      const date = addDays(monday, index);
      const key = dayKey(date);
      const done = Boolean(progress.active_days[key]);
      const isToday = isSameDay(date, today);
      const isFuture = date > today;
      return `
        <div class="lp-week-day${done ? " done" : ""}${isToday ? " today" : ""}${isFuture ? " future" : ""}">
          <div class="lp-week-dot"></div>
          <div class="lp-week-label">${label}</div>
        </div>
      `;
    }).join("");
  }

  function renderHeatmap(progress) {
    const host = document.getElementById("lpHeatmap");
    if (!host) return;
    const today = new Date();
    host.innerHTML = Array.from({ length: 28 }, (_, index) => {
      const date = addDays(today, index - 27);
      const key = dayKey(date);
      const active = Boolean(progress.active_days[key]);
      return `<span class="lp-heatmap-cell${active ? " active" : ""}" title="${esc(key)}"></span>`;
    }).join("");
  }

  function renderBadgeGrid(progress, doneCount) {
    const host = document.getElementById("lpBadgeGrid");
    if (!host) return;
    const badges = computeUnlockedBadges(progress, doneCount);
    host.innerHTML = badges.map((badge) => `
      <div class="lp-badge-item ${badge.unlocked ? "unlocked" : "locked"}">
        <div class="lp-badge-icon">${badge.unlocked ? "OK" : "--"}</div>
        <div class="lp-badge-name">${esc(badge.name)}</div>
      </div>
    `).join("");

    const unlockedCount = badges.filter((item) => item.unlocked).length;
    const statBadges = document.getElementById("upStatBadges");
    if (statBadges) statBadges.textContent = String(unlockedCount);
  }

  function updatePlanWidgets() {
    const progress = readPlanProgress();
    const stats = computePlanTaskStats();
    const level = Math.max(1, Math.floor(progress.xp / 100) + 1);
    const currentXp = progress.xp % 100;
    const checkedToday = Boolean(progress.last_checkin && isSameDay(parseDayKey(progress.last_checkin), new Date()));

    const streakCount = document.getElementById("lpStreakCount");
    const streakBest = document.getElementById("lpStreakBest");
    const streakIcon = document.getElementById("lpStreakIcon");
    const levelTag = document.getElementById("lpLevel");
    const xpValue = document.getElementById("lpXP");
    const xpNext = document.getElementById("lpXPNext");
    const xpFill = document.getElementById("lpXPFill");
    const checkinBtn = document.getElementById("lpCheckinBtn");
    const checkinHint = document.getElementById("lpCheckinHint");
    const statStreak = document.getElementById("upStatStreak");
    const statXp = document.getElementById("upStatXP");
    const statDone = document.getElementById("upStatDone");

    if (streakCount) streakCount.textContent = String(progress.streak);
    if (streakBest) streakBest.textContent = String(progress.best_streak);
    if (streakIcon) streakIcon.textContent = progress.streak >= 7 ? "++" : progress.streak >= 3 ? "+!" : "+";
    if (levelTag) levelTag.textContent = `Lv.${level}`;
    if (xpValue) xpValue.textContent = String(currentXp);
    if (xpNext) xpNext.textContent = "100";
    if (xpFill) xpFill.style.width = `${currentXp}%`;
    if (checkinBtn) {
      checkinBtn.disabled = checkedToday;
      checkinBtn.classList.toggle("checked", checkedToday);
      checkinBtn.textContent = checkedToday ? "今日已打卡" : "今日打卡 · +10 XP";
    }
    if (checkinHint) {
      checkinHint.textContent = checkedToday
        ? `已完成今日打卡，当前连续 ${progress.streak} 天。`
        : "每天打卡会累积连续记录，并自动带动当前计划任务推进。";
    }
    if (statStreak) statStreak.textContent = `${progress.streak}天`;
    if (statXp) statXp.textContent = `${progress.xp} XP`;
    if (statDone) statDone.textContent = String(stats.done);

    renderWeekStrip(progress);
    renderHeatmap(progress);
    renderBadgeGrid(progress, stats.done);
  }

  function schedulePlanRefresh() {
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => {
        updatePlanWidgets();
      });
      return;
    }
    setTimeout(updatePlanWidgets, 0);
  }

  function ensurePlanFunctionsWrapped() {
    if (reportRuntime.planWrapped) return;
    reportRuntime.planWrapped = true;

    const wrap = (name) => {
      if (typeof window[name] !== "function") return;
      const original = window[name];
      window[name] = function wrappedPlanAction() {
        const result = original.apply(this, arguments);
        schedulePlanRefresh();
        return result;
      };
    };

    ["createNewPlan", "addPlanItem", "togglePlanItem", "showPlanList", "showPlanDetail"].forEach(wrap);

    if (typeof window.doCheckin === "function") {
      const originalCheckin = window.doCheckin;
      window.doCheckin = function wrappedCheckin() {
        const progress = readPlanProgress();
        const todayKey = dayKey(new Date());
        if (progress.last_checkin === todayKey) {
          toast("今日已打卡", "今天的打卡奖励已经领取过了。", "info", 1600);
          schedulePlanRefresh();
          return;
        }

        const yesterday = dayKey(addDays(new Date(), -1));
        progress.streak = progress.last_checkin === yesterday ? progress.streak + 1 : 1;
        progress.best_streak = Math.max(progress.best_streak, progress.streak);
        progress.xp += progress.streak % 7 === 0 ? 50 : 10;
        progress.last_checkin = todayKey;
        progress.active_days[todayKey] = true;
        writePlanProgress(progress);

        const result = originalCheckin.apply(this, arguments);
        schedulePlanRefresh();
        return result;
      };
    }
  }

  function loadCareerPlans() {
    updatePlanWidgets();
    if (typeof window.showPlanList === "function") {
      window.showPlanList();
    }
  }

  function bindGlobalRestorationEvents() {
    if (reportRuntime.eventsBound) return;
    reportRuntime.eventsBound = true;

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn && !logoutBtn.dataset.restorationBound) {
      logoutBtn.addEventListener("click", () => {
        stopCareerReportPolling();
        closeReportViewer();
      });
      logoutBtn.dataset.restorationBound = "1";
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeReportViewer();
      }
    });
  }

  async function initializeRestoration() {
    ensureAppState();
    ensurePlanFunctionsWrapped();
    primeCareerReportStateFromBootstrap();
    bindGlobalRestorationEvents();

    await loadAccountAvatarState(false);
    loadCareerPlans();

    if (!isAuthenticated()) {
      applyCareerReportState(null, null, null, {
        historical: false,
        userCenterRefresh: true
      });
      return;
    }

    try {
      const [statusResult, currentResult] = await Promise.allSettled([
        syncCareerReportStatus(),
        loadCurrentCareerReport({ userCenterRefresh: true })
      ]);

      const statusPayload = statusResult.status === "fulfilled" ? statusResult.value : null;
      const state = statusPayload?.state || getCareerReportStateSafe();
      const status = String(state?.status || "").trim().toLowerCase();
      const jobId = String(state?.job_id || statusPayload?.job?.job_id || "").trim();
      if ((status === "queued" || status === "running") && jobId) {
        void pollCareerReportJob(jobId);
      }

      if (currentResult.status === "rejected") {
        console.warn("load current career report failed", currentResult.reason);
      }
    } catch (error) {
      console.warn("workspace restoration init failed", error);
    } finally {
      scheduleRender(true);
    }
  }

  window.getCareerReportStateSafe = getCareerReportStateSafe;
  window.getCareerReportTracker = getCareerReportTracker;
  window.getCareerReportVersionList = getCareerReportVersionList;
  window.fetchCareerReportVersion = fetchCareerReportVersion;
  window.restoreLatestCareerReportView = restoreLatestCareerReportView;
  window.startCareerReportGeneration = startCareerReportGeneration;
  window.openReportViewer = openReportViewer;
  window.closeReportViewer = closeReportViewer;
  window.saveReport = saveReport;
  window.exportReport = exportReport;
  window.setCareerReportFocusRole = setCareerReportFocusRole;
  window.getAccountAvatarState = getAccountAvatarState;
  window.loadAccountAvatarState = loadAccountAvatarState;
  window.renderTopbarAvatar = renderTopbarAvatar;
  window._loadCareerPlans = loadCareerPlans;
  window._updateLifeProgress = updatePlanWidgets;
  window._updatePlanStats = updatePlanWidgets;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      const authReady = typeof window.initAuth === "function"
        ? window.initAuth()
        : (typeof initAuth === "function" ? initAuth() : null);
      Promise.resolve(authReady).finally(() => {
        void initializeRestoration();
      });
    }, { once: true });
  } else {
    const authReady = typeof window.initAuth === "function"
      ? window.initAuth()
      : (typeof initAuth === "function" ? initAuth() : null);
    Promise.resolve(authReady).finally(() => {
      void initializeRestoration();
    });
  }

  window.addEventListener("app:auth-changed", () => {
    stopCareerReportPolling();
    closeReportViewer();
    avatarRuntime.username = "";
    avatarRuntime.state = null;
    void initializeRestoration();
  });
})();
