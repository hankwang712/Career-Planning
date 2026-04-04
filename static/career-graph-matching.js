(function initCareerGraphMatchingModule() {
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
    queryResultIds: new Set(),
    recommendationIds: new Set(),
    matchResults: [],
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
    if (nodeId === context.selectedId) return "selected";
    if (context.promotionIds.has(nodeId)) return "promotion";
    if (context.transferIds.has(nodeId)) return "transfer";
    if (context.queryIds.size) return context.queryIds.has(nodeId) ? "query" : "muted";
    if (context.recommendationIds.has(nodeId)) return "recommended";
    if (context.selectedId) return "muted";
    return "default";
  }

  function edgeIsContextual(edge, context) {
    const sourceId = edgeNodeId(edge.source);
    const targetId = edgeNodeId(edge.target);
    if (!sourceId || !targetId) return false;

    if (context.selectedId) {
      if (sourceId === context.selectedId || targetId === context.selectedId) return true;
      if (edge.relation === "promotion" && context.trailIds.has(sourceId) && context.trailIds.has(targetId)) return true;
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
    const queryMatches = state.searchQuery ? searchAllNodes(state.searchQuery, state.nodeMap.size || 2000) : [];
    state.queryResultIds = new Set(queryMatches.map((node) => node.id));

    if (state.pathOnly && state.selectedNodeId) {
      const seeds = [
        state.selectedNodeId,
        ...buildPromotionTrail(state.selectedNodeId, "out", 4),
        ...buildPromotionTrail(state.selectedNodeId, "in", 3),
        ...getEdgesForNode(state.selectedNodeId, relationFilter).map((edge) => getOtherNodeId(edge, state.selectedNodeId))
      ];
      return expandContext(seeds, { limit: GRAPH_NODE_LIMIT, includeBaseFill: false, relationFilter });
    }

    if (queryMatches.length) {
      return expandContext(queryMatches.map((node) => node.id), {
        limit: GRAPH_NODE_LIMIT,
        includeBaseFill: false,
        relationFilter
      });
    }

    const focusSeeds = unique([
      state.selectedNodeId,
      ...Array.from(state.recommendationIds),
      ...buildPromotionTrail(state.selectedNodeId, "out", 4)
    ].filter(Boolean));

    if (focusSeeds.length) {
      return expandContext(focusSeeds, {
        limit: GRAPH_NODE_LIMIT,
        includeBaseFill: true,
        relationFilter
      });
    }

    return state.baseNodeIds.slice(0, GRAPH_NODE_LIMIT);
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
    const queryCount = state.queryResultIds.size;
    if (info) {
      const extra = queryCount ? ` · 搜索命中 ${queryCount}` : "";
      info.textContent = `Nodes ${displayNodes.length} / ${Math.min(GRAPH_NODE_LIMIT, totalNodes)} · Edges ${displayEdges.length}${extra}`;
    }
    if (connected) {
      connected.lastElementChild.textContent = `职业图谱在线 · 全量 ${totalNodes} 节点 · 当前上限 ${GRAPH_NODE_LIMIT}`;
    }
  }

  function panelRecommendationHtml() {
    if (!state.matchResults.length) {
      return `
        <section class="kb-panel-section">
          <h4 class="kb-panel-section-title is-green">匹配推荐</h4>
          <p class="kb-empty-copy">点击“开始匹配”后，系统会结合画像信号、岗位关系和推荐规则，为你生成 5 个方向。</p>
        </section>
      `;
    }
    return `
      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-green">匹配推荐</h4>
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
    `;
  }

  function relationItemHtml(title, items, relationLabel) {
    if (!items.length) {
      return `<p class="kb-empty-copy">当前没有可展示的${escapeHtml(title)}</p>`;
    }
    return `
      <div class="kb-relation-list">
        ${items.map((item) => `
          <button type="button" class="kb-relation-item" data-node-id="${escapeHtml(item.node.id)}">
            <span class="kb-relation-name">${escapeHtml(item.node.title)}</span>
            <span class="kb-relation-meta">${escapeHtml([item.node.level, item.node.city, item.node.cluster].filter(Boolean).join(" · "))}</span>
            <span class="kb-relation-type">${escapeHtml(relationLabel)} · 置信度 ${escapeHtml(formatPercent(item.edge.confidence))}</span>
          </button>
        `).join("")}
      </div>
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

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title">路径摘要</h4>
        <p class="kb-empty-copy">${escapeHtml(detail.path || "当前节点暂无更长的路径摘要。")}</p>
      </section>

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-green">晋升路径</h4>
        ${relationItemHtml("晋升路径", detail.relations?.promotion_out || [], "晋升")}
      </section>

      <section class="kb-panel-section">
        <h4 class="kb-panel-section-title is-cyan">换岗路径</h4>
        ${relationItemHtml("换岗路径", detail.relations?.substitution || [], "换岗")}
      </section>

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
    const displayEdges = state.edgeList.filter((edge) => displayIdSet.has(edge.source) && displayIdSet.has(edge.target) && activeLinkFilter(edge));

    const selectedId = state.selectedNodeId;
    const trailIds = new Set(selectedId ? [selectedId, ...buildPromotionTrail(selectedId, "out", 4), ...buildPromotionTrail(selectedId, "in", 3)] : []);
    const recommendationIds = state.recommendationIds;
    const queryIds = state.queryResultIds;
    const selectedContext = buildSelectedContext(displayEdges, selectedId, trailIds);
    const visualContext = {
      selectedId,
      trailIds,
      queryIds,
      recommendationIds,
      promotionIds: selectedContext.promotionIds,
      transferIds: selectedContext.transferIds
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

    state.simulation = d3.forceSimulation(displayNodes)
      .force("link", d3.forceLink(displayEdges).id((d) => d.id).distance((d) => d.relation === "promotion" ? 110 : 170).strength((d) => d.relation === "promotion" ? 0.72 : 0.42))
      .force("charge", d3.forceManyBody().strength(displayNodes.length > 550 ? -90 : -220))
      .force("collision", d3.forceCollide().radius((d) => levelRadius(d.level) + 12))
      .force("center", d3.forceCenter(width * 0.42, height * 0.5));

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

    const linkLabels = state.graphLayer.labels.selectAll("text")
      .data(displayEdges)
      .enter()
      .append("text")
      .attr("class", (d) => {
        const visible = edgeIsContextual(d, visualContext) && (!queryIds.size || queryIds.size <= 8 || selectedId);
        return `kb-link-label${visible ? "" : " is-hidden"}`;
      })
      .attr("fill", (d) => edgeIsContextual(d, visualContext) ? (RELATION_META[d.relation]?.color || "#80849a") : "#94a3b8")
      .attr("text-anchor", "middle")
      .text((d) => RELATION_META[d.relation]?.label || "");

    const nodeGroups = state.graphLayer.nodes.selectAll("g")
      .data(displayNodes)
      .enter()
      .append("g")
      .attr("class", (d) => {
        const classes = ["kb-node-group", `is-${d.visualState}`];
        if (d.visualState === "muted" && selectedId) classes.push("is-dimmed");
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

    nodeGroups.append("text")
      .attr("class", "kb-node-label")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => levelRadius(d.level) + 16)
      .attr("fill", (d) => d.visual.label)
      .text((d) => d.title);

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

    state.simulation.on("tick", () => {
      links
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);

      linkLabels
        .attr("x", (d) => (d.source.x + d.target.x) / 2)
        .attr("y", (d) => (d.source.y + d.target.y) / 2 - 6);

      nodeGroups.attr("transform", (d) => {
        state.positions.set(d.id, { x: d.x, y: d.y });
        return `translate(${d.x},${d.y})`;
      });
    });

    updateInfoBar(displayNodes, displayEdges);
    renderSearchResults(searchAllNodes(state.searchQuery, DEFAULT_SEARCH_RESULT_LIMIT));
  }

  async function startMatch({ force = false } = {}) {
    if (!state.profile) return;
    if (state.matchResults.length && !force) {
      renderDefaultPanel();
      renderGraph();
      return;
    }

    const button = getEl("knowledgeBaseMatchButton");
    if (button) {
      button.disabled = true;
      button.textContent = "匹配中...";
    }
    setStatus("正在计算匹配结果", "loading");

    try {
      const payload = await fetchJson("/api/career-graph/match", {
        method: "POST",
        body: JSON.stringify({ profile: state.profile, limit: 5 })
      });
      state.matchResults = Array.isArray(payload.recommendations) ? payload.recommendations : [];
      state.recommendationIds = new Set(state.matchResults.map((item) => item.id).filter(Boolean));
      setStatus(`已生成 ${state.matchResults.length} 条推荐`, "ready");
      renderDefaultPanel();
      renderGraph();
      if (state.matchResults[0]?.id) {
        await focusNode(state.matchResults[0].id);
      }
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

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        state.searchQuery = searchInput.value.trim();
        renderGraph();
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

    window.addEventListener("resize", () => {
      renderGraph();
    });
  }

  async function render({ profile } = {}) {
    if (profile) {
      const nextSignature = profileSignature(profile);
      if (nextSignature !== state.profileSignature) {
        state.profileSignature = nextSignature;
        state.profile = profile;
        state.matchResults = [];
        state.recommendationIds = new Set();
        state.selectedNodeId = "";
      } else {
        state.profile = profile;
      }
    }

    bindEvents();
    setStatus("图谱准备中", (state.profile?.missingItems || []).length ? "warning" : "loading");
    await ensureBootstrap();
    renderDefaultPanel();
    renderGraph();
    setStatus((state.profile?.missingItems || []).length ? "画像待补充" : "图谱已就绪", (state.profile?.missingItems || []).length ? "warning" : "ready");
  }

  function onSectionVisible() {
    bindEvents();
    if (!state.bootstrap) {
      void ensureBootstrap().then(() => {
        renderDefaultPanel();
        renderGraph();
      }).catch((error) => showToast("图谱加载失败", error.message, "warning"));
      return;
    }
    renderGraph();
  }

  window.__careerGraphMatchingApi = {
    render,
    startMatch,
    focusNode,
    resetLayout,
    onSectionVisible
  };
})();
