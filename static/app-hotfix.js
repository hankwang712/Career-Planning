(function () {
  const GUIDE_VERSION = "v8";
  const PLAN_STORAGE_PREFIX = "dp_overlay_plans_v1_";

  const guideState = {
    open: false,
    autoOpened: false,
    currentIndex: 0,
    steps: [],
    activeAction: null
  };

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
    const url = new URL("/user-center.html", window.location.origin);
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value === null || value === undefined || value === "") return;
      url.searchParams.set(key, String(value));
    });
    const safeAnchor = String(anchor || "").trim().replace(/^#/, "");
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

  function getGuideElements() {
    return {
      overlay: document.getElementById("workspaceGuideOverlay"),
      fullFrost: document.getElementById("workspaceGuideFullFrost"),
      frostFrame: document.getElementById("workspaceGuideFrostFrame"),
      highlight: document.getElementById("workspaceGuideHighlight"),
      card: document.getElementById("workspaceGuideCard"),
      stepLabel: document.getElementById("workspaceGuideStepLabel"),
      kicker: document.getElementById("workspaceGuideKicker"),
      title: document.getElementById("workspaceGuideTitle"),
      copy: document.getElementById("workspaceGuideCopy"),
      meta: document.getElementById("workspaceGuideMeta"),
      primaryBtn: document.getElementById("workspaceGuidePrimaryBtn"),
      prevBtn: document.getElementById("workspaceGuidePrevBtn"),
      nextBtn: document.getElementById("workspaceGuideNextBtn")
    };
  }

  function syncGuideOverlayLock() {
    const { overlay, highlight, card, fullFrost, frostFrame } = getGuideElements();
    if (!overlay) return;
    const isVisible = !overlay.classList.contains("hidden");
    overlay.style.pointerEvents = "none";
    /* 具体可点击性由 workspace-shell.css 中 #workspaceGuideCard 规则保证；此处仅清理隐藏态 */
    if (card) card.style.removeProperty("pointer-events");
    document.body.classList.toggle("workspace-guide-open", isVisible);
    guideState.open = isVisible;

    if (!isVisible) {
      guideState.activeAction = null;
      document.body.classList.remove("workspace-guide-phase-intro", "workspace-guide-phase-spotlight");
      overlay.classList.remove("workspace-guide-phase-intro", "workspace-guide-phase-spotlight");
      highlight?.classList.remove("is-intro");
      if (highlight) highlight.style.opacity = "0";
      card?.classList.remove("workspace-guide-card--intro");
      fullFrost?.classList.add("hidden");
      frostFrame?.classList.add("hidden");
    }

    if (typeof window.updateWorkspaceJourneyVisibility === "function") {
      window.updateWorkspaceJourneyVisibility();
    }
  }

  function buildWorkspaceGuideSteps() {
    return [
      {
        phase: "intro",
        selector: "#workspaceJourneyBand",
        kicker: "Step 01",
        title: "总览工作台流程",
        copy: "先看 01-06 的全链路，你会知道每一块在什么时候做最有效。",
        meta: "当前页是第一步，后续会逐个定位到每个模块入口。",
        actionLabel: "去工作台",
        onPrimary: () => window.showSection?.("dashboard")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="dashboard"]',
        kicker: "Step 02",
        title: "工作台入口",
        copy: "这里回到总览面板，系统会汇总下一步建议和关键进度。",
        meta: "建议每天先从这里开始。",
        actionLabel: "打开工作台",
        onPrimary: () => window.showSection?.("dashboard")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="jobs"]',
        kicker: "Step 03",
        title: "岗位探索",
        copy: "对比城市、岗位和门槛，先明确主线目标岗位。",
        meta: "主线越清晰，后续报告越有价值。",
        actionLabel: "去岗位探索",
        onPrimary: () => window.showSection?.("jobs")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="profile"]',
        kicker: "Step 04",
        title: "画像输入",
        copy: "补齐测评、简历、访谈，系统会自动识别当前缺口。",
        meta: "优先补最关键的证据项。",
        actionLabel: "去画像输入",
        onPrimary: () => window.showSection?.("profile")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="matching"]',
        kicker: "Step 05",
        title: "人岗匹配",
        copy: "查看候选岗位与能力差距，确认当前最值得推进的一条线。",
        meta: "这一步会直接影响报告结论。",
        actionLabel: "去人岗匹配",
        onPrimary: () => window.showSection?.("matching")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="report"]',
        kicker: "Step 06",
        title: "职业报告",
        copy: "在这里进入报告工作区，查看版本、结论和行动清单。",
        meta: "支持持续迭代，不是一次性输出。",
        actionLabel: "去职业报告",
        onPrimary: () => window.showSection?.("report")
      },
      {
        phase: "spotlight",
        selector: 'button[data-section="qa"]',
        kicker: "Step 07",
        title: "决策问答",
        copy: "用于快速对比方案和澄清疑问，作为决策辅助。",
        meta: "适合做短问题验证。",
        actionLabel: "去决策问答",
        onPrimary: () => window.showSection?.("qa")
      },
      {
        phase: "spotlight",
        selector: ".topbar-avatar-btn",
        kicker: "Step 08",
        title: "个人中心入口",
        copy: "点击头像进入新界面，可看你的岗位板、计划和账号配置。",
        meta: "你可以随时重新打开本引导。",
        actionLabel: "打开个人中心",
        onPrimary: () => window.handleAvatarClick?.(new Event("click"))
      }
    ];
  }

  function setGuideStepContent(step) {
    const { stepLabel, kicker, title, copy, meta, primaryBtn, prevBtn, nextBtn } = getGuideElements();
    const total = guideState.steps.length || 1;
    const current = Math.min(total, guideState.currentIndex + 1);
    if (stepLabel) stepLabel.textContent = `${String(current).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;
    if (kicker) kicker.textContent = step.kicker || "Guide";
    if (title) title.textContent = step.title || "Guide";
    if (copy) copy.textContent = step.copy || "";
    if (meta) meta.textContent = step.meta || "";
    if (primaryBtn) primaryBtn.textContent = step.actionLabel || "Go";
    if (prevBtn) {
      const disabled = guideState.currentIndex <= 0;
      prevBtn.disabled = disabled;
      prevBtn.classList.toggle("is-disabled", disabled);
      prevBtn.setAttribute("aria-disabled", disabled ? "true" : "false");
    }
    if (nextBtn) {
      nextBtn.textContent = guideState.currentIndex >= total - 1 ? "完成" : "下一步";
    }
  }

  function getGuideTargetRect(step) {
    const target = step?.selector ? document.querySelector(step.selector) : null;
    if (!target || typeof target.getBoundingClientRect !== "function") return null;
    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return rect;
  }

  function positionWorkspaceGuide(step) {
    const { overlay, highlight, card, fullFrost, frostFrame } = getGuideElements();
    if (!overlay || !highlight || !card || !step) return;

    const isIntro = step.phase === "intro";
    document.body.classList.toggle("workspace-guide-phase-intro", isIntro);
    document.body.classList.toggle("workspace-guide-phase-spotlight", !isIntro);
    overlay.classList.toggle("workspace-guide-phase-intro", isIntro);
    overlay.classList.toggle("workspace-guide-phase-spotlight", !isIntro);
    highlight.classList.toggle("is-intro", isIntro);
    card.classList.toggle("workspace-guide-card--intro", false);

    fullFrost?.classList.add("hidden");
    frostFrame?.classList.add("hidden");

    setGuideStepContent(step);
    guideState.activeAction = typeof step.onPrimary === "function" ? step.onPrimary : null;

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const rect = getGuideTargetRect(step);

    if (!rect) {
      highlight.style.opacity = "0";
      card.style.width = `${Math.min(420, viewportWidth - 32)}px`;
      card.style.left = "50%";
      card.style.top = "50%";
      card.style.bottom = "auto";
      card.style.transform = "translate(-50%, -50%)";
      if (typeof window.updateWorkspaceJourneyVisibility === "function") {
        window.updateWorkspaceJourneyVisibility();
      }
      return;
    }

    highlight.style.opacity = "1";
    highlight.style.left = `${Math.max(10, rect.left - 8)}px`;
    highlight.style.top = `${Math.max(10, rect.top - 8)}px`;
    highlight.style.width = `${Math.max(64, rect.width + 16)}px`;
    highlight.style.height = `${Math.max(44, rect.height + 16)}px`;

    const cardWidth = Math.min(420, viewportWidth - 32);
    card.style.width = `${cardWidth}px`;
    card.style.transform = "none";

    const cardHeight = Math.max(220, Math.min(360, card.offsetHeight || 260));
    const spaceBelow = viewportHeight - rect.bottom;
    const placeBelow = spaceBelow >= (cardHeight + 18);
    const top = placeBelow
      ? Math.min(viewportHeight - cardHeight - 12, rect.bottom + 14)
      : Math.max(12, rect.top - cardHeight - 14);
    const left = Math.max(12, Math.min(viewportWidth - cardWidth - 12, rect.left));

    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
    card.style.bottom = "auto";

    if (typeof window.updateWorkspaceJourneyVisibility === "function") {
      window.updateWorkspaceJourneyVisibility();
    }
  }

  function openWorkspaceGuide(force = false) {
    const { overlay } = getGuideElements();
    if (!overlay) return;
    if (!isAuthenticatedSafe()) return;
    if (!force && window.hasSeenWorkspaceGuide?.()) return;
    guideState.steps = buildWorkspaceGuideSteps();
    guideState.currentIndex = 0;
    overlay.classList.remove("hidden");
    syncGuideOverlayLock();
    positionWorkspaceGuide(guideState.steps[0]);
    window.requestAnimationFrame(() => {
      positionWorkspaceGuide(guideState.steps[0]);
    });
  }

  function closeWorkspaceGuide(markSeen = false) {
    const { overlay, highlight } = getGuideElements();
    if (overlay) overlay.classList.add("hidden");
    if (highlight) {
      highlight.style.opacity = "0";
      highlight.classList.remove("is-intro");
    }
    if (markSeen) window.setSeenWorkspaceGuide?.();
    syncGuideOverlayLock();
  }

  function nextWorkspaceGuideStep() {
    if (!guideState.open) return;
    if (guideState.currentIndex >= guideState.steps.length - 1) {
      closeWorkspaceGuide(true);
      return;
    }
    guideState.currentIndex += 1;
    positionWorkspaceGuide(guideState.steps[guideState.currentIndex]);
  }

  function prevWorkspaceGuideStep() {
    if (!guideState.open) return;
    if (guideState.currentIndex <= 0) return;
    guideState.currentIndex -= 1;
    positionWorkspaceGuide(guideState.steps[guideState.currentIndex]);
  }

  function handleWorkspaceGuidePrimary() {
    if (typeof guideState.activeAction === "function") {
      guideState.activeAction();
    }
    if (guideState.open) {
      window.setTimeout(() => {
        positionWorkspaceGuide(guideState.steps[guideState.currentIndex]);
      }, 80);
    }
  }

  function handleWorkspaceGuideBackdropClick(event) {
    if (event?.target?.id === "workspaceGuideOverlay") {
      closeWorkspaceGuide(true);
    }
  }

  window.openWorkspaceGuide = openWorkspaceGuide;
  window.closeWorkspaceGuide = closeWorkspaceGuide;
  window.nextWorkspaceGuideStep = nextWorkspaceGuideStep;
  window.prevWorkspaceGuideStep = prevWorkspaceGuideStep;
  window.handleWorkspaceGuidePrimary = handleWorkspaceGuidePrimary;
  window.handleWorkspaceGuideBackdropClick = handleWorkspaceGuideBackdropClick;

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
    if (typeof window.openSettingsPanel === "function") {
      window.openSettingsPanel();
      return;
    }
    window.openUserCenterPage?.("report-workspace");
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
    if (guideState.autoOpened) return;
    if (!isAuthenticatedSafe()) return;
    if (window.hasSeenWorkspaceGuide?.()) return;
    const overlay = document.getElementById("workspaceGuideOverlay");
    if (!overlay) return;
    guideState.autoOpened = true;
    window.setTimeout(() => {
      window.openWorkspaceGuide?.(false);
    }, 420);
  }

  function mountGuideOverlayObserver() {
    const overlay = document.getElementById("workspaceGuideOverlay");
    if (!overlay) return;
    syncGuideOverlayLock();
    const observer = new MutationObserver(syncGuideOverlayLock);
    observer.observe(overlay, { attributes: true, attributeFilter: ["class"] });
  }

  function onResizeOrScroll() {
    if (!guideState.open) return;
    const step = guideState.steps[guideState.currentIndex];
    if (!step) return;
    positionWorkspaceGuide(step);
  }

  function onGuideEscape(event) {
    if (event.key !== "Escape") return;
    if (!guideState.open) return;
    event.preventDefault();
    closeWorkspaceGuide(true);
  }

  function bootstrap() {
    mountGuideOverlayObserver();
    tryAutoOpenGuide();
    window.addEventListener("resize", onResizeOrScroll);
    window.addEventListener("scroll", onResizeOrScroll, { passive: true });
    document.addEventListener("keydown", onGuideEscape);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }

  window.addEventListener("app:auth-changed", () => {
    guideState.autoOpened = false;
    overlayState.loaded = false;
    overlayState.plans = [];
    overlayState.activePlanId = "";
    closeUserProfile();
    syncGuideOverlayLock();
    window.setTimeout(() => {
      tryAutoOpenGuide();
      renderUserProfileOverlay();
    }, 80);
  });
})();
