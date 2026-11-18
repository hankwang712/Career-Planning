(function () {
  const GUIDE_VERSION = "v9";
  const PLAN_STORAGE_PREFIX = "dp_overlay_plans_v1_";

  let guideAutoOpened = false;

  const overlayState = {
    plans: [],
    activePlanId: "",
    loaded: false
  };

  function getCurrentPageKind() {
    return String(document.body?.dataset?.page || "main").trim() || "main";
  }

  function isUserCenterPage() {
    return getCurrentPageKind() === "user-center";
  }

  function getCurrentUserSafe() {
    if (typeof window.getCurrentUser === "function") return window.getCurrentUser();
    return null;
  }

  function isAuthenticatedSafe() {
    if (typeof window.isAuthenticatedUser === "function") return window.isAuthenticatedUser();
    return Boolean(getCurrentUserSafe());
  }

  function esc(value) {
    if (typeof window.escHtml === "function") return window.escHtml(value);
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function safeToast(title, text, type = "info", duration = 1800) {
    if (typeof window.showToast === "function") {
      window.showToast(title, text, type, duration);
    }
  }

  function getUserCenterUrl(anchor = "", params = {}) {
    const safeAnchor = String(anchor || "").trim().replace(/^#/, "");
    if ((!safeAnchor || safeAnchor === "career-profile") && !Object.keys(params || {}).length) {
      return new URL("/user-center/resumes", window.location.origin).toString();
    }
    const url = new URL("/user-center/workspace", window.location.origin);
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value === null || value === undefined || value === "") return;
      url.searchParams.set(key, String(value));
    });
    if (safeAnchor) url.hash = safeAnchor;
    return url.toString();
  }

  if (typeof window.openUserCenterPage !== "function") {
    window.openUserCenterPage = function openUserCenterPage(anchor = "", params = {}) {
      const targetUrl = getUserCenterUrl(anchor, params);
      if (isUserCenterPage()) {
        const target = new URL(targetUrl);
        const current = new URL(window.location.href);
        const samePath = target.origin === current.origin && target.pathname === current.pathname;
        if (samePath) {
          if (window.location.href !== target.toString()) {
            window.history.pushState({}, "", target.toString());
          }
          if (typeof window.handleUserCenterUrlChange === "function") {
            window.handleUserCenterUrlChange();
            return;
          }
          const sectionId = String(anchor || "").trim().replace(/^#/, "");
          if (sectionId && typeof window.switchUserCenterSection === "function") {
            window.switchUserCenterSection(sectionId, { updateHash: false });
          } else if (sectionId) {
            document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" });
          }
          return;
        }
      }
      window.location.href = targetUrl;
    };
  }

  function getGuideStorageKey() {
    const username = String(getCurrentUserSafe()?.username || "anonymous").trim().toLowerCase() || "anonymous";
    return `dp_workspace_guide_${GUIDE_VERSION}_${username}`;
  }

  function consumeForceWorkspaceGuideFlag() {
    try {
      const forced = sessionStorage.getItem("app_force_workspace_guide") === "1";
      if (forced) sessionStorage.removeItem("app_force_workspace_guide");
      return forced;
    } catch (_) {
      return false;
    }
  }

  if (typeof window.hasSeenWorkspaceGuide !== "function") {
    window.hasSeenWorkspaceGuide = function hasSeenWorkspaceGuide() {
      try {
        return localStorage.getItem(getGuideStorageKey()) === "done";
      } catch (_) {
        return false;
      }
    };
  }

  if (typeof window.setSeenWorkspaceGuide !== "function") {
    window.setSeenWorkspaceGuide = function setSeenWorkspaceGuide() {
      try {
        localStorage.setItem(getGuideStorageKey(), "done");
      } catch (_) {
        // ignore storage errors
      }
    };
  }

  async function refreshWorkspaceGuide() {
    const status = document.getElementById("workspaceGuideModelStatus");
    if (!status) return;
    status.textContent = "正在检查模型配置…";
    delete status.dataset.ready;
    try {
      const response = await fetch("/api/llm-status", { cache: "no-store" });
      if (!response.ok) throw new Error();
      const data = await response.json();
      status.textContent = data.configured ? "模型已填写" : "待配置模型";
      status.dataset.ready = String(data.configured);
    } catch {
      status.textContent = "暂时无法检查";
      delete status.dataset.ready;
    }
  }

  function openWorkspaceGuide(force = false) {
    const dialog = document.getElementById("workspaceSetupGuide");
    if (!dialog || dialog.open || !isAuthenticatedSafe()) return;
    if (!force && window.hasSeenWorkspaceGuide()) return;
    const focus = document.activeElement;
    dialog.addEventListener("close", () => {
      window.setSeenWorkspaceGuide();
      document.body.classList.remove("workspace-guide-open");
      window.updateWorkspaceJourneyVisibility?.();
      focus?.focus();
    }, { once: true });
    dialog.showModal();
    document.body.classList.add("workspace-guide-open");
    window.updateWorkspaceJourneyVisibility?.();
    void refreshWorkspaceGuide();
  }

  window.openWorkspaceGuide = openWorkspaceGuide;
  window.closeWorkspaceGuide = () => document.getElementById("workspaceSetupGuide")?.close();

  function getPlanStorageKey() {
    const username = String(getCurrentUserSafe()?.username || "guest").trim().toLowerCase() || "guest";
    return `${PLAN_STORAGE_PREFIX}${username}`;
  }

  function defaultPlans() {
    return [
      {
        id: `plan_${Date.now()}_a`,
        title: "首月求职节奏",
        items: [
          { id: "i1", text: "完成简历首版", done: true },
          { id: "i2", text: "锁定 10 个目标岗位", done: false },
          { id: "i3", text: "每周 3 次投递复盘", done: false }
        ]
      }
    ];
  }

  function loadOverlayPlans() {
    if (overlayState.loaded) return;
    overlayState.loaded = true;
    try {
      const raw = JSON.parse(localStorage.getItem(getPlanStorageKey()) || "null");
      if (Array.isArray(raw) && raw.length) {
        overlayState.plans = raw;
      } else {
        overlayState.plans = defaultPlans();
      }
    } catch (_) {
      overlayState.plans = defaultPlans();
    }
    if (!overlayState.activePlanId && overlayState.plans.length) {
      overlayState.activePlanId = overlayState.plans[0].id;
    }
  }

  function saveOverlayPlans() {
    try {
      localStorage.setItem(getPlanStorageKey(), JSON.stringify(overlayState.plans));
    } catch (_) {
      // ignore storage errors
    }
  }

  function getCurrentFocusRole() {
    const selectedJobs = Array.isArray(window.appState?.selectedJobs) ? window.appState.selectedJobs : [];
    const focused = String(window.appState?.focusedRoleId || "").trim();
    const roleId = focused || selectedJobs[0] || "";
    const roleName = (window.jobNameMap && roleId && window.jobNameMap[roleId]) ? window.jobNameMap[roleId] : roleId;
    return roleName || "待识别";
  }

  function getOverlayCompletion() {
    const completion = Number(window.appState?.profileCompletion || 0);
    return Math.max(0, Math.min(100, Math.round(completion)));
  }

  function getPlanStats(plan) {
    const items = Array.isArray(plan?.items) ? plan.items : [];
    const done = items.filter((item) => item.done).length;
    const total = items.length;
    const pct = total ? Math.round((done / total) * 100) : 0;
    return { done, total, pct };
  }

  function renderPlanList() {
    loadOverlayPlans();
    const list = document.getElementById("upPlanList");
    if (!list) return;
    if (!overlayState.plans.length) {
      list.innerHTML = '<div class="up-plan-row muted">No plans yet.</div>';
      return;
    }
    list.innerHTML = overlayState.plans.map((plan) => {
      const stat = getPlanStats(plan);
      const active = overlayState.activePlanId === plan.id;
      return `
        <button type="button" class="up-plan-row ${active ? "active" : ""}" onclick="showPlanDetail('${esc(plan.id)}')">
          <div>
            <strong>${esc(plan.title)}</strong>
            <span>${stat.done}/${stat.total} completed</span>
          </div>
          <b>${stat.pct}%</b>
        </button>
      `;
    }).join("");
  }

  function renderPlanDetail() {
    const detailView = document.getElementById("upPlanDetailView");
    const listView = document.getElementById("upPlanListView");
    const title = document.getElementById("upDetailTitle");
    const pct = document.getElementById("upDetailPct");
    const fill = document.getElementById("upDetailProgFill");
    const txt = document.getElementById("upDetailProgTxt");
    const items = document.getElementById("upDetailItems");
    if (!detailView || !listView || !title || !pct || !fill || !txt || !items) return;

    const plan = overlayState.plans.find((item) => item.id === overlayState.activePlanId) || overlayState.plans[0];
    if (!plan) {
      listView.classList.remove("hidden");
      detailView.classList.add("hidden");
      return;
    }
    overlayState.activePlanId = plan.id;
    const stat = getPlanStats(plan);

    title.textContent = plan.title;
    pct.textContent = `${stat.pct}%`;
    fill.style.width = `${stat.pct}%`;
    txt.textContent = `${stat.done} / ${stat.total} 已完成`;
    items.innerHTML = plan.items.map((item) => `
      <label class="up-item-row ${item.done ? "done" : ""}">
        <input type="checkbox" ${item.done ? "checked" : ""} onchange="togglePlanItem('${esc(plan.id)}','${esc(item.id)}')">
        <span>${esc(item.text)}</span>
      </label>
    `).join("");

    listView.classList.add("hidden");
    detailView.classList.remove("hidden");
  }

  function renderUserProfileOverlay() {
    loadOverlayPlans();
    const user = getCurrentUserSafe();
    const name = String(user?.display_name || user?.displayName || user?.username || "User");
    const roleTag = user?.role === "super_admin" ? "System Admin" : "User";
    const focusRole = getCurrentFocusRole();
    const completion = getOverlayCompletion();

    const nameEl = document.getElementById("upName");
    const roleEl = document.getElementById("upRoleTag");
    const avatarEl = document.getElementById("upAvatarCircle");
    if (nameEl) nameEl.textContent = name;
    if (roleEl) roleEl.textContent = roleTag;
    if (avatarEl) avatarEl.textContent = name.charAt(0).toUpperCase();

    const reportTitle = document.getElementById("upReportTitle");
    const reportSummary = document.getElementById("upReportSummary");
    const reportFocus = document.getElementById("upReportFocusRole");
    const reportNext = document.getElementById("upReportNextFocus");
    const reportCompletion = document.getElementById("upReportCompletion");
    const reportSync = document.getElementById("upReportLastSync");
    if (reportTitle) reportTitle.textContent = `${focusRole} 职业快照`;
    if (reportSummary) reportSummary.textContent = "系统会把当前主线岗位、关键缺口和下一步动作同步到这里。";
    if (reportFocus) reportFocus.textContent = focusRole;
    if (reportNext) reportNext.textContent = "继续补齐证据并推进主线";
    if (reportCompletion) reportCompletion.textContent = `${completion}%`;
    if (reportSync) reportSync.textContent = new Date().toLocaleString();

    const accountFocus = document.getElementById("upAccountFocusRole");
    const accountSummary = document.getElementById("upAccountSummary");
    const accountNext = document.getElementById("upAccountNextAction");
    const accountHint = document.getElementById("upAccountPermissionHint");
    if (accountFocus) accountFocus.textContent = focusRole;
    if (accountSummary) accountSummary.textContent = "该面板会持续同步你的岗位状态、计划执行与报告进展。";
    if (accountNext) accountNext.textContent = "先做最小可执行动作";
    if (accountHint) {
      accountHint.textContent = user?.role === "super_admin"
        ? "你当前是 system 用户，可管理模型与 API 配置。"
        : "普通用户可维护个人进度与计划，系统配置由管理员维护。";
    }

    const signals = document.getElementById("upReportSignals");
    if (signals) {
      const jobs = Array.isArray(window.appState?.selectedJobs) ? window.appState.selectedJobs : [];
      const chips = jobs.length ? jobs.slice(0, 4).map((id) => (window.jobNameMap?.[id] || id)) : [focusRole];
      signals.innerHTML = chips.map((item) => `<span class="up-report-chip">${esc(item)}</span>`).join("");
    }

    const tasks = document.getElementById("upReportTasks");
    if (tasks) {
      tasks.innerHTML = `
        <div class="up-report-list-item">
          <strong>锁定主线岗位</strong>
          <p>先确认一个主线岗位，避免多线分散。</p>
        </div>
        <div class="up-report-list-item">
          <strong>补齐关键证据</strong>
          <p>围绕主线补 2-3 条最关键的能力证据。</p>
        </div>
      `;
    }

    const progressFill = document.getElementById("upProgressFill");
    const progressText = document.getElementById("upProgressText");
    if (progressFill) progressFill.style.width = `${completion}%`;
    if (progressText) progressText.textContent = `${completion}%`;

    const reportsCount = Number(window.appState?.reportReady ? 1 : 0);
    const planDone = overlayState.plans.reduce((sum, plan) => sum + getPlanStats(plan).done, 0);
    const planTotal = overlayState.plans.reduce((sum, plan) => sum + getPlanStats(plan).total, 0);
    const statReports = document.getElementById("upStatReports");
    const statDone = document.getElementById("upStatDone");
    const statScore = document.getElementById("upStatScore");
    const statPending = document.getElementById("upStatPending");
    if (statReports) statReports.textContent = String(reportsCount);
    if (statDone) statDone.textContent = String(planDone);
    if (statScore) statScore.textContent = String(completion);
    if (statPending) statPending.textContent = String(Math.max(0, planTotal - planDone));

    renderPlanList();
    showPlanList();
  }

  function openUserProfile() {
    const overlay = document.getElementById("userProfileOverlay");
    if (!overlay) return;
    renderUserProfileOverlay();
    overlay.classList.remove("hidden");
  }

  function closeUserProfile() {
    const overlay = document.getElementById("userProfileOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
  }

  function handleOverlayBackdropClick(event) {
    if (event?.target?.id === "userProfileOverlay") closeUserProfile();
  }

  function handleAvatarClick(event) {
    event?.preventDefault?.();
    if (document.getElementById("userProfileOverlay")) {
      openUserProfile();
      return;
    }
    window.openUserCenterPage?.();
  }

  function showPlanList() {
    const detailView = document.getElementById("upPlanDetailView");
    const listView = document.getElementById("upPlanListView");
    if (detailView) detailView.classList.add("hidden");
    if (listView) listView.classList.remove("hidden");
    renderPlanList();
  }

  function showPlanDetail(planId) {
    overlayState.activePlanId = String(planId || "").trim();
    renderPlanDetail();
    renderPlanList();
  }

  function createNewPlan() {
    loadOverlayPlans();
    const name = String(window.prompt("请输入新规划名称", "新的职业规划") || "").trim();
    if (!name) return;
    const plan = {
      id: `plan_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      title: name,
      items: [{ id: `i_${Date.now()}`, text: "添加第一条行动项", done: false }]
    };
    overlayState.plans.unshift(plan);
    overlayState.activePlanId = plan.id;
    saveOverlayPlans();
    renderUserProfileOverlay();
    showPlanDetail(plan.id);
  }

  function addPlanItem() {
    const input = document.getElementById("upNewItemInput");
    const text = String(input?.value || "").trim();
    if (!text) return;
    const plan = overlayState.plans.find((item) => item.id === overlayState.activePlanId);
    if (!plan) return;
    plan.items.push({
      id: `i_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      text,
      done: false
    });
    if (input) input.value = "";
    saveOverlayPlans();
    renderPlanDetail();
    renderPlanList();
  }

  function togglePlanItem(planId, itemId) {
    const plan = overlayState.plans.find((item) => item.id === planId);
    if (!plan) return;
    const task = plan.items.find((item) => item.id === itemId);
    if (!task) return;
    task.done = !task.done;
    saveOverlayPlans();
    renderPlanDetail();
    renderPlanList();
    renderUserProfileOverlay();
  }

  function doCheckin() {
    const plan = overlayState.plans.find((item) => item.id === overlayState.activePlanId) || overlayState.plans[0];
    if (!plan) return;
    const nextTodo = plan.items.find((item) => !item.done);
    if (nextTodo) {
      nextTodo.done = true;
      saveOverlayPlans();
      renderPlanDetail();
      renderPlanList();
      renderUserProfileOverlay();
      safeToast("已打卡", `完成：${nextTodo.text}`, "success", 1600);
      return;
    }
    safeToast("提示", "当前规划已全部完成", "info", 1400);
  }

  if (typeof window.openUserProfile !== "function") window.openUserProfile = openUserProfile;
  if (typeof window.closeUserProfile !== "function") window.closeUserProfile = closeUserProfile;
  if (typeof window.handleOverlayBackdropClick !== "function") window.handleOverlayBackdropClick = handleOverlayBackdropClick;
  if (typeof window.handleAvatarClick !== "function") window.handleAvatarClick = handleAvatarClick;
  if (typeof window.showPlanList !== "function") window.showPlanList = showPlanList;
  if (typeof window.showPlanDetail !== "function") window.showPlanDetail = showPlanDetail;
  if (typeof window.createNewPlan !== "function") window.createNewPlan = createNewPlan;
  if (typeof window.addPlanItem !== "function") window.addPlanItem = addPlanItem;
  if (typeof window.doCheckin !== "function") window.doCheckin = doCheckin;
  if (typeof window.togglePlanItem !== "function") window.togglePlanItem = togglePlanItem;

  if (typeof window.handleDashboardPrimaryAction !== "function") {
    window.handleDashboardPrimaryAction = function handleDashboardPrimaryAction() {
      if (typeof window.showSection === "function") {
        window.showSection("jobs");
      }
    };
  }

  if (typeof window.startCareerReportGeneration !== "function") {
    window.startCareerReportGeneration = function startCareerReportGeneration() {
      if (typeof window.openUserCenterPage === "function") {
        window.openUserCenterPage("report-workspace", { action: "generate" });
        return;
      }
      window.showSection?.("report");
    };
  }

  if (typeof window.generateProfilePortrait !== "function") {
    window.generateProfilePortrait = function generateProfilePortrait() {
      window.showSection?.("profile");
      safeToast("提示", "请先完善画像输入，再生成画像。", "info", 1600);
    };
  }

  if (typeof window.openReportViewer !== "function") {
    window.openReportViewer = function openReportViewer() {
      window.openUserCenterPage?.("report-workspace");
    };
  }

  if (typeof window.closeReportViewer !== "function") {
    window.closeReportViewer = function closeReportViewer() {};
  }

  function tryAutoOpenGuide() {
    if (guideAutoOpened || !isAuthenticatedSafe() || !document.getElementById("workspaceSetupGuide")) return;
    const forceOpen = consumeForceWorkspaceGuideFlag();
    if (!forceOpen && window.hasSeenWorkspaceGuide()) return;
    guideAutoOpened = true;
    window.setTimeout(() => openWorkspaceGuide(forceOpen), 420);
  }

  function bootstrap() {
    const dialog = document.getElementById("workspaceSetupGuide");
    dialog?.querySelector("[data-guide-refresh]").addEventListener("click", refreshWorkspaceGuide);
    dialog?.querySelectorAll("[data-guide-section]").forEach(button => {
      button.addEventListener("click", () => {
        const section = button.dataset.guideSection;
        dialog.close();
        window.showSection?.(section);
      });
    });
    document.querySelectorAll("[data-open-workspace-guide]").forEach(button => {
      button.addEventListener("click", () => openWorkspaceGuide(true));
    });
    tryAutoOpenGuide();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }

  window.addEventListener("app:auth-changed", () => {
    guideAutoOpened = false;
    overlayState.loaded = false;
    overlayState.plans = [];
    overlayState.activePlanId = "";
    closeUserProfile();
    if (!isAuthenticatedSafe()) window.closeWorkspaceGuide();
    window.setTimeout(() => {
      tryAutoOpenGuide();
      renderUserProfileOverlay();
    }, 80);
  });
})();
