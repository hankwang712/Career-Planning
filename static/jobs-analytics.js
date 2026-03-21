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
    setPanel(grid2(      // ② 再替换 HTML
      cardHead("城市薪资区间对比", "橙线 = 中位月薪，蓝色 = 均值范围") + canvasWrap("acSR"),
      cardHead("薪资段分布", "各薪资区间岗位占比 %") + canvasWrap("acSD")
    ));
    _salaryRange();      // ③ 最后创建新图
    _salaryDist();
  }

  function _salaryRange() {
    const cities = getCities(S.jobs);
    const labels = [], ranges = [], medians = [];
    cities.forEach(city => {
      const sals = byCity(S.jobs, city).map(j => parseSalary(j["薪资"])).filter(Boolean);
      if (!sals.length) return;
      const avgLo = sals.reduce((a, s) => a + s.lo, 0) / sals.length;
      const avgHi = sals.reduce((a, s) => a + s.hi, 0) / sals.length;
      const mids = sals.map(s => (s.lo + s.hi) / 2).sort((a, b) => a - b);
      labels.push(city);
      ranges.push([+avgLo.toFixed(1), +avgHi.toFixed(1)]);
      medians.push(+mids[Math.floor(mids.length / 2)].toFixed(1));
    });
    const ctx = document.getElementById("acSR");
    if (!ctx) return;
    S.charts.sr = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          { label: "薪资区间（均值）", data: ranges, backgroundColor: "rgba(99,102,241,0.35)", borderColor: "#6366f1", borderWidth: 1, borderSkipped: false },
          { type: "line", label: "中位月薪", data: medians, borderColor: "#f97316", backgroundColor: "#f97316", pointRadius: 5, borderWidth: 2, fill: false }
        ]
      },
      options: baseOpts({
        indexAxis: "y",
        plugins: {
          legend: LEGEND_OPTS,
          tooltip: { callbacks: { label: c => c.dataset.label === "中位月薪" ? `中位：${c.parsed.x}K` : `区间：${Array.isArray(c.raw) ? c.raw[0] + "K - " + c.raw[1] + "K" : c.parsed.x + "K"}` } }
        },
        scales: { x: { title: { display: true, text: "月薪 (K)", font: { size: 10 } }, min: 0 }, y: { ticks: { font: { size: 11 } } } }
      })
    });
  }

  function _salaryDist() {
    const brackets = ["<5K", "5-8K", "8-12K", "12-20K", ">20K"];
    const cities = getCities(S.jobs);
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
    setPanel(grid2(
      cardHead(cityLabel + " 技能词云", "字号 ∝ 出现频次") + `<div id="acCloud" class="ac-cloud"></div>`,
      cardHead("城市核心技能需求雷达", "Top 6 技能 · 各城市频率对比") + canvasWrap("acRadar")
    ));
    _skillCloud();
    _skillRadar();
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

  function _skillRadar() {
    const cities = getCities(S.jobs).slice(0, 9);
    const topSkills = topN(getSkillMap(S.jobs), 6).map(([k]) => k);
    const ctx = document.getElementById("acRadar");
    if (!ctx || !topSkills.length) return;
    S.charts.radar = new Chart(ctx, {
      type: "radar",
      data: {
        labels: topSkills,
        datasets: cities.map((city, i) => {
          const sm = getSkillMap(byCity(S.jobs, city));
          const total = byCity(S.jobs, city).length || 1;
          return { label: city, data: topSkills.map(sk => +((sm[sk] || 0) / total * 100).toFixed(1)), backgroundColor: PAL[i % PAL.length] + "22", borderColor: PAL[i % PAL.length], borderWidth: 1.5, pointRadius: 3 };
        })
      },
      options: baseOpts({
        plugins: { legend: { position: "right", labels: { font: { size: 9 }, boxWidth: 10 } } },
        scales: { r: { ticks: { font: { size: 9 }, callback: v => v + "%" }, pointLabels: { font: { size: 10 } } } }
      })
    });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 4 — 人才门槛
  // ══════════════════════════════════════════════════════════════════════════
  function renderThresholdTab() {
    destroyAllCharts();
    setPanel(grid2(
      cardHead("学历要求分布", "各城市岗位学历门槛占比") + canvasWrap("acEdu"),
      cardHead("实习期要求分布", "实习周期偏好对比") + canvasWrap("acDur")
    ));
    _education();
    _internDuration();
  }

  function _education() {
    const cities = getCities(S.jobs);
    const levels = ["大专", "本科", "硕士", "博士"];
    const eduOf = j => { const e = (j["学历要求"] || "").trim(); return levels.includes(e) ? e : "不限"; };
    const datasets = [...levels, "不限"].map((lv, i) => ({
      label: lv,
      data: cities.map(city => { const cj = byCity(S.jobs, city); return cj.length ? +((cj.filter(j => eduOf(j) === lv).length / cj.length * 100).toFixed(1)) : 0; }),
      backgroundColor: PAL[i * 2 % PAL.length], borderWidth: 0
    }));
    const ctx = document.getElementById("acEdu");
    if (!ctx) return;
    S.charts.edu = new Chart(ctx, { type: "bar", data: { labels: cities, datasets }, options: stackedOpts() });
  }

  function _internDuration() {
    const cities = getCities(S.jobs);
    const parseDur = exp => {
      const s = String(exp || "");
      const m = s.match(/(\d+)个月/);
      if (m) { const n = +m[1]; return n <= 3 ? "≤3个月" : n <= 6 ? "4-6个月" : ">6个月"; }
      return (s.includes("应届") || s.includes("在校")) ? "应届生" : "其他";
    };
    const durLabels = ["应届生", "≤3个月", "4-6个月", ">6个月", "其他"];
    const datasets = durLabels.map((lb, i) => ({
      label: lb,
      data: cities.map(city => { const cj = byCity(S.jobs, city); return cj.length ? +((cj.filter(j => parseDur(j["经验要求"]) === lb).length / cj.length * 100).toFixed(1)) : 0; }),
      backgroundColor: PAL[(i * 3) % PAL.length], borderWidth: 0
    }));
    const ctx = document.getElementById("acDur");
    if (!ctx) return;
    S.charts.dur = new Chart(ctx, { type: "bar", data: { labels: cities, datasets }, options: stackedOpts() });
  }

  // ══════════════════════════════════════════════════════════════════════════
  // Tab 5 — 福利竞争力
  // ══════════════════════════════════════════════════════════════════════════
  function renderWelfareTab() {
    destroyAllCharts();
    setPanel(`<div class="ac-card ac-card-full">${cardHead("城市福利竞争力热图", "颜色深浅 = 该福利出现率 %，越深越普遍")}<div id="acHeatmap" class="ac-heatmap-wrap"></div></div>`);
    _welfareHeatmap();
  }

  function _welfareHeatmap() {
    const el = document.getElementById("acHeatmap");
    if (!el) return;
    const cities = getCities(S.jobs);
    const wmap = {};
    S.jobs.forEach(j => {
      String(j["公司福利"] || "").split(/[,，、]+/).forEach(w => {
        w = w.trim();
        if (w && w.length >= 2 && w.length <= 10) wmap[w] = (wmap[w] || 0) + 1;
      });
    });
    const topW = topN(wmap, 15).map(([k]) => k);
    if (!topW.length) { el.innerHTML = '<p class="ac-empty">暂无福利数据</p>'; return; }

    const matrix = {};
    cities.forEach(city => {
      const cj = byCity(S.jobs, city);
      matrix[city] = {};
      topW.forEach(w => { matrix[city][w] = cj.length ? Math.round(cj.filter(j => String(j["公司福利"] || "").includes(w)).length / cj.length * 100) : 0; });
    });
    const maxVal = Math.max(...cities.flatMap(c => topW.map(w => matrix[c][w])), 1);

    el.innerHTML = `
      <table class="ac-heatmap">
        <thead><tr><th class="ac-hm-city">城市</th>${topW.map(w => `<th class="ac-hm-label">${esc(w)}</th>`).join("")}</tr></thead>
        <tbody>${cities.map(city => `
          <tr>
            <td class="ac-hm-city-cell">${esc(city)}</td>
            ${topW.map(w => {
              const v = matrix[city][w];
              const r = v / maxVal;
              const alpha = (0.08 + r * 0.82).toFixed(2);
              const fg = r > 0.55 ? "#fff" : "#374151";
              return `<td class="ac-hm-val" style="background:rgba(99,102,241,${alpha});color:${fg}" title="${esc(city)} · ${esc(w)}: ${v}%">${v}%</td>`;
            }).join("")}
          </tr>`).join("")}
        </tbody>
      </table>`;
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
      case "welfare":   renderWelfareTab();   break;
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
