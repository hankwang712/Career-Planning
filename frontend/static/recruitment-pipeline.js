/* 岗位全链路流水线 · 面板层
   右滑抽屉 7 面板：本地导入 / 规则清洗 / AI 评估 /
   简历改写 / 打招呼语 / 审批操作 / 投递队列 + 物料预览渲染。
   依赖 recruitment.js 暴露的 window.RP；流水线配置走 /pipeline/config。 */
(() => {
  "use strict";
  const RP = window.RP;
  if (!RP) return;
  const { node, icon, tile, toast, api, pipelineApi, meta, state } = RP;

  const PROFILE_KEYS = Object.keys(meta.profiles || { general: "通用" });
  const DEEP_KEYS = [
    ["extracted_skills", "技能提取"],
    ["ats_ability_analysis", "ATS 能力分析"],
    ["resume_audit", "简历审计"],
    ["dream_picture", "理想画像"],
    ["strong_fit_assessment", "强匹配评估"],
    ["risk_red_flags", "风险红旗"],
    ["deep_action_plan", "深度行动建议"]
  ];
  const DIMENSION_LABELS = {
    role_match: "职责匹配", skills_align: "技能重合", seniority: "职级资历", compensation: "薪资契合",
    interview_prob: "面试概率", company_stage: "公司阶段", market_fit: "赛道前景", growth: "成长空间"
  };
  const GRADE_OPTIONS = ["A", "B", "C", "D", "F"];

  /* ---------- 面板小工具 ---------- */
  function alive(token, body) { return token === RP.drawerToken() && body.isConnected; }
  function section(title, iconName) {
    const root = node("section", "", "rp-panel-section");
    if (title) {
      const h = node("h3", title);
      if (iconName) h.prepend(icon(iconName));
      root.append(h);
    }
    return root;
  }
  function note(text, tone) {
    const el = node("p", text, "rp-panel-note");
    if (tone) el.dataset.tone = tone;
    return el;
  }
  function feedback() { return node("p", "", "rp-feedback"); }
  function setFeedback(el, message, tone) {
    el.textContent = message || "";
    if (tone) el.dataset.tone = tone;
    else delete el.dataset.tone;
  }
  function field(labelText, control, span2) {
    const label = node("label", "", "rp-field" + (span2 ? " rp-span-2" : ""));
    label.append(node("span", labelText), control);
    return label;
  }
  function input(type, attrs = {}) {
    const el = node("input");
    el.type = type;
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
    return el;
  }
  function select(options, value) {
    const el = node("select");
    for (const [key, label] of options) el.append(new Option(label, key));
    if (value != null) el.value = value;
    return el;
  }
  /* SOURCES 值为元组（标签+URL+选择器），JSON 后是数组；展示只取标签 */
  const sourceLabel = (value) => Array.isArray(value) ? String(value[0] || "") : String(value ?? "");
  const sourceEntries = (map) => Object.entries(map || {}).map(([key, value]) => [key, sourceLabel(value)]);
  /* 平台 logo（brand/recruitment/<key>.jpg）；缺资产时回退首字 tile */
  function platformLogo(key, label) {
    const wrap = node("span", "", "rp-platform-mark");
    const img = node("img");
    img.src = `/static/brand/recruitment/${key}.jpg`;
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      wrap.replaceChildren(node("span", (label || key).slice(0, 2)));
      wrap.dataset.fallback = "1";
    });
    wrap.append(img);
    return wrap;
  }
  function profileSelect(value) {
    return select(Object.entries(meta.profiles), value || PROFILE_KEYS[0]);
  }
  function button(label, cls, iconName) {
    const el = node("button", label, "rp-btn " + (cls || ""));
    el.type = "button";
    if (iconName) el.prepend(icon(iconName));
    return el;
  }
  function emptyBlock(title, desc, actionLabel, onAction) {
    const el = node("div", "", "rp-empty");
    el.append(tile("inbox", "accent"), node("strong", title));
    if (desc) el.append(node("p", desc));
    if (actionLabel) {
      const action = button(actionLabel, "rp-btn-primary");
      action.addEventListener("click", onAction);
      el.append(action);
    }
    return el;
  }
  function gradeBadge(grade) {
    const el = node("span", grade || "—", "rp-grade");
    if (grade) el.dataset.grade = grade;
    return el;
  }
  function payloadOf(payload, ...keys) {
    if (!payload) return null;
    for (const key of keys) {
      if (payload[key] != null && payload[key] !== "") return payload[key];
    }
    return null;
  }
  async function copyText(text, okMessage) {
    if (!text) { toast("没有可复制的内容。", "warning"); return; }
    try {
      await navigator.clipboard.writeText(text);
      toast(okMessage || "已复制到剪贴板。", "success");
    } catch (_) {
      const area = node("textarea");
      area.value = text;
      area.style.cssText = "position:fixed;opacity:0;";
      document.body.append(area);
      area.select();
      try { document.execCommand("copy"); toast(okMessage || "已复制到剪贴板。", "success"); }
      catch (__) { toast("复制失败，请手动选择文本。", "error"); }
      area.remove();
    }
  }
  function miniJob(job, { checkbox = false, checked = false, onCheck } = {}) {
    const row = node("div", "", "rp-mini-job");
    const head = node("div", "", "rp-mini-job-head");
    if (checkbox) {
      const box = input("checkbox");
      box.checked = checked;
      box.setAttribute("aria-label", "选择 " + job.title);
      box.addEventListener("change", () => onCheck?.(box.checked));
      head.append(box);
    }
    head.append(node("span", job.title, "rp-mini-job-title"));
    if (job.grade) head.append(gradeBadge(job.grade));
    const metaLine = node("p", [job.company, RP.sourceLabel(job.source), job.salary, job.score != null ? job.score + " 分" : ""]
      .filter(Boolean).join(" · "), "rp-mini-job-meta");
    row.append(head, metaLine);
    return row;
  }
  async function withBusy(task, feedbackEl, busyMessage) {
    RP.setDrawerBusy(true);
    if (feedbackEl) setFeedback(feedbackEl, busyMessage || "正在处理…");
    try { return await task(); }
    finally { RP.setDrawerBusy(false); }
  }
  function loadConfig() { return pipelineApi("/config", undefined, "GET"); }
  async function saveConfig(patch, feedbackEl, okMessage) {
    const result = await withBusy(() => pipelineApi("/config", patch), feedbackEl, "正在保存配置…");
    toast(okMessage || "流水线配置已保存。", "success");
    void RP.refresh({ silent: true });
    return result;
  }
  function modeChip(mode) {
    const chip = node("span", mode === "llm" ? "模型生成" : "启发式生成", "rp-stat-chip");
    return chip;
  }

  /* ---------- 1. 本地导入（scraping） ---------- */
  RP.registerDrawer("scraping", {
    title: "抓取 · 平台采集与本地导入", icon: "search", tone: "accent",
    render(body) {
      const token = RP.drawerToken();

      /* 平台实时采集：登录态检查 + 采集表单 + 采集记录（复用现有 /session /runs 端点） */
      const collectSection = section("平台实时采集", "search");
      const chromeSources = Object.keys(meta.chrome_sources || {});
      const canUseChrome = meta.chrome_available && chromeSources.length > 0;
      const collectEntries = sourceEntries(meta.collection_sources || meta.sources);
      const statusNames = {
        queued: "等待中", running: "采集中", succeeded: "已采集", complete: "已完成",
        partial: "部分完成", empty: "无结果", interrupted: "已中断", blocked: "需要验证", unavailable: "暂不可用",
        opening: "打开浏览器", waiting_user: "等待登录或验证", login_required: "需要登录", login_timeout: "登录超时",
        city_unsupported: "城市暂不支持"
      };
      if (!canUseChrome) {
        collectSection.append(note("本机 Chrome 连接未启用。可尝试直接采集公开搜索结果，部分平台可能需要登录。", "warn"));
      }
      const sessionWrap = node("div", "", "rp-sessions");
      const checks = [];
      for (const [key, label] of collectEntries) {
        const card = node("div", "", "rp-session");
        const head = node("div", "", "rp-session-head");
        head.append(platformLogo(key, label), node("strong", label));
        const checkBtn = button("检查登录", "rp-btn-sm rp-btn-ghost", "user-check");
        const result = node("div", "", "rp-session-result");
        const stateLabel = node("span", "未检查", "rp-session-label");
        const stateMsg = node("p", "", "rp-session-message");
        result.setAttribute("role", "status");
        stateMsg.hidden = true;
        result.append(stateLabel, stateMsg);
        const loginLink = node("a", "打开平台官网", "rp-btn rp-btn-sm rp-btn-ghost");
        loginLink.target = "_blank";
        loginLink.rel = "noopener noreferrer";
        loginLink.hidden = true;
        const copyBtn = button("复制授权地址", "rp-btn-sm rp-btn-ghost", "copy");
        copyBtn.hidden = true;
        copyBtn.addEventListener("click", async () => {
          try {
            await navigator.clipboard.writeText("chrome://inspect/#remote-debugging");
            toast("授权页地址已复制，粘贴到 Chrome 地址栏打开。", "success");
          } catch (_) {
            toast("复制失败，请手动输入 chrome://inspect/#remote-debugging", "error");
          }
        });
        const check = async () => {
          if (checkBtn.disabled) return;
          checkBtn.disabled = true;
          delete result.dataset.state;
          stateLabel.textContent = "检查中…";
          stateMsg.hidden = true;
          copyBtn.hidden = true;
          loginLink.hidden = true;
          try {
            const status = await api(`/session/${key}`, {});
            if (!alive(token, body)) return;
            result.dataset.state = status.state;
            stateLabel.textContent = status.label;
            stateMsg.textContent = status.message || "";
            stateMsg.hidden = !status.message;
            if (status.login_url) {
              loginLink.href = status.login_url;
              loginLink.hidden = false;
            }
            copyBtn.hidden = status.state !== "authorization_required_manual";
          } catch (error) {
            if (!alive(token, body)) return;
            result.dataset.state = "unavailable";
            stateLabel.textContent = "检查失败";
            stateMsg.textContent = error.message;
            stateMsg.hidden = false;
          } finally { checkBtn.disabled = false; }
        };
        checkBtn.addEventListener("click", check);
        checks.push(check);
        head.append(checkBtn);
        card.append(head, result, loginLink, copyBtn);
        sessionWrap.append(card);
      }
      const checkAll = button("检查全部平台", "rp-btn-sm rp-btn-ghost", "shield");
      checkAll.addEventListener("click", async () => {
        checkAll.disabled = true;
        try { await Promise.all(checks.map((check) => check())); } finally { checkAll.disabled = false; }
      });
      collectSection.append(sessionWrap, checkAll);

      const catalog = meta.city_catalog || {};
      const cityOptions = [["", "全部城市"]];
      const seenCity = new Set();
      for (const city of [...(catalog.hot || []), ...(catalog.scopes || []), ...Object.values(catalog.groups || {}).flat()]) {
        if (!seenCity.has(city)) { seenCity.add(city); cityOptions.push([city, city]); }
      }
      const form = node("form", "", "rp-collect-form");
      const keyword = input("text", { placeholder: "关键词，如 Python 实习", maxlength: 80, required: true });
      const city = select(cityOptions);
      const collectProfile = profileSelect();
      const limit = input("number", { min: 1, max: 30, value: 20 });
      const checksWrap = node("div", "", "rp-checks");
      const sourceBoxes = collectEntries.map(([key, label]) => {
        const wrap = node("label", "", "rp-check");
        const box = input("checkbox", { value: key });
        wrap.append(box, platformLogo(key, label), node("span", label));
        checksWrap.append(wrap);
        return box;
      });
      const localWrap = node("label", "", "rp-check");
      const localBox = input("checkbox", {});
      localWrap.append(localBox, node("span", canUseChrome ? "使用本机 Chrome 登录态（推荐）" : "使用 BOSS 本地登录态"));
      localWrap.hidden = !canUseChrome && !meta.boss_local;
      localBox.checked = Boolean(canUseChrome || meta.boss_local);
      const submit = button("启动采集", "rp-btn-primary", "play");
      submit.type = "submit";
      const collectFeedback = feedback();
      collectFeedback.setAttribute("role", "status");
      form.append(
        field("关键词", keyword), field("城市", city), field("归入求职方向", collectProfile),
        field("每平台上限", limit), checksWrap, localWrap, submit, collectFeedback
      );
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const term = keyword.value.trim();
        if (!term) { setFeedback(collectFeedback, "请输入采集关键词。", "error"); keyword.focus(); return; }
        const sources = sourceBoxes.filter((box) => box.checked).map((box) => box.value);
        if (!sources.length) { setFeedback(collectFeedback, "请至少选择一个采集平台。", "error"); return; }
        submit.disabled = true;
        try {
          const run = await withBusy(() => api("/runs", {
            keyword: term, city: city.value, limit: Number(limit.value) || 20,
            sources, profile: collectProfile.value,
            boss_local: Boolean(!canUseChrome && meta.boss_local && sources.includes("boss") && localBox.checked),
            chrome_local: Boolean(canUseChrome && localBox.checked && chromeSources.some((source) => sources.includes(source)))
          }), collectFeedback, "正在启动采集…");
          if (!alive(token, body)) return;
          setFeedback(collectFeedback, "已启动采集，可在下方查看各平台进度。", "success");
          openRun = run.id;
          history.open = true;
          void loadRuns();
        } catch (error) {
          if (alive(token, body)) setFeedback(collectFeedback, error.message, "error");
        } finally { submit.disabled = false; }
      });
      collectSection.append(form);

      const history = node("details", "", "rp-run-history");
      const historyHead = node("summary", "", "rp-run-history-head");
      const historyCount = node("span", "", "rp-run-history-count");
      const runsWrap = node("div", "正在读取采集记录…", "rp-runs");
      historyHead.append(node("span", "采集记录"), historyCount);
      history.append(historyHead, runsWrap);
      let runPoll = null;
      let runRequest = 0;
      let lastRuns = "";
      let openRun = null;
      const runCard = (run) => {
        const card = node("details", "", "rp-run");
        card.dataset.state = run.status;
        card.dataset.runId = run.id;
        const head = node("summary", "", "rp-run-head");
        const label = node("span", "", "rp-run-label");
        label.append(
          node("strong", [run.keyword, run.city].filter(Boolean).join(" · ") || "采集任务"),
          node("span", new Date(run.started_at * 1000).toLocaleString("zh-CN"), "rp-run-date")
        );
        head.append(
          label,
          node("span", statusNames[run.status] || run.status, "rp-run-state")
        );
        card.append(head);
        for (const [source, item] of Object.entries(run.progress || {})) {
          const line = node("div", "", "rp-run-source");
          const itemStatus = run.status === "interrupted" && ["queued", "running", "opening", "waiting_user"].includes(item.status)
            ? "interrupted" : item.status;
          line.append(node("strong", sourceLabel((meta.collection_sources || {})[source]) || source));
          const loginUrl = ["waiting_user", "login_required", "login_timeout"].includes(itemStatus) && item.login_url;
          if (loginUrl || item.search_url) {
            const link = node("a", loginUrl ? "去登录 ↗" : "原站 ↗");
            link.href = loginUrl || item.search_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            line.append(link);
          }
          const message = node("p", itemStatus === "interrupted" ? statusNames[itemStatus] : (item.message || statusNames[itemStatus] || ""));
          message.dataset.state = itemStatus;
          line.append(message);
          card.append(line);
        }
        return card;
      };
      async function loadRuns() {
        clearTimeout(runPoll);
        const request = ++runRequest;
        try {
          const data = await api("/runs");
          if (request !== runRequest || !alive(token, body)) return;
          const items = data.items || [];
          const snapshot = JSON.stringify(items);
          if (snapshot !== lastRuns || openRun) {
            const expanded = new Set([...runsWrap.querySelectorAll(".rp-run[open]")].map(card => card.dataset.runId));
            const focused = document.activeElement?.closest(".rp-run");
            const cards = items.map(run => {
              const card = runCard(run);
              card.open = run.id === openRun || expanded.has(run.id);
              if (run.id === openRun) openRun = null;
              return card;
            });
            runsWrap.replaceChildren(...(cards.length ? cards : [node("p", "暂无采集记录。", "rp-hint")]));
            historyCount.textContent = `${items.length} 条`;
            lastRuns = snapshot;
            if (focused && !focused.isConnected) {
              cards.find(card => card.dataset.runId === focused.dataset.runId)?.firstElementChild.focus({ preventScroll: true });
            }
          }
          if (items.some((run) => run.status === "running")) runPoll = setTimeout(loadRuns, 3000);
          else void RP.refresh({ silent: true });
        } catch (error) {
          if (request === runRequest && alive(token, body)) {
            if (!lastRuns) runsWrap.replaceChildren(node("p", "暂时无法读取采集记录，正在重试。", "rp-hint"));
            runPoll = setTimeout(loadRuns, 5000);
          }
        }
      }
      collectSection.append(history);
      void loadRuns();

      const csvSection = section("导入 CSV", "upload");
      const csvProfile = profileSelect();
      const csvFile = input("file", { accept: ".csv,text/csv" });
      const csvFeedback = feedback();
      const csvBtn = button("导入 CSV 文件", "", "upload");
      csvBtn.addEventListener("click", async () => {
        const file = csvFile.files[0];
        if (!file) { setFeedback(csvFeedback, "请先选择 CSV 文件（不超过 2 MB）。", "error"); return; }
        const data = new FormData();
        data.append("file", file);
        data.append("profile", csvProfile.value);
        csvBtn.disabled = true;
        try {
          const result = await withBusy(() => api("/import", data), csvFeedback, "正在读取 CSV…");
          if (!alive(token, body)) return;
          setFeedback(csvFeedback, `已保存 ${result.count} 条记录。`, "success");
          toast(`CSV 导入完成：${result.count} 条。`, "success");
          csvFile.value = "";
          void RP.refresh({ silent: true });
        } catch (error) {
          if (alive(token, body)) setFeedback(csvFeedback, error.message, "error");
        } finally { csvBtn.disabled = false; }
      });
      csvSection.append(
        node("p", "表头需包含链接列（url / job_link），以及标题或描述列；兼容常见平台导出格式。", "rp-hint"),
        field("归入求职方向", csvProfile), field("CSV 文件", csvFile), csvBtn, csvFeedback
      );

      const htmlSection = section("导入已保存的搜索页", "file-text");
      const htmlSource = select(sourceEntries(meta.sources));
      const htmlProfile = profileSelect();
      const htmlFile = input("file", { accept: ".html,.htm,text/html" });
      const htmlFeedback = feedback();
      const htmlBtn = button("读取页面岗位", "", "upload");
      htmlBtn.addEventListener("click", async () => {
        const file = htmlFile.files[0];
        if (!file) { setFeedback(htmlFeedback, "请先选择浏览器保存的 HTML 文件（不超过 5 MB）。", "error"); return; }
        const data = new FormData();
        data.append("file", file);
        data.append("source", htmlSource.value);
        data.append("profile", htmlProfile.value);
        htmlBtn.disabled = true;
        try {
          const result = await withBusy(() => api("/import-html", data), htmlFeedback, "正在读取页面…");
          if (!alive(token, body)) return;
          setFeedback(htmlFeedback, `已保存 ${result.count} 条记录。`, "success");
          toast(`页面导入完成：${result.count} 条。`, "success");
          htmlFile.value = "";
          void RP.refresh({ silent: true });
        } catch (error) {
          if (alive(token, body)) setFeedback(htmlFeedback, error.message, "error");
        } finally { htmlBtn.disabled = false; }
      });
      htmlSection.append(
        node("p", "在原站打开搜索结果后，用浏览器「网页，仅 HTML」保存，再上传该文件；读取在本地完成。", "rp-hint"),
        field("来源平台", htmlSource), field("归入求职方向", htmlProfile), field("HTML 文件", htmlFile), htmlBtn, htmlFeedback
      );

      const files = node("details", "", "rp-import-files");
      files.append(node("summary", "手动导入文件"), csvSection, htmlSection);
      body.append(collectSection, files);
    }
  });

  /* ---------- 2. 规则清洗（cleaning，复用现有 cleaning 引擎） ---------- */
  RP.registerDrawer("cleaning", {
    title: "规则清洗配置", icon: "filter", tone: "brass",
    render(body) {
      const token = RP.drawerToken();
      const form = node("form", "", "rp-form rp-clean-form");
      const profile = profileSelect();
      const profileRow = node("div", "", "rp-select-row rp-clean-profile");
      profile.setAttribute("aria-label", "清洗方向");
      profileRow.append(node("strong", "清洗方向"), profile);
      const fields = node("fieldset");
      const status = feedback();
      status.setAttribute("role", "status");

      function ruleGroup(title, iconName, tone) {
        const group = section(title);
        group.classList.add("rp-clean-group");
        group.dataset.tone = tone;
        group.firstElementChild.prepend(tile(iconName, tone, true));
        return group;
      }

      const pay = ruleGroup("薪资与经验", "banknote", "success");
      const salaryGrid = node("div", "", "rp-panel-grid rp-clean-salary-range");
      const minSalary = input("number", { min: "0.01", max: "1000", step: "0.01", placeholder: "不限" });
      const maxSalary = input("number", { min: "0.01", max: "1000", step: "0.01", placeholder: "不限" });
      const expMax = input("number", { min: "1", max: "50", step: "1", placeholder: "不限" });
      salaryGrid.append(field("最低月薪（K）", minSalary), field("最高月薪（K）", maxSalary));
      const dailyPay = node("div", "", "rp-daily-pay");
      dailyPay.hidden = true;
      const dailyGrid = node("div", "", "rp-panel-grid rp-clean-salary-range");
      const minDaily = input("number", { min: "0.01", max: "100000", step: "0.01", placeholder: "不限" });
      const maxDaily = input("number", { min: "0.01", max: "100000", step: "0.01", placeholder: "不限" });
      dailyGrid.append(field("最低日薪（元/天）", minDaily), field("最高日薪（元/天）", maxDaily));
      const payEstimate = node("p", "", "rp-pay-estimate");
      payEstimate.setAttribute("aria-live", "polite");
      const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2, minimumFractionDigits: 0 });
      let workdaysPerMonth = 22;
      function renderPayEstimate() {
        const lower = minDaily.value ? money.format(Number(minDaily.value) * workdaysPerMonth) : "";
        const upper = maxDaily.value ? money.format(Number(maxDaily.value) * workdaysPerMonth) : "";
        let range = "";
        if (lower && upper) range = lower === upper ? lower : `${lower}–${upper}`;
        else if (lower) range = `${lower} 起`;
        else if (upper) range = `${upper} 以内`;
        payEstimate.textContent = range ? `月薪约 ${range}（每月 ${workdaysPerMonth} 个工作日）`
          : `月薪按每月 ${workdaysPerMonth} 个工作日折算。`;
      }
      dailyGrid.addEventListener("input", renderPayEstimate);
      dailyPay.append(dailyGrid, payEstimate);
      const experience = node("div", "", "rp-clean-experience");
      experience.append(field("经验上限（年）", expMax), node("p", "岗位要求的最低经验达到上限时淘汰。", "rp-hint"));
      pay.append(salaryGrid, dailyPay, experience);

      const splitTerms = (value) => value.split(/[,，、\n]+/).map((term) => term.trim()).filter(Boolean);
      function termsEditor(key, label, placeholder) {
        const wrap = node("div", "", "rp-terms");
        wrap.dataset.terms = key;
        const row = node("div", "", "rp-terms-input");
        const entry = input("text", { id: `rp-rule-${key}`, maxlength: "2500", placeholder });
        const add = button("添加", "rp-btn-sm rp-btn-ghost", "plus");
        add.setAttribute("aria-label", `添加${label}`);
        const title = node("label", label);
        title.htmlFor = entry.id;
        const valuesField = node("div", "", "rp-terms-values");
        const chips = node("div", "", "rp-chips");
        const paint = (values) => {
          chips.replaceChildren(...values.map((value) => {
            const chip = node("button", value + " ×", "rp-chip-x");
            chip.type = "button";
            chip.dataset.value = value;
            chip.setAttribute("aria-label", "移除 " + value);
            chip.addEventListener("click", () => { chip.remove(); resetPreview(); entry.focus(); });
            return chip;
          }));
        };
        const commit = () => {
          const values = [...new Set([
            ...[...chips.querySelectorAll("[data-value]")].map((chip) => chip.dataset.value),
            ...splitTerms(entry.value)
          ])];
          paint(values);
          entry.value = "";
          resetPreview();
          entry.focus();
        };
        add.addEventListener("click", commit);
        entry.addEventListener("keydown", (event) => {
          if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); commit(); }
        });
        valuesField.append(chips, entry);
        row.append(valuesField, add);
        wrap.append(title, row);
        wrap._paint = paint;
        wrap._read = () => [...new Set([
          ...[...chips.querySelectorAll("[data-value]")].map((chip) => chip.dataset.value),
          ...splitTerms(entry.value)
        ])];
        return wrap;
      }
      const cities = termsEditor("cities", "目标城市", "输入城市后回车添加");
      const requireEdu = termsEditor("require_education", "最低学历", "例如 本科");
      const excludeEdu = termsEditor("exclude_education", "要排除的学历", "例如 博士");
      const degreeOptions = node("datalist");
      degreeOptions.id = "rp-degree-options";
      for (const degree of ["初中", "中专", "高中", "大专", "本科", "硕士", "博士"]) {
        degreeOptions.append(new Option(degree));
      }
      for (const editor of [requireEdu, excludeEdu]) {
        editor.querySelector("input").setAttribute("list", degreeOptions.id);
      }
      const qualifications = ruleGroup("城市与学历", "graduation", "info");
      const educationMode = select([["none", "不限岗位学历"], ["require", "按最低学历筛选"], ["exclude", "排除指定学历要求"]], "none");
      const educationField = field("岗位学历要求", educationMode);
      educationField.firstElementChild.id = "rp-education-label";
      educationMode.setAttribute("aria-labelledby", "rp-education-label");
      const educationHelp = node("p", "", "rp-education-help");
      educationHelp.id = "rp-education-help";
      educationMode.setAttribute("aria-describedby", educationHelp.id);
      const educationDescriptions = {
        none: "这一项看的是招聘方写的学历要求。未注明学历的岗位会保留。",
        require: "例如选「本科」，要求为「大专」的岗位会被淘汰。选择多项时，以最低的一项为门槛。",
        exclude: "例如选「博士」，学历要求包含「博士」的岗位会被淘汰，即使同时列出了其他学历。"
      };
      function renderEducationMode() {
        requireEdu.hidden = educationMode.value !== "require";
        excludeEdu.hidden = educationMode.value !== "exclude";
        educationHelp.textContent = educationDescriptions[educationMode.value];
      }
      educationMode.addEventListener("change", renderEducationMode);
      renderEducationMode();
      qualifications.append(cities, educationField, educationHelp, requireEdu, excludeEdu, degreeOptions);

      const titleExcl = node("textarea");
      titleExcl.rows = 2; titleExcl.maxLength = 4100; titleExcl.placeholder = "例如 电话销售、保险代理";
      const companyExcl = node("textarea");
      companyExcl.rows = 2; companyExcl.maxLength = 4100; companyExcl.placeholder = "用逗号、顿号或换行分隔";
      const exclusions = node("details", "", "rp-panel-section rp-clean-group rp-clean-exclusions");
      exclusions.dataset.tone = "brass";
      const exclusionHead = node("summary");
      const exclusionCount = node("small", "", "rp-clean-exclusion-count");
      exclusionHead.append(tile("filter", "brass", true), node("strong", "排除词"), exclusionCount, icon("chevron-down"));
      const exclusionFields = node("div", "", "rp-panel-grid rp-clean-exclusion-fields");
      exclusionFields.append(field("岗位标题排除词", titleExcl), field("公司排除词", companyExcl));
      exclusions.append(exclusionHead, exclusionFields);
      function renderExclusionCount() {
        const count = splitTerms(titleExcl.value).length + splitTerms(companyExcl.value).length;
        exclusionCount.textContent = count ? `${count} 项` : "";
        exclusionCount.hidden = !count;
      }
      exclusionFields.addEventListener("input", renderExclusionCount);
      renderExclusionCount();

      const auto = input("checkbox");
      const autoLabel = node("label", "", "rp-inline-check rp-clean-auto");
      autoLabel.append(auto, document.createTextNode("新采集或导入的岗位自动执行硬规则"));

      /* AI 初筛规则 */
      const scout = ruleGroup("AI 初筛规则", "sparkles", "accent");
      const scoutHead = node("div", "", "rp-scout-head");
      const scoutAdd = button("添加规则", "rp-btn-sm rp-btn-ghost", "plus");
      scoutHead.append(scout.firstElementChild, scoutAdd);
      const exampleNotice = node("div", "", "rp-scout-samples");
      exampleNotice.hidden = true;
      const exampleHead = node("div", "", "rp-scout-head");
      const exampleEnable = button("使用示例", "rp-btn-sm rp-btn-ghost");
      const exampleList = node("div", "", "rp-scout-examples");
      exampleHead.append(node("strong", "规则示例"), exampleEnable);
      exampleNotice.append(exampleHead, exampleList);
      const scoutList = node("div", "", "rp-scout-list");
      let examples = [];
      const conditionLabel = (condition) => condition === "must" ? "必须包含" : "绝不包含";
      function scoutExample(rule) {
        const example = node("details", "", "rp-scout-example");
        const summary = node("summary");
        summary.append(node("strong", rule.keyword), node("small", conditionLabel(rule.condition)));
        example.append(summary, node("p", rule.desc));
        return example;
      }
      function readScout(row) {
        return {
          keyword: row.querySelector("input").value.trim(),
          condition: row.querySelector("select").value,
          desc: row.querySelector("textarea").value.trim()
        };
      }
      function scoutRow(rule = { keyword: "", condition: "never", desc: "" }) {
        const row = node("details", "", "rp-scout-row");
        if (rule.legacy) row.dataset.legacy = rule.legacy;
        const heading = node("summary");
        const name = node("strong", rule.keyword || "新规则");
        const constraint = node("small", conditionLabel(rule.condition));
        heading.append(name, constraint);
        const editor = node("div", "", "rp-scout-editor");
        const controls = node("div", "", "rp-scout-controls");
        const keyword = input("text", { maxlength: "240", placeholder: "规则词，例如 单休" });
        keyword.value = rule.keyword;
        const condition = select([["must", "必须包含"], ["never", "绝不包含"]], rule.condition);
        controls.append(field("规则词", keyword), field("判定条件", condition));
        const desc = node("textarea");
        desc.rows = 2; desc.maxLength = 600; desc.value = rule.desc;
        desc.placeholder = "判定标准：命中/排除的具体依据";
        const actions = node("div", "", "rp-scout-actions");
        const generate = button("AI 生成标准", "rp-btn-sm", "sparkles");
        const remove = button("删除规则", "rp-btn-sm rp-btn-ghost rp-scout-remove", "trash");
        const rowStatus = feedback();
        row.addEventListener("input", () => {
          delete row.dataset.legacy;
          name.textContent = keyword.value.trim() || "新规则";
          constraint.textContent = conditionLabel(condition.value);
        });
        remove.addEventListener("click", () => { row.remove(); resetPreview(); scoutAdd.focus(); });
        generate.addEventListener("click", async () => {
          const current = readScout(row);
          if (!current.keyword) { setFeedback(rowStatus, "请先填写规则词。", "error"); keyword.focus(); return; }
          generate.disabled = true;
          setFeedback(rowStatus, "正在生成…");
          try {
            const result = await api("/cleaning/describe", current);
            const latest = readScout(row);
            if (row.isConnected && Object.keys(current).every((key) => current[key] === latest[key])) {
              desc.value = result.desc;
              delete row.dataset.legacy;
              resetPreview();
              setFeedback(rowStatus, "");
            } else setFeedback(rowStatus, "生成期间规则已变更，请重新生成。", "error");
          } catch (error) {
            setFeedback(rowStatus, error.message, "error");
          } finally { generate.disabled = false; }
        });
        actions.append(generate, remove);
        editor.append(controls, field("判定标准", desc), actions, rowStatus);
        row.append(heading, editor);
        return row;
      }
      scoutAdd.addEventListener("click", () => {
        if (scoutList.children.length >= 24) { setFeedback(status, "每个方向最多保存 24 条 AI 初筛规则。", "error"); return; }
        exampleNotice.hidden = true;
        const row = scoutRow();
        row.open = true;
        scoutList.append(row);
        row.querySelector("input").focus();
      });
      exampleEnable.addEventListener("click", () => {
        scoutList.replaceChildren(...examples.map(scoutRow));
        exampleNotice.hidden = true;
        resetPreview();
        const first = scoutList.firstElementChild;
        if (first) { first.open = true; first.querySelector("input").focus(); }
      });
      scout.append(scoutHead, exampleNotice, scoutList);

      /* 操作与预览 */
      const actions = node("div", "", "rp-clean-actions");
      const saveBtn = button("保存规则", "rp-btn-primary", "check");
      const previewBtn = button("预览现有岗位", "", "eye");
      previewBtn.type = "submit";
      const applyBtn = button("应用到现有岗位", "rp-btn-primary", "check");
      applyBtn.disabled = true;
      applyBtn.hidden = true;
      const actionRow = node("div", "", "rp-panel-actions");
      actionRow.append(previewBtn, saveBtn, applyBtn);
      const previewList = node("div", "", "rp-rule-preview");
      previewList.hidden = true;
      actions.append(status, actionRow);

      fields.append(pay, qualifications, exclusions, scout, autoLabel, previewList, actions);
      form.append(profileRow, fields);
      body.append(form);

      let previewToken = "";
      let loadedProfile = "";
      let loadSeq = 0;
      const CLEAN_NAMES = { unreviewed: "未清洗", passed: "通过", rejected: "淘汰", review: "待核对", released: "已放行" };
      function resetPreview() {
        previewToken = "";
        applyBtn.disabled = true;
        applyBtn.hidden = true;
        saveBtn.classList.add("rp-btn-primary");
        previewList.hidden = true;
        previewList.replaceChildren();
      }
      function showRules(rules) {
        titleExcl.value = (rules.title_exclusions || []).join("、");
        companyExcl.value = (rules.company_exclusions || []).join("、");
        renderExclusionCount();
        cities._paint(rules.cities || []);
        requireEdu._paint(rules.require_education || []);
        excludeEdu._paint(rules.exclude_education || []);
        educationMode.value = rules.require_education?.length ? "require" : rules.exclude_education?.length ? "exclude" : "none";
        renderEducationMode();
        minSalary.value = rules.min_salary_k ?? "";
        maxSalary.value = rules.max_salary_k ?? "";
        expMax.value = rules.experience_years_max ?? "";
        const hasDailyBounds = rules.min_daily_salary != null || rules.max_daily_salary != null;
        const fromLegacyMonthly = (value) => value == null ? "" : (value * 1000 / workdaysPerMonth).toFixed(2);
        minDaily.value = hasDailyBounds ? (rules.min_daily_salary ?? "") : fromLegacyMonthly(rules.min_salary_k);
        maxDaily.value = hasDailyBounds ? (rules.max_daily_salary ?? "") : fromLegacyMonthly(rules.max_salary_k);
        const stored = [
          ...(rules.ai_scout_rules || []),
          ...(rules.semantic_required || []).map((keyword) => ({ keyword, condition: "must", desc: "", legacy: "semantic_required" })),
          ...(rules.semantic_excluded || []).map((keyword) => ({ keyword, condition: "never", desc: "", legacy: "semantic_excluded" }))
        ];
        const showExamples = !stored.length && examples.length > 0;
        exampleNotice.hidden = !showExamples;
        exampleList.replaceChildren(...(showExamples ? examples.map(scoutExample) : []));
        scoutList.replaceChildren(...stored.map(scoutRow));
        auto.checked = Boolean(rules.auto);
        const daily = profile.value === "internship";
        dailyPay.hidden = !daily;
        salaryGrid.hidden = daily;
        minSalary.disabled = maxSalary.disabled = daily;
        minDaily.disabled = maxDaily.disabled = !daily;
        if (daily) renderPayEstimate();
      }
      function readRules() {
        const number = (el) => !el.disabled && el.value ? Number(el.value) : null;
        const rows = [...scoutList.children];
        const legacy = (name) => rows.filter((row) => row.dataset.legacy === name).map((row) => readScout(row).keyword);
        return {
          cities: cities._read(),
          require_education: educationMode.value === "require" ? requireEdu._read() : [],
          exclude_education: educationMode.value === "exclude" ? excludeEdu._read() : [],
          title_exclusions: splitTerms(titleExcl.value), company_exclusions: splitTerms(companyExcl.value),
          min_salary_k: number(minSalary), max_salary_k: number(maxSalary),
          experience_years_max: number(expMax),
          min_daily_salary: number(minDaily), max_daily_salary: number(maxDaily),
          ai_scout_rules: rows.filter((row) => !row.dataset.legacy).map(readScout).filter((rule) => rule.keyword),
          semantic_required: legacy("semantic_required"), semantic_excluded: legacy("semantic_excluded"),
          auto: auto.checked
        };
      }
      async function loadRules() {
        const target = profile.value;
        const sequence = ++loadSeq;
        loadedProfile = "";
        resetPreview();
        fields.disabled = true;
        setFeedback(status, "正在读取规则…");
        try {
          const data = await api("/cleaning?profile=" + target);
          if (sequence !== loadSeq || !alive(token, body)) return;
          workdaysPerMonth = data.internship_workdays_per_month || workdaysPerMonth;
          examples = (data.examples || []).slice(0, 2);
          showRules(data.rules);
          loadedProfile = target;
          setFeedback(status, "");
        } catch (error) {
          if (sequence === loadSeq) setFeedback(status, error.message, "error");
        } finally {
          if (sequence === loadSeq) fields.disabled = loadedProfile !== target;
        }
      }
      async function runAction(action) {
        if (loadedProfile !== profile.value || !form.reportValidity() || (action === "apply" && !previewToken)) return;
        const payload = { profile: loadedProfile, rules: readRules(), token: previewToken };
        resetPreview();
        fields.disabled = true;
        profile.disabled = true;
        try {
          const result = await withBusy(() => api("/cleaning/" + action, payload), status, "正在处理…");
          if (!alive(token, body)) return;
          if (action === "preview") {
            previewToken = result.token;
            applyBtn.disabled = false;
            applyBtn.hidden = false;
            saveBtn.classList.remove("rp-btn-primary");
            previewList.replaceChildren(...Object.entries(result.samples || {}).map(([cleanStatus, samples]) => {
              const group = node("div", "", "rp-rule-preview-group");
              group.dataset.status = cleanStatus;
              group.append(node("strong", `${CLEAN_NAMES[cleanStatus] || cleanStatus} ${result.counts?.[cleanStatus] ?? 0} 条`));
              for (const sample of samples) {
                group.append(node("p", [sample.title, RP.sourceLabel(sample.source), sample.reason].filter(Boolean).join(" · ")));
              }
              return group;
            }));
            previewList.hidden = false;
            setFeedback(status, "预览完成，确认后应用到该方向岗位。", "success");
            previewList.scrollIntoView({ block: "nearest" });
          } else {
            showRules(result.rules);
            setFeedback(status, action === "save" ? "规则已保存。" : "已应用清洗规则。", "success");
            void RP.refresh({ silent: true });
          }
        } catch (error) {
          if (alive(token, body)) setFeedback(status, error.message, "error");
        } finally {
          fields.disabled = false;
          profile.disabled = false;
        }
      }
      form.addEventListener("submit", (event) => { event.preventDefault(); void runAction("preview"); });
      form.addEventListener("input", resetPreview);
      educationMode.addEventListener("change", resetPreview);
      saveBtn.addEventListener("click", () => void runAction("save"));
      applyBtn.addEventListener("click", () => void runAction("apply"));
      profile.addEventListener("change", () => void loadRules());
      void loadRules();
    }
  });

  /* ---------- AI 评估 ---------- */
  RP.registerDrawer("evaluating", {
    title: "AI 评估", icon: "sparkles", tone: "info",
    render(body) {
      const token = RP.drawerToken();
      const readiness = note("正在读取模型与评估配置…");
      const form = node("form", "", "rp-form");
      const settingsSection = section("八维评估权重", "sliders");
      const weights = node("div", "", "rp-weights");
      const weightInputs = new Map();
      for (const [key, label] of Object.entries(DIMENSION_LABELS)) {
        const number = input("number", { min: "0", max: "5", step: "0.1", required: "required" });
        weightInputs.set(key, number);
        const wrap = node("label");
        wrap.append(document.createTextNode(label), number);
        weights.append(wrap);
      }
      const heuristic = input("checkbox");
      const heuristicLabel = node("label", "", "rp-inline-check");
      heuristicLabel.append(heuristic, document.createTextNode("使用启发式评估（按规则打分和诊断）"));
      const saveBtn = button("保存评估配置", "", "check");
      saveBtn.type = "submit";
      const settingsFeedback = feedback();
      settingsSection.append(
        node("p", "权重 0-5：3 为中性缺失，4 为明确正面，5 极罕见；总分只展示不分流，分流只看 A-F 评级。", "rp-hint"),
        weights, heuristicLabel, saveBtn, settingsFeedback
      );
      form.append(settingsSection);

      const runSection = section("批量评估", "play");
      runSection.append(node("p", "先对清洗通过和待重评岗位做八维评级。达到精投阈值的岗位自动生成深评诊断，其余进入海投。初评解析失败时保留待重试状态。", "rp-hint"));
      const runFeedback = feedback();
      const runBtn = button("运行 AI 评估", "rp-btn-primary", "play");
      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        try {
          const result = await withBusy(() => RP.runStage("evaluate"), runFeedback, "正在评级并诊断精投岗位…");
          if (!alive(token, body)) return;
          const message = RP.stageResultMessage(result, "AI 评估");
          setFeedback(runFeedback, message, "success");
          toast(message, "success");
          await RP.refresh({ silent: true });
          if (!alive(token, body)) return;
          paintStats();
          paintList();
        } catch (error) {
          if (alive(token, body)) setFeedback(runFeedback, error.message, "error");
        } finally { runBtn.disabled = false; }
      });
      const stats = node("div", "", "rp-stat-chips");
      function paintStats() {
        const grades = { A: 0, B: 0, C: 0, D: 0, F: 0 };
        let scored = 0;
        let custom = 0;
        let mass = 0;
        for (const job of state.jobs) {
          if (job.score != null) scored += 1;
          if (job.grade) grades[job.grade] = (grades[job.grade] || 0) + 1;
          if (job.track === "mass") mass += 1;
          else if (job.stage !== "collected" && job.stage !== "cleaned") custom += 1;
        }
        const chips = [node("span", "", "rp-stat-chip")];
        chips[0].append(document.createTextNode("已评分 "), node("b", String(scored)));
        for (const [grade, count] of Object.entries(grades)) {
          if (!count) continue;
          const chip = node("span", "", "rp-stat-chip");
          chip.append(document.createTextNode(grade + " 级 "), node("b", String(count)));
          chips.push(chip);
        }
        const trackChip = node("span", "", "rp-stat-chip");
        trackChip.append(document.createTextNode("精投 "), node("b", String(custom)), document.createTextNode(" · 海投 "), node("b", String(mass)));
        chips.push(trackChip);
        stats.replaceChildren(...(scored ? chips : [node("span", "暂无已评分岗位", "rp-stat-chip")]));
      }
      paintStats();
      runSection.append(runBtn, runFeedback, stats);
      body.append(readiness, form, runSection);
      const paintList = appendEvaluationDetails(body, token);

      let loadSeq = 0;
      function showConfig(data) {
        const settings = data.settings || {};
        for (const [key, number] of weightInputs) number.value = settings.evaluation_weights?.[key] ?? 1;
        heuristic.checked = Boolean(settings.heuristic_mode);
        if (settings.heuristic_mode) {
          readiness.dataset.tone = "warning";
          readiness.textContent = "当前使用启发式评估。";
        } else if (data.llm_configured) {
          readiness.dataset.tone = "success";
          readiness.textContent = "对话模型已就绪，可运行八维评级与精投诊断。";
        } else if (data.heuristic_active) {
          readiness.dataset.tone = "warning";
          readiness.replaceChildren(document.createTextNode("启发式模式：对话模型未配置，初评使用确定性启发式打分。前往 "),
            (() => { const a = node("a", "系统配置"); a.href = meta.settings_url; return a; })(),
            document.createTextNode(" 填写模型。"));
        } else {
          readiness.dataset.tone = "danger";
          readiness.textContent = "模型未配置且启发式回退已关闭：初评无法执行，请开启启发式或先配置模型。";
        }
      }
      async function loadSettings() {
        const sequence = ++loadSeq;
        saveBtn.disabled = true;
        try {
          const data = await loadConfig();
          if (sequence !== loadSeq || !alive(token, body)) return;
          showConfig(data);
        } catch (error) {
          if (sequence === loadSeq) { readiness.dataset.tone = "danger"; readiness.textContent = error.message; }
        } finally {
          if (sequence === loadSeq) saveBtn.disabled = false;
        }
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const patch = {
          heuristic_mode: heuristic.checked,
          evaluation_weights: Object.fromEntries([...weightInputs].map(([key, number]) => [key, Number(number.value)]))
        };
        saveBtn.disabled = true;
        try {
          const data = await saveConfig(patch, settingsFeedback, "评估配置已保存。");
          if (!alive(token, body)) return;
          showConfig(data);
          setFeedback(settingsFeedback, "评估配置已保存。", "success");
        } catch (error) {
          if (alive(token, body)) setFeedback(settingsFeedback, error.message, "error");
        } finally { saveBtn.disabled = false; }
      });
      void loadSettings();
    }
  });

  function appendEvaluationDetails(body, token) {
    const gate = section("分流阈值与投递白名单", "target");
    const threshold = select([["A", "A 级（仅 A 走精投）"], ["B", "B 级（A/B 走精投，默认）"], ["C", "C 级（A/B/C 走精投）"]], "B");
    const gradeBoxes = new Map();
    const gradeRow = node("div", "", "rp-stat-chips");
    for (const grade of GRADE_OPTIONS) {
      const box = input("checkbox");
      gradeBoxes.set(grade, box);
      const label = node("label", "", "rp-inline-check");
      label.append(box, document.createTextNode(grade + " 级"));
      gradeRow.append(label);
    }
    const gateFeedback = feedback();
    const gateSave = button("保存阈值配置", "", "check");
    gateSave.addEventListener("click", async () => {
      const autoDeliver = [...gradeBoxes].filter(([, box]) => box.checked).map(([grade]) => grade);
      if (!autoDeliver.length) { setFeedback(gateFeedback, "自动投递等级白名单不能为空。", "error"); return; }
      gateSave.disabled = true;
      try {
        await saveConfig({ threshold: threshold.value, auto_deliver_grades: autoDeliver }, gateFeedback, "阈值配置已保存。");
        if (alive(token, body)) setFeedback(gateFeedback, "阈值配置已保存。", "success");
      } catch (error) {
        if (alive(token, body)) setFeedback(gateFeedback, error.message, "error");
      } finally { gateSave.disabled = false; }
    });
    gate.append(field("精投分流阈值", threshold),
      node("p", "自动投递等级白名单（海投轨）：白名单外评级与解析失败件一律拦截进审批。", "rp-hint"),
      gradeRow, gateSave, gateFeedback);

    const listSection = section("深评记录", "eye");
    const list = node("div", "", "rp-mini-list");
    const detail = node("div", "", "rp-deep-keys");
    function paintList() {
      const jobs = state.jobs.filter(job => job.hasDeep).slice(0, 8);
      if (!jobs.length) {
        list.replaceChildren(emptyBlock("暂无深评记录", "运行 AI 评估后，可在这里查看精投岗位的诊断。"));
        return;
      }
      list.replaceChildren(...jobs.map((job) => {
        const row = miniJob(job);
        const actions = node("div", "", "rp-mini-job-actions");
        const view = button("查看七键分析", "rp-btn-sm rp-btn-ghost", "eye");
        view.addEventListener("click", async () => {
          view.disabled = true;
          detail.replaceChildren(node("p", "正在读取深评结果…", "rp-hint"));
          try {
            const payload = await RP.fetchJobPayload(job);
            if (!alive(token, body)) return;
            const deep = payloadOf(payload, "deep_payload", "deep");
            detail.replaceChildren();
            if (!deep) {
              detail.append(note("该岗位还没有深评结果，可能仍在队列中。", "warning"));
              return;
            }
            for (const [key, label] of DEEP_KEYS) {
              const value = deep[key];
              if (value == null || value === "") continue;
              const fold = node("details", "", "rp-deep-key");
              fold.append(node("summary", label));
              const doc = node("div", "", "rp-doc");
              RP.renderDoc(doc, RP.payloadText(value));
              fold.append(doc);
              detail.append(fold);
            }
            if (!detail.childNodes.length) detail.append(note("深评结果为空。", "warning"));
          } catch (error) {
            if (alive(token, body)) detail.replaceChildren(note(error.message, "danger"));
          } finally { view.disabled = false; }
        });
        actions.append(view);
        row.append(actions);
        return row;
      }));
    }
    paintList();
    listSection.append(list, detail);
    body.append(gate, listSection);

    loadConfig().then((data) => {
      if (!alive(token, body)) return;
      threshold.value = data.settings?.threshold || "B";
      const allowed = data.settings?.auto_deliver_grades || ["C", "D", "F"];
      for (const [grade, box] of gradeBoxes) box.checked = allowed.includes(grade);
    }).catch(() => {});
    return paintList;
  }

  /* ---------- 5. 简历改写（rewriting，基准简历 + 对比） ---------- */
  RP.registerDrawer("rewriting", {
    title: "简历改写 · 定制面板", icon: "pen", tone: "accent",
    render(body, ctx) {
      const token = RP.drawerToken();
      body.append(note("以基准简历 + 岗位 JD 生成定向改写稿。真实性边界：不虚构经历、不注入原简历没有的技术、经历一段不裁、无量化不编数据。", "info"));

      const baselineSection = section("基准简历", "file-text");
      const baselineSelect = select([["", "正在读取简历库…"]]);
      const baselineInfo = node("p", "", "rp-hint");
      const baselineFeedback = feedback();
      baselineSelect.addEventListener("change", async () => {
        if (!baselineSelect.value) return;
        baselineSelect.disabled = true;
        try {
          await saveConfig({ baseline_resume_id: baselineSelect.value }, baselineFeedback, "基准简历已切换。");
          if (alive(token, body)) void loadCompare();
        } catch (error) {
          if (alive(token, body)) setFeedback(baselineFeedback, error.message, "error");
        } finally { baselineSelect.disabled = false; }
      });
      const baselineLink = node("a", "去简历库上传/解析 ↗");
      baselineLink.href = meta.resumes_url;
      baselineSection.append(field("选择基准简历", baselineSelect), baselineInfo, baselineLink, baselineFeedback);

      const picker = section("选择岗位", "briefcase");
      const eligible = state.jobs.filter((job) => RP.stageIndex(job.stage) >= RP.stageIndex("screened") && job.tab !== "rejected" && job.tab !== "failed");
      if (ctx.job && !eligible.some((job) => RP.jobId(job) === RP.jobId(ctx.job))) eligible.unshift(ctx.job);
      const jobSelect = select(eligible.slice(0, 200).map((job) => [RP.jobId(job), `${job.title} · ${job.company || RP.sourceLabel(job.source)}`]),
        ctx.job ? RP.jobId(ctx.job) : eligible[0] ? RP.jobId(eligible[0]) : null);
      const currentJob = () => eligible.find((job) => RP.jobId(job) === jobSelect.value) || null;
      const runFeedback = feedback();
      const runBtn = button("生成定向改写（批量阶段）", "rp-btn-primary", "pen");
      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        try {
          const result = await withBusy(() => RP.runStage("rewrite"), runFeedback, "正在生成定向改写稿…");
          if (!alive(token, body)) return;
          setFeedback(runFeedback, RP.stageResultMessage(result, "简历改写"), "success");
          toast(RP.stageResultMessage(result, "简历改写"), "success");
          void RP.refresh({ silent: true });
          void loadCompare();
        } catch (error) {
          if (alive(token, body)) setFeedback(runFeedback, error.message, "error");
        } finally { runBtn.disabled = false; }
      });
      picker.append(field("目标岗位", jobSelect), runBtn, runFeedback);
      if (!eligible.length) picker.append(note("暂无可改写的岗位：先完成初评，或从看板选择岗位。", "warning"));

      const compareSection = section("改写对比", "eye");
      const compare = node("div", "", "rp-compare");
      const baseCol = node("div", "", "rp-compare-col");
      const rewriteCol = node("div", "", "rp-compare-col");
      baseCol.append(node("h4", "基准简历"));
      rewriteCol.append(node("h4", "定向改写稿"));
      const baseDoc = node("div", "", "rp-doc");
      const rewriteDoc = node("div", "", "rp-doc");
      baseCol.append(baseDoc);
      rewriteCol.append(rewriteDoc);
      compare.append(baseCol, rewriteCol);
      const rewriteMeta = node("div", "", "rp-stat-chips");
      const downgrades = node("details", "", "rp-deep-key");
      downgrades.hidden = true;
      const compareActions = node("div", "", "rp-panel-actions");
      const copyBtn = button("复制改写稿", "rp-btn-sm", "copy");
      let rewriteText = "";
      copyBtn.addEventListener("click", () => copyText(rewriteText, "改写稿已复制。"));
      compareActions.append(copyBtn);
      compareSection.append(compare, rewriteMeta, downgrades, compareActions);
      body.append(baselineSection, picker, compareSection);

      let baselineOptions = [];
      loadConfig().then((data) => {
        if (!alive(token, body)) return;
        const baseline = data.resume_baseline || {};
        baselineOptions = baseline.options || [];
        baselineSelect.replaceChildren(...baselineOptions.map((option) =>
          new Option(`${option.title}（${option.chars} 字）`, option.id)));
        if (!baselineOptions.length) {
          baselineSelect.replaceChildren(new Option("简历库暂无已解析文档", ""));
          baselineInfo.textContent = "请先在简历库上传并解析简历，再选择基准。";
        } else {
          const current = baselineOptions.find((option) => option.title === baseline.name);
          baselineSelect.value = current?.id || baselineOptions[0].id;
          baselineInfo.textContent = baseline.enabled
            ? `当前基准：${baseline.name}。初评与改写均以该简历为底稿。`
            : "尚未选定基准简历：选择后保存，改写阶段才可执行。";
        }
      }).catch((error) => {
        if (alive(token, body)) setFeedback(baselineFeedback, error.message, "error");
      });

      let compareSeq = 0;
      async function loadCompare() {
        const sequence = ++compareSeq;
        const job = currentJob();
        const selected = baselineOptions.find((option) => option.id === baselineSelect.value);
        baseDoc.replaceChildren();
        if (selected) {
          baseDoc.append(node("h5", selected.title));
          baseDoc.append(node("p", `已解析简历文档 · ${selected.chars} 字。全文请在简历库查看，改写稿不会裁剪经历条目。`));
        } else {
          baseDoc.append(node("p", "尚未选定基准简历。", "rp-doc-empty"));
        }
        const baseLink = node("a", "在简历库中查看 ↗");
        baseLink.href = meta.resumes_url;
        baseDoc.append(baseLink);
        rewriteDoc.replaceChildren(node("p", job ? "正在读取改写稿…" : "请先选择岗位。", "rp-doc-empty"));
        rewriteMeta.replaceChildren();
        downgrades.hidden = true;
        rewriteText = "";
        copyBtn.disabled = true;
        if (!job) return;
        try {
          const payload = await RP.fetchJobPayload(job);
          if (sequence !== compareSeq || !alive(token, body)) return;
          const rewrite = payloadOf(payload, "rewrite_payload", "rewrite");
          rewriteDoc.replaceChildren();
          rewriteText = RP.payloadText(rewrite);
          if (rewriteText) RP.renderDoc(rewriteDoc, rewriteText);
          else rewriteDoc.append(node("p", "尚未生成改写稿，点击上方按钮生成。", "rp-doc-empty"));
          copyBtn.disabled = !rewriteText;
          if (rewrite && typeof rewrite === "object") {
            rewriteMeta.append(modeChip(rewrite.mode));
            if (rewrite.baseline_name) rewriteMeta.append(node("span", `基准：${rewrite.baseline_name}`, "rp-stat-chip"));
            const list = Array.isArray(rewrite.downgrades) ? rewrite.downgrades : [];
            if (list.length) {
              downgrades.hidden = false;
              downgrades.replaceChildren(node("summary", `真实性边界降级记录（${list.length}）`));
              const doc = node("div", "", "rp-doc");
              for (const item of list) {
                doc.append(node("p", `${item.original} → ${item.replaced} · ${item.reason || ""}`));
              }
              downgrades.append(doc);
            }
          }
        } catch (error) {
          if (sequence === compareSeq) rewriteDoc.replaceChildren(node("p", error.message, "rp-doc-empty"));
        }
      }
      jobSelect.addEventListener("change", () => void loadCompare());
      void loadCompare();
    }
  });

  /* ---------- 6. 打招呼语（greeting，海投母本 + 预览核验） ---------- */
  RP.registerDrawer("greeting", {
    title: "打招呼语预览", icon: "message", tone: "success",
    render(body) {
      const token = RP.drawerToken();
      body.append(note("高情商开场白：150-250 字、2-3 个匹配理由、禁弱势词。精投轨由模型/模板生成；海投轨只认下方人工母本，母本为空时岗位转人工复核，禁止现场编造。", "info"));

      const masterSection = section("海投母本（人工配置）", "pen");
      const master = node("textarea");
      master.rows = 4; master.maxLength = 2000;
      master.placeholder = "填写海投轨统一使用的打招呼母本；留空时海投岗位停在人工复核。";
      const masterFeedback = feedback();
      const masterSave = button("保存母本", "", "check");
      masterSave.addEventListener("click", async () => {
        masterSave.disabled = true;
        try {
          await saveConfig({ mass_greeting: master.value }, masterFeedback, "海投母本已保存。");
          if (alive(token, body)) setFeedback(masterFeedback, "海投母本已保存。", "success");
        } catch (error) {
          if (alive(token, body)) setFeedback(masterFeedback, error.message, "error");
        } finally { masterSave.disabled = false; }
      });
      masterSection.append(master, masterSave, masterFeedback);

      const runSection = section("批量生成", "play");
      const runFeedback = feedback();
      const runBtn = button("生成打招呼语", "rp-btn-primary", "play");
      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        try {
          const result = await withBusy(() => RP.runStage("greet"), runFeedback, "正在批量生成…");
          if (!alive(token, body)) return;
          setFeedback(runFeedback, RP.stageResultMessage(result, "打招呼语"), "success");
          toast(RP.stageResultMessage(result, "打招呼语"), "success");
          void RP.refresh({ silent: true });
          paintList();
        } catch (error) {
          if (alive(token, body)) setFeedback(runFeedback, error.message, "error");
        } finally { runBtn.disabled = false; }
      });
      runSection.append(runBtn, runFeedback);

      const previewSection = section("生成稿预览", "eye");
      const list = node("div", "", "rp-mini-list");
      const preview = node("div", "", "rp-panel-section");
      const textBox = node("div", "", "rp-greeting-text");
      const gate = feedback();
      const actions = node("div", "", "rp-panel-actions");
      const copyBtn = button("复制欢迎语", "rp-btn-sm", "copy");
      let greetingText = "";
      copyBtn.addEventListener("click", () => copyText(greetingText, "欢迎语已复制。"));
      actions.append(copyBtn);
      preview.append(textBox, gate, actions);
      preview.hidden = true;

      function showGreeting(greeting) {
        const text = RP.payloadText(greeting);
        greetingText = text;
        preview.hidden = false;
        textBox.textContent = text || "（空）";
        const illegal = !text.trim() || /❌|生成失败/.test(text) || (greeting && greeting.legal === false);
        if (illegal) setFeedback(gate, "未通过合法性闸：内容为空或含失败标记，严禁外发。", "error");
        else {
          const length = text.replace(/\s/g, "").length;
          setFeedback(gate, `合法性闸通过 · ${length} 字${length < 150 || length > 250 ? "（建议 150-250 字）" : ""}，外发前请人工核验。`, "success");
        }
        copyBtn.disabled = illegal;
      }
      function paintList() {
        const jobs = state.jobs.filter((job) => job.hasGreeting || RP.stageIndex(job.stage) >= RP.stageIndex("greeted")).slice(0, 10);
        if (!jobs.length) {
          list.replaceChildren(emptyBlock("暂无打招呼语", "运行生成后，这里会列出可预览的岗位。"));
          preview.hidden = true;
          return;
        }
        list.replaceChildren(...jobs.map((job) => {
          const row = miniJob(job);
          const rowActions = node("div", "", "rp-mini-job-actions");
          const view = button("预览", "rp-btn-sm rp-btn-ghost", "eye");
          view.addEventListener("click", async () => {
            view.disabled = true;
            try {
              const payload = await RP.fetchJobPayload(job);
              if (!alive(token, body)) return;
              showGreeting(payloadOf(payload, "greeting_payload", "greeting"));
            } catch (error) {
              if (alive(token, body)) toast(error.message, "error");
            } finally { view.disabled = false; }
          });
          rowActions.append(view);
          row.append(rowActions);
          return row;
        }));
      }
      paintList();
      previewSection.append(list, preview);
      body.append(masterSection, runSection, previewSection);

      loadConfig().then((data) => {
        if (alive(token, body)) master.value = data.settings?.mass_greeting || "";
      }).catch(() => {});
    }
  });

  /* ---------- 7. 审批操作（review） ---------- */
  RP.registerDrawer("review", {
    title: "审批操作", icon: "shield", tone: "warning",
    render(body) {
      const token = RP.drawerToken();
      body.append(note("精投轨走简历人工复核；海投轨按公司规模闸拦截（默认 ≥1000 人）。放行需物料齐备（定制简历稿 + 合法欢迎语），拒绝为终态，重评打回评估段。", "info"));
      const head = section("待审批队列", "user-check");
      const countLine = node("p", "", "rp-hint");
      const bulkBtn = button("一键放行全部", "rp-btn-primary", "check");
      const list = node("div", "", "rp-mini-list");
      function paint() {
        const jobs = state.jobs.filter((job) => job.tab === "approval");
        countLine.textContent = jobs.length ? `共 ${jobs.length} 个岗位等待审批。` : "";
        bulkBtn.disabled = !jobs.length || state.bulkBusy;
        bulkBtn.textContent = jobs.length ? `一键放行全部（${jobs.length}）` : "一键放行全部";
        if (!jobs.length) {
          list.replaceChildren(emptyBlock("审批队列已清空", "启动流水线或等待岗位流转到审批段。"));
          return;
        }
        list.replaceChildren(...jobs.slice(0, 50).map((job) => {
          const row = miniJob(job);
          row.append(node("p", [job.track === "mass" ? "海投轨" : "精投轨", job.followStatus, job.reason].filter(Boolean).join(" · "), "rp-mini-job-meta"));
          const actions = node("div", "", "rp-mini-job-actions");
          const reject = button("拒绝", "rp-btn-sm rp-btn-danger", "x");
          const reeval = button("重评", "rp-btn-sm rp-btn-ghost", "rotate");
          const approve = button("放行", "rp-btn-sm rp-btn-success", "check");
          reject.addEventListener("click", async () => { await RP.decide(job, "reject"); if (alive(token, body)) paint(); });
          reeval.addEventListener("click", async () => { await RP.decide(job, "reeval"); if (alive(token, body)) paint(); });
          approve.addEventListener("click", async () => { await RP.decide(job, "approve"); if (alive(token, body)) paint(); });
          actions.append(reject, reeval, approve);
          row.append(actions);
          return row;
        }));
      }
      bulkBtn.addEventListener("click", async () => {
        const jobs = state.jobs.filter((job) => job.tab === "approval");
        bulkBtn.disabled = true;
        let done = 0;
        for (const job of jobs) {
          try {
            await pipelineApi("/approve", { source: job.source, url_key: job.url_key, decision: "approve" });
            job.stage = "queued"; job.tab = "queued"; job.followStatus = "待投递";
            RP.adjustCounts("approval", "queued");
            done += 1;
          } catch (error) { toast(`放行中断：${error.message}`, "error"); break; }
        }
        RP.renderBoard();
        void RP.refresh({ silent: true });
        if (done) toast(`已放行 ${done} 个岗位。`, "success");
        if (alive(token, body)) paint();
      });
      paint();
      head.append(countLine, bulkBtn, list);
      body.append(head);
    }
  });

  /* ---------- 8. 投递队列（delivering，dry-run + 投递包） ---------- */
  RP.registerDrawer("delivering", {
    title: "投递队列 · dry-run", icon: "send", tone: "accent",
    render(body, ctx) {
      const token = RP.drawerToken();
      body.append(note("投递为本地 dry-run：模拟执行并生成投递包（JSON/CSV 导出），不向外部平台发起请求。失败台账按持久/瞬时故障分诊，自动重试最多 2 次。", "info"));

      const gate = section("投递闸配置", "sliders");
      const headcount = input("number", { min: "1", max: "10000000", step: "1" });
      const stopAtReview = input("checkbox");
      const stopLabel = node("label", "", "rp-inline-check");
      stopLabel.append(stopAtReview, document.createTextNode("停在待投递队列等待手动/波次 dry-run（推荐）"));
      const gateFeedback = feedback();
      const gateSave = button("保存投递闸配置", "", "check");
      gateSave.addEventListener("click", async () => {
        gateSave.disabled = true;
        try {
          await saveConfig({
            mass_apply_max_headcount: Number(headcount.value) || 1000,
            stop_at_review: stopAtReview.checked
          }, gateFeedback, "投递闸配置已保存。");
          if (alive(token, body)) setFeedback(gateFeedback, "投递闸配置已保存。", "success");
        } catch (error) {
          if (alive(token, body)) setFeedback(gateFeedback, error.message, "error");
        } finally { gateSave.disabled = false; }
      });
      gate.append(field("海投拦截门槛（公司规模上限，人）", headcount), stopLabel, gateSave, gateFeedback);

      const selected = new Set();
      const queueSection = section("待投递", "send");
      const queueList = node("div", "", "rp-mini-list");
      const queueActions = node("div", "", "rp-panel-actions");
      const deliverBtn = button("dry-run 投递所选", "rp-btn-accent", "send");
      const exportBtn = button("全部投递并导出 CSV", "rp-btn-ghost", "download");
      const deliverFeedback = feedback();
      function syncDeliverBtn() {
        deliverBtn.disabled = !selected.size || state.bulkBusy;
        deliverBtn.textContent = selected.size ? `dry-run 投递所选（${selected.size}）` : "dry-run 投递所选";
      }
      function paintQueue() {
        const jobs = state.jobs.filter((job) => job.tab === "queued");
        syncDeliverBtn();
        if (!jobs.length) {
          queueList.replaceChildren(emptyBlock("待投递队列为空", "审批放行后岗位会进入这里。"));
          return;
        }
        queueList.replaceChildren(...jobs.slice(0, 50).map((job) => {
          const row = miniJob(job, {
            checkbox: true,
            checked: selected.has(RP.jobId(job)),
            onCheck: (checked) => {
              if (checked) selected.add(RP.jobId(job));
              else selected.delete(RP.jobId(job));
              syncDeliverBtn();
            }
          });
          const actions = node("div", "", "rp-mini-job-actions");
          const deliver = button("立即投递", "rp-btn-sm rp-btn-accent", "send");
          deliver.addEventListener("click", async () => {
            await RP.deliverJobs([job]);
            if (alive(token, body)) { paintQueue(); paintDelivered(); }
          });
          const cancel = button("终止投递", "rp-btn-sm rp-btn-ghost", "stop");
          cancel.addEventListener("click", async () => {
            await RP.abandonDelivery(job);
            if (alive(token, body)) paintQueue();
          });
          actions.append(cancel, deliver);
          row.append(actions);
          return row;
        }));
      }
      deliverBtn.addEventListener("click", async () => {
        const jobs = state.jobs.filter((job) => job.tab === "queued" && selected.has(RP.jobId(job)));
        selected.clear();
        await RP.deliverJobs(jobs);
        if (alive(token, body)) { paintQueue(); paintDelivered(); }
      });
      exportBtn.addEventListener("click", async () => {
        exportBtn.disabled = true;
        setFeedback(deliverFeedback, "正在执行 dry-run 并导出投递包…");
        try {
          await RP.exportDeliveryCsv();
          if (!alive(token, body)) return;
          setFeedback(deliverFeedback, "投递包 CSV 已导出（含本轮 dry-run 结果）。", "success");
          toast("投递包 CSV 已导出。", "success");
          void RP.refresh({ silent: true });
          paintQueue();
          paintDelivered();
        } catch (error) {
          if (alive(token, body)) setFeedback(deliverFeedback, error.message, "error");
        } finally { exportBtn.disabled = false; }
      });
      queueActions.append(deliverBtn, exportBtn);
      queueSection.append(queueActions, deliverFeedback, queueList);

      const deliveredSection = section("已投递 · 投递包", "check-circle");
      const deliveredList = node("div", "", "rp-mini-list");
      const packageView = node("div", "", "rp-panel-section");
      packageView.hidden = true;
      function renderPackage(delivery) {
        packageView.replaceChildren();
        const pkg = delivery?.package;
        if (!pkg) {
          packageView.append(RP.payloadText(delivery)
            ? (() => { const doc = node("div", "", "rp-doc"); RP.renderDoc(doc, RP.payloadText(delivery)); return doc; })()
            : note("投递包为空：该岗位可能由早期 dry-run 生成。", "warning"));
          return;
        }
        const chips = node("div", "", "rp-stat-chips");
        for (const text of [
          pkg.grade ? `评级 ${pkg.grade}` : "", pkg.score != null ? `${pkg.score} 分` : "",
          pkg.track === "mass" ? "海投轨" : "精投轨", "dry-run 模拟投递",
          delivery.delivered_at ? "投递时间 " + RP.fmtTime(delivery.delivered_at) : ""
        ].filter(Boolean)) chips.append(node("span", text, "rp-stat-chip"));
        packageView.append(chips);
        if (pkg.greeting) {
          packageView.append(node("h3", "破冰欢迎语"));
          const box = node("div", "", "rp-greeting-text");
          box.textContent = pkg.greeting;
          packageView.append(box);
        }
        if (pkg.resume_markdown) {
          packageView.append(node("h3", "投递简历（改写稿）"));
          const doc = node("div", "", "rp-doc");
          RP.renderDoc(doc, pkg.resume_markdown);
          packageView.append(doc);
        }
      }
      async function openPackage(job) {
        packageView.hidden = false;
        packageView.replaceChildren(node("p", "正在读取投递包…", "rp-hint"));
        try {
          const payload = await RP.fetchJobPayload(job);
          if (!alive(token, body)) return;
          renderPackage(payloadOf(payload, "delivery_payload", "delivery"));
        } catch (error) {
          if (alive(token, body)) packageView.replaceChildren(note(error.message, "danger"));
        }
      }
      function paintDelivered() {
        const jobs = state.jobs.filter((job) => job.tab === "delivered");
        if (!jobs.length) {
          deliveredList.replaceChildren(emptyBlock("暂无投递记录", "dry-run 投递完成后会在这里留档。"));
          return;
        }
        deliveredList.replaceChildren(...jobs.slice(0, 30).map((job) => {
          const row = miniJob(job);
          row.append(node("p", job.updatedAt ? "投递时间 " + RP.fmtTime(job.updatedAt) : "", "rp-mini-job-meta"));
          const actions = node("div", "", "rp-mini-job-actions");
          const view = button("查看投递包", "rp-btn-sm rp-btn-ghost", "eye");
          view.addEventListener("click", () => openPackage(job));
          actions.append(view);
          row.append(actions);
          return row;
        }));
      }
      deliveredSection.append(deliveredList, packageView);
      paintQueue();
      paintDelivered();
      body.append(gate, queueSection, deliveredSection);

      loadConfig().then((data) => {
        if (!alive(token, body)) return;
        headcount.value = data.settings?.mass_apply_max_headcount ?? 1000;
        stopAtReview.checked = data.settings?.stop_at_review !== false;
      }).catch(() => {});
      if (ctx.job && ctx.job.tab === "delivered") void openPackage(ctx.job);
    }
  });

  /* ---------- 物料预览弹窗渲染 ---------- */
  RP.registerMaterialsRenderer((body, job, payload, tab) => {
    body.append(node("p", [job.company, RP.sourceLabel(job.source), job.location, job.salary].filter(Boolean).join(" · "), "rp-modal-meta"));
    if (tab === "resume") {
      const rewrite = payloadOf(payload, "rewrite_payload", "rewrite");
      const text = RP.payloadText(rewrite);
      if (!text) {
        body.append(emptyBlock("尚未生成定向改写稿", "改写以基准简历为底稿，结合该岗位 JD 生成。", "去生成改写", () => {
          RP.closeMaterials();
          RP.openDrawer("rewriting", { job });
        }));
        return;
      }
      if (rewrite && typeof rewrite === "object") {
        const chips = node("div", "", "rp-stat-chips");
        chips.append(modeChip(rewrite.mode));
        if (rewrite.baseline_name) chips.append(node("span", `基准：${rewrite.baseline_name}`, "rp-stat-chip"));
        body.append(chips);
      }
      const doc = node("div", "", "rp-doc");
      RP.renderDoc(doc, text);
      const actions = node("div", "", "rp-modal-actions");
      const copy = button("复制全文", "rp-btn-sm", "copy");
      copy.addEventListener("click", () => copyText(text, "改写稿已复制。"));
      const open = button("打开定制面板", "rp-btn-sm rp-btn-ghost", "sliders");
      open.addEventListener("click", () => { RP.closeMaterials(); RP.openDrawer("rewriting", { job }); });
      actions.append(copy, open);
      body.append(doc, actions);
      const list = Array.isArray(rewrite?.downgrades) ? rewrite.downgrades : [];
      if (list.length) {
        const fold = node("details", "", "rp-deep-key");
        fold.append(node("summary", `真实性边界降级记录（${list.length}）`));
        const foldDoc = node("div", "", "rp-doc");
        for (const item of list) foldDoc.append(node("p", `${item.original} → ${item.replaced} · ${item.reason || ""}`));
        fold.append(foldDoc);
        body.append(fold);
      }
      body.append(note("本地改写稿预览，无外部原件；外发前请人工核验真实性边界。", "info"));
    } else {
      const greeting = payloadOf(payload, "greeting_payload", "greeting");
      const text = RP.payloadText(greeting);
      if (!text) {
        body.append(emptyBlock("尚未生成破冰欢迎语", "生成后可在这里核验合法性并复制。", "去生成欢迎语", () => {
          RP.closeMaterials();
          RP.openDrawer("greeting");
        }));
        return;
      }
      const box = node("div", "", "rp-greeting-text");
      box.textContent = text;
      const illegal = /❌|生成失败/.test(text) || (greeting && greeting.legal === false);
      const gate = note(illegal ? "未通过合法性闸：内容为空或含失败标记，严禁外发。" : "合法性闸通过，外发前请人工核验匹配理由。", illegal ? "danger" : "success");
      const actions = node("div", "", "rp-modal-actions");
      const copy = button("复制欢迎语", "rp-btn-sm", "copy");
      copy.disabled = illegal;
      copy.addEventListener("click", () => copyText(text, "欢迎语已复制。"));
      actions.append(copy);
      body.append(box, gate, actions);
    }
  });
})();
