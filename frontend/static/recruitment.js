(() => {
  "use strict";
  const API = "/api/job-market/collection";
  const byId = (id) => document.getElementById(id);
  const config = byId("recruitmentCollect");
  const filterForm = byId("recruitmentFilters");
  const sources = new Map(Array.from(filterForm.elements.source.options).map((option) => [option.value, option.text]));
  const captureDate = new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" });
  const start = byId("recruitmentStart");
  const statusNames = {
    queued: "等待中", running: "采集中", succeeded: "已采集", complete: "已完成",
    partial: "部分完成", empty: "无结果", interrupted: "已中断", blocked: "需要验证", unavailable: "暂不可用",
    opening: "打开浏览器", waiting_user: "等待登录或验证", login_required: "需要登录"
  };
  let page = 1;
  let filters = new URLSearchParams();
  let jobsSequence = 0;
  let runSequence = 0;
  let detailSequence = 0;
  let poll;
  let submitting = false;
  let active = false;

  async function api(path, body) {
    const options = body === undefined ? {} : { method: "POST", headers: await window.CareerAuth.headers() };
    if (body instanceof FormData) options.body = body;
    else if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(API + path, options);
    if (response.status === 401) throw new Error("登录已过期，请重新登录。");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "请求未完成，请稍后重试。");
    return payload;
  }

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  function notice(message, tone = "info") {
    const el = byId("recruitmentFeedback");
    el.textContent = message;
    el.dataset.tone = tone;
    el.hidden = !message;
  }

  function updateStart() {
    start.disabled = submitting || active;
    start.textContent = active ? "正在采集…" : "开始采集";
  }

  function displaySalary(salary) {
    return /[\p{Co}\uFFFD]/u.test(salary || "") ? "" : salary;
  }

  async function details(row) {
    const sequence = ++detailSequence;
    const dialog = byId("recruitmentDetail");
    const description = byId("recruitmentDescription");
    const detailStatus = byId("recruitmentDetailStatus");
    byId("recruitmentDetailTitle").textContent = row.title;
    byId("recruitmentDetailMeta").textContent = [sources.get(row.source), row.company, row.location, displaySalary(row.salary)].filter(Boolean).join(" · ");
    description.textContent = row.description || "可在原站查看详情。";
    byId("recruitmentOriginal").href = row.url;
    detailStatus.hidden = row.source !== "zhilian";
    dialog.showModal();
    if (row.source !== "zhilian") return;
    detailStatus.textContent = "正在读取智联职位描述…";
    try {
      const result = await api("/jobs/zhilian/detail", { url: row.url });
      if (sequence !== detailSequence || !dialog.open) return;
      description.textContent = result.description;
      detailStatus.hidden = true;
    } catch (error) {
      if (sequence !== detailSequence || !dialog.open) return;
      detailStatus.textContent = error.message;
    }
  }

  function resultRow(row) {
    const el = node("article", "", "recruitment-row");
    const header = node("div", "", "recruitment-row-header");
    const source = node("span", sources.get(row.source), "recruitment-badge recruitment-job-source");
    source.dataset.source = row.source;
    header.append(source);
    if (row.updated_at) {
      header.append(node("span", captureDate.format(new Date(row.updated_at * 1000)) + " 采集", "recruitment-row-date"));
    }
    const title = node("button", row.title, "recruitment-row-title");
    title.type = "button";
    title.addEventListener("click", () => details(row));
    const meta = [row.company, row.location].filter(Boolean).join(" · ");
    const footer = node("div", "", "recruitment-row-footer");
    const salary = displaySalary(row.salary);
    footer.append(node("strong", salary || "薪资未获取", salary ? "recruitment-salary" : "recruitment-salary is-missing"));
    const original = node("a", "原帖 ↗", "recruitment-original");
    original.href = row.url;
    original.target = "_blank";
    original.rel = "noopener noreferrer";
    original.setAttribute("aria-label", "查看原帖：" + row.title);
    footer.append(original);
    el.append(header, title, node("p", meta, "recruitment-row-meta"), footer);
    return el;
  }

  async function loadJobs() {
    const sequence = ++jobsSequence;
    const query = new URLSearchParams(filters);
    query.set("page", page);
    try {
      const data = await api("/jobs?" + query);
      if (sequence !== jobsSequence) return;
      const pages = Math.max(1, Math.ceil(data.total / data.page_size));
      if (page > pages) {
        page = pages;
        return loadJobs();
      }
      byId("recruitmentCount").textContent = `${data.total} 条结果`;
      byId("recruitmentRows").replaceChildren(...(data.items.length ? data.items.map(resultRow) : [
        node("p", filters.toString() ? "没有匹配的岗位，请调整筛选条件。" : "暂无结果。开始一次采集，或导入已有 CSV。", "recruitment-empty")
      ]));
      byId("recruitmentPaging").hidden = pages === 1;
      byId("recruitmentPrev").disabled = page === 1;
      byId("recruitmentNext").disabled = page === pages;
      byId("recruitmentPage").textContent = `${page} / ${pages}`;
      byId("recruitmentExport").href = API + "/export?" + filters;
    } catch (error) {
      if (sequence === jobsSequence) notice(error.message, "error");
    }
  }

  function runCard(run, first) {
    const card = node("details", "", "recruitment-run");
    card.open = first;
    const title = node("summary");
    title.append(node("strong", [run.keyword, run.city].filter(Boolean).join(" · ")),
      node("span", statusNames[run.status] || run.status, "recruitment-badge"));
    card.append(title, node("p", new Date(run.started_at * 1000).toLocaleString("zh-CN"), "recruitment-run-date"));
    for (const [source, item] of Object.entries(run.progress)) {
      const line = node("div", "", "recruitment-run-source");
      const link = node("a", "原站 ↗");
      link.href = item.search_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      line.append(node("strong", sources.get(source)), link);
      const interrupted = run.status === "interrupted" && ["queued", "running", "opening", "waiting_user"].includes(item.status);
      const message = node("p", interrupted ? "已中断" : item.message || statusNames[item.status]);
      message.dataset.status = item.status;
      line.append(message);
      card.append(line);
    }
    return card;
  }

  async function loadRuns() {
    clearTimeout(poll);
    const sequence = ++runSequence;
    try {
      const data = await api("/runs");
      if (sequence !== runSequence) return;
      const previouslyActive = active;
      active = data.items.some((run) => run.status === "running");
      updateStart();
      byId("recruitmentRuns").replaceChildren(...(data.items.length ? data.items.map((run, index) => runCard(run, index === 0)) : [
        node("p", "暂无采集记录。", "recruitment-empty")
      ]));
      if (active || previouslyActive) void loadJobs();
      if (active) poll = setTimeout(loadRuns, 3000);
    } catch (error) {
      if (sequence !== runSequence) return;
      notice(error.message, "error");
      if (active) poll = setTimeout(loadRuns, 5000);
    }
  }

  config.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (start.disabled) return;
    const data = new FormData(config);
    const platforms = data.getAll("source");
    if (!platforms.length) return notice("请至少选择一个采集平台。", "error");
    submitting = true;
    updateStart();
    try {
      const chromeSources = config.elements.bossLocal?.dataset.chromeSources;
      await api("/runs", {
        keyword: data.get("keyword"), city: data.get("city"), limit: Number(data.get("limit")), sources: platforms,
        boss_local: !chromeSources && platforms.includes("boss") && data.has("bossLocal"),
        chrome_local: Boolean(data.has("bossLocal") && chromeSources?.split(",").some((source) => platforms.includes(source)))
      });
      active = true;
      notice("已启动采集。各平台的结果会陆续显示。");
    } catch (error) {
      notice(error.message, "error");
    } finally {
      submitting = false;
      updateStart();
      void loadRuns();
    }
  });

  filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    filters = new URLSearchParams(Array.from(new FormData(filterForm)).filter(([, value]) => value.trim()));
    page = 1;
    void loadJobs();
  });
  byId("recruitmentPrev").onclick = () => { page -= 1; void loadJobs(); };
  byId("recruitmentNext").onclick = () => { page += 1; void loadJobs(); };
  byId("recruitmentRefresh").onclick = () => { void loadRuns(); void loadJobs(); };
  const zhilianLogin = byId("recruitmentZhilianLogin");
  if (zhilianLogin) {
    const status = byId("recruitmentZhilianStatus");
    const check = byId("recruitmentCheckZhilian");
    const zhilian = config.querySelector('input[name="source"][value="zhilian"]');
    const syncVisibility = () => { zhilianLogin.hidden = !zhilian.checked; };
    zhilian.addEventListener("change", syncVisibility);
    syncVisibility();
    check.addEventListener("click", async () => {
      check.disabled = true;
      status.dataset.state = "checking";
      status.textContent = "正在检查当前 Chrome 的智联登录状态…";
      try {
        const result = await api("/session/zhilian", {});
        status.dataset.state = result.state;
        status.textContent = result.message;
      } catch (error) {
        status.dataset.state = "unavailable";
        status.textContent = error.message;
      } finally {
        check.disabled = false;
      }
    });
  }
  const upload = byId("recruitmentFile");
  const importButton = byId("recruitmentImport");
  importButton.onclick = () => upload.click();
  upload.onchange = async () => {
    const file = upload.files[0];
    if (!file) return;
    importButton.disabled = true;
    const data = new FormData();
    data.append("file", file);
    try {
      const result = await api("/import", data);
      notice(`已保存 ${result.count} 条记录。`);
      page = 1;
      void loadJobs();
    } catch (error) {
      notice(error.message, "error");
    } finally {
      upload.value = "";
      importButton.disabled = false;
    }
  };
  const importPage = byId("recruitmentImportPage");
  const htmlForm = byId("recruitmentHtmlForm");
  const htmlFeedback = byId("recruitmentHtmlFeedback");
  byId("recruitmentSavedPage").onclick = () => {
    htmlFeedback.textContent = "";
    importPage.showModal();
  };
  htmlForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = htmlForm.querySelector("button");
    button.disabled = true;
    htmlFeedback.textContent = "正在读取页面…";
    try {
      const result = await api("/import-html", new FormData(htmlForm));
      htmlForm.reset();
      importPage.close();
      notice(`已保存 ${result.count} 条记录。`);
      page = 1;
      void loadJobs();
    } catch (error) {
      htmlFeedback.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });
  void loadRuns();
  void loadJobs();
})();
