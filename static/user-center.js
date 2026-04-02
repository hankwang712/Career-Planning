const USER_CENTER_DEFAULT_SECTION = "report-workspace";
const USER_CENTER_SECTIONS = ["report-workspace", "plan-workspace", "account-center"];
const USER_CENTER_ROLE_FILTERS = {
  all: "全部",
  employed: "在职",
  reapply: "再投",
  expected: "期望",
  left: "离职"
};

const userCenterState = {
  activeSection: USER_CENTER_DEFAULT_SECTION,
  roleFilter: "all",
  /** 个人中心：是否在下方「职业报告正文」区域展开全文（默认 false，需点击运行记录） */
  reportReaderExpanded: false,
  cropper: {
    fileName: "",
    image: null,
    imageSrc: "",
    baseScale: 1,
    zoom: 1,
    offsetX: 0,
    offsetY: 0,
    dragging: false,
    pointerId: null,
    dragStartX: 0,
    dragStartY: 0,
    originOffsetX: 0,
    originOffsetY: 0
  }
};

const USER_CENTER_ROLE_STATUS_ORDER = ["expected", "reapply", "employed", "left"];
const USER_CENTER_ROLE_BOARD_STORAGE_KEY_PREFIX = "uc_role_board_v1_";
userCenterState.roleBoard = null;

function resetUserCenterRoleBoardCache() {
  userCenterState.roleBoard = null;
}

function clipUserCenterText(value, limit = 64) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length <= limit) return text;
  return `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function normalizeUserCenterSection(sectionId) {
  const normalized = String(sectionId || "").trim().replace(/^#/, "");
  return USER_CENTER_SECTIONS.includes(normalized) ? normalized : USER_CENTER_DEFAULT_SECTION;
}

function setUserCenterPasswordMessage(message, tone = "info") {
  const el = document.getElementById("ucPasswordMessage");
  if (!el) return;
  el.textContent = message || "";
  el.style.color = tone === "error" ? "#dc2626" : tone === "success" ? "#047857" : "#64748b";
}

async function submitUserCenterPassword(event) {
  if (event) event.preventDefault();
  const currentPassword = document.getElementById("ucCurrentPassword")?.value || "";
  const newPassword = document.getElementById("ucNewPassword")?.value || "";
  const confirmPassword = document.getElementById("ucConfirmPassword")?.value || "";
  if (!currentPassword || !newPassword || !confirmPassword) {
    setUserCenterPasswordMessage("请完整填写当前密码、新密码和确认密码。", "error");
    return;
  }
  setUserCenterPasswordMessage("正在更新密码…");
  try {
    const payload = await requestJson("/api/auth/password", {
      method: "PUT",
      body: {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword
      }
    });
    ["ucCurrentPassword", "ucNewPassword", "ucConfirmPassword"].forEach((id) => {
      const input = document.getElementById(id);
      if (input) input.value = "";
    });
    setUserCenterPasswordMessage(payload?.message || "密码已更新。", "success");
    showToast("密码已更新", "下次登录请使用新密码。", "success", 1800);
  } catch (error) {
    setUserCenterPasswordMessage(error.message || "密码更新失败。", "error");
  }
}

function switchUserCenterSection(sectionId, options = {}) {
  const nextSection = normalizeUserCenterSection(sectionId);
  userCenterState.activeSection = nextSection;
  if (nextSection === "report-workspace" && !options.keepReportReaderExpanded) {
    userCenterState.reportReaderExpanded = false;
  }

  document.querySelectorAll(".uc-nav-link[data-target]").forEach((button) => {
    button.classList.toggle("active", button.dataset.target === nextSection);
  });
  document.querySelectorAll(".uc-section").forEach((section) => {
    section.classList.toggle("active", section.id === nextSection);
  });

  if (options.updateHash !== false) {
    const url = new URL(window.location.href);
    url.hash = nextSection;
    window.history.replaceState({}, "", url.toString());
  }

  if (nextSection === "plan-workspace" && typeof _loadCareerPlans === "function") {
    void _loadCareerPlans();
  }

  if (nextSection === "account-center") {
    renderUserCenterIdentity();
  }
}

function getUserCenterSelectedJobs() {
  const selected = Array.isArray(appState?.selectedJobs) ? appState.selectedJobs : [];
  return selected.map((jobType) => ({
    id: String(jobType || "").trim(),
    name: (typeof jobNameMap === "object" && jobNameMap?.[jobType]) ? jobNameMap[jobType] : String(jobType || "").trim(),
    source: "manual",
    status: "expected"
  })).filter((item) => item.name);
}

function getUserCenterRoleBoardStorageKey() {
  const username = String(
    (typeof getCurrentUser === "function" ? (getCurrentUser()?.username || "") : "")
      || "guest"
  ).trim().toLowerCase() || "guest";
  return `${USER_CENTER_ROLE_BOARD_STORAGE_KEY_PREFIX}${username}`;
}

function normalizeUserCenterRoleStatus(statusValue) {
  const text = String(statusValue || "").trim().toLowerCase();
  if (!text) return "expected";
  if (["employed", "working", "onboard", "active", "在职"].includes(text)) return "employed";
  if (["reapply", "applied", "interview", "offer", "再投", "投递", "面试中"].includes(text)) return "reapply";
  if (["left", "departed", "inactive", "离职"].includes(text)) return "left";
  if (["expected", "interest", "recommended", "target", "期望", "意向"].includes(text)) return "expected";
  return "expected";
}

function getDefaultUserCenterRoleBoard() {
  return { custom_roles: [], status_by_role: {} };
}

function normalizeUserCenterRoleBoard(rawBoard) {
  const raw = rawBoard && typeof rawBoard === "object" ? rawBoard : {};
  const customRolesRaw = Array.isArray(raw.custom_roles) ? raw.custom_roles : [];
  const statusByRoleRaw = raw.status_by_role && typeof raw.status_by_role === "object" ? raw.status_by_role : {};
  const custom_roles = customRolesRaw
    .map((item, index) => {
      const name = String(item?.name || "").trim();
      if (!name) return null;
      const id = String(item?.id || `custom_${index}_${name}`).trim();
      if (!id) return null;
      return {
        id,
        name,
        status: normalizeUserCenterRoleStatus(item?.status),
        source: "custom",
        meta: "手动添加"
      };
    })
    .filter(Boolean);

  const status_by_role = {};
  Object.entries(statusByRoleRaw).forEach(([roleId, status]) => {
    const key = String(roleId || "").trim();
    if (!key) return;
    status_by_role[key] = normalizeUserCenterRoleStatus(status);
  });

  return { custom_roles, status_by_role };
}

function ensureUserCenterRoleBoard() {
  if (userCenterState.roleBoard) return userCenterState.roleBoard;
  const fallback = getDefaultUserCenterRoleBoard();
  try {
    const parsed = JSON.parse(localStorage.getItem(getUserCenterRoleBoardStorageKey()) || "null");
    userCenterState.roleBoard = normalizeUserCenterRoleBoard(parsed || fallback);
  } catch (_) {
    userCenterState.roleBoard = fallback;
  }
  return userCenterState.roleBoard;
}

function saveUserCenterRoleBoard() {
  const board = normalizeUserCenterRoleBoard(userCenterState.roleBoard || getDefaultUserCenterRoleBoard());
  userCenterState.roleBoard = board;
  try {
    localStorage.setItem(getUserCenterRoleBoardStorageKey(), JSON.stringify(board));
  } catch (_) {
    // ignore storage errors
  }
}

function getUserCenterRoleStatusLabel(status) {
  return USER_CENTER_ROLE_FILTERS[normalizeUserCenterRoleStatus(status)] || USER_CENTER_ROLE_FILTERS.expected;
}

function cycleUserCenterRoleStatus(status) {
  const current = normalizeUserCenterRoleStatus(status);
  const index = USER_CENTER_ROLE_STATUS_ORDER.indexOf(current);
  const nextIndex = index < 0 ? 0 : ((index + 1) % USER_CENTER_ROLE_STATUS_ORDER.length);
  return USER_CENTER_ROLE_STATUS_ORDER[nextIndex];
}

function inferUserCenterRoleStatus(rawStatus, source = "") {
  const normalized = normalizeUserCenterRoleStatus(rawStatus);
  if (rawStatus) return normalized;
  const sourceText = String(source || "").trim().toLowerCase();
  if (sourceText === "report") return "reapply";
  if (sourceText === "manual") return "expected";
  return normalized;
}

function buildUserCenterTargetRoles() {
  const tracker = typeof getCareerReportTracker === "function" ? getCareerReportTracker() : null;
  const reportData = appState?.careerReport || null;
  const matchingRoles = Array.isArray(appState?.matchingRoles) ? appState.matchingRoles : [];
  const recommendedRoles = Array.isArray(appState?.derivedProfile?.recommendedRoles) ? appState.derivedProfile.recommendedRoles : [];
  const board = ensureUserCenterRoleBoard();
  const roleMap = new Map();

  const pushRole = (raw) => {
    const name = String(raw?.name || raw?.title || "").trim();
    if (!name) return;
    const key = String(raw?.id || name).trim().toLowerCase();
    if (!key) return;
    const score = Number(raw?.score ?? raw?.overallScore ?? raw?.matchScore ?? raw?.traitScore ?? raw?.trait?.score ?? 0);
    const next = {
      id: String(raw?.id || key),
      name,
      score: Number.isFinite(score) ? Math.max(0, Math.round(score)) : 0,
      status: inferUserCenterRoleStatus(raw?.status, raw?.source),
      source: raw?.source || "matching",
      isFocus: Boolean(raw?.isFocus),
      meta: String(raw?.meta || "").trim()
    };
    if (!roleMap.has(key)) {
      roleMap.set(key, next);
      return;
    }
    const current = roleMap.get(key);
    roleMap.set(key, {
      ...current,
      ...next,
      score: Math.max(Number(current?.score || 0), Number(next.score || 0)),
      isFocus: Boolean(current?.isFocus || next.isFocus),
      meta: current?.meta || next.meta || ""
    });
  };

  pushRole({
    id: tracker?.focus_role_id || reportData?.meta?.focus_role_id || appState?.focusedRoleId || "",
    name: tracker?.focus_role_name || reportData?.meta?.focus_role_name || "",
    isFocus: true,
    score: tracker?.completion_rate || reportData?.meta?.confidence || 0,
    meta: tracker?.generated_at || tracker?.last_synced_at || reportData?.meta?.generated_at || "",
    source: "report"
  });

  matchingRoles.slice(0, 8).forEach((role, index) => {
    pushRole({
      id: role?.id || "",
      name: role?.name || "",
      score: role?.overallScore || role?.score || role?.trait?.score || 0,
      source: "matching",
      status: role?.status || "",
      isFocus: index === 0 && !tracker?.focus_role_name && !reportData?.meta?.focus_role_name
    });
  });

  getUserCenterSelectedJobs().forEach(pushRole);
  recommendedRoles.slice(0, 6).forEach((name) => {
    pushRole({ id: name, name, source: "recommended" });
  });
  (Array.isArray(board.custom_roles) ? board.custom_roles : []).forEach(pushRole);

  const statusByRole = board.status_by_role && typeof board.status_by_role === "object" ? board.status_by_role : {};
  return [...roleMap.values()]
    .map((item) => {
      const override = statusByRole[String(item.id || "").trim()];
      return {
        ...item,
        status: normalizeUserCenterRoleStatus(override || item.status)
      };
    })
    .sort((left, right) => {
      if (left.isFocus && !right.isFocus) return -1;
      if (!left.isFocus && right.isFocus) return 1;
      return Number(right.score || 0) - Number(left.score || 0);
    });
}

function promptAddUserCenterTargetRole() {
  const roleName = String(window.prompt("请输入目标岗位名称", "") || "").trim();
  if (!roleName) return;
  const board = ensureUserCenterRoleBoard();
  const roleId = `custom_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  board.custom_roles = [
    { id: roleId, name: roleName, status: "expected", source: "custom", meta: "手动添加" },
    ...(Array.isArray(board.custom_roles) ? board.custom_roles : [])
  ];
  board.status_by_role = board.status_by_role && typeof board.status_by_role === "object" ? board.status_by_role : {};
  board.status_by_role[roleId] = "expected";
  saveUserCenterRoleBoard();
  renderUserCenterTargetRoles();
}

function updateUserCenterRoleStatus(roleId, nextStatus) {
  const id = String(roleId || "").trim();
  if (!id) return;
  const board = ensureUserCenterRoleBoard();
  board.status_by_role = board.status_by_role && typeof board.status_by_role === "object" ? board.status_by_role : {};
  board.status_by_role[id] = normalizeUserCenterRoleStatus(nextStatus);
  if (Array.isArray(board.custom_roles)) {
    board.custom_roles = board.custom_roles.map((item) => {
      if (String(item?.id || "").trim() !== id) return item;
      return { ...item, status: board.status_by_role[id] };
    });
  }
  saveUserCenterRoleBoard();
  renderUserCenterTargetRoles();
}

function removeUserCenterRole(roleId) {
  const id = String(roleId || "").trim();
  if (!id) return;
  const board = ensureUserCenterRoleBoard();
  board.custom_roles = (Array.isArray(board.custom_roles) ? board.custom_roles : []).filter((item) => String(item?.id || "").trim() !== id);
  if (board.status_by_role && typeof board.status_by_role === "object") {
    delete board.status_by_role[id];
  }
  saveUserCenterRoleBoard();
  renderUserCenterTargetRoles();
}

function renderUserCenterTargetRoles() {
  const container = document.getElementById("userCenterTargetRoles");
  if (!container) return;
  const roles = buildUserCenterTargetRoles();
  const filter = String(userCenterState.roleFilter || "all").trim();
  const visibleRoles = filter === "all" ? roles : roles.filter((item) => item.status === filter);
  const actionableRoleIds = new Set((Array.isArray(appState?.matchingRoles) ? appState.matchingRoles : []).map((item) => String(item?.id || "")));

  if (!visibleRoles.length) {
    container.innerHTML = `<span class="uc-role-strip-empty">${USER_CENTER_ROLE_FILTERS[filter] || "当前筛选"}下暂无岗位</span>`;
    return;
  }

  container.innerHTML = visibleRoles.map((item) => {
    const roleId = String(item.id || "").trim();
    const isActionable = Boolean(roleId && actionableRoleIds.has(roleId) && typeof setCareerReportFocusRole === "function");
    const isCustom = String(item.source || "").toLowerCase() === "custom";
    return `
      <div class="uc-role-chip${item.isFocus ? " active" : ""}${isCustom ? " custom" : ""}">
        ${isActionable
          ? `<button type="button" class="uc-role-chip-main" data-focus-role-id="${escHtml(roleId)}" title="设为当前报告主岗位">${escHtml(item.name)}</button>`
          : `<span class="uc-role-chip-main static">${escHtml(item.name)}</span>`
        }
        <button type="button" class="uc-role-chip-status" data-role-status-id="${escHtml(roleId)}" title="点击切换状态">
          ${escHtml(getUserCenterRoleStatusLabel(item.status))}
        </button>
        ${isCustom
          ? `<button type="button" class="uc-role-chip-remove" data-role-remove-id="${escHtml(roleId)}" title="移除岗位">×</button>`
          : ""
        }
      </div>
    `;
  }).join("");

  container.querySelectorAll(".uc-role-chip-main[data-focus-role-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const roleId = String(button.dataset.focusRoleId || "").trim();
      if (!roleId || typeof setCareerReportFocusRole !== "function") return;
      setCareerReportFocusRole(roleId);
      switchUserCenterSection("report-workspace", { updateHash: true });
      renderUserCenterDashboard();
    });
  });

  container.querySelectorAll(".uc-role-chip-status[data-role-status-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const roleId = String(button.dataset.roleStatusId || "").trim();
      if (!roleId) return;
      const current = String(button.textContent || "").trim();
      const currentStatus = Object.keys(USER_CENTER_ROLE_FILTERS).find((key) => USER_CENTER_ROLE_FILTERS[key] === current) || "expected";
      updateUserCenterRoleStatus(roleId, cycleUserCenterRoleStatus(currentStatus));
    });
  });

  container.querySelectorAll(".uc-role-chip-remove[data-role-remove-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const roleId = String(button.dataset.roleRemoveId || "").trim();
      if (!roleId) return;
      removeUserCenterRole(roleId);
    });
  });
}

function applyUserCenterReportReaderGate() {
  const onUserCenter = typeof isUserCenterPage === "function" && isUserCenterPage();
  if (!onUserCenter || userCenterState.activeSection !== "report-workspace") return;

  const main = document.getElementById("careerReportMain");
  const banner = document.getElementById("careerReportStatusBanner");
  const aside = document.getElementById("careerReportAside");
  const layout = main?.closest(".career-report-layout");
  if (!main || !banner) return;

  if (!userCenterState.reportReaderExpanded) {
    banner.innerHTML = `
      <div class="uc-report-reader-gate-banner">
        <p>请先在上方<strong>报告运行记录</strong>中点选一条版本，下方才会展开完整正文与侧栏目录。</p>
      </div>`;
    main.innerHTML = `
      <div class="uc-report-reader-placeholder">
        <p class="uc-report-reader-placeholder-title">职业报告正文尚未展开</p>
        <p class="uc-report-reader-placeholder-copy">默认不展示全文，避免与上方摘要重复占屏。点选「报告运行记录」中的任意一行后，这里会加载该版本的章节化正文。</p>
      </div>`;
    if (aside) {
      aside.innerHTML = "";
      aside.classList.add("uc-report-aside-collapsed");
    }
    if (layout) layout.classList.add("uc-report-layout-gated");
    return;
  }

  if (aside) aside.classList.remove("uc-report-aside-collapsed");
  if (layout) layout.classList.remove("uc-report-layout-gated");
}

function setUserCenterReportReaderExpanded(value) {
  userCenterState.reportReaderExpanded = Boolean(value);
}

function renderUserCenterReportRunList() {
  const host = document.getElementById("userCenterReportRuns");
  if (!host) return;
  const pack = typeof window.getCareerReportVersionList === "function" ? window.getCareerReportVersionList() : { versions: [], reportState: null, canonicalReportId: "" };
  const { versions, reportState, canonicalReportId } = pack;
  const selectedId = String(appState?.careerReport?.meta?.report_id || "").trim();

  let pendingBlock = "";
  if (reportState?.status === "running" || reportState?.status === "queued") {
    pendingBlock = `
      <div class="uc-report-run-row uc-report-run-row--pending" role="status">
        <div class="uc-report-run-main">
          <strong>报告生成中</strong>
          <span class="uc-report-run-sub">${escHtml(reportState.stage_label || "排队或编排中")}</span>
        </div>
        <span class="uc-report-run-time">—</span>
      </div>
    `;
  }

  if (!versions.length && !pendingBlock) {
    host.innerHTML = `
      <div class="uc-report-runs-empty">
        <p>还没有已生成的职业报告。先在主界面锁定目标岗位并补齐画像，再回到这里生成。</p>
      </div>
    `;
    return;
  }

  const rows = versions.map((v) => {
    const rid = String(v?.report_id || "").trim();
    const isActive = Boolean(rid && rid === selectedId);
    const title = escHtml(v?.title || "职业规划报告");
    const when = escHtml(v?.generated_at || "--");
    const role = escHtml(v?.focus_role_name || "待识别");
    const isLatest = Boolean(canonicalReportId && rid === canonicalReportId);
    const badge = isLatest
      ? `<span class="uc-report-run-badge">最新</span>`
      : `<span class="uc-report-run-badge muted">历史</span>`;
    return `
      <button type="button" class="uc-report-run-row${isActive ? " active" : ""}" data-report-id="${escHtml(rid)}" ${!rid ? "disabled" : ""}>
        <div class="uc-report-run-main">
          ${badge}
          <strong>${title}</strong>
          <span class="uc-report-run-sub">主目标：${role}</span>
        </div>
        <span class="uc-report-run-time">${when}</span>
      </button>
    `;
  }).join("");

  host.innerHTML = pendingBlock + rows;

  host.querySelectorAll(".uc-report-run-row[data-report-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.getAttribute("data-report-id") || "";
      if (!id) return;
      userCenterState.reportReaderExpanded = true;
      if (canonicalReportId && id === canonicalReportId) {
        void window.restoreLatestCareerReportView();
        return;
      }
      void window.fetchCareerReportVersion(id);
    });
  });
}

function renderUserCenterReportOverview() {
  const displayTracker =
    appState?.careerReportViewingHistorical && appState?.careerReportTracker
      ? appState.careerReportTracker
      : typeof getCareerReportTracker === "function"
        ? getCareerReportTracker()
        : null;
  const reportState = typeof getCareerReportStateSafe === "function" ? getCareerReportStateSafe() : null;
  const reportData = appState?.careerReport || null;
  const scoped = window.userWorkspaceState?.scopedData?.career_report;
  const listTracker = scoped?.tracker || displayTracker;
  const versions = Array.isArray(listTracker?.versions) ? listTracker.versions : [];

  const focusRole = displayTracker?.focus_role_name
    || reportData?.meta?.focus_role_name
    || buildUserCenterTargetRoles()[0]?.name
    || "待识别";
  const updatedAt = reportData?.meta?.generated_at
    || displayTracker?.generated_at
    || displayTracker?.last_synced_at
    || "--";
  const completion = Math.max(0, Math.min(100, Number(displayTracker?.completion_rate ?? appState?.score ?? appState?.profileCompletion ?? 0)));

  const focusEl = document.getElementById("userCenterFocusRole");
  const updatedEl = document.getElementById("userCenterUpdatedAt");
  const completionEl = document.getElementById("userCenterCompletionRate");
  const versionEl = document.getElementById("userCenterVersionCount");
  const historyEl = document.getElementById("userCenterReportHistory");
  const switchHintEl = document.getElementById("userCenterReportSwitchHint");
  const sublineEl = document.getElementById("userCenterReportSubline");
  const viewerBtn = document.getElementById("userCenterOpenReportBtn");
  const generateBtn = document.getElementById("userCenterGenerateReportBtn");
  const versionCount = Number(versions.length || (reportData?.report_document ? 1 : 0));

  if (focusEl) focusEl.textContent = focusRole;
  if (updatedEl) updatedEl.textContent = updatedAt;
  if (completionEl) completionEl.textContent = `${completion}%`;
  if (versionEl) versionEl.textContent = String(versionCount);
  if (viewerBtn) viewerBtn.disabled = !Boolean(appState?.reportReady && reportData?.report_document);
  if (generateBtn) {
    generateBtn.disabled = Boolean(reportState?.status === "running" || reportState?.status === "queued");
    generateBtn.textContent = reportState?.status === "running" || reportState?.status === "queued"
      ? "生成中..."
      : appState?.reportReady ? "重新生成职业报告" : "生成职业报告";
  }

  if (sublineEl) {
    const title = reportData?.meta?.title || displayTracker?.report_title || "职业规划报告";
    const at = reportData?.meta?.generated_at || displayTracker?.generated_at || "--";
    sublineEl.textContent = `${title} · 生成时间 ${at}`;
  }

  if (historyEl) {
    historyEl.textContent = appState?.careerReportViewingHistorical
      ? "当前为历史版本，计划状态与同步不会在服务端更新，直至回到最新版本。"
      : "";
  }
  if (switchHintEl) {
    switchHintEl.textContent = versionCount > 1
      ? `当前共 ${versionCount} 份报告，可在左侧「报告运行记录」中点击切换查看。`
      : "当前仅 1 份报告。后续每次重新生成会自动新增版本，可在左侧运行记录切换查看。";
  }
}

function getUserCenterAvatarState() {
  return typeof getAccountAvatarState === "function" ? getAccountAvatarState() : null;
}

function renderUserCenterIdentity() {
  const user = typeof getCurrentUser === "function" ? getCurrentUser() : null;
  if (!user) return;

  const displayName = user.display_name || user.displayName || user.username || "用户";
  const roleLabel = user.role === "super_admin" ? "系统管理员" : "普通用户";
  const avatarState = getUserCenterAvatarState();
  const avatarUrl = avatarState?.source === "uploaded" ? String(avatarState.image_url || "").trim() : "";

  const nameEl = document.getElementById("upName");
  const roleEl = document.getElementById("upRoleTag");
  const stageEl = document.getElementById("userCenterAvatarStage");
  const hintEl = document.getElementById("userCenterAvatarHint");
  const removeBtn = document.getElementById("userCenterAvatarRemoveBtn");
  const permissionHint = document.getElementById("upAccountPermissionHint");
  const adminBar = document.getElementById("upAdminBar");
  const adminBtn = adminBar?.querySelector(".up-admin-link");

  if (nameEl) nameEl.textContent = displayName;
  if (roleEl) roleEl.textContent = roleLabel;

  if (stageEl) {
    if (avatarUrl) {
      stageEl.innerHTML = `<img src="${escHtml(avatarUrl)}" alt="${escHtml(displayName)}">`;
    } else {
      stageEl.innerHTML = `<div class="up-avatar-circle">${escHtml(displayName.charAt(0).toUpperCase())}</div>`;
    }
  }

  if (hintEl) {
    hintEl.textContent = avatarUrl
      ? `当前头像最近更新于 ${avatarState?.updated_at || "--"}。`
      : "支持本地图片上传，并在裁切框中调整后保存为账号头像。";
  }
  if (removeBtn) removeBtn.classList.toggle("hidden", !avatarUrl);

  if (permissionHint) {
    permissionHint.textContent = user.role === "super_admin"
      ? "你当前是 system 用户，可以直接打开配置面板管理模型、Provider 和 API Key。"
      : "普通用户不开放系统 API 管理，只能维护自己的账号信息与职业档案。";
  }

  if (adminBtn) {
    adminBtn.classList.remove("locked", "unlocked");
    if (user.role === "super_admin") {
      adminBtn.disabled = false;
      adminBtn.classList.add("unlocked");
      adminBtn.innerHTML = `
        <div class="up-admin-link-copy">
          <strong>系统 API 配置</strong>
          <span>点击右侧按钮直接打开配置面板，修改当前可用的 Provider、模型和 API Key。</span>
        </div>
        <span>打开配置</span>
      `;
    } else {
      adminBtn.disabled = true;
      adminBtn.classList.add("locked");
      adminBtn.innerHTML = `
        <div class="up-admin-link-copy">
          <strong>系统 API 配置</strong>
          <span>普通用户不可修改系统 API，只保留查看个人中心和学习路径的权限。</span>
        </div>
        <span>不可用</span>
      `;
    }
  }
}

function getUserCenterCropFrameSize() {
  return Math.max(1, document.getElementById("userCenterCropFrame")?.clientWidth || 320);
}

function clampUserCenterCropOffsets() {
  const cropper = userCenterState.cropper;
  if (!cropper.image) return;
  const frameSize = getUserCenterCropFrameSize();
  const scale = cropper.baseScale * cropper.zoom;
  const scaledWidth = cropper.image.naturalWidth * scale;
  const scaledHeight = cropper.image.naturalHeight * scale;
  const maxOffsetX = Math.max(0, (scaledWidth - frameSize) / 2);
  const maxOffsetY = Math.max(0, (scaledHeight - frameSize) / 2);
  cropper.offsetX = Math.min(maxOffsetX, Math.max(-maxOffsetX, cropper.offsetX));
  cropper.offsetY = Math.min(maxOffsetY, Math.max(-maxOffsetY, cropper.offsetY));
}

function renderUserCenterCropper() {
  const frame = document.getElementById("userCenterCropFrame");
  const image = document.getElementById("userCenterCropImage");
  const cropper = userCenterState.cropper;
  if (!frame || !image || !cropper.image) return;

  clampUserCenterCropOffsets();
  const scale = cropper.baseScale * cropper.zoom;
  image.src = cropper.imageSrc;
  image.style.width = `${cropper.image.naturalWidth}px`;
  image.style.height = `${cropper.image.naturalHeight}px`;
  image.style.transform = `translate(-50%, -50%) translate(${cropper.offsetX}px, ${cropper.offsetY}px) scale(${scale})`;
  frame.classList.toggle("dragging", cropper.dragging);
}

function closeUserCenterAvatarCropper() {
  const modal = document.getElementById("userCenterCropperModal");
  if (modal) modal.classList.add("hidden");
  userCenterState.cropper.dragging = false;
  userCenterState.cropper.pointerId = null;
}

function openUserCenterAvatarCropper(file) {
  if (!file) return;
  if (!String(file.type || "").startsWith("image/")) {
    showToast("文件类型不支持", "请选择 JPG、PNG 或 WebP 图片。", "warning", 2000);
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => {
      const frameSize = getUserCenterCropFrameSize();
      userCenterState.cropper.fileName = file.name || "";
      userCenterState.cropper.image = img;
      userCenterState.cropper.imageSrc = String(reader.result || "");
      userCenterState.cropper.baseScale = Math.max(frameSize / img.naturalWidth, frameSize / img.naturalHeight);
      userCenterState.cropper.zoom = 1;
      userCenterState.cropper.offsetX = 0;
      userCenterState.cropper.offsetY = 0;
      const zoomInput = document.getElementById("userCenterCropZoom");
      if (zoomInput) zoomInput.value = "100";
      document.getElementById("userCenterCropperModal")?.classList.remove("hidden");
      renderUserCenterCropper();
    };
    img.src = String(reader.result || "");
  };
  reader.readAsDataURL(file);
}

function beginUserCenterCropDrag(event) {
  if (!userCenterState.cropper.image) return;
  const frame = document.getElementById("userCenterCropFrame");
  userCenterState.cropper.dragging = true;
  userCenterState.cropper.pointerId = event.pointerId;
  userCenterState.cropper.dragStartX = event.clientX;
  userCenterState.cropper.dragStartY = event.clientY;
  userCenterState.cropper.originOffsetX = userCenterState.cropper.offsetX;
  userCenterState.cropper.originOffsetY = userCenterState.cropper.offsetY;
  frame?.setPointerCapture?.(event.pointerId);
  renderUserCenterCropper();
}

function moveUserCenterCropDrag(event) {
  if (!userCenterState.cropper.dragging) return;
  userCenterState.cropper.offsetX = userCenterState.cropper.originOffsetX + (event.clientX - userCenterState.cropper.dragStartX);
  userCenterState.cropper.offsetY = userCenterState.cropper.originOffsetY + (event.clientY - userCenterState.cropper.dragStartY);
  renderUserCenterCropper();
}

function endUserCenterCropDrag(event) {
  if (!userCenterState.cropper.dragging) return;
  const frame = document.getElementById("userCenterCropFrame");
  userCenterState.cropper.dragging = false;
  if (event?.pointerId !== undefined) {
    frame?.releasePointerCapture?.(event.pointerId);
  }
  userCenterState.cropper.pointerId = null;
  renderUserCenterCropper();
}

async function saveUserCenterAvatarFromCropper() {
  const cropper = userCenterState.cropper;
  if (!cropper.image) return;

  const frameSize = getUserCenterCropFrameSize();
  const outputSize = 360;
  const scaleRatio = outputSize / frameSize;
  const scale = cropper.baseScale * cropper.zoom * scaleRatio;
  const canvas = document.createElement("canvas");
  canvas.width = outputSize;
  canvas.height = outputSize;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  ctx.clearRect(0, 0, outputSize, outputSize);
  ctx.translate(outputSize / 2 + cropper.offsetX * scaleRatio, outputSize / 2 + cropper.offsetY * scaleRatio);
  ctx.scale(scale, scale);
  ctx.drawImage(cropper.image, -cropper.image.naturalWidth / 2, -cropper.image.naturalHeight / 2);

  const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
  await saveScopedUserState("account_avatar", {
    source: "uploaded",
    image_url: dataUrl,
    file_name: cropper.fileName || "",
    updated_at: new Date().toLocaleString("zh-CN")
  });

  if (typeof renderTopbarAvatar === "function") renderTopbarAvatar();
  closeUserCenterAvatarCropper();
  renderUserCenterIdentity();
  showToast("头像已更新", "右上角头像和个人设置页已同步刷新。", "success", 1800);
}

async function clearUserCenterAvatar() {
  await saveScopedUserState("account_avatar", null);
  if (typeof renderTopbarAvatar === "function") renderTopbarAvatar();
  renderUserCenterIdentity();
  showToast("头像已移除", "已恢复为默认头像。", "success", 1600);
}

function bindUserCenterEvents() {
  document.querySelectorAll(".uc-nav-link[data-target]").forEach((button) => {
    button.addEventListener("click", () => {
      switchUserCenterSection(button.dataset.target, { updateHash: true });
    });
  });

  document.querySelectorAll(".uc-filter-chip[data-role-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      userCenterState.roleFilter = String(button.dataset.roleFilter || "all");
      document.querySelectorAll(".uc-filter-chip[data-role-filter]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderUserCenterTargetRoles();
    });
  });

  const addRoleButton = document.getElementById("userCenterTargetRoleAddBtn");
  addRoleButton?.addEventListener("click", promptAddUserCenterTargetRole);

  const avatarUploadBtn = document.getElementById("userCenterAvatarUploadBtn");
  const avatarInput = document.getElementById("userCenterAvatarInput");
  const avatarRemoveBtn = document.getElementById("userCenterAvatarRemoveBtn");
  const cropFrame = document.getElementById("userCenterCropFrame");
  const cropZoom = document.getElementById("userCenterCropZoom");

  avatarUploadBtn?.addEventListener("click", () => avatarInput?.click());
  avatarInput?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    if (file) openUserCenterAvatarCropper(file);
    event.target.value = "";
  });
  avatarRemoveBtn?.addEventListener("click", () => {
    void clearUserCenterAvatar().catch((error) => {
      showToast("头像移除失败", error.message || "请稍后重试。", "error", 2200);
    });
  });

  cropFrame?.addEventListener("pointerdown", beginUserCenterCropDrag);
  cropFrame?.addEventListener("pointermove", moveUserCenterCropDrag);
  cropFrame?.addEventListener("pointerup", endUserCenterCropDrag);
  cropFrame?.addEventListener("pointercancel", endUserCenterCropDrag);
  cropFrame?.addEventListener("pointerleave", endUserCenterCropDrag);
  cropZoom?.addEventListener("input", (event) => {
    userCenterState.cropper.zoom = Math.max(1, Number(event.target.value || 100) / 100);
    renderUserCenterCropper();
  });

  document.getElementById("userCenterCropperClose")?.addEventListener("click", closeUserCenterAvatarCropper);
  document.getElementById("userCenterCropperCancel")?.addEventListener("click", closeUserCenterAvatarCropper);
  document.getElementById("userCenterCropperSave")?.addEventListener("click", () => {
    void saveUserCenterAvatarFromCropper().catch((error) => {
      showToast("头像保存失败", error.message || "请稍后重试。", "error", 2200);
    });
  });
  document.getElementById("userCenterCropperModal")?.addEventListener("click", (event) => {
    if (event.target?.id === "userCenterCropperModal") closeUserCenterAvatarCropper();
  });

  window.addEventListener("resize", () => {
    if (!document.getElementById("userCenterCropperModal")?.classList.contains("hidden")) {
      renderUserCenterCropper();
    }
  });
  window.addEventListener("hashchange", () => handleUserCenterUrlChange());
  window.addEventListener("popstate", () => handleUserCenterUrlChange());
  window.addEventListener("app:auth-changed", () => {
    resetUserCenterRoleBoardCache();
    if (typeof getCurrentUser === "function" && getCurrentUser() && typeof loadAccountAvatarState === "function") {
      void loadAccountAvatarState(false).finally(() => renderUserCenterDashboard());
      return;
    }
    renderUserCenterDashboard();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeUserCenterAvatarCropper();
  });
}

function handleUserCenterUrlChange() {
  const url = new URL(window.location.href);
  const hashSection = normalizeUserCenterSection(url.hash || USER_CENTER_DEFAULT_SECTION);
  const focusRoleId = url.searchParams.get("focus_role");
  const action = url.searchParams.get("action");
  const reportIdOpen = String(url.searchParams.get("report_id") || "").trim();
  const initialSection = reportIdOpen ? "report-workspace" : hashSection;

  switchUserCenterSection(initialSection, { updateHash: false, keepReportReaderExpanded: Boolean(reportIdOpen) });

  if (focusRoleId) {
    appState.focusedRoleId = String(focusRoleId);
    if (typeof renderReportWorkspace === "function") {
      renderReportWorkspace(appState.derivedProfile || deriveUnifiedProfile(), appState.matchingRoles || []);
    }
    switchUserCenterSection("report-workspace", { updateHash: false, keepReportReaderExpanded: Boolean(reportIdOpen) });
    url.searchParams.delete("focus_role");
  }

  if (reportIdOpen) {
    userCenterState.reportReaderExpanded = true;
    switchUserCenterSection("report-workspace", { updateHash: false, keepReportReaderExpanded: true });
    const pack = typeof window.getCareerReportVersionList === "function" ? window.getCareerReportVersionList() : { canonicalReportId: "" };
    const canonical = String(pack.canonicalReportId || "").trim();
    if (canonical && reportIdOpen === canonical) {
      void window.restoreLatestCareerReportView?.();
    } else {
      void window.fetchCareerReportVersion?.(reportIdOpen);
    }
    url.searchParams.delete("report_id");
    url.hash = "report-workspace";
    window.history.replaceState({}, "", url.toString());
    renderUserCenterDashboard();
    return;
  }

  if (action === "settings") {
    // 地址栏 hash 已指定报告/学习路径时，不要被 ?action=settings 拽到设置中心（例如从主站带头像跳转后仍带旧 query）
    if (hashSection === "report-workspace" || hashSection === "plan-workspace") {
      url.searchParams.delete("action");
    } else {
      switchUserCenterSection("account-center", { updateHash: false });
      if (typeof openSettingsPanel === "function") openSettingsPanel();
      url.searchParams.delete("action");
    }
  } else if (action === "generate") {
    switchUserCenterSection("report-workspace", { updateHash: false });
    url.searchParams.delete("action");
    window.history.replaceState({}, "", url.toString());
    void startCareerReportGeneration();
    renderUserCenterDashboard();
    return;
  }

  window.history.replaceState({}, "", url.toString());
  renderUserCenterDashboard();
}

function renderUserCenterDashboard() {
  const reportState = typeof getCareerReportStateSafe === "function" ? getCareerReportStateSafe() : null;
  if (reportState?.status === "running" || reportState?.status === "queued") {
    userCenterState.reportReaderExpanded = true;
  }
  renderUserCenterReportRunList();
  if (!userCenterState.reportReaderExpanded) {
    const firstRun = document.querySelector("#userCenterReportRuns .uc-report-run-row[data-report-id]");
    if (firstRun) firstRun.click();
  }
  renderUserCenterTargetRoles();
  renderUserCenterReportOverview();
  renderUserCenterIdentity();
  if (typeof _updateLifeProgress === "function") _updateLifeProgress();
  if (typeof _updatePlanStats === "function") _updatePlanStats();
  applyUserCenterReportReaderGate();
}

window.switchUserCenterSection = switchUserCenterSection;
window.handleUserCenterUrlChange = handleUserCenterUrlChange;
window.renderUserCenterDashboard = renderUserCenterDashboard;
window.applyUserCenterReportReaderGate = applyUserCenterReportReaderGate;
window.setUserCenterReportReaderExpanded = setUserCenterReportReaderExpanded;
window.submitUserCenterPassword = submitUserCenterPassword;

document.addEventListener("DOMContentLoaded", () => {
  bindUserCenterEvents();
  Promise.resolve(initAuth()).finally(async () => {
    if (typeof _loadCareerPlans === "function") {
      await _loadCareerPlans();
    }
    renderUserCenterDashboard();
    handleUserCenterUrlChange();
  });
});
