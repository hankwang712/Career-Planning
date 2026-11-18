// 全局常量之外的基础设施：日期与提示、登录提示、接口封装、会话缓存、岗位索引
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function getApiBase() {
  const raw = String(window.__API_BASE__ || "").trim();
  return raw.replace(/\/+$/, "");
}

function resolveApiUrl(path) {
  const target = String(path || "").trim();
  if (!target) return target;
  if (/^https?:\/\//i.test(target)) return target;
  const base = getApiBase();
  if (!base) return target;
  if (target.startsWith("/")) return `${base}${target}`;
  return `${base}/${target}`;
}

function getDefaultProfileBasics() {
  return {
    gender: "",
    major: "",
    grade: "",
    target_city: "",
    target_direction: ""
  };
}

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

function formatRelativeTimeCN(value) {
  const ts = Number(value || 0);
  if (!ts) return "刚刚";
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  try {
    return new Date(ts * 1000).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  } catch (_) {
    return "较早";
  }
}

function addMonths(date, count) {
  const d = new Date(date.getTime());
  d.setMonth(d.getMonth() + count);
  return d;
}

function getActiveAuthFeedbackEl() {
  if (!document.getElementById("loginAuthFeedback")) {
    return document.getElementById("authMessage");
  }
  const startupScreen = document.getElementById("startupScreen");
  const isLogin = startupScreen ? startupScreen.classList.contains("auth-mode-login") : true;
  return document.getElementById(isLogin ? "loginAuthFeedback" : "registerAuthFeedback");
}

function clearInactiveAuthFeedback(isLogin) {
  const otherId = isLogin ? "registerAuthFeedback" : "loginAuthFeedback";
  const other = document.getElementById(otherId);
  if (!other) return;
  other.textContent = "";
  other.className = "auth-feedback";
  other.setAttribute("role", "status");
}

function showAuthMessage(message, type = "info") {
  const el = getActiveAuthFeedbackEl();
  if (!el) return;
  const isInline = el.id === "loginAuthFeedback" || el.id === "registerAuthFeedback";
  el.textContent = message || "";
  if (isInline) {
    el.className = "auth-feedback";
    if (type === "success") el.classList.add("success");
    else if (type === "error") el.classList.add("error");
    else if (type === "warning") el.classList.add("warning");
    else el.classList.add("is-muted");
    el.setAttribute("role", type === "error" ? "alert" : "status");
    el.setAttribute("aria-live", type === "error" ? "assertive" : "polite");
  } else {
    el.className = "auth-message";
    if (type === "success" || type === "error" || type === "warning") el.classList.add(type);
  }
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
      await loadScriptOnce("/static/vendor/echarts.min.js", "echarts");
      await loadScriptOnce("/static/vendor/china.js", "china-map");
      await loadScriptOnce("/static/jobs-geo.js", "jobs-geo");
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
  const owner = getCurrentUser()?.username || "";
  const epoch = accountRequestEpoch;
  const accountBound = /^\/api\/(user-state\/|resume\/|career-report\/|career-profile|job-market|profile|account|community-feed|career-interview|llm|resume-llm|deep-test|tools\/)/.test(url);
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if ((url.startsWith("/api/auth/") || url.startsWith("/api/career-profile") || url.startsWith("/api/job-market")) && ["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    Object.assign(headers, await window.CareerAuth.headers());
  }
  let body = options.body;
  if (body && typeof body !== "string" && !(body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  }
  const isGetWithoutBody = method === "GET" && !body;
  const dedupeKey = isGetWithoutBody ? `${owner}::${epoch}::${method}::${url}::${JSON.stringify(headers)}` : "";
  if (isGetWithoutBody && inFlightGetRequests.has(dedupeKey)) {
    return inFlightGetRequests.get(dedupeKey);
  }

  const runner = (async () => {
    const response = await fetch(resolveApiUrl(url), {
      ...options,
      method,
      headers,
      body,
      credentials: options.credentials || "include"
    });

    const payload = await response.json().catch(() => ({}));
    const responseOwner = decodeURIComponent(response.headers.get("X-Workspace-Owner") || "");
    if (!url.startsWith("/api/auth/") && (accountBound || responseOwner)) {
      if (owner !== (getCurrentUser()?.username || "") || epoch !== accountRequestEpoch || (responseOwner && responseOwner !== owner)) {
        const error = new Error("账号已切换，本次请求的结果已丢弃。");
        error.code = "ACCOUNT_CHANGED";
        if (responseOwner && responseOwner !== owner && epoch === accountRequestEpoch) window.location.reload();
        throw error;
      }
    }
    if (!response.ok) {
      if (response.status === 401) {
        userWorkspaceState.currentUser = null;
        userWorkspaceState.scopedData.career_interview = null;
        userWorkspaceState.scopedData.assessment_hub = null;
        userWorkspaceState.scopedData.resume_profile = null;
        userWorkspaceState.scopedData.career_report = null;
        userWorkspaceState.scopedData.profile_portrait = null;
        userWorkspaceState.scopedData.account_avatar = null;
        userWorkspaceState.scopedData.profile_snapshot = null;
        userWorkspaceState.scopedData.career_matching = null;
        userWorkspaceState.scopedData.news_context = null;
        userWorkspaceState.scopedDataLoaded.career_interview = false;
        userWorkspaceState.scopedDataLoaded.assessment_hub = false;
        userWorkspaceState.scopedDataLoaded.resume_profile = false;
        userWorkspaceState.scopedDataLoaded.career_report = false;
        userWorkspaceState.scopedDataLoaded.profile_portrait = false;
        userWorkspaceState.scopedDataLoaded.account_avatar = false;
        userWorkspaceState.scopedDataLoaded.profile_snapshot = false;
        userWorkspaceState.scopedDataLoaded.career_matching = false;
        userWorkspaceState.scopedDataLoaded.news_context = false;
        if (typeof lockApp === "function") lockApp();
        emitAuthStateChange();
      }
      const error = new Error(payload.message || `请求失败：${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  })();

  if (isGetWithoutBody) {
    inFlightGetRequests.set(dedupeKey, runner);
    runner.then(() => inFlightGetRequests.delete(dedupeKey), () => inFlightGetRequests.delete(dedupeKey));
  }
  return runner;
}

function getDefaultScopedData(scope) {
  return scope === "career_interview" ? null : null;
}

async function fetchScopedUserState(scope, force = false) {
  if (!force && userWorkspaceState.scopedDataLoaded?.[scope]) {
    return userWorkspaceState.scopedData[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultScopedData(scope);
  const payload = await requestJson(`/api/user-state/${scope}`);
  userWorkspaceState.scopedData[scope] = payload.data ?? null;
  if (userWorkspaceState.scopedDataLoaded && Object.prototype.hasOwnProperty.call(userWorkspaceState.scopedDataLoaded, scope)) {
    userWorkspaceState.scopedDataLoaded[scope] = true;
  }
  return userWorkspaceState.scopedData[scope];
}

async function loadProfilePortraitState(force = false) {
  if (!isAuthenticatedUser()) return null;
  const data = await fetchScopedUserState("profile_portrait", force);
  userWorkspaceState.scopedData.profile_portrait = data ?? null;
  userWorkspaceState.scopedDataLoaded.profile_portrait = true;
  return userWorkspaceState.scopedData.profile_portrait;
}

async function saveScopedUserState(scope, data) {
  if (!isAuthenticatedUser()) return null;
  await requestJson(`/api/user-state/${scope}`, {
    method: "PUT",
    body: { data }
  });
  userWorkspaceState.scopedData[scope] = data ?? null;
  if (userWorkspaceState.scopedDataLoaded && Object.prototype.hasOwnProperty.call(userWorkspaceState.scopedDataLoaded, scope)) {
    userWorkspaceState.scopedDataLoaded[scope] = true;
  }
  return userWorkspaceState.scopedData[scope];
}

async function mergeScopedUserState(scope, patch) {
  const current = (userWorkspaceState.scopedData?.[scope] && typeof userWorkspaceState.scopedData[scope] === "object")
    ? userWorkspaceState.scopedData[scope]
    : {};
  const next = { ...current, ...(patch && typeof patch === "object" ? patch : {}) };
  return saveScopedUserState(scope, next);
}

async function requestFormData(url, formData, options = {}) {
  const response = await fetch(resolveApiUrl(url), {
    method: options.method || "POST",
    body: formData,
    credentials: options.credentials || "include"
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.message || `请求失败：${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function formatUnixTime(ts) {
  if (!ts) return "--";
  try {
    return new Date(Number(ts) * 1000).toLocaleString("zh-CN", { hour12: false });
  } catch (_) {
    return "--";
  }
}

// 功能页面仅使用服务端公开的模型名称与配置状态。
async function fetchLlmStatus() {
  const payload = await requestJson("/api/llm-status");
  const config = {
    base_url: "",
    api_key: "",
    model: String(payload.model || "").trim(),
    configured: Boolean(payload.configured),
    editable: false,
    api_key_masked: ""
  };
  userWorkspaceState.llmConfigs.career_interview = config;
  userWorkspaceState.llmConfigs.assessment_hub = config;
  return config;
}

async function fetchManagedLlmConfig(scope, force = false) {
  if (!force && userWorkspaceState.llmConfigs[scope]) {
    return userWorkspaceState.llmConfigs[scope];
  }
  if (!isAuthenticatedUser()) return getDefaultCareerInterviewConfig();
  return fetchLlmStatus();
}

async function fetchActiveLlmRuntimeConfig(force = false) {
  if (!isAuthenticatedUser()) return getDefaultCareerInterviewConfig();
  const cached = userWorkspaceState.llmConfigs.career_interview;
  if (!force && cached && cached.configured) return cached;
  return fetchLlmStatus();
}

function readSessionCache(key) {
  let raw = null;
  try {
    raw = sessionStorage.getItem(key);
  } catch (error) {
    console.warn("sessionStorage read failed", error);
    return null;
  }
  const payload = safeJsonParse(raw, null);
  if (!payload || typeof payload !== "object") return null;
  if (Number(payload.expiresAt || 0) < Date.now()) {
    try {
      sessionStorage.removeItem(key);
    } catch (error) {
      console.warn("sessionStorage remove failed", error);
    }
    return null;
  }
  return payload.data ?? null;
}

function isStorageQuotaExceeded(error) {
  if (!error) return false;
  const name = String(error.name || "");
  const code = Number(error.code || 0);
  if (name === "QuotaExceededError" || name === "NS_ERROR_DOM_QUOTA_REACHED") return true;
  if (code === 22 || code === 1014) return true;
  return /quota/i.test(String(error.message || ""));
}

function clearSessionCacheEntries(keysOrPrefixes = []) {
  if (!Array.isArray(keysOrPrefixes) || keysOrPrefixes.length === 0) return;
  const markers = keysOrPrefixes.map((item) => String(item || "")).filter(Boolean);
  if (markers.length === 0) return;
  const targets = [];
  for (let i = 0; i < sessionStorage.length; i += 1) {
    const key = sessionStorage.key(i);
    if (!key) continue;
    if (markers.some((marker) => key === marker || key.startsWith(marker))) {
      targets.push(key);
    }
  }
  targets.forEach((key) => {
    try {
      sessionStorage.removeItem(key);
    } catch (error) {
      console.warn("sessionStorage cleanup failed", error);
    }
  });
}

function writeSessionCache(key, data, ttlMs = JOBS_CACHE_TTL_MS) {
  const payload = JSON.stringify({
    expiresAt: Date.now() + ttlMs,
    data
  });
  try {
    sessionStorage.setItem(key, payload);
    return;
  } catch (error) {
    if (!isStorageQuotaExceeded(error)) {
      console.warn("sessionStorage write failed", error);
      return;
    }
  }

  clearSessionCacheEntries([JOBS_LIST_CACHE_PREFIX, JOBS_DETAIL_CACHE_PREFIX, JOBS_CITIES_CACHE_KEY]);
  try {
    sessionStorage.setItem(key, payload);
  } catch (error) {
    console.warn("sessionStorage quota exceeded, skip cache", error);
  }
}

async function fetchJsonWithSessionCache(url, cacheKey, ttlMs = JOBS_CACHE_TTL_MS) {
  const cached = readSessionCache(cacheKey);
  if (cached) return cached;
  const response = await fetch(resolveApiUrl(url), {
    credentials: "include"
  });
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
  const opts = {};
  if (Array.isArray(jobsAnalyticsBossCities) && jobsAnalyticsBossCities.length) {
    opts.bossCities = jobsAnalyticsBossCities;
  }
  if (jobsAnalyticsCitySupplementExtra && typeof jobsAnalyticsCitySupplementExtra === "object") {
    opts.citySupplementExtra = jobsAnalyticsCitySupplementExtra;
  }
  const runner = () => window.initJobsAnalytics(jobs, opts);
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
