(() => {
  "use strict";
  // Old root bookmarks retain their hash across the redirect to the new home page.
  if (["#dashboard", "#profile", "#report"].includes(window.location.hash)) {
    window.location.replace("/main.html" + window.location.hash);
    return;
  }
  const API = "/api/job-market/collection";
  const byId = (id) => document.getElementById(id);
  const config = byId("recruitmentCollect");
  const collectDialog = byId("recruitmentCollectDialog");
  const collectFeedback = byId("recruitmentCollectFeedback");
  const profileSelect = byId("recruitmentProfile");
  const rulesProfileSelect = byId("recruitmentRulesProfile");
  const profileNames = new Map(Array.from(profileSelect.options, (option) => [option.value, option.text]));
  const filterForm = byId("recruitmentFilters");
  const views = byId("recruitmentViews");
  const sources = new Map(Array.from(filterForm.elements.source.options).map((option) => [option.value, option.text]));
  const captureDate = new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" });
  const start = byId("recruitmentStart");
  const platformCards = document.querySelectorAll("[data-recruitment-platform]");
  const statusNames = {
    queued: "等待中", running: "采集中", succeeded: "已采集", complete: "已完成",
    partial: "部分完成", empty: "无结果", interrupted: "已中断", blocked: "需要验证", unavailable: "暂不可用",
    opening: "打开浏览器", waiting_user: "等待登录或验证", login_required: "需要登录", login_timeout: "登录超时",
    city_unsupported: "城市暂不支持"
  };
  const cleaningNames = { unreviewed: "未清洗", passed: "通过", rejected: "淘汰", review: "待核对", released: "已放行" };
  let page = 1;
  let view = "priority";
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

  function updateCollectionSummary() {
    const summary = [profileNames.get(profileSelect.value), byId("recruitmentCityValue").textContent,
      config.elements.keyword.value.trim()];
    byId("recruitmentCollectSummary").textContent = summary.filter(Boolean).join(" · ");
  }

  function showCollectFeedback(message) {
    collectFeedback.textContent = message;
    collectFeedback.hidden = !message;
  }

  function displaySalary(salary) {
    return /[\p{Co}\uFFFD]/u.test(salary || "") ? "" : salary;
  }

  async function details(row) {
    const sequence = ++detailSequence;
    const dialog = byId("recruitmentDetail");
    const description = byId("recruitmentDescription");
    const detailStatus = byId("recruitmentDetailStatus");
    const decision = byId("recruitmentDetailDecision");
    const rewrite = byId("recruitmentResumeRewrite");
    byId("recruitmentDetailTitle").textContent = row.title;
    byId("recruitmentDetailMeta").textContent = [sources.get(row.source), row.company, row.location, displaySalary(row.salary)].filter(Boolean).join(" · ");
    setupProfileMove(row, sequence);
    description.textContent = "";
    decision.hidden = true;
    byId("recruitmentOriginal").href = row.url;
    rewrite.disabled = true;
    rewrite.onclick = () => {
      const text = description.textContent;
      const job = { title: row.title, description: text === "可在原站查看详情。" ? "" : text, source: row.source, url: row.url };
      try { sessionStorage.setItem("career:resume-rewrite-job", JSON.stringify(job)); } catch (_) {}
      window.location.assign("/user-center/resumes?rewrite=1");
    };
    setupJobAi(row, sequence);
    detailStatus.hidden = false;
    detailStatus.textContent = "正在读取岗位详情…";
    dialog.showModal();
    try {
      const result = await api("/jobs/detail", { source: row.source, url: row.url });
      if (sequence !== detailSequence || !dialog.open) return;
      description.textContent = result.description || "可在原站查看详情。";
      if (result.cleaning_reason) {
        decision.textContent = (result.cleaning_status === "released" ? "原淘汰原因：" : "清洗依据：") + result.cleaning_reason;
        decision.hidden = false;
      }
      if (row.source !== "zhilian") {
        detailStatus.hidden = true;
        return;
      }
      detailStatus.textContent = "正在读取智联职位描述…";
      const full = await api("/jobs/zhilian/detail", { url: row.url });
      if (sequence !== detailSequence || !dialog.open) return;
      description.textContent = full.description || description.textContent;
      detailStatus.hidden = true;
    } catch (error) {
      if (sequence !== detailSequence || !dialog.open) return;
      detailStatus.textContent = error.message;
    } finally {
      if (sequence === detailSequence && dialog.open) rewrite.disabled = !description.textContent;
    }
  }

  function setupProfileMove(row, sequence) {
    let current = row.profile || "general";
    const select = byId("recruitmentDetailProfile");
    const button = byId("recruitmentMoveProfile");
    const feedback = byId("recruitmentMoveFeedback");
    select.value = current;
    select.disabled = false;
    button.disabled = true;
    feedback.hidden = true;
    select.onchange = () => { button.disabled = select.value === current; };
    button.onclick = async () => {
      const profile = select.value;
      select.disabled = true;
      button.disabled = true;
      feedback.hidden = true;
      try {
        await api("/jobs/profile", { source: row.source, url: row.url, profile });
        current = profile;
        if (sequence === detailSequence) feedback.textContent = "已归入" + profileNames.get(profile);
        void loadJobs();
      } catch (error) {
        if (sequence === detailSequence) feedback.textContent = error.message;
      } finally {
        if (sequence === detailSequence) {
          select.disabled = false;
          button.disabled = select.value === current;
          feedback.hidden = false;
        }
      }
    };
  }

  function resultRow(row) {
    const el = node("article", "", "recruitment-row");
    const header = node("div", "", "recruitment-row-header");
    const source = node("span", sources.get(row.source), "recruitment-badge recruitment-job-source");
    source.dataset.source = row.source;
    header.append(source);
    if (row.profile) header.append(node("span", profileNames.get(row.profile), "recruitment-badge"));
    if (row.ai_score != null || row.ai_match_status === "review") {
      header.append(node("span", row.ai_score == null ? "AI · 待补资料" : `AI · ${row.ai_score} 分`, "recruitment-badge"));
    }
    const title = node("button", row.title, "recruitment-row-title");
    title.type = "button";
    title.addEventListener("click", () => details(row));
    const meta = [row.company, row.location].filter(Boolean).join(" · ");
    const content = node("div", "", "recruitment-row-content");
    const footer = node("div", "", "recruitment-row-footer");
    const salary = displaySalary(row.salary);
    footer.append(node("strong", salary || "薪资未获取", salary ? "recruitment-salary" : "recruitment-salary is-missing"));
    content.append(header, title);
    if (meta) content.append(node("p", meta, "recruitment-row-meta"));
    if (row.updated_at) footer.append(node("span", captureDate.format(new Date(row.updated_at * 1000)) + " 采集", "recruitment-row-date"));
    if (cleaningNames[row.cleaning_status]) {
      const decision = node("div", "", "recruitment-cleaning-decision");
      decision.dataset.cleanStatus = row.cleaning_status;
      decision.append(node("span", cleaningNames[row.cleaning_status], "recruitment-badge recruitment-cleaning-badge"));
      if (row.cleaning_status === "rejected") {
        const release = node("button", "手动放行");
        release.type = "button";
        release.addEventListener("click", async () => {
          release.disabled = true;
          try {
            await api("/cleaning/release", { source: row.source, url: row.url, profile: row.profile || "general" });
            notice("已放行：" + row.title);
            await loadJobs();
          } catch (error) {
            notice(error.message, "error");
          } finally {
            release.disabled = false;
          }
        });
        decision.append(release);
      }
      footer.append(decision);
    }
    el.append(content, footer);
    return el;
  }

  async function loadJobs() {
    const sequence = ++jobsSequence;
    const query = new URLSearchParams(filters);
    if (view !== "all") query.set("clean_status", view === "priority" ? "passed" : view);
    if (!query.has("sort") && ["priority", "scored"].includes(view)) query.set("sort", "match");
    const exportQuery = query.toString();
    query.set("page", page);
    query.set("compact", "1");
    query.set("count_profile", profileSelect.value);
    try {
      const data = await api("/jobs?" + query);
      if (sequence !== jobsSequence) return;
      if (data.cleaning_counts) showCleaningCounts(data.cleaning_counts);
      for (const button of views.querySelectorAll("[data-view]")) {
        const key = button.dataset.view === "priority" ? "passed" : button.dataset.view;
        button.querySelector("[data-view-count]").textContent = data.view_counts?.[key] ?? "";
      }
      const pages = Math.max(1, Math.ceil(data.total / data.page_size));
      if (page > pages) {
        page = pages;
        return loadJobs();
      }
      byId("recruitmentCount").textContent = `${data.total} 条结果`;
      byId("recruitmentRows").replaceChildren(...(data.items.length ? data.items.map(resultRow) : [emptyView(data.view_counts)]));
      byId("recruitmentPaging").hidden = pages === 1;
      byId("recruitmentPrev").disabled = page === 1;
      byId("recruitmentNext").disabled = page === pages;
      byId("recruitmentPage").textContent = `${page} / ${pages}`;
      byId("recruitmentExport").href = API + "/export?" + exportQuery;
    } catch (error) {
      if (sequence === jobsSequence) notice(error.message, "error");
    }
  }

  function selectView(next) {
    view = next;
    page = 1;
    for (const button of views.querySelectorAll("[data-view]")) {
      button.setAttribute("aria-pressed", String(button.dataset.view === view));
    }
    void loadJobs();
  }

  function emptyView(counts) {
    const empty = node("div", "", "recruitment-empty recruitment-view-empty");
    if (view === "priority" && counts?.all > 0) {
      empty.append(node("strong", "暂时没有通过清洗的岗位"));
      const pending = counts.unreviewed > 0;
      const button = node("button", pending ? "查看待清洗岗位" : "查看全部岗位");
      button.type = "button";
      button.onclick = () => selectView(pending ? "unreviewed" : "all");
      empty.append(button);
    } else {
      empty.append(node("strong", filters.size ? "当前筛选没有结果" : "当前视图暂无岗位"));
    }
    return empty;
  }

  function platformStatus(run, item) {
    if (run.status === "interrupted" && ["queued", "running", "opening", "waiting_user"].includes(item.status)) {
      return "interrupted";
    }
    return item.status;
  }

  function loginLink(status, item) {
    return ["waiting_user", "login_required", "login_timeout"].includes(status) && item.login_url;
  }

  function updateOverview(run) {
    byId("recruitmentLatest").textContent = run
      ? ["最近一次", run.keyword, run.city, statusNames[run.status] || run.status].filter(Boolean).join(" · ")
      : "暂无采集记录";
    for (const card of platformCards) {
      const item = run?.progress[card.dataset.recruitmentPlatform];
      const status = item ? platformStatus(run, item) : "idle";
      const badge = card.querySelector(".recruitment-run-state");
      badge.textContent = statusNames[status] || (item ? status : run ? "未参与" : "未采集");
      badge.dataset.status = status;
      card.querySelector(".recruitment-platform-count").textContent = Number.isInteger(item?.count) ? `${item.count} 条` : "—";

      const login = card.querySelector(".recruitment-platform-login");
      const url = item && loginLink(status, item);
      login.hidden = !url;
      if (url) login.href = url;
      else login.removeAttribute("href");

      const message = card.querySelector(".recruitment-platform-message");
      message.textContent = status === "interrupted" ? "" : item?.message || "";
      message.hidden = !message.textContent || status === "succeeded";
    }
    const needsLogin = run?.status === "running" && Object.values(run.progress).some(item => item.status === "waiting_user");
    const overview = byId("recruitmentPlatformOverview");
    if (needsLogin && overview.dataset.loginRun !== String(run.id)) {
      overview.open = true;
      overview.dataset.loginRun = run.id;
    }
  }

  function runCard(run, open) {
    const card = node("details", "", "recruitment-run");
    card.open = open;
    card.dataset.runId = run.id;
    const title = node("summary");
    const badge = node("span", statusNames[run.status] || run.status, "recruitment-badge recruitment-run-state");
    badge.dataset.status = run.status;
    title.append(node("strong", [run.keyword, run.city, run.profile !== "general" && profileNames.get(run.profile)].filter(Boolean).join(" · ")),
      badge);
    card.append(title, node("p", new Date(run.started_at * 1000).toLocaleString("zh-CN"), "recruitment-run-date"));
    for (const [source, item] of Object.entries(run.progress)) {
      const line = node("div", "", "recruitment-run-source");
      const status = platformStatus(run, item);
      const url = loginLink(status, item);
      line.append(node("strong", sources.get(source)));
      if (url || item.search_url) {
        const link = node("a", url ? "去登录 ↗" : "原站 ↗");
        link.href = url || item.search_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        line.append(link);
      }
      const message = node("p", status === "interrupted" ? statusNames[status] : item.message || statusNames[status]);
      message.dataset.status = status;
      line.append(message);
      if (item.cleaning) line.append(node("p", "规则清洗 · " + cleaningSummary(item.cleaning)));
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
      updateOverview(data.items[0]);
      const history = byId("recruitmentRuns");
      const expanded = new Map(Array.from(history.querySelectorAll("[data-run-id]"), (card) => [card.dataset.runId, card.open]));
      history.replaceChildren(...(data.items.length ? data.items.map((run, index) => runCard(run, expanded.get(String(run.id)) ?? index === 0)) : [
        node("p", "暂无采集记录。", "recruitment-empty")
      ]));
      if (active || previouslyActive) void loadJobs();
      if (active) poll = setTimeout(loadRuns, 3000);
    } catch (error) {
      if (sequence !== runSequence) return;
      byId("recruitmentLatest").textContent = "采集概况读取失败";
      notice(error.message, "error");
      if (active) poll = setTimeout(loadRuns, 5000);
    }
  }

  const cityPicker = byId("recruitmentCityPicker");
  const cityToggle = byId("recruitmentCityToggle");
  const cityMenu = byId("recruitmentCityMenu");
  const citySearch = byId("recruitmentCitySearch");
  const citySections = [...cityMenu.querySelectorAll("[data-city-section]")];
  const cityIndexes = [...cityMenu.querySelectorAll("[data-city-index]")];
  let cityIndex = "hot";
  let unsupportedPlatforms = {};

  function showCities() {
    const term = citySearch.value.trim().replace(/(.+)市$/, "$1");
    let firstMatch;
    for (const section of citySections) {
      const group = section.dataset.citySection;
      const matchingGroup = term ? group !== "hot" : group === "scope" || group === cityIndex ||
        (cityIndex === "all" && group !== "hot");
      let hasVisibleCity = false;
      for (const option of section.querySelectorAll("[data-city]")) {
        option.hidden = Boolean(term && !option.textContent.includes(term));
        if (matchingGroup && !option.hidden) {
          hasVisibleCity = true;
          firstMatch ||= option;
        }
      }
      section.hidden = !hasVisibleCity;
    }
    for (const index of cityIndexes) index.setAttribute("aria-pressed", index.dataset.cityIndex === cityIndex);
    byId("recruitmentCityEmpty").hidden = Boolean(firstMatch);
    return firstMatch;
  }

  function closeCities(restoreFocus = false) {
    cityMenu.hidden = true;
    cityToggle.setAttribute("aria-expanded", "false");
    if (restoreFocus) cityToggle.focus();
  }

  function showCityCoverage() {
    const coverage = byId("recruitmentCityCoverage");
    const skipped = new FormData(config).getAll("source").filter((source) => source in unsupportedPlatforms);
    coverage.hidden = !skipped.length;
    coverage.textContent = skipped.length
      ? `将跳过 ${skipped.map((source) => unsupportedPlatforms[source]).join("、")}，暂无「${config.elements.city.value}」的城市筛选编码。`
      : "";
  }

  function selectCity(option) {
    config.elements.city.value = option.dataset.city;
    byId("recruitmentCityValue").textContent = option.textContent;
    unsupportedPlatforms = JSON.parse(option.dataset.unsupported);
    for (const button of cityMenu.querySelectorAll("[data-city]")) {
      button.setAttribute("aria-pressed", button.dataset.city === option.dataset.city);
    }
    showCityCoverage();
    updateCollectionSummary();
    closeCities(true);
  }

  cityToggle.onclick = () => {
    if (!cityMenu.hidden) return closeCities();
    citySearch.value = "";
    showCities();
    cityMenu.hidden = false;
    cityToggle.setAttribute("aria-expanded", "true");
    citySearch.focus();
  };
  citySearch.addEventListener("input", showCities);
  citySearch.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.isComposing) return;
    event.preventDefault();
    const match = citySearch.value.trim() && showCities();
    if (match) selectCity(match);
  });
  cityMenu.addEventListener("click", (event) => {
    const option = event.target.closest("[data-city]");
    if (option) return selectCity(option);
    const index = event.target.closest("[data-city-index]");
    if (index) {
      cityIndex = index.dataset.cityIndex;
      citySearch.value = "";
      showCities();
    }
  });
  cityPicker.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !cityMenu.hidden) {
      event.preventDefault();
      closeCities(true);
    }
  });
  document.addEventListener("click", (event) => {
    if (!cityMenu.hidden && !cityPicker.contains(event.target)) closeCities();
  });
  config.addEventListener("change", (event) => {
    if (event.target.name === "source") showCityCoverage();
  });
  config.elements.keyword.addEventListener("input", updateCollectionSummary);
  byId("recruitmentCollectOpen").onclick = () => {
    showCollectFeedback("");
    collectDialog.showModal();
  };
  collectDialog.addEventListener("close", () => closeCities());
  for (const drawer of document.querySelectorAll(".recruitment-drawer")) {
    drawer.addEventListener("click", (event) => {
      if (event.target === drawer && event.clientX < drawer.getBoundingClientRect().left) drawer.close();
    });
  }

  config.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (start.disabled) return;
    const data = new FormData(config);
    const platforms = data.getAll("source");
    if (!platforms.length) return showCollectFeedback("请至少选择一个采集平台。");
    submitting = true;
    showCollectFeedback("");
    updateStart();
    try {
      const chromeSources = config.elements.bossLocal?.dataset.chromeSources;
      await api("/runs", {
        keyword: data.get("keyword"), city: data.get("city"), limit: Number(data.get("limit")), sources: platforms,
        profile: profileSelect.value,
        boss_local: !chromeSources && platforms.includes("boss") && data.has("bossLocal"),
        chrome_local: Boolean(data.has("bossLocal") && chromeSources?.split(",").some((source) => platforms.includes(source)))
      });
      active = true;
      collectDialog.close();
      notice("已启动采集。各平台的结果会陆续显示。");
    } catch (error) {
      if (collectDialog.open) showCollectFeedback(error.message);
      else notice(error.message, "error");
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
  views.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (button) selectView(button.dataset.view);
  });
  byId("recruitmentPrev").onclick = () => { page -= 1; void loadJobs(); };
  byId("recruitmentNext").onclick = () => { page += 1; void loadJobs(); };
  byId("recruitmentRefresh").onclick = () => { void loadRuns(); void loadJobs(); };
  const cleaningDialog = byId("recruitmentCleaningDialog");
  const cleaningForm = byId("recruitmentCleaningForm");
  const cleaningFields = cleaningForm.querySelector("fieldset");
  const cleaningFeedback = byId("recruitmentCleaningFeedback");
  const cleaningPreview = byId("recruitmentCleaningPreview");
  const applyRules = byId("recruitmentCleaningApply");
  let previewToken = "";
  let loadedProfile = "";
  let ruleLoadSequence = 0;
  let rulesBusy = false;

  function showCleaningCounts(counts) {
    for (const card of byId("recruitmentCleaningCounts").children) {
      card.querySelector("b").textContent = counts[card.dataset.cleanStatus];
    }
  }

  function cleaningSummary(counts) {
    return ["passed", "rejected", "review"].map((status) => `${cleaningNames[status]} ${counts[status]}`).join(" · ");
  }

  function showRules(rules) {
    for (const name of ["cities", "title_exclusions", "company_exclusions"]) {
      cleaningForm.elements[name].value = rules[name].join("、");
    }
    for (const name of ["min_salary_k", "max_salary_k", "min_daily_salary", "max_daily_salary"]) {
      cleaningForm.elements[name].value = rules[name] ?? "";
    }
    for (const name of ["semantic_required", "semantic_excluded"]) {
      cleaningForm.elements[name].value = (rules[name] || []).join("\n");
    }
    cleaningForm.elements.auto.checked = rules.auto;
    const name = profileNames.get(profileSelect.value);
    byId("recruitmentCleaningMode").textContent = `${name} · ${rules.auto ? "自动清洗已开启" : "手动清洗"}`;
  }

  function readRules() {
    const form = new FormData(cleaningForm);
    const terms = (name) => [...new Set(form.get(name).split(/[,，、\n]+/).map((term) => term.trim()).filter(Boolean))];
    const salary = (name) => form.get(name) ? Number(form.get(name)) : null;
    const semantic = (name) => form.get(name).split("\n").map((rule) => rule.trim()).filter(Boolean);
    return {
      cities: terms("cities"), title_exclusions: terms("title_exclusions"), company_exclusions: terms("company_exclusions"),
      min_salary_k: salary("min_salary_k"), max_salary_k: salary("max_salary_k"),
      semantic_required: semantic("semantic_required"), semantic_excluded: semantic("semantic_excluded"),
      min_daily_salary: salary("min_daily_salary"), max_daily_salary: salary("max_daily_salary"), auto: form.has("auto")
    };
  }

  function resetPreview() {
    previewToken = "";
    applyRules.disabled = true;
    cleaningPreview.hidden = true;
    cleaningPreview.replaceChildren();
  }

  function showPreview(result) {
    previewToken = result.token;
    applyRules.disabled = false;
    for (const [status, samples] of Object.entries(result.samples)) {
      const group = node("li", "", "recruitment-rule-preview-group");
      group.dataset.cleanStatus = status;
      group.append(node("strong", `${cleaningNames[status]} ${result.counts[status]} 条`));
      for (const sample of samples) {
        group.append(node("p", [sample.title, sources.get(sample.source), sample.reason].filter(Boolean).join(" · ")));
      }
      cleaningPreview.append(group);
    }
    cleaningPreview.hidden = false;
  }

  async function loadRules() {
    const profile = profileSelect.value;
    if (loadedProfile === profile || rulesBusy) return;
    const sequence = ++ruleLoadSequence;
    loadedProfile = "";
    resetPreview();
    cleaningFields.disabled = true;
    const profileName = profileNames.get(profile);
    byId("recruitmentCleaningMode").textContent = profileName;
    const dailyRules = byId("recruitmentDailyRules");
    dailyRules.hidden = profile !== "internship";
    for (const input of dailyRules.querySelectorAll("input")) input.disabled = dailyRules.hidden;
    cleaningFeedback.textContent = "正在读取规则…";
    try {
      const data = await api("/cleaning?profile=" + profile);
      if (sequence !== ruleLoadSequence) return;
      showRules(data.rules);
      loadedProfile = profile;
      cleaningFeedback.textContent = "";
    } catch (error) {
      if (sequence === ruleLoadSequence) cleaningFeedback.textContent = error.message;
    } finally {
      if (sequence === ruleLoadSequence) cleaningFields.disabled = loadedProfile !== profile;
    }
  }

  async function runRuleAction(action) {
    if (rulesBusy || loadedProfile !== profileSelect.value || !cleaningForm.reportValidity() || (action === "apply" && !previewToken)) return;
    const payload = { profile: loadedProfile, rules: readRules(), token: previewToken };
    resetPreview();
    rulesBusy = true;
    cleaningFields.disabled = true;
    profileSelect.disabled = true;
    rulesProfileSelect.disabled = true;
    cleaningFeedback.textContent = "正在处理…";
    try {
      const result = await api("/cleaning/" + action, payload);
      if (action === "preview") {
        showPreview(result);
        cleaningFeedback.textContent = `预览完成，确认后应用到「${profileNames.get(payload.profile)}」岗位。`;
      } else {
        showRules(result.rules);
        showCleaningCounts(result.counts);
        cleaningFeedback.textContent = action === "save" ? "规则已保存。" : "已应用清洗规则。";
        if (action === "apply") void loadJobs();
      }
    } catch (error) {
      cleaningFeedback.textContent = error.message;
    } finally {
      cleaningFields.disabled = false;
      profileSelect.disabled = false;
      rulesProfileSelect.disabled = false;
      rulesBusy = false;
    }
  }

  byId("recruitmentCleaningOpen").onclick = () => {
    rulesProfileSelect.value = profileSelect.value;
    cleaningDialog.showModal();
    void loadRules();
  };
  cleaningForm.addEventListener("input", () => {
    resetPreview();
    cleaningFeedback.textContent = "";
  });
  cleaningForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void runRuleAction("preview");
  });
  byId("recruitmentCleaningSave").onclick = () => { void runRuleAction("save"); };
  applyRules.onclick = () => { void runRuleAction("apply"); };
  function selectProfile(profile) {
    profileSelect.value = profile;
    rulesProfileSelect.value = profile;
    updateCollectionSummary();
    void loadRules();
    void loadJobs();
  }
  profileSelect.addEventListener("change", () => selectProfile(profileSelect.value));
  rulesProfileSelect.addEventListener("change", () => selectProfile(rulesProfileSelect.value));
  void loadRules();

  const aiDialog = byId("recruitmentAiDialog");
  const aiProfile = byId("recruitmentAiProfile");
  const aiSettings = byId("recruitmentAiSettings");
  const aiRun = byId("recruitmentAiRun");
  const aiCandidates = byId("recruitmentAiCandidates");
  const aiSearch = byId("recruitmentAiSearch");
  const aiFeedback = byId("recruitmentAiFeedback");
  const aiBatchResults = byId("recruitmentAiBatchResults");
  const weights = [...aiSettings.querySelectorAll("[data-dimension]")];
  let aiKind = "match";
  let aiSequence = 0;
  let aiSettingsSequence = 0;
  let aiSettingsReady = false;
  let aiRunning = false;
  let aiSearchTimer;

  function showAiSettings(data) {
    aiSettings.elements.resume.value = data.settings.resume;
    aiSettings.elements.preferences.value = data.settings.preferences;
    for (const weight of weights) weight.value = data.settings.weights[weight.dataset.dimension] ?? 0;
    byId("recruitmentAiReadiness").textContent = !data.configured ? "请先在系统配置中设置对话模型。"
      : !data.resume_available ? "请填写基准简历，或先上传并解析账号简历。" : "模型与基准简历已就绪。";
    aiSettingsReady = data.configured && data.resume_available;
  }

  async function loadAiSettings() {
    const sequence = ++aiSettingsSequence;
    const profile = aiProfile.value;
    aiSettingsReady = false;
    aiSettings.querySelector("button").disabled = true;
    for (const field of aiSettings.querySelectorAll("input, textarea")) field.disabled = true;
    try {
      const data = await api("/ai/settings?profile=" + profile);
      if (sequence !== aiSettingsSequence) return;
      showAiSettings(data);
      aiSettings.querySelector("button").disabled = false;
      for (const field of aiSettings.querySelectorAll("input, textarea")) field.disabled = false;
    } catch (error) {
      if (sequence === aiSettingsSequence) byId("recruitmentAiReadiness").textContent = error.message;
    } finally {
      updateAiRun();
    }
  }

  function updateAiRun() {
    const count = aiCandidates.querySelectorAll("input:checked").length;
    aiRun.disabled = aiRunning || !count || count > 10 || (aiKind === "match" && !aiSettingsReady);
    if (count > 10) aiFeedback.textContent = "每次最多处理 10 条岗位。";
    else if (aiFeedback.textContent === "每次最多处理 10 条岗位。") aiFeedback.textContent = "";
  }

  async function loadAiCandidates() {
    const sequence = ++aiSequence;
    aiCandidates.replaceChildren();
    updateAiRun();
    try {
      const query = new URLSearchParams({ profile: aiProfile.value, q: aiSearch.value.trim() });
      const data = await api(`/ai/candidates/${aiKind}?${query}`);
      if (sequence !== aiSequence) return;
      for (const item of data.items) {
        const label = node("label", "", "recruitment-ai-candidate");
        const input = node("input");
        input.type = "checkbox";
        input.dataset.source = item.source;
        input.value = item.url;
        input.disabled = aiRunning;
        label.append(input, node("span", [item.title, item.company, item.score == null ? "" : item.score + " 分"]
          .filter(Boolean).join(" · ")));
        aiCandidates.append(label);
      }
      if (!data.items.length) aiCandidates.append(node("p", "暂无已通过规则清洗的岗位。", "recruitment-rule-feedback"));
    } catch (error) {
      if (sequence === aiSequence) aiFeedback.textContent = error.message;
    }
  }

  function openAi(kind) {
    if (!aiRunning) {
      aiKind = kind;
      aiProfile.value = profileSelect.value;
      aiSearch.value = "";
      aiFeedback.textContent = "";
      aiBatchResults.replaceChildren();
      aiSettings.hidden = kind !== "match";
      byId("recruitmentAiDialogTitle").textContent = kind === "match" ? "AI 初评" : "AI 语义清洗";
      aiRun.textContent = kind === "match" ? "评估所选岗位" : "清洗所选岗位";
      if (kind === "match") void loadAiSettings();
      else aiSettingsSequence += 1;
      void loadAiCandidates();
    }
    if (!aiDialog.open) aiDialog.showModal();
  }

  byId("recruitmentAiOpen").onclick = () => openAi("match");
  byId("recruitmentSemanticOpen").onclick = () => {
    if (rulesBusy) return;
    cleaningDialog.close();
    openAi("semantic");
  };
  aiProfile.addEventListener("change", () => {
    aiFeedback.textContent = "";
    aiBatchResults.replaceChildren();
    if (aiKind === "match") void loadAiSettings();
    void loadAiCandidates();
  });
  aiSearch.addEventListener("input", () => {
    clearTimeout(aiSearchTimer);
    aiSearchTimer = setTimeout(() => { if (!aiRunning && aiDialog.open) void loadAiCandidates(); }, 250);
  });
  aiCandidates.addEventListener("change", updateAiRun);
  aiSettings.addEventListener("submit", async (event) => {
    event.preventDefault();
    const profile = aiProfile.value;
    const button = aiSettings.querySelector("button");
    button.disabled = true;
    try {
      const settings = {
        resume: aiSettings.elements.resume.value, preferences: aiSettings.elements.preferences.value,
        weights: Object.fromEntries(weights.map((weight) => [weight.dataset.dimension, Number(weight.value)]))
      };
      const data = await api("/ai/settings", { profile, settings });
      if (aiKind === "match" && aiProfile.value === profile) {
        showAiSettings(data);
        aiFeedback.textContent = "初评配置已保存。";
        void loadAiCandidates();
      }
      void loadJobs();
    } catch (error) {
      if (aiProfile.value === profile) aiFeedback.textContent = error.message;
    } finally {
      if (aiProfile.value === profile) button.disabled = false;
      updateAiRun();
    }
  });

  function aiResultLabel(result) {
    if (result.score != null) return `${result.score} 分 · ${result.coverage} 项有依据`;
    return { passed: "通过", rejected: "淘汰", extracted: "提取完成", review: "待核对" }[result.verdict] || "已完成";
  }

  aiRun.onclick = async () => {
    const selected = [...aiCandidates.querySelectorAll("input:checked")];
    if (aiRun.disabled || !selected.length) return;
    aiRunning = true;
    aiProfile.disabled = aiSearch.disabled = true;
    const save = aiSettings.querySelector("button");
    const saveWasDisabled = save.disabled;
    save.disabled = true;
    for (const input of aiCandidates.querySelectorAll("input")) input.disabled = true;
    updateAiRun();
    aiBatchResults.replaceChildren();
    let completed = 0;
    for (const item of selected) {
      aiFeedback.textContent = `正在处理 ${completed + 1} / ${selected.length} 条…`;
      const title = item.closest("label").textContent;
      let summary;
      try {
        const { result } = await api("/ai/run/" + aiKind, { profile: aiProfile.value, source: item.dataset.source, url: item.value });
        summary = [aiResultLabel(result), result.reason].filter(Boolean).join(" · ");
      } catch (error) {
        summary = error.message;
      }
      aiBatchResults.append(node("li", title + " · " + summary));
      completed += 1;
    }
    aiFeedback.textContent = `已处理 ${completed} 条岗位。`;
    aiRunning = false;
    aiProfile.disabled = aiSearch.disabled = false;
    save.disabled = saveWasDisabled;
    void loadAiCandidates();
    void loadJobs();
  };

  function renderJobAi(results) {
    const section = byId("recruitmentAiDetails");
    section.replaceChildren();
    for (const [kind, entry] of Object.entries(results)) {
      const title = { semantic: "AI 语义清洗", match: "AI 初评", vision: "图片提取结果" }[kind];
      section.append(node("h3", title + " · " + aiResultLabel(entry)));
      if (entry.reason) section.append(node("p", entry.reason));
      if (entry.evidence) section.append(node("p", "岗位原文：" + entry.evidence));
      for (const part of Object.values(entry.dimensions || {})) {
        const card = node("div", "", "recruitment-ai-evidence");
        card.append(node("strong", `${part.label} · ${part.score == null ? "待核对" : part.score + " / 5"}`), node("p", part.reason));
        if (part.jd_evidence) card.append(node("p", "岗位原文：" + part.jd_evidence));
        if (part.resume_evidence) card.append(node("p", "简历或偏好依据：" + part.resume_evidence));
        section.append(card);
      }
      for (const job of entry.jobs || []) {
        const card = node("div", "", "recruitment-ai-evidence");
        card.append(node("strong", job.title), node("p", [job.company, job.location, job.salary].filter(Boolean).join(" · ")),
          node("p", job.description));
        section.append(card);
      }
    }
    section.hidden = !section.childNodes.length;
  }

  function setupJobAi(row, sequence) {
    const identity = { source: row.source, url: row.url };
    const vision = byId("recruitmentVision");
    const files = byId("recruitmentVisionFiles");
    const feedback = byId("recruitmentVisionFeedback");
    const read = byId("recruitmentVisionRead");
    const upload = byId("recruitmentVisionUpload");
    const show = (results) => { if (sequence === detailSequence) renderJobAi(results); };
    let stored = {};
    show(stored);
    void api("/ai/details", identity).then(({ results }) => {
      stored = { ...results, ...stored };
      show(stored);
    }).catch(() => {});
    vision.hidden = row.source !== "xiaohongshu";
    files.value = "";
    feedback.textContent = "";
    read.disabled = upload.disabled = false;
    async function extract(useFiles) {
      let payload = identity;
      if (useFiles) {
        if (!files.files.length) {
          feedback.textContent = "请先选择图片。";
          return;
        }
        payload = new FormData();
        for (const [name, value] of Object.entries(identity)) payload.append(name, value);
        for (const file of files.files) payload.append("images", file);
      }
      read.disabled = upload.disabled = true;
      feedback.textContent = "正在读取并提取岗位…";
      try {
        const { result } = await api("/ai/run/vision", payload);
        stored = { vision: result };
        show(stored);
        if (sequence === detailSequence) feedback.textContent = result.jobs.length ? `识别到 ${result.jobs.length} 个岗位。` : result.reason;
        void loadJobs();
      } catch (error) {
        if (sequence === detailSequence) feedback.textContent = error.message;
      } finally {
        if (sequence === detailSequence) read.disabled = upload.disabled = false;
      }
    }
    read.onclick = () => { void extract(false); };
    upload.onclick = () => { void extract(true); };
  }

  const sessions = byId("recruitmentSessions");
  if (sessions) {
    const localChrome = config.elements.bossLocal;
    const checkAll = byId("recruitmentCheckAll");
    const syncVisibility = () => { sessions.hidden = !localChrome.checked; };
    localChrome.addEventListener("change", syncVisibility);
    syncVisibility();
    const checks = Array.from(sessions.querySelectorAll(".recruitment-session"), (card) => {
      const button = card.querySelector("button");
      const result = card.querySelector(".recruitment-session-result");
      const label = result.querySelector(".recruitment-session-label");
      const message = result.querySelector(".recruitment-session-message");
      function render(state, title, detail = "") {
        result.dataset.state = state;
        label.textContent = title;
        message.textContent = detail;
        message.hidden = !detail;
      }
      async function check() {
        if (button.disabled) return;
        button.disabled = true;
        render("checking", "检查中…");
        try {
          const status = await api(`/session/${card.dataset.source}`, {});
          render(status.state, status.label, status.message);
        } catch (error) {
          render("unavailable", "检查失败", error.message);
        } finally {
          button.disabled = false;
        }
      }
      button.addEventListener("click", check);
      return check;
    });
    checkAll.addEventListener("click", async () => {
      checkAll.disabled = true;
      try {
        await Promise.all(checks.map((check) => check()));
      } finally {
        checkAll.disabled = false;
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
    const profile = profileSelect.value;
    data.append("profile", profile);
    try {
      const result = await api("/import", data);
      notice(`已保存 ${result.count} 条记录 · ${profileNames.get(profile)}。` +
        (Object.keys(result.cleaning || {}).length ? cleaningSummary(result.cleaning) : ""));
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
    htmlForm.elements.profile.value = profileSelect.value;
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
      notice(`已保存 ${result.count} 条记录。` + (Object.keys(result.cleaning || {}).length ? cleaningSummary(result.cleaning) : ""));
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
