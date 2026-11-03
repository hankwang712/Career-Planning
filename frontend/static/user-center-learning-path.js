(function () {
  const CAREER_PLAN_SCOPE = "career_plans";
  const LEGACY_PLAN_STORAGE_PREFIX = "dp_overlay_plans_v1_";
  const LEGACY_PROGRESS_STORAGE_PREFIX = "dp_plan_progress_v1_";
  const PHASE_ORDER = ["short", "mid", "long"];
  const PHASE_META = {
    short: { label: "短期", title: "短期 · 1—3个月", empty: "尚未生成短期任务，请生成报告或添加自己的计划。", accent: "short" },
    mid: { label: "中期", title: "中期 · 3—12个月", empty: "这份报告尚无中期成长路线，可重新生成报告补充。", accent: "mid" },
    long: { label: "长期", title: "长期 · 1—3年", empty: "这份报告尚无长期成长路线，可重新生成报告补充。", accent: "long" }
  };
  const BADGE_META = {
    start: { icon: "🚀", title: "开始行动", desc: "完成第一项任务" },
    streak3: { icon: "🔥", title: "连击 3 天", desc: "连续打卡 3 天" },
    streak7: { icon: "💎", title: "连击 7 天", desc: "历史连续 7 天" },
    xp100: { icon: "⚡", title: "累计 100XP", desc: "经验值过百" },
    skills: { icon: "🎓", title: "技能大师", desc: "完成 5 项技能任务" },
    path: { icon: "🏅", title: "路径完成者", desc: "完成一个完整阶段" }
  };

  const runtime = {
    initialized: false,
    loading: false,
    tracker: null,
    store: null,
    toastTimer: null,
    activePhaseFilter: "all"   // "all" | "short" | "mid" | "long"
  };

  const PHASE_TABS = [
    { key: "all",   label: "全部",  emoji: "" },
    { key: "short", label: "短期",  emoji: "" },
    { key: "mid",   label: "中期",  emoji: "" },
    { key: "long",  label: "长期",  emoji: "" }
  ];

  function getCurrentUserSafe() {
    return typeof window.getCurrentUser === "function" ? window.getCurrentUser() : null;
  }

  function currentUserName() {
    return String(getCurrentUserSafe()?.username || "guest").trim().toLowerCase() || "guest";
  }

  function legacyPlanKey() {
    return `${LEGACY_PLAN_STORAGE_PREFIX}${currentUserName()}`;
  }

  function legacyProgressKey() {
    return `${LEGACY_PROGRESS_STORAGE_PREFIX}${currentUserName()}`;
  }

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function uid(prefix) {
    return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  }

  function nowStamp() {
    return new Date().toISOString();
  }

  function dayKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function addDays(date, delta) {
    const next = new Date(date);
    next.setDate(next.getDate() + delta);
    return next;
  }

  function formatDateTime(value) {
    const text = String(value || "").trim();
    if (!text) return "--";
    const normalized = text.includes("T") ? text : text.replace(" ", "T");
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) return text;
    return parsed.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function focusRoleName() {
    const trackerRole = String(runtime.tracker?.focus_role_name || "").trim();
    if (trackerRole) return trackerRole;
    const focused = String(window.appState?.focusedRoleId || "").trim();
    if (focused && window.jobNameMap?.[focused]) return window.jobNameMap[focused];
    const selected = Array.isArray(window.appState?.selectedJobs) ? window.appState.selectedJobs : [];
    const first = String(selected[0] || "").trim();
    return (first && window.jobNameMap?.[first]) || first || "待识别";
  }

  function readJsonStorage(key, fallback) {
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      return parsed ?? fallback;
    } catch (_) {
      return fallback;
    }
  }

  function defaultProgress() {
    return {
      streak: 0,
      best_streak: 0,
      xp: 0,
      last_checkin: "",
      active_days: {}
    };
  }

  function inferPhaseKey(value, fallback = "short") {
    const text = String(value || "").trim().toLowerCase();
    if (!text) return fallback;
    if (text.includes("中期")) return "mid";
    if (text.includes("长期")) return "long";
    if (text.includes("短期") && text.includes("进阶")) return "mid";
    if (text.includes("复查")) return "long";
    if (text.includes("短期")) return "short";
    if (["short", "mid", "long"].includes(text)) return text;
    if (text.includes("long")) return "long";
    if (text.includes("mid")) return "mid";
    if (text.includes("short")) return "short";
    // 数字范围推断：3-12m、6m、12m 等视为中期；1-3y 等视为长期；0-3m 视为短期
    if (/\b(3-12|6m|12m|3~12|3—12)\b/.test(text)) return "mid";
    if (/\b(0-3|3m|0~3|0—3)\b/.test(text)) return "short";
    if (/\b(1-3y|1~3y|1—3y|year|years)\b/.test(text)) return "long";
    return fallback;
  }

  function phaseLabel(phaseKey) {
    return PHASE_META[phaseKey]?.label || "短期";
  }

  function taskTagClass(tag) {
    const text = String(tag || "").trim();
    if (["证据", "阶段目标"].includes(text)) return "evidence";
    if (["实践", "起步", "推进"].includes(text)) return "practice";
    if (["复查", "验证"].includes(text)) return "interview";
    return "skill";
  }

  function sourceLabel(source) {
    return source === "report" ? "报告" : "手动";
  }

  function normalizeTask(rawTask, index) {
    const raw = rawTask && typeof rawTask === "object" ? rawTask : {};
    return {
      id: String(raw.id || `task_${index}`).trim() || `task_${index}`,
      title: String(raw.title || raw.text || raw.label || "").trim() || `任务 ${index + 1}`,
      note: String(raw.note || raw.summary || "").trim(),
      tag: String(raw.tag || "").trim(),
      deadline: String(raw.deadline || "").trim(),
      xp: Math.max(0, Number(raw.xp ?? 20) || 0),
      done: Boolean(raw.done || String(raw.status || "").trim().toLowerCase() === "done")
    };
  }

  function normalizePlan(rawPlan, index) {
    const raw = rawPlan && typeof rawPlan === "object" ? rawPlan : {};
    const itemsRaw = Array.isArray(raw.items) ? raw.items : [];
    return {
      id: String(raw.id || `plan_${index}`).trim() || `plan_${index}`,
      title: String(raw.title || raw.name || "").trim() || `未命名计划 ${index + 1}`,
      summary: String(raw.summary || raw.description || "").trim(),
      phase_key: inferPhaseKey(raw.phase_key || raw.phaseKey || raw.type || raw.phase || "", "short"),
      source: String(raw.source || "manual").trim() === "report" ? "report" : "manual",
      role: String(raw.role || raw.focus_role_name || "").trim(),
      timeline: String(raw.timeline || raw.phase || "").trim(),
      report_id: String(raw.report_id || raw.reportId || "").trim(),
      created_at: String(raw.created_at || raw.createdAt || "").trim() || nowStamp(),
      updated_at: String(raw.updated_at || raw.updatedAt || "").trim() || nowStamp(),
      items: itemsRaw.map(normalizeTask)
    };
  }

  function defaultManualPlans() {
    return [];
  }

  function normalizeStore(rawStore) {
    const raw = rawStore && typeof rawStore === "object" ? rawStore : {};
    const progressRaw = raw.progress && typeof raw.progress === "object" ? raw.progress : {};
    const plans = Array.isArray(raw.plans) ? raw.plans.map(normalizePlan).filter((plan) => !isUntouchedExamplePlan(plan)) : [];
    return {
      version: 3,
      plans: plans.length ? plans : defaultManualPlans(),
      progress: {
        streak: Math.max(0, Number(progressRaw.streak || 0)),
        best_streak: Math.max(0, Number(progressRaw.best_streak || 0)),
        xp: Math.max(0, Number(progressRaw.xp || 0)),
        last_checkin: String(progressRaw.last_checkin || "").trim(),
        active_days: progressRaw.active_days && typeof progressRaw.active_days === "object" ? progressRaw.active_days : {}
      },
      updated_at: String(raw.updated_at || raw.updatedAt || "").trim() || nowStamp()
    };
  }

  function isUntouchedExamplePlan(plan) {
    if (plan.source === "report" || plan.items.some((item) => item.done || item.note || item.deadline)) return false;
    const templates = [
      ["短期推进", "用 2-4 周先建立一轮能被验证的岗位证据。", ["整理 10 条目标岗位样本", "补一段能证明能力的项目案例"]],
      ["中期进阶", "把方向判断逐步变成稳定输出和可复用能力。", ["围绕目标岗位补一轮作品集", "完成一次周复盘并更新路径判断"]],
      ["长期路径验证", "把求职推进、路径验证和后续复盘放在同一条长期线上。", ["建立季度复盘节奏"]]
    ];
    return templates.some(([suffix, summary, titles]) => plan.title.endsWith(` ${suffix}`) && plan.summary === summary
      && JSON.stringify(plan.items.map((item) => item.title)) === JSON.stringify(titles));
  }

  function legacyStore() {
    const rawPlans = readJsonStorage(legacyPlanKey(), []);
    const rawProgress = readJsonStorage(legacyProgressKey(), defaultProgress());
    const normalizedPlans = (Array.isArray(rawPlans) ? rawPlans : []).map((plan, index) => {
      const title = String(plan?.title || "").trim();
      const phaseKey = inferPhaseKey(plan?.phase_key || plan?.type || title, index === 0 ? "short" : index === 1 ? "mid" : "long");
      return normalizePlan({
        ...plan,
        phase_key: phaseKey,
        source: "manual",
        role: focusRoleName()
      }, index);
    });
    return normalizeStore({
      plans: normalizedPlans.length ? normalizedPlans : defaultManualPlans(),
      progress: rawProgress
    });
  }

  function writeLegacyMirror(store) {
    if (!store) return;
    try {
      localStorage.setItem(legacyPlanKey(), JSON.stringify(store.plans));
      localStorage.setItem(legacyProgressKey(), JSON.stringify(store.progress));
    } catch (_) {
      // ignore storage failures
    }
  }

  async function readScopedStore() {
    if (typeof window.fetchScopedUserState !== "function") return null;
    try {
      const payload = await window.fetchScopedUserState(CAREER_PLAN_SCOPE, true);
      return payload && typeof payload === "object" ? payload : null;
    } catch (_) {
      return null;
    }
  }

  async function saveStore() {
    if (!runtime.store) return;
    runtime.store.updated_at = nowStamp();
    writeLegacyMirror(runtime.store);
    if (typeof window.saveScopedUserState === "function" && getCurrentUserSafe()) {
      try {
        await window.saveScopedUserState(CAREER_PLAN_SCOPE, runtime.store);
      } catch (error) {
        console.warn("save career plans failed", error);
      }
    }
  }

  async function loadTracker() {
    const direct = typeof window.getCareerReportTracker === "function" ? window.getCareerReportTracker() : null;
    if (direct && typeof direct === "object") return direct;
    if (typeof window.fetchScopedUserState !== "function") return null;
    try {
      const payload = await window.fetchScopedUserState("career_report", true);
      return payload?.tracker || null;
    } catch (_) {
      return null;
    }
  }

  function buildTrackerPlans(tracker) {
    if (!tracker || typeof tracker !== "object") return [];
    const role = String(tracker.focus_role_name || "").trim();
    const reportId = String(tracker.report_id || "").trim();
    const plans = [];
    const allItems = Array.isArray(tracker.plan_items) ? tracker.plan_items : [];

    // Separate phase-level items from nested task items
    const phaseItems = allItems.filter((item) => item?.is_phase);
    const taskItems = allItems.filter((item) => item?.is_task);

    // Build lookup: parent_phase_id → [child task items]
    const tasksByPhase = {};
    taskItems.forEach((task) => {
      const parentId = String(task?.parent_phase || "").trim();
      if (!parentId) return;
      if (!tasksByPhase[parentId]) tasksByPhase[parentId] = [];
      tasksByPhase[parentId].push(task);
    });

    phaseItems.forEach((item, index) => {
      const phase = String(item?.phase || "").trim();
      // 根据 phase 文本推断 short/mid/long，不再依赖硬编码的索引
      const phaseKey = inferPhaseKey(item?.phase_key || phase, "short");
      const summary = String(item?.objective || "").trim();
      const tasks = [];
      const actualAction = item.is_action || Boolean(item.deliverable && !item.is_roadmap);
      const taskNote = (task) => [
        task.requirement ? `对应要求：${task.requirement}` : "",
        task.deliverable ? `交付物：${task.deliverable}` : "",
        task.acceptance_criteria ? `验收：${task.acceptance_criteria}` : "",
        task.hours ? `预计 ${task.hours} 小时` : "",
        task.depends_on?.length ? `前置任务：${task.depends_on.join("、")}` : "",
        task.conditional ? `进入条件：${item.entry_conditions || "阶段复核后确认"}` : ""
      ].filter(Boolean).join("\n");

      if (actualAction) tasks.push({ id: item.id, title: item.title, note: taskNote(item),
        deadline: item.deadline, tag: "行动", xp: 20, done: item.status === "done" });

      // 1. Phase objective as an overview task
      if (summary && !actualAction && !item.is_roadmap && !(tasksByPhase[String(item?.id || "")] || []).length) {
        tasks.push({
          id: `${item.id || index}_objective`,
          title: summary,
          tag: "阶段目标",
          xp: 40,
          done: String(item?.status || "").trim().toLowerCase() === "done"
        });
      }

      // 2. Actual action tasks from phase_plan.tasks[] (stored as is_task items in tracker)
      const childTasks = tasksByPhase[String(item?.id || "")] || [];
      childTasks.forEach((task) => {
        tasks.push({
          id: String(task.id || ""),
          title: String(task.title || task.objective || "").trim(),
          tag: "实践",
          note: taskNote(task),
          deadline: task.deadline || "",
          xp: 20,
          done: String(task?.status || "").trim().toLowerCase() === "done"
        });
      });

      // 3. Focus points as skill tasks (fallback when no nested task items exist)
      if (childTasks.length === 0 && !actualAction && !item.is_roadmap && !summary) {
        (Array.isArray(item?.focus_points) ? item.focus_points : []).forEach((point, pointIndex) => {
          const text = String(point || "").trim();
          if (!text || /^C\d+$/i.test(text)) return;
          tasks.push({
            id: `${item.id || index}_focus_${pointIndex}`,
            title: text,
            tag: "技能",
            xp: 20
          });
        });
      }

      // 4. Success signals as validation tasks
      (Array.isArray(item?.signals) && !actualAction && !item.is_roadmap && !summary && !childTasks.length ? item.signals : []).forEach((signal, signalIndex) => {
        const text = String(signal || "").trim();
        if (!text) return;
        tasks.push({
          id: `${item.id || index}_signal_${signalIndex}`,
          title: text,
          tag: "验证",
          xp: 16
        });
      });

      plans.push(normalizePlan({
        id: `report_${item?.id || index}`,
        title: String(item?.title || phase || `阶段 ${index + 1}`).trim(),
        summary,
        phase_key: phaseKey,
        source: "report",
        role,
        timeline: item.deadline || phase || `阶段 ${index + 1}`,
        report_id: reportId,
        updated_at: item?.updated_at || tracker.last_synced_at || tracker.generated_at,
        items: tasks
      }));
    });

    // 复核节点保留真实阶段和日期。
    const checkpoints = Array.isArray(tracker.checkpoints) ? tracker.checkpoints : [];
    PHASE_ORDER.forEach((phaseKey) => {
      const phaseChecks = checkpoints.filter((item) => inferPhaseKey(item.label, "short") === phaseKey);
      if (!phaseChecks.length) return;
      plans.push(normalizePlan({
        id: `report_review_${phaseKey}_${reportId || "current"}`,
        title: `${phaseLabel(phaseKey)}阶段评估`,
        summary: "根据交付成果判断是否继续、延长练习或调整职业目标。",
        phase_key: phaseKey,
        source: "report",
        role,
        timeline: phaseChecks[0].due_date || `${phaseLabel(phaseKey)} · 阶段复核`,
        report_id: reportId,
        updated_at: tracker.last_synced_at || tracker.generated_at,
        items: phaseChecks.map((checkpoint, checkIndex) => ({
          id: `checkpoint_${checkpoint.id || checkIndex}`,
          title: String(checkpoint?.label || `复查 ${checkIndex + 1}`).trim(),
          note: String(checkpoint?.summary || "").trim(),
          deadline: checkpoint.due_date || "",
          tag: "复查",
          xp: 18,
          done: String(checkpoint?.status || "").trim().toLowerCase() === "done"
        }))
      }));
    });

    return plans;
  }

  function mergeTrackerPlans(store, tracker) {
    const next = normalizeStore(store);
    const manualPlans = next.plans.filter((plan) => plan.source !== "report");
    const previousReportPlans = new Map(next.plans.filter((plan) => plan.source === "report").map((plan) => [plan.id, plan]));
    const reportPlans = buildTrackerPlans(tracker).map((plan) => {
      const previous = previousReportPlans.get(plan.id);
      if (!previous || previous.report_id !== plan.report_id) return plan;
      const itemMap = new Map(previous.items.map((item) => [item.id, item]));
      return {
        ...plan,
        items: plan.items.map((item) => ({
          ...item,
          done: itemMap.get(item.id)?.done ?? itemMap.get(`${item.id}_objective`)?.done ?? item.done
        }))
      };
    });
    next.plans = [...reportPlans, ...manualPlans];
    return next;
  }

  function planStats(plan) {
    const total = Array.isArray(plan?.items) ? plan.items.length : 0;
    const done = Array.isArray(plan?.items) ? plan.items.filter((item) => item.done).length : 0;
    return { total, done, pct: total ? Math.round((done / total) * 100) : 0 };
  }

  function computeStats(store) {
    const plans = Array.isArray(store?.plans) ? store.plans : [];
    const totals = plans.reduce((acc, plan) => {
      const stats = planStats(plan);
      acc.total += stats.total;
      acc.done += stats.done;
      acc.completedPlans += stats.total > 0 && stats.done === stats.total ? 1 : 0;
      return acc;
    }, { total: 0, done: 0, completedPlans: 0 });
    const progress = store?.progress || defaultProgress();
    const badges = [
      { id: "start", unlocked: totals.done >= 1 },
      { id: "streak3", unlocked: progress.streak >= 3 || progress.best_streak >= 3 },
      { id: "streak7", unlocked: progress.best_streak >= 7 },
      { id: "xp100", unlocked: progress.xp >= 100 },
      { id: "skills", unlocked: plans.flatMap((plan) => plan.items).filter((item) => item.done && taskTagClass(item.tag) === "skill").length >= 5 },
      { id: "path", unlocked: totals.completedPlans >= 1 }
    ].map((item) => ({ ...BADGE_META[item.id], id: item.id, unlocked: item.unlocked }));
    return {
      totalTasks: totals.total,
      doneTasks: totals.done,
      completedPlans: totals.completedPlans,
      badges,
      unlockedBadges: badges.filter((badge) => badge.unlocked).length
    };
  }

  function phaseGroups(store) {
    const groups = { short: [], mid: [], long: [] };
    (Array.isArray(store?.plans) ? store.plans : []).forEach((plan) => {
      const key = PHASE_ORDER.includes(plan.phase_key) ? plan.phase_key : "short";
      groups[key].push(plan);
    });
    PHASE_ORDER.forEach((key) => {
      groups[key].sort((left, right) => {
        if (left.source !== right.source) return left.source === "report" ? -1 : 1;
        return Date.parse(left.updated_at || "") - Date.parse(right.updated_at || "");
      });
    });
    return groups;
  }

  function phaseAggregate(plans) {
    const tasks = [];
    plans.forEach((plan) => {
      plan.items.forEach((item, index) => {
        tasks.push({
          ...item,
          planId: plan.id,
          planTitle: plan.title,
          source: plan.source,
          role: plan.role,
          order: index
        });
      });
    });
    const done = tasks.filter((task) => task.done).length;
    const total = tasks.length;
    return { tasks, done, total, pct: total ? Math.round((done / total) * 100) : 0 };
  }

  function milestoneNodes(phaseKey, plans) {
    const grouped = new Map();
    plans.forEach((plan) => {
      const label = plan.timeline || plan.title;
      if (!grouped.has(label)) grouped.set(label, []);
      grouped.get(label).push(plan);
    });
    return [...grouped].map(([label, items]) => ({
      label,
      title: items.length > 1 ? `${items.length} 项准备任务` : items[0].title,
      state: items.every((plan) => planStats(plan).pct === 100) ? "completed" : "pending"
    }));
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function setWidth(id, value) {
    const el = document.getElementById(id);
    if (el) el.style.width = value;
  }

  function ensureAchievementPopup() {
    let popup = document.getElementById("lpAchievementPopup");
    if (popup) return popup;
    popup = document.createElement("div");
    popup.id = "lpAchievementPopup";
    popup.className = "lp-achievement-popup";
    popup.innerHTML = `
      <div class="lp-achievement-icon">🏆</div>
      <div class="lp-achievement-copy">
        <h4 id="lpAchievementTitle">任务完成</h4>
        <p id="lpAchievementDesc">+20 XP 已添加到你的经验值</p>
      </div>
    `;
    document.body.appendChild(popup);
    return popup;
  }

  function showAchievement(title, desc) {
    const popup = ensureAchievementPopup();
    setText("lpAchievementTitle", title);
    setText("lpAchievementDesc", desc);
    popup.classList.add("show");
    if (runtime.toastTimer) window.clearTimeout(runtime.toastTimer);
    runtime.toastTimer = window.setTimeout(() => {
      popup.classList.remove("show");
    }, 2200);
  }

  function renderTopStats() {
    const store = runtime.store;
    if (!store) return;
    const progress = store.progress || defaultProgress();
    const stats = computeStats(store);
    setText("lpFusionStatStreak", String(progress.streak));
    setText("lpFusionStatXP", String(progress.xp));
    setText("lpFusionStatDone", String(stats.doneTasks));
    setText("lpFusionStatBadges", String(stats.unlockedBadges));
  }

  function renderWeekStrip() {
    const host = document.getElementById("lpFusionWeekStrip");
    const progress = runtime.store?.progress || defaultProgress();
    if (!host) return;
    const labels = ["一", "二", "三", "四", "五", "六", "日"];
    const today = new Date();
    const start = addDays(today, -((today.getDay() + 6) % 7));
    host.innerHTML = labels.map((label, index) => {
      const date = addDays(start, index);
      const key = dayKey(date);
      const checked = Boolean(progress.active_days?.[key]);
      const isToday = key === dayKey(today);
      return `
        <div class="lp-fusion-week-day">
          <span class="lp-fusion-week-name">${label}</span>
          <span class="lp-fusion-week-dot ${checked ? "is-checked" : ""} ${isToday ? "is-today" : ""}">${checked ? "✓" : label}</span>
        </div>
      `;
    }).join("");
  }

  function renderHeatmap() {
    const host = document.getElementById("lpFusionHeatmap");
    const progress = runtime.store?.progress || defaultProgress();
    if (!host) return;
    const today = new Date();
    const cells = [];
    for (let index = 27; index >= 0; index -= 1) {
      const date = addDays(today, -index);
      const key = dayKey(date);
      const active = Boolean(progress.active_days?.[key]);
      const level = active ? (index < 7 ? "l4" : index < 14 ? "l3" : index < 21 ? "l2" : "l1") : "";
      cells.push(`<div class="lp-fusion-heat-cell ${level}" title="${esc(key)}"></div>`);
    }
    host.innerHTML = cells.join("");
  }

  function renderBadges() {
    const host = document.getElementById("lpFusionBadgeGrid");
    const stats = computeStats(runtime.store);
    if (!host) return;
    host.innerHTML = stats.badges.map((badge) => `
      <article class="lp-fusion-badge ${badge.unlocked ? "is-unlocked" : ""}">
        <span class="lp-fusion-badge-icon">${esc(badge.icon)}</span>
        <strong>${esc(badge.title)}</strong>
        <span>${esc(badge.desc)}</span>
      </article>
    `).join("");
  }

  function renderGrowthPanel() {
    const store = runtime.store;
    if (!store) return;
    const progress = store.progress || defaultProgress();
    const stats = computeStats(store);
    const level = Math.max(1, Math.floor(progress.xp / 100) + 1);
    const xpInLevel = progress.xp % 100;
    setText("lpFusionStreakIcon", progress.streak >= 7 ? "⚡" : progress.streak >= 3 ? "🔥" : "✨");
    setText("lpFusionStreakCount", String(progress.streak));
    setText("lpFusionStreakBest", String(progress.best_streak));
    setText("lpFusionLevel", `Lv.${level}`);
    setText("lpFusionXP", String(xpInLevel));
    setText("lpFusionXPNext", "100");
    setText("lpFusionXpSummary", `累计经验值 ${progress.xp} XP`);
    setText("lpFusionTaskXpSummary", `已完成 ${stats.doneTasks}/${stats.totalTasks} 项任务`);
    setWidth("lpFusionXPFill", `${Math.max(0, Math.min(100, xpInLevel))}%`);

    const checkedToday = progress.last_checkin === dayKey(new Date());
    const btn = document.getElementById("lpFusionCheckinBtn");
    if (btn) {
      btn.disabled = checkedToday;
      btn.classList.toggle("checked", checkedToday);
      btn.innerHTML = checkedToday ? "今日已打卡 <span>✓</span>" : "今日打卡";
    }
    setText("lpFusionCheckinHint", checkedToday
      ? `已完成今日打卡，当前连续 ${progress.streak} 天。`
      : "每天打卡记录学习节奏；任务完成后请核对交付物和验收标准，再手动勾选。");

    renderWeekStrip();
    renderHeatmap();
    renderBadges();
  }

  function renderTaskRow(task) {
    return `
      <label class="lp-stage-task ${task.done ? "is-done" : ""}">
        <input class="lp-stage-task-input" type="checkbox" ${task.done ? "checked" : ""} onchange="togglePlanItem('${esc(task.planId)}','${esc(task.id)}')">
        <span class="lp-stage-task-check"><span>✓</span></span>
        <span class="lp-stage-task-body">
          <span class="lp-stage-task-title">${esc(task.title)}</span>
          <span class="lp-stage-task-meta">
            <span class="lp-stage-task-tag ${esc(taskTagClass(task.tag))}">${esc(task.tag || "技能")}</span>
            <span class="lp-stage-task-source">${esc(sourceLabel(task.source))}</span>
            ${task.planTitle && task.planTitle !== task.title ? `<span class="lp-stage-task-plan">${esc(task.planTitle)}</span>` : ""}
            ${task.deadline ? `<span class="lp-stage-task-deadline">截止 ${esc(task.deadline)}</span>` : ""}
          </span>
          ${task.note ? `<span class="lp-stage-task-note">${esc(task.note)}</span>` : ""}
        </span>
        <span class="lp-stage-task-xp">+${esc(task.xp)} XP</span>
      </label>
    `;
  }

  function renderPhaseSection(phaseKey, plans) {
    const meta = PHASE_META[phaseKey];
    const aggregate = phaseAggregate(plans);
    const milestones = milestoneNodes(phaseKey, plans);
    const title = meta.title;
    const reportPlan = plans.find((p) => p.source === "report");
    const roleHint = reportPlan?.role ? ` · ${reportPlan.role}` : "";
    const subtitle = plans.length
      ? `${formatDateTime(plans[0]?.updated_at).split(" ")[0]} · ${plans.length} 个计划${roleHint}`
      : meta.empty;
    return `
      <section class="lp-stage-section" data-phase="${esc(phaseKey)}">
        <div class="lp-stage-header">
          <div class="lp-stage-header-left">
            <span class="lp-stage-badge ${esc(meta.accent)}">${esc(meta.label)}</span>
            <div>
              <div class="lp-stage-title">${esc(title)}</div>
              <div class="lp-stage-subtitle">${esc(subtitle)}</div>
            </div>
          </div>
          <div class="lp-stage-header-right">
            <span class="lp-stage-progress-text">${aggregate.done}/${aggregate.total} 完成</span>
            <div class="lp-stage-progress-bar">
              <div class="lp-stage-progress-fill ${esc(meta.accent)}" style="width:${aggregate.pct}%"></div>
            </div>
          </div>
        </div>
        ${milestones.length ? `<div class="lp-stage-timeline">
          ${milestones.map((node) => `
            <div class="lp-stage-milestone ${esc(node.state)}">
              <div class="lp-stage-milestone-dot"></div>
              <div class="lp-stage-milestone-label">${esc(node.label)}</div>
              <div class="lp-stage-milestone-date">${esc(node.title)}</div>
            </div>
          `).join("")}
        </div>` : ""}
        <div class="lp-stage-task-list">
          ${aggregate.tasks.length
            ? aggregate.tasks.map((task) => renderTaskRow(task)).join("")
            : `<div class="lp-stage-empty">${esc(meta.empty)}</div>`}
        </div>
      </section>
    `;
  }

  function renderPhaseTabs(filterBar) {
    const groups = phaseGroups(runtime.store);
    filterBar.innerHTML = PHASE_TABS.map((tab) => {
      const isActive = runtime.activePhaseFilter === tab.key;
      // Show task count badge for non-all tabs
      let badge = "";
      if (tab.key !== "all") {
        const agg = phaseAggregate(groups[tab.key] || []);
        badge = agg.total > 0 ? ` <span class="lp-tab-count">${agg.done}/${agg.total}</span>` : "";
      }
      return `<button class="lp-plan-filter-btn${isActive ? " active" : ""}"
                      onclick="setPhaseFilter('${tab.key}')">${esc(tab.label)}${badge}</button>`;
    }).join("");
  }

  function setPhaseFilter(key) {
    runtime.activePhaseFilter = PHASE_TABS.some((t) => t.key === key) ? key : "all";
    renderPlanBoard();
  }

  function renderPlanBoard() {
    const host = document.getElementById("lpFusionPlanList");
    if (!host || !runtime.store) return;
    const groups = phaseGroups(runtime.store);
    const filterBar = document.getElementById("lpFusionFilterBar");
    if (filterBar) renderPhaseTabs(filterBar);
    const detail = document.getElementById("lpFusionDetailView");
    if (detail) detail.classList.add("hidden");

    const filter = runtime.activePhaseFilter;
    const phasesToShow = filter === "all" ? PHASE_ORDER : [filter];
    host.innerHTML = phasesToShow.map((phaseKey) => renderPhaseSection(phaseKey, groups[phaseKey] || [])).join("");
  }

  function renderHeaderMeta() {
    const tracker = runtime.tracker;
    setText("lpFusionReportTitle", "学习路径");
    setText("lpFusionReportSummary", "不做总览横幅，直接按短期、中期、长期三个阶段推进你的计划。");
    setText("lpFusionFocusRole", focusRoleName());
    setText("lpFusionNextFocus", String(tracker?.next_focus || "先做最小可执行动作").trim() || "先做最小可执行动作");
    setText("lpFusionGeneratedAt", formatDateTime(tracker?.generated_at || tracker?.last_synced_at || ""));
    const pill = document.getElementById("lpFusionSyncStatus");
    if (pill) {
      if (tracker) {
        const syncTime = formatDateTime(tracker.last_synced_at || tracker.generated_at || "").split(" ")[0];
        pill.textContent = `已接入报告${syncTime ? " · " + syncTime : ""}`;
        pill.title = "来自职业规划报告 · 点击重新同步";
        pill.classList.add("is-synced");
      } else {
        pill.textContent = "本地计划";
        pill.title = "当前无报告连接，计划由用户手动创建";
        pill.classList.remove("is-synced");
      }
    }
    bindSyncPill();
  }

  function renderAll() {
    if (!runtime.store) return;
    renderHeaderMeta();
    renderTopStats();
    renderGrowthPanel();
    renderPlanBoard();
  }

  function activePhasePlan() {
    const plans = Array.isArray(runtime.store?.plans) ? runtime.store.plans : [];
    return plans.find((plan) => plan.phase_key === "short") || plans[0] || null;
  }

  async function ensureStore(force = false) {
    if (runtime.loading) return runtime.store;
    if (!force && runtime.store) return runtime.store;
    runtime.loading = true;
    try {
      runtime.tracker = await loadTracker();
      const scoped = await readScopedStore();
      const base = scoped ? normalizeStore(scoped) : legacyStore();
      runtime.store = mergeTrackerPlans(base, runtime.tracker);
      await saveStore();
      return runtime.store;
    } finally {
      runtime.loading = false;
    }
  }

  function openComposer() {
    const el = document.getElementById("lpFusionComposer");
    if (el) el.classList.remove("hidden");
  }

  function closeComposer() {
    const el = document.getElementById("lpFusionComposer");
    if (el) el.classList.add("hidden");
    ["lpFusionNewPlanName", "lpFusionNewPlanRole", "lpFusionNewPlanSummary"].forEach((id) => {
      const input = document.getElementById(id);
      if (input) input.value = "";
    });
    const typeInput = document.getElementById("lpFusionNewPlanType");
    if (typeInput) typeInput.value = "short";
  }

  async function createNewPlan() {
    await ensureStore();
    openComposer();
  }

  async function submitCareerPlanDraft() {
    await ensureStore();
    const title = String(document.getElementById("lpFusionNewPlanName")?.value || "").trim();
    if (!title) {
      window.showToast?.("计划名称不能为空", "请先填入计划名称。", "warning", 1800);
      return;
    }
    const phaseKey = inferPhaseKey(document.getElementById("lpFusionNewPlanType")?.value || "short", "short");
    const role = String(document.getElementById("lpFusionNewPlanRole")?.value || "").trim() || focusRoleName();
    const summary = String(document.getElementById("lpFusionNewPlanSummary")?.value || "").trim();
    runtime.store.plans.push(normalizePlan({
      id: uid("manual"),
      title,
      summary,
      phase_key: phaseKey,
      source: "manual",
      role,
      timeline: `${phaseLabel(phaseKey)}阶段 · 手动计划`,
      items: [{ id: uid("task"), title: "添加第一条行动项", tag: "实践", xp: 16 }]
    }));
    closeComposer();
    await saveStore();
    renderAll();
  }

  async function addPlanItem() {
    await ensureStore();
    const input = document.getElementById("lpFusionNewItemInput");
    const title = String(input?.value || "").trim();
    if (!title) return;
    const plan = activePhasePlan();
    if (!plan) return;
    plan.items.push(normalizeTask({ id: uid("task"), title, tag: "技能", xp: 16 }, plan.items.length));
    if (input) input.value = "";
    await saveStore();
    renderAll();
  }

  async function syncTaskToTracker(taskId, status) {
    try {
      // Only sync tasks that originated directly from the tracker (skip derived IDs)
      const isDerived = !taskId || taskId.includes("_objective") || taskId.includes("_focus_") || taskId.includes("_signal_");
      if (isDerived) return;
      const isCheckpoint = taskId.startsWith("checkpoint_");
      await fetch("/api/career-report/tracker/item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          item_type: isCheckpoint ? "checkpoint" : "plan",
          item_id: isCheckpoint ? taskId.slice("checkpoint_".length) : taskId,
          status
        })
      });
    } catch (_) {
      // Non-critical — fail silently
    }
  }

  async function togglePlanItem(planId, itemId) {
    await ensureStore();
    const plan = runtime.store.plans.find((entry) => entry.id === planId);
    const task = plan?.items.find((entry) => entry.id === itemId);
    if (!plan || !task) return;
    const nextDone = !task.done;
    task.done = nextDone;
    if (nextDone) {
      runtime.store.progress.xp += Math.max(0, Number(task.xp || 0));
      showAchievement("任务完成", `+${Math.max(0, Number(task.xp || 0))} XP 已添加到你的经验值！`);
    } else {
      runtime.store.progress.xp = Math.max(0, runtime.store.progress.xp - Math.max(0, Number(task.xp || 0)));
    }
    await saveStore();
    // Sync completion status back to career report tracker for report-sourced tasks
    if (plan.source === "report") {
      void syncTaskToTracker(itemId, nextDone ? "done" : "pending");
    }
    renderAll();
  }

  async function doCheckin() {
    await ensureStore();
    const progress = runtime.store.progress;
    const today = dayKey(new Date());
    if (progress.last_checkin === today) {
      showAchievement("今日已打卡", "今天的打卡奖励已经领取过了。");
      renderGrowthPanel();
      return;
    }
    const yesterday = dayKey(addDays(new Date(), -1));
    progress.streak = progress.last_checkin === yesterday ? progress.streak + 1 : 1;
    progress.best_streak = Math.max(progress.best_streak, progress.streak);
    progress.xp += progress.streak % 7 === 0 ? 50 : 10;
    progress.last_checkin = today;
    progress.active_days[today] = true;
    await saveStore();
    renderAll();
    showAchievement("打卡完成", `连续 ${progress.streak} 天，成长值已更新。`);
  }

  async function showPlanList() {
    await ensureStore();
    renderAll();
  }

  async function showPlanDetail() {
    await ensureStore();
    renderAll();
  }

  async function loadCareerPlans() {
    await ensureStore(true);
    renderAll();
  }

  async function refreshFromReport() {
    runtime.store = null;
    runtime.tracker = null;
    const pill = document.getElementById("lpFusionSyncStatus");
    if (pill) { pill.textContent = "同步中…"; pill.style.opacity = "0.6"; }
    await loadCareerPlans();
    if (pill) { pill.style.opacity = ""; }
    showAchievement("计划已刷新", "已从最新职业报告重新同步计划。");
  }

  function bindSyncPill() {
    const pill = document.getElementById("lpFusionSyncStatus");
    if (!pill || pill.dataset.syncBound) return;
    pill.dataset.syncBound = "1";
    pill.style.cursor = "pointer";
    pill.title = "点击重新从报告同步";
    pill.addEventListener("click", () => void refreshFromReport());
  }

  function bindGlobalExports() {
    window.createNewPlan = createNewPlan;
    window.cancelCareerPlanDraft = closeComposer;
    window.submitCareerPlanDraft = submitCareerPlanDraft;
    window.addPlanItem = addPlanItem;
    window.togglePlanItem = togglePlanItem;
    window.doCheckin = doCheckin;
    window.showPlanList = showPlanList;
    window.showPlanDetail = showPlanDetail;
    window._loadCareerPlans = loadCareerPlans;
    window._updateLifeProgress = renderGrowthPanel;
    window._updatePlanStats = renderTopStats;
    window.refreshPlanFromReport = refreshFromReport;
    window.setPhaseFilter = setPhaseFilter;
  }

  function initialize() {
    if (runtime.initialized) return;
    runtime.initialized = true;
    ensureAchievementPopup();
    void loadCareerPlans();
    bindSyncPill();
    window.addEventListener("app:auth-changed", () => {
      runtime.store = null;
      runtime.tracker = null;
      void loadCareerPlans();
    });
    // Auto-refresh when a new career report is generated
    window.addEventListener("career-report:updated", () => {
      runtime.store = null;
      runtime.tracker = null;
      void loadCareerPlans();
    });
  }

  bindGlobalExports();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
