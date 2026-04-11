(function () {
  async function fetchResumeProfilePayload() {
    try {
      const path = "/api/resume/profile";
      const url = typeof resolveApiUrl === "function" ? resolveApiUrl(path) : path;
      const res = await fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" }
      });
      if (!res.ok) return null;
      const payload = await res.json();
      return payload && payload.data ? payload.data : null;
    } catch (_) {
      return null;
    }
  }

  function waitForRenderer(maxMs) {
    const limit = typeof maxMs === "number" ? maxMs : 12000;
    const start = Date.now();
    return new Promise(function (resolve) {
      function tick() {
        if (window.__resumeDeepAuditRenderer && typeof window.__resumeDeepAuditRenderer.renderHtml === "function") {
          resolve(true);
          return;
        }
        if (Date.now() - start > limit) {
          resolve(false);
          return;
        }
        setTimeout(tick, 30);
      }
      tick();
    });
  }

  document.addEventListener("DOMContentLoaded", async function () {
    const root = document.getElementById("resumeDeepAuditRoot");
    if (!root) return;
    const ready = await waitForRenderer();
    if (!ready) {
      root.innerHTML = "<div class=\"career-list-empty\">报告渲染器未能加载，请刷新页面重试。</div>";
      return;
    }
    const state = await fetchResumeProfilePayload();
    if (!state || String(state.status || "").trim() !== "analyzed") {
      root.innerHTML = "<div class=\"career-list-empty\">暂无已完成的分析结果。请先返回上传简历并完成分析。</div>";
      return;
    }
    const hasBody = String(state.analysis_result || "").trim() || String(state.analysis_html || "").trim();
    if (!hasBody) {
      root.innerHTML = "<div class=\"career-list-empty\">尚未生成完整深度诊断正文。</div>";
      return;
    }
    root.innerHTML = window.__resumeDeepAuditRenderer.renderHtml(state);
    var scope = root.querySelector(".resume-6html-scope");
    if (scope && typeof initResume6htmlScopeEffects === "function") {
      initResume6htmlScopeEffects(scope);
    }
  });
})();
