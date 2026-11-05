(() => {
  const root = document.getElementById("datasetBrowser");
  if (!root) return;
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = "/static/dataset-browser.css";
  document.head.appendChild(stylesheet);
  const detailStylesheet = document.createElement("link");
  detailStylesheet.rel = "stylesheet";
  detailStylesheet.href = root.dataset.detailStyleUrl || "/static/job-detail.css";
  document.head.appendChild(detailStylesheet);

  const categories = document.getElementById("datasetCategories");
  const search = document.getElementById("datasetSearch");
  const status = document.getElementById("datasetStatus");
  const results = document.getElementById("datasetResults");
  const pagination = document.getElementById("datasetPagination");
  const retry = document.getElementById("datasetRetry");
  const dialog = document.getElementById("datasetDetail");
  const detailBody = document.getElementById("datasetDetailBody");
  const detailHeader = document.getElementById("datasetDetailHeader");
  const detailFooter = document.getElementById("datasetDetailFooter");
  const previous = root.querySelector('[data-dataset-action="previous"]');
  const next = root.querySelector('[data-dataset-action="next"]');
  const cache = new Map();
  let datasets = [];
  let catalogPromise = null;
  let selected = "";
  let page = 1;
  let query = "";
  let listController = null;
  let detailController = null;
  let pending = false;
  let needsReload = false;
  let analyticsPromise = null;
  let detailRecord = null;
  let currentView = document.getElementById("liveJobMarket") ? "live" : "list";
  const categoryState = new Map();
  const categoryViews = {
    city_jobs: { title: "城市岗位", label: "寻找适合你的岗位", placeholder: "搜索岗位、技能、公司或城市", tag: "招聘样本", picks: ["前端", "Python", "产品经理", "实习"] },
    other_city: { title: "跨城机会", label: "探索更多城市的工作机会", placeholder: "输入城市、岗位或公司名称", tag: "城市拓展", picks: ["技术支持", "软件", "工程师", "运营"] },
    job_research_hub: { title: "招聘档案", label: "查找招聘记录", placeholder: "搜索岗位名称、公司或技能", tag: "历史快照", picks: ["开发", "数据分析", "销售", "设计"] },
    occupation: { title: "职业百科", label: "了解职业与分类", placeholder: "搜索职业名称、分类编码或所属类别", tag: "职业知识", picks: ["计算机", "工程", "技术", "服务"] },
    industry: { title: "行业图谱", label: "探索行业与产业分类", placeholder: "搜索行业名称、分类编码或相关业务", tag: "行业知识", picks: ["软件", "互联网", "制造", "金融"] }
  };
  root.querySelector('[data-dataset-action="analytics"]')?.remove();
  if (!document.querySelector(".jobs-view-switch")) {
    root.insertAdjacentHTML("beforebegin", '<nav class="jobs-view-switch" aria-label="探索视图"><button type="button" data-jobs-view="list" aria-pressed="true" aria-controls="datasetBrowser">岗位列表</button><button type="button" data-jobs-view="cities" aria-pressed="false" aria-controls="legacyJobsExplorer">城市分析</button></nav>');
  }
  const searchForm = document.getElementById("datasetSearchForm");
  searchForm.insertAdjacentHTML("beforebegin", '<div class="ds-section-heading" id="datasetSectionHeading"></div>');
  searchForm.insertAdjacentHTML("beforeend", '<div class="ds-search-picks" id="datasetSearchPicks" aria-label="快捷搜索"></div>');

  const closeIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
  const locationIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></svg>';
  const arrowIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>';
  const categoryIcons = {
    city_jobs: '<rect x="4" y="7" width="16" height="13" rx="3"/><path d="M9 7V4h6v3M4 12c5 3 11 3 16 0M12 12v4"/>',
    other_city: '<path d="M4 20V8l8-4v16M12 10l8-3v13M8 9v2m0 3v2m8-5v2m0 3v1M3 20h18"/>',
    job_research_hub: '<rect x="5" y="4" width="14" height="17" rx="3"/><path d="M9 4V2h6v2M9 9h6M9 13h6M9 17h3"/>',
    occupation: '<path d="M12 6C9 3 5 3 2 4v15c4-1 7-1 10 2 3-3 6-3 10-2V4c-3-1-7-1-10 2Zm0 0v15"/>',
    industry: '<path d="M4 20V9l6 3V7l6 3V4h4v16ZM8 16v1m4-1v1m4-1v1"/>'
  };
  const categoryTones = { city_jobs: "blue", other_city: "teal", job_research_hub: "violet", occupation: "amber", industry: "slate" };

  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
  const number = (value) => Number(value).toLocaleString("zh-CN");
  const endpoint = (path) => typeof resolveApiUrl === "function" ? resolveApiUrl(path) : path;

  async function request(path, signal) {
    const response = await fetch(endpoint(path), { credentials: "include", signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || "读取失败，请稍后重试。");
    return data;
  }

  function renderCategories() {
    categories.innerHTML = datasets.map(dataset => `<button type="button" data-dataset="${escape(dataset.id)}" data-tone="${categoryTones[dataset.id] || "blue"}" aria-pressed="${dataset.id === selected}">
      <span class="ds-category-top"><span class="ds-category-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${categoryIcons[dataset.id] || categoryIcons.city_jobs}</svg></span><span class="ds-category-check" aria-hidden="true">✓</span></span>
      <span class="ds-category-name">${escape(dataset.name)}</span><span class="ds-category-total"><strong>${number(dataset.count)}</strong><small>${dataset.kind === "job" ? "条岗位样本" : "条分类知识"}</small></span><span class="ds-category-bottom">${escape(categoryViews[dataset.id]?.tag || "探索")}${arrowIcon}</span></button>`).join("");
    const view = categoryViews[selected];
    if (!view) return;
    root.dataset.active = selected;
    root.dataset.tone = categoryTones[selected];
    document.getElementById("datasetSectionHeading").innerHTML = `<div><span class="ds-section-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${categoryIcons[selected]}</svg></span><h3>${escape(view.title)}</h3></div><span class="ds-section-count">${number(datasets.find(d => d.id === selected)?.count || 0)} ${selected === "occupation" || selected === "industry" ? "条分类" : "条样本"}</span>`;
    searchForm.querySelector("label").textContent = view.label;
    search.placeholder = view.placeholder;
    document.getElementById("datasetSearchPicks").innerHTML = `<span>快捷查找</span>${view.picks.map(pick => `<button type="button" data-dataset-query="${escape(pick)}">${escape(pick)}</button>`).join("")}`;
  }

  async function loadCatalog() {
    if (!catalogPromise) {
      catalogPromise = request("/api/datasets").then((data) => {
        datasets = data.datasets;
        if (!selected) selected = datasets[0]?.id || "";
        renderCategories();
        if (selected) void loadPage();
        retry.hidden = true;
      }).catch((error) => {
        catalogPromise = null;
        status.textContent = error.message;
        retry.hidden = false;
      });
    }
    await catalogPromise;
  }

  function renderRecords(items) {
    const dataset = datasets.find(value => value.id === selected);
    results.innerHTML = items.map(item => {
      const isJob = item.kind === "job";
      if (!isJob) {
        const industry = item.kind === "industry";
        const codes = item.codes || [];
        const parents = item.parents || [];
        return `<article class="dataset-card ds-knowledge-card" data-tone="${industry ? "slate" : "amber"}">
          <div class="ds-knowledge-top"><span class="ds-knowledge-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${categoryIcons[industry ? "industry" : "occupation"]}</svg></span><span>${industry ? "行业分类" : "职业分类"}</span>${codes.length ? `<code>${escape(codes.join(" / "))}</code>` : ""}</div>
          <h4>${escape(item.title)}</h4>${parents.length ? `<p class="ds-knowledge-parent">${escape(parents.join(" / "))}</p>` : ""}
          ${item.preview ? `<p class="dataset-card-preview">${escape(item.preview)}</p>` : '<p class="ds-knowledge-quiet">分类条目</p>'}
          <div class="ds-card-foot"><span class="ds-card-source">${industry ? "行业图谱" : "职业百科"}</span><button type="button" data-record="${escape(item.id)}" aria-label="查看${escape(item.title)}详情">查看分类${arrowIcon}</button></div></article>`;
      }
      const identity = item.company || (isJob ? "公司未提供" : item.kind === "industry" ? "行业分类" : "职业分类");
      const hash = Array.from(identity).reduce((sum, character) => sum + character.codePointAt(0), 0);
      const tone = ["blue", "teal", "violet", "amber"][hash % 4];
      const cities = (item.locations || []).join(" / ");
      const internship = isJob && /实习|intern/i.test(item.title);
      const skills = item.skills || [];
      const salary = String(item.salary || "薪资未提供").replace(/(\d)\s*[-~～]\s*(?=\d)/g, "$1–");
      const salaryParts = salary.match(/^(.*?)(元\s*[\/／]\s*(?:天|日|月|年|小时)|[kK](?:\s*[·•]\s*.*)?|万.*)$/);
      const salaryHtml = salaryParts ? `${escape(salaryParts[1])}<small>${escape(salaryParts[2])}</small>` : escape(salary);
      const metadata = isJob ? [item.education].filter(Boolean) : [...(item.codes || []), ...(item.parents || [])].filter(Boolean);
      return `<article class="dataset-card${isJob ? " ds-job-card" : " ds-knowledge-card"}" data-tone="${tone}">
        <div class="ds-card-head"><span class="ds-company-mark" aria-hidden="true">${escape(Array.from(identity).slice(0, /^[\x00-\x7F]/.test(identity) ? 2 : 1).join("").toUpperCase())}</span><div class="ds-company-identity"><p class="dataset-card-company">${escape(identity)}</p>${cities ? `<span class="ds-card-city">${locationIcon}${escape(cities)}</span>` : ""}</div>${internship ? '<span class="ds-intern-badge">实习</span>' : ""}</div>
        <h4>${escape(item.title)}</h4>
        ${isJob ? `<div class="ds-salary-row"><p class="ds-card-salary${item.salary ? "" : " is-missing"}">${salaryHtml}</p>${metadata.map(value => `<span class="ds-education">${escape(value)}</span>`).join("")}</div>` : `<p class="ds-knowledge-code">${escape(metadata.join(" · "))}</p>`}
        ${item.preview ? `<p class="dataset-card-preview">${escape(item.preview)}</p>` : ""}
        ${skills.length ? `<div class="dataset-card-skills">${skills.slice(0, 4).map(skill => `<span>${escape(skill)}</span>`).join("")}${skills.length > 4 ? '<span class="ds-more-skills">+更多</span>' : ""}</div>` : ""}
        <div class="ds-card-foot"><span class="ds-card-source"><i aria-hidden="true"></i>${escape(dataset?.name || "")}</span><button type="button" data-record="${escape(item.id)}" aria-label="查看${escape(item.title)}详情">查看详情${arrowIcon}</button></div></article>`;
    }).join("");
  }

  async function loadPage(targetPage = 1) {
    if (!selected) {
      status.textContent = "请先选择数据分类，再搜索其中的内容。";
      return;
    }
    listController?.abort();
    const controller = new AbortController();
    listController = controller;
    page = targetPage;
    pending = true;
    needsReload = false;
    root.setAttribute("aria-busy", "true");
    previous.disabled = next.disabled = true;
    pagination.hidden = true;
    retry.hidden = true;
    results.innerHTML = Array.from({length: 6}, () => '<div class="ds-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>').join("");
    status.textContent = "正在加载…";
    const parameters = new URLSearchParams({ page: String(targetPage), page_size: "12", q: query });
    const path = `/api/datasets/${encodeURIComponent(selected)}/records?${parameters}`;
    try {
      const cached = cache.get(path);
      const fresh = cached && Date.now() - cached.created < 60000;
      const data = fresh ? cached.data : await request(path, controller.signal);
      if (controller.signal.aborted) return;
      cache.delete(path);
      cache.set(path, { data, created: fresh ? cached.created : Date.now() });
      if (cache.size > 10) cache.delete(cache.keys().next().value);
      page = data.page;
      const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
      renderRecords(data.items);
      if (!data.total) results.innerHTML = `<div class="ds-empty"><span aria-hidden="true">⌕</span><h4>没有找到相关${datasetKindLabel()}</h4><p>换一个关键词，或查看此分类的全部内容。</p><button type="button" data-dataset-action="reset-search">查看全部</button></div>`;
      status.textContent = data.total ? `共 ${number(data.total)} 条${query ? "匹配记录" : "记录"}` : "没有匹配记录，试试其他关键词或数据分类。";
      pagination.hidden = data.total === 0;
      document.getElementById("datasetPageInfo").textContent = `第 ${page} / ${number(totalPages)} 页`;
      previous.disabled = page <= 1;
      next.disabled = page >= totalPages;
    } catch (error) {
      if (error.name !== "AbortError") {
        needsReload = true;
        results.replaceChildren();
        status.textContent = error.message;
        retry.hidden = false;
      }
    } finally {
      if (listController === controller) {
        pending = false;
        root.removeAttribute("aria-busy");
      }
    }
  }

  function datasetKindLabel() {
    return selected === "occupation" ? "职业" : selected === "industry" ? "行业" : "岗位";
  }

  function safeLink(value) {
    try {
      const parsed = new URL(value);
      return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  }

  function sourceName(source) {
    return datasets.find(dataset => dataset.id === source.dataset)?.name || ({
      china_occupations_2022: "2022 职业分类", common_chinese_occupations: "常见职业分类", china_industries_2017: "2017 行业分类"
    })[source.dataset] || source.platform || "公开招聘信息";
  }

  function jobSections(record) {
    const description = String(record.description || "").replace(/\r\n?/g, "\n");
    const heading = /^[ \t]*(?:[一二三四五六七八九十\d]+[、.．)）][ \t]*)?(岗位职责|工作职责|职责描述|工作内容|岗位描述|职位描述|任职要求|任职资格|岗位要求|职位要求|招聘要求|任职条件|加分项|优先条件|岗位亮点|职位亮点|福利待遇|岗位福利|工作时间)[ \t]*(?:[：:][ \t]*|(?=$))/gm;
    const matches = [...description.matchAll(heading)];
    const sections = [];
    if (matches.length) {
      const intro = description.slice(0, matches[0].index).trim();
      if (intro) sections.push({ title: "岗位介绍", text: intro });
      matches.forEach((match, index) => {
        const text = description.slice(match.index + match[0].length, matches[index + 1]?.index ?? description.length).trim();
        if (text) sections.push({ title: match[1], text });
      });
    } else if (description.trim()) {
      sections.push({ title: "岗位内容", text: description.trim() });
    }
    [["岗位职责", record.responsibilities], ["任职要求", record.requirements]].forEach(([title, value]) => {
      const text = Array.isArray(value) ? value.join("\n") : String(value || "");
      if (text.trim() && !description.replace(/\s/g, "").includes(text.replace(/\s/g, ""))) sections.push({ title, text: text.trim() });
    });
    return sections;
  }

  function sectionContent(text) {
    const blocks = [];
    let paragraph = [];
    let list = [];
    function flushParagraph() {
      if (paragraph.length) blocks.push(`<p class="jd-paragraph">${escape(paragraph.join("\n"))}</p>`);
      paragraph = [];
    }
    function flushList() {
      if (list.length) blocks.push(`<ol class="jd-num-list">${list.map((item, index) => `<li><span class="jd-num" aria-hidden="true">${item.bullet ? "·" : String(index + 1).padStart(2, "0")}</span><span>${escape(item.text)}</span></li>`).join("")}</ol>`);
      list = [];
    }
    for (const line of String(text).split("\n")) {
      const item = line.match(/^\s*(?:(\d{1,3})[.、．)）]|([-•◦▪●]))\s*(.+)$/);
      if (item) {
        flushParagraph();
        list.push({ text: item[3], bullet: Boolean(item[2]) });
      } else if (line.trim()) {
        if (list.length) list[list.length - 1].text += `\n${line.trim()}`;
        else paragraph.push(line.trim());
      } else {
        flushParagraph();
      }
    }
    flushParagraph();
    flushList();
    return blocks.join("");
  }

  function renderJobDetail(record) {
    const title = record.title || "岗位详情";
    const company = record.company || "公司未提供";
    const cities = (record.locations || []).filter(Boolean).join(" · ");
    const internship = /实习|intern/i.test(`${title} ${record.recruitment_type || ""}`);
    const badge = record.recruitment_type || (internship ? "实习岗位" : "招聘岗位");
    const salary = String(record.salary || "薪资未提供").replace(/(\d)\s*[-~～]\s*(?=\d)/g, "$1–");
    const salaryUnit = /元\s*[\/／]\s*[天日]/.test(salary) ? "日薪" : /元\s*[\/／]\s*月/.test(salary) ? "月薪" : "";
    const tags = [record.education, ...String(record.experience || "").split(/[,，;；]|\s+(?=\d)/), record.graduation_year].filter(Boolean);
    detailHeader.className = "dataset-detail-head jd-head";
    detailHeader.innerHTML = `<div class="jd-topline"><span class="jd-label"><span class="jd-dot"></span>${escape(badge)}</span><button type="button" class="jd-close" data-dataset-action="close" aria-label="关闭岗位详情">${closeIcon}</button></div>
      <h2 id="datasetDetailTitle">${escape(title)}</h2>
      <div class="jd-subline"><span class="jd-company-icon" aria-hidden="true">${escape(company.slice(0, 1))}</span><strong>${escape(company)}</strong>${[record.industry, cities].filter(Boolean).map(value => `<span class="jd-meta-dot" aria-hidden="true">·</span><span>${escape(value)}</span>`).join("")}</div>
      <div class="jd-salary-row"><div class="jd-salary">${escape(salary)}${salaryUnit ? `<span>· ${salaryUnit}</span>` : ""}</div><div class="jd-summary-tags">${tags.map(tag => `<span class="jd-tag-light">${escape(tag)}</span>`).join("")}</div>`;
    const skills = [...new Set((record.skills || []).filter(Boolean))];
    skills.sort((a, b) => Number(/^(python|agent)$/i.test(b)) - Number(/^(python|agent)$/i.test(a)));
    const sections = jobSections(record);
    const rows = [[internship ? "实习薪资" : "岗位薪资", salary], ["工作城市", cities], ["学历要求", record.education], [internship ? "实习安排" : "经验要求", record.experience], ["行业领域", record.industry], ["公司规模", record.company_scale]].filter(([, value]) => value);
    const sources = record.sources || [];
    const sourceLabels = [...new Set(sources.map(sourceName))];
    const urls = [...new Set(sources.map(source => safeLink(source.url)).filter(Boolean))];
    const location = record.work_address || cities;
    detailBody.innerHTML = `<div class="jd-body"><div class="jd-maincol">
      ${skills.length ? `<section class="jd-section"><h3 class="jd-sect-head">岗位技能</h3><div class="jd-skill-list">${skills.map(skill => `<span class="jd-skill${/^(python|agent)$/i.test(skill) ? " primary" : ""}">${escape(skill)}</span>`).join("")}</div></section>` : ""}
      ${sections.length ? sections.map(section => `<section class="jd-section"><h3 class="jd-sect-head">${escape(section.title)}</h3>${sectionContent(section.text)}</section>`).join("") : '<p class="jd-paragraph">暂无岗位描述</p>'}
      </div><aside class="jd-aside"><section class="jd-info-card blue"><h3>岗位概览</h3>${rows.map(([label, value]) => `<div class="jd-info-row"><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`).join("")}</section>
      ${location ? `<section class="jd-info-card"><h3>工作地点</h3><div class="jd-location">${locationIcon}<span>${escape(location)}</span></div></section>` : ""}
      <section class="jd-info-card"><h3>来源信息</h3><div class="jd-sources">${sourceLabels.map(label => `<span class="jd-source">${escape(label)}</span>`).join("")}</div>${urls.length ? urls.map(url => `<a class="jd-source-link" href="${escape(url)}" target="_blank" rel="noopener noreferrer">查看原始岗位 ↗</a>`).join("") : '<p class="jd-hint">暂无原始岗位链接</p>'}${record.published_at ? `<p class="jd-hint">发布于 ${escape(record.published_at)}</p>` : ""}</section></aside></div>`;
    detailFooter.className = "jd-foot";
    detailFooter.hidden = false;
    detailFooter.innerHTML = '<span class="jd-foot-note">职位信息来自公开招聘样本<br>请以招聘方最新发布内容为准</span><div class="jd-actions"><button type="button" class="jd-ghost" data-dataset-action="copy-job">复制岗位信息</button><button type="button" class="jd-primary" data-dataset-action="close">返回岗位列表 →</button></div>';
    detailBody.scrollTop = 0;
    detailHeader.querySelector("button")?.focus({ preventScroll: true });
  }

  async function copyJob(button) {
    if (!detailRecord) return;
    const record = detailRecord;
    const text = [record.title, [record.company, ...(record.locations || []), record.salary, record.education, record.experience].filter(Boolean).join(" · "), record.skills?.length ? `技能：${record.skills.join("、")}` : "", record.description, record.responsibilities, record.requirements, record.work_address ? `工作地址：${record.work_address}` : ""].filter(Boolean).join("\n\n");
    let copied = false;
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (_) {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.cssText = "position:fixed;opacity:0;left:0;top:0";
      dialog.appendChild(field);
      field.select();
      try { copied = document.execCommand("copy"); } catch (_) { /* Clipboard unavailable. */ }
      field.remove();
      button.focus();
    }
    if (typeof window.showToast === "function") window.showToast(copied ? "岗位信息已复制" : "复制失败", copied ? "" : "请检查浏览器剪贴板权限。", copied ? "success" : "warning", 2200);
    else {
      button.textContent = copied ? "已复制" : "复制失败，请重试";
      window.setTimeout(() => { button.textContent = "复制岗位信息"; }, 2200);
    }
  }

  async function showDetail(recordId) {
    detailController?.abort();
    const controller = new AbortController();
    detailController = controller;
    detailRecord = null;
    const isJob = datasets.find(dataset => dataset.id === selected)?.kind === "job";
    dialog.classList.toggle("jd-modal", isJob);
    dialog.classList.toggle("ds-knowledge-modal", !isJob);
    detailHeader.className = isJob ? "dataset-detail-head jd-head" : "dataset-detail-head";
    detailHeader.innerHTML = `<h3 id="datasetDetailTitle">${isJob ? "岗位详情" : "分类详情"}</h3><button type="button" data-dataset-action="close" class="${isJob ? "jd-close" : ""}" autofocus aria-label="关闭详情">${closeIcon}</button>`;
    detailFooter.hidden = true;
    detailBody.className = isJob ? "jd-scroll" : "";
    detailBody.tabIndex = isJob ? 0 : -1;
    detailBody.innerHTML = '<div class="jd-loading" role="status">正在加载…</div>';
    document.body.classList.add("dataset-detail-open");
    if (!dialog.open) dialog.showModal();
    try {
      const record = await request(`/api/datasets/${encodeURIComponent(selected)}/records/${encodeURIComponent(recordId)}`, controller.signal);
      if (controller.signal.aborted) return;
      if (isJob) {
        detailRecord = record;
        renderJobDetail(record);
        return;
      }
      const industry = selected === "industry";
      const title = record.title || record.name || "分类详情";
      document.getElementById("datasetDetailTitle").textContent = title;
      detailHeader.insertAdjacentHTML("afterbegin", `<span class="ds-detail-type">${industry ? "行业图谱" : "职业百科"}</span>`);
      const sources = (record.sources || []).map((source) => {
        const url = safeLink(source.url);
        return `<div class="ds-reference"><strong>${escape(sourceName(source))}</strong><div>${source.code ? `<code>${escape(source.code)}</code>` : ""}${source.parent_name ? `<span>${escape(source.parent_name)}</span>` : ""}${url ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>` : ""}</div></div>`;
      }).join("");
      const codes = [...new Set((record.sources || []).map(s => s.code).filter(Boolean))];
      const parents = [...new Set((record.sources || []).map(s => s.parent_name).filter(Boolean))];
      detailBody.innerHTML = `<div class="ds-detail-facts">${codes.length ? `<div><span>分类编码</span><strong>${escape(codes.join(" / "))}</strong></div>` : ""}${parents.length ? `<div><span>所属类别</span><strong>${escape(parents.join(" / "))}</strong></div>` : ""}</div>
        <section class="ds-detail-section"><h4>${industry ? "行业说明" : "职业说明"}</h4>${record.description ? `<p>${escape(record.description)}</p>` : '<p class="ds-detail-muted">此分类暂无详细说明。</p>'}</section>
        ${sources ? `<section class="ds-detail-section"><h4>分类来源</h4>${sources}</section>` : ""}`;
    } catch (error) {
      if (error.name !== "AbortError") detailBody.innerHTML = `<div class="jd-loading" role="alert">${escape(error.message)}</div>`;
    }
  }

  root.addEventListener("click", (event) => {
    const category = event.target.closest("[data-dataset]");
    if (category) {
      if (selected) categoryState.set(selected, { query: search.value.trim(), page });
      selected = category.dataset.dataset;
      const saved = categoryState.get(selected);
      query = saved?.query || "";
      search.value = query;
      page = saved?.page || 1;
      dialog.close();
      renderCategories();
      void loadPage(page);
    }
    const card = event.target.closest("[data-record]");
    if (card) void showDetail(card.dataset.record);
    const action = event.target.closest("[data-dataset-action]")?.dataset.datasetAction;
    if (action === "close") dialog.close();
    if (action === "copy-job") void copyJob(event.target.closest("button"));
    if (action === "previous" && !pending) void loadPage(page - 1);
    if (action === "next" && !pending) void loadPage(page + 1);
    const pick = event.target.closest("[data-dataset-query]");
    if (pick || action === "reset-search") {
      query = pick?.dataset.datasetQuery || "";
      search.value = query;
      void loadPage();
    }
  });
  function selectView(view) {
    currentView = view;
    const cities = view === "cities";
    root.hidden = view !== "list";
    const live = document.getElementById("liveJobMarket");
    if (live) live.hidden = view !== "live";
    document.getElementById("legacyJobsExplorer").hidden = !cities;
    document.querySelectorAll("[data-jobs-view]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.jobsView === view));
    });
    dialog.close();
    window.dispatchEvent(new CustomEvent("jobs:view-changed", { detail: { view } }));
    if (view === "list") void loadCatalog();
    if (cities && !analyticsPromise) {
      const panel = document.getElementById("legacyJobsExplorer");
      const loading = document.getElementById("jobsLoading");
      panel.setAttribute("aria-busy", "true");
      loading.innerHTML = '<div class="loading-spinner mx-auto mb-4"></div><p>正在加载城市分析…</p>';
      analyticsPromise = loadJobs().finally(() => {
        panel.setAttribute("aria-busy", "false");
        if (!allJobsData.length) {
          analyticsPromise = null;
          loading.classList.remove("hidden");
          loading.innerHTML = '<p>暂时无法加载城市数据</p><button type="button" class="jobs-city-retry">重新加载</button>';
          loading.querySelector("button").addEventListener("click", () => selectView("cities"));
        }
      });
    }
    if (cities) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  document.querySelector(".jobs-view-switch").addEventListener("click", event => {
    const button = event.target.closest("[data-jobs-view]");
    if (button) selectView(button.dataset.jobsView);
  });
  dialog.addEventListener("close", () => {
    if (dialog.open) return;
    detailController?.abort();
    detailRecord = null;
    document.body.classList.remove("dataset-detail-open");
  });
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  document.getElementById("datasetSearchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    query = search.value.trim();
    page = 1;
    void loadPage();
  });
  retry.addEventListener("click", () => selected ? void loadPage(page) : void loadCatalog());

  window.DatasetBrowser = {
    async open(options = {}) {
      if (options.query !== undefined) {
        selectView("list");
        search.value = options.query.slice(0, 100);
        query = search.value.trim();
        needsReload = Boolean(selected);
        page = 1;
      }
      selectView(currentView);
      if (currentView !== "list") return;
      await loadCatalog();
      if (needsReload) void loadPage(page);
      if (!document.getElementById("legacyJobsExplorer").hidden) requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    },
    pause() {
      window.JobMarket?.pause();
      if (pending) {
        needsReload = true;
        listController?.abort();
      }
      detailController?.abort();
      dialog.close();
    }
  };
})();
