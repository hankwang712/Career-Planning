/* 岗位全链路流水线 · 核心层
   状态管理 / 漏斗 / 执行轨道 / 岗位看板 / 顶栏三态主操作 / 12s 轮询 /
   抽屉与弹窗框架 / 乐观更新 / toast / count-up / 自绘 line-icon 图标库。
   抽屉面板与物料渲染在 recruitment-pipeline.js 中注册（window.RP）。 */
(() => {
  "use strict";
  // 旧根路径书签带着 hash 跳转到新首页。
  if (["#dashboard", "#profile", "#report"].includes(window.location.hash)) {
    window.location.replace("/main.html" + window.location.hash);
    return;
  }

  const API = "/api/job-market/collection";
  // 契约 §2 同时出现两种前缀写法；按 blueprint 前缀优先探测，404 时回退另一写法。
  const PIPELINE_BASES = [API + "/pipeline", "/api/recruitment/pipeline"];
  const POLL_MS = 12000;
  const PAGE_SIZE = 100; // 后端 /jobs limit 上限 100
  const MAX_JOBS = 600;
  const TAB_FETCH_CAP = 300;
  const BOARD_PAGE_SIZE = 8;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const byId = (id) => document.getElementById(id);

  const meta = (() => {
    let data;
    try { data = JSON.parse(byId("rpMeta").textContent); }
    catch (_) { data = {}; }
    data.profiles ||= { general: "通用" };
    data.dimensions ||= {};
    data.settings_url ||= "/settings";
    data.resumes_url ||= "/user-center/resumes";
    data.export_url ||= API + "/export";
    // 后端 SOURCES 值为元组（名称, …），统一归一为 id → 名称。
    data.sources = Object.fromEntries(Object.entries(data.sources || {}).map(([id, value]) =>
      [id, Array.isArray(value) ? String(value[0]) : String(value)]));
    return data;
  })();

  /* ---------- 自绘 line-icon 图标库（24×24，stroke 风格） ---------- */
  const ICONS = {
    inbox: '<path d="M5 5h14l2 8v6H3v-6z"/><path d="M3 13h5l2 3h4l2-3h5"/>',
    filter: '<path d="M4 5h16l-6.5 7.5V19l-3 1.5v-8z"/>',
    sparkles: '<path d="m11 4 1.5 4.5L17 10l-4.5 1.5L11 16l-1.5-4.5L5 10l4.5-1.5z"/><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z"/>',
    gauge: '<path d="M4.5 17a9 9 0 1 1 15 0"/><path d="m12 14 4-4"/><circle cx="12" cy="14" r="1.4"/>',
    pen: '<path d="m4 20 1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="m14.5 6.5 3 3"/>',
    message: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
    shield: '<path d="m12 3 8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="m9 12 2 2 4-4"/>',
    send: '<path d="M21 3 10.5 13.5"/><path d="M21 3l-7 18-3.5-7.5L3 10z"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    "chevron-left": '<path d="m14 6-6 6 6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "arrow-right": '<path d="M4 12h15m-6-6 6 6-6 6"/>',
    external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5H5V6h5"/>',
    alert: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4m0 3h.01"/>',
    check: '<path d="m5 13 4 4L19 7"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/>',
    "file-text": '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M3 13h18"/>',
    "map-pin": '<path d="M19 10c0 5-7 10-7 10s-7-5-7-10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2.3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    graduation: '<path d="m2.5 9 9.5-4 9.5 4-9.5 4z"/><path d="M6.5 11v5c3.5 3 7.5 3 11 0v-5"/>',
    banknote: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="m9 9 3 3 3-3M12 12v4M9.5 13.5h5"/>',
    trash: '<path d="M4.5 6.5h15m-12 0 1 14h7l1-14m-7-3h5l1 3M10.5 10v7m3-7v7"/>',
    rotate: '<path d="M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4"/>',
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    upload: '<path d="M12 16V4m-5 5 5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>',
    sliders: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20v-1.5A4.5 4.5 0 0 1 7.5 14h3a4.5 4.5 0 0 1 4.5 4.5V20"/><path d="M16 5.5a3.5 3.5 0 0 1 0 6.8M18.5 14a4.5 4.5 0 0 1 2.5 4v2"/>',
    building: '<rect x="5" y="3" width="14" height="18" rx="1.5"/><path d="M9 7h2m2 0h2M9 11h2m2 0h2M9 15h2m2 0h2M10 21v-3h4v3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>',
    download: '<path d="M12 4v12m-5-5 5 5 5-5"/><path d="M4 16v4h16v-4"/>',
    funnel: '<path d="M4 5h16l-6.5 7.5V19l-3 1.5v-8z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>',
    "user-check": '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20v-1.5A4.5 4.5 0 0 1 8 14h4"/><path d="m15 17 2 2 4-4"/>',
    bookmark: '<path d="M6 4h12v16l-6-4-6 4z"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>'
  };
  function icon(name, className) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (className) svg.setAttribute("class", className);
    svg.innerHTML = ICONS[name] || ICONS.info;
    return svg;
  }
  function tile(name, tone, small) {
    const el = node("span", "", "rp-icon-tile" + (small ? " rp-tile-sm" : ""));
    if (tone) el.dataset.tone = tone;
    el.append(icon(name));
    return el;
  }
  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  /* ---------- toast（最多 3 条，避免轰炸） ---------- */
  function toast(message, tone = "info") {
    const root = byId("rpToasts");
    if (!message) return;
    while (root.children.length >= 3) root.firstChild.remove();
    const el = node("div", "", "rp-toast");
    el.dataset.tone = tone;
    el.append(icon({ success: "check-circle", error: "alert", warning: "alert" }[tone] || "info"), node("span", message));
    root.append(el);
    window.setTimeout(() => {
      el.classList.add("is-leaving");
      window.setTimeout(() => el.remove(), reduceMotion ? 0 : 240);
    }, 3600);
  }

  /* ---------- 请求层 ---------- */
  async function rawRequest(url, body, method, signal) {
    const options = { signal, credentials: "include" };
    const useMethod = method || (body !== undefined ? "POST" : "GET");
    if (useMethod !== "GET") {
      options.method = useMethod;
      options.headers = { ...(await (window.CareerAuth?.headers?.() || {})) };
      if (body instanceof FormData) options.body = body;
      else if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
    }
    return fetch(url, options);
  }
  async function readJson(response) {
    if (response.status === 401) throw new Error("登录已过期，请重新登录。");
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* 非 JSON 响应 */ }
    if (!response.ok) {
      const error = new Error(payload?.message || `请求未完成（${response.status}），请稍后重试。`);
      error.status = response.status;
      throw error;
    }
    return payload || {};
  }
  async function api(path, body, method) {
    return readJson(await rawRequest(API + path, body, method));
  }
  let pipelineBase = null;
  async function pipelineApi(path, body, method, signal) {
    const detect = !pipelineBase && /^\/(funnel|rail|jobs)/.test(path);
    const bases = pipelineBase ? [pipelineBase] : detect ? PIPELINE_BASES : [PIPELINE_BASES[0]];
    let lastError;
    for (const base of bases) {
      let response;
      try { response = await rawRequest(base + path, body, method, signal); }
      catch (error) {
        if (error.name === "AbortError") throw error;
        lastError = error;
        continue;
      }
      if (response.status === 404 && detect && base !== bases[bases.length - 1]) {
        lastError = Object.assign(new Error("流水线接口尚未就绪。"), { status: 404 });
        continue;
      }
      pipelineBase = base;
      if (response.status === 404 && (path === "/purge" || path === "/save") &&
          !response.headers.get("content-type")?.includes("application/json")) {
        throw new Error("当前运行的后端还未加载岗位保存和清理接口。请重启工作台服务后刷新页面。");
      }
      return readJson(response);
    }
    throw lastError || Object.assign(new Error("流水线接口尚未就绪。"), { status: 404 });
  }

  /* ---------- 状态 ---------- */
  const STAGE_LABELS = {
    collected: "已导入", cleaned: "清洗通过", screened: "已初评", deep: "已深评",
    rewritten: "已改写", greeted: "打招呼已生成", approval: "待审批", queued: "待投递",
    delivered: "已投递", rejected: "已淘汰", failed: "执行失败", reeval: "待重评"
  };
  const STAGE_ORDER = ["collected", "cleaned", "screened", "deep", "rewritten", "greeted", "approval", "queued", "delivered"];
  const IN_PROGRESS = new Set(["collected", "cleaned", "screened", "deep", "rewritten", "greeted"]);
  const TABS = ["all", "saved", "rejected", "in_progress", "reeval", "approval", "queued", "delivered", "failed"];
  const RUN_STAGES = [
    { stage: "clean", label: "规则清洗" }, { stage: "evaluate", label: "AI 评估" },
    { stage: "rewrite", label: "简历改写" },
    { stage: "greet", label: "打招呼语" }
  ];
  const RAIL_STEPS = [
    { key: "scraping", label: "抓取导入", icon: "inbox", result: "已采集" },
    { key: "cleaning", label: "规则清洗", icon: "filter", run: "clean", result: "已清洗" },
    { key: "evaluating", label: "AI 评估", icon: "sparkles", run: "evaluate", result: "已评估" },
    { key: "rewriting", label: "简历改写", icon: "pen", run: "rewrite", result: "已改写" },
    { key: "greeting", label: "打招呼语", icon: "message", run: "greet", result: "已生成" },
    { key: "review", label: "人工审批", icon: "shield", waiting: "待审批" },
    { key: "delivering", label: "投递队列", icon: "send", result: "已生成投递包", waiting: "待投递" }
  ];
  const activeRailRuns = new Map();
  let cleaningRun = null;
  const FUNNEL_ICONS = [
    { match: /collect|crawl|scrap|import|seed/, icon: "inbox", tone: "accent" },
    { match: /clean/, icon: "filter", tone: "brass" },
    { match: /eval|screen|ai/, icon: "sparkles", tone: "info" },
    { match: /approv|pending|review/, icon: "shield", tone: "warning" },
    { match: /ready|queu/, icon: "send", tone: "accent" },
    { match: /deliver|success/, icon: "check-circle", tone: "success" }
  ];

  const state = {
    funnel: null, rail: null, config: null,
    jobs: [], jobsTotal: 0, counts: {}, tabLoadToken: 0,
    tab: "all", q: "", source: "", page: 1, boardJobs: [], boardTotal: 0,
    boardLoading: false, boardError: "", boardRequest: 0,
    apiReady: false, loading: true, refreshing: false, failCount: 0, stale: false,
    running: false, runStage: null, runToken: 0, runController: null,
    armed: false, armTimer: 0,
    selectedFailed: new Map(),
    drawer: null, drawerCtx: null, drawerBusy: false, drawerSeq: 0,
    modalJob: null, modalTab: "resume",
    bulkBusy: false, funnelTotal: 0, funnelPrev: {}
  };

  /* ---------- 通用小工具 ---------- */
  const timeFmt = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  function fmtTime(ts) {
    if (!ts) return "";
    const date = new Date(ts * 1000);
    return Number.isNaN(date.getTime()) ? "" : timeFmt.format(date);
  }
  const SOURCE_EXTRA = { city_jobs: "城市种子", local: "本地导入", csv: "CSV 导入", html: "网页导入", seed: "种子导入" };
  function sourceLabel(source) {
    return meta.sources[source] || SOURCE_EXTRA[source] || source || "本地";
  }
  function jobId(job) { return job.source + "|" + job.url_key; }
  function stageIndex(stage) { return STAGE_ORDER.indexOf(stage); }
  function gradeOf(raw) {
    const value = String(raw || "").trim().toUpperCase();
    return /^[A-F]$/.test(value) ? value : "";
  }
  function displaySalary(salary) {
    return /[\p{Co}�]/u.test(salary || "") ? "" : (salary || "");
  }
  function animateNumber(el, target, suffix = "") {
    const from = Number(el.dataset.value || 0);
    el.dataset.value = String(target);
    if (reduceMotion || from === target) { el.textContent = target + suffix; return; }
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = Math.round(from + (target - from) * eased) + suffix;
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /* ---------- 岗位归一化 ---------- */
  function normalizeJob(raw) {
    const job = { ...raw };
    const meta = raw.meta && typeof raw.meta === "object" ? raw.meta : {};
    const failure = raw.failure && typeof raw.failure === "object" ? raw.failure : {};
    job.source = String(raw.source || "");
    job.url_key = String(raw.url_key || raw.url || "");
    job.url = raw.url || "";
    job.title = raw.title || "未命名岗位";
    job.company = raw.company || "";
    job.location = raw.location || meta.collected_city || "";
    job.salary = displaySalary(raw.salary);
    job.experience = raw.experience || "";
    job.education = raw.education || "";
    job.scale = meta.company_size || "";
    job.description = raw.description || "";
    job.profile = raw.profile || "general";
    job.stage = raw.stage || "collected";
    job.followStatus = raw.follow_status || "";
    job.grade = gradeOf(raw.grade);
    const score = raw.score ?? null;
    job.score = score != null && score !== "" && Number.isFinite(Number(score)) ? Number(score) : null;
    job.track = raw.review_type === "mass" ? "mass" : "precision";
    job.reason = raw.cleaning_reason || failure.reason || "";
    job.error = failure.error || "";
    job.failureKind = failure.kind || "";
    job.retryable = failure.retryable;
    job.attempts = raw.failure_count ?? failure.failure_count ?? null;
    job.updatedAt = raw.action_at || raw.updated_at || 0;
    job.crawledAt = raw.updated_at || 0;
    job.hasDeep = Boolean(raw.has_deep);
    job.hasRewrite = Boolean(raw.has_rewrite);
    job.hasGreeting = Boolean(raw.has_greeting);
    job.saved = Boolean(raw.saved);
    job.savedAt = raw.saved_at || 0;
    job.tab = TABS.includes(raw.tab) ? raw.tab : tabOf(job);
    return job;
  }
  function tabOf(job) {
    if (job.saved) return "saved";
    return stageTabOf(job);
  }
  function stageTabOf(job) {
    if (job.stage === "rejected" || job.status === "rejected") return "rejected";
    if (job.stage === "failed" || job.status === "failed") return "failed";
    if (job.stage === "reeval") return "reeval";
    if (job.stage === "approval") return "approval";
    if (job.stage === "queued") return "queued";
    if (job.stage === "delivered") return "delivered";
    return "in_progress";
  }
  function filteredJobs() {
    return state.boardJobs.filter((job) => state.tab === "all" ? !job.saved : job.tab === state.tab);
  }
  function tabCounts() {
    // 优先用服务端口径（全量），乐观更新时做增量调整；未就绪时回退本地计数。
    if (state.counts && Object.keys(state.counts).length) return { ...state.counts };
    const counts = Object.fromEntries(TABS.map((tab) => [tab, 0]));
    for (const job of state.jobs) {
      if (!job.saved) counts.all += 1;
      counts[job.tab] += 1;
    }
    return counts;
  }
  function adjustCounts(from, to, n = 1) {
    if (!state.counts || !Object.keys(state.counts).length || from === to) return;
    state.counts[from] = Math.max(0, (state.counts[from] || 0) - n);
    state.counts[to] = (state.counts[to] || 0) + n;
  }

  /* ---------- 漏斗 ---------- */
  function renderFunnel() {
    const root = byId("rpFunnel");
    const data = state.funnel;
    const stages = Array.isArray(data?.stages) ? data.stages : [];
    if (!stages.length) return;
    const total = stages[0]?.count || 0;
    const delivered = stages.find((s) => /deliver/.test(s.key))?.count || 0;
    const evaluated = stages.find((s) => /eval|screen/.test(s.key))?.count || 0;
    const rate = data.delivery_rate ?? data.conversion ?? (evaluated ? Math.round(delivered / Math.max(evaluated, 1) * 100) : 0);
    animateNumber(byId("rpDeliveryRate"), Number(rate) || 0, "%");
    const parts = [];
    stages.forEach((stage, index) => {
      if (index) {
        const arrow = node("span", "", "rp-funnel-arrow");
        arrow.append(icon("arrow-right"));
        parts.push(arrow);
      }
      const conf = FUNNEL_ICONS.find((item) => item.match.test(stage.key || "")) || FUNNEL_ICONS[0];
      const tileEl = node("div", "", "rp-funnel-tile");
      const isApproval = /approv|pending|review/.test(stage.key || "");
      if (isApproval && stage.count > 0) tileEl.classList.add("is-hot");
      const top = node("div", "", "rp-funnel-tile-top");
      top.append(node("span", stage.label || "阶段", "rp-funnel-label"), tile(conf.icon, conf.tone, true));
      const value = node("div", "", "rp-funnel-value");
      const num = node("span", "0", "dr-count");
      num.dataset.value = String(state.funnelPrev[stage.key] || 0);
      value.append(num, node("span", stage.unit || "条", "rp-funnel-unit"));
      tileEl.append(top, value);
      parts.push(tileEl);
      state.funnelPrev[stage.key] = Number(stage.count) || 0;
      animateNumber(num, Number(stage.count) || 0);
    });
    root.replaceChildren(...parts);
    state.funnelTotal = total;
  }

  /* ---------- 执行轨道 ---------- */
  function railSteps() {
    const steps = Array.isArray(state.rail?.steps) ? state.rail.steps : [];
    return RAIL_STEPS.map((base) => {
      const remote = steps.find((s) => s.key === base.key) || {};
      return { ...base, label: remote.label || base.label, desc: remote.desc || "", config_state: remote.config_state || "auto", count: Number(remote.count) || 0 };
    });
  }
  function renderRail() {
    if (!state.rail) return;
    const steps = railSteps();
    const warnings = Array.isArray(state.rail.warnings) ? state.rail.warnings : [];
    const delivery = new Map((state.funnel?.stages || []).map(stage => [stage.key, stage.count]));
    const needsConfig = (step) => step.key !== "scraping" &&
      (step.config_state === "required_missing" || warnings.includes(step.key));
    const next = steps.find(step => !step.waiting && !step.count);
    const root = byId("rpRail");
    root.replaceChildren(...steps.map((step, index) => {
      const pending = step.key === "delivering" ? (delivery.get("ready") || 0) : step.waiting ? step.count : 0;
      const count = step.key === "delivering" ? (delivery.get("delivered") || 0) : step.waiting ? 0 : step.count;
      let cardState = "idle", label = "未开始";
      if (activeRailRuns.has(step.run) || (step.key === "cleaning" && cleaningRun)) [cardState, label] = ["active", "执行中"];
      else if (needsConfig(step)) [cardState, label] = ["blocked", "待配置"];
      else if (pending) [cardState, label] = ["waiting", step.waiting];
      else if (count) [cardState, label] = ["done", step.result];
      else if (step === next && !activeRailRuns.size && !state.running) [cardState, label] = ["next", "下一步"];
      const detail = pending && count ? `${pending} 条待投递 · ${count} 条已出包`
        : pending || count ? `${pending || count} 条${label === step.result || label === step.waiting ? "" : step.result}` : "";
      const isCleaning = step.key === "cleaning";
      const card = node(isCleaning ? "div" : "button", "", "rp-step");
      const configButton = isCleaning ? node("button", "", "rp-step-config") : card;
      configButton.type = "button";
      card.dataset.state = cardState;
      card.dataset.step = step.key;
      configButton.setAttribute("aria-label", [step.label, label, detail, "打开阶段面板"].filter(Boolean).join("，"));
      configButton.title = step.desc;
      const head = node("span", "", "rp-step-head");
      const num = node("span", String(index + 1), "rp-step-num");
      if (cardState === "done") { num.textContent = ""; num.append(icon("check")); }
      const title = node("span", "", "rp-step-title");
      title.append(icon(step.icon), node("span", step.label));
      head.append(num, title);
      const badge = node("span", label, "rp-step-chip");
      const summary = pending || count ? node("span", detail, "rp-step-count") : null;
      configButton.append(head, badge);
      if (summary) configButton.append(summary);
      configButton.addEventListener("click", () => openDrawer(step.key));
      if (isCleaning) {
        card.append(configButton);
        if (cleaningRun) {
          const { total, processed, finished } = cleaningRun;
          const progress = node("progress", "", "rp-clean-meter");
          progress.setAttribute("aria-label", "岗位清洗进度");
          if (total !== null) {
            progress.max = Math.max(total, 1);
            progress.value = processed;
          }
          const labels = node("div", "", "rp-clean-progress-labels");
          const current = total === null ? "正在读取岗位…" : finished || !total
            ? `已处理 ${processed} 条` : `第 ${Math.min(processed + 1, total)} / ${total} 条`;
          labels.append(node("span", current));
          if (total !== null) labels.append(node("span", `剩余 ${Math.max(0, total - processed)} 条`));
          const meter = node("div", "", "rp-clean-progress");
          meter.append(labels, progress);
          card.append(meter);
        } else {
          const run = actionButton("执行规则清洗", "rp-btn-accent rp-clean-run", runSavedCleaning, "play");
          run.disabled = !steps[0].count || needsConfig(step) || state.running;
          run.title = needsConfig(step) ? "请先配置并保存规则" : "按岗位所属方向执行已保存的规则";
          card.append(run);
        }
      }
      return card;
    }));
    renderRailNotice(steps.filter(needsConfig), Boolean(steps[0]?.count));
    renderResumePill();
  }
  function renderRailNotice(missing, hasJobs) {
    const root = byId("rpRailNotice");
    const bar = node("div", "", "rp-railnotice-bar");
    if (missing.length) {
      bar.dataset.tone = "warning";
      bar.append(icon("alert"), node("span", `待配置 ${missing.length} 个阶段：`));
      const links = node("span", "", "rp-notice-links");
      for (const step of missing) {
        const link = node("button", step.label, "rp-noticelink");
        link.type = "button";
        link.addEventListener("click", () => openDrawer(step.key));
        links.append(link);
      }
      bar.append(links);
    } else if (hasJobs) {
      bar.dataset.tone = "success";
      bar.append(icon("check-circle"), node("span", "全部阶段就绪，可以启动本轮流水线。"));
    }
    root.replaceChildren(...(bar.childNodes.length ? [bar] : []));
  }
  function renderResumePill() {
    const slot = byId("rpResumePill");
    const baseline = state.rail?.resume_baseline;
    const options = Array.isArray(baseline?.options) ? baseline.options : [];
    slot.replaceChildren();
    if (baseline && baseline.enabled) {
      const current = options.find((item) => item.title === baseline.name);
      const pill = node("button", "", "rp-resume-pill");
      pill.type = "button";
      pill.setAttribute("aria-expanded", "false");
      pill.append(node("i", "", "rp-resume-dot"), node("span", baseline.name || "基准简历", "rp-resume-name"));
      if (current?.chars) pill.append(node("span", `${current.chars} 字`, "rp-resume-chars"));
      pill.append(icon("chevron-down"));
      const pop = node("div", "", "rp-resume-pop");
      pop.hidden = true;
      pop.append(node("strong", "切换基准简历"), node("p", "初评与改写以选中的简历为底稿。"));
      for (const option of options.slice(0, 8)) {
        const item = node("button", "", "rp-resume-option");
        item.type = "button";
        item.dataset.current = String(option.title === baseline.name);
        item.append(node("span", option.title || "简历文档"), node("small", `${option.chars || 0} 字`));
        item.addEventListener("click", async () => {
          item.disabled = true;
          try {
            await pipelineApi("/config", { baseline_resume_id: option.id });
            toast(`基准简历已切换为「${option.title}」。`, "success");
            pop.hidden = true;
            void refresh({ silent: true });
          } catch (error) {
            toast(error.message, "error");
          } finally { item.disabled = false; }
        });
        pop.append(item);
      }
      if (!options.length) pop.append(node("p", "简历库暂无已解析文档。"));
      const link = node("a", "去简历库管理 ↗");
      link.href = meta.resumes_url;
      pop.append(link);
      pill.addEventListener("click", (event) => {
        event.stopPropagation();
        pop.hidden = !pop.hidden;
        pill.setAttribute("aria-expanded", String(!pop.hidden));
      });
      slot.append(pill, pop);
    } else {
      const pill = node("a", "", "rp-resume-pill");
      pill.dataset.missing = "1";
      pill.href = meta.resumes_url;
      pill.append(icon("alert"), node("span", "未找到启用简历", "rp-resume-name"), icon("external"));
      slot.append(pill);
    }
  }

  /* ---------- 顶栏三态主操作 ---------- */
  function warningsList() {
    if (!state.rail) return [];
    const warnings = Array.isArray(state.rail.warnings) ? state.rail.warnings : [];
    const steps = railSteps();
    return [...new Set([...warnings, ...steps.filter((s) => s.config_state === "required_missing").map((s) => s.key)])];
  }
  function renderCommandbar() {
    const pill = byId("rpRunPill");
    const pillText = byId("rpRunPillText");
    const action = byId("rpMainAction");
    const warnings = warningsList();
    let pillState, pillLabel = "", actionState, actionLabel, disabled = false;
    if (state.loading && !state.apiReady) {
      actionState = "loading"; actionLabel = "正在读取…"; disabled = true;
    } else if (state.running) {
      const stageLabel = RUN_STAGES.find((s) => s.stage === state.runStage)?.label || "";
      pillState = "running"; pillLabel = stageLabel ? `运行中 · ${stageLabel}` : "运行中";
      actionState = "running"; actionLabel = "终止运行";
    } else if (cleaningRun) {
      pillState = "running"; pillLabel = "运行中 · 规则清洗";
      actionState = "loading"; actionLabel = "正在清洗…"; disabled = true;
    } else if (state.stale) {
      pillState = "stale"; pillLabel = "连接中断 · 自动重试";
      actionState = warnings.length ? "blocked" : "ready";
      actionLabel = warnings.length ? `待配置 ${warnings.length} 项` : "启动流水线";
    } else if (warnings.length) {
      actionState = "blocked"; actionLabel = `待配置 ${warnings.length} 项`;
    } else {
      actionState = state.armed ? "armed" : "ready";
      actionLabel = state.armed ? "再次点击确认启动" : "启动流水线";
    }
    pill.dataset.state = pillState || "";
    pill.hidden = !pillLabel;
    pillText.textContent = pillLabel;
    action.dataset.state = actionState;
    action.disabled = disabled;
    action.replaceChildren();
    if (actionState === "running") action.append(icon("stop"));
    else if (actionState === "ready" || actionState === "armed") action.append(icon("play"));
    else if (actionState === "blocked") action.append(icon("alert"));
    action.append(document.createTextNode(actionLabel));
    renderBlockBanner(warnings);
  }
  function renderBlockBanner(warnings) {
    const banner = byId("rpBlockBanner");
    const rail = state.rail;
    const llmMissing = rail ? rail.llm_configured === false : warnings.includes("evaluating");
    banner.hidden = !llmMissing || !state.apiReady;
    if (!banner.hidden) {
      byId("rpBlockBannerText").textContent = rail?.heuristic_mode
        ? "启发式模式运行中：对话模型未配置，AI 阶段使用确定性启发式结果，仅供筛选参考，外发前请人工核验。"
        : "对话模型未配置且未确认启发式模式：AI 阶段暂无法执行，请先完成配置。";
    }
  }
  function disarm() {
    state.armed = false;
    window.clearTimeout(state.armTimer);
    renderCommandbar();
  }
  async function runPipeline() {
    if (!state.apiReady) return;
    if (!(state.funnelTotal > 0) && !state.jobs.length) {
      toast("暂无岗位，请先获取新岗位。", "warning");
      openDrawer("scraping");
      return;
    }
    const token = ++state.runToken;
    state.running = true;
    state.armed = false;
    renderCommandbar();
    let aborted = false;
    let failed = false;
    for (let i = 0; i < RUN_STAGES.length; i += 1) {
      if (token !== state.runToken) { aborted = true; break; }
      const { stage, label } = RUN_STAGES[i];
      state.runStage = stage;
      renderCommandbar();
      try {
        if (stage === "clean") await runCleaningBatches({}, () => token === state.runToken);
        else await runStage(stage);
      } catch (error) {
        if (error.name === "AbortError" || token !== state.runToken) aborted = true;
        else { failed = true; toast(`${label}阶段未完成：${error.message}`, "error"); }
        break;
      }
    }
    state.running = false;
    state.runStage = null;
    state.runController = null;
    renderCommandbar();
    await refresh({ silent: true });
    if (aborted) toast("本轮流水线已终止。", "warning");
    else if (!failed) toast("本轮流水线执行完成，待审批岗位已在看板就位。", "success");
  }
  function stopPipeline() {
    state.runToken += 1;
    state.runController?.abort();
    state.running = false;
    state.runStage = null;
    renderCommandbar();
    toast("已请求终止：当前阶段停止后不再继续。", "warning");
    void refresh({ silent: true });
  }
  async function runStage(stage, options = {}) {
    const controller = new AbortController();
    state.runController = controller;
    const base = pipelineBase || PIPELINE_BASES[0];
    activeRailRuns.set(stage, (activeRailRuns.get(stage) || 0) + 1);
    renderRail();
    try {
      return await readJson(await rawRequest(base + "/run", { stage, ...options }, "POST", controller.signal));
    } catch (error) {
      if (error.name === "AbortError") throw new Error("阶段执行已终止。");
      throw error;
    } finally {
      const remaining = activeRailRuns.get(stage) - 1;
      if (remaining) activeRailRuns.set(stage, remaining);
      else activeRailRuns.delete(stage);
      renderRail();
    }
  }
  async function runCleaningBatches(options, shouldContinue, onBatch = () => {}) {
    let after = null;
    do {
      const result = await runStage("clean", { ...options, after });
      onBatch(result);
      after = result.next_cursor;
    } while (after && shouldContinue());
  }
  async function runSavedCleaning() {
    if (cleaningRun || state.running || activeRailRuns.size) return;
    const totals = { total: null, processed: 0, passed: 0, rejected: 0, review: 0, skipped: 0, finished: false };
    cleaningRun = totals;
    let modelMissing = false;
    let modelFailures = 0;
    renderRail();
    renderCommandbar();
    try {
      const queue = await pipelineApi("/cleaning/queue");
      totals.total = queue.total;
      renderRail();
      if (totals.total) {
        await runCleaningBatches({ use_cleaner: true, limit: 1 }, () => modelFailures < 3, (result) => {
          totals.processed += result.processed || 0;
          totals.total = result.next_cursor ? Math.max(totals.total, totals.processed + 1) : totals.processed;
          for (const key of ["passed", "rejected", "review", "skipped"]) totals[key] += result.counts?.[key] || 0;
          modelMissing ||= result.tier2 === "pending";
          if (result.counts?.tier2_preserved) modelFailures += 1;
          else if (result.counts?.tier2_processed) modelFailures = 0;
          renderRail();
        });
      }
      totals.finished = true;
      if (!totals.processed) toast("当前没有可清洗的岗位，请检查是否已保存对应求职方向的规则。");
      else {
        const skipped = totals.skipped ? `，跳过已变更岗位 ${totals.skipped} 条` : "";
        const details = `通过 ${totals.passed} 条，淘汰 ${totals.rejected} 条，待核对 ${totals.review} 条${skipped}。`;
        const heading = modelFailures >= 3 && totals.total > totals.processed
          ? `清洗模型连续失败，剩余 ${totals.total - totals.processed} 条未处理。`
          : modelMissing ? "硬规则已执行，AI 初筛需配置招聘清洗模型。" : "规则清洗完成。";
        toast(heading + details, totals.review || totals.skipped ? "warning" : "success");
      }
    } catch (error) {
      const progress = totals.processed ? `（已处理 ${totals.processed} 条）` : "";
      toast(`规则清洗中断${progress}：${error.message}`, "error");
    } finally {
      await refresh({ silent: true });
      cleaningRun = null;
      renderRail();
      renderCommandbar();
    }
  }
  function stageResultMessage(result, label) {
    const processed = result?.processed ?? 0;
    const mode = result?.mode === "llm" ? "模型" : "启发式";
    if (result?.stage === "evaluate") {
      const { screened, deep, parse_failed: failed } = result.counts;
      return `${label}完成：初评 ${screened} 条，深评 ${deep} 条${failed ? `，待重试 ${failed} 条` : ""}。`;
    }
    return `${label}完成：处理 ${processed} 条（${mode}模式）。`;
  }

  /* ---------- 岗位看板 ---------- */
  let purgeMode = false;
  let purgeAll = false;
  const purgeIds = new Map();
  const savingJobs = new Set();
  function purgeSelected(id) { return purgeAll !== purgeIds.has(id); }
  function selectForPurge(job, selected) {
    const id = jobId(job);
    if (selected === purgeAll) purgeIds.delete(id);
    else purgeIds.set(id, { source: job.source, url_key: job.url_key });
  }
  function purgeCount() {
    return purgeAll ? Math.max(0, (tabCounts().all || 0) - purgeIds.size) : purgeIds.size;
  }
  function renderPurgeTools() {
    byId("rpPurgeTools").hidden = !purgeMode;
    if (!purgeMode) return;
    const jobs = state.boardLoading || state.boardError ? [] : filteredJobs();
    const selected = jobs.filter(job => purgeSelected(jobId(job))).length;
    const page = byId("rpPurgePage");
    page.disabled = state.bulkBusy || !jobs.length;
    page.checked = selected > 0 && selected === jobs.length;
    page.indeterminate = selected > 0 && selected < jobs.length;
    const all = byId("rpPurgeAll");
    all.disabled = state.bulkBusy || !tabCounts().all;
    all.textContent = purgeAll ? "取消全选" : "全选全部未保存岗位";
    const count = purgeCount();
    byId("rpPurgeCount").textContent = `已选 ${count} 条`;
    byId("rpPurgeDelete").disabled = state.bulkBusy || !count;
  }
  function syncPurgeCheckboxes() {
    for (const box of byId("rpJobs").querySelectorAll("[data-purge-id]")) {
      box.checked = purgeSelected(box.dataset.purgeId);
      box.disabled = state.bulkBusy;
    }
    renderPurgeTools();
  }
  function renderTabs() {
    const counts = tabCounts();
    for (const button of byId("rpTabs").querySelectorAll("[data-tab]")) {
      const key = button.dataset.tab;
      button.setAttribute("aria-pressed", String(key === state.tab));
      button.querySelector("[data-tab-count]").textContent = counts[key] ? String(counts[key]) : "";
    }
    const filtered = Boolean(state.q.trim() || state.source);
    const total = filtered ? state.boardTotal : state.tab === "saved" ? (counts.saved || 0) : (state.counts?.all ?? state.jobsTotal);
    byId("rpBoardCount").textContent = total || filtered ? `共 ${total} 条` : "";
    const purge = byId("rpPurge");
    purge.disabled = state.bulkBusy || savingJobs.size > 0 || state.tab === "saved" || (!purgeMode && !counts.all);
    purge.setAttribute("aria-expanded", String(purgeMode));
    purge.replaceChildren(icon(purgeMode ? "x" : "trash"), document.createTextNode(purgeMode ? "退出批量删除" : "批量删除"));
    renderPurgeTools();
  }
  function resetPurgeSelection() {
    purgeMode = false;
    purgeAll = false;
    purgeIds.clear();
  }
  async function purgeUnsaved() {
    if (state.bulkBusy || !purgeCount()) return;
    state.bulkBusy = true;
    renderTabs();
    syncPurgeCheckboxes();
    try {
      const result = await pipelineApi("/purge", { all: purgeAll, ids: [...purgeIds.values()] });
      resetPurgeSelection();
      toast(`已删除 ${result.deleted ?? 0} 条未保存岗位${result.kept ? `，${result.kept} 条已保存岗位保留` : ""}。`, "success");
      state.selectedFailed.clear();
      await refresh({ silent: true });
      await loadBoardPage(1);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.bulkBusy = false;
      renderBoard();
    }
  }
  function setTab(tab, { updateUrl = true } = {}) {
    if (!TABS.includes(tab)) tab = "all";
    if (tab === "saved") resetPurgeSelection();
    state.tab = tab;
    state.page = 1;
    state.selectedFailed.clear();
    void loadBoardPage(1);
    if (updateUrl) syncUrl();
    void ensureTabLoaded(tab);
  }
  function renderTabBanner() {
    const root = byId("rpTabBanner");
    root.replaceChildren();
    root.hidden = true;
    const counts = tabCounts();
    const bar = node("div", "", "rp-tabbanner-bar");
    const addButton = (label, cls, handler, iconName) => {
      const button = node("button", label, "rp-btn rp-btn-sm " + cls);
      button.type = "button";
      if (iconName) button.prepend(icon(iconName));
      button.addEventListener("click", handler);
      button.disabled = state.bulkBusy;
      bar.append(button);
      return button;
    };
    if (state.tab === "saved") {
      bar.dataset.tone = "info";
      if (!counts.saved) { bar.hidden = true; return; }
      bar.append(node("p", "保存的岗位跨天保留，卡片显示当前处理状态。取消保存时，仅当天采集的岗位会回到「全部」。"));
    } else if (state.tab === "queued" && counts.queued > 0) {
      const queuedJobs = state.jobs.filter((j) => j.tab === "queued");
      bar.dataset.tone = "accent";
      bar.append(node("p", `${counts.queued} 个岗位已通过审批，进入待投递队列。`));
      addButton(`立即执行投递（${queuedJobs.length}）`, "rp-btn-accent", () => deliverJobs(queuedJobs), "send");
      bar.append(node("p", "投递为本地 dry-run：生成投递包并导出，不连接外部招聘平台。", "rp-banner-note"));
    } else if (state.tab === "approval" && counts.approval > 0) {
      const approvalJobs = state.jobs.filter((j) => j.tab === "approval");
      bar.dataset.tone = "warning";
      bar.append(node("p", `${counts.approval} 个岗位等待人工审批，放行后进入待投递队列。`));
      addButton(`一键放行全部（${approvalJobs.length}）`, "rp-btn-primary", () => bulkApprove(approvalJobs), "check");
    } else if (state.tab === "reeval") {
      bar.dataset.tone = "info";
      bar.append(node("p", counts.reeval
        ? `${counts.reeval} 个岗位处于待重评停机位，不会自动流转。`
        : "待重评队列：人工打回的岗位会停在这里，等待重新评估。"));
      if (counts.reeval) addButton(`重新评估（${counts.reeval}）`, "rp-btn-accent", () => runScreenBatch(), "rotate");
    } else if (state.tab === "failed") {
      bar.dataset.tone = "danger";
      bar.append(node("p", counts.failed ? `${counts.failed} 个岗位执行失败，可批量分诊处理。` : "暂无执行失败的岗位。"));
      if (counts.failed) {
        const tools = node("div", "", "rp-failed-tools");
        const selectAll = node("label");
        const box = node("input");
        box.type = "checkbox";
        box.checked = state.selectedFailed.size > 0 && state.selectedFailed.size === counts.failed;
        box.addEventListener("change", () => {
          state.selectedFailed = box.checked
            ? new Map([...state.jobs, ...state.boardJobs].filter((j) => j.tab === "failed").map(job => [jobId(job), job]))
            : new Map();
          renderTabBanner();
          renderJobs();
        });
        selectAll.append(box, document.createTextNode("全选"));
        tools.append(selectAll);
        const selected = () => [...state.selectedFailed.values()].filter(job => job.tab === "failed");
        const retry = node("button", `批量重试${state.selectedFailed.size ? `（${state.selectedFailed.size}）` : ""}`, "rp-btn rp-btn-sm");
        retry.type = "button";
        retry.disabled = !state.selectedFailed.size || state.bulkBusy;
        retry.addEventListener("click", () => bulkRetry(selected()));
        const abandon = node("button", `批量放弃${state.selectedFailed.size ? `（${state.selectedFailed.size}）` : ""}`, "rp-btn rp-btn-sm rp-btn-danger");
        abandon.type = "button";
        abandon.disabled = !state.selectedFailed.size || state.bulkBusy;
        abandon.addEventListener("click", () => bulkAbandon(selected()));
        tools.append(retry, abandon);
        bar.append(tools);
      }
    } else if (state.tab === "in_progress" && counts.in_progress === 0 && counts.queued > 0) {
      bar.dataset.tone = "info";
      bar.append(node("p", `评估·改写·投递中的岗位已清空，还有 ${counts.queued} 个岗位等待投递。`));
      addButton("查看待投递", "rp-btn-accent", () => setTab("queued"), "arrow-right");
    }
    if (bar.childNodes.length) { root.append(bar); root.hidden = false; }
  }

  function statusBadge(job) {
    const tones = { approval: "warning", queued: "accent", delivered: "success", rejected: "danger", failed: "danger", reeval: "info" };
    const badge = node("span", STAGE_LABELS[job.stage] || job.stage, "rp-status-badge");
    badge.dataset.tone = tones[job.stage] || (IN_PROGRESS.has(job.stage) ? "accent" : "muted");
    return badge;
  }
  function jobTags(job) {
    const tags = node("div", "", "rp-job-tags");
    const add = (iconName, text) => {
      if (!text) return;
      const tag = node("span", "", "rp-job-tag");
      tag.append(icon(iconName), document.createTextNode(text));
      tags.append(tag);
    };
    add("map-pin", job.location);
    add("briefcase", job.experience);
    add("graduation", job.education);
    add("users", job.scale);
    add("clock", job.crawledAt ? fmtTime(job.crawledAt) + " 采集" : "");
    add("clock", job.updatedAt && job.updatedAt !== job.crawledAt ? fmtTime(job.updatedAt) + " 动作" : "");
    add("bookmark", job.saved && job.savedAt ? fmtTime(job.savedAt) + " 保存" : "");
    const track = node("span", job.track === "mass" ? "海投" : "精投", "rp-track-tag");
    track.dataset.track = job.track;
    tags.append(track);
    return tags;
  }
  function materialButtons(job) {
    const wrap = node("div", "", "rp-job-materials");
    const resume = node("button", "简历预览", "rp-material-btn");
    resume.type = "button";
    resume.prepend(icon("file-text"));
    resume.addEventListener("click", () => openMaterials(job, "resume"));
    const greeting = node("button", "欢迎语核验", "rp-material-btn");
    greeting.type = "button";
    greeting.prepend(icon("message"));
    greeting.addEventListener("click", () => openMaterials(job, "greeting"));
    wrap.append(resume, greeting);
    return wrap;
  }
  function actionButton(label, cls, handler, iconName) {
    const button = node("button", label, "rp-btn rp-btn-sm " + cls);
    button.type = "button";
    if (iconName) button.prepend(icon(iconName));
    button.addEventListener("click", handler);
    return button;
  }
  function saveButton(job) {
    const button = actionButton(job.saved ? "取消保存" : "保存",
      "rp-btn-ghost rp-job-save" + (job.saved ? " is-saved" : ""), () => toggleSave(job), "bookmark");
    button.title = job.saved
      ? "取消保存：当天采集的岗位回到「全部」，早前的岗位会移除。"
      : "保存：岗位跨天保留在「已保存」视图，并标注当前阶段。";
    return button;
  }
  function jobActions(job) {
    const actions = node("div", "", "rp-job-actions");
    // 已保存视图按当前阶段提供操作，保存开关始终在首位。
    const tab = job.tab === "saved" ? stageTabOf(job) : job.tab;
    actions.append(saveButton(job), actionButton("定制面板", "rp-btn-ghost", () => openDrawer("rewriting", { job }), "sliders"));
    if (tab === "approval") {
      actions.append(
        actionButton("拒绝", "rp-btn-danger", () => decide(job, "reject"), "x"),
        actionButton("重评", "rp-btn-ghost", () => decide(job, "reeval"), "rotate"),
        actionButton("放行", "rp-btn-success", () => decide(job, "approve"), "check")
      );
    } else if (tab === "queued") {
      actions.append(
        actionButton("终止投递", "rp-btn-ghost", () => abandonDelivery(job), "stop"),
        actionButton("立即投递", "rp-btn-accent", () => deliverJobs([job]), "send")
      );
    } else if (tab === "delivered") {
      actions.append(actionButton("投递详情", "rp-btn-ghost", () => openDrawer("delivering", { job }), "eye"));
    } else if (tab === "reeval") {
      actions.append(actionButton("重新评估", "rp-btn-accent", () => runScreenBatch(), "rotate"));
    } else if (tab === "failed") {
      actions.append(
        actionButton("放弃", "rp-btn-danger", () => abandonJob(job), "trash"),
        actionButton("重试", "rp-btn-accent", () => retryJob(job), "rotate")
      );
    } else if (tab === "rejected" && /^https?:/.test(job.url || "")) {
      actions.append(actionButton("放行并推送", "rp-btn-success", () => releaseJob(job), "check"));
    } else if (tab === "in_progress" && job.hasGreeting) {
      actions.append(actionButton("补发打招呼", "rp-btn-ghost", () => regreet(), "message"));
    }
    return actions;
  }
  function normalJobCard(job) {
    const card = node("article", "", "rp-job");
    const top = node("div", "", "rp-job-top");
    const logo = node("span", sourceLabel(job.source).slice(0, 2), "rp-job-logo");
    logo.dataset.source = job.source;
    const head = node("div", "", "rp-job-head");
    const company = node("div", "", "rp-job-company");
    company.append(node("strong", job.company || "未知公司"), node("span", sourceLabel(job.source), "rp-source-pill"));
    if (job.url && /^https?:/.test(job.url)) {
      const link = node("a", "原帖", "rp-job-link");
      link.href = job.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.append(icon("external"));
      company.append(link);
    }
    const title = node("button", job.title, "rp-job-title");
    title.type = "button";
    title.addEventListener("click", () => openDrawer("rewriting", { job }));
    head.append(company, title);
    top.append(logo, head);
    if (job.grade || job.score != null) {
      const gradeWrap = node("div", "", "rp-job-grade");
      if (job.grade) {
        const badge = node("span", job.grade, "rp-grade");
        badge.dataset.grade = job.grade;
        gradeWrap.append(badge);
      }
      if (job.score != null) gradeWrap.append(node("span", `${job.score} 分`, "rp-job-score"));
      top.append(gradeWrap);
    }
    top.append(node("strong", job.salary || "薪资未获取", "rp-job-salary" + (job.salary ? "" : " is-missing")));
    const bottom = node("div", "", "rp-job-bottom");
    const foot = node("div", "", "rp-job-foot");
    const status = node("span", "", "rp-job-status");
    status.append(statusBadge(job));
    const detail = job.tab === "rejected" ? "" : (job.followStatus || job.reason);
    if (detail) status.append(node("span", detail, "rp-job-status-detail"));
    foot.append(status, materialButtons(job), jobActions(job));
    bottom.append(jobTags(job), foot);
    card.append(top, bottom);
    return card;
  }
  function rejectedJobCard(job) {
    const card = normalJobCard(job);
    card.classList.add("is-rejected");
    card.querySelector(".rp-job-actions")?.remove();
    const reason = node("div", "", "rp-reject-reason");
    reason.append(icon("alert"), node("span", job.reason || "命中清洗规则或人工淘汰，未记录具体原因。"));
    const fold = node("details", "", "rp-jd-fold");
    const summary = node("summary", "查看岗位 JD");
    const body = node("p", job.description || "展开后读取岗位描述…");
    fold.append(summary, body);
    fold.addEventListener("toggle", async () => {
      if (!fold.open || job.description) return;
      body.textContent = "正在读取岗位描述…";
      try {
        const payload = await fetchJobPayload(job);
        job.description = payload?.description || "";
        body.textContent = job.description || "暂无岗位描述，可在原站查看。";
        if (payload?.cleaning_reason && !job.reason) {
          job.reason = payload.cleaning_reason;
          reason.lastChild.textContent = payload.cleaning_reason;
        }
      } catch (_) {
        body.textContent = "岗位描述读取失败，可在原站查看。";
      }
    });
    const actions = node("div", "", "rp-job-actions");
    // 岗位已处淘汰终态：确认淘汰只做本地确认；放行仅对仍有原站链接的平台记录开放。
    actions.append(saveButton(job), actionButton("确认淘汰", "rp-btn-danger", () => toast("已确认淘汰，岗位保留在淘汰视图。"), "x"));
    if (/^https?:/.test(job.url || "")) {
      actions.append(actionButton("放行并推送", "rp-btn-success", () => releaseJob(job), "check"));
    }
    card.querySelector(".rp-job-foot").append(actions);
    card.append(reason, fold);
    return card;
  }
  const PERSISTENT_HINTS = /物料|缺少|缺失|下架|风控|验证码|非法|引擎|未找到|数据不全|简历失配|手动终止|已终止|未知来源/;
  const TRANSIENT_HINTS = /超时|timeout|登录|会话|session|网络|network|浏览器|browser|页面|崩溃|抖动|临时/i;
  function diagnose(job) {
    const kind = job.failureKind || (PERSISTENT_HINTS.test(job.error || "") ? "persistent"
      : TRANSIENT_HINTS.test(job.error || "") ? "transient" : "unknown");
    if (kind === "eval") {
      return { kind: "persistent", label: "评估解析失败", advice: "AI 输出无法解析，评级已置空并拦截投递。重试会先回到待重评，再重新初评。" };
    }
    if (kind === "persistent") {
      return { kind, label: "持久故障", advice: "多与物料缺失、岗位下架或风控有关，重试无法自愈；建议补齐物料或放弃。" };
    }
    if (kind === "transient") {
      return { kind, label: "瞬时故障", advice: "多与网络波动、会话或页面抖动有关，重试通常可以恢复。" };
    }
    return { kind: "unknown", label: "待人工分诊", advice: "缺少明确故障特征，建议查看原帖与阶段记录后再决定重试或放弃。" };
  }
  function failedJobCard(job) {
    const card = normalJobCard(job);
    card.classList.add("is-failed");
    card.querySelector(".rp-job-actions")?.remove();
    const head = node("div", "", "rp-failed-head");
    const box = node("input");
    box.type = "checkbox";
    box.checked = state.selectedFailed.has(jobId(job));
    box.setAttribute("aria-label", "选择 " + job.title);
    box.addEventListener("change", () => {
      if (box.checked) state.selectedFailed.set(jobId(job), job);
      else state.selectedFailed.delete(jobId(job));
      renderTabBanner();
    });
    head.append(box, node("strong", "故障诊断", ""));
    const diagnosis = node("div", "", "rp-diagnosis");
    diagnosis.hidden = true;
    const info = diagnose(job);
    const kind = node("span", info.label + (job.failureKind ? "" : "（启发式）"), "rp-diagnosis-kind");
    kind.dataset.kind = info.kind;
    diagnosis.append(
      node("strong", [job.followStatus || "执行失败", job.attempts != null ? `已尝试 ${job.attempts} 次` : "",
        job.retryable === false ? "自动重试已用尽" : ""].filter(Boolean).join(" · ")),
      node("p", job.error || "未记录失败详情。"),
      kind, node("p", info.advice)
    );
    const actions = node("div", "", "rp-job-actions");
    const diagBtn = actionButton("AI 诊断", "rp-btn-ghost", () => { diagnosis.hidden = !diagnosis.hidden; }, "sparkles");
    actions.append(
      saveButton(job),
      diagBtn,
      actionButton("放弃", "rp-btn-danger", () => abandonJob(job), "trash"),
      actionButton("重试", "rp-btn-accent", () => retryJob(job), "rotate")
    );
    card.querySelector(".rp-job-foot").append(actions);
    card.insertBefore(head, card.firstChild);
    card.append(diagnosis);
    return card;
  }
  // 后台轮询保留原有卡片，避免打断键盘焦点和页面的滚动锚点。
  const renderedJobs = new Map();
  function renderJobPlaceholder(root, placeholder) {
    renderedJobs.clear();
    if (!root.firstElementChild?.isEqualNode(placeholder)) root.replaceChildren(placeholder);
  }
  function renderJobs() {
    const root = byId("rpJobs");
    const list = filteredJobs();
    if (!state.apiReady && state.loading) return; // 骨架保留
    renderJobPager();
    renderPurgeTools();
    if (state.boardLoading || state.boardError) {
      const empty = node("div", "", "rp-view-empty");
      empty.append(node("strong", state.boardError || "正在读取岗位…"));
      if (state.boardError) {
        empty.append(actionButton("重试", "rp-btn-ghost", () => loadBoardPage(state.page), "refresh"));
      }
      renderJobPlaceholder(root, empty);
      return;
    }
    if (!list.length) {
      const empty = node("div", "", "rp-view-empty");
      empty.append(tile("inbox", "accent"));
      if (state.tab === "saved" && !state.counts.saved) {
        empty.append(node("strong", "暂无已保存岗位"), node("p", "在岗位卡片上点「保存」，之后可在这里继续跟进。"));
      } else if (state.tab !== "saved" && !(state.counts.all ?? state.jobsTotal)) {
        empty.append(node("strong", "当日暂无岗位"), node("p", "点击「获取新岗位」开始实时采集。"));
        if (state.counts.saved) {
          empty.append(actionButton(`查看已保存（${state.counts.saved}）`, "rp-btn-ghost", () => setTab("saved"), "bookmark"));
        }
      } else {
        const filtered = Boolean(state.q.trim() || state.source);
        empty.append(node("strong", filtered ? "没有匹配的岗位" : "当前视图暂无岗位"),
          node("p", filtered ? "试试其他关键词或平台。" : "切换其他状态视图，或启动流水线推进岗位。"));
      }
      renderJobPlaceholder(root, empty);
      return;
    }
    if (!renderedJobs.size) root.replaceChildren();
    const visible = new Set(list.map(jobId));
    for (const [id, entry] of renderedJobs) {
      if (!visible.has(id)) {
        entry.card.remove();
        renderedJobs.delete(id);
      }
    }
    list.forEach((job, index) => {
      const id = jobId(job);
      const previous = renderedJobs.get(id);
      // JD 正文由折叠区按需加载；加载完成后已经直接更新了卡片。
      const signature = JSON.stringify([{ ...job, description: undefined }, purgeMode]);
      let card = previous?.card;
      if (!previous || previous.job !== job || previous.signature !== signature) {
        card = renderJobCard(job);
        if (previous) {
          const fold = card.querySelector(".rp-jd-fold");
          if (fold && previous.card.querySelector(".rp-jd-fold[open]")) fold.open = true;
          const diagnosis = card.querySelector(".rp-diagnosis");
          if (diagnosis && previous.card.querySelector(".rp-diagnosis:not([hidden])")) diagnosis.hidden = false;
          previous.card.replaceWith(card);
        }
        renderedJobs.set(id, { job, signature, card });
      }
      const anchor = root.children[index];
      if (anchor !== card) root.insertBefore(card, anchor || null);
      card.querySelector(".rp-job-save").disabled = savingJobs.has(id) || state.bulkBusy;
      const failed = card.querySelector(".rp-failed-head input");
      if (failed) failed.checked = state.selectedFailed.has(id);
    });
    if (purgeMode) syncPurgeCheckboxes();
  }
  function renderJobCard(job) {
    const card = job.tab === "rejected" ? rejectedJobCard(job) : job.tab === "failed" ? failedJobCard(job) : normalJobCard(job);
    if (purgeMode && !job.saved) {
      const box = node("input", "", "rp-purge-checkbox");
      box.type = "checkbox";
      box.setAttribute("aria-label", `选择 ${job.title}`);
      box.dataset.purgeId = jobId(job);
      box.addEventListener("change", () => {
        selectForPurge(job, box.checked);
        renderPurgeTools();
      });
      card.querySelector(".rp-job-top").prepend(box);
    }
    return card;
  }
  function boardPageCount() {
    return Math.max(1, Math.ceil(state.boardTotal / BOARD_PAGE_SIZE));
  }
  function renderJobPager() {
    const pages = boardPageCount();
    const disabled = state.boardLoading || Boolean(state.boardError);
    byId("rpJobPager").hidden = pages <= 1;
    byId("rpJobPrev").disabled = disabled || state.page <= 1;
    byId("rpJobNext").disabled = disabled || state.page >= pages;
    byId("rpJobPageStatus").textContent = state.boardLoading
      ? "正在读取…"
      : `第 ${state.page} / ${pages} 页 · ${state.boardTotal} 条`;
    const input = byId("rpJobPageInput");
    input.max = String(pages);
    input.disabled = disabled;
    if (document.activeElement !== input) input.value = String(state.page);
    byId("rpJobPageGo").disabled = disabled;
  }
  function renderBoard() {
    renderTabs();
    renderTabBanner();
    renderJobs();
  }

  /* ---------- 写操作：乐观更新 + toast + 回滚 ---------- */
  async function mutateJob(job, patch, request, message) {
    const before = { stage: job.stage, followStatus: job.followStatus, tab: job.tab, reason: job.reason, grade: job.grade, score: job.score };
    const fromTab = job.tab;
    Object.assign(job, patch);
    job.tab = patch.tab || tabOf(job);
    adjustCounts(fromTab, job.tab);
    renderBoard();
    try {
      const result = await request();
      toast(message, "success");
      void refresh({ silent: true });
      return result;
    } catch (error) {
      const optimisticTab = job.tab;
      Object.assign(job, before);
      adjustCounts(optimisticTab, fromTab);
      renderBoard();
      toast(error.message, "error");
      throw error;
    }
  }
  function decide(job, decision) {
    const patches = {
      approve: { stage: "queued", followStatus: "待投递" },
      reject: { stage: "rejected", followStatus: "已拒绝" },
      reeval: { stage: "reeval", followStatus: "待重评", grade: "", score: null }
    };
    const messages = { approve: "已放行，进入待投递队列。", reject: "已标记淘汰。", reeval: "已打回待重评。" };
    return mutateJob(job, patches[decision], () =>
      pipelineApi("/approve", { source: job.source, url_key: job.url_key, decision }), messages[decision])
      .catch(() => {});
  }
  async function toggleSave(job) {
    const id = jobId(job);
    if (savingJobs.has(id) || state.bulkBusy) return;
    const saved = !job.saved;
    savingJobs.add(id);
    resetPurgeSelection();
    renderTabs();
    renderJobs();
    try {
      const result = await pipelineApi("/save", { source: job.source, url_key: job.url_key, saved });
      toast(saved ? "已移至「已保存」。" : result.expired ? "已取消保存并移除早前采集的岗位。" : "已取消保存。", "success");
      await loadBoardPage(state.page, { quiet: true });
      void refresh({ silent: true });
    } catch (error) {
      toast(error.message, "error");
    } finally {
      savingJobs.delete(id);
      renderBoard();
    }
  }
  function deliverJobs(jobs) {
    if (!jobs.length || state.bulkBusy) return Promise.resolve();
    state.bulkBusy = true;
    renderTabBanner();
    const ids = jobs.map((job) => ({ source: job.source, url_key: job.url_key }));
    const before = jobs.map((job) => ({ job, stage: job.stage, tab: job.tab, followStatus: job.followStatus }));
    for (const job of jobs) {
      const from = job.tab;
      job.stage = "delivered"; job.tab = job.saved ? "saved" : "delivered"; job.followStatus = "已投递";
      adjustCounts(from, job.tab);
    }
    renderBoard();
    return pipelineApi("/deliver_dry", { ids })
      .then((result) => {
        const delivered = result?.delivered ?? jobs.length;
        const failed = result?.failed ?? 0;
        toast(failed
          ? `dry-run 投递完成：${delivered} 成功，${failed} 失败（已入失败台账）。`
          : `dry-run 投递完成：${delivered} 个岗位已生成投递包。`, failed ? "warning" : "success");
        void refresh({ silent: true });
      })
      .catch((error) => {
        for (const item of before) {
          const optimistic = item.job.tab;
          item.job.stage = item.stage; item.job.tab = item.tab; item.job.followStatus = item.followStatus;
          adjustCounts(optimistic, item.tab);
        }
        renderBoard();
        toast(error.message, "error");
      })
      .finally(() => { state.bulkBusy = false; renderTabBanner(); });
  }
  function abandonDelivery(job) {
    return mutateJob(job, { stage: "rejected", followStatus: "已拒绝" }, () =>
      pipelineApi("/abandon", { source: job.source, url_key: job.url_key }),
      "已终止投递，岗位转入淘汰存档。").catch(() => {});
  }
  function retryJob(job) {
    const toReeval = job.failureKind === "eval";
    return mutateJob(job, toReeval
      ? { stage: "reeval", followStatus: "待重评", error: "" }
      : { stage: "queued", followStatus: "待投递", error: "" }, () =>
      pipelineApi("/retry", { source: job.source, url_key: job.url_key }),
      toReeval ? "已打回待重评，将重新初评。" : "已重试，岗位回到待投递队列。").catch(() => {});
  }
  function abandonJob(job) {
    return mutateJob(job, { stage: "rejected", followStatus: "已拒绝" }, () =>
      pipelineApi("/abandon", { source: job.source, url_key: job.url_key }),
      "已放弃该岗位。").catch(() => {});
  }
  function regreet() {
    toast("正在触发打招呼语阶段（批量，覆盖待生成岗位）…");
    return runStage("greet")
      .then((result) => { toast(stageResultMessage(result, "打招呼语"), "success"); void refresh({ silent: true }); })
      .catch((error) => toast(error.message, "error"));
  }
  function runScreenBatch() {
    if (state.bulkBusy) return Promise.resolve();
    state.bulkBusy = true;
    renderTabBanner();
    toast("正在运行 AI 评估…");
    return runStage("evaluate")
      .then((result) => { toast(stageResultMessage(result, "AI 评估"), "success"); void refresh({ silent: true }); })
      .catch((error) => toast(error.message, "error"))
      .finally(() => { state.bulkBusy = false; renderTabBanner(); });
  }
  function releaseJob(job) {
    // 放行清洗淘汰：复用现有 /cleaning/release（仅平台来源记录支持）。
    return api("/cleaning/release", { source: job.source, url: job.url, profile: job.profile || "general" })
      .then(() => { toast("已放行清洗淘汰结果，岗位将重新参与流转。", "success"); void refresh({ silent: true }); })
      .catch((error) => { toast(error.message, "error"); });
  }
  async function bulkApprove(jobs) {
    if (!jobs.length || state.bulkBusy) return;
    state.bulkBusy = true;
    renderTabBanner();
    let done = 0;
    for (const job of jobs) {
      try {
        await pipelineApi("/approve", { source: job.source, url_key: job.url_key, decision: "approve" });
        job.stage = "queued"; job.tab = "queued"; job.followStatus = "待投递";
        adjustCounts("approval", "queued");
        done += 1;
        renderBoard();
      } catch (error) {
        toast(`放行中断：${error.message}`, "error");
        break;
      }
    }
    state.bulkBusy = false;
    if (done) toast(`已放行 ${done} 个岗位。`, "success");
    void refresh({ silent: true });
  }
  async function bulkRetry(jobs) {
    if (!jobs.length || state.bulkBusy) return;
    state.bulkBusy = true;
    renderTabBanner();
    let done = 0;
    for (const job of jobs) {
      const toReeval = job.failureKind === "eval";
      try {
        await pipelineApi("/retry", { source: job.source, url_key: job.url_key });
        job.stage = toReeval ? "reeval" : "queued";
        job.tab = job.stage;
        job.followStatus = toReeval ? "待重评" : "待投递";
        adjustCounts("failed", job.tab);
        done += 1;
      } catch (error) {
        toast(`批量重试中断：${error.message}`, "error");
        break;
      }
    }
    state.bulkBusy = false;
    state.selectedFailed.clear();
    renderBoard();
    if (done) toast(`已重试 ${done} 个岗位。`, "success");
    void refresh({ silent: true });
  }
  async function bulkAbandon(jobs) {
    if (!jobs.length || state.bulkBusy) return;
    state.bulkBusy = true;
    renderTabBanner();
    let done = 0;
    for (const job of jobs) {
      try {
        await pipelineApi("/abandon", { source: job.source, url_key: job.url_key });
        job.stage = "rejected"; job.tab = "rejected"; job.followStatus = "已拒绝";
        adjustCounts("failed", "rejected");
        done += 1;
      } catch (error) {
        toast(`批量放弃中断：${error.message}`, "error");
        break;
      }
    }
    state.bulkBusy = false;
    state.selectedFailed.clear();
    renderBoard();
    if (done) toast(`已放弃 ${done} 个岗位。`, "success");
    void refresh({ silent: true });
  }
  async function exportDeliveryCsv() {
    const base = pipelineBase || PIPELINE_BASES[0];
    const response = await rawRequest(base + "/deliver_dry", { format: "csv" }, "POST");
    if (!response.ok) {
      let message = `导出失败（${response.status}）。`;
      try { message = (await response.json()).message || message; } catch (_) { /* CSV 或空响应 */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = node("a");
    link.href = url;
    link.download = "delivery-packages.csv";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  /* ---------- 数据加载与轮询 ---------- */
  const recentBoardPages = new Map();
  let boardController = null;
  let boardViewKey = "";
  let jobsLoading = null;

  function showBoardPage(data, page, key) {
    const known = new Map([...state.jobs, ...state.boardJobs].map(job => [jobId(job), job]));
    state.boardJobs = (data.items || []).map(row => {
      const job = normalizeJob(row);
      const current = known.get(jobId(job));
      if (!current) return job;
      if (!job.description && current.crawledAt === job.crawledAt) job.description = current.description;
      return Object.assign(current, job);
    });
    if (data.counts) state.counts = { ...data.counts };
    state.boardTotal = Number(data.total) || 0;
    state.page = page;
    state.boardError = "";
    boardViewKey = key;
  }

  async function loadBoardPage(page, { quiet = false, scroll = false } = {}) {
    if (quiet && boardController) return;
    boardController?.abort();
    const controller = new AbortController();
    boardController = controller;
    const token = ++state.boardRequest;
    const params = new URLSearchParams({ tab: state.tab, limit: String(BOARD_PAGE_SIZE) });
    if (state.q.trim()) params.set("q", state.q.trim());
    if (state.source) params.set("source", state.source);
    const pageKey = (number) => `${params}#${number}`;
    const key = pageKey(page);
    state.page = page;
    if (!quiet) {
      state.boardError = "";
      const cached = recentBoardPages.get(key);
      if (boardViewKey !== key && cached && Date.now() - cached.at < 30_000) showBoardPage(cached.data, page, key);
      state.boardLoading = boardViewKey !== key;
      renderBoard();
    }
    try {
      let data;
      while (true) {
        params.set("offset", String((page - 1) * BOARD_PAGE_SIZE));
        data = await pipelineApi("/jobs?" + params, undefined, "GET", controller.signal);
        if (token !== state.boardRequest) return;
        const last = Math.max(1, Math.ceil(data.total / BOARD_PAGE_SIZE));
        if (page <= last) break;
        page = last;
      }
      params.delete("offset");
      const loadedKey = pageKey(page);
      showBoardPage(data, page, loadedKey);
      recentBoardPages.delete(loadedKey);
      recentBoardPages.set(loadedKey, { data, at: Date.now() });
      if (recentBoardPages.size > 12) recentBoardPages.delete(recentBoardPages.keys().next().value);
      hideBoot();
      syncUrl();
      return true;
    } catch (error) {
      if (token !== state.boardRequest || error.name === "AbortError") return;
      if (boardViewKey !== key) state.boardError = error.message || "岗位读取失败。";
      else if (!quiet) toast("岗位列表暂时无法更新，保留上次读取的结果。", "warning");
    } finally {
      if (token === state.boardRequest) {
        boardController = null;
        state.boardLoading = false;
        renderBoard();
        if (scroll && !state.boardError) document.querySelector(".rp-board-card").scrollIntoView({ behavior: "instant" });
      }
    }
  }

  function refreshJobChoices() {
    if (!jobsLoading) {
      jobsLoading = loadJobs()
        .then(() => ensureTabLoaded(state.tab))
        .catch(() => {})
        .finally(() => { jobsLoading = null; renderBoard(); });
    }
    return jobsLoading;
  }
  async function loadJobs() {
    const first = await pipelineApi(`/jobs?tab=all&limit=${PAGE_SIZE}&offset=0`);
    const items = (first.items || []).map(normalizeJob);
    const total = Number(first.total ?? items.length) || items.length;
    if (!boardViewKey && first.counts) state.counts = { ...first.counts };
    let offset = items.length;
    while (offset < Math.min(total, MAX_JOBS)) {
      const next = await pipelineApi(`/jobs?tab=all&limit=${PAGE_SIZE}&offset=${offset}`);
      const rows = (next.items || []).map(normalizeJob);
      if (!rows.length) break;
      items.push(...rows);
      offset += rows.length;
    }
    // 已保存岗位跨天保留：并入本地状态，供各面板按阶段选岗（不计入当日看板）。
    const savedWant = Math.min(Number(first.counts?.saved) || 0, TAB_FETCH_CAP);
    let savedOffset = 0;
    while (savedOffset < savedWant) {
      const next = await pipelineApi(`/jobs?tab=saved&limit=${PAGE_SIZE}&offset=${savedOffset}`);
      const rows = (next.items || []).map(normalizeJob);
      if (!rows.length) break;
      items.push(...rows);
      savedOffset += rows.length;
    }
    const boardJobs = new Map(state.boardJobs.map(job => [jobId(job), job]));
    state.jobs = items.map(job => boardJobs.get(jobId(job)) || job);
    state.jobsTotal = total;
  }
  async function ensureTabLoaded(tab) {
    // Bulk actions need their full candidate list. The board itself is paged by the server.
    if (!["approval", "queued", "failed"].includes(tab)) return;
    const want = state.counts?.[tab] || 0;
    const have = state.jobs.filter((job) => job.tab === tab).length;
    if (!want || have >= want) return;
    const token = ++state.tabLoadToken;
    const merged = [];
    let offset = 0;
    while (offset < Math.min(want, TAB_FETCH_CAP)) {
      let data;
      try { data = await pipelineApi(`/jobs?tab=${tab}&limit=${PAGE_SIZE}&offset=${offset}`); }
      catch (_) { return; }
      if (token !== state.tabLoadToken) return;
      const rows = (data.items || []).map(normalizeJob);
      if (!rows.length) break;
      merged.push(...rows);
      offset += rows.length;
    }
    if (token !== state.tabLoadToken || !merged.length) return;
    const byIdentity = new Map(state.jobs.map((job) => [jobId(job), job]));
    const boardJobs = new Map(state.boardJobs.map(job => [jobId(job), job]));
    for (const job of merged) byIdentity.set(jobId(job), boardJobs.get(jobId(job)) || job);
    state.jobs = [...byIdentity.values()];
    renderBoard();
  }
  function showBoot(message) {
    byId("rpBoot").hidden = false;
    byId("rpBootText").textContent = message ||
      "流水线服务尚未就绪。后端接口上线后，这里会显示转化漏斗、执行轨道与岗位看板。";
    document.querySelector(".rp-stack").hidden = true;
    byId("rpBlockBanner").hidden = true;
  }
  function hideBoot() {
    byId("rpBoot").hidden = true;
    document.querySelector(".rp-stack").hidden = false;
  }
  async function refresh({ silent = false, poll = false } = {}) {
    if (state.refreshing) return;
    state.refreshing = true;
    const refreshBtn = byId("rpRailRefresh");
    refreshBtn.classList.add("rp-spin");
    refreshBtn.disabled = true;
    const results = await Promise.allSettled([
      pipelineApi("/funnel"),
      pipelineApi("/rail"),
      loadBoardPage(state.page, { quiet: true })
    ]);
    const [funnel, rail, board] = results;
    let okCount = 0;
    if (funnel.status === "fulfilled" && funnel.value) { state.funnel = funnel.value; okCount += 1; }
    if (rail.status === "fulfilled" && rail.value) { state.rail = rail.value; okCount += 1; }
    if (board.status === "fulfilled" && board.value) okCount += 1;
    state.refreshing = false;
    refreshBtn.classList.remove("rp-spin");
    refreshBtn.disabled = false;
    if (okCount === 0) {
      state.failCount += 1;
      const error = funnel.reason || rail.reason;
      if (!state.apiReady) {
        state.loading = false;
        renderCommandbar();
        showBoot(error?.status === 404
          ? "流水线接口尚未上线（404）。后端部署完成后点击重试，即可加载漏斗与看板。"
          : `暂时连不上流水线服务：${error?.message || "网络异常"}。`);
      } else if (!state.stale) {
        state.stale = true;
        renderCommandbar();
        toast("流水线连接中断，正在自动重试。", "warning");
      }
      return;
    }
    state.failCount = 0;
    state.stale = false;
    state.apiReady = true;
    state.loading = false;
    payloadCache.clear();
    hideBoot();
    renderFunnel();
    renderRail();
    renderBoard();
    renderCommandbar();
    if (!silent && !(state.counts.all || state.counts.saved)) toast("流水线已就绪，先导入岗位再启动本轮。");
    if (!poll) await refreshJobChoices();
    else void ensureTabLoaded(state.tab);
  }
  let pollTimer = 0;
  function schedulePoll() {
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(async () => {
      if (!document.hidden) await refresh({ silent: true, poll: true });
      schedulePoll();
    }, POLL_MS);
  }

  /* ---------- 抽屉框架 ---------- */
  const drawers = new Map();
  const jobChoiceDrawers = new Set(["evaluating", "rewriting", "greeting", "review", "delivering"]);
  let lastFocus = null;
  function registerDrawer(key, definition) { drawers.set(key, definition); }
  function drawerToken() { return state.drawerSeq; }
  function setDrawerBusy(value) { state.drawerBusy = Boolean(value); }
  function openDrawer(key, ctx = null) {
    const definition = drawers.get(key);
    if (!definition) { toast("该配置面板尚未注册。", "warning"); return; }
    state.drawer = key;
    state.drawerCtx = ctx;
    state.drawerSeq += 1;
    lastFocus = document.activeElement;
    const root = byId("rpDrawerRoot");
    byId("rpDrawerTitle").textContent = definition.title;
    const iconSlot = byId("rpDrawerIcon");
    iconSlot.dataset.tone = definition.tone || "accent";
    iconSlot.replaceChildren(icon(definition.icon || "sliders"));
    const body = byId("rpDrawerBody");
    body.replaceChildren();
    body.scrollTop = 0;
    root.hidden = false;
    document.body.classList.add("rp-lock");
    requestAnimationFrame(() => root.classList.add("is-open"));
    syncUrl();
    const render = () => {
      try { definition.render(body, ctx || {}); }
      catch (error) { body.replaceChildren(node("p", "面板渲染失败：" + error.message, "rp-feedback")); }
    };
    if (jobChoiceDrawers.has(key) && !state.jobs.length && (state.counts.all || state.counts.saved)) {
      const token = drawerToken();
      body.append(node("p", "正在读取岗位…", "rp-feedback"));
      void refreshJobChoices().then(() => {
        if (drawerToken() !== token) return;
        body.replaceChildren();
        render();
      });
    } else render();
    byId("rpDrawerClose").focus();
  }
  function closeDrawer({ force = false } = {}) {
    if (state.drawerBusy && !force) { toast("正在保存，请稍候再关闭。", "warning"); return; }
    const root = byId("rpDrawerRoot");
    if (root.hidden) return;
    state.drawer = null;
    state.drawerCtx = null;
    state.drawerSeq += 1;
    state.drawerBusy = false;
    root.classList.remove("is-open");
    document.body.classList.remove("rp-lock");
    window.setTimeout(() => {
      if (state.drawer) return; // 关闭动画期间又重新打开
      root.hidden = true;
      byId("rpDrawerBody").replaceChildren();
    }, reduceMotion ? 0 : 260);
    syncUrl();
    if (lastFocus?.isConnected) lastFocus.focus();
  }

  /* ---------- 物料预览弹窗 ---------- */
  let materialsRenderer = null;
  function registerMaterialsRenderer(fn) { materialsRenderer = fn; }
  const payloadCache = new Map();
  async function fetchJobPayload(job) {
    const payload = await pipelineApi(`/job?source=${encodeURIComponent(job.source)}&url_key=${encodeURIComponent(job.url_key)}`);
    payloadCache.set(jobId(job), payload);
    return payload;
  }
  function openMaterials(job, tab = "resume") {
    state.modalJob = job;
    state.modalTab = tab;
    const root = byId("rpModalRoot");
    byId("rpModalTitle").textContent = "物料预览 · " + job.title;
    for (const button of byId("rpModalTabs").querySelectorAll("[data-material]")) {
      button.setAttribute("aria-pressed", String(button.dataset.material === tab));
    }
    root.hidden = false;
    document.body.classList.add("rp-lock");
    requestAnimationFrame(() => root.classList.add("is-open"));
    renderMaterials();
    byId("rpModalClose").focus();
  }
  function closeMaterials() {
    const root = byId("rpModalRoot");
    if (root.hidden) return;
    state.modalJob = null;
    root.classList.remove("is-open");
    if (byId("rpDrawerRoot").hidden) document.body.classList.remove("rp-lock");
    window.setTimeout(() => {
      if (state.modalJob) return;
      root.hidden = true;
      byId("rpModalBody").replaceChildren();
    }, reduceMotion ? 0 : 240);
  }
  async function renderMaterials() {
    const body = byId("rpModalBody");
    const job = state.modalJob;
    if (!job) return;
    const token = jobId(job) + "|" + state.modalTab + "|" + Date.now();
    body.dataset.token = token;
    body.replaceChildren(node("p", "正在读取物料…", "rp-modal-meta"));
    let payload = payloadCache.get(jobId(job)) || null;
    try {
      if (!payload) payload = await fetchJobPayload(job);
    } catch (_) { payload = null; }
    if (body.dataset.token !== token || !state.modalJob) return;
    body.replaceChildren();
    if (materialsRenderer) materialsRenderer(body, job, payload, state.modalTab);
    else body.append(node("p", "物料渲染器未加载。", "rp-modal-meta"));
  }

  /* ---------- 文本渲染（markdown-lite，安全构建 DOM） ---------- */
  function payloadText(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "object") {
      for (const key of ["text", "markdown", "content", "resume", "greeting", "message", "body"]) {
        if (typeof value[key] === "string" && value[key].trim()) return value[key];
      }
      if (Array.isArray(value)) return value.map(payloadText).filter(Boolean).join("\n");
      return Object.entries(value).map(([key, item]) => `${key}：${payloadText(item)}`).join("\n");
    }
    return String(value);
  }
  function appendInline(parent, text) {
    const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
    for (const part of parts) {
      if (!part) continue;
      if (part.startsWith("**") && part.endsWith("**")) parent.append(node("strong", part.slice(2, -2)));
      else parent.append(document.createTextNode(part));
    }
  }
  function renderDoc(el, text) {
    const lines = String(text || "").split(/\r?\n/);
    let list = null;
    let paragraph = [];
    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = node("p");
      appendInline(p, paragraph.join(" "));
      el.append(p);
      paragraph = [];
    };
    const flushList = () => { if (list) { el.append(list); list = null; } };
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) { flushParagraph(); flushList(); continue; }
      const heading = trimmed.match(/^#{1,4}\s+(.*)$/);
      if (heading) {
        flushParagraph(); flushList();
        const h = node("h5");
        appendInline(h, heading[1]);
        el.append(h);
        continue;
      }
      const bullet = trimmed.match(/^[-*·]\s+(.*)$/);
      if (bullet) {
        flushParagraph();
        list ||= node("ul");
        const li = node("li");
        appendInline(li, bullet[1]);
        list.append(li);
        continue;
      }
      flushList();
      paragraph.push(trimmed);
    }
    flushParagraph(); flushList();
    if (!el.childNodes.length) el.append(node("p", "（暂无内容）", "rp-doc-empty"));
  }

  /* ---------- URL 深链 ---------- */
  function syncUrl() {
    const url = new URL(window.location.href);
    if (state.tab && state.tab !== "all") url.searchParams.set("tab", state.tab);
    else url.searchParams.delete("tab");
    if (state.q.trim()) url.searchParams.set("q", state.q.trim());
    else url.searchParams.delete("q");
    if (state.source) url.searchParams.set("source", state.source);
    else url.searchParams.delete("source");
    if (state.page > 1) url.searchParams.set("page", state.page);
    else url.searchParams.delete("page");
    if (state.drawer) url.searchParams.set("drawer", state.drawer);
    else url.searchParams.delete("drawer");
    window.history.replaceState(null, "", url);
  }

  /* ---------- 事件绑定与启动 ---------- */
  function bindEvents() {
    byId("rpMainAction").addEventListener("click", () => {
      const actionState = byId("rpMainAction").dataset.state;
      if (actionState === "running") return stopPipeline();
      if (actionState === "blocked") {
        const first = warningsList()[0];
        if (first) openDrawer(first);
        return;
      }
      if (actionState === "ready") {
        state.armed = true;
        renderCommandbar();
        window.clearTimeout(state.armTimer);
        state.armTimer = window.setTimeout(disarm, 4000);
        return;
      }
      if (actionState === "armed") {
        window.clearTimeout(state.armTimer);
        void runPipeline();
      }
    });
    byId("rpRailRefresh").addEventListener("click", () => refresh());
    byId("rpCollectJobs").addEventListener("click", () => openDrawer("scraping"));
    byId("rpPurge").addEventListener("click", () => {
      if (state.bulkBusy) return;
      if (purgeMode) resetPurgeSelection();
      else purgeMode = true;
      renderBoard();
    });
    byId("rpPurgePage").addEventListener("change", (event) => {
      for (const job of filteredJobs()) selectForPurge(job, event.target.checked);
      syncPurgeCheckboxes();
    });
    byId("rpPurgeAll").addEventListener("click", () => {
      purgeAll = !purgeAll;
      purgeIds.clear();
      syncPurgeCheckboxes();
    });
    const purgeConfirm = byId("rpPurgeConfirm");
    byId("rpPurgeDelete").addEventListener("click", () => {
      const count = purgeCount();
      if (state.bulkBusy || !count) return;
      byId("rpPurgeMessage").textContent = purgeAll && !purgeIds.size
        ? `将删除全部未保存岗位（当前 ${count} 条）。已保存岗位会保留。`
        : `将删除所选的 ${count} 条未保存岗位。`;
      purgeConfirm.returnValue = "";
      purgeConfirm.showModal();
    });
    purgeConfirm.addEventListener("close", () => {
      if (purgeConfirm.returnValue === "delete") void purgeUnsaved();
    });
    byId("rpBootRetry").addEventListener("click", () => {
      byId("rpBootText").textContent = "正在重新连接流水线服务…";
      void refresh();
    });
    byId("rpBlockBannerOpen").addEventListener("click", () => openDrawer("evaluating"));
    byId("rpTabs").addEventListener("click", (event) => {
      const button = event.target.closest("[data-tab]");
      if (button) setTab(button.dataset.tab);
    });
    let searchTimer = 0;
    const applyBoardFilters = () => {
      window.clearTimeout(searchTimer);
      state.q = byId("rpSearch").value;
      state.source = byId("rpSourceFilter").value;
      void loadBoardPage(1);
    };
    byId("rpSearch").addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(applyBoardFilters, 300);
    });
    byId("rpSourceFilter").addEventListener("change", applyBoardFilters);
    const goToPage = page => {
      if (page >= 1 && page <= boardPageCount() && page !== state.page) void loadBoardPage(page, { scroll: true });
    };
    byId("rpJobPrev").addEventListener("click", () => goToPage(state.page - 1));
    byId("rpJobNext").addEventListener("click", () => goToPage(state.page + 1));
    byId("rpJobPageJump").addEventListener("submit", event => {
      event.preventDefault();
      goToPage(Number(byId("rpJobPageInput").value));
    });
    byId("rpDrawerClose").addEventListener("click", () => closeDrawer());
    document.querySelector("[data-rp-drawer-close]").addEventListener("click", () => closeDrawer());
    byId("rpModalClose").addEventListener("click", closeMaterials);
    document.querySelector("[data-rp-modal-close]").addEventListener("click", closeMaterials);
    byId("rpModalTabs").addEventListener("click", (event) => {
      const button = event.target.closest("[data-material]");
      if (!button) return;
      state.modalTab = button.dataset.material;
      for (const item of byId("rpModalTabs").querySelectorAll("[data-material]")) {
        item.setAttribute("aria-pressed", String(item === button));
      }
      renderMaterials();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!byId("rpModalRoot").hidden) { event.preventDefault(); closeMaterials(); return; }
      if (!byId("rpDrawerRoot").hidden) { event.preventDefault(); closeDrawer(); }
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.apiReady) void refresh({ silent: true });
    });
    document.addEventListener("click", (event) => {
      const slot = byId("rpResumePill");
      if (slot && !slot.contains(event.target)) {
        const pop = slot.querySelector(".rp-resume-pop");
        if (pop) pop.hidden = true;
        slot.querySelector(".rp-resume-pill")?.setAttribute("aria-expanded", "false");
      }
    });
    // 看板滚动定位需要避开主导航。
    const topbar = document.querySelector(".recruitment-topbar");
    const measure = () => {
      if (topbar) document.documentElement.style.setProperty("--rp-topbar-h", topbar.offsetHeight + "px");
    };
    measure();
    window.addEventListener("resize", measure);
  }

  function boot() {
    bindEvents();
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    if (tab && TABS.includes(tab)) state.tab = tab;
    const q = (params.get("q") || "").trim().slice(0, 120);
    if (q) { state.q = q; byId("rpSearch").value = q; }
    const platform = byId("rpSourceFilter");
    const sources = { ...meta.sources, ...SOURCE_EXTRA };
    for (const [key, label] of Object.entries(sources)) platform.add(new Option(label, key));
    const source = params.get("source");
    if (Object.hasOwn(sources, source)) state.source = platform.value = source;
    const page = Number(params.get("page"));
    if (Number.isSafeInteger(page) && page > 1 && page <= Math.floor(Number.MAX_SAFE_INTEGER / BOARD_PAGE_SIZE)) state.page = page;
    renderTabs();
    renderCommandbar();
    const drawer = params.get("drawer") === "deep_eval" ? "evaluating" : params.get("drawer");
    let bootDrawerOpened = false;
    if (drawer && drawers.has(drawer)) { openDrawer(drawer); bootDrawerOpened = true; }
    void refresh({ silent: true }).then(() => {
      if (!bootDrawerOpened && drawer && drawers.has(drawer) && !state.drawer) openDrawer(drawer);
    });
    schedulePoll();
  }

  /* ---------- 对外接口（recruitment-pipeline.js 使用） ---------- */
  window.RP = {
    meta, state, ICONS,
    node, icon, tile, toast,
    api, pipelineApi,
    refresh, runStage, stageResultMessage,
    registerDrawer, openDrawer, closeDrawer, setDrawerBusy, drawerToken,
    registerMaterialsRenderer, openMaterials, closeMaterials, fetchJobPayload,
    renderDoc, payloadText,
    sourceLabel, fmtTime, jobId, tabOf, stageIndex, gradeOf,
    STAGE_LABELS, STAGE_ORDER, RAIL_STEPS, TABS,
    mutateJob, decide, deliverJobs, retryJob, abandonJob, abandonDelivery,
    exportDeliveryCsv, adjustCounts, renderBoard, filteredJobs, tabCounts,
    reduceMotion
  };

  // 延迟到 DOMContentLoaded / 下一个宏任务：确保 recruitment-pipeline.js 已注册抽屉面板。
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else window.setTimeout(boot, 0);
})();
