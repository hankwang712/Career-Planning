(function () {
  const TYT_ASSET_BASE = "/static/trueyouteller";

  const COVER_MAP = {
    friends: `${TYT_ASSET_BASE}/miniGames/friends.png`,
    insideout: `${TYT_ASSET_BASE}/miniGames/insideOut.png`,
    deep: `${TYT_ASSET_BASE}/brand/trueyouteller.png`,
  };

  const META = {
    deep: {
      pageTitle: "深层 MBTI 测试作答页",
      sectionTitle: "深层 MBTI · 52 题",
      sectionHint: "完成 52 题后将进入完整结果页，并保留本次记录用于前后对比。",
      heroTitle: "深层性格探索",
      heroDesc: "五档量表题，更细腻地观察你的四维偏好与变化趋势。",
    },
    friends: {
      pageTitle: "老友记角色测试作答页",
      sectionTitle: "老友记角色 · 10 题",
      sectionHint: "完成 10 题后将进入完整结果页，展示角色分析和得分分布。",
      heroTitle: "你是哪个老友记角色？",
      heroDesc: "通过情景选择题，看看你最像 Central Perk 的哪位常客。",
    },
    insideout: {
      pageTitle: "情绪主导测试作答页",
      sectionTitle: "情绪主导 · 14 题",
      sectionHint: "完成 14 题后将进入完整结果页，展示主导情绪与特质分布。",
      heroTitle: "你是哪种情绪？",
      heroDesc: "通过情绪选择题识别你当前主导的情感风格。",
    },
  };

  const state = {
    user: null,
    testType: "deep",
    questions: [],
    answers: {},
    idx: 0,
    submitting: false,
    hasResult: false,
  };

  function core() {
    return window.__DeepTestHubCore__ || null;
  }

  function resolveApiUrl(path) {
    const rawBase = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
    const target = String(path || "").trim();
    if (!target) return target;
    if (/^https?:\/\//i.test(target)) return target;
    if (!rawBase) return target;
    return target.startsWith("/") ? `${rawBase}${target}` : `${rawBase}/${target}`;
  }

  async function requestJson(path, options) {
    const response = await fetch(resolveApiUrl(path), {
      credentials: "include",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options && options.headers ? options.headers : {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(String(data.message || "请求失败"));
    return data;
  }

  function sanitizeType(raw) {
    const c = core();
    if (!c || typeof c.sanitizeTestType !== "function") return "deep";
    return c.sanitizeTestType(raw);
  }

  function parseTypeFromUrl() {
    try {
      const url = new URL(window.location.href);
      return sanitizeType(url.searchParams.get("test"));
    } catch (_) {
      return "deep";
    }
  }

  function setTypeToUrl(type, replaceOnly) {
    const safe = sanitizeType(type);
    const url = new URL(window.location.href);
    url.searchParams.set("test", safe);
    if (replaceOnly) window.history.replaceState({}, "", url.toString());
    else window.history.pushState({}, "", url.toString());
  }

  function totalCount() {
    return Array.isArray(state.questions) ? state.questions.length : 0;
  }

  function answeredCount() {
    return Object.keys(state.answers || {}).length;
  }

  function currentQuestion() {
    if (!Array.isArray(state.questions) || !state.questions.length) return null;
    return state.questions[state.idx] || null;
  }

  function coverForType(type) {
    const safe = sanitizeType(type);
    return COVER_MAP[safe] || COVER_MAP.deep;
  }

  function updateTopUser(user) {
    const label = document.getElementById("currentUserLabel");
    const avatar = document.getElementById("currentUserAvatar");
    const display = String(user?.display_name || user?.displayName || user?.username || "未登录");
    if (label) label.textContent = display;
    if (avatar) avatar.textContent = display.slice(0, 1).toUpperCase();
  }

  function updateActiveNav() {
    document.querySelectorAll(".tr-nav-link").forEach((btn) => {
      const t = sanitizeType(btn.dataset.test || "");
      btn.classList.toggle("active", t === state.testType);
    });
  }

  function updateHeader() {
    const meta = META[state.testType] || META.deep;
    const total = totalCount();

    const titleEl = document.getElementById("tsPageTitle");
    const sectionTitleEl = document.getElementById("tsSectionTitle");
    const sectionHintEl = document.getElementById("tsSectionHint");
    const heroTitleEl = document.getElementById("tsHeroTitle");
    const heroDescEl = document.getElementById("tsHeroDesc");
    const coverEl = document.getElementById("tsCoverImage");
    const metaLineEl = document.getElementById("tsMetaLine");

    if (titleEl) titleEl.textContent = meta.pageTitle;
    if (sectionTitleEl) sectionTitleEl.textContent = meta.sectionTitle;
    if (sectionHintEl) sectionHintEl.textContent = meta.sectionHint;
    if (heroTitleEl) heroTitleEl.textContent = meta.heroTitle;
    if (heroDescEl) heroDescEl.textContent = meta.heroDesc;
    if (coverEl) coverEl.src = coverForType(state.testType);
    if (metaLineEl) metaLineEl.textContent = `总题数：${total} 题 ｜ 来源：trueyouteller 题库与素材`;

    document.title = `${meta.pageTitle} | 职业规划智能体`;
  }

  function updateProgress() {
    const total = Math.max(1, totalCount());
    const answered = answeredCount();
    const idx = Math.min(state.idx + 1, total);
    const progress = Math.round((answered / total) * 100);

    const progressTextEl = document.getElementById("tsProgressText");
    const answeredTextEl = document.getElementById("tsAnsweredText");
    const fillEl = document.getElementById("tsProgressFill");

    if (progressTextEl) progressTextEl.textContent = `进度 ${idx} / ${total}`;
    if (answeredTextEl) answeredTextEl.textContent = `已作答 ${answered} / ${total}`;
    if (fillEl) fillEl.style.width = `${progress}%`;
  }

  function renderOptions(question) {
    const root = document.getElementById("tsOptions");
    if (!root) return;
    root.innerHTML = "";
    root.className = "ts-options";
    if (!question) return;

    const qId = Number(question.id);
    const selectedValue = state.answers[qId];
    const isDeep = state.testType === "deep";
    const options = isDeep
      ? (core()?.getLikertAnswers?.() || [])
      : (Array.isArray(question.opts) ? question.opts : []);

    root.classList.add(isDeep ? "ts-options-likert" : "ts-options-grid");

    options.forEach((item) => {
      const value = isDeep ? Number(item.value) : String(item.v);
      const label = isDeep ? String(item.label || "") : String(item.t || "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ts-option";
      if (String(selectedValue) === String(value)) btn.classList.add("selected");
      btn.textContent = label;
      btn.addEventListener("click", () => {
        state.answers[qId] = value;
        renderQuestion();
        if (state.idx < totalCount() - 1) {
          window.setTimeout(() => {
            state.idx += 1;
            renderQuestion();
          }, 120);
        }
      });
      root.appendChild(btn);
    });
  }

  function renderQuestion() {
    const q = currentQuestion();
    const total = totalCount();
    const answered = answeredCount();
    const noEl = document.getElementById("tsQuestionNo");
    const textEl = document.getElementById("tsQuestionText");
    const hintEl = document.getElementById("tsHintLine");
    const prevBtn = document.getElementById("tsPrevBtn");
    const nextBtn = document.getElementById("tsNextBtn");
    const submitBtn = document.getElementById("tsSubmitBtn");
    const viewResultBtn = document.getElementById("tsViewResultBtn");

    if (!q || !total) {
      if (noEl) noEl.textContent = "题目加载失败";
      if (textEl) textEl.textContent = "当前测试题库为空。";
      if (hintEl) hintEl.textContent = "请返回主界面后重试。";
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (noEl) noEl.textContent = `第 ${state.idx + 1} 题 / 共 ${total} 题`;
    if (textEl) textEl.textContent = String(q.text || "");
    if (hintEl) {
      hintEl.textContent = answered >= total
        ? "已完成全部作答，可点击“完成并查看完整结果”。"
        : "点击选项后会自动进入下一题，也可手动点击“下一题”。";
    }

    const answeredCurrent = state.answers[Number(q.id)] !== undefined;
    if (prevBtn) prevBtn.disabled = state.idx <= 0 || state.submitting;
    if (nextBtn) nextBtn.disabled = state.idx >= total - 1 || !answeredCurrent || state.submitting;
    if (submitBtn) {
      submitBtn.disabled = answered < total || state.submitting;
      submitBtn.textContent = state.submitting ? "正在生成结果..." : "完成并查看完整结果";
    }
    if (viewResultBtn) {
      viewResultBtn.disabled = !state.hasResult;
    }

    updateProgress();
    renderOptions(q);
  }

  function initQuestions(keepUrl) {
    const c = core();
    state.questions = (c?.getQuestionsByType?.(state.testType) || []);
    state.answers = {};
    state.idx = 0;
    state.hasResult = Boolean(c?.getStoredResultByType?.(state.testType));

    if (!keepUrl) setTypeToUrl(state.testType, false);
    else setTypeToUrl(state.testType, true);

    updateActiveNav();
    updateHeader();
    renderQuestion();
  }

  function toMainProfile() {
    if (typeof window.goBackToLastInterface === "function") {
      window.goBackToLastInterface("/main.html#profile");
      return;
    }
    window.location.href = "/main.html#profile";
  }

  function toResultPage() {
    const c = core();
    if (!c?.getResultPageUrl) return;
    window.location.href = c.getResultPageUrl(state.testType);
  }

  function goUserCenter() {
    window.location.href = "/user-center.html#report-workspace";
  }

  async function submitTest() {
    if (state.submitting) return;
    const c = core();
    if (!c) return;
    const total = totalCount();
    if (!total || answeredCount() < total) {
      window.alert("请先完成全部题目。");
      return;
    }
    state.submitting = true;
    renderQuestion();
    try {
      const result = c.computeResultByType(state.testType, state.answers);
      if (!result) throw new Error("结果计算失败");
      if (state.testType === "deep" && !result.completed) {
        throw new Error("深层 MBTI 作答未完成");
      }
      const saved = c.saveResultByType(state.testType, result, {
        completedAt: Date.now(),
        answers: { ...state.answers },
        aiText: "",
      });
      if (!saved) throw new Error("结果保存失败");
      toResultPage();
    } catch (err) {
      window.alert(`提交失败：${String(err?.message || err)}`);
    } finally {
      state.submitting = false;
      renderQuestion();
    }
  }

  function switchType(nextType, fromPopState) {
    const safe = sanitizeType(nextType);
    if (safe === state.testType && !fromPopState) return;
    if (!fromPopState && answeredCount() > 0) {
      const ok = window.confirm("切换测试会丢失当前页未提交作答，是否继续？");
      if (!ok) return;
    }
    state.testType = safe;
    initQuestions(Boolean(fromPopState));
  }

  function bindEvents() {
    document.querySelectorAll(".tr-nav-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchType(btn.dataset.test || "deep", false);
      });
    });

    const prevBtn = document.getElementById("tsPrevBtn");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (state.idx > 0) {
          state.idx -= 1;
          renderQuestion();
        }
      });
    }

    const nextBtn = document.getElementById("tsNextBtn");
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        const q = currentQuestion();
        if (!q) return;
        if (state.answers[Number(q.id)] === undefined) return;
        if (state.idx < totalCount() - 1) {
          state.idx += 1;
          renderQuestion();
        }
      });
    }

    const submitBtn = document.getElementById("tsSubmitBtn");
    if (submitBtn) submitBtn.addEventListener("click", submitTest);

    const restartBtn = document.getElementById("tsRestartBtn");
    if (restartBtn) {
      restartBtn.addEventListener("click", () => {
        const ok = window.confirm("确定清空当前作答并从第一题重新开始吗？");
        if (!ok) return;
        state.answers = {};
        state.idx = 0;
        renderQuestion();
      });
    }

    const viewResultBtn = document.getElementById("tsViewResultBtn");
    if (viewResultBtn) {
      viewResultBtn.addEventListener("click", () => {
        if (state.hasResult) toResultPage();
      });
    }

    const backBtn = document.getElementById("tsBackBtn");
    if (backBtn) backBtn.addEventListener("click", toMainProfile);

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        try {
          await requestJson("/api/auth/logout", { method: "POST" });
        } catch (_) {}
        window.location.href = "/main.html";
      });
    }

    const avatarBtn = document.getElementById("tsAvatarBtn");
    if (avatarBtn) avatarBtn.addEventListener("click", goUserCenter);

    window.addEventListener("popstate", () => {
      switchType(parseTypeFromUrl(), true);
    });
  }

  async function initAuth() {
    const payload = await requestJson("/api/auth/status");
    if (!payload || !payload.authenticated || !payload.user) {
      window.location.href = "/main.html";
      return false;
    }
    state.user = payload.user;
    updateTopUser(payload.user);
    return true;
  }

  async function init() {
    bindEvents();
    const c = core();
    if (!c) {
      const textEl = document.getElementById("tsQuestionText");
      if (textEl) textEl.textContent = "测试引擎未加载，请刷新页面重试。";
      return;
    }
    const ok = await initAuth().catch(() => false);
    if (!ok) return;
    // Expose authenticated user so deep-test-hub uses the correct username for localStorage keys
    window.getCurrentUser = () => state.user;
    window.dispatchEvent(new CustomEvent("app:auth-changed", { detail: state.user }));
    state.testType = parseTypeFromUrl();
    initQuestions(true);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
