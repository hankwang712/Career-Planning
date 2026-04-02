(function () {
  const stageMeta = {
    dashboard: "Dashboard",
    jobs: "Job Explorer",
    profile: "Profile Input",
    matching: "Role Matching",
    report: "Career Report",
    qa: "Decision Q&A"
  };

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(value ?? "");
  }

  function setHtml(id, value) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = String(value ?? "");
  }

  function escapeHtml(value) {
    if (typeof window.escHtml === "function") return window.escHtml(value);
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;");
  }

  function resolveFocusRole() {
    const selected = Array.isArray(window.appState?.selectedJobs) ? window.appState.selectedJobs : [];
    const focused = String(window.appState?.focusedRoleId || "").trim();
    const roleId = focused || selected[0] || "";
    const roleName = roleId && window.jobNameMap ? window.jobNameMap[roleId] : "";
    return roleName || roleId || "Unresolved";
  }

  function getBrief() {
    if (typeof window.buildWorkspaceBrief === "function") {
      try {
        const brief = window.buildWorkspaceBrief();
        if (brief && typeof brief === "object") return brief;
      } catch (_) {
        // fall through to default brief
      }
    }

    const focusRole = resolveFocusRole();
    const completionRate = Math.max(0, Math.min(100, Math.round(Number(window.appState?.profileCompletion || 0))));
    const reportReady = Boolean(window.appState?.reportReady);

    return {
      focusRole,
      completionRate,
      statusLabel: reportReady ? "Generated" : "Pending",
      summary: focusRole === "Unresolved"
        ? "Start from Job Explorer to lock one main role."
        : `Keep building evidence for ${focusRole}.`,
      action: {
        label: focusRole === "Unresolved" ? "Explore Jobs" : "Continue Mainline",
        description: focusRole === "Unresolved"
          ? "Use Job Explorer to pick one role first."
          : `Push the ${focusRole} track with focused actions.`
      },
      tracker: {
        next_focus: focusRole === "Unresolved" ? "Select one target role" : `Advance ${focusRole}`
      },
      profile: {
        missingItems: []
      },
      signalChips: focusRole === "Unresolved"
        ? ["Need target role", "Profile evidence pending"]
        : [focusRole, "Mainline active"],
      taskItems: [
        {
          title: "Do one concrete next action",
          copy: "Move one step forward today and keep momentum."
        }
      ],
      reportData: {
        meta: {
          title: `${focusRole} Snapshot`
        }
      }
    };
  }

  function updateWorkspaceJourneyVisibility(options = {}) {
    const journeyBand = document.getElementById("workspaceJourneyBand");
    const guideActionBtn = document.getElementById("workspaceGuideActionBtn");

    const isAuthenticated = typeof window.isAuthenticatedUser === "function"
      ? window.isAuthenticatedUser()
      : Boolean(typeof window.getCurrentUser === "function" ? window.getCurrentUser() : null);
    const hasSeenGuide = typeof window.hasSeenWorkspaceGuide === "function"
      ? window.hasSeenWorkspaceGuide()
      : false;

    const guideOpen = document.body.classList.contains("workspace-guide-open");
    const guideIntroPhase = document.body.classList.contains("workspace-guide-phase-intro");
    const forceShowJourney = Boolean(options.forceShowJourney);

    let shouldShowJourney = false;
    if (isAuthenticated) {
      if (guideOpen) {
        shouldShowJourney = guideIntroPhase;
      } else {
        shouldShowJourney = forceShowJourney || !hasSeenGuide;
      }
    }

    if (journeyBand) {
      journeyBand.classList.toggle("hidden", !shouldShowJourney);
    }

    if (guideActionBtn) {
      guideActionBtn.classList.toggle("hidden", !(isAuthenticated && hasSeenGuide));
    }
  }

  function updateSectionHints(brief) {
    if (!brief) return;
    const focusRole = brief.focusRole || "Unresolved";
    const nextFocus = brief.tracker?.next_focus || brief.action?.description || "Explore jobs first";

    setText(
      "profileSectionHint",
      focusRole === "Unresolved"
        ? "Finish key profile inputs to improve recommendations."
        : `Add stronger evidence for ${focusRole}.`
    );
    setText(
      "jobsSectionHint",
      focusRole === "Unresolved"
        ? "Compare role direction, city and threshold to lock one mainline."
        : `Verify market requirements for ${focusRole}.`
    );
    setText(
      "matchingSectionHint",
      focusRole === "Unresolved"
        ? "Pick one candidate role first, then inspect gaps."
        : `Current mainline: ${focusRole}. Next: ${nextFocus}.`
    );
    setText(
      "reportSectionHint",
      brief.statusLabel === "Generated"
        ? `Report ready. Prioritize: ${nextFocus}.`
        : "Generate the first report after role and profile are stable."
    );
    setText(
      "qaSectionHint",
      focusRole === "Unresolved"
        ? "Use Q&A to narrow choices, but keep one final mainline."
        : `Ask role-specific questions for ${focusRole}.`
    );
  }

  function renderWorkspaceJourney(brief = null) {
    const safeBrief = brief || getBrief();
    if (!safeBrief) return;

    const matchingRoles = Array.isArray(window.appState?.matchingRoles) ? window.appState.matchingRoles : [];
    const reportReady = Boolean(window.appState?.reportReady);
    const currentSection = window.appState?.currentSection || "dashboard";

    const statusMap = {
      dashboard: { done: safeBrief.completionRate > 0, status: currentSection === "dashboard" ? "Current" : "Ready" },
      jobs: { done: matchingRoles.length > 0, status: matchingRoles.length > 0 ? "Visited" : "Start" },
      profile: { done: safeBrief.completionRate >= 60, status: `${safeBrief.completionRate}%` },
      matching: { done: matchingRoles.length > 0, status: matchingRoles.length > 0 ? "Has roles" : "Pending" },
      report: { done: reportReady, status: reportReady ? "Generated" : "Pending" },
      qa: { done: false, status: currentSection === "qa" ? "Current" : "Assist" }
    };

    document.querySelectorAll("[data-journey-section]").forEach((button) => {
      const section = button.getAttribute("data-journey-section");
      const meta = statusMap[section] || { done: false, status: "Pending" };
      button.classList.toggle("is-active", section === currentSection);
      button.classList.toggle("is-done", Boolean(meta.done));
      button.classList.toggle("is-support", section === "qa");
      const statusEl = button.querySelector(".workspace-journey-step-status");
      if (statusEl) statusEl.textContent = section === currentSection ? "Current" : meta.status;
      if (section === currentSection) {
        button.setAttribute("aria-current", "step");
      } else {
        button.removeAttribute("aria-current");
      }
    });

    setText("workspaceJourneyCurrentStage", stageMeta[currentSection] || "Dashboard");
    setText("workspaceJourneyCurrentAction", safeBrief.action?.label || "Continue");
    setText("workspaceJourneyNarrative", safeBrief.summary || "Keep moving one focused step at a time.");

    updateWorkspaceJourneyVisibility();
  }

  function renderDashboardWorkspace() {
    const brief = getBrief();
    if (!brief) return;

    const focusRole = brief.focusRole || "Unresolved";

    setText(
      "dashboardFocusTitle",
      focusRole === "Unresolved"
        ? "Lock one role direction first"
        : `Push your ${focusRole} mainline`
    );
    setText("dashboardFocusSummary", brief.summary || "");
    setText("dashboardLaunchpadRole", focusRole);
    setText("dashboardLaunchpadNext", brief.tracker?.next_focus || brief.action?.description || "Continue");
    setText("dashboardLaunchpadSync", brief.statusLabel || "Pending");
    setText("dashboardReportCardTitle", brief.reportData?.meta?.title || `${focusRole} Snapshot`);
    setText("dashboardReportCardSummary", brief.summary || "");
    setText("dashboardReportStatusTag", brief.statusLabel || "Pending");
    setText(
      "dashboardGuideState",
      typeof window.hasSeenWorkspaceGuide === "function" && window.hasSeenWorkspaceGuide()
        ? "Can reopen"
        : "First time"
    );

    const primaryBtn = document.getElementById("dashboardPrimaryActionBtn");
    if (primaryBtn) primaryBtn.textContent = brief.action?.label || "Continue";

    const heroBtn = document.querySelector(".dash-hero-btns .dash-btn-primary");
    if (heroBtn) {
      heroBtn.textContent = brief.action?.label || "Continue";
      heroBtn.onclick = () => window.handleDashboardPrimaryAction?.();
    }

    setHtml(
      "dashboardSignalList",
      (brief.signalChips || [])
        .map((item) => `<span class="dash-workspace-chip">${escapeHtml(item)}</span>`)
        .join("")
    );

    renderWorkspaceJourney(brief);
    updateSectionHints(brief);
  }

  function renderUserProfileWorkspace() {
    const brief = getBrief();
    if (!brief) return;

    setText("upReportTitle", brief.reportData?.meta?.title || "Career Snapshot");
    setText("upReportSummary", brief.summary || "");
    setText("upReportFocusRole", brief.focusRole || "Unresolved");
    setText("upReportNextFocus", brief.tracker?.next_focus || brief.action?.description || "Continue");
    setText("upReportCompletion", `${Math.max(0, Math.min(100, Math.round(Number(brief.completionRate || 0))))}%`);
    setText("upReportLastSync", brief.statusLabel || "Pending");

    setHtml(
      "upReportSignals",
      (brief.signalChips || [])
        .map((item) => `<span class="up-report-chip">${escapeHtml(item)}</span>`)
        .join("")
    );

    setHtml(
      "upReportTasks",
      (brief.taskItems || [])
        .map((item) => `
          <div class="up-report-list-item">
            <strong>${escapeHtml(item.title || "Next task")}</strong>
            <p>${escapeHtml(item.copy || "")}</p>
          </div>
        `)
        .join("")
    );

    const currentUser = typeof window.getCurrentUser === "function" ? window.getCurrentUser() : null;
    setText("upAccountFocusRole", brief.focusRole || "Unresolved");
    setText("upAccountNextAction", brief.action?.label || "Continue");
    setText("upAccountSummary", brief.summary || "");
    setText(
      "upAccountPermissionHint",
      currentUser?.role === "super_admin"
        ? "You can manage model/provider/API configuration."
        : "System configuration is managed by admin."
    );

    renderWorkspaceJourney(brief);
    updateSectionHints(brief);
  }

  function handleUserPermissionCardClick() {
    const user = typeof window.getCurrentUser === "function" ? window.getCurrentUser() : null;
    if (!user) return;
    if (user.role !== "super_admin") {
      if (typeof window.showToast === "function") {
        window.showToast("Permission denied", "Only system admin can edit API settings.", "warning", 1800);
      }
      return;
    }
    if (typeof window.closeUserProfile === "function") window.closeUserProfile();
    if (typeof window.openSettingsPanel === "function") window.openSettingsPanel();
  }

  function syncWorkspaceShell() {
    const brief = getBrief();
    updateWorkspaceJourneyVisibility();
    if (!brief) return;
    renderWorkspaceJourney(brief);
    updateSectionHints(brief);
  }

  const originalShowSection = window.showSection;
  if (typeof originalShowSection === "function") {
    window.showSection = function wrappedShowSection() {
      const result = originalShowSection.apply(this, arguments);
      window.requestAnimationFrame(syncWorkspaceShell);
      return result;
    };
  }

  window.renderDashboardWorkspace = renderDashboardWorkspace;
  window.renderUserProfileWorkspace = renderUserProfileWorkspace;
  window.handleUserPermissionCardClick = handleUserPermissionCardClick;
  window.renderWorkspaceJourney = renderWorkspaceJourney;
  window.updateWorkspaceJourneyVisibility = updateWorkspaceJourneyVisibility;

  document.addEventListener("DOMContentLoaded", () => {
    window.requestAnimationFrame(syncWorkspaceShell);
  });

  window.addEventListener("app:auth-changed", () => {
    window.setTimeout(syncWorkspaceShell, 0);
  });
})();
