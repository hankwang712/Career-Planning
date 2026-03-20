const appState = {
  currentSection: "dashboard",
  selectedJobs: [],
  profileComplete: true,
  matchingComplete: true,
  reportGenerated: false,
  notifications: 3,
  baseExploredJobs: 12,
  score: 87,
  profileCompletion: 85,
  timersStarted: false,
  lastGreetingKey: "",
  lastJobFilterKey: "",
  dashboardRadarChart: null,
  profileRadarChart: null,
  weights: { "基础要求": 25, "职业技能": 35, "职业素养": 20, "发展潜力": 20 }
};

// 岗位数据（从 /api/jobs 加载）
let allJobsData = [];
let filteredJobsData = [];
let jobCurrentPage = 1;
const JOB_PAGE_SIZE  = 18;
let fuseIndex = null;

let jobsGeoAssetsPromise = null;
const JOBS_CACHE_TTL_MS = 15 * 60 * 1000;
const JOBS_CACHE_VERSION = "v4";
const JOBS_CITIES_CACHE_KEY = `ms_jobs_cities_${JOBS_CACHE_VERSION}`;
const JOBS_LIST_CACHE_PREFIX = `ms_jobs_list_${JOBS_CACHE_VERSION}_`;
const JOBS_DETAIL_CACHE_PREFIX = `ms_jobs_detail_${JOBS_CACHE_VERSION}_`;

const authConfig = {
  allowSelfRegister: false,
  superUser: {
    username: "system",
    password: "123456",
    role: "super_admin",
    displayName: "System Admin"
  }
};

const userWorkspaceState = {
  currentUser: null,
  authReadyPromise: null,
  llmConfigs: {
    career_interview: null,
    assessment_hub: null
  },
  scopedData: {
    career_interview: null,
    assessment_hub: null
  }
};

const jobNameMap = { ml: "Machine Learning Engineer", da: "Data Analyst", pm: "AI Product Manager", fe: "Frontend Engineer" };
const jobRateMap = { ml: 94, da: 91, pm: 87, fe: 86 };
const liveActivityTemplates = [
  "Model service latency dropped by 4%",
  "New job samples synced to recommendation engine",
  "Profile dimensions auto-calibrated",
  "Matching strategy generated fresh candidates",
  "Report module completed incremental update",
  "System detected new job trend changes"
];

const CAREER_INTERVIEW_DIMENSIONS = ["职业兴趣", "工作价值观", "学习方式", "沟通风格", "行动证据", "职业成熟度"];
const CAREER_INTERVIEW_RIASEC_LABELS = [
  { key: "realistic", label: "现实型" },
  { key: "investigative", label: "研究型" },
  { key: "artistic", label: "艺术型" },
  { key: "social", label: "社会型" },
  { key: "enterprising", label: "企业型" },
  { key: "conventional", label: "常规型" }
];
const CAREER_INTERVIEW_DIMENSION_PLAN = [
  {
    name: "职业兴趣",
    target: 2,
    prompts: [
      "如果不考虑专业限制，你最想长期投入哪类工作或行业？为什么？",
      "最近一次让你很投入、甚至停不下来的任务是什么？你最享受哪一部分？"
    ]
  },
  {
    name: "工作价值观",
    target: 2,
    prompts: [
      "你在选职业时最看重哪三件事？比如成长、收入、稳定、影响力或自由度。",
      "如果两份工作内容差不多，你通常会用什么标准做决定？"
    ]
  },
  {
    name: "学习方式",
    target: 2,
    prompts: [
      "遇到一个完全陌生的新方向时，你通常怎么学得最快？",
      "你更适合边做边学、先搭框架，还是先把资料研究透再动手？"
    ]
  },
  {
    name: "沟通风格",
    target: 2,
    prompts: [
      "团队协作时，你通常更像推动者、协调者，还是深度执行者？",
      "当你和别人意见不一致时，你一般会怎么表达并推动事情继续？"
    ]
  },
  {
    name: "行动证据",
    target: 2,
    prompts: [
      "讲一个你主动推进并真正做成的项目、活动或作品，最后结果怎么样？",
      "有没有一段经历能证明你对某个方向不是嘴上感兴趣，而是真的投入过？"
    ]
  },
  {
    name: "职业成熟度",
    target: 2,
    prompts: [
      "你对下一步是升学、求职还是转方向，现在的判断有多明确？",
      "如果今天就要开始准备下一阶段，你最先会行动的三件事是什么？"
    ]
  }
];

const careerInterviewState = {
  started: false,
  loading: false,
  isComplete: false,
  messages: [],
  result: null,
  completionScore: 0,
  focusDimension: "职业兴趣"
};

careerInterviewState.dimensionProgress = [];

function formatDateCN(date, withTime = false) {
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  if (!withTime) return `${y} 年${m} 月${d} 日`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${y} 年${m} 月${d} 日 ${hh}:${mm}`;
}

function formatClock(date) {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function addMonths(date, count) {
  const d = new Date(date.getTime());
  d.setMonth(d.getMonth() + count);
  return d;
}

function showAuthMessage(message, type = "info") {
  const el = document.getElementById("authMessage");
  if (!el) return;
  el.textContent = message;
  el.className = "auth-message";
  if (type === "success" || type === "error" || type === "warning") el.classList.add(type);
}

function showToast(title, text = "", type = "info", duration = 2200) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast-item ${type}`;
  toast.innerHTML = `<p class="toast-title">${title}</p>${text ? `<p class="toast-text">${text}</p>` : ""}`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    setTimeout(() => toast.remove(), 220);
  }, duration);
}

function loadScriptOnce(src, key) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-script-key="${key}"]`);
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.dataset.scriptKey = key;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      resolve();
    }, { once: true });
    script.addEventListener("error", () => reject(new Error(`Failed to load ${key}`)), { once: true });
    document.body.appendChild(script);
  });
}

async function ensureJobsGeoAssets() {
  if (window.echarts && typeof window.initializeJobGeoInsights === "function") return;
  if (!jobsGeoAssetsPromise) {
    jobsGeoAssetsPromise = (async () => {
      await loadScriptOnce("/static/vendor/echarts.min.js?v=20260319-lazy-geo", "echarts");
      await loadScriptOnce("/static/vendor/china.js?v=20260318-geo", "china-map");
      await loadScriptOnce("/static/jobs-geo.js?v=20260318-rollback-1", "jobs-geo");
    })().catch((error) => {
      jobsGeoAssetsPromise = null;
      throw error;
    });
  }
  return jobsGeoAssetsPromise;
}

function getDefaultCareerInterviewConfig() {
  return {
    base_url: "",
    api_key: "",
    model: "gpt-4o-mini"
  };
}

function safeJsonParse(raw, fallback) {
  try {
    return JSON.parse(raw);
  } catch (_) {
    return fallback;
  }
}

function getCurrentUser() {
  return userWorkspaceState.currentUser;
}

function isAuthenticatedUser() {
  return Boolean(userWorkspaceState.currentUser);
}

function isSuperAdminUser() {
  return userWorkspaceState.currentUser?.role === "super_admin";
}

function emitAuthStateChange() {
  window.dispatchEvent(new CustomEvent("app:auth-changed", {
    detail: {
      user: userWorkspaceState.currentUser
    }
  }));
}

async function requestJson(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body !== "string") {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  }

  const response = await fetch(url, {
    ...options,
    headers,
    body,
    credentials: "same-origin"
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      userWorkspaceState.currentUser = null;
      userWorkspaceState.scopedData.career_interview = null;
      userWorkspaceState.scopedData.assessment_hub = null;
      if (typeof lockApp === "function") lockApp();
      emitAuthStateChange();
    }
    const error = new Error(payload.message || `请求失败：${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function getDefaultScopedData(scope) {
  return scope === "career_interview" ? null : null;
}

async function fetchScopedUserState(scope, force = false) {
  if (!force && Object.prototype.hasOwnProperty.call(userWorkspaceState.scopedData, scope) && userWorkspaceState.scopedData[scope] !== null) {
    return userWorkspaceState.scopedData[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultScopedData(scope);
  const payload = await requestJson(`/api/user-state/${scope}`);
  userWorkspaceState.scopedData[scope] = payload.data ?? null;
  return userWorkspaceState.scopedData[scope];
}

async function saveScopedUserState(scope, data) {
  if (!isAuthenticatedUser()) return null;
  await requestJson(`/api/user-state/${scope}`, {
    method: "PUT",
    body: { data }
  });
  userWorkspaceState.scopedData[scope] = data ?? null;
  return userWorkspaceState.scopedData[scope];
}

async function fetchManagedLlmConfig(scope, force = false) {
  if (!force && userWorkspaceState.llmConfigs[scope]) {
    return userWorkspaceState.llmConfigs[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultCareerInterviewConfig();
  const payload = await requestJson(`/api/llm-config/${scope}`);
  const config = {
    base_url: String(payload.base_url || "").trim(),
    api_key: String(payload.api_key || "").trim(),
    model: String(payload.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(payload.configured),
    editable: Boolean(payload.editable),
    api_key_masked: String(payload.api_key_masked || "")
  };
  userWorkspaceState.llmConfigs[scope] = config;
  return config;
}

async function saveManagedLlmConfig(scope, config) {
  const payload = await requestJson(`/api/llm-config/${scope}`, {
    method: "PUT",
    body: config
  });
  userWorkspaceState.llmConfigs[scope] = {
    base_url: String(payload.base_url || "").trim(),
    api_key: String(payload.api_key || "").trim(),
    model: String(payload.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(payload.configured),
    editable: Boolean(payload.editable),
    api_key_masked: String(payload.api_key_masked || "")
  };
  return userWorkspaceState.llmConfigs[scope];
}

window.getCurrentUser = getCurrentUser;
window.isAuthenticatedUser = isAuthenticatedUser;
window.isSuperAdminUser = isSuperAdminUser;
window.fetchScopedUserState = fetchScopedUserState;
window.saveScopedUserState = saveScopedUserState;
window.fetchManagedLlmConfig = fetchManagedLlmConfig;
window.saveManagedLlmConfig = saveManagedLlmConfig;
window.userWorkspaceState = userWorkspaceState;

function readSessionCache(key) {
  const payload = safeJsonParse(sessionStorage.getItem(key), null);
  if (!payload || typeof payload !== "object") return null;
  if (Number(payload.expiresAt || 0) < Date.now()) {
    sessionStorage.removeItem(key);
    return null;
  }
  return payload.data ?? null;
}

function writeSessionCache(key, data, ttlMs = JOBS_CACHE_TTL_MS) {
  sessionStorage.setItem(key, JSON.stringify({
    expiresAt: Date.now() + ttlMs,
    data
  }));
}

async function fetchJsonWithSessionCache(url, cacheKey, ttlMs = JOBS_CACHE_TTL_MS) {
  const cached = readSessionCache(cacheKey);
  if (cached) return cached;
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || `Request failed: ${response.status}`);
  }
  writeSessionCache(cacheKey, payload, ttlMs);
  return payload;
}

function buildJobSearchIndex() {
  if (!window.Fuse || fuseIndex || allJobsData.length === 0) return;
  fuseIndex = new Fuse(allJobsData, {
    keys: [
      { name: "岗位名称", weight: 0.4 },
      { name: "公司名称", weight: 0.3 },
      { name: "技能要求", weight: 0.15 },
      { name: "职位类别", weight: 0.1 },
      { name: "公司行业", weight: 0.05 }
    ],
    threshold: 0.7,
    distance: 200,
    includeScore: true,
    ignoreLocation: true,
    minMatchCharLength: 1
  });
}

function scheduleGeoInsightsInit(jobs) {
  if (typeof window.initializeJobGeoInsights !== "function") return;
  const runner = () => window.initializeJobGeoInsights(jobs);
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(runner, { timeout: 1200 });
    return;
  }
  window.setTimeout(runner, 16);
}

async function getJobDetail(jobId) {
  return fetchJsonWithSessionCache(
    `/api/job-detail?id=${encodeURIComponent(jobId)}`,
    `${JOBS_DETAIL_CACHE_PREFIX}${jobId}`
  );
}

function createCareerInterviewDimensionProgress() {
  return CAREER_INTERVIEW_DIMENSION_PLAN.map((item) => ({
    name: item.name,
    target: item.target,
    answered: 0
  }));
}

function normalizeCareerDimensionName(name) {
  const text = String(name || "").trim();
  if (!text) return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  const exact = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === text);
  if (exact) return exact.name;
  const fuzzy = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => text.includes(item.name) || item.name.includes(text));
  return fuzzy ? fuzzy.name : CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
}

function getCareerDimensionProgressByName(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }
  return careerInterviewState.dimensionProgress.find((item) => item.name === normalizedName) || null;
}

function getCareerInterviewProgressPercent() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return 0;
  }
  const total = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Number(item.target || 0), 0);
  const answered = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Math.min(Number(item.target || 0), Number(item.answered || 0)), 0);
  if (!total) return 0;
  return Math.round(answered / total * 100);
}

function getNextPendingCareerDimensionName() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  }
  const nextItem = careerInterviewState.dimensionProgress.find((item) => Number(item.answered || 0) < Number(item.target || 0));
  return nextItem ? nextItem.name : null;
}

function getCareerDimensionPrompt(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  const plan = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === normalizedName) || CAREER_INTERVIEW_DIMENSION_PLAN[0];
  const progress = getCareerDimensionProgressByName(normalizedName);
  const promptIndex = Math.min(Number(progress?.answered || 0), plan.prompts.length - 1);
  return plan.prompts[promptIndex];
}

function markCareerDimensionAnswered(name) {
  const target = getCareerDimensionProgressByName(name);
  if (!target) return;
  target.answered = Math.min(Number(target.target || 0), Number(target.answered || 0) + 1);
  careerInterviewState.completionScore = getCareerInterviewProgressPercent();
}

function syncCareerInterviewProgress(result = null) {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }

  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  careerInterviewState.focusDimension = focusName;

  if (result?.is_complete) {
    careerInterviewState.dimensionProgress.forEach((item) => {
      item.answered = item.target;
    });
  }

  careerInterviewState.completionScore = Math.max(
    getCareerInterviewProgressPercent(),
    Number(result?.completion_score || 0)
  );
}

function renderCareerInterviewDimensionProgress() {
  const progress = Array.isArray(careerInterviewState.dimensionProgress) ? careerInterviewState.dimensionProgress : [];
  const html = progress.map((item) => {
    const isActive = normalizeCareerDimensionName(careerInterviewState.focusDimension) === item.name;
    const answered = Math.min(Number(item.answered || 0), Number(item.target || 0));
    const ratio = item.target ? Math.round(answered / item.target * 100) : 0;
    return `
      <div class="career-progress-item${isActive ? " active" : ""}">
        <div class="career-progress-head">
          <span>${escHtml(item.name)}</span>
          <span>${answered}/${item.target}</span>
        </div>
        <div class="career-progress-track">
          <span class="career-progress-fill" style="width:${ratio}%"></span>
        </div>
      </div>
    `;
  }).join("");

  ["careerInterviewHeroDimensionProgress", "careerInterviewModalDimensionProgress"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  });
}

function getStoredCareerInterviewConfig() {
  const fallback = getDefaultCareerInterviewConfig();
  const parsed = userWorkspaceState.llmConfigs.career_interview || fallback;
  return {
    base_url: String(parsed.base_url || parsed.baseUrl || fallback.base_url || "").trim(),
    api_key: String(parsed.api_key || parsed.apiKey || fallback.api_key || "").trim(),
    model: String(parsed.model || fallback.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(parsed.configured ?? (parsed.base_url && parsed.api_key)),
    editable: Boolean(parsed.editable ?? isSuperAdminUser()),
    api_key_masked: String(parsed.api_key_masked || "")
  };
}

function getCareerInterviewConfigFromForm() {
  return {
    base_url: (document.getElementById("careerApiBaseUrl")?.value || "").trim(),
    api_key: (document.getElementById("careerApiKey")?.value || "").trim(),
    model: (document.getElementById("careerModelName")?.value || "").trim() || "gpt-4o-mini"
  };
}

function fillCareerInterviewConfigForm() {
  const config = getStoredCareerInterviewConfig();
  const baseUrlEl = document.getElementById("careerApiBaseUrl");
  const apiKeyEl = document.getElementById("careerApiKey");
  const modelEl = document.getElementById("careerModelName");
  if (baseUrlEl) baseUrlEl.value = config.base_url;
  if (apiKeyEl) apiKeyEl.value = config.api_key;
  if (modelEl) modelEl.value = config.model;
  [baseUrlEl, apiKeyEl, modelEl].forEach((el) => {
    if (el) el.disabled = !config.editable;
  });
}

function maskApiKey(apiKey) {
  if (!apiKey) return "未填写";
  if (apiKey.length <= 8) return "已填写";
  return `${apiKey.slice(0, 4)}****${apiKey.slice(-4)}`;
}

function updateCareerInterviewConfigStatus() {
  const config = getStoredCareerInterviewConfig();
  const statusEl = document.getElementById("careerInterviewConfigStatus");
  if (!statusEl) return;
  if (!config.configured) {
    statusEl.textContent = isSuperAdminUser() ? "未配置" : "等待系统管理员配置";
    return;
  }
  statusEl.textContent = `${config.model} / ${config.api_key_masked || maskApiKey(config.api_key)}`;
}

function persistCareerInterviewSnapshot() {
  const snapshot = {
    started: careerInterviewState.started,
    loading: false,
    isComplete: careerInterviewState.isComplete,
    messages: careerInterviewState.messages,
    result: careerInterviewState.result,
    completionScore: careerInterviewState.completionScore,
    focusDimension: careerInterviewState.focusDimension,
    dimensionProgress: careerInterviewState.dimensionProgress
  };
  void saveScopedUserState("career_interview", snapshot).catch((error) => {
    console.error("save career interview snapshot failed", error);
  });
}
function resetCareerInterviewState() {
  careerInterviewState.started = false;
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = false;
  careerInterviewState.messages = [];
  careerInterviewState.result = null;
  careerInterviewState.completionScore = 0;
  careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
}
async function saveCareerInterviewConfig() {
  if (!isSuperAdminUser()) {
    showToast("权限不足", "普通用户只能使用系统管理员预设的模型配置。", "warning", 2000);
    return;
  }
  const config = getCareerInterviewConfigFromForm();
  await saveManagedLlmConfig("career_interview", config);
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  showToast("模型配置已保存", `当前模型：${config.model}`, "success", 1600);
}

async function loadCareerInterviewConfig(force = false) {
  if (!isAuthenticatedUser()) {
    userWorkspaceState.llmConfigs.career_interview = getDefaultCareerInterviewConfig();
    fillCareerInterviewConfigForm();
    updateCareerInterviewConfigStatus();
    return userWorkspaceState.llmConfigs.career_interview;
  }
  try {
    await fetchManagedLlmConfig("career_interview", force);
  } catch (error) {
    console.error("load career interview config failed", error);
  }
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  return getStoredCareerInterviewConfig();
}

function updateCareerInterviewHero(result = null) {
  const statusEl = document.getElementById("careerInterviewHeroStatus");
  const hintEl = document.getElementById("careerInterviewHeroHint");
  renderCareerInterviewDimensionProgress();
  if (!statusEl || !hintEl) return;

  const progress = careerInterviewState.completionScore || Number(result?.completion_score || 0) || 0;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  const focusProgress = getCareerDimensionProgressByName(focusName);
  const ratioText = focusProgress ? `${Math.min(focusProgress.answered, focusProgress.target)}/${focusProgress.target}` : "0/0";

  if (!careerInterviewState.started && !result) {
    statusEl.textContent = getStoredCareerInterviewConfig().configured ? "可开始访谈" : "等待系统模型配置";
    hintEl.textContent = isSuperAdminUser()
      ? "请先保存系统模型配置，再启动访谈。启动后会按维度同步推进职业兴趣画像。"
      : "当前模型由系统管理员统一配置。配置完成后即可启动访谈，并按维度同步推进职业兴趣画像。";
    return;
  }

  if (careerInterviewState.isComplete || result?.is_complete) {
    statusEl.textContent = "访谈完成";
    hintEl.textContent = "六个核心维度已经补齐，可以直接参考下方的岗位方向、证据和行动建议。";
    return;
  }

  statusEl.textContent = `访谈进行中 ${progress}%`;
  hintEl.textContent = `当前聚焦“${focusName}”，维度进度 ${ratioText}。继续回答即可推进画像。`;
}
function careerTagHtml(items, emptyText, variant = "default") {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<span class="career-empty-inline">${escHtml(emptyText)}</span>`;
  }
  return values
    .map((item) => `<span class="career-tag career-tag-${variant}">${escHtml(String(item))}</span>`)
    .join("");
}

function careerListHtml(items, emptyText) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<div class="career-list-empty">${escHtml(emptyText)}</div>`;
  }
  return values
    .map((item) => `<div class="career-list-item"><span class="career-list-dot"></span><span>${escHtml(String(item))}</span></div>`)
    .join("");
}

function careerDimensionHtml(dimensions) {
  const rows = Array.isArray(dimensions) ? dimensions : [];
  return rows
    .map((item) => {
      const name = escHtml(String(item.name || "未命名维度"));
      const score = Number(item.score || 0);
      const evidence = escHtml(String(item.evidence || "等待补充更多证据"));
      return `
        <div class="career-dimension-item">
          <div class="career-dimension-head">
            <span>${name}</span>
            <span>${score}%</span>
          </div>
          <div class="career-dimension-track">
            <div class="career-dimension-fill" style="width: ${Math.max(0, Math.min(100, score))}%"></div>
          </div>
          <p class="career-dimension-evidence">${evidence}</p>
        </div>
      `;
    })
    .join("");
}

function renderCareerInterviewMessages() {
  const thread = document.getElementById("careerInterviewMessages");
  const composer = document.getElementById("careerInterviewComposer");
  const input = document.getElementById("careerInterviewInput");
  const sendBtn = document.getElementById("careerInterviewSendBtn");
  const startBtn = document.getElementById("careerInterviewStartBtn");
  const hintEl = document.getElementById("careerInterviewHint");
  if (!thread) return;

  const focusName = normalizeCareerDimensionName(careerInterviewState.focusDimension);
  const focusProgress = getCareerDimensionProgressByName(focusName);
  const answered = focusProgress ? Math.min(focusProgress.answered, focusProgress.target) : 0;
  const target = focusProgress ? focusProgress.target : 0;
  const bannerHtml = careerInterviewState.started ? `
    <div class="career-chat-dimension-banner">
      <div class="career-chat-dimension-title">
        <span>当前维度</span>
        <strong>${escHtml(focusName)}</strong>
      </div>
      <div class="career-chat-dimension-meta">${answered}/${target}</div>
    </div>
  ` : "";

  if (!careerInterviewState.started || careerInterviewState.messages.length === 0) {
    thread.innerHTML = `
      <div class="career-chat-empty">
        <p class="career-chat-empty-title">模型就绪后再开始访谈。</p>
        <p class="career-chat-empty-copy">${isSuperAdminUser() ? "请先保存系统模型配置，然后开始第一轮提问。" : "当前模型由系统管理员统一配置，配置完成后即可开始第一轮提问。"}</p>
      </div>
    `;
  } else {
    thread.innerHTML = bannerHtml + careerInterviewState.messages
      .map((message) => {
        const roleClass = message.role === "user" ? "user" : "assistant";
        const roleLabel = message.role === "user" ? "你的回答" : "访谈代理";
        return `
          <div class="career-chat-item ${roleClass}">
            <div class="career-chat-meta">${roleLabel}</div>
            <div class="career-chat-bubble ${roleClass}">${escHtml(String(message.content || ""))}</div>
          </div>
        `;
      })
      .join("");
    thread.scrollTop = thread.scrollHeight;
  }

  if (composer) composer.classList.toggle("hidden", !careerInterviewState.started);
  if (input) input.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
  if (sendBtn) {
    sendBtn.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
    sendBtn.textContent = careerInterviewState.loading ? "生成中..." : "发送并继续";
  }
  if (startBtn) {
    startBtn.disabled = careerInterviewState.loading;
    startBtn.textContent = careerInterviewState.loading
      ? "生成中..."
      : careerInterviewState.started
        ? "访谈已启动"
        : "立即开始访谈";
  }
  if (hintEl) {
    hintEl.textContent = careerInterviewState.isComplete
      ? "访谈已完成，可直接参考同步到能力画像的结果。"
      : `当前维度：${focusName}（${answered}/${target}）`;
  }

  renderCareerInterviewDimensionProgress();
}
function renderCareerInterviewResult(result) {
  const emptyState = document.getElementById("careerInterviewEmptyState");
  const content = document.getElementById("careerInterviewContent");
  const progressEl = document.getElementById("careerInterviewResultProgress");
  const modalProgressEl = document.getElementById("careerInterviewModalProgress");
  const focusEl = document.getElementById("careerInterviewResultFocus");
  const modalFocusEl = document.getElementById("careerInterviewModalFocus");
  const summaryEl = document.getElementById("careerInterviewSummary");
  const valueTagsEl = document.getElementById("careerInterviewValueTags");
  const interestTagsEl = document.getElementById("careerInterviewInterestTags");
  const roleTagsEl = document.getElementById("careerInterviewRoleTags");
  const dimensionListEl = document.getElementById("careerInterviewDimensionList");
  const evidenceListEl = document.getElementById("careerInterviewEvidenceList");
  const actionListEl = document.getElementById("careerInterviewActionList");

  syncCareerInterviewProgress(result);
  updateCareerInterviewHero(result);

  const progressText = `${careerInterviewState.completionScore || 0}%`;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);

  if (!result || !result.profile) {
    if (emptyState) emptyState.classList.remove("hidden");
    if (content) content.classList.add("hidden");
    if (progressEl) progressEl.textContent = progressText;
    if (modalProgressEl) modalProgressEl.textContent = progressText;
    if (focusEl) focusEl.textContent = focusName;
    if (modalFocusEl) modalFocusEl.textContent = focusName;
    updateProfileRadarChart(null);
    renderCareerInterviewDimensionProgress();
    return;
  }

  if (emptyState) emptyState.classList.add("hidden");
  if (content) content.classList.remove("hidden");
  if (progressEl) progressEl.textContent = progressText;
  if (modalProgressEl) modalProgressEl.textContent = progressText;
  if (focusEl) focusEl.textContent = focusName;
  if (modalFocusEl) modalFocusEl.textContent = focusName;
  if (summaryEl) summaryEl.textContent = result.profile.summary || "访谈结果已更新。";
  if (valueTagsEl) valueTagsEl.innerHTML = careerTagHtml(result.profile.work_values, "等待补充", "soft");
  if (interestTagsEl) interestTagsEl.innerHTML = careerTagHtml(result.profile.career_interests, "等待识别", "primary");
  if (roleTagsEl) roleTagsEl.innerHTML = careerTagHtml(result.profile.recommended_roles, "等待生成", "accent");
  if (dimensionListEl) dimensionListEl.innerHTML = careerDimensionHtml(result.profile.dimensions || []);
  if (evidenceListEl) evidenceListEl.innerHTML = careerListHtml(result.profile.evidence_highlights, "等待更多真实经历证据");
  if (actionListEl) actionListEl.innerHTML = careerListHtml(result.profile.next_steps, "等待生成下一步建议");

  renderCareerInterviewDimensionProgress();
  updateProfileRadarChart(result.profile);
}
function updateProfileRadarChart(profile) {
  const chart = appState.profileRadarChart;
  if (!chart) return;

  if (!profile || !Array.isArray(profile.dimensions) || profile.dimensions.length === 0) {
    chart.data.labels = ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"];
    chart.data.datasets[0].label = "能力评分";
    chart.data.datasets[0].data = [75, 60, 82, 88, 70, 65, 60, 55];
    chart.update();
    return;
  }

  chart.data.labels = profile.dimensions.map((item) => item.name);
  chart.data.datasets[0].label = "访谈画像";
  chart.data.datasets[0].data = profile.dimensions.map((item) => Number(item.score || 0));
  chart.update();
}

async function hydrateCareerInterviewState(force = false) {
  await loadCareerInterviewConfig(force);
  if (!isAuthenticatedUser()) {
    resetCareerInterviewState();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  const snapshot = await fetchScopedUserState("career_interview", force);
  if (!snapshot) {
    resetCareerInterviewState();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  careerInterviewState.started = Boolean(snapshot.started);
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = Boolean(snapshot.isComplete);
  careerInterviewState.messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
  careerInterviewState.result = snapshot.result || null;
  careerInterviewState.completionScore = Number(snapshot.completionScore || 0);
  careerInterviewState.focusDimension = snapshot.focusDimension || CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = Array.isArray(snapshot.dimensionProgress) && snapshot.dimensionProgress.length > 0
    ? snapshot.dimensionProgress
    : createCareerInterviewDimensionProgress();

  syncCareerInterviewProgress(careerInterviewState.result);
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
}
function openCareerInterviewModal(mode = "chat") {
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
  const modal = document.getElementById("careerInterviewModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  window.setTimeout(() => {
    if (mode === "config") {
      document.getElementById("careerApiBaseUrl")?.focus();
    } else if (careerInterviewState.started && !careerInterviewState.isComplete) {
      document.getElementById("careerInterviewInput")?.focus();
    } else {
      document.getElementById("careerInterviewStartBtn")?.focus();
    }
  }, 50);
}

function closeCareerInterviewModal() {
  const modal = document.getElementById("careerInterviewModal");
  if (modal) modal.classList.add("hidden");
  document.body.style.overflow = "";
}

function handleCareerInterviewOverlayClick(event) {
  if (event.target?.id === "careerInterviewModal") {
    closeCareerInterviewModal();
  }
}

function clearCareerInterviewSession() {
  resetCareerInterviewState();
  void saveScopedUserState("career_interview", null).catch((error) => {
    console.error("clear career interview state failed", error);
  });
  renderCareerInterviewMessages();
  renderCareerInterviewResult(null);
  showToast("访谈已清空", "你可以重新开始新的访谈。", "info", 1600);
}

function handleCareerInterviewInputKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCareerInterviewAnswer();
  }
}

async function requestCareerInterview(messages) {
  const config = getStoredCareerInterviewConfig();
  if (!config.configured) {
    throw new Error("职业访谈模型尚未由系统管理员配置。");
  }
  return requestJson("/api/career-interview", {
    method: "POST",
    body: {
      messages: messages.slice(-8),
      focus_dimension: careerInterviewState.focusDimension,
      progress: careerInterviewState.dimensionProgress
    }
  });
}
async function startCareerInterview() {
  if (careerInterviewState.loading) return;

  const config = getStoredCareerInterviewConfig();
  if (!config.configured) {
    showToast("缺少模型配置", isSuperAdminUser() ? "请先保存系统模型配置。" : "当前模型由系统管理员统一配置，请联系管理员。", "warning", 2200);
    openCareerInterviewModal("config");
    return;
  }

  resetCareerInterviewState();
  careerInterviewState.started = true;
  careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  careerInterviewState.result = {
    is_complete: false,
    completion_score: 0,
    focus_dimension: careerInterviewState.focusDimension,
    profile: null
  };
  careerInterviewState.messages.push({
    role: "assistant",
    content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
  });
  syncCareerInterviewProgress(careerInterviewState.result);
  persistCareerInterviewSnapshot();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
  document.getElementById("careerInterviewInput")?.focus();
}
async function submitCareerInterviewAnswer() {
  if (careerInterviewState.loading || !careerInterviewState.started || careerInterviewState.isComplete) return;
  const input = document.getElementById("careerInterviewInput");
  const answer = (input?.value || "").trim();
  if (!answer) {
    showToast("请先输入回答", "模型需要你的回答才能继续追问。", "warning", 1800);
    return;
  }

  markCareerDimensionAnswered(careerInterviewState.focusDimension);
  careerInterviewState.messages.push({ role: "user", content: answer });
  if (input) input.value = "";

  const currentProgress = getCareerDimensionProgressByName(careerInterviewState.focusDimension);
  const shouldAskLocalFollowUp = currentProgress && currentProgress.answered < currentProgress.target;

  if (shouldAskLocalFollowUp) {
    careerInterviewState.completionScore = getCareerInterviewProgressPercent();
    careerInterviewState.messages.push({
      role: "assistant",
      content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
    });
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    document.getElementById("careerInterviewInput")?.focus();
    return;
  }

  careerInterviewState.loading = true;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);

  try {
    const result = await requestCareerInterview(careerInterviewState.messages);
    careerInterviewState.loading = false;
    careerInterviewState.result = result;
    syncCareerInterviewProgress(result);
    const nextFocus = getNextPendingCareerDimensionName();
    careerInterviewState.isComplete = !nextFocus || Boolean(result.is_complete) || careerInterviewState.completionScore >= 100;
    careerInterviewState.focusDimension = careerInterviewState.isComplete
      ? normalizeCareerDimensionName(result.focus_dimension || careerInterviewState.focusDimension)
      : nextFocus;
    result.completion_score = careerInterviewState.completionScore;
    result.focus_dimension = careerInterviewState.focusDimension;
    if (careerInterviewState.isComplete) {
      careerInterviewState.messages.push({
        role: "assistant",
        content: result.assistant_reply || "访谈完成，我已经整理出你的职业兴趣画像。"
      });
    } else {
      careerInterviewState.messages.push({
        role: "assistant",
        content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
      });
    }
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(result);
    document.getElementById("careerInterviewInput")?.focus();
  } catch (error) {
    careerInterviewState.loading = false;
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("继续访谈失败", error.message, "error", 2400);
  }
}
function addLiveActivity(message) {
  const feed = document.getElementById("liveActivityFeed");
  if (!feed) return;
  const li = document.createElement("li");
  li.className = "live-feed-item";
  li.innerHTML = `
    <span class="live-feed-dot"></span>
    <div>
      <p class="text-sm text-gray-800">${message}</p>
      <p class="text-xs text-gray-500">${formatClock(new Date())}</p>
    </div>
  `;
  feed.insertBefore(li, feed.firstChild);
  while (feed.children.length > 6) feed.removeChild(feed.lastElementChild);
}

function animateCounter(el, target, suffix = "", duration = 500) {
  if (!el) return;
  const from = Number((el.textContent || "").replace(/[^\d.-]/g, "")) || 0;
  if (from === target) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  if (el.offsetParent === null) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  const start = performance.now();
  function frame(now) {
    const p = Math.min(1, (now - start) / duration);
    const val = Math.round(from + (target - from) * p);
    el.textContent = `${val}${suffix}`;
    if (p < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function fillSuperUser() {
  const u = document.getElementById("loginUsername");
  const p = document.getElementById("loginPassword");
  if (u) u.value = authConfig.superUser.username;
  if (p) p.value = authConfig.superUser.password;
}

function switchAuthTab(tab) {
  const isLogin = tab === "login";
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const loginBtn = document.getElementById("loginTabBtn");
  const registerBtn = document.getElementById("registerTabBtn");
  if (!loginForm || !registerForm || !loginBtn || !registerBtn) return;
  loginForm.classList.toggle("hidden", !isLogin);
  registerForm.classList.toggle("hidden", isLogin);
  loginBtn.classList.toggle("active", isLogin);
  registerBtn.classList.toggle("active", !isLogin);
  if (isLogin) {
    showAuthMessage("预置账号：system");
  } else if (!authConfig.allowSelfRegister) {
    showAuthMessage("当前环境仅开放预置账号登录，普通用户不支持自助注册。", "warning");
  } else {
    showAuthMessage("创建普通用户账号。");
  }
}

function lockApp() {
  userWorkspaceState.currentUser = null;
  document.body.classList.add("auth-locked");
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  if (startup) startup.classList.remove("hidden");
  if (label) { label.textContent = "未登录"; label.classList.add("hidden"); }
  if (logoutBtn) logoutBtn.classList.add("hidden");
  if (avatar) avatar.textContent = "人";
}

function unlockAppForUser(user) {
  userWorkspaceState.currentUser = user;
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  document.body.classList.remove("auth-locked");
  if (startup) startup.classList.add("hidden");
  if (label) { label.textContent = `${user.display_name || user.displayName || user.username} (${user.role === "super_admin" ? "Super Admin" : "User"})`; label.classList.remove("hidden"); }
  if (logoutBtn) logoutBtn.classList.remove("hidden");
  if (avatar) avatar.textContent = user.role === "super_admin" ? "管" : "人";
  addLiveActivity(`User signed in: ${user.username}`);
  showToast("登录成功", `欢迎回来，${user.display_name || user.displayName || user.username}。`, "success", 1800);
  emitAuthStateChange();
}

async function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) return showAuthMessage("请输入用户名和密码。", "error");
  try {
    await requestJson("/api/auth/login", {
      method: "POST",
      body: { username, password }
    });
    showAuthMessage("登录成功，正在进入你的独立空间……", "success");
    window.setTimeout(() => window.location.reload(), 180);
  } catch (error) {
    showAuthMessage(error.message || "用户名或密码错误。", "error");
  }
}

function handleRegister(event) {
  event.preventDefault();
  if (!authConfig.allowSelfRegister) return showAuthMessage("当前环境仅开放预置账号登录，不支持自助注册。", "warning");
  showAuthMessage("注册入口后续开放。", "warning");
}

async function logout() {
  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (_) {
    // ignore logout race
  }
  window.location.reload();
}

async function initAuth() {
  if (userWorkspaceState.authReadyPromise) return userWorkspaceState.authReadyPromise;
  userWorkspaceState.authReadyPromise = (async () => {
    try {
      const payload = await requestJson("/api/auth/status");
      if (payload.authenticated && payload.user) {
        unlockAppForUser(payload.user);
        await Promise.allSettled([
          loadCareerInterviewConfig(true),
          hydrateCareerInterviewState(true)
        ]);
        return payload.user;
      }
    } catch (error) {
      console.error("init auth failed", error);
    }
    lockApp();
    switchAuthTab("login");
    fillSuperUser();
    emitAuthStateChange();
    return null;
  })();
  return userWorkspaceState.authReadyPromise;
}

function setTagState(el, state) {
  if (!el) return;
  el.classList.remove("text-green-600", "text-orange-600", "text-red-600");
  if (state === "done") { el.classList.add("text-green-600"); el.textContent = "已完成"; }
  else if (state === "processing") { el.classList.add("text-orange-600"); el.textContent = "进行中"; }
  else { el.classList.add("text-red-600"); el.textContent = "待完成"; }
}

function updateNotificationCount(count = null) {
  if (typeof count === "number") appState.notifications = Math.max(0, count);
  const el = document.getElementById("notificationCount");
  if (el) el.textContent = String(appState.notifications);
}

function updateReportDates(baseDate = new Date()) {
  const validDate = addMonths(baseDate, 6);
  const generatedTime = document.getElementById("reportGeneratedTime");
  const headerDate = document.getElementById("reportHeaderDate");
  const footerGenerated = document.getElementById("reportFooterGeneratedDate");
  const footerValid = document.getElementById("reportFooterValidDate");
  const footerYear = document.getElementById("footerYear");
  if (generatedTime) generatedTime.textContent = formatDateCN(baseDate, true);
  if (headerDate) headerDate.textContent = formatDateCN(baseDate);
  if (footerGenerated) footerGenerated.textContent = formatDateCN(baseDate);
  if (footerValid) footerValid.textContent = formatDateCN(validDate);
  if (footerYear) footerYear.textContent = String(baseDate.getFullYear());
}

function updateLiveClock() {
  const now = new Date();
  const clockEl = document.getElementById("liveClock");
  if (clockEl) clockEl.textContent = formatClock(now);
  const greetingKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}`;
  if (appState.lastGreetingKey === greetingKey) return;
  appState.lastGreetingKey = greetingKey;
  const title = document.getElementById("welcomeTitle");
  const subtitle = document.getElementById("welcomeSubtitle");
  const h = now.getHours();
  let greeting = "晚上好";
  let icon = "馃寵";
  if (h >= 6 && h < 12) { greeting = "早上好"; icon = "☀"; }
  if (h >= 12 && h < 18) { greeting = "下午好"; icon = "🌤"; }
  const dayIndex = Math.ceil((now - new Date(now.getFullYear(), 0, 1)) / 86400000);
  if (title) title.textContent = `${greeting}，张明同学！${icon}`;
  if (subtitle) subtitle.textContent = `今天是 ${formatDateCN(now)}，年度第 ${dayIndex} 天，系统正在同步你的最新进度。`;
}

function updateTaskPanels(explored) {
  const exploreStatus = document.getElementById("taskJobExploreStatus");
  const exploreTag = document.getElementById("taskJobExploreTag");
  const matchingStatus = document.getElementById("taskMatchingStatus");
  const matchingTag = document.getElementById("taskMatchingTag");
  const progressHint = document.getElementById("taskProgressHint");
  const reportBtn = document.getElementById("generateReportBtn");
  const exploredDone = explored >= 10;
  if (exploreStatus) exploreStatus.textContent = `已探索 ${explored} 个岗位`;
  setTagState(exploreTag, exploredDone ? "done" : "processing");
  if (matchingStatus) matchingStatus.textContent = `已分析 ${Math.max(5, appState.selectedJobs.length + 4)} 个目标岗位`;
  setTagState(matchingTag, appState.matchingComplete ? "done" : "processing");
  const doneCount = [appState.profileComplete, exploredDone, appState.matchingComplete, appState.reportGenerated].filter(Boolean).length;
  if (progressHint) progressHint.textContent = `已完成 ${doneCount}/4 个关键任务`;
  if (reportBtn) {
    if (appState.reportGenerated) {
      reportBtn.textContent = "报告已更新";
      reportBtn.classList.add("bg-green-600", "hover:bg-green-700");
      reportBtn.classList.remove("bg-purple-600", "hover:bg-purple-700");
    } else {
      reportBtn.textContent = "绔嬪嵆鐢熸垚";
      reportBtn.classList.add("bg-purple-600", "hover:bg-purple-700");
      reportBtn.classList.remove("bg-green-600", "hover:bg-green-700");
    }
  }
}

function updateDashboardMetrics() {
  const explored = appState.baseExploredJobs + appState.selectedJobs.length;
  const code = appState.selectedJobs[appState.selectedJobs.length - 1] || "ml";
  const topRate = jobRateMap[code] || 94;
  const topJob = jobNameMap[code] || "Machine Learning Engineer";
  const pending = [!appState.profileComplete, explored < 10, !appState.matchingComplete, !appState.reportGenerated].filter(Boolean).length;
  animateCounter(document.getElementById("exploredJobsCount"), explored);
  animateCounter(document.getElementById("profileCompletionRate"), appState.profileCompletion, "%");
  animateCounter(document.getElementById("topMatchRate"), topRate, "%");
  animateCounter(document.getElementById("pendingTaskCount"), pending);
  animateCounter(document.getElementById("dashboardScore"), appState.score, "%");
  const topRole = document.getElementById("topMatchRole");
  const scoreTrend = document.getElementById("scoreTrend");
  const profileHint = document.getElementById("profileCompletionHint");
  const pendingHint = document.getElementById("pendingTaskHint");
  if (topRole) topRole.textContent = topJob;
  if (scoreTrend) scoreTrend.textContent = `较基线 ${appState.score - 82 >= 0 ? "+" : ""}${appState.score - 82}%`;
  if (profileHint) profileHint.textContent = appState.profileCompletion >= 90 ? "评估表现优秀" : `剩余 ${Math.max(0, Math.ceil((100 - appState.profileCompletion) / 5))} 项`;
  if (pendingHint) pendingHint.textContent = pending === 0 ? "全部完成" : "点击查看";
  updateTaskPanels(explored);
}

function markReportGenerated() {
  if (!appState.reportGenerated) {
    appState.reportGenerated = true;
    updateReportDates(new Date());
    addLiveActivity("Report regenerated with latest data");
    showToast("Report updated", "Latest jobs and profile data were merged.", "success", 2000);
  }
  updateDashboardMetrics();
}

function showSection(sectionId) {
  if (sectionId === appState.currentSection) return;
  const sections = ["dashboard", "jobs", "profile", "matching", "report", "qa"];
  sections.forEach((id) => {
    const section = document.getElementById(id);
    // 优先使用 data-section 选择导航按钮，避免依赖 onclick 选择器。
    const navItem = document.querySelector(`button[data-section="${id}"]`);
    if (!section) return;
    if (id === sectionId) {
      section.classList.remove("hidden");
      section.classList.add("fade-in");
      if (navItem) navItem.classList.add("active");
    } else {
      section.classList.add("hidden");
      section.classList.remove("fade-in");
      if (navItem) navItem.classList.remove("active");
    }
  });
  appState.currentSection = sectionId;
  if (sectionId === "report") markReportGenerated();
  if (sectionId === "jobs" && allJobsData.length === 0) loadJobs();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function checkReportReadiness() {
  const explored = appState.baseExploredJobs + appState.selectedJobs.length;
  if (appState.profileComplete && explored >= 10 && appState.matchingComplete) {
    showToast("Ready", "All conditions are satisfied for report generation.", "success", 1800);
    addLiveActivity("Report readiness check passed");
    showSection("report");
  } else {
    showToast("Not ready", "Please finish remaining tasks first.", "warning", 2200);
  }
}

function selectTargetJob(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Target updated", `${name} added to target list.`, "success", 1800);
  addLiveActivity(`Target selected: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function addToReport(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Synced to report", `${name} added to report targets.`, "success", 1800);
  addLiveActivity(`Synced to report: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function showJobDetail(jobType) {
  const data = {
    ml: { title: "机器学习工程师", company: "明材科技 · 北京" },
    da: { title: "数据分析师", company: "字节跃动 · 上海" },
    pm: { title: "AI 产品经理", company: "腾讯 · 深圳" },
    fe: { title: "前端开发工程师", company: "阿里巴巴 · 杭州" }
  };
  const item = data[jobType] || data.ml;
  const title = document.getElementById("modalJobTitle");
  const company = document.getElementById("modalJobCompany");
  const modal = document.getElementById("jobDetailModal");
  if (title) title.textContent = item.title;
  if (company) company.textContent = item.company;
  if (modal) modal.classList.remove("hidden");
  addLiveActivity(`Viewed job details: ${item.title}`);
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add("hidden");
}

function switchGraphType(type) {
  const verticalGraph = document.getElementById("verticalGraph");
  const horizontalGraph = document.getElementById("horizontalGraph");
  const btns = document.querySelectorAll(".graph-type-btn");
  if (!verticalGraph || !horizontalGraph || btns.length < 2) return;
  if (type === "vertical") {
    verticalGraph.style.display = "block";
    horizontalGraph.style.display = "none";
    btns[0].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.remove("bg-gray-100", "text-gray-600");
    btns[1].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.add("bg-gray-100", "text-gray-600");
  } else {
    verticalGraph.style.display = "none";
    horizontalGraph.style.display = "block";
    btns[1].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.remove("bg-gray-100", "text-gray-600");
    btns[0].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.add("bg-gray-100", "text-gray-600");
  }
}

function updateWeight(slider, dimension) {
  const value = Number(slider.value);
  appState.weights[dimension] = value;
  const card = slider.closest(".text-center");
  if (card) {
    const circles = card.querySelectorAll("svg circle");
    const text = card.querySelector("svg text");
    if (text) text.textContent = `${value}%`;
    if (circles.length > 1) {
      const c = 251.2;
      circles[1].setAttribute("stroke-dasharray", String(c));
      circles[1].setAttribute("stroke-dashoffset", String((1 - value / 100) * c));
    }
  }
  const sliders = Array.from(document.querySelectorAll("input[type='range'][onchange*='updateWeight']"));
  const total = sliders.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) {
    totalEl.textContent = `${total}%`;
    totalEl.classList.toggle("text-orange-600", total !== 100);
    totalEl.classList.toggle("text-purple-600", total === 100);
  }
}

function recalculateMatching() {
  const total = Object.values(appState.weights).reduce((sum, n) => sum + n, 0);
  if (total !== 100) return showToast("Invalid weight total", "Weight sum must equal 100%.", "warning", 2200);
  showToast("Recalculating", "Applying latest weight strategy...", "info", 1000);
  setTimeout(() => {
    appState.score = Math.min(99, Math.max(70, appState.score + Math.round(Math.random() * 4 - 1)));
    updateDashboardMetrics();
    addLiveActivity("Matching engine recalculated by new weights");
    showToast("Done", "Matching ranking has been updated.", "success", 1800);
  }, 850);
}

function recalculateProfile() {
  showToast("Re-evaluating", "Refreshing capability profile...", "info", 1000);
  setTimeout(() => {
    appState.profileCompletion = Math.min(98, Math.max(70, appState.profileCompletion + Math.round(Math.random() * 5 - 2)));
    appState.score = Math.min(99, Math.max(72, appState.score + Math.round(Math.random() * 3 - 1)));
    updateDashboardMetrics();
    addLiveActivity("Capability profile updated");
    showToast("Updated", "Profile changes synced to matching module.", "success", 1800);
  }, 820);
}

function triggerFileUpload() {
  const up = document.getElementById("resumeUpload");
  if (up) up.click();
}

function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  showToast("Parsing resume", `Processing ${file.name}...`, "info", 1200);
  setTimeout(() => {
    appState.profileCompletion = Math.min(96, appState.profileCompletion + 2);
    updateDashboardMetrics();
    addLiveActivity(`Resume parsed: ${file.name}`);
    showToast("Done", "Capability profile updated.", "success", 1600);
  }, 1200);
}

function showManualInput() { showToast("Coming soon", "Manual profile input will be enabled soon.", "info", 1700); }
function editReport() { showToast("Edit mode", "Report editing is enabled.", "success", 1500); }
function saveReport() { showToast("Saved", "Report draft saved in this session.", "success", 1500); addLiveActivity("Report draft saved by user"); }

function exportReport() {
  showToast("Exporting", "Generating PDF report...", "info", 1000);
  setTimeout(() => {
    markReportGenerated();
    showToast("Export complete", "PDF report generated.", "success", 1800);
    addLiveActivity("PDF export completed");
  }, 1200);
}

function shareReport() { showToast("Share link ready", "You can now share this report.", "success", 1700); }
function scheduleConsultation() { showToast("Consultation", "Booking flow is now available.", "info", 1700); }
function showNodeDetail(nodeName) { showToast("Node details", `${nodeName} details are available.`, "info", 1700); }

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
//  浠庢湇鍔″櫒鍔犺浇宀椾綅鏁版嵁
// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
async function loadJobs() {
  const loading = document.getElementById("jobsLoading");
  const grid = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (loading) loading.classList.remove("hidden");
  if (grid) grid.classList.add("hidden");
  if (pager) pager.classList.add("hidden");

  try {
    const geoAssetsPromise = ensureJobsGeoAssets().catch((error) => {
      console.warn("jobs geo assets failed to load", error);
      return null;
    });
    const cities = await fetchJsonWithSessionCache("/api/cities", JOBS_CITIES_CACHE_KEY, 60 * 60 * 1000);
    const citySelect = document.getElementById("cityFilter");
    if (citySelect) {
      citySelect.innerHTML = '<option value="all">全部城市</option>';
      cities.forEach((city) => {
        const option = document.createElement("option");
        option.value = city;
        option.textContent = city;
        citySelect.appendChild(option);
      });
    }

    allJobsData = await fetchJsonWithSessionCache("/api/jobs?city=all&view=summary", `${JOBS_LIST_CACHE_PREFIX}all`);
    filteredJobsData = [...allJobsData];
    fuseIndex = null;
    appState.lastJobFilterKey = "";

    const industrySet = new Set(allJobsData.map((job) => job["公司行业"]).filter(Boolean));
    const industrySel = document.getElementById("industryFilter");
    if (industrySel) {
      industrySel.innerHTML = '<option value="all">全部行业</option>';
      [...industrySet].sort().forEach((industry) => {
        const option = document.createElement("option");
        option.value = industry;
        option.textContent = industry;
        industrySel.appendChild(option);
      });
    }

    if (loading) loading.classList.add("hidden");
    filterJobs(true);
    geoAssetsPromise.then(() => scheduleGeoInsightsInit(allJobsData));

    const summary = document.getElementById("jobFilterSummary");
    if (summary) summary.textContent = `已加载 ${allJobsData.length} 个岗位摘要`;
  } catch (err) {
    if (loading) {
      loading.innerHTML = `<p class="text-red-500">无法连接数据服务<br><span class="text-xs text-gray-400">${escHtml(err.message)}</span></p>`;
    }
  }
}
function filterJobs(silent = false) {
  if (allJobsData.length === 0) return;
  const query = (document.getElementById("jobSearch")?.value || "").trim();
  const cityVal = document.getElementById("cityFilter")?.value || "all";
  const industryVal = document.getElementById("industryFilter")?.value || "all";
  const filterKey = `${query}__${cityVal}__${industryVal}__${allJobsData.length}`;
  if (filterKey === appState.lastJobFilterKey) return;
  appState.lastJobFilterKey = filterKey;
  if (cityVal !== "all" && typeof window.syncJobGeoSelectionWithCity === "function") {
    window.syncJobGeoSelectionWithCity(cityVal);
  }

  let queryResult = allJobsData;
  if (query) {
    buildJobSearchIndex();
    if (fuseIndex) {
      queryResult = fuseIndex.search(query).map((item) => item.item);
      if (queryResult.length === 0) {
        const lowerQuery = query.toLowerCase();
        queryResult = allJobsData.filter((job) =>
          [job["岗位名称"], job["公司名称"], job["技能要求"], job["职位类别"], job["公司行业"]]
            .join(" ")
            .toLowerCase()
            .includes(lowerQuery)
        );
      }
    }
  }

  filteredJobsData = queryResult.filter((job) => {
    const okCity = cityVal === "all" || (job["采集城市"] || job["城市"] || "") === cityVal;
    const okIndustry = industryVal === "all" || (job["公司行业"] || "") === industryVal;
    return okCity && okIndustry;
  });

  jobCurrentPage = 1;
  renderJobCards();

  const summary = document.getElementById("jobFilterSummary");
  if (summary) summary.textContent = `当前显示 ${filteredJobsData.length} / ${allJobsData.length} 个岗位`;
  if (!silent) {
    addLiveActivity(`岗位筛选完成：共 ${filteredJobsData.length} 个结果`);
  }
}
function renderJobCards() {
  const grid  = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (!grid) return;

  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  const start      = (jobCurrentPage - 1) * JOB_PAGE_SIZE;
  const pageData   = filteredJobsData.slice(start, start + JOB_PAGE_SIZE);

  if (total === 0) {
    grid.innerHTML = `<div class="col-span-3 py-16 text-center text-gray-400">
      <p class="text-4xl mb-3">馃攳</p>
      <p class="text-lg font-medium text-gray-500">没有找到匹配的岗位</p>
      <p class="text-sm mt-1">试试调整搜索关键词或城市筛选</p>
    </div>`;
    grid.classList.remove("hidden");
    pager.classList.add("hidden");
    return;
  }

  grid.innerHTML = pageData.map((job, i) => {
    const idx     = start + i;
    const skills  = String(job["技能要求"] || "").split(",").map((s) => s.trim()).filter(Boolean);
    const skillTags = skills.slice(0, 5).map(s =>
      `<span class="px-2 py-0.5 bg-purple-50 text-purple-700 text-xs rounded border border-purple-100 whitespace-nowrap">${escHtml(s)}</span>`
    ).join("") + (skills.length > 5 ? `<span class="px-2 py-0.5 bg-gray-50 text-gray-400 text-xs rounded">+${skills.length - 5}</span>` : "");

    const fundingColors = {
      "已上市": "bg-blue-100 text-blue-700",
      "D轮及以上": "bg-indigo-100 text-indigo-700",
      "C轮": "bg-violet-100 text-violet-700",
      "B轮": "bg-purple-100 text-purple-700",
      "A轮": "bg-fuchsia-100 text-fuchsia-700",
      "天使轮": "bg-pink-100 text-pink-700"
    };
    const fundingCls = fundingColors[job["融资阶段"]] || "bg-gray-100 text-gray-500";

    return `
    <div class="job-card-real bg-white rounded-xl glass-surface p-5 shadow-sm cursor-pointer
                border-2 border-transparent hover:border-purple-300 hover:shadow-lg transition-all duration-200"
         onclick="openJobModal(${idx})">
      <!-- 鏍囬 + 钖祫 -->
      <div class="flex justify-between items-start mb-2 gap-2">
        <h3 class="text-base font-bold text-gray-800 leading-tight line-clamp-2 flex-1">${escHtml(job["岗位名称"] || "--")}</h3>
        <span class="text-sm font-bold text-emerald-600 flex-shrink-0 mt-0.5">${escHtml(job["薪资"] || "面议")}</span>
      </div>
      <!-- 鍏徃 -->
      <p class="text-sm text-gray-500 mb-3 truncate">${escHtml(job["公司名称"] || "")}</p>
      <!-- 鍩庡競 / 缁忛獙 / 瀛﹀巻 -->
      <div class="flex flex-wrap gap-1.5 mb-3">
        <span class="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs rounded-full whitespace-nowrap">馃搷 ${escHtml(job["城市"] || job["采集城市"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">${escHtml(job["经验要求"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">馃帗 ${escHtml(job["学历要求"] || "")}</span>
      </div>
      <!-- 鎶€鑳芥爣绛?-->
      <div class="flex flex-wrap gap-1 mb-4">${skillTags}</div>
      <!-- 搴曢儴锛氬叕鍙镐俊鎭?-->
      <div class="flex justify-between items-center pt-3 border-t border-gray-100 text-xs text-gray-400">
        <span class="truncate">${escHtml(job["公司规模"] || "")} 路 ${escHtml(job["公司行业"] || "")}</span>
        <span class="px-2 py-0.5 rounded-full flex-shrink-0 ml-2 ${fundingCls}">${escHtml(job["融资阶段"] || "")}</span>
      </div>
    </div>`;
  }).join("");

  grid.classList.remove("hidden");

  // 鍒嗛〉
  const prevBtn  = document.getElementById("jobPrevBtn");
  const nextBtn  = document.getElementById("jobNextBtn");
  const pageInfo = document.getElementById("jobPageInfo");
  if (pager) {
    pager.classList.remove("hidden");
    if (prevBtn)  prevBtn.disabled  = jobCurrentPage <= 1;
    if (nextBtn)  nextBtn.disabled  = jobCurrentPage >= totalPages;
    if (pageInfo) pageInfo.textContent = `第 ${jobCurrentPage} / ${totalPages} 页 · 共 ${total} 个岗位`;
  }
}

function jobChangePage(delta) {
  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  jobCurrentPage   = Math.max(1, Math.min(totalPages, jobCurrentPage + delta));
  renderJobCards();
  document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
//  寮圭獥锛氭墦寮€ / 鍏抽棴
// 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
// 绂忓埄鍏抽敭璇?鈫?emoji 鏄犲皠
const welfareIcons = {
  "年终奖": "★",
  "五险一金": "保",
  "弹性工作": "时",
  "远程办公": "远",
  "股票期权": "股",
  "带薪年假": "假",
  "团队旅游": "游",
  "员工旅游": "游",
  "餐补": "餐",
  "包吃": "食",
  "零食下午茶": "茶",
  "定期体检": "检",
  "补充医疗保险": "医",
  "节日福利": "礼",
  "通讯补贴": "讯",
  "交通补贴": "交",
  "包住": "住",
  "提供住宿": "住",
  "绩效奖金": "奖",
  "周末双休": "休",
  "大小周": "周"
};

async function openJobModal(idx) {
  let job = filteredJobsData[idx];
  if (!job) return;

  if (job.job_id) {
    try {
      job = await getJobDetail(job.job_id);
    } catch (error) {
      showToast("岗位详情加载失败", error.message, "warning", 2200);
    }
  }

  const companyName = job["公司名称"] || "--";
  const jobTitle = job["岗位名称"] || "--";

  const avatar = document.getElementById("jobModalAvatar");
  if (avatar) {
    const firstChar = companyName.charAt(0) || "?";
    avatar.textContent = firstChar;
    const hue = (firstChar.charCodeAt(0) * 37) % 360;
    avatar.style.background = `hsla(${hue},55%,55%,0.35)`;
  }

  document.getElementById("jobModalTitle").textContent = jobTitle;
  document.getElementById("jobModalCompany").textContent = companyName;
  document.getElementById("jobModalSalary").textContent = job["薪资"] || "面议";

  const meta = document.getElementById("jobModalMeta");
  const metaItems = [
    ["地点", job["城市"] || job["采集城市"]],
    ["经验", job["经验要求"]],
    ["学历", job["学历要求"]],
    ["行业", job["公司行业"]]
  ].filter(([, value]) => value);
  meta.innerHTML = metaItems.map(([label, text]) =>
    `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-white/80 whitespace-nowrap"
           style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.2)">
       ${escHtml(label)} ${escHtml(text)}
     </span>`
  ).join("");

  const skills = String(job["技能要求"] || "").split(",").map((item) => item.trim()).filter(Boolean);
  document.getElementById("jobModalSkills").innerHTML = skills.length
    ? skills.map((skill) =>
        `<span class="px-3 py-1 text-xs rounded-full font-medium"
               style="background:#f0ebff;color:#6d28d9;border:1px solid #ddd6fe">${escHtml(skill)}</span>`
      ).join("")
    : `<span class="text-gray-400 text-sm">暂无标签</span>`;

  document.getElementById("jobModalDesc").textContent = job["岗位描述"] || "暂无描述";

  const compInfo = document.getElementById("jobModalCompanyInfo");
  const compFields = [
    { icon: "融资", label: "融资阶段", val: job["融资阶段"] },
    { icon: "规模", label: "公司规模", val: job["公司规模"] },
    { icon: "行业", label: "所属行业", val: job["公司行业"] }
  ];
  compInfo.innerHTML = compFields.map(({ icon, label, val }) => `
    <div class="rounded-xl p-3 text-center" style="background:#f8f5ff;border:1px solid #ede9fe">
      <p class="text-lg mb-0.5">${icon}</p>
      <p class="text-xs font-semibold text-violet-700 leading-tight">${escHtml(val || "--")}</p>
      <p class="text-xs text-gray-400 mt-0.5">${label}</p>
    </div>`).join("");
  document.getElementById("jobModalCompanyDesc").textContent = job["公司简介"] || "";

  const addr = document.getElementById("jobModalAddr");
  if (addr) addr.textContent = job["工作地址"] || "暂无地址信息";

  const welfares = String(job["公司福利"] || "").split(",").map((item) => item.trim()).filter(Boolean);
  document.getElementById("jobModalWelfare").innerHTML = welfares.length
    ? welfares.map((welfare) => {
        const icon = welfareIcons[welfare] || "✓";
        return `<span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full font-medium"
                      style="background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0">
                  ${icon} ${escHtml(welfare)}
                </span>`;
      }).join("")
    : `<span class="text-gray-400 text-xs">暂无福利信息</span>`;

  const modal = document.getElementById("jobModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.body.style.overflow = "hidden";
}
function closeJobModal() {
  const modal = document.getElementById("jobModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  document.body.style.overflow = "";
}

function initCharts() {
  const radarCanvas = document.getElementById("radarChart");
  const profileRadarCanvas = document.getElementById("profileRadarChart");
  if (radarCanvas && window.Chart) {
    appState.dashboardRadarChart = new Chart(radarCanvas.getContext("2d"), {
      type: "radar",
      data: {
        labels: ["专业技能", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历"],
        datasets: [
          { label: "当前能力", data: [75, 82, 88, 70, 65, 60], backgroundColor: "rgba(102,126,234,0.2)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)" },
          { label: "岗位要求", data: [85, 75, 80, 75, 70, 75], backgroundColor: "rgba(118,75,162,0.2)", borderColor: "rgba(118,75,162,1)", borderWidth: 2, pointBackgroundColor: "rgba(118,75,162,1)" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 12 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { position: "top", labels: { usePointStyle: true } } } }
    });
  }
  if (profileRadarCanvas && window.Chart) {
    appState.profileRadarChart = new Chart(profileRadarCanvas.getContext("2d"), {
      type: "radar",
      data: { labels: ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"], datasets: [{ label: "能力评分", data: [75, 60, 82, 88, 70, 65, 60, 55], backgroundColor: "rgba(102,126,234,0.3)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)", pointRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 11 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { display: false } } }
    });
  }
}

function initAnimations() {
  const bars = document.querySelectorAll(".progress-bar");
  bars.forEach((bar) => {
    const w = bar.style.width;
    bar.style.width = "0";
    setTimeout(() => { bar.style.width = w; }, 400);
  });
  const modal = document.getElementById("jobDetailModal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) closeModal("jobDetailModal"); });
  if (typeof IntersectionObserver !== "undefined") {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("slide-in");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".glass-surface, .product-hero-card, .product-gallery-card").forEach((el) => observer.observe(el));
  }
}

function bindGlobalEvents() {
  const notificationBtn = document.getElementById("notificationBtn");
  if (notificationBtn) {
    notificationBtn.addEventListener("click", () => {
      const unread = appState.notifications;
      if (unread > 0) {
        showToast("Notifications", `You have ${unread} new update(s).`, "info", 1600);
        addLiveActivity(`Notification center opened (${unread})`);
      } else {
        showToast("Notifications", "No new updates.", "info", 1400);
      }
      appState.notifications = Math.max(0, unread - 1);
      updateNotificationCount();
    });
  }

  const searchInput = document.getElementById("jobSearch");
  if (searchInput) {
    // 实时输入时直接触发筛选。
    searchInput.addEventListener("input", () => filterJobs());
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        filterJobs();
      }
    });
  }

  const industryFilter = document.getElementById("industryFilter");
  const cityFilter = document.getElementById("cityFilter");
  if (industryFilter) {
    industryFilter.addEventListener("change", () => filterJobs());
  }
  if (cityFilter) {
    cityFilter.addEventListener("change", () => filterJobs());
  }
}

function startRealtimeEngine() {
  if (appState.timersStarted) return;
  appState.timersStarted = true;
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  setInterval(() => {
    const msg = liveActivityTemplates[Math.floor(Math.random() * liveActivityTemplates.length)];
    addLiveActivity(msg);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
  }, 20000);
}

document.addEventListener("DOMContentLoaded", function () {
  const authReady = initAuth();
  initCharts();
  initAnimations();
  bindGlobalEvents();
  startRealtimeEngine();
  updateReportDates(new Date());
  updateNotificationCount();
  updateDashboardMetrics();
  addLiveActivity("System initialized. Dynamic monitoring is active.");
  Promise.resolve(authReady).finally(() => {
    updateCareerInterviewConfigStatus();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
  });
});

// 鑱屼笟闂瓟妯″潡
function fillQAQuestion(question) {
  const input = document.getElementById("qaInput");
  if (input) {
    input.value = question;
    input.focus();
  }
}

function submitQAQuestion() {
  const input = document.getElementById("qaInput");
  if (!input || !input.value.trim()) {
    showToast("提示", "请先输入你的职业问题", "warning", 2000);
    return;
  }
  showToast(
    "职业问答",
    `RAG 引擎正在接入中，当前可先参考下方预置问答示例。问题已记录：${input.value.substring(0, 20)}...`,
    "info",
    3000
  );
}

function expandQA(el) {
  const content = el.querySelector(".hidden, .block");
  const arrow = el.querySelector("span:last-child");
  if (!content) return;
  if (content.classList.contains("hidden")) {
    content.classList.remove("hidden");
    content.classList.add("block");
    if (arrow) arrow.textContent = "▴";
  } else {
    content.classList.add("hidden");
    content.classList.remove("block");
    if (arrow) arrow.textContent = "▾";
  }
}

