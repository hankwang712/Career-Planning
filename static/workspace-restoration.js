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
    previousBodyOverflow: "",
    feedbackVerdict: "",
    feedbackNote: "",
    editorSource: null,
    editorSelection: null,
    editorDiff: null,
    editorConversation: []
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

  // Lightweight markdown-to-HTML for v2 module content
  function renderMarkdownBasic(md) {
    if (!md) return "";
    let text = String(md);
    // Escape HTML first
    text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    // Code blocks (```...```)
    text = text.replace(/```(?:json|python|markdown|md)?\s*([\s\S]*?)```/g, (_, code) =>
      `<pre><code>${code.trim()}</code></pre>`);
    // Inline code
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Headings
    text = text.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
    text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    text = text.replace(/^# (.+)$/gm, "<h2>$1</h2>");
    // Bold
    text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // Tables: find lines with | separators
    text = text.replace(/((?:\|.+\|\n?)+)/g, (tableBlock) => {
      const lines = tableBlock.trim().split("\n").filter((l) => l.trim());
      if (lines.length < 2) return tableBlock;
      const rows = lines.map((line) => {
        const cells = line.split("|").slice(1, -1).map((c) => c.trim());
        return cells;
      });
      const isSep = (row) => row.every((c) => /^[-:]+$/.test(c));
      let html = "<table>";
      let headerDone = false;
      for (let i = 0; i < rows.length; i++) {
        if (i === 1 && isSep(rows[i])) continue;
        const tag = !headerDone && i === 0 ? "th" : "td";
        if (tag === "th") headerDone = true;
        html += "<tr>" + rows[i].map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
      }
      html += "</table>";
      return html;
    });
    // Unordered lists
    text = text.replace(/((?:^[-*] .+\n?)+)/gm, (block) => {
      const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^[-*] /, "")}</li>`).join("");
      return `<ul>${items}</ul>`;
    });
    // Numbered lists
    text = text.replace(/((?:^\d+\. .+\n?)+)/gm, (block) => {
      const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\. /, "")}</li>`).join("");
      return `<ol>${items}</ol>`;
    });
    // Horizontal rules
    text = text.replace(/^---+$/gm, "<hr>");
    // Paragraphs (double newlines)
    text = text.replace(/\n\n+/g, "</p><p>");
    text = `<p>${text}</p>`;
    // Single newlines
    text = text.replace(/\n/g, "<br>");
    // Clean up empty paragraphs
    text = text.replace(/<p>\s*<\/p>/g, "");
    text = text.replace(/<p>(<(?:h[1-4]|ul|ol|table|pre|hr)[^>]*>)/g, "$1");
    text = text.replace(/(<\/(?:h[1-4]|ul|ol|table|pre|hr)>)<\/p>/g, "$1");
    return text;
  }

  function truncateSummary(text, maxLen = 100) {
    const t = String(text || "").replace(/\s+/g, " ").trim();
    if (!t) return "";
    if (t.length <= maxLen) return t;
    return `${t.slice(0, maxLen)}…`;
  }

  function computeGenerationPercent(progress) {
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    const done = items.filter((x) => x && x.status === "done").length;
    return Math.round((done / Math.max(items.length, 1)) * 100);
  }

  function renderReportGenerationMain(state, progress) {
    const pct = computeGenerationPercent(progress);
    const dash = Math.max(0, Math.min(264, (pct / 100) * 264));
    const detail = esc(String(state?.stage_detail || state?.stage_label || "后台正在按阶段生成结构化职业规划报告，请稍候。").trim());
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    return `
      <div class="career-report-gen">
        <div class="career-report-gen-inner">
          <p class="career-report-gen-kicker">Career Report Pipeline</p>
          <h2 class="career-report-gen-title">正在生成你的职业发展报告</h2>
          <p class="career-report-gen-copy">当前页面仅展示生成进度，不展开报告正文。完成后会出现「报告已同步」提示，并自动载入新版式正文；也可通过顶部头像随时回到此处阅读。</p>
          <div class="career-report-gen-ring-wrap" aria-hidden="true">
            <svg class="career-report-gen-ring" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(148,163,184,0.28)" stroke-width="8" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="url(#crGenGradPipe)" stroke-width="8"
                stroke-dasharray="${dash} 264" stroke-linecap="round" transform="rotate(-90 50 50)" />
              <defs>
                <linearGradient id="crGenGradPipe" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#2563eb" />
                  <stop offset="100%" stop-color="#38bdf8" />
                </linearGradient>
              </defs>
            </svg>
            <div class="career-report-gen-ring-label">
              <strong>${pct}%</strong>
              <span>阶段完成度</span>
            </div>
          </div>
          <p class="career-report-gen-status">${detail}</p>
          <div class="career-report-gen-stages">
            ${items.map((item) => {
              const done = item.status === "done";
              const active = item.status === "active" || item.status === "running";
              return `
                <div class="career-report-gen-stage${done ? " done" : ""}${active ? " active" : ""}">
                  <span class="career-report-gen-dot"></span>
                  <span class="career-report-gen-stage-label">${esc(item.label || item.key || "阶段")}</span>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderScoreRing(pct) {
    const v = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    const dash = (v / 100) * 264;
    return `
      <div class="cr-v2-score">
        <svg class="cr-v2-score-ring" viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="7" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.95)" stroke-width="7"
            stroke-dasharray="${dash} 264" stroke-linecap="round" transform="rotate(-90 50 50)" />
        </svg>
        <div class="cr-v2-score-val">${v}%</div>
        <div class="cr-v2-score-cap">综合置信</div>
      </div>
    `;
  }

  function renderReportMagazineLayout(bundle, tracker) {
    const meta = bundle?.meta || {};
    const snap = bundle?.profile_snapshot || {};
    const interest = snap?.interest_profile || {};
    const basics = snap?.basics || {};
    const roles = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const gapMap = bundle?.gap_map || {};
    const gaps = Array.isArray(gapMap.capability_gaps) ? gapMap.capability_gaps.slice(0, 6) : [];
    const phasePlan = bundle?.phase_plan || {};
    const shortPhases = Array.isArray(phasePlan.short_term) ? phasePlan.short_term.slice(0, 2) : [];
    const longPhases = Array.isArray(phasePlan.long_term) ? phasePlan.long_term.slice(0, 1) : [];
    const trend = bundle?.trend_brief || {};
    const workValues = Array.isArray(snap?.work_values) ? snap.work_values : [];
    const exec = String(bundle?.report_document?.executive_summary || meta.summary || snap?.summary || "").trim();
    const focusRole = bundle?.report_document?.focus_role_name || gapMap?.focus_role_name || tracker?.focus_role_name || "待识别";
    const userLabel = esc(currentUser()?.display_name || currentUser()?.username || "用户");
    const conf = Math.max(
      0,
      Math.min(
        100,
        Number(meta.evidence_score ?? tracker?.completion_rate ?? snap?.readiness_score ?? 67) || 0
      )
    );
    const mbtiPill = esc(String(interest.mbti || "MBTI 待补充"));
    const holPill = esc(String(interest.holland || "Holland 待补充"));

    const roleRows = roles.length
      ? roles.map((r) => {
          const score = Math.max(0, Math.min(100, Number(r.overallScore ?? r.overall_score ?? 0)));
          return `
            <div class="cr-v2-role-row">
              <span>${esc(r.name || r.title || "岗位")}</span>
              <span>${score}%</span>
            </div>
          `;
        }).join("")
      : `<div class="cr-v2-role-row"><span>${esc(focusRole)}</span><span>--</span></div>`;

    const gapRows = gaps.length
      ? gaps.map((g) => {
          const cur = g.current != null ? Number(g.current) : 0;
          const req = g.required != null ? Number(g.required) : 85;
          const ratio = req > 0 ? Math.round(Math.min(100, (cur / req) * 100)) : 0;
          return `
            <div class="cr-v2-gap-row">
              <div class="cr-v2-gap-head">
                <span>${esc(g.label || "能力项")}</span>
                <span>${esc(String(cur))}/${esc(String(req))}</span>
              </div>
              <div class="cr-v2-bar"><i style="width:${ratio}%"></i></div>
            </div>
          `;
        }).join("")
      : `<p class="cr-v2-lead" style="margin:0;color:#94a3b8;font-size:0.8rem;">差距分析将在生成完成后显示。</p>`;

    const phaseBlocks = [...shortPhases, ...longPhases]
      .map((ph) => {
        const tasks = Array.isArray(ph.tasks) ? ph.tasks.map((t) => esc(t.text || t.title || "")).filter(Boolean) : [];
        return `
          <div class="cr-v2-phase">
            <h5>${esc(ph.phase || ph.title || "阶段")}</h5>
            <p>${esc(ph.objective || ph.title || "")}</p>
            ${tasks.length ? `<ul>${tasks.slice(0, 4).map((t) => `<li>${t}</li>`).join("")}</ul>` : ""}
          </div>
        `;
      })
      .join("");

    const valueTags = workValues.length
      ? workValues.slice(0, 8).map((w) => `<span class="cr-v2-pill">${esc(w)}</span>`).join("")
      : `<span class="cr-v2-pill neutral">继续补充访谈与简历以丰富价值观标签</span>`;

    const basicsLine = [basics.major, basics.grade, basics.target_city, basics.target_direction]
      .filter(Boolean)
      .map((x) => esc(x))
      .join(" · ");

    const trendSignals = Array.isArray(trend.signals) && trend.signals.length
      ? trend.signals.slice(0, 2).map((s) => `<span class="cr-v2-pill neutral">${esc(s.title || s.summary || s.text || "趋势")}</span>`).join("")
      : `<span class="cr-v2-pill neutral">趋势快照待刷新</span>`;

    // v2: additional data
    const matchOutput = bundle?.match_output || {};
    const fitScore = Number(matchOutput.fit_score || 0);
    const fitBand = String(matchOutput.fit_band || "");
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || "";
    const positioning = bundle?.positioning_output || {};
    const recommendedTracks = Array.isArray(positioning.recommended_tracks) ? positioning.recommended_tracks : [];

    return `
      <div class="cr-v2-wrap">
        <header class="cr-v2-hero">
          <div>
            <p class="cr-v2-hero-kicker">Career Report · 发展规划摘要</p>
            <h2 class="cr-v2-hero-title">${esc(meta.title || "职业生涯发展报告")}</h2>
            <p class="cr-v2-hero-copy">${formatText(exec || "报告已整合测评、画像、岗位匹配与阶段规划，以下为结构化摘要。")}</p>
            <div class="cr-v2-hero-meta">
              <span>主线岗位：${esc(focusRole)}</span>
              <span>生成时间：${esc(meta.generated_at || "--")}</span>
              <span>版本：${esc(meta.version || "--")}</span>
              <span>姓名：${userLabel}</span>
            </div>
          </div>
          ${renderScoreRing(conf)}
        </header>
        <div class="cr-v2-grid">
          <div class="cr-v2-stack" style="display:grid;gap:1rem;">
            <article class="cr-v2-card">
              <h4>测评与画像结论</h4>
              <p class="cr-v2-lead">${formatText(snap.core_thesis || snap.summary || "画像摘要已同步至报告。")}</p>
              <div class="cr-v2-pill-row">
                <span class="cr-v2-pill">MBTI：${mbtiPill}</span>
                <span class="cr-v2-pill">Holland：${holPill}</span>
              </div>
            </article>
            <article class="cr-v2-card">
              <h4>优先岗位方向</h4>
              <div class="cr-v2-role-list">${roleRows}</div>
            </article>
            <article class="cr-v2-card">
              <h4>差距驱动 · 能力对照</h4>
              ${gapRows}
              ${Array.isArray(gapMap.skill_gaps) && gapMap.skill_gaps.length ? `
                <p class="cr-v2-lead" style="margin-top:0.5rem;font-size:0.78rem;color:#64748b;">
                  ${esc(gapMap.skill_gaps.slice(0, 2).join("；"))}
                </p>
              ` : ""}
            </article>
          </div>
          <div class="cr-v2-stack" style="display:grid;gap:1rem;">
            <article class="cr-v2-card">
              <h4>阶段性职业规划</h4>
              ${phaseBlocks || '<p class="cr-v2-lead" style="margin:0;color:#94a3b8;">阶段任务将在生成完成后展示。</p>'}
            </article>
            <article class="cr-v2-card">
              <h4>工作价值观与基础信息</h4>
              <div class="cr-v2-pill-row" style="margin-bottom:0.65rem;">${valueTags}</div>
              <p class="cr-v2-lead" style="margin:0;font-size:0.78rem;">${basicsLine || "专业 / 学历 / 目标城市等可在画像中继续补充。"}</p>
            </article>
            <article class="cr-v2-card">
              <h4>行业信号与待接入能力</h4>
              <div class="cr-v2-pill-row" style="margin-bottom:0.65rem;">${trendSignals}</div>
              <div class="cr-v2-placeholder-grid">
                <div class="cr-v2-placeholder">资源推荐<br/>待接入</div>
                <div class="cr-v2-placeholder">趋势解读<br/>待接入</div>
                <div class="cr-v2-placeholder">提醒追踪<br/>待接入</div>
              </div>
            </article>
            ${renderReportFeedbackCard()}
          </div>
        </div>
      </div>
    `;
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

  function getCareerReportFeedback() {
    const feedback = getCareerReportStateSafe()?.feedback;
    return feedback && typeof feedback === "object" ? feedback : null;
  }

  function getFeedbackVerdictLabel(verdict) {
    const key = String(verdict || "").trim().toLowerCase();
    if (key === "accurate") return "基本准确";
    if (key === "off_target") return "明显偏差";
    return "部分准确";
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
        // Notify learning plan to auto-refresh from new tracker data
        window.dispatchEvent(new CustomEvent("career-report:updated"));
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

  function renderReportSections(bundle, options = {}) {
    const rawSections = bundle?.report_document?.sections;

    // v2: sections is an object keyed by module name
    if (rawSections && !Array.isArray(rawSections) && typeof rawSections === "object") {
      return renderReportSections4(bundle, rawSections, options);
    }

    // Legacy: sections is an array
    const sections = Array.isArray(rawSections) ? rawSections : [];
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
                ${section.summary ? `<p class="career-report-section-deck">${esc(truncateSummary(section.summary, 140))}</p>` : ""}
              </div>
            </div>
            ${renderMetricRow(section.metrics)}
            ${renderVisualization(section.visualization)}
            ${renderCardGrid(section.cards)}
            ${section.summary ? `<div class="career-report-section-body">${formatText(section.summary)}</div>` : ""}
          </section>
        `).join("")}
      </div>
    `;
  }

  function renderReportSections4(bundle, sections, options = {}) {
    const requestedGroup = String(options.group || "").trim().toLowerCase();
    const groupConfig = REPORT_WORKSPACE_GROUPS[requestedGroup] || null;
    const navOrder = ["industry_analysis", "career_positioning", "resume_evidence", "competency_profile", "role_match", "path_plan"];
    const navMeta = {
      "industry_analysis":  { label: "行业与需求侧判断", icon: "01", anchor: "cr-sec-industry",    kicker: "Industry Analyst",             accentClass: "cr-module-purple" },
      "career_positioning": { label: "职业定位假设",     icon: "02", anchor: "cr-sec-positioning", kicker: "Career Positioning Advisor",   accentClass: "cr-module-blue" },
      "resume_evidence":    { label: "简历证据链",       icon: "03", anchor: "cr-sec-resume",       kicker: "Resume Evidence Analyst",      accentClass: "cr-module-amber" },
      "competency_profile": { label: "能力评估画像",     icon: "04", anchor: "cr-sec-competency",   kicker: "Competency Assessor",          accentClass: "cr-module-green" },
      "role_match":         { label: "岗位匹配结论",     icon: "05", anchor: "cr-sec-match",        kicker: "Role Match Officer",           accentClass: "cr-module-indigo" },
      "path_plan":          { label: "阶段学习路径",     icon: "06", anchor: "cr-sec-path",         kicker: "Career Path Planner",          accentClass: "cr-module-teal" },
    };

    // ── helpers ──────────────────────────────────────────────────────────────

    function skillBar(label, pct, colorVar) {
      const w = Math.min(100, Math.max(0, Number(pct) || 0));
      return `
        <div class="cr4-skill-item">
          <div class="cr4-skill-header">
            <span class="cr4-skill-name">${esc(label)}</span>
            <span class="cr4-skill-score">${w}</span>
          </div>
          <div class="cr4-skill-bar">
            <div class="cr4-skill-bar-fill" style="width:${w}%;background:${colorVar || "var(--cr4-primary)"};"></div>
          </div>
        </div>`;
    }

    function dimCard(icon, title, desc, pct, colorVar, accentClass) {
      const w = Math.min(100, Math.max(0, Number(pct) || 0));
      return `
        <div class="cr4-dim-card">
          <div class="cr4-dim-header">
            <div class="cr4-dim-icon ${accentClass}">${icon}</div>
            <div class="cr4-dim-score" style="color:${colorVar}">${w}</div>
          </div>
          <div class="cr4-dim-title">${esc(title)}</div>
          <div class="cr4-dim-desc">${esc(desc)}</div>
          <div class="cr4-dim-bar">
            <div class="cr4-dim-bar-fill" style="width:${w}%;background:${colorVar};"></div>
          </div>
        </div>`;
    }

    function statCard(label, value, sub, accentClass) {
      return `
        <div class="cr4-stat-card ${accentClass}">
          <div class="cr4-stat-label">${esc(label)}</div>
          <div class="cr4-stat-value">${esc(String(value))}</div>
          ${sub ? `<div class="cr4-stat-sub">${esc(sub)}</div>` : ""}
        </div>`;
    }

    function gapPill(text, type) {
      const cls = type === "urgent" ? "cr4-gap-urgent" : type === "warn" ? "cr4-gap-warn" : "cr4-gap-info";
      const label = type === "urgent" ? "急需提升" : type === "warn" ? "需要提升" : "建议加强";
      return `
        <div class="cr4-gap-pill ${cls}">
          <div class="cr4-gap-pill-label">${label}</div>
          <div class="cr4-gap-pill-text">${esc(text)}</div>
        </div>`;
    }

    function timelineItem(phase, title, period, desc, tags, state) {
      return `
        <div class="cr4-timeline-item ${state || "future"}">
          <div class="cr4-timeline-dot"></div>
          <div class="cr4-timeline-content">
            <div class="cr4-timeline-phase">${esc(phase)}</div>
            <div class="cr4-timeline-title">${esc(title)}</div>
            ${period ? `<div class="cr4-timeline-period">${esc(period)}</div>` : ""}
            ${desc ? `<div class="cr4-timeline-desc">${esc(desc)}</div>` : ""}
            ${tags && tags.length ? `<div class="cr4-timeline-tags">${tags.map((t) => `<span class="cr4-tag">${esc(String(t))}</span>`).join("")}</div>` : ""}
          </div>
        </div>`;
    }

    // grade → 0-100 score for bar widths
    function gradeToScore(level) {
      return {"S": 96, "A": 85, "B": 70, "C": 55, "D": 35}[String(level).toUpperCase()] || 0;
    }

    function normalizeExplainItem(item) {
      if (item == null) return null;
      if (typeof item === "string" || typeof item === "number") {
        const text = String(item).trim();
        return text ? { title: text, detail: "", meta: "", validate: "" } : null;
      }
      if (typeof item !== "object") return null;
      const title = String(
        item.title
        || item.label
        || item.name
        || item.skill
        || item.competency
        || item.requirement
        || item.track
        || ""
      ).trim();
      const detail = String(
        item.detail
        || item.summary
        || item.reason
        || item.note
        || item.why_important
        || item.priority_reason
        || item.because
        || ""
      ).trim();
      const metaParts = [];
      if (item.source_type) metaParts.push(`来源：${item.source_type}`);
      if (item.time_horizon) metaParts.push(`时效：${item.time_horizon}`);
      if (item.status) metaParts.push(`状态：${item.status}`);
      if (item.evidence) metaParts.push(String(item.evidence).trim());
      if (Array.isArray(item.evidence_ids) && item.evidence_ids.length) {
        metaParts.push(`证据 ID：${item.evidence_ids.join("、")}`);
      }
      const validate = String(item.validate || item.validation_action || "").trim();
      if (!title && !detail && !metaParts.length && !validate) return null;
      return {
        title: title || detail || metaParts[0] || "待补充",
        detail: title ? detail : "",
        meta: metaParts.join(" · "),
        validate,
      };
    }

    function renderExplainList(items, empty = "暂无补充") {
      const normalized = (Array.isArray(items) ? items : [items])
        .map((item) => normalizeExplainItem(item))
        .filter(Boolean);
      if (!normalized.length) {
        return `<p class="cr4-explain-empty">${esc(empty)}</p>`;
      }
      return `
        <ul class="cr4-explain-list">
          ${normalized.map((item) => `
            <li>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
              ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
              ${item.validate ? `<em>验证：${esc(item.validate)}</em>` : ""}
            </li>
          `).join("")}
        </ul>
      `;
    }

    function renderExplainabilityBlock(explainability) {
      const block = explainability && typeof explainability === "object" ? explainability : {};
      const judgement = String(block.judgement || "").trim();
      const because = Array.isArray(block.because) ? block.because : [];
      const evidence = Array.isArray(block.evidence) ? block.evidence : [];
      const validate = Array.isArray(block.validate) ? block.validate : [];
      if (!judgement && !because.length && !evidence.length && !validate.length) return "";
      return `
        <section class="cr4-explain">
          <div class="cr4-explain-head">
            <p class="cr4-explain-kicker">Explainability</p>
            <h4>${esc(judgement || "为什么这么判断")}</h4>
          </div>
          <div class="cr4-explain-grid">
            <div class="cr4-explain-card">
              <span>因为</span>
              ${renderExplainList(because, "当前未补充原因说明")}
            </div>
            <div class="cr4-explain-card">
              <span>依据</span>
              ${renderExplainList(evidence, "当前未补充依据来源")}
            </div>
            <div class="cr4-explain-card">
              <span>可验证动作</span>
              ${renderExplainList(validate, "当前未补充验证动作")}
            </div>
          </div>
        </section>
      `;
    }

    // ── per-section body renderers ────────────────────────────────────────────

    function renderIndustryBody(data) {
      const explainability = data.explainability || {};
      const hotDirs   = Array.isArray(data.hot_directions)   ? data.hot_directions.slice(0, 4)   : [];
      const skillPrios = Array.isArray(data.skill_priorities) ? data.skill_priorities.slice(0, 6) : [];
      const risks      = Array.isArray(data.risk_signals)     ? data.risk_signals.slice(0, 4)     : [];
      const summary    = data.industry_summary || "";

      const statCards = [
        statCard("升温方向", hotDirs.length || "—", "个热点赛道", "cr4-ac-purple"),
        statCard("高优先技能", skillPrios.filter((s) => s.importance === "高").length || skillPrios.length || "—", "项能力投资", "cr4-ac-blue"),
        statCard("风险信号", risks.length || "—", "项待关注", "cr4-ac-amber"),
      ];

      const hotList = hotDirs.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">升温方向</div></div>
          ${hotDirs.map((d) => `
            <div class="cr4-insight-item">
              <div class="cr4-insight-head">
                <span class="cr4-row-label">${esc(d.name || String(d))}</span>
                <span class="cr4-badge ${d.confidence === "高" ? "cr4-badge-green" : d.confidence === "低" ? "cr4-badge-red" : "cr4-badge-amber"}">${esc(d.confidence || "中")}</span>
              </div>
              ${(d.summary || d.why_important) ? `<p>${esc(d.summary || d.why_important || "")}</p>` : ""}
              <div class="cr4-meta-row">
                ${d.source_type ? `<small>${esc(`来源：${d.source_type}`)}</small>` : ""}
                ${d.time_horizon ? `<small>${esc(`时效：${d.time_horizon}`)}</small>` : ""}
              </div>
              ${d.validation_action ? `<em>${esc(`验证：${d.validation_action}`)}</em>` : ""}
            </div>`).join("")}
        </div>` : "";

      const skillList = skillPrios.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">能力投资优先级</div></div>
          ${skillPrios.map((s) => `
            ${skillBar(s.skill || String(s), s.importance === "高" ? 85 : s.importance === "低" ? 40 : 65,
              s.importance === "高" ? "linear-gradient(90deg,var(--cr4-primary),var(--cr4-primary-light))" :
              s.importance === "低" ? "linear-gradient(90deg,#94a3b8,#cbd5e1)" :
              "linear-gradient(90deg,var(--cr4-secondary),#38bdf8)")}
            ${(s.reason || s.priority_reason) ? `<div class="cr4-inline-note">${esc(s.reason || s.priority_reason || "")}</div>` : ""}
          `).join("")}
        </div>` : "";

      const riskList = risks.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">风险信号</div></div>
          <div class="cr4-gap-grid">
            ${risks.map((r, i) => gapPill(String(r), i === 0 ? "urgent" : "warn")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        ${summary ? `<div class="cr4-summary-banner">${esc(summary)}</div>` : ""}
        <div class="cr4-stat-row">${statCards.join("")}</div>
        <div class="cr4-grid-2">${hotList}${skillList}</div>
        ${riskList}`;
    }

    function renderPositioningBody(data) {
      const explainability = data.explainability || {};
      const tracks      = Array.isArray(data.recommended_tracks)       ? data.recommended_tracks      : [];
      const hyps        = Array.isArray(data.hypotheses_for_evidence)  ? data.hypotheses_for_evidence : [];
      const constraints = Array.isArray(data.constraints_hard)         ? data.constraints_hard        : [];
      const summary     = data.user_intent_summary || "";

      const trackCards = tracks.map((t, i) => `
        <div class="cr4-track-card ${i === 0 ? "cr4-track-primary" : ""}">
          <div class="cr4-track-priority">${i === 0 ? "P0 主推荐" : `P${i} 备选`}</div>
          <div class="cr4-track-name">${esc(String(t))}</div>
          ${hyps[i]?.reason ? `<div class="cr4-track-copy">${esc(hyps[i].reason)}</div>` : ""}
          ${hyps[i] ? `<div class="cr4-track-prove">须证明：${esc((hyps[i].must_prove || []).slice(0, 2).join("、"))}</div>` : ""}
        </div>`).join("");

      const constraintBlock = constraints.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">硬约束</div></div>
          <div class="cr4-gap-grid">
            ${constraints.map((c) => gapPill(String(c), "warn")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        ${summary ? `<div class="cr4-summary-banner">${esc(summary)}</div>` : ""}
        <div class="cr4-stat-row">
          ${statCard("推荐方向", tracks.length || "—", "条并行假设", "cr4-ac-purple")}
          ${statCard("硬约束", constraints.length || "0", "项限制条件", "cr4-ac-amber")}
          ${statCard("证据命题", hyps.reduce((n, h) => n + (h.must_prove || []).length, 0) || "—", "项待验证", "cr4-ac-blue")}
        </div>
        ${tracks.length ? `<div class="cr4-track-grid">${trackCards}</div>` : ""}
        ${constraintBlock}`;
    }

    function renderResumeBody(data) {
      const explainability = data.explainability || {};
      const skills  = Array.isArray(data.technical_skills)    ? data.technical_skills.slice(0, 8)   : [];
      const genComp = Array.isArray(data.general_competencies) ? data.general_competencies.slice(0, 6) : [];
      const gaps    = Array.isArray(data.gaps)                 ? data.gaps.slice(0, 4)               : [];
      const hyps    = Array.isArray(data.hypothesis_support)   ? data.hypothesis_support              : [];

      const strengthCount = skills.filter((s) => s.strength === "strong").length;
      const gapCount = gaps.length;

      const skillBars = skills.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">专业技能证据</div><div class="cr4-card-sub">技术能力</div></div>
          ${skills.map((s) => skillBar(s.skill || String(s),
            s.strength === "strong" ? 88 : s.strength === "medium" ? 65 : 38,
            s.strength === "strong" ? "linear-gradient(90deg,var(--cr4-primary),var(--cr4-primary-light))" :
            s.strength === "medium" ? "linear-gradient(90deg,var(--cr4-secondary),#38bdf8)" :
            "linear-gradient(90deg,#f59e0b,#fbbf24)")).join("")}
        </div>` : "";

      const genBars = genComp.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">通用能力证据</div><div class="cr4-card-sub">软技能</div></div>
          ${genComp.map((g) => skillBar(g.competency || String(g),
            g.strength === "strong" ? 85 : g.strength === "medium" ? 62 : 35,
            "linear-gradient(90deg,var(--cr4-success),#34d399)")).join("")}
        </div>` : "";

      const gapBlock = gaps.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">证据缺口</div></div>
          <div class="cr4-gap-grid">
            ${gaps.map((g, i) => gapPill(String(g.claim_in_resume || g.issue || g), i === 0 ? "urgent" : "warn")).join("")}
          </div>
          <div class="cr4-detail-stack">
            ${gaps.map((g) => `
              <div class="cr4-detail-item">
                <strong>${esc(String(g.claim_in_resume || "证据缺口"))}</strong>
                ${g.why_it_matters ? `<p>${esc(g.why_it_matters)}</p>` : ""}
                ${g.suggestion ? `<em>${esc(`建议：${g.suggestion}`)}</em>` : ""}
              </div>
            `).join("")}
          </div>
        </div>` : "";

      const traceBlock = (skills.length || genComp.length) ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">判断依据回指</div><div class="cr4-card-sub">哪些结论能指回简历</div></div>
          <div class="cr4-detail-stack">
            ${skills.slice(0, 3).map((s) => `
              <div class="cr4-detail-item">
                <strong>${esc(s.skill || "")}</strong>
                ${s.note || s.why_counts_as_evidence ? `<p>${esc(s.note || s.why_counts_as_evidence || "")}</p>` : ""}
                ${Array.isArray(s.evidence_ids) && s.evidence_ids.length ? `<small>${esc(`证据 ID：${s.evidence_ids.join("、")}`)}</small>` : `<small>当前未识别到明确证据 ID</small>`}
              </div>
            `).join("")}
            ${genComp.slice(0, 2).map((g) => `
              <div class="cr4-detail-item">
                <strong>${esc(g.competency || "")}</strong>
                ${g.note || g.why_counts_as_evidence ? `<p>${esc(g.note || g.why_counts_as_evidence || "")}</p>` : ""}
                ${Array.isArray(g.evidence_ids) && g.evidence_ids.length ? `<small>${esc(`证据 ID：${g.evidence_ids.join("、")}`)}</small>` : `<small>当前未识别到明确证据 ID</small>`}
              </div>
            `).join("")}
          </div>
        </div>` : "";

      const hypBlock = hyps.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">方向假设对齐</div></div>
          ${hyps.map((h) => `
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(h.track || "")}</span>
              <span class="cr4-badge ${h.status === "supported" ? "cr4-badge-green" : h.status === "partial" ? "cr4-badge-amber" : h.status === "unsupported" ? "cr4-badge-red" : "cr4-badge-muted"}">
                ${esc(h.status === "supported" ? "已支持" : h.status === "partial" ? "部分支持" : h.status === "unsupported" ? "不支持" : "待核实")}
              </span>
            </div>`).join("")}
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("强证据", strengthCount || "—", "项可追溯", "cr4-ac-green")}
          ${statCard("证据缺口", gapCount || "0", "项待补充", "cr4-ac-amber")}
          ${statCard("通用能力", genComp.length || "—", "项", "cr4-ac-blue")}
        </div>
        <div class="cr4-grid-2">${skillBars}${genBars}</div>
        ${gapBlock}
        ${traceBlock}
        ${hypBlock}`;
    }

    function renderCompetencyBody(data) {
      const explainability = data.explainability || {};
      const dims     = data.dimensions || {};
      const strengths = Array.isArray(data.strengths) ? data.strengths.slice(0, 4) : [];
      const gaps     = Array.isArray(data.gaps)       ? data.gaps.slice(0, 4)      : [];

      const DIM_CFG = [
        { key: "professional_skills",       label: "专业技能",  icon: "📚", color: "var(--cr4-primary)",   accent: "cr4-dim-purple" },
        { key: "general_ability",           label: "通用能力",  icon: "💻", color: "var(--cr4-secondary)", accent: "cr4-dim-blue"   },
        { key: "communication_collaboration",label: "沟通协作", icon: "🤝", color: "var(--cr4-accent)",    accent: "cr4-dim-amber"  },
        { key: "learning_agility",          label: "学习力",    icon: "🚀", color: "var(--cr4-success)",   accent: "cr4-dim-green"  },
        { key: "execution",                 label: "执行力",    icon: "⚡", color: "var(--cr4-primary)",   accent: "cr4-dim-purple" },
        { key: "practice_maturity",         label: "实践力",    icon: "🔧", color: "var(--cr4-secondary)", accent: "cr4-dim-blue"   },
      ];

      const dimCards = DIM_CFG.map((cfg) => {
        const d = dims[cfg.key] || {};
        const level = String(d.level || "unknown");
        const score = gradeToScore(level);
        const conf  = String(d.confidence || "low");
        const confLabel = conf === "high" ? "高置信" : conf === "medium" ? "中置信" : "低置信/未知";
        return dimCard(cfg.icon, cfg.label, `等级 ${level.toUpperCase()} · ${confLabel}`, score, cfg.color, cfg.accent);
      }).join("");

      const overallScore = (() => {
        const scored = DIM_CFG.map((cfg) => gradeToScore((dims[cfg.key] || {}).level)).filter((s) => s > 0);
        return scored.length ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : 0;
      })();

      const strengthBlock = strengths.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">核心优势</div></div>
          ${strengths.map((s) => `<div class="cr4-row-item"><span class="cr4-row-label">✓ ${esc(String(s))}</span></div>`).join("")}
        </div>` : "";

      const gapBlock = gaps.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">短板与提升项</div></div>
          ${gaps.map((g, i) => `
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(g.dimension || String(g.id || ""))}</span>
              <span class="cr4-badge ${g.severity === "high" ? "cr4-badge-red" : g.severity === "medium" ? "cr4-badge-amber" : "cr4-badge-muted"}">${esc(g.severity === "high" ? "高" : g.severity === "medium" ? "中" : "低")}</span>
            </div>`).join("")}
        </div>` : "";

      const dimExplain = Object.entries(dims).length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">维度判断依据</div></div>
          <div class="cr4-detail-stack">
            ${Object.entries(dims).slice(0, 6).map(([key, value]) => {
              const entry = value && typeof value === "object" ? value : {};
              const reason = String(entry.judgement_reason || "").trim();
              const evidenceIds = Array.isArray(entry.evidence_ids) && entry.evidence_ids.length
                ? `证据 ID：${entry.evidence_ids.join("、")}`
                : "当前缺少明确证据 ID";
              const label = {"professional_skills":"专业技能","general_ability":"通用能力","communication_collaboration":"沟通协作","learning_agility":"学习力","execution":"执行力","practice_maturity":"实践力"}[key] || key;
              return `
                <div class="cr4-detail-item">
                  <strong>${esc(label)}</strong>
                  <p>${esc(reason || `当前等级为 ${String(entry.level || "unknown").toUpperCase()}，置信度 ${String(entry.confidence || "low")}`)}</p>
                  <small>${esc(evidenceIds)}</small>
                </div>
              `;
            }).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("综合能力分", overallScore || "—", "基于证据推算", "cr4-ac-purple")}
          ${statCard("核心优势", strengths.length || "—", "项", "cr4-ac-green")}
          ${statCard("短板项", gaps.length || "0", "项待提升", "cr4-ac-amber")}
        </div>
        <div class="cr4-dim-grid">${dimCards}</div>
        <div class="cr4-grid-2">${strengthBlock}${gapBlock}</div>
        ${dimExplain}`;
    }

    function renderMatchBody(data) {
      const explainability = data.explainability || {};
      const fitScore  = Number(data.fit_score || 0);
      const fitBand   = String(data.fit_band || "not_ready");
      const hardFails = Array.isArray(data.hard_failures) ? data.hard_failures.slice(0, 4) : [];
      const gapsArr   = Array.isArray(data.partial_gaps)  ? data.partial_gaps.slice(0, 5)  : [];
      const bandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || fitBand;
      const bandClass = fitBand === "strong" ? "cr4-badge-green" : fitBand === "moderate" ? "cr4-badge-blue" : fitBand === "weak" ? "cr4-badge-amber" : "cr4-badge-red";
      const scoreColor = fitScore >= 70 ? "#10b981" : fitScore >= 50 ? "#f59e0b" : "#ef4444";
      const circum = 2 * Math.PI * 54;
      const offset = circum * (1 - fitScore / 100);

      const scoreRing = `
        <div class="cr4-card cr4-match-score-card">
          <div class="cr4-card-title" style="margin-bottom:16px">综合契合度</div>
          <div class="cr4-match-circle">
            <svg width="140" height="140" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="54" fill="none" stroke="#e2e8f0" stroke-width="10"/>
              <circle cx="70" cy="70" r="54" fill="none" stroke="${scoreColor}" stroke-width="10"
                stroke-linecap="round" stroke-dasharray="${circum.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
                transform="rotate(-90 70 70)"/>
              <defs>
                <linearGradient id="cr4matchGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="${scoreColor}"/>
                  <stop offset="100%" stop-color="${scoreColor}88"/>
                </linearGradient>
              </defs>
            </svg>
            <div class="cr4-match-circle-text">
              <div class="cr4-match-circle-value" style="color:${scoreColor}">${fitScore}</div>
              <div class="cr4-match-circle-unit">/ 100</div>
            </div>
          </div>
          <div style="margin-top:12px">
            <div style="font-size:14px;font-weight:600;margin-bottom:6px">${esc(data.target_role || "目标岗位")}</div>
            <span class="cr4-badge ${bandClass}">${esc(bandLabel)}</span>
          </div>
          <div class="cr4-match-details">
            <div class="cr4-match-detail"><div class="cr4-match-detail-label">硬门槛缺口</div><div class="cr4-match-detail-val" style="color:var(--cr4-danger)">${hardFails.length}</div></div>
            <div class="cr4-match-detail"><div class="cr4-match-detail-label">待补强项</div><div class="cr4-match-detail-val" style="color:var(--cr4-accent)">${gapsArr.length}</div></div>
          </div>
        </div>`;

      const hardBlock = hardFails.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">硬门槛缺口</div></div>
          <div class="cr4-gap-grid">
            ${hardFails.map((f) => gapPill(String(f), "urgent")).join("")}
          </div>
        </div>` : "";

      const gapBlock = gapsArr.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">待补强项</div></div>
          ${gapsArr.map((g) => `
            <div class="cr4-detail-item">
              <div class="cr4-detail-head">
                <strong>${esc(g.requirement || String(g))}</strong>
                <span class="cr4-badge cr4-badge-amber">${esc(g.remediation_type || "待补充")}</span>
              </div>
              ${g.reason || g.note ? `<p>${esc(g.reason || g.note || "")}</p>` : ""}
              <div class="cr4-meta-row">
                ${g.evidence_basis ? `<small>${esc(`依据：${g.evidence_basis}`)}</small>` : ""}
                ${g.priority_reason ? `<small>${esc(`优先级：${g.priority_reason}`)}</small>` : ""}
              </div>
            </div>`).join("")}
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-match-layout">
          ${scoreRing}
          <div class="cr4-match-right">
            ${hardBlock}
            ${gapBlock}
          </div>
        </div>`;
    }

    function renderPathBody(data) {
      const explainability = data.explainability || {};
      const milestones = Array.isArray(data.milestones)    ? data.milestones    : [];
      const visions    = Array.isArray(data.vision_roles)  ? data.vision_roles  : [];
      const contin     = Array.isArray(data.contingency)   ? data.contingency   : [];
      const hardMust   = ((data.dependencies || {}).must_resolve_hard_failures || []);

      const timelineHtml = milestones.length ? milestones.slice(0, 5).map((m, i) => {
        const stateClass = i === 0 ? "current" : "future";
        return timelineItem(
          m.horizon || `阶段${i + 1}`,
          m.title || "",
          "",
          [m.reason, (m.actions || []).slice(0, 2).join("；")].filter(Boolean).join(" · "),
          [...(m.metrics || []), ...(m.linked_gap ? [`关联差距：${m.linked_gap}`] : [])],
          stateClass
        );
      }).join("") : "";

      const visionBlock = visions.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">长期愿景角色</div></div>
          ${visions.map((v, i) => `
            <div class="cr4-row-item">
              <span class="cr4-badge ${i === 0 ? "cr4-badge-purple" : "cr4-badge-blue"}">${i === 0 ? "主目标" : "远期"}</span>
              <span class="cr4-row-label">${esc(String(v))}</span>
            </div>`).join("")}
        </div>` : "";

      const continBlock = contin.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">B 计划 / 应急</div></div>
          ${contin.map((c) => `<div class="cr4-row-item"><span class="cr4-row-label">· ${esc(String(c))}</span></div>`).join("")}
        </div>` : "";

      const hardBlock = hardMust.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">必须先解决的硬门槛</div></div>
          <div class="cr4-gap-grid">
            ${hardMust.map((h) => gapPill(String(h), "urgent")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("里程碑", milestones.length || "—", "个阶段", "cr4-ac-blue")}
          ${statCard("长期角色", visions.length || "—", "个愿景", "cr4-ac-purple")}
          ${statCard("B计划", contin.length || "—", "条应急", "cr4-ac-green")}
        </div>
        <div class="cr4-grid-2">
          ${timelineHtml ? `<div class="cr4-card cr4-card-full"><div class="cr4-card-header"><div class="cr4-card-title">成长路径时间线</div></div><div class="cr4-timeline">${timelineHtml}</div></div>` : ""}
        </div>
        <div class="cr4-grid-2">${visionBlock}${continBlock}</div>
        ${hardBlock}`;
    }

    // ── render all sections ───────────────────────────────────────────────────

    const bodyRenderers = {
      industry_analysis:  renderIndustryBody,
      career_positioning: renderPositioningBody,
      resume_evidence:    renderResumeBody,
      competency_profile: renderCompetencyBody,
      role_match:         renderMatchBody,
      path_plan:          renderPathBody,
    };

    const allowedKeys = groupConfig ? new Set(groupConfig.sectionKeys || []) : null;
    const availableModules = navOrder
      .map((key, idx) => ({ key, idx, meta: navMeta[key], section: sections[key] }))
      .filter((item) => Boolean(item.section) && (!allowedKeys || allowedKeys.has(item.key)));

    const moduleIndexHtml = `
      <section class="cr4-report-index">
        <div>
          <p class="cr4-report-index-kicker">职业报告</p>
          <h3 class="cr4-report-index-title">报告模块目录</h3>
          <p class="cr4-report-index-copy">每个模块都先展示判断，再展示因为、依据与可验证动作，避免黑箱式职业建议。</p>
        </div>
        <div class="cr4-report-index-tree">
          <div class="cr4-report-index-root">职业报告</div>
          ${availableModules.map(({ meta }, index) => `
            <button type="button" class="cr4-report-index-item" data-report-scroll-target="${meta.anchor}">
              <span>${String(index + 1).padStart(2, "0")}</span>
              <strong>${esc(meta.label)}</strong>
              <small>${esc(meta.kicker)}</small>
            </button>
          `).join("")}
        </div>
      </section>
    `;

    const groupHeroHtml = groupConfig ? `
      <section class="cr4-group-hero">
        <div class="cr4-group-head">
          <div class="cr4-group-copy">
            <p class="cr4-group-kicker">${esc(groupConfig.label || "Report Module")}</p>
            <h3 class="cr4-group-title">${esc(groupConfig.title || "")}</h3>
            <p class="cr4-group-summary">${esc(groupConfig.summary || "")}</p>
            <div class="cr4-group-meta">
              <span>${esc(bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || "褰撳墠涓荤嚎宀椾綅")}</span>
              <span>${esc(`鐗堟湰 ${bundle?.meta?.version || "--"}`)}</span>
              <span>${esc(bundle?.meta?.generated_at || "--")}</span>
            </div>
          </div>
          <button type="button" class="career-report-secondary-btn cr4-group-action" onclick="openCareerReportEditor()">鏅鸿兘娑﹁壊</button>
        </div>
        <div class="cr4-group-stat-grid">
          ${availableModules.map(({ meta, section }) => {
            const markdown = String(section?.markdown || "").trim();
            const bodyText = String(section?.data?.industry_summary || section?.data?.user_intent_summary || section?.data?.target_role || section?.data?.fit_band || "").trim();
            return `
              <article class="cr4-group-stat">
                <span>${esc(meta.kicker)}</span>
                <strong>${esc(meta.label)}</strong>
                <small>${esc(bodyText || (markdown ? "宸茬敓鎴愭ā鍧楀唴瀹癸紝鍙互缁х画涓嬮捇鏌ョ湅銆?" : "璇ユā鍧楁殏鏃犺緭鍑哄唴瀹广€?"))}</small>
              </article>
            `;
          }).join("")}
        </div>
        <div class="cr4-group-module-strip">
          ${availableModules.map(({ meta }, index) => `
            <button type="button" class="cr4-group-module-pill" data-report-scroll-target="${meta.anchor}">
              <span>${String(index + 1).padStart(2, "0")}</span>
              <strong>${esc(meta.label)}</strong>
              <small>${esc(meta.kicker)}</small>
            </button>
          `).join("")}
        </div>
      </section>
    ` : "";

    const sectionHtml = availableModules.map(({ key, idx, meta, section: sec }) => {
      if (!sec) return "";
      const markdown = String(sec.markdown || "").trim();
      const data     = sec.data || {};
      const renderer = bodyRenderers[key];
      const body     = renderer ? renderer(data) : "";
      const polishTargetId = `cr4-polish-${key}`;

      return `
        <section id="${meta.anchor}" class="cr4-module ${meta.accentClass}">
          <div class="cr4-module-head">
            <div class="cr4-module-icon">${meta.icon}</div>
            <div class="cr4-module-titles">
              <div class="cr4-module-kicker">${esc(meta.kicker)}</div>
              <h3 class="cr4-module-title">${esc(meta.label)}</h3>
            </div>
            <div class="cr4-module-actions">
              <button type="button" class="cr4-polish-btn" data-report-polish-section="${esc(key)}" data-report-polish-target="${esc(polishTargetId)}">润色本段</button>
            </div>
            <div class="cr4-module-num">${String(idx + 1).padStart(2, "0")}</div>
          </div>
          <div class="cr4-module-body">${body}</div>
          <div id="${polishTargetId}" class="cr4-polish-output hidden"></div>
          ${markdown ? `
            <details class="cr4-module-detail">
              <summary>查看完整分析文本</summary>
              <div class="cr4-module-markdown">${renderMarkdownBasic(markdown)}</div>
            </details>` : `<p class="cr4-module-empty">该模块尚未生成内容</p>`}
        </section>`;
    }).filter(Boolean).join("");

    return `<div class="cr4-report-modules ${groupConfig ? "is-grouped" : ""}">${groupConfig ? groupHeroHtml : moduleIndexHtml}${sectionHtml}</div>`;
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
      ${renderReportFeedbackCard()}
    `;
  }

  function getUserCenterReportViewModeSafe() {
    return typeof window.getUserCenterReportViewMode === "function"
      ? String(window.getUserCenterReportViewMode() || "dashboard").trim().toLowerCase()
      : "report";
  }

  function getDashboardItemText(item) {
    if (item == null) return "";
    if (typeof item === "string" || typeof item === "number") return String(item).trim();
    if (typeof item === "object") {
      return String(
        item.name
        || item.skill
        || item.requirement
        || item.title
        || item.label
        || item.summary
        || item.text
        || item.claim_in_resume
        || item.competency
        || item.track
        || ""
      ).trim();
    }
    return "";
  }

  function normalizeExplainItem(item) {
    if (item == null) return null;
    if (typeof item === "string" || typeof item === "number") {
      const text = String(item).trim();
      return text ? { title: text, detail: "", meta: "", validate: "" } : null;
    }
    if (typeof item !== "object") return null;
    const title = String(
      item.title
      || item.label
      || item.name
      || item.skill
      || item.competency
      || item.requirement
      || item.track
      || getDashboardItemText(item)
      || ""
    ).trim();
    const detail = String(
      item.detail
      || item.summary
      || item.reason
      || item.note
      || item.why_important
      || item.priority_reason
      || item.because
      || ""
    ).trim();
    const metaParts = [];
    if (item.source_type) metaParts.push(`来源：${item.source_type}`);
    if (item.time_horizon) metaParts.push(`时效：${item.time_horizon}`);
    if (item.status) metaParts.push(`状态：${item.status}`);
    if (item.evidence) metaParts.push(String(item.evidence).trim());
    if (Array.isArray(item.evidence_ids) && item.evidence_ids.length) {
      metaParts.push(`证据 ID：${item.evidence_ids.join("、")}`);
    }
    const validate = String(item.validate || item.validation_action || "").trim();
    if (!title && !detail && !metaParts.length && !validate) return null;
    return {
      title: title || detail || metaParts[0] || "待补充",
      detail: title ? detail : "",
      meta: metaParts.join(" · "),
      validate,
    };
  }

  function renderDashboardList(title, items, placeholder = "暂无补充") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item) || {
        title: getDashboardItemText(item),
        detail: "",
        meta: "",
        validate: "",
      })
      .filter((item) => item.title);
    return `
      <div class="ucrd-list-block">
        <div class="ucrd-list-title">${esc(title)}</div>
        ${normalized.length ? `
          <ul class="ucrd-list">
            ${normalized.map((item) => `
              <li>
                <strong>${esc(item.title)}</strong>
                ${item.detail ? `<span>${esc(item.detail)}</span>` : ""}
                ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
                ${item.validate ? `<em>${esc(`验证：${item.validate}`)}</em>` : ""}
              </li>
            `).join("")}
          </ul>
        ` : `<p class="ucrd-list-empty">${esc(placeholder)}</p>`}
      </div>
    `;
  }

  function renderDashboardItemCluster(title, items, empty = "暂无补充") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item))
      .filter(Boolean);
    return `
      <div class="ucrd-trace-block">
        <div class="ucrd-list-title">${esc(title)}</div>
        ${normalized.length ? normalized.map((item) => `
          <article class="ucrd-trace-item">
            <strong>${esc(item.title)}</strong>
            ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
            ${item.validate ? `<em>${esc(`验证：${item.validate}`)}</em>` : ""}
          </article>
        `).join("") : `<p class="ucrd-list-empty">${esc(empty)}</p>`}
      </div>
    `;
  }

  function renderReasonGroup(label, items, empty = "") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item))
      .filter(Boolean);
    if (!normalized.length && !empty) return "";
    return `
      <div class="ucrd-mini-group">
        <span>${esc(label)}</span>
        ${normalized.length ? `
          <ul>
            ${normalized.map((item) => `
              <li>
                <strong>${esc(item.title)}</strong>
                ${item.detail ? `<small>${esc(item.detail)}</small>` : ""}
              </li>
            `).join("")}
          </ul>
        ` : `<p>${esc(empty)}</p>`}
      </div>
    `;
  }

  function renderFullReportHeader(bundle, tracker) {
    const meta = bundle?.meta || {};
    const matchOutput = bundle?.match_output || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(matchOutput.fit_score || 0)));
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(matchOutput.fit_band || "")] || "待评估";
    return `
      <section class="ucrd-full-head">
        <div class="ucrd-full-head-copy">
          <p class="ucrd-kicker">Complete Report</p>
          <h2 class="ucrd-full-head-title">${esc(meta.title || "职业规划报告")}</h2>
          <p class="ucrd-full-head-summary">${formatText(bundle?.report_document?.executive_summary || meta.summary || "完整报告将按模块展开行业判断、能力证据、岗位匹配与路径规划。每个模块先展示判断，再展示因为、依据与可验证动作。")}</p>
        </div>
        <div class="ucrd-full-head-meta">
          <span>主岗位：${esc(focusRole)}</span>
          <span>匹配：${esc(`${fitScore}% · ${fitBandLabel}`)}</span>
          <span>版本：${esc(meta.version || "--")}</span>
          <span>生成时间：${esc(meta.generated_at || "--")}</span>
        </div>
      </section>
    `;
  }

  function getReportFitTone(fitBand, score = 0) {
    const normalized = String(fitBand || "").trim().toLowerCase();
    if (normalized === "strong" || score >= 75) return { label: "较高", tone: "high" };
    if (normalized === "moderate" || score >= 45) return { label: "中等", tone: "medium" };
    if (normalized === "weak" || score > 0) return { label: "较低", tone: "low" };
    return { label: "尚需准备", tone: "blocked" };
  }

  function normalizeReportDimensions(dimensions) {
    const labelMap = {
      professional_skills: "专业技能",
      general_ability: "通用能力",
      communication_collaboration: "沟通协作",
      learning_agility: "学习力",
      execution: "执行力",
      practice_maturity: "实践力",
      user_research: "用户研究",
      data_analysis: "数据分析",
      management: "管理能力",
      ai_application: "AI 应用",
      planning: "产品规划"
    };
    const scoreMap = {
      strong: 86,
      high: 86,
      moderate: 62,
      medium: 62,
      basic: 42,
      low: 42,
      weak: 28,
      unknown: 16
    };
    const levelLabelMap = {
      strong: "优势",
      high: "优势",
      moderate: "中等",
      medium: "中等",
      basic: "待提升",
      low: "待提升",
      weak: "短板",
      unknown: "待补证据"
    };
    const rawEntries = Array.isArray(dimensions)
      ? dimensions.map((item, index) => [item?.key || item?.id || item?.dimension || `dimension_${index}`, item])
      : Object.entries(dimensions || {});
    return rawEntries.slice(0, 6).map(([key, value]) => {
      const level = String(value?.level || value?.status || "unknown").trim().toLowerCase();
      const score = Math.max(0, Math.min(100, Number(value?.score ?? scoreMap[level] ?? 16)));
      const confidence = String(value?.confidence || "").trim();
      const evidenceIds = Array.isArray(value?.evidence_ids) ? value.evidence_ids : [];
      return {
        key,
        label: labelMap[key] || String(value?.label || key).trim(),
        level,
        levelLabel: levelLabelMap[level] || "待判断",
        score,
        confidence,
        reason: String(value?.judgement_reason || value?.reason || value?.summary || "").trim(),
        evidenceIds
      };
    });
  }

  function collectUniqueExplainItems(...sources) {
    const seen = new Set();
    const result = [];
    sources.forEach((source) => {
      (Array.isArray(source) ? source : []).forEach((item) => {
        const normalized = normalizeExplainItem(item) || (() => {
          const title = getDashboardItemText(item);
          return title ? { title, detail: "", meta: "", validate: "" } : null;
        })();
        if (!normalized || !normalized.title) return;
        const key = `${normalized.title}__${normalized.detail}`;
        if (seen.has(key)) return;
        seen.add(key);
        result.push(normalized);
      });
    });
    return result;
  }

  function renderReportDocChips(items) {
    const texts = (Array.isArray(items) ? items : [])
      .map((item) => {
        if (typeof item === "string" || typeof item === "number") return String(item).trim();
        const normalized = normalizeExplainItem(item);
        return normalized ? normalized.title : "";
      })
      .filter(Boolean);
    if (!texts.length) return "";
    return `
      <div class="crdoc-chip-row">
        ${texts.map((text) => `<span class="crdoc-chip">${esc(text)}</span>`).join("")}
      </div>
    `;
  }

  function renderReportDocList(items, emptyText = "暂无补充", limit = 4) {
    const normalized = collectUniqueExplainItems(items).slice(0, limit);
    if (!normalized.length) {
      return `<p class="crdoc-empty">${esc(emptyText)}</p>`;
    }
    return `
      <ul class="crdoc-list">
        ${normalized.map((item) => `
          <li class="crdoc-list-item">
            <strong>${esc(item.title)}</strong>
            ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
            ${item.validate ? `<em>${esc(`可验证：${item.validate}`)}</em>` : ""}
          </li>
        `).join("")}
      </ul>
    `;
  }

  function renderCapabilityRadar(entries) {
    const normalized = Array.isArray(entries) ? entries.slice(0, 6) : [];
    if (!normalized.length) {
      return `<div class="crdoc-radar-empty">等待能力画像生成</div>`;
    }
    const center = 110;
    const radius = 74;
    const levels = [0.25, 0.5, 0.75, 1];
    const axisCount = normalized.length;
    const toPoint = (value, index, multiplier = 1) => {
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / axisCount);
      const currentRadius = radius * multiplier * value;
      return {
        x: center + Math.cos(angle) * currentRadius,
        y: center + Math.sin(angle) * currentRadius
      };
    };
    const polygon = normalized.map((entry, index) => {
      const point = toPoint(Math.max(0.12, entry.score / 100), index);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    }).join(" ");
    const gridPolygons = levels.map((level) => normalized.map((_, index) => {
      const point = toPoint(1, index, level);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    }).join(" "));
    const axes = normalized.map((entry, index) => {
      const linePoint = toPoint(1, index);
      const labelPoint = toPoint(1, index, 1.18);
      const anchor = labelPoint.x < center - 18 ? "end" : labelPoint.x > center + 18 ? "start" : "middle";
      return `
        <g>
          <line x1="${center}" y1="${center}" x2="${linePoint.x.toFixed(1)}" y2="${linePoint.y.toFixed(1)}"></line>
          <text x="${labelPoint.x.toFixed(1)}" y="${labelPoint.y.toFixed(1)}" text-anchor="${anchor}">${esc(entry.label)}</text>
        </g>
      `;
    }).join("");
    return `
      <svg class="crdoc-radar-svg" viewBox="0 0 220 220" aria-hidden="true">
        <g class="crdoc-radar-grid">
          ${gridPolygons.map((points) => `<polygon points="${points}"></polygon>`).join("")}
          ${axes}
        </g>
        <polygon class="crdoc-radar-area" points="${polygon}"></polygon>
        ${normalized.map((entry, index) => {
          const point = toPoint(Math.max(0.12, entry.score / 100), index);
          return `<circle class="crdoc-radar-dot" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.6"></circle>`;
        }).join("")}
      </svg>
    `;
  }

  function bindReportDocNavigation(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const buttons = Array.from(root.querySelectorAll("[data-report-doc-nav-target]"));
    const sections = buttons
      .map((button) => {
        const targetId = String(button.dataset.reportDocNavTarget || "").trim();
        if (!targetId) return null;
        const target = root.querySelector(`#${targetId}`);
        return target ? { button, target, targetId } : null;
      })
      .filter(Boolean);
    if (!sections.length) return;

    const setActive = (targetId) => {
      buttons.forEach((button) => {
        const active = String(button.dataset.reportDocNavTarget || "").trim() === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    };

    sections.forEach(({ button, target, targetId }) => {
      button.addEventListener("click", () => {
        setActive(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    setActive(sections[0].targetId);
    if (typeof window.IntersectionObserver !== "function") return;

    const observer = new window.IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible?.target?.id) return;
      setActive(visible.target.id);
    }, {
      threshold: [0.25, 0.45, 0.65],
      rootMargin: "-18% 0px -52% 0px"
    });

    sections.forEach(({ target }) => observer.observe(target));
  }

  function renderReportDashboard(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 3) : [];
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? bundle?.match_output?.fit_score ?? 0)));
    const fitBandLabel = String(dashboardSummary.fit_band_label || "").trim()
      || ({"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(bundle?.match_output?.fit_band || "")] || "待评估");
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    const thisWeek = Array.isArray(nextActions.this_week) ? nextActions.this_week : [];
    const next30Days = nextActions.next_30_days || {};
    const marketHot = Array.isArray(marketSignals.hot_directions) ? marketSignals.hot_directions : [];
    const marketSkills = Array.isArray(marketSignals.skill_priorities) ? marketSignals.skill_priorities : [];
    const headlineBecause = Array.isArray(dashboardSummary.headline_because) ? dashboardSummary.headline_because : [];
    const confidenceSources = Array.isArray(dashboardSummary.confidence_sources) ? dashboardSummary.confidence_sources : [];
    const actionItems = Array.isArray(nextActions.action_items) ? nextActions.action_items : [];
    const priorityLogic = Array.isArray(nextActions.priority_logic) ? nextActions.priority_logic : [];
    const evidenceTrace = Array.isArray(evidenceHealth.evidence_trace) ? evidenceHealth.evidence_trace : [];
    const signalCards = Array.isArray(marketSignals.signal_cards) ? marketSignals.signal_cards : [];
    const headline = String(dashboardSummary.headline || meta.summary || reportDocument.executive_summary || "").trim() || `当前建议优先围绕 ${focusRole} 推进。`;
    const rationale = String(dashboardSummary.rationale || reportDocument.executive_summary || meta.summary || "").trim();

    const roleBars = roleRankings.length
      ? roleRankings.map((role) => {
          const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
          const fitSummary = String(role?.fit_summary || role?.summary || "").trim();
          const because = Array.isArray(role?.because) ? role.because : [];
          const requiredSkills = Array.isArray(role?.required_skills) ? role.required_skills.slice(0, 4) : [];
          return `
            <article class="ucrd-role-row">
              <div class="ucrd-role-row-head">
                <strong>${esc(role?.name || role?.title || "候选岗位")}</strong>
                <span>${score}%</span>
              </div>
              <div class="ucrd-role-bar"><i style="width:${score}%"></i></div>
              ${fitSummary ? `<p>${esc(fitSummary)}</p>` : ""}
              ${because.length ? `<div class="ucrd-role-because">${because.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
              ${requiredSkills.length ? `<div class="ucrd-role-tags">${requiredSkills.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""}
            </article>
          `;
        }).join("")
      : `<p class="ucrd-list-empty">候选岗位对比会在匹配结果生成后显示。</p>`;

    return `
      <div class="ucrd-dashboard">
        <section class="ucrd-hero">
          <div class="ucrd-hero-copy">
            <p class="ucrd-kicker">Decision Cockpit</p>
            <h2 class="ucrd-hero-title">${esc(headline)}</h2>
            <p class="ucrd-hero-summary">${formatText(rationale || `当前主线岗位是 ${focusRole}，建议先围绕差距补强和证据补齐再推进求职动作。`)}</p>
            ${headlineBecause.length ? `
              <div class="ucrd-hero-because">
                <span>因为</span>
                <ul>
                  ${headlineBecause.map((item) => `<li>${esc(item)}</li>`).join("")}
                </ul>
              </div>
            ` : ""}
            <div class="ucrd-hero-meta">
              <span>主岗位：${esc(focusRole)}</span>
              <span>匹配判断：${esc(fitBandLabel)}</span>
              <span>生成时间：${esc(meta.generated_at || "--")}</span>
              <span>版本：${esc(meta.version || "--")}</span>
            </div>
            ${confidenceSources.length ? `<div class="ucrd-source-strip">${confidenceSources.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
          </div>
          <div class="ucrd-hero-side">
            <div class="ucrd-score-pod">
              <strong>${fitScore}%</strong>
              <span>${esc(fitBandLabel)}</span>
            </div>
            <button type="button" class="career-report-primary-btn" data-user-center-report-view="report">查看完整报告</button>
          </div>
        </section>

        <section class="ucrd-section">
          <div class="ucrd-section-head">
            <div>
              <p class="ucrd-kicker">Role Comparison</p>
              <h3>候选岗位对比</h3>
            </div>
          </div>
          <div class="ucrd-role-grid">${roleBars}</div>
        </section>

        <div class="ucrd-grid">
          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Decision Logic</p>
                <h3>为什么推荐 / 为什么暂缓</h3>
              </div>
            </div>
            <div class="ucrd-decision-grid">
              ${decisionCards.map((card) => `
                <article class="ucrd-decision-card ${esc(card?.tone || "neutral")}">
                  <span class="ucrd-decision-label">${esc(card?.label || "判断")}</span>
                  <h4>${esc(card?.title || "待补充")}</h4>
                  <p>${esc(card?.summary || "")}</p>
                  ${Array.isArray(card?.items) && card.items.length ? `
                    <ul>
                      ${card.items.map((item) => `<li>${esc(getDashboardItemText(item))}</li>`).join("")}
                    </ul>
                  ` : ""}
                  ${renderReasonGroup("因为", card?.because)}
                  ${renderReasonGroup("依据", card?.evidence)}
                  ${renderReasonGroup("可验证动作", card?.validate)}
                </article>
              `).join("")}
            </div>
          </section>

          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Evidence Health</p>
                <h3>核心差距与证据健康</h3>
              </div>
            </div>
            <p class="ucrd-panel-summary">${esc(String(evidenceHealth.summary || "证据健康度将在报告完成后汇总。"))}</p>
            <div class="ucrd-list-grid">
              ${renderDashboardList("硬门槛缺口", evidenceHealth.hard_failures, "当前未发现明确硬门槛")}
              ${renderDashboardList("待补强技能", evidenceHealth.skill_gaps, "暂未识别到明确补强项")}
              ${renderDashboardList("简历证据缺失", evidenceHealth.evidence_gaps, "当前简历证据已覆盖核心判断")}
              ${renderDashboardList("缺失输入项", evidenceHealth.missing_inputs, "当前没有明显缺失输入")}
            </div>
            ${renderDashboardItemCluster("判断依据回指", evidenceTrace, "等待证据映射生成")}
          </section>
        </div>

        <div class="ucrd-grid">
          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Action Plan</p>
                <h3>下一阶段行动计划</h3>
              </div>
            </div>
            <div class="ucrd-action-grid">
              <article class="ucrd-action-card">
                <span>本周先做什么</span>
                ${thisWeek.length ? `<ul>${thisWeek.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p>等待短期计划生成。</p>`}
              </article>
              <article class="ucrd-action-card">
                <span>30 天目标</span>
                <strong>${esc(String(next30Days.title || "建立短期推进主线"))}</strong>
                ${Array.isArray(next30Days.tasks) && next30Days.tasks.length ? `<ul>${next30Days.tasks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p>等待阶段任务同步。</p>`}
              </article>
              <article class="ucrd-action-card">
                <span>失败后的 B 计划</span>
                <p>${esc(String(nextActions.plan_b || "先保留次优岗位探索，同时继续补项目和证据。"))}</p>
                ${Array.isArray(nextActions.checkpoints) && nextActions.checkpoints.length ? `
                  <div class="ucrd-checkpoints">
                    ${nextActions.checkpoints.map((item) => `<small>${esc(item.label || "复查节点")} · ${esc(item.summary || "")}</small>`).join("")}
                  </div>
                ` : ""}
              </article>
            </div>
            ${priorityLogic.length ? `<div class="ucrd-source-strip">${priorityLogic.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
            ${renderDashboardItemCluster("行动建议为什么这样排", actionItems, "等待阶段动作生成")}
          </section>

          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Market Signals</p>
                <h3>行业信号与能力投资</h3>
              </div>
            </div>
            ${marketSignals.overview ? `<p class="ucrd-panel-summary">${esc(marketSignals.overview)}</p>` : ""}
            <div class="ucrd-list-grid">
              ${renderDashboardList("热门方向", marketHot, "等待行业热点判断")}
              ${renderDashboardList("能力优先级", marketSkills, "等待能力投资建议")}
              ${renderDashboardList("风险信号", marketSignals.risk_signals, "当前未识别明显风险")}
              ${renderDashboardList("验证动作", marketSignals.verification_actions, "等待验证动作建议")}
            </div>
            ${renderDashboardItemCluster("趋势判断依据", signalCards, "等待趋势依据生成")}
          </section>
        </div>

        <div class="ucrd-feedback">
          ${renderReportFeedbackCard()}
        </div>
      </div>
    `;
  }

  function renderReportDashboardV2(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const next30Days = nextActions.next_30_days || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const industryStory = reportDocument.industry_story || {};
    const roleCards = Array.isArray(reportDocument.role_cards) ? reportDocument.role_cards : [];
    const planBoard = reportDocument.plan_board || {};
    const explainabilitySummary = reportDocument.explainability_summary || {};
    const competencyProfile = bundle?.competency_profile || {};
    const matchOutput = bundle?.match_output || {};
    const pathPlan = bundle?.path_plan || {};
    const explainabilityOverview = reportDocument.explainability_overview || {};
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? matchOutput.fit_score ?? 0)));
    const fitBandLabel = String(dashboardSummary.fit_band_label || "").trim()
      || ({"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(matchOutput.fit_band || "")] || "待评估");
    const dimensions = normalizeReportDimensions(competencyProfile.dimensions);
    const headline = String(dashboardSummary.headline || meta.summary || reportDocument.executive_summary || "").trim() || `当前建议优先围绕 ${focusRole} 推进。`;
    const rationale = String(dashboardSummary.rationale || reportDocument.executive_summary || meta.summary || "").trim()
      || `先围绕 ${focusRole} 解决硬门槛和证据缺口，再推进求职动作。`;
    const headlineBecause = Array.isArray(dashboardSummary.headline_because) ? dashboardSummary.headline_because : (Array.isArray(explainabilitySummary.headline_because) ? explainabilitySummary.headline_because : []);
    const strengths = collectUniqueExplainItems(evidenceHealth.strengths, competencyProfile.strengths);
    const gaps = collectUniqueExplainItems(
      evidenceHealth.hard_failures,
      evidenceHealth.skill_gaps,
      evidenceHealth.evidence_gaps,
      evidenceHealth.missing_inputs,
      matchOutput.partial_gaps
    );
    const roles = (roleCards.length
      ? roleCards.map((item) => ({
          name: item?.role_name || "",
          overall_score: item?.fit_score || 0,
          fit_summary: item?.fit_summary || "",
          required_skills: Array.isArray(item?.required_skills) ? item.required_skills : [],
          because: Array.isArray(item?.why_fit) ? item.why_fit : [],
          hard_gaps: Array.isArray(item?.hard_gaps) ? item.hard_gaps : [],
          partial_gaps: Array.isArray(item?.partial_gaps) ? item.partial_gaps : [],
          switch_path: item?.switch_path || "",
          promotion_path: item?.promotion_path || ""
        }))
      : (Array.isArray(bundle?.role_rankings) ? [...bundle.role_rankings] : []))
      .sort((left, right) => {
        const leftName = String(left?.name || left?.title || "").trim();
        const rightName = String(right?.name || right?.title || "").trim();
        const leftFocus = leftName && focusRole && leftName.includes(focusRole);
        const rightFocus = rightName && focusRole && rightName.includes(focusRole);
        if (leftFocus && !rightFocus) return -1;
        if (!leftFocus && rightFocus) return 1;
        return Number(right?.overall_score || 0) - Number(left?.overall_score || 0);
      })
      .slice(0, 3);
    const signals = (Array.isArray(marketSignals.signal_cards) && marketSignals.signal_cards.length
      ? marketSignals.signal_cards
      : Array.isArray(industryStory.highlight_items) && industryStory.highlight_items.length
        ? industryStory.highlight_items.map((item) => ({
            title: item?.title || "",
            summary: item?.summary || "",
            source_type: item?.source || "",
            time_horizon: item?.published_label || "",
            validation_action: item?.topic || ""
          }))
        : collectUniqueExplainItems(marketSignals.hot_directions)).slice(0, 3);
    const milestones = Array.isArray(pathPlan.milestones) ? pathPlan.milestones : [];
    const actionItems = Array.isArray(planBoard.action_items) && planBoard.action_items.length ? planBoard.action_items.slice(0, 4) : (Array.isArray(nextActions.action_items) ? nextActions.action_items.slice(0, 4) : []);
    const planHorizons = Array.isArray(planBoard.horizons) ? planBoard.horizons : [];
    const shortPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "short_term")?.items)
      ? planHorizons.find((item) => item?.key === "short_term").items
      : (Array.isArray(nextActions.this_week) ? nextActions.this_week.map((item) => ({ title: item })) : []);
    const mediumPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "mid_term")?.items)
      ? planHorizons.find((item) => item?.key === "mid_term").items
      : (Array.isArray(next30Days.tasks) ? next30Days.tasks.map((item) => ({ title: item })) : []);
    const longPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "long_term")?.items)
      ? planHorizons.find((item) => item?.key === "long_term").items
      : (Array.isArray(nextActions.checkpoints) ? nextActions.checkpoints : []);
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    const sectionHead = (index, kicker, title, copy) => `
      <div class="crdoc-section-head">
        <span class="crdoc-section-index">${esc(index)}</span>
        <div>
          <p class="crdoc-section-kicker">${esc(kicker)}</p>
          <h3>${esc(title)}</h3>
          ${copy ? `<p>${esc(copy)}</p>` : ""}
        </div>
      </div>
    `;

    const dimensionRows = dimensions.length
      ? dimensions.map((entry) => `
          <article class="crdoc-dimension-row">
            <div class="crdoc-dimension-head">
              <strong>${esc(entry.label)}</strong>
              <span class="crdoc-level-pill ${esc(entry.level)}">${esc(entry.levelLabel)}</span>
            </div>
            <div class="crdoc-progress"><i style="width:${entry.score}%"></i></div>
            ${entry.reason ? `<p>${esc(entry.reason)}</p>` : ""}
          </article>
        `).join("")
      : `<p class="crdoc-empty">等待能力维度生成。</p>`;

    return `
      <div class="crdoc-page">
        <section class="crdoc-hero">
          <div class="crdoc-hero-copy">
            <p class="crdoc-kicker">Career Report</p>
            <h2>${esc(meta.title || "职业发展报告")}</h2>
            <p class="crdoc-hero-summary">${esc(headline)}</p>
            <p class="crdoc-hero-body">${esc(rationale)}</p>
            ${headlineBecause.length ? `<div class="crdoc-why-block"><span>为什么会得出这个结论</span>${renderReportDocList(headlineBecause.map((item) => ({ title: item })), "等待结论依据", 4)}</div>` : ""}
            ${renderReportDocChips(dashboardSummary.confidence_sources)}
          </div>
          <aside class="crdoc-hero-aside">
            <div class="crdoc-stat-card"><span>当前主岗位</span><strong>${esc(focusRole)}</strong></div>
            <div class="crdoc-stat-card"><span>匹配判断</span><strong>${esc(`${fitScore}%`)}</strong><small>${esc(fitBandLabel)}</small></div>
            <div class="crdoc-stat-card"><span>生成时间</span><strong>${esc(meta.generated_at || "--")}</strong><small>版本 ${esc(meta.version || "--")}</small></div>
            <button type="button" class="career-report-primary-btn crdoc-hero-cta" data-user-center-report-view="report">查看完整报告</button>
          </aside>
        </section>

        <nav class="crdoc-nav" aria-label="报告段落导航">
          <button type="button" class="crdoc-nav-btn active" data-report-doc-nav-target="reportDocSection-position" aria-pressed="true">① 当前定位</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-trends" aria-pressed="false">② 行业趋势</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-targets" aria-pressed="false">③ 目标岗位对比</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-path" aria-pressed="false">④ 职业路径图</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-plan" aria-pressed="false">⑤ 提升计划</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-summary" aria-pressed="false">⑥ 关键判断</button>
        </nav>

        <section id="reportDocSection-position" class="crdoc-section">
          ${sectionHead("01", "Current Position", "你现在的定位", "判断、原因、证据回指放在同一屏里。")}
          <div class="crdoc-position-grid">
            <article class="crdoc-card">
              <div class="crdoc-card-topline"><span class="crdoc-card-label">当前判断</span><span class="crdoc-card-meta">${esc(focusRole)}</span></div>
              <h4>${esc(headline)}</h4>
              <p>${esc(rationale)}</p>
              <div class="crdoc-two-col">
                <div class="crdoc-mini-card"><span>已证实的优势</span>${renderReportDocList(strengths, "当前更像是证据不足，不建议把未验证优势当结论。", 4)}</div>
                <div class="crdoc-mini-card"><span>优先补强项</span>${renderReportDocList(gaps, "当前没有额外缺口提示。", 4)}</div>
              </div>
            </article>
            <article class="crdoc-card">
              <div class="crdoc-card-topline"><span class="crdoc-card-label">能力画像</span><span class="crdoc-card-meta">每个维度都附判断理由</span></div>
              <div class="crdoc-radar-wrap">${renderCapabilityRadar(dimensions)}<div class="crdoc-dimension-list">${dimensionRows}</div></div>
            </article>
          </div>
          <article class="crdoc-card">
            <div class="crdoc-card-topline"><span class="crdoc-card-label">判断依据回指</span></div>
            ${renderReportDocList(evidenceHealth.evidence_trace, "当前这份报告的主要限制是输入证据还不够完整。", 4)}
          </article>
        </section>

        <section id="reportDocSection-trends" class="crdoc-section">
          ${sectionHead("02", "Industry Trends", "行业趋势（与你相关）", "把趋势结论、来源类型、时效性和验证动作放在一起。")}
          ${industryStory.narrative ? `
            <article class="crdoc-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">行业现状</span>
                <span class="crdoc-card-meta">${esc(industryStory.snapshot_label || "本地热点快照")}</span>
              </div>
              <h4>${esc(industryStory.refresh_rule || "本地热点语料快照")}</h4>
              <p>${esc(industryStory.narrative)}</p>
            </article>
          ` : ""}
          <div class="crdoc-trend-grid">
            ${signals.length ? signals.map((item, index) => {
              const normalized = normalizeExplainItem(item) || { title: getDashboardItemText(item), detail: "", validate: "" };
              const raw = typeof item === "object" && item ? item : {};
              return `
                <article class="crdoc-trend-card">
                  <div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(index === 0 ? "优先关注" : index === 1 ? "重点观察" : "持续跟进")}</span><span class="crdoc-card-meta">${esc(String(raw.time_horizon || "趋势观察"))}</span></div>
                  <h4>${esc(normalized.title)}</h4>
                  ${(raw.summary || raw.why_important || normalized.detail) ? `<p>${esc(raw.summary || raw.why_important || normalized.detail || "")}</p>` : ""}
                  <div class="crdoc-fact-row"><span>来源</span><strong>${esc(String(raw.source_type || "综合判断"))}</strong></div>
                  ${(normalized.validate || raw.validation_action) ? `<div class="crdoc-meaning-box"><span>你可以怎么验证</span><p>${esc(normalized.validate || raw.validation_action || "")}</p></div>` : ""}
                </article>
              `;
            }).join("") : `<article class="crdoc-card"><p class="crdoc-empty">等待行业趋势生成。</p></article>`}
          </div>
          <div class="crdoc-two-col">
            <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">能力投资优先级</span></div>${renderReportDocList(marketSignals.skill_priorities, "等待能力投资建议。", 4)}</article>
            <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">风险与验证</span></div>${renderReportDocList(marketSignals.risk_signals, "当前未识别明确风险。", 3)}${renderReportDocList(marketSignals.verification_actions, "等待验证动作。", 3)}</article>
          </div>
        </section>

        <section id="reportDocSection-targets" class="crdoc-section">
          ${sectionHead("03", "Target Roles", "目标岗位对比", "不只给总分，还拆成为什么进入候选和还差什么。")}
          <div class="crdoc-target-grid-main">
            ${roles.length ? roles.map((role, index) => {
              const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
              return `
                <article class="crdoc-target-card ${esc(getReportFitTone(index === 0 ? matchOutput.fit_band : "", score).tone)}">
                  <div class="crdoc-target-head"><div><h4>${esc(role?.name || role?.title || "候选岗位")}</h4><span>${esc(index === 0 ? "当前主线" : `候选方向 ${index + 1}`)}</span></div><div class="crdoc-target-score"><strong>${score}</strong><small>分</small></div></div>
                  <div class="crdoc-target-bar"><i style="width:${score}%"></i></div>
                  ${role?.fit_summary ? `<p class="crdoc-target-summary">${esc(role.fit_summary)}</p>` : ""}
                  ${Array.isArray(role?.required_skills) && role.required_skills.length ? `<div class="crdoc-chip-row">${role.required_skills.slice(0, 4).map((skill) => `<span class="crdoc-chip crdoc-chip--blue">${esc(skill)}</span>`).join("")}</div>` : ""}
                  <div class="crdoc-two-col">
                    <div class="crdoc-mini-card"><span>${esc(index === 0 ? "为什么推荐" : "为什么会进入候选")}</span>${renderReportDocList(index === 0 ? collectUniqueExplainItems(matchOutput.why_match, role?.because) : role?.because, "当前还缺少明确支持项", 3)}</div>
                    <div class="crdoc-mini-card"><span>${esc(index === 0 ? "还差什么" : "关键要求")}</span>${renderReportDocList(index === 0 ? collectUniqueExplainItems(role?.partial_gaps, role?.hard_gaps, matchOutput.partial_gaps, matchOutput.hard_failures) : collectUniqueExplainItems(role?.hard_gaps, role?.partial_gaps, Array.isArray(role?.required_skills) ? role.required_skills.map((skill) => ({ title: skill, detail: "该岗位的高频硬要求" })) : []), "当前没有额外门槛提示", 3)}</div>
                  </div>
                </article>
              `;
            }).join("") : `<article class="crdoc-card"><p class="crdoc-empty">等待岗位匹配结果生成。</p></article>`}
          </div>
        </section>

        <section id="reportDocSection-path" class="crdoc-section">
          ${sectionHead("04", "Career Path", "职业路径图", "让用户看到推荐这条路的前提条件、里程碑和风险。")}
          <div class="crdoc-path-grid">
            <div class="crdoc-timeline">
              <article class="crdoc-timeline-card done"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><div class="crdoc-card-topline"><span class="crdoc-card-label">当前判断</span><span class="crdoc-card-meta">${esc(meta.generated_at || "--")}</span></div><h4>${esc(focusRole)}</h4><p>${esc(rationale)}</p></div></article>
              ${milestones.length ? milestones.map((item, index) => `<article class="crdoc-timeline-card ${index === 0 ? "current" : ""}"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(index === 0 ? "下一步" : index === 1 ? "中期" : "长期")}</span><span class="crdoc-card-meta">${esc(String(item?.horizon || "--"))}</span></div><h4>${esc(String(item?.title || "阶段目标"))}</h4>${item?.reason ? `<p>${esc(item.reason)}</p>` : ""}${renderReportDocList((Array.isArray(item?.actions) ? item.actions : []).map((action) => ({ title: action, detail: item?.priority_reason || item?.linked_gap || "" })), "等待阶段动作", 4)}</div></article>`).join("") : `<article class="crdoc-timeline-card"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><p class="crdoc-empty">等待路径规划生成。</p></div></article>`}
            </div>
            <div class="crdoc-stack">
              <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">路径推荐理由</span></div>${renderReportDocList(pathPlan.path_rationale, "等待路径解释。", 4)}</article>
              <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">前提条件与风险</span></div>${renderReportDocList(pathPlan.dependencies?.must_resolve_hard_failures, "当前未标出必须先解决的硬门槛。", 3)}${renderReportDocList(pathPlan.path_risks, "当前未标出显性路径风险。", 3)}${renderReportDocList(pathPlan.contingency, "当前没有 B 计划提示。", 3)}</article>
            </div>
          </div>
        </section>

        <section id="reportDocSection-plan" class="crdoc-section">
          ${sectionHead("05", "Action Plan", "提升计划", "每条建议都要说明它对应哪个判断，以及为什么排在前面。")}
          <div class="crdoc-plan-grid">
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">短期（0-30 天）</span><span class="crdoc-card-meta">先补硬门槛</span></div>${renderReportDocList(shortPlanActions, "等待短期动作。", 4)}${Array.isArray(nextActions.priority_logic) && nextActions.priority_logic.length ? `<div class="crdoc-meaning-box"><span>为什么先做这些</span><p>${esc(nextActions.priority_logic[0])}</p></div>` : ""}</article>
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">中期（1-6 个月）</span><span class="crdoc-card-meta">${esc(String(milestones[1]?.horizon || "能力沉淀"))}</span></div>${renderReportDocList(mediumPlanActions, "等待中期动作。", 4)}</article>
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">长期（6-12 个月）</span><span class="crdoc-card-meta">${esc(String(milestones[2]?.horizon || "形成路径闭环"))}</span></div>${renderReportDocList(longPlanActions, "等待长期动作。", 4)}${nextActions.plan_b ? `<div class="crdoc-meaning-box"><span>如果主线受阻</span><p>${esc(String(nextActions.plan_b))}</p></div>` : ""}</article>
          </div>
          <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">行动建议与闭环说明</span></div><div class="crdoc-action-detail-grid">${actionItems.length ? actionItems.map((item) => `<article class="crdoc-mini-card"><span>${esc(String(item?.window || "行动建议"))}</span><h4>${esc(String(item?.title || "待补充"))}</h4>${item?.reason ? `<p>${esc(item.reason)}</p>` : ""}${item?.linked_judgement ? `<small>${esc(`对应判断：${item.linked_judgement}`)}</small>` : ""}${item?.priority_reason ? `<em>${esc(`优先级原因：${item.priority_reason}`)}</em>` : ""}</article>`).join("") : `<p class="crdoc-empty">等待行动建议生成。</p>`}</div></article>
        </section>

        <section id="reportDocSection-summary" class="crdoc-section">
          ${sectionHead("06", "Key Judgements", "关键判断", "把“是什么”后面的“为什么”直接写出来，帮助用户建立信任。")}
          <div class="crdoc-insight-grid">
            <article class="crdoc-insight-card breakthrough"><div class="crdoc-card-topline"><span class="crdoc-card-label">最快突破口</span></div><p class="crdoc-insight-summary">${esc(String(decisionCards.find((card) => card?.tone === "positive")?.title || actionItems[0]?.title || "先把最影响投递通过率的硬门槛补齐。"))}</p>${renderReportDocList((decisionCards.find((card) => card?.tone === "positive")?.because || [actionItems[0]?.priority_reason || actionItems[0]?.reason || "优先解决最影响投递反馈的问题。"]).map((item) => ({ title: item })), "等待原因说明", 3)}</article>
            <article class="crdoc-insight-card risk"><div class="crdoc-card-topline"><span class="crdoc-card-label">最需要警惕的风险</span></div><p class="crdoc-insight-summary">${esc(String(decisionCards.find((card) => card?.tone === "risk")?.title || explainabilityOverview.match?.judgement || "不要在证据不足时直接相信岗位匹配结论。"))}</p>${renderReportDocList((decisionCards.find((card) => card?.tone === "risk")?.because || explainabilityOverview.match?.because || []).map((item) => ({ title: item })), "等待原因说明", 3)}</article>
            <article class="crdoc-insight-card strength"><div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(strengths.length ? "当前已能保留的优势" : "当前最值得保留的基础")}</span></div><p class="crdoc-insight-summary">${esc(strengths[0]?.title || decisionCards.find((card) => card?.tone === "neutral")?.title || explainabilityOverview.positioning?.judgement || "当前最有价值的不是盲目扩岗位，而是保持主线聚焦。")}</p>${renderReportDocList((strengths.length ? [strengths[0]] : (decisionCards.find((card) => card?.tone === "neutral")?.because || explainabilityOverview.positioning?.because || []).map((item) => ({ title: item }))), "等待原因说明", 3)}</article>
          </div>
          <div class="crdoc-feedback-wrap">${renderReportFeedbackCard()}</div>
        </section>
      </div>
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

    if (status === "queued" || status === "running") {
      host.innerHTML = `
        <div class="career-report-banner-main running">
          <div>
            <h3 class="career-report-banner-title">职业报告正在生成</h3>
            <p class="career-report-banner-copy">${formatText(state?.stage_detail || state?.summary || "后台正在按阶段生成职业报告，请稍候。")}</p>
          </div>
          <div class="career-report-banner-meta">
            <span>阶段：${esc(state?.stage_label || "编排中")}</span>
            <span>主岗位：${esc(bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || state?.focus_role_id || "待识别")}</span>
          </div>
        </div>
      `;
      return;
    }

    if (status === "failed") {
      host.innerHTML = `
        <div class="career-report-banner-main failed">
          <div>
            <h3 class="career-report-banner-title">职业报告生成失败</h3>
            <p class="career-report-banner-copy">${formatText(state?.error_message || "请检查画像输入和模型配置后重试。")}</p>
          </div>
        </div>
      `;
      return;
    }

    if (historical) {
      host.innerHTML = `
        <div class="career-report-banner-main">
          <div>
            <h3 class="career-report-banner-title">当前正在查看历史版本</h3>
            <p class="career-report-banner-copy">当前页面只读，任务勾选和进度同步不会写回服务端。</p>
          </div>
          <div class="career-report-banner-meta">
            <span>版本：${esc(bundle?.meta?.version || "--")}</span>
            <span>时间：${esc(bundle?.meta?.generated_at || "--")}</span>
          </div>
        </div>
      `;
      return;
    }

    host.innerHTML = "";
  }

  function renderReportFeedbackCard() {
    const feedback = getCareerReportFeedback();
    const selectedVerdict = reportRuntime.feedbackVerdict || feedback?.latest_verdict || "partial";
    const noteValue = reportRuntime.feedbackNote || "";
    const summary = String(
      feedback?.summary
      || "标记本版是否准确。你的反馈会被写入下次职业报告生成链路。"
    ).trim();
    const latestMeta = feedback?.count
      ? `最近一次：${getFeedbackVerdictLabel(feedback?.latest_verdict)}${feedback?.last_updated ? ` · ${feedback.last_updated}` : ""}`
      : "还没有记录过纠偏反馈。";

    return `
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Feedback Loop</p>
        <h3 class="career-report-side-title">纠偏反馈</h3>
        <p class="career-report-side-copy">${formatText(summary)}</p>
        <div class="career-report-feedback-actions" data-report-feedback-root="1">
          ${[
            ["accurate", "基本准确"],
            ["partial", "部分准确"],
            ["off_target", "明显偏差"]
          ].map(([value, label]) => `
            <button
              type="button"
              class="career-report-feedback-pill${selectedVerdict === value ? " active" : ""}"
              data-report-feedback-verdict="${esc(value)}"
            >${esc(label)}</button>
          `).join("")}
        </div>
        <textarea
          class="career-report-feedback-input"
          data-report-feedback-note="1"
          rows="4"
          placeholder="补充哪里不准、漏了什么，或者哪些判断值得保留。"
        >${esc(noteValue)}</textarea>
        <div class="career-report-feedback-foot">
          <span class="career-report-feedback-meta">${esc(latestMeta)}</span>
          <button type="button" class="career-report-primary-btn career-report-feedback-submit" data-report-feedback-submit="1">保存反馈</button>
        </div>
      </section>
    `;
  }

  async function submitCareerReportFeedback(verdict, note) {
    const bundle = window.appState?.careerReport || null;
    const payload = await requestJsonSafe("/api/career-report/feedback", {
      method: "POST",
      body: {
        verdict,
        note,
        report_id: bundle?.meta?.report_id || "",
        focus_role_id: bundle?.meta?.focus_role_id || "",
        focus_role_name: bundle?.report_document?.focus_role_name || ""
      }
    });
    reportRuntime.feedbackVerdict = payload?.feedback?.latest_verdict || verdict;
    reportRuntime.feedbackNote = "";
    applyCareerReportState(undefined, getCareerReportTracker(), payload.state || getCareerReportStateSafe(), {
      keepBundle: true,
      historical: Boolean(window.appState?.careerReportViewingHistorical),
      userCenterRefresh: true
    });
    return payload;
  }

  function bindCareerReportFeedbackHandlers(root) {
    if (!root || typeof root.querySelector !== "function") return;
    const feedbackNoteInput = root.querySelector("[data-report-feedback-note]");
    if (feedbackNoteInput) {
      feedbackNoteInput.addEventListener("input", () => {
        reportRuntime.feedbackNote = feedbackNoteInput.value || "";
      });
    }
    root.querySelectorAll("[data-report-feedback-verdict]").forEach((button) => {
      button.addEventListener("click", () => {
        reportRuntime.feedbackVerdict = String(button.dataset.reportFeedbackVerdict || "partial").trim() || "partial";
        root.querySelectorAll("[data-report-feedback-verdict]").forEach((item) => {
          item.classList.toggle("active", item === button);
        });
      });
    });
    const feedbackSubmitButton = root.querySelector("[data-report-feedback-submit]");
    if (feedbackSubmitButton) {
      feedbackSubmitButton.addEventListener("click", async () => {
        const verdict = reportRuntime.feedbackVerdict || getCareerReportFeedback()?.latest_verdict || "partial";
        const note = String(feedbackNoteInput?.value || reportRuntime.feedbackNote || "").trim();
        try {
          await submitCareerReportFeedback(verdict, note);
          if (feedbackNoteInput) feedbackNoteInput.value = "";
          toast("反馈已记录", "下一次生成职业报告时会优先吸收这条纠偏信息。", "success", 2200);
        } catch (error) {
          toast("反馈保存失败", error.message || "请稍后重试。", "error", 2200);
        }
      });
    }
  }

  async function polishCareerReportSection(sectionKey, targetId, button) {
    const key = String(sectionKey || "").trim();
    const targetIdText = String(targetId || "").trim();
    const targetSelector = targetIdText ? `#${escapeSelectorId(targetIdText)}` : "";
    const target = (targetSelector ? button?.closest(".cr4-module")?.querySelector(targetSelector) : null)
      || document.getElementById(targetIdText);
    const section = window.appState?.careerReport?.report_document?.sections?.[key] || null;
    const text = String(section?.markdown || "").trim();
    if (!key || !text) {
      toast("暂无可润色内容", "该模块还没有完整正文。", "warning", 1800);
      return;
    }
    const originalText = button?.textContent || "";
    if (button) {
      button.disabled = true;
      button.textContent = "润色中";
    }
    try {
      const payload = await requestJsonSafe("/api/career-report/polish", {
        method: "POST",
        body: {
          section_key: key,
          text
        }
      });
      if (target) {
        target.classList.remove("hidden");
        target.innerHTML = `
          <div class="cr4-polish-output-head">
            <strong>润色版本</strong>
            <span>只优化表达，不新增事实</span>
          </div>
          <div class="cr4-polish-output-body">${renderMarkdownBasic(payload.polished || "")}</div>
        `;
      }
      toast("润色完成", "已生成该模块的润色版本。", "success", 1800);
    } catch (error) {
      toast("润色失败", error.message || "请检查模型配置后重试。", "error", 2200);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText || "润色本段";
      }
    }
  }

  function bindReportPolishHandlers(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-report-polish-section]").forEach((button) => {
      button.addEventListener("click", () => {
        void polishCareerReportSection(
          button.dataset.reportPolishSection || "",
          button.dataset.reportPolishTarget || "",
          button
        );
      });
    });
  }

  function bindReportScrollHandlers(root, container) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-report-scroll-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = String(button.dataset.reportScrollTarget || "").trim();
        if (!targetId) return;
        const target = container?.querySelector?.(`#${escapeSelectorId(targetId)}`) || document.getElementById(targetId);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  // section definitions for nav
  const SECTION_NAV = [
    { key: "industry_analysis",  label: "行业与需求侧判断", icon: "01", anchor: "cr-sec-industry" },
    { key: "career_positioning", label: "职业定位假设",     icon: "02", anchor: "cr-sec-positioning" },
    { key: "resume_evidence",    label: "简历证据链",       icon: "03", anchor: "cr-sec-resume" },
    { key: "competency_profile", label: "能力评估画像",     icon: "04", anchor: "cr-sec-competency" },
    { key: "role_match",         label: "岗位匹配结论",     icon: "05", anchor: "cr-sec-match" },
    { key: "path_plan",          label: "阶段学习路径",     icon: "06", anchor: "cr-sec-path" },
  ];

  const REPORT_WORKSPACE_GROUPS = {
    trends: {
      label: "\u884c\u4e1a\u8d8b\u52bf",
      title: "\u884c\u4e1a\u5224\u65ad\u4e0e\u5f53\u524d\u804c\u4e1a\u5b9a\u4f4d",
      summary: "\u5148\u770b\u884c\u4e1a\u666f\u6c14\u5ea6\u3001\u5c97\u4f4d\u9700\u6c42\u53d8\u5316\u548c\u4f60\u5f53\u524d\u9002\u5408\u7684\u5207\u5165\u65b9\u5411\uff0c\u907f\u514d\u76f4\u63a5\u628a\u62a5\u544a\u53d8\u6210\u4e00\u6574\u9875\u5806\u5b57\u3002",
      sectionKeys: ["industry_analysis", "career_positioning"]
    },
    matching: {
      label: "\u5c97\u4f4d\u5339\u914d",
      title: "\u8bc1\u636e\u3001\u80fd\u529b\u4e0e\u76ee\u6807\u5c97\u4f4d\u7684\u5339\u914d\u5224\u65ad",
      summary: "\u628a\u7b80\u5386\u8bc1\u636e\u3001\u80fd\u529b\u753b\u50cf\u548c\u76ee\u6807\u5c97\u4f4d\u8981\u6c42\u62c6\u5f00\u5bf9\u7167\uff0c\u6e05\u6670\u770b\u5230\u5f53\u524d\u5dee\u8ddd\u3001\u4f18\u52bf\u4e0e\u9700\u8981\u8865\u8bc1\u7684\u70b9\u3002",
      sectionKeys: ["resume_evidence", "competency_profile", "role_match"]
    },
    plan: {
      label: "\u89c4\u5212\u8def\u5f84",
      title: "\u5206\u9636\u6bb5\u8865\u9f50\u80fd\u529b\u5e76\u5f62\u6210\u6267\u884c\u8def\u7ebf",
      summary: "\u628a\u957f\u671f\u76ee\u6807\u62c6\u6210\u8fd1\u671f\u52a8\u4f5c\u3001\u9636\u6bb5\u76ee\u6807\u548c\u91cc\u7a0b\u7891\uff0c\u4fbf\u4e8e\u540e\u7eed\u7ee7\u7eed\u7f16\u8f91\u3001\u68c0\u67e5\u548c\u5bfc\u51fa\u3002",
      sectionKeys: ["path_plan"]
    }
  };
  window.CAREER_REPORT_WORKSPACE_GROUPS = REPORT_WORKSPACE_GROUPS;

  function isModularBundle(bundle) {
    const sections = bundle?.report_document?.sections;
    return sections && !Array.isArray(sections) && typeof sections === "object";
  }

  function getReportTocItems(bundle) {
    const sections = bundle?.report_document?.sections;
    if (sections && !Array.isArray(sections) && typeof sections === "object") {
      return SECTION_NAV
        .filter((item) => Boolean(sections[item.key]))
        .map((item, index) => ({
          id: item.anchor,
          title: item.label,
          kicker: item.icon,
          index
        }));
    }
    const legacySections = Array.isArray(sections) ? sections : [];
    return legacySections.map((section, index) => ({
      id: getReportSectionDomId(section, index),
      title: section.title || section.kicker || `章节 ${index + 1}`,
      kicker: section.kicker || "",
      index
    }));
  }

  function renderReportAside() {
    const aside = document.getElementById("careerReportAside");
    if (!aside) return;

    const state = getCareerReportStateSafe();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";
    const viewMode = getUserCenterReportViewModeSafe();
    if (generating || viewMode !== "report") {
      aside.innerHTML = "";
      aside.classList.add("career-report-aside--hidden");
      return;
    }
    aside.classList.remove("career-report-aside--hidden");

    const bundle = window.appState?.careerReport || null;
    if (!bundle?.report_document) {
      aside.innerHTML = "";
      return;
    }
    const tracker = getCareerReportTracker();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "待识别";
    const isModular = isModularBundle(bundle);
    const matchOutput = bundle?.match_output || {};
    const fitScore = Number(matchOutput.fit_score || bundle?.role_rankings?.[0]?.overall_score || 0);
    const fitBand = String(matchOutput.fit_band || "");
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || "--";

    const moduleNavHtml = isModular ? `
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Contents</p>
        <h3 class="career-report-side-title">章节目录</h3>
        <nav class="cr4-module-nav">
          ${SECTION_NAV.map((sec) => {
            const hasData = Boolean(bundle?.report_document?.sections?.[sec.key]?.markdown);
            return `
              <button type="button" class="cr4-module-nav-btn${hasData ? "" : " muted"}"
                data-report-scroll-target="${sec.anchor}">
                <span class="cr4-module-nav-icon">${sec.icon}</span>
                <span>${esc(sec.label)}</span>
                ${hasData ? "" : '<span class="cr4-module-nav-empty">待生成</span>'}
              </button>
            `;
          }).join("")}
        </nav>
      </section>
    ` : "";

    aside.innerHTML = `
      <section class="career-report-side-card primary">
        <p class="career-report-side-kicker">Snapshot</p>
        <h3 class="career-report-side-title">${esc(bundle?.meta?.title || "职业报告")}</h3>
        <p class="career-report-side-copy">${formatText(bundle?.report_document?.executive_summary || bundle?.meta?.summary || "完整报告将围绕当前主岗位展开。")}</p>
        <div class="career-report-side-metrics">
          <article>
            <span>主岗位</span>
            <strong>${esc(focusRole)}</strong>
          </article>
          <article>
            <span>匹配判断</span>
            <strong>${esc(`${fitScore}% · ${fitBandLabel}`)}</strong>
          </article>
          <article>
            <span>版本</span>
            <strong>${esc(bundle?.meta?.version || tracker?.report_version || "--")}</strong>
          </article>
        </div>
      </section>
      ${moduleNavHtml}
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
      ${renderReportFeedbackCard()}
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

    bindCareerReportFeedbackHandlers(aside);
  }

  function renderReportMain() {
    const main = document.getElementById("careerReportMain");
    if (!main) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const state = getCareerReportStateSafe();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";

    if (generating) {
      main.innerHTML = renderReportGenerationMain(state, progress);
      return;
    }

    if (!bundle || !bundle.report_document) {
      main.innerHTML = renderEmptyReportMain();
      return;
    }

    const viewMode = getUserCenterReportViewModeSafe();
    const activeGroup = typeof window.getUserCenterReportModule === "function"
      ? String(window.getUserCenterReportModule() || "trends").trim().toLowerCase()
      : "trends";
    main.innerHTML = viewMode === "report"
      ? `
        ${renderHistoricalNotice()}
        ${renderFullReportHeader(bundle, tracker)}
        ${renderReportSections(bundle, { group: activeGroup })}
      `
      : `
        ${renderHistoricalNotice()}
        ${renderReportDashboardV2(bundle, tracker)}
      `;

    main.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
    main.querySelectorAll("[data-user-center-report-view]").forEach((button) => {
      button.addEventListener("click", () => {
        window.setUserCenterReportViewMode?.(button.dataset.userCenterReportView || "report");
      });
    });
    bindCareerReportFeedbackHandlers(main);
    if (viewMode === "report") {
      bindReportPolishHandlers(main);
      bindReportScrollHandlers(main, main);
    } else {
      bindReportDocNavigation(main);
    }
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
    const tocItems = getReportTocItems(bundle);
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
        ${tocItems.map((section, index) => `
          <button type="button" class="rv-toc-item${index === 0 ? " active" : ""}" data-rv-target="${esc(section.id)}">
            <span class="rv-toc-num">${String(index + 1).padStart(2, "0")}</span>
            <span>${esc(section.title || `章节 ${index + 1}`)}</span>
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
        ? `${renderHistoricalNotice()}${renderFullReportHeader(bundle, tracker)}${renderReportSections(bundle)}`
        : renderEmptyReportMain();
      if (bundle && bundle.report_document) {
        bindCareerReportFeedbackHandlers(main);
        bindReportPolishHandlers(main);
        bindReportScrollHandlers(main, main);
      }
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
    const state = getCareerReportStateSafe();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";
    const layout = document.querySelector("#report-workspace .career-report-layout");
    if (layout) {
      layout.classList.toggle("career-report-layout--generating", generating);
    }
    renderReportAside();
    renderReportMain();
    renderReportViewer();
    window.applyUserCenterReportReaderGate?.();
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

  function renderReportEditorSectionMap(source) {
    const host = document.getElementById("reportEditorSectionMap");
    if (!host) return;
    const items = Array.isArray(source?.section_map) ? source.section_map : [];
    host.innerHTML = items.length
      ? items.map((item, index) => `
          <button type="button" class="report-editor-section-item" data-editor-scroll-index="${index}">
            <strong>${esc(item?.label || `章节 ${index + 1}`)}</strong>
            <small>${esc(String(item?.markdown || "").slice(0, 60) || "点击快速定位")}</small>
          </button>
        `).join("")
      : `<div class="report-editor-section-item active"><strong>暂无章节</strong><small>等待源文稿加载</small></div>`;

    host.querySelectorAll("[data-editor-scroll-index]").forEach((button) => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.editorScrollIndex || 0);
        const textarea = document.getElementById("reportEditorTextarea");
        const section = items[index];
        if (!textarea || !section) return;
        const label = String(section.label || "").trim();
        const anchor = label ? `## ${label}` : "";
        const position = anchor ? textarea.value.indexOf(anchor) : -1;
        if (position >= 0) {
          textarea.focus();
          textarea.setSelectionRange(position, position);
        }
      });
    });
  }

  function renderReportEditorSnapshotList(source) {
    const host = document.getElementById("reportEditorSnapshotList");
    if (!host) return;
    const reportId = String(source?.report_id || window.appState?.careerReport?.meta?.report_id || "").trim();
    const snapshots = Array.isArray(window.appState?.careerReport?.draft_snapshots) ? window.appState.careerReport.draft_snapshots : [];
    const activeSnapshotId = String(source?.snapshot_id || "").trim();
    const activeFormal = !activeSnapshotId;
    const formalTitle = esc(window.appState?.careerReport?.meta?.title || "正式职业报告");
    host.innerHTML = `
      <button type="button" class="report-editor-snapshot-item${activeFormal ? " active" : ""}" data-editor-source-report="${esc(reportId)}">
        <strong>${formalTitle}</strong>
        <small>正式报告基线</small>
      </button>
      ${snapshots.map((snapshot) => `
        <button type="button" class="report-editor-snapshot-item${String(snapshot?.snapshot_id || "") === activeSnapshotId ? " active" : ""}" data-editor-source-snapshot="${esc(snapshot?.snapshot_id || "")}">
          <strong>${esc(snapshot?.title || snapshot?.label || "编辑快照")}</strong>
          <small>${esc(snapshot?.updated_at || snapshot?.created_at || "--")}</small>
        </button>
      `).join("")}
    `;
    host.querySelector("[data-editor-source-report]")?.addEventListener("click", () => {
      void openCareerReportEditor({ reportId, snapshotId: "" });
    });
    host.querySelectorAll("[data-editor-source-snapshot]").forEach((button) => {
      button.addEventListener("click", () => {
        const snapshotId = String(button.dataset.editorSourceSnapshot || "").trim();
        if (!snapshotId) return;
        void openCareerReportEditor({ reportId, snapshotId });
      });
    });
  }

  function clipReportEditorText(value, limit = 180) {
    const text = String(value || "").trim().replace(/\s+/g, " ");
    if (!text) return "";
    if (text.length <= limit) return text;
    return `${text.slice(0, Math.max(0, limit - 3))}...`;
  }

  function appendReportEditorMessage(role, label, body, tone = role) {
    const next = {
      role: String(role || "system"),
      tone: String(tone || role || "system"),
      label: String(label || role || "System"),
      body: String(body || "").trim()
    };
    reportRuntime.editorConversation = [
      ...(Array.isArray(reportRuntime.editorConversation) ? reportRuntime.editorConversation : []),
      next
    ].slice(-10);
  }

  function renderReportEditorChatLog() {
    const host = document.getElementById("reportEditorChatLog");
    if (!host) return;
    const messages = Array.isArray(reportRuntime.editorConversation) ? reportRuntime.editorConversation : [];
    if (!messages.length) {
      const selectionText = clipReportEditorText(reportRuntime.editorSelection?.text || "", 120);
      const hint = selectionText
        ? `\u5df2\u9009\u4e2d\u5185\u5bb9\uff1a${selectionText}\u3002\u5728\u53f3\u4fa7\u8f93\u5165\u4f60\u5e0c\u671b AI \u600e\u4e48\u4fee\uff0c\u7cfb\u7edf\u4f1a\u5148\u751f\u6210 diff \u5efa\u8bae\uff0c\u4e0d\u4f1a\u81ea\u52a8\u8986\u76d6\u6b63\u6587\u3002`
        : "\u5148\u5728\u5de6\u4fa7\u9009\u4e2d\u9700\u8981\u4fee\u6539\u7684\u51e0\u884c\uff0c\u6216\u8005\u76f4\u63a5\u5bf9\u6574\u7bc7\u62a5\u544a\u53d1\u8d77\u6da6\u8272\u3002";
      host.innerHTML = `
        <div class="report-editor-chat-item system">
          <span class="report-editor-chat-role">Workflow</span>
          <p>${esc(hint)}</p>
        </div>
      `;
      return;
    }
    host.innerHTML = messages.map((item) => `
      <div class="report-editor-chat-item ${esc(item?.tone || item?.role || "system")}">
        <span class="report-editor-chat-role">${esc(item?.label || item?.role || "System")}</span>
        <p>${esc(item?.body || "")}</p>
      </div>
    `).join("");
    host.scrollTop = host.scrollHeight;
  }

  function renderReportEditorCheckPanel(checkResult) {
    const panel = document.getElementById("reportEditorCheckPanel");
    if (!panel) return;
    const result = checkResult && typeof checkResult === "object" ? checkResult : null;
    const issues = Array.isArray(result?.issues) ? result.issues : [];
    if (!result) {
      panel.classList.add("hidden");
      panel.innerHTML = "";
      return;
    }
    const statusLabel = result.status === "pass"
      ? "\u901a\u8fc7"
      : `\u5f85\u5904\u7406 ${issues.length} \u9879`;
    panel.classList.remove("hidden");
    panel.innerHTML = `
      <div class="report-editor-diff-head">
        <div>
          <p class="report-editor-kicker">Completeness Check</p>
          <h3 class="report-editor-title">\u5185\u5bb9\u5b8c\u6574\u6027\u4e0e\u53ef\u89e3\u91ca\u6027\u68c0\u67e5</h3>
        </div>
        <span>${esc(statusLabel)}</span>
      </div>
      ${issues.length ? issues.map((item) => `
        <div class="report-editor-check-item">
          <strong>${esc(item?.type || "issue")}</strong>
          <div>${esc(item?.message || "\u5b58\u5728\u5f85\u5904\u7406\u95ee\u9898")}</div>
        </div>
      `).join("") : `
        <div class="report-editor-check-item">
          <strong>\u68c0\u67e5\u901a\u8fc7</strong>
          <div>\u5f53\u524d\u62a5\u544a\u7ed3\u6784\u5b8c\u6574\uff0c\u5173\u952e\u5224\u65ad\u4e0e\u8bc1\u636e\u94fe\u8def\u5df2\u8fbe\u5230\u57fa\u672c\u8981\u6c42\u3002</div>
        </div>
      `}
    `;
  }

  function renderReportEditorDiffPanel() {
    const panel = document.getElementById("reportEditorDiffPanel");
    if (!panel) return;
    const diff = reportRuntime.editorDiff;
    if (!diff || !Array.isArray(diff.diff_blocks) || !diff.diff_blocks.length) {
      panel.classList.add("hidden");
      panel.innerHTML = "";
      return;
    }
    panel.classList.remove("hidden");
    panel.innerHTML = `
      <div class="report-editor-diff-head">
        <div>
          <p class="report-editor-kicker">Diff Review</p>
          <h3 class="report-editor-title">AI \u6da6\u8272\u63d0\u6848</h3>
          <p class="report-editor-meta">\u53f3\u4fa7\u662f\u5efa\u8bae\u7248\uff0c\u5de6\u4fa7\u662f\u539f\u6587\u3002\u4f60\u786e\u8ba4\u540e\u518d Keep All \u5199\u56de\u6b63\u6587\u3002</p>
        </div>
        <div class="report-editor-actions">
          <button type="button" class="career-report-secondary-btn" id="reportEditorUndoBtn">Undo</button>
          <button type="button" class="career-report-primary-btn" id="reportEditorKeepAllBtn">Keep All</button>
        </div>
      </div>
      <div class="report-editor-diff-compare">
        <div class="report-editor-diff-card original">
          <span>Original</span>
          <pre>${esc(String(diff.original || ""))}</pre>
        </div>
        <div class="report-editor-diff-card revised">
          <span>Suggested</span>
          <pre>${esc(String(diff.proposed || ""))}</pre>
        </div>
      </div>
      ${diff.diff_blocks.map((block) => {
        const type = String(block?.type || "equal");
        const label = type === "add"
          ? "\u65b0\u589e"
          : type === "delete"
            ? "\u5220\u9664"
            : "\u4fdd\u7559";
        return `
          <div class="report-editor-diff-block ${esc(type)}">
            <strong>${esc(label)}</strong>
            <pre>${esc(Array.isArray(block?.lines) ? block.lines.join("\n") : "")}</pre>
          </div>
        `;
      }).join("")}
    `;
    panel.querySelector("#reportEditorUndoBtn")?.addEventListener("click", () => {
      clearCareerReportEditorDiff();
    });
    panel.querySelector("#reportEditorKeepAllBtn")?.addEventListener("click", () => {
      applyCareerReportEditorDiff();
    });
  }

  function updateCareerReportEditorSelectionInfo() {
    const textarea = document.getElementById("reportEditorTextarea");
    const info = document.getElementById("reportEditorSelectionInfo");
    if (!textarea || !info) return;
    const start = Number(textarea.selectionStart || 0);
    const end = Number(textarea.selectionEnd || 0);
    const length = Math.max(0, end - start);
    reportRuntime.editorSelection = length > 0
      ? { start, end, text: textarea.value.slice(start, end) }
      : null;
    info.textContent = length > 0
      ? `\u5df2\u9009\u4e2d ${length} \u4e2a\u5b57\u7b26\uff0c\u53ef\u4ee5\u53ea\u9488\u5bf9\u5f53\u524d\u7247\u6bb5\u53d1\u8d77 AI \u6da6\u8272\u3002`
      : "\u672a\u9009\u4e2d\u6587\u672c\uff0c\u53d1\u8d77\u6da6\u8272\u65f6\u4f1a\u9ed8\u8ba4\u9488\u5bf9\u6574\u7bc7\u62a5\u544a\u3002";
    renderReportEditorChatLog();
  }

  function clearCareerReportEditorDiff(options = {}) {
    const hadDiff = Boolean(reportRuntime.editorDiff);
    reportRuntime.editorDiff = null;
    renderReportEditorDiffPanel();
    if (!options.silent && hadDiff) {
      appendReportEditorMessage("assistant", "Undo", "\u5df2\u64a4\u9500\u5f53\u524d\u6da6\u8272\u63d0\u6848\uff0c\u6b63\u6587\u672a\u53d1\u751f\u53d8\u5316\u3002");
    }
    renderReportEditorChatLog();
  }

  function applyCareerReportEditorDiff() {
    const textarea = document.getElementById("reportEditorTextarea");
    const diff = reportRuntime.editorDiff;
    if (!textarea || !diff) return;
    if (diff.selection && Number.isFinite(diff.selection.start) && Number.isFinite(diff.selection.end)) {
      textarea.value = `${textarea.value.slice(0, diff.selection.start)}${diff.proposed}${textarea.value.slice(diff.selection.end)}`;
      const cursor = diff.selection.start + String(diff.proposed || "").length;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
    } else {
      textarea.value = String(diff.proposed || "");
      textarea.focus();
      textarea.setSelectionRange(0, 0);
    }
    clearCareerReportEditorDiff({ silent: true });
    appendReportEditorMessage("assistant", "Applied", "\u5df2\u5c06\u5f53\u524d AI \u5efa\u8bae\u5199\u56de\u7f16\u8f91\u533a\uff0c\u4f60\u53ef\u4ee5\u7ee7\u7eed\u4fee\u6539\u6216\u76f4\u63a5\u5bfc\u51fa DOCX\u3002");
    updateCareerReportEditorSelectionInfo();
    renderReportEditorChatLog();
  }

  async function loadCareerReportEditorSource(options = {}) {
    const reportId = String(options.reportId || window.appState?.careerReport?.meta?.report_id || "").trim();
    const snapshotId = String(options.snapshotId || "").trim();
    if (!reportId && !window.appState?.careerReport?.report_document) {
      throw new Error("\u5f53\u524d\u6ca1\u6709\u53ef\u7f16\u8f91\u7684\u804c\u4e1a\u62a5\u544a\u3002");
    }
    const url = new URL(resolveUrl("/api/career-report/source"), window.location.origin);
    if (reportId) url.searchParams.set("report_id", reportId);
    if (snapshotId) url.searchParams.set("snapshot_id", snapshotId);
    const payload = await requestJsonSafe(`${url.pathname}${url.search}`);
    reportRuntime.editorSource = payload;
    reportRuntime.editorDiff = null;
    reportRuntime.editorConversation = [];
    reportRuntime.editorSelection = null;
    if (payload?.bundle && payload.bundle.meta) {
      window.appState.careerReport = payload.bundle;
      window.appState.reportReady = Boolean(payload.bundle.report_document);
      window.appState.reportGenerated = Boolean(payload.bundle.report_document);
    }
    const titleEl = document.getElementById("reportEditorTitle");
    const metaEl = document.getElementById("reportEditorMeta");
    const textarea = document.getElementById("reportEditorTextarea");
    const promptInput = document.getElementById("reportEditorPromptInput");
    if (titleEl) titleEl.textContent = payload?.title || "\u804c\u4e1a\u62a5\u544a";
    if (metaEl) {
      metaEl.textContent = payload?.source_type === "formal_report"
        ? `\u6b63\u5f0f\u62a5\u544a | report_id ${payload?.report_id || "--"}`
        : `\u7f16\u8f91\u5feb\u7167 | snapshot_id ${payload?.snapshot_id || "--"}`;
    }
    if (textarea) textarea.value = String(payload?.markdown || "");
    if (promptInput) promptInput.value = "";
    renderReportEditorSnapshotList(payload);
    renderReportEditorSectionMap(payload);
    renderReportEditorCheckPanel(payload?.completeness_check || null);
    renderReportEditorDiffPanel();
    updateCareerReportEditorSelectionInfo();
    renderReportEditorChatLog();
    return payload;
  }

  async function openCareerReportEditor(options = {}) {
    const overlay = document.getElementById("reportEditorOverlay");
    if (!overlay) return;
    if (!window.appState?.careerReport?.report_document) {
      toast("\u6682\u65e0\u5b8c\u6574\u62a5\u544a", "\u8bf7\u5148\u751f\u6210\u804c\u4e1a\u62a5\u544a\uff0c\u518d\u8fdb\u5165\u5b8c\u6574\u62a5\u544a\u7684\u6da6\u8272\u4e0e\u7f16\u8f91\u89c6\u56fe\u3002", "warning", 2200);
      return;
    }
    await loadCareerReportEditorSource(options);
    reportRuntime.previousBodyOverflow = document.body.style.overflow || "";
    document.body.style.overflow = "hidden";
    overlay.classList.remove("hidden");
  }

  function closeCareerReportEditor() {
    const overlay = document.getElementById("reportEditorOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
    document.body.style.overflow = reportRuntime.previousBodyOverflow;
  }

  async function checkCareerReportEditorCompleteness() {
    const source = reportRuntime.editorSource || {};
    const textarea = document.getElementById("reportEditorTextarea");
    const payload = await requestJsonSafe("/api/career-report/snapshot/check", {
      method: "POST",
      body: {
        report_id: source.report_id || window.appState?.careerReport?.meta?.report_id || "",
        snapshot_id: source.snapshot_id || "",
        markdown: textarea?.value || ""
      }
    });
    if (source && typeof source === "object") {
      source.completeness_check = payload?.completeness_check || null;
    }
    renderReportEditorCheckPanel(payload?.completeness_check || null);
    appendReportEditorMessage("assistant", "Check", "\u5b8c\u6574\u6027\u68c0\u67e5\u5df2\u66f4\u65b0\uff0c\u53ef\u4ee5\u6839\u636e\u4e0b\u65b9\u95ee\u9898\u9879\u7ee7\u7eed\u8865\u5145\u6216\u4fee\u6539\u3002");
    renderReportEditorChatLog();
    toast("\u68c0\u67e5\u5b8c\u6210", "\u5df2\u66f4\u65b0\u5f53\u524d\u6587\u7a3f\u7684\u5b8c\u6574\u6027\u4e0e\u53ef\u89e3\u91ca\u6027\u68c0\u67e5\u7ed3\u679c\u3002", "success", 1800);
  }

  async function polishCareerReportEditorSelection() {
    const source = reportRuntime.editorSource || {};
    const textarea = document.getElementById("reportEditorTextarea");
    const promptInput = document.getElementById("reportEditorPromptInput");
    if (!textarea) return;
    const selection = reportRuntime.editorSelection;
    const targetText = selection?.text || textarea.value || "";
    const instruction = String(promptInput?.value || "").trim();
    if (!String(targetText).trim()) {
      toast("\u6682\u65e0\u53ef\u6da6\u8272\u5185\u5bb9", "\u8bf7\u5148\u9009\u62e9\u4e00\u6bb5\u6b63\u6587\uff0c\u6216\u786e\u4fdd\u7f16\u8f91\u533a\u91cc\u5df2\u6709\u62a5\u544a\u5185\u5bb9\u3002", "warning", 1800);
      return;
    }
    const selectionLabel = selection
      ? `\u9009\u4e2d\u7247\u6bb5\uff1a${clipReportEditorText(selection.text, 96)}`
      : "\u5f53\u524d\u6309\u6574\u7bc7\u62a5\u544a\u8fdb\u884c\u6da6\u8272";
    appendReportEditorMessage(
      "user",
      "Prompt",
      instruction
        ? `${instruction}\n${selectionLabel}`
        : `\u8bf7\u5e2e\u6211\u91cd\u5199\u8fd9\u90e8\u5206\uff0c\u4f46\u4e0d\u8981\u65b0\u589e\u4e8b\u5b9e\u3002\n${selectionLabel}`,
      "user"
    );
    renderReportEditorChatLog();
    const payload = await requestJsonSafe("/api/career-report/polish", {
      method: "POST",
      body: {
        section_key: source.section_map?.[0]?.key || "",
        selection: selection?.text || "",
        text: selection ? "" : textarea.value,
        instruction
      }
    });
    reportRuntime.editorDiff = {
      original: payload?.original || targetText,
      proposed: payload?.proposed || payload?.polished || "",
      diff_blocks: Array.isArray(payload?.diff_blocks) ? payload.diff_blocks : [],
      selection: selection ? { start: selection.start, end: selection.end } : null
    };
    appendReportEditorMessage(
      "assistant",
      "AI Draft",
      selection
        ? "\u5df2\u751f\u6210\u5f53\u524d\u9009\u4e2d\u7247\u6bb5\u7684\u6da6\u8272\u5efa\u8bae\uff0c\u8bf7\u5148\u5bf9\u7167\u53f3\u4fa7 diff\uff0c\u518d\u9009\u62e9 Keep All \u6216 Undo\u3002"
        : "\u5df2\u751f\u6210\u6574\u7bc7\u62a5\u544a\u7684\u6da6\u8272\u5efa\u8bae\uff0c\u8bf7\u5148\u5bf9\u7167 diff \u518d\u51b3\u5b9a\u662f\u5426\u5199\u56de\u6b63\u6587\u3002"
    );
    renderReportEditorDiffPanel();
    renderReportEditorChatLog();
    toast("\u6da6\u8272\u63d0\u6848\u5df2\u751f\u6210", "\u8bf7\u5148\u68c0\u67e5 diff\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u4f7f\u7528 Keep All \u5199\u56de\u6b63\u6587\u3002", "success", 1800);
  }

  async function saveCareerReportEditorSnapshot() {
    const source = reportRuntime.editorSource || {};
    const textarea = document.getElementById("reportEditorTextarea");
    const markdown = String(textarea?.value || "").trim();
    if (!markdown) {
      toast("\u65e0\u6cd5\u4fdd\u5b58", "\u5f53\u524d\u7f16\u8f91\u533a\u4e3a\u7a7a\u3002", "warning", 1800);
      return;
    }
    const label = source?.snapshot_id
      ? String(source?.title || "\u7f16\u8f91\u5feb\u7167").trim()
      : `\u7f16\u8f91\u5feb\u7167 ${new Date().toLocaleString("zh-CN")}`;
    const payload = await requestJsonSafe("/api/career-report/snapshot/save", {
      method: "POST",
      body: {
        report_id: source.report_id || window.appState?.careerReport?.meta?.report_id || "",
        snapshot_id: source.snapshot_id || "",
        source: source.source_type === "formal_report" ? "manual" : (source.source_type || "manual"),
        title: label,
        markdown,
        diff_blocks: reportRuntime.editorDiff?.diff_blocks || []
      }
    });
    reportRuntime.editorSource = {
      ...(reportRuntime.editorSource || {}),
      ...(payload?.snapshot || {}),
      report_id: source.report_id || window.appState?.careerReport?.meta?.report_id || "",
      source_type: payload?.snapshot?.snapshot_id ? "snapshot" : (payload?.snapshot?.source || "manual")
    };
    if (window.appState?.careerReport) {
      window.appState.careerReport.draft_snapshots = Array.isArray(payload?.draft_snapshots) ? payload.draft_snapshots : [];
    }
    clearCareerReportEditorDiff({ silent: true });
    appendReportEditorMessage("assistant", "Snapshot", `\u5df2\u5c06\u5f53\u524d\u7f16\u8f91\u5185\u5bb9\u4fdd\u5b58\u4e3a\u5feb\u7167\uff1a${label}`);
    renderReportEditorSnapshotList(reportRuntime.editorSource);
    renderReportEditorSectionMap(reportRuntime.editorSource);
    renderReportEditorChatLog();
    window.renderUserCenterDashboard?.();
    toast("\u5feb\u7167\u5df2\u4fdd\u5b58", `\u5df2\u6309\u300c${label}\u300d\u4fdd\u5b58\u5f53\u524d\u7f16\u8f91\u5185\u5bb9\u3002`, "success", 1800);
  }

  function exportCareerReportSource(format = "docx") {
    const source = reportRuntime.editorSource || {};
    if (source?.source_type !== "formal_report" && !source?.snapshot_id) {
      toast("\u8bf7\u5148\u4fdd\u5b58\u5feb\u7167", "\u672a\u4fdd\u5b58\u7684\u7f16\u8f91\u5185\u5bb9\u4e0d\u80fd\u76f4\u63a5\u5bfc\u51fa\uff0c\u8bf7\u5148\u4fdd\u5b58\u4e3a\u7f16\u8f91\u5feb\u7167\u3002", "warning", 2200);
      return;
    }
    const url = new URL(resolveUrl("/api/career-report/export"), window.location.origin);
    url.searchParams.set("format", String(format || "docx").trim().toLowerCase());
    url.searchParams.set("report_id", source.report_id || window.appState?.careerReport?.meta?.report_id || "");
    if (source?.snapshot_id) {
      url.searchParams.set("snapshot_id", source.snapshot_id);
    }
    const anchor = document.createElement("a");
    anchor.href = url.toString();
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    toast("\u5f00\u59cb\u5bfc\u51fa", `\u6b63\u5728\u5bfc\u51fa ${String(format || "docx").toUpperCase()} \u6587\u6863\u3002`, "success", 1800);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  }

  function bindCareerReportEditorEvents() {
    if (reportRuntime.editorEventsBound) return;
    reportRuntime.editorEventsBound = true;
    const textarea = document.getElementById("reportEditorTextarea");
    const promptInput = document.getElementById("reportEditorPromptInput");
    const runPolish = () => {
      void polishCareerReportEditorSelection().catch((error) => {
        toast("\u6da6\u8272\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
      });
    };
    textarea?.addEventListener("select", updateCareerReportEditorSelectionInfo);
    textarea?.addEventListener("keyup", updateCareerReportEditorSelectionInfo);
    textarea?.addEventListener("mouseup", updateCareerReportEditorSelectionInfo);
    document.getElementById("reportEditorCheckBtn")?.addEventListener("click", () => {
      void checkCareerReportEditorCompleteness().catch((error) => {
        toast("\u68c0\u67e5\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
      });
    });
    document.getElementById("reportEditorPolishBtn")?.addEventListener("click", runPolish);
    document.getElementById("reportEditorPromptSendBtn")?.addEventListener("click", runPolish);
    document.getElementById("reportEditorClearPromptBtn")?.addEventListener("click", () => {
      if (promptInput) {
        promptInput.value = "";
        promptInput.focus();
      }
      appendReportEditorMessage("system", "Prompt", "\u5df2\u6e05\u7a7a\u5f53\u524d\u6da6\u8272\u6307\u4ee4\u3002", "system");
      renderReportEditorChatLog();
    });
    promptInput?.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runPolish();
      }
    });
    document.getElementById("reportEditorSaveBtn")?.addEventListener("click", () => {
      void saveCareerReportEditorSnapshot().catch((error) => {
        toast("\u4fdd\u5b58\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
      });
    });
    document.getElementById("reportEditorExportDocxBtn")?.addEventListener("click", () => {
      exportCareerReportSource("docx");
    });
    document.getElementById("reportEditorOverlay")?.addEventListener("click", (event) => {
      if (event.target?.id === "reportEditorOverlay") {
        closeCareerReportEditor();
      }
    });
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
    const normalized = String(format || "html").trim().toLowerCase();
    const exportFormat = normalized === "md" ? "md" : normalized === "docx" ? "docx" : "html";
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
        closeCareerReportEditor();
      });
      logoutBtn.dataset.restorationBound = "1";
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeReportViewer();
        closeCareerReportEditor();
      }
    });
  }

  function getReportUiText(value, fallback = "") {
    const text = value == null ? "" : String(value).trim();
    return text || fallback;
  }

  function normalizeReportDocItems(items) {
    return (Array.isArray(items) ? items : [])
      .map((item) => {
        const normalized = normalizeExplainItem(item);
        if (normalized) return normalized;
        if (typeof item === "string" && item.trim()) {
          return { title: item.trim(), detail: "", validate: "" };
        }
        if (item && typeof item === "object") {
          const title = getReportUiText(item.title || item.label || item.name || item.requirement || item.summary);
          if (!title) return null;
          return {
            title,
            detail: getReportUiText(item.detail || item.reason || item.note || item.summary || item.why_important),
            validate: getReportUiText(item.validate || item.validation_action || item.how_to_validate)
          };
        }
        return null;
      })
      .filter(Boolean);
  }

  function renderReportUiSectionHead(index, kicker, title, copy) {
    return `
      <div class="crdoc-section-head">
        <span class="crdoc-section-index">${esc(index)}</span>
        <div class="crdoc-section-title-group">
          <div class="crdoc-section-title-row">
            <span class="crdoc-section-accent" aria-hidden="true"></span>
            <div>
              <p class="crdoc-section-kicker">${esc(kicker)}</p>
              <h3>${esc(title)}</h3>
            </div>
          </div>
          ${copy ? `<p>${esc(copy)}</p>` : ""}
        </div>
      </div>
    `;
  }

  function getReportIssueTone(item, fallback = "muted") {
    const severity = getReportUiText(item?.severity || item?.priority || item?.type).toLowerCase();
    if (severity.includes("high") || severity.includes("critical") || severity.includes("urgent")) return "danger";
    if (severity.includes("medium") || severity.includes("warn") || severity.includes("partial")) return "warn";
    return fallback;
  }

  function renderReportIssueList(items, emptyText) {
    const normalized = normalizeReportDocItems(items).slice(0, 5);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">${esc(emptyText)}</p>`;
    }
    return `
      <ul class="crdoc-issue-list">
        ${normalized.map((item) => `
          <li class="crdoc-issue-item ${getReportIssueTone(item)}">
            <span class="crdoc-issue-dot" aria-hidden="true"></span>
            <div>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            </div>
          </li>
        `).join("")}
      </ul>
    `;
  }

  function renderReportChipCloud(items, variant = "") {
    const normalized = normalizeReportDocItems(items).slice(0, 10);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">\u6682\u65e0\u53ef\u5c55\u793a\u9879</p>`;
    }
    return `
      <div class="crdoc-chip-cloud">
        ${normalized.map((item) => `
          <span class="crdoc-cloud-chip${variant ? ` ${variant}` : ""}">
            <i aria-hidden="true"></i>
            ${esc(item.title)}
          </span>
        `).join("")}
      </div>
    `;
  }

  function renderReportTaskList(items, emptyText) {
    const normalized = normalizeReportDocItems(items).slice(0, 5);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">${esc(emptyText)}</p>`;
    }
    return `
      <div class="crdoc-task-list">
        ${normalized.map((item) => `
          <div class="crdoc-task-item">
            <span class="crdoc-task-check" aria-hidden="true"></span>
            <div>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderReportMetricCard(label, value, meta, tone = "") {
    return `
      <article class="crdoc-header-info-card${tone ? ` ${tone}` : ""}">
        <span>${esc(label)}</span>
        <strong>${esc(value)}</strong>
        ${meta ? `<small>${esc(meta)}</small>` : ""}
      </article>
    `;
  }

  function renderReportTrendTimeline(activeStep) {
    const labels = ["\u73b0\u5728", "\u91cd\u70b9\u9700\u8981", "\u8fd11-3\u5e74", "\u8fd11-5\u5e74"];
    return `
      <div class="crdoc-trend-timeline">
        ${labels.map((label, index) => `
          <span class="crdoc-trend-step${index <= activeStep ? " active" : ""}">
            <i aria-hidden="true"></i>
            <em>${esc(label)}</em>
          </span>
        `).join("")}
      </div>
    `;
  }

  function getReportRoleScoreTone(score) {
    if (score >= 60) return "high";
    if (score >= 44) return "medium";
    return "low";
  }

  function renderReportFullHeaderMeta(bundle, tracker) {
    const meta = bundle?.meta || {};
    const matchOutput = bundle?.match_output || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_name || "\u5f85\u8bc6\u522b";
    const fitScore = Math.max(0, Math.min(100, Number(matchOutput.fit_score || 0)));
    const fitBandLabel = {
      strong: "\u9ad8\u5339\u914d",
      moderate: "\u4e2d\u7b49\u5339\u914d",
      weak: "\u4f4e\u5339\u914d",
      not_ready: "\u5c1a\u9700\u51c6\u5907"
    }[String(matchOutput.fit_band || "")] || "\u5f85\u8bc4\u4f30";
    return `
      <div class="crdoc-header-meta-grid">
        ${renderReportMetricCard("\u76ee\u6807\u5c97\u4f4d", focusRole, "\u5f53\u524d\u62a5\u544a\u4e3b\u7ebf")}
        ${renderReportMetricCard("\u5339\u914d\u5ea6", `${fitScore}%`, fitBandLabel, fitScore < 44 ? "danger" : fitScore < 60 ? "warn" : "success")}
        ${renderReportMetricCard("\u751f\u6210\u65f6\u95f4", meta.generated_at || "--", `v${meta.version || "--"}`)}
      </div>
    `;
  }

  function buildReportDashboardUiData(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const next30Days = nextActions.next_30_days || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const industryStory = reportDocument.industry_story || {};
    const roleCards = Array.isArray(reportDocument.role_cards) ? reportDocument.role_cards : [];
    const planBoard = reportDocument.plan_board || {};
    const explainabilitySummary = reportDocument.explainability_summary || {};
    const competencyProfile = bundle?.competency_profile || {};
    const matchOutput = bundle?.match_output || {};
    const pathPlan = bundle?.path_plan || {};
    const explainabilityOverview = reportDocument.explainability_overview || {};
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "\u5f85\u8bc6\u522b";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? matchOutput.fit_score ?? 0)));
    const fitBandLabel = getReportUiText(dashboardSummary.fit_band_label) || ({
      strong: "\u9ad8\u5339\u914d",
      moderate: "\u4e2d\u7b49\u5339\u914d",
      weak: "\u4f4e\u5339\u914d",
      not_ready: "\u5c1a\u9700\u51c6\u5907"
    }[String(matchOutput.fit_band || "")] || "\u5f85\u8bc4\u4f30");
    const dimensions = normalizeReportDimensions(competencyProfile.dimensions);
    const headline = getReportUiText(
      dashboardSummary.headline || meta.summary || reportDocument.executive_summary,
      `\u73b0\u9636\u6bb5\u5efa\u8bae\u56f4\u7ed5 ${focusRole} \u96c6\u4e2d\u8865\u8db3\u5173\u952e\u8bc1\u636e\u548c\u7f3a\u53e3\u3002`
    );
    const rationale = getReportUiText(
      dashboardSummary.rationale || reportDocument.executive_summary || meta.summary,
      `\u5148\u89e3\u51b3 ${focusRole} \u5bf9\u5e94\u7684\u786c\u95e8\u69db\u548c\u8bc1\u636e\u7f3a\u53e3\uff0c\u518d\u63a8\u8fdb\u6295\u9012\u548c\u8def\u5f84\u9009\u62e9\u3002`
    );
    const headlineBecause = Array.isArray(dashboardSummary.headline_because)
      ? dashboardSummary.headline_because
      : (Array.isArray(explainabilitySummary.headline_because) ? explainabilitySummary.headline_because : []);
    const strengths = collectUniqueExplainItems(evidenceHealth.strengths, competencyProfile.strengths);
    const gaps = collectUniqueExplainItems(
      evidenceHealth.hard_failures,
      evidenceHealth.skill_gaps,
      evidenceHealth.evidence_gaps,
      evidenceHealth.missing_inputs,
      matchOutput.partial_gaps
    );
    const roles = (roleCards.length
      ? roleCards.map((item) => ({
          name: item?.role_name || "",
          overall_score: item?.fit_score || 0,
          fit_summary: item?.fit_summary || "",
          required_skills: Array.isArray(item?.required_skills) ? item.required_skills : [],
          because: Array.isArray(item?.why_fit) ? item.why_fit : [],
          hard_gaps: Array.isArray(item?.hard_gaps) ? item.hard_gaps : [],
          partial_gaps: Array.isArray(item?.partial_gaps) ? item.partial_gaps : []
        }))
      : (Array.isArray(bundle?.role_rankings) ? [...bundle.role_rankings] : []))
      .sort((left, right) => Number(right?.overall_score || 0) - Number(left?.overall_score || 0))
      .slice(0, 3);
    const signals = (Array.isArray(marketSignals.signal_cards) && marketSignals.signal_cards.length
      ? marketSignals.signal_cards
      : Array.isArray(industryStory.highlight_items) && industryStory.highlight_items.length
        ? industryStory.highlight_items.map((item) => ({
            title: item?.title || "",
            summary: item?.summary || "",
            source_type: item?.source || "",
            time_horizon: item?.published_label || "",
            validation_action: item?.topic || ""
          }))
        : collectUniqueExplainItems(marketSignals.hot_directions)).slice(0, 3);
    const milestones = Array.isArray(pathPlan.milestones) ? pathPlan.milestones : [];
    const actionItems = Array.isArray(planBoard.action_items) && planBoard.action_items.length
      ? planBoard.action_items.slice(0, 6)
      : (Array.isArray(nextActions.action_items) ? nextActions.action_items.slice(0, 6) : []);
    const planHorizons = Array.isArray(planBoard.horizons) ? planBoard.horizons : [];
    const shortPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "short_term")?.items)
      ? planHorizons.find((item) => item?.key === "short_term").items
      : (Array.isArray(nextActions.this_week) ? nextActions.this_week.map((item) => ({ title: item })) : []);
    const mediumPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "mid_term")?.items)
      ? planHorizons.find((item) => item?.key === "mid_term").items
      : (Array.isArray(next30Days.tasks) ? next30Days.tasks.map((item) => ({ title: item })) : []);
    const longPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "long_term")?.items)
      ? planHorizons.find((item) => item?.key === "long_term").items
      : (Array.isArray(nextActions.checkpoints) ? nextActions.checkpoints : []);
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    return {
      bundle,
      tracker,
      meta,
      reportDocument,
      nextActions,
      evidenceHealth,
      marketSignals,
      industryStory,
      competencyProfile,
      matchOutput,
      pathPlan,
      explainabilityOverview,
      focusRole,
      fitScore,
      fitBandLabel,
      dimensions,
      headline,
      rationale,
      headlineBecause,
      strengths,
      gaps,
      roles,
      signals,
      milestones,
      actionItems,
      shortPlanActions,
      mediumPlanActions,
      longPlanActions,
      decisionCards
    };
  }

  function renderReportDashboardHero(data) {
    return `
      <section class="crdoc-hero crdoc-reveal is-visible">
        <div class="crdoc-header-main">
          <div class="crdoc-header-copy">
            <span class="crdoc-header-bar" aria-hidden="true"></span>
            <div>
              <p class="crdoc-kicker">Career Report</p>
              <h2>${esc(data.meta.title || "\u804c\u4e1a\u751f\u6daf\u53d1\u5c55\u62a5\u544a")}</h2>
              <p class="crdoc-hero-summary">${esc(data.headline)}</p>
              <p class="crdoc-hero-body">${esc(data.rationale)}</p>
              ${data.headlineBecause.length ? `
                <div class="crdoc-header-evidence">
                  <span>\u4e3a\u4ec0\u4e48\u662f\u8fd9\u4e2a\u7ed3\u8bba</span>
                  ${renderReportChipCloud(data.headlineBecause.map((item) => ({ title: item })), "muted")}
                </div>
              ` : ""}
            </div>
          </div>
          ${renderReportFullHeaderMeta(data.bundle, data.tracker)}
        </div>
      </section>
    `;
  }

  function renderReportDashboardPositionSection(data) {
    const issueItems = normalizeReportDocItems(data.gaps).slice(0, 4);
    const evidenceTrace = normalizeReportDocItems(data.evidenceHealth.evidence_trace).slice(0, 3);
    const dimensionCards = data.dimensions.length
      ? data.dimensions.map((entry, index) => {
          const pending = String(entry.level || "").toLowerCase() === "unknown";
          const failed = !pending && Number(entry.score || 0) < 58;
          const statusText = pending ? "\u5f85\u9a8c\u8bc1" : failed ? "\u672a\u901a\u8fc7" : "\u5df2\u9a8c\u8bc1";
          const statusClass = pending ? "pending" : failed ? "failed" : "verified";
          return `
            <article class="crdoc-cap-card ${statusClass} crdoc-reveal" style="transition-delay:${Math.min(index, 5) * 60}ms">
              <div class="crdoc-cap-head">
                <strong>${esc(entry.label)}</strong>
                <span class="crdoc-status-pill ${statusClass}">${pending ? `<i aria-hidden="true">&#128274;</i>` : ""}${esc(statusText)}</span>
              </div>
              <div class="crdoc-progress ${pending ? "is-pending" : ""}">
                <i style="width:${Math.max(12, pending ? 32 : entry.score)}%"></i>
              </div>
              <p>${esc(getReportUiText(entry.reason, pending ? "\u9700\u8981\u589e\u52a0\u66f4\u660e\u786e\u7684\u8bc1\u636e\u6216\u9879\u76ee\u8f93\u51fa\u518d\u5b8c\u6210\u5224\u65ad\u3002" : failed ? "\u8fd9\u4e2a\u7ef4\u5ea6\u8fd8\u4e0d\u8db3\u4ee5\u652f\u6491\u5f53\u524d\u76ee\u6807\u5c97\u4f4d\u3002" : "\u5f53\u524d\u5df2\u6709\u4e00\u5b9a\u8bc1\u636e\u652f\u6491\uff0c\u53ef\u4ee5\u7ee7\u7eed\u52a0\u6df1\u3002"))}</p>
            </article>
          `;
        }).join("")
      : `<p class="crdoc-empty-state">\u6682\u65e0\u80fd\u529b\u7ef4\u5ea6\u6570\u636e</p>`;

    return `
      <section id="reportDocSection-position" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("01", "Current Position", "\u5f53\u524d\u72b6\u6001", "\u5148\u770b\u6700\u963b\u585e\u4f60\u7684\u95ee\u9898\uff0c\u518d\u5bf9\u5e94\u5230\u80fd\u529b\u7ef4\u5ea6\u548c\u8bc1\u636e\u72b6\u6001\u3002")}
        <div class="crdoc-position-grid">
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u95ee\u9898\u6e05\u5355</span>
              <span class="crdoc-card-meta">${esc(data.focusRole)}</span>
            </div>
            <h4>\u5f53\u524d\u5b9a\u4f4d\u5224\u65ad</h4>
            <p>${esc(data.rationale)}</p>
            ${renderReportIssueList(issueItems, "\u5f53\u524d\u672a\u68c0\u51fa\u9ad8\u98ce\u9669\u7f3a\u53e3")}
            <div class="crdoc-inline-stack">
              <span class="crdoc-inline-title">\u53ef\u8ffd\u6eaf\u8bc1\u636e</span>
              ${evidenceTrace.length ? evidenceTrace.map((item) => `
                <div class="crdoc-inline-evidence">
                  <strong>${esc(item.title)}</strong>
                  ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
                </div>
              `).join("") : `<p class="crdoc-empty-state">\u6682\u65e0\u53ef\u8ffd\u6eaf\u8bc1\u636e</p>`}
            </div>
          </article>
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u80fd\u529b\u8bc4\u4f30</span>
              <span class="crdoc-card-meta">\u72b6\u6001 + \u8fdb\u5ea6\u6761</span>
            </div>
            <div class="crdoc-cap-grid">${dimensionCards}</div>
          </article>
        </div>
      </section>
    `;
  }

  function renderReportDashboardTrendSection(data) {
    const skillPriorities = normalizeReportDocItems(data.marketSignals.skill_priorities);
    const verificationActions = normalizeReportDocItems(data.marketSignals.verification_actions);
    const riskSignals = normalizeReportDocItems(data.marketSignals.risk_signals);
    return `
      <section id="reportDocSection-trends" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("02", "Industry Trends", "\u884c\u4e1a\u8d8b\u52bf", "\u628a\u5f53\u524d\u53d8\u5316\u3001\u91cd\u70b9\u80fd\u529b\u548c\u9a8c\u8bc1\u65b9\u5f0f\u653e\u5728\u540c\u4e00\u5c42\u7ea7\u91cc\u3002")}
        <div class="crdoc-trend-grid">
          ${data.signals.length ? data.signals.map((item, index) => {
            const normalized = normalizeExplainItem(item) || { title: getReportUiText(item?.title || item?.summary || item), detail: "", validate: "" };
            const raw = item && typeof item === "object" ? item : {};
            return `
              <article class="crdoc-trend-card crdoc-reveal" style="transition-delay:${index * 70}ms">
                ${renderReportTrendTimeline(Math.min(3, index + 1))}
                <div class="crdoc-card-topline">
                  <span class="crdoc-card-label">${esc(index === 0 ? "\u73b0\u5728" : index === 1 ? "\u91cd\u70b9\u9700\u8981" : "\u4e2d\u957f\u671f")}</span>
                  <span class="crdoc-card-meta">${esc(getReportUiText(raw.time_horizon, "\u8d8b\u52bf\u89c2\u5bdf"))}</span>
                </div>
                <h4>${esc(normalized.title)}</h4>
                <p>${esc(getReportUiText(raw.summary || raw.why_important || normalized.detail, "\u6682\u65e0\u8fd9\u4e2a\u8d8b\u52bf\u7684\u8be6\u7ec6\u8bf4\u660e"))}</p>
                <div class="crdoc-fact-row">
                  <span>\u6765\u6e90</span>
                  <strong>${esc(getReportUiText(raw.source_type, "\u7efc\u5408\u5224\u65ad"))}</strong>
                </div>
                <details class="crdoc-accordion">
                  <summary>\u5982\u4f55\u9a8c\u8bc1</summary>
                  <p>${esc(getReportUiText(normalized.validate || raw.validation_action, "\u53ef\u4ee5\u901a\u8fc7\u9879\u76ee\u4ea7\u51fa\u3001\u5c97\u4f4d\u9700\u6c42\u6216\u8bd5\u6295\u53cd\u9988\u6765\u9a8c\u8bc1\u3002"))}</p>
                </details>
              </article>
            `;
          }).join("") : `<article class="crdoc-card"><p class="crdoc-empty-state">\u6682\u65e0\u884c\u4e1a\u8d8b\u52bf\u6570\u636e</p></article>`}
        </div>
        <article class="crdoc-card">
          <div class="crdoc-card-topline">
            <span class="crdoc-card-label">\u80fd\u529b\u5efa\u8bae</span>
            <span class="crdoc-card-meta">\u6807\u7b7e\u4e91</span>
          </div>
          ${renderReportChipCloud([...skillPriorities, ...verificationActions], "accent")}
          ${riskSignals.length ? `<div class="crdoc-inline-note crdoc-risk-note">${renderReportChipCloud(riskSignals, "warn")}</div>` : ""}
        </article>
      </section>
    `;
  }

  function renderReportDashboardTargetsSection(data) {
    return `
      <section id="reportDocSection-targets" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("03", "Target Roles", "\u76ee\u6807\u5c97\u4f4d\u5bf9\u6bd4", "\u4e0d\u53ea\u770b\u603b\u5206\uff0c\u8fd8\u8981\u770b\u4f60\u5df2\u7ecf\u62ff\u5728\u624b\u91cc\u7684\u80fd\u529b\u548c\u8fd8\u6ca1\u8865\u4e0a\u7684\u7f3a\u53e3\u3002")}
        <div class="crdoc-role-grid">
          ${data.roles.length ? data.roles.map((role, index) => {
            const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
            const tone = getReportRoleScoreTone(score);
            const requiredSkills = Array.isArray(role?.required_skills) ? role.required_skills.slice(0, 8) : [];
            const hardGapText = normalizeReportDocItems(role?.hard_gaps).map((item) => item.title.toLowerCase());
            const partialGapText = normalizeReportDocItems(role?.partial_gaps).map((item) => item.title.toLowerCase());
            return `
              <article class="crdoc-target-card ${tone} crdoc-reveal" style="transition-delay:${index * 70}ms">
                <div class="crdoc-target-head">
                  <div>
                    <h4>${esc(role?.name || role?.title || "\u5019\u9009\u5c97\u4f4d")}</h4>
                    <span>${esc(index === 0 ? "\u4f18\u5148\u65b9\u5411" : `\u5019\u9009\u65b9\u5411 ${index + 1}`)}</span>
                  </div>
                  <div class="crdoc-target-score ${tone}">
                    <strong>${score}</strong>
                    <small>\u5206</small>
                  </div>
                </div>
                <p class="crdoc-target-summary">${esc(getReportUiText(role?.fit_summary, "\u8fd9\u4e2a\u5c97\u4f4d\u7684\u8bf4\u660e\u8fd8\u5728\u8865\u5168\u4e2d\u3002"))}</p>
                <div class="crdoc-skill-system">
                  ${requiredSkills.length ? requiredSkills.map((skill) => {
                    const skillText = String(skill || "").toLowerCase();
                    const chipClass = hardGapText.some((item) => item.includes(skillText) || skillText.includes(item))
                      ? "missing-core"
                      : partialGapText.some((item) => item.includes(skillText) || skillText.includes(item))
                        ? "missing"
                        : "owned";
                    return `<span class="crdoc-skill-chip ${chipClass}">${esc(skill)}</span>`;
                  }).join("") : `<span class="crdoc-skill-chip missing">\u6682\u65e0\u6280\u80fd\u660e\u7ec6</span>`}
                </div>
                <div class="crdoc-target-layout">
                  <div class="crdoc-target-explain">
                    <span class="crdoc-target-mini-title">\u5339\u914d\u4f9d\u636e</span>
                    ${renderReportIssueList(index === 0 ? collectUniqueExplainItems(data.matchOutput.why_match, role?.because) : role?.because, "\u6682\u65e0\u5173\u952e\u652f\u6491\u9879")}
                  </div>
                  <aside class="crdoc-missing-rail">
                    <span class="crdoc-target-mini-title">\u7f3a\u5931\u9700\u6c42</span>
                    ${renderReportIssueList(collectUniqueExplainItems(role?.hard_gaps, role?.partial_gaps), "\u6682\u65e0\u660e\u663e\u7f3a\u53e3")}
                  </aside>
                </div>
              </article>
            `;
          }).join("") : `<article class="crdoc-card"><p class="crdoc-empty-state">\u6682\u65e0\u5c97\u4f4d\u5bf9\u6bd4\u6570\u636e</p></article>`}
        </div>
      </section>
    `;
  }

  function renderReportDashboardPathSection(data) {
    return `
      <section id="reportDocSection-path" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("04", "Career Path", "\u804c\u4e1a\u8def\u5f84", "\u628a\u5f53\u524d\u8282\u70b9\u3001\u4e0b\u4e00\u6b65\u3001\u4e2d\u671f\u548c\u8fdc\u671f\u8def\u5f84\u6536\u5728\u4e00\u6761\u7eb5\u5411\u6d41\u91cc\u3002")}
        <div class="crdoc-path-grid">
          <div class="crdoc-step-flow">
            <article class="crdoc-step-item current">
              <div class="crdoc-step-node"><span>1</span></div>
              <div class="crdoc-step-card">
                <div class="crdoc-step-card-head">
                  <span class="crdoc-time-pill">\u73b0\u5728</span>
                  <small>${esc(data.meta.generated_at || "--")}</small>
                </div>
                <h4>${esc(data.focusRole)}</h4>
                <p>${esc(data.rationale)}</p>
              </div>
            </article>
            ${data.milestones.length ? data.milestones.slice(0, 4).map((item, index) => `
              <article class="crdoc-step-item">
                <div class="crdoc-step-node"><span>${index + 2}</span></div>
                <div class="crdoc-step-card">
                  <div class="crdoc-step-card-head">
                    <span class="crdoc-time-pill">${esc(getReportUiText(item?.horizon, `0-${(index + 1) * 3}m`))}</span>
                    <small>${esc(index === 0 ? "\u4e0b\u4e00\u6b65" : index === 1 ? "\u4e2d\u671f" : "\u540e\u7eed\u9636\u6bb5")}</small>
                  </div>
                  <h4>${esc(getReportUiText(item?.title, "\u9636\u6bb5\u76ee\u6807"))}</h4>
                  <p>${esc(getReportUiText(item?.reason, "\u6682\u65e0\u8be6\u7ec6\u8bf4\u660e"))}</p>
                  ${renderReportTaskList(Array.isArray(item?.actions) ? item.actions.map((action) => ({ title: action, detail: item?.linked_gap || item?.priority_reason || "" })) : [], "\u6682\u65e0\u9636\u6bb5\u52a8\u4f5c")}
                </div>
              </article>
            `).join("") : `<p class="crdoc-empty-state">\u6682\u65e0\u804c\u4e1a\u8def\u5f84\u8282\u70b9</p>`}
          </div>
          <div class="crdoc-stack">
            <article class="crdoc-card crdoc-tip-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">\u63a8\u8350\u4fe1\u606f</span>
              </div>
              <h4>\u4e3a\u4ec0\u4e48\u662f\u8fd9\u6761\u8def</h4>
              ${renderReportIssueList(data.pathPlan.path_rationale, "\u6682\u65e0\u8def\u5f84\u89e3\u91ca")}
            </article>
            <article class="crdoc-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">\u98ce\u9669\u4e0e\u524d\u63d0</span>
              </div>
              ${renderReportIssueList(data.pathPlan.dependencies?.must_resolve_hard_failures, "\u6682\u65e0\u5fc5\u987b\u5148\u89e3\u51b3\u7684\u786c\u95e8\u69db")}
              ${renderReportIssueList(data.pathPlan.path_risks, "\u6682\u65e0\u663e\u6027\u98ce\u9669")}
              ${renderReportIssueList(data.pathPlan.contingency, "\u6682\u65e0\u5907\u9009\u8def\u7ebf")}
            </article>
          </div>
        </div>
      </section>
    `;
  }

  function renderReportDashboardPlanSection(data) {
    const stageCards = [
      {
        label: "0-2w",
        title: "\u5f53\u4e0b\u6821\u51c6",
        items: data.shortPlanActions,
        reason: Array.isArray(data.nextActions.priority_logic) ? data.nextActions.priority_logic[0] : ""
      },
      {
        label: "0-30d",
        title: "\u4e00\u4e2a\u6708\u5185",
        items: data.mediumPlanActions.slice(0, 3).length ? data.mediumPlanActions.slice(0, 3) : data.actionItems.slice(0, 3),
        reason: Array.isArray(data.nextActions.priority_logic) ? data.nextActions.priority_logic[1] : ""
      },
      {
        label: "1-3m",
        title: "\u80fd\u529b\u8865\u5f3a",
        items: data.mediumPlanActions.slice(3, 6).length ? data.mediumPlanActions.slice(3, 6) : data.actionItems.slice(3, 6),
        reason: data.milestones[1]?.reason || ""
      },
      {
        label: "3-12m",
        title: "\u8def\u5f84\u6210\u578b",
        items: data.longPlanActions,
        reason: getReportUiText(data.nextActions.plan_b || data.milestones[2]?.reason)
      }
    ];
    return `
      <section id="reportDocSection-plan" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("05", "Action Plan", "\u884c\u52a8\u8ba1\u5212", "\u62c6\u6210\u56db\u4e2a\u65f6\u95f4\u9636\u6bb5\uff0c\u8ba9\u5148\u540e\u987a\u5e8f\u548c\u4f18\u5148\u7ea7\u66f4\u6e05\u695a\u3002")}
        <div class="crdoc-stage-strip">
          ${stageCards.map((stage, index) => `
            <div class="crdoc-stage-node ${index < 2 ? "active" : ""}">
              <span>${esc(stage.label)}</span>
            </div>
          `).join("")}
        </div>
        <div class="crdoc-plan-grid crdoc-plan-grid-4">
          ${stageCards.map((stage, index) => `
            <article class="crdoc-plan-card crdoc-reveal" style="transition-delay:${index * 70}ms">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">${esc(stage.label)}</span>
                <span class="crdoc-card-meta">${esc(stage.title)}</span>
              </div>
              ${renderReportTaskList(stage.items, "\u6682\u65e0\u8fd9\u4e2a\u9636\u6bb5\u7684\u4efb\u52a1")}
              <details class="crdoc-accordion muted">
                <summary>\u4e3a\u4ec0\u4e48\u5148\u505a\u8fd9\u6b65</summary>
                <p>${esc(getReportUiText(stage.reason, "\u8fd9\u4e2a\u9636\u6bb5\u4e3b\u8981\u7528\u6765\u8865\u8db3\u6700\u5f71\u54cd\u5339\u914d\u7ed3\u679c\u7684\u5173\u952e\u7f3a\u53e3\u3002"))}</p>
              </details>
            </article>
          `).join("")}
        </div>
        <div class="crdoc-two-col">
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u884c\u52a8\u5206\u89e3</span>
            </div>
            ${renderReportTaskList(data.actionItems, "\u6682\u65e0\u53ef\u6267\u884c\u52a8\u4f5c")}
          </article>
          <article class="crdoc-alert-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u672a\u901a\u8fc7\u8bf4\u660e</span>
            </div>
            ${renderReportIssueList(data.matchOutput.hard_failures || data.evidenceHealth.hard_failures, "\u6682\u65e0\u660e\u786e\u7684\u672a\u901a\u8fc7\u6761\u76ee")}
          </article>
        </div>
      </section>
    `;
  }

  function renderReportDashboardSummarySection(data) {
    return `
      <section id="reportDocSection-summary" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("06", "Key Judgements", "\u5173\u952e\u5224\u65ad", "\u628a\u6700\u5f3a\u7f3a\u53e3\u3001\u6700\u5927\u98ce\u9669\u548c\u6700\u503c\u5f97\u4fdd\u7559\u7684\u57fa\u7840\u6536\u62e2\u6210\u4e09\u4e2a\u6807\u51c6\u89c6\u56fe\u3002")}
        <div class="crdoc-insight-grid crdoc-insight-grid-3">
          <article class="crdoc-insight-card breakthrough">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u5f3a\u7f3a\u53e3</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.decisionCards.find((card) => card?.tone === "risk")?.title || data.gaps[0]?.title, "\u76ee\u524d\u6700\u9700\u8981\u5148\u8865\u7684\uff0c\u662f\u6700\u5f71\u54cd\u5c97\u4f4d\u5224\u65ad\u7684\u5173\u952e\u7f3a\u53e3\u3002"))}</p>
            ${renderReportIssueList(data.decisionCards.find((card) => card?.tone === "risk")?.because || data.gaps, "\u6682\u65e0\u5f3a\u7f3a\u53e3\u8bf4\u660e")}
          </article>
          <article class="crdoc-insight-card risk">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u91cd\u8981\u98ce\u9669</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.explainabilityOverview.match?.judgement || data.decisionCards.find((card) => card?.tone === "neutral")?.title, "\u4e0d\u8981\u5728\u8bc1\u636e\u4e0d\u8db3\u65f6\u628a\u5339\u914d\u5ea6\u5f53\u6210\u786e\u8ba4\u7ed3\u8bba\u3002"))}</p>
            ${renderReportIssueList(data.explainabilityOverview.match?.because || data.marketSignals.risk_signals, "\u6682\u65e0\u98ce\u9669\u8bf4\u660e")}
          </article>
          <article class="crdoc-insight-card strength">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u503c\u5f97\u4fdd\u7559\u57fa\u7840</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.strengths[0]?.title || data.explainabilityOverview.positioning?.judgement, "\u76ee\u524d\u6700\u503c\u5f97\u4fdd\u7559\u7684\uff0c\u662f\u5df2\u88ab\u8bc1\u636e\u652f\u6491\u7684\u4e3b\u7ebf\u80fd\u529b\u57fa\u7840\u3002"))}</p>
            ${renderReportIssueList(data.strengths.length ? data.strengths : (data.explainabilityOverview.positioning?.because || []), "\u6682\u65e0\u57fa\u7840\u4f18\u52bf\u8bf4\u660e")}
          </article>
        </div>
        <div class="crdoc-feedback-wrap">
          ${renderReportFeedbackCard()}
        </div>
      </section>
    `;
  }

  function renderFullReportHeader(bundle, tracker) {
    const meta = bundle?.meta || {};
    const summary = getReportUiText(
      bundle?.report_document?.executive_summary || meta.summary,
      "\u62a5\u544a\u6309\u7167\u884c\u4e1a\u5224\u65ad\u3001\u80fd\u529b\u8bc1\u636e\u3001\u5c97\u4f4d\u5bf9\u6bd4\u548c\u804c\u4e1a\u8def\u5f84\u5c55\u5f00\u3002"
    );
    return `
      <section class="ucrd-full-head crdoc-full-head">
        <div class="crdoc-header-main">
          <div class="crdoc-header-copy">
            <span class="crdoc-header-bar" aria-hidden="true"></span>
            <div>
              <p class="ucrd-kicker">Career Report</p>
              <h2 class="ucrd-full-head-title">${esc(meta.title || "\u804c\u4e1a\u751f\u6daf\u53d1\u5c55\u62a5\u544a")}</h2>
              <p class="ucrd-full-head-summary">${esc(summary)}</p>
            </div>
          </div>
          ${renderReportFullHeaderMeta(bundle, tracker)}
        </div>
      </section>
    `;
  }

  function renderReportDashboardV2(bundle, tracker) {
    const data = buildReportDashboardUiData(bundle, tracker);
    return `
      <div class="crdoc-page">
        ${renderReportDashboardHero(data)}
        <nav class="crdoc-nav" aria-label="\u62a5\u544a\u6bb5\u843d\u5bfc\u822a">
          <button type="button" class="crdoc-nav-btn active" data-report-doc-nav-target="reportDocSection-position" aria-pressed="true">01 \u5f53\u524d\u72b6\u6001</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-trends" aria-pressed="false">02 \u884c\u4e1a\u8d8b\u52bf</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-targets" aria-pressed="false">03 \u76ee\u6807\u5c97\u4f4d\u5bf9\u6bd4</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-path" aria-pressed="false">04 \u804c\u4e1a\u8def\u5f84</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-plan" aria-pressed="false">05 \u884c\u52a8\u8ba1\u5212</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-summary" aria-pressed="false">06 \u5173\u952e\u5224\u65ad</button>
        </nav>
        ${renderReportDashboardPositionSection(data)}
        ${renderReportDashboardTrendSection(data)}
        ${renderReportDashboardTargetsSection(data)}
        ${renderReportDashboardPathSection(data)}
        ${renderReportDashboardPlanSection(data)}
        ${renderReportDashboardSummarySection(data)}
      </div>
    `;
  }

  function bindReportDocNavigation(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const buttons = Array.from(root.querySelectorAll("[data-report-doc-nav-target]"));
    const sections = buttons
      .map((button) => {
        const targetId = String(button.dataset.reportDocNavTarget || "").trim();
        if (!targetId) return null;
        const target = root.querySelector(`#${targetId}`);
        return target ? { button, target, targetId } : null;
      })
      .filter(Boolean);
    const revealTargets = Array.from(root.querySelectorAll(".crdoc-reveal"));

    const setActive = (targetId) => {
      buttons.forEach((button) => {
        const active = String(button.dataset.reportDocNavTarget || "").trim() === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    };

    sections.forEach(({ button, target, targetId }) => {
      button.addEventListener("click", () => {
        setActive(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    setActive(sections[0]?.targetId || "");

    if (typeof window.IntersectionObserver !== "function") {
      revealTargets.forEach((node) => node.classList.add("is-visible"));
      return;
    }

    const navObserver = new window.IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible?.target?.id) return;
      setActive(visible.target.id);
    }, {
      threshold: [0.25, 0.45, 0.65],
      rootMargin: "-18% 0px -52% 0px"
    });
    sections.forEach(({ target }) => navObserver.observe(target));

    const revealObserver = new window.IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, {
      threshold: 0.18,
      rootMargin: "0px 0px -8% 0px"
    });
    revealTargets.forEach((node) => {
      if (node.classList.contains("is-visible")) return;
      revealObserver.observe(node);
    });
  }

  async function initializeRestoration() {
    ensureAppState();
    ensurePlanFunctionsWrapped();
    primeCareerReportStateFromBootstrap();
    bindGlobalRestorationEvents();
    bindCareerReportEditorEvents();

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
  window.loadCurrentCareerReport = loadCurrentCareerReport;
  window.startCareerReportGeneration = startCareerReportGeneration;
  window.renderCareerReportPanels = renderCareerReportPanels;
  window.openReportViewer = openReportViewer;
  window.closeReportViewer = closeReportViewer;
  window.openCareerReportEditor = openCareerReportEditor;
  window.closeCareerReportEditor = closeCareerReportEditor;
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
