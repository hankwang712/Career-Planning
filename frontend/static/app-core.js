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

function getDefaultCareerInterviewConfig() {
  return {
    base_url: "",
    api_key: "",
    model: "gpt-4o-mini"
  };
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
  const method = String(options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if ((url.startsWith("/api/career-profile") || url.startsWith("/api/job-market")) && ["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    Object.assign(headers, await window.CareerAuth.headers());
  }
  let body = options.body;
  if (body && typeof body !== "string" && !(body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  }
  const isGetWithoutBody = method === "GET" && !body;
  const dedupeKey = isGetWithoutBody ? `${method}::${url}::${JSON.stringify(headers)}` : "";
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
    if (!response.ok) {
      const error = Object.assign(new Error(payload.message || `请求失败：${response.status}`), { status: response.status, code: payload.code });
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
    const error = Object.assign(new Error(payload.message || `请求失败：${response.status}`), { status: response.status, code: payload.code });
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
