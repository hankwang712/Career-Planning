const authConfig = {
  allowSelfRegister: false,
  superUser: {
    username: "system",
    password: "123456"
  }
};

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
    throw new Error(payload.error || payload.message || "请求失败。");
  }
  return payload;
}

function showAuthMessage(message, tone = "info") {
  const el = document.getElementById("authMessage");
  if (!el) return;
  el.textContent = message || "";
  el.classList.remove("success", "error", "warning");
  if (tone !== "info") {
    el.classList.add(tone);
  }
}

function fillSuperUser() {
  const username = document.getElementById("loginUsername");
  const password = document.getElementById("loginPassword");
  if (username) username.value = authConfig.superUser.username;
  if (password) password.value = authConfig.superUser.password;
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
    showAuthMessage("预置账号：system，密码：123456。");
  } else if (!authConfig.allowSelfRegister) {
    showAuthMessage("当前环境仅开放预置账号登录，不支持自助注册。", "warning");
  } else {
    showAuthMessage("创建普通用户账号。");
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) {
    showAuthMessage("请输入用户名和密码。", "error");
    return;
  }

  showAuthMessage("登录中，请稍候……");
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
  showAuthMessage("当前环境仅开放预置账号登录，不支持自助注册。", "warning");
}

document.addEventListener("DOMContentLoaded", () => {
  switchAuthTab("login");
});

window.switchAuthTab = switchAuthTab;
window.fillSuperUser = fillSuperUser;
window.handleLogin = handleLogin;
window.handleRegister = handleRegister;
