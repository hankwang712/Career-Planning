(function () {
  "use strict";
  const TESTS = [
    { id: "mbti", name: "MBTI 性格倾向", category: "性格偏好", count: "93 题", time: "约 12 分钟", color: "blue", icon: "M", description: "了解获取能量、处理信息与做出决定的偏好。" },
    { id: "holland", name: "霍兰德职业兴趣", category: "职业兴趣", count: "90 题", time: "约 10 分钟", color: "teal", icon: "H", description: "从喜欢的活动出发，探索你的职业兴趣方向。" },
    { id: "deep", name: "深层 MBTI", category: "性格探索", count: "52 题", time: "约 8 分钟", color: "indigo", icon: "D", description: "通过五档量表，进一步观察四个维度的性格倾向。" },
    { id: "friends", name: "老友记角色", category: "趣味探索", count: "10 题", time: "约 2 分钟", color: "amber", icon: "F", description: "走进熟悉的生活情境，看看你更像哪位老友。" },
    { id: "insideout", name: "情绪主导", category: "趣味探索", count: "14 题", time: "约 3 分钟", color: "rose", icon: "E", description: "通过日常情境，探索你当前的情感表达风格。" },
    { id: "sbti", name: "SBTI 人格扩展", category: "人格探索", count: "30 题＋补充题", time: "约 5 分钟", color: "violet", icon: "S", description: "从更多生活偏好出发，认识你的人格表达方式。" }
  ];
  const IDS = new Set(TESTS.map(test => test.id));
  const HISTORY_PREFIX = "career_assessment_history_v1_";
  const HISTORY_LIMIT = 50;
  let filter = "all";

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
  function recordExtended(type, stored) {
    if (!stored) return;
    let result;
    if (type === "deep") result = stored.result?.type;
    else if (type === "sbti") result = stored.title || stored.code;
    else result = stored.detail?.name || stored.winner;
    record([{ test: type, completedAt: stored.completedAt, result }]);
  }
  function currentResults() {
    const current = window.getAssessmentHubSnapshot?.();
    const snapshot = current?.owner === username() ? current : null;
    const available = { mbti: Boolean(snapshot?.mbti?.completed), holland: Boolean(snapshot?.holland?.completed) };
    const core = window.__DeepTestHubCore__;
    for (const test of ["deep", "friends", "insideout", "sbti"]) available[test] = Boolean(core?.getStoredResultByType(test));
    return available;
  }
  function render() {
    const grid = document.getElementById("assessmentTestGrid");
    if (!grid) return;
    const history = readHistory();
    const available = currentResults();
    grid.innerHTML = TESTS.map((test, index) => {
      const latest = history.find(item => item.test === test.id);
      return `<article class="assessment-center-card tone-${test.color}">
        <div class="assessment-center-card-top"><span class="assessment-center-icon" aria-hidden="true">${test.icon}</span><span class="assessment-center-category">${test.category}</span><span class="assessment-center-index">0${index + 1}</span></div>
        <h3>${test.name}</h3><p class="assessment-center-description">${test.description}</p>
        <div class="assessment-center-meta"><span>${test.count}</span><span>${test.time}</span></div>
        <div class="assessment-center-last">${latest ? `<span>最近结果</span><strong>${esc(latest.result)}</strong>` : '<span class="assessment-center-not-started">还没有完成记录</span>'}</div>
        <div class="assessment-center-card-actions"><button type="button" class="assessment-center-primary" data-assessment-test="${test.id}" data-assessment-action="${available[test.id] ? "result" : "start"}">${available[test.id] ? "查看结果" : "开始测评"}<span aria-hidden="true">↗</span></button>
        ${available[test.id] ? `<button type="button" class="assessment-center-restart" data-assessment-test="${test.id}" data-assessment-action="restart">重新测评</button>` : ""}</div>
      </article>`;
    }).join("");
    const rows = filter === "all" ? history : history.filter(item => item.test === filter);
    document.getElementById("assessmentHistoryCount").textContent = `${rows.length} 条`;
    document.getElementById("assessmentHistoryList").innerHTML = rows.length ? rows.map(item => {
      const test = TESTS.find(test => test.id === item.test);
      const time = new Date(item.completedAt).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
      return `<article class="assessment-center-record"><div><span class="assessment-center-record-dot tone-${test.color}"></span><strong>${test.name}</strong><time datetime="${new Date(item.completedAt).toISOString()}">${esc(time)}</time></div><p>${esc(item.result)}</p></article>`;
    }).join("") : `<div class="assessment-center-empty"><span aria-hidden="true">◷</span><strong>${filter === "all" ? "还没有测评记录" : "这项测评还没有记录"}</strong><p>完成一项测评后，简要结果会显示在这里。</p></div>`;
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
