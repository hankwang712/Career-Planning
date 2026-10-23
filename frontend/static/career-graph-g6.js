/**
 * AntV G6 职业图谱渲染器 - 大数据优化版
 * 专为 4000+ 节点设计，支持聚合与展开
 */
(function initCareerGraphG6() {
  'use strict';

  let graph = null;

  const RELATION_META = {
    promotion: { label: '晋升关系', color: '#10b981' },
    substitution: { label: '转岗关系', color: '#f59e0b' },
    related: { label: '关联关系', color: '#6366f1' }
  };

  const FAMILY_COLORS = {
    '技术': '#38bdf8', '产品': '#a78bfa', '设计': '#f472b6',
    '运营': '#34d399', '市场': '#fbbf24', '销售': '#f87171',
    '职能': '#22d3ee', '数据': '#818cf8', '算法': '#c084fc',
    'default': '#64748b'
  };

  function getFamilyColor(family) {
    if (!family) return FAMILY_COLORS.default;
    for (const [key, color] of Object.entries(FAMILY_COLORS)) {
      if (family.includes(key) || key.includes(family)) return color;
    }
    return FAMILY_COLORS.default;
  }

  const g6State = {
    nodes: [],
    edges: [],
    nodeMap: new Map(),
    selectedNodeId: '',
    aggregationThreshold: 100
  };

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ============================================
  // 初始化 G6 图
  // ============================================
  async function initG6Graph(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return null;

    if (graph) {
      graph.destroy();
      graph = null;
    }

    const width = container.offsetWidth || 1200;
    const height = container.offsetHeight || 700;

    // 加载 G6
    if (!window.G6) {
      await new Promise((resolve, reject) => {
        if (document.querySelector('script[src*="g6.min.js"]')) {
          resolve(); return;
        }
        const script = document.createElement('script');
        script.src = '/static/vendor/g6.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }

    // 注册自定义节点
    window.G6.registerNode('job-node', {
      draw(cfg, group) {
        const color = cfg.color || '#38bdf8';
        const w = cfg.width || 100;
        const h = cfg.height || 50;

        // 主体
        const rect = group.addShape('rect', {
          attrs: {
            x: -w/2, y: -h/2, width: w, height: h,
            fill: color, stroke: color, lineWidth: 2,
            radius: 6,
            shadowBlur: 12, shadowColor: `${color}55`
          }
        });

        // 顶部高光线
        group.addShape('rect', {
          attrs: {
            x: -w/2 + 6, y: -h/2 + 6, width: w - 12, height: 3,
            fill: '#ffffff', opacity: 0.8, radius: 1.5
          }
        });

        // 标签
        if (cfg.label) {
          group.addShape('text', {
            attrs: {
              x: 0, y: 4, text: cfg.label,
              fill: '#ffffff', fontSize: 10, fontWeight: 500,
              textAlign: 'center', textBaseline: 'middle'
            }
          });
        }

        return rect;
      },
      setState(name, value, item) {
        const group = item.getContainer();
        const rect = group.get('children')[0];
        if (!rect) return;

        if (name === 'selected') {
          rect.attr('shadowBlur', 25);
          rect.attr('shadowColor', '#ffffff66');
          rect.attr('lineWidth', 3);
        } else if (name === 'highlighted') {
          rect.attr('shadowBlur', 20);
          rect.attr('shadowColor', '#fbbf2466');
        } else if (name === 'faded') {
          rect.attr('opacity', 0.15);
        } else {
          rect.attr('shadowBlur', 12);
          rect.attr('shadowColor', `${rect.attr('fill')}55`);
          rect.attr('lineWidth', 2);
          rect.attr('opacity', 1);
        }
      }
    });

    // 创建图
    graph = new window.G6.Graph({
      container: containerId,
      width,
      height,
      fitView: true,
      fitViewPadding: 40,
      animate: true,
      animateCfg: { duration: 300, easing: 'easeQuadOut' },
      modes: {
        default: ['drag-canvas', 'zoom-canvas', 'drag-node']
      },
      defaultNode: {
        type: 'job-node',
        width: 80,
        height: 40
      },
      defaultEdge: {
        type: 'line',
        style: {
          stroke: '#6366f1', lineWidth: 1.5, opacity: 0.5,
          endArrow: { path: window.G6.Arrow.triangle(4, 6, 0), fill: '#6366f1' }
        }
      },
      // 力导向布局 - 适合大规模图
      layout: {
        type: 'force',
        preventOverlap: true,
        nodeSpacing: 30,
        linkDistance: 100,
        nodeStrength: -80,
        edgeStrength: 0.3,
        collideStrength: 0.8,
        alpha: 0.3,
        alphaDecay: 0.02,
        alphaMin: 0.001,
        forceSimulation: null
      },
      nodeStateStyles: {
        selected: {}, highlighted: {}, faded: {}
      },
      edgeStateStyles: {
        selected: { lineWidth: 3, opacity: 1, stroke: '#10b981' },
        faded: { opacity: 0.1 }
      },
      minZoom: 0.1,
      maxZoom: 4
    });

    // 事件
    graph.on('node:click', (evt) => {
      const node = evt.item;
      if (node) {
        selectNode(node.getModel().id);
      }
    });

    graph.on('node:dblclick', (evt) => {
      const node = evt.item;
      if (node && node.getModel().isCluster) {
        expandCluster(node.getModel().id);
      }
    });

    graph.on('canvas:click', () => {
      deselectAll();
    });

    graph.on('edge:mouseenter', (evt) => {
      const edge = evt.item;
      if (edge) {
        const model = edge.getModel();
        showEdgeTip(model);
      }
    });

    graph.on('edge:mouseleave', () => {
      hideEdgeTip();
    });

    return graph;
  }

  // ============================================
  // 选择与高亮
  // ============================================
  function selectNode(nodeId) {
    if (!graph) return;

    g6State.selectedNodeId = nodeId;

    // 清除状态
    graph.getNodes().forEach(n => graph.clearItemStates(n));
    graph.getEdges().forEach(e => graph.clearItemStates(e));

    const node = graph.findById(nodeId);
    if (!node) return;

    // 高亮选中节点
    graph.setItemState(node, 'selected', true);

    // 获取并高亮邻居
    const edges = node.getEdges();
    const neighborIds = new Set();

    edges.forEach(edge => {
      graph.setItemState(edge, 'selected', true);
      const model = edge.getModel();
      const nid = model.source === nodeId ? model.target : model.source;
      neighborIds.add(nid);
      const neighbor = graph.findById(nid);
      if (neighbor) graph.setItemState(neighbor, 'highlighted', true);
    });

    // 淡化其他
    graph.getNodes().forEach(n => {
      if (!neighborIds.has(n.getModel().id) && n.getModel().id !== nodeId) {
        graph.setItemState(n, 'faded', true);
      }
    });

    graph.focusItem(node, { duration: 200 });

    // 回调
    if (typeof window.onG6NodeSelect === 'function') {
      window.onG6NodeSelect(nodeId);
    }
  }

  function deselectAll() {
    if (!graph) return;
    g6State.selectedNodeId = '';
    graph.getNodes().forEach(n => graph.clearItemStates(n));
    graph.getEdges().forEach(e => graph.clearItemStates(e));
    if (typeof window.onG6NodeDeselect === 'function') {
      window.onG6NodeDeselect();
    }
  }

  // ============================================
  // 数据聚合
  // ============================================
  function aggregateNodes(rawNodes) {
    if (rawNodes.length <= g6State.aggregationThreshold) {
      return { aggregated: false, nodes: rawNodes, clusters: [] };
    }

    const familyMap = new Map();
    rawNodes.forEach(n => {
      const f = n.family || '其他';
      if (!familyMap.has(f)) familyMap.set(f, []);
      familyMap.get(f).push(n);
    });

    const result = [];
    const clusterMap = new Map();

    familyMap.forEach((nodes, family) => {
      if (nodes.length <= 3) {
        nodes.forEach(n => result.push({ ...n, isCluster: false }));
      } else {
        const cid = `cluster_${family}`;
        const avgDeg = nodes.reduce((s, n) => s + (n.degree || 1), 0) / nodes.length;
        result.push({
          id: cid, title: `${family} (${nodes.length})`, family, isCluster: true,
          clusterCount: nodes.length, memberNodes: nodes.map(n => n.id),
          degree: avgDeg, color: getFamilyColor(family),
          width: Math.min(100, 50 + nodes.length * 0.5), height: 50
        });
        clusterMap.set(cid, nodes);
      }
    });

    g6State.clusterData = clusterMap;
    return { aggregated: true, nodes: result, clusters: Array.from(clusterMap.keys()) };
  }

  function expandCluster(clusterId) {
    if (!graph || !g6State.clusterData.has(clusterId)) return;

    const clusterNode = graph.findById(clusterId);
    if (!clusterNode) return;

    const members = g6State.clusterData.get(clusterId);
    const model = clusterNode.getModel();

    graph.removeItem(clusterNode);

    members.forEach((node, i) => {
      const angle = (i / members.length) * Math.PI * 2;
      const r = Math.min(150, 40 + members.length * 2);
      graph.addItem('node', {
        ...node,
        x: (model.x || 0) + Math.cos(angle) * r,
        y: (model.y || 0) + Math.sin(angle) * r,
        color: getFamilyColor(node.family)
      });
    });

    g6State.clusterData.delete(clusterId);
  }

  // ============================================
  // Tooltip
  // ============================================
  let tipEl = null;

  function showEdgeTip(model) {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.style.cssText = `
        position:fixed;background:rgba(15,23,42,0.95);border:1px solid rgba(99,102,241,0.3);
        border-radius:10px;padding:10px 14px;color:#e2e8f0;font-size:12px;
        z-index:9999;pointer-events:none;max-width:260px;box-shadow:0 10px 30px rgba(0,0,0,0.4);
      `;
      document.body.appendChild(tipEl);
    }

    const src = g6State.nodeMap.get(model.source);
    const tgt = g6State.nodeMap.get(model.target);
    const rel = RELATION_META[model.relation] || RELATION_META.related;

    tipEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
        <span style="width:8px;height:8px;border-radius:50%;background:${rel.color};"></span>
        <strong style="color:${rel.color};font-size:11px;">${rel.label}</strong>
      </div>
      <div style="color:#94a3b8;margin-bottom:4px;">
        ${escapeHtml(src?.title || model.source)} → ${escapeHtml(tgt?.title || model.target)}
      </div>
    `;
    tipEl.style.display = 'block';
  }

  function hideEdgeTip() {
    if (tipEl) tipEl.style.display = 'none';
  }

  document.addEventListener('mousemove', (e) => {
    if (tipEl && tipEl.style.display !== 'none') {
      tipEl.style.left = e.clientX + 12 + 'px';
      tipEl.style.top = e.clientY + 12 + 'px';
    }
  });

  // ============================================
  // 渲染
  // ============================================
  async function renderGraph(rawNodes, rawEdges, options = {}) {
    const container = document.getElementById('careerGraphCanvas');
    if (!container) return;

    g6State.nodes = rawNodes;
    g6State.edges = rawEdges;
    g6State.nodeMap.clear();
    rawNodes.forEach(n => g6State.nodeMap.set(n.id, n));

    if (!graph) {
      await initG6Graph('careerGraphCanvas');
    }
    if (!graph) return;

    // 聚合
    const { nodes: aggNodes, aggregated } = aggregateNodes(rawNodes);

    // 转换节点
    const g6Nodes = aggNodes.map(node => {
      const color = node.isCluster ? node.color : getFamilyColor(node.family);
      return {
        id: node.id,
        label: node.title,
        title: node.title,
        family: node.family,
        level: node.level,
        cluster: node.cluster,
        width: node.width || 80,
        height: node.height || 40,
        color,
        isCluster: node.isCluster,
        clusterCount: node.clusterCount,
        memberNodes: node.memberNodes
      };
    });

    // 转换边
    const g6Edges = rawEdges.map((edge, i) => ({
      id: edge.id || `e${i}`,
      source: edge.source,
      target: edge.target,
      relation: edge.relation,
      confidence: edge.confidence
    }));

    graph.changeData({ nodes: g6Nodes, edges: g6Edges });
    graph.fitView();

    return { total: rawNodes.length, displayed: g6Nodes.length, aggregated };
  }

  // ============================================
  // API
  // ============================================
  window.CareerGraphG6 = {
    init: initG6Graph,
    render,
    select: selectNode,
    deselect: deselectAll,
    expandCluster,
    resize: () => {
      if (graph) {
        const c = document.getElementById('careerGraphCanvas');
        if (c) graph.changeSize(c.offsetWidth, c.offsetHeight);
      }
    },
    getGraph: () => graph
  };

})();
