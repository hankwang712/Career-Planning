(function () {
  "use strict";
  const root = document.getElementById("liveJobMarket");
  if (!root) return;
  const API = "/api/job-market";
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const types = { intern: "实习", graduate: "校招 / 应届", experienced: "社招", unknown: "类型待核对" };
  const states = { queued: "等待采集", running: "正在采集", succeeded: "已更新", partial: "部分更新", failed: "采集未成功", empty: "未获取到岗位", unavailable: "环境待配置", timeout: "达到时限", cancelled: "已停止", interrupted: "任务中断" };
  const units = { month: "月", day: "天", year: "年", hour: "小时", unknown: "待确认" };
  const sourceNames = { ncss: "国家就业平台", api: "企业直招", shixiseng: "实习僧", website: "企业官网" };
  let active = false, page = 1, pages = 1, generation = 0, timer = null, statusData = null, busy = false;
  const filters = new URLSearchParams({ days: "30", sort: "recent" });
  const number = value => Number(value || 0).toLocaleString("zh-CN");
  const time = (value, full = false) => value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", ...(full ? { hour: "2-digit", minute: "2-digit" } : {}) }) : "尚无记录";
  const empty = (title, copy) => `<div class="lm-empty"><strong>${esc(title)}</strong><p>${esc(copy)}</p></div>`;
  function feedback(message, error = false) { el("lmFeedback").textContent = message; el("lmFeedback").classList.toggle("is-error", error); }
  function parameters(includePage = true) { const result = new URLSearchParams(filters); if (includePage) result.set("page", String(page)); return result; }
  const metricIcons = [
    '<rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V4h8v3M3 12h18M10 12v3h4v-3"/>',
    '<path d="M4 21V5h10v16M14 10h6v11M2 21h20M7 9h4M7 13h4M7 17h4M17 14h1M17 17h1"/>',
    '<path d="m12 3 10 5-10 5L2 8l10-5Zm-9 10 9 5 9-5M3 18l9 5 9-5"/>',
    '<path d="m6 3 6 8 6-8M5 11h14M5 16h14M12 11v10"/>'
  ];
  function statsCard(label, value, note, icon) { return `<article class="lm-stat"><span class="lm-stat-icon" data-tone="${icon}" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${metricIcons[icon]}</svg></span><div><span>${label}</span><strong>${value}</strong><small>${note}</small></div></article>`; }
  function bars(rows, sourceNames = {}) {
    if (!rows?.length) return '<p class="lm-muted">暂无足够样本</p>';
    const max = Math.max(...rows.map(row => row.count), 1);
    return rows.slice(0, 5).map(row => `<div class="lm-bar-row"><span title="${esc(row.name)}">${esc(sourceNames[row.name] || row.name)}</span><div class="lm-bar-track"><i style="width:${Math.max(2, row.count / max * 100)}%"></i></div><b>${number(row.count)}</b></div>`).join("");
  }
  function renderStats(data) {
    const monthly = data.salary.month;
    const daily = data.salary.day;
    const salary = monthly.count ? monthly : daily;
    const unit = monthly.count ? "月" : "天";
    el("lmStats").innerHTML = statsCard("岗位样本", number(data.total), "当前筛选 · 去重记录", 0) + statsCard("覆盖企业", number(data.companies), "按来源公司名称统计", 1) + statsCard("近 7 天发现", number(data.new_7d), "首次收录的岗位", 2) + statsCard(`薪资中位数 · 元/${unit}`, salary.median_midpoint ? number(salary.median_midpoint) : "—", `${number(salary.count)} 条同周期薪资样本`, 3);
    const timeline = [];
    for (let offset = 6; offset >= 0; offset--) {
      const day = new Date(Date.now() - offset * 86400000).toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
      timeline.push({ day, added: data.timeline.find(row => row.day === day)?.added || 0 });
    }
    const maximum = Math.max(...timeline.map(row => row.added), 1);
    const points = timeline.map((row, index) => [12 + index * 40, 88 - row.added / maximum * 66]);
    el("lmTrend").innerHTML = data.timeline.length ? `<div class="lm-chart-total"><strong>${number(timeline.reduce((sum, row) => sum + row.added, 0))}</strong><span>条首次收录</span></div><svg class="lm-line-chart" viewBox="0 0 264 108" role="img" aria-label="近七天每日首次发现岗位数量"><defs><linearGradient id="lmTrendFill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#2974ff" stop-opacity=".16"/><stop offset="1" stop-color="#2974ff" stop-opacity="0"/></linearGradient></defs><path d="M12 22H252M12 55H252M12 88H252" stroke="#eaf0f8" fill="none"/><path d="M12 88 ${points.map(point => `L${point.join(" ")}`).join(" ")} L252 88Z" fill="url(#lmTrendFill)"/><polyline points="${points.map(point => point.join(",")).join(" ")}" fill="none" stroke="#2974ff" stroke-width="2" stroke-linejoin="round"/>${points.map((point, index) => `<circle cx="${point[0]}" cy="${point[1]}" r="3" fill="white" stroke="#2974ff" stroke-width="1.5"><title>${timeline[index].day}：${number(timeline[index].added)} 条</title></circle>`).join("")}</svg><div class="lm-chart-dates"><span>${timeline[0].day.slice(5)}</span><span>${timeline[3].day.slice(5)}</span><span>${timeline[6].day.slice(5)}</span></div><details class="lm-trend-values"><summary>查看每日数量</summary><dl>${timeline.map(row => `<div><dt>${row.day.slice(5)}</dt><dd>${number(row.added)} 条</dd></div>`).join("")}</dl></details>` : '<p class="lm-muted">完成采集后显示每日首次发现的岗位数量。</p>';
    el("lmInsights").innerHTML = `<section class="lm-insight"><h4>岗位地点</h4>${bars(data.cities)}</section><section class="lm-insight"><h4>${data.skills?.length ? "JD 技能关键词" : "学历要求"}</h4>${bars(data.skills?.length ? data.skills : data.education)}</section>`;
  }
  function renderJobs(data) {
    pages = data.pages;
    el("lmResultCount").textContent = `${number(data.total)} 个样本`;
    el("lmResults").innerHTML = data.items.length ? data.items.map(row => {
      const company = String(row.company_name || "招聘企业");
      const mark = Array.from(company).slice(0, /^[a-zA-Z]/.test(company) ? 2 : 1).join("").toUpperCase();
      const tone = Array.from(company).reduce((sum, char) => sum + char.codePointAt(0), 0) % 5;
      const locationIcon = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M15.5 8.5c0 4-5.5 8-5.5 8s-5.5-4-5.5-8a5.5 5.5 0 0 1 11 0Z"/><circle cx="10" cy="8" r="1.8"/></svg>';
      return `<article class="lm-job"><span class="lm-company-mark" data-tone="${tone}" aria-hidden="true">${esc(mark)}</span><div class="lm-job-info"><div class="lm-job-title"><h5 title="${esc(row.job_title)}">${esc(row.job_title)}</h5>${row.job_type && row.job_type !== "unknown" ? `<span class="lm-type">${esc(types[row.job_type] || "")}</span>` : ""}</div><p class="lm-company-line"><span class="lm-company" title="${esc(company)}">${esc(company)}</span>${row.industry ? `<span class="lm-company-sector">· ${esc(row.industry)}</span>` : ""}</p><div class="lm-tags"><span class="lm-location" title="${esc(row.location || "地点未提供")}">${locationIcon}${esc(row.location || "地点未提供")}</span>${row.education ? `<span>${esc(row.education)}</span>` : ""}<span class="lm-source-badge" title="${esc(row.source_label)}">${esc(sourceNames[row.source] || row.source_label)}</span></div></div><div class="lm-job-pay"><p class="lm-salary${row.salary ? "" : " is-undisclosed"}">${esc(row.salary || "薪资未提供")}</p><p class="lm-job-collected">${row.stale ? "较久未更新 · " : ""}${time(row.last_seen)} 采集</p></div><button class="lm-job-action" type="button" data-lm-action="detail" data-id="${row.id}">查看详情 <span aria-hidden="true">›</span></button></article>`;
    }).join("") : empty("暂时没有匹配的岗位", "试试调整关键词或筛选条件，发现更多机会。");
    el("lmPagination").hidden = data.total === 0;
    el("lmPageInfo").textContent = `第 ${page} / ${pages} 页`;
    root.querySelector('[data-lm-action="previous"]').disabled = page <= 1;
    root.querySelector('[data-lm-action="next"]').disabled = page >= pages;
    el("lmExport").href = `${API}/export?${parameters(false)}`;
  }
  function renderStatus(data) {
    statusData = data;
    const settings = data.settings;
    const running = data.runs.find(run => run.status === "running");
    const next = settings.enabled ? `每 ${settings.interval_hours} 小时更新 · 下次计划 ${time(settings.next_run_at, true)}` : "自动采集已暂停";
    el("lmScheduleLine").textContent = running ? `${running.cancel_requested ? "正在停止采集" : "正在采集"} · ${running.message || "岗位将分批更新"}` : next;
    root.querySelectorAll(".lm-admin-only").forEach(item => { item.hidden = !data.can_manage; });
    const collect = root.querySelector('[data-lm-action="collect"]');
    const cancel = root.querySelector('[data-lm-action="cancel"]');
    collect.disabled = Boolean(running);
    cancel.disabled = !running || Boolean(running.cancel_requested);
    el("lmSourceStatus").innerHTML = Object.entries(data.sources).map(([key, label]) => {
      const run = data.runs.find(run => run.sources.some(source => source.source === key));
      const source = run?.sources.find(source => source.source === key);
      const state = source?.status || "queued";
      return `<article class="lm-source"><div><strong>${esc(label)}</strong><span class="lm-state is-${state}">${source ? states[state] || "待核对" : settings.sources.includes(key) ? "等待首次采集" : "未启用"}</span></div><p>${run ? time(run.started_at, true) : ""}${source?.message ? `${run ? " · " : ""}${esc(source.message)}` : key === "website" ? "通用官网采集可用性因站点而异。" : "公开来源，获取到的岗位按条目归档。"}</p>${source?.rejected ? `<p>${source.rejected} 条记录因缺少有效字段未入库。</p>` : ""}</article>`;
    }).join("");
    el("lmSourceSummary").textContent = `${settings.sources.length} 个来源已启用`;
    schedulePoll(Boolean(running));
  }
  function toggleSources(open, restoreFocus = false) {
    const drawer = el("lmSourceDrawer");
    const toggle = el("lmSourceToggle");
    if (open && !drawer.open) drawer.show();
    if (!open && drawer.open) drawer.close();
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "收起数据更新" : "打开数据更新");
    toggle.title = open ? "收起数据更新" : "数据更新";
    if (!open && restoreFocus) toggle.focus({ preventScroll: true });
  }
  function schedulePoll(running) {
    clearTimeout(timer);
    if (!active || document.hidden) return;
    timer = setTimeout(() => { if (active && !document.hidden) void load(true); }, running ? 5000 : 60000);
  }
  async function load(quiet = false) {
    if (!window.getCurrentUser?.()) return;
    const serial = ++generation;
    busy = true;
    root.setAttribute("aria-busy", "true");
    if (!quiet) feedback("正在读取最新岗位与采集状态…");
    const query = parameters();
    const results = await Promise.allSettled([
      window.requestJson(`${API}/jobs?${query}`), window.requestJson(`${API}/stats?${query}`), window.requestJson(`${API}/status`)
    ]);
    if (serial !== generation) return;
    const errors = [];
    results.forEach((result, index) => {
      if (result.status === "rejected") { errors.push(result.reason?.message || "部分数据读取失败，请重试。"); return; }
      if (index === 0) renderJobs(result.value);
      if (index === 1) renderStats(result.value.data);
      if (index === 2) renderStatus(result.value);
    });
    feedback(errors.length ? [...new Set(errors)].join(" ") : "", errors.length > 0);
    if (results[0].status === "rejected" && !el("lmResults").children.length) el("lmResults").innerHTML = empty("岗位暂时无法读取", "点击刷新岗位重试。");
    busy = false;
    root.setAttribute("aria-busy", "false");
    if (results[2].status === "rejected") schedulePoll(false);
  }
  async function detail(id) {
    toggleSources(false);
    const dialog = el("lmDetailDialog");
    el("lmDetailContent").innerHTML = '<h3 id="lmDetailTitle">正在读取岗位详情…</h3>';
    dialog.showModal();
    try {
      const response = await window.requestJson(`${API}/jobs/${encodeURIComponent(id)}`);
      const row = response.data;
      if (!dialog.open) return;
      el("lmDetailContent").innerHTML = `<p class="lm-eyebrow">${esc(row.source_label)}</p><h3 id="lmDetailTitle">${esc(row.job_title)}</h3><p class="lm-muted">${esc(row.company_name)}</p><p class="lm-salary">${esc(row.salary || "薪资未提供")}</p><div class="lm-tags">${[row.location, row.education, types[row.job_type], row.industry, row.company_nature, row.company_size].filter(Boolean).map(text => `<span>${esc(text)}</span>`).join("")}</div>${row.welfare ? `<h4>福利与待遇</h4><p class="lm-detail-description">${esc(row.welfare)}</p>` : ""}<h4>岗位描述与要求</h4><div class="lm-detail-description">${esc(row.job_desc || "来源暂未返回详细描述，请打开原站核对招聘要求。")}</div><div class="lm-detail-meta"><span>来源发布：${esc(row.publish_date || "未提供")}</span><span>首次发现：${time(row.first_seen, true)}</span><span>最近采集：${time(row.last_seen, true)}</span><span>内容变化：${time(row.changed_at, true)}</span></div><p class="lm-muted">来源分类可能根据标题推断；岗位是否仍开放、投递条件与薪资请以原站为准。</p><a class="lm-btn lm-btn-primary lm-detail-link" href="${esc(row.job_url)}" target="_blank" rel="noopener noreferrer">查看原站与投递入口 ↗</a>`;
    } catch (error) { el("lmDetailContent").textContent = error.message; }
  }
  function openSettings() {
    if (!statusData?.can_manage) return;
    toggleSources(false);
    const settings = statusData.settings;
    const input = (name, label, min, max) => `<label>${label}<input name="${name}" type="number" min="${min}" max="${max}" value="${settings[name]}" required></label>`;
    el("lmSettingsFields").innerHTML = `<label class="lm-setting-source"><span><input name="enabled" type="checkbox" ${settings.enabled ? "checked" : ""}>启用自动定时采集</span></label><fieldset><legend class="lm-muted">采集来源</legend><div class="lm-setting-source">${Object.entries(statusData.sources).map(([key, label]) => `<label><input type="checkbox" name="sources" value="${key}" ${settings.sources.includes(key) ? "checked" : ""}>${esc(label)}</label>`).join("")}</div></fieldset><div class="lm-settings-grid">${input("interval_hours", "更新间隔（小时）", 1, 168)}${input("max_pages", "每个来源 / 企业的最大页数", 1, 10)}${input("max_jobs", "每类来源最多岗位数", 20, 2000)}${input("timeout_seconds", "每类来源采集时限（秒）", 30, 1800)}<label>采集企业（可选，以逗号分隔）<input name="companies" list="lmCompanyOptions" maxlength="1500" value="${esc(settings.companies.join("，"))}" placeholder="留空采集来源内的企业"></label><label>地点（可选，以逗号分隔）<input name="locations" maxlength="800" value="${esc(settings.locations.join("，"))}" placeholder="例如：北京，上海"></label><label>行业（可选，以逗号分隔）<input name="industries" maxlength="800" value="${esc(settings.industries.join("，"))}" placeholder="例如：互联网/科技"></label></div><datalist id="lmCompanyOptions">${statusData.companies.map(company => `<option value="${esc(company.name)}">${esc(company.industry)}</option>`).join("")}</datalist><p class="lm-muted">企业 API 与国家平台优先；通用官网采集可能无法取得数据。不同来源支持的定向条件不同，国家平台和实习僧主要使用首个城市条件。保存后可点击“立即采集”验证来源。</p>`;
    el("lmSettingsFeedback").textContent = "";
    el("lmSettingsDialog").showModal();
  }
  el("lmSearchForm").addEventListener("submit", event => {
    event.preventDefault();
    [...filters.keys()].forEach(key => filters.delete(key));
    const values = new FormData(event.currentTarget);
    for (const [key, value] of values) { if (String(value).trim()) filters.set(key, String(value).trim()); }
    if ((filters.has("salary_min") || filters.has("salary_max")) && !filters.get("salary_unit")) return feedback("筛选薪资时，请先选择计薪周期。", true);
    page = 1;
    void load();
  });
  el("lmSearchForm").addEventListener("reset", () => { setTimeout(() => { [...filters.keys()].forEach(key => filters.delete(key)); filters.set("days", "30"); filters.set("sort", "recent"); page = 1; void load(); }, 0); });
  el("lmSettingsForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!statusData?.can_manage) return;
    const form = new FormData(event.currentTarget);
    const payload = { enabled: form.has("enabled"), sources: form.getAll("sources") };
    for (const key of ["interval_hours", "max_pages", "max_jobs", "timeout_seconds"]) payload[key] = Number(form.get(key));
    for (const key of ["companies", "locations", "industries"]) payload[key] = String(form.get(key) || "").split(/[,，\n]/).map(text => text.trim()).filter(Boolean);
    const submit = event.currentTarget.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      await window.requestJson(`${API}/settings`, { method: "PUT", body: payload });
      el("lmSettingsDialog").close();
      await load(true);
      feedback("采集计划已保存。");
    } catch (error) { el("lmSettingsFeedback").textContent = error.message; }
    finally { submit.disabled = false; }
  });
  document.addEventListener("click", async event => {
    const target = event.target.closest("[data-lm-action]");
    if (!target) return;
    const action = target.dataset.lmAction;
    if (action === "cities" || action === "archives") return document.querySelector(`.jobs-view-switch [data-jobs-view="${action === "cities" ? "cities" : "list"}"]`).click();
    if (action === "toggle-sources") return toggleSources(!el("lmSourceDrawer").open, el("lmSourceDrawer").open);
    if (action === "close-sources") return toggleSources(false, true);
    if (action === "close-detail") return el("lmDetailDialog").close();
    if (action === "close-settings") return el("lmSettingsDialog").close();
    if (action === "detail") return void detail(target.dataset.id);
    if (action === "settings") return openSettings();
    if (action === "refresh") return void load();
    if (action === "previous" && !busy && page > 1) { page--; return void load(); }
    if (action === "next" && !busy && page < pages) { page++; return void load(); }
    if (action === "collect" || action === "cancel") {
      if (!statusData?.can_manage) return;
      target.disabled = true;
      try {
        await window.requestJson(`${API}/collect`, { method: action === "collect" ? "POST" : "DELETE", body: {} });
        await load(true);
      } catch (error) { feedback(error.message, true); target.disabled = false; }
    }
  });
  window.addEventListener("jobs:view-changed", event => {
    active = event.detail.view === "live";
    if (active) void load();
    else { clearTimeout(timer); toggleSources(false); el("lmDetailDialog").close(); }
  });
  document.addEventListener("pointerdown", event => {
    if (el("lmSourceDrawer").open && !el("lmSourceDrawer").contains(event.target) && !el("lmSourceToggle").contains(event.target)) toggleSources(false);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && el("lmSourceDrawer").open) {
      event.preventDefault();
      toggleSources(false, true);
    }
  });
  el("lmSourceDrawer").addEventListener("close", () => {
    if (!el("lmSourceDrawer").open) toggleSources(false);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(timer); else if (active) void load(true); });
  window.JobMarket = { open() { active = true; return load(); }, pause() { active = false; clearTimeout(timer); toggleSources(false); el("lmDetailDialog").close(); el("lmSettingsDialog").close(); } };
})();
