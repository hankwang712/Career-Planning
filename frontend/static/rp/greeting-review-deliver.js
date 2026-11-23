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

  /* ---------- 6. 打招呼语（greeting，原始母本 + JD 关键词微调 + 聊天预览工作台） ---------- */
  RP.registerDrawer("greeting", {
    title: "打招呼语 · 聊天预览", icon: "message", tone: "success",
    render(body, ctx) {
      const token = RP.drawerToken();
      const SAMPLE_BASE = "您好，看到贵司正在招聘相关实习岗位，我目前在读计算机/人工智能方向，熟悉 Python、大模型应用与多智能体系统开发，曾主导过 RAG 混合检索与多智能体编排项目并取得明确指标提升。我的项目背景与岗位方向高度契合，每周可实习 5 天，完整简历已备妥，期待与您进一步沟通！";

      /* 1. 可折叠「原始打招呼语（母本）」卡片 */
      const baseCard = node("div", "", "rp-gr-card rp-gr-base");
      const baseHead = node("div", "", "rp-gr-base-head");
      const baseTitleWrap = node("div", "", "rp-gr-base-title");
      const baseTitle = node("strong", "原始打招呼语（母本）");
      const baseBadge = node("span", "加载中…", "rp-gr-badge");
      baseTitleWrap.append(icon("pen"), baseTitle, baseBadge);
      const baseToggle = button("展开编辑", "rp-btn-sm rp-btn-ghost");
      baseHead.append(baseTitleWrap, baseToggle);

      const baseBody = node("div", "", "rp-gr-base-body");
      const master = node("textarea", "", "rp-gr-textarea");
      master.rows = 4; master.maxLength = 2000;
      master.placeholder = "输入你平时习惯用的原始打招呼语；AI 将严格以此为底稿，结合目标岗位 JD 关键词做定向微调（不推倒重写）。";
      const baseFoot = node("div", "", "rp-gr-base-foot");
      const baseCount = node("span", "0 字", "rp-gr-count");
      const baseBtns = node("div", "", "rp-gr-btn-row");
      const fillSampleBtn = button("填入参考模板", "rp-btn-sm rp-btn-ghost");
      const masterSave = button("保存母本", "rp-btn-sm rp-btn-primary", "check");
      baseBtns.append(fillSampleBtn, masterSave);
      baseFoot.append(baseCount, baseBtns);
      const masterFeedback = feedback();
      baseBody.append(master, baseFoot, masterFeedback);
      baseCard.append(baseHead, baseBody);

      let baseOpen = false;
      function syncBaseUI(expandOverride) {
        const len = master.value.replace(/\s/g, "").length;
        baseCount.textContent = `${len} 字`;
        if (len > 0) {
          baseBadge.textContent = `已配置 · ${len} 字 · 按 JD 微调`;
          baseBadge.dataset.state = "ok";
        } else {
          baseBadge.textContent = "未配置（留空则由 AI 按简历起草）";
          baseBadge.dataset.state = "empty";
        }
        if (typeof expandOverride === "boolean") baseOpen = expandOverride;
        baseBody.hidden = !baseOpen;
        baseToggle.textContent = baseOpen ? "收起" : (len > 0 ? "编辑母本" : "填写母本");
      }
      baseToggle.addEventListener("click", () => syncBaseUI(!baseOpen));
      master.addEventListener("input", () => syncBaseUI());
      fillSampleBtn.addEventListener("click", () => {
        master.value = SAMPLE_BASE;
        syncBaseUI(true);
        master.focus();
      });
      masterSave.addEventListener("click", async () => {
        masterSave.disabled = true;
        try {
          await saveConfig({ mass_greeting: master.value }, masterFeedback, "原始打招呼语已保存。");
          if (alive(token, body)) {
            setFeedback(masterFeedback, "原始打招呼语已保存。", "success");
            syncBaseUI(false);
          }
        } catch (error) {
          if (alive(token, body)) setFeedback(masterFeedback, error.message, "error");
        } finally { masterSave.disabled = false; }
      });

      /* 2. 目标岗位 + 风格切换 + 生成控制 + 进度条 */
      const ctrlCard = node("div", "", "rp-gr-card");
      const jobRow = node("div", "", "rp-gr-ctrl-row");
      const jobSelect = node("select", "", "rp-gr-select");
      jobRow.append(jobSelect);

      const styleRow = node("div", "", "rp-gr-style-row");
      const styleLabel = node("span", "微调风格", "rp-gr-style-label");
      const styleGroup = node("div", "", "rp-gr-seg");
      let currentStyle = "standard";
      const styleBtns = [
        ["standard", "标准微调"],
        ["concise", "精炼直击"],
        ["project", "突出项目"],
      ].map(([key, label]) => {
        const b = node("button", label, "rp-gr-seg-btn");
        b.type = "button";
        b.dataset.style = key;
        if (key === currentStyle) b.dataset.active = "1";
        b.addEventListener("click", () => {
          currentStyle = key;
          styleBtns.forEach((btn) => { btn.dataset.active = btn.dataset.style === key ? "1" : "0"; });
        });
        return b;
      });
      styleGroup.append(...styleBtns);
      styleRow.append(styleLabel, styleGroup);

      const actionRow = node("div", "", "rp-gr-actions");
      const oneBtn = button("微调当前岗位", "rp-rw-primary-btn", "sparkles");
      const batchBtn = button("批量生成全部", "rp-btn-ghost", "play");
      actionRow.append(oneBtn, batchBtn);

      const progressWrap = node("div", "", "rp-rw-progress");
      progressWrap.hidden = true;
      const progressHead = node("div", "", "rp-rw-prog-head");
      const progressText = node("span", "");
      const progressPct = node("span", "0%", "rp-rw-prog-meta");
      progressHead.append(progressText, progressPct);
      const progressTrack = node("div", "", "rp-rw-prog-track");
      const progressFill = node("div", "", "rp-rw-prog-bar");
      progressTrack.append(progressFill);
      progressWrap.append(progressHead, progressTrack);
      const runFeedback = feedback();
      ctrlCard.append(jobRow, styleRow, actionRow, progressWrap, runFeedback);

      let progressTimer = null;
      function startProgress(label) {
        clearInterval(progressTimer);
        let pct = 14;
        progressWrap.hidden = false;
        progressText.textContent = label;
        progressPct.textContent = `${pct}%`;
        progressFill.style.width = `${pct}%`;
        progressTimer = setInterval(() => {
          pct = Math.min(90, pct + (pct < 55 ? 8 : 3));
          progressPct.textContent = `${pct}%`;
          progressFill.style.width = `${pct}%`;
        }, 450);
      }
      function endProgress(doneText) {
        clearInterval(progressTimer);
        progressText.textContent = doneText;
        progressPct.textContent = "100%";
        progressFill.style.width = "100%";
        setTimeout(() => { if (alive(token, body)) progressWrap.hidden = true; }, 1100);
      }

      /* 3. 拟真聊天预览 + JD 关键词命中 + 行内微调保存 */
      const previewCard = node("div", "", "rp-gr-card rp-gr-preview-card");
      const pvHead = node("div", "", "rp-gr-pv-head");
      const pvTitle = node("strong", "聊天预览");
      const pvMode = node("span", "", "rp-gr-mode");
      pvHead.append(pvTitle, pvMode);

      const chatStage = node("div", "", "rp-gr-chat");
      const chatMeta = node("div", "", "rp-gr-chat-meta");
      const bubble = node("div", "", "rp-gr-bubble");
      const editArea = node("textarea", "", "rp-gr-textarea rp-gr-edit-area");
      editArea.rows = 6; editArea.maxLength = 2000; editArea.hidden = true;
      chatStage.append(chatMeta, bubble, editArea);

      const kwRow = node("div", "", "rp-gr-kw-row");
      kwRow.hidden = true;

      const qualityBar = node("div", "", "rp-gr-quality");
      const qualityCount = node("span", "", "rp-gr-q-pill");
      const qualityGate = node("span", "", "rp-gr-q-pill");
      qualityBar.append(qualityCount, qualityGate);

      const pvActions = node("div", "", "rp-gr-pv-actions");
      const copyBtn = button("复制欢迎语", "rp-btn-sm rp-btn-primary", "copy");
      const editBtn = button("编辑微调", "rp-btn-sm rp-btn-ghost", "pen");
      const saveEditBtn = button("保存修改", "rp-btn-sm rp-btn-primary", "check");
      const cancelEditBtn = button("取消", "rp-btn-sm rp-btn-ghost");
      saveEditBtn.hidden = true;
      cancelEditBtn.hidden = true;
      pvActions.append(copyBtn, editBtn, saveEditBtn, cancelEditBtn);

      const emptyPreview = emptyBlock("暂无打招呼语", "选择岗位后点击「微调当前岗位」，或点击「批量生成全部」。");
      previewCard.append(pvHead, emptyPreview, chatStage, kwRow, qualityBar, pvActions);

      let selectedJob = null;
      let currentGreeting = null;
      let editing = false;

      function candidateJobs() {
        const ready = state.jobs.filter((job) =>
          job.hasGreeting || ["rewritten", "deep", "approval", "queued", "delivered", "screened"].includes(job.stage)
        );
        return ready.slice(0, 40);
      }

      function modeLabel(mode) {
        return {
          llm_base: "AI 基于母本微调",
          llm: "AI 定向生成",
          heuristic_base: "母本关键词微调",
          manual_edit: "人工微调已保存",
          manual: "人工母本",
          heuristic: "本地模板",
        }[mode] || "已生成";
      }

      function setEditMode(on) {
        editing = on;
        bubble.hidden = on;
        editArea.hidden = !on;
        editBtn.hidden = on;
        copyBtn.hidden = on;
        saveEditBtn.hidden = !on;
        cancelEditBtn.hidden = !on;
        if (on) {
          editArea.value = RP.payloadText(currentGreeting) || "";
          editArea.focus();
        }
      }

      function renderPreview(job, greeting) {
        currentGreeting = greeting;
        setEditMode(false);
        const text = RP.payloadText(greeting);
        const hasText = Boolean(text.trim());
        emptyPreview.hidden = hasText;
        chatStage.hidden = !hasText;
        qualityBar.hidden = !hasText;
        pvActions.hidden = !hasText;
        pvTitle.textContent = job ? `${job.title || "目标岗位"} · ${job.company || ""}` : "聊天预览";
        if (!hasText) {
          pvMode.textContent = "待生成";
          pvMode.dataset.tone = "muted";
          kwRow.hidden = true;
          return;
        }
        pvMode.textContent = modeLabel(greeting && greeting.mode);
        pvMode.dataset.tone = (greeting && greeting.mode && greeting.mode.startsWith("llm")) ? "ai" : "ok";
        chatMeta.textContent = `发送给 ${job?.company || "目标公司"} HR · 首屏预览`;
        bubble.textContent = text;

        const kws = Array.isArray(greeting?.matched_keywords) ? greeting.matched_keywords : [];
        if (kws.length) {
          kwRow.hidden = false;
          const lower = text.toLowerCase();
          kwRow.replaceChildren(
            node("span", "JD 命中词：", "rp-gr-kw-label"),
            ...kws.map((kw) => {
              const hit = lower.includes(String(kw).toLowerCase());
              const chip = node("span", kw, "rp-gr-kw-chip");
              chip.dataset.hit = hit ? "1" : "0";
              return chip;
            })
          );
        } else {
          kwRow.hidden = true;
        }

        const len = text.replace(/\s/g, "").length;
        const illegal = !text.trim() || /❌|生成失败/.test(text) || (greeting && greeting.legal === false);
        qualityCount.textContent = `${len} 字${len >= 80 && len <= 480 ? " · 篇幅正常" : len < 80 ? " · 偏短" : " · 偏长"}`;
        qualityCount.dataset.tone = (len >= 80 && len <= 480) ? "ok" : "warn";
        qualityGate.textContent = illegal ? "未通过合规检查" : "合规 · 可直接发送";
        qualityGate.dataset.tone = illegal ? "err" : "ok";
        copyBtn.disabled = illegal;
      }

      async function loadSelectedJob() {
        const jobs = candidateJobs();
        const idx = Number(jobSelect.value);
        selectedJob = Number.isInteger(idx) && jobs[idx] ? jobs[idx] : jobs[0] || null;
        oneBtn.disabled = !selectedJob;
        if (!selectedJob) {
          renderPreview(null, null);
          return;
        }
        try {
          const payload = await RP.fetchJobPayload(selectedJob);
          if (!alive(token, body)) return;
          renderPreview(selectedJob, payloadOf(payload, "greeting_payload", "greeting"));
        } catch (error) {
          if (alive(token, body)) toast(error.message, "error");
        }
      }

      function populateJobs(preserveKey) {
        const jobs = candidateJobs();
        const prevKey = preserveKey || (selectedJob ? `${selectedJob.source}::${selectedJob.url_key}` : "");
        jobSelect.replaceChildren();
        if (!jobs.length) {
          const opt = node("option", "暂无可生成打招呼语的岗位（请先完成初筛或深评）");
          opt.value = "";
          jobSelect.append(opt);
          oneBtn.disabled = true;
          renderPreview(null, null);
          return;
        }
        let matchIdx = 0;
        jobs.forEach((job, i) => {
          const tag = job.hasGreeting ? "✓" : "○";
          const grade = job.grade ? ` [${job.grade}]` : "";
          const opt = node("option", `${tag} ${job.title || "未命名岗位"} · ${job.company || ""}${grade}`);
          opt.value = String(i);
          if (`${job.source}::${job.url_key}` === prevKey) matchIdx = i;
          jobSelect.append(opt);
        });
        jobSelect.value = String(matchIdx);
        void loadSelectedJob();
      }

      jobSelect.addEventListener("change", () => { void loadSelectedJob(); });
      copyBtn.addEventListener("click", () => copyText(RP.payloadText(currentGreeting), "打招呼语已复制到剪贴板。"));
      editBtn.addEventListener("click", () => setEditMode(true));
      cancelEditBtn.addEventListener("click", () => setEditMode(false));

      saveEditBtn.addEventListener("click", async () => {
        if (!selectedJob) return;
        const nextText = editArea.value.trim();
        if (!nextText) { toast("打招呼语不能为空。", "error"); return; }
        saveEditBtn.disabled = true;
        try {
          const data = await pipelineApi("/greeting/save", {
            source: selectedJob.source,
            url_key: selectedJob.url_key,
            text: nextText,
          });
          if (!alive(token, body)) return;
          renderPreview(selectedJob, data.greeting);
          toast("微调后的打招呼语已保存。", "success");
          void RP.refresh({ silent: true });
        } catch (error) {
          if (alive(token, body)) toast(error.message, "error");
        } finally { saveEditBtn.disabled = false; }
      });

      oneBtn.addEventListener("click", async () => {
        if (!selectedJob) return;
        oneBtn.disabled = true; batchBtn.disabled = true;
        startProgress(master.value.trim() ? "正在提取 JD 关键词并基于母本微调…" : "正在结合简历与 JD 生成打招呼语…");
        try {
          const data = await pipelineApi("/run", {
            stage: "greet",
            source: selectedJob.source,
            url_key: selectedJob.url_key,
            style: currentStyle,
          });
          if (!alive(token, body)) return;
          endProgress("微调完成");
          renderPreview(selectedJob, data.greeting);
          setFeedback(runFeedback, `已为「${selectedJob.title}」完成定向微调。`, "success");
          await RP.refresh({ silent: true });
          populateJobs(`${selectedJob.source}::${selectedJob.url_key}`);
        } catch (error) {
          if (alive(token, body)) {
            clearInterval(progressTimer);
            progressWrap.hidden = true;
            setFeedback(runFeedback, error.message, "error");
          }
        } finally { oneBtn.disabled = false; batchBtn.disabled = false; }
      });

      batchBtn.addEventListener("click", async () => {
        oneBtn.disabled = true; batchBtn.disabled = true;
        startProgress("正在批量生成候选岗位的打招呼语…");
        try {
          const result = await RP.runStage("greet");
          if (!alive(token, body)) return;
          endProgress("批量生成完成");
          const msg = RP.stageResultMessage(result, "打招呼语");
          setFeedback(runFeedback, msg, "success");
          toast(msg, "success");
          await RP.refresh({ silent: true });
          populateJobs();
        } catch (error) {
          if (alive(token, body)) {
            clearInterval(progressTimer);
            progressWrap.hidden = true;
            setFeedback(runFeedback, error.message, "error");
          }
        } finally { oneBtn.disabled = false; batchBtn.disabled = false; }
      });

      body.append(baseCard, ctrlCard, previewCard);
      const initialKey = ctx && ctx.job ? `${ctx.job.source}::${ctx.job.url_key}` : "";
      populateJobs(initialKey);

      loadConfig().then((data) => {
        if (!alive(token, body)) return;
        master.value = data.settings?.mass_greeting || "";
        syncBaseUI(!master.value.trim());
      }).catch(() => { if (alive(token, body)) syncBaseUI(true); });
    }
  });

  /* ---------- 7. 审批操作（review，投递前终审台） ---------- */
  RP.registerDrawer("review", {
    title: "投递终审台", icon: "shield", tone: "warning",
    render(body) {
      const token = RP.drawerToken();

      const topCard = node("div", "", "rp-rv-top");
      const statsWrap = node("div", "", "rp-rv-stats");
      const statTotal = node("div", "", "rp-rv-stat");
      const statTotalVal = node("strong", "0");
      statTotal.append(statTotalVal, node("span", "待审批"));
      const statReady = node("div", "", "rp-rv-stat");
      const statReadyVal = node("strong", "0");
      statReady.append(statReadyVal, node("span", "物料齐备"));
      statsWrap.append(statTotal, statReady);

      const bulkBtn = button("一键放行全部", "rp-rv-bulk-btn", "check");
      topCard.append(statsWrap, bulkBtn);

      const list = node("div", "", "rp-rv-list");

      function reviewQueueJobs() {
        return state.jobs.filter((job) =>
          job.tab === "approval" || (job.hasRewrite && job.hasGreeting && ["rewritten", "greeted"].includes(job.stage))
        );
      }

      function paint() {
        const jobs = reviewQueueJobs();
        const readyJobs = jobs.filter((j) => (j.hasRewrite || j.track === "mass") && j.hasGreeting);
        statTotalVal.textContent = String(jobs.length);
        statReadyVal.textContent = String(readyJobs.length);
        bulkBtn.disabled = !readyJobs.length || state.bulkBusy;
        bulkBtn.lastChild.textContent = readyJobs.length ? `一键放行 (${readyJobs.length})` : "一键放行全部";

        if (!jobs.length) {
          const empty = node("div", "", "rp-rv-empty");
          empty.append(
            tile("inbox", "accent"),
            node("strong", "当前没有待审批岗位"),
            node("p", "完成任意岗位的「简历改写 + 打招呼语」后，该岗位会自动进入这里等待最终放行。")
          );
          const jumps = node("div", "", "rp-rv-jumps");
          const toRewrite = button("去改写简历", "rp-btn-sm rp-btn-ghost", "pen");
          const toGreet = button("去写打招呼语", "rp-btn-sm rp-btn-primary", "message");
          toRewrite.addEventListener("click", () => RP.openDrawer("rewriting"));
          toGreet.addEventListener("click", () => RP.openDrawer("greeting"));
          jumps.append(toRewrite, toGreet);
          empty.append(jumps);
          list.replaceChildren(empty);
          return;
        }

        list.replaceChildren(...jobs.slice(0, 50).map((job) => {
          const card = node("div", "", "rp-rv-card");
          const head = node("div", "", "rp-rv-card-head");
          const titleBox = node("div", "", "rp-rv-card-title");
          titleBox.append(
            node("strong", job.title || "未命名岗位"),
            node("span", [job.company, RP.sourceLabel(job.source), job.salary].filter(Boolean).join(" · "))
          );
          const scoreBox = node("div", "", "rp-rv-card-score");
          if (job.grade) scoreBox.append(gradeBadge(job.grade));
          if (job.score != null) scoreBox.append(node("span", `${job.score} 分`, "rp-rv-score-num"));
          head.append(titleBox, scoreBox);

          const mats = node("div", "", "rp-rv-mats");
          const resumeReady = job.hasRewrite || job.track === "mass";
          const mResume = node("span", resumeReady ? "✓ 定制简历" : "○ 待改写简历", "rp-rv-mat");
          mResume.dataset.ok = resumeReady ? "1" : "0";
          const mGreet = node("span", job.hasGreeting ? "✓ 打招呼语" : "○ 待写打招呼语", "rp-rv-mat");
          mGreet.dataset.ok = job.hasGreeting ? "1" : "0";
          const mTrack = node("span", job.track === "mass" ? "海投轨" : "精投轨", "rp-rv-track");
          const previewToggle = button("核验物料", "rp-rv-preview-btn", "eye");
          mats.append(mResume, mGreet, mTrack, previewToggle);

          const previewPane = node("div", "", "rp-rv-preview");
          previewPane.hidden = true;
          let loaded = false;
          previewToggle.addEventListener("click", async () => {
            previewPane.hidden = !previewPane.hidden;
            if (!previewPane.hidden && !loaded) {
              previewPane.textContent = "正在加载物料…";
              try {
                const payload = await RP.fetchJobPayload(job);
                if (!alive(token, body)) return;
                loaded = true;
                const gText = RP.payloadText(payloadOf(payload, "greeting_payload", "greeting"));
                const rText = RP.payloadText(payloadOf(payload, "rewrite_payload", "rewrite"));
                previewPane.replaceChildren();
                const gBlock = node("div", "", "rp-rv-pv-block");
                gBlock.append(node("h5", "打招呼语"), node("p", gText || "尚未生成打招呼语"));
                const rBlock = node("div", "", "rp-rv-pv-block");
                rBlock.append(node("h5", "定制简历摘要"), node("p", rText ? `${rText.slice(0, 220)}${rText.length > 220 ? "…" : ""}` : "尚未生成改写稿"));
                previewPane.append(gBlock, rBlock);
              } catch (error) {
                if (alive(token, body)) previewPane.textContent = error.message;
              }
            }
          });

          const actions = node("div", "", "rp-rv-actions");
          const approve = button("放行入队", "rp-rv-approve-btn", "check");
          approve.disabled = !(resumeReady && job.hasGreeting);
          const reeval = button("重评", "rp-btn-sm rp-btn-ghost", "rotate");
          const reject = button("淘汰", "rp-btn-sm rp-btn-danger", "x");
          approve.addEventListener("click", async () => { await RP.decide(job, "approve"); if (alive(token, body)) paint(); });
          reeval.addEventListener("click", async () => { await RP.decide(job, "reeval"); if (alive(token, body)) paint(); });
          reject.addEventListener("click", async () => { await RP.decide(job, "reject"); if (alive(token, body)) paint(); });
          actions.append(approve, reeval, reject);

          card.append(head, mats, previewPane, actions);
          return card;
        }));
      }

      bulkBtn.addEventListener("click", async () => {
        const jobs = reviewQueueJobs().filter((j) => (j.hasRewrite || j.track === "mass") && j.hasGreeting);
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
        if (done) toast(`已放行 ${done} 个岗位进入待投递队列。`, "success");
        if (alive(token, body)) paint();
      });

      paint();
      body.append(topCard, list);
    }
  });

  /* ---------- 8. 投递队列（delivering，BOSS 草稿填入 + dry-run 归档） ---------- */
  RP.registerDrawer("delivering", {
    title: "投递执行台", icon: "send", tone: "accent",
    render(body, ctx) {
      const token = RP.drawerToken();

      /* 1. 可折叠「投递闸配置」 */
      const gateCard = node("div", "", "rp-gr-card rp-dl-gate");
      const gateHead = node("div", "", "rp-gr-base-head");
      const gateTitle = node("div", "", "rp-gr-base-title");
      const gateSummary = node("span", "加载中…", "rp-gr-badge");
      gateTitle.append(icon("sliders"), node("strong", "投递闸配置"), gateSummary);
      const gateToggle = button("配置", "rp-btn-sm rp-btn-ghost");
      gateHead.append(gateTitle, gateToggle);

      const gateBody = node("div", "", "rp-gr-base-body");
      gateBody.hidden = true;
      const headcount = input("number", { min: "1", max: "10000000", step: "1" });
      const stopAtReview = input("checkbox");
      const stopLabel = node("label", "", "rp-inline-check");
      stopLabel.append(stopAtReview, document.createTextNode("停在待投递队列等待手动确认（推荐）"));
      const gateFeedback = feedback();
      const gateSave = button("保存配置", "rp-btn-sm rp-btn-primary", "check");
      gateSave.addEventListener("click", async () => {
        gateSave.disabled = true;
        try {
          await saveConfig({
            mass_apply_max_headcount: Number(headcount.value) || 1000,
            stop_at_review: stopAtReview.checked
          }, gateFeedback, "投递闸配置已保存。");
          if (alive(token, body)) {
            setFeedback(gateFeedback, "已保存。", "success");
            syncGateSummary();
            gateBody.hidden = true;
            gateToggle.textContent = "配置";
          }
        } catch (error) {
          if (alive(token, body)) setFeedback(gateFeedback, error.message, "error");
        } finally { gateSave.disabled = false; }
      });
      gateBody.append(field("海投拦截门槛（公司规模上限，人）", headcount), stopLabel, gateSave, gateFeedback);
      gateCard.append(gateHead, gateBody);

      function syncGateSummary() {
        const cap = Number(headcount.value) || 1000;
        gateSummary.textContent = `海投拦截 ≥${cap} 人 · ${stopAtReview.checked ? "队列确认" : "自动 dry-run"}`;
      }
      gateToggle.addEventListener("click", () => {
        gateBody.hidden = !gateBody.hidden;
        gateToggle.textContent = gateBody.hidden ? "配置" : "收起";
      });

      /* 2. 待投递队列 */
      const selected = new Set();
      const queueCard = node("div", "", "rp-gr-card");
      const queueHead = node("div", "", "rp-dl-sec-head");
      const queueTitle = node("div", "", "rp-gr-base-title");
      const queueBadge = node("span", "0", "rp-gr-badge");
      queueTitle.append(icon("send"), node("strong", "待投递队列"), queueBadge);
      const queueBtns = node("div", "", "rp-gr-btn-row");
      const deliverBtn = button("dry-run 所选", "rp-btn-sm rp-btn-ghost", "check");
      const exportBtn = button("导出 CSV", "rp-btn-sm rp-btn-ghost", "download");
      queueBtns.append(deliverBtn, exportBtn);
      queueHead.append(queueTitle, queueBtns);
      const deliverFeedback = feedback();
      const queueList = node("div", "", "rp-rv-list");

      function syncDeliverBtn() {
        deliverBtn.disabled = !selected.size || state.bulkBusy;
        deliverBtn.lastChild.textContent = selected.size ? `dry-run 所选 (${selected.size})` : "dry-run 所选";
      }

      function paintQueue() {
        const jobs = state.jobs.filter((job) => job.tab === "queued");
        queueBadge.textContent = `${jobs.length} 岗`;
        queueBadge.dataset.state = jobs.length ? "ok" : "";
        syncDeliverBtn();
        if (!jobs.length) {
          queueList.replaceChildren(emptyBlock("待投递队列为空", "在「投递终审台」放行后，岗位会进入这里。"));
          return;
        }
        queueList.replaceChildren(...jobs.slice(0, 50).map((job) => {
          const card = node("div", "", "rp-dl-card");
          const head = node("div", "", "rp-rv-card-head");
          const left = node("div", "", "rp-dl-card-left");
          const box = input("checkbox");
          box.checked = selected.has(RP.jobId(job));
          box.setAttribute("aria-label", "选择 " + job.title);
          box.addEventListener("change", () => {
            if (box.checked) selected.add(RP.jobId(job));
            else selected.delete(RP.jobId(job));
            syncDeliverBtn();
          });
          const titleBox = node("div", "", "rp-rv-card-title");
          titleBox.append(
            node("strong", job.title || "未命名岗位"),
            node("span", [job.company, RP.sourceLabel(job.source), job.salary].filter(Boolean).join(" · "))
          );
          left.append(box, titleBox);

          const scoreBox = node("div", "", "rp-rv-card-score");
          if (job.grade) scoreBox.append(gradeBadge(job.grade));
          if (job.score != null) scoreBox.append(node("span", `${job.score} 分`, "rp-rv-score-num"));
          head.append(left, scoreBox);

          const actions = node("div", "", "rp-dl-actions");
          const DRAFT_LABELS = { boss: "BOSS", zhilian: "智联", "51job": "前程无忧" };
          if (DRAFT_LABELS[job.source]) {
            const pLabel = DRAFT_LABELS[job.source];
            const draftBtn = button(`填入${pLabel}草稿（不发送）`, "rp-dl-draft-btn", "message");
            draftBtn.addEventListener("click", async () => {
              draftBtn.disabled = true;
              setFeedback(deliverFeedback, `正在 Chrome 打开${pLabel}「${job.title}」并填入打招呼语草稿…`);
              try {
                const res = await pipelineApi("/deliver_draft", { source: job.source, url_key: job.url_key });
                if (!alive(token, body)) return;
                setFeedback(deliverFeedback, res.message || `已填入${pLabel}聊天草稿（未发送）。`, "success");
                toast(`已填入${pLabel}聊天草稿，切换 Chrome 按 Enter 发送。`, "success");
              } catch (error) {
                if (alive(token, body)) {
                  setFeedback(deliverFeedback, error.message, "error");
                  toast(error.message, "error");
                }
              } finally { draftBtn.disabled = false; }
            });
            actions.append(draftBtn);
          }
          const deliver = button("dry-run 归档", "rp-btn-sm rp-btn-ghost", "check");
          deliver.addEventListener("click", async () => {
            await RP.deliverJobs([job]);
            if (alive(token, body)) { paintQueue(); paintDelivered(); }
          });
          const cancel = button("终止", "rp-btn-sm rp-btn-danger", "stop");
          cancel.addEventListener("click", async () => {
            await RP.abandonDelivery(job);
            if (alive(token, body)) paintQueue();
          });
          actions.append(deliver, cancel);
          card.append(head, actions);
          return card;
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
          setFeedback(deliverFeedback, "投递包 CSV 已导出。", "success");
          toast("投递包 CSV 已导出。", "success");
          void RP.refresh({ silent: true });
          paintQueue();
          paintDelivered();
        } catch (error) {
          if (alive(token, body)) setFeedback(deliverFeedback, error.message, "error");
        } finally { exportBtn.disabled = false; }
      });
      queueCard.append(queueHead, deliverFeedback, queueList);

      /* 3. 已投递 · 投递包归档 */
      const deliveredCard = node("div", "", "rp-gr-card");
      const delHead = node("div", "", "rp-dl-sec-head");
      const delTitle = node("div", "", "rp-gr-base-title");
      const delBadge = node("span", "0", "rp-gr-badge");
      delTitle.append(icon("check-circle"), node("strong", "已投递 · 投递包归档"), delBadge);
      delHead.append(delTitle);
      const deliveredList = node("div", "", "rp-rv-list");
      const packageView = node("div", "", "rp-rv-preview");
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
          pkg.track === "mass" ? "海投轨" : "精投轨", "dry-run 归档",
          delivery.delivered_at ? "归档时间 " + RP.fmtTime(delivery.delivered_at) : ""
        ].filter(Boolean)) chips.append(node("span", text, "rp-stat-chip"));
        packageView.append(chips);
        if (pkg.greeting) {
          const gBlock = node("div", "", "rp-rv-pv-block");
          gBlock.append(node("h5", "打招呼语"), node("p", pkg.greeting));
          packageView.append(gBlock);
        }
        if (pkg.resume_markdown) {
          const rBlock = node("div", "", "rp-rv-pv-block");
          rBlock.append(node("h5", "投递简历（改写稿）"));
          const doc = node("div", "", "rp-doc");
          RP.renderDoc(doc, pkg.resume_markdown);
          rBlock.append(doc);
          packageView.append(rBlock);
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
        delBadge.textContent = `${jobs.length} 岗`;
        if (!jobs.length) {
          deliveredList.replaceChildren(emptyBlock("暂无归档记录", "完成投递归档后会在这里留档备查。"));
          return;
        }
        deliveredList.replaceChildren(...jobs.slice(0, 30).map((job) => {
          const card = node("div", "", "rp-dl-card");
          const head = node("div", "", "rp-rv-card-head");
          const titleBox = node("div", "", "rp-rv-card-title");
          titleBox.append(
            node("strong", job.title || "未命名岗位"),
            node("span", [job.company, job.updatedAt ? "归档 " + RP.fmtTime(job.updatedAt) : ""].filter(Boolean).join(" · "))
          );
          const view = button("查看投递包", "rp-btn-sm rp-btn-ghost", "eye");
          view.addEventListener("click", () => openPackage(job));
          head.append(titleBox, view);
          card.append(head);
          return card;
        }));
      }
      deliveredCard.append(delHead, deliveredList, packageView);
      paintQueue();
      paintDelivered();
      body.append(gateCard, queueCard, deliveredCard);

      loadConfig().then((data) => {
        if (!alive(token, body)) return;
        headcount.value = data.settings?.mass_apply_max_headcount ?? 1000;
        stopAtReview.checked = data.settings?.stop_at_review !== false;
        syncGateSummary();
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
