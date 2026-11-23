(() => {
  "use strict";
  const RP = window.RP;
  if (!RP || !RP.ui) return;
  const { node, icon, tile, toast, api, pipelineApi, meta, state } = RP;
  const {
    PROFILE_KEYS, rememberedProfile, setRememberedProfile,
    DEEP_KEYS, DIMENSION_LABELS, GRADE_OPTIONS, DIMENSION_META,
    alive, section, note, feedback, setFeedback, field, input, select,
    sourceLabel, sourceEntries, platformLogo, profileSelect, button,
    emptyBlock, gradeBadge, payloadOf, copyText, miniJob, withBusy,
    loadConfig, saveConfig, modeChip,
    INLINE_SVGS, PLATFORM_TAGLINES, inlineIcon, compactTime,
  } = RP.ui;

  RP.registerDrawer("scraping", {
    title: "抓取 · 平台实时采集", icon: "search", tone: "accent",
    render(body) {
      const token = RP.drawerToken();
      const chromeSources = Object.keys(meta.chrome_sources || {});
      const canUseChrome = meta.chrome_available && chromeSources.length > 0;
      const collectEntries = sourceEntries(meta.collection_sources || meta.sources);
      const statusNames = {
        queued: "等待中", running: "采集中", succeeded: "已采集", complete: "已完成",
        partial: "部分完成", empty: "无结果", interrupted: "已中断", blocked: "需要验证", unavailable: "暂不可用",
        opening: "打开浏览器", waiting_user: "等待登录或验证", login_required: "需要登录", login_timeout: "登录超时",
        city_unsupported: "城市暂不支持", reading_details: "读取原站 JD"
      };

      /* 顶部 Hero 横幅（融合 3D 玻璃拟态插画 + 特性胶囊） */
      const hero = node("header", "", "rp-collect-hero");
      const heroTop = node("div", "", "rp-collect-hero-top");
      const heroBadge = node("span", "", "rp-collect-hero-icon");
      heroBadge.append(icon("search"));
      const heroText = node("div", "", "rp-collect-hero-text");
      heroText.append(
        node("h2", "抓取 · 平台实时采集"),
        node("p", "多平台职位信息实时采集 · 统一清洗 · 高效入库")
      );
      heroTop.append(heroBadge, heroText);
      const heroPills = node("div", "", "rp-collect-hero-pills");
      for (const [svgName, label] of [
        ["bolt", "多平台聚合"], ["layers", "实时采集"], ["shield", "去重校验"], ["chart", "数据可溯"]
      ]) {
        const pill = node("span", "", "rp-hero-pill");
        pill.append(svgName === "layers" || svgName === "shield" ? icon(svgName) : inlineIcon(svgName), node("span", label));
        heroPills.append(pill);
      }
      hero.append(heroTop, heroPills);

      /* 主体白卡：采集平台 + 采集设置 */
      const mainCard = node("section", "", "rp-collect-card");
      if (!canUseChrome) {
        mainCard.append(note("本机 Chrome 连接未启用，当前仅采集公开搜索结果。", "warning"));
      }

      const selectedSources = new Set(collectEntries.map(([key]) => key));
      const platformToolbar = node("div", "", "rp-collect-toolbar");
      const platformTitleWrap = node("div", "", "rp-collect-toolbar-title");
      const selectedCountBadge = node("span", `${selectedSources.size} / ${collectEntries.length}`, "rp-count-pill");
      platformTitleWrap.append(icon("layers"), node("strong", "采集平台"), selectedCountBadge);
      const toolbarActions = node("div", "", "rp-collect-toolbar-actions");
      const selectAllBtn = button("清空", "rp-btn-sm rp-btn-ghost rp-tool-btn");
      selectAllBtn.prepend(inlineIcon("trash"));
      const checkAll = button("检查全部", "rp-btn-sm rp-btn-ghost rp-tool-btn", "shield");
      toolbarActions.append(selectAllBtn, checkAll);
      platformToolbar.append(platformTitleWrap, toolbarActions);

      const sessionWrap = node("div", "", "rp-sessions");
      const checks = [];
      const cardSyncers = [];
      let syncSubmitLabel = () => {};

      function syncSelectionUI() {
        const count = selectedSources.size;
        selectedCountBadge.textContent = `${count} / ${collectEntries.length}`;
        selectedCountBadge.dataset.active = count > 0 ? "1" : "0";
        selectAllBtn.lastChild.textContent = count === collectEntries.length ? "清空" : "全选";
        for (const sync of cardSyncers) sync();
        syncSubmitLabel();
      }

      for (const [key, label] of collectEntries) {
        const card = node("div", "", "rp-session");
        card.setAttribute("role", "checkbox");
        card.setAttribute("tabindex", "0");
        card.setAttribute("aria-checked", "true");
        card.dataset.selected = "1";

        const top = node("div", "", "rp-session-top");
        const logo = platformLogo(key, label);
        const info = node("div", "", "rp-session-info");
        info.append(
          node("strong", label),
          node("span", PLATFORM_TAGLINES[key] || "招聘渠道", "rp-session-sub")
        );
        const pick = node("span", "", "rp-session-pick");
        pick.append(icon("check"));
        top.append(logo, info, pick);

        const foot = node("div", "", "rp-session-foot");
        const result = node("div", "", "rp-session-result");
        result.setAttribute("role", "status");
        const dot = node("span", "", "rp-session-dot");
        const stateLabel = node("span", "未检查", "rp-session-label");
        result.append(dot, stateLabel);
        const checkBtn = button("检测", "rp-btn-sm rp-btn-ghost rp-session-check");
        checkBtn.prepend(inlineIcon("pulse"));
        foot.append(result, checkBtn);

        const extra = node("div", "", "rp-session-extra");
        extra.hidden = true;
        const stateMsg = node("p", "", "rp-session-message");
        stateMsg.hidden = true;
        const extraActions = node("div", "", "rp-session-extra-actions");
        const loginLink = node("a", "打开官网 ↗", "rp-btn rp-btn-sm rp-btn-ghost");
        loginLink.target = "_blank";
        loginLink.rel = "noopener noreferrer";
        loginLink.hidden = true;
        loginLink.addEventListener("click", (event) => event.stopPropagation());
        const copyBtn = button("复制授权地址", "rp-btn-sm rp-btn-ghost", "copy");
        copyBtn.hidden = true;
        copyBtn.addEventListener("click", async (event) => {
          event.stopPropagation();
          try {
            await navigator.clipboard.writeText("chrome://inspect/#remote-debugging");
            toast("授权页地址已复制，粘贴到 Chrome 地址栏打开。", "success");
          } catch (_) {
            toast("复制失败，请手动输入 chrome://inspect/#remote-debugging", "error");
          }
        });
        extraActions.append(loginLink, copyBtn);
        extra.append(stateMsg, extraActions);

        const syncCard = () => {
          const on = selectedSources.has(key);
          card.dataset.selected = on ? "1" : "0";
          card.setAttribute("aria-checked", on ? "true" : "false");
        };
        cardSyncers.push(syncCard);

        const toggleSelect = () => {
          if (selectedSources.has(key)) selectedSources.delete(key);
          else selectedSources.add(key);
          syncSelectionUI();
        };
        card.addEventListener("click", toggleSelect);
        card.addEventListener("keydown", (event) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            toggleSelect();
          }
        });

        const check = async () => {
          if (checkBtn.disabled) return;
          checkBtn.disabled = true;
          card.dataset.state = "checking";
          result.dataset.state = "checking";
          stateLabel.textContent = "检查中…";
          stateMsg.hidden = true;
          copyBtn.hidden = true;
          loginLink.hidden = true;
          extra.hidden = true;
          try {
            const status = await api(`/session/${key}`, {});
            if (!alive(token, body)) return;
            card.dataset.state = status.state;
            result.dataset.state = status.state;
            stateLabel.textContent = status.label;
            const showMsg = Boolean(status.message && status.state !== "ready");
            stateMsg.textContent = showMsg ? status.message : "";
            stateMsg.hidden = !showMsg;
            if (status.login_url) {
              loginLink.href = status.login_url;
              loginLink.hidden = false;
            }
            copyBtn.hidden = status.state !== "authorization_required_manual";
            extra.hidden = !showMsg && loginLink.hidden && copyBtn.hidden;
          } catch (error) {
            if (!alive(token, body)) return;
            card.dataset.state = "unavailable";
            result.dataset.state = "unavailable";
            stateLabel.textContent = "检查失败";
            stateMsg.textContent = error.message;
            stateMsg.hidden = false;
            extra.hidden = false;
          } finally { checkBtn.disabled = false; }
        };
        checkBtn.addEventListener("click", (event) => {
          event.stopPropagation();
          void check();
        });
        checks.push(check);
        card.append(top, foot, extra);
        sessionWrap.append(card);
      }

      selectAllBtn.addEventListener("click", () => {
        if (selectedSources.size === collectEntries.length) selectedSources.clear();
        else for (const [key] of collectEntries) selectedSources.add(key);
        syncSelectionUI();
      });
      checkAll.addEventListener("click", async () => {
        checkAll.disabled = true;
        try { await Promise.all(checks.map((check) => check())); } finally { checkAll.disabled = false; }
      });

      /* 采集设置区 */
      const settingsHead = node("div", "", "rp-collect-subhead");
      settingsHead.append(inlineIcon("gear"), node("strong", "采集设置"));

      const catalog = meta.city_catalog || {};
      const cityOptions = [["", "全部城市"]];
      const seenCity = new Set();
      for (const cityName of [...(catalog.hot || []), ...(catalog.scopes || []), ...Object.values(catalog.groups || {}).flat()]) {
        if (!seenCity.has(cityName)) { seenCity.add(cityName); cityOptions.push([cityName, cityName]); }
      }
      const form = node("form", "", "rp-collect-form");

      const keyword = input("text", { placeholder: "关键词，如 Agent、Python 实习、大模型", maxlength: 80, required: true });
      const keywordInputWrap = node("div", "", "rp-input-with-icon");
      keywordInputWrap.append(icon("search"), keyword);
      const keywordRow = node("div", "", "rp-hfield");
      const kwLabel = node("label", "", "rp-hlabel");
      kwLabel.append(inlineIcon("pencil"), node("span", "关键词"));
      keywordRow.append(kwLabel, keywordInputWrap);

      const city = select(cityOptions);
      const cityLabel = node("label", "", "rp-hlabel");
      cityLabel.append(inlineIcon("pin"), node("span", "城市"));
      const cityCell = node("div", "", "rp-hfield");
      cityCell.append(cityLabel, city);

      const limit = input("number", { min: 1, max: 30, value: 20 });
      const stepper = node("div", "", "rp-stepper");
      const minusBtn = node("button", "−", "rp-step-btn");
      minusBtn.type = "button";
      minusBtn.setAttribute("aria-label", "减少上限");
      const plusBtn = node("button", "+", "rp-step-btn");
      plusBtn.type = "button";
      plusBtn.setAttribute("aria-label", "增加上限");
      const stepLimit = (delta) => {
        const current = Number(limit.value) || 20;
        limit.value = String(Math.max(1, Math.min(30, current + delta)));
      };
      minusBtn.addEventListener("click", () => stepLimit(-5));
      plusBtn.addEventListener("click", () => stepLimit(5));
      stepper.append(limit, minusBtn, plusBtn);
      const limitLabel = node("label", "", "rp-hlabel");
      limitLabel.append(icon("layers"), node("span", "每平台上限"));
      const limitCell = node("div", "", "rp-hfield");
      limitCell.append(limitLabel, stepper);

      const cityLimitRow = node("div", "", "rp-collect-row");
      cityLimitRow.append(cityCell, limitCell);

      /* 求职方向：三段式带图标卡片 */
      const profileOrder = ["full_time", "general", "internship"].filter((k) => k in (meta.profiles || {}));
      const orderedProfiles = profileOrder.length ? profileOrder : PROFILE_KEYS;
      const profileIcons = { full_time: "briefcase", general: "grid", internship: "cap" };
      let selectedProfile = rememberedProfile();
      if (!orderedProfiles.includes(selectedProfile)) selectedProfile = orderedProfiles[0];
      const profileSeg = node("div", "", "rp-segmented");
      profileSeg.setAttribute("role", "group");
      profileSeg.setAttribute("aria-label", "求职方向");
      const segButtons = orderedProfiles.map((key) => {
        const label = (meta.profiles || {})[key] || key;
        const btn = node("button", "", "rp-seg-btn");
        btn.type = "button";
        btn.dataset.value = key;
        btn.setAttribute("aria-pressed", key === selectedProfile ? "true" : "false");
        btn.append(inlineIcon(profileIcons[key] || "grid"), node("span", label));
        btn.addEventListener("click", () => {
          selectedProfile = key;
          setRememberedProfile(key);
          for (const item of segButtons) {
            item.setAttribute("aria-pressed", item.dataset.value === selectedProfile ? "true" : "false");
          }
        });
        profileSeg.append(btn);
        return btn;
      });
      const dirLabel = node("span", "", "rp-hlabel");
      dirLabel.append(inlineIcon("briefcase"), node("span", "求职方向"));
      const profileRow = node("div", "", "rp-hfield");
      profileRow.append(dirLabel, profileSeg);

      const localWrap = node("label", "", "rp-switch-row");
      const localBox = input("checkbox", {});
      const switchTrack = node("span", "", "rp-switch-track");
      const chromeBadge = inlineIcon("chrome", "rp-chrome-svg");
      const infoTip = node("span", "", "rp-info-tip");
      infoTip.append(icon("info"));
      infoTip.title = "复用本机 Chrome 已登录的招聘平台账号，获取完整薪资与原站 JD";
      localWrap.append(
        localBox,
        switchTrack,
        chromeBadge,
        node("span", canUseChrome ? "使用本机 Chrome 登录态" : "使用 BOSS 本地登录态"),
        infoTip
      );
      localWrap.hidden = !canUseChrome && !meta.boss_local;
      localBox.checked = Boolean(canUseChrome || meta.boss_local);

      const submit = button("启动采集", "rp-collect-submit", "play");
      submit.type = "submit";
      const submitText = submit.lastChild;
      syncSubmitLabel = () => {
        const count = selectedSources.size;
        if (submitText) submitText.textContent = count > 0 ? `启动采集 · ${count} 个平台` : "启动采集";
      };
      syncSelectionUI();

      const collectFeedback = feedback();
      collectFeedback.setAttribute("role", "status");
      form.append(keywordRow, cityLimitRow, profileRow, localWrap, submit, collectFeedback);

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const term = keyword.value.trim();
        if (!term) { setFeedback(collectFeedback, "请输入采集关键词。", "error"); keyword.focus(); return; }
        const sources = [...selectedSources];
        if (!sources.length) { setFeedback(collectFeedback, "请先选择至少一个采集平台。", "error"); return; }
        submit.disabled = true;
        try {
          const run = await withBusy(() => api("/runs", {
            keyword: term, city: city.value, limit: Number(limit.value) || 20,
            sources, profile: selectedProfile,
            boss_local: Boolean(!canUseChrome && meta.boss_local && sources.includes("boss") && localBox.checked),
            chrome_local: Boolean(canUseChrome && localBox.checked && chromeSources.some((source) => sources.includes(source)))
          }), collectFeedback, "正在启动采集…");
          if (!alive(token, body)) return;
          setFeedback(collectFeedback, "", "");
          openRun = run.id;
          currentRun = run.id;
          void loadRuns();
        } catch (error) {
          if (alive(token, body)) setFeedback(collectFeedback, error.message, "error");
        } finally { submit.disabled = false; }
      });

      mainCard.append(platformToolbar, sessionWrap, settingsHead, form);

      /* 实时进度面板 + 采集记录白卡 */
      const activeProgress = node("section", "", "rp-collect-progress");
      activeProgress.hidden = true;

      const historyCard = node("section", "", "rp-history-card");
      const historyHead = node("div", "", "rp-history-head");
      const historyTitle = node("div", "", "rp-history-title");
      historyTitle.append(inlineIcon("doc"), node("strong", "采集记录"));
      const historyToggle = node("button", "", "rp-history-toggle");
      historyToggle.type = "button";
      const historyCount = node("span", "共 0 条", "rp-run-history-count");
      historyToggle.append(historyCount, node("span", "›", "rp-history-chevron"));
      historyHead.append(historyTitle, historyToggle);
      const runsWrap = node("div", "正在读取采集记录…", "rp-runs");
      let showAllRuns = false;
      let latestItems = [];
      historyCard.append(historyHead, runsWrap);

      let runPoll = null;
      let runRequest = 0;
      let lastRuns = "";
      let openRun = null;
      let currentRun = null;
      const pendingStates = new Set(["queued", "running", "opening", "waiting_user", "reading_details"]);

      function progressBar(percent, tone, animated) {
        const track = node("div", "", "rp-prog-track");
        track.setAttribute("role", "progressbar");
        track.setAttribute("aria-valuemin", "0");
        track.setAttribute("aria-valuemax", "100");
        track.setAttribute("aria-valuenow", String(Math.round(percent)));
        const fill = node("div", "", "rp-prog-fill" + (animated ? " is-animated" : ""));
        if (tone) fill.dataset.tone = tone;
        fill.style.width = `${Math.max(4, Math.min(100, Math.round(percent)))}%`;
        track.append(fill);
        return track;
      }

      function sourcePercent(status, item) {
        if (status === "queued") return 8;
        if (status === "opening") return 24;
        if (status === "waiting_user") return 42;
        if (status === "running") return 68;
        if (status === "reading_details") {
          const total = Math.max(1, item.details?.total || 1);
          const checked = item.details?.checked || 0;
          return 70 + Math.round((checked / total) * 30);
        }
        return 100;
      }

      function statusTone(status) {
        if (status === "succeeded" || status === "complete") return "success";
        if (status === "waiting_user" || status === "partial" || status === "login_required") return "warning";
        if (status === "blocked" || status === "unavailable" || status === "interrupted" || status === "login_timeout") return "danger";
        if (status === "empty" || status === "city_unsupported") return "muted";
        return "accent";
      }

      function paintProgress(run) {
        activeProgress.hidden = !run;
        if (!run) return;
        const entries = Object.entries(run.progress || {});
        const running = run.status === "running";
        activeProgress.dataset.state = run.status;
        const finished = entries.filter(([, item]) => !running || !pendingStates.has(item.status)).length;
        const totalJobs = entries.reduce((sum, [, item]) => sum + (Number(item.count) || 0), 0);
        const totalPct = !entries.length ? 100 : !running ? 100 : Math.round(
          entries.reduce((sum, [, item]) => sum + sourcePercent(item.status, item), 0) / entries.length
        );

        const head = node("div", "", "rp-collect-progress-head");
        const headLeft = node("div", "", "rp-collect-progress-title");
        const liveDot = node("span", "", "rp-prog-dot" + (running ? " is-live" : ""));
        liveDot.dataset.tone = statusTone(run.status);
        const titleText = [run.keyword, run.city].filter(Boolean).join(" · ") || "实时采集";
        headLeft.append(liveDot, node("strong", running ? `采集中 · ${titleText}` : `${statusNames[run.status] || run.status} · ${titleText}`));
        const headRight = node("div", "", "rp-collect-progress-stats");
        headRight.append(
          node("span", `${finished}/${entries.length} 平台`, "rp-prog-meta"),
          node("span", totalJobs ? `${totalJobs} 条` : `${totalPct}%`, "rp-prog-pct")
        );
        head.append(headLeft, headRight);

        const overallTone = running ? "accent" : statusTone(run.status);
        const overallBar = progressBar(totalPct, overallTone, running);

        const sources = entries.map(([source, item]) => {
          const row = node("div", "", "rp-collect-progress-source");
          const status = !running && pendingStates.has(item.status) ? run.status : item.status;
          const tone = statusTone(status);
          const isWorking = running && pendingStates.has(status);
          row.dataset.tone = tone;

          const top = node("div", "", "rp-collect-progress-rowhead");
          const label = sourceLabel((meta.collection_sources || {})[source]) || source;
          const left = node("div", "", "rp-collect-progress-brand");
          left.append(platformLogo(source, label), node("strong", label));
          const right = node("div", "", "rp-collect-progress-right");
          if (item.count > 0) right.append(node("span", `${item.count} 条`, "rp-prog-count"));
          const pill = node("span", statusNames[status] || status, "rp-prog-pill");
          pill.dataset.tone = tone;
          right.append(pill);
          top.append(left, right);
          row.append(top);

          const pct = sourcePercent(status, item);
          const miniBar = progressBar(pct, tone, isWorking);
          miniBar.classList.add("is-sm");
          row.append(miniBar);

          if (item.details) {
            const { total, checked, available } = item.details;
            const detailLine = node("div", "", "rp-collect-progress-sub");
            detailLine.append(
              node("span", status === "reading_details" ? `原站 JD ${Math.min(checked + 1, total)}/${total}` : `原站 JD 共 ${total} 条`),
              node("span", `已读取 ${available} 条`)
            );
            row.append(detailLine);
          }
          if (item.message && (tone === "warning" || tone === "danger" || status === "waiting_user")) {
            const msgLine = node("p", item.message, "rp-prog-msg");
            if (item.login_url && ["waiting_user", "login_required", "login_timeout"].includes(status)) {
              const link = node("a", "去登录 ↗");
              link.href = item.login_url;
              link.target = "_blank";
              link.rel = "noopener noreferrer";
              msgLine.append(" ", link);
            }
            row.append(msgLine);
          }
          return row;
        });

        activeProgress.replaceChildren(head, overallBar, ...sources);
      }

      const runRow = (run) => {
        const card = node("details", "", "rp-run");
        card.dataset.state = run.status;
        card.dataset.runId = run.id;
        const entries = Object.entries(run.progress || {});
        const totalJobs = entries.reduce((sum, [, item]) => sum + (Number(item.count) || 0), 0);
        const profileName = (meta.profiles || {})[run.profile] || "";
        const kwText = [run.keyword, profileName && run.profile !== "general" ? profileName : ""].filter(Boolean).join("、") || "采集任务";

        const head = node("summary", "", "rp-run-head");
        const statusDot = node("span", "", "rp-run-status-ico");
        statusDot.dataset.tone = statusTone(run.status);
        statusDot.append(icon(run.status === "complete" || run.status === "succeeded" ? "check" : "info"));
        const viewChip = node("span", "查看", "rp-run-view");
        head.append(
          statusDot,
          node("span", compactTime(run.started_at), "rp-run-date"),
          node("strong", kwText, "rp-run-kw"),
          node("span", run.city || "全国", "rp-run-city"),
          node("span", `${entries.length} 个平台`, "rp-run-platforms"),
          node("span", `共 ${totalJobs} 条`, "rp-run-total"),
          viewChip
        );
        card.append(head);

        const detailWrap = node("div", "", "rp-run-details");
        for (const [source, item] of entries) {
          const line = node("div", "", "rp-run-source");
          const itemStatus = run.status === "interrupted" && pendingStates.has(item.status)
            ? "interrupted" : item.status;
          const top = node("div", "", "rp-run-source-top");
          top.append(node("strong", sourceLabel((meta.collection_sources || {})[source]) || source));
          const loginNeeded = ["waiting_user", "login_required", "login_timeout"].includes(itemStatus) ||
            ["not_logged_in", "verification_required"].includes(item.detail_state);
          const loginUrl = loginNeeded && item.login_url;
          if (loginUrl || item.search_url) {
            const link = node("a", loginUrl ? "去登录 ↗" : "原站 ↗");
            link.href = loginUrl || item.search_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            top.append(link);
          }
          line.append(top);
          const message = node("p", itemStatus === "interrupted" ? statusNames[itemStatus] : (item.message || statusNames[itemStatus] || ""));
          message.dataset.state = itemStatus;
          line.append(message);
          if (item.details) line.append(node("p", `原站 JD 已读取 ${item.details.available} / ${item.details.total} 条`));
          detailWrap.append(line);
        }
        card.append(detailWrap);
        return card;
      };

      function paintHistory(items) {
        const expanded = new Set([...runsWrap.querySelectorAll(".rp-run[open]")].map(card => card.dataset.runId));
        const visible = showAllRuns ? items : items.slice(0, 3);
        const cards = visible.map(run => {
          const card = runRow(run);
          card.open = run.id === openRun || expanded.has(run.id);
          if (run.id === openRun) openRun = null;
          return card;
        });
        runsWrap.replaceChildren(...(cards.length ? cards : [node("p", "暂无采集记录。", "rp-hint")]));
        historyCount.textContent = `共 ${items.length} 条`;
        historyToggle.dataset.expanded = showAllRuns ? "1" : "0";
      }

      historyToggle.addEventListener("click", () => {
        showAllRuns = !showAllRuns;
        paintHistory(latestItems);
      });

      async function loadRuns() {
        clearTimeout(runPoll);
        const request = ++runRequest;
        try {
          const data = await api("/runs");
          if (request !== runRequest || !alive(token, body)) return;
          const items = data.items || [];
          latestItems = items;
          const snapshot = JSON.stringify(items);
          if (snapshot !== lastRuns || openRun) {
            const active = items.find(run => run.status === "running") || items.find(run => run.id === currentRun);
            if (active) currentRun = active.id;
            paintProgress(active);
            const focused = document.activeElement?.closest(".rp-run");
            paintHistory(items);
            lastRuns = snapshot;
            if (focused && !focused.isConnected) {
              runsWrap.querySelector(`[data-run-id="${focused.dataset.runId}"] > summary`)?.focus({ preventScroll: true });
            }
          }
          if (items.some((run) => run.status === "running")) runPoll = setTimeout(loadRuns, 1500);
          else void RP.refresh({ silent: true });
        } catch (error) {
          if (request === runRequest && alive(token, body)) {
            if (!lastRuns) runsWrap.replaceChildren(node("p", "暂时无法读取采集记录，正在重试。", "rp-hint"));
            runPoll = setTimeout(loadRuns, 5000);
          }
        }
      }

      body.append(hero, mainCard, activeProgress, historyCard);
      void loadRuns();
    }
  });

  /* ---------- 2. 规则清洗（cleaning，复用现有 cleaning 引擎） ---------- */
  RP.registerDrawer("cleaning", {
    title: "规则清洗配置", icon: "filter", tone: "accent",
    render(body) {
      const token = RP.drawerToken();
      const form = node("form", "", "rp-form rp-clean-form");

      /* 顶部标题区 */
      const hero = node("header", "", "rp-clean-hero");
      const heroIcon = node("span", "", "rp-clean-hero-icon");
      heroIcon.append(icon("filter"));
      const heroText = node("div", "", "rp-clean-hero-text");
      heroText.append(
        node("h2", "规则清洗配置"),
        node("p", "配置筛选条件，自动过滤不匹配的岗位")
      );
      hero.append(heroIcon, heroText);

      const profile = profileSelect(rememberedProfile());
      const profileRow = node("div", "", "rp-select-row rp-clean-profile");
      profile.setAttribute("aria-label", "清洗方向");
      profile.addEventListener("change", () => setRememberedProfile(profile.value));
      const profileSelectWrap = node("div", "", "rp-clean-profile-select");
      profileSelectWrap.append(inlineIcon("briefcase"), profile);
      profileRow.append(node("strong", "清洗方向"), profileSelectWrap);
      const fields = node("fieldset");
      const status = feedback();
      status.setAttribute("role", "status");

      function ruleGroup(title, subtitle, iconName, tone, decor) {
        const group = node("section", "", "rp-panel-section rp-clean-group");
        group.dataset.tone = tone;
        const head = node("div", "", "rp-clean-card-head");
        const iconTile = node("span", "", "rp-clean-card-icon");
        iconTile.dataset.tone = tone;
        iconTile.append(iconName === "briefcase" || iconName === "cap" ? inlineIcon(iconName) : icon(iconName));
        const copy = node("div", "", "rp-clean-card-copy");
        copy.append(node("h3", title));
        if (subtitle) copy.append(node("p", subtitle));
        head.append(iconTile, copy);
        if (decor) {
          const deco = node("span", "", "rp-clean-card-decor");
          deco.innerHTML = decor;
          head.append(deco);
        }
        group.append(head);
        return group;
      }

      const PAY_DECOR = '<svg viewBox="0 0 64 42" fill="none" aria-hidden="true"><rect x="34" y="6" width="22" height="28" rx="4" fill="#10b981" fill-opacity=".16"/><rect x="14" y="16" width="26" height="20" rx="4" fill="#10b981" fill-opacity=".22"/><circle cx="27" cy="26" r="5" fill="#10b981" fill-opacity=".3"/></svg>';
      const CITY_DECOR = '<svg viewBox="0 0 76 44" fill="none" aria-hidden="true"><path d="M12 42V22h10v20M26 42V12h12v30M42 42V6l4-4 4 4v36M54 42V18h12v24" fill="#3b82f6" fill-opacity=".16"/></svg>';

      const pay = ruleGroup("薪资与经验", "设置薪资范围和经验要求", "briefcase", "success", PAY_DECOR);
      const payBody = node("div", "", "rp-clean-card-body");
      const salaryGrid = node("div", "", "rp-panel-grid rp-clean-salary-range");
      const minSalary = input("number", { min: "0.01", max: "1000", step: "0.01", placeholder: "不限" });
      const maxSalary = input("number", { min: "0.01", max: "1000", step: "0.01", placeholder: "不限" });
      const expMax = input("number", { min: "1", max: "50", step: "1", placeholder: "不限" });
      salaryGrid.append(field("最低月薪 (K)", minSalary), field("最高月薪 (K)", maxSalary));
      const dailyPay = node("div", "", "rp-daily-pay");
      dailyPay.hidden = true;
      const dailyGrid = node("div", "", "rp-panel-grid rp-clean-salary-range");
      const minDaily = input("number", { min: "0.01", max: "100000", step: "0.01", placeholder: "不限" });
      const maxDaily = input("number", { min: "0.01", max: "100000", step: "0.01", placeholder: "不限" });
      dailyGrid.append(field("最低日薪 (元/天)", minDaily), field("最高日薪 (元/天)", maxDaily));
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
      experience.append(field("经验上限 (年)", expMax));
      payBody.append(salaryGrid, dailyPay, experience);
      pay.append(payBody);

      const splitTerms = (value) => value.split(/[,，、\n]+/).map((term) => term.trim()).filter(Boolean);
      function termsEditor(key, label, placeholder, iconName) {
        const wrap = node("div", "", "rp-terms");
        wrap.dataset.terms = key;
        const row = node("div", "", "rp-terms-input");
        const entry = input("text", { id: `rp-rule-${key}`, maxlength: "2500", placeholder });
        const add = button("添加", "rp-btn-sm rp-btn-ghost rp-terms-add", "plus");
        add.setAttribute("aria-label", `添加${label}`);
        const title = node("label", "", "rp-terms-label");
        if (iconName) title.append(inlineIcon(iconName));
        title.append(node("span", label));
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
      const cities = termsEditor("cities", "目标城市", "输入城市后回车", "pin");
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
      const qualifications = ruleGroup("城市与学历", "限定目标城市和学历要求", "cap", "info", CITY_DECOR);
      const qualBody = node("div", "", "rp-clean-card-body");
      const educationMode = select([["none", "不限岗位学历"], ["require", "按最低学历筛选"], ["exclude", "排除指定学历要求"]], "none");
      const educationField = node("label", "", "rp-field");
      const eduLabel = node("span", "", "rp-terms-label");
      eduLabel.id = "rp-education-label";
      eduLabel.append(inlineIcon("cap"), node("span", "岗位学历要求"));
      educationMode.setAttribute("aria-labelledby", "rp-education-label");
      educationField.append(eduLabel, educationMode);
      const educationHelp = node("p", "", "rp-education-help");
      educationHelp.id = "rp-education-help";
      educationMode.setAttribute("aria-describedby", educationHelp.id);
      const educationDescriptions = {
        none: "",
        require: "例如选「本科」，要求为「大专」的岗位会被淘汰。",
        exclude: "例如选「博士」，学历要求包含「博士」的岗位会被淘汰。"
      };
      function renderEducationMode() {
        requireEdu.hidden = educationMode.value !== "require";
        excludeEdu.hidden = educationMode.value !== "exclude";
        const help = educationDescriptions[educationMode.value];
        educationHelp.textContent = help;
        educationHelp.hidden = !help;
      }
      educationMode.addEventListener("change", renderEducationMode);
      renderEducationMode();
      qualBody.append(cities, educationField, educationHelp, requireEdu, excludeEdu, degreeOptions);
      qualifications.append(qualBody);

      /* 两列并排主卡片容器 */
      const topPair = node("div", "", "rp-clean-pair");
      topPair.append(pay, qualifications);

      const titleExcl = node("textarea");
      titleExcl.rows = 2; titleExcl.maxLength = 4100; titleExcl.placeholder = "例如 电话销售、保险代理";
      const companyExcl = node("textarea");
      companyExcl.rows = 2; companyExcl.maxLength = 4100; companyExcl.placeholder = "用逗号、顿号或换行分隔";
      const exclusions = node("details", "", "rp-panel-section rp-clean-exclusions");
      const exclusionHead = node("summary");
      const exclusionCount = node("span", "(0)", "rp-clean-exclusion-count");
      exclusionHead.append(inlineIcon("ban", "rp-clean-ban-ico"), node("strong", "排除词"), exclusionCount, icon("chevron-down"));
      const exclusionFields = node("div", "", "rp-panel-grid rp-clean-exclusion-fields");
      exclusionFields.append(field("岗位标题排除词", titleExcl), field("公司排除词", companyExcl));
      exclusions.append(exclusionHead, exclusionFields);
      function renderExclusionCount() {
        const count = splitTerms(titleExcl.value).length + splitTerms(companyExcl.value).length;
        exclusionCount.textContent = `(${count})`;
      }
      exclusionFields.addEventListener("input", renderExclusionCount);
      renderExclusionCount();

      const auto = input("checkbox");
      auto.checked = false;
      const autoLabel = node("label", "", "rp-inline-check rp-clean-auto");
      autoLabel.hidden = true;
      autoLabel.append(auto, document.createTextNode("新采集或导入的岗位自动执行该规则"));

      /* AI 初筛规则 */
      const scout = node("section", "", "rp-panel-section rp-clean-scout");
      const scoutHead = node("div", "", "rp-scout-head");
      const scoutTitle = node("h3", "AI 初筛规则");
      scoutTitle.prepend(icon("sparkles"));
      const scoutAdd = button("添加规则", "rp-btn-sm rp-btn-ghost rp-scout-add-btn", "plus");
      scoutHead.append(scoutTitle, scoutAdd);
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
      const SCOUT_ICONS = ["code", "layers", "monitor"];
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
          desc: row.querySelector(".rp-scout-standard").value.trim()
        };
      }
      function scoutRow(rule = { keyword: "", condition: "never", desc: "" }, idx = 0) {
        const row = node("details", "", "rp-scout-row");
        if (rule.legacy) row.dataset.legacy = rule.legacy;
        const heading = node("summary");
        const iconName = SCOUT_ICONS[idx % SCOUT_ICONS.length];
        const rowIcon = node("span", "", "rp-scout-row-icon");
        rowIcon.append(iconName === "layers" ? icon("layers") : inlineIcon(iconName));
        const name = node("strong", rule.keyword || "新规则");
        const constraint = node("small", conditionLabel(rule.condition), "rp-scout-condition");
        constraint.dataset.condition = rule.condition;
        const chevron = icon("chevron-down");
        chevron.classList.add("rp-scout-chevron");
        heading.append(inlineIcon("grip", "rp-scout-grip"), rowIcon, name, constraint, chevron);
        const editor = node("div", "", "rp-scout-editor");
        const controls = node("div", "", "rp-scout-controls");
        const keyword = input("text", { maxlength: "240", placeholder: "规则词，例如 单休" });
        keyword.value = rule.keyword;
        const condition = select([["must", "必须包含"], ["never", "绝不包含"]], rule.condition);
        controls.append(field("规则词", keyword), field("判定条件", condition));
        const assistant = node("div", "", "rp-scout-assistant");
        const intent = node("textarea", "", "rp-scout-intent");
        intent.rows = 2; intent.maxLength = 600;
        const desc = node("textarea", "", "rp-scout-standard");
        desc.rows = 4; desc.maxLength = 600; desc.value = rule.desc;
        desc.placeholder = "由 AI 生成，也可直接填写 JD 中什么情况算命中。";
        const actions = node("div", "", "rp-scout-actions");
        const footer = node("div", "", "rp-scout-footer");
        const generate = button("AI 生成标准", "rp-btn-sm rp-btn-accent", "sparkles");
        const remove = button("删除规则", "rp-btn-sm rp-btn-ghost rp-scout-remove", "trash");
        const rowStatus = feedback();
        rowStatus.setAttribute("role", "status");
        function updateCondition() {
          constraint.textContent = conditionLabel(condition.value);
          constraint.dataset.condition = condition.value;
          intent.placeholder = condition.value === "must"
            ? "例如：希望岗位主要做 Agent 开发，偶尔调用大模型接口不算。"
            : "例如：不想做以服务端开发为主的岗位，仅与后端团队对接可以接受。";
        }
        updateCondition();
        row.addEventListener("input", (event) => {
          if (event.target === intent) return;
          delete row.dataset.legacy;
          name.textContent = keyword.value.trim() || "新规则";
          if (event.target === condition) updateCondition();
        });
        remove.addEventListener("click", () => { row.remove(); resetPreview(); scoutAdd.focus(); });
        generate.addEventListener("click", async () => {
          const current = readScout(row);
          if (!current.keyword) { setFeedback(rowStatus, "请先填写规则词。", "error"); keyword.focus(); return; }
          const draft = intent.value.trim();
          generate.disabled = true;
          setFeedback(rowStatus, "正在生成判定标准…");
          try {
            const result = await api("/cleaning/describe", {
              keyword: current.keyword, condition: current.condition, intent: draft
            });
            if (!row.isConnected) return;
            const latest = readScout(row);
            if (fields.disabled) {
              setFeedback(rowStatus, "规则正在处理，请稍后重新生成。", "error");
            } else if (draft === intent.value.trim() && Object.keys(current).every((key) => current[key] === latest[key])) {
              desc.value = result.desc;
              delete row.dataset.legacy;
              resetPreview();
              setFeedback(rowStatus, "已生成，可继续编辑。", "success");
            } else setFeedback(rowStatus, "生成期间规则已变更，请重新生成。", "error");
          } catch (error) {
            setFeedback(rowStatus, error.message, "error");
          } finally { generate.disabled = false; }
        });
        actions.append(rowStatus, generate);
        assistant.append(field("筛选意图（选填）", intent), actions);
        footer.append(remove);
        editor.append(controls, assistant, field("判定标准", desc), footer);
        row.append(heading, editor);
        return row;
      }
      scoutAdd.addEventListener("click", () => {
        if (scoutList.children.length >= 24) { setFeedback(status, "每个方向最多保存 24 条 AI 初筛规则。", "error"); return; }
        exampleNotice.hidden = true;
        const row = scoutRow(undefined, scoutList.children.length);
        row.open = true;
        scoutList.append(row);
        row.querySelector("input").focus();
      });
      exampleEnable.addEventListener("click", () => {
        scoutList.replaceChildren(...examples.map((rule, i) => scoutRow(rule, i)));
        exampleNotice.hidden = true;
        resetPreview();
        const first = scoutList.firstElementChild;
        if (first) { first.open = true; first.querySelector("input").focus(); }
      });
      scout.append(scoutHead, exampleNotice, scoutList);

      /* 操作与预览 */
      const actions = node("div", "", "rp-clean-actions");
      const saveBtn = button("保存规则", "rp-btn-primary rp-clean-save-btn", "check");
      const previewBtn = button("预览现有岗位", "rp-clean-preview-btn", "eye");
      previewBtn.type = "submit";
      const applyBtn = button("应用到现有岗位", "rp-btn-primary rp-clean-save-btn", "check");
      applyBtn.disabled = true;
      applyBtn.hidden = true;
      const actionRow = node("div", "", "rp-panel-actions");
      actionRow.append(previewBtn, saveBtn, applyBtn);
      const previewList = node("div", "", "rp-rule-preview");
      previewList.hidden = true;
      actions.append(status, actionRow);

      fields.append(topPair, exclusions, scout, autoLabel, previewList, actions);
      form.append(hero, profileRow, fields);
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
        auto.checked = false;
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
      form.addEventListener("input", (event) => {
        if (!event.target.classList.contains("rp-scout-intent")) resetPreview();
      });
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
      readiness.classList.add("rp-eval-readiness");
      const form = node("form", "", "rp-form");
      const settingsSection = section("八维评估权重", "sliders", "accent");
      const weights = node("div", "", "rp-weights");
      const weightInputs = new Map();
      const weightMeters = new Map();
      const weightShares = new Map();
      const WEIGHT_PRESETS = [
        ["实习/校招", { role_match: 5, skills_align: 5, seniority: 2, compensation: 2, interview_prob: 4, company_stage: 1, market_fit: 4, growth: 4 }],
        ["正式工作", { role_match: 5, skills_align: 5, seniority: 4, compensation: 4, interview_prob: 4, company_stage: 2, market_fit: 3, growth: 3 }],
        ["均衡默认", { role_match: 5, skills_align: 5, seniority: 4, compensation: 4, interview_prob: 4, company_stage: 1, market_fit: 2, growth: 2 }]
      ];
      function paintMeters() {
        let sum = 0;
        for (const number of weightInputs.values()) {
          const val = Number(number.value);
          if (Number.isFinite(val) && val > 0) sum += val;
        }
        for (const [key, number] of weightInputs) {
          const value = Number(number.value);
          const safe = Number.isFinite(value) ? Math.min(5, Math.max(0, value)) : 0;
          weightMeters.get(key).style.width = ((safe / 5) * 100) + "%";
          const pct = sum > 0 ? Math.round((safe / sum) * 100) : 0;
          weightShares.get(key).textContent = `${pct}%`;
        }
      }
      const presetBar = node("div", "", "rp-weight-presets");
      for (const [presetLabel, presetValues] of WEIGHT_PRESETS) {
        const presetBtn = button(presetLabel, "rp-btn-sm rp-btn-ghost");
        presetBtn.addEventListener("click", () => {
          for (const [key, number] of weightInputs) number.value = String(presetValues[key] ?? 3);
          paintMeters();
        });
        presetBar.append(presetBtn);
      }
      for (const [key, label] of Object.entries(DIMENSION_LABELS)) {
        const number = input("number", { min: "0", max: "5", step: "1", required: "required" });
        weightInputs.set(key, number);
        const [iconName, tone] = DIMENSION_META[key] || ["sliders", "accent"];
        const wrap = node("label", "", "rp-weight-cell");
        wrap.dataset.tone = tone;
        const top = node("div", "", "rp-weight-top");
        const head = node("span", "", "rp-weight-head");
        const share = node("span", "0%", "rp-weight-share");
        weightShares.set(key, share);
        head.append(tile(iconName, tone, true), node("span", label, "rp-weight-name"), share);
        top.append(head, number);
        const meter = node("i", "", "rp-weight-meter");
        const fill = node("b");
        meter.append(fill);
        weightMeters.set(key, fill);
        number.addEventListener("input", paintMeters);
        wrap.append(top, meter);
        weights.append(wrap);
      }
      const heuristic = input("checkbox");
      const heuristicLabel = node("label", "", "rp-inline-check");
      heuristicLabel.append(heuristic, document.createTextNode("启发式评估（按规则打分和诊断）"));
      const saveBtn = button("保存评估配置", "", "check");
      saveBtn.type = "submit";
      const settingsFeedback = feedback();
      const saveRow = node("div", "", "rp-panel-actions rp-eval-saverow");
      saveRow.append(heuristicLabel, saveBtn);
      settingsSection.append(
        node("p", "权重 0–5 整数（自动按占比换算百分制）；A ≥ 85 · B ≥ 70 · C ≥ 55 · D ≥ 40。", "rp-hint"),
        presetBar,
        weights, saveRow, settingsFeedback
      );
      form.append(settingsSection);

      const runSection = section("批量评估", "play", "info");
      runSection.append(node("p", "清洗通过与待重评岗位先做八维评级；达精投阈值自动深评，其余进海投。解析失败保留待重试。", "rp-hint"));
      const runFeedback = feedback();
      const runBtn = button("运行 AI 评估", "rp-btn-accent rp-eval-run-btn", "play");
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
          chip.dataset.grade = grade;
          chip.append(document.createTextNode(grade + " 级 "), node("b", String(count)));
          chips.push(chip);
        }
        const trackChip = node("span", "", "rp-stat-chip");
        trackChip.append(document.createTextNode("精投 "), node("b", String(custom)), document.createTextNode(" · 海投 "), node("b", String(mass)));
        chips.push(trackChip);
        stats.replaceChildren(...(scored ? chips : [node("span", "暂无已评分岗位", "rp-stat-chip")]));
      }
      paintStats();
      const runRow = node("div", "", "rp-panel-actions rp-eval-runrow");
      runRow.append(runBtn, stats);
      runSection.append(runRow, runFeedback);
      body.append(readiness, form, runSection);
      const paintList = appendEvaluationDetails(body, token);

      let loadSeq = 0;
      function showConfig(data) {
        const settings = data.settings || {};
        const rawWeights = settings.evaluation_weights || {};
        const values = Object.values(rawWeights).map(Number).filter(Number.isFinite);
        const isLegacyScale = values.length > 0 && Math.max(...values) <= 1;
        for (const [key, number] of weightInputs) {
          const val = rawWeights[key] ?? 3;
          number.value = String(isLegacyScale ? Math.round(Number(val) * 5) : Math.round(Number(val)));
        }
        paintMeters();
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
    const gate = section("分流阈值与投递白名单", "target", "brass");
    const threshold = select([["A", "A 级（仅 A 走精投）"], ["B", "B 级（A/B 走精投，默认）"], ["C", "C 级（A/B/C 走精投）"]], "B");
    const gradeBoxes = new Map();
    const gradeRow = node("div", "", "rp-grade-chips");
    gradeRow.setAttribute("role", "group");
    gradeRow.setAttribute("aria-label", "自动投递等级白名单");
    for (const grade of GRADE_OPTIONS) {
      const chip = node("button", grade + " 级", "rp-grade-chip");
      chip.type = "button";
      chip.dataset.grade = grade;
      chip.setAttribute("aria-pressed", "false");
      chip.addEventListener("click", () => {
        chip.setAttribute("aria-pressed", String(chip.getAttribute("aria-pressed") !== "true"));
      });
      gradeBoxes.set(grade, chip);
      gradeRow.append(chip);
    }
    const gateFeedback = feedback();
    const gateSave = button("保存阈值配置", "", "check");
    gateSave.addEventListener("click", async () => {
      const autoDeliver = [...gradeBoxes].filter(([, chip]) => chip.getAttribute("aria-pressed") === "true").map(([grade]) => grade);
      if (!autoDeliver.length) { setFeedback(gateFeedback, "自动投递等级白名单不能为空。", "error"); return; }
      gateSave.disabled = true;
      try {
        await saveConfig({ threshold: threshold.value, auto_deliver_grades: autoDeliver }, gateFeedback, "阈值配置已保存。");
        if (alive(token, body)) setFeedback(gateFeedback, "阈值配置已保存。", "success");
      } catch (error) {
        if (alive(token, body)) setFeedback(gateFeedback, error.message, "error");
      } finally { gateSave.disabled = false; }
    });
    const gateRow = node("div", "", "rp-panel-actions rp-eval-saverow");
    gateRow.append(gradeRow, gateSave);
    gate.append(field("精投分流阈值", threshold),
      node("p", "海投自动投递白名单：白名单外评级与解析失败件拦截进审批。", "rp-hint"),
      gateRow, gateFeedback);

    const listSection = section("深评记录", "eye", "success");
    listSection.classList.add("rp-deep-section");
    const list = node("div", "", "rp-deep-list");
    const detail = node("div", "", "rp-deep-keys");
    const DEEP_CARD_ICONS = [
      ["layers", "blue"],
      ["code", "green"],
      ["monitor", "blue"],
      ["bolt", "green"],
      ["grid", "blue"]
    ];
    const DEEP_KEY_ICONS = {
      extracted_skills: ["layers", "green"],
      ats_ability_analysis: ["chart", "green"],
      resume_audit: ["doc", "blue"],
      dream_picture: ["briefcase", "blue"],
      strong_fit_assessment: ["bolt", "teal"],
      risk_red_flags: ["ban", "amber"],
      deep_action_plan: ["chart", "indigo"]
    };
    let activeJobKey = "";

    function extractSkillChips(value) {
      if (Array.isArray(value)) {
        const items = value.map((v) => String(v || "").trim()).filter(Boolean);
        return items.length && items.every((s) => s.length <= 24) ? items.slice(0, 16) : null;
      }
      if (typeof value === "string") {
        const cleaned = value.trim();
        if (!cleaned || cleaned.length > 260) return null;
        const parts = cleaned
          .replace(/^[\s•·\-*]+/gm, "")
          .split(/[,，、;；\n|]+/)
          .map((s) => s.trim())
          .filter((s) => s && s.length <= 24);
        return parts.length >= 2 ? [...new Set(parts)].slice(0, 16) : null;
      }
      return null;
    }

    function paintList() {
      const jobs = state.jobs.filter(job => job.hasDeep).slice(0, 8);
      if (!jobs.length) {
        list.replaceChildren(emptyBlock("暂无深评记录", "运行 AI 评估后，可在这里查看精投岗位的诊断。"));
        return;
      }
      list.replaceChildren(...jobs.map((job, idx) => {
        const keyId = `${job.source}:${job.url_key || job.url}`;
        const [cardIcon, iconTone] = DEEP_CARD_ICONS[idx % DEEP_CARD_ICONS.length];
        const card = node("article", "", "rp-deep-card");
        card.dataset.active = keyId === activeJobKey ? "1" : "0";

        const avatar = node("span", "", "rp-deep-avatar");
        avatar.dataset.tone = iconTone;
        avatar.append(cardIcon === "layers" ? icon("layers") : inlineIcon(cardIcon));

        const mid = node("div", "", "rp-deep-mid");
        mid.append(node("strong", job.title, "rp-deep-title"));

        const metaRow = node("div", "", "rp-deep-meta");
        const companyText = [job.company || "未知公司", RP.sourceLabel(job.source)].filter(Boolean).join(" · ");
        const companySpan = node("span", "", "rp-deep-meta-item");
        companySpan.append(inlineIcon("briefcase"), node("span", companyText));
        metaRow.append(companySpan);
        if (job.salary) {
          const salSpan = node("span", "", "rp-deep-meta-item");
          salSpan.append(icon("banknote"), node("span", job.salary));
          metaRow.append(node("i", "", "rp-deep-sep"), salSpan);
        }
        if (job.score != null) {
          const scoreSpan = node("span", "", "rp-deep-meta-item");
          scoreSpan.append(inlineIcon("chart"), node("span", `${job.score} 分`));
          metaRow.append(node("i", "", "rp-deep-sep"), scoreSpan);
        }

        const view = button("查看七维分析", "rp-deep-view-btn", "eye");
        mid.append(metaRow, view);

        const right = node("div", "", "rp-deep-right");
        if (job.grade) right.append(gradeBadge(job.grade));
        right.append(node("span", "›", "rp-deep-arrow"));

        const openDeep = async () => {
          if (view.disabled) return;
          activeJobKey = keyId;
          for (const el of list.querySelectorAll(".rp-deep-card")) {
            el.dataset.active = el === card ? "1" : "0";
          }
          view.disabled = true;
          detail.replaceChildren(node("p", "正在读取七维分析…", "rp-hint"));
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
              const [kIcon, kTone] = DEEP_KEY_ICONS[key] || ["layers", "green"];
              const fold = node("details", "", "rp-deep-key");
              if (key === "extracted_skills") fold.open = true;
              const sum = node("summary", "", "rp-deep-key-head");
              const ico = node("span", "", "rp-deep-key-ico");
              ico.dataset.tone = kTone;
              ico.append(kIcon === "layers" ? icon("layers") : inlineIcon(kIcon));
              sum.append(ico, node("strong", label), node("span", "›", "rp-deep-key-chevron"));
              fold.append(sum);
              const skillChips = key === "extracted_skills" ? extractSkillChips(value) : null;
              if (skillChips) {
                const chipBox = node("div", "", "rp-deep-skills");
                const chipIcons = ["code", "layers", "chart", "code", "grid"];
                skillChips.forEach((skill, sIdx) => {
                  const pill = node("span", "", "rp-deep-skill-pill");
                  const cName = chipIcons[sIdx % chipIcons.length];
                  pill.append(cName === "layers" ? icon("layers") : inlineIcon(cName), node("span", skill));
                  chipBox.append(pill);
                });
                fold.append(chipBox);
              } else {
                const doc = node("div", "", "rp-doc");
                RP.renderDoc(doc, RP.payloadText(value));
                fold.append(doc);
              }
              detail.append(fold);
            }
            if (!detail.childNodes.length) detail.append(note("深评结果为空。", "warning"));
            detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
          } catch (error) {
            if (alive(token, body)) detail.replaceChildren(note(error.message, "danger"));
          } finally { view.disabled = false; }
        };
        view.addEventListener("click", (event) => { event.stopPropagation(); void openDeep(); });
        card.addEventListener("click", () => { void openDeep(); });
        card.append(avatar, mid, right);
        return card;
      }));
    }
    paintList();
    listSection.append(list, detail);
    body.append(gate, listSection);

    loadConfig().then((data) => {
      if (!alive(token, body)) return;
      threshold.value = data.settings?.threshold || "B";
      const allowed = data.settings?.auto_deliver_grades || ["C", "D", "F"];
      for (const [grade, chip] of gradeBoxes) chip.setAttribute("aria-pressed", String(allowed.includes(grade)));
    }).catch(() => {});
    return paintList;
  }


})();
