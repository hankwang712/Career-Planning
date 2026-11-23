(function () {
  const COVER_MAP = {
    friends: "/static/brand/assessments/friends.svg",
    insideout: "/static/brand/assessments/insideout.svg",
    deep: "/static/brand/assessments/deep.jpg",
    sbti: "/static/brand/assessments/sbti.svg",
  };
  const PET_GIFS = {
    idle: "/static/pet/clawd-mini-idle.gif",
    happy: "/static/pet/clawd-mini-happy.gif",
    cheer: "/static/pet/clawd-happy.gif",
    alert: "/static/pet/clawd-mini-alert.gif",
  };
  const PET_LINES = {
    answer: ["选得很干脆 ✨", "节奏很棒 💪", "又推进一题！", "越来越了解自己了 🌟", "继续保持 👍"],
    q25: "已完成 25%，进入状态啦 🌱",
    q50: "过半啦！50% 达成 ⚡",
    q75: "已完成 75%，马上揭晓画像 🔥",
    q90: "最后冲刺，胜利在望 🎯",
    poke: ["我在陪你答题呢 😊", "按数字键 1–5 选得更快哦 ⌨️", "凭第一直觉选最准 ✨", "加油，很快就能看结果啦 🎉"],
  };
  let streakCount = 0;
  let reachedMilestones = new Set();
  let petTimer = null;

  function triggerPet(mood, text, ms = 2200) {
    const img = document.getElementById("tsPetImg");
    const bubble = document.getElementById("tsPetBubble");
    if (bubble && text) bubble.textContent = text;
    if (img && PET_GIFS[mood]) {
      img.src = PET_GIFS[mood];
      window.clearTimeout(petTimer);
      petTimer = window.setTimeout(() => { img.src = PET_GIFS.idle; }, ms);
    }
  }

  function updateStreakAndMilestones() {
    const badge = document.getElementById("tsStreakBadge");
    if (badge) {
      badge.hidden = streakCount < 3;
      badge.textContent = `连续 ${streakCount} 题 🔥`;
    }
    const total = Math.max(1, totalCount());
    const pct = Math.round((answeredCount() / total) * 100);
    const toast = document.getElementById("tsMilestoneToast");
    for (const [mark, key] of [[90, "q90"], [75, "q75"], [50, "q50"], [25, "q25"]]) {
      if (pct >= mark && !reachedMilestones.has(mark)) {
        reachedMilestones.add(mark);
        const msg = PET_LINES[key];
        if (toast) {
          toast.textContent = msg;
          toast.classList.add("is-celebrate");
          window.setTimeout(() => toast.classList.remove("is-celebrate"), 2600);
        }
        triggerPet("cheer", msg, 3200);
        return;
      }
    }
    if (streakCount > 0 && streakCount % 5 === 0) {
      const line = PET_LINES.answer[Math.floor(Math.random() * PET_LINES.answer.length)];
      triggerPet("happy", line, 1800);
    }
  }

  function renderQuestionMap() {
    const map = document.getElementById("tsQuestionMap");
    if (!map || map.hidden) return;
    const list = visibleQuestions();
    map.replaceChildren(...list.map((item, i) => {
      const key = state.testType === "sbti" ? String(item.id || "") : Number(item.id);
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ts-map-cell";
      if (state.answers[key] !== undefined) btn.classList.add("is-done");
      if (i === state.idx) btn.classList.add("is-current");
      btn.textContent = String(i + 1);
      btn.addEventListener("click", () => {
        cancelAdvance();
        state.idx = i;
        saveDraft();
        renderQuestion();
      });
      return btn;
    }));
  }

  const META = {
    deep: {
      pageTitle: "深层 MBTI 测试作答页",
      sectionTitle: "深层 MBTI · 52 题",
      sectionHint: "完成 52 题后将进入完整结果页，展示四维分布和人格解析。",
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
    sbti: {
      pageTitle: "SBTI 人格扩展作答页",
      sectionTitle: "SBTI 人格扩展 · 30 题 + 补充题",
      sectionHint: "完成主问题后将进入完整结果页，展示人格代号、匹配度与 15 维画像反馈。",
      heroTitle: "SBTI 人格扩展",
      heroDesc: "完整题库与完整匹配逻辑已并入扩展测试中心，点击选项会自动跳到下一题。",
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
  let advanceTimer = null;
  const autoAdvanceEnabled = () => document.getElementById("tsAutoAdvance")?.checked !== false;
  function cancelAdvance() { window.clearTimeout(advanceTimer); advanceTimer = null; }
  function draftKey() { return `career_assessment_draft_v1_${state.user?.username || "guest"}_${state.testType}`; }
  function saveDraft() {
    if (!state.user) return;
    try { localStorage.setItem(draftKey(), JSON.stringify({ answers: state.answers, index: state.idx })); } catch (_) {}
  }

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

  function visibleQuestions() {
    if (!Array.isArray(state.questions) || !state.questions.length) return [];
    if (state.testType !== "sbti") return state.questions;
    const list = [...state.questions];
    const specialIndex = list.findIndex((q) => String(q?.id || "") === "drink_gate_q1");
    if (specialIndex !== -1 && Number(state.answers.drink_gate_q1) === 3) {
      const hubCore = core();
      const conditional = hubCore?.getSbtiConditionalQuestion?.();
      if (conditional) list.splice(specialIndex + 1, 0, conditional);
    }
    return list;
  }

  function totalCount() {
    return visibleQuestions().length;
  }

  function answeredCount() {
    const list = visibleQuestions();
    return list.reduce((count, item) => {
      const key = state.testType === "sbti" ? String(item.id || "") : Number(item.id);
      return state.answers[key] !== undefined ? count + 1 : count;
    }, 0);
  }

  function currentQuestion() {
    const list = visibleQuestions();
    if (!list.length) return null;
    const safeIdx = Math.max(0, Math.min(state.idx, list.length - 1));
    state.idx = safeIdx;
    return list[safeIdx] || null;
  }

  function coverForType(type) {
    const safe = sanitizeType(type);
    return COVER_MAP[safe] || COVER_MAP.deep;
  }

  function updateTopUser(user) {
    const label = document.getElementById("currentUserLabel");
    const avatar = document.getElementById("currentUserAvatar");
    const display = String(user?.display_name || user?.displayName || user?.username || "个人工作区");
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
    if (metaLineEl) {
      metaLineEl.textContent = `${total} 道题 · 进度自动保存`;
    }

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
    fillEl?.parentElement?.setAttribute("aria-valuenow", String(progress));
  }

  function renderOptions(question) {
    const root = document.getElementById("tsOptions");
    if (!root) return;
    root.innerHTML = "";
    root.className = "ts-options";
    if (!question) return;

    const qId = state.testType === "sbti" ? String(question.id || "") : Number(question.id);
    const selectedValue = state.answers[qId];
    const isDeep = state.testType === "deep";
    const isSbti = state.testType === "sbti";
    const options = isDeep
      ? (core()?.getLikertAnswers?.() || [])
      : isSbti
        ? (Array.isArray(question.options) ? question.options : [])
        : (Array.isArray(question.opts) ? question.opts : []);

    root.classList.add(isDeep ? "ts-options-likert" : "ts-options-grid");

    options.forEach((item, idx) => {
      const value = isDeep ? Number(item.value) : isSbti ? (idx + 1) : String(item.v);
      const label = isDeep ? String(item.label || "") : isSbti ? String(item || "") : String(item.t || "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ts-option";
      if (String(selectedValue) === String(value)) btn.classList.add("selected");
      const marker = document.createElement("span");
      marker.className = "ts-option-marker";
      marker.textContent = isDeep ? String(idx + 1) : String.fromCharCode(65 + idx);
      marker.setAttribute("aria-hidden", "true");
      const copy = document.createElement("span");
      copy.textContent = label;
      btn.append(marker, copy);
      btn.setAttribute("aria-pressed", String(String(selectedValue) === String(value)));
      btn.addEventListener("click", () => {
        if (advanceTimer || state.submitting) return;
        const wasUnanswered = state.answers[qId] === undefined;
        state.answers[qId] = value;
        if (isSbti && qId === "drink_gate_q1" && Number(value) !== 3) {
          delete state.answers.drink_gate_q2;
        }
        if (wasUnanswered) {
          streakCount += 1;
          updateStreakAndMilestones();
        }
        renderQuestion();
        saveDraft();
        if (!autoAdvanceEnabled()) return;
        const total = totalCount();
        if (state.idx < total - 1) {
          advanceTimer = window.setTimeout(() => {
            advanceTimer = null;
            state.idx += 1;
            saveDraft();
            renderQuestion();
          }, 220);
        } else {
          advanceTimer = window.setTimeout(() => {
            advanceTimer = null;
            if (answeredCount() >= totalCount() && !state.submitting) {
              submitTest();
            }
          }, 220);
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
        ? state.submitting
          ? "正在生成结果并跳转完整结果页…"
          : "已完成全部作答，可以查看完整结果。"
        : autoAdvanceEnabled() ? "选中后自动进入下一题，完成全部题目后生成结果。" : "选择最接近自己的答案，再点击下一题。";
    }

    const questionKey = state.testType === "sbti" ? String(q.id || "") : Number(q.id);
    const answeredCurrent = state.answers[questionKey] !== undefined;
    if (prevBtn) prevBtn.disabled = state.idx <= 0 || state.submitting;
    if (nextBtn) {
      nextBtn.disabled = state.idx >= total - 1 || !answeredCurrent || state.submitting;
      nextBtn.hidden = answered >= total;
    }
    if (submitBtn) {
      submitBtn.hidden = answered < total;
      submitBtn.disabled = answered < total || state.submitting;
      submitBtn.textContent = state.submitting ? "正在生成结果..." : "查看测评结果 →";
    }
    if (viewResultBtn) {
      viewResultBtn.disabled = !state.hasResult;
      viewResultBtn.hidden = !state.hasResult;
    }

    const card = document.querySelector(".ts-question-card");
    if (card) {
      card.classList.remove("ts-card-enter");
      void card.offsetWidth;
      card.classList.add("ts-card-enter");
    }
    updateProgress();
    renderOptions(q);
    renderQuestionMap();
  }

  function initQuestions(keepUrl) {
    cancelAdvance();
    const c = core();
    state.questions = (c?.getQuestionsByType?.(state.testType) || []);
    state.answers = {};
    state.idx = 0;
    try {
      const saved = JSON.parse(localStorage.getItem(draftKey()) || "null");
      if (saved && saved.answers && typeof saved.answers === "object" && !Array.isArray(saved.answers)) {
        const validIds = new Set(state.questions.map(q => String(q.id)));
        state.answers = Object.fromEntries(Object.entries(saved.answers).filter(([key]) => validIds.has(key)));
        state.idx = Math.max(0, Math.min(Math.trunc(Number(saved.index) || 0), Math.max(0, totalCount() - 1)));
      }
    } catch (_) {}
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
    window.location.assign("/main.html#profile");
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
      if (state.testType === "sbti" && !result.code) {
        throw new Error("SBTI 结果生成失败");
      }
      const saved = c.saveResultByType(state.testType, result, {
        completedAt: Date.now(),
        answers: { ...state.answers },
        aiText: "",
      });
      if (!saved) throw new Error("结果保存失败");
      try { localStorage.removeItem(draftKey()); } catch (_) {}
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
    cancelAdvance();
    saveDraft();
    state.testType = safe;
    initQuestions(Boolean(fromPopState));
  }

  function bindEvents() {
    document.getElementById("tsAutoAdvance")?.addEventListener("change", () => { cancelAdvance(); renderQuestion(); });
    document.getElementById("tsMapToggle")?.addEventListener("click", (e) => {
      const map = document.getElementById("tsQuestionMap");
      if (!map) return;
      map.hidden = !map.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!map.hidden));
      if (!map.hidden) renderQuestionMap();
    });
    document.getElementById("tsPetCard")?.addEventListener("click", () => {
      const line = PET_LINES.poke[Math.floor(Math.random() * PET_LINES.poke.length)];
      triggerPet("happy", line, 2200);
    });
    document.addEventListener("keydown", event => {
      if (event.ctrlKey || event.metaKey || event.altKey || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
      const options = document.querySelectorAll("#tsOptions button");
      if (/^[1-9]$/.test(event.key) && options[Number(event.key) - 1]) { event.preventDefault(); options[Number(event.key) - 1].click(); return; }
      const letterIdx = "abcd".indexOf(event.key.toLowerCase());
      if (letterIdx >= 0 && options[letterIdx]) { event.preventDefault(); options[letterIdx].click(); return; }
      if (event.key === "ArrowLeft") { document.getElementById("tsPrevBtn")?.click(); }
      else if (event.key === "ArrowRight") { document.getElementById("tsNextBtn")?.click(); }
    });
    document.querySelectorAll(".tr-nav-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchType(btn.dataset.test || "deep", false);
      });
    });

    const prevBtn = document.getElementById("tsPrevBtn");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (state.idx > 0) {
          cancelAdvance();
          state.idx -= 1;
          saveDraft();
          renderQuestion();
        }
      });
    }

    const nextBtn = document.getElementById("tsNextBtn");
      if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        const q = currentQuestion();
        if (!q) return;
        const key = state.testType === "sbti" ? String(q.id || "") : Number(q.id);
        if (state.answers[key] === undefined) return;
        if (state.idx < totalCount() - 1) {
          cancelAdvance();
          state.idx += 1;
          saveDraft();
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
        cancelAdvance();
        state.answers = {};
        state.idx = 0;
        saveDraft();
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

    const avatarBtn = document.getElementById("tsAvatarBtn");
    if (avatarBtn) avatarBtn.addEventListener("click", goUserCenter);

    window.addEventListener("popstate", () => {
      switchType(parseTypeFromUrl(), true);
    });
  }

  async function initWorkspace() {
    const payload = await requestJson("/api/bootstrap");
    if (!payload || !payload.authenticated || !payload.user) {
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
    const ok = await initWorkspace().catch(() => false);
    if (!ok) return;
    // Expose authenticated user so deep-test-hub uses the correct username for localStorage keys
    window.getCurrentUser = () => state.user;
    window.dispatchEvent(new CustomEvent("app:auth-changed", { detail: state.user }));
    state.testType = parseTypeFromUrl();
    initQuestions(true);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
