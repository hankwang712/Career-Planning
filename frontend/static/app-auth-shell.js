// 登录与锁定、导航、仪表盘与各分区切换
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function animateCounter(el, target, suffix = "", duration = 500) {
  if (!el) return;
  const from = Number((el.textContent || "").replace(/[^\d.-]/g, "")) || 0;
  if (from === target) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  if (el.offsetParent === null) {
    el.textContent = `${target}${suffix}`;
    return;
  }
  const start = performance.now();
  function frame(now) {
    const p = Math.min(1, (now - start) / duration);
    const val = Math.round(from + (target - from) * p);
    el.textContent = `${val}${suffix}`;
    if (p < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function getRelockReturnTarget() {
  try {
    const url = new URL(window.location.href);
    const raw = String(url.searchParams.get("return_to") || "").trim();
    if (!raw) return "";
    if (/^https?:\/\//i.test(raw)) {
      const parsed = new URL(raw);
      if (parsed.origin !== window.location.origin) return "";
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    }
    return raw.startsWith("/") ? raw : `/${raw.replace(/^\/+/, "")}`;
  } catch (_) {
    return "";
  }
}

function shouldForceRelock() {
  try {
    const url = new URL(window.location.href);
    return ["1", "true", "yes"].includes(String(url.searchParams.get("force_lock") || "").trim().toLowerCase());
  } catch (_) {
    return false;
  }
}

function consumeRelockParams() {
  try {
    const url = new URL(window.location.href);
    let changed = false;
    if (url.searchParams.has("force_lock")) {
      url.searchParams.delete("force_lock");
      changed = true;
    }
    if (url.searchParams.has("return_to")) {
      url.searchParams.delete("return_to");
      changed = true;
    }
    if (changed) window.history.replaceState({}, "", url.toString());
  } catch (_) {}
}

function redirectAfterUnlock() {
  const target = getRelockReturnTarget();
  if (!target) return false;
  consumeRelockParams();
  window.location.href = target;
  return true;
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
  const startupScreen = document.getElementById("startupScreen");
  if (startupScreen && document.getElementById("loginAuthFeedback")) {
    startupScreen.classList.toggle("auth-mode-login", isLogin);
    startupScreen.classList.toggle("auth-mode-register", !isLogin);
    clearInactiveAuthFeedback(isLogin);
  }
  if (isLogin) {
    showAuthMessage("使用账号和密码登录，并完成安全验证。");
  } else {
    showAuthMessage("输入邮箱和密码即可创建账户，注册成功后会自动登录。");
  }
}

function closeNavWorkspaceMenu() {
  const menu = document.getElementById("navWorkspaceMenu");
  const toggle = document.getElementById("navWorkspaceToggle");
  if (menu) menu.classList.add("hidden");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "false");
    toggle.classList.remove("nav-workspace-menu-open");
  }
}

function initNavWorkspaceMenu() {
  const shell = document.getElementById("navWorkspaceShell");
  const toggle = document.getElementById("navWorkspaceToggle");
  const menu = document.getElementById("navWorkspaceMenu");
  if (!shell || !toggle || !menu) return;
  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = !menu.classList.contains("hidden");
    if (isOpen) closeNavWorkspaceMenu();
    else {
      menu.classList.remove("hidden");
      toggle.setAttribute("aria-expanded", "true");
      toggle.classList.add("nav-workspace-menu-open");
    }
  });
  document.addEventListener("click", (e) => {
    if (!shell.contains(e.target)) closeNavWorkspaceMenu();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeNavWorkspaceMenu();
  });
}

function clearPrivateWorkspace() {
  accountRequestEpoch += 1;
  window.ReportReview?.reset();
  Object.assign(reportResumeUiState, { pending: false, loaded: false, source: null, error: "" });
  Object.assign(reportWizardUiState, { stage: 2, runtimeKey: "", started: false, manual: false });
  document.getElementById("reportWorkflowInput")?.reset();
  document.getElementById("reportWorkflowTargets")?.removeAttribute("data-edited");
  reportGenerationStarting = false;
  reportGenerationError = "";
  inFlightGetRequests.clear();
  stopCareerReportPolling();
  stopAnalyzeProgressTicker();
  stopProfilePortraitLoading();
  Object.keys(userWorkspaceState.scopedData).forEach(key => { userWorkspaceState.scopedData[key] = null; });
  Object.keys(userWorkspaceState.scopedDataLoaded).forEach(key => { userWorkspaceState.scopedDataLoaded[key] = false; });
  Object.keys(userWorkspaceState.llmConfigs).forEach(key => { userWorkspaceState.llmConfigs[key] = null; });
  Object.assign(appState, { careerReport: null, careerReportState: null, careerReportTracker: null,
    careerReportVersions: [], careerReportCanonicalId: "", careerReportViewingHistorical: false,
    reportGenerated: false, reportReady: false, derivedProfile: null, matchingRoles: [], focusedRoleId: "",
    selectedJobs: [], profileComplete: false, profileCompletion: 0, baseExploredJobs: 0, score: 0, lastGreetingKey: "" });
  Object.assign(resumeTaskState, { uploadInFlight: false, analyzeInFlight: false, forceInputView: false, deckIndices: {} });
  reportWorkflowSnapshot = null;
  resetCareerInterviewState({ preserveBasics: false });
  window.closeReportViewer?.();
  window.renderCareerReportPanels?.();
}

function lockApp() {
  void window.CareerAuth.ensureReady();
  clearPrivateWorkspace();
  userWorkspaceState.currentUser = null;
  userWorkspaceState.authReadyPromise = null;
  document.body.classList.remove("auth-checking");
  document.body.classList.add("auth-locked");
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const avatar = document.getElementById("currentUserAvatar");
  const shell = document.getElementById("navWorkspaceShell");
  if (startup) startup.classList.remove("hidden");
  if (label) label.textContent = "未登录";
  if (shell) shell.classList.add("hidden");
  if (typeof window.loadAccountAvatarState === "function") {
    void window.loadAccountAvatarState(true);
  } else if (avatar) {
    avatar.textContent = "人";
  }
  closeNavWorkspaceMenu();
  if (typeof window.__hidePageLoader === "function") {
    requestAnimationFrame(() => window.__hidePageLoader());
  }
}

function unlockAppForUser(user) {
  if (userWorkspaceState.currentUser?.username !== user.username) clearPrivateWorkspace();
  userWorkspaceState.currentUser = user;
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const avatar = document.getElementById("currentUserAvatar");
  const shell = document.getElementById("navWorkspaceShell");
  const hadAuthChecking = document.body.classList.contains("auth-checking");
  let postLogin = false;
  try {
    postLogin = sessionStorage.getItem("app_post_login_refresh") === "1";
    if (postLogin) sessionStorage.removeItem("app_post_login_refresh");
  } catch (_) {
    postLogin = false;
  }
  document.body.classList.remove("auth-checking", "auth-locked");
  if (startup) startup.classList.add("hidden");
  if (label) label.textContent = `${user.display_name || user.displayName || user.username} (${user.role === "super_admin" ? "Super Admin" : "User"})`;
  if (shell) shell.classList.remove("hidden");
  if (typeof window.loadAccountAvatarState === "function") {
    void window.loadAccountAvatarState(true);
  } else if (avatar) {
    avatar.textContent = user.role === "super_admin" ? "管" : "人";
  }
  addLiveActivity(`User signed in: ${user.username}`);
  const silentSessionRestore = hadAuthChecking && !postLogin;
  if (!silentSessionRestore) {
    showToast("登录成功", `欢迎回来，${user.display_name || user.displayName || user.username}。`, "success", 1800);
  }
  emitAuthStateChange();
  if (redirectAfterUnlock()) return;
  if (typeof window.__hidePageLoader === "function") {
    requestAnimationFrame(() => window.__hidePageLoader());
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) return showAuthMessage("请输入账号和密码。", "error");
  const submitBtn = event.target?.querySelector?.('button[type="submit"]');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.dataset.originalLabel = submitBtn.textContent;
    submitBtn.textContent = "登录中…";
  }
  try {
    await requestJson("/api/auth/login", {
      method: "POST",
      body: { username, password, ...await window.CareerAuth.credentials("login") }
    });
    try {
      sessionStorage.setItem("app_post_login_refresh", "1");
    } catch (_) {
      // ignore
    }
    if (typeof window.__showPageLoader === "function") {
      window.__showPageLoader({
        brand: shouldForceRelock() ? "解 锁 成 功" : "登 录 成 功",
        tip: shouldForceRelock()
          ? "正在返回上一界面 · Restoring your session"
          : "正在进入你的工作台 · Preparing your workspace"
      });
    }
    if (shouldForceRelock()) {
      showAuthMessage("解锁成功，正在返回上一界面……", "success");
    } else {
      showAuthMessage("登录成功，正在进入你的独立空间……", "success");
    }
    window.setTimeout(() => window.location.reload(), 360);
  } catch (error) {
    if (submitBtn) {
      submitBtn.disabled = false;
      if (submitBtn.dataset.originalLabel) submitBtn.textContent = submitBtn.dataset.originalLabel;
    }
    showAuthMessage(error.message || "登录失败，请稍后重试。", "error");
    void window.CareerAuth.refresh("login");
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const email = (document.getElementById("registerUsername")?.value || "").trim();
  const password = document.getElementById("registerPassword")?.value || "";
  const confirmPassword = document.getElementById("registerConfirmPassword")?.value || "";
  if (!email || !password || !confirmPassword) {
    showAuthMessage("请完整填写邮箱和密码。", "error");
    return;
  }
  const submitBtn = event.target?.querySelector?.('button[type="submit"]');
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.dataset.originalLabel = submitBtn.textContent;
    submitBtn.textContent = "创建中…";
  }
  showAuthMessage("正在创建账户，请稍候……");
  try {
    await requestJson("/api/auth/register", {
      method: "POST",
      body: {
        email,
        password,
        confirm_password: confirmPassword,
        ...await window.CareerAuth.credentials("register")
      }
    });
    if (typeof window.__showPageLoader === "function") {
      window.__showPageLoader({
        brand: "注 册 成 功",
        tip: "正在初始化你的独立空间 · Initializing your workspace"
      });
    }
    showAuthMessage("注册成功，正在进入你的独立空间……", "success");
    window.setTimeout(() => window.location.reload(), 360);
  } catch (error) {
    if (submitBtn) {
      submitBtn.disabled = false;
      if (submitBtn.dataset.originalLabel) submitBtn.textContent = submitBtn.dataset.originalLabel;
    }
    showAuthMessage(error.message || "注册失败，请稍后重试。", "error");
    void window.CareerAuth.refresh("register");
  }
}

async function logout() {
  if (typeof window.__showPageLoader === "function") {
    window.__showPageLoader({
      brand: "正 在 退 出",
      tip: "正在安全退出当前会话 · Signing you out"
    });
  }
  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (_) {
    // ignore logout race
  }
  window.location.reload();
}

async function initAuth() {
  if (userWorkspaceState.authReadyPromise) return userWorkspaceState.authReadyPromise;
  userWorkspaceState.authReadyPromise = (async () => {
    try {
      let payload = null;
      try {
        payload = await requestJson("/api/auth/status?bootstrap=1");
      } catch (bootstrapError) {
        console.warn("bootstrap endpoint unavailable, fallback to auth/status", bootstrapError);
        payload = await requestJson("/api/auth/status");
      }
      if (payload.authenticated && payload.user) {
        if (shouldForceRelock()) {
          const returnTarget = getRelockReturnTarget();
          consumeRelockParams();
          if (returnTarget) {
            window.location.replace(returnTarget);
            return null;
          }
          // 已登录且无 return_to：仅去掉 force_lock 参数，正常进入系统，不再弹出假登录
        }
        unlockAppForUser(payload.user);
        const llm = payload.llm || {};
        const scoped = payload.scoped_data || {};
        if (typeof llm.configured === "boolean") {
          const config = { base_url: "", api_key: "", model: String(llm.model || "").trim(), configured: llm.configured, editable: false, api_key_masked: "" };
          userWorkspaceState.llmConfigs.career_interview = config;
          userWorkspaceState.llmConfigs.assessment_hub = config;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "career_interview")) {
          userWorkspaceState.scopedData.career_interview = scoped.career_interview ?? null;
          userWorkspaceState.scopedDataLoaded.career_interview = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "assessment_hub")) {
          userWorkspaceState.scopedData.assessment_hub = scoped.assessment_hub ?? null;
          userWorkspaceState.scopedDataLoaded.assessment_hub = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "resume_profile")) {
          userWorkspaceState.scopedData.resume_profile = scoped.resume_profile || emptyResumeProfile();
          userWorkspaceState.scopedDataLoaded.resume_profile = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "career_report")) {
          userWorkspaceState.scopedData.career_report = scoped.career_report ?? null;
          userWorkspaceState.scopedDataLoaded.career_report = true;
          appState.careerReportState = scoped.career_report ?? null;
          appState.reportGenerated = isCareerReportReadyStatus(scoped.career_report?.status);
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "profile_portrait")) {
          userWorkspaceState.scopedData.profile_portrait = scoped.profile_portrait ?? null;
          userWorkspaceState.scopedDataLoaded.profile_portrait = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "account_avatar")) {
          userWorkspaceState.scopedData.account_avatar = scoped.account_avatar ?? null;
          userWorkspaceState.scopedDataLoaded.account_avatar = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "profile_snapshot")) {
          userWorkspaceState.scopedData.profile_snapshot = scoped.profile_snapshot ?? null;
          userWorkspaceState.scopedDataLoaded.profile_snapshot = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "career_matching")) {
          userWorkspaceState.scopedData.career_matching = scoped.career_matching ?? null;
          userWorkspaceState.scopedDataLoaded.career_matching = true;
        }
        if (Object.prototype.hasOwnProperty.call(scoped, "news_context")) {
          userWorkspaceState.scopedData.news_context = scoped.news_context ?? null;
          userWorkspaceState.scopedDataLoaded.news_context = true;
        }
        await Promise.allSettled([
          loadCareerInterviewConfig(false),
          hydrateCareerInterviewState(false),
          refreshResumeProfile(false),
          loadProfilePortraitState(false)
        ]);
        return payload.user;
      }
    } catch (error) {
      console.error("init auth failed", error);
    }
    lockApp();
    switchAuthTab("login");
    emitAuthStateChange();
    return null;
  })();
  return userWorkspaceState.authReadyPromise;
}

function setTagState(el, state) {
  if (!el) return;
  el.classList.remove("text-green-600", "text-orange-600", "text-red-600");
  if (state === "done") { el.classList.add("text-green-600"); el.textContent = "已完成"; }
  else if (state === "processing") { el.classList.add("text-orange-600"); el.textContent = "进行中"; }
  else { el.classList.add("text-red-600"); el.textContent = "待完成"; }
}

function updateReportDates(baseDate = new Date()) {
  const validDate = addMonths(baseDate, 6);
  const generatedTime = document.getElementById("reportGeneratedTime");
  const headerDate = document.getElementById("reportHeaderDate");
  const footerGenerated = document.getElementById("reportFooterGeneratedDate");
  const footerValid = document.getElementById("reportFooterValidDate");
  const footerYear = document.getElementById("footerYear");
  if (generatedTime) generatedTime.textContent = formatDateCN(baseDate, true);
  if (headerDate) headerDate.textContent = formatDateCN(baseDate);
  if (footerGenerated) footerGenerated.textContent = formatDateCN(baseDate);
  if (footerValid) footerValid.textContent = formatDateCN(validDate);
  if (footerYear) footerYear.textContent = String(baseDate.getFullYear());
}

function normalizeGenderLabel(raw) {
  const v = String(raw || "").trim().toLowerCase();
  if (!v) return "";
  if (/^(m|male|man|boy|男|男性|先生)$/i.test(v) || v.includes("男")) return "male";
  if (/^(f|female|woman|girl|女|女性|女士)$/i.test(v) || v.includes("女")) return "female";
  return "";
}

function resolveDashboardPortraitGender() {
  const basicsGender = appState.derivedProfile?.basics?.gender;
  const interviewGender = careerInterviewState?.profileBasics?.gender;
  const userGender = getCurrentUser()?.gender;
  return normalizeGenderLabel(basicsGender || interviewGender || userGender || "");
}

function updateDashboardPortraitVisual() {
  const imageEl = document.getElementById("dashboardPortraitImage");
  const badgeEl = document.getElementById("dashboardPortraitBadge");
  const toneEl = document.getElementById("dashboardPortraitTone");
  const visualEl = document.getElementById("dashboardPortraitVisual");
  if (imageEl) {
    imageEl.removeAttribute("src");
    imageEl.setAttribute("alt", "");
    imageEl.hidden = true;
  }
  if (badgeEl) badgeEl.textContent = "";
  if (toneEl) toneEl.textContent = "";
  if (visualEl) {
    visualEl.classList.remove("is-female", "is-male");
  }
}

function updateLiveClock() {
  const now = new Date();
  const clockEl = document.getElementById("liveClock");
  if (clockEl) clockEl.textContent = formatClock(now);
  updateDashboardPortraitVisual();
  const greetingKey = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${now.getHours()}`;
  if (appState.lastGreetingKey === greetingKey) return;
  appState.lastGreetingKey = greetingKey;
  const title = document.getElementById("welcomeTitle");
  const subtitle = document.getElementById("welcomeSubtitle");
  const displayName = getCurrentUser()?.display_name || getCurrentUser()?.displayName || getCurrentUser()?.username || "同学";
  const h = now.getHours();
  let greeting = "晚上好";
  if (h >= 6 && h < 12) greeting = "早上好";
  if (h >= 12 && h < 18) greeting = "下午好";
  const dayIndex = Math.ceil((now - new Date(now.getFullYear(), 0, 1)) / 86400000);
  if (title) title.textContent = `${greeting}，${displayName}`;
  if (subtitle) subtitle.textContent = `今天是 ${formatDateCN(now)}，年度第 ${dayIndex} 天，系统正在用最新测评、访谈和基础信息更新你的职业画像。`;
}

function updateTaskPanels(explored) {
  const exploreStatus = document.getElementById("taskJobExploreStatus");
  const exploreStatusCard = document.getElementById("taskJobExploreStatusCard");
  const exploreTag = document.getElementById("taskJobExploreTag");
  const exploreTagCard = document.getElementById("taskJobExploreTagCard");
  const progressHint = document.getElementById("taskProgressHint");
  const progressHintDisplay = document.getElementById("taskProgressHintDisplay");
  const reportBtn = document.getElementById("generateReportBtn");
  const reportBtnCard = document.getElementById("generateReportBtnCard");
  const exploredDone = explored >= 3;
  const exploreText = `已形成 ${explored} 个初步岗位方向`;
  if (exploreStatus) exploreStatus.textContent = exploreText;
  if (exploreStatusCard) exploreStatusCard.textContent = exploreText;
  setTagState(exploreTag, exploredDone ? "done" : "processing");
  setTagState(exploreTagCard, exploredDone ? "done" : "processing");
  const doneCount = [appState.profileComplete, exploredDone, appState.reportGenerated].filter(Boolean).length;
  if (progressHint) progressHint.textContent = `已完成 ${doneCount}/3 个关键任务`;
  if (progressHintDisplay) progressHintDisplay.textContent = `已完成 ${doneCount}/3 个关键任务`;
  [reportBtn, reportBtnCard].forEach((button) => {
    if (!button) return;
    if (appState.reportGenerated) {
      button.textContent = "报告已更新";
      button.classList.add("bg-green-600", "hover:bg-green-700");
      button.classList.remove("bg-purple-600", "hover:bg-purple-700", "bg-violet-600", "hover:bg-violet-700");
    } else {
      button.textContent = "生成当前报告";
      if (button.id === "generateReportBtnCard") {
        button.classList.add("bg-violet-600", "hover:bg-violet-700");
        button.classList.remove("bg-green-600", "hover:bg-green-700");
      } else {
        button.classList.add("bg-purple-600", "hover:bg-purple-700");
        button.classList.remove("bg-green-600", "hover:bg-green-700");
      }
    }
  });
}

function updateDashboardMetrics() {
  const roles = Array.isArray(appState.matchingRoles) ? appState.matchingRoles : [];
  const profile = appState.derivedProfile;
  updateDashboardPortraitVisual();
  const topRoleData = roles[0];
  const explored = roles.slice(0, 3).length;
  const topRate = topRoleData?.overallScore || topRoleData?.trait?.score || 0;
  const topJob = topRoleData?.name || "等待岗位方向";
  const pending = profile ? profile.missingItems.length + (appState.reportGenerated ? 0 : 1) : 4;
  animateCounter(document.getElementById("exploredJobsCount"), explored);
  animateCounter(document.getElementById("profileCompletionRate"), appState.profileCompletion, "%");
  animateCounter(document.getElementById("topMatchRate"), topRate, "%");
  animateCounter(document.getElementById("pendingTaskCount"), pending);
  animateCounter(document.getElementById("dashboardScore"), appState.score, "%");
  const topRole = document.getElementById("topMatchRole");
  const scoreTrend = document.getElementById("scoreTrend");
  const profileHint = document.getElementById("profileCompletionHint");
  const pendingHint = document.getElementById("pendingTaskHint");
  if (topRole) topRole.textContent = topJob;
  if (scoreTrend) scoreTrend.textContent = topRoleData ? `Top1 置信度 ${topRoleData.confidence}` : "等待画像输入";
  if (profileHint) profileHint.textContent = profile?.missingItems?.length ? `待补充 ${profile.missingItems.length} 项` : "画像基础已就绪";
  if (pendingHint) pendingHint.textContent = pending === 0 ? "全部完成" : "优先补基础信息和访谈";
  updateTaskPanels(explored);
}

function markReportGenerated(source = "view") {
  if (!appState.reportGenerated) {
    appState.reportGenerated = true;
    updateReportDates(new Date());
    if (source !== "view") {
      addLiveActivity("Report regenerated with latest profile data");
    }
  }
  renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
  updateDashboardMetrics();
}

function showSection(sectionId) {
  const sections = ["dashboard", "jobs", "profile", "report"];
  if (!sections.includes(sectionId)) sectionId = "dashboard";
  if (sectionId === appState.currentSection) return;
  sections.forEach((id) => {
    const section = document.getElementById(id);
    // 优先使用 data-section 选择导航按钮，避免依赖 onclick 选择器。
    const navItem = document.querySelector(`button[data-section="${id}"]`);
    if (!section) return;
    if (id === sectionId) {
      section.classList.remove("hidden");
      section.classList.add("fade-in");
      if (navItem) {
        navItem.classList.add("active");
        navItem.setAttribute("aria-current", "page");
        const strip = navItem.closest(".nav-tab-strip");
        if (strip && strip.scrollWidth > strip.clientWidth) {
          strip.scrollTo({ left: navItem.offsetLeft - strip.offsetLeft - (strip.clientWidth - navItem.offsetWidth) / 2, behavior: "auto" });
        }
      }
    } else {
      section.classList.add("hidden");
      section.classList.remove("fade-in");
      if (navItem) {
        navItem.classList.remove("active");
        navItem.removeAttribute("aria-current");
      }
    }
  });
  document.querySelectorAll(".cs-hero-concierge-nav button[data-section]").forEach((btn) => {
    const sid = btn.getAttribute("data-section");
    btn.classList.toggle("is-active", Boolean(sid) && sid === sectionId);
  });
  appState.currentSection = sectionId;
  // 更新 URL hash，让 return-nav 能记录当前 section，返回时恢复正确页面
  try { window.history.replaceState({}, '', '#' + sectionId); } catch (_) {}
  if (sectionId === "report") {
    renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
    void refreshReportResumePanel();
  }
  if (sectionId === "jobs") {
    void openDatasetBrowser();
  } else {
    window.DatasetBrowser?.pause();
  }
  if (sectionId === "profile") {
    window.AssessmentCenter?.refresh();
    void refreshResumeProfile(true);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function checkReportReadiness() {
  const profile = appState.derivedProfile || deriveUnifiedProfile();
  if (profile.missingItems.length) {
    showToast("可生成初步报告", `当前仍有待补充项：${profile.missingItems.slice(0, 2).join("、")}`, "warning", 2400);
  } else {
    showToast("报告就绪", "统一画像与岗位匹配已同步完成。", "success", 1800);
  }
  showSection("report");
}

function selectTargetJob(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Target updated", `${name} added to target list.`, "success", 1800);
  addLiveActivity(`Target selected: ${name}`);
  updateDashboardMetrics();
}

function addToReport(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Synced to report", `${name} added to report targets.`, "success", 1800);
  addLiveActivity(`Synced to report: ${name}`);
  updateDashboardMetrics();
}

function showJobDetail(jobType) {
  const data = {
    ml: { title: "机器学习工程师", company: "明材科技 · 北京" },
    da: { title: "数据分析师", company: "字节跃动 · 上海" },
    pm: { title: "AI 产品经理", company: "腾讯 · 深圳" },
    fe: { title: "前端开发工程师", company: "阿里巴巴 · 杭州" }
  };
  const item = data[jobType] || data.ml;
  const title = document.getElementById("modalJobTitle");
  const company = document.getElementById("modalJobCompany");
  const modal = document.getElementById("jobDetailModal");
  if (title) title.textContent = item.title;
  if (company) company.textContent = item.company;
  if (modal) modal.classList.remove("hidden");
  addLiveActivity(`Viewed job details: ${item.title}`);
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) modal.classList.add("hidden");
}

function switchGraphType(type) {
  const verticalGraph = document.getElementById("verticalGraph");
  const horizontalGraph = document.getElementById("horizontalGraph");
  const btns = document.querySelectorAll(".graph-type-btn");
  if (!verticalGraph || !horizontalGraph || btns.length < 2) return;
  if (type === "vertical") {
    verticalGraph.style.display = "block";
    horizontalGraph.style.display = "none";
    btns[0].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.remove("bg-gray-100", "text-gray-600");
    btns[1].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.add("bg-gray-100", "text-gray-600");
  } else {
    verticalGraph.style.display = "none";
    horizontalGraph.style.display = "block";
    btns[1].classList.add("active", "bg-purple-100", "text-purple-600");
    btns[1].classList.remove("bg-gray-100", "text-gray-600");
    btns[0].classList.remove("active", "bg-purple-100", "text-purple-600");
    btns[0].classList.add("bg-gray-100", "text-gray-600");
  }
}

function recalculateProfile() {
  refreshUnifiedExperience();
  addLiveActivity("Profile synthesis refreshed from latest assessment and interview state");
  showToast("画像已重算", "测评、访谈和基础信息已经重新同步。", "success", 1800);
}

function triggerFileUpload() {
  const up = document.getElementById("resumeUpload");
  if (up) up.click();
}

function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  showToast("Parsing resume", `Processing ${file.name}...`, "info", 1200);
  setTimeout(() => {
    appState.profileCompletion = Math.min(96, appState.profileCompletion + 2);
    updateDashboardMetrics();
    addLiveActivity(`Resume parsed: ${file.name}`);
    showToast("Done", "Capability profile updated.", "success", 1600);
  }, 1200);
}

function showManualInput() { showToast("Coming soon", "Manual profile input will be enabled soon.", "info", 1700); }

function editReport() { showToast("报告说明", "当前报告由统一画像实时生成，暂不提供段落级手改。", "info", 1800); }

function saveReport() { markReportGenerated("save"); showToast("报告已保存", "当前草稿状态已刷新到本地会话。", "success", 1500); addLiveActivity("Report draft saved by user"); }

function exportReport() {
  showToast("正在导出", "系统正在准备当前报告内容。", "info", 1000);
  setTimeout(() => {
    markReportGenerated("export");
    showToast("导出完成", "报告内容已整理完成，可继续扩展 PDF 流程。", "success", 1800);
    addLiveActivity("PDF export completed");
  }, 1200);
}

function shareReport() { showToast("Share link ready", "You can now share this report.", "success", 1700); }

function scheduleConsultation() { showToast("Consultation", "Booking flow is now available.", "info", 1700); }

function showNodeDetail(nodeName) { showToast("Node details", `${nodeName} details are available.`, "info", 1700); }

// --------------------------------------------------
//  从服务器加载岗位数据
// --------------------------------------------------
async function openDatasetBrowser(options = {}) {
  try {
    await loadScriptOnce("/static/dataset-browser.js", "dataset-browser");
    if (appState.currentSection !== "jobs") return;
    await window.DatasetBrowser?.open(options);
  } catch (error) {
    const status = document.getElementById("datasetStatus");
    if (status) status.textContent = `数据浏览器加载失败，请刷新重试：${error.message}`;
  }
}
