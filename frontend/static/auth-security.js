(() => {
  let pending;

  async function loadHeaders() {
    const base = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
    const response = await fetch(base + "/api/workspace/security", { credentials: "include", cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "工作区安全校验暂时不可用。");
    return { "X-CSRF-Token": data.csrf_token };
  }

  function headers() {
    if (!pending) pending = loadHeaders().finally(() => { pending = null; });
    return pending;
  }

  window.CareerAuth = { headers };
})();
