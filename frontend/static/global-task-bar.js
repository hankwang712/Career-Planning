/* Global floating background task activity bar (SSE-backed, persists across all workspace pages). */
(() => {
  "use strict";
  if (window.CareerTaskBar) return;

  const API_BASE = "/api/job-market/collection/pipeline/tasks";
  let root = null;
  let titleEl = null;
  let metaEl = null;
  let fillEl = null;
  let abortBtn = null;
  let jumpBtn = null;
  let currentTaskId = "";
  let es = null;
  let hideTimer = null;
  const listeners = new Set();

  function ensureUI() {
    if (root) return;
    const style = document.createElement("style");
    style.textContent = `
      .ca-task-bar {
        position: fixed; right: 20px; bottom: 20px; z-index: 9500;
        width: min(360px, calc(100vw - 32px));
        padding: 12px 14px; border-radius: 14px;
        background: rgba(15, 23, 42, 0.94); color: #f8fafc;
        box-shadow: 0 16px 36px -10px rgba(15, 23, 42, 0.45);
        backdrop-filter: blur(12px);
        display: grid; gap: 8px; font-size: 12.5px;
        transition: opacity 0.2s ease, transform 0.2s ease;
      }
      .ca-task-bar[hidden] { display: none; }
      .ca-task-bar-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
      .ca-task-bar-title { font-weight: 650; display: inline-flex; align-items: center; gap: 7px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .ca-task-dot { width: 8px; height: 8px; border-radius: 999px; background: #60a5fa; flex: none; animation: caPulse 1.2s infinite ease-in-out; }
      .ca-task-bar[data-status="completed"] .ca-task-dot { background: #34d399; animation: none; }
      .ca-task-bar[data-status="aborted"] .ca-task-dot,
      .ca-task-bar[data-status="failed"] .ca-task-dot { background: #f87171; animation: none; }
      @keyframes caPulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.45; transform: scale(0.8); } }
      .ca-task-meta { font-size: 11.5px; color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .ca-task-track { height: 5px; border-radius: 999px; background: rgba(255,255,255,0.16); overflow: hidden; }
      .ca-task-fill { height: 100%; width: 0; border-radius: 999px; background: linear-gradient(90deg, #38bdf8, #818cf8); transition: width 0.3s ease; }
      .ca-task-bar[data-status="completed"] .ca-task-fill { background: linear-gradient(90deg, #10b981, #34d399); }
      .ca-task-btns { display: flex; align-items: center; gap: 6px; flex: none; }
      .ca-task-btn { border: 1px solid rgba(255,255,255,0.22); background: rgba(255,255,255,0.08); color: #f8fafc; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 7px; cursor: pointer; }
      .ca-task-btn:hover { background: rgba(255,255,255,0.18); }
      .ca-task-btn-danger { border-color: rgba(248,113,113,0.45); color: #fecaca; }
    `;
    document.head.append(style);

    root = document.createElement("aside");
    root.className = "ca-task-bar";
    root.hidden = true;
    root.setAttribute("aria-live", "polite");

    const top = document.createElement("div");
    top.className = "ca-task-bar-top";
    titleEl = document.createElement("div");
    titleEl.className = "ca-task-bar-title";
    const dot = document.createElement("span");
    dot.className = "ca-task-dot";
    const titleText = document.createElement("span");
    titleText.className = "ca-task-title-text";
    titleEl.append(dot, titleText);

    const btns = document.createElement("div");
    btns.className = "ca-task-btns";
    jumpBtn = document.createElement("button");
    jumpBtn.type = "button";
    jumpBtn.className = "ca-task-btn";
    jumpBtn.textContent = "查看";
    jumpBtn.addEventListener("click", () => {
      if (!location.pathname.startsWith("/recruitment")) location.href = "/recruitment";
      else root.hidden = true;
    });
    abortBtn = document.createElement("button");
    abortBtn.type = "button";
    abortBtn.className = "ca-task-btn ca-task-btn-danger";
    abortBtn.textContent = "中止";
    abortBtn.addEventListener("click", async () => {
      if (!currentTaskId) return;
      abortBtn.disabled = true;
      try {
        await fetch(`${API_BASE}/${encodeURIComponent(currentTaskId)}/abort`, { method: "POST" });
      } catch { /* ignore */ }
      finally { abortBtn.disabled = false; }
    });
    btns.append(jumpBtn, abortBtn);
    top.append(titleEl, btns);

    metaEl = document.createElement("div");
    metaEl.className = "ca-task-meta";
    const track = document.createElement("div");
    track.className = "ca-task-track";
    fillEl = document.createElement("div");
    fillEl.className = "ca-task-fill";
    track.append(fillEl);
    root.append(top, metaEl, track);
    document.body.append(root);
  }

  function renderSnapshot(snap) {
    const task = (snap.running && snap.running[0]) || snap.latest;
    for (const fn of listeners) {
      try { fn(snap, task); } catch { /* ignore */ }
    }
    if (!task) return;
    const isRunning = task.status === "running";
    const recentDone = !isRunning && task.finished_at && (Date.now() / 1000 - task.finished_at < 6);
    if (!isRunning && !recentDone) return;

    ensureUI();
    clearTimeout(hideTimer);
    currentTaskId = task.task_id;
    root.hidden = false;
    root.dataset.status = task.status;
    titleEl.querySelector(".ca-task-title-text").textContent = `${task.label} (${task.done}/${task.total || 0})`;
    metaEl.textContent = task.message || task.current || "";
    fillEl.style.width = `${Math.max(isRunning ? 8 : 100, task.percent || 0)}%`;
    abortBtn.hidden = !isRunning;
    jumpBtn.textContent = location.pathname.startsWith("/recruitment") ? "收起" : "去看板";

    if (!isRunning) {
      if (window.RP && typeof window.RP.refresh === "function") {
        void window.RP.refresh({ silent: true });
      }
      hideTimer = setTimeout(() => { if (root) root.hidden = true; }, 4500);
    }
  }

  function connectStream() {
    if (es) { try { es.close(); } catch { /* ignore */ } es = null; }
    if (typeof EventSource === "undefined") return;
    es = new EventSource(`${API_BASE}/stream`);
    es.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data);
        renderSnapshot(snap);
        if (!snap.running || !snap.running.length) {
          es.close();
          es = null;
        }
      } catch { /* ignore */ }
    };
    es.onerror = () => {
      if (es) { es.close(); es = null; }
    };
  }

  async function checkActive() {
    try {
      const res = await fetch(`${API_BASE}/active`, { cache: "no-store" });
      if (!res.ok) return;
      const snap = await res.json();
      renderSnapshot(snap);
      if (snap.running && snap.running.length) connectStream();
    } catch { /* ignore */ }
  }

  async function startTask(payload) {
    const res = await fetch(`${API_BASE}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || "任务启动失败");
    renderSnapshot({ running: [data.task], latest: data.task });
    connectStream();
    return data.task;
  }

  window.CareerTaskBar = {
    startTask,
    checkActive,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { void checkActive(); initTerminalDrawer(); });
  } else {
    void checkActive();
    initTerminalDrawer();
  }

  /* 全局实时控制台抽屉（借鉴 JobHunter GlobalTerminalDrawer：Ctrl+` / Ctrl+J 呼出，空闲不轮询） */
  function initTerminalDrawer() {
    if (document.getElementById("caTermFab")) return;
    const style = document.createElement("style");
    style.textContent = `
      .ca-term-fab {
        position: fixed; left: 18px; bottom: 18px; z-index: 9450;
        display: inline-flex; align-items: center; gap: 6px;
        height: 32px; padding: 0 11px; border-radius: 999px;
        border: 1px solid rgba(148,163,184,0.35);
        background: rgba(15,23,42,0.88); color: #e2e8f0;
        font-size: 11.5px; font-weight: 600; cursor: pointer;
        box-shadow: 0 8px 20px -8px rgba(15,23,42,0.45);
        backdrop-filter: blur(8px); transition: all 0.15s ease;
      }
      .ca-term-fab:hover { background: #0f172a; color: #ffffff; transform: translateY(-1px); }
      .ca-term-drawer {
        position: fixed; left: 18px; right: 18px; bottom: 18px; z-index: 9550;
        height: 300px; max-height: 72vh; border-radius: 14px;
        border: 1px solid rgba(148,163,184,0.28);
        background: rgba(15,23,42,0.96); color: #e2e8f0;
        box-shadow: 0 24px 56px -14px rgba(15,23,42,0.65);
        backdrop-filter: blur(14px);
        display: grid; grid-template-rows: auto 1fr; overflow: hidden;
      }
      .ca-term-drawer.is-tall { height: 64vh; }
      .ca-term-drawer[hidden] { display: none; }
      .ca-term-head {
        display: flex; align-items: center; justify-content: space-between; gap: 10px;
        padding: 9px 14px; border-bottom: 1px solid rgba(148,163,184,0.18);
        background: rgba(30,41,59,0.75); font-size: 12px;
      }
      .ca-term-head-left { display: flex; align-items: center; gap: 8px; font-weight: 650; }
      .ca-term-kbd { padding: 1px 6px; border-radius: 5px; background: rgba(255,255,255,0.1); color: #94a3b8; font-size: 10.5px; font-family: monospace; }
      .ca-term-tools { display: flex; align-items: center; gap: 6px; }
      .ca-term-search {
        height: 26px; width: 160px; padding: 0 8px; border-radius: 6px;
        border: 1px solid rgba(148,163,184,0.28); background: rgba(15,23,42,0.7);
        color: #f8fafc; font-size: 11.5px;
      }
      .ca-term-search:focus { outline: none; border-color: #38bdf8; }
      .ca-term-body {
        padding: 10px 14px; overflow-y: auto;
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        font-size: 11.5px; line-height: 1.65;
      }
      .ca-term-line { display: flex; gap: 8px; padding: 1px 0; word-break: break-all; }
      .ca-term-t { color: #64748b; flex: none; }
      .ca-term-lv { flex: none; font-weight: 700; min-width: 42px; }
      .ca-term-lv[data-lv="ERROR"] { color: #f87171; }
      .ca-term-lv[data-lv="WARN"], .ca-term-lv[data-lv="SLOW"] { color: #fbbf24; }
      .ca-term-lv[data-lv="INFO"] { color: #38bdf8; }
    `;
    document.head.append(style);

    const fab = document.createElement("button");
    fab.id = "caTermFab";
    fab.type = "button";
    fab.className = "ca-term-fab";
    fab.title = "打开实时后端日志（Ctrl + ` 或 Ctrl + J）";
    fab.innerHTML = `<span style="color:#38bdf8;">&gt;_</span><span>日志</span>`;

    const drawer = document.createElement("section");
    drawer.className = "ca-term-drawer";
    drawer.hidden = true;
    const head = document.createElement("div");
    head.className = "ca-term-head";
    const left = document.createElement("div");
    left.className = "ca-term-head-left";
    left.innerHTML = `<span style="color:#38bdf8;">&gt;_</span><span>实时后端控制台</span><span class="ca-term-kbd">Ctrl+\`</span>`;
    const tools = document.createElement("div");
    tools.className = "ca-term-tools";
    const search = document.createElement("input");
    search.className = "ca-term-search";
    search.placeholder = "筛选关键词…";
    const copyBtn = document.createElement("button");
    copyBtn.type = "button"; copyBtn.className = "ca-task-btn"; copyBtn.textContent = "复制";
    const clearBtn = document.createElement("button");
    clearBtn.type = "button"; clearBtn.className = "ca-task-btn"; clearBtn.textContent = "清空";
    const sizeBtn = document.createElement("button");
    sizeBtn.type = "button"; sizeBtn.className = "ca-task-btn"; sizeBtn.textContent = "放大";
    const closeBtn = document.createElement("button");
    closeBtn.type = "button"; closeBtn.className = "ca-task-btn"; closeBtn.textContent = "收起";
    tools.append(search, copyBtn, clearBtn, sizeBtn, closeBtn);
    head.append(left, tools);
    const body = document.createElement("div");
    body.className = "ca-term-body";
    drawer.append(head, body);
    document.body.append(fab, drawer);

    let entries = [];
    let lastSeq = 0;
    let pollTimer = null;

    function renderLines() {
      const q = search.value.trim().toLowerCase();
      const filtered = q ? entries.filter(e => `${e.level} ${e.text}`.toLowerCase().includes(q)) : entries;
      if (!filtered.length) {
        body.innerHTML = `<div style="color:#64748b;">暂无日志记录（触发 AI 改写、评估或接口请求后会实时显示在这里）。</div>`;
        return;
      }
      body.replaceChildren(...filtered.map(e => {
        const row = document.createElement("div");
        row.className = "ca-term-line";
        const t = document.createElement("span");
        t.className = "ca-term-t"; t.textContent = e.time;
        const lv = document.createElement("span");
        lv.className = "ca-term-lv"; lv.dataset.lv = e.level; lv.textContent = `[${e.level}]`;
        const txt = document.createElement("span");
        txt.textContent = e.text;
        row.append(t, lv, txt);
        return row;
      }));
      body.scrollTop = body.scrollHeight;
    }

    async function pullLogs() {
      try {
        const res = await fetch(`/api/system-settings/console-logs?after=${lastSeq}`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const incoming = Array.isArray(data.entries) ? data.entries : [];
        if (incoming.length) {
          entries.push(...incoming);
          if (entries.length > 300) entries = entries.slice(-300);
          lastSeq = entries[entries.length - 1].seq;
          renderLines();
        } else if (!entries.length) {
          renderLines();
        }
      } catch { /* ignore */ }
    }

    function setOpen(open) {
      drawer.hidden = !open;
      fab.hidden = open;
      clearInterval(pollTimer);
      if (open) {
        void pullLogs();
        pollTimer = setInterval(() => { void pullLogs(); }, 2500);
      }
    }

    fab.addEventListener("click", () => setOpen(true));
    closeBtn.addEventListener("click", () => setOpen(false));
    sizeBtn.addEventListener("click", () => {
      drawer.classList.toggle("is-tall");
      sizeBtn.textContent = drawer.classList.contains("is-tall") ? "还原" : "放大";
    });
    search.addEventListener("input", renderLines);
    copyBtn.addEventListener("click", async () => {
      const text = entries.map(e => `${e.time} [${e.level}] ${e.text}`).join("\n");
      try { await navigator.clipboard.writeText(text); copyBtn.textContent = "已复制"; setTimeout(() => { copyBtn.textContent = "复制"; }, 1200); }
      catch { /* ignore */ }
    });
    clearBtn.addEventListener("click", async () => {
      entries = []; lastSeq = 0; renderLines();
      try { await fetch("/api/system-settings/console-logs", { method: "DELETE" }); } catch { /* ignore */ }
    });
    window.addEventListener("keydown", (e) => {
      if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") || (e.ctrlKey && e.key === "`")) {
        e.preventDefault();
        setOpen(drawer.hidden);
      }
    });
  }
})();
