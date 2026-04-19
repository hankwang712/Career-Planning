(function initCareerGraphMatchingModule() {
  const LS_MATCH_RESULTS = "career_match_results";
  const LS_MATCH_PROFILE = "career_match_profile";
  const LS_MATCH_META = "career_match_meta";

  const GRAPH_NODE_LIMIT = 500;
  const DEFAULT_SEARCH_RESULT_LIMIT = 10;
  const RELATION_META = {
    promotion: { label: "晋升", color: "#22c55e", dash: "4,3" },
    substitution: { label: "换岗", color: "#3b82f6", dash: "2,2" }
  };
  const NODE_VISUALS = {
    default: { shellFill: "#ffffff", shellStroke: "#c7d2fe", coreFill: "#3b47d6", coreStroke: "#2535b8", label: "#172554" },
    query: { shellFill: "#ffffff", shellStroke: "#93c5fd", coreFill: "#2563eb", coreStroke: "#1d4ed8", label: "#172554" },
    recommended: { shellFill: "#fffbeb", shellStroke: "#fcd34d", coreFill: "#f59e0b", coreStroke: "#d97706", label: "#78350f" },
    selected: { shellFill: "#fff1f2", shellStroke: "#fda4af", coreFill: "#ef4444", coreStroke: "#dc2626", label: "#7f1d1d" },
    promotion: { shellFill: "#ecfdf3", shellStroke: "#86efac", coreFill: "#22c55e", coreStroke: "#16a34a", label: "#166534" },
    transfer: { shellFill: "#eff6ff", shellStroke: "#93c5fd", coreFill: "#3b82f6", coreStroke: "#1d4ed8", label: "#1e3a8a" },
    muted: { shellFill: "#ffffff", shellStroke: "#dbe2ea", coreFill: "#cbd5e1", coreStroke: "#94a3b8", label: "#94a3b8" }
  };
  const NODE_VISUAL_ORDER = {
    muted: 0,
    default: 1,
    query: 2,
    recommended: 3,
    transfer: 4,
    promotion: 5,
    selected: 6
  };

  const state = {
    bootstrap: null,
    bootstrapPromise: null,
    profile: null,
    nodeMap: new Map(),
    edgeList: [],
    edgeByNode: new Map(),
    baseNodeIds: [],
    displayNodeIds: [],
    detailCache: new Map(),
    selectedNodeId: "",
    searchQuery: "",
    relationFilter: "all",
    layoutMode: "force",
    pathOnly: false,
    visibilityPauseBound: false,
    currentDisplayEdges: [],   // 供 updateVisualStates 复用，避免重建 simulation
    queryResultIds: new Set(),
    recommendationIds: new Set(),
    matchResults: [],
    matchMeta: null,
    cityPreferences: [],
    suggestedCities: [],
    positions: new Map(),
    simulation: null,
    svg: null,
    svgRoot: null,
    graphLayer: null,
    zoom: null,
    viewportFocusToken: 0,
    bound: false,
    renderTicket: 0,
    profileSignature: ""
  };

  function getEl(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function normalizeText(value) {
    return String(value == null ? "" : value).trim().toLowerCase();
  }

  function unique(values, limit = 999) {
    const seen = new Set();
    const result = [];
    (Array.isArray(values) ? values : []).forEach((raw) => {
      const value = String(raw || "").trim();
      if (!value || seen.has(value)) return;
      seen.add(value);
      result.push(value);
    });
    return result.slice(0, limit);
  }

  function splitCityTokens(value) {
    const rawValues = Array.isArray(value) ? value : [value];
    return unique(
      rawValues.flatMap((raw) => String(raw == null ? "" : raw)
        .split(/[,\u3001;；/|｜\s]+/)
        .map((item) => item.trim())
        .filter(Boolean)),
      12
    );
  }

  function getProfileCityTokens() {
    return splitCityTokens([
      state.profile?.basics?.target_city,
      state.profile?.basics?.targetCity
    ]);
  }

  function getActiveCityPreferences() {
    const chosen = splitCityTokens(state.cityPreferences);
    return chosen.length ? chosen : getProfileCityTokens();
  }

  function buildSuggestedCities(nodes) {
    const counts = new Map();
    (Array.isArray(nodes) ? nodes : []).forEach((node) => {
      const city = String(node?.city || "").trim();
      if (!city) return;
      counts.set(city, (counts.get(city) || 0) + 1);
    });
    const profileCities = getProfileCityTokens();
    const ranked = Array.from(counts.entries())
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0], "zh-Hans-CN"))
      .map(([city]) => city);
    return unique([...profileCities, ...ranked], 12);
  }

  function cityIsSelected(city) {
    const normalized = String(city || "").trim();
    return Boolean(normalized && splitCityTokens(state.cityPreferences).includes(normalized));
  }

  function clearCareerMatchStorage(options = {}) {
    const shouldClearRemote = Boolean(options && options.clearRemote);
    try {
      localStorage.removeItem(LS_MATCH_RESULTS);
      localStorage.removeItem(LS_MATCH_PROFILE);
      localStorage.removeItem(LS_MATCH_META);
      sessionStorage.removeItem(LS_MATCH_RESULTS);
      sessionStorage.removeItem(LS_MATCH_PROFILE);
    } catch (_) { /* ignore */ }
    if (
      shouldClearRemote
      && typeof window.isAuthenticatedUser === "function"
      && window.isAuthenticatedUser()
      && typeof window.mergeScopedUserState === "function"
    ) {
      void window.mergeScopedUserState("career_matching", {
        updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
        graph_match_bundle: {}
      });
    }
  }

  function buildMatchProfilePayload() {
    return {
      summary: state.profile?.summary || "",
      basics: state.profile?.basics || {},
      assessment: state.profile?.assessment || {},
      matchSource: matchSourceLabel(),
      matchBasis: matchBasisHint(),
      cityPreferences: state.cityPreferences || []
    };
  }

  function getScopedCareerMatchingState() {
    const scoped = window.userWorkspaceState?.scopedData?.career_matching;
    return scoped && typeof scoped === "object" ? scoped : null;
  }

  function persistCareerMatchBundleToAccount(profilePayload) {
    if (
      !state.matchResults.length
      || typeof window.isAuthenticatedUser !== "function"
      || !window.isAuthenticatedUser()
      || typeof window.mergeScopedUserState !== "function"
    ) {
      return;
    }
    const roleRows =
      typeof window.graphMatchResultsToRoleRankings === "function"
        ? window.graphMatchResultsToRoleRankings(state.matchResults)
        : [];
    const patch = {
      updated_at: new Date().toLocaleString("zh-CN", { hour12: false }),
      graph_match_bundle: {
        version: "2026.04-graph-match-v1",
        saved_at: new Date().toLocaleString("zh-CN", { hour12: false }),
        profile_signature: state.profileSignature || "",
        results: Array.isArray(state.matchResults) ? state.matchResults : [],
        meta: state.matchMeta && typeof state.matchMeta === "object" ? state.matchMeta : {},
        profile: profilePayload && typeof profilePayload === "object" ? profilePayload : {},
        city_preferences: Array.isArray(state.cityPreferences) ? state.cityPreferences : []
      }
    };
    if (roleRows.length) {
      patch.role_rankings = roleRows;
      patch.focus_role_id = String(roleRows[0].id || "").trim();
    }
    void window.mergeScopedUserState("career_matching", patch).then(() => {
      if (typeof window.refreshUnifiedExperience === "function") {
        window.refreshUnifiedExperience();
      }
    });
  }

  function persistCareerMatchBundle() {
    if (!state.matchResults.length) return;
    const profilePayload = buildMatchProfilePayload();
    try {
      const metaStr = JSON.stringify(state.matchMeta || {});
      const resultsStr = JSON.stringify(state.matchResults);
      const profileStr = JSON.stringify(profilePayload);
      localStorage.setItem(LS_MATCH_RESULTS, resultsStr);
      localStorage.setItem(LS_MATCH_PROFILE, profileStr);
      localStorage.setItem(LS_MATCH_META, metaStr);
      sessionStorage.setItem(LS_MATCH_RESULTS, resultsStr);
      sessionStorage.setItem(LS_MATCH_PROFILE, profileStr);
    } catch (_) { /* quota / private mode */ }
    persistCareerMatchBundleToAccount(profilePayload);
  }

  /** 进入模块或刷新后恢复上次保存的匹配结果（含城市偏好） */
  function tryRestorePersistedMatch() {
    if (state.matchResults.length) return;
    try {
      const scoped = getScopedCareerMatchingState();
      const bundle = scoped?.graph_match_bundle;
      const results = Array.isArray(bundle?.results) ? bundle.results : [];
      if (results.length) {
        state.matchResults = results;
        state.matchMeta = bundle?.meta && typeof bundle.meta === "object" ? bundle.meta : null;
        state.recommendationIds = new Set(state.matchResults.map((item) => item.id).filter(Boolean));
        const savedCities = Array.isArray(bundle?.city_preferences)
          ? bundle.city_preferences
          : (Array.isArray(bundle?.profile?.cityPreferences) ? bundle.profile.cityPreferences : []);
        if (savedCities.length) {
          state.cityPreferences = splitCityTokens(savedCities);
        }
        return;
      }
    } catch (_) { /* ignore account scope restore */ }
    try {
      const raw = localStorage.getItem(LS_MATCH_RESULTS);
      if (!raw) return;
      const results = JSON.parse(raw);
      if (!Array.isArray(results) || !results.length) return;
      state.matchResults = results;
      const metaRaw = localStorage.getItem(LS_MATCH_META);
      state.matchMeta = metaRaw ? JSON.parse(metaRaw) : null;
      state.recommendationIds = new Set(state.matchResults.map((item) => item.id).filter(Boolean));
      const pRaw = localStorage.getItem(LS_MATCH_PROFILE);
      if (pRaw) {
        const p = JSON.parse(pRaw);
        if (Array.isArray(p.cityPreferences) && p.cityPreferences.length) {
          state.cityPreferences = splitCityTokens(p.cityPreferences);
        }
      }
    } catch (_) { /* ignore */ }
  }

  function setCityPreferences(cities, { resetMatches = true } = {}) {
    state.cityPreferences = splitCityTokens(cities);
    if (resetMatches) {
      state.matchResults = [];
      state.matchMeta = null;
      state.recommendationIds = new Set();
      state.selectedNodeId = "";
    }
    renderCityPlanner();
    renderPathDeck();
    renderDefaultPanel();
    renderGraph();
  }

  function addCityPreference(value) {
    const next = unique([...state.cityPreferences, ...splitCityTokens(value)], 12);
    setCityPreferences(next);
  }

  function removeCityPreference(value) {
    const target = String(value || "").trim();
    setCityPreferences(state.cityPreferences.filter((item) => item !== target));
  }

  function renderCityPlanner() {
    const chips = getEl("knowledgeBaseCityChips");
    const summary = getEl("knowledgeBaseCitySummary");
    if (!chips && !summary) return;

    const selected = splitCityTokens(state.cityPreferences);
    const active = getActiveCityPreferences();
    const suggestions = unique([...selected, ...state.suggestedCities], 12);

    if (summary) {
      summary.textContent = selected.length
        ? `已锁定 ${selected.length} 个城市：${selected.join("、")}`
        : active.length
          ? `未手动选择，将使用画像目标城市：${active.join("、")}`
          : "未选择时不限制城市，优先看画像与岗位能力匹配";
    }

    if (chips) {
      chips.innerHTML = suggestions.length
        ? suggestions.map((city) => `
            <button type="button" class="kb-city-chip${cityIsSelected(city) ? " is-active" : ""}" data-city="${escapeHtml(city)}">
              <span>${escapeHtml(city)}</span>
              ${cityIsSelected(city) ? "<b>已选</b>" : ""}
            </button>
          `).join("")
        : `<span class="kb-city-placeholder">图谱加载后会展示可选城市</span>`;
    }
  }

  function resolveUrl(path) {
    if (typeof window.resolveApiUrl === "function") return window.resolveApiUrl(path);
    const base = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
    if (!base || /^https?:\/\//i.test(path)) return path;
    return `${base}${path.startsWith("/") ? path : `/${path}`}`;
  }

  async function fetchJson(path, options = {}) {
    const response = await fetch(resolveUrl(path), {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {})
      },
      ...options
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.message || `请求失败（${response.status}）`);
    }
    return payload;
  }

  function levelNumber(level) {
    const match = String(level || "").match(/(\d+)/);
    return match ? Number(match[1]) : 0;
  }

  function levelRadius(level) {
    const numeric = levelNumber(level);
    if (numeric >= 5) return 26;
    if (numeric === 4) return 22;
    if (numeric === 3) return 18;
    if (numeric === 2) return 14;
    return 10;
  }

  function formatNumber(value, fixed = 1) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "--";
    return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(fixed);
  }

  function formatSalary(node) {
    const min = Number(node?.salaryMin);
    const max = Number(node?.salaryMax);
    if (!Number.isFinite(min) || !Number.isFinite(max)) return "薪资待定";
    return `${formatNumber(min)}-${formatNumber(max)}k`;
  }

  function formatPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "--";
    return `${Math.round(numeric * 100)}%`;
  }

  function formatScore(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "--";
    return `${Math.round(numeric)}%`;
  }

  function formatTrack(track) {
    if (track === "management") return "管理";
    if (track === "product") return "产品";
    return "专家";
  }

  function profileSignature(profile) {
    return JSON.stringify({
      basics: profile?.basics || {},
      recommendedRoles: profile?.recommendedRoles || [],
      missingItems: profile?.missingItems || [],
      capabilities: Object.fromEntries(
        Object.entries(profile?.capabilities || {}).map(([key, value]) => [key, value?.score ?? null])
      )
    });
  }

  function edgeNodeId(value) {
    return value && typeof value === "object" ? String(value.id || "") : String(value || "");
  }

  function buildSelectedContext(displayEdges, selectedId, trailIds) {
    const promotionIds = new Set();
    const transferIds = new Set();
    if (!selectedId) return { promotionIds, transferIds };

    displayEdges.forEach((edge) => {
      const sourceId = edgeNodeId(edge.source);
      const targetId = edgeNodeId(edge.target);
      if (!sourceId || !targetId) return;

      if (edge.relation === "promotion" && (
        sourceId === selectedId ||
        targetId === selectedId ||
        (trailIds.has(sourceId) && trailIds.has(targetId))
      )) {
        promotionIds.add(sourceId);
        promotionIds.add(targetId);
      }

      if (edge.relation === "substitution" && (sourceId === selectedId || targetId === selectedId)) {
        transferIds.add(sourceId);
        transferIds.add(targetId);
      }
    });

    promotionIds.delete(selectedId);
    transferIds.delete(selectedId);
    return { promotionIds, transferIds };
  }

  function resolveNodeVisualState(nodeId, context) {
    if (nodeId === context.focusId) return "selected";
    if (context.promotionIds.has(nodeId)) return "promotion";
    if (context.transferIds.has(nodeId)) return "transfer";
    if (context.queryIds.size) return context.queryIds.has(nodeId) ? "query" : "muted";
    if (context.recommendationIds.has(nodeId)) return "recommended";
    if (context.focusId) return "muted";
    return "default";
  }

  function edgeIsContextual(edge, context) {
    const sourceId = edgeNodeId(edge.source);
    const targetId = edgeNodeId(edge.target);
    if (!sourceId || !targetId) return false;

    if (context.focusId) {
      if (sourceId === context.focusId || targetId === context.focusId) return true;
      if (edge.relation === "promotion" && context.promotionCluster.has(sourceId) && context.promotionCluster.has(targetId)) return true;
      if (edge.relation === "substitution" && context.transferCluster.has(sourceId) && context.transferCluster.has(targetId)) return true;
      return false;
    }

    if (context.queryIds.size) {
      return context.queryIds.has(sourceId) || context.queryIds.has(targetId);
    }

    if (context.recommendationIds.size) {
      return context.recommendationIds.has(sourceId) || context.recommendationIds.has(targetId);
    }

    return true;
  }

  function nodeVisual(nodeState) {
    return NODE_VISUALS[nodeState] || NODE_VISUALS.default;
  }

  function focusViewportOnNode(nodeId, options = {}) {
    const normalizedId = String(nodeId || "").trim();
    const canvas = getEl("knowledgeBaseCanvas");
    if (!normalizedId || !canvas || !state.svg || !state.zoom || !window.d3) return false;

    const point = state.positions.get(normalizedId);
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return false;

    const width = Math.max(canvas.clientWidth || 0, 640);
    const height = Math.max(canvas.clientHeight || 0, 520);
    const scale = Math.max(1, Number(options.scale || 1.8));
    const duration = Math.max(120, Number(options.duration || 320));
    const focusCenterX = width >= 1180 ? width * 0.5 - 118 : width >= 980 ? width * 0.5 - 72 : width * 0.5;
    const focusCenterY = height * 0.5;
    const transform = window.d3.zoomIdentity
      .translate(focusCenterX - scale * point.x, focusCenterY - scale * point.y)
      .scale(scale);

    state.svg
      .transition()
      .duration(duration)
      .ease(window.d3.easeCubicOut)
      .call(state.zoom.transform, transform);
    return true;
  }

  function scheduleViewportFocus(nodeId, options = {}) {
    const normalizedId = String(nodeId || "").trim();
    if (!normalizedId) return;

    state.viewportFocusToken += 1;
    const token = state.viewportFocusToken;
    const delays = options.delays || [0, 160, 360];
    delays.forEach((delay, index) => {
      window.setTimeout(() => {
        if (state.viewportFocusToken !== token) return;
        if (state.selectedNodeId !== normalizedId) return;
        void focusViewportOnNode(normalizedId, {
          scale: options.scale || 1.85,
          duration: index === 0 ? 320 : 220
        });
      }, delay);
    });
  }

  function setStatus(text, variant = "ready") {
    const el = getEl("knowledgeBaseStatus");
    if (!el) return;
    el.textContent = text;
    el.style.color = variant === "error" ? "#dc2626" : variant === "warning" ? "#d97706" : "#2563eb";
    el.style.background = variant === "error" ? "#fef2f2" : variant === "warning" ? "#fff7ed" : "#f5f8ff";
    el.style.borderColor = variant === "error" ? "#fecaca" : variant === "warning" ? "#fed7aa" : "#dbe4ff";
  }

  function showToast(title, message, type = "info") {
    if (typeof window.showToast === "function") {
      window.showToast(title, message, type, 2200);
    }
  }

  function buildSearchText(node) {
    return normalizeText([
      node.title,
      node.family,
      node.subDomain,
      node.cluster,
      node.city,
      node.industry,
      ...(node.skills || [])
    ].join(" "));
  }

  function sortByPriority(nodes) {
    return nodes.slice().sort((left, right) => {
      const richnessDiff = Number(right.relationRichnessScore || 0) - Number(left.relationRichnessScore || 0);
      if (richnessDiff) return richnessDiff;
      const balanceDiff = Number(right.relationBalanceScore || 0) - Number(left.relationBalanceScore || 0);
      if (balanceDiff) return balanceDiff;
      const bridgeDiff = Number(right.relationshipBridgeScore || 0) - Number(left.relationshipBridgeScore || 0);
      if (bridgeDiff) return bridgeDiff;
      const degreeDiff = Number(right.degree || 0) - Number(left.degree || 0);
      if (degreeDiff) return degreeDiff;
      const levelDiff = levelNumber(right.level) - levelNumber(left.level);
      if (levelDiff) return levelDiff;
      return String(left.title || "").localeCompare(String(right.title || ""), "zh-Hans-CN");
    });
  }

  function buildRelationStats(nodeId) {
    const stats = {
      promotionIn: 0,
      promotionOut: 0,
      substitution: 0,
      total: 0
    };
    (state.edgeByNode.get(String(nodeId || "")) || []).forEach((edge) => {
      if (edge.relation === "promotion") {
        if (String(edge.source || "") === String(nodeId || "")) stats.promotionOut += 1;
        if (String(edge.target || "") === String(nodeId || "")) stats.promotionIn += 1;
      } else if (edge.relation === "substitution") {
        stats.substitution += 1;
      }
    });
    stats.total = stats.promotionIn + stats.promotionOut + stats.substitution;
    return stats;
  }

  function decorateNodeRelationPriority(node) {
    const relationStats = buildRelationStats(node.id);
    const promotionTotal = relationStats.promotionIn + relationStats.promotionOut;
    const balanceScore = Math.min(promotionTotal, relationStats.substitution);
    const bridgeScore = (relationStats.promotionIn > 0 ? 1 : 0) + (relationStats.promotionOut > 0 ? 1 : 0) + (relationStats.substitution > 0 ? 1 : 0);
    const richnessScore = (
      balanceScore * 15 +
      promotionTotal * 7 +
      relationStats.substitution * 6 +
      Number(node.degree || 0) * 1.6 +
      levelNumber(node.level) * 1.5
    );
    return {
      ...node,
      relationStats,
      relationBalanceScore: balanceScore,
      relationshipBridgeScore: bridgeScore,
      relationRichnessScore: richnessScore
    };
  }

  function buildBaseNodeIds(nodes) {
    const prioritizedNodes = sortByPriority(nodes.map((node) => decorateNodeRelationPriority(node)));
    const primaryTarget = Math.max(280, Math.floor(GRAPH_NODE_LIMIT * 0.72));
    const chosen = new Set(prioritizedNodes.slice(0, primaryTarget).map((node) => node.id));

    const grouped = new Map();
    prioritizedNodes.forEach((node) => {
      const family = String(node.family || "其他");
      if (!grouped.has(family)) grouped.set(family, []);
      if (!chosen.has(node.id)) grouped.get(family).push(node.id);
    });

    const families = Array.from(grouped.keys()).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
    const result = Array.from(chosen);
    let exhausted = false;
    let index = 0;

    while (result.length < GRAPH_NODE_LIMIT && !exhausted) {
      exhausted = true;
      families.forEach((family) => {
        const items = grouped.get(family) || [];
        if (items[index]) {
          result.push(items[index]);
          exhausted = false;
        }
      });
      index += 1;
    }
    return result.slice(0, GRAPH_NODE_LIMIT);
  }

  function addEdgeToNodeMap(map, edge) {
    [edge.source, edge.target].forEach((nodeId) => {
      if (!map.has(nodeId)) map.set(nodeId, []);
      map.get(nodeId).push(edge);
    });
  }

  async function ensureBootstrap() {
    if (state.bootstrap) return state.bootstrap;
    if (!state.bootstrapPromise) {
      state.bootstrapPromise = fetchJson("/api/career-graph/bootstrap")
        .then((payload) => {
          state.bootstrap = payload;
          const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
          const edges = Array.isArray(payload.edges) ? payload.edges : [];
          state.nodeMap = new Map(nodes.map((node) => [String(node.id || ""), { ...node, __searchText: buildSearchText(node) }]));
          state.edgeList = edges.map((edge) => ({
            ...edge,
            source: String(edge.source || ""),
            target: String(edge.target || "")
          })).filter((edge) => edge.source && edge.target && state.nodeMap.has(edge.source) && state.nodeMap.has(edge.target));
          state.edgeByNode = new Map();
          state.edgeList.forEach((edge) => addEdgeToNodeMap(state.edgeByNode, edge));
          state.baseNodeIds = buildBaseNodeIds(Array.from(state.nodeMap.values()));
          state.suggestedCities = buildSuggestedCities(nodes);
          renderCityPlanner();
          return payload;
        })
        .catch((error) => {
          state.bootstrapPromise = null;
          setStatus("图谱加载失败", "error");
          throw error;
        });
    }
    return state.bootstrapPromise;
  }

  function searchAllNodes(query, limit = DEFAULT_SEARCH_RESULT_LIMIT) {
    const normalized = normalizeText(query);
    if (!normalized) return [];
    const tokens = normalized.split(/\s+/).filter(Boolean);
    return Array.from(state.nodeMap.values())
      .map((node) => {
        let score = 0;
        const title = normalizeText(node.title);
        const family = normalizeText(node.family);
        const text = node.__searchText || "";
        tokens.forEach((token) => {
          if (title.startsWith(token)) score += 48;
          if (title.includes(token)) score += 36;
          if (family.includes(token)) score += 18;
          if (text.includes(token)) score += 10;
        });
        return score ? { node, score } : null;
      })
      .filter(Boolean)
      .sort((left, right) => right.score - left.score || Number(right.node.degree || 0) - Number(left.node.degree || 0))
      .slice(0, limit)
      .map((item) => item.node);
  }

  function getEdgesForNode(nodeId, relation = "all") {
    return (state.edgeByNode.get(String(nodeId || "")) || []).filter((edge) => relation === "all" || edge.relation === relation);
  }

  function getOtherNodeId(edge, nodeId) {
    return edge.source === nodeId ? edge.target : edge.source;
  }

  function getCurrentFocusNodeId() {
    if (state.selectedNodeId && state.nodeMap.has(state.selectedNodeId)) return state.selectedNodeId;
    const firstMatch = state.matchResults[0]?.id;
    if (firstMatch && state.nodeMap.has(firstMatch)) return String(firstMatch);
    return "";
  }

  function getActiveNodeLimit() {
    if (state.searchQuery || state.selectedNodeId || state.pathOnly) return GRAPH_NODE_LIMIT;
    if (state.matchResults.length) return Math.min(GRAPH_NODE_LIMIT, 360);
    return Math.min(GRAPH_NODE_LIMIT, 260);
  }

  function buildPromotionTrail(nodeId, direction = "out", maxHops = 4) {
    const trail = [];
    let currentId = String(nodeId || "");
    const visited = new Set();
    while (currentId && trail.length < maxHops) {
      visited.add(currentId);
      const candidates = getEdgesForNode(currentId, "promotion")
        .filter((edge) => (direction === "out" ? edge.source === currentId : edge.target === currentId))
        .sort((left, right) => Number(right.confidence || 0) - Number(left.confidence || 0));
      if (!candidates.length) break;
      const nextId = direction === "out" ? candidates[0].target : candidates[0].source;
      if (!nextId || visited.has(nextId)) break;
      trail.push(nextId);
      currentId = nextId;
    }
    return trail;
  }

  function expandContext(seedIds, options = {}) {
    const limit = Number(options.limit || GRAPH_NODE_LIMIT);
    const includeBaseFill = Boolean(options.includeBaseFill);
    const relationFilter = options.relationFilter || "all";
    const queue = unique(seedIds);
    const selected = new Set(queue.filter((id) => state.nodeMap.has(id)));

    while (queue.length && selected.size < limit) {
      const nodeId = queue.shift();
      const neighbors = getEdgesForNode(nodeId, relationFilter)
        .slice()
        .sort((left, right) => Number(right.confidence || 0) - Number(left.confidence || 0));
      neighbors.forEach((edge) => {
        const nextId = getOtherNodeId(edge, nodeId);
        if (!nextId || selected.has(nextId) || !state.nodeMap.has(nextId) || selected.size >= limit) return;
        selected.add(nextId);
        queue.push(nextId);
      });
    }

    if (includeBaseFill && selected.size < limit) {
      state.baseNodeIds.forEach((nodeId) => {
        if (selected.size >= limit) return;
        if (state.nodeMap.has(nodeId)) selected.add(nodeId);
      });
    }

    return Array.from(selected).slice(0, limit);
  }

  function computeDisplayNodeIds() {
    const relationFilter = state.relationFilter === "all" ? "all" : state.relationFilter;
    const activeLimit = getActiveNodeLimit();
    const queryMatches = state.searchQuery ? searchAllNodes(state.searchQuery, state.nodeMap.size || 2000) : [];
    state.queryResultIds = new Set(queryMatches.map((node) => node.id));

    if (state.pathOnly && state.selectedNodeId) {
      const seeds = [
        state.selectedNodeId,
        ...buildPromotionTrail(state.selectedNodeId, "out", 4),
        ...buildPromotionTrail(state.selectedNodeId, "in", 3),
        ...getEdgesForNode(state.selectedNodeId, relationFilter).map((edge) => getOtherNodeId(edge, state.selectedNodeId))
      ];
      return expandContext(seeds, { limit: activeLimit, includeBaseFill: false, relationFilter });
    }

    if (state.selectedNodeId) {
      const selectedEdges = getEdgesForNode(state.selectedNodeId, relationFilter);
      const seeds = [
        state.selectedNodeId,
        ...buildPromotionTrail(state.selectedNodeId, "out", 4),
        ...buildPromotionTrail(state.selectedNodeId, "in", 3),
        ...selectedEdges.map((edge) => getOtherNodeId(edge, state.selectedNodeId))
      ];
      return expandContext(seeds, {
        limit: activeLimit,
        includeBaseFill: false,
        relationFilter
      });
    }

    if (queryMatches.length) {
      return expandContext(queryMatches.map((node) => node.id), {
        limit: activeLimit,
        includeBaseFill: false,
        relationFilter
      });
    }

    const focusSeeds = unique([
      ...Array.from(state.recommendationIds),
    ].filter(Boolean));

    if (focusSeeds.length) {
      return expandContext(focusSeeds, {
        limit: activeLimit,
        includeBaseFill: true,
        relationFilter
      });
    }

    return state.baseNodeIds.slice(0, activeLimit);
  }

  function renderSearchResults(matches) {
    const container = getEl("knowledgeBaseSearchResults");
    if (!container) return;
    if (!state.searchQuery) {
      container.classList.remove("show");
      container.innerHTML = "";
      return;
    }
    if (!matches.length) {
      container.classList.add("show");
      container.innerHTML = `<div class="kb-empty-copy">没有找到对应的岗位节点</div>`;
      return;
    }
    container.classList.add("show");
    container.innerHTML = matches.map((node) => `
      <button type="button" class="kb-search-result${state.selectedNodeId === node.id ? " is-active" : ""}" data-node-id="${escapeHtml(node.id)}">
        <strong>${escapeHtml(node.title)}</strong>
        <span>${escapeHtml([node.family, node.level, node.city].filter(Boolean).join(" · "))}</span>
      </button>
    `).join("");
  }

  function updateInfoBar(displayNodes, displayEdges) {
    const info = getEl("knowledgeBaseBottomInfo");
    const connected = getEl("knowledgeBaseConnected");
    const totalNodes = state.nodeMap.size;
    const activeLimit = getActiveNodeLimit();
    const queryCount = state.queryResultIds.size;
    if (info) {
      const extra = queryCount ? ` · 搜索命中 ${queryCount}` : "";
      info.textContent = `Nodes ${displayNodes.length} / ${Math.min(activeLimit, totalNodes)} · Edges ${displayEdges.length}${extra}`;
    }
    if (connected) {
      connected.lastElementChild.textContent = `职业图谱在线 · 全量 ${totalNodes} 节点 · 当前上限 ${GRAPH_NODE_LIMIT}`;
    }
  }

  function matchSourceLabel() {
    if (state.matchMeta?.mode === "llm_reranked") {
      return state.matchMeta.model ? `AI 重排 · ${state.matchMeta.model}` : "AI 重排";
    }
    if (state.matchMeta?.mode === "deterministic") return "规则候选 · AI 未配置";
    return "等待匹配";
  }

  function matchBasisHint() {
    const parts = [];
    if (state.profile?.capabilities && typeof state.profile.capabilities === "object") {
      const n = Object.values(state.profile.capabilities).filter((x) => x && x.score != null).length;
      if (n) parts.push(`六维能力 ${n} 项`);
    }
    if (state.profile?.assessment?.mbti?.completed || state.profile?.assessment?.holland?.completed) {
      parts.push("测评");
    }
    if (state.profile?.resume?.status === "analyzed") parts.push("简历解析");
    if (state.profile?.interview?.profile) parts.push("职业访谈");
    if (state.profile?.basics?.target_direction) parts.push("目标方向");
    return parts.length ? `已纳入：${parts.join("、")}` : "已纳入：当前画像中的可用信号（可继续补充测评与简历以提高置信度）";
  }

  /** 中央「匹配路径看板」已移除；同步顶部「查看完整路线图」「重新匹配」按钮 */
  function renderPathDeck() {
    const btn = getEl("knowledgeBaseRoadmapBtn");
    const rematchBtn = getEl("knowledgeBaseRematchBtn");
    const hasMem = state.matchResults.length > 0;
    let hasStored = false;
    try {
      hasStored = Boolean(localStorage.getItem(LS_MATCH_RESULTS));
    } catch (_) {
      hasStored = false;
    }
    const canOpenReport = hasMem || hasStored;
    const canRematch = hasMem || hasStored;
    if (btn) {
      btn.disabled = !canOpenReport;
      btn.title = canOpenReport
        ? "在新标签页打开完整职业路径报告"
        : "请先点击「开始匹配」或等待恢复上次保存的结果";
    }
    if (rematchBtn) {
      rematchBtn.disabled = !canRematch;
      rematchBtn.title = canRematch
        ? "清除本地保存的上次诊断并重新向服务器请求匹配"
        : "暂无已保存的匹配结果";
    }
  }

  function panelRecommendationHtml() {
    const activeCities = getActiveCityPreferences();
    if (!state.matchResults.length) {
      return `
        <section class="kb-panel-section">
          <h4 class="kb-panel-section-title is-green">匹配推荐</h4>
          <p class="kb-empty-copy">选择城市后点击“开始匹配”，系统会先用图谱规则筛出候选岗位，再在已配置模型可用时进行 AI 重排，输出 5 条左右的职业路径。</p>
        </section>
      `;
    }
    return `
      <section class="kb-panel-section">
        <div class="kb-panel-title-row">
          <h4 class="kb-panel-section-title is-green">匹配推荐</h4>
          <span class="kb-match-source">${escapeHtml(matchSourceLabel())}</span>
        </div>
        <p class="kb-match-context">${activeCities.length ? `城市范围：${activeCities.join("、")}` : "城市范围：不限，优先看岗位画像与用户画像的相似度"}</p>
        <div class="kb-recommend-list">
          ${state.matchResults.map((item, index) => `
            <button type="button" class="kb-recommend-card${state.selectedNodeId === item.id ? " is-active" : ""}" data-node-id="${escapeHtml(item.id)}">
              <div class="kb-recommend-head">
                <span class="kb-recommend-rank">${String(index + 1).padStart(2, "0")}</span>
                <span class="kb-recommend-score">${escapeHtml(formatScore(item.overallScore))}</span>
              </div>
              <p class="kb-recommend-name">${escapeHtml(item.title)}</p>
              <p class="kb-recommend-meta">${escapeHtml([item.cluster, item.level, item.city].filter(Boolean).join(" · "))}</p>
              <p class="kb-recommend-copy">${escapeHtml(item.fitReason || (item.reasonLines || [])[0] || "推荐信号较强")}</p>
            </button>
          `).join("")}
        </div>
      </section>
    `;
  }

  function gapScoreRows(match) {
    if (!match) return [];
    return [
      { label: "方向", value: match.directionScore },
      { label: "技能", value: match.skillScore },
      { label: "能力", value: match.capabilityScore },
      { label: "经验", value: match.experienceScore },
      { label: "专业", value: match.majorScore },
      { label: "城市", value: match.cityScore }
    ].filter((item) => Number.isFinite(Number(item.value)));
  }

  function panelGapAnalysisHtml(match, nodeTitle = "") {
    const title = nodeTitle || match?.title || "目标岗位";
    if (!match) {
      return `
        <section class="kb-panel-section kb-gap-section">
          <h4 class="kb-panel-section-title is-cyan">画像差距分析</h4>
          <p class="kb-empty-copy">点击“开始匹配”后，这里会把用户画像与岗位画像逐项对比，输出技能、能力和行动建议。</p>
        </section>
      `;
    }

    const rows = gapScoreRows(match);
    const missingSkills = unique(match.missingSkills || [], 5);
    const capabilityGaps = unique(match.capabilityGaps || [], 5);
    const actions = unique(match.nextActions || [], 4);
    const gapItems = unique([
      ...missingSkills.map((item) => `技能证据：${item}`),
      ...capabilityGaps.map((item) => `能力差距：${item}`)
    ], 6);

    return `
      <section class="kb-panel-section kb-gap-section">
        <h4 class="kb-panel-section-title is-cyan">岗位画像 × 用户画像差距</h4>
        <p class="kb-gap-brief">${escapeHtml(title)} · 匹配度 ${escapeHtml(formatScore(match.overallScore))} · 置信度 ${escapeHtml(match.confidence || "中")}</p>
        ${rows.length ? `
          <div class="kb-gap-bars">
            ${rows.map((row) => {
              const score = Math.max(0, Math.min(100, Number(row.value || 0)));
              const stateClass = score >= 78 ? "is-good" : score >= 58 ? "is-mid" : "is-low";
              return `
                <div class="kb-gap-row ${stateClass}">
                  <span>${escapeHtml(row.label)}</span>
                  <i><b style="width:${score}%"></b></i>
                  <strong>${Math.round(score)}%</strong>
                </div>
              `;
            }).join("")}
          </div>
        ` : ""}
        <div class="kb-gap-grid">
          <div>
            <span class="kb-gap-label">主要缺口</span>
            <div class="kb-tag-list">
              ${gapItems.length ? gapItems.map((item) => `<span class="kb-tag warning">${escapeHtml(item)}</span>`).join("") : `<span class="kb-tag">暂无明显硬缺口</span>`}
            </div>
          </div>
          <div>
            <span class="kb-gap-label">行动计划</span>
            <div class="kb-relation-list">
              ${actions.length ? actions.map((item) => `<div class="kb-gap-action">${escapeHtml(item)}</div>`).join("") : `<p class="kb-empty-copy">继续补充测评、简历或访谈后会生成更具体的行动项。</p>`}
            </div>
          </div>
        </div>
      </section>
    `;
  }

  function renderDefaultPanel() {
    const title = getEl("knowledgeBasePanelTitle");
    const sub = getEl("knowledgeBasePanelSub");
    const body = getEl("knowledgeBasePanelBody");
    if (title) title.textContent = "岗位知识库";
    if (sub) sub.textContent = "选择一个岗位节点查看详情，或直接开始匹配";
    if (!body) return;

    const profileTags = unique([
      state.profile?.basics?.target_direction ? `目标方向：${state.profile.basics.target_direction}` : "",
      state.profile?.basics?.target_city ? `目标城市：${state.profile.basics.target_city}` : "",
      state.profile?.basics?.major ? `专业：${state.profile.basics.major}` : "",
      state.profile?.assessment?.mbti?.completed ? `MBTI：${state.profile.assessment.mbti.display_type || state.profile.assessment.mbti.final_type}` : "",
      state.profile?.assessment?.holland?.completed ? `霍兰德：${state.profile.assessment.holland.code}` : ""
    ].filter(Boolean), 6);

    body.innerHTML = `
      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title">画像信号</h4>
        <div class="kb-info-row">
          <span class="kb-info-label">摘要</span>
          <span class="kb-info-value">${escapeHtml(state.profile?.summary || "系统会把前面已填写的测评、简历、访谈和目标方向用于岗位匹配。")}</span>
        </div>
        <div class="kb-tag-list">
          ${profileTags.length ? profileTags.map((tag) => `<span class="kb-tag">${escapeHtml(tag)}</span>`).join("") : `<span class="kb-empty-copy">当前画像仍可继续补充，但已经可以开始做首轮匹配。</span>`}
        </div>
      </section>

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-cyan">图谱状态</h4>
        <div class="kb-info-row"><span class="kb-info-label">节点上限</span><span class="kb-info-value">${GRAPH_NODE_LIMIT}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">采样方式</span><span class="kb-info-value">优先展示晋升与换岗关系更丰富的岗位节点</span></div>
        <div class="kb-info-row"><span class="kb-info-label">当前布局</span><span class="kb-info-value">${escapeHtml(state.layoutMode)}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">路径模式</span><span class="kb-info-value">${escapeHtml(state.pathOnly ? "只看路径" : "完整图谱")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">搜索</span><span class="kb-info-value">${escapeHtml(state.searchQuery || "未输入关键词")}</span></div>
      </section>

      ${panelRecommendationHtml()}
      ${panelGapAnalysisHtml(state.matchResults[0] || null)}
    `;
  }

  function renderNodePanel(detail) {
    const title = getEl("knowledgeBasePanelTitle");
    const sub = getEl("knowledgeBasePanelSub");
    const body = getEl("knowledgeBasePanelBody");
    if (!body || !detail) return;

    const node = detail.node || {};
    const summary = detail.summary || {};
    const currentMatch = state.matchResults.find((item) => item.id === summary.id) || null;
    const salaryMax = Math.max(1, Number(summary.salaryMax || 1));

    if (title) title.textContent = summary.title || node.title || "Node";
    if (sub) sub.textContent = [summary.family, summary.level, summary.city].filter(Boolean).join(" · ") || "岗位详情";

    body.innerHTML = `
      <section class="kb-panel-section">
        <div class="kb-info-row"><span class="kb-info-label">岗位</span><span class="kb-info-value">${escapeHtml(summary.title || node.title || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">序列</span><span class="kb-info-value">${escapeHtml(summary.cluster || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">职级</span><span class="kb-info-value">${escapeHtml(summary.level || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">城市</span><span class="kb-info-value">${escapeHtml(summary.city || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">行业</span><span class="kb-info-value">${escapeHtml(summary.industry || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">年限</span><span class="kb-info-value">${escapeHtml(formatNumber(summary.years, 1))} 年</span></div>
        <div class="kb-info-row"><span class="kb-info-label">轨道</span><span class="kb-info-value">${escapeHtml(formatTrack(summary.track))}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">决策</span><span class="kb-info-value">${escapeHtml(summary.decisionScope || "--")}</span></div>
        <div class="kb-info-row"><span class="kb-info-label">协作</span><span class="kb-info-value">${escapeHtml(summary.collaborationScope || "--")}</span></div>
      </section>

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-purple">技能画像</h4>
        <div class="kb-tag-list">
          ${(summary.skills || []).length ? summary.skills.map((skill) => `<span class="kb-tag">${escapeHtml(skill)}</span>`).join("") : `<span class="kb-empty-copy">没有技能标签</span>`}
        </div>
      </section>

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-cyan">薪资范围</h4>
        <div class="kb-salary-text"><span>${escapeHtml(formatNumber(summary.salaryMin, 1))}k</span><strong>${escapeHtml(formatNumber(summary.salaryMax, 1))}k</strong></div>
        <div class="kb-salary-bar"><div class="kb-salary-fill" style="width:${Math.min(100, Math.max(8, salaryMax))}%"></div></div>
      </section>

      ${currentMatch ? `
        <section class="kb-panel-section">
          <h4 class="kb-panel-section-title is-green">匹配原因</h4>
          <div class="kb-info-row"><span class="kb-info-label">匹配度</span><span class="kb-info-value">${escapeHtml(formatScore(currentMatch.overallScore))}</span></div>
          <div class="kb-info-row"><span class="kb-info-label">原因</span><span class="kb-info-value">${escapeHtml(currentMatch.fitReason || (currentMatch.reasonLines || [])[0] || "该岗位与当前画像较接近。")}</span></div>
        </section>
      ` : ""}

      ${panelGapAnalysisHtml(currentMatch, summary.title || node.title || "")}

      ${currentMatch ? `
        <section class="kb-panel-section kb-path-side-note">
          <h4 class="kb-panel-section-title is-cyan">路径查看</h4>
          <p class="kb-empty-copy">晋升、换岗与验证路径已移到图谱底部的“匹配路径看板”，这里保留岗位画像与差距分析。</p>
        </section>
      ` : ""}

      ${panelRecommendationHtml()}
    `;
  }

  async function focusNode(nodeId) {
    const normalizedId = String(nodeId || "").trim();
    if (!normalizedId || !state.nodeMap.has(normalizedId)) return;
    state.selectedNodeId = normalizedId;
    renderGraph();
    scheduleViewportFocus(normalizedId);

    if (state.detailCache.has(normalizedId)) {
      renderNodePanel(state.detailCache.get(normalizedId));
      return;
    }

    const body = getEl("knowledgeBasePanelBody");
    if (body) {
      body.innerHTML = `<p class="kb-empty-copy">正在读取岗位详情...</p>`;
    }

    try {
      const payload = await fetchJson(`/api/career-graph/node/${encodeURIComponent(normalizedId)}`);
      state.detailCache.set(normalizedId, payload);
      if (state.selectedNodeId === normalizedId) {
        renderNodePanel(payload);
      }
    } catch (error) {
      renderDefaultPanel();
      showToast("岗位详情加载失败", error.message, "warning");
    }
  }

  function clearSelection() {
    state.viewportFocusToken += 1;
    state.selectedNodeId = "";
    renderDefaultPanel();
    renderGraph();
  }

  function ensureGraphCanvas() {
    const canvas = getEl("knowledgeBaseCanvas");
    if (!canvas || !window.d3) return null;
    if (state.svg) return canvas;

    canvas.innerHTML = "";
    state.svg = window.d3.select(canvas).append("svg").attr("class", "kb-graph-svg");
    state.svgRoot = state.svg.append("g");
    state.graphLayer = {
      links: state.svgRoot.append("g"),
      labels: state.svgRoot.append("g"),
      nodes: state.svgRoot.append("g")
    };

    const defs = state.svg.append("defs");
    Object.entries(RELATION_META).forEach(([key, meta]) => {
      [
        { suffix: "", color: meta.color },
        { suffix: "-muted", color: "#d5dde7" }
      ].forEach((variant) => {
        const marker = defs.append("marker")
          .attr("id", `kb-arrow-${key}${variant.suffix}`)
          .attr("viewBox", "0 0 10 10")
          .attr("refX", 9)
          .attr("refY", 5)
          .attr("markerWidth", 5)
          .attr("markerHeight", 5)
          .attr("orient", "auto");
        marker.append("path").attr("d", "M 0 0 L 10 5 L 0 10 Z").attr("fill", variant.color);
      });
    });

    state.zoom = window.d3.zoom()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        state.svgRoot.attr("transform", event.transform);
      });

    state.svg.call(state.zoom).on("dblclick.zoom", null);
    state.svg.on("click", (event) => {
      if (event.target === state.svg.node()) {
        clearSelection();
      }
    });

    return canvas;
  }

  function activeLinkFilter(edge) {
    return state.relationFilter === "all" || edge.relation === state.relationFilter;
  }

  function renderGraph() {
    const canvas = ensureGraphCanvas();
    if (!canvas || !state.bootstrap || !window.d3) return;
    const width = Math.max(canvas.clientWidth || 0, 640);
    const height = Math.max(canvas.clientHeight || 0, 520);
    state.svg.attr("viewBox", `0 0 ${width} ${height}`);

    if (state.simulation) {
      state.simulation.stop();
      state.simulation = null;
    }

    state.displayNodeIds = computeDisplayNodeIds();
    const displayIdSet = new Set(state.displayNodeIds);
    const displayNodes = state.displayNodeIds
      .map((id) => state.nodeMap.get(id))
      .filter(Boolean)
      .map((node) => ({ ...node }));
    const displayEdges = state.edgeList
      .filter((edge) => displayIdSet.has(edgeNodeId(edge.source)) && displayIdSet.has(edgeNodeId(edge.target)) && activeLinkFilter(edge))
      .map((edge) => ({
        ...edge,
        source: edgeNodeId(edge.source),
        target: edgeNodeId(edge.target)
      }));
    state.currentDisplayEdges = displayEdges; // 缓存给 updateVisualStates 使用

    const focusId = getCurrentFocusNodeId();
    const selectedId = state.selectedNodeId;
    const trailIds = new Set(focusId ? [focusId, ...buildPromotionTrail(focusId, "out", 4), ...buildPromotionTrail(focusId, "in", 3)] : []);
    const recommendationIds = state.recommendationIds;
    const queryIds = state.queryResultIds;
    const selectedContext = buildSelectedContext(displayEdges, focusId, trailIds);
    const promotionCluster = new Set([focusId, ...trailIds, ...selectedContext.promotionIds].filter(Boolean));
    const transferCluster = new Set([focusId, ...selectedContext.transferIds].filter(Boolean));
    const visualContext = {
      selectedId,
      focusId,
      trailIds,
      queryIds,
      recommendationIds,
      promotionIds: selectedContext.promotionIds,
      transferIds: selectedContext.transferIds,
      promotionCluster,
      transferCluster
    };

    displayNodes.forEach((node, index) => {
      const existing = state.positions.get(node.id);
      node.x = existing?.x ?? (width * 0.42 + Math.cos(index / 6) * 120);
      node.y = existing?.y ?? (height * 0.5 + Math.sin(index / 6) * 120);
      node.visualState = resolveNodeVisualState(node.id, visualContext);
      node.visual = nodeVisual(node.visualState);
    });
    displayNodes.sort((left, right) => (NODE_VISUAL_ORDER[left.visualState] || 0) - (NODE_VISUAL_ORDER[right.visualState] || 0));

    const d3 = window.d3;
    if (state.layoutMode === "circle") {
      const radius = Math.min(width, height) * 0.3;
      displayNodes.forEach((node, index) => {
        const angle = (Math.PI * 2 * index) / Math.max(displayNodes.length, 1);
        node.fx = width * 0.42 + Math.cos(angle) * radius;
        node.fy = height * 0.5 + Math.sin(angle) * radius;
      });
    }

    const nodeCount = displayNodes.length;
    const heavyGraph = nodeCount > 200;
    const manyCharge = d3.forceManyBody()
      .strength(nodeCount > 450 ? -190 : -250)
      .theta(heavyGraph ? 0.94 : 0.9)
      .distanceMax(Math.min(width, height) * 0.52);
    const collideRadius = (d) => levelRadius(d.level) + 10;
    const collisionForce = d3.forceCollide()
      .radius(collideRadius)
      .iterations(heavyGraph ? 1 : 2)
      .strength(0.86);

    state.simulation = d3.forceSimulation(displayNodes)
      .force("link", d3.forceLink(displayEdges).id((d) => d.id).distance((d) => d.relation === "promotion" ? 146 : 240).strength((d) => d.relation === "promotion" ? 0.58 : 0.32))
      .force("charge", manyCharge)
      .force("collision", collisionForce)
      .force("center", d3.forceCenter(width * 0.42, height * 0.5))
      .force("radialSpread", d3.forceRadial(Math.min(width, height) * 0.32, width * 0.42, height * 0.5).strength(heavyGraph ? 0.08 : 0.04))
      .velocityDecay(heavyGraph ? 0.64 : 0.54)
      .alphaDecay(heavyGraph ? 0.068 : 0.048)
      .alphaMin(0.02);

    if (state.layoutMode === "radial") {
      state.simulation
        .force("radial", d3.forceRadial((d) => 80 + levelNumber(d.level) * 70, width * 0.42, height * 0.5).strength(0.35))
        .force("x", d3.forceX(width * 0.42).strength(0.04))
        .force("y", d3.forceY(height * 0.5).strength(0.04));
    } else if (state.layoutMode === "circle") {
      state.simulation.alpha(0.2);
    }

    state.graphLayer.links.selectAll("*").remove();
    state.graphLayer.labels.selectAll("*").remove();
    state.graphLayer.nodes.selectAll("*").remove();

    const links = state.graphLayer.links.selectAll("line")
      .data(displayEdges)
      .enter()
      .append("line")
      .attr("class", (d) => {
        const classes = ["kb-link-line", `is-${d.relation}`];
        classes.push(edgeIsContextual(d, visualContext) ? "is-context" : "is-muted");
        return classes.join(" ");
      })
      .attr("stroke", (d) => edgeIsContextual(d, visualContext) ? (RELATION_META[d.relation]?.color || "#d0d0d8") : "#d5dde7")
      .attr("stroke-dasharray", (d) => RELATION_META[d.relation]?.dash || null)
      .attr("marker-end", (d) => `url(#kb-arrow-${d.relation}${edgeIsContextual(d, visualContext) ? "" : "-muted"})`);
    state.graphLayer.linkSel = links; // 保存供 updateVisualStates 使用

    let linkLabels = null;
    const shouldRenderLinkLabels = Boolean(focusId || (queryIds.size && queryIds.size <= 8)) && displayEdges.length <= 850;
    if (shouldRenderLinkLabels) {
      linkLabels = state.graphLayer.labels.selectAll("text")
        .data(displayEdges)
        .enter()
        .append("text")
        .attr("class", (d) => {
          const visible = edgeIsContextual(d, visualContext) && (focusId || (queryIds.size && queryIds.size <= 8));
          return `kb-link-label${visible ? "" : " is-hidden"}`;
        })
        .attr("fill", (d) => edgeIsContextual(d, visualContext) ? (RELATION_META[d.relation]?.color || "#80849a") : "#94a3b8")
        .attr("text-anchor", "middle")
        .text((d) => RELATION_META[d.relation]?.label || "");
    }
    state.graphLayer.linkLabelSel = linkLabels; // 保存供 updateVisualStates 使用

    const nodeGroups = state.graphLayer.nodes.selectAll("g")
      .data(displayNodes)
      .enter()
      .append("g")
      .attr("class", (d) => {
        const classes = ["kb-node-group", `is-${d.visualState}`];
        if (d.visualState === "muted" && focusId) classes.push("is-dimmed");
        if (d.visualState === "muted" && queryIds.size) classes.push("is-faded");
        if (trailIds.has(d.id)) classes.push("is-path");
        return classes.join(" ");
      })
      .call(d3.drag()
        .on("start", (event, d) => {
          if (!event.active) state.simulation.alphaTarget(0.2).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) state.simulation.alphaTarget(0);
          state.positions.set(d.id, { x: d.x, y: d.y });
          if (state.layoutMode !== "circle") {
            d.fx = null;
            d.fy = null;
          }
        }));

    nodeGroups.append("circle")
      .attr("class", "kb-node-shell")
      .attr("r", (d) => levelRadius(d.level) + 6)
      .attr("fill", (d) => d.visual.shellFill)
      .attr("stroke", (d) => d.visual.shellStroke)
      .attr("stroke-width", (d) => d.visualState === "selected" ? 2.8 : 2.3);

    nodeGroups.append("circle")
      .attr("class", "kb-node-core")
      .attr("r", (d) => levelRadius(d.level))
      .attr("fill", (d) => d.visual.coreFill)
      .attr("stroke", (d) => d.visual.coreStroke)
      .attr("stroke-width", 1.2);

    const hideMutedLabels = nodeCount > 260 && !focusId && !queryIds.size;
    nodeGroups.append("text")
      .attr("class", "kb-node-label")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => levelRadius(d.level) + 16)
      .attr("fill", (d) => d.visual.label)
      .attr("opacity", (d) => (hideMutedLabels && d.visualState === "muted" ? 0 : 1))
      .text((d) => d.title);
    state.graphLayer.nodeGroupSel = nodeGroups; // 保存供 updateVisualStates 使用

    const tooltip = getEl("knowledgeBaseTooltip");
    const tooltipTitle = getEl("knowledgeBaseTooltipTitle");
    const tooltipSub = getEl("knowledgeBaseTooltipSub");

    nodeGroups
      .on("mouseover", (event, d) => {
        if (!tooltip || !tooltipTitle || !tooltipSub) return;
        tooltipTitle.textContent = d.title;
        tooltipSub.textContent = [d.level, d.family, d.city].filter(Boolean).join(" · ");
        tooltip.classList.add("is-visible");
      })
      .on("mousemove", (event) => {
        if (!tooltip) return;
        tooltip.style.left = `${event.clientX + 14}px`;
        tooltip.style.top = `${event.clientY - 10}px`;
      })
      .on("mouseout", () => {
        if (tooltip) tooltip.classList.remove("is-visible");
      })
      .on("click", (event, d) => {
        event.stopPropagation();
        void focusNode(d.id);
      });

    let tickFrame = 0;
    state.simulation.on("tick", () => {
      if (heavyGraph && tickFrame++ % 2 === 1) return;
      links
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);

      if (linkLabels) {
        linkLabels
          .attr("x", (d) => (d.source.x + d.target.x) / 2)
          .attr("y", (d) => (d.source.y + d.target.y) / 2 - 6);
      }

      nodeGroups.attr("transform", (d) => `translate(${d.x},${d.y})`);

      if (heavyGraph && tickFrame > 90 && state.simulation.alpha() < 0.035) {
        state.simulation.stop();
      }
    });

    state.simulation.on("end", () => {
      displayNodes.forEach((d) => {
        if (d.x != null && d.y != null) state.positions.set(d.id, { x: d.x, y: d.y });
      });
    });

    updateInfoBar(displayNodes, displayEdges);
    renderSearchResults(searchAllNodes(state.searchQuery, DEFAULT_SEARCH_RESULT_LIMIT));
    renderPathDeck();
  }

  /**
   * 仅更新节点/边的视觉状态（颜色、CSS类），不重建 simulation 也不重建 DOM。
   * 用于点击节点、取消选中等操作，避免 500 个节点重新碰撞抖动。
   */
  function updateVisualStates() {
    if (!state.graphLayer || !state.graphLayer.nodeGroupSel || !state.graphLayer.linkSel) {
      // 图尚未渲染，回退到完整渲染
      renderGraph();
      return;
    }

    const focusId = getCurrentFocusNodeId();
    const selectedId = state.selectedNodeId;
    const displayEdges = state.currentDisplayEdges;
    const trailIds = new Set(
      focusId
        ? [focusId, ...buildPromotionTrail(focusId, "out", 4), ...buildPromotionTrail(focusId, "in", 3)]
        : []
    );
    const selectedContext = buildSelectedContext(displayEdges, focusId, trailIds);
    const promotionCluster = new Set([focusId, ...trailIds, ...selectedContext.promotionIds].filter(Boolean));
    const transferCluster = new Set([focusId, ...selectedContext.transferIds].filter(Boolean));
    const visualContext = {
      selectedId,
      focusId,
      trailIds,
      queryIds: state.queryResultIds,
      recommendationIds: state.recommendationIds,
      promotionIds: selectedContext.promotionIds,
      transferIds: selectedContext.transferIds,
      promotionCluster,
      transferCluster,
    };

    // 1. 更新每个节点的 visualState & visual 数据
    state.graphLayer.nodeGroupSel.each(function (d) {
      d.visualState = resolveNodeVisualState(d.id, visualContext);
      d.visual = nodeVisual(d.visualState);
    });

    // 2. 更新节点组 CSS 类（控制 opacity/scale 动画）
    state.graphLayer.nodeGroupSel.attr("class", (d) => {
      const classes = ["kb-node-group", `is-${d.visualState}`];
      if (d.visualState === "muted" && focusId) classes.push("is-dimmed");
      if (d.visualState === "muted" && state.queryResultIds.size) classes.push("is-faded");
      if (trailIds.has(d.id)) classes.push("is-path");
      return classes.join(" ");
    });

    // 3. 更新外圈（shell）颜色
    state.graphLayer.nodeGroupSel.select(".kb-node-shell")
      .attr("fill", (d) => d.visual.shellFill)
      .attr("stroke", (d) => d.visual.shellStroke)
      .attr("stroke-width", (d) => (d.visualState === "selected" ? 2.8 : 2.3));

    // 4. 更新内核（core）颜色
    state.graphLayer.nodeGroupSel.select(".kb-node-core")
      .attr("fill", (d) => d.visual.coreFill)
      .attr("stroke", (d) => d.visual.coreStroke);

    // 5. 更新标签颜色
    state.graphLayer.nodeGroupSel.select(".kb-node-label")
      .attr("fill", (d) => d.visual.label)
      .attr("opacity", (d) => {
        const hideMutedLabels = state.displayNodeIds.length > 260 && !focusId && !state.queryResultIds.size;
        return hideMutedLabels && d.visualState === "muted" ? 0 : 1;
      });

    // 6. 更新边的颜色/可见性
    state.graphLayer.linkSel
      .attr("class", (d) => {
        const classes = ["kb-link-line", `is-${d.relation}`];
        classes.push(edgeIsContextual(d, visualContext) ? "is-context" : "is-muted");
        return classes.join(" ");
      })
      .attr("stroke", (d) =>
        edgeIsContextual(d, visualContext) ? (RELATION_META[d.relation]?.color || "#d0d0d8") : "#d5dde7"
      );

    // 7. 更新边标签可见性
    if (state.graphLayer.linkLabelSel) {
      state.graphLayer.linkLabelSel.attr("class", (d) => {
        const visible =
          edgeIsContextual(d, visualContext) &&
          (focusId || (state.queryResultIds.size && state.queryResultIds.size <= 8));
        return `kb-link-label${visible ? "" : " is-hidden"}`;
      });
    }

    // 8. 让 simulation 静止（如有残余能量），但不重启
    if (state.simulation && state.simulation.alpha() > 0.01) {
      state.simulation.alpha(0).stop();
    }
  }

  async function startMatch({ force = false } = {}) {
    if (typeof window.getLatestUnifiedProfile === "function") {
      const fresh = window.getLatestUnifiedProfile();
      if (fresh && typeof fresh === "object") state.profile = fresh;
    }
    if (!state.profile) {
      showToast("画像未就绪", "请先加载测评与基础画像后再试", "warning", 2200);
      return;
    }
    if (state.matchResults.length && !force) {
      renderPathDeck();
      renderDefaultPanel();
      renderGraph();
      return;
    }

    const button = getEl("knowledgeBaseMatchButton");
    const cities = getActiveCityPreferences();
    if (button) {
      button.disabled = true;
      button.textContent = "AI 匹配中...";
    }
    setStatus(cities.length ? `正在匹配 ${cities.join("、")} 的岗位路径` : "正在计算岗位匹配结果", "loading");

    try {
      const payload = await fetchJson("/api/career-graph/match", {
        method: "POST",
        body: JSON.stringify({
          profile: state.profile,
          cityPreferences: cities,
          limit: 5
        })
      });
      state.matchResults = Array.isArray(payload.recommendations) ? payload.recommendations : [];
      state.matchMeta = {
        mode: payload.mode || "deterministic",
        model: payload.model || "",
        profileEcho: payload.profileEcho || {}
      };
      state.recommendationIds = new Set(state.matchResults.map((item) => item.id).filter(Boolean));
      setStatus(`${matchSourceLabel()} · ${state.matchResults.length} 条路径`, "ready");
      persistCareerMatchBundle();
      renderCityPlanner();
      renderPathDeck();
      renderDefaultPanel();
      renderGraph();
    } catch (error) {
      setStatus("职业匹配失败", "error");
      showToast("职业匹配失败", error.message, "error");
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "开始匹配";
      }
    }
  }

  function resetLayout() {
    state.positions.clear();
    state.searchQuery = "";
    state.selectedNodeId = "";
    state.relationFilter = "all";
    state.pathOnly = false;
    const searchInput = getEl("knowledgeBaseSearchInput");
    const relationFilter = getEl("knowledgeBaseRelationFilter");
    const searchResults = getEl("knowledgeBaseSearchResults");
    const pathBtn = getEl("knowledgeBasePathBtn");
    if (searchInput) searchInput.value = "";
    if (relationFilter) relationFilter.value = "all";
    if (searchResults) {
      searchResults.classList.remove("show");
      searchResults.innerHTML = "";
    }
    if (pathBtn) pathBtn.classList.remove("is-active");
    renderGraph();
  }

  function bindEvents() {
    if (state.bound) return;
    state.bound = true;

    if (!state.visibilityPauseBound && typeof document !== "undefined") {
      state.visibilityPauseBound = true;
      document.addEventListener("visibilitychange", () => {
        if (document.hidden && state.simulation) state.simulation.alpha(0).stop();
      });
    }

    const searchInput = getEl("knowledgeBaseSearchInput");
    const searchResults = getEl("knowledgeBaseSearchResults");
    const relationFilter = getEl("knowledgeBaseRelationFilter");
    const layoutBtn = getEl("knowledgeBaseLayoutBtn");
    const layoutMenu = getEl("knowledgeBaseLayoutMenu");
    const pathBtn = getEl("knowledgeBasePathBtn");
    const resetBtn = getEl("knowledgeBaseResetBtn");
    const refreshBtn = getEl("knowledgeBaseRefreshBtn");
    const closeBtn = getEl("knowledgeBasePanelClose");
    const zoomIn = getEl("knowledgeBaseZoomIn");
    const zoomOut = getEl("knowledgeBaseZoomOut");
    const cityChips = getEl("knowledgeBaseCityChips");
    const cityInput = getEl("knowledgeBaseCityInput");
    const cityAdd = getEl("knowledgeBaseCityAdd");
    const cityClear = getEl("knowledgeBaseCityClear");
    let searchDebounceTimer = 0;
    if (searchInput) {
      searchInput.addEventListener("input", () => {
        window.clearTimeout(searchDebounceTimer);
        searchDebounceTimer = window.setTimeout(() => {
          state.searchQuery = searchInput.value.trim();
          renderGraph();
        }, 120);
      });
    }

    if (searchResults) {
      searchResults.addEventListener("click", (event) => {
        const target = event.target.closest("[data-node-id]");
        if (!target) return;
        const nodeId = target.getAttribute("data-node-id");
        if (nodeId) void focusNode(nodeId);
      });
    }

    if (cityChips) {
      cityChips.addEventListener("click", (event) => {
        const target = event.target.closest("[data-city]");
        if (!target) return;
        const city = target.getAttribute("data-city") || "";
        if (!city) return;
        if (cityIsSelected(city)) {
          removeCityPreference(city);
        } else {
          addCityPreference(city);
        }
      });
    }

    if (cityAdd) {
      cityAdd.addEventListener("click", () => {
        addCityPreference(cityInput?.value || "");
        if (cityInput) cityInput.value = "";
      });
    }

    if (cityInput) {
      cityInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        addCityPreference(cityInput.value);
        cityInput.value = "";
      });
    }

    if (cityClear) {
      cityClear.addEventListener("click", () => {
        setCityPreferences([]);
      });
    }

    const roadmapBtn = getEl("knowledgeBaseRoadmapBtn");
    if (roadmapBtn) {
      roadmapBtn.addEventListener("click", () => openCareerReport());
    }

    const rematchBtn = getEl("knowledgeBaseRematchBtn");
    if (rematchBtn) {
      rematchBtn.addEventListener("click", () => {
        void rematchCareerMatching();
      });
    }

    if (relationFilter) {
      relationFilter.addEventListener("change", () => {
        state.relationFilter = relationFilter.value || "all";
        renderGraph();
      });
    }

    if (layoutBtn && layoutMenu) {
      layoutBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        layoutMenu.classList.toggle("show");
      });
      document.addEventListener("click", () => layoutMenu.classList.remove("show"));
      layoutMenu.addEventListener("click", (event) => {
        const item = event.target.closest("[data-layout]");
        if (!item) return;
        layoutMenu.querySelectorAll(".kb-layout-item").forEach((el) => el.classList.remove("is-active"));
        item.classList.add("is-active");
        state.layoutMode = item.getAttribute("data-layout") || "force";
        layoutMenu.classList.remove("show");
        state.positions.clear();
        renderGraph();
      });
    }

    if (pathBtn) {
      pathBtn.addEventListener("click", () => {
        state.pathOnly = !state.pathOnly;
        pathBtn.classList.toggle("is-active", state.pathOnly);
        renderDefaultPanel();
        renderGraph();
      });
    }

    if (resetBtn) resetBtn.addEventListener("click", () => resetLayout());
    if (refreshBtn) refreshBtn.addEventListener("click", () => {
      state.detailCache.clear();
      state.positions.clear();
      renderGraph();
    });
    if (closeBtn) closeBtn.addEventListener("click", () => clearSelection());

    if (zoomIn) {
      zoomIn.addEventListener("click", () => {
        if (state.svg) state.svg.transition().duration(240).call(state.zoom.scaleBy, 1.2);
      });
    }

    if (zoomOut) {
      zoomOut.addEventListener("click", () => {
        if (state.svg) state.svg.transition().duration(240).call(state.zoom.scaleBy, 0.84);
      });
    }

    const panel = getEl("knowledgeBasePanelBody");
    if (panel) {
      panel.addEventListener("click", (event) => {
        const target = event.target.closest("[data-node-id]");
        if (!target) return;
        const nodeId = target.getAttribute("data-node-id");
        if (nodeId) void focusNode(nodeId);
      });
    }

    let resizeRaf = 0;
    window.addEventListener("resize", () => {
      if (resizeRaf) window.cancelAnimationFrame(resizeRaf);
      resizeRaf = window.requestAnimationFrame(() => {
        renderGraph();
        resizeRaf = 0;
      });
    });
  }

  async function render({ profile } = {}) {
    if (profile) {
      const nextSignature = profileSignature(profile);
      if (nextSignature !== state.profileSignature) {
        state.profileSignature = nextSignature;
        state.profile = profile;
      } else {
        state.profile = profile;
      }
    }

    bindEvents();
    setStatus("图谱准备中", (state.profile?.missingItems || []).length ? "warning" : "loading");
    await ensureBootstrap();
    tryRestorePersistedMatch();
    state.suggestedCities = buildSuggestedCities(Array.from(state.nodeMap.values()));
    renderCityPlanner();
    renderPathDeck();
    renderDefaultPanel();
    renderGraph();
    if (state.matchResults.length) {
      setStatus(`${matchSourceLabel()} · ${state.matchResults.length} 条路径`, "ready");
    } else {
      setStatus(
        (state.profile?.missingItems || []).length ? "画像待补充" : "图谱已就绪",
        (state.profile?.missingItems || []).length ? "warning" : "ready"
      );
    }
  }

  function onSectionVisible() {
    bindEvents();
    if (!state.bootstrap) {
      void ensureBootstrap().then(() => {
        tryRestorePersistedMatch();
        renderCityPlanner();
        renderPathDeck();
        renderDefaultPanel();
        renderGraph();
      }).catch((error) => showToast("图谱加载失败", error.message, "warning"));
      return;
    }
    tryRestorePersistedMatch();
    renderCityPlanner();
    renderPathDeck();
    renderGraph();
  }

  function openCareerReport() {
    if (!state.matchResults.length) {
      try {
        const raw = localStorage.getItem(LS_MATCH_RESULTS);
        const pRaw = localStorage.getItem(LS_MATCH_PROFILE);
        if (raw && pRaw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length) {
            sessionStorage.setItem(LS_MATCH_RESULTS, raw);
            sessionStorage.setItem(LS_MATCH_PROFILE, pRaw);
            window.open("/static/career-report.html", "_blank");
            return;
          }
        }
      } catch (_) { /* ignore */ }
      showToast("暂无可展示结果", "请先点击「开始匹配」生成岗位推荐", "warning", 2400);
      return;
    }
    try {
      const profilePayload = buildMatchProfilePayload();
      sessionStorage.setItem(LS_MATCH_RESULTS, JSON.stringify(state.matchResults));
      sessionStorage.setItem(LS_MATCH_PROFILE, JSON.stringify(profilePayload));
      persistCareerMatchBundle();
    } catch (_) { /* sessionStorage unavailable */ }
    window.open("/static/career-report.html", "_blank");
  }

  async function rematchCareerMatching() {
    clearCareerMatchStorage({ clearRemote: true });
    state.matchResults = [];
    state.matchMeta = null;
    state.recommendationIds = new Set();
    state.selectedNodeId = "";
    renderPathDeck();
    renderDefaultPanel();
    renderGraph();
    showToast("已清除上次诊断", "正在重新匹配…", "info", 2600);
    await startMatch({ force: true });
  }

  window.__careerGraphMatchingApi = {
    render,
    startMatch,
    rematchCareerMatching,
    focusNode,
    resetLayout,
    onSectionVisible
  };
})();
