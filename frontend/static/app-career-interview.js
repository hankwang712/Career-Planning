// 职业访谈：维度进度、语音输入、对话与结果
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function createCareerInterviewDimensionProgress() {
  return CAREER_INTERVIEW_DIMENSION_PLAN.map((item) => ({
    name: item.name,
    target: item.target,
    answered: 0,
    turn_count: 0,
    effective_answered: 0,
    coverage: null,
    specificity: null,
    confidence: null,
    consistency: null,
    evidence_count: null,
    saturated: false,
    missing_slots: []
  }));
}

function scoreCareerAnswerQuality(text) {
  const raw = String(text || "").trim();
  if (raw.length < 8) {
    return {
      effective: false,
      reminder: "可以再具体一点：例如最近一次你投入较多的任务、场景或选择依据（不必很长，但要能指向真实经历）。"
    };
  }
  const weakHead = /^(不知道|都行|随便|没想好|没想过|差不多|看情况|还好|一般|无所谓|不太清楚|没区别|都可以)/;
  if (weakHead.test(raw) && raw.length < 36) {
    return {
      effective: false,
      reminder: "没关系，我们换个更小的切口：最近一次让你印象最深的学习、项目或合作经历是什么？用一两句话即可。"
    };
  }
  if (raw.length < 14 && !/[，。！？；、]/.test(raw)) {
    return {
      effective: false,
      reminder: "试着多写半句：当时的情境、你具体做了什么、以及你更看重结果还是过程？"
    };
  }
  return { effective: true };
}

function bumpCareerDimensionTurn(dimName) {
  const row = getCareerDimensionProgressByName(dimName);
  if (!row) return;
  row.turn_count = Number(row.turn_count || 0) + 1;
}

function mergeDimensionMetricsFromResult(result) {
  const dm = result?.dimension_metrics;
  if (!dm || typeof dm !== "object") return;
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }
  careerInterviewState.dimensionProgress.forEach((item) => {
    const block = dm[item.name];
    if (!block || typeof block !== "object") return;
    const n = (x) => (x == null || Number.isNaN(Number(x)) ? null : Number(x));
    item.coverage = n(block.coverage);
    item.specificity = n(block.specificity);
    item.confidence = n(block.confidence);
    item.consistency = n(block.consistency);
    item.evidence_count = block.evidence_count != null ? Number(block.evidence_count) : item.evidence_count;
    item.missing_slots = Array.isArray(block.missing_slots) ? block.missing_slots.filter(Boolean).slice(0, 6) : item.missing_slots;
    if (block.saturated) {
      item.saturated = true;
      const t = Number(item.target || 0);
      item.answered = Math.max(Number(item.answered || 0), t);
      item.effective_answered = Math.max(Number(item.effective_answered || 0), t);
    }
  });
}

function normalizeCareerDimensionName(name) {
  const text = String(name || "").trim();
  if (!text) return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  const exact = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === text);
  if (exact) return exact.name;
  const fuzzy = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => text.includes(item.name) || item.name.includes(text));
  return fuzzy ? fuzzy.name : CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
}

function getCareerDimensionProgressByName(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }
  return careerInterviewState.dimensionProgress.find((item) => item.name === normalizedName) || null;
}

function getCareerInterviewProgressPercent() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return 0;
  }
  const total = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Number(item.target || 0), 0);
  const answered = careerInterviewState.dimensionProgress.reduce((sum, item) => sum + Math.min(Number(item.target || 0), Number(item.answered || 0)), 0);
  if (!total) return 0;
  return Math.round(answered / total * 100);
}

function getNextPendingCareerDimensionName() {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    return CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  }
  const nextItem = careerInterviewState.dimensionProgress.find((item) => {
    if (item.saturated) return false;
    return Number(item.answered || 0) < Number(item.target || 0);
  });
  return nextItem ? nextItem.name : null;
}

function getCareerDimensionPrompt(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  const plan = CAREER_INTERVIEW_DIMENSION_PLAN.find((item) => item.name === normalizedName) || CAREER_INTERVIEW_DIMENSION_PLAN[0];
  const progress = getCareerDimensionProgressByName(normalizedName);
  const promptIndex = Math.min(Number(progress?.answered || 0), plan.prompts.length - 1);
  return plan.prompts[promptIndex];
}

function getCareerInterviewGuideConfig(name) {
  const normalizedName = normalizeCareerDimensionName(name);
  return CAREER_INTERVIEW_GUIDE_LIBRARY[normalizedName] || CAREER_INTERVIEW_GUIDE_LIBRARY["职业兴趣"];
}

function getCurrentCareerInterviewQuestion() {
  if (careerInterviewState.isComplete) {
    return "访谈已完成。你仍然可以继续补充新的经历，再点击“发送并继续”让系统更新理解。";
  }
  const assistantMessages = (careerInterviewState.messages || []).filter((item) => item.role === "assistant");
  const lastAssistant = assistantMessages[assistantMessages.length - 1];
  return String(lastAssistant?.content || getCareerDimensionPrompt(careerInterviewState.focusDimension) || "").trim();
}

function renderCareerInterviewHelperAnchor() {
  const anchorEl = document.getElementById("careerInterviewSelectedScene");
  if (!anchorEl) return;
  const anchor = String(careerInterviewState.helperAnchor || "").trim();
  if (!anchor) {
    anchorEl.classList.add("hidden");
    anchorEl.innerHTML = "";
    return;
  }
  anchorEl.classList.remove("hidden");
  anchorEl.innerHTML = `
    <span class="career-chat-anchor-label">当前线索</span>
    <strong>${escHtml(anchor)}</strong>
    <button type="button" class="career-chat-anchor-clear" onclick="clearCareerInterviewHelperAnchor()">清除</button>
  `;
}

function setCareerInterviewComposerDraft(rawText, options = {}) {
  const input = document.getElementById("careerInterviewInput");
  const text = String(rawText || "").trim();
  if (!input || !text) return;
  const append = Boolean(options.append);
  const current = String(input.value || "").trim();
  const nextValue = append && current
    ? `${current}${/[。！？.!?]$/.test(current) ? "" : "。"}\n${text}`
    : text;
  input.value = nextValue;
  careerInterviewState.helperAnchor = String(options.anchorLabel || options.anchor || "").trim();
  renderCareerInterviewHelperAnchor();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
  adjustCareerInterviewInputHeight();
}

async function useCareerInterviewDraft(rawText, options = {}) {
  const draft = String(rawText || "").trim();
  if (!draft) return;
  if (!careerInterviewState.started) {
    await startCareerInterview({
      initialDraft: draft,
      helperAnchor: String(options.anchorLabel || options.anchor || "").trim()
    });
    return;
  }
  setCareerInterviewComposerDraft(draft, {
    append: Boolean(options.append),
    anchorLabel: options.anchorLabel || options.anchor || ""
  });
}

function bindCareerInterviewHelperInteractions() {
  const chipRow = document.getElementById("careerInterviewQuickChips");
  const sceneGrid = document.getElementById("careerInterviewSceneGrid");

  if (chipRow && chipRow.dataset.bound !== "true") {
    chipRow.dataset.bound = "true";
    chipRow.addEventListener("click", (event) => {
      const target = event.target.closest("[data-draft]");
      if (!target) return;
      void useCareerInterviewDraft(target.getAttribute("data-draft"), {
        anchorLabel: target.getAttribute("data-label") || "",
        append: target.getAttribute("data-mode") === "append"
      });
    });
  }

  if (sceneGrid && sceneGrid.dataset.bound !== "true") {
    sceneGrid.dataset.bound = "true";
    sceneGrid.addEventListener("click", (event) => {
      const target = event.target.closest("[data-draft]");
      if (!target) return;
      void useCareerInterviewDraft(target.getAttribute("data-draft"), {
        anchorLabel: target.getAttribute("data-label") || "",
        append: false
      });
    });
  }
}

function getCareerInterviewSpeechApi() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function adjustCareerInterviewInputHeight() {
  const el = document.getElementById("careerInterviewInput");
  if (!el || !el.classList.contains("career-chat-textarea-autogrow")) return;
  el.style.height = "auto";
  const next = Math.min(el.scrollHeight, CAREER_INTERVIEW_INPUT_MAX_HEIGHT_PX);
  el.style.height = `${next}px`;
  el.style.overflowY = el.scrollHeight > CAREER_INTERVIEW_INPUT_MAX_HEIGHT_PX ? "auto" : "hidden";
}

function scrollCareerInterviewModalToBottom() {
  const modal = document.getElementById("careerInterviewModal");
  if (!modal || modal.classList.contains("hidden")) return;
  const run = () => {
    modal.scrollTop = modal.scrollHeight;
  };
  requestAnimationFrame(run);
  requestAnimationFrame(() => {
    requestAnimationFrame(run);
  });
}

function updateCareerInterviewVoiceButton() {
  const voiceBtn = document.getElementById("careerInterviewVoiceBtn");
  if (!voiceBtn) return;
  if (careerInterviewVoiceState.supported === null) {
    careerInterviewVoiceState.supported = Boolean(getCareerInterviewSpeechApi());
  }
  const supported = Boolean(careerInterviewVoiceState.supported);
  voiceBtn.disabled = !supported || !careerInterviewState.started || careerInterviewState.loading || careerInterviewState.isComplete;
  voiceBtn.classList.toggle("is-listening", careerInterviewVoiceState.listening);
  voiceBtn.classList.toggle("is-unsupported", !supported);
  if (!supported) {
    voiceBtn.innerHTML = CAREER_VOICE_MIC_SVG;
    voiceBtn.setAttribute("aria-label", "当前浏览器不支持语音输入");
    voiceBtn.title = "当前浏览器不支持语音";
    return;
  }
  if (careerInterviewVoiceState.listening) {
    voiceBtn.innerHTML = CAREER_VOICE_STOP_SVG;
    voiceBtn.setAttribute("aria-label", "停止录音");
    voiceBtn.title = "停止录音";
    return;
  }
  voiceBtn.innerHTML = CAREER_VOICE_MIC_SVG;
  voiceBtn.setAttribute("aria-label", "语音输入");
  voiceBtn.title = "语音输入";
}

function stopCareerInterviewVoice() {
  if (careerInterviewVoiceState.recognition && careerInterviewVoiceState.listening) {
    careerInterviewVoiceState.recognition.stop();
  }
  careerInterviewVoiceState.listening = false;
  updateCareerInterviewVoiceButton();
}

function ensureCareerInterviewVoiceRecognition() {
  if (careerInterviewVoiceState.recognition) return careerInterviewVoiceState.recognition;
  const SpeechApi = getCareerInterviewSpeechApi();
  careerInterviewVoiceState.supported = Boolean(SpeechApi);
  if (!SpeechApi) return null;

  const recognition = new SpeechApi();
  recognition.lang = "zh-CN";
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    careerInterviewVoiceState.listening = true;
    updateCareerInterviewVoiceButton();
  };

  recognition.onresult = (event) => {
    const transcript = Array.from(event.results || [])
      .map((item) => item[0]?.transcript || "")
      .join("")
      .trim();
    if (transcript) {
      setCareerInterviewComposerDraft(transcript, {
        append: Boolean(document.getElementById("careerInterviewInput")?.value?.trim()),
        anchorLabel: careerInterviewState.helperAnchor || "语音输入"
      });
    }
  };

  recognition.onerror = (event) => {
    careerInterviewVoiceState.listening = false;
    updateCareerInterviewVoiceButton();
    if (event?.error && event.error !== "no-speech") {
      showToast("语音输入失败", "当前浏览器没有成功识别语音，请改用文本输入。", "warning", 2000);
    }
  };

  recognition.onend = () => {
    careerInterviewVoiceState.listening = false;
    updateCareerInterviewVoiceButton();
  };

  careerInterviewVoiceState.recognition = recognition;
  return recognition;
}

function renderCareerInterviewAssistSurface() {
  const config = getCareerInterviewGuideConfig(careerInterviewState.focusDimension);
  const headlineEl = document.getElementById("careerInterviewPromptHeadline");
  const bodyEl = document.getElementById("careerInterviewPromptBody");
  const guideEl = document.getElementById("careerInterviewGuideText");
  const questionEl = document.getElementById("careerInterviewCurrentQuestion");
  const chipRow = document.getElementById("careerInterviewQuickChips");
  const sceneGrid = document.getElementById("careerInterviewSceneGrid");

  if (headlineEl) headlineEl.textContent = config.headline;
  if (bodyEl) bodyEl.textContent = config.body;
  if (guideEl) guideEl.textContent = config.guide;
  if (questionEl) questionEl.textContent = getCurrentCareerInterviewQuestion() || "模型就绪后会在这里显示当前问题。";

  if (sceneGrid) {
    sceneGrid.innerHTML = (config.scenes || []).map((item) => `
      <button type="button" class="career-scene-card${careerInterviewState.helperAnchor === item.title ? " is-active" : ""}" data-draft="${escHtml(item.draft)}" data-label="${escHtml(item.title)}">
        <strong class="career-scene-title">${escHtml(item.title)}</strong>
        <span class="career-scene-copy">${escHtml(item.caption)}</span>
      </button>
    `).join("");
  }

  if (chipRow) {
    chipRow.innerHTML = (config.chips || []).map((item) => `
      <button type="button" class="career-quick-chip${careerInterviewState.helperAnchor === item.label ? " is-active" : ""}" data-draft="${escHtml(item.draft)}" data-label="${escHtml(item.label)}" data-mode="append">
        ${escHtml(item.label)}
      </button>
    `).join("");
  }

  renderCareerInterviewHelperAnchor();
  updateCareerInterviewVoiceButton();
  bindCareerInterviewHelperInteractions();
}

function markCareerDimensionAnswered(name) {
  const target = getCareerDimensionProgressByName(name);
  if (!target) return;
  const t = Number(target.target || 0);
  const next = Math.min(t, Number(target.answered || 0) + 1);
  target.answered = next;
  target.effective_answered = Math.min(t, Number(target.effective_answered || 0) + 1);
  careerInterviewState.completionScore = getCareerInterviewProgressPercent();
}

function syncCareerInterviewProgress(result = null) {
  if (!Array.isArray(careerInterviewState.dimensionProgress) || careerInterviewState.dimensionProgress.length === 0) {
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  }

  mergeDimensionMetricsFromResult(result);

  let focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  const cur = getCareerDimensionProgressByName(focusName);
  if (cur && !result?.is_complete && Number(cur.answered) >= Number(cur.target)) {
    const nextPending = getNextPendingCareerDimensionName();
    if (nextPending) focusName = nextPending;
  }
  careerInterviewState.focusDimension = focusName;

  if (result?.is_complete) {
    careerInterviewState.dimensionProgress.forEach((item) => {
      item.answered = item.target;
      item.saturated = true;
    });
  }

  if (result?.readiness_score != null) {
    careerInterviewState.readinessScore = Math.max(
      Number(careerInterviewState.readinessScore || 0),
      Number(result.readiness_score || 0)
    );
  }

  careerInterviewState.completionScore = Math.max(
    getCareerInterviewProgressPercent(),
    Number(result?.completion_score || 0)
  );
}

function renderCareerInterviewDimensionProgress() {
  const progress = Array.isArray(careerInterviewState.dimensionProgress) ? careerInterviewState.dimensionProgress : [];
  const html = progress.map((item) => {
    const isActive = normalizeCareerDimensionName(careerInterviewState.focusDimension) === item.name;
    const answered = Math.min(Number(item.answered || 0), Number(item.target || 0));
    const ratio = item.target ? Math.round(answered / item.target * 100) : 0;
    const cov = item.coverage != null && !Number.isNaN(Number(item.coverage))
      ? Math.round(Number(item.coverage) * 100)
      : null;
    const sat = Boolean(item.saturated);
    const sub = sat
      ? "证据已饱和"
      : cov != null
        ? `覆盖约 ${cov}%`
        : `${Number(item.turn_count || 0)} 轮`;
    return `
      <div class="career-progress-item${isActive ? " active" : ""}${sat ? " is-saturated" : ""}">
        <div class="career-progress-head">
          <span>${escHtml(item.name)}</span>
          <span>${answered}/${item.target}</span>
        </div>
        <div class="career-progress-sub">${escHtml(sub)}</div>
        <div class="career-progress-track">
          <span class="career-progress-fill" style="width:${ratio}%"></span>
        </div>
        ${cov != null ? `<div class="career-progress-coverage"><span style="width:${Math.min(100, cov)}%"></span></div>` : ""}
      </div>
    `;
  }).join("");

  ["careerInterviewHeroDimensionProgress", "careerInterviewModalDimensionProgress"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  });
}

function getStoredCareerInterviewConfig() {
  const fallback = getDefaultCareerInterviewConfig();
  const parsed = userWorkspaceState.llmConfigs.career_interview || fallback;
  return {
    base_url: String(parsed.base_url || parsed.baseUrl || fallback.base_url || "").trim(),
    api_key: String(parsed.api_key || parsed.apiKey || fallback.api_key || "").trim(),
    model: String(parsed.model || fallback.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
    configured: Boolean(parsed.configured ?? (parsed.base_url && parsed.api_key)),
    editable: Boolean(parsed.editable ?? isSuperAdminUser()),
    api_key_masked: String(parsed.api_key_masked || "")
  };
}

function getCareerInterviewConfigFromForm() {
  // 配置输入已移至设置面板，直接返回内存中的配置
  return getStoredCareerInterviewConfig();
}

function fillCareerInterviewConfigForm() {
  // 配置表单已移至头像设置面板，此函数保留以兼容调用链
}

function maskApiKey(apiKey) {
  if (!apiKey) return "未填写";
  if (apiKey.length <= 8) return "已填写";
  return `${apiKey.slice(0, 4)}****${apiKey.slice(-4)}`;
}

function updateCareerInterviewConfigStatus() {
  const config = getStoredCareerInterviewConfig();
  const statusEl = document.getElementById("careerInterviewConfigStatus");
  const notConfiguredText = "服务端未配置模型";

  if (!statusEl) return;
  if (!config.configured) {
    statusEl.textContent = notConfiguredText;
    return;
  }
  statusEl.textContent = `${config.model} / ${config.api_key_masked || maskApiKey(config.api_key)}`;
}

async function updateProfileFlowModelStatus(force = false) {
  const statusEl = document.getElementById("profileFlowModelStatus");
  if (!statusEl) return;
  const show = (text, ready) => {
    statusEl.textContent = text;
    statusEl.classList.toggle("bg-emerald-100", ready);
    statusEl.classList.toggle("text-emerald-700", ready);
    statusEl.classList.toggle("bg-slate-100", !ready);
    statusEl.classList.toggle("text-slate-600", !ready);
  };
  if (!isAuthenticatedUser()) {
    show("模型：未登录", false);
    return;
  }
  try {
    const config = await fetchLlmStatus();
    show(config.configured ? `模型：${config.model}` : "模型：服务端未配置", config.configured);
  } catch (error) {
    if (!force) show("模型：读取失败", false);
  }
}

function persistCareerInterviewSnapshot() {
  const snapshot = {
    started: careerInterviewState.started,
    loading: false,
    isComplete: careerInterviewState.isComplete,
    messages: careerInterviewState.messages,
    result: careerInterviewState.result,
    completionScore: careerInterviewState.completionScore,
    readinessScore: careerInterviewState.readinessScore,
    focusDimension: careerInterviewState.focusDimension,
    dimensionProgress: careerInterviewState.dimensionProgress,
    profileBasics: careerInterviewState.profileBasics
  };
  void saveScopedUserState("career_interview", snapshot).catch((error) => {
    console.error("save career interview snapshot failed", error);
  });
}

function resetCareerInterviewState(options = {}) {
  const preserveBasics = options.preserveBasics !== false;
  const retainedBasics = preserveBasics ? normalizeProfileBasics(careerInterviewState.profileBasics) : getDefaultProfileBasics();
  stopCareerInterviewVoice();
  careerInterviewState.started = false;
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = false;
  careerInterviewState.messages = [];
  careerInterviewState.result = null;
  careerInterviewState.completionScore = 0;
  careerInterviewState.readinessScore = 0;
  careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
  careerInterviewState.profileBasics = retainedBasics;
  careerInterviewState.helperAnchor = "";
}

async function saveCareerInterviewConfig() {
  // 配置入口已迁移至头像设置面板
  if (typeof openSettingsPanel === "function") openSettingsPanel();
}

async function loadCareerInterviewConfig(force = false) {
  if (!isAuthenticatedUser()) {
    userWorkspaceState.llmConfigs.career_interview = getDefaultCareerInterviewConfig();
    fillCareerInterviewConfigForm();
    updateCareerInterviewConfigStatus();
    return userWorkspaceState.llmConfigs.career_interview;
  }
  try {
    // 访谈实际走“当前选择的 API+模型”，优先读取运行时选择而非管理员静态配置。
    await fetchActiveLlmRuntimeConfig(force);
  } catch (error) {
    console.error("load career interview config failed", error);
  }
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  return getStoredCareerInterviewConfig();
}

function updateCareerInterviewHero(result = null) {
  const statusEl = document.getElementById("careerInterviewHeroStatus");
  const hintEl = document.getElementById("careerInterviewHeroHint");
  renderCareerInterviewDimensionProgress();
  if (!statusEl || !hintEl) return;

  const progress = careerInterviewState.completionScore || Number(result?.completion_score || 0) || 0;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);
  const focusProgress = getCareerDimensionProgressByName(focusName);
  const ratioText = focusProgress ? `${Math.min(focusProgress.answered, focusProgress.target)}/${focusProgress.target}` : "0/0";

  if (!careerInterviewState.started && !result) {
    statusEl.textContent = getStoredCareerInterviewConfig().configured ? "可开始访谈" : "模型尚未配置";
    hintEl.textContent = "模型由服务端统一配置。配置完成后即可启动访谈，并按维度同步推进职业兴趣画像。";
    return;
  }

  if (careerInterviewState.isComplete || result?.is_complete) {
    statusEl.textContent = "访谈完成";
    hintEl.textContent = "六个核心维度已补齐；方向假设与证据卡见下方「画像收敛」面板。";
    return;
  }

  const rd = Number(careerInterviewState.readinessScore || 0);
  statusEl.textContent = `访谈进行中 ${progress}%`;
  hintEl.textContent = rd
    ? `当前聚焦「${focusName}」，本维 ${ratioText}；可决策度约 ${rd}%。`
    : `当前聚焦「${focusName}」，维度进度 ${ratioText}。继续回答即可推进画像。`;
}

function careerTagHtml(items, emptyText, variant = "default") {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<span class="career-empty-inline">${escHtml(emptyText)}</span>`;
  }
  return values
    .map((item) => `<span class="career-tag career-tag-${variant}">${escHtml(String(item))}</span>`)
    .join("");
}

function careerListHtml(items, emptyText) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (values.length === 0) {
    return `<div class="career-list-empty">${escHtml(emptyText)}</div>`;
  }
  return values
    .map((item) => `<div class="career-list-item"><span class="career-list-dot"></span><span>${escHtml(String(item))}</span></div>`)
    .join("");
}

function renderCareerInterviewEnginePanel(result) {
  const el = document.getElementById("careerInterviewEnginePanel");
  if (!el) return;
  const r = result || careerInterviewState.result;
  if (!r || !careerInterviewState.started) {
    el.innerHTML = "";
    el.classList.add("hidden");
    return;
  }
  const pol = r.next_question_policy && typeof r.next_question_policy === "object" ? r.next_question_policy : null;
  const ph = r.profile_hypothesis && typeof r.profile_hypothesis === "object" ? r.profile_hypothesis : null;
  const cards = Array.isArray(r.evidence_cards) ? r.evidence_cards : [];
  const conflicts = Array.isArray(r.conflict_points) ? r.conflict_points : [];
  const roles = Array.isArray(ph?.top_roles) ? ph.top_roles : [];
  const uconf = Array.isArray(ph?.unresolved_conflicts) ? ph.unresolved_conflicts : [];
  const rs = Number(r.readiness_score ?? careerInterviewState.readinessScore ?? 0);
  const has =
    (pol && (pol.rationale || pol.strategy || pol.target_dimension)) ||
    roles.length ||
    uconf.length ||
    cards.length ||
    conflicts.length ||
    rs > 0;
  if (!has) {
    el.innerHTML = "";
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  const strategyLabelZh = {
    fact_example: "事实举例",
    motive_reason: "动机与原因",
    value_tradeoff: "价值权衡",
    behavior_pref: "行为偏好",
    conflict_clarify: "冲突澄清",
    micro_scenario: "微场景"
  };
  const policyBlock = pol && (pol.rationale || pol.strategy)
    ? `<div class="career-engine-block career-engine-block-policy">
        <p class="career-engine-label">追问策略</p>
        <div class="career-engine-policy-row">
          <span class="career-engine-strategy-chip">${escHtml(strategyLabelZh[pol.strategy] || pol.strategy || "自适应")}</span>
          ${pol.target_dimension ? `<span class="career-engine-policy-target">指向「${escHtml(pol.target_dimension)}」</span>` : ""}
        </div>
        ${pol.rationale ? `<p class="career-engine-copy">${escHtml(pol.rationale)}</p>` : ""}
      </div>`
    : "";
  const rolesBlock = roles.length
    ? `<div class="career-engine-block">
        <p class="career-engine-label">职业方向假设（动态）</p>
        <div class="career-engine-pills">
          ${roles.slice(0, 5).map((x) => {
            const nm = escHtml(String(x.name || ""));
            const raw = Number(x.score || 0);
            const sc = raw <= 1 ? Math.round(raw * 100) : Math.round(Math.min(100, raw));
            return `<span class="career-engine-pill">${nm} <em>${sc}%</em></span>`;
          }).join("")}
        </div>
      </div>`
    : "";
  const confBlock = uconf.length
    ? `<div class="career-engine-block">
        <p class="career-engine-label">待澄清张力</p>
        <ul class="career-engine-list">${uconf.map((t) => `<li>${escHtml(String(t))}</li>`).join("")}</ul>
      </div>`
    : "";
  const evidenceAccentClass = (cat) => {
    const s = String(cat || "");
    if (s.includes("偏好")) return "career-engine-evidence-card--pref";
    if (s.includes("能力")) return "career-engine-evidence-card--ability";
    if (s.includes("风险") || s.includes("张力")) return "career-engine-evidence-card--risk";
    return "career-engine-evidence-card--default";
  };
  const cardBlocks = cards
    .filter((c) => c && (c.category || (c.bullets && c.bullets.length)))
    .map((c) => {
      const bullets = Array.isArray(c.bullets) ? c.bullets : [];
      const cat = String(c.category || "证据");
      const accent = evidenceAccentClass(cat);
      const bulletHtml = bullets
        .map(
          (b) => `
        <div class="career-engine-bullet">
          <span class="career-engine-bullet-dot" aria-hidden="true"></span>
          <p class="career-engine-bullet-text">${escHtml(String(b))}</p>
        </div>`
        )
        .join("");
      return `<article class="career-engine-card career-engine-evidence-card ${accent}">
        <header class="career-engine-card-head">
          <span class="career-engine-card-head-mark"></span>
          <h4 class="career-engine-card-title">${escHtml(cat)}</h4>
        </header>
        <div class="career-engine-bullet-stack">${bulletHtml}</div>
      </article>`;
    })
    .join("");
  const clash = conflicts
    .map((c) => {
      const sm = escHtml(String(c.summary || ""));
      const cq = c.clarify_prompt ? `<p class="career-engine-clarify">${escHtml(String(c.clarify_prompt))}</p>` : "";
      return `<div class="career-engine-clash"><p>${sm}</p>${cq}</div>`;
    })
    .join("");
  el.innerHTML = `
    <div class="career-engine-head">
      <p class="career-engine-kicker">画像收敛</p>
      <p class="career-engine-readiness">可决策度 <strong>${rs}</strong> / 100（模型估计）</p>
    </div>
    <div class="career-engine-grid">
      ${policyBlock}
      ${rolesBlock}
      ${confBlock}
      ${clash ? `<div class="career-engine-block career-engine-wide"><p class="career-engine-label">冲突与反证线索</p>${clash}</div>` : ""}
      ${cardBlocks
    ? `<div class="career-engine-block career-engine-wide career-engine-evidence-wrap">
        <div class="career-engine-evidence-heading">
          <span class="career-engine-evidence-heading-icon" aria-hidden="true"></span>
          <div>
            <p class="career-engine-label career-engine-label-section">职业证据卡</p>
            <p class="career-engine-evidence-sub">按类别摘录、便于引用与复盘</p>
          </div>
        </div>
        <div class="career-engine-cards">${cardBlocks}</div>
      </div>`
    : ""}
    </div>
  `;
}

function syncCareerInterviewGuideDrawer() {
  const drawer = document.getElementById("careerInterviewGuideDrawer");
  if (!drawer) return;
  const userCount = careerInterviewState.messages.filter((m) => m.role === "user").length;
  // 未开始：展开引导；已开始后的首次同步：收起一次让出对话区（之后不反复关掉用户手动展开）
  if (!careerInterviewState.started) {
    drawer.setAttribute("open", "");
    careerInterviewGuideUserCountSeen = 0;
    careerInterviewGuideAutoCollapsedThisSession = false;
    return;
  }
  if (!careerInterviewGuideAutoCollapsedThisSession) {
    drawer.removeAttribute("open");
    careerInterviewGuideAutoCollapsedThisSession = true;
  }
  if (userCount >= 1 && careerInterviewGuideUserCountSeen === 0) {
    drawer.removeAttribute("open");
  }
  careerInterviewGuideUserCountSeen = userCount;
}

function renderCareerInterviewMessages() {
  const thread = document.getElementById("careerInterviewMessages");
  const composer = document.getElementById("careerInterviewComposer");
  const input = document.getElementById("careerInterviewInput");
  const sendBtn = document.getElementById("careerInterviewSendBtn");
  const startBtn = document.getElementById("careerInterviewStartBtn");
  const hintEl = document.getElementById("careerInterviewHint");
  if (!thread) return;

  // 新的主题式进度（旧维度系统仍保留兼容）
  const topicDots = ["角色模型", "生活故事", "工作价值观", "情境应对"];
  const userMessageCount = careerInterviewState.messages.filter(m => m.role === "user").length;
  const exploredCount = Math.min(Math.floor(userMessageCount / 2), 4); // 约每2轮探索一个主题
  const dotsHtml = topicDots.map((t, i) =>
    `<span class="career-chat-topic-dot ${i < exploredCount ? "active" : ""}">${t}</span>`
  ).join("");

  const bannerHtml = careerInterviewState.started ? `
    <div class="career-chat-dimension-banner">
      <div class="career-chat-dimension-title">
        <span>已探索主题</span>
      </div>
      <div class="career-chat-topic-dots">${dotsHtml}</div>
      <div class="career-chat-dimension-meta">${userMessageCount} 次发言</div>
    </div>
  ` : "";

  if (!careerInterviewState.started || careerInterviewState.messages.length === 0) {
    thread.innerHTML = `
      <div class="career-chat-empty">
        <p class="career-chat-empty-title">从上面的场景卡或快捷标签开始，会更容易开口。</p>
        <p class="career-chat-empty-copy">你可以先点场景卡，系统会自动带着这条线索进入第一轮访谈。</p>
      </div>
    `;
  } else {
    thread.innerHTML = bannerHtml + careerInterviewState.messages
      .map((message) => {
        const roleClass = message.role === "user" ? "user" : "assistant";
        const roleLabel = message.role === "user" ? "你的回答" : "访谈代理";
        return `
          <div class="career-chat-item ${roleClass}">
            <div class="career-chat-meta">${roleLabel}</div>
            <div class="career-chat-bubble ${roleClass}">${escHtml(String(message.content || ""))}</div>
          </div>
        `;
      })
      .join("");
  }

  if (composer) composer.classList.toggle("hidden", !careerInterviewState.started);
  if (input) {
    input.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
    if (input.dataset.autogrowBound !== "true") {
      input.dataset.autogrowBound = "true";
      input.addEventListener("input", adjustCareerInterviewInputHeight);
    }
    adjustCareerInterviewInputHeight();
  }
  if (sendBtn) {
    sendBtn.disabled = !careerInterviewState.started || careerInterviewState.isComplete || careerInterviewState.loading;
    sendBtn.textContent = careerInterviewState.loading ? "生成中..." : "发送并继续";
  }
  if (startBtn) {
    startBtn.disabled = careerInterviewState.loading;
    startBtn.textContent = careerInterviewState.loading
      ? "生成中..."
      : careerInterviewState.started
        ? "访谈已启动"
        : (careerInterviewState.helperAnchor ? `围绕「${careerInterviewState.helperAnchor}」开始` : "立即开始访谈");
  }
  if (hintEl) {
    const fd = normalizeCareerDimensionName(careerInterviewState.focusDimension);
    const fp = getCareerDimensionProgressByName(fd);
    const a = fp ? Math.min(Number(fp.answered || 0), Number(fp.target || 0)) : 0;
    const t = fp ? Number(fp.target || 0) : 0;
    hintEl.textContent = careerInterviewState.isComplete
      ? "访谈已完成，可直接参考同步到能力画像的结果。"
      : fp
        ? `已发言 ${userMessageCount} 次 · 当前维度「${fp.name}」有效证据 ${a}/${t}（每维需 ${t} 条实质回答；过短/敷衍会提示重写且不计入）。点「完成访谈」可结束整段访谈。`
        : `已发言 ${userMessageCount} 次。点「完成访谈」可结束整段访谈。`;
  }

  renderCareerInterviewAssistSurface();
  syncCareerInterviewGuideDrawer();
  renderCareerInterviewDimensionProgress();

  if (careerInterviewState.started && careerInterviewState.messages.length > 0) {
    scrollCareerInterviewModalToBottom();
  }
}

function renderCareerInterviewResult(result) {
  const emptyState = document.getElementById("careerInterviewEmptyState");
  const content = document.getElementById("careerInterviewContent");
  const progressEl = document.getElementById("careerInterviewResultProgress");
  const modalProgressEl = document.getElementById("careerInterviewModalProgress");
  const focusEl = document.getElementById("careerInterviewResultFocus");
  const modalFocusEl = document.getElementById("careerInterviewModalFocus");
  const valueTagsEl = document.getElementById("careerInterviewValueTags");

  syncCareerInterviewProgress(result);
  updateCareerInterviewHero(result);

  const basePct = careerInterviewState.completionScore || 0;
  const readinessPct = careerInterviewState.readinessScore || 0;
  const progressText = readinessPct ? `覆盖 ${basePct}% · 可决策 ${readinessPct}%` : `${basePct}%`;
  const focusName = normalizeCareerDimensionName(result?.focus_dimension || careerInterviewState.focusDimension);

  if (!result || !result.profile) {
    if (emptyState) emptyState.classList.remove("hidden");
    if (content) content.classList.add("hidden");
    if (progressEl) progressEl.textContent = progressText;
    if (modalProgressEl) modalProgressEl.textContent = progressText;
    if (focusEl) focusEl.textContent = focusName;
    if (modalFocusEl) modalFocusEl.textContent = focusName;
    updateProfileRadarChart(null);
    renderCareerInterviewDimensionProgress();
    renderCareerInterviewEnginePanel(null);
    refreshUnifiedExperience();
    return;
  }

  if (emptyState) emptyState.classList.add("hidden");
  if (content) content.classList.remove("hidden");
  if (progressEl) progressEl.textContent = progressText;
  if (modalProgressEl) modalProgressEl.textContent = progressText;
  if (focusEl) focusEl.textContent = focusName;
  if (modalFocusEl) modalFocusEl.textContent = focusName;

  if (valueTagsEl) {
    const values = result.profile?.work_values || [];
    valueTagsEl.innerHTML = values.length > 0
      ? careerTagHtml(values, "等待补充", "soft")
      : '<span class="text-xs text-gray-400">多轮对话后会在此收敛价值观标签</span>';
  }

  renderCareerInterviewDimensionProgress();
  renderCareerInterviewEnginePanel(result);
  renderCareerInterviewAssistSurface();
  updateProfileRadarChart(result.profile);
  refreshUnifiedExperience();
}

function updateProfileRadarChart(profile) {
  const chart = appState.profileRadarChart;
  if (!chart) return;

  if (!profile || !Array.isArray(profile.dimensions) || profile.dimensions.length === 0) {
    chart.data.labels = ["专业技能", "证书资质", "沟通能力", "学习能力", "抗压能力", "创新能力", "实习经历", "项目经验"];
    chart.data.datasets[0].label = "能力评分";
    chart.data.datasets[0].data = [75, 60, 82, 88, 70, 65, 60, 55];
    chart.update();
    return;
  }

  chart.data.labels = profile.dimensions.map((item) => item.name);
  chart.data.datasets[0].label = "访谈画像";
  chart.data.datasets[0].data = profile.dimensions.map((item) => Number(item.score || 0));
  chart.update();
}

async function hydrateCareerInterviewState(force = false) {
  await loadCareerInterviewConfig(force);
  if (!isAuthenticatedUser()) {
    resetCareerInterviewState({ preserveBasics: false });
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  const snapshot = await fetchScopedUserState("career_interview", force);
  if (!snapshot) {
    resetCareerInterviewState({ preserveBasics: false });
    renderCareerInterviewMessages();
    renderCareerInterviewResult(null);
    return;
  }

  careerInterviewState.started = Boolean(snapshot.started);
  careerInterviewState.loading = false;
  careerInterviewState.isComplete = Boolean(snapshot.isComplete);
  careerInterviewState.messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
  careerInterviewState.result = snapshot.result || null;
  careerInterviewState.completionScore = Number(snapshot.completionScore || 0);
  careerInterviewState.readinessScore = Number(snapshot.readinessScore || 0);
  careerInterviewState.focusDimension = snapshot.focusDimension || CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
  careerInterviewState.profileBasics = normalizeProfileBasics(snapshot.profileBasics);
  careerInterviewState.dimensionProgress = Array.isArray(snapshot.dimensionProgress) && snapshot.dimensionProgress.length > 0
    ? snapshot.dimensionProgress
    : createCareerInterviewDimensionProgress();

  syncCareerInterviewProgress(careerInterviewState.result);
  syncProfileBasicsForm();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
}

function openCareerInterviewModal(mode = "chat") {
  fillCareerInterviewConfigForm();
  updateCareerInterviewConfigStatus();
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);
  renderCareerInterviewAssistSurface();
  bindCareerInterviewHelperInteractions();
  const modal = document.getElementById("careerInterviewModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  document.body.classList.add("career-interview-open");

  window.setTimeout(() => {
    if (mode === "config") {
      // 配置已迁移至头像设置面板
      openSettingsPanel();
    } else if (careerInterviewState.started && !careerInterviewState.isComplete) {
      document.getElementById("careerInterviewInput")?.focus();
    } else {
      document.getElementById("careerInterviewStartBtn")?.focus();
    }
    adjustCareerInterviewInputHeight();
    scrollCareerInterviewModalToBottom();
  }, 120);
}

function closeCareerInterviewModal() {
  const modal = document.getElementById("careerInterviewModal");
  if (modal) modal.classList.add("hidden");
  document.body.classList.remove("career-interview-open");
  stopCareerInterviewVoice();
}

function handleCareerInterviewOverlayClick(event) {
  if (event.target?.id === "careerInterviewModal") {
    closeCareerInterviewModal();
  }
}

function clearCareerInterviewSession() {
  careerInterviewState.loading = false;
  resetCareerInterviewState({ preserveBasics: true });
  persistCareerInterviewSnapshot();
  careerInterviewGuideUserCountSeen = 0;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(null);
  showToast("访谈已清空", "你可以重新开始新的访谈。", "info", 1600);
}

function restartCareerInterview() {
  if (careerInterviewState.loading) {
    showToast("访谈正在处理中", "请等待当前请求结束后再操作。", "info", 1800);
    return;
  }
  const hasProgress =
    careerInterviewState.started &&
    (careerInterviewState.messages.length > 0 || careerInterviewState.isComplete);
  if (hasProgress) {
    if (!window.confirm("确定重新开始？当前访谈内容将清空。")) return;
  }
  clearCareerInterviewSession();
}

function terminateCareerInterview() {
  if (careerInterviewState.loading) {
    showToast("访谈正在处理中", "请等待当前请求结束后再操作。", "info", 1800);
    return;
  }
  if (!careerInterviewState.started) {
    closeCareerInterviewModal();
    return;
  }
  if (!window.confirm("确定终止访谈？本次对话将清空，且不会执行完成整理（与「完成访谈」不同）。")) return;
  resetCareerInterviewState({ preserveBasics: true });
  persistCareerInterviewSnapshot();
  stopCareerInterviewVoice();
  careerInterviewGuideUserCountSeen = 0;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(null);
  closeCareerInterviewModal();
  showToast("访谈已终止", "如需继续可随时重新开始。", "info", 1800);
}

function handleCareerInterviewInputKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCareerInterviewAnswer();
  }
}

async function requestCareerInterview(messages) {
  const config = getStoredCareerInterviewConfig();
  if (!config.configured) {
    throw new Error("职业访谈模型尚未由系统管理员配置。");
  }
  return requestJson("/api/career-interview", {
    method: "POST",
    body: {
      messages: messages.slice(-8),
      focus_dimension: careerInterviewState.focusDimension,
      progress: careerInterviewState.dimensionProgress,
      assessment_context: buildAssessmentContextPayload()
    }
  });
}

async function startCareerInterview(options = {}) {
  if (careerInterviewState.loading) {
    showToast("访谈正在处理中", "请稍候，当前请求尚未完成。", "info", 1600);
    return;
  }

  try {
    await loadCareerInterviewConfig(true);
    const config = getStoredCareerInterviewConfig();
    if (!config.configured) {
      showToast("模型尚未配置", "请联系部署人员在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL。", "warning", 3200);
      return;
    }

    resetCareerInterviewState({ preserveBasics: true });
    careerInterviewState.started = true;
    careerInterviewState.focusDimension = CAREER_INTERVIEW_DIMENSION_PLAN[0].name;
    careerInterviewState.dimensionProgress = createCareerInterviewDimensionProgress();
    careerInterviewState.result = {
      is_complete: false,
      completion_score: 0,
      focus_dimension: careerInterviewState.focusDimension,
      profile: null
    };
    careerInterviewState.messages.push({
      role: "assistant",
      content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
    });
    syncCareerInterviewProgress(careerInterviewState.result);
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("访谈已启动", "请先回答第一轮问题。", "success", 1200);
    if (options.initialDraft) {
      setCareerInterviewComposerDraft(options.initialDraft, {
        append: false,
        anchorLabel: options.helperAnchor || ""
      });
    } else {
      document.getElementById("careerInterviewInput")?.focus();
    }
  } catch (error) {
    showToast("启动访谈失败", error?.message || "请稍后重试。", "error", 2200);
  }
}

async function submitCareerInterviewAnswer() {
  if (careerInterviewState.loading || !careerInterviewState.started || careerInterviewState.isComplete) return;
  const input = document.getElementById("careerInterviewInput");
  const answer = (input?.value || "").trim();
  if (!answer) {
    showToast("请先输入回答", "模型需要你的回答才能继续追问。", "warning", 1800);
    return;
  }
  if (input) {
    input.value = "";
    adjustCareerInterviewInputHeight();
  }

  careerInterviewState.messages.push({ role: "user", content: answer });
  bumpCareerDimensionTurn(careerInterviewState.focusDimension);

  const quality = scoreCareerAnswerQuality(answer);
  if (!quality.effective) {
    careerInterviewState.messages.push({
      role: "assistant",
      content: quality.reminder
    });
    careerInterviewState.completionScore = getCareerInterviewProgressPercent();
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    document.getElementById("careerInterviewInput")?.focus();
    return;
  }

  markCareerDimensionAnswered(careerInterviewState.focusDimension);

  const currentProgress = getCareerDimensionProgressByName(careerInterviewState.focusDimension);
  const shouldAskLocalFollowUp = currentProgress && currentProgress.answered < currentProgress.target;

  if (shouldAskLocalFollowUp) {
    careerInterviewState.completionScore = getCareerInterviewProgressPercent();
    careerInterviewState.messages.push({
      role: "assistant",
      content: getCareerDimensionPrompt(careerInterviewState.focusDimension)
    });
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    document.getElementById("careerInterviewInput")?.focus();
    return;
  }

  careerInterviewState.loading = true;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);

  try {
    const result = await requestCareerInterview(careerInterviewState.messages);
    careerInterviewState.loading = false;
    careerInterviewState.result = result;
    syncCareerInterviewProgress(result);

    // 检查是否是 __FINISH__ 标记（AI认为可以结束）
    const nextQuestion = result.next_question || "";
    const shouldFinish = nextQuestion === "__FINISH__" || Boolean(result.is_complete);

    careerInterviewState.isComplete = shouldFinish;

    if (shouldFinish) {
      careerInterviewState.messages.push({
        role: "assistant",
        content: result.profile?.summary || "访谈完成，我已经整理出你的职业画像。"
      });
    } else {
      careerInterviewState.messages.push({
        role: "assistant",
        content: nextQuestion
      });
    }
    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(result);
    document.getElementById("careerInterviewInput")?.focus();
  } catch (error) {
    careerInterviewState.loading = false;
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("继续访谈失败", error.message, "error", 2400);
  }
}

async function finishCareerInterview() {
  if (careerInterviewState.loading || !careerInterviewState.started) return;
  if (careerInterviewState.messages.length === 0) {
    showToast("还没有开始访谈", "请先开始访谈再完成。", "warning", 1800);
    return;
  }

  careerInterviewState.loading = true;
  renderCareerInterviewMessages();
  renderCareerInterviewResult(careerInterviewState.result);

  try {
    const result = await requestJson("/api/career-interview/finish", {
      method: "POST",
      body: {
        messages: careerInterviewState.messages.slice(-20),
        assessment_context: buildAssessmentContextPayload()
      }
    });

    careerInterviewState.loading = false;
    careerInterviewState.isComplete = true;

    // 更新 result 中的 profile
    if (result.profile) {
      careerInterviewState.result = {
        ...careerInterviewState.result,
        profile: result.profile,
        summary: result.summary || result.profile.summary || "访谈已完成"
      };
    }

    careerInterviewState.messages.push({
      role: "assistant",
      content: result.summary || "感谢你的分享！我已经整理出你的职业画像。"
    });

    persistCareerInterviewSnapshot();
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("访谈已完成", "感谢你的参与！", "success", 1600);
  } catch (error) {
    careerInterviewState.loading = false;
    renderCareerInterviewMessages();
    renderCareerInterviewResult(careerInterviewState.result);
    showToast("完成访谈失败", error.message, "error", 2400);
  }
}
