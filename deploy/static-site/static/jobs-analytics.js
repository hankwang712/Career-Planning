/**
 * 城市招聘全景分析仪表盘
 * 依赖：Chart.js（已在 base.html 引入）
 * 入口：window.initJobsAnalytics(jobs)
 *
 * 关键设计原则：
 *   1. 先销毁所有 Chart.js 实例，再替换 innerHTML——避免 canvas context 泄漏导致白屏
 *   2. S.ready 标志防止重复初始化（loadJobs 只触发一次，但做防御）
 *   3. Tab 点击通过 HTML onclick 属性绑定，彻底避免 addEventListener 累积
 */
(function () {
  "use strict";

  // ── 配色板 ────────────────────────────────────────────────────────────────
  const PAL = [
    "#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
    "#ef4444", "#ec4899", "#0ea5e9", "#14b8a6", "#f97316",
    "#84cc16", "#a855f7", "#64748b", "#eab308", "#22d3ee"
  ];

  // ── 状态 ──────────────────────────────────────────────────────────────────
  const S = { jobs: [], city: "all", tab: "salary", ready: false, charts: {} };

  // ── 工具函数 ──────────────────────────────────────────────────────────────
  function cityOf(j) { return (String(j["城市"] || j["采集城市"] || "")).trim(); }
  function byCity(jobs, c) { return c === "all" ? jobs : jobs.filter(j => cityOf(j) === c); }
  function getCities(jobs) { return [...new Set(jobs.map(cityOf).filter(Boolean))].sort(); }
  function countBy(jobs, fn) {
    const m = {};
    jobs.forEach(j => { const k = fn(j); if (k) m[k] = (m[k] || 0) + 1; });
    return m;
  }
  function topN(map, n) { return Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, n); }
  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  // ── Chart.js 实例管理 ─────────────────────────────────────────────────────
  /**
   * ⚠️ 必须先调此函数销毁所有实例，再替换 innerHTML
   * 原因：Chart.js 在 canvas 从 DOM 移除前必须 .destroy()，
   *       否则 WebGL/2D context 不会释放，多次切换后浏览器耗尽 context 导致白屏
   */
  function destroyAllCharts() {
    Object.keys(S.charts).forEach(id => {
      try { if (S.charts[id]) S.charts[id].destroy(); } catch (_) {}
      delete S.charts[id];
    });
  }

  // ── 薪资解析 ──────────────────────────────────────────────────────────────
  function parseSalary(s) {
    const str = String(s || "").trim();
    const km = str.match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)K/);
    if (km) return { lo: +km[1], hi: +km[2] };
    const dm = str.match(/(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)元\/天/);
    if (dm) return { lo: +(+dm[1] * 22 / 1000).toFixed(1), hi: +(+dm[2] * 22 / 1000).toFixed(1) };
    return null;
  }
  function salBracket(s) {
    const m = (s.lo + s.hi) / 2;
    return m < 5 ? "<5K" : m < 8 ? "5-8K" : m < 12 ? "8-12K" : m < 20 ? "12-20K" : ">20K";
  }

  // ── 技能解析 ──────────────────────────────────────────────────────────────
  function getSkillMap(jobs) {
    const m = {};
    jobs.forEach(j => {
      String(j["技能要求"] || "").split(/[,，、\s]+/).forEach(s => {
        s = s.trim();
        if (s && s.length >= 2 && s.length <= 20) m[s] = (m[s] || 0) + 1;
      });
    });
    return m;
  }

  // ── 共用 Chart 选项 ───────────────────────────────────────────────────────
  const LEGEND_OPTS = { position: "top", labels: { font: { size: 10 }, boxWidth: 12, padding: 8 } };
  function baseOpts(extra) {
    return Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 350 }, plugins: { legend: LEGEND_OPTS } }, extra || {});
  }
  function stackedOpts() {
    return baseOpts({
      plugins: { legend: LEGEND_OPTS },
      scales: {
        x: { stacked: true, ticks: { font: { size: 10 } } },
        y: { stacked: true, max: 100, ticks: { callback: v => v + "%", font: { size: 10 } } }
      }
    });
  }

  // ── 面板 HTML 模板 ────────────────────────────────────────────────────────
  function setPanel(html) {
    const el = document.getElementById("analyticsPanel");
    if (el) el.innerHTML = html;
  }
  function grid2(a, b) {
    return `<div class="ac-grid-2">${card(a)}${card(b)}</div>`;
  }
  function card(inner) { return `<div class="ac-card">${inner}</div>`; }
  function cardHead(title, hint) {
    return `<div class="ac-card-head"><h4>${esc(title)}</h4><span class="ac-hint">${hint}</span></div>`;
  }
  function canvasWrap(id) { return `<div class="ac-canvas-wrap"><canvas id="${id}"></canvas></div>`; }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 1 — 薪资对比
  // ══════════════════════════════════════════════════════════════════════════
  function renderSalaryTab() {
    destroyAllCharts();   // ① 先销毁
    const cities = getCities(S.jobs);
    // 高度按城市数量动态计算，避免 canvas 截断
    const srH = Math.max(320, cities.length * 36);
    const sdH = Math.max(280, cities.length * 28);
    setPanel(grid2(      // ② 再替换 HTML
      cardHead("城市薪资区间对比", "橙线 = 中位月薪，蓝色 = P25-P75 区间") + `<div class="ac-canvas-wrap" style="height:${srH}px"><canvas id="acSR"></canvas></div>`,
      cardHead("薪资段分布", "各薪资区间岗位占比 %") + `<div class="ac-canvas-wrap" style="height:${sdH}px"><canvas id="acSD"></canvas></div>`
    ));
    _salaryRange(cities);      // ③ 最后创建新图
    _salaryDist(cities);
  }

  function _pct(arr, p) {
    // 返回已排序数组 arr 的第 p 百分位值（0-100）
    if (!arr.length) return 0;
    const idx = (p / 100) * (arr.length - 1);
    const lo = Math.floor(idx), hi = Math.ceil(idx);
    return +(arr[lo] + (arr[hi] - arr[lo]) * (idx - lo)).toFixed(1);
  }

  function _salaryRange(cities) {
    const labels = [], ranges = [], medians = [];
    cities.forEach(city => {
      const mids = byCity(S.jobs, city)
        .map(j => parseSalary(j["薪资"]))
        .filter(Boolean)
        .map(s => (s.lo + s.hi) / 2)
        .sort((a, b) => a - b);
      if (!mids.length) return;
      // P25-P75 区间：中位线必然在柱内
      const p25 = _pct(mids, 25);
      const p50 = _pct(mids, 50);
      const p75 = _pct(mids, 75);
      labels.push(city);
      ranges.push([p25, p75]);
      medians.push(p50);
    });
    const ctx = document.getElementById("acSR");
    if (!ctx) return;
    S.charts.sr = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "P25-P75 薪资区间",
            data: ranges,
            backgroundColor: "rgba(99,102,241,0.30)",
            borderColor: "#6366f1",
            borderWidth: 1.5,
            borderSkipped: false
          },
          {
            type: "line",
            label: "中位月薪 (P50)",
            data: medians,
            borderColor: "#f97316",
            backgroundColor: "#f97316",
            pointRadius: 5,
            pointHoverRadius: 7,
            borderWidth: 2,
            fill: false,
            tension: 0
          }
        ]
      },
      options: baseOpts({
        indexAxis: "y",
        plugins: {
          legend: LEGEND_OPTS,
          tooltip: {
            callbacks: {
              label: c => c.dataset.label.startsWith("中位")
                ? `中位薪资：${c.parsed.x}K`
                : `P25-P75 区间：${Array.isArray(c.raw) ? c.raw[0] + "K ~ " + c.raw[1] + "K" : c.parsed.x + "K"}`
            }
          }
        },
        scales: {
          x: { title: { display: true, text: "月薪 (K)", font: { size: 10 } }, min: 0 },
          y: { ticks: { font: { size: 11 } } }
        }
      })
    });
  }

  function _salaryDist(cities) {
    cities = cities || getCities(S.jobs);
    const brackets = ["<5K", "5-8K", "8-12K", "12-20K", ">20K"];
    const datasets = brackets.map((lb, i) => ({
      label: lb,
      data: cities.map(city => {
        const sals = byCity(S.jobs, city).map(j => parseSalary(j["薪资"])).filter(Boolean);
        return sals.length ? +((sals.filter(s => salBracket(s) === lb).length / sals.length * 100).toFixed(1)) : 0;
      }),
      backgroundColor: PAL[i * 2 % PAL.length], borderWidth: 0
    }));
    const ctx = document.getElementById("acSD");
    if (!ctx) return;
    S.charts.sd = new Chart(ctx, { type: "bar", data: { labels: cities, datasets }, options: stackedOpts() });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 2 — 产业生态
  // ══════════════════════════════════════════════════════════════════════════
  function renderIndustryTab() {
    destroyAllCharts();
    const cityLabel = S.city === "all" ? "全国" : S.city;
    setPanel(grid2(
      cardHead(cityLabel + " 主导行业", "极坐标玫瑰图 · Top 8") + canvasWrap("acPolar"),
      cardHead("企业规模分布", "各城市按公司规模分层 %") + canvasWrap("acScale")
    ));
    _industryPolar();
    _companyScale();
  }

  function _industryPolar() {
    const top = topN(countBy(byCity(S.jobs, S.city), j => (j["公司行业"] || "").trim() || null), 8);
    const ctx = document.getElementById("acPolar");
    if (!ctx || !top.length) return;
    S.charts.polar = new Chart(ctx, {
      type: "polarArea",
      data: { labels: top.map(([k]) => k), datasets: [{ data: top.map(([, v]) => v), backgroundColor: PAL.slice(0, 8).map(c => c + "bb"), borderWidth: 1 }] },
      options: baseOpts({ plugins: { legend: { position: "right", labels: { font: { size: 10 }, boxWidth: 12 } } } })
    });
  }

  function _companyScale() {
    const scaleOrder = ["0-20人", "20-99人", "100-499人", "500-999人", "1000-9999人", "10000人以上"];
    const cities = getCities(S.jobs);
    const datasets = scaleOrder.map((s, i) => ({
      label: s,
      data: cities.map(city => { const cj = byCity(S.jobs, city); return cj.length ? +((cj.filter(j => j["公司规模"] === s).length / cj.length * 100).toFixed(1)) : 0; }),
      backgroundColor: PAL[i * 2 % PAL.length], borderWidth: 0
    }));
    const ctx = document.getElementById("acScale");
    if (!ctx) return;
    S.charts.scale = new Chart(ctx, { type: "bar", data: { labels: cities, datasets }, options: stackedOpts() });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 3 — 技能图谱
  // ══════════════════════════════════════════════════════════════════════════
  function renderSkillsTab() {
    destroyAllCharts();
    const cityLabel = S.city === "all" ? "全国" : S.city;
    // 上下布局：词云全宽置顶（高度紧凑），热图全宽在下（更宽更清晰）
    setPanel(`
      <div class="ac-card" style="margin-bottom:12px;">
        ${cardHead(cityLabel + " 技能词云", "字号 ∝ 出现频次")}
        <div id="acCloud" class="ac-cloud ac-cloud-compact"></div>
      </div>
      <div class="ac-card">
        ${cardHead("各城市技能需求热图", "Top 15 技能 · 颜色深 = 出现率高")}
        <div id="acSkillHeatmap" class="ac-skill-heatmap-wrap"></div>
      </div>
    `);
    _skillCloud();
    _skillHeatmap();
  }

  function _skillCloud() {
    const el = document.getElementById("acCloud");
    if (!el) return;
    const top = topN(getSkillMap(byCity(S.jobs, S.city)), 45);
    if (!top.length) { el.innerHTML = '<p class="ac-empty">暂无技能标签数据</p>'; return; }
    const maxV = top[0][1];
    const shuffled = [...top].sort(() => Math.random() - 0.5);
    el.innerHTML = shuffled.map(([skill, cnt]) => {
      const r = cnt / maxV;
      const sz = Math.round(11 + r * 20);
      const ci = Math.abs((skill.charCodeAt(0) * 7 + skill.length * 13) % PAL.length);
      return `<span class="ac-word" style="font-size:${sz}px;color:${PAL[ci]};opacity:${(0.55 + r * 0.45).toFixed(2)}" title="${esc(skill)}: ${cnt}次">${esc(skill)}</span>`;
    }).join(" ");
  }

  // 用热图替换雷达图，多城市对比时清晰度远胜雷达
  function _skillHeatmap() {
    const el = document.getElementById("acSkillHeatmap");
    if (!el) return;
    const cities = getCities(S.jobs);
    const topSkills = topN(getSkillMap(S.jobs), 15).map(([k]) => k);
    if (!topSkills.length) { el.innerHTML = '<p class="ac-empty">暂无技能数据</p>'; return; }

    // 计算每个城市每个技能的出现率（%）
    const matrix = {};
    cities.forEach(city => {
      const cj = byCity(S.jobs, city);
      const sm = getSkillMap(cj);
      const total = cj.length || 1;
      matrix[city] = {};
      topSkills.forEach(sk => { matrix[city][sk] = +((sm[sk] || 0) / total * 100).toFixed(1); });
    });
    const maxVal = Math.max(...cities.flatMap(c => topSkills.map(sk => matrix[c][sk])), 1);

    el.innerHTML = `
      <table class="ac-heatmap">
        <thead>
          <tr>
            <th class="ac-hm-city">城市</th>
            ${topSkills.map(sk => `<th class="ac-hm-label" title="${esc(sk)}">${esc(sk)}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${cities.map(city => `
            <tr>
              <td class="ac-hm-city-cell">${esc(city)}</td>
              ${topSkills.map(sk => {
                const v = matrix[city][sk];
                const r = v / maxVal;
                const alpha = r < 0.01 ? 0 : +(0.08 + r * 0.82).toFixed(2);
                const fg = r > 0.55 ? "#fff" : "#374151";
                return `<td class="ac-hm-val" style="background:rgba(16,185,129,${alpha});color:${fg}" title="${esc(city)} · ${esc(sk)}: ${v}%">${v > 0 ? v + "%" : ""}</td>`;
              }).join("")}
            </tr>`).join("")}
        </tbody>
      </table>`;
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 4 — 实习画像（数据全部为应届/实习岗，学历分布无意义，改为出勤 & 岗位类型）
  // ══════════════════════════════════════════════════════════════════════════

  // 从"5天/周 3个月"格式提取每周天数标签
  function _parseDaysPerWeek(exp) {
    const s = String(exp || "");
    const m = s.match(/(\d+)天\/周/);
    if (m) return m[1] + "天/周";
    return (s.includes("应届") || s.includes("在校")) ? "灵活" : "其他";
  }

  // 从"5天/周 3个月"格式提取实习时长标签
  function _parseDuration(exp) {
    const s = String(exp || "");
    const m = s.match(/(\d+)个月/);
    if (!m) return (s.includes("应届") || s.includes("在校")) ? "不限" : "其他";
    const n = +m[1];
    return n <= 2 ? "≤2个月" : n === 3 ? "3个月" : n <= 5 ? "4-5个月" : "6个月+";
  }

  function renderThresholdTab() {
    destroyAllCharts();
    const cities = getCities(S.jobs);
    const h = Math.max(280, cities.length * 26);
    const cityLabel = S.city === "all" ? "全国" : S.city;
    setPanel(grid2(
      cardHead("各城市每周出勤要求", "灵活 = 在校/应届不限时；按城市对比") +
        `<div class="ac-canvas-wrap" style="height:${h}px"><canvas id="acDays"></canvas></div>`,
      cardHead(cityLabel + " 热门岗位类型 Top 10", "基于职位类别字段统计") +
        `<div class="ac-canvas-wrap" style="height:${h}px"><canvas id="acJobType"></canvas></div>`
    ));
    _daysPerWeekChart(cities);
    _jobTypeChart(cityLabel);
  }

  function _daysPerWeekChart(cities) {
    const dayLabels = ["灵活", "3天/周", "4天/周", "5天/周", "6天/周", "其他"];
    const colors = ["#10b981", "#06b6d4", "#6366f1", "#f97316", "#ef4444", "#94a3b8"];
    const datasets = dayLabels.map((lb, i) => ({
      label: lb,
      data: cities.map(city => {
        const cj = byCity(S.jobs, city);
        return cj.length ? +((cj.filter(j => _parseDaysPerWeek(j["经验要求"]) === lb).length / cj.length * 100).toFixed(1)) : 0;
      }),
      backgroundColor: colors[i],
      borderWidth: 0
    }));
    const ctx = document.getElementById("acDays");
    if (!ctx) return;
    S.charts.days = new Chart(ctx, { type: "bar", data: { labels: cities, datasets }, options: stackedOpts() });
  }

  function _jobTypeChart() {
    const jobs = byCity(S.jobs, S.city);
    const typeMap = countBy(jobs, j => (j["职位类别"] || "").trim() || null);
    const top10 = topN(typeMap, 10);
    if (!top10.length) return;
    const labels = top10.map(([k]) => k).reverse();
    const values = top10.map(([, v]) => v).reverse();
    const ctx = document.getElementById("acJobType");
    if (!ctx) return;
    S.charts.jobType = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "岗位数",
          data: values,
          backgroundColor: labels.map((_, i) => PAL[i % PAL.length] + "cc"),
          borderWidth: 0
        }]
      },
      options: baseOpts({
        indexAxis: "y",
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: c => `${c.parsed.x} 个岗位` } }
        },
        scales: {
          x: { ticks: { font: { size: 10 } }, title: { display: true, text: "岗位数量", font: { size: 10 } } },
          y: { ticks: { font: { size: 11 } } }
        }
      })
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 城市选择器
  // ══════════════════════════════════════════════════════════════════════════
  function renderCityChips() {
    const el = document.getElementById("analyticsCityChips");
    if (!el) return;
    const cities = ["all", ...getCities(S.jobs)];
    el.innerHTML = cities.map(c => {
      const label = c === "all" ? "全部城市" : c;
      return `<button class="ac-city-chip${c === S.city ? " active" : ""}" onclick="analyticsSelectCity('${esc(c)}')">${esc(label)}</button>`;
    }).join("");
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 路由（通过 HTML onclick 绑定，不用 addEventListener 累积）
  // ══════════════════════════════════════════════════════════════════════════
  function renderTab(tab) {
    S.tab = tab;
    document.querySelectorAll(".ac-tab").forEach(btn => btn.classList.toggle("active", btn.dataset.tab === tab));
    switch (tab) {
      case "salary":    renderSalaryTab();    break;
      case "industry":  renderIndustryTab();  break;
      case "skills":    renderSkillsTab();    break;
      case "threshold": renderThresholdTab(); break;
    }
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 公开 API
  // ══════════════════════════════════════════════════════════════════════════
  function init(jobs) {
    if (!Array.isArray(jobs) || !jobs.length) return;
    if (S.ready) return;   // 防重复初始化（section 切换不触发重复 init）

    S.jobs = jobs;
    S.ready = true;

    const hub = document.getElementById("jobsAnalyticsHub");
    if (hub) hub.classList.remove("hidden");

    const counter = document.getElementById("analyticsJobCount");
    if (counter) counter.textContent = `共 ${jobs.length} 条样本`;

    renderCityChips();
    renderTab("salary");
  }

  window.initJobsAnalytics = init;

  window.analyticsSelectCity = function (city) {
    S.city = city;
    renderCityChips();
    renderTab(S.tab);
  };

  // Tab 点击路由（通过全局函数绑定，避免 addEventListener 累积）
  window.analyticsSelectTab = function (tab) { renderTab(tab); };
})();
