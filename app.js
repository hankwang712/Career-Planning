const appState = {
  currentSection: "dashboard",
  selectedJobs: [],
  profileComplete: true,
  matchingComplete: true,
  reportGenerated: false,
  notifications: 3,
  baseExploredJobs: 12,
  score: 87,
  profileCompletion: 85,
  timersStarted: false,
  weights: { "基础要求": 25, "职业技能": 35, "职业素养": 20, "发展潜力": 20 }
};

// ══════════════════════════════════════════════════
//  岗位数据（从 /api/jobs 加载）
// ══════════════════════════════════════════════════
let allJobsData      = [];    // 全量
let filteredJobsData = [];    // 当前筛选结果
let jobCurrentPage   = 1;
const JOB_PAGE_SIZE  = 18;

const authConfig = {
  allowSelfRegister: false,
  usersKey: "ms_auth_users_v1",
  sessionKey: "ms_auth_session_v1",
  superUser: {
    username: "system",
    password: "123456",
    role: "super_admin",
    displayName: "System Admin"
  }
};

const jobNameMap = { ml: "Machine Learning Engineer", da: "Data Analyst", pm: "AI Product Manager", fe: "Frontend Engineer" };
const jobRateMap = { ml: 94, da: 91, pm: 87, fe: 86 };
const liveActivityTemplates = [
  "Model service latency dropped by 4%",
  "New job samples synced to recommendation engine",
  "Profile dimensions auto-calibrated",
  "Matching strategy generated fresh candidates",
  "Report module completed incremental update",
  "System detected new job trend changes"
];

function formatDateCN(date, withTime = false) {
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  const d = date.getDate();
  if (!withTime) return `${y} 年 ${m} 月 ${d} 日`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${y} 年 ${m} 月 ${d} 日 ${hh}:${mm}`;
}

function formatClock(date) {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function addMonths(date, count) {
  const d = new Date(date.getTime());
  d.setMonth(d.getMonth() + count);
  return d;
}

function showAuthMessage(message, type = "info") {
  const el = document.getElementById("authMessage");
  if (!el) return;
  el.textContent = message;
  el.className = "auth-message";
  if (type === "success" || type === "error" || type === "warning") el.classList.add(type);
}

function showToast(title, text = "", type = "info", duration = 2200) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast-item ${type}`;
  toast.innerHTML = `<p class="toast-title">${title}</p>${text ? `<p class="toast-text">${text}</p>` : ""}`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("removing");
    setTimeout(() => toast.remove(), 220);
  }, duration);
}

function addLiveActivity(message) {
  const feed = document.getElementById("liveActivityFeed");
  if (!feed) return;
  const li = document.createElement("li");
  li.className = "live-feed-item";
  li.innerHTML = `
    <span class="live-feed-dot"></span>
    <div>
      <p class="text-sm text-gray-800">${message}</p>
      <p class="text-xs text-gray-500">${formatClock(new Date())}</p>
    </div>
  `;
  feed.insertBefore(li, feed.firstChild);
  while (feed.children.length > 6) feed.removeChild(feed.lastElementChild);
}

function animateCounter(el, target, suffix = "", duration = 500) {
  if (!el) return;
  const from = Number((el.textContent || "").replace(/[^\d.-]/g, "")) || 0;
  const start = performance.now();
  function frame(now) {
    const p = Math.min(1, (now - start) / duration);
    const val = Math.round(from + (target - from) * p);
    el.textContent = `${val}${suffix}`;
    if (p < 1) {
      requestAnimationFrame(frame);
    } else {
      el.classList.remove("stat-pop");
      void el.offsetWidth;
      el.classList.add("stat-pop");
    }
  }
  requestAnimationFrame(frame);
}

function getStoredUsers() {
  try {
    const raw = localStorage.getItem(authConfig.usersKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    return [];
  }
}

function saveStoredUsers(users) { localStorage.setItem(authConfig.usersKey, JSON.stringify(users)); }

function seedSuperUser() {
  const users = getStoredUsers();
  const idx = users.findIndex((u) => u.username === authConfig.superUser.username);
  if (idx === -1) users.push({ ...authConfig.superUser });
  else users[idx] = { ...users[idx], password: authConfig.superUser.password, role: "super_admin", displayName: users[idx].displayName || authConfig.superUser.displayName };
  saveStoredUsers(users);
}

function findUser(username) { return getStoredUsers().find((u) => u.username === username) || null; }

function persistSession(user) {
  localStorage.setItem(authConfig.sessionKey, JSON.stringify({ username: user.username, role: user.role, loginAt: new Date().toISOString() }));
}

function getSession() {
  try {
    const raw = localStorage.getItem(authConfig.sessionKey);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

function clearSession() { localStorage.removeItem(authConfig.sessionKey); }

function fillSuperUser() {
  const u = document.getElementById("loginUsername");
  const p = document.getElementById("loginPassword");
  if (u) u.value = authConfig.superUser.username;
  if (p) p.value = authConfig.superUser.password;
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
  if (isLogin) showAuthMessage("Preset super user: system / 123456");
  else if (!authConfig.allowSelfRegister) showAuthMessage("Registration UI is ready, but disabled in this demo.", "warning");
  else showAuthMessage("Create a normal user account.");
}

function lockApp() {
  document.body.classList.add("auth-locked");
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  if (startup) startup.classList.remove("hidden");
  if (label) { label.textContent = "Not signed in"; label.classList.add("hidden"); }
  if (logoutBtn) logoutBtn.classList.add("hidden");
  if (avatar) avatar.textContent = "👤";
}

function unlockAppForUser(user) {
  const startup = document.getElementById("startupScreen");
  const label = document.getElementById("currentUserLabel");
  const logoutBtn = document.getElementById("logoutBtn");
  const avatar = document.getElementById("currentUserAvatar");
  document.body.classList.remove("auth-locked");
  if (startup) startup.classList.add("hidden");
  if (label) { label.textContent = `${user.displayName || user.username} (${user.role === "super_admin" ? "Super User" : "User"})`; label.classList.remove("hidden"); }
  if (logoutBtn) logoutBtn.classList.remove("hidden");
  if (avatar) avatar.textContent = user.role === "super_admin" ? "🛡️" : "👤";
  addLiveActivity(`User signed in: ${user.username}`);
  showToast("Login success", `Welcome back, ${user.displayName || user.username}.`, "success", 1800);
}

function handleLogin(event) {
  event.preventDefault();
  const username = (document.getElementById("loginUsername")?.value || "").trim();
  const password = document.getElementById("loginPassword")?.value || "";
  if (!username || !password) return showAuthMessage("Please input username and password.", "error");
  const user = findUser(username);
  if (!user || user.password !== password) return showAuthMessage("Invalid username or password.", "error");
  persistSession(user);
  showAuthMessage("Signed in, loading workspace...", "success");
  setTimeout(() => unlockAppForUser(user), 260);
}

function handleRegister(event) {
  event.preventDefault();
  if (!authConfig.allowSelfRegister) return showAuthMessage("Registration is disabled in this demo.", "warning");
  showAuthMessage("Registration will be enabled in next version.", "warning");
}

function logout() {
  clearSession();
  lockApp();
  switchAuthTab("login");
  fillSuperUser();
  showAuthMessage("Signed out. Please sign in again.", "warning");
  showToast("Signed out", "Current session ended safely.", "warning", 1700);
}

function initAuth() {
  seedSuperUser();
  const session = getSession();
  if (session?.username) {
    const user = findUser(session.username);
    if (user) return unlockAppForUser(user);
  }
  lockApp();
  switchAuthTab("login");
  fillSuperUser();
}

function setTagState(el, state) {
  if (!el) return;
  el.classList.remove("text-green-600", "text-orange-600", "text-red-600");
  if (state === "done") { el.classList.add("text-green-600"); el.textContent = "已完成"; }
  else if (state === "processing") { el.classList.add("text-orange-600"); el.textContent = "进行中"; }
  else { el.classList.add("text-red-600"); el.textContent = "待完成"; }
}

function updateNotificationCount(count = null) {
  if (typeof count === "number") appState.notifications = Math.max(0, count);
  const el = document.getElementById("notificationCount");
  if (el) el.textContent = String(appState.notifications);
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

function updateLiveClock() {
  const now = new Date();
  const clockEl = document.getElementById("liveClock");
  if (clockEl) clockEl.textContent = formatClock(now);
  const title = document.getElementById("welcomeTitle");
  const subtitle = document.getElementById("welcomeSubtitle");
  const h = now.getHours();
  let greeting = "晚上好";
  let icon = "🌙";
  if (h >= 6 && h < 12) { greeting = "早上好"; icon = "☀️"; }
  if (h >= 12 && h < 18) { greeting = "下午好"; icon = "🌤️"; }
  const dayIndex = Math.ceil((now - new Date(now.getFullYear(), 0, 1)) / 86400000);
  if (title) title.textContent = `${greeting}，张明同学！${icon}`;
  if (subtitle) subtitle.textContent = `今天是 ${formatDateCN(now)}，年度第 ${dayIndex} 天，系统正在同步你的最新进度`;
}

function updateTaskPanels(explored) {
  const exploreStatus = document.getElementById("taskJobExploreStatus");
  const exploreTag = document.getElementById("taskJobExploreTag");
  const matchingStatus = document.getElementById("taskMatchingStatus");
  const matchingTag = document.getElementById("taskMatchingTag");
  const progressHint = document.getElementById("taskProgressHint");
  const reportBtn = document.getElementById("generateReportBtn");
  const exploredDone = explored >= 10;
  if (exploreStatus) exploreStatus.textContent = `已探索 ${explored} 个岗位`;
  setTagState(exploreTag, exploredDone ? "done" : "processing");
  if (matchingStatus) matchingStatus.textContent = `已分析 ${Math.max(5, appState.selectedJobs.length + 4)} 个目标岗位`;
  setTagState(matchingTag, appState.matchingComplete ? "done" : "processing");
  const doneCount = [appState.profileComplete, exploredDone, appState.matchingComplete, appState.reportGenerated].filter(Boolean).length;
  if (progressHint) progressHint.textContent = `已完成 ${doneCount}/4 个关键任务`;
  if (reportBtn) {
    if (appState.reportGenerated) {
      reportBtn.textContent = "报告已更新";
      reportBtn.classList.add("bg-green-600", "hover:bg-green-700");
      reportBtn.classList.remove("bg-purple-600", "hover:bg-purple-700");
    } else {
      reportBtn.textContent = "立即生成";
      reportBtn.classList.add("bg-purple-600", "hover:bg-purple-700");
      reportBtn.classList.remove("bg-green-600", "hover:bg-green-700");
    }
  }
}

function updateDashboardMetrics() {
  const explored = appState.baseExploredJobs + appState.selectedJobs.length;
  const code = appState.selectedJobs[appState.selectedJobs.length - 1] || "ml";
  const topRate = jobRateMap[code] || 94;
  const topJob = jobNameMap[code] || "Machine Learning Engineer";
  const pending = [!appState.profileComplete, explored < 10, !appState.matchingComplete, !appState.reportGenerated].filter(Boolean).length;
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
  if (scoreTrend) scoreTrend.textContent = `较基线 ${appState.score - 82 >= 0 ? "+" : ""}${appState.score - 82}%`;
  if (profileHint) profileHint.textContent = appState.profileCompletion >= 90 ? "评估表现优秀" : `剩余 ${Math.max(0, Math.ceil((100 - appState.profileCompletion) / 5))} 项`;
  if (pendingHint) pendingHint.textContent = pending === 0 ? "全部完成" : "点击查看";
  updateTaskPanels(explored);
}

function markReportGenerated() {
  if (!appState.reportGenerated) {
    appState.reportGenerated = true;
    updateReportDates(new Date());
    addLiveActivity("Report regenerated with latest data");
    showToast("Report updated", "Latest jobs and profile data were merged.", "success", 2000);
  }
  updateDashboardMetrics();
}

function showSection(sectionId) {
  const sections = ["dashboard", "jobs", "profile", "matching", "report", "qa"];
  sections.forEach((id) => {
    const section = document.getElementById(id);
    // 优先用 data-section 属性选择导航按钮，避免 onclick 属性选择器在部分浏览器失效
    const navItem = document.querySelector(`button[data-section="${id}"]`);
    if (!section) return;
    if (id === sectionId) {
      section.classList.remove("hidden");
      section.classList.add("fade-in");
      if (navItem) navItem.classList.add("active");
    } else {
      section.classList.add("hidden");
      section.classList.remove("fade-in");
      if (navItem) navItem.classList.remove("active");
    }
  });
  appState.currentSection = sectionId;
  if (sectionId === "report") markReportGenerated();
  if (sectionId === "jobs" && allJobsData.length === 0) loadJobs();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function checkReportReadiness() {
  const explored = appState.baseExploredJobs + appState.selectedJobs.length;
  if (appState.profileComplete && explored >= 10 && appState.matchingComplete) {
    showToast("Ready", "All conditions are satisfied for report generation.", "success", 1800);
    addLiveActivity("Report readiness check passed");
    showSection("report");
  } else {
    showToast("Not ready", "Please finish remaining tasks first.", "warning", 2200);
  }
}

function selectTargetJob(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Target updated", `${name} added to target list.`, "success", 1800);
  addLiveActivity(`Target selected: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function addToReport(jobType) {
  const isNew = !appState.selectedJobs.includes(jobType);
  if (isNew) appState.selectedJobs.push(jobType);
  const name = jobNameMap[jobType] || jobType;
  showToast("Synced to report", `${name} added to report targets.`, "success", 1800);
  addLiveActivity(`Synced to report: ${name}`);
  if (isNew) appState.notifications += 1;
  updateNotificationCount();
  updateDashboardMetrics();
}

function showJobDetail(jobType) {
  const data = {
    ml: { title: "机器学习工程师", company: "明杉科技 · 北京" },
    da: { title: "数据分析师", company: "字节跳动 · 上海" },
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

function updateWeight(slider, dimension) {
  const value = Number(slider.value);
  appState.weights[dimension] = value;
  const card = slider.closest(".text-center");
  if (card) {
    const circles = card.querySelectorAll("svg circle");
    const text = card.querySelector("svg text");
    if (text) text.textContent = `${value}%`;
    if (circles.length > 1) {
      const c = 251.2;
      circles[1].setAttribute("stroke-dasharray", String(c));
      circles[1].setAttribute("stroke-dashoffset", String((1 - value / 100) * c));
    }
  }
  const sliders = Array.from(document.querySelectorAll("input[type='range'][onchange*='updateWeight']"));
  const total = sliders.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const totalEl = document.getElementById("weightTotal");
  if (totalEl) {
    totalEl.textContent = `${total}%`;
    totalEl.classList.toggle("text-orange-600", total !== 100);
    totalEl.classList.toggle("text-purple-600", total === 100);
  }
}

function recalculateMatching() {
  const total = Object.values(appState.weights).reduce((sum, n) => sum + n, 0);
  if (total !== 100) return showToast("Invalid weight total", "Weight sum must equal 100%.", "warning", 2200);
  showToast("Recalculating", "Applying latest weight strategy...", "info", 1000);
  setTimeout(() => {
    appState.score = Math.min(99, Math.max(70, appState.score + Math.round(Math.random() * 4 - 1)));
    updateDashboardMetrics();
    addLiveActivity("Matching engine recalculated by new weights");
    showToast("Done", "Matching ranking has been updated.", "success", 1800);
  }, 850);
}

function recalculateProfile() {
  showToast("Re-evaluating", "Refreshing capability profile...", "info", 1000);
  setTimeout(() => {
    appState.profileCompletion = Math.min(98, Math.max(70, appState.profileCompletion + Math.round(Math.random() * 5 - 2)));
    appState.score = Math.min(99, Math.max(72, appState.score + Math.round(Math.random() * 3 - 1)));
    updateDashboardMetrics();
    addLiveActivity("Capability profile updated");
    showToast("Updated", "Profile changes synced to matching module.", "success", 1800);
  }, 820);
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
function editReport() { showToast("Edit mode", "Report editing is enabled.", "success", 1500); }
function saveReport() { showToast("Saved", "Report draft saved in this session.", "success", 1500); addLiveActivity("Report draft saved by user"); }

function exportReport() {
  showToast("Exporting", "Generating PDF report...", "info", 1000);
  setTimeout(() => {
    markReportGenerated();
    showToast("Export complete", "PDF report generated.", "success", 1800);
    addLiveActivity("PDF export completed");
  }, 1200);
}

function shareReport() { showToast("Share link ready", "You can now share this report.", "success", 1700); }
function scheduleConsultation() { showToast("Consultation", "Booking flow is now available.", "info", 1700); }
function showNodeDetail(nodeName) { showToast("Node details", `${nodeName} details are available.`, "info", 1700); }

// ──────────────────────────────────────────────────
//  从服务器加载岗位数据
// ──────────────────────────────────────────────────
async function loadJobs() {
  const loading = document.getElementById("jobsLoading");
  const grid    = document.getElementById("jobGrid");
  const pager   = document.getElementById("jobPagination");
  if (loading) loading.classList.remove("hidden");
  if (grid)    grid.classList.add("hidden");
  if (pager)   pager.classList.add("hidden");

  try {
    // 1. 拉取可用城市，填充下拉
    const citiesResp = await fetch("/api/cities");
    if (citiesResp.ok) {
      const cities = await citiesResp.json();
      const sel = document.getElementById("cityFilter");
      if (sel) {
        sel.innerHTML = '<option value="all">全部城市</option>';
        cities.forEach(c => {
          const o = document.createElement("option");
          o.value = c; o.textContent = c;
          sel.appendChild(o);
        });
      }
    }

    // 2. 拉取全部岗位
    const jobsResp = await fetch("/api/jobs?city=all");
    if (!jobsResp.ok) throw new Error("服务器返回异常");
    allJobsData = await jobsResp.json();
    filteredJobsData = [...allJobsData];

    if (loading) loading.classList.add("hidden");
    filterJobs(true);

    const summary = document.getElementById("jobFilterSummary");
    if (summary) summary.textContent = `已加载 ${allJobsData.length} 个真实岗位`;

  } catch (err) {
    if (loading) {
      loading.innerHTML = `<p class="text-red-500">⚠ 无法连接数据服务（请确认已运行 server.py）<br><span class="text-xs text-gray-400">${err.message}</span></p>`;
    }
  }
}

// ──────────────────────────────────────────────────
//  筛选（数据驱动）
// ──────────────────────────────────────────────────
function filterJobs(silent = false) {
  if (allJobsData.length === 0) return;   // 数据还没加载，跳过

  const query    = (document.getElementById("jobSearch")?.value || "").trim().toLowerCase();
  const cityVal  = document.getElementById("cityFilter")?.value  || "all";

  filteredJobsData = allJobsData.filter(job => {
    const okCity  = cityVal === "all" || (job["采集城市"] || job["城市"] || "") === cityVal;
    const haystack = [
      job["岗位名称"], job["公司名称"], job["技能要求"],
      job["职位类别"], job["公司行业"]
    ].join(" ").toLowerCase();
    const okQuery = !query || haystack.includes(query);
    return okCity && okQuery;
  });

  jobCurrentPage = 1;
  renderJobCards();

  const summary = document.getElementById("jobFilterSummary");
  if (summary) summary.textContent = `当前显示 ${filteredJobsData.length} / ${allJobsData.length} 个岗位`;

  if (!silent) {
    addLiveActivity(`岗位筛选完成：共 ${filteredJobsData.length} 个结果`);
  }
}

// ──────────────────────────────────────────────────
//  渲染当前页卡片
// ──────────────────────────────────────────────────
function renderJobCards() {
  const grid  = document.getElementById("jobGrid");
  const pager = document.getElementById("jobPagination");
  if (!grid) return;

  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  const start      = (jobCurrentPage - 1) * JOB_PAGE_SIZE;
  const pageData   = filteredJobsData.slice(start, start + JOB_PAGE_SIZE);

  if (total === 0) {
    grid.innerHTML = `<div class="col-span-3 py-16 text-center text-gray-400">
      <p class="text-4xl mb-3">🔍</p>
      <p class="text-lg font-medium text-gray-500">没有找到匹配的岗位</p>
      <p class="text-sm mt-1">试试调整搜索关键词或城市筛选</p>
    </div>`;
    grid.classList.remove("hidden");
    pager.classList.add("hidden");
    return;
  }

  grid.innerHTML = pageData.map((job, i) => {
    const idx     = start + i;
    const skills  = (job["技能要求"] || "").split(",").map(s => s.trim()).filter(Boolean);
    const skillTags = skills.slice(0, 5).map(s =>
      `<span class="px-2 py-0.5 bg-purple-50 text-purple-700 text-xs rounded border border-purple-100 whitespace-nowrap">${escHtml(s)}</span>`
    ).join("") + (skills.length > 5 ? `<span class="px-2 py-0.5 bg-gray-50 text-gray-400 text-xs rounded">+${skills.length - 5}</span>` : "");

    const fundingColors = { "已上市":"bg-blue-100 text-blue-700", "D轮及以上":"bg-indigo-100 text-indigo-700",
      "C轮":"bg-violet-100 text-violet-700", "B轮":"bg-purple-100 text-purple-700",
      "A轮":"bg-fuchsia-100 text-fuchsia-700", "天使轮":"bg-pink-100 text-pink-700" };
    const fundingCls = fundingColors[job["融资阶段"]] || "bg-gray-100 text-gray-500";

    return `
    <div class="job-card-real bg-white rounded-xl glass-surface p-5 shadow-sm cursor-pointer
                border-2 border-transparent hover:border-purple-300 hover:shadow-lg transition-all duration-200"
         onclick="openJobModal(${idx})">
      <!-- 标题 + 薪资 -->
      <div class="flex justify-between items-start mb-2 gap-2">
        <h3 class="text-base font-bold text-gray-800 leading-tight line-clamp-2 flex-1">${escHtml(job["岗位名称"] || "—")}</h3>
        <span class="text-sm font-bold text-emerald-600 flex-shrink-0 mt-0.5">${escHtml(job["薪资"] || "面议")}</span>
      </div>
      <!-- 公司 -->
      <p class="text-sm text-gray-500 mb-3 truncate">${escHtml(job["公司名称"] || "")}</p>
      <!-- 城市 / 经验 / 学历 -->
      <div class="flex flex-wrap gap-1.5 mb-3">
        <span class="px-2 py-0.5 bg-blue-50 text-blue-600 text-xs rounded-full whitespace-nowrap">📍 ${escHtml(job["城市"] || job["采集城市"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">${escHtml(job["经验要求"] || "")}</span>
        <span class="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full whitespace-nowrap">🎓 ${escHtml(job["学历要求"] || "")}</span>
      </div>
      <!-- 技能标签 -->
      <div class="flex flex-wrap gap-1 mb-4">${skillTags}</div>
      <!-- 底部：公司信息 -->
      <div class="flex justify-between items-center pt-3 border-t border-gray-100 text-xs text-gray-400">
        <span class="truncate">${escHtml(job["公司规模"] || "")} · ${escHtml(job["公司行业"] || "")}</span>
        <span class="px-2 py-0.5 rounded-full flex-shrink-0 ml-2 ${fundingCls}">${escHtml(job["融资阶段"] || "")}</span>
      </div>
    </div>`;
  }).join("");

  grid.classList.remove("hidden");

  // 分页
  const prevBtn  = document.getElementById("jobPrevBtn");
  const nextBtn  = document.getElementById("jobNextBtn");
  const pageInfo = document.getElementById("jobPageInfo");
  if (pager) {
    pager.classList.remove("hidden");
    if (prevBtn)  prevBtn.disabled  = jobCurrentPage <= 1;
    if (nextBtn)  nextBtn.disabled  = jobCurrentPage >= totalPages;
    if (pageInfo) pageInfo.textContent = `第 ${jobCurrentPage} / ${totalPages} 页  ·  共 ${total} 个岗位`;
  }
}

function jobChangePage(delta) {
  const total      = filteredJobsData.length;
  const totalPages = Math.ceil(total / JOB_PAGE_SIZE);
  jobCurrentPage   = Math.max(1, Math.min(totalPages, jobCurrentPage + delta));
  renderJobCards();
  document.getElementById("jobs")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

// ──────────────────────────────────────────────────
//  弹窗：打开 / 关闭
// ──────────────────────────────────────────────────
// 福利关键词 → emoji 映射
const welfareIcons = {
  "年终奖":"🎁","五险一金":"🛡","弹性工作":"⏰","远程办公":"🏠","股票期权":"📈",
  "带薪年假":"🌴","团队旅游":"✈","员工旅游":"✈","餐补":"🍱","包餐":"🍜",
  "零食下午茶":"🧋","定期体检":"🏥","补充医疗保险":"💊","节日福利":"🎉",
  "通讯补贴":"📱","通讯补贴":"📱","交通补贴":"🚇","包住":"🏠","提供住宿":"🏠",
  "绩效奖金":"💰","周末双休":"📅","大小周":"📅",
};

function openJobModal(idx) {
  const job = filteredJobsData[idx];
  if (!job) return;

  const companyName = job["公司名称"] || "—";
  const jobTitle    = job["岗位名称"] || "—";

  // 公司头像（首字）
  const avatar = document.getElementById("jobModalAvatar");
  if (avatar) {
    const firstChar = companyName.charAt(0) || "?";
    avatar.textContent = firstChar;
    // 根据首字 charCode 生成一个柔和色调
    const hue = (firstChar.charCodeAt(0) * 37) % 360;
    avatar.style.background = `hsla(${hue},55%,55%,0.35)`;
  }

  document.getElementById("jobModalTitle").textContent   = jobTitle;
  document.getElementById("jobModalCompany").textContent = companyName;
  document.getElementById("jobModalSalary").textContent  = job["薪资"] || "面议";

  // meta 药丸
  const meta = document.getElementById("jobModalMeta");
  const metaItems = [
    ["📍", job["城市"] || job["采集城市"]],
    ["⏱",  job["经验要求"]],
    ["🎓",  job["学历要求"]],
    ["🏭",  job["公司行业"]],
  ].filter(([, v]) => v);
  meta.innerHTML = metaItems.map(([icon, text]) =>
    `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs text-white/80 whitespace-nowrap"
           style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.2)">
       ${icon} ${escHtml(text)}
     </span>`
  ).join("");

  // 技能标签
  const skills = (job["技能要求"] || "").split(",").map(s => s.trim()).filter(Boolean);
  document.getElementById("jobModalSkills").innerHTML = skills.length
    ? skills.map(s =>
        `<span class="px-3 py-1 text-xs rounded-full font-medium"
               style="background:#f0ebff;color:#6d28d9;border:1px solid #ddd6fe">${escHtml(s)}</span>`
      ).join("")
    : `<span class="text-gray-400 text-sm">暂无标签</span>`;

  // 岗位描述
  document.getElementById("jobModalDesc").textContent = job["岗位描述"] || "暂无描述";

  // 公司信息三格
  const compInfo = document.getElementById("jobModalCompanyInfo");
  const compFields = [
    { icon:"💰", label:"融资阶段", val: job["融资阶段"] },
    { icon:"👥", label:"公司规模", val: job["公司规模"] },
    { icon:"🏢", label:"所属行业", val: job["公司行业"] },
  ];
  compInfo.innerHTML = compFields.map(({ icon, label, val }) => `
    <div class="rounded-xl p-3 text-center" style="background:#f8f5ff;border:1px solid #ede9fe">
      <p class="text-lg mb-0.5">${icon}</p>
      <p class="text-xs font-semibold text-violet-700 leading-tight">${escHtml(val || "—")}</p>
      <p class="text-xs text-gray-400 mt-0.5">${label}</p>
    </div>`).join("");
  document.getElementById("jobModalCompanyDesc").textContent = job["公司简介"] || "";

  // 工作地址
  const addr = document.getElementById("jobModalAddr");
  if (addr) addr.textContent = job["工作地址"] || "暂无地址信息";

  // 公司福利
  const welfares = (job["公司福利"] || "").split(",").map(s => s.trim()).filter(Boolean);
  document.getElementById("jobModalWelfare").innerHTML = welfares.length
    ? welfares.map(w => {
        const icon = welfareIcons[w] || "✦";
        return `<span class="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full font-medium"
                      style="background:#f0fdf4;color:#15803d;border:1px solid #bbf7d0">
                  ${icon} ${escHtml(w)}
                </span>`;
      }).join("")
    : `<span class="text-gray-400 text-xs">暂无福利信息</span>`;

  // 显示弹窗
  const modal = document.getElementById("jobModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  document.body.style.overflow = "hidden";
}

function closeJobModal() {
  const modal = document.getElementById("jobModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  document.body.style.overflow = "";
}

function initCharts() {
  const radarCanvas = document.getElementById("radarChart");
  const profileRadarCanvas = document.getElementById("profileRadarChart");
  if (radarCanvas && window.Chart) {
    new Chart(radarCanvas.getContext("2d"), {
      type: "radar",
      data: {
        labels: ["专业技能", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历"],
        datasets: [
          { label: "当前能力", data: [75, 82, 88, 70, 65, 60], backgroundColor: "rgba(102,126,234,0.2)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)" },
          { label: "岗位要求", data: [85, 75, 80, 75, 70, 75], backgroundColor: "rgba(118,75,162,0.2)", borderColor: "rgba(118,75,162,1)", borderWidth: 2, pointBackgroundColor: "rgba(118,75,162,1)" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 12 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { position: "top", labels: { usePointStyle: true } } } }
    });
  }
  if (profileRadarCanvas && window.Chart) {
    new Chart(profileRadarCanvas.getContext("2d"), {
      type: "radar",
      data: { labels: ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"], datasets: [{ label: "能力评分", data: [75, 60, 82, 88, 70, 65, 60, 55], backgroundColor: "rgba(102,126,234,0.3)", borderColor: "rgba(102,126,234,1)", borderWidth: 2, pointBackgroundColor: "rgba(102,126,234,1)", pointRadius: 4 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { r: { angleLines: { color: "rgba(0,0,0,0.1)" }, grid: { color: "rgba(0,0,0,0.1)" }, pointLabels: { font: { size: 11 }, color: "#666" }, ticks: { backdropColor: "transparent", max: 100, stepSize: 20 } } }, plugins: { legend: { display: false } } }
    });
  }
}

function initAnimations() {
  const bars = document.querySelectorAll(".progress-bar");
  bars.forEach((bar) => {
    const w = bar.style.width;
    bar.style.width = "0";
    setTimeout(() => { bar.style.width = w; }, 400);
  });
  const modal = document.getElementById("jobDetailModal");
  if (modal) modal.addEventListener("click", function (e) { if (e.target === this) closeModal("jobDetailModal"); });
  if (typeof IntersectionObserver !== "undefined") {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("slide-in");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".glass-surface, .product-hero-card, .product-gallery-card").forEach((el) => observer.observe(el));
  }
}

function bindGlobalEvents() {
  const notificationBtn = document.getElementById("notificationBtn");
  if (notificationBtn) {
    notificationBtn.addEventListener("click", () => {
      const unread = appState.notifications;
      if (unread > 0) {
        showToast("Notifications", `You have ${unread} new update(s).`, "info", 1600);
        addLiveActivity(`Notification center opened (${unread})`);
      } else {
        showToast("Notifications", "No new updates.", "info", 1400);
      }
      appState.notifications = Math.max(0, unread - 1);
      updateNotificationCount();
    });
  }

  const searchInput = document.getElementById("jobSearch");
  if (searchInput) {
    // 实时输入触发筛选
    searchInput.addEventListener("input", () => filterJobs());
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        filterJobs();
      }
    });
  }

  const industryFilter = document.getElementById("industryFilter");
  const cityFilter = document.getElementById("cityFilter");
  if (industryFilter) {
    industryFilter.addEventListener("change", () => filterJobs());
  }
  if (cityFilter) {
    cityFilter.addEventListener("change", () => filterJobs());
  }
}

function startRealtimeEngine() {
  if (appState.timersStarted) return;
  appState.timersStarted = true;
  updateLiveClock();
  setInterval(updateLiveClock, 1000);
  setInterval(() => {
    appState.score = Math.min(99, Math.max(75, appState.score + Math.round(Math.random() * 2 - 1)));
    updateDashboardMetrics();
  }, 12000);
  setInterval(() => {
    const msg = liveActivityTemplates[Math.floor(Math.random() * liveActivityTemplates.length)];
    addLiveActivity(msg);
    appState.notifications = Math.min(9, appState.notifications + 1);
    updateNotificationCount();
  }, 14000);
}

document.addEventListener("DOMContentLoaded", function () {
  initAuth();
  initCharts();
  initAnimations();
  bindGlobalEvents();
  startRealtimeEngine();
  updateReportDates(new Date());
  updateNotificationCount();
  updateDashboardMetrics();
  // 实时搜索：typing 自动筛选
  const jobSearchEl = document.getElementById("jobSearch");
  if (jobSearchEl) {
    jobSearchEl.addEventListener("input", () => filterJobs(true));
  }
  const cityFilterEl = document.getElementById("cityFilter");
  if (cityFilterEl) {
    cityFilterEl.addEventListener("change", () => filterJobs(true));
  }
  addLiveActivity("System initialized. Dynamic monitoring is active.");
});

// 职业问答模块
function fillQAQuestion(question) {
  const input = document.getElementById("qaInput");
  if (input) {
    input.value = question;
    input.focus();
  }
}

function submitQAQuestion() {
  const input = document.getElementById("qaInput");
  if (!input || !input.value.trim()) {
    showToast("提示", "请先输入你的职业问题", "warning", 2000);
    return;
  }
  showToast(
    "职业问答",
    "RAG 引擎对接中，当前请参考下方预置问答示例。问题已记录：" + input.value.substring(0, 20) + "...",
    "info",
    3000
  );
}

function expandQA(el) {
  const content = el.querySelector(".hidden, .block");
  const arrow = el.querySelector("span:last-child");
  if (!content) return;
  if (content.classList.contains("hidden")) {
    content.classList.remove("hidden");
    content.classList.add("block");
    if (arrow) arrow.textContent = "▴";
  } else {
    content.classList.add("hidden");
    content.classList.remove("block");
    if (arrow) arrow.textContent = "▾";
  }
}
