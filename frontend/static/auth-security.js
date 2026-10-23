(() => {
  const challenges = new Map();
  let readyPromise;

  function apiUrl(path) {
    return `${String(window.__API_BASE__ || "").trim().replace(/\/+$/, "")}${path}`;
  }

  async function getJson(path) {
    const response = await fetch(apiUrl(path), { credentials: "include", cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "安全验证暂时不可用，请稍后重试。");
    return data;
  }

  async function headers() {
    const data = await getJson("/api/auth/security");
    return { "X-CSRF-Token": data.csrf_token };
  }

  async function refresh(purpose) {
    const container = document.querySelector(`[data-auth-captcha="${purpose}"]`);
    if (!container) return;
    const image = container.querySelector("img");
    const input = container.querySelector("input");
    const status = container.querySelector("[data-captcha-status]");
    const button = container.querySelector("button");
    challenges.delete(purpose);
    input.value = "";
    input.disabled = true;
    button.disabled = true;
    status.textContent = "正在加载验证码…";
    try {
      const data = await getJson(`/api/auth/challenge?purpose=${purpose}`);
      image.src = data.image;
      challenges.set(purpose, { id: data.id, expiresAt: Date.now() + data.expires_in * 1000 });
      input.disabled = false;
      status.textContent = "输入图中的 5 位字符，不区分大小写。3 分钟内有效。";
    } catch (error) {
      image.removeAttribute("src");
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function ensureReady() {
    if (!document.querySelector("[data-auth-captcha]")) return;
    if (!readyPromise) {
      readyPromise = (async () => {
        await headers();
        for (const container of document.querySelectorAll("[data-auth-captcha]")) {
          const purpose = container.dataset.authCaptcha;
          await refresh(purpose);
        }
      })().catch((error) => {
        readyPromise = null;
        document.querySelectorAll("[data-captcha-status]").forEach((element) => {
          element.textContent = error.message;
        });
      });
    }
    return readyPromise;
  }

  async function credentials(purpose) {
    await ensureReady();
    const challenge = challenges.get(purpose);
    const answer = document.querySelector(`[data-auth-captcha="${purpose}"] input`)?.value.trim();
    if (!challenge || challenge.expiresAt <= Date.now()) {
      await refresh(purpose);
      throw new Error("验证码已刷新，请输入新的验证码。");
    }
    if (!answer || !/^[A-Za-z0-9]{5}$/.test(answer)) throw new Error("请输入图片中的 5 位验证码。");
    return { captcha_id: challenge.id, captcha_answer: answer };
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-captcha-refresh]");
    if (button) void refresh(button.dataset.captchaRefresh);
  });
  document.addEventListener("DOMContentLoaded", () => {
    const screen = document.getElementById("startupScreen");
    if (screen && !screen.classList.contains("hidden")) void ensureReady();
  });
  window.CareerAuth = { headers, credentials, refresh, ensureReady };
})();
