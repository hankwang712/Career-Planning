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
    feedbackNote: ""
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

  function renderReportSections(bundle) {
    const rawSections = bundle?.report_document?.sections;

    // v2: sections is an object keyed by module name
    if (rawSections && !Array.isArray(rawSections) && typeof rawSections === "object") {
      return renderReportSections4(bundle, rawSections);
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

  function renderReportSections4(bundle, sections) {
    const navOrder = ["industry_analysis", "career_positioning", "resume_evidence", "competency_profile", "role_match", "path_plan"];
    const navMeta = {
      "industry_analysis":  { label: "行业分析",   icon: "📈", anchor: "cr-sec-industry",    kicker: "Industry Analyst",             accentClass: "cr-module-purple" },
      "career_positioning": { label: "职业定位",   icon: "🎯", anchor: "cr-sec-positioning", kicker: "Career Positioning Advisor",   accentClass: "cr-module-blue" },
      "resume_evidence":    { label: "简历证据",   icon: "📄", anchor: "cr-sec-resume",       kicker: "Resume Evidence Analyst",      accentClass: "cr-module-amber" },
      "competency_profile": { label: "能力评估",   icon: "💡", anchor: "cr-sec-competency",   kicker: "Competency Assessor",          accentClass: "cr-module-green" },
      "role_match":         { label: "岗位匹配",   icon: "🎯", anchor: "cr-sec-match",        kicker: "Role Match Officer",           accentClass: "cr-module-indigo" },
      "path_plan":          { label: "路径规划",   icon: "🛤️", anchor: "cr-sec-path",         kicker: "Career Path Planner",          accentClass: "cr-module-teal" },
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

    // ── per-section body renderers ────────────────────────────────────────────

    function renderIndustryBody(data) {
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
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(d.name || String(d))}</span>
              <span class="cr4-badge ${d.confidence === "高" ? "cr4-badge-green" : d.confidence === "低" ? "cr4-badge-red" : "cr4-badge-amber"}">${esc(d.confidence || "中")}</span>
            </div>`).join("")}
        </div>` : "";

      const skillList = skillPrios.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">能力投资优先级</div></div>
          ${skillPrios.map((s) => skillBar(s.skill || String(s), s.importance === "高" ? 85 : s.importance === "低" ? 40 : 65,
            s.importance === "高" ? "linear-gradient(90deg,var(--cr4-primary),var(--cr4-primary-light))" :
            s.importance === "低" ? "linear-gradient(90deg,#94a3b8,#cbd5e1)" :
            "linear-gradient(90deg,var(--cr4-secondary),#38bdf8)")).join("")}
        </div>` : "";

      const riskList = risks.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">风险信号</div></div>
          <div class="cr4-gap-grid">
            ${risks.map((r, i) => gapPill(String(r), i === 0 ? "urgent" : "warn")).join("")}
          </div>
        </div>` : "";

      return `
        ${summary ? `<div class="cr4-summary-banner">${esc(summary)}</div>` : ""}
        <div class="cr4-stat-row">${statCards.join("")}</div>
        <div class="cr4-grid-2">${hotList}${skillList}</div>
        ${riskList}`;
    }

    function renderPositioningBody(data) {
      const tracks      = Array.isArray(data.recommended_tracks)       ? data.recommended_tracks      : [];
      const hyps        = Array.isArray(data.hypotheses_for_evidence)  ? data.hypotheses_for_evidence : [];
      const constraints = Array.isArray(data.constraints_hard)         ? data.constraints_hard        : [];
      const summary     = data.user_intent_summary || "";

      const trackCards = tracks.map((t, i) => `
        <div class="cr4-track-card ${i === 0 ? "cr4-track-primary" : ""}">
          <div class="cr4-track-priority">${i === 0 ? "P0 主推荐" : `P${i} 备选`}</div>
          <div class="cr4-track-name">${esc(String(t))}</div>
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
        <div class="cr4-stat-row">
          ${statCard("强证据", strengthCount || "—", "项可追溯", "cr4-ac-green")}
          ${statCard("证据缺口", gapCount || "0", "项待补充", "cr4-ac-amber")}
          ${statCard("通用能力", genComp.length || "—", "项", "cr4-ac-blue")}
        </div>
        <div class="cr4-grid-2">${skillBars}${genBars}</div>
        ${gapBlock}
        ${hypBlock}`;
    }

    function renderCompetencyBody(data) {
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

      return `
        <div class="cr4-stat-row">
          ${statCard("综合能力分", overallScore || "—", "基于证据推算", "cr4-ac-purple")}
          ${statCard("核心优势", strengths.length || "—", "项", "cr4-ac-green")}
          ${statCard("短板项", gaps.length || "0", "项待提升", "cr4-ac-amber")}
        </div>
        <div class="cr4-dim-grid">${dimCards}</div>
        <div class="cr4-grid-2">${strengthBlock}${gapBlock}</div>`;
    }

    function renderMatchBody(data) {
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
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(g.requirement || String(g))}</span>
              <span class="cr4-badge cr4-badge-amber">${esc(g.remediation_type || "待补充")}</span>
            </div>`).join("")}
        </div>` : "";

      return `
        <div class="cr4-match-layout">
          ${scoreRing}
          <div class="cr4-match-right">
            ${hardBlock}
            ${gapBlock}
          </div>
        </div>`;
    }

    function renderPathBody(data) {
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
          (m.actions || []).slice(0, 2).join("；"),
          m.metrics || [],
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

    const sectionHtml = navOrder.map((key, idx) => {
      const sec  = sections[key];
      const meta = navMeta[key];
      if (!sec) return "";
      const markdown = String(sec.markdown || "").trim();
      const data     = sec.data || {};
      const renderer = bodyRenderers[key];
      const body     = renderer ? renderer(data) : "";

      return `
        <section id="${meta.anchor}" class="cr4-module ${meta.accentClass}">
          <div class="cr4-module-head">
            <div class="cr4-module-icon">${meta.icon}</div>
            <div class="cr4-module-titles">
              <div class="cr4-module-kicker">${esc(meta.kicker)}</div>
              <h3 class="cr4-module-title">${esc(meta.label)}</h3>
            </div>
            <div class="cr4-module-num">${String(idx + 1).padStart(2, "0")}</div>
          </div>
          <div class="cr4-module-body">${body}</div>
          ${markdown ? `
            <details class="cr4-module-detail">
              <summary>查看完整分析文本</summary>
              <div class="cr4-module-markdown">${renderMarkdownBasic(markdown)}</div>
            </details>` : `<p class="cr4-module-empty">该模块尚未生成内容</p>`}
        </section>`;
    }).filter(Boolean).join("");

    return `<div class="cr4-report-modules">${sectionHtml}</div>`;
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
        : (bundle?.report_document
          ? "报告已生成并加载新版式正文。请向下滚动阅读摘要与章节，或使用「全屏查看」。"
          : (bundle?.meta?.summary || state?.summary || "当前展示的是已完成的职业报告。"));

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

  // section definitions for nav
  const SECTION_NAV = [
    { key: "industry_analysis",  label: "行业分析",   icon: "📈", anchor: "cr-sec-industry" },
    { key: "career_positioning", label: "职业定位",   icon: "🎯", anchor: "cr-sec-positioning" },
    { key: "resume_evidence",    label: "简历证据",   icon: "📄", anchor: "cr-sec-resume" },
    { key: "competency_profile", label: "能力评估",   icon: "💡", anchor: "cr-sec-competency" },
    { key: "role_match",         label: "岗位匹配",   icon: "🔗", anchor: "cr-sec-match" },
    { key: "path_plan",          label: "路径规划",   icon: "🛤️", anchor: "cr-sec-path" },
  ];

  function isModularBundle(bundle) {
    const sections = bundle?.report_document?.sections;
    return sections && !Array.isArray(sections) && typeof sections === "object";
  }

  function renderReportAside() {
    const aside = document.getElementById("careerReportAside");
    if (!aside) return;

    const state = getCareerReportStateSafe();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";
    if (generating) {
      aside.innerHTML = "";
      return;
    }

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const outline = Array.isArray(bundle?.report_document?.outline) ? bundle.report_document.outline : [];
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "待识别";
    const isModular = isModularBundle(bundle);

    // Build module nav for modular reports
    const moduleNavHtml = isModular ? `
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Report Modules</p>
        <h3 class="career-report-side-title">报告模块</h3>
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

    // v2: show match score if available
    const matchOutput = bundle?.match_output || {};
    const fitScore = Number(matchOutput.fit_score || bundle?.role_rankings?.[0]?.overall_score || 0);
    const fitBand = String(matchOutput.fit_band || "");
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || "--";

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
            <span>${v2 ? "人岗契合" : "报告版本"}</span>
            <strong>${v2 ? esc(`${fitScore}% · ${fitBandLabel}`) : esc(bundle?.meta?.version || tracker?.report_version || "--")}</strong>
          </article>
          <article>
            <span>完成度</span>
            <strong>${esc(`${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`)}</strong>
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
      ${!v2 ? `
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
      </section>` : ""}
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

    main.innerHTML = `
      ${renderHistoricalNotice()}
      ${renderReportMagazineLayout(bundle, tracker)}
      ${renderReportSections(bundle)}
    `;

    main.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
    bindCareerReportFeedbackHandlers(main);
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
        ? `${renderHistoricalNotice()}${renderReportMagazineLayout(bundle, tracker)}${renderReportSections(bundle)}`
        : renderEmptyReportMain();
      if (bundle && bundle.report_document) {
        bindCareerReportFeedbackHandlers(main);
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
