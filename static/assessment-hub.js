(function () {
  const DATA_URL = "/static/assessment-data.json?v=20260321-route-align-v2";
  const MBTI_SCALE = [
    { key: "a_strong", label: "非常偏向 A", a: 2, b: 0 },
    { key: "a_lean", label: "比较偏向 A", a: 1, b: 0 },
    { key: "neutral", label: "两边都像", a: 1, b: 1 },
    { key: "b_lean", label: "比较偏向 B", a: 0, b: 1 },
    { key: "b_strong", label: "非常偏向 B", a: 0, b: 2 }
  ];
  const HOLLAND_SCALE = [
    { key: "yes", label: "符合我", score: 1 },
    { key: "no", label: "不符合", score: 0 }
  ];
  const MBTI_PAIRS = [["E", "I"], ["S", "N"], ["T", "F"], ["J", "P"]];
  const HOLLAND_ORDER = ["R", "I", "A", "S", "E", "C"];

  let hollandChart = null;

  const state = {
    data: null,
    dataPromise: null,
    modalOpen: false,
    activeTest: null,
    configOpen: false,
    hydrated: false,
    config: {
      base_url: "",
      api_key: "",
      model: "gpt-4o-mini",
      configured: false,
      editable: false,
      api_key_masked: ""
    },
    mbti: {
      currentIndex: 0,
      answers: {},
      result: null,
      clarifier: { loading: false, summary: "", questions: [], currentIndex: 0, answers: {}, applied: false, requestedSignature: "" }
    },
    holland: {
      currentIndex: 0,
      answers: {},
      result: null
    }
  };

  function esc(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function notify(title, text = "", type = "info", duration = 2000) {
    if (typeof window.showToast === "function") {
      window.showToast(title, text, type, duration);
    } else {
      console[type === "error" ? "error" : "log"](`${title}${text ? `: ${text}` : ""}`);
    }
  }

  function getConfig() {
    return {
      base_url: String(state.config.base_url || "").trim(),
      api_key: String(state.config.api_key || "").trim(),
      model: String(state.config.model || "gpt-4o-mini").trim() || "gpt-4o-mini",
      configured: Boolean(state.config.configured),
      editable: Boolean(state.config.editable),
      api_key_masked: String(state.config.api_key_masked || "")
    };
  }

  function fillConfigForm() {
    // 配置表单已移至头像设置面板，此函数保留但不再操作已移除的元素
  }

  function maskKey(apiKey) {
    if (!apiKey) return "未配置";
    if (apiKey.length <= 8) return "已配置";
    return `${apiKey.slice(0, 4)}****${apiKey.slice(-4)}`;
  }

  function updateConfigStatus() {
    const config = getConfig();
    const ok = Boolean(config.configured);
    const label = document.getElementById("assessmentConfigStatusLabel");
    const hint = document.getElementById("assessmentConfigStatusHint");
    const panel = document.getElementById("assessmentConfigPanelStatus");
    const text = ok ? `${config.model} / ${config.api_key_masked || maskKey(config.api_key)}` : (config.editable ? "未配置" : "等待系统管理员配置");
    if (label) label.textContent = text;
    if (hint) hint.textContent = ok ? "MBTI 维度接近时会自动追加 AI 二选一" : (config.editable ? "仅在 MBTI 维度接近时调用" : "当前账号只能使用系统管理员预设配置");
    if (panel) panel.textContent = ok ? `已就绪：${text}` : text;
  }

  async function saveAssessmentConfig() {
    // 配置入口已移至头像设置面板，此函数仅作兼容保留
    notify("提示", "请点击右上角头像图标打开模型设置。", "info", 2000);
  }

  function persistState() {
    const snapshot = {
      mbti: {
        currentIndex: state.mbti.currentIndex,
        answers: state.mbti.answers,
        clarifier: state.mbti.clarifier
      },
      holland: {
        currentIndex: state.holland.currentIndex,
        answers: state.holland.answers
      }
    };
    if (typeof window.saveScopedUserState === "function" && typeof window.isAuthenticatedUser === "function" && window.isAuthenticatedUser()) {
      void window.saveScopedUserState("assessment_hub", snapshot).catch((error) => {
        console.error("save assessment state failed", error);
      });
    }
  }

  async function hydrateState(force = false) {
    if (typeof window.fetchScopedUserState !== "function" || typeof window.isAuthenticatedUser !== "function" || !window.isAuthenticatedUser()) {
      state.hydrated = true;
      return;
    }
    const snapshot = await window.fetchScopedUserState("assessment_hub", force);
    if (!snapshot) {
      state.hydrated = true;
      return;
    }
    if (snapshot.mbti) {
      state.mbti.currentIndex = Number(snapshot.mbti.currentIndex || 0);
      state.mbti.answers = snapshot.mbti.answers || {};
      state.mbti.clarifier = { ...state.mbti.clarifier, ...(snapshot.mbti.clarifier || {}) };
    }
    if (snapshot.holland) {
      state.holland.currentIndex = Number(snapshot.holland.currentIndex || 0);
      state.holland.answers = snapshot.holland.answers || {};
    }
    state.hydrated = true;
  }

  async function loadConfig(force = false) {
    if (typeof window.fetchManagedLlmConfig !== "function" || typeof window.isAuthenticatedUser !== "function" || !window.isAuthenticatedUser()) {
      state.config = {
        base_url: "",
        api_key: "",
        model: "gpt-4o-mini",
        configured: false,
        editable: false,
        api_key_masked: ""
      };
      fillConfigForm();
      updateConfigStatus();
      return state.config;
    }
    try {
      state.config = await window.fetchManagedLlmConfig("assessment_hub", force);
    } catch (error) {
      console.error("load assessment config failed", error);
    }
    fillConfigForm();
    updateConfigStatus();
    return state.config;
  }

  function mbtiQuestions() { return state.data?.mbti?.questions || []; }
  function hollandQuestions() { return state.data?.holland?.questions || []; }

  function ensureData() {
    if (state.data) return Promise.resolve(state.data);
    if (state.dataPromise) return state.dataPromise;
    state.dataPromise = fetch(DATA_URL)
      .then((res) => res.json().then((payload) => ({ ok: res.ok, payload })))
      .then(({ ok, payload }) => {
        if (!ok) throw new Error(payload.message || "题库加载失败");
        state.data = payload;
        recomputeAll();
        renderAll();
        maybeAutoRunMbtiClarifier();
        return payload;
      })
      .catch((error) => {
        state.dataPromise = null;
        throw error;
      });
    return state.dataPromise;
  }

  function hollandMap() {
    const map = {};
    const groups = state.data?.holland?.groups || {};
    Object.entries(groups).forEach(([code, ids]) => ids.forEach((id) => { map[id] = code; }));
    return map;
  }

  function getMbtiTypeDetail(type) {
    const typeCode = String(type || "").trim().toUpperCase();
    return state.data?.mbti?.type_details?.[typeCode] || null;
  }

  function getHollandTypeDetail(code) {
    const typeCode = String(code || "").trim().toUpperCase();
    return state.data?.holland?.type_details?.[typeCode] || null;
  }

  function getMbtiScale(key) {
    return MBTI_SCALE.find((item) => item.key === key) || MBTI_SCALE[0];
  }

  function createEmptyClarifier() {
    return { loading: false, summary: "", questions: [], currentIndex: 0, answers: {}, applied: false, requestedSignature: "" };
  }

  function resetClarifier(keepRequest = false) {
    const signature = keepRequest ? state.mbti.clarifier.requestedSignature : "";
    state.mbti.clarifier = { ...createEmptyClarifier(), requestedSignature: signature };
  }

  function computeMbti() {
    if (!state.data) return null;
    const rawScores = { E: 0, I: 0, S: 0, N: 0, T: 0, F: 0, J: 0, P: 0 };
    let answered = 0;
    mbtiQuestions().forEach((q) => {
      const answer = state.mbti.answers[String(q.id)];
      if (!answer) return;
      const scale = getMbtiScale(answer);
      rawScores[q.a_letter] += scale.a;
      rawScores[q.b_letter] += scale.b;
      answered += 1;
    });

    const clarifierScores = {};
    (state.mbti.clarifier.questions || []).forEach((q) => {
      const pair = String(q.pair || "");
      if (!pair) return;
      if (!clarifierScores[pair]) {
        clarifierScores[pair] = { left: pair[0], right: pair[1], leftScore: 0, rightScore: 0, answered: 0 };
      }
      const answer = state.mbti.clarifier.answers[String(q.id)];
      if (!answer) return;
      const scale = getMbtiScale(answer);
      const weight = Math.max(1, Math.min(3, Number(q.weight || 2)));
      clarifierScores[pair].leftScore += scale.a * weight;
      clarifierScores[pair].rightScore += scale.b * weight;
      clarifierScores[pair].answered += 1;
    });

    const rawPairResults = MBTI_PAIRS.map(([left, right]) => {
      const pair = `${left}${right}`;
      const leftScore = rawScores[left];
      const rightScore = rawScores[right];
      const total = leftScore + rightScore;
      const diff = Math.abs(leftScore - rightScore);
      const selected = leftScore > rightScore ? left : rightScore > leftScore ? right : (state.data.mbti.tie_breakers?.[pair] || right);
      const threshold = 5;
      return {
        pair, left, right, leftScore, rightScore, total, diff,
        selected, close: diff <= threshold, meta: state.data.mbti.pair_hints?.[pair] || {}
      };
    });

    const finalPairResults = rawPairResults.map((item) => {
      const clarified = clarifierScores[item.pair];
      const hasClarifierAnswer = Boolean(clarified && clarified.answered > 0);
      let finalSelected = item.selected;
      if (hasClarifierAnswer) {
        if (clarified.leftScore > clarified.rightScore) {
          finalSelected = item.left;
        } else if (clarified.rightScore > clarified.leftScore) {
          finalSelected = item.right;
        }
      }
      return {
        ...item,
        rawSelected: item.selected,
        finalSelected,
        clarified: hasClarifierAnswer,
        clarifierLeftScore: clarified?.leftScore || 0,
        clarifierRightScore: clarified?.rightScore || 0,
        clarifierAnswered: clarified?.answered || 0
      };
    });

    const rawType = rawPairResults.map((item) => item.selected).join("");
    const finalType = finalPairResults.map((item) => item.finalSelected).join("");
    const detail = getMbtiTypeDetail(finalType) || getMbtiTypeDetail(rawType);
    return {
      completed: answered >= mbtiQuestions().length,
      answeredCount: answered,
      totalQuestions: mbtiQuestions().length,
      rawType,
      finalType,
      scores: rawScores,
      rawPairResults,
      pairResults: finalPairResults,
      closePairs: rawPairResults.filter((item) => item.close),
      unresolvedClosePairs: finalPairResults.filter((item) => item.close && !item.clarified),
      resolvedClosePairs: finalPairResults.filter((item) => item.close && item.clarified),
      confidence: Math.round(rawPairResults.reduce((sum, item) => sum + (item.total ? item.diff / item.total : 0), 0) / rawPairResults.length * 100),
      overview: state.data.mbti.type_overviews?.[finalType] || "结果已生成。",
      detail,
      careers: (state.data.mbti.career_examples?.[finalType] || []).slice(0, 8),
      clarifierApplied: Boolean(state.mbti.clarifier.applied && finalPairResults.some((item) => item.clarified))
    };
  }

  function computeHolland() {
    if (!state.data) return null;
    const map = hollandMap();
    const scores = { R: 0, I: 0, A: 0, S: 0, E: 0, C: 0 };
    let answered = 0;
    hollandQuestions().forEach((q) => {
      const answer = state.holland.answers[String(q.id)];
      if (!answer) return;
      const option = HOLLAND_SCALE.find((item) => item.key === answer) || HOLLAND_SCALE[1];
      scores[map[q.id]] += option.score;
      answered += 1;
    });
    const ranking = HOLLAND_ORDER
      .map((code) => ({ code, score: scores[code], meta: state.data.holland.type_meta?.[code] || {} }))
      .sort((a, b) => b.score - a.score || HOLLAND_ORDER.indexOf(a.code) - HOLLAND_ORDER.indexOf(b.code));
    const top3 = ranking.slice(0, 3);
    const careers = [];
    top3.forEach((item) => (item.meta.careers || []).forEach((career) => {
      if (career && !careers.includes(career) && careers.length < 10) careers.push(career);
    }));
    const primaryDetail = top3[0] ? getHollandTypeDetail(top3[0].code) : null;
    return {
      completed: answered >= hollandQuestions().length,
      answeredCount: answered,
      totalQuestions: hollandQuestions().length,
      scores,
      ranking,
      top3,
      code: top3.map((item) => item.code).join(""),
      primary: top3[0],
      primaryDetail,
      careers,
      summary: top3[0]
        ? `你的兴趣结构当前以${top3[0].meta.name || top3[0].code}为主，其次是${top3.slice(1).map((item) => item.meta.name || item.code).join("、")}。${top3[0].meta.description || ""}`
        : "结果已生成。"
    };
  }

  function recomputeAll() {
    state.mbti.result = computeMbti();
    state.holland.result = computeHolland();
    persistState();
  }

  function hasMbtiConfig() {
    const config = getConfig();
    return Boolean(config.configured || (config.base_url && config.api_key));
  }

  function getMbtiResultSignature(result = state.mbti.result) {
    if (!result?.completed) return "";
    return MBTI_PAIRS.map(([left, right]) => `${left}${right}:${result.scores[left] || 0}-${result.scores[right] || 0}`).join("|");
  }

  function getMbtiPendingPairsLabel(result = state.mbti.result) {
    return (result?.unresolvedClosePairs || []).map((item) => `${item.left}/${item.right}`).join("、");
  }

  function getMbtiDisplayType(result = state.mbti.result) {
    if (!result?.completed) return "--";
    return result.unresolvedClosePairs.length ? "待确认" : result.finalType;
  }

  function getMbtiStatusValue(result = state.mbti.result) {
    if (!result?.completed) return "未开始";
    if (result.unresolvedClosePairs.length) return hasMbtiConfig() ? `待澄清 ${result.unresolvedClosePairs.length} 个` : `待配置 ${result.unresolvedClosePairs.length} 个`;
    if (result.resolvedClosePairs.length) return `已澄清 ${result.resolvedClosePairs.length} 个`;
    return "无需澄清";
  }

  function getMbtiSummaryText(result = state.mbti.result) {
    if (!result?.completed) return "";
    if (result.unresolvedClosePairs.length) {
      return `主测先给出 ${result.rawType} 倾向，但 ${getMbtiPendingPairsLabel(result)} 仍在 5 分以内，最终类型会在 AI 二选一后确认。原始主测分布保持不变。`;
    }
    return `原始类型 ${result.rawType}，最终类型 ${result.finalType}。${result.overview}${result.clarifierApplied ? " 临界维度已由 AI 澄清单独确认，原始分布不变。" : ""}`;
  }

  function maybeAutoRunMbtiClarifier() {
    const result = state.mbti.result;
    const signature = getMbtiResultSignature(result);
    if (!result?.completed || !result.unresolvedClosePairs.length || !signature) return;
    if (!hasMbtiConfig() || state.mbti.clarifier.loading) return;
    if (state.mbti.clarifier.requestedSignature === signature || state.mbti.clarifier.questions.length) return;
    void runMbtiClarifier({ auto: true });
  }

  function renderMbtiDims(result) {
    return result.pairResults.map((item) => {
      const total = Math.max(1, item.total);
      const leftPercent = Math.round(item.leftScore / total * 100);
      const rightPercent = 100 - leftPercent;
      const rawText = item.rawSelected === item.left ? item.meta.left_label || item.left : item.meta.right_label || item.right;
      const finalText = item.finalSelected === item.left ? item.meta.left_label || item.left : item.meta.right_label || item.right;
      return `
        <div class="assessment-dimension-item">
          <div class="assessment-dimension-head">
            <span>${esc(item.meta.title || item.pair)}</span>
            <span>${item.left} ${item.leftScore} : ${item.rightScore} ${item.right}</span>
          </div>
          <div class="assessment-dimension-sub">${item.close ? (item.clarified ? `AI 最终判定：${finalText}` : "临界维度，等待 AI 澄清") : `原始判定：${rawText}`}</div>
          <div class="assessment-dimension-track"><div class="assessment-dimension-fill" style="width:${Math.max(leftPercent, rightPercent)}%"></div></div>
          <div class="assessment-dimension-sub">${esc(item.meta.left_label || item.left)} ${leftPercent}% / ${esc(item.meta.right_label || item.right)} ${rightPercent}%</div>
        </div>
      `;
    }).join("");
  }

  function tags(items, variant = "") {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!list.length) return `<span class="assessment-tag ${variant}">暂无</span>`;
    return list.map((item) => `<span class="assessment-tag ${variant}">${esc(item)}</span>`).join("");
  }

  function setHtml(id, value) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = value;
  }

  function buildAssessmentHubSnapshot() {
    if (!state.data) return null;
    const mbti = state.mbti.result;
    const holland = state.holland.result;
    return {
      generated_at: new Date().toISOString(),
      knowledge_version: state.data.knowledge_version || "",
      mbti: mbti?.completed ? {
        completed: true,
        raw_type: mbti.rawType,
        final_type: mbti.finalType,
        display_type: getMbtiDisplayType(mbti),
        summary: getMbtiSummaryText(mbti),
        confidence: mbti.confidence,
        scores: { ...mbti.scores },
        close_pairs: (mbti.closePairs || []).map((item) => ({
          pair: item.pair,
          diff: item.diff,
          left: item.left,
          right: item.right,
          clarified: Boolean(item.clarified),
          selected: item.finalSelected
        })),
        detail: mbti.detail || null,
        careers: (mbti.careers || []).slice(0, 6)
      } : { completed: false },
      holland: holland?.completed ? {
        completed: true,
        code: holland.code,
        summary: holland.summary,
        scores: { ...holland.scores },
        top_codes: (holland.top3 || []).map((item) => item.code),
        primary: holland.primary ? {
          code: holland.primary.code,
          name: holland.primary.meta?.name || holland.primary.code,
          score: holland.primary.score
        } : null,
        detail: holland.primaryDetail || null,
        careers: (holland.careers || []).slice(0, 6)
      } : { completed: false },
      combined_summary: mbti?.completed && holland?.completed
        ? `MBTI 倾向 ${getMbtiDisplayType(mbti)}，兴趣代码 ${holland.code}，当前更适合结合人格偏好与职业兴趣做岗位初筛。`
        : ""
    };
  }

  function publishAssessmentSnapshot() {
    const snapshot = buildAssessmentHubSnapshot();
    window.getAssessmentHubSnapshot = function () { return snapshot; };
    window.dispatchEvent(new CustomEvent("assessment-hub:updated", { detail: snapshot }));
  }

  function updateMbtiCard() {
    const empty = document.getElementById("mbtiResultEmpty");
    const content = document.getElementById("mbtiResultContent");
    const status = document.getElementById("mbtiResultStatus");
    const result = state.mbti.result;
    if (!empty || !content || !status) return;
    if (!result?.completed) {
      empty.classList.remove("hidden");
      content.classList.add("hidden");
      const progress = Object.keys(state.mbti.answers).length;
      status.textContent = progress ? "进行中" : "未开始";
      status.className = `assessment-status-chip${progress ? " progress" : ""}`;
      return;
    }
    empty.classList.add("hidden");
    content.classList.remove("hidden");
    status.textContent = "已完成";
    status.className = "assessment-status-chip done";
    document.getElementById("mbtiRawType").textContent = result.rawType;
    document.getElementById("mbtiResultType").textContent = getMbtiDisplayType(result);
    document.getElementById("mbtiResultMetaLabel").textContent = "判定状态";
    document.getElementById("mbtiResultMetaValue").textContent = getMbtiStatusValue(result);
    document.getElementById("mbtiResultSummary").textContent = getMbtiSummaryText(result);
    document.getElementById("mbtiDimensionList").innerHTML = renderMbtiDims(result);
    document.getElementById("mbtiCareerTags").innerHTML = tags(result.careers.slice(0, 6), "accent");
    document.getElementById("mbtiResultNickname") && (document.getElementById("mbtiResultNickname").textContent = result.detail?.nickname || "--");
    setHtml("mbtiStrengthTags", tags(result.detail?.strengths || [], "warm"));
    setHtml("mbtiRiskTags", tags(result.detail?.risks || [], ""));
    setHtml("mbtiAdviceTags", tags(result.detail?.career_advice || [], "accent"));
    setHtml("mbtiWorkStyleTags", tags(result.detail?.work_style || [], ""));
    const decisionBlock = document.getElementById("mbtiDecisionBlock");
    const decisionHint = document.getElementById("mbtiDecisionHint");
    const decisionTags = document.getElementById("mbtiDecisionTags");
    if (decisionBlock) decisionBlock.classList.toggle("hidden", result.resolvedClosePairs.length === 0);
    if (decisionHint) decisionHint.textContent = result.resolvedClosePairs.length
      ? "以下维度由 AI 追加题单独做最终二选一，不会修改原始主测分布。"
      : "当前还没有 AI 澄清结论。";
    if (decisionTags) {
      decisionTags.innerHTML = result.resolvedClosePairs.map((item) => {
        const decided = item.finalSelected === item.left ? item.meta.left_label || item.left : item.meta.right_label || item.right;
        return `<span class="assessment-tag warm">${esc(item.meta.title || item.pair)} → ${esc(decided)}</span>`;
      }).join("");
    }
    const clarifierBlock = document.getElementById("mbtiClarifierBlock");
    const clarifierHint = document.getElementById("mbtiClarifierHint");
    const need = result.unresolvedClosePairs.length > 0;
    if (clarifierBlock) clarifierBlock.classList.toggle("hidden", !need);
    if (clarifierHint) clarifierHint.textContent = need
      ? (hasMbtiConfig()
        ? `当前最接近的维度：${getMbtiPendingPairsLabel(result)}。系统会自动生成 AI 澄清题；如果没有拉起，可以手动重试。`
        : `当前最接近的维度：${getMbtiPendingPairsLabel(result)}。配置接口后会自动生成 AI 澄清题。`)
      : "当前四个维度差异已经足够明显。";
  }

  function updateHollandCard() {
    const empty = document.getElementById("hollandResultEmpty");
    const content = document.getElementById("hollandResultContent");
    const status = document.getElementById("hollandResultStatus");
    const result = state.holland.result;
    if (!empty || !content || !status) return;
    if (!result?.completed) {
      empty.classList.remove("hidden");
      content.classList.add("hidden");
      const progress = Object.keys(state.holland.answers).length;
      status.textContent = progress ? "进行中" : "未开始";
      status.className = `assessment-status-chip${progress ? " progress" : ""}`;
      updateRadar(null);
      return;
    }
    empty.classList.add("hidden");
    content.classList.remove("hidden");
    status.textContent = "已完成";
    status.className = "assessment-status-chip done";
    document.getElementById("hollandResultCode").textContent = result.code;
    document.getElementById("hollandResultPrimary").textContent = result.primary?.meta?.name || result.primary?.code || "--";
    document.getElementById("hollandResultSummary").textContent = result.summary;
    document.getElementById("hollandTopTags").innerHTML = result.top3.map((item, index) => `<span class="assessment-tag ${index === 0 ? "warm" : index === 1 ? "accent" : ""}">${esc((item.meta.name || item.code) + " " + item.score + "/15")}</span>`).join("");
    document.getElementById("hollandCareerTags").innerHTML = tags(result.careers, "accent");
    setHtml("hollandTraitTags", tags(result.primaryDetail?.traits || [], "warm"));
    setHtml("hollandEnvironmentTags", tags(result.primaryDetail?.typical_environment || [], ""));
    setHtml("hollandRiskTags", tags(result.primaryDetail?.risks || [], ""));
    setHtml("hollandAdviceTags", tags(result.primaryDetail?.development_advice || [], "accent"));
    updateRadar(result);
  }

  function updateCombinedCard() {
    const card = document.getElementById("assessmentCombinedCard");
    const text = document.getElementById("assessmentCombinedText");
    if (!card || !text) return;
    const mbti = state.mbti.result;
    const holland = state.holland.result;
    if (!mbti?.completed || !holland?.completed) {
      card.classList.add("hidden");
      return;
    }
    const mbtiLabel = mbti.unresolvedClosePairs.length ? `${mbti.rawType}（最终待 AI 确认）` : mbti.finalType;
    text.textContent = `当前综合画像更接近 ${mbtiLabel} 风格，职业兴趣集中在 ${holland.top3.map((item) => item.meta.name || item.code).join("、")}。这意味着你在性格偏好上更适合 ${(mbti.detail?.summary || mbti.overview).replace(/。?$/, "")} 的环境，而在职业方向上更容易被 ${holland.primaryDetail?.summary || holland.primary?.meta?.description || "当前主导兴趣类型"} 吸引。`;
    card.classList.remove("hidden");
  }

  function updateRadar(result) {
    const canvas = document.getElementById("hollandRadarChart");
    if (!canvas || !window.Chart || !state.data) return;
    const labels = HOLLAND_ORDER.map((code) => state.data.holland.type_meta?.[code]?.name || code);
    const values = result ? HOLLAND_ORDER.map((code) => Math.round((Number(result.scores[code] || 0) / 15) * 100)) : [0, 0, 0, 0, 0, 0];
    if (!hollandChart) {
      hollandChart = new Chart(canvas.getContext("2d"), {
        type: "radar",
        data: {
          labels,
          datasets: [{ label: "兴趣强度", data: values, backgroundColor: "rgba(124,58,237,0.18)", borderColor: "rgba(14,116,144,0.95)", borderWidth: 2, pointBackgroundColor: "rgba(14,116,144,1)", pointRadius: 3 }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { r: { min: 0, max: 100, ticks: { stepSize: 20, backdropColor: "transparent" }, grid: { color: "rgba(148,163,184,0.25)" }, angleLines: { color: "rgba(148,163,184,0.18)" }, pointLabels: { color: "#334155", font: { size: 11 } } } }
        }
      });
    } else {
      hollandChart.data.labels = labels;
      hollandChart.data.datasets[0].data = values;
      hollandChart.update();
    }
  }

  function renderAll() {
    updateConfigStatus();
    updateMbtiCard();
    updateHollandCard();
    updateCombinedCard();
    publishAssessmentSnapshot();
    if (state.modalOpen) renderModal();
  }

  function activeAnsweredCount(test) {
    return test === "mbti" ? Object.keys(state.mbti.answers).length : Object.keys(state.holland.answers).length;
  }

  function setModalHeader(title, subtitle, status, progress) {
    const titleEl = document.getElementById("assessmentModalTitle");
    const subtitleEl = document.getElementById("assessmentModalSubtitle");
    const statusEl = document.getElementById("assessmentModalStateText");
    const progressEl = document.getElementById("assessmentModalProgressText");
    if (titleEl) titleEl.textContent = title;
    if (subtitleEl) subtitleEl.textContent = subtitle;
    if (statusEl) statusEl.textContent = status;
    if (progressEl) progressEl.textContent = progress;
  }

  function renderRail() {
    const rail = document.getElementById("assessmentModalProgressRail");
    if (!rail) return;
    let items = [];
    if (!state.activeTest) {
      items = [
        { title: "MBTI 性格倾向", meta: state.mbti.result?.completed ? `已完成 · ${getMbtiDisplayType(state.mbti.result)}` : `${activeAnsweredCount("mbti")}/${mbtiQuestions().length || 93}`, cls: state.mbti.result?.completed ? "done" : activeAnsweredCount("mbti") ? "active" : "" },
        { title: "霍兰德兴趣测评", meta: state.holland.result?.completed ? `已完成 · ${state.holland.result.code}` : `${activeAnsweredCount("holland")}/${hollandQuestions().length || 90}`, cls: state.holland.result?.completed ? "done" : activeAnsweredCount("holland") ? "active" : "" }
      ];
    } else if (state.activeTest === "mbti") {
      items = [
        { title: "主测 93 题", meta: `${activeAnsweredCount("mbti")}/${mbtiQuestions().length || 93}`, cls: state.mbti.result?.completed ? "done" : "active" },
        {
          title: "AI 澄清",
          meta: state.mbti.clarifier.loading
            ? "自动生成中"
            : state.mbti.clarifier.questions.length
              ? `${Object.keys(state.mbti.clarifier.answers).length}/${state.mbti.clarifier.questions.length}`
              : state.mbti.result?.unresolvedClosePairs.length
                ? (hasMbtiConfig() ? "待生成" : "待配置接口")
                : "无需介入",
          cls: state.mbti.clarifier.applied ? "done" : (state.mbti.clarifier.loading || state.mbti.clarifier.questions.length ? "active" : "")
        },
        { title: "结果汇总", meta: state.mbti.result?.completed ? getMbtiDisplayType(state.mbti.result) : "待生成", cls: state.mbti.result?.completed ? "done" : "" }
      ];
    } else {
      items = [
        { title: "兴趣答题", meta: `${activeAnsweredCount("holland")}/${hollandQuestions().length || 90}`, cls: state.holland.result?.completed ? "done" : "active" },
        { title: "结果汇总", meta: state.holland.result?.completed ? state.holland.result.code : "待生成", cls: state.holland.result?.completed ? "done" : "" }
      ];
    }
    rail.innerHTML = items.map((item) => `<div class="assessment-progress-node ${item.cls}"><div class="assessment-progress-title">${esc(item.title)}</div><div class="assessment-progress-meta">${esc(item.meta)}</div></div>`).join("");
  }

  function renderHome() {
    return `
      <div class="assessment-home-grid">
        <div class="assessment-home-card">
          <span class="assessment-mini-label">${state.mbti.result?.completed ? "已完成" : "可立即开始"}</span>
          <h4>MBTI 性格倾向测评</h4>
          <p>93 道题，5 档倾向评分。完成后会输出 4 个维度分布；差值在 5 分以内时会自动追加 AI 二选一。</p>
          <p class="assessment-summary-text">${state.mbti.result?.completed ? `主测：${state.mbti.result.rawType} / 最终：${getMbtiDisplayType(state.mbti.result)}` : `已完成 ${activeAnsweredCount("mbti")} / ${mbtiQuestions().length || 93}`}</p>
          <button type="button" class="assessment-home-btn" onclick="openAssessmentModal('mbti')">${state.mbti.result?.completed ? "查看 MBTI 结果" : "进入 MBTI 测评"}</button>
        </div>
        <div class="assessment-home-card">
          <span class="assessment-mini-label">${state.holland.result?.completed ? "已完成" : "可立即开始"}</span>
          <h4>霍兰德职业兴趣测评</h4>
          <p>90 道题，点击即答。完成后会生成 RIASEC 代码与职业兴趣雷达图。</p>
          <p class="assessment-summary-text">${state.holland.result?.completed ? `当前结果：${state.holland.result.code}` : `已完成 ${activeAnsweredCount("holland")} / ${hollandQuestions().length || 90}`}</p>
          <button type="button" class="assessment-home-btn" onclick="openAssessmentModal('holland')">${state.holland.result?.completed ? "查看霍兰德结果" : "进入霍兰德测评"}</button>
        </div>
      </div>
    `;
  }

  function renderPoleStrip(leftCode, leftText, rightCode, rightText) {
    return `
      <div class="assessment-pole-strip">
        <div class="assessment-pole-chip">
          <span class="assessment-pole-label">${esc(leftCode)}</span>
          <span>${esc(leftText)}</span>
        </div>
        <div class="assessment-pole-chip b">
          <span class="assessment-pole-label">${esc(rightCode)}</span>
          <span>${esc(rightText)}</span>
        </div>
      </div>
    `;
  }

  function getPolarOptionCopy(key) {
    if (key === "a_strong") return "明显偏向左侧";
    if (key === "a_lean") return "略微偏向左侧";
    if (key === "neutral") return "两边都像";
    if (key === "b_lean") return "略微偏向右侧";
    return "明显偏向右侧";
  }

  function getPolarOptionFlair(key, leftCode, rightCode) {
    if (key === "a_strong") return `${leftCode}++`;
    if (key === "a_lean") return `${leftCode}+`;
    if (key === "neutral") return `${leftCode}${rightCode}`;
    if (key === "b_lean") return `${rightCode}+`;
    return `${rightCode}++`;
  }

  function renderPolarScaleOptions(selected, clickBuilder, leftCode, rightCode) {
    return MBTI_SCALE.map((item, index) => {
      const side = item.key.startsWith("a") ? "a" : item.key.startsWith("b") ? "b" : "neutral";
      const active = selected === item.key ? ` active ${side}` : "";
      return `
        <button type="button" class="assessment-option-card dynamic${active}" style="--lift-delay:${index * 0.04}s" onclick="${clickBuilder(item.key)}">
          <div class="assessment-option-core">
            <span class="assessment-option-level">${esc(item.label)}</span>
            <div class="assessment-option-copy">${esc(getPolarOptionCopy(item.key))}</div>
          </div>
          <span class="assessment-option-flair">${esc(getPolarOptionFlair(item.key, leftCode, rightCode))}</span>
        </button>
      `;
    }).join("");
  }

  function renderMbtiQuestion() {
    const questions = mbtiQuestions();
    const index = Math.min(state.mbti.currentIndex, questions.length - 1);
    const q = questions[index];
    const selected = state.mbti.answers[String(q.id)] || "";
    const options = renderPolarScaleOptions(
      selected,
      (key) => `submitAssessmentChoice('mbti','${q.id}','${key}')`,
      "A",
      "B"
    );
    return `
      <div class="assessment-question-card">
        <div class="assessment-question-meta"><span class="assessment-question-index">第 ${index + 1} / ${questions.length} 题</span><span class="assessment-mini-label">已答 ${activeAnsweredCount("mbti")} 题</span></div>
        <h4 class="assessment-question-title">${esc(q.prompt)}</h4>
        ${renderPoleStrip("A", q.option_a, "B", q.option_b)}
        <div class="assessment-option-grid">${options}</div>
        <div class="assessment-question-actions"><button type="button" class="assessment-nav-btn" onclick="goToPreviousQuestion('mbti')" ${index <= 0 ? "disabled" : ""}>返回上一题</button><button type="button" class="assessment-nav-btn primary" onclick="renderAssessmentModal()" ${activeAnsweredCount("mbti") < questions.length ? "disabled" : ""}>查看结果</button></div>
      </div>
    `;
  }

  function renderHollandQuestion() {
    const questions = hollandQuestions();
    const index = Math.min(state.holland.currentIndex, questions.length - 1);
    const q = questions[index];
    const selected = state.holland.answers[String(q.id)] || "";
    const options = HOLLAND_SCALE.map((item) => {
      const active = selected === item.key ? " style=\"border-color:rgba(14,116,144,0.48);background:#ccfbf1\"" : "";
      const copy = item.key === "yes" ? "这条描述与我比较符合。" : "这条描述与我不太符合。";
      return `<button type="button" class="assessment-option-card"${active} onclick="submitAssessmentChoice('holland','${q.id}','${item.key}')"><span class="assessment-option-level">${esc(item.label)}</span><div class="assessment-option-copy">${esc(copy)}</div></button>`;
    }).join("");
    return `
      <div class="assessment-question-card">
        <div class="assessment-question-meta"><span class="assessment-question-index">第 ${index + 1} / ${questions.length} 题</span><span class="assessment-mini-label">已答 ${activeAnsweredCount("holland")} 题</span></div>
        <h4 class="assessment-question-title">${esc(q.prompt)}</h4>
        <div class="assessment-option-grid">${options}</div>
        <div class="assessment-question-actions"><button type="button" class="assessment-nav-btn" onclick="goToPreviousQuestion('holland')" ${index <= 0 ? "disabled" : ""}>返回上一题</button><button type="button" class="assessment-nav-btn primary" onclick="renderAssessmentModal()" ${activeAnsweredCount("holland") < questions.length ? "disabled" : ""}>查看结果</button></div>
      </div>
    `;
  }

  function renderClarifierQuestion() {
    const list = state.mbti.clarifier.questions || [];
    const index = Math.min(state.mbti.clarifier.currentIndex, list.length - 1);
    const q = list[index];
    const selected = state.mbti.clarifier.answers[String(q.id)] || "";
    const left = q.pair[0];
    const right = q.pair[1];
    const options = renderPolarScaleOptions(
      selected,
      (key) => `submitClarifierChoice('${q.id}','${key}')`,
      left,
      right
    );
    return `
      <div class="assessment-ai-card">
        <span class="assessment-mini-label">AI 澄清题 · ${left}/${right}</span>
        <h4 class="assessment-question-title" style="margin-top:0.35rem;">${esc(q.question)}</h4>
        <p class="assessment-summary-text">${esc(state.mbti.clarifier.summary || "本轮仅用于确认接近维度。")}</p>
        ${renderPoleStrip(left, q.option_a, right, q.option_b)}
        <div class="assessment-option-grid">${options}</div>
        <div class="assessment-question-actions"><button type="button" class="assessment-nav-btn" onclick="goToPreviousClarifierQuestion()" ${index <= 0 ? "disabled" : ""}>返回上一题</button><button type="button" class="assessment-nav-btn primary" onclick="renderAssessmentModal()" ${Object.keys(state.mbti.clarifier.answers).length < list.length ? "disabled" : ""}>返回结果页</button></div>
      </div>
    `;
  }

  function renderMbtiResult() {
    const result = state.mbti.result;
    const pendingPairs = getMbtiPendingPairsLabel(result);
    const resolvedPairs = result.resolvedClosePairs.map((item) => `${item.left}/${item.right}`).join("、");
    const aiAction = !result.unresolvedClosePairs.length
      ? `<button type="button" class="assessment-nav-btn primary" disabled>无需 AI 澄清</button>`
      : hasMbtiConfig()
        ? `<button type="button" class="assessment-nav-btn primary" onclick="runMbtiClarifier({ force: true })">${result.resolvedClosePairs.length ? "重新生成 AI 追问" : "立即生成 AI 追问"}</button>`
        : `<button type="button" class="assessment-nav-btn primary" onclick="toggleAssessmentConfigPanel(true)">配置 AI 接口</button>`;
    return `
      <div class="assessment-result-panel">
        <div class="assessment-type-row">
          <div class="assessment-type-cluster">
            <div>
              <span class="assessment-mini-label">原始类型</span>
              <div class="assessment-type-badge subtle">${esc(result.rawType)}</div>
            </div>
            <div>
              <span class="assessment-mini-label">最终类型</span>
              <div class="assessment-type-badge">${esc(getMbtiDisplayType(result))}</div>
            </div>
          </div>
          <div class="text-right">
            <span class="assessment-mini-label">判定状态</span>
            <p class="assessment-confidence-text">${esc(getMbtiStatusValue(result))}</p>
          </div>
        </div>
        <p class="assessment-summary-text">${esc(getMbtiSummaryText(result))}</p>
        <div class="assessment-dimension-list">${renderMbtiDims(result)}</div>
        ${result.resolvedClosePairs.length ? `<div class="assessment-decision-block"><div><span class="assessment-mini-label">AI 澄清结论</span><p class="assessment-summary-text">以下维度由 AI 追加题单独完成最终二选一，不会改动原始主测分布。</p></div><div class="assessment-tag-row">${result.resolvedClosePairs.map((item) => {
          const decided = item.finalSelected === item.left ? item.meta.left_label || item.left : item.meta.right_label || item.right;
          return `<span class="assessment-tag warm">${esc(item.meta.title || item.pair)} → ${esc(decided)}</span>`;
        }).join("")}</div></div>` : ""}
        <div><span class="assessment-mini-label">${result.unresolvedClosePairs.length ? "当前参考职业" : "职业示例"}</span><div class="assessment-tag-row">${tags(result.careers, "accent")}</div></div>
        <div class="assessment-ai-card">
          <span class="assessment-mini-label">AI 澄清状态</span>
          <p class="assessment-summary-text">${
            !result.closePairs.length
              ? "四个维度差异已足够明显，最终类型无需 AI 补判。"
              : result.unresolvedClosePairs.length
                ? (hasMbtiConfig()
                  ? `检测到 ${pendingPairs} 落在 5 分以内，系统会自动生成 AI 二选一澄清题；原始主测分布保持不变。`
                  : `检测到 ${pendingPairs} 落在 5 分以内。补充配置接口后会自动生成 AI 二选一澄清题；当前先保留主测类型 ${result.rawType}。`)
                : `AI 已对 ${resolvedPairs} 完成二选一确认。原始主测分布保持不变，最终类型按澄清结论输出。`
          }</p>
          <div class="assessment-question-actions"><button type="button" class="assessment-nav-btn" onclick="showAssessmentHome()">返回测评首页</button>${aiAction}</div>
        </div>
      </div>
    `;
  }

  function renderHollandResult() {
    const result = state.holland.result;
    return `
      <div class="assessment-result-panel">
        <div class="assessment-type-row"><div><span class="assessment-mini-label">兴趣代码</span><div class="assessment-type-badge secondary">${esc(result.code)}</div></div><div class="text-right"><span class="assessment-mini-label">主导类型</span><p class="assessment-confidence-text">${esc(result.primary?.meta?.name || result.primary?.code || "--")}</p></div></div>
        <p class="assessment-summary-text">${esc(result.summary)}</p>
        <div class="assessment-tag-row">${result.top3.map((item, index) => `<span class="assessment-tag ${index === 0 ? "warm" : index === 1 ? "accent" : ""}">${esc((item.meta.name || item.code) + " " + item.score + "/15")}</span>`).join("")}</div>
        <div><span class="assessment-mini-label">职业线索</span><div class="assessment-tag-row">${tags(result.careers, "accent")}</div></div>
        <div class="assessment-question-actions"><button type="button" class="assessment-nav-btn" onclick="showAssessmentHome()">返回测评首页</button><button type="button" class="assessment-nav-btn primary" onclick="closeAssessmentModal()">关闭测评中心</button></div>
      </div>
    `;
  }

  function renderModal() {
    const content = document.getElementById("assessmentModalContent");
    if (!content) return;
    renderRail();
    const panel = document.getElementById("assessmentConfigPanel");
    if (panel) panel.classList.toggle("hidden", !state.configOpen);
    if (!state.data) {
      setModalHeader("用户画像测评中心", "正在加载题库与结果映射。", "题库加载中", "请稍候");
      content.innerHTML = `<div class="assessment-ai-card" style="display:grid;justify-items:start;"><div class="assessment-loader"></div><h4 class="assessment-question-title">正在加载测评题库</h4><p class="assessment-summary-text">请稍候，系统正在准备当前内容。</p></div>`;
      return;
    }
    if (!state.activeTest) {
      setModalHeader("用户画像测评中心", "任选一个测评开始，系统会自动保存你的进度。", "等待选择测评", `${activeAnsweredCount("mbti") + activeAnsweredCount("holland")} 题已作答`);
      content.innerHTML = renderHome();
      return;
    }
    if (state.activeTest === "mbti") {
      if (state.mbti.clarifier.loading) {
        setModalHeader("MBTI 性格倾向测评", "正在根据临界维度生成追加澄清题。", "AI 生成中", "请稍候");
        content.innerHTML = `<div class="assessment-ai-card" style="display:grid;justify-items:start;"><div class="assessment-loader"></div><h4 class="assessment-question-title">正在生成 MBTI 澄清题</h4><p class="assessment-summary-text">请稍候，系统正在准备当前内容。</p></div>`;
        return;
      }
      if (state.mbti.clarifier.questions.length && !state.mbti.clarifier.applied && Object.keys(state.mbti.clarifier.answers).length < state.mbti.clarifier.questions.length) {
        setModalHeader("MBTI 性格倾向测评", "本轮仅用于确认分数最接近的维度。", "AI 澄清中", `${state.mbti.clarifier.currentIndex + 1} / ${state.mbti.clarifier.questions.length}`);
        content.innerHTML = renderClarifierQuestion();
        return;
      }
      if (state.mbti.result?.completed) {
        const result = state.mbti.result;
        const subtitle = !result.closePairs.length
          ? "主测已完成，四个维度差异已足够明显。"
          : result.unresolvedClosePairs.length
            ? (hasMbtiConfig()
              ? "主测已完成，临界维度会自动触发 AI 二选一。"
              : "主测已完成，补充接口配置后会自动触发 AI 二选一。")
            : "主测已完成，可查看原始分布与 AI 最终判定。";
        setModalHeader("MBTI 性格倾向测评", subtitle, "结果已生成", `${result.answeredCount} / ${result.totalQuestions}`);
        content.innerHTML = renderMbtiResult();
        return;
      }
      state.mbti.currentIndex = Math.max(0, Math.min(state.mbti.currentIndex, mbtiQuestions().length - 1));
      setModalHeader("MBTI 性格倾向测评", "先看上方两端说明，再选择你更靠近哪一侧。点击后会自动跳到下一题。", "MBTI 主测中", `${state.mbti.currentIndex + 1} / ${mbtiQuestions().length}`);
      content.innerHTML = renderMbtiQuestion();
      return;
    }
    if (state.holland.result?.completed) {
      setModalHeader("霍兰德职业兴趣测评", "职业兴趣主测已完成，可查看结果与职业线索。", "结果已生成", `${state.holland.result.answeredCount} / ${state.holland.result.totalQuestions}`);
      content.innerHTML = renderHollandResult();
      return;
    }
    state.holland.currentIndex = Math.max(0, Math.min(state.holland.currentIndex, hollandQuestions().length - 1));
    setModalHeader("霍兰德职业兴趣测评", "每道题只需判断是否符合你，点击后自动进入下一题。", "霍兰德答题中", `${state.holland.currentIndex + 1} / ${hollandQuestions().length}`);
    content.innerHTML = renderHollandQuestion();
  }

  function openAssessmentModal(test) {
    state.modalOpen = true;
    state.activeTest = test === "mbti" || test === "holland" ? test : null;
    if (state.activeTest === "mbti" && !state.mbti.result?.completed) {
      const first = mbtiQuestions().findIndex((q) => !state.mbti.answers[String(q.id)]);
      state.mbti.currentIndex = first === -1 ? 0 : first;
    }
    if (state.activeTest === "holland" && !state.holland.result?.completed) {
      const first = hollandQuestions().findIndex((q) => !state.holland.answers[String(q.id)]);
      state.holland.currentIndex = first === -1 ? 0 : first;
    }
    if (test === "config") state.configOpen = true;
    const modal = document.getElementById("assessmentModal");
    if (modal) modal.classList.remove("hidden");
    document.body.style.overflow = "hidden";
    fillConfigForm();
    updateConfigStatus();
    renderModal();
    ensureData().catch((error) => notify("题库加载失败", error.message, "error", 2600));
  }

  function closeAssessmentModal() {
    state.modalOpen = false;
    document.getElementById("assessmentModal")?.classList.add("hidden");
    document.body.style.overflow = "";
  }

  function handleAssessmentOverlayClick(event) {
    if (event.target?.id === "assessmentModal") closeAssessmentModal();
  }

  function toggleAssessmentConfigPanel(force) {
    // 配置入口已迁移至头像设置面板
    if (typeof window.openSettingsPanel === "function") {
      window.openSettingsPanel();
    }
  }

  function restartAssessmentFlow() {
    if (!state.activeTest || state.activeTest === "mbti") {
      state.mbti = { currentIndex: 0, answers: {}, result: null, clarifier: createEmptyClarifier() };
    }
    if (!state.activeTest || state.activeTest === "holland") {
      state.holland = { currentIndex: 0, answers: {}, result: null };
    }
    recomputeAll();
    renderAll();
    notify("测评进度已重置", state.activeTest ? `已清空 ${state.activeTest.toUpperCase()} 当前进度` : "已清空双测评进度", "info", 1800);
  }

  function submitAssessmentChoice(test, id, answer) {
    if (test === "mbti") {
      const previous = state.mbti.answers[String(id)];
      if (previous !== answer) resetClarifier();
      state.mbti.answers[String(id)] = answer;
      const idx = mbtiQuestions().findIndex((q) => String(q.id) === String(id));
      state.mbti.currentIndex = idx >= 0 ? Math.min(idx + 1, mbtiQuestions().length - 1) : state.mbti.currentIndex;
    } else {
      state.holland.answers[String(id)] = answer;
      const idx = hollandQuestions().findIndex((q) => String(q.id) === String(id));
      state.holland.currentIndex = idx >= 0 ? Math.min(idx + 1, hollandQuestions().length - 1) : state.holland.currentIndex;
    }
    recomputeAll();
    renderAll();
    if (test === "mbti") maybeAutoRunMbtiClarifier();
  }

  function goToPreviousQuestion(test) {
    if (test === "mbti") state.mbti.currentIndex = Math.max(0, state.mbti.currentIndex - 1);
    if (test === "holland") state.holland.currentIndex = Math.max(0, state.holland.currentIndex - 1);
    renderModal();
  }

  function resumeAssessment(test) {
    state.activeTest = test;
    renderModal();
  }

  function showAssessmentHome() {
    state.activeTest = null;
    renderModal();
  }

  function buildAnswerHighlights() {
    const result = state.mbti.result;
    const letters = new Set();
    result.closePairs.forEach((pair) => { letters.add(pair.left); letters.add(pair.right); });
    return mbtiQuestions()
      .filter((q) => (letters.has(q.a_letter) || letters.has(q.b_letter)) && state.mbti.answers[String(q.id)])
      .slice(0, 12)
      .map((q) => ({ id: q.id, prompt: q.prompt, option_a: q.option_a, option_b: q.option_b, a_letter: q.a_letter, b_letter: q.b_letter, answer: getMbtiScale(state.mbti.answers[String(q.id)]).label }));
  }

  async function runMbtiClarifier(options = {}) {
    const force = Boolean(options.force);
    const auto = Boolean(options.auto);
    const result = state.mbti.result;
    if (!result?.completed) {
      notify("请先完成 MBTI 主测", "完成 93 道主测题后才会判断是否需要追加澄清题。", "warning", 2200);
      return;
    }
    if (!result.closePairs.length) {
      notify("当前无需 AI 追问", "四个维度差异已足够明显。", "info", 1800);
      return;
    }
    if (result.clarifierApplied && !force) {
      notify("AI 澄清已完成", "最终二选一已经确认，原始主测分布保持不变。", "info", 1800);
      return;
    }
    const signature = getMbtiResultSignature(result);
    if (!signature) return;
    if (!force && state.mbti.clarifier.requestedSignature === signature && (state.mbti.clarifier.loading || state.mbti.clarifier.questions.length)) {
      return;
    }
    const config = getConfig();
    if (!hasMbtiConfig()) {
      if (!auto) {
        state.configOpen = true;
        renderModal();
        notify("AI 配置未就绪", config.editable ? "请先保存系统 AI 配置。" : "当前配置由系统管理员统一维护，请联系管理员。", "warning", 2600);
      }
      return;
    }
    state.mbti.clarifier = { ...createEmptyClarifier(), loading: true, requestedSignature: signature };
    persistState();
    renderModal();
    try {
      const response = await fetch("/api/mbti-clarifier", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          close_pairs: result.closePairs.map((item) => ({ pair: item.pair, left: item.left, right: item.right, left_score: item.leftScore, right_score: item.rightScore, diff: item.diff })),
          score_snapshot: result.scores,
          answer_highlights: buildAnswerHighlights()
        })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || `请求失败：${response.status}`);
      if (!Array.isArray(payload.questions) || !payload.questions.length) throw new Error("AI 未返回可用的澄清题");
      state.mbti.clarifier = {
        ...createEmptyClarifier(),
        requestedSignature: signature,
        summary: payload.summary || "本轮仅用于确认接近维度。",
        questions: payload.questions
      };
      persistState();
      renderAll();
      notify(auto ? "AI 已自动介入" : "AI 澄清题已生成", `共 ${state.mbti.clarifier.questions.length} 题`, "success", 1800);
    } catch (error) {
      state.mbti.clarifier = { ...createEmptyClarifier(), requestedSignature: signature };
      persistState();
      renderAll();
      notify("生成澄清题失败", auto ? `${error.message}，可稍后手动重试。` : error.message, "error", 2600);
    }
  }

  function submitClarifierChoice(id, answer) {
    state.mbti.clarifier.answers[String(id)] = answer;
    const list = state.mbti.clarifier.questions || [];
    const idx = list.findIndex((q) => String(q.id) === String(id));
    state.mbti.clarifier.currentIndex = idx >= 0 ? Math.min(idx + 1, list.length - 1) : state.mbti.clarifier.currentIndex;
    if (Object.keys(state.mbti.clarifier.answers).length >= list.length) {
      state.mbti.clarifier.applied = true;
      notify("MBTI 澄清完成", "最终二选一已确认，原始主测分布保持不变。", "success", 1800);
    }
    recomputeAll();
    renderAll();
  }

  function goToPreviousClarifierQuestion() {
    state.mbti.clarifier.currentIndex = Math.max(0, state.mbti.clarifier.currentIndex - 1);
    renderModal();
  }

  function resetWorkspaceState() {
    state.activeTest = null;
    state.configOpen = false;
    state.hydrated = false;
    state.config = {
      base_url: "",
      api_key: "",
      model: "gpt-4o-mini",
      configured: false,
      editable: false,
      api_key_masked: ""
    };
    state.mbti = {
      currentIndex: 0,
      answers: {},
      result: null,
      clarifier: createEmptyClarifier()
    };
    state.holland = {
      currentIndex: 0,
      answers: {},
      result: null
    };
    publishAssessmentSnapshot();
  }

  async function syncWorkspace(force = false) {
    if (typeof window.isAuthenticatedUser !== "function" || !window.isAuthenticatedUser()) {
      resetWorkspaceState();
      fillConfigForm();
      updateConfigStatus();
      renderAll();
      return;
    }
    resetWorkspaceState();
    await loadConfig(force);
    await hydrateState(force);
    recomputeAll();
    renderAll();
    maybeAutoRunMbtiClarifier();
  }

  function init() {
    ensureData().catch((error) => console.error("assessment data load failed", error));
    const authReady = window.userWorkspaceState?.authReadyPromise;
    if (authReady && typeof authReady.finally === "function") {
      authReady.finally(() => { void syncWorkspace(true); });
    } else {
      void syncWorkspace(true);
    }
    window.addEventListener("app:auth-changed", () => {
      void syncWorkspace(true);
    });
  }

  window.openAssessmentModal = openAssessmentModal;
  window.closeAssessmentModal = closeAssessmentModal;
  window.handleAssessmentOverlayClick = handleAssessmentOverlayClick;
  window.toggleAssessmentConfigPanel = toggleAssessmentConfigPanel;
  window.saveAssessmentConfig = saveAssessmentConfig;
  window.restartAssessmentFlow = restartAssessmentFlow;
  window.submitAssessmentChoice = submitAssessmentChoice;
  window.goToPreviousQuestion = goToPreviousQuestion;
  window.resumeAssessment = resumeAssessment;
  window.showAssessmentHome = showAssessmentHome;
  window.runMbtiClarifier = runMbtiClarifier;
  window.submitClarifierChoice = submitClarifierChoice;
  window.goToPreviousClarifierQuestion = goToPreviousClarifierQuestion;
  window.renderAssessmentModal = renderModal;
  window.getAssessmentHubSnapshot = function () { return buildAssessmentHubSnapshot(); };
  window.assessmentHubUpdateConfigStatus = updateConfigStatus;

  document.addEventListener("DOMContentLoaded", init);
})();
