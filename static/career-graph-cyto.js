/**
 * Cytoscape.js 职业图谱 - 简洁高效版
 * 特点：限制1000节点、全屏沉浸、悬浮高亮、即时搜索
 */
(function initCareerGraphCyto() {
  'use strict';

  let cy = null;
  const MAX_NODES = 1000;

  // 职业族颜色
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

  function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ============================================
  // 初始化
  // ============================================
  async function initCytoGraph(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return null;

    // 加载 Cytoscape
    if (!window.cytoscape) {
      await new Promise((resolve, reject) => {
        if (document.querySelector('script[src*="cytoscape"]')) { resolve(); return; }
        const script = document.createElement('script');
        script.src = '/static/vendor/cytoscape.min.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }

    // 销毁旧实例
    if (cy) { cy.destroy(); cy = null; }

    const width = container.offsetWidth || window.innerWidth;
    const height = container.offsetHeight || window.innerHeight - 60;

    cy = window.cytoscape({
      container: container,
      width: width,
      height: height,

      style: [
        {
          selector: 'node',
          style: {
            'width': 24,
            'height': 24,
            'shape': 'ellipse',
            'background-color': '#475569',
            'opacity': 0.4,
            'border-width': 2,
            'border-color': '#64748b',
            'label': 'data(label)',
            'color': '#e2e8f0',
            'font-size': 9,
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'text-opacity': 0,
            'font-family': 'PingFang SC, Microsoft YaHei, sans-serif',
            'transition-property': 'opacity, background-color, border-color, width, height',
            'transition-duration': '150ms'
          }
        },
        {
          selector: 'node.highlighted',
          style: {
            'opacity': 1,
            'background-color': '#38bdf8',
            'border-color': '#7dd3fc',
            'border-width': 2,
            'width': 32,
            'height': 32,
            'z-index': 10
          }
        },
        {
          selector: 'node.selected',
          style: {
            'opacity': 1,
            'background-color': '#f472b6',
            'border-color': '#fbcfe8',
            'border-width': 3,
            'width': 40,
            'height': 40,
            'font-size': 11,
            'font-weight': 600,
            'text-opacity': 1,
            'z-index': 20
          }
        },
        {
          selector: 'node.faded',
          style: {
            'opacity': 0.1,
            'z-index': 1
          }
        },
        {
          selector: 'node.show-label',
          style: {
            'text-opacity': 0.8,
            'font-size': 10
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 1,
            'line-color': '#334155',
            'opacity': 0.3,
            'curve-style': 'bezier',
            'target-arrow-shape': 'none',
            'transition-property': 'opacity, line-color',
            'transition-duration': '150ms'
          }
        },
        {
          selector: 'edge.highlighted',
          style: {
            'opacity': 0.8,
            'width': 1.5,
            'line-color': '#10b981',
            'z-index': 5
          }
        },
        {
          selector: 'edge.faded',
          style: {
            'opacity': 0.02,
            'z-index': 0
          }
        }
      ],

      layout: { name: 'preset' },
      minZoom: 0.15,
      maxZoom: 4,
      wheelSensitivity: 0.4
    });

    // 事件
    bindEvents();

    return cy;
  }

  // ============================================
  // 事件绑定
  // ============================================
  function bindEvents() {
    if (!cy) return;

    cy.on('tap', 'node', (evt) => {
      selectNode(evt.target.id());
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) deselectAll();
    });

    cy.on('mouseover', 'node', (evt) => {
      const node = evt.target;
      showTooltip(node);
      node.addClass('show-label');
    });

    cy.on('mouseout', 'node', (evt) => {
      const node = evt.target;
      if (node.id() !== window._cytoSelected) {
        node.removeClass('show-label');
      }
      hideTooltip();
    });
  }

  window._cytoSelected = '';

  function selectNode(nodeId) {
    if (!cy) return;
    window._cytoSelected = nodeId;

    const node = cy.getElementById(nodeId);
    const neighbors = node.neighborhood();

    cy.nodes().removeClass('highlighted selected faded show-label');
    cy.edges().removeClass('highlighted faded');

    cy.nodes().forEach(n => {
      const id = n.id();
      if (id === nodeId) {
        n.addClass('selected');
        n.addClass('show-label');
      } else if (neighbors.has(n)) {
        n.addClass('highlighted');
      } else {
        n.addClass('faded');
      }
    });

    cy.edges().forEach(e => {
      const s = e.source().id();
      const t = e.target().id();
      if (s === nodeId || t === nodeId) {
        e.addClass('highlighted');
      } else {
        e.addClass('faded');
      }
    });

    // 聚焦
    cy.animate({
      center: { eles: node },
      zoom: Math.max(cy.zoom(), 1.2),
      duration: 200
    });

    // 详情
    const data = node.data();
    showNodeDetail(data);

    if (typeof window.onCytoNodeSelect === 'function') {
      window.onCytoNodeSelect(nodeId, data);
    }
  }

  function deselectAll() {
    if (!cy) return;
    window._cytoSelected = '';

    cy.nodes().removeClass('highlighted selected faded');
    cy.edges().removeClass('highlighted faded');

    hideNodeDetail();

    if (typeof window.onCytoNodeDeselect === 'function') {
      window.onCytoNodeDeselect();
    }
  }

  // ============================================
  // Tooltip
  // ============================================
  let tooltipEl = null;

  function showTooltip(node) {
    if (!tooltipEl) {
      tooltipEl = document.createElement('div');
      tooltipEl.id = 'cyto-tooltip';
      tooltipEl.style.cssText = `
        position: fixed;
        background: rgba(15, 23, 42, 0.95);
        border: 1px solid rgba(99, 102, 241, 0.3);
        border-radius: 8px;
        padding: 10px 14px;
        color: #e2e8f0;
        font-size: 12px;
        z-index: 9999;
        pointer-events: none;
        max-width: 260px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
        opacity: 0;
        transition: opacity 100ms;
      `;
      document.body.appendChild(tooltipEl);
    }

    const data = node.data();
    const color = getFamilyColor(data.family);

    tooltipEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};flex-shrink:0;"></span>
        <strong style="font-size:13px;">${escapeHtml(data.title || data.label)}</strong>
      </div>
      <div style="font-size:11px;color:#94a3b8;line-height:1.5;">
        ${escapeHtml([data.family, data.level, data.city].filter(Boolean).join(' · ') || (data.cluster ? '职业簇: ' + data.cluster : ''))}
      </div>
      ${data.salaryMin || data.salaryMax ? `
        <div style="margin-top:6px;font-size:12px;color:#34d399;">
          ${formatSalary(data)}
        </div>
      ` : ''}
    `;

    tooltipEl.style.opacity = '1';
  }

  function showEdgeTip(edge) {
    if (!tooltipEl) return;
    const data = edge.data();
    tooltipEl.innerHTML = `
      <div style="font-size:11px;color:#94a3b8;">${escapeHtml(data.relation || '关联关系')}</div>
    `;
    tooltipEl.style.opacity = '1';
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.style.opacity = '0';
  }

  document.addEventListener('mousemove', (e) => {
    if (tooltipEl && tooltipEl.style.opacity !== '0') {
      tooltipEl.style.left = Math.min(e.clientX + 12, window.innerWidth - 280) + 'px';
      tooltipEl.style.top = e.clientY + 12 + 'px';
    }
  });

  function formatSalary(node) {
    const min = node.salaryMin, max = node.salaryMax;
    if (min && max) return `${min}-${max}万/月`;
    if (min) return `${min}万/月起`;
    if (max) return `最高${max}万/月`;
    return '';
  }

  // ============================================
  // 详情面板
  // ============================================
  let detailPanel = null;

  function showNodeDetail(data) {
    if (!detailPanel) detailPanel = document.getElementById('cyto-detail-panel');
    if (!detailPanel) return;

    const color = getFamilyColor(data.family);
    detailPanel.innerHTML = `
      <div class="cyto-detail-header">
        <span class="cyto-detail-dot" style="background:${color};"></span>
        <div>
          <h3 class="cyto-detail-title">${escapeHtml(data.title || data.label)}</h3>
          <p class="cyto-detail-meta">${escapeHtml([data.family, data.level, data.city].filter(Boolean).join(' · '))}</p>
        </div>
      </div>
      ${(data.salaryMin || data.salaryMax) ? `
        <div class="cyto-detail-stat">
          <span class="cyto-detail-stat-label">薪资</span>
          <span class="cyto-detail-stat-value">${formatSalary(data)}</span>
        </div>
      ` : ''}
      ${data.skills && data.skills.length ? `
        <div class="cyto-detail-section">
          <span class="cyto-detail-section-label">核心技能</span>
          <div class="cyto-detail-tags">
            ${data.skills.slice(0, 5).map(s => `<span class="cyto-detail-tag">${escapeHtml(s)}</span>`).join('')}
          </div>
        </div>
      ` : ''}
    `;
    detailPanel.classList.add('visible');
  }

  function hideNodeDetail() {
    if (detailPanel) detailPanel.classList.remove('visible');
  }

  // ============================================
  // 数据渲染
  // ============================================
  async function renderGraph(rawNodes, rawEdges, options = {}) {
    const container = document.getElementById('careerGraphCanvas');
    if (!container) return;

    if (!cy) await initCytoGraph('careerGraphCanvas');
    if (!cy) return;

    // 限制节点数量
    let displayNodes = rawNodes;
    if (displayNodes.length > MAX_NODES) {
      displayNodes = displayNodes.slice(0, MAX_NODES);
    }

    const displayNodeIds = new Set(displayNodes.map(n => n.id));
    const displayEdges = rawEdges.filter(e =>
      displayNodeIds.has(e.source) && displayNodeIds.has(e.target)
    );

    // 记录位置
    const positions = {};

    cy.elements().remove();

    const elements = [];

    // 节点
    displayNodes.forEach((node, i) => {
      const color = getFamilyColor(node.family);
      elements.push({
        data: {
          id: node.id,
          label: node.title,
          title: node.title,
          family: node.family,
          cluster: node.cluster,
          level: node.level,
          city: node.city,
          skills: node.skills || [],
          salaryMin: node.salaryMin,
          salaryMax: node.salaryMax
        },
        position: { x: (i % 80) * 50 + Math.random() * 30, y: Math.floor(i / 80) * 50 + Math.random() * 30 }
      });
    });

    // 边
    displayEdges.forEach(edge => {
      elements.push({
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          relation: edge.relation || 'related'
        }
      });
    });

    cy.add(elements);

    // 初始淡化
    cy.nodes().addClass('faded');

    // 高亮推荐
    if (options.recommendationIds && options.recommendationIds.length) {
      const recSet = new Set(options.recommendationIds);
      cy.nodes().forEach(n => {
        if (recSet.has(n.id())) {
          n.removeClass('faded');
          n.addClass('highlighted');
        }
      });
    }

    // 布局 - 力导向但更轻量
    cy.layout({
      name: 'cose',
      animate: false,
      fit: true,
      padding: 50,
      nodeRepulsion: 6000,
      idealEdgeLength: 60,
      edgeElasticity: 50,
      gravity: 0.2,
      numIter: 200,
      randomize: true
    }).run();

    return {
      total: displayNodes.length,
      totalOriginal: rawNodes.length,
      edges: displayEdges.length
    };
  }

  // ============================================
  // 搜索高亮
  // ============================================
  function highlightSearch(query) {
    if (!cy) return;

    if (!query || !query.trim()) {
      cy.nodes().removeClass('highlighted faded');
      cy.edges().removeClass('highlighted faded');
      // 恢复推荐高亮
      return;
    }

    const q = query.toLowerCase();
    let matched = 0;

    cy.nodes().forEach(n => {
      const text = (n.data('title') || '') + (n.data('family') || '') + (n.data('cluster') || '');
      if (text.toLowerCase().includes(q)) {
        n.removeClass('faded');
        n.addClass('highlighted');
        matched++;
      } else {
        n.addClass('faded');
        n.removeClass('highlighted');
      }
    });

    cy.edges().addClass('faded');

    return matched;
  }

  // ============================================
  // API
  // ============================================
  window.CareerGraphCyto = {
    init: initCytoGraph,
    render: renderGraph,
    select: selectNode,
    deselect: deselectAll,
    highlightSearch,
    resize: () => { if (cy) cy.resize(); },
    getCy: () => cy
  };

})();
