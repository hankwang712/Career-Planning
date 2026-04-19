const LAST_LOGIN_EMAIL_KEY = "last_login_email";

function resolveApiUrl(path) {
  const base = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
  return base ? `${base}${path}` : path;
}

async function requestJson(path, options = {}) {
  const method = options.method || "GET";
  const headers = { ...(options.headers || {}) };
  const init = {
    method,
    credentials: options.credentials || "include",
    headers
  };

  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(resolveApiUrl(path), init);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || payload.message || "Request failed.");
  }
  return payload;
}

function persistLoginEmail(email) {
  const normalized = String(email || "").trim();
  if (!normalized) return;

  try {
    window.localStorage.setItem(LAST_LOGIN_EMAIL_KEY, normalized);
  } catch {
    // Ignore storage failures and keep auth flow moving.
  }
}

function wirePasswordVisibilityToggles() {
  document.querySelectorAll("[data-password-toggle-for]").forEach((btn) => {
    const targetId = btn.getAttribute("data-password-toggle-for");
    const input = targetId ? document.getElementById(targetId) : null;
    if (!input || input.tagName !== "INPUT") return;

    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const nextVisible = input.type === "password";
      input.type = nextVisible ? "text" : "password";
      btn.classList.toggle("is-password-visible", nextVisible);
      btn.setAttribute("aria-pressed", nextVisible ? "true" : "false");
      btn.setAttribute("aria-label", nextVisible ? "隐藏密码" : "显示密码");
    });
  });
}

function restoreLastLoginEmail() {
  const loginInput = document.getElementById("loginUsername");
  const loginPassword = document.getElementById("loginPassword");
  if (!loginInput) return;

  try {
    const savedEmail = window.localStorage.getItem(LAST_LOGIN_EMAIL_KEY);
    if (savedEmail) {
      loginInput.value = savedEmail;
    }
  } catch {
    // Ignore storage failures and leave fields empty.
  }

  if (loginPassword) {
    loginPassword.value = "";
    loginPassword.type = "password";
    const toggle = document.querySelector('[data-password-toggle-for="loginPassword"]');
    if (toggle) {
      toggle.classList.remove("is-password-visible");
      toggle.setAttribute("aria-pressed", "false");
      toggle.setAttribute("aria-label", "显示密码");
    }
  }
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

function showAuthMessage(message, tone = "info") {
  const el = getActiveAuthFeedbackEl();
  if (!el) return;

  const isInline = el.id === "loginAuthFeedback" || el.id === "registerAuthFeedback";
  el.textContent = message || "";
  if (isInline) {
    el.className = "auth-feedback";
    if (tone === "success") el.classList.add("success");
    else if (tone === "error") el.classList.add("error");
    else if (tone === "warning") el.classList.add("warning");
    else el.classList.add("is-muted");
    el.setAttribute("role", tone === "error" ? "alert" : "status");
    el.setAttribute("aria-live", tone === "error" ? "assertive" : "polite");
  } else {
    el.className = "auth-message";
    if (tone === "success" || tone === "error" || tone === "warning") {
      el.classList.add(tone);
    }
  }
}

function switchAuthTab(tab) {
  const isLogin = tab === "login";
  const startupScreen = document.getElementById("startupScreen");
  const loginBtn = document.getElementById("loginTabBtn");
  const registerBtn = document.getElementById("registerTabBtn");

  if (startupScreen) {
    startupScreen.classList.toggle("auth-mode-login", isLogin);
    startupScreen.classList.toggle("auth-mode-register", !isLogin);
  }
  if (loginBtn) loginBtn.classList.toggle("active", isLogin);
  if (registerBtn) registerBtn.classList.toggle("active", !isLogin);

  clearInactiveAuthFeedback(isLogin);

  if (isLogin) {
    showAuthMessage("支持邮箱或演示账号 system 登录。", "info");
  } else {
    showAuthMessage("请使用邮箱与密码完成注册。", "info");
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) {
    showAuthMessage("请输入账号和密码。", "error");
    return;
  }

  showAuthMessage("正在登录…", "info");
  try {
    await requestJson("/api/auth/login", {
      method: "POST",
      body: { username, password }
    });
    persistLoginEmail(username);
    showAuthMessage("登录成功，正在跳转…", "success");
    window.setTimeout(() => window.location.reload(), 180);
  } catch (error) {
    showAuthMessage(error.message || "登录失败，请稍后重试。", "error");
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const email = (document.getElementById("registerUsername")?.value || "").trim();
  const password = document.getElementById("registerPassword")?.value || "";
  const confirmPassword = document.getElementById("registerConfirmPassword")?.value || "";

  if (!email || !password || !confirmPassword) {
    showAuthMessage("请完整填写注册信息。", "error");
    return;
  }

  showAuthMessage("正在创建账户…", "info");
  try {
    await requestJson("/api/auth/register", {
      method: "POST",
      body: {
        email,
        password,
        confirm_password: confirmPassword
      }
    });
    persistLoginEmail(email);
    showAuthMessage("注册成功，正在跳转…", "success");
    window.setTimeout(() => window.location.reload(), 180);
  } catch (error) {
    showAuthMessage(error.message || "注册失败，请稍后重试。", "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  restoreLastLoginEmail();
  wirePasswordVisibilityToggles();
  switchAuthTab("login");
});

window.switchAuthTab = switchAuthTab;
window.handleLogin = handleLogin;
window.handleRegister = handleRegister;
