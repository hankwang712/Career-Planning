const appState = {
  currentSection: "dashboard",
  selectedJobs: [],
  profileComplete: false,
  matchingComplete: false,
  reportGenerated: false,
  notifications: 3,
  baseExploredJobs: 0,
  score: 0,
  profileCompletion: 0,
  timersStarted: false,
  lastGreetingKey: "",
  lastJobFilterKey: "",
  dashboardRadarChart: null,
  profileRadarChart: null,
  derivedProfile: null,
  matchingRoles: [],
  focusedRoleId: "",
  weights: { "特质匹配": 30, "能力匹配": 40, "专业匹配": 15, "意愿匹配": 15 }
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

const PROFILE_BASIC_FIELDS = ["major", "grade", "target_city", "target_direction"];
const PROFILE_BASIC_LABELS = {
  major: "专业",
  grade: "年级",
  target_city: "目标城市",
  target_direction: "目标方向"
};
const ROLE_LIBRARY = [
  {
    id: "java_backend",
    name: "Java 后端开发",
    category: "互联网/科技",
    majors: ["计算机", "软件", "信息", "网络", "智能"],
    requiredSkills: ["编程", "数据库", "Spring"],
    certificates: ["软考"],
    requirements: { professional: 85, innovation: 60, learning: 90, stress_tolerance: 80, communication: 50, internship: 80, execution: 85 },
    recommendedHolland: ["I", "R", "C"],
    recommendedMbti: ["ISTJ", "INTJ"],
    workValues: ["稳定成长", "技术深耕"],
    path: "后端开发 → 高级开发 → 架构师"
  },
  {
    id: "product_manager",
    name: "产品经理",
    category: "互联网/科技",
    majors: ["不限", "计算机", "智能", "管理"],
    requiredSkills: ["需求分析", "原型设计", "数据分析"],
    certificates: ["NPDP", "PMP"],
    requirements: { professional: 75, innovation: 90, learning: 80, stress_tolerance: 90, communication: 90, internship: 85, execution: 80 },
    recommendedHolland: ["E", "I", "S"],
    recommendedMbti: ["ENTJ", "ENFP", "INTJ"],
    workValues: ["成长空间", "影响力", "协作成就"],
    path: "产品助理 → 产品经理 → 高级产品经理"
  },
  {
    id: "data_analyst",
    name: "数据分析师",
    category: "数据与商业分析",
    majors: ["统计", "计算机", "经管", "数学", "智能"],
    requiredSkills: ["SQL", "Python", "BI"],
    certificates: ["CDA"],
    requirements: { professional: 80, innovation: 70, learning: 90, stress_tolerance: 70, communication: 60, internship: 65, execution: 75 },
    recommendedHolland: ["I", "C", "S"],
    recommendedMbti: ["INTJ", "ISTJ"],
    workValues: ["问题解决", "稳定成长", "数据驱动"],
    path: "数据分析师 → 高级分析师 → 数据策略"
  },
  {
    id: "new_media_ops",
    name: "新媒体运营",
    category: "内容与增长",
    majors: ["不限", "新闻", "传播", "中文", "设计"],
    requiredSkills: ["内容策划", "剪辑", "运营分析"],
    certificates: ["营销师"],
    requirements: { professional: 65, innovation: 80, learning: 70, stress_tolerance: 60, communication: 80, internship: 60, execution: 70 },
    recommendedHolland: ["A", "E", "S"],
    recommendedMbti: ["ENFP", "ESFP"],
    workValues: ["创造表达", "传播影响", "节奏灵活"],
    path: "运营专员 → 内容负责人 → 增长运营"
  },
  {
    id: "hr_specialist",
    name: "人力资源专员",
    category: "组织与服务",
    majors: ["管理", "心理", "不限"],
    requiredSkills: ["招聘", "沟通", "劳动法规"],
    certificates: ["人力资源管理师"],
    requirements: { professional: 65, innovation: 50, learning: 60, stress_tolerance: 70, communication: 95, internship: 65, execution: 72 },
    recommendedHolland: ["S", "C", "E"],
    recommendedMbti: ["ESFJ", "ENFJ"],
    workValues: ["助人成长", "组织支持", "关系协作"],
    path: "HR 助理 → HRBP/招聘专员 → 人力负责人"
  },
  {
    id: "sales_trainee",
    name: "销售管培生",
    category: "商业拓展",
    majors: ["不限"],
    requiredSkills: ["谈判", "客户管理", "目标推进"],
    certificates: [],
    requirements: { professional: 55, innovation: 60, learning: 80, stress_tolerance: 95, communication: 95, internship: 80, execution: 82 },
    recommendedHolland: ["E", "S", "A"],
    recommendedMbti: ["ESTJ", "ENTJ"],
    workValues: ["回报激励", "竞争成就", "成长速度"],
    path: "管培生 → 销售经理 → 区域负责人"
  },
  {
    id: "uiux_designer",
    name: "UI/UX 设计师",
    category: "设计与体验",
    majors: ["设计", "计算机", "数字媒体", "不限"],
    requiredSkills: ["界面设计", "交互设计", "用户研究"],
    certificates: ["Adobe"],
    requirements: { professional: 72, innovation: 95, learning: 80, stress_tolerance: 70, communication: 70, internship: 75, execution: 68 },
    recommendedHolland: ["A", "I", "R"],
    recommendedMbti: ["INFP", "ENFP"],
    workValues: ["审美表达", "用户体验", "作品成就"],
    path: "设计师 → 高级设计师 → 体验负责人"
  },
  {
    id: "finance_audit",
    name: "财务/审计助理",
    category: "财务与风控",
    majors: ["会计", "财务", "审计", "经济"],
    requiredSkills: ["会计准则", "税务", "报表"],
    certificates: ["初级会计", "CPA"],
    requirements: { professional: 80, innovation: 40, learning: 70, stress_tolerance: 80, communication: 50, internship: 80, execution: 90 },
    recommendedHolland: ["C", "I", "E"],
    recommendedMbti: ["ISTJ", "ISFJ"],
    workValues: ["稳定性", "规范流程", "准确性"],
    path: "财务助理 → 审计/财务专员 → 财务经理"
  },
  {
    id: "project_assistant",
    name: "项目管理助理",
    category: "组织与项目",
    majors: ["不限", "管理", "工程", "计算机"],
    requiredSkills: ["进度管理", "风险跟踪", "协调沟通"],
    certificates: ["PMP"],
    requirements: { professional: 68, innovation: 50, learning: 70, stress_tolerance: 80, communication: 90, internship: 65, execution: 88 },
    recommendedHolland: ["E", "S", "C"],
    recommendedMbti: ["ENTJ", "ESTJ"],
    workValues: ["组织推进", "交付成果", "节奏掌控"],
    path: "项目助理 → 项目经理 → PMO"
  },
  {
    id: "content_editor",
    name: "内容创作/编辑",
    category: "内容与表达",
    majors: ["文史", "新闻", "中文", "传播", "不限"],
    requiredSkills: ["写作", "策划", "选题"],
    certificates: ["出版资格"],
    requirements: { professional: 68, innovation: 90, learning: 60, stress_tolerance: 60, communication: 60, internship: 60, execution: 70 },
    recommendedHolland: ["A", "S", "I"],
    recommendedMbti: ["INFP", "INFJ"],
    workValues: ["表达自由", "内容影响", "持续创作"],
    path: "编辑 → 内容策划 → 内容负责人"
  }
];

function getDefaultProfileBasics() {
  return {
    major: "",
    grade: "",
    target_city: "",
    target_direction: ""
  };
}

const careerInterviewState = {
  started: false,
  loading: false,
  isComplete: false,
  messages: [],
  result: null,
  completionScore: 0,
  focusDimension: "职业兴趣",
  profileBasics: getDefaultProfileBasics()
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

function scheduleAnalyticsInit(jobs) {
  if (typeof window.initJobsAnalytics !== "function") return;
  const runner = () => window.initJobsAnalytics(jobs);
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(runner, { timeout: 2000 });
    return;
  }
  window.setTimeout(runner, 200);
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
  // 配置输入已移至设置面板，直接返回内存中的配置
  return getStoredCareerInterviewConfig();
}

function fillCareerInterviewConfigForm() {
  // 配置表单已移至头像设置面板，此函数保留以兼容调用链
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
    dimensionProgress: careerInterviewState.dimensionProgress,
    profileBasics: careerInterviewState.profileBasics
  };
  void saveScopedUserState("career_interview", snapshot).catch((error) => {
    console.error("save career interview snapshot failed", error);
  });
}
function resetCareerInterviewState(options = {}) {
  const preserveBasics = options.preserveBasics !== false;
  const retainedBasics = preserveBasics ? normalizeProfileBasics(careerInterviewState.profileBasics) : getDefaultProfileBasics();
  careerInterviewState.started = false;
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = false;
  careerInterviewState.messages = [];
  careerInterviewState.result = null;
  careerInterviewState.completionScore = 0;
  careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  careerInterviewState.profileBasics = retainedBasics;
}
async function saveCareerInterviewConfig() {
  // 配置入口已迁移至头像设置面板
  if (typeof openSettingsPanel === "function") openSettingsPanel();
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
    refreshUnifiedExperience();
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
  refreshUnifiedExperience();
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
    resetCareerInterviewState({ preserveBasics: false });
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  const snapshot = await fetchScopedUserState("career_interview", force);
  if (!snapshot) {
    resetCareerInterviewState({ preserveBasics: false });
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
  careerInterviewState.profileBasics = normalizeProfileBasics(snapshot.profileBasics);
  careerInterviewState.dimensionProgress = Array.isArray(snapshot.dimensionProgress) && snapshot.dimensionProgress.length > 0
    ? snapshot.dimensionProgress
    : createCareerInterviewDimensionProgress();

  syncCareerInterviewProgress(careerInterviewState.result);
  syncProfileBasicsForm();
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
      // 配置已迁移至头像设置面板
      openSettingsPanel();
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
  resetCareerInterviewState({ preserveBasics: true });
  persistCareerInterviewSnapshot();
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
      progress: careerInterviewState.dimensionProgress,
      assessment_context: buildAssessmentContextPayload()
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

  resetCareerInterviewState({ preserveBasics: true });
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

function clampPercent(value, fallback = 0) {
  const num = Number(value);
  if (!Number.isFinite(num)) return fallback;
  return Math.max(0, Math.min(100, Math.round(num)));
}

function averageValues(values) {
  const list = Array.isArray(values) ? values.filter((value) => Number.isFinite(Number(value))) : [];
  if (!list.length) return null;
  return Math.round(list.reduce((sum, value) => sum + Number(value), 0) / list.length);
}

function uniqueValues(values, limit = 6) {
  return [...new Set((Array.isArray(values) ? values : []).map((item) => String(item || "").trim()).filter(Boolean))].slice(0, limit);
}

function normalizeProfileBasics(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  return {
    major: String(source.major || "").trim(),
    grade: String(source.grade || "").trim(),
    target_city: String(source.target_city || source.targetCity || "").trim(),
    target_direction: String(source.target_direction || source.targetDirection || "").trim()
  };
}

function syncProfileBasicsForm() {
  const basics = normalizeProfileBasics(careerInterviewState.profileBasics);
  const fieldMap = {
    profileMajorInput: basics.major,
    profileGradeInput: basics.grade,
    profileTargetCityInput: basics.target_city,
    profileTargetDirectionInput: basics.target_direction
  };
  Object.entries(fieldMap).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  const missing = PROFILE_BASIC_FIELDS.filter((key) => !basics[key]);
  const statusEl = document.getElementById("profileBasicsStatus");
  if (statusEl) {
    statusEl.textContent = missing.length
      ? `待补充：${missing.map((key) => PROFILE_BASIC_LABELS[key]).join("、")}`
      : "基础信息已同步到画像、匹配与报告。";
  }
}

function collectProfileBasicsFromForm() {
  return normalizeProfileBasics({
    major: document.getElementById("profileMajorInput")?.value || "",
    grade: document.getElementById("profileGradeInput")?.value || "",
    target_city: document.getElementById("profileTargetCityInput")?.value || "",
    target_direction: document.getElementById("profileTargetDirectionInput")?.value || ""
  });
}

function saveProfileBasics() {
  careerInterviewState.profileBasics = collectProfileBasicsFromForm();
  persistCareerInterviewSnapshot();
  syncProfileBasicsForm();
  refreshUnifiedExperience();
  showToast("基础信息已保存", "后续匹配与报告会直接引用这些字段。", "success", 1800);
}

function getAssessmentHubSnapshotSafe() {
  try {
    return typeof window.getAssessmentHubSnapshot === "function" ? window.getAssessmentHubSnapshot() : null;
  } catch (error) {
    console.error("read assessment snapshot failed", error);
    return null;
  }
}

function buildAssessmentContextPayload() {
  const assessment = getAssessmentHubSnapshotSafe() || {};
  return {
    mbti: assessment.mbti || {},
    holland: assessment.holland || {},
    basics: normalizeProfileBasics(careerInterviewState.profileBasics)
  };
}

function addCapabilitySignal(bag, key, value, source) {
  if (!Object.prototype.hasOwnProperty.call(bag, key)) return;
  const score = clampPercent(value, NaN);
  if (!Number.isFinite(score)) return;
  bag[key].push({ score, source });
}

function deriveCapabilityScores(assessment, interviewProfile, basics) {
  const bag = {
    professional: [],
    learning: [],
    communication: [],
    innovation: [],
    stress_tolerance: [],
    internship: [],
    execution: []
  };

  const mbtiType = assessment?.mbti?.completed
    ? String(assessment.mbti.final_type || assessment.mbti.raw_type || "")
    : "";
  if (mbtiType.length === 4) {
    const [ei, sn, tf, jp] = mbtiType.split("");
    if (ei === "E") {
      addCapabilitySignal(bag, "communication", 82, "MBTI");
      addCapabilitySignal(bag, "internship", 72, "MBTI");
    } else {
      addCapabilitySignal(bag, "learning", 80, "MBTI");
      addCapabilitySignal(bag, "professional", 72, "MBTI");
    }
    if (sn === "N") {
      addCapabilitySignal(bag, "innovation", 88, "MBTI");
      addCapabilitySignal(bag, "learning", 84, "MBTI");
    } else {
      addCapabilitySignal(bag, "execution", 78, "MBTI");
      addCapabilitySignal(bag, "internship", 76, "MBTI");
    }
    if (tf === "T") {
      addCapabilitySignal(bag, "professional", 78, "MBTI");
      addCapabilitySignal(bag, "stress_tolerance", 74, "MBTI");
    } else {
      addCapabilitySignal(bag, "communication", 80, "MBTI");
      addCapabilitySignal(bag, "innovation", 72, "MBTI");
    }
    if (jp === "J") {
      addCapabilitySignal(bag, "execution", 86, "MBTI");
      addCapabilitySignal(bag, "stress_tolerance", 78, "MBTI");
    } else {
      addCapabilitySignal(bag, "innovation", 84, "MBTI");
      addCapabilitySignal(bag, "execution", 58, "MBTI");
    }
  }

  const hollandCodes = Array.isArray(assessment?.holland?.top_codes) ? assessment.holland.top_codes : [];
  hollandCodes.forEach((code) => {
    if (code === "R") {
      addCapabilitySignal(bag, "internship", 82, "Holland");
      addCapabilitySignal(bag, "execution", 76, "Holland");
    }
    if (code === "I") {
      addCapabilitySignal(bag, "learning", 88, "Holland");
      addCapabilitySignal(bag, "professional", 82, "Holland");
    }
    if (code === "A") {
      addCapabilitySignal(bag, "innovation", 92, "Holland");
    }
    if (code === "S") {
      addCapabilitySignal(bag, "communication", 88, "Holland");
      addCapabilitySignal(bag, "internship", 72, "Holland");
    }
    if (code === "E") {
      addCapabilitySignal(bag, "communication", 90, "Holland");
      addCapabilitySignal(bag, "execution", 78, "Holland");
      addCapabilitySignal(bag, "stress_tolerance", 80, "Holland");
    }
    if (code === "C") {
      addCapabilitySignal(bag, "execution", 86, "Holland");
      addCapabilitySignal(bag, "professional", 78, "Holland");
    }
  });

  if (basics.major) {
    addCapabilitySignal(bag, "professional", 68, "基础信息");
  }
  if (basics.grade) {
    const gradeText = basics.grade;
    if (/大一|一年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 45, "基础信息");
    else if (/大二|二年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 55, "基础信息");
    else if (/大三|三年级/.test(gradeText)) addCapabilitySignal(bag, "internship", 68, "基础信息");
    else if (/大四|四年级|研/.test(gradeText)) addCapabilitySignal(bag, "internship", 78, "基础信息");
    addCapabilitySignal(bag, "execution", /大三|大四|研/.test(gradeText) ? 72 : 60, "基础信息");
  }

  if (interviewProfile) {
    const dimensions = Array.isArray(interviewProfile.dimensions) ? interviewProfile.dimensions : [];
    const dimMap = {};
    dimensions.forEach((item) => {
      const name = String(item.name || "").trim();
      if (name) dimMap[name] = clampPercent(item.score, 0);
    });
    if (dimMap["学习方式"] !== undefined) addCapabilitySignal(bag, "learning", dimMap["学习方式"], "访谈");
    if (dimMap["沟通风格"] !== undefined) addCapabilitySignal(bag, "communication", dimMap["沟通风格"], "访谈");
    if (dimMap["行动证据"] !== undefined) {
      addCapabilitySignal(bag, "internship", dimMap["行动证据"], "访谈");
      addCapabilitySignal(bag, "execution", dimMap["行动证据"], "访谈");
    }
    if (dimMap["职业成熟度"] !== undefined) {
      addCapabilitySignal(bag, "stress_tolerance", dimMap["职业成熟度"], "访谈");
      addCapabilitySignal(bag, "execution", dimMap["职业成熟度"], "访谈");
    }
    if (dimMap["职业兴趣"] !== undefined) addCapabilitySignal(bag, "innovation", dimMap["职业兴趣"], "访谈");
    if (dimMap["工作价值观"] !== undefined) addCapabilitySignal(bag, "communication", dimMap["工作价值观"], "访谈");

    const riasec = interviewProfile.riasec || {};
    addCapabilitySignal(bag, "innovation", Math.max(Number(riasec.artistic || 0), Number(riasec.investigative || 0)), "访谈");
    addCapabilitySignal(bag, "communication", Math.max(Number(riasec.social || 0), Number(riasec.enterprising || 0)), "访谈");
  }

  const capabilities = Object.fromEntries(Object.entries(bag).map(([key, items]) => {
    const score = averageValues(items.map((item) => item.score));
    return [key, {
      score,
      sources: uniqueValues(items.map((item) => item.source), 4),
      inferred: Boolean(score !== null && !items.some((item) => item.source === "访谈" || item.source === "基础信息"))
    }];
  }));

  const availableCount = Object.values(capabilities).filter((item) => item.score !== null).length;
  return {
    capabilities,
    coverage: Math.round(availableCount / Object.keys(capabilities).length * 100)
  };
}

function normalizeTextForMatch(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function roleMatchesText(role, text) {
  const target = normalizeTextForMatch(text);
  if (!target) return false;
  return [role.name, role.category, ...(role.requiredSkills || []), ...(role.workValues || [])]
    .some((item) => {
      const normalized = normalizeTextForMatch(item);
      return normalized && (target.includes(normalized) || normalized.includes(target));
    });
}

function deriveUnifiedProfile() {
  const assessment = getAssessmentHubSnapshotSafe() || { mbti: { completed: false }, holland: { completed: false } };
  const basics = normalizeProfileBasics(careerInterviewState.profileBasics);
  const interviewProfile = careerInterviewState.result?.profile || null;
  const capabilityModel = deriveCapabilityScores(assessment, interviewProfile, basics);
  const missingItems = [];
  if (!assessment?.mbti?.completed) missingItems.push("MBTI 测评待完成");
  if (!assessment?.holland?.completed) missingItems.push("霍兰德测评待完成");
  PROFILE_BASIC_FIELDS.forEach((key) => {
    if (!basics[key]) missingItems.push(`${PROFILE_BASIC_LABELS[key]}待补充`);
  });
  if (!interviewProfile) missingItems.push("职业访谈待完成");

  const summaryParts = [];
  if (assessment?.mbti?.completed) summaryParts.push(`MBTI ${assessment.mbti.display_type || assessment.mbti.final_type}`);
  if (assessment?.holland?.completed) summaryParts.push(`霍兰德 ${assessment.holland.code}`);
  if (basics.major) summaryParts.push(`专业 ${basics.major}`);
  if (basics.grade) summaryParts.push(`年级 ${basics.grade}`);
  if (basics.target_direction) summaryParts.push(`目标方向 ${basics.target_direction}`);
  const fallbackSummary = summaryParts.length
    ? `${summaryParts.join("，")}。当前画像已可用于岗位初筛，缺失项会在匹配和报告中显式标记。`
    : "画像基础信息仍较少，建议先完成双测评并补充基础信息。";

  return {
    assessment,
    basics,
    interview: {
      started: careerInterviewState.started,
      isComplete: careerInterviewState.isComplete,
      completionScore: clampPercent(careerInterviewState.completionScore),
      profile: interviewProfile
    },
    summary: interviewProfile?.summary || fallbackSummary,
    workValues: uniqueValues(interviewProfile?.work_values || ["成长空间", "自主性", "匹配兴趣"], 4),
    recommendedRoles: uniqueValues(interviewProfile?.recommended_roles || [], 6),
    nextSteps: uniqueValues(interviewProfile?.next_steps || [], 6),
    capabilities: capabilityModel.capabilities,
    capabilityCoverage: capabilityModel.coverage,
    missingItems
  };
}

function computeTraitMatch(role, profile) {
  const assessment = profile.assessment;
  const scores = [];
  const reasons = [];
  const mbtiType = assessment?.mbti?.completed ? String(assessment.mbti.final_type || assessment.mbti.raw_type || "") : "";
  if (mbtiType) {
    if ((role.recommendedMbti || []).includes(mbtiType)) {
      scores.push(95);
      reasons.push(`MBTI ${mbtiType} 落在岗位推荐类型内`);
    } else if ((role.recommendedMbti || []).some((code) => code.slice(1, 3) === mbtiType.slice(1, 3))) {
      scores.push(80);
      reasons.push("MBTI 与岗位推荐的核心偏好相近");
    } else {
      scores.push(58);
      reasons.push("MBTI 与岗位偏好存在一定差距");
    }
  }
  const hollandCodes = Array.isArray(assessment?.holland?.top_codes) ? assessment.holland.top_codes : [];
  if (hollandCodes.length) {
    const overlap = (role.recommendedHolland || []).filter((code) => hollandCodes.includes(code)).length;
    if (overlap >= 3) {
      scores.push(95);
      reasons.push("霍兰德代码与岗位画像高度重合");
    } else if (overlap === 2) {
      scores.push(82);
      reasons.push("霍兰德主导兴趣与岗位需求较一致");
    } else if (overlap === 1) {
      scores.push(66);
      reasons.push("霍兰德兴趣部分覆盖岗位画像");
    } else {
      scores.push(45);
      reasons.push("霍兰德兴趣与岗位画像重合度较低");
    }
  }
  return {
    score: averageValues(scores),
    reason: reasons.join("；") || "等待测评结果。"
  };
}

function computeAbilityMatch(role, profile) {
  const capabilityConfig = [
    { key: "professional", label: "专业技能", weight: 0.2 },
    { key: "innovation", label: "创新能力", weight: 0.15 },
    { key: "learning", label: "学习能力", weight: 0.15 },
    { key: "stress_tolerance", label: "抗压能力", weight: 0.12 },
    { key: "communication", label: "沟通能力", weight: 0.18 },
    { key: "internship", label: "实习能力", weight: 0.1 },
    { key: "execution", label: "执行能力", weight: 0.1 }
  ];
  const strengths = [];
  const gaps = [];
  const lines = [];
  let weightedScore = 0;
  let usedWeight = 0;
  capabilityConfig.forEach((item) => {
    const current = profile.capabilities[item.key]?.score;
    const required = Number(role.requirements[item.key] || 0);
    if (current === null || current === undefined || !required) return;
    const fitScore = clampPercent(current / required * 100);
    weightedScore += fitScore * item.weight;
    usedWeight += item.weight;
    lines.push(`${item.label} ${current}/${required}`);
    if (current + 8 < required) gaps.push(`${item.label} ${current}/${required}`);
    if (current >= required) strengths.push(`${item.label} ${current}/${required}`);
  });
  return {
    score: usedWeight ? Math.round(weightedScore / usedWeight) : null,
    coverageWeight: Math.round(usedWeight * 100),
    reason: lines.length ? `已使用 ${lines.join("、")} 计算能力匹配。` : "职业访谈和基础信息尚不足以判断能力匹配。",
    strengths: strengths.slice(0, 3),
    gaps: gaps.slice(0, 4)
  };
}

function computeMajorMatch(role, basics) {
  const major = String(basics.major || "").trim();
  if (!major) {
    return { score: null, reason: "未填写专业，专业匹配待补充。" };
  }
  if ((role.majors || []).includes("不限")) {
    return { score: 82, reason: "该岗位对专业限制较低，可通过能力与作品补足。" };
  }
  if ((role.majors || []).some((item) => major.includes(item) || item.includes(major))) {
    return { score: 100, reason: `${major} 与岗位常见专业背景直接相关。` };
  }
  const relatedGroups = [
    { keywords: ["计算机", "软件", "信息", "网络", "智能"], score: 80 },
    { keywords: ["统计", "数学", "数据", "经管"], score: 78 },
    { keywords: ["设计", "数字媒体", "美术"], score: 82 },
    { keywords: ["新闻", "传播", "中文", "文史"], score: 80 },
    { keywords: ["管理", "心理", "工商", "人力"], score: 76 },
    { keywords: ["会计", "财务", "审计", "经济"], score: 86 }
  ];
  const matchedGroup = relatedGroups.find((group) => group.keywords.some((item) => major.includes(item)) && (role.majors || []).some((item) => group.keywords.includes(item)));
  if (matchedGroup) {
    return { score: matchedGroup.score, reason: `${major} 与岗位专业要求存在相关性，但仍需用课程或项目进一步证明。` };
  }
  return { score: 38, reason: `${major} 与岗位主流专业背景相关性较弱，需要额外的项目和技能证明。` };
}

function computeWillingnessMatch(role, profile) {
  const signals = [];
  const reasons = [];
  if (profile.basics.target_direction) {
    const matched = roleMatchesText(role, profile.basics.target_direction);
    signals.push(matched ? 92 : 52);
    reasons.push(matched ? "目标方向与岗位关键词一致" : "目标方向与岗位未形成明显重合");
  }
  const interviewProfile = profile.interview.profile;
  const recommendedRoles = Array.isArray(interviewProfile?.recommended_roles) ? interviewProfile.recommended_roles : [];
  if (recommendedRoles.length) {
    const matched = recommendedRoles.some((item) => roleMatchesText(role, item));
    signals.push(matched ? 95 : 58);
    reasons.push(matched ? "访谈推荐岗位包含该方向" : "访谈推荐岗位更偏向其他方向");
  }
  const interests = Array.isArray(interviewProfile?.career_interests) ? interviewProfile.career_interests : [];
  if (interests.length) {
    const matched = interests.some((item) => roleMatchesText(role, item));
    signals.push(matched ? 85 : 60);
    reasons.push(matched ? "访谈兴趣点与岗位特征重合" : "兴趣点与岗位仅部分相关");
  }
  return {
    score: averageValues(signals),
    reason: reasons.join("；") || "尚未填写目标方向或完成访谈，意愿匹配待补充。"
  };
}

function computeRoleMatches(profile) {
  const hasSignal = Boolean(
    profile.assessment?.mbti?.completed
    || profile.assessment?.holland?.completed
    || profile.basics.major
    || profile.basics.target_direction
    || profile.interview.profile
  );
  if (!hasSignal) return [];
  return ROLE_LIBRARY.map((role) => {
    const trait = computeTraitMatch(role, profile);
    const ability = computeAbilityMatch(role, profile);
    const major = computeMajorMatch(role, profile.basics);
    const willingness = computeWillingnessMatch(role, profile);
    const weightedParts = [
      { weight: appState.weights["特质匹配"], result: trait },
      { weight: appState.weights["能力匹配"], result: ability },
      { weight: appState.weights["专业匹配"], result: major },
      { weight: appState.weights["意愿匹配"], result: willingness }
    ];
    const coverageWeight = weightedParts.reduce((sum, item) => sum + (item.result.score === null ? 0 : item.weight), 0);
    const weightedScore = weightedParts.reduce((sum, item) => sum + (item.result.score === null ? 0 : item.result.score * item.weight), 0);
    const overallScore = coverageWeight ? Math.round(weightedScore / coverageWeight) : null;
    const confidence = coverageWeight >= 85 ? "高" : coverageWeight >= 55 ? "中" : "低";
    const nextActions = uniqueValues([
      ...ability.gaps.map((item) => `补足 ${item}`),
      major.score !== null && major.score < 60 ? `为 ${role.name} 准备跨专业证明材料` : "",
      willingness.score === null ? "补充目标方向或完成访谈，提升意愿匹配精度" : "",
      `围绕 ${role.name} 的 ${role.requiredSkills.slice(0, 2).join("、")} 产出作品或经历`
    ], 4);
    return {
      ...role,
      trait,
      ability,
      major,
      willingness,
      coverageWeight,
      overallScore,
      confidence,
      summary: [trait.reason, ability.reason, major.reason, willingness.reason].filter(Boolean).slice(0, 2).join("；"),
      nextActions
    };
  }).sort((a, b) => {
    const scoreA = a.overallScore ?? a.trait.score ?? 0;
    const scoreB = b.overallScore ?? b.trait.score ?? 0;
    return scoreB - scoreA;
  });
}

function buildAgentModuleStates(profile, roles) {
  const basicsReady = PROFILE_BASIC_FIELDS.every((key) => Boolean(profile.basics[key]));
  const staticMemoryReady = Boolean(profile.assessment?.mbti?.completed || profile.assessment?.holland?.completed || basicsReady);
  const dynamicMemoryReady = Boolean(profile.interview.profile);
  const planningReady = Boolean(roles[0]);
  return [
    {
      title: "静态记忆",
      status: staticMemoryReady ? "available" : "pending",
      reason: staticMemoryReady ? "已记录测评结果与基础信息，可作为画像基底。" : "等待 MBTI / 霍兰德结果与基础信息补齐。",
      action_label: staticMemoryReady ? "已同步" : "补充基础信息"
    },
    {
      title: "动态记忆",
      status: dynamicMemoryReady ? "available" : "pending",
      reason: dynamicMemoryReady ? "访谈结果已进入动态画像，可追踪能力与行动证据。" : "接口已保留，等待访谈继续沉淀成长证据。",
      action_label: dynamicMemoryReady ? "继续访谈" : "开始访谈"
    },
    {
      title: "规划模块",
      status: planningReady ? "available" : "pending",
      reason: planningReady ? "已根据统一画像生成阶段性岗位方向与行动建议。" : "等待画像基础形成后生成阶段计划。",
      action_label: planningReady ? "查看报告" : "先完成测评"
    },
    {
      title: "工具模块",
      status: "placeholder",
      reason: "岗位查询已接入；资源推荐、进度追踪和模拟面试先保留规范接口。",
      action_label: "待接入"
    },
    {
      title: "反思模块",
      status: "placeholder",
      reason: "已保留状态字段与展示位，后续可接入月度复盘与推荐修正逻辑。",
      action_label: "即将上线"
    }
  ];
}

function renderCapabilityList(profile) {
  const labels = {
    professional: "专业技能",
    learning: "学习能力",
    communication: "沟通能力",
    innovation: "创新能力",
    stress_tolerance: "抗压能力",
    internship: "实践/实习能力",
    execution: "执行能力"
  };
  return Object.entries(labels).map(([key, label]) => {
    const item = profile.capabilities[key];
    const score = item?.score;
    const text = score === null ? "待补充" : `${score}%`;
    const hint = score === null
      ? "当前主要依赖测评与基础信息，后续用访谈/经历补强。"
      : `${(item.sources || []).join(" / ")}${item.inferred ? " · 推断值" : " · 有实证输入"}`;
    return `
      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-center justify-between gap-3 mb-2">
          <span class="text-sm font-medium text-slate-700">${escHtml(label)}</span>
          <span class="text-sm font-semibold ${score === null ? "text-slate-400" : "text-sky-700"}">${escHtml(text)}</span>
        </div>
        <div class="h-2 rounded-full bg-white overflow-hidden">
          <div class="h-full rounded-full ${score === null ? "bg-slate-200" : "bg-gradient-to-r from-sky-500 to-cyan-400"}" style="width:${score === null ? 18 : score}%"></div>
        </div>
        <p class="mt-2 text-xs text-slate-500 leading-5">${escHtml(hint)}</p>
      </div>
    `;
  }).join("");
}

function renderProfileWorkspace(profile, roles) {
  syncProfileBasicsForm();
  const topRoles = roles.slice(0, 3);
  const readinessEl = document.getElementById("profileReadinessValue");
  const summaryEl = document.getElementById("profileUnifiedSummary");
  const assessmentEl = document.getElementById("profileAssessmentDigest");
  const valuesEl = document.getElementById("profileWorkValueTags");
  const topRoleEl = document.getElementById("profileTopRoleTags");
  const nextStepEl = document.getElementById("profileNextStepList");
  const missingEl = document.getElementById("profileMissingList");
  const capabilityEl = document.getElementById("profileCapabilityList");
  const modulesEl = document.getElementById("agentModuleGrid");
  if (readinessEl) readinessEl.textContent = `${appState.profileCompletion}%`;
  if (summaryEl) summaryEl.textContent = profile.summary;
  if (assessmentEl) {
    const items = [];
    if (profile.assessment?.mbti?.completed) items.push(`MBTI：${profile.assessment.mbti.display_type || profile.assessment.mbti.final_type}`);
    if (profile.assessment?.holland?.completed) items.push(`霍兰德：${profile.assessment.holland.code}`);
    if (profile.basics.major) items.push(`专业：${profile.basics.major}`);
    if (profile.basics.grade) items.push(`年级：${profile.basics.grade}`);
    assessmentEl.textContent = items.length ? items.join("｜") : "尚未形成足够的基础画像。";
  }
  if (valuesEl) valuesEl.innerHTML = careerTagHtml(profile.workValues, "待补充工作价值观", "soft");
  if (topRoleEl) topRoleEl.innerHTML = careerTagHtml(uniqueValues([...profile.recommendedRoles, ...topRoles.map((item) => item.name)], 5), "待生成岗位方向", "accent");
  if (nextStepEl) nextStepEl.innerHTML = careerListHtml(uniqueValues([...profile.nextSteps, ...(roles[0]?.nextActions || [])], 6), "等待画像完善后生成行动建议");
  if (missingEl) missingEl.innerHTML = careerListHtml(profile.missingItems, "当前画像基础已满足本轮演示范围");
  if (capabilityEl) capabilityEl.innerHTML = renderCapabilityList(profile);
  if (modulesEl) {
    modulesEl.innerHTML = buildAgentModuleStates(profile, roles).map((item) => {
      const statusClass = item.status === "available"
        ? "bg-emerald-100 text-emerald-700"
        : item.status === "placeholder"
          ? "bg-amber-100 text-amber-700"
          : "bg-slate-200 text-slate-600";
      return `
        <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h4 class="text-base font-semibold text-slate-900">${escHtml(item.title)}</h4>
            <span class="rounded-full px-3 py-1 text-xs font-medium ${statusClass}">${escHtml(item.action_label)}</span>
          </div>
          <p class="text-sm text-slate-600 leading-6">${escHtml(item.reason)}</p>
        </div>
      `;
    }).join("");
  }
  updateProfileRadarChart({
    dimensions: [
      { name: "专业技能", score: profile.capabilities.professional.score || 0 },
      { name: "学习能力", score: profile.capabilities.learning.score || 0 },
      { name: "沟通能力", score: profile.capabilities.communication.score || 0 },
      { name: "创新能力", score: profile.capabilities.innovation.score || 0 },
      { name: "抗压能力", score: profile.capabilities.stress_tolerance.score || 0 },
      { name: "实践能力", score: profile.capabilities.internship.score || 0 },
      { name: "执行能力", score: profile.capabilities.execution.score || 0 }
    ]
  });
}

function renderMatchingWorkspace(profile, roles) {
  const topRole = roles[0] || null;
  const focused = roles.find((item) => item.id === appState.focusedRoleId) || topRole;
  const overviewEl = document.getElementById("matchingOverviewCards");
  const listEl = document.getElementById("matchingRoleList");
  const detailEl = document.getElementById("matchingRoleDetail");
  const moduleEl = document.getElementById("matchingPlaceholderModules");
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) totalEl.textContent = `${Object.values(appState.weights).reduce((sum, value) => sum + Number(value || 0), 0)}%`;

  if (overviewEl) {
    const cards = [
      { label: "当前 Top1", value: topRole?.overallScore !== null && topRole?.overallScore !== undefined ? `${topRole.overallScore}%` : "初步推荐", hint: topRole ? `${topRole.name} · 置信度${topRole.confidence}` : "等待画像输入" },
      { label: "岗位覆盖", value: `${roles.length}`, hint: "基于 10 个岗位画像库自动初筛" },
      { label: "关键差距", value: `${focused?.ability?.gaps?.length || 0}`, hint: focused ? `聚焦 ${focused.name}` : "等待选择岗位" },
      { label: "状态提示", value: profile.missingItems.length ? "待补充" : "已就绪", hint: profile.missingItems.length ? profile.missingItems[0] : "可进入报告页查看行动计划" }
    ];
    overviewEl.innerHTML = cards.map((card) => `
      <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-sm text-slate-500">${escHtml(card.label)}</p>
        <p class="mt-2 text-3xl font-bold text-slate-900">${escHtml(card.value)}</p>
        <p class="mt-2 text-xs text-slate-500 leading-5">${escHtml(card.hint)}</p>
      </div>
    `).join("");
  }

  if (listEl) {
    listEl.innerHTML = roles.map((role) => {
      const active = role.id === focused?.id;
      return `
        <div class="rounded-2xl border ${active ? "border-sky-400 bg-sky-50/70" : "border-slate-200 bg-white"} p-5 shadow-sm">
          <div class="flex items-start justify-between gap-4">
            <div>
              <p class="text-xs font-semibold tracking-[0.18em] text-slate-400 uppercase">${escHtml(role.category)}</p>
              <h4 class="mt-1 text-lg font-semibold text-slate-900">${escHtml(role.name)}</h4>
              <p class="mt-2 text-sm text-slate-600 leading-6">${escHtml(role.summary || "等待更多输入提升解释性。")}</p>
            </div>
            <div class="text-right">
              <p class="text-2xl font-bold text-sky-700">${role.overallScore === null ? "初筛" : `${role.overallScore}%`}</p>
              <p class="text-xs text-slate-500">置信度 ${escHtml(role.confidence)}</p>
            </div>
          </div>
          <div class="mt-4 grid gap-2 md:grid-cols-2">
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">特质匹配：${role.trait.score === null ? "待补充" : `${role.trait.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">能力匹配：${role.ability.score === null ? "待补充" : `${role.ability.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">专业匹配：${role.major.score === null ? "待补充" : `${role.major.score}%`}</div>
            <div class="rounded-xl bg-slate-50 px-3 py-2 text-sm text-slate-600">意愿匹配：${role.willingness.score === null ? "待补充" : `${role.willingness.score}%`}</div>
          </div>
          <div class="mt-4 flex flex-wrap gap-3">
            <button type="button" onclick="focusMatchingRole('${role.id}')" class="rounded-lg border border-sky-500 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-50 transition-all">查看解释</button>
            <button type="button" onclick="openMatchingRoleReport('${role.id}')" class="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700 transition-all">写入报告</button>
          </div>
        </div>
      `;
    }).join("");
  }

  if (detailEl) {
    detailEl.innerHTML = focused ? `
      <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold tracking-[0.18em] text-slate-400 uppercase">Focused Role</p>
            <h3 class="mt-1 text-xl font-semibold text-slate-900">${escHtml(focused.name)}</h3>
            <p class="mt-2 text-sm text-slate-600 leading-6">${escHtml(focused.path)}</p>
          </div>
          <div class="text-right">
            <p class="text-3xl font-bold text-slate-900">${focused.overallScore === null ? "初筛" : `${focused.overallScore}%`}</p>
            <p class="text-xs text-slate-500">覆盖权重 ${focused.coverageWeight}%</p>
          </div>
        </div>
        <div class="mt-5 grid gap-5 lg:grid-cols-3">
          <div>
            <p class="text-sm font-semibold text-slate-800">匹配理由</p>
            <div class="mt-3">${careerListHtml([focused.trait.reason, focused.major.reason, focused.willingness.reason], "等待更多解释")}</div>
          </div>
          <div>
            <p class="text-sm font-semibold text-slate-800">能力差距</p>
            <div class="mt-3">${careerListHtml(focused.ability.gaps, "当前没有明显硬缺口，建议继续用经历加固。")}</div>
          </div>
          <div>
            <p class="text-sm font-semibold text-slate-800">建议动作</p>
            <div class="mt-3">${careerListHtml(focused.nextActions, "等待生成行动建议")}</div>
          </div>
        </div>
      </div>
    ` : `
      <div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
        当前还没有可解释的岗位结果，请先完成测评并补充基础信息。
      </div>
    `;
  }

  if (moduleEl) {
    const placeholders = [
      { title: "资源推荐工具", reason: "课程/证书/模板推送接口已预留，后续接入真实资源库。", action: "待接入" },
      { title: "趋势分析工具", reason: "行业趋势卡位已保留，后续接入实时岗位市场与更新频率。", action: "待接入" },
      { title: "提醒追踪工具", reason: "行动提醒与任务进度字段已规范化，后续接入调度器。", action: "即将上线" }
    ];
    moduleEl.innerHTML = placeholders.map((item) => `
      <div class="rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <div class="flex items-center justify-between gap-3">
          <h4 class="text-base font-semibold text-slate-900">${escHtml(item.title)}</h4>
          <span class="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">${escHtml(item.action)}</span>
        </div>
        <p class="mt-3 text-sm text-slate-600 leading-6">${escHtml(item.reason)}</p>
      </div>
    `).join("");
  }
}

function renderReportWorkspace(profile, roles) {
  const selected = roles.find((item) => item.id === appState.focusedRoleId) || roles[0] || null;
  const bodyEl = document.getElementById("reportBody");
  const headerName = document.getElementById("reportHeaderName");
  const headerRole = document.getElementById("reportHeaderRole");
  const headerScore = document.getElementById("reportHeaderScore");
  const headerConfidence = document.getElementById("reportHeaderConfidence");
  const statusTitle = document.getElementById("reportStatusTitle");
  const statusHint = document.getElementById("reportStatusHint");
  if (headerName) headerName.textContent = getCurrentUser()?.display_name || getCurrentUser()?.displayName || getCurrentUser()?.username || "当前用户";
  if (headerRole) headerRole.textContent = selected?.name || "待确定岗位方向";
  if (headerScore) headerScore.textContent = selected?.overallScore === null || selected?.overallScore === undefined ? "初筛" : `${selected.overallScore}%`;
  if (headerConfidence) headerConfidence.textContent = selected ? `置信度 ${selected.confidence}` : "等待画像输入";
  if (statusTitle) statusTitle.textContent = appState.reportGenerated ? "报告已按最新画像刷新" : "报告为可编辑草稿";
  if (statusHint) statusHint.textContent = profile.missingItems.length
    ? `仍有 ${profile.missingItems.length} 项待补充：${profile.missingItems[0]}`
    : "关键输入已基本就绪，可直接使用这份报告作为行动底稿。";
  if (!bodyEl) return;
  if (!selected) {
    bodyEl.innerHTML = `<div class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-8 text-sm text-slate-500">当前还没有可生成的报告内容，请先完成测评和基础信息补充。</div>`;
    return;
  }
  const topRoles = roles.slice(0, 3).map((item) => `${item.name}${item.overallScore === null ? "（初筛）" : `（${item.overallScore}%）`}`);
  const stagePlan = [
    `本周：围绕 ${selected.name} 复盘现有经历，并补齐 ${selected.requiredSkills.slice(0, 2).join("、")} 相关证据。`,
    "本月：根据报告中的差距项完成一项作品、项目或课程证明。",
    "本季度：针对 Top 岗位投递实习、竞赛或项目机会，形成新的动态记忆。"
  ];
  bodyEl.innerHTML = `
    <div class="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-slate-50 p-6">
          <h4 class="text-lg font-semibold text-slate-900">测评结论</h4>
          <p class="mt-3 text-sm leading-7 text-slate-600">${escHtml(profile.summary)}</p>
          <div class="mt-4 grid gap-3 md:grid-cols-2">
            <div class="rounded-xl bg-white p-4">
              <p class="text-xs text-slate-500">MBTI</p>
              <p class="mt-1 font-semibold text-slate-900">${escHtml(profile.assessment?.mbti?.completed ? (profile.assessment.mbti.display_type || profile.assessment.mbti.final_type) : "待完成")}</p>
            </div>
            <div class="rounded-xl bg-white p-4">
              <p class="text-xs text-slate-500">霍兰德</p>
              <p class="mt-1 font-semibold text-slate-900">${escHtml(profile.assessment?.holland?.completed ? profile.assessment.holland.code : "待完成")}</p>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <h4 class="text-lg font-semibold text-slate-900">Top 岗位方向</h4>
          <div class="mt-4">${careerListHtml(topRoles, "等待生成岗位方向")}</div>
          <p class="mt-4 text-sm leading-7 text-slate-600">当前主推岗位为 ${escHtml(selected.name)}，路径建议：${escHtml(selected.path)}。</p>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <h4 class="text-lg font-semibold text-slate-900">差距驱动行动计划</h4>
          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <p class="text-sm font-semibold text-slate-800">重点缺口</p>
              <div class="mt-3">${careerListHtml(selected.ability.gaps, "当前没有明显高优先级缺口，可直接强化项目证据。")}</div>
            </div>
            <div>
              <p class="text-sm font-semibold text-slate-800">建议动作</p>
              <div class="mt-3">${careerListHtml(selected.nextActions, "等待生成动作建议")}</div>
            </div>
          </div>
        </section>
      </div>

      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <h4 class="text-lg font-semibold text-slate-900">阶段性职业规划</h4>
          <div class="mt-4">${careerListHtml(stagePlan, "等待生成阶段计划")}</div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-slate-50 p-6">
          <h4 class="text-lg font-semibold text-slate-900">工作价值观与偏好</h4>
          <div class="mt-4">${careerTagHtml(profile.workValues, "待补充价值观", "soft")}</div>
          <p class="mt-4 text-sm text-slate-600 leading-6">专业：${escHtml(profile.basics.major || "待补充")}｜年级：${escHtml(profile.basics.grade || "待补充")}｜目标城市：${escHtml(profile.basics.target_city || "待补充")}</p>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-6">
          <h4 class="text-lg font-semibold text-slate-900">待接入模块</h4>
          <div class="mt-4 space-y-3 text-sm text-slate-600">
            <div class="rounded-xl border border-dashed border-slate-300 p-4">资源推荐：已保留接口，后续对接课程、证书和模板库。</div>
            <div class="rounded-xl border border-dashed border-slate-300 p-4">趋势分析：已保留接口，后续接入岗位市场趋势。</div>
            <div class="rounded-xl border border-dashed border-slate-300 p-4">提醒追踪：已保留接口，后续接入任务提醒与复盘节奏。</div>
          </div>
        </section>
      </div>
    </div>
  `;
  updateReportDates(new Date());
}

function refreshUnifiedExperience() {
  const profile = deriveUnifiedProfile();
  const roles = computeRoleMatches(profile);
  profile.recommendedRoles = uniqueValues([...profile.recommendedRoles, ...roles.slice(0, 3).map((item) => item.name)], 6);
  profile.nextSteps = uniqueValues([...profile.nextSteps, ...(roles[0]?.nextActions || [])], 6);
  profile.moduleStates = buildAgentModuleStates(profile, roles);

  appState.derivedProfile = profile;
  appState.matchingRoles = roles;
  if (!roles.some((item) => item.id === appState.focusedRoleId)) {
    appState.focusedRoleId = roles[0]?.id || "";
  }
  appState.profileCompletion = Math.round(
    (profile.assessment?.mbti?.completed ? 15 : 0)
    + (profile.assessment?.holland?.completed ? 15 : 0)
    + (PROFILE_BASIC_FIELDS.filter((key) => profile.basics[key]).length / PROFILE_BASIC_FIELDS.length) * 30
    + clampPercent(profile.interview.completionScore) * 0.4
  );
  appState.profileComplete = Boolean(
    profile.assessment?.mbti?.completed
    && profile.assessment?.holland?.completed
    && PROFILE_BASIC_FIELDS.every((key) => profile.basics[key])
  );
  appState.matchingComplete = roles.length > 0 && Boolean(profile.assessment?.mbti?.completed || profile.assessment?.holland?.completed);
  appState.score = roles[0]?.overallScore || roles[0]?.trait?.score || appState.profileCompletion;

  renderProfileWorkspace(profile, roles);
  renderMatchingWorkspace(profile, roles);
  renderReportWorkspace(profile, roles);
  updateDashboardMetrics();
}

function focusMatchingRole(roleId) {
  appState.focusedRoleId = String(roleId || "");
  renderMatchingWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
}

function openMatchingRoleReport(roleId) {
  focusMatchingRole(roleId);
  showSection("report");
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
  const displayName = getCurrentUser()?.display_name || getCurrentUser()?.displayName || getCurrentUser()?.username || "同学";
  const h = now.getHours();
  let greeting = "晚上好";
  let icon = "☾";
  if (h >= 6 && h < 12) { greeting = "早上好"; icon = "☀"; }
  if (h >= 12 && h < 18) { greeting = "下午好"; icon = "🌤"; }
  const dayIndex = Math.ceil((now - new Date(now.getFullYear(), 0, 1)) / 86400000);
  if (title) title.textContent = `${greeting}，${displayName}${icon}`;
  if (subtitle) subtitle.textContent = `今天是 ${formatDateCN(now)}，年度第 ${dayIndex} 天，系统正在用最新测评、访谈和基础信息更新你的职业画像。`;
}

function updateTaskPanels(explored) {
  const exploreStatus = document.getElementById("taskJobExploreStatus");
  const exploreTag = document.getElementById("taskJobExploreTag");
  const matchingStatus = document.getElementById("taskMatchingStatus");
  const matchingTag = document.getElementById("taskMatchingTag");
  const progressHint = document.getElementById("taskProgressHint");
  const reportBtn = document.getElementById("generateReportBtn");
  const exploredDone = explored >= 3;
  if (exploreStatus) exploreStatus.textContent = `已形成 ${explored} 个初步岗位方向`;
  setTagState(exploreTag, exploredDone ? "done" : "processing");
  if (matchingStatus) matchingStatus.textContent = appState.matchingRoles.length
    ? `已生成 ${appState.matchingRoles.length} 个岗位匹配结果`
    : "等待画像输入生成匹配";
  setTagState(matchingTag, appState.matchingComplete ? "done" : "processing");
  const doneCount = [appState.profileComplete, exploredDone, appState.matchingComplete, appState.reportGenerated].filter(Boolean).length;
  if (progressHint) progressHint.textContent = `已完成 ${doneCount}/4 个关键任务`;
  if (reportBtn) {
    if (appState.reportGenerated) {
      reportBtn.textContent = "报告已更新";
      reportBtn.classList.add("bg-green-600", "hover:bg-green-700");
      reportBtn.classList.remove("bg-purple-600", "hover:bg-purple-700");
    } else {
      reportBtn.textContent = "生成当前报告";
      reportBtn.classList.add("bg-purple-600", "hover:bg-purple-700");
      reportBtn.classList.remove("bg-green-600", "hover:bg-green-700");
    }
  }
}

function updateDashboardMetrics() {
  const roles = Array.isArray(appState.matchingRoles) ? appState.matchingRoles : [];
  const profile = appState.derivedProfile;
  const topRoleData = roles[0];
  const explored = roles.slice(0, 3).length;
  const topRate = topRoleData?.overallScore || topRoleData?.trait?.score || 0;
  const topJob = topRoleData?.name || "等待岗位方向";
  const pending = profile ? profile.missingItems.length + (appState.reportGenerated ? 0 : 1) : 4;
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
  if (scoreTrend) scoreTrend.textContent = topRoleData ? `Top1 置信度 ${topRoleData.confidence}` : "等待画像输入";
  if (profileHint) profileHint.textContent = profile?.missingItems?.length ? `待补充 ${profile.missingItems.length} 项` : "画像基础已就绪";
  if (pendingHint) pendingHint.textContent = pending === 0 ? "全部完成" : "优先补基础信息和访谈";
  updateTaskPanels(explored);
}

function markReportGenerated(source = "view") {
  if (!appState.reportGenerated) {
    appState.reportGenerated = true;
    updateReportDates(new Date());
    if (source !== "view") {
      addLiveActivity("Report regenerated with latest profile data");
    }
  }
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
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
  const profile = appState.derivedProfile || deriveUnifiedProfile();
  if (profile.missingItems.length) {
    showToast("可生成初步报告", `当前仍有待补充项：${profile.missingItems.slice(0, 2).join("、")}`, "warning", 2400);
  } else {
    showToast("报告就绪", "统一画像与岗位匹配已同步完成。", "success", 1800);
  }
  showSection("report");
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
  const valueLabel = slider.closest(".matching-weight-card")?.querySelector(".matching-weight-value");
  if (valueLabel) valueLabel.textContent = `${value}%`;
  const sliders = Array.from(document.querySelectorAll("input[type='range'][onchange*='updateWeight']"));
  const total = sliders.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) {
    totalEl.textContent = `${total}%`;
    totalEl.classList.toggle("text-orange-600", total !== 100);
    totalEl.classList.toggle("text-sky-600", total === 100);
  }
}

function recalculateMatching() {
  const total = Object.values(appState.weights).reduce((sum, n) => sum + n, 0);
  if (total !== 100) return showToast("权重总和不正确", "四个分项权重之和必须等于 100%。", "warning", 2200);
  refreshUnifiedExperience();
  addLiveActivity("Matching strategy refreshed with new weight settings");
  showToast("匹配结果已刷新", "系统已按最新权重重新排序岗位结果。", "success", 1800);
}

function recalculateProfile() {
  refreshUnifiedExperience();
  addLiveActivity("Profile synthesis refreshed from latest assessment and interview state");
  showToast("画像已重算", "测评、访谈和基础信息已经重新同步。", "success", 1800);
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
function editReport() { showToast("报告说明", "当前报告由统一画像实时生成，暂不提供段落级手改。", "info", 1800); }
function saveReport() { markReportGenerated("save"); showToast("报告已保存", "当前草稿状态已刷新到本地会话。", "success", 1500); addLiveActivity("Report draft saved by user"); }

function exportReport() {
  showToast("正在导出", "系统正在准备当前报告内容。", "info", 1000);
  setTimeout(() => {
    markReportGenerated("export");
    showToast("导出完成", "报告内容已整理完成，可继续扩展 PDF 流程。", "success", 1800);
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
    scheduleAnalyticsInit(allJobsData);

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
    // 防止重复创建（canvas 已被 Chart.js 占用时先销毁旧实例）
    if (appState.dashboardRadarChart) { appState.dashboardRadarChart.destroy(); appState.dashboardRadarChart = null; }
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
    if (appState.profileRadarChart) { appState.profileRadarChart.destroy(); appState.profileRadarChart = null; }
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
  syncProfileBasicsForm();
  refreshUnifiedExperience();
  addLiveActivity("System initialized. Dynamic monitoring is active.");
  window.addEventListener("assessment-hub:updated", () => {
    refreshUnifiedExperience();
  });
  Promise.resolve(authReady).finally(() => {
    updateCareerInterviewConfigStatus();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    refreshUnifiedExperience();
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

// ── 设置面板（头像点击） ────────────────────────────────────────────────────────

let _settingsPanelOpen = false;
let _settingsOutsideListener = null;
let _cachedAvailableModels = [];   // 全局缓存：拉取到的模型列表，切换板块后不需重新获取

function toggleSettingsPanel(event) {
  if (event) event.stopPropagation();
  if (_settingsPanelOpen) {
    closeSettingsPanel();
  } else {
    openSettingsPanel();
  }
}

function openSettingsPanel() {
  const panel = document.getElementById("settingsPanel");
  if (!panel) return;
  panel.classList.remove("hidden");
  _settingsPanelOpen = true;
  loadSettingsPanelData();
  setTimeout(() => {
    _settingsOutsideListener = (e) => {
      if (!panel.contains(e.target)) closeSettingsPanel();
    };
    document.addEventListener("click", _settingsOutsideListener);
  }, 30);
}

function closeSettingsPanel() {
  const panel = document.getElementById("settingsPanel");
  if (panel) panel.classList.add("hidden");
  _settingsPanelOpen = false;
  if (_settingsOutsideListener) {
    document.removeEventListener("click", _settingsOutsideListener);
    _settingsOutsideListener = null;
  }
}

function _setSettingsStatus(text, state) {
  const dot = document.getElementById("settingsStatusDot");
  const textEl = document.getElementById("settingsStatusText");
  const colorMap = { ok: "bg-green-400", warn: "bg-amber-400", error: "bg-red-400", loading: "bg-gray-300" };
  if (dot) dot.className = `w-2 h-2 rounded-full flex-shrink-0 ${colorMap[state] || colorMap.loading}`;
  if (textEl) textEl.textContent = text;
}

function _populateModelDropdown(models, currentModel) {
  const select = document.getElementById("settingsModelSelect");
  if (!select) return;
  const prev = currentModel || select.value;
  select.innerHTML = `<option value="">-- 选择模型 --</option>`;
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    if (m === prev) opt.selected = true;
    select.appendChild(opt);
  });
}

async function loadSettingsPanelData() {
  _setSettingsStatus("正在加载配置…", "loading");
  const user = getCurrentUser();
  if (!user) {
    _setSettingsStatus("请先登录", "warn");
    return;
  }
  const labelEl = document.getElementById("settingsPanelUserLabel");
  if (labelEl) {
    labelEl.textContent = `${user.display_name || user.username}  ·  ${user.role === "super_admin" ? "系统管理员" : "普通用户"}`;
  }

  const isAdmin = isSuperAdminUser();
  const adminSection = document.getElementById("settingsAdminSection");
  if (adminSection) adminSection.classList.toggle("hidden", !isAdmin);

  try {
    const config = await fetchManagedLlmConfig("career_interview", true);
    if (isAdmin) {
      const bu = document.getElementById("settingsBaseUrl");
      const ak = document.getElementById("settingsApiKey");
      if (bu) bu.value = config.base_url || "";
      if (ak) ak.value = config.api_key || "";
    }
    if (config.configured) {
      _setSettingsStatus(`已配置  ·  当前模型：${config.model}`, "ok");
      if (_cachedAvailableModels.length > 0) {
        // 已有缓存，直接渲染，不发起网络请求
        _populateModelDropdown(_cachedAvailableModels, config.model);
        const btn = document.getElementById("settingsFetchModelsBtn");
        if (btn) btn.textContent = `✓ ${_cachedAvailableModels.length} 个模型`;
      } else {
        await fetchSettingsModels();
      }
    } else {
      _setSettingsStatus(
        isAdmin ? "尚未配置，请填写 Base URL 和 API Key" : "等待系统管理员配置",
        "warn"
      );
      if (_cachedAvailableModels.length > 0) {
        _populateModelDropdown(_cachedAvailableModels, config.model);
        const btn = document.getElementById("settingsFetchModelsBtn");
        if (btn) btn.textContent = `✓ ${_cachedAvailableModels.length} 个模型`;
      } else if (config.model) {
        const select = document.getElementById("settingsModelSelect");
        if (select) {
          select.innerHTML = `<option value="${escHtml(config.model)}" selected>${escHtml(config.model)}</option>`;
        }
      }
    }
  } catch (err) {
    _setSettingsStatus("加载失败：" + err.message, "error");
  }
}

async function fetchSettingsModels() {
  const btn = document.getElementById("settingsFetchModelsBtn");
  if (btn) btn.textContent = "⏳ 获取中…";

  try {
    let url = "/api/llm-models";
    let options = { credentials: "same-origin" };

    if (isSuperAdminUser()) {
      const baseUrl = (document.getElementById("settingsBaseUrl")?.value || "").trim();
      const apiKey = (document.getElementById("settingsApiKey")?.value || "").trim();
      if (baseUrl && apiKey) {
        url = "/api/llm-models/preview";
        options = {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base_url: baseUrl, api_key: apiKey })
        };
      }
    }

    const res = await fetch(url, options);
    const data = await res.json();
    if (data.models && data.models.length > 0) {
      _cachedAvailableModels = data.models;   // 写入全局缓存
      const currentModel = getStoredCareerInterviewConfig().model;
      _populateModelDropdown(data.models, currentModel);
      if (btn) btn.textContent = `✓ ${data.models.length} 个模型`;
    } else {
      showToast("获取模型", data.message || "未获取到模型列表，请检查配置", "warning", 2400);
      if (btn) btn.textContent = "🔄 获取列表";
    }
  } catch (err) {
    showToast("获取模型失败", err.message, "error", 2400);
    if (btn) btn.textContent = "🔄 获取列表";
  }
}

async function saveSettingsAdmin() {
  if (!isSuperAdminUser()) return;
  const baseUrl = (document.getElementById("settingsBaseUrl")?.value || "").trim();
  const apiKey = (document.getElementById("settingsApiKey")?.value || "").trim();
  const model = (document.getElementById("settingsModelSelect")?.value || "").trim();

  if (!baseUrl || !apiKey) {
    showToast("配置不完整", "请填写 Base URL 和 API Key", "warning", 2000);
    return;
  }
  if (!model) {
    showToast("请选择模型", "请先点击「获取列表」，再选择一个模型", "warning", 2000);
    return;
  }

  try {
    await saveManagedLlmConfig("career_interview", { base_url: baseUrl, api_key: apiKey, model });
    await saveManagedLlmConfig("assessment_hub", { base_url: baseUrl, api_key: apiKey, model });
    userWorkspaceState.llmConfigs.career_interview = null;
    userWorkspaceState.llmConfigs.assessment_hub = null;
    _cachedAvailableModels = [];   // 换了 API，清除旧模型缓存
    _setSettingsStatus(`已保存  ·  ${model}`, "ok");
    showToast("系统配置已保存", `模型：${model}`, "success", 1600);
    updateCareerInterviewConfigStatus();
    if (typeof window.assessmentHubUpdateConfigStatus === "function") {
      window.assessmentHubUpdateConfigStatus();
    }
    await fetchSettingsModels();   // 用新凭据重新拉一次，填充缓存
  } catch (err) {
    showToast("保存失败", err.message, "error", 2400);
  }
}

async function saveSettingsModel() {
  const model = (document.getElementById("settingsModelSelect")?.value || "").trim();
  if (!model) {
    showToast("请选择模型", "请先从列表中选择一个模型", "warning", 2000);
    return;
  }
  try {
    const res = await fetch("/api/llm-config/model", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || "更新失败");
    if (userWorkspaceState.llmConfigs.career_interview) {
      userWorkspaceState.llmConfigs.career_interview.model = model;
    }
    if (userWorkspaceState.llmConfigs.assessment_hub) {
      userWorkspaceState.llmConfigs.assessment_hub.model = model;
    }
    _setSettingsStatus(`模型已选：${model}`, "ok");
    showToast("模型已更新", `当前模型：${model}`, "success", 1600);
    updateCareerInterviewConfigStatus();
    if (typeof window.assessmentHubUpdateConfigStatus === "function") {
      window.assessmentHubUpdateConfigStatus();
    }
  } catch (err) {
    showToast("更新模型失败", err.message, "error", 2400);
  }
}
