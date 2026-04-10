(function () {
  const STORAGE_KEY = "sbti_profile";
  const LEGACY_STORAGE_KEY = "sbti_profile_v1";
  const HIDDEN_RESULT_TRIGGER_ID = "drink_gate_q2";

  const DIMENSIONS = {
    S1: { name: "S1 自尊自信" }, S2: { name: "S2 自我清晰度" }, S3: { name: "S3 核心价值" },
    E1: { name: "E1 依恋安全感" }, E2: { name: "E2 情感投入度" }, E3: { name: "E3 边界与依赖" },
    A1: { name: "A1 世界观倾向" }, A2: { name: "A2 规则与灵活度" }, A3: { name: "A3 人生意义感" },
    Ac1: { name: "Ac1 动机导向" }, Ac2: { name: "Ac2 决策风格" }, Ac3: { name: "Ac3 执行模式" },
    So1: { name: "So1 社交主动性" }, So2: { name: "So2 人际边界感" }, So3: { name: "So3 表达与真实度" },
  };

  const QUESTIONS = [
    { id: "q1", dim: "S1", text: "我不够好，周围的人都比我优秀", options: ["确实", "有时", "不是"] },
    { id: "q2", dim: "S1", text: "我会因为别人的优秀而明显怀疑自己", options: ["经常", "偶尔", "基本不会"] },
    { id: "q3", dim: "S2", text: "我很清楚真正的自己是什么样的", options: ["不认同", "中立", "认同"] },
    { id: "q4", dim: "S2", text: "我内心有真正追求的东西", options: ["不认同", "中立", "认同"] },
    { id: "q5", dim: "S3", text: "我一定要不断往上爬、变得更厉害", options: ["不认同", "中立", "认同"] },
    { id: "q6", dim: "S3", text: "外人的评价对我来说无所谓", options: ["不认同", "中立", "认同"] },
    { id: "q7", dim: "E1", text: "对象超过 5 小时没回消息时，你会怎么想？", options: ["更容易怀疑", "在怀疑和信任之间摇摆", "倾向先信任"] },
    { id: "q8", dim: "E1", text: "我在感情里经常担心被对方抛弃", options: ["是的", "偶尔", "不是"] },
    { id: "q9", dim: "E2", text: "我对待每一份感情都是认真的", options: ["并没有", "也许", "是的"] },
    { id: "q10", dim: "E2", text: "遇到很优秀且契合的对象，你会？", options: ["保持克制", "介于两者之间", "会非常投入"] },
    { id: "q11", dim: "E3", text: "恋爱后对象非常黏人时，你更接近？", options: ["那很爽", "都行", "更想保留独立空间"] },
    { id: "q12", dim: "E3", text: "我在关系里很重视个人空间", options: ["不太认同", "看情况", "非常认同"] },
    { id: "q13", dim: "A1", text: "大多数人是善良的", options: ["不太认同", "也许吧", "认同"] },
    { id: "q14", dim: "A1", text: "陌生人突然示好时，你更接近？", options: ["先警惕", "先观察", "先接纳"] },
    { id: "q15", dim: "A2", text: "规则和自由冲突时，你通常？", options: ["优先自由", "看场景", "优先规则"] },
    { id: "q16", dim: "A2", text: "我喜欢打破常规，不喜欢被束缚", options: ["认同", "中立", "不认同"] },
    { id: "q17", dim: "A3", text: "我做事通常有目标", options: ["不认同", "中立", "认同"] },
    { id: "q18", dim: "A3", text: "我会觉得很多事情没有真正意义", options: ["认同", "不确定", "不认同"] },
    { id: "q19", dim: "Ac1", text: "我做事更为取得成果，而不是只为避免风险", options: ["不认同", "中立", "认同"] },
    { id: "q20", dim: "Ac1", text: "面对卡住的任务，你更像？", options: ["先拖一拖", "再观察一下", "尽快想办法推进"] },
    { id: "q21", dim: "Ac2", text: "我做决定比较果断，不喜欢犹豫", options: ["不认同", "中立", "认同"] },
    { id: "q22", dim: "Ac2", text: "在信息不完整时，我通常？", options: ["继续犹豫", "边想边定", "先定再迭代"] },
    { id: "q23", dim: "Ac3", text: "别人说你执行力强，你更接近哪句？", options: ["被逼到最后才强", "有时", "事情就该被推进"] },
    { id: "q24", dim: "Ac3", text: "我做事常常有计划", options: ["计划常被打断", "有时能完成", "很讨厌被打乱"] },
    { id: "q25", dim: "So1", text: "在陌生社交场景中，你更接近？", options: ["慢热", "有人聊就聊", "主动打开场子"] },
    { id: "q26", dim: "So1", text: "朋友带了新朋友来，你通常？", options: ["天然有距离", "看情况", "会主动热情聊"] },
    { id: "q27", dim: "So2", text: "我和人相处有明显边界感", options: ["认同", "中立", "不认同"] },
    { id: "q28", dim: "So2", text: "我渴望和信任的人关系很亲密", options: ["认同", "中立", "不认同"] },
    { id: "q29", dim: "So3", text: "很多时候我会把真实负面看法收起来", options: ["较少", "看关系", "较多"] },
    { id: "q30", dim: "So3", text: "我在不同人面前会表现出不同的自己", options: ["不认同", "中立", "认同"] },
  ];

  const SPECIAL_QUESTIONS = [
    { id: "drink_gate_q1", special: true, text: "您平时有什么爱好？", options: ["吃喝拉撒", "艺术爱好", "饮酒", "健身"] },
    { id: "drink_gate_q2", special: true, text: "您对饮酒的态度是？", options: ["小酌怡情", "习惯大量饮酒"] },
  ];

  const TYPE_PATTERNS = [
    { code: "CTRL", pattern: "HHH-HMH-MHH-HHH-MHM" }, { code: "ATM-er", pattern: "HHH-HHM-HHH-HMH-MHL" },
    { code: "Dior-s", pattern: "MHM-MMH-MHM-HMH-LHL" }, { code: "BOSS", pattern: "HHH-HMH-MMH-HHH-LHL" },
    { code: "THAN-K", pattern: "MHM-HMM-HHM-MMH-MHL" }, { code: "OH-NO", pattern: "HHL-LMH-LHH-HHM-LHL" },
    { code: "GOGO", pattern: "HHM-HMH-MMH-HHH-MHM" }, { code: "SEXY", pattern: "HMH-HHL-HMM-HMM-HLH" },
    { code: "LOVE-R", pattern: "MLH-LHL-HLH-MLM-MLH" }, { code: "MUM", pattern: "MMH-MHL-HMM-LMM-HLL" },
    { code: "FAKE", pattern: "HLM-MML-MLM-MLM-HLH" }, { code: "OG8K", pattern: "MMH-MMM-HML-LMM-MML" },
    { code: "MALO", pattern: "MLH-MHM-MLH-MLH-LMH" }, { code: "JOKE-R", pattern: "LLH-LHL-LML-LLL-MLM" },
    { code: "WOC!", pattern: "HHL-HMH-MMH-HHM-LHH" }, { code: "THIN-K", pattern: "HHL-HMH-MLH-MHM-LHH" },
    { code: "SHIT", pattern: "HHL-HLH-LMM-HHM-LHH" }, { code: "ZZZZ", pattern: "MHL-MLH-LML-MML-LHM" },
    { code: "POOR", pattern: "HHL-MLH-LMH-HHH-LHL" }, { code: "MONK", pattern: "HHL-LLH-LLM-MML-LHM" },
    { code: "IMSB", pattern: "LLM-LMM-LLL-LLL-MLM" }, { code: "SOLO", pattern: "LML-LLH-LHL-LML-LHM" },
    { code: "FUCK", pattern: "MLL-LHL-LLM-MLL-HLH" }, { code: "DEAD", pattern: "LLL-LLM-LML-LLL-LHM" },
    { code: "IMFW", pattern: "LLH-LHL-LML-LLL-MLL" },
  ];

  const TYPE_NAMES = {
    "CTRL": "拿捏者", "ATM-er": "送钱者", "Dior-s": "雕丝", "BOSS": "领导者", "THAN-K": "感恩者",
    "OH-NO": "哦不人", "GOGO": "行人", "SEXY": "尤物", "LOVE-R": "多情者", "MUM": "妈妈",
    "FAKE": "伪人", "OG8K": "无所谓人", "MALO": "吗喽", "JOKE-R": "小丑", "WOC!": "握草人",
    "THIN-K": "思考者", "SHIT": "愤世者", "ZZZZ": "装死者", "POOR": "贫困者", "MONK": "僧人",
    "IMSB": "傻者", "SOLO": "孤儿", "FUCK": "草者", "DEAD": "死者", "IMFW": "废物",
    "HHHH": "傻乐者", "DRUNK": "酒鬼",
  };

  const DIMENSION_ORDER = ["S1", "S2", "S3", "E1", "E2", "E3", "A1", "A2", "A3", "Ac1", "Ac2", "Ac3", "So1", "So2", "So3"];

  const DIMENSION_FEEDBACK = {
    S1: { L: "自我评价偏苛刻，容易先否定自己。", M: "自信会波动，受情境影响较大。", H: "自我评价更稳定，不易被外界扰动。" },
    S2: { L: "内在方向感较弱，容易迷茫。", M: "有方向，但会阶段性摇摆。", H: "对自己的目标与边界较清晰。" },
    S3: { L: "更偏稳态与舒适。", M: "成长与稳定并重。", H: "有较强进取与突破驱动力。" },
    E1: { L: "关系中的不安感偏高。", M: "信任与怀疑并存。", H: "关系安全感较强。" },
    E2: { L: "投入偏谨慎保守。", M: "投入与自保并行。", H: "投入深度较高。" },
    E3: { L: "更偏亲密黏性。", M: "亲密与空间可调。", H: "个人边界与独立感更强。" },
    A1: { L: "更偏防御性视角。", M: "保持观察，不轻易下结论。", H: "更倾向相信善意与合作。" },
    A2: { L: "灵活与自由优先。", M: "规则与变通平衡。", H: "秩序与流程优先。" },
    A3: { L: "意义感较弱，容易空转。", M: "意义感阶段性起伏。", H: "方向感与意义感较稳定。" },
    Ac1: { L: "以避险为主。", M: "推进与避险并重。", H: "以成果导向与推进为主。" },
    Ac2: { L: "决策偏慢，犹豫较多。", M: "决策速度适中。", H: "决策果断度较高。" },
    Ac3: { L: "执行常依赖截止压力。", M: "执行稳定性中等。", H: "执行推进感更强。" },
    So1: { L: "社交启动慢热。", M: "社交弹性中等。", H: "更愿意主动社交。" },
    So2: { L: "更偏关系融合。", M: "边界感可调。", H: "边界意识较强。" },
    So3: { L: "表达更直接。", M: "表达会考虑场景。", H: "擅长分层表达真实想法。" },
  };

  const state = {
    answers: {},
    shuffledQuestions: [],
    currentIndex: 0,
    autoJumpTimer: null,
  };

  const refs = {
    questionCard: document.getElementById("sbtiQuestionCard"),
    resultCard: document.getElementById("sbtiResultCard"),
    progressBar: document.getElementById("sbtiProgressBar"),
    progressText: document.getElementById("sbtiProgressText"),
    title: document.getElementById("sbtiQuestionTitle"),
    meta: document.getElementById("sbtiQuestionMeta"),
    optionList: document.getElementById("sbtiOptionList"),
    prevBtn: document.getElementById("sbtiPrevBtn"),
    nextBtn: document.getElementById("sbtiNextBtn"),
    restartBtn: document.getElementById("sbtiRestartBtn"),
    retakeBtn: document.getElementById("sbtiReTakeBtn"),
    resultTitle: document.getElementById("sbtiResultTitle"),
    resultMatch: document.getElementById("sbtiResultMatch"),
    resultSummary: document.getElementById("sbtiResultSummary"),
    dimList: document.getElementById("sbtiDimList"),
  };

  const ALWAYS_INCLUDED_SPECIAL_QUESTION = SPECIAL_QUESTIONS[0];
  const CONDITIONAL_SPECIAL_QUESTION = SPECIAL_QUESTIONS[1];

  function shuffle(items) {
    const cloned = [...items];
    for (let i = cloned.length - 1; i > 0; i -= 1) {
      const ri = Math.floor(Math.random() * (i + 1));
      [cloned[i], cloned[ri]] = [cloned[ri], cloned[i]];
    }
    return cloned;
  }

  function scoreToLevel(score) {
    if (score <= 3) return "L";
    if (score === 4) return "M";
    return "H";
  }

  function levelToWeight(level) {
    return { L: 1, M: 2, H: 3 }[level] || 1;
  }

  function splitPattern(pattern) {
    return String(pattern || "").replaceAll("-", "").split("");
  }

  function getVisibleQuestions() {
    const list = [...state.shuffledQuestions];
    const specialIndex = list.findIndex((q) => q.id === ALWAYS_INCLUDED_SPECIAL_QUESTION.id);
    if (specialIndex !== -1 && Number(state.answers[ALWAYS_INCLUDED_SPECIAL_QUESTION.id]) === 3) {
      list.splice(specialIndex + 1, 0, CONDITIONAL_SPECIAL_QUESTION);
    }
    return list;
  }

  function getCurrentQuestion() {
    const list = getVisibleQuestions();
    const safeIndex = Math.max(0, Math.min(state.currentIndex, list.length - 1));
    state.currentIndex = safeIndex;
    return { list, question: list[safeIndex], index: safeIndex };
  }

  function answeredCount() {
    const list = getVisibleQuestions();
    return list.reduce((n, q) => (state.answers[q.id] !== undefined ? n + 1 : n), 0);
  }

  function updateProgress() {
    const total = getVisibleQuestions().length;
    const done = answeredCount();
    const percent = total > 0 ? Math.round((done / total) * 100) : 0;
    refs.progressBar.style.width = `${percent}%`;
    refs.progressText.textContent = `${done} / ${total}`;
  }

  function cancelAutoJump() {
    if (state.autoJumpTimer) {
      window.clearTimeout(state.autoJumpTimer);
      state.autoJumpTimer = null;
    }
  }

  function goNext() {
    const list = getVisibleQuestions();
    if (state.currentIndex >= list.length - 1) {
      const done = answeredCount();
      if (done === list.length) renderResult();
      return;
    }
    state.currentIndex += 1;
    renderQuestion();
  }

  function renderQuestion() {
    refs.resultCard.classList.add("hidden");
    refs.questionCard.classList.remove("hidden");

    const { list, question, index } = getCurrentQuestion();
    if (!question) return;
    const selectedValue = Number(state.answers[question.id] || 0);
    const isSpecial = Boolean(question.special);
    const dimName = isSpecial ? "补充题" : (DIMENSIONS[question.dim]?.name || "题目");

    refs.title.textContent = `Q${index + 1}. ${question.text}`;
    refs.meta.textContent = `${dimName} · 点击选项会自动进入下一题`;
    refs.optionList.innerHTML = "";

    question.options.forEach((label, idx) => {
      const value = idx + 1;
      const active = selectedValue === value;
      const node = document.createElement("label");
      node.className = `sbti-option${active ? " active" : ""}`;
      node.innerHTML = `<input type="radio" name="${question.id}" value="${value}" ${active ? "checked" : ""}><span>${label}</span>`;
      node.addEventListener("click", () => {
        cancelAutoJump();
        state.answers[question.id] = value;
        if (question.id === ALWAYS_INCLUDED_SPECIAL_QUESTION.id && value !== 3) {
          delete state.answers[HIDDEN_RESULT_TRIGGER_ID];
        }
        updateProgress();
        renderQuestion();
        state.autoJumpTimer = window.setTimeout(() => {
          goNext();
        }, 160);
      });
      refs.optionList.appendChild(node);
    });

    refs.prevBtn.disabled = index <= 0;
    refs.nextBtn.disabled = state.answers[question.id] === undefined;
    refs.nextBtn.textContent = index >= list.length - 1 ? "提交并查看结果" : "下一题";
    updateProgress();
  }

  function calculateResult() {
    const rawScores = Object.fromEntries(Object.keys(DIMENSIONS).map((key) => [key, 0]));
    QUESTIONS.forEach((q) => {
      rawScores[q.dim] += Number(state.answers[q.id] || 0);
    });

    const levels = Object.fromEntries(Object.entries(rawScores).map(([k, v]) => [k, scoreToLevel(v)]));
    const userPattern = DIMENSION_ORDER.map((key) => levelToWeight(levels[key]));

    const ranked = TYPE_PATTERNS.map((tp) => {
      const pattern = splitPattern(tp.pattern).map(levelToWeight);
      let distance = 0;
      let exact = 0;
      pattern.forEach((w, idx) => {
        const delta = Math.abs(userPattern[idx] - w);
        distance += delta;
        if (delta === 0) exact += 1;
      });
      return {
        code: tp.code,
        distance,
        exact,
        similarity: Math.max(0, Math.round((1 - distance / 30) * 100)),
      };
    }).sort((a, b) => (a.distance - b.distance) || (b.exact - a.exact) || (b.similarity - a.similarity));

    const best = ranked[0];
    let finalCode = best.code;
    let mode = "你的主类型";
    let summary = "维度命中度较高，当前结果可视为你的第一人格画像。";

    if (Number(state.answers[HIDDEN_RESULT_TRIGGER_ID]) === 2) {
      finalCode = "DRUNK";
      mode = "隐藏人格已激活";
      summary = "饮酒补充题触发隐藏人格分支。";
    } else if (best.similarity < 60) {
      finalCode = "HHHH";
      mode = "系统强制兜底";
      summary = "标准人格库最高匹配较低，已落入兜底人格。";
    }

    const finalName = TYPE_NAMES[finalCode] || finalCode;
    return {
      code: finalCode,
      title: `${finalCode}（${finalName}）`,
      match: finalCode === "DRUNK" ? 100 : best.similarity,
      badge: finalCode === "DRUNK" ? "匹配度 100% · 隐藏分支" : `匹配度 ${best.similarity}% · 命中 ${best.exact}/15`,
      mode,
      summary,
      levels,
      rawScores,
      completedAt: Date.now(),
    };
  }

  function saveProfile(profile) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  }

  function loadProfile() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
          localStorage.removeItem(LEGACY_STORAGE_KEY);
        } catch (_) {}
        return parsed;
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  function renderResult(profileArg = null) {
    const profile = profileArg || calculateResult();
    if (!profileArg) saveProfile(profile);

    refs.questionCard.classList.add("hidden");
    refs.resultCard.classList.remove("hidden");
    refs.resultTitle.textContent = profile.title;
    refs.resultMatch.textContent = profile.badge || `匹配度 ${Number(profile.match || 0)}%`;
    refs.resultSummary.textContent = `${profile.mode}。${profile.summary}`;
    refs.dimList.innerHTML = "";
    DIMENSION_ORDER.forEach((key) => {
      const node = document.createElement("div");
      node.className = "sbti-dim-item";
      const level = profile.levels?.[key] || "-";
      const tip = DIMENSION_FEEDBACK[key]?.[level] || "";
      node.textContent = `${DIMENSIONS[key].name}：${level}${tip ? "｜" + tip : ""}`;
      refs.dimList.appendChild(node);
    });
  }

  function startOver() {
    cancelAutoJump();
    state.answers = {};
    state.currentIndex = 0;
    const shuffled = shuffle(QUESTIONS);
    const insertAt = Math.floor(Math.random() * shuffled.length) + 1;
    state.shuffledQuestions = [...shuffled.slice(0, insertAt), ALWAYS_INCLUDED_SPECIAL_QUESTION, ...shuffled.slice(insertAt)];
    renderQuestion();
  }

  refs.prevBtn.addEventListener("click", () => {
    cancelAutoJump();
    state.currentIndex = Math.max(0, state.currentIndex - 1);
    renderQuestion();
  });

  refs.nextBtn.addEventListener("click", () => {
    cancelAutoJump();
    goNext();
  });

  refs.restartBtn.addEventListener("click", startOver);
  refs.retakeBtn.addEventListener("click", startOver);

  const params = new URLSearchParams(window.location.search);
  if (params.get("view") === "result") {
    const cached = loadProfile();
    if (cached) {
      renderResult(cached);
    } else {
      startOver();
    }
  } else {
    startOver();
  }
})();
