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

function initWorkspace() {
  if (userWorkspaceState.authReadyPromise) return userWorkspaceState.authReadyPromise;
  userWorkspaceState.authReadyPromise = (async () => {
    try {
      const payload = await requestJson("/api/bootstrap");
      userWorkspaceState.currentUser = payload.user;
      const llm = payload.llm || {};
      if (typeof llm.configured === "boolean") {
        const config = { base_url: "", api_key: "", model: llm.model || "", configured: llm.configured, editable: false, api_key_masked: "" };
        userWorkspaceState.llmConfigs.career_interview = config;
        userWorkspaceState.llmConfigs.assessment_hub = config;
      }
      for (const [scope, data] of Object.entries(payload.scoped_data || {})) {
        userWorkspaceState.scopedData[scope] = scope === "resume_profile" ? data || emptyResumeProfile() : data;
        userWorkspaceState.scopedDataLoaded[scope] = true;
      }
      appState.careerReportState = payload.scoped_data?.career_report ?? null;
      appState.reportGenerated = isCareerReportReadyStatus(appState.careerReportState?.status);
      emitAuthStateChange();
      await Promise.allSettled([
        loadCareerInterviewConfig(false),
        hydrateCareerInterviewState(false),
        refreshResumeProfile(false),
        loadProfilePortraitState(false),
        window.loadAccountAvatarState?.(false)
      ]);
      return payload.user;
    } catch (error) {
      showToast("工作区加载失败", "请刷新页面重试。", "error");
      console.error(error);
      return null;
    } finally {
      requestAnimationFrame(() => window.__hidePageLoader?.());
    }
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
  if (generatedTime) generatedTime.textContent = formatDateCN(baseDate, true);
  if (headerDate) headerDate.textContent = formatDateCN(baseDate);
  if (footerGenerated) footerGenerated.textContent = formatDateCN(baseDate);
  if (footerValid) footerValid.textContent = formatDateCN(validDate);
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
  const dayIndex = Math.ceil((now.getTime() - new Date(now.getFullYear(), 0, 1).getTime()) / 86400000);
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

var showSection = function(sectionId) {
  // 岗位探索直接使用招聘信息采集工作台（/recruitment）：实时采集的岗位在本机缓存为实时岗位库。
  if (sectionId === "jobs") { window.location.href = "/recruitment"; return; }
  const sections = ["dashboard", "profile", "report"];
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
  if (sectionId === "profile") {
    window.AssessmentCenter?.refresh();
    void refreshResumeProfile(true);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
};

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
