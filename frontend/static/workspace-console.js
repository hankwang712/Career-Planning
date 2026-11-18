(() => {
  const panel = document.getElementById("workspaceConsolePanel");
  const toggle = document.querySelector("[data-console-toggle]");
  const filter = panel.querySelector("[data-console-filter]");
  const list = panel.querySelector("[data-console-entries]");
  const status = panel.querySelector("[data-console-status]");
  const empty = panel.querySelector("[data-console-empty]");
  let entries = [];
  let timer;
  let session = 0;

  function render() {
    const query = filter.value.trim().toLowerCase();
    const lines = entries.map(entry => ({
      text: `${new Date(entry.time).toLocaleTimeString()}  ${entry.method} ${entry.route}  ${entry.status} · ${entry.duration_ms} ms`,
      failed: entry.status >= 400
    })).filter(line => line.text.toLowerCase().includes(query));
    list.replaceChildren(...lines.map(line => {
      const row = document.createElement("li");
      row.textContent = line.text;
      row.classList.toggle("failed", line.failed);
      return row;
    }));
    empty.hidden = lines.length > 0;
    empty.textContent = query ? "没有匹配的日志" : "暂无请求记录";
  }

  async function refresh(currentSession) {
    try {
      const response = await fetch("/api/workspace-logs", { cache: "no-store" });
      if (response.status === 401) {
        if (currentSession === session) close();
        return;
      }
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (currentSession !== session) return;
      entries = data.entries.reverse();
      status.textContent = `自动刷新 · ${entries.length} 条`;
      render();
    } catch {
      if (currentSession === session) status.textContent = "暂时无法读取";
    } finally {
      if (currentSession === session && !panel.hidden) {
        timer = window.setTimeout(() => refresh(currentSession), 3000);
      }
    }
  }

  function close() {
    session += 1;
    window.clearTimeout(timer);
    panel.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    entries = [];
    list.replaceChildren();
    filter.value = "";
    render();
  }

  toggle.addEventListener("click", () => {
    if (!panel.hidden) return close();
    panel.hidden = false;
    status.textContent = "加载中…";
    toggle.setAttribute("aria-expanded", "true");
    filter.focus();
    void refresh(++session);
  });
  filter.addEventListener("input", render);
  panel.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      close();
      toggle.focus();
    }
  });
  window.addEventListener("app:auth-changed", close);
})();
