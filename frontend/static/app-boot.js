// 加载时执行的语句：对外暴露的 window 函数、事件监听与对 showSection 的包装（必须最后加载）
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

const careerInterviewState = {
  started: false,
  loading: false,
  isComplete: false,
  messages: [],
  result: null,
  completionScore: 0,
  readinessScore: 0,
  focusDimension: "职业兴趣",
  profileBasics: getDefaultProfileBasics(),
  helperAnchor: ""
};

careerInterviewState.dimensionProgress = [];

window.getCurrentUser = getCurrentUser;

window.isAuthenticatedUser = isAuthenticatedUser;

window.isSuperAdminUser = isSuperAdminUser;

window.fetchScopedUserState = fetchScopedUserState;

window.saveScopedUserState = saveScopedUserState;

window.mergeScopedUserState = mergeScopedUserState;

window.fetchManagedLlmConfig = fetchManagedLlmConfig;

window.fetchActiveLlmRuntimeConfig = fetchActiveLlmRuntimeConfig;

window.appState = appState;

window.userWorkspaceState = userWorkspaceState;

window.resolveApiUrl = resolveApiUrl;

window.requestJson = requestJson;

window.requestFormData = requestFormData;

window.setResumeStackDeck = setResumeStackDeck;

window.shiftResumeStackDeck = shiftResumeStackDeck;

window.advanceResumeStackDeck = advanceResumeStackDeck;

window.handleResumeStackDeckKey = handleResumeStackDeckKey;

window.openResumeReportModal = openResumeReportModal;

window.closeResumeReportModal = closeResumeReportModal;

window.handleResumeReportOverlayClick = handleResumeReportOverlayClick;

window.jumpResumeReportSection = jumpResumeReportSection;

window.getCareerReportStateSafe = getCareerReportStateSafe;

window.startCareerReportGeneration = startCareerReportGeneration;

window.cancelCareerReportGeneration = cancelCareerReportGeneration;

window.pollCareerReportJob = pollCareerReportJob;

window.resumeCareerReportRuntime = resumeCareerReportRuntime;

window.clearCareerInterviewHelperAnchor = function clearCareerInterviewHelperAnchor() {
  careerInterviewState.helperAnchor = "";
  renderCareerInterviewAssistSurface();
};

window.toggleCareerInterviewVoice = function toggleCareerInterviewVoice() {
  if (!careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading) return;
  const recognition = ensureCareerInterviewVoiceRecognition();
  if (!recognition) {
    showToast("当前浏览器不支持语音", "请继续使用文本输入。", "warning", 1800);
    return;
  }
  if (careerInterviewVoiceState.listening) {
    recognition.stop();
    return;
  }
  try {
    recognition.start();
  } catch (_) {
    showToast("语音输入暂不可用", "请稍后再试或直接输入文字。", "warning", 1800);
  }
};

/** 读取最新统一画像，包含简历解析结果。 */
window.getLatestUnifiedProfile = function getLatestUnifiedProfile() {
  return deriveUnifiedProfile();
};

window.buildReportRoleRankingsForPayload = buildReportRoleRankingsForPayload;

window.continueCareerReportWorkflow = continueCareerReportWorkflow;

document.addEventListener("DOMContentLoaded", function () {
  const authReady = initWorkspace();
  initCharts();
  initAnimations();
  bindGlobalEvents();
  initCareerNewsBoard();
  startRealtimeEngine();
  updateReportDates(new Date());
  syncProfileBasicsForm();
  refreshUnifiedExperience();
  addLiveActivity("System initialized. Dynamic monitoring is active.");
  window.addEventListener("assessment-hub:updated", () => {
    refreshUnifiedExperience();
  });
  Promise.resolve(authReady).finally(() => {
    updateCareerInterviewConfigStatus();
    void updateProfileFlowModelStatus(true);
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    const restoredUnifiedExperience = restoreUnifiedExperienceFromSavedScopes();
    if (!restoredUnifiedExperience) {
      refreshUnifiedExperience();
    }
    void resumeCareerReportRuntime();
    // 从 URL hash 恢复上次所在 section（支持 return-nav 返回到正确页面）
    try {
      const VALID_SECTIONS = ["dashboard", "jobs", "profile", "report"];
      const hashId = (window.location.hash || "").replace(/^#/, "").trim().toLowerCase();
      if (hashId && VALID_SECTIONS.includes(hashId) && hashId !== (appState.currentSection || "dashboard")) {
        showSection(hashId);
      }
    } catch (_) {}
  });

  // 双保险绑定，避免仅依赖内联 onclick 在部分环境失效。
  const startBtn = document.getElementById("careerInterviewStartBtn");
  if (startBtn && !startBtn.dataset.boundClick) {
    startBtn.addEventListener("click", () => { void startCareerInterview(); });
    startBtn.dataset.boundClick = "1";
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const careerIv = document.getElementById("careerInterviewModal");
    if (careerIv && !careerIv.classList.contains("hidden")) {
      closeCareerInterviewModal();
      return;
    }
    const resumeReportModal = document.getElementById("resumeReportModal");
    if (resumeReportModal && !resumeReportModal.classList.contains("hidden")) {
      closeResumeReportModal();
    }
  });
});

if (typeof window !== "undefined") {
  window.__resumeDeepAuditRenderer = {
    renderHtml(state) {
      resumeTaskState.reportTabSerial = 0;
      return resumeDetailedReportHtml(state);
    }
  };
}

const _originalShowSection = showSection;

showSection = function(sectionId) {
  _originalShowSection(sectionId);
  if (sectionId === "dashboard") {
    requestAnimationFrame(initCareerNewsGsapAnimations);
  }
};
