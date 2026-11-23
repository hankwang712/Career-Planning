(function () {
  "use strict";
  const TESTS = [
    { id: "mbti", group: "career", name: "MBTI 性格倾向", category: "性格偏好", total: 93, count: "93 题", time: "约 12 分钟", color: "blue", icon: "M", cover: "/static/brand/assessments/mbti.jpg", description: "了解获取能量、处理信息与做出决定的偏好。" },
    { id: "holland", group: "career", name: "霍兰德职业兴趣", category: "职业兴趣", total: 90, count: "90 题", time: "约 10 分钟", color: "teal", icon: "H", cover: "/static/brand/assessments/holland.jpg", description: "从喜欢的活动出发，探索你的职业兴趣方向。" },
    { id: "deep", group: "career", name: "深层 MBTI", category: "性格探索", total: 52, count: "52 题", time: "约 8 分钟", color: "indigo", icon: "D", cover: "/static/brand/assessments/deep.jpg", description: "通过五档量表，进一步观察四个维度的性格倾向。" },
    { id: "friends", group: "fun", name: "老友记角色", category: "趣味探索", total: 10, count: "10 题", time: "约 2 分钟", color: "amber", icon: "F", cover: "/static/brand/assessments/friends.svg", description: "走进熟悉的生活情境，看看你更像哪位老友。" },
    { id: "insideout", group: "fun", name: "情绪主导", category: "趣味探索", total: 14, count: "14 题", time: "约 3 分钟", color: "rose", icon: "E", cover: "/static/brand/assessments/insideout.svg", description: "通过日常情境，探索你当前的情感表达风格。" },
    { id: "sbti", group: "fun", name: "SBTI 人格扩展", category: "人格探索", total: 30, count: "30 题+", time: "约 5 分钟", color: "violet", icon: "S", cover: "/static/brand/assessments/sbti.svg", description: "从更多生活偏好出发，认识你的人格表达方式。" }
  ];
  const IDS = new Set(TESTS.map(test => test.id));
  const HISTORY_PREFIX = "career_assessment_history_v1_";
  const HISTORY_LIMIT = 50;
  let filter = "all";
  let categoryFilter = "all";

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }
  function username() {
    return window.getCurrentUser?.()?.username || window.userWorkspaceState?.currentUser?.username || "guest";
  }
  function normalize(items) {
    const unique = new Map();
    if (!Array.isArray(items)) return [];
    for (const item of items) {
      const completedAt = Number(item?.completedAt);
      const result = String(item?.result || "").trim().slice(0, 100);
      if (!IDS.has(item?.test) || !Number.isFinite(completedAt) || completedAt <= 0 || Number.isNaN(new Date(completedAt).getTime()) || !result) continue;
      unique.set(`${item.test}:${completedAt}`, { test: item.test, completedAt, result });
    }
    return [...unique.values()].sort((a, b) => b.completedAt - a.completedAt).slice(0, HISTORY_LIMIT);
  }
  function readHistory() {
    try { return normalize(JSON.parse(localStorage.getItem(HISTORY_PREFIX + username()) || "[]")); }
    catch (_) { return []; }
  }
  function record(items) {
    const before = readHistory();
    const next = normalize([...before, ...items]);
    if (JSON.stringify(next) !== JSON.stringify(before)) {
      try { localStorage.setItem(HISTORY_PREFIX + username(), JSON.stringify(next)); }
      catch (_) { /* 已有测评结果不受历史记录存储失败影响。 */ }
    }
    render();
  }
  function recordBasic(snapshot) {
    if (!snapshot || snapshot.owner !== username()) return;
    const items = [];
    for (const test of ["mbti", "holland"]) {
      const runs = snapshot[test]?.history_runs || [];
      runs.forEach((run, index) => {
        const latest = index === runs.length - 1 && snapshot[test]?.completed;
        const result = test === "mbti"
          ? (latest ? snapshot[test].display_type || run.displayType : run.displayType)
          : (latest ? snapshot[test].code || run.code : run.code);
        items.push({ test, completedAt: run.recordedAt, result });
      });
    }
    record(items);
  }
  // 深层 MBTI、老友记、情绪主导、SBTI 的结果原本只存在浏览器里。同步一份精简结果到服务器，
  // 聊天助手和报告 Agent 才能把"用户做过哪些测评"当作画像的一部分；没做过的测评不会出现。
  const synced = new Set();
  let syncQueue = Promise.resolve();
  // 趣味测评的角色名/类型名不同步，只同步分析文字（由 deep-test-hub 去掉名字后生成）。
  function compactExtended(type, stored) {
    const completedAt = Number(stored?.completedAt);
    const core = window.__DeepTestHubCore__;
    if (!Number.isFinite(completedAt) || completedAt <= 0 || typeof core?.describeStored !== "function") return null;
    const described = core.describeStored(type, stored);
    if (!described || (!described.result && !described.summary)) return null;
    return { result: String(described.result || ""), summary: String(described.summary || ""), completed_at: completedAt };
  }
  function syncExtended(type, stored) {
    const user = username();
    const entry = compactExtended(type, stored);
    if (!entry || user === "guest") return;
    const key = `${user}:${type}:${entry.completed_at}`;
    if (synced.has(key)) return;
    synced.add(key);
    syncQueue = syncQueue.then(async () => {
      const base = String(window.__API_BASE__ || "").replace(/\/+$/, "");
      try {
        const current = await fetch(`${base}/api/user-state/deep_tests`, { credentials: "same-origin" });
        if (!current.ok) { synced.delete(key); return; }
        const existing = (await current.json()).data || {};
        const known = existing[type];
        if (known && Number(known.completed_at) >= entry.completed_at && known.result === entry.result && known.summary === entry.summary) return;
        const security = await (await fetch(`${base}/api/workspace/security`, { credentials: "same-origin" })).json();
        const saved = await fetch(`${base}/api/user-state/deep_tests`, {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": security.csrf_token },
          body: JSON.stringify({ data: { ...existing, [type]: entry } })
        });
        if (!saved.ok) synced.delete(key);
      } catch (_) { synced.delete(key); }
    });
  }
  function recordExtended(type, stored) {
    if (!stored) return;
    let result;
    if (type === "deep") result = stored.result?.type;
    else if (type === "sbti") result = stored.title || stored.code;
    else result = stored.detail?.name || stored.winner;
    record([{ test: type, completedAt: stored.completedAt, result }]);
    syncExtended(type, stored);
  }
  function currentResults() {
    const current = window.getAssessmentHubSnapshot?.();
    const snapshot = current?.owner === username() ? current : null;
    const available = { mbti: Boolean(snapshot?.mbti?.completed), holland: Boolean(snapshot?.holland?.completed) };
    const core = window.__DeepTestHubCore__;
    for (const test of ["deep", "friends", "insideout", "sbti"]) available[test] = Boolean(core?.getStoredResultByType(test));
    return available;
  }
  function draftProgress(test) {
    if (test.id === "mbti" || test.id === "holland") {
      const snap = window.getAssessmentHubSnapshot?.();
      if (snap?.owner === username()) {
        const part = snap[test.id];
        if (part && !part.completed && part.answered_count > 0) {
          return Math.min(99, Math.round((part.answered_count / test.total) * 100));
        }
      }
      return 0;
    }
    try {
      const saved = JSON.parse(localStorage.getItem(`career_assessment_draft_v1_${username()}_${test.id}`) || "null");
      const count = saved?.answers ? Object.keys(saved.answers).length : 0;
      if (count > 0) return Math.min(99, Math.round((count / test.total) * 100));
    } catch (_) {}
    return 0;
  }

  function render() {
    const grid = document.getElementById("assessmentTestGrid");
    if (!grid) return;
    const history = readHistory();
    const available = currentResults();
    const doneCount = TESTS.filter(t => available[t.id]).length;
    const summaryEl = document.getElementById("assessmentCenterSummary");
    if (summaryEl) summaryEl.textContent = `已完成 ${doneCount} / ${TESTS.length}`;
    const visible = TESTS.filter(test => {
      if (categoryFilter === "career") return test.group === "career";
      if (categoryFilter === "fun") return test.group === "fun";
      if (categoryFilter === "done") return Boolean(available[test.id]);
      return true;
    });
    grid.innerHTML = visible.length ? visible.map((test) => {
      const latest = history.find(item => item.test === test.id);
      const done = Boolean(available[test.id]);
      const pct = done ? 100 : draftProgress(test);
      const badge = done
        ? `<span class="assessment-cover-status is-done">已完成</span>`
        : pct > 0
          ? `<span class="assessment-cover-status is-wip">进行中 ${pct}%</span>`
          : "";
      const ctaText = done ? "查看结果" : pct > 0 ? "继续答题" : "开始测评";
      return `<article class="assessment-center-card tone-${test.color}">
        <div class="assessment-card-cover">
          <img src="${test.cover}" alt="${esc(test.name)}" loading="lazy">
          <span class="assessment-cover-cat">${test.category}</span>
          ${badge}
        </div>
        <div class="assessment-card-body">
          <h3>${test.name}</h3>
          <p class="assessment-center-description">${test.description}</p>
          <div class="assessment-center-meta"><span>${test.count}</span><span>${test.time}</span></div>
          <div class="assessment-center-last">${latest ? `<span>最近结果</span><strong>${esc(latest.result)}</strong>` : pct > 0 ? `<div class="assessment-mini-bar"><i style="width:${pct}%"></i></div><span>已保存 ${pct}%</span>` : '<span class="assessment-center-not-started">随时开始 · 自动存进度</span>'}</div>
          <div class="assessment-center-card-actions"><button type="button" class="assessment-center-primary" data-assessment-test="${test.id}" data-assessment-action="${done ? "result" : "start"}">${ctaText}<span aria-hidden="true">→</span></button>
          ${done ? `<button type="button" class="assessment-center-restart" data-assessment-test="${test.id}" data-assessment-action="restart">重测</button>` : ""}</div>
        </div>
      </article>`;
    }).join("") : `<div class="assessment-grid-empty">该分类下暂无测评记录</div>`;
    const rows = filter === "all" ? history : history.filter(item => item.test === filter);
    document.getElementById("assessmentHistoryCount").textContent = `${rows.length} 条`;
    document.getElementById("assessmentHistoryList").innerHTML = rows.length ? rows.map(item => {
      const test = TESTS.find(t => t.id === item.test);
      const time = new Date(item.completedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
      return `<article class="assessment-center-record" data-history-test="${item.test}" role="button" tabindex="0"><div><span class="assessment-center-record-dot tone-${test.color}"></span><strong>${test.name}</strong><time datetime="${new Date(item.completedAt).toISOString()}">${esc(time)}</time></div><p>${esc(item.result)}</p></article>`;
    }).join("") : `<div class="assessment-center-empty"><span aria-hidden="true">◷</span><strong>${filter === "all" ? "还没有测评记录" : "这项测评还没有记录"}</strong></div>`;
  }
  function restore() {
    recordBasic(window.getAssessmentHubSnapshot?.());
    const core = window.__DeepTestHubCore__;
    for (const type of ["deep", "friends", "insideout", "sbti"]) recordExtended(type, core?.getStoredResultByType(type));
    render();
  }
  function init() {
    const grid = document.getElementById("assessmentTestGrid");
    if (grid) {
      grid.addEventListener("click", event => {
        const button = event.target.closest("[data-assessment-test]");
        if (!button) return;
        const test = button.dataset.assessmentTest;
        const action = button.dataset.assessmentAction;
        if (test === "mbti" || test === "holland") {
          window.openAssessmentModal(test);
          if (action === "restart") window.restartAssessmentFlow();
        } else if (action === "result") window.openDeepTestResultPage(test);
        else window.openDeepTestRunnerPage(test, action === "restart");
      });
      const select = document.getElementById("assessmentHistoryFilter");
      select.insertAdjacentHTML("beforeend", TESTS.map(test => `<option value="${test.id}">${test.name}</option>`).join(""));
      select.addEventListener("change", () => { filter = select.value; render(); });
      document.getElementById("assessmentCategoryTabs")?.addEventListener("click", event => {
        const tab = event.target.closest("[data-cat]");
        if (!tab) return;
        categoryFilter = tab.dataset.cat || "all";
        document.querySelectorAll("#assessmentCategoryTabs .assessment-cat-tab").forEach(btn => {
          const active = btn === tab;
          btn.classList.toggle("active", active);
          btn.setAttribute("aria-selected", String(active));
        });
        render();
      });
      document.getElementById("assessmentHistoryList")?.addEventListener("click", event => {
        const row = event.target.closest("[data-history-test]");
        if (!row) return;
        const test = row.dataset.historyTest;
        if (test === "mbti" || test === "holland") window.openAssessmentModal(test);
        else window.openDeepTestResultPage(test);
      });
    }
    restore();
    window.userWorkspaceState?.authReadyPromise?.then(restore);
  }
  window.AssessmentCenter = { recordExtended, refresh: restore };
  window.addEventListener("assessment-hub:updated", event => recordBasic(event.detail));
  window.addEventListener("app:auth-changed", () => { filter = "all"; const select = document.getElementById("assessmentHistoryFilter"); if (select) select.value = "all"; render(); });
  window.addEventListener("storage", event => { if (event.key?.startsWith(HISTORY_PREFIX)) render(); });
  window.addEventListener("focus", restore);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
