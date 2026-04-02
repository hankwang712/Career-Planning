(function () {
  const HISTORY_KEY_PREFIX = "dp_deeptest_hist_v2_";
  const RESULT_KEY_PREFIX = "dp_deeptest_result_v1_";
  const TYT_ASSET_BASE = "/static/trueyouteller";

  const GAME_COVER_MAP = {
    friends: `${TYT_ASSET_BASE}/miniGames/friends.png`,
    insideout: `${TYT_ASSET_BASE}/miniGames/insideOut.png`,
    deep: `${TYT_ASSET_BASE}/brand/trueyouteller.png`,
  };

  const FRIENDS_GIF_MAP = {
    Ross: "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExYjhybnJzbjVxY2Vpa21pem1vYmdkaHQ1YmQ4ZXR3NjlkamZ1ZjRjayZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/UrbnbuU24p1zgyDMUH/giphy.gif",
    Joey: "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExYnRiM2RvZGozZWd1cDBsNjAyemV4bXhxa3hhemNkOW4zeDJzbmhnaSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/fYxTODxnJMhuvjMcOr/giphy.gif",
    Phoebe: "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExNTcyZXkwdTIybHV0N3IwcGRuYzFmbDliMjg5OTI3NXg2aHp0c2F3aSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/A6EACTPNYLSA8/giphy.gif",
    Monica: "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExY2pyYzFqNjVja3k4M214NWNmOG5zb3QzOHQ3N21mMTZiODNzcDRzMCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/SwmYRaqcowXczDPAxP/giphy.gif",
    Chandler: "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExczRrZ2M4b2x2eTJicWZuZTg5bWhwNGsyajd0dzE4bzV3a3JlN3UzeSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/RqcgJ51z5oWty/giphy.gif",
    Rachel: "https://media2.giphy.com/media/v1.Y2lkPTc5MGI3NjExZWVpdHR3MmIyanF0MjZtZHF6a3JsdWV0Zmw1dHR2ZzM1ZGxnMmhnOSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/JqDeI2yjpSRgdh35oe/giphy.gif",
  };

  const IO_GIF_MAP = {
    Joy: "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExNmh0czcwcTd4OXpjMjJlZmg2Y2cwZ3dqajZjb2picjA3dnNqOHluMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/Ta2eHM043vhVS/giphy.gif",
    Sadness: "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExbmFvNGozcWFpaDdzajAxcGhzMXV1eXJ3aGkxc3BkemJrZ2RwZ3IyNSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nWSs8uXjqRvpu/giphy.gif",
    Anger: "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExYWtnNjJwMGJpM3planZmZm1odHMybzIxNnVpNzd6d2RrNTd6MGRmdSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/UUUuU50X5lAYw/giphy.gif",
    Fear: "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExdWw3d2xnYzlveDhydG03bDJicXFud25meTkxOXRrcTVhOG0wZGhvdiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/qd4NxQ0OW6VNe/giphy.gif",
    Disgust: "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExOTN0cWZ3cmpzcTVvampiYXF4eTFra3EzNW12aTY4d25zZTRuZXR0dyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/eLWJeULcoOYbS/giphy.gif",
    Anxiety: "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExYnJkdWZicmpwd3RiaHE3N2ttdHNzY3ZzdDY0NTRuajl4Ymd6bm1yNSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/cYblQbWbVCtdMVH7tZ/giphy.gif",
    Ennui: "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExdDNuZTJmZjU1YnZqamRyMXpueWhwcHU3Mmh1MHhrMTNmNnFzbWd6MiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/bAyPHKg4KMVW5qz32n/giphy.gif",
    Embarrassment: "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExMXFocmdxa3FiemlyejJvemZoNzZyNjExMTVsZW4yeXgwb3Q5NXI2bCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nI1KDpXAN8MQxEKdIX/giphy.gif",
    Envy: "https://sketchok.com/images/articles/01-cartoons/101-pixar/10/16.jpg",
  };

  const SPIRIT_ANIMAL_FILE_MAP = {
    ISTJ: "beaver.jpg",
    ISFJ: "deer.jpg",
    INFJ: "wolf.jpg",
    INTJ: "owl.jpg",
    ISTP: "cat.jpg",
    ISFP: "butterfly.jpg",
    INFP: "panda.jpg",
    INTP: "fox.jpg",
    ESTP: "cheetah.jpg",
    ESFP: "otter.jpg",
    ENFP: "dophin.jpg",
    ENTP: "raven.jpg",
    ESTJ: "lion.jpg",
    ESFJ: "elephant.jpg",
    ENFJ: "horse.jpg",
    ENTJ: "eagle.jpg",
  };

  const TEST_META = {
    deep: {
      pageTitle: "深层 MBTI 完整结果",
      sectionTitle: "深层 MBTI 完整结果",
      sectionHint: "包含四维分布、AI 分析和最近两次测试对比。",
    },
    friends: {
      pageTitle: "老友记角色完整结果",
      sectionTitle: "老友记角色完整结果",
      sectionHint: "完整展示角色说明、共性特质和分数分布。",
    },
    insideout: {
      pageTitle: "情绪主导完整结果",
      sectionTitle: "情绪主导完整结果",
      sectionHint: "完整展示情绪角色、行为特征和分数分布。",
    },
  };

  const MBTI_NAMES = {
    INTJ: "建筑师", INTP: "逻辑学家", ENTJ: "指挥官", ENTP: "辩论者",
    INFJ: "提倡者", INFP: "调停者", ENFJ: "主人公", ENFP: "竞选者",
    ISTJ: "物流师", ISFJ: "守卫者", ESTJ: "总经理", ESFJ: "执政官",
    ISTP: "鉴赏家", ISFP: "探险家", ESTP: "企业家", ESFP: "表演者",
  };

  const MBTI_EMOJI = {
    INTJ: "🏛️", INTP: "🔭", ENTJ: "⚡", ENTP: "💡",
    INFJ: "🌟", INFP: "🎨", ENFJ: "🌍", ENFP: "🎪",
    ISTJ: "📋", ISFJ: "🛡️", ESTJ: "📊", ESFJ: "🤝",
    ISTP: "🔧", ISFP: "🌸", ESTP: "🎯", ESFP: "🎭",
  };

  const FRIENDS_FALLBACK = {
    Ross: { name: "罗斯", emoji: "🦖", color: "#7c6fcd", tagline: "PIVOT！PIVOT！PIVOT！", synopsis: "理性、细腻、对热爱领域极其投入，容易因为计划被打乱而戏剧化崩溃。", traits: [], compatible: [] },
    Joey: { name: "乔伊", emoji: "🍟", color: "#e8a44a", tagline: "你……还好吗？", synopsis: "可爱、忠诚、单纯，永远优先朋友和美食，天然自带亲和力。", traits: [], compatible: [] },
    Phoebe: { name: "菲比", emoji: "🎐", color: "#66bb6a", tagline: "臭猫咪，臭猫咪……", synopsis: "自由、不按常理出牌、极具个人风格，常给出意想不到但深刻的洞察。", traits: [], compatible: [] },
    Monica: { name: "莫妮卡", emoji: "🍆", color: "#ef5350", tagline: "欢迎来到真实世界！", synopsis: "组织力强、竞争心重、执行标准高，做事追求秩序和可控。", traits: [], compatible: [] },
    Chandler: { name: "钱德勒", emoji: "😄", color: "#42a5f5", tagline: "我这个人挺别扭的。", synopsis: "机智幽默、擅长缓和尴尬，用玩笑化解不安，本质上非常重情义。", traits: [], compatible: [] },
    Rachel: { name: "瑞秋", emoji: "💃", color: "#ab47bc", tagline: "TA-DA！", synopsis: "有活力、时尚敏感、成长性强，从依赖到独立，目标驱动明显。", traits: [], compatible: [] },
  };

  const IO_FALLBACK = {
    Joy: { name: "乐乐", emoji: "🌞", color: "#f4b400", tagline: "我们一定能找到好的一面！", synopsis: "乐观、外向、驱动力强，擅长把复杂场景转为可执行的积极行动。", traits: [], compatible: [] },
    Sadness: { name: "忧忧", emoji: "🌧️", color: "#5c8edb", tagline: "难过也是重要的。", synopsis: "共情能力强，能帮助团队识别情绪成本与长期影响。", traits: [], compatible: [] },
    Anger: { name: "怒怒", emoji: "🔥", color: "#ff7043", tagline: "这件事必须马上修正。", synopsis: "对不公平高度敏感，行动果断，适合在关键节点推进问题解决。", traits: [], compatible: [] },
    Fear: { name: "怕怕", emoji: "⚠️", color: "#9c6ade", tagline: "先评估风险。", synopsis: "风险感知强，重视预案和边界，擅长避免低级失误。", traits: [], compatible: [] },
    Disgust: { name: "厌厌", emoji: "💚", color: "#4caf50", tagline: "这个不行。", synopsis: "审美与标准意识强，能快速识别低质量方案并提出优化方向。", traits: [], compatible: [] },
    Anxiety: { name: "焦焦", emoji: "😰", color: "#ff8a65", tagline: "我需要一个完整备份计划。", synopsis: "对未来高敏感，善于制定细颗粒计划，强调确定性。", traits: [], compatible: [] },
    Ennui: { name: "厌倦", emoji: "😒", color: "#808080", tagline: "随便。", synopsis: "在低刺激环境里保持疏离，追求更高信息密度和更强新鲜感。", traits: [], compatible: [] },
    Embarrassment: { name: "尴尬", emoji: "😳", color: "#ffb6c1", tagline: "呃……", synopsis: "社交自我意识高，注重场合反馈与他人评价。", traits: [], compatible: [] },
    Envy: { name: "羡慕", emoji: "😤", color: "#adff2f", tagline: "我也可以，而且更好。", synopsis: "比较敏锐，能快速识别差距并驱动自我提升。", traits: [], compatible: [] },
  };

  const SOURCE_RESULT_DATA = window.__TrueYouTellerResultData__ || {};
  const SOURCE_PERSONALITY_TYPES = SOURCE_RESULT_DATA.PERSONALITY_TYPES || {};
  const SOURCE_FRIENDS_RESULTS = SOURCE_RESULT_DATA.FRIENDS_QUIZ_DATA?.results || {};
  const SOURCE_INSIDEOUT_RESULTS = SOURCE_RESULT_DATA.INSIDEOUT_QUIZ_DATA?.results || {};

  const FRIENDS_SOURCE_KEY_MAP = {
    Ross: "Ross Geller",
    Joey: "Joey Tribbiani",
    Phoebe: "Phoebe Buffay",
    Monica: "Monica Geller",
    Chandler: "Chandler Bing",
    Rachel: "Rachel Green",
  };

  const FRIENDS_SCORE_LABELS = {
    Ross: "罗斯",
    Joey: "乔伊",
    Phoebe: "菲比",
    Monica: "莫妮卡",
    Chandler: "钱德勒",
    Rachel: "瑞秋",
  };

  const INSIDEOUT_SCORE_LABELS = {
    Joy: "快乐",
    Sadness: "悲伤",
    Anger: "愤怒",
    Fear: "恐惧",
    Disgust: "厌恶",
    Anxiety: "焦虑",
    Ennui: "厌倦",
    Embarrassment: "尴尬",
    Envy: "羡慕",
  };

  const state = {
    user: null,
    testType: "deep",
    store: null,
    historyRuns: [],
    deepAiLoading: false,
  };

  function esc(v) {
    return String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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
    if (!response.ok) {
      throw new Error(String(data.message || "请求失败"));
    }
    return data;
  }

  function formatDate(ts) {
    const d = new Date(Number(ts || Date.now()));
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function sanitizeTestType(raw) {
    const v = String(raw || "").trim().toLowerCase();
    return ["deep", "friends", "insideout"].includes(v) ? v : "deep";
  }

  function parseTestTypeFromUrl() {
    try {
      const url = new URL(window.location.href);
      return sanitizeTestType(url.searchParams.get("test"));
    } catch (_) {
      return "deep";
    }
  }

  function setTestTypeToUrl(type, replaceOnly) {
    const safe = sanitizeTestType(type);
    const url = new URL(window.location.href);
    url.searchParams.set("test", safe);
    if (replaceOnly) {
      window.history.replaceState({}, "", url.toString());
    } else {
      window.history.pushState({}, "", url.toString());
    }
  }

  function username() {
    return state.user && state.user.username ? String(state.user.username) : "guest";
  }

  function resultStorageKey() {
    return `${RESULT_KEY_PREFIX}${username()}`;
  }

  function persistStoreData() {
    try {
      localStorage.setItem(resultStorageKey(), JSON.stringify(state.store || {}));
    } catch (_) {}
  }

  function getGameCover(type) {
    return GAME_COVER_MAP[sanitizeTestType(type)] || GAME_COVER_MAP.deep;
  }

  function getGameGif(type, winner) {
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") return FRIENDS_GIF_MAP[winner] || "";
    if (safeType === "insideout") return IO_GIF_MAP[winner] || "";
    return "";
  }

  function getSpiritAnimalImage(type) {
    const code = String(type || "").trim().toUpperCase();
    const file = SPIRIT_ANIMAL_FILE_MAP[code] || "owl.jpg";
    return `${TYT_ASSET_BASE}/animals/${file}`;
  }

  function normalizeGameResult(raw, fallbackMap) {
    if (!raw || typeof raw !== "object") return null;
    const winner = String(raw.winner || "").trim();
    if (!winner) return null;
    const fallback = fallbackMap[winner] || { name: winner, emoji: "🧩", color: "#6366f1", tagline: "", synopsis: "", traits: [], compatible: [] };
    const detailRaw = raw.detail && typeof raw.detail === "object" ? raw.detail : fallback;
    const scoreRaw = raw.scores && typeof raw.scores === "object" ? raw.scores : {};
    const scores = {};
    Object.keys(fallbackMap).forEach((key) => {
      scores[key] = Number(scoreRaw[key] || 0);
    });
    return {
      winner,
      scores,
      completedAt: Number(raw.completedAt || Date.now()),
      detail: {
        name: String(detailRaw.name || fallback.name || winner),
        emoji: String(detailRaw.emoji || fallback.emoji || "🧩"),
        color: String(detailRaw.color || fallback.color || "#6366f1"),
        tagline: String(detailRaw.tagline || fallback.tagline || ""),
        synopsis: String(detailRaw.synopsis || fallback.synopsis || ""),
        traits: Array.isArray(detailRaw.traits) ? detailRaw.traits.map(v => String(v || "")).filter(Boolean) : [],
        compatible: Array.isArray(detailRaw.compatible) ? detailRaw.compatible.map(v => String(v || "")).filter(Boolean) : [],
      },
    };
  }

  function normalizeDeepResult(raw) {
    if (!raw || typeof raw !== "object") return null;
    const type = String(raw.type || "").trim().toUpperCase();
    if (!type) return null;
    return {
      completed: true,
      answeredCount: Number(raw.answeredCount || 52),
      type,
      axisScores: {
        IE: Number(raw.axisScores?.IE || 0),
        SN: Number(raw.axisScores?.SN || 0),
        TF: Number(raw.axisScores?.TF || 0),
        JP: Number(raw.axisScores?.JP || 0),
      },
      pct: {
        IE: Number(raw.pct?.IE || 0),
        SN: Number(raw.pct?.SN || 0),
        TF: Number(raw.pct?.TF || 0),
        JP: Number(raw.pct?.JP || 0),
      },
    };
  }

  function loadStoreData() {
    let parsed = {};
    try {
      const raw = localStorage.getItem(resultStorageKey());
      parsed = raw ? JSON.parse(raw) : {};
    } catch (_) {
      parsed = {};
    }
    state.store = {
      friends: normalizeGameResult(parsed?.friends, FRIENDS_FALLBACK),
      insideout: normalizeGameResult(parsed?.insideout, IO_FALLBACK),
      deep: parsed?.deep && typeof parsed.deep === "object" ? {
        result: normalizeDeepResult(parsed.deep.result),
        aiText: String(parsed.deep.aiText || ""),
        completedAt: Number(parsed.deep.completedAt || Date.now()),
      } : null,
    };
    if (state.store.deep && !state.store.deep.result) state.store.deep = null;
  }

  function loadHistoryRuns() {
    let runs = [];
    try {
      const raw = localStorage.getItem(`${HISTORY_KEY_PREFIX}${username()}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed?.runs)) runs = parsed.runs;
        else if (Array.isArray(parsed)) runs = parsed;
      }
    } catch (_) {
      runs = [];
    }
    state.historyRuns = runs
      .map(item => ({
        type: String(item?.type || "").trim().toUpperCase(),
        axisScores: {
          IE: Number(item?.axisScores?.IE || 0),
          SN: Number(item?.axisScores?.SN || 0),
          TF: Number(item?.axisScores?.TF || 0),
          JP: Number(item?.axisScores?.JP || 0),
        },
        pct: {
          IE: Number(item?.pct?.IE || 0),
          SN: Number(item?.pct?.SN || 0),
          TF: Number(item?.pct?.TF || 0),
          JP: Number(item?.pct?.JP || 0),
        },
        answeredCount: Number(item?.answeredCount || 52),
        savedAt: Number(item?.savedAt || 0),
      }))
      .filter(item => item.type)
      .sort((a, b) => Number(a.savedAt || 0) - Number(b.savedAt || 0));
  }

  function setHeaderByType() {
    const meta = TEST_META[state.testType] || TEST_META.deep;
    const titleEl = document.getElementById("trPageTitle");
    const sectionTitleEl = document.getElementById("trSectionTitle");
    const hintEl = document.getElementById("trSectionHint");
    if (titleEl) titleEl.textContent = meta.pageTitle;
    if (sectionTitleEl) sectionTitleEl.textContent = meta.sectionTitle;
    if (hintEl) hintEl.textContent = meta.sectionHint;
    document.title = `${meta.pageTitle} | 职业规划智能体`;
  }

  function setActiveNav() {
    document.querySelectorAll(".tr-nav-link").forEach((btn) => {
      const type = sanitizeTestType(btn.dataset.test || "");
      btn.classList.toggle("active", type === state.testType);
    });
  }

  function scoreRowsHtml(scores, labels) {
    const entries = Object.keys(labels).map((key) => ({ key, label: labels[key], value: Number(scores?.[key] || 0) }));
    const max = Math.max(1, ...entries.map(item => item.value));
    return `
      <div class="tr-score-list">
        ${entries.map((item) => {
          const pct = Math.round((item.value / max) * 100);
          return `
            <div class="tr-score-row">
              <span class="tr-score-name">${esc(item.label)}</span>
              <div class="tr-score-track"><div class="tr-score-fill" style="width:${pct}%"></div></div>
              <span class="tr-score-num">${item.value}</span>
            </div>`;
        }).join("")}
      </div>`;
  }

  function renderEmpty(message) {
    return `
      <div class="tr-empty">
        <strong>暂无可展示的结果。</strong><br>
        ${esc(message)}
        <div class="tr-empty-actions">
          <button id="trStartTestBtn" type="button" class="tr-btn ghost sm">去开始测试</button>
          <button id="trBackMainFromEmptyBtn" type="button" class="tr-btn primary sm">返回主界面</button>
        </div>
      </div>`;
  }

  function getSourceGameResult(type, winner) {
    const safeType = sanitizeTestType(type);
    const rawWinner = String(winner || "").trim();
    if (!rawWinner) return null;
    if (safeType === "friends") {
      return SOURCE_FRIENDS_RESULTS[FRIENDS_SOURCE_KEY_MAP[rawWinner] || rawWinner] || null;
    }
    if (safeType === "insideout") {
      return SOURCE_INSIDEOUT_RESULTS[rawWinner] || null;
    }
    return null;
  }

  function deepTestCore() {
    return window.__DeepTestHubCore__ || null;
  }

  function hasChineseText(value) {
    return /[\u4e00-\u9fff]/.test(String(value || ""));
  }

  function getLocalizedGameMeta(type, winner) {
    const safeType = sanitizeTestType(type);
    const rawWinner = String(winner || "").trim();
    if (!rawWinner) return null;
    const core = deepTestCore();
    if (safeType === "friends") {
      const meta = core?.getFriendsResultMeta?.() || {};
      return meta[rawWinner] || FRIENDS_FALLBACK[rawWinner] || null;
    }
    if (safeType === "insideout") {
      const meta = core?.getInsideOutResultMeta?.() || {};
      return meta[rawWinner] || IO_FALLBACK[rawWinner] || null;
    }
    return null;
  }

  function buildLocalizedGameMoment(type, winner, meta) {
    const name = meta?.name || winner || "该角色";
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") {
      const map = {
        Ross: "你的高光时刻通常出现在你极度认真地解释一件事，结果把全场带进你的节奏里。",
        Joey: "你的高光时刻通常出现在朋友需要被逗笑、被支持，或者一起冲向美食的时候。",
        Phoebe: "你的高光时刻通常出现在你用非常规想法打破僵局，让场面突然变得有趣又有记忆点。",
        Monica: "你的高光时刻通常出现在大家都还没进入状态时，你已经把秩序、分工和结果全部安排好了。",
        Chandler: "你的高光时刻通常出现在气氛最尴尬的那一秒，你用一句吐槽让所有人都松了口气。",
        Rachel: "你的高光时刻通常出现在需要你站出来表达自己、重塑形象或把场子点亮的时候。",
      };
      return map[winner] || `${name}型的高光时刻通常出现在需要把个性、幽默感或判断力推到台前的时候。`;
    }
    const ioMap = {
      Joy: "你的高光时刻通常出现在团队情绪低落时，你能先把气氛重新拉回到可行动的状态。",
      Sadness: "你的高光时刻通常出现在别人需要被理解的时候，你能让情绪被认真接住。",
      Anger: "你的高光时刻通常出现在规则失衡或效率过低的场景里，你会直接把问题推到台面上。",
      Fear: "你的高光时刻通常出现在大家忽略风险时，你会最早发现漏洞并提醒边界。",
      Disgust: "你的高光时刻通常出现在方案需要被快速筛选时，你会第一时间指出不合格项。",
      Anxiety: "你的高光时刻通常出现在临近节点前，你会把潜在问题提前拆出来并补上预案。",
      Ennui: "你的高光时刻通常出现在信息冗余的场景里，你会迅速过滤掉无效内容，保留重点。",
      Embarrassment: "你的高光时刻通常出现在社交失误刚发生时，你会立刻意识到气氛变化并主动收束。",
      Envy: "你的高光时刻通常出现在看见更高标准时，你会迅速把差距转换成行动动力。",
    };
    return ioMap[winner] || `${name}主导时，你的高光表现通常出现在需要即时情绪判断和现场反应的时刻。`;
  }

  function buildLocalizedFriendReason(type, winner, friendName) {
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") {
      return `${friendName}能和你形成互补节奏，一个负责带动场面，一个负责稳住关系，所以很容易玩到一起。`;
    }
    return `${friendName}会和你形成稳定配合，你们在情绪处理和现场判断上容易彼此接住。`;
  }

  function buildLocalizedGameContent(entry) {
    if (!entry) return null;
    const meta = getLocalizedGameMeta(state.testType, entry.winner) || {};
    const detail = entry?.detail || {};
    const compatibleNames = Array.isArray(meta.compatible) && meta.compatible.length
      ? meta.compatible
      : Array.isArray(detail.compatible) ? detail.compatible : [];
    const habitList = Array.isArray(meta.traits) && meta.traits.length
      ? meta.traits
      : Array.isArray(detail.traits) ? detail.traits : [];
    const displayName = meta.name || detail.name || entry.winner || "未知角色";
    const tagline = meta.tagline || detail.tagline || "结果已就绪";
    return {
      character_name: displayName,
      tagline,
      gif_url: getGameGif(state.testType, entry.winner) || getGameCover(state.testType),
      brief_character_synopsis: meta.synopsis || detail.synopsis || "",
      top_3_character_habits_you_share: habitList,
      your_famous_episode_moment: buildLocalizedGameMoment(state.testType, entry.winner, { ...meta, ...detail }),
      custom_share_card: { phrase: tagline },
      who_would_you_be_friends_with: compatibleNames.map((name) => ({
        friend_name: name,
        reason: buildLocalizedFriendReason(state.testType, entry.winner, name),
      })),
    };
  }

  function getGameAccentColor(type, winner) {
    const safeType = sanitizeTestType(type);
    if (safeType === "friends") return FRIENDS_FALLBACK[winner]?.color || "#ff4b5c";
    if (safeType === "insideout") return IO_FALLBACK[winner]?.color || "#f59e0b";
    return "#6366f1";
  }

  function renderOriginalList(items, className) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="tr-muted">暂无详细说明。</p>';
    }
    return `<ul class="${className || "tr-tyt-list"}">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
  }

  function renderOriginalFriendCards(items) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="tr-muted">暂无友情匹配说明。</p>';
    }
    return `
      <div class="tr-tyt-friends-grid">
        ${items.map((item) => `
          <article class="tr-tyt-friend-card">
            <p class="tr-tyt-friend-name">${esc(item.friend_name || item.name || "友情匹配")}</p>
            <p class="tr-tyt-friend-reason">${esc(item.reason || "")}</p>
          </article>
        `).join("")}
      </div>`;
  }

  function renderOriginalTags(items) {
    if (!Array.isArray(items) || !items.length) {
      return '<p class="tr-muted">暂无标签。</p>';
    }
    return `<div class="tr-tyt-tags">${items.map((item) => `<span class="tr-tyt-tag">${esc(item)}</span>`).join("")}</div>`;
  }

  function buildFallbackGameContent(entry) {
    const detail = entry?.detail || {};
    return {
      character_name: detail.name || entry?.winner || "未知角色",
      tagline: detail.tagline || "",
      gif_url: getGameGif(state.testType, entry?.winner) || getGameCover(state.testType),
      brief_character_synopsis: detail.synopsis || "",
      top_3_character_habits_you_share: Array.isArray(detail.traits) ? detail.traits : [],
      your_famous_episode_moment: detail.synopsis || "",
      custom_share_card: { phrase: detail.tagline || "" },
      who_would_you_be_friends_with: Array.isArray(detail.compatible)
        ? detail.compatible.map((name) => ({
            friend_name: name,
            reason: "该匹配基于你当前的简化测评结果档案。",
          }))
        : [],
    };
  }

  function renderGame(entry, labels) {
    if (!entry) {
      return renderEmpty("请先在画像输入页完成测试，然后再查看完整结果。");
    }

    const sourceResult = getSourceGameResult(state.testType, entry.winner);
    const view = buildLocalizedGameContent(entry) || buildFallbackGameContent(entry);
    const accent = getGameAccentColor(state.testType, entry.winner);
    const gifUrl = String(view.gif_url || sourceResult?.gif_url || getGameGif(state.testType, entry.winner) || getGameCover(state.testType)).trim();
    const coverUrl = getGameCover(state.testType);
    const sharePhrase = String(view.custom_share_card?.phrase || "").trim();

    return `
      <div class="tr-result-grid tr-tyt-mini-page">
        <article class="tr-tyt-mini-hero" style="--tr-accent:${esc(accent)};">
          <div class="tr-tyt-mini-cover">
            <img src="${esc(coverUrl)}" alt="${esc(view.character_name || entry.winner)} 测试封面">
          </div>
          <div class="tr-tyt-mini-copy">
            <p class="tr-tyt-overline">扩展测试 · 中文结果</p>
            <h2 class="tr-tyt-mini-title">你是 ${esc(view.character_name || entry.winner)}！</h2>
            <p class="tr-tyt-mini-tagline">${esc(view.tagline || "结果已就绪")}</p>
            <p class="tr-meta-line">完成时间：${esc(formatDate(entry.completedAt))}</p>
            ${sharePhrase ? `<span class="tr-tyt-share-pill">${esc(sharePhrase)}</span>` : ""}
          </div>
        </article>

        <article class="tr-tyt-visual-card">
          <img class="tr-tyt-result-gif" src="${esc(gifUrl)}" alt="${esc(view.character_name || entry.winner)} 结果图">
        </article>

        <article class="tr-tyt-panel">
          <h3 class="tr-tyt-section-title">角色简介</h3>
          <p class="tr-tyt-copy">${esc(view.brief_character_synopsis || "暂无简介。")}</p>
        </article>

        <article class="tr-tyt-panel">
          <h3 class="tr-tyt-section-title">与你最像的 3 个角色习惯</h3>
          ${renderOriginalList(view.top_3_character_habits_you_share, "tr-tyt-mini-list")}
        </article>

        <article class="tr-tyt-panel">
          <h3 class="tr-tyt-section-title">你的「名场面」时刻</h3>
          <p class="tr-tyt-copy">${esc(view.your_famous_episode_moment || "暂无名场面描述。")}</p>
        </article>

        <article class="tr-tyt-panel">
          <h3 class="tr-tyt-section-title">你最可能和谁成为好友？</h3>
          ${renderOriginalFriendCards(view.who_would_you_be_friends_with)}
        </article>

        <article class="tr-block">
          <h3>得分分布</h3>
          ${scoreRowsHtml(entry.scores || {}, labels)}
        </article>
      </div>`;
  }

  function deepRowsHtml(result) {
    const axisRows = [
      { axis: "IE", label: "外向—内向", left: "外向 E", right: "内向 I" },
      { axis: "SN", label: "直觉—感觉", left: "直觉 N", right: "感觉 S" },
      { axis: "TF", label: "情感—思考", left: "情感 F", right: "思考 T" },
      { axis: "JP", label: "感知—判断", left: "感知 P", right: "判断 J" },
    ];
    return axisRows.map((row) => {
      const score = Number(result.axisScores?.[row.axis] || 0);
      const pct = Number(result.pct?.[row.axis] || 0);
      const toward = score >= 0 ? row.left : row.right;
      return `
        <div class="tr-dim-row">
          <div class="tr-dim-head">
            <strong>${esc(row.label)}</strong>
            <span class="tr-dim-code">${esc(row.axis)} ${score > 0 ? "+" : ""}${score}</span>
          </div>
          <div class="tr-dim-track"><div class="tr-dim-fill" style="width:${pct}%"></div></div>
          <div class="tr-dim-tip">${pct}% 倾向 ${esc(toward)}</div>
        </div>`;
    }).join("");
  }

  function deepHistoryHtml() {
    if (!Array.isArray(state.historyRuns) || state.historyRuns.length < 2) {
      return '<p class="tr-muted">至少完成两次深层 MBTI 测试后，才会显示前后对比。</p>';
    }
    const prev = state.historyRuns[state.historyRuns.length - 2];
    const cur = state.historyRuns[state.historyRuns.length - 1];
    const labels = {
      IE: ["外向E", "内向I"],
      SN: ["直觉N", "感觉S"],
      TF: ["情感F", "思考T"],
      JP: ["感知P", "判断J"],
    };
    const axisTableTitles = {
      IE: "外向—内向",
      SN: "直觉—感觉",
      TF: "情感—思考",
      JP: "感知—判断",
    };
    const row = (axis) => {
      const p = Number(prev.axisScores?.[axis] || 0);
      const c = Number(cur.axisScores?.[axis] || 0);
      const delta = c - p;
      const pLabel = p >= 0 ? labels[axis][0] : labels[axis][1];
      const cLabel = c >= 0 ? labels[axis][0] : labels[axis][1];
      return `
        <tr>
          <td>${esc(axisTableTitles[axis] || axis)}</td>
          <td>${p > 0 ? "+" : ""}${p}（${esc(pLabel)}）</td>
          <td>${delta > 0 ? "+" : ""}${delta}</td>
          <td>${c > 0 ? "+" : ""}${c}（${esc(cLabel)}）</td>
        </tr>`;
    };
    return `
      <p class="tr-muted">上次：${esc(formatDate(prev.savedAt))} ｜ 本次：${esc(formatDate(cur.savedAt))}</p>
      <table class="tr-history-table">
        <thead>
          <tr>
            <th>维度</th>
            <th>上次</th>
            <th>变化</th>
            <th>本次</th>
          </tr>
        </thead>
        <tbody>
          ${row("IE")}
          ${row("SN")}
          ${row("TF")}
          ${row("JP")}
        </tbody>
      </table>`;
  }

  function getOriginalSpiritAnimalImage(detail, type) {
    const label = String(detail?.spiritAnimal || "").trim();
    if (label) {
      const parts = label.split(/\s+/);
      let animalName = String(parts[parts.length - 1] || "").toLowerCase();
      if (animalName === "dolphin") animalName = "dophin";
      if (animalName) return `${TYT_ASSET_BASE}/animals/${animalName}.jpg`;
    }
    return getSpiritAnimalImage(type);
  }

  async function getLegacyMbtiDetail(type) {
    try {
      const core = window.__DeepTestHubCore__;
      if (!core || typeof core.getMbtiDetail !== "function") return null;
      const legacy = await core.getMbtiDetail(type);
      if (!legacy) return null;
      return {
        code: String(type || "").toUpperCase(),
        name: MBTI_NAMES[String(type || "").toUpperCase()] || String(type || "").toUpperCase(),
        description: legacy.description || "",
        spiritAnimal: legacy.spiritAnimal || "",
        reason: legacy.reason || "",
        personalityTraits: legacy.personalityTraits || "",
        personalGrowth: legacy.personalGrowth || "",
        strengthsWeaknesses: {
          strengths: Array.isArray(legacy.strengths) ? legacy.strengths : [],
          weaknesses: Array.isArray(legacy.weaknesses) ? legacy.weaknesses : [],
        },
        whatEnergizesYou: legacy.energizes || "",
        whatDrainsYou: legacy.drains || "",
        careerInsights: {
          careerPath: legacy.careerPath || "",
          careerStrengthsWeaknesses: {
            strengths: Array.isArray(legacy.careerStrengths) ? legacy.careerStrengths : [],
            weaknesses: Array.isArray(legacy.careerWeaknesses) ? legacy.careerWeaknesses : [],
          },
          careerIdeas: Array.isArray(legacy.careerIdeas) ? legacy.careerIdeas : [],
          workspaceHabits: legacy.workspaceHabits || "",
        },
        relationshipsConnections: {
          yourRelationships: legacy.relationships || "",
          relationshipStrengthsWeaknesses: {
            strengths: Array.isArray(legacy.relStrengths) ? legacy.relStrengths : [],
            weaknesses: Array.isArray(legacy.relWeaknesses) ? legacy.relWeaknesses : [],
          },
          yourLoveLanguage: legacy.loveLanguage || "",
        },
        socialCirclesFamilyLife: {
          friendships: {
            description: legacy.friendships || "",
            strengths: Array.isArray(legacy.friendStrengths) ? legacy.friendStrengths : [],
            weaknesses: Array.isArray(legacy.friendWeaknesses) ? legacy.friendWeaknesses : [],
          },
          parenthood: {
            description: legacy.parenthood || "",
            strengths: Array.isArray(legacy.parentStrengths) ? legacy.parentStrengths : [],
            weaknesses: Array.isArray(legacy.parentWeaknesses) ? legacy.parentWeaknesses : [],
          },
        },
        culturalConnections: {
          famousMatches: Array.isArray(legacy.famousMatches) ? legacy.famousMatches.map((item) => item?.name).filter(Boolean) : [],
        },
      };
    } catch (_) {
      return null;
    }
  }

  async function getOriginalMbtiDetail(type) {
    const code = String(type || "").trim().toUpperCase();
    return SOURCE_PERSONALITY_TYPES[code] || await getLegacyMbtiDetail(code) || null;
  }

  const MBTI_LETTER_LABELS = {
    I: "内向沉淀",
    E: "外向互动",
    N: "抽象洞察",
    S: "现实细节",
    T: "理性判断",
    F: "价值共情",
    J: "规划收束",
    P: "灵活探索",
  };

  const MBTI_STRENGTH_HINTS = {
    I: "能够在相对安静的环境里独立思考，把问题想深想透。",
    E: "愿意主动打开交流，把信息带进讨论并推动气氛流动。",
    N: "擅长从现象里看到趋势、模式和长期可能性。",
    S: "重视事实、细节和可执行性，判断更稳。",
    T: "面对复杂问题时，能优先抓住逻辑与结构。",
    F: "能注意到关系、氛围和价值取向，对人更敏感。",
    J: "有规划感，能把任务推进到落地和收束。",
    P: "面对变化适应快，能在不完整信息里继续前进。",
  };

  const MBTI_RISK_HINTS = {
    I: "如果长期只在内部消化问题，容易错过外部反馈。",
    E: "在节奏很快的互动中，可能比沉淀更早给出结论。",
    N: "当想法过多时，容易出现发散过度或落地不足。",
    S: "如果过于依赖经验，可能会忽略新机会和新路径。",
    T: "逻辑优先时，容易让他人感受到距离感或压迫感。",
    F: "过度顾及感受时，容易延迟必要的边界判断。",
    J: "过早定稿会让自己在变化场景里显得僵硬。",
    P: "保持开放很有优势，但也要注意节奏和收尾质量。",
  };

  const MBTI_ANIMAL_LABELS = {
    beaver: "河狸",
    deer: "鹿",
    wolf: "狼",
    owl: "猫头鹰",
    cat: "猫",
    butterfly: "蝴蝶",
    panda: "熊猫",
    fox: "狐狸",
    cheetah: "猎豹",
    otter: "水獭",
    dophin: "海豚",
    raven: "渡鸦",
    lion: "狮子",
    elephant: "大象",
    horse: "马",
    eagle: "鹰",
  };

  const MBTI_FAMILY_META = {
    NT: {
      path: "策略、研究、产品、技术、分析类场景",
      ideas: ["策略研究", "产品规划", "技术方案", "商业分析", "创新项目"],
      workspace: "更适合有独立判断空间、允许深度思考和系统推演的工作环境。",
      relationship: "更看重认知匹配、沟通效率和长期成长感。",
      friendship: "在朋友关系里更重视价值观和判断质量，宁缺毋滥。",
      parenting: "倾向于用结构、原则和长期视角来支持家人。",
    },
    NF: {
      path: "咨询、教育、内容、品牌、组织发展类场景",
      ideas: ["教育培训", "内容策划", "咨询辅导", "品牌传播", "社区运营"],
      workspace: "更适合有人际连接、愿景驱动且允许表达价值感的工作环境。",
      relationship: "更看重真诚、共鸣和关系中的共同成长。",
      friendship: "在朋友关系里常扮演理解者、连接者或鼓励者。",
      parenting: "更重视情感支持、价值引导和长期影响。",
    },
    SJ: {
      path: "运营、项目、行政、质量、交付管理类场景",
      ideas: ["项目管理", "运营管理", "行政支持", "质量控制", "流程优化"],
      workspace: "更适合边界清晰、节奏稳定、标准明确的工作环境。",
      relationship: "更看重稳定、责任感和可持续投入。",
      friendship: "在朋友关系里往往可靠、守时、愿意长期提供支持。",
      parenting: "更重视规则感、安全感和持续性的陪伴。",
    },
    SP: {
      path: "体验、创意、现场执行、用户沟通类场景",
      ideas: ["用户运营", "活动执行", "产品体验", "创意表达", "一线协作"],
      workspace: "更适合反馈直接、变化真实、能够边做边调的工作环境。",
      relationship: "更看重真实感、现场回应和相处中的轻松流动。",
      friendship: "在朋友关系里更容易带来活力、陪伴和即时支持。",
      parenting: "更重视体验式陪伴、灵活应对和情境反馈。",
    },
  };

  function buildChineseSpiritAnimal(type) {
    const file = String(SPIRIT_ANIMAL_FILE_MAP[String(type || "").toUpperCase()] || "").replace(/\.jpg$/i, "");
    const label = MBTI_ANIMAL_LABELS[file] || "象征动物";
    return {
      label,
      reason: `${label}象征你当前更稳定的一面: 在熟悉节奏里形成自己的判断，并按自己的方式持续推进。`,
    };
  }

  function buildChineseMbtiDetail(type) {
    const code = String(type || "").trim().toUpperCase();
    const family = `${code[1] || "N"}${code[2] || "T"}`;
    const familyMeta = MBTI_FAMILY_META[family] || MBTI_FAMILY_META.NT;
    const animal = buildChineseSpiritAnimal(code);
    const letters = code.split("").filter(Boolean);
    const summary = letters.map((letter) => MBTI_LETTER_LABELS[letter]).filter(Boolean);
    const strengths = letters.map((letter) => MBTI_STRENGTH_HINTS[letter]).filter(Boolean);
    const weaknesses = letters.map((letter) => MBTI_RISK_HINTS[letter]).filter(Boolean);
    const outerMode = code[0] === "I" ? "先在内部沉淀，再输出结论" : "先在互动里摸清信息，再形成判断";
    const energyMode = code[0] === "I" ? "独立空间、连续专注和高质量深聊" : "交流反馈、协作推进和即时互动";
    const drainMode = code[0] === "I" ? "高频打断、无效社交和被迫持续外放" : "长期独处、反馈稀缺和气氛停滞";
    const relationshipMode = code[2] === "F"
      ? "你更容易从感受、关系和价值一致性判断一段关系是否值得投入。"
      : "你更容易从逻辑、边界和相处效率判断一段关系是否稳定。";
    const loveLanguage = code[2] === "F"
      ? "更偏向肯定表达、情绪回应和被认真理解。"
      : "更偏向行动支持、可靠兑现和高质量陪伴。";
    return {
      code,
      name: MBTI_NAMES[code] || code,
      description: `${MBTI_NAMES[code] || code}（${code}）当前呈现为 ${summary.join(" / ")} 的组合，更容易在明确目标下形成自己的稳定节奏。`,
      spiritAnimal: animal.label,
      reason: animal.reason,
      personalityTraits: `${MBTI_NAMES[code] || code}型通常会以“${outerMode}”的方式处理信息，并在 ${summary.join("、")} 之间建立自己的工作风格。`,
      personalGrowth: `下一步更值得关注的是把已有优势用得更平衡一些，尤其注意：${weaknesses.slice(0, 2).join("；")}`,
      strengthsWeaknesses: {
        strengths,
        weaknesses,
      },
      whatEnergizesYou: `最容易让你进入状态的通常是：${energyMode}。`,
      whatDrainsYou: `最容易消耗你的通常是：${drainMode}。`,
      careerInsights: {
        careerPath: `${MBTI_NAMES[code] || code}型更适合 ${familyMeta.path}。当任务允许你按自己的节奏持续推进时，优势会更稳定。`,
        careerStrengthsWeaknesses: {
          strengths: strengths.slice(0, 3),
          weaknesses: weaknesses.slice(0, 3),
        },
        careerIdeas: familyMeta.ideas,
        workspaceHabits: familyMeta.workspace,
      },
      relationshipsConnections: {
        yourRelationships: `${familyMeta.relationship} ${relationshipMode}`,
        relationshipStrengthsWeaknesses: {
          strengths: strengths.slice(0, 3),
          weaknesses: weaknesses.slice(0, 3),
        },
        yourLoveLanguage: loveLanguage,
      },
      socialCirclesFamilyLife: {
        friendships: {
          description: familyMeta.friendship,
          strengths: strengths.slice(0, 2),
          weaknesses: weaknesses.slice(0, 2),
        },
        parenthood: {
          description: familyMeta.parenting,
          strengths: strengths.slice(1, 3),
          weaknesses: weaknesses.slice(1, 3),
        },
      },
      culturalConnections: {
        famousMatches: [],
      },
      showCulturalConnections: false,
    };
  }

  async function getLocalizedMbtiDetail(type) {
    const original = await getOriginalMbtiDetail(type);
    if (original && hasChineseText(original.description || original.personalityTraits || original.careerPath)) {
      return {
        ...original,
        showCulturalConnections: Array.isArray(original?.culturalConnections?.famousMatches) && original.culturalConnections.famousMatches.length > 0,
      };
    }
    return buildChineseMbtiDetail(type);
  }

  function originalFamousMatchUrl(typeCode, matchName) {
    const cleanName = String(matchName || "")
      .replace(/\s*\(.*\)\s*/g, "")
      .replace(/\./g, "")
      .replace(/\s+/g, "-")
      .trim();
    const extension = String(matchName || "").trim() === "Lisa Simpson" ? "jpeg" : "png";
    return `${TYT_ASSET_BASE}/famousMatches/${esc(String(typeCode || "").toUpperCase())}/${esc(cleanName)}.${extension}`;
  }

  function renderOriginalColumns(leftTitle, leftItems, rightTitle, rightItems) {
    return `
      <div class="tr-tyt-columns">
        <div>
          <h4>${esc(leftTitle)}</h4>
          ${renderOriginalList(leftItems)}
        </div>
        <div>
          <h4>${esc(rightTitle)}</h4>
          ${renderOriginalList(rightItems)}
        </div>
      </div>`;
  }

  async function renderDeep() {
    const deepStore = state.store?.deep;
    const fallbackCur = state.historyRuns[state.historyRuns.length - 1] || null;
    const result = deepStore?.result || (fallbackCur ? normalizeDeepResult(fallbackCur) : null);
    const completedAt = deepStore?.completedAt || fallbackCur?.savedAt || Date.now();
    const aiText = deepStore?.aiText || "";
    if (!result) return renderEmpty("请先完成深层 MBTI 测试，再查看该页面。");
    const chineseTypeName = MBTI_NAMES[result.type] || result.type;
    const detail = await getLocalizedMbtiDetail(result.type);
    const displayTypeTitle = `${chineseTypeName}（${result.type}）`;
    const typeEmoji = MBTI_EMOJI[result.type] || "🧩";
    const animalUrl = getOriginalSpiritAnimalImage(detail, result.type);
    const famousMatches = Array.isArray(detail?.culturalConnections?.famousMatches)
      ? detail.culturalConnections.famousMatches
      : [];
    const showCulturalConnections = Boolean(detail?.showCulturalConnections && famousMatches.length);

    return `
      <div class="tr-result-grid tr-tyt-detailed-page">
        <header class="tr-tyt-detailed-header">
          <img src="${esc(animalUrl)}" alt="${esc(detail?.spiritAnimal || result.type)}" class="tr-tyt-detailed-animal">
          <div class="tr-tyt-detailed-emoji">${esc(typeEmoji)}</div>
          <p class="tr-tyt-overline">深层 MBTI · 中文结果</p>
          <h2>${esc(displayTypeTitle)}</h2>
          <p class="tr-tyt-header-desc">${esc(detail?.description || `已完成 ${Number(result.answeredCount || 52)} / 52 题。`)}</p>
          <p class="tr-tyt-header-meta">类型代号：${esc(result.type)} ｜ 心灵动物：${esc(detail?.spiritAnimal || "—")} ｜ 完成时间：${esc(formatDate(completedAt))}</p>
        </header>

        <article class="tr-tyt-card">
          <h3>维度一览</h3>
          <div class="tr-dim-grid">${deepRowsHtml(result)}</div>
        </article>

        <article class="tr-tyt-card">
          <h3>AI 深度分析</h3>
          ${aiText
            ? `<p class="tr-tyt-copy">${esc(aiText).replace(/\n/g, "<br>")}</p>`
            : `<p class="tr-muted">还没有生成 AI 深度分析，可在本页面直接生成。</p>
               <div class="tr-empty-actions">
                 <button id="trAiGenerateBtn" type="button" class="tr-btn ghost sm" ${state.deepAiLoading ? "disabled" : ""}>
                   ${state.deepAiLoading ? "生成中..." : "生成 AI 深度分析"}
                 </button>
               </div>`}
        </article>

        <article class="tr-tyt-card">
          <h3>人格总览</h3>
          <p class="tr-tyt-copy"><strong>人格特质：</strong> ${esc(detail.personalityTraits || "")}</p>
          <div class="tr-tyt-subsection">
            <h4>心灵动物</h4>
            <p class="tr-tyt-copy">${esc(detail.spiritAnimal || "")}${detail.reason ? `：${esc(detail.reason)}` : ""}</p>
          </div>
          <div class="tr-tyt-subsection">
            <h4>个人成长</h4>
            <p class="tr-tyt-copy">${esc(detail.personalGrowth || "")}</p>
          </div>
          ${renderOriginalColumns(
            "优势",
            detail.strengthsWeaknesses?.strengths || [],
            "注意点",
            detail.strengthsWeaknesses?.weaknesses || []
          )}
          <div class="tr-tyt-columns">
            <div>
              <h4>什么会为你充电</h4>
              <p class="tr-tyt-copy">${esc(detail.whatEnergizesYou || "")}</p>
            </div>
            <div>
              <h4>什么容易消耗你</h4>
              <p class="tr-tyt-copy">${esc(detail.whatDrainsYou || "")}</p>
            </div>
          </div>
        </article>

        <article class="tr-tyt-card">
          <h3>职业与发展</h3>
          <p class="tr-tyt-copy">${esc(detail.careerInsights?.careerPath || "")}</p>
          ${renderOriginalColumns(
            "职场优势",
            detail.careerInsights?.careerStrengthsWeaknesses?.strengths || [],
            "职场挑战",
            detail.careerInsights?.careerStrengthsWeaknesses?.weaknesses || []
          )}
          <div class="tr-tyt-subsection">
            <h4>可能适合你的职业方向</h4>
            ${renderOriginalTags(detail.careerInsights?.careerIdeas || [])}
          </div>
          <div class="tr-tyt-subsection">
            <h4>工作习惯与偏好</h4>
            <p class="tr-tyt-copy">${esc(detail.careerInsights?.workspaceHabits || "")}</p>
          </div>
        </article>

        <article class="tr-tyt-card">
          <h3>关系与连结</h3>
          <p class="tr-tyt-copy">${esc(detail.relationshipsConnections?.yourRelationships || "")}</p>
          ${renderOriginalColumns(
            "关系中的优势",
            detail.relationshipsConnections?.relationshipStrengthsWeaknesses?.strengths || [],
            "关系中的陷阱",
            detail.relationshipsConnections?.relationshipStrengthsWeaknesses?.weaknesses || []
          )}
          <div class="tr-tyt-subsection">
            <h4>爱的语言倾向</h4>
            <p class="tr-tyt-copy">${esc(detail.relationshipsConnections?.yourLoveLanguage || "")}</p>
          </div>
        </article>

        <article class="tr-tyt-card">
          <h3>社交圈与家庭生活</h3>
          <div class="tr-tyt-subsection">
            <h4>友谊</h4>
            <p class="tr-tyt-copy">${esc(detail.socialCirclesFamilyLife?.friendships?.description || "")}</p>
            ${renderOriginalColumns(
              "优势",
              detail.socialCirclesFamilyLife?.friendships?.strengths || [],
              "注意点",
              detail.socialCirclesFamilyLife?.friendships?.weaknesses || []
            )}
          </div>
          <div class="tr-tyt-subsection">
            <h4>为人父母</h4>
            <p class="tr-tyt-copy">${esc(detail.socialCirclesFamilyLife?.parenthood?.description || "")}</p>
            ${renderOriginalColumns(
              "优势",
              detail.socialCirclesFamilyLife?.parenthood?.strengths || [],
              "注意点",
              detail.socialCirclesFamilyLife?.parenthood?.weaknesses || []
            )}
          </div>
        </article>

        ${showCulturalConnections ? `
        <article class="tr-tyt-card">
          <h3>文化连结</h3>
          <p class="tr-tyt-copy">仅供参考：以下名人或虚构角色可能与你同属一类人格气质（娱乐向对照）。</p>
          <div class="tr-tyt-famous-grid">
            ${famousMatches.map((match) => `
              <article class="tr-tyt-famous-card">
                <img src="${originalFamousMatchUrl(result.type, match)}" alt="${esc(match)}" onerror="this.remove()">
                <p>${esc(match)}</p>
              </article>
            `).join("")}
          </div>
        </article>` : ""}

        <article class="tr-tyt-card">
          <h3>最近两次测试对比</h3>
          ${deepHistoryHtml()}
        </article>
      </div>`;
  }

  function currentDeepResult() {
    const deepStore = state.store?.deep;
    if (deepStore?.result) return deepStore.result;
    const fallbackCur = state.historyRuns[state.historyRuns.length - 1] || null;
    return fallbackCur ? normalizeDeepResult(fallbackCur) : null;
  }

  function buildDeepDimDetails(result) {
    if (!result) return [];
    return [
      { axis: "IE", label: result.axisScores.IE >= 0 ? "外向(E)" : "内向(I)", score: result.axisScores.IE },
      { axis: "SN", label: result.axisScores.SN >= 0 ? "直觉(N)" : "感觉(S)", score: result.axisScores.SN },
      { axis: "TF", label: result.axisScores.TF >= 0 ? "情感(F)" : "思考(T)", score: result.axisScores.TF },
      { axis: "JP", label: result.axisScores.JP >= 0 ? "感知(P)" : "判断(J)", score: result.axisScores.JP },
    ];
  }

  async function generateDeepAi() {
    if (state.deepAiLoading) return;
    const result = currentDeepResult();
    if (!result) return;
    state.deepAiLoading = true;
    renderResult();
    try {
      const data = await requestJson("/api/deep-test-analysis", {
        method: "POST",
        body: JSON.stringify({
          mbti_type: result.type,
          scores: result.axisScores,
          dimension_details: buildDeepDimDetails(result),
        }),
      });
      const text = String(data?.analysis || "").trim();
      if (!text) throw new Error("分析内容为空");
      if (!state.store || typeof state.store !== "object") {
        state.store = { friends: null, insideout: null, deep: null };
      }
      state.store.deep = {
        result: result,
        aiText: text,
        completedAt: state.store.deep?.completedAt || Date.now(),
      };
      persistStoreData();
      renderResult();
    } catch (err) {
      window.alert(`AI 分析生成失败：${String(err?.message || err)}`);
    } finally {
      state.deepAiLoading = false;
      renderResult();
    }
  }

  function bindResultActionEvents() {
    const startBtn = document.getElementById("trStartTestBtn");
    if (startBtn) startBtn.onclick = toRetest;

    const emptyBackBtn = document.getElementById("trBackMainFromEmptyBtn");
    if (emptyBackBtn) emptyBackBtn.onclick = toMainProfile;

    const aiBtn = document.getElementById("trAiGenerateBtn");
    if (aiBtn) aiBtn.onclick = generateDeepAi;
  }

  async function renderResult() {
    const root = document.getElementById("trResultRoot");
    if (!root) return;
    if (state.testType === "friends") {
      root.innerHTML = renderGame(state.store?.friends, FRIENDS_SCORE_LABELS);
      bindResultActionEvents();
      return;
    }
    if (state.testType === "insideout") {
      root.innerHTML = renderGame(state.store?.insideout, INSIDEOUT_SCORE_LABELS);
      bindResultActionEvents();
      return;
    }
    root.innerHTML = await renderDeep();
    bindResultActionEvents();
  }

  function updateTopUser(user) {
    const label = document.getElementById("currentUserLabel");
    const avatar = document.getElementById("currentUserAvatar");
    const display = String(user?.display_name || user?.displayName || user?.username || "未登录");
    if (label) label.textContent = display;
    if (avatar) avatar.textContent = display.slice(0, 1).toUpperCase();
  }

  function toMainProfile() {
    if (typeof window.goBackToLastInterface === "function") {
      window.goBackToLastInterface("/main.html#profile");
      return;
    }
    window.location.href = "/main.html#profile";
  }

  function toRetest() {
    const safe = sanitizeTestType(state.testType);
    window.location.href = `/test-runner.html?test=${encodeURIComponent(safe)}&restart=1`;
  }

  async function doLogout() {
    try {
      await requestJson("/api/auth/logout", { method: "POST" });
    } catch (_) {}
    window.location.href = "/main.html";
  }

  function bindEvents() {
    document.querySelectorAll(".tr-nav-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nextType = sanitizeTestType(btn.dataset.test || "");
        if (nextType === state.testType) return;
        state.testType = nextType;
        setTestTypeToUrl(nextType, false);
        setHeaderByType();
        setActiveNav();
        renderResult();
      });
    });

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) logoutBtn.addEventListener("click", doLogout);

    const avatarBtn = document.getElementById("trAvatarBtn");
    if (avatarBtn) avatarBtn.addEventListener("click", () => {
      window.location.href = "/user-center.html#report-workspace";
    });

    const backBtn = document.getElementById("trBackBtn");
    if (backBtn) backBtn.addEventListener("click", toMainProfile);

    const retestBtn = document.getElementById("trRetestBtn");
    if (retestBtn) retestBtn.addEventListener("click", toRetest);

    window.addEventListener("popstate", () => {
      state.testType = parseTestTypeFromUrl();
      setHeaderByType();
      setActiveNav();
      renderResult();
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
    const ok = await initAuth().catch(() => false);
    if (!ok) return;
    state.testType = parseTestTypeFromUrl();
    setTestTypeToUrl(state.testType, true);
    setHeaderByType();
    setActiveNav();
    loadStoreData();
    loadHistoryRuns();
    renderResult();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
