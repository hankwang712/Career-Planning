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

  /* ---------- 5. 简历改写（rewriting，基准简历 + 对比） ---------- */
  RP.registerDrawer("rewriting", {
    title: "简历改写 · 定制面板", icon: "pen", tone: "accent",
    render(body, ctx) {
      const token = RP.drawerToken();

      /* 顶部玻璃态 Hero + 合规胶囊 */
      const hero = node("div", "", "rp-rw-hero");
      const heroCopy = node("div", "", "rp-rw-hero-copy");
      heroCopy.append(node("p", "AI 智能优化简历表达，精准对齐目标岗位 JD", "rp-rw-hero-sub"));
      const rulesBar = node("div", "", "rp-rw-rules");
      for (const [ico, tone, text] of [
        ["bolt", "blue", "不虚构经历"],
        ["layers", "violet", "禁注入缺失技能"],
        ["shield", "indigo", "经历一段不裁"]
      ]) {
        const pill = node("span", "", `rp-rw-rule-pill tone-${tone}`);
        pill.append((ico === "layers" || ico === "shield") ? icon(ico) : inlineIcon(ico), node("span", text));
        rulesBar.append(pill);
      }
      heroCopy.append(rulesBar);
      const heroArt = document.createElement("div");
      heroArt.className = "rp-rw-hero-art";
      heroArt.setAttribute("aria-hidden", "true");
      heroArt.innerHTML = `<svg viewBox="0 0 116 86" fill="none"><rect x="18" y="8" width="66" height="72" rx="11" fill="#ffffff" fill-opacity="0.88" stroke="#dbeafe" stroke-width="1.4" transform="rotate(8 51 44)"/><rect x="30" y="21" width="16" height="16" rx="5" fill="#dbeafe" transform="rotate(8 38 29)"/><rect x="52" y="24" width="24" height="5" rx="2.5" fill="#cbd5e1" transform="rotate(8 64 26)"/><rect x="51" y="33" width="18" height="4" rx="2" fill="#e2e8f0" transform="rotate(8 60 35)"/><rect x="27" y="45" width="46" height="4.5" rx="2.2" fill="#e2e8f0" transform="rotate(8 50 47)"/><rect x="26" y="55" width="38" height="4.5" rx="2.2" fill="#e2e8f0" transform="rotate(8 45 57)"/><circle cx="88" cy="52" r="18" fill="url(#rwAiGrad)"/><text x="88" y="57" text-anchor="middle" fill="#fff" font-size="12" font-weight="800" font-family="system-ui,sans-serif">AI</text><defs><linearGradient id="rwAiGrad" x1="70" y1="34" x2="106" y2="70"><stop stop-color="#3b82f6"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs></svg>`;
      hero.append(heroCopy, heroArt);
      body.append(hero);

      /* 1. 基础简历卡片 */
      const baselineSection = section("基础简历", "file-text", "accent");
      baselineSection.classList.add("rp-rw-card");
      const baselineRow = node("div", "", "rp-rw-base-row");
      const baselineSelect = select([["", "正在读取简历库…"]]);
      const baselineLink = node("a", "简历库 →", "rp-rw-lib-btn");
      baselineLink.href = meta.resumes_url;
      baselineRow.append(baselineSelect, baselineLink);
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
      baselineSection.append(baselineRow, baselineInfo, baselineFeedback);

      /* 2. 目标岗位与改写卡片 */
      const picker = section("目标岗位与改写", "briefcase", "blue");
      picker.classList.add("rp-rw-card");
      const eligible = state.jobs.filter((job) => RP.stageIndex(job.stage) >= RP.stageIndex("screened") && job.tab !== "rejected" && job.tab !== "failed");
      if (ctx.job && !eligible.some((job) => RP.jobId(job) === RP.jobId(ctx.job))) eligible.unshift(ctx.job);
      const jobSelect = select(eligible.slice(0, 200).map((job) => [RP.jobId(job), `${job.title} · ${job.company || RP.sourceLabel(job.source)}`]),
        ctx.job ? RP.jobId(ctx.job) : eligible[0] ? RP.jobId(eligible[0]) : null);
      const currentJob = () => eligible.find((job) => RP.jobId(job) === jobSelect.value) || null;
      const jobPreview = node("div", "", "rp-rw-job-preview");
      const runFeedback = feedback();
      const progressWrap = node("div", "", "rp-rw-progress");
      progressWrap.hidden = true;
      const progHead = node("div", "", "rp-rw-prog-head");
      const progLabel = node("span", "准备开始…");
      const progMeta = node("span", "0s", "rp-rw-prog-meta");
      progHead.append(progLabel, progMeta);
      const progTrack = node("div", "", "rp-rw-prog-track");
      const progBar = node("div", "", "rp-rw-prog-bar");
      progTrack.append(progBar);
      progressWrap.append(progHead, progTrack);

      const actionRow = node("div", "", "rp-rw-actions rp-rw-actions-3");
      const singleBtn = button("微调当前岗位", "rp-rw-primary-btn", "sparkles");
      const runBtn = button("批量生成全部", "rp-rw-ghost-btn", "layers");
      const studioBtn = button("去简历工坊导出", "rp-rw-ghost-btn", "sliders");

      function openInWorkshop() {
        const job = currentJob();
        if (job) {
          try {
            sessionStorage.setItem("career:resume-rewrite-job", JSON.stringify({
              title: job.title || "",
              description: job.description || job.jd || `${job.title || ""} ${job.company || ""}`
            }));
          } catch (_) {}
          window.open(`${meta.resumes_url}?rewrite=1`, "_blank", "noopener");
        } else {
          window.open(meta.resumes_url, "_blank", "noopener");
        }
      }
      studioBtn.addEventListener("click", openInWorkshop);

      singleBtn.addEventListener("click", async () => {
        const job = currentJob();
        if (!job) return;
        singleBtn.disabled = true;
        runBtn.disabled = true;
        const startedAt = Date.now();
        progressWrap.hidden = false;
        progressWrap.dataset.state = "running";
        progBar.style.width = "22%";
        progLabel.textContent = `正在针对「${(job.title || "").slice(0, 18)}」精准微调…`;
        progMeta.textContent = "0s";
        const timer = window.setInterval(() => {
          const secs = Math.round((Date.now() - startedAt) / 1000);
          progMeta.textContent = `${secs}s`;
          progBar.style.width = `${Math.min(90, 22 + secs * 3)}%`;
        }, 1000);
        try {
          const result = await withBusy(
            () => RP.runStage("rewrite", { source: job.source, url_key: job.url_key, limit: 1 }),
            runFeedback,
            ""
          );
          window.clearInterval(timer);
          if (!alive(token, body)) return;
          const totalSecs = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
          progressWrap.dataset.state = "done";
          progBar.style.width = "100%";
          const msg = `当前岗位定向微调完成（${result?.mode === "llm" ? "AI 模型" : "模板"}，耗时 ${totalSecs}s）`;
          progLabel.textContent = msg;
          progMeta.textContent = `${totalSecs}s`;
          setFeedback(runFeedback, "", "info");
          toast(msg, "success");
          void RP.refresh({ silent: true });
          void loadCompare();
        } catch (error) {
          window.clearInterval(timer);
          if (alive(token, body)) {
            progressWrap.dataset.state = "error";
            progLabel.textContent = error.message || "微调失败";
            setFeedback(runFeedback, error.message, "error");
          }
        } finally {
          singleBtn.disabled = false;
          runBtn.disabled = false;
        }
      });

      runBtn.addEventListener("click", async () => {
        runBtn.disabled = true;
        singleBtn.disabled = true;
        const maxSteps = Math.max(1, eligible.length);
        const startedAt = Date.now();
        let doneCount = 0;
        let lastMode = "llm";
        progressWrap.hidden = false;
        progressWrap.dataset.state = "running";
        progBar.style.width = "8%";
        progLabel.textContent = `正在 AI 微调第 1 / ${maxSteps} 个岗位…`;
        progMeta.textContent = "0s";
        const timer = window.setInterval(() => {
          const secs = Math.round((Date.now() - startedAt) / 1000);
          progMeta.textContent = `${doneCount}/${maxSteps} · ${secs}s`;
        }, 1000);
        try {
          await withBusy(async () => {
            for (let step = 0; step < maxSteps; step += 1) {
              if (!alive(token, body)) break;
              progLabel.textContent = `正在 AI 微调第 ${doneCount + 1} 个岗位…`;
              progBar.style.width = `${Math.min(92, Math.max(10, Math.round(((doneCount + 0.35) / maxSteps) * 100)))}%`;
              const result = await RP.runStage("rewrite", { limit: 1 });
              if (!alive(token, body)) break;
              const n = Number(result?.processed || 0);
              if (result?.mode) lastMode = result.mode;
              if (n <= 0) break;
              doneCount += n;
              const pct = Math.min(96, Math.round((doneCount / maxSteps) * 100));
              progBar.style.width = `${pct}%`;
              progLabel.textContent = `已完成 ${doneCount} 个岗位，继续处理下一个…`;
              void loadCompare();
            }
          }, runFeedback, "");
          window.clearInterval(timer);
          if (!alive(token, body)) return;
          const totalSecs = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
          progressWrap.dataset.state = "done";
          progBar.style.width = "100%";
          const msg = doneCount
            ? `批量微调完成：已处理 ${doneCount} 个岗位（${lastMode === "llm" ? "AI 模型" : "模板"}，耗时 ${totalSecs}s）`
            : "所有待改写岗位均已完成，如需重跑请点左侧「微调当前岗位」。";
          progLabel.textContent = msg;
          progMeta.textContent = `${totalSecs}s`;
          setFeedback(runFeedback, "", "info");
          toast(msg, "success");
          void RP.refresh({ silent: true });
          void loadCompare();
        } catch (error) {
          window.clearInterval(timer);
          if (alive(token, body)) {
            progressWrap.dataset.state = "error";
            progLabel.textContent = error.message || "改写中断";
            setFeedback(runFeedback, error.message, "error");
          }
        } finally { runBtn.disabled = false; singleBtn.disabled = false; }
      });
      actionRow.append(singleBtn, runBtn, studioBtn);
      picker.append(jobSelect, jobPreview, actionRow, progressWrap, runFeedback);
      if (!eligible.length) picker.append(note("暂无可改写岗位：先完成 AI 评估，或从看板点选岗位。", "warning"));

      /* 3. 改写对比 + 优化效果雷达图 */
      const compareSection = section("改写对比", "eye", "indigo");
      compareSection.classList.add("rp-rw-card");
      const viewSwitch = node("div", "", "rp-rw-view-switch");
      const btnCompareView = node("button", "对比视图", "rp-rw-view-btn active");
      btnCompareView.type = "button";
      const btnDiffView = node("button", "差异高亮", "rp-rw-view-btn");
      btnDiffView.type = "button";
      viewSwitch.append(btnCompareView, btnDiffView);
      const cmpHead = compareSection.querySelector(".rp-section-head");
      if (cmpHead) cmpHead.append(viewSwitch);

      const compareWrap = node("div", "", "rp-rw-compare-wrap");
      const baseCol = node("div", "", "rp-rw-pane rp-rw-pane-base");
      const baseHead = node("div", "", "rp-rw-pane-head");
      baseHead.append(inlineIcon("doc"), node("span", "基础简历 (原稿)"));
      const baseDoc = node("div", "", "rp-doc rp-rw-doc");
      baseCol.append(baseHead, baseDoc);

      const arrowMid = node("span", "→", "rp-rw-arrow-mid");

      const rewriteCol = node("div", "", "rp-rw-pane rp-rw-pane-ai");
      const rewriteHead = node("div", "", "rp-rw-pane-head");
      const expandBtn = node("button", "放大对比", "rp-rw-expand-btn");
      expandBtn.type = "button";
      expandBtn.disabled = true;
      rewriteHead.append(icon("sparkles"), node("span", "AI 改写稿"), node("em", "推荐", "rp-rw-rec-tag"), expandBtn);
      const rewriteDoc = node("div", "", "rp-doc rp-rw-doc");
      rewriteCol.append(rewriteHead, rewriteDoc);
      compareWrap.append(baseCol, arrowMid, rewriteCol);

      const effectBox = node("div", "", "rp-rw-effect");
      const downgrades = node("details", "", "rp-deep-key");
      downgrades.hidden = true;
      const compareActions = node("div", "", "rp-rw-foot");
      const previewModalBtn = button("全屏对比预览", "rp-rw-foot-ghost", "eye");
      previewModalBtn.disabled = true;
      const copyBtn = button("复制改写稿", "rp-rw-foot-ghost", "copy");
      const saveCopyBtn = button("存为该公司专属副本", "rp-rw-foot-primary", "save");
      saveCopyBtn.disabled = true;
      let rewriteText = "";
      let baselineText = "";
      let lastRewriteObj = null;
      let diffHighlightMode = false;

      async function saveAsCompanyDraft(triggerBtn) {
        if (!rewriteText) return;
        const job = currentJob();
        const btn = triggerBtn || saveCopyBtn;
        const oldText = btn.textContent;
        btn.disabled = true;
        btn.textContent = "正在保存专属副本…";
        try {
          const headers = window.CareerAuth ? await window.CareerAuth.headers() : {};
          const parseData = new FormData();
          parseData.set("source", "text");
          parseData.set("text", rewriteText);
          parseData.set("use_ai", "0");
          const parsedRes = await fetch("/api/resume-editor/import", { method: "POST", headers, body: parseData });
          if (!parsedRes.ok) throw new Error("改写稿解析失败，请稍后重试。");
          const parsedDoc = (await parsedRes.json()).document;

          let baseDoc = null;
          if (baselineSelect.value) {
            const baseRes = await fetch("/api/resume-editor/drafts/" + encodeURIComponent(baselineSelect.value), { cache: "no-store" });
            if (baseRes.ok) baseDoc = (await baseRes.json()).document;
          }
          const companyTag = (job?.company || job?.title || "定向").trim().slice(0, 18);
          const baseTitle = (baseDoc?.title || "定向简历").slice(0, 54);
          const mergedDoc = {
            ...(baseDoc || {}),
            title: `${baseTitle} · ${companyTag}`.slice(0, 80),
            contact: {
              ...(baseDoc?.contact || {}),
              ...(parsedDoc?.contact?.target ? { target: parsedDoc.contact.target } : {})
            },
            sections: parsedDoc?.sections?.length ? parsedDoc.sections : (baseDoc?.sections || [])
          };
          const jsonHeaders = { ...headers, "Content-Type": "application/json" };
          const createRes = await fetch("/api/resume-editor/drafts", {
            method: "POST",
            headers: jsonHeaders,
            body: JSON.stringify(mergedDoc)
          });
          if (!createRes.ok) {
            const err = await createRes.json().catch(() => ({}));
            throw new Error(err.message || "保存副本失败。");
          }
          const created = await createRes.json();
          toast(`已另存为「${created.document.title}」（原简历完好保留）`, "success");
          window.open(`${meta.resumes_url}?draft=${encodeURIComponent(created.id)}`, "_blank", "noopener");
        } catch (error) {
          toast(error.message || "保存副本失败。", "error");
        } finally {
          btn.textContent = oldText;
          btn.disabled = !rewriteText;
        }
      }

      function normDiffLine(line) {
        return String(line || "")
          .replace(/^\s*([-*•+]|\d+\.)\s+/, "")
          .replace(/\*\*|__|`/g, "")
          .replace(/[：:]/g, ":")
          .replace(/\s+/g, "")
          .toLowerCase();
      }

      function computeResumeDiff(origText, newText) {
        const a = String(origText || "").split("\n").map(s => s.trim()).filter(Boolean);
        const b = String(newText || "").split("\n").map(s => s.trim()).filter(Boolean);
        const setA = new Set(a.map(normDiffLine));
        const setB = new Set(b.map(normDiffLine));
        const baseLines = a.map(text => ({ text, status: setB.has(normDiffLine(text)) ? "same" : "removed" }));
        const newLines = b.map(text => ({ text, status: setA.has(normDiffLine(text)) ? "same" : "added" }));
        return {
          baseLines,
          newLines,
          addedCount: newLines.filter(l => l.status === "added").length,
          removedCount: baseLines.filter(l => l.status === "removed").length
        };
      }

      function openDiffModal() {
        if (!rewriteText) return;
        const job = currentJob();
        const diff = computeResumeDiff(baselineText, rewriteText);
        // Line-level cherry-pick state: default true = accept AI change for added lines / drop removed lines
        const acceptAdded = new Map();
        const restoreRemoved = new Map();
        diff.newLines.forEach((l, i) => { if (l.status === "added") acceptAdded.set(i, true); });
        diff.baseLines.forEach((l, i) => { if (l.status === "removed") restoreRemoved.set(i, false); });

        function assembledMarkdown() {
          const out = [];
          let bIdx = 0;
          diff.newLines.forEach((item, nIdx) => {
            if (item.status === "same") {
              // Flush any user-restored removed base lines that appeared before this matching line
              while (bIdx < diff.baseLines.length && diff.baseLines[bIdx].status !== "same") {
                if (restoreRemoved.get(bIdx)) out.push(diff.baseLines[bIdx].text);
                bIdx += 1;
              }
              out.push(item.text);
              if (bIdx < diff.baseLines.length) bIdx += 1;
            } else if (acceptAdded.get(nIdx)) {
              out.push(item.text);
            }
          });
          while (bIdx < diff.baseLines.length) {
            if (diff.baseLines[bIdx].status === "removed" && restoreRemoved.get(bIdx)) {
              out.push(diff.baseLines[bIdx].text);
            }
            bIdx += 1;
          }
          return out.join("\n").trim() || rewriteText;
        }

        const dialog = document.createElement("dialog");
        dialog.className = "rp-rw-modal";

        const head = node("header", "", "rp-rw-modal-head");
        const titleWrap = node("div", "", "rp-rw-modal-title");
        const statPill = node("span", `+${diff.addedCount} 处优化 / -${diff.removedCount} 处调整 · 支持逐条采纳/还原`, "rp-rw-diff-stat");
        titleWrap.append(
          node("h3", job ? `${job.title} · 改写稿对比与逐条采纳` : "改写稿对比预览"),
          statPill
        );
        const modeBar = node("div", "", "rp-rw-view-switch");
        const tabSplit = node("button", "左右对比", "rp-rw-view-btn active");
        const tabChanges = node("button", "只看修改", "rp-rw-view-btn");
        const tabClean = node("button", "拼装成稿", "rp-rw-view-btn");
        for (const b of [tabSplit, tabChanges, tabClean]) b.type = "button";
        modeBar.append(tabSplit, tabChanges, tabClean);
        const closeX = node("button", "×", "rp-rw-modal-close");
        closeX.type = "button";
        closeX.setAttribute("aria-label", "关闭对比预览");
        closeX.addEventListener("click", () => dialog.close());
        head.append(titleWrap, modeBar, closeX);

        const content = node("div", "", "rp-rw-modal-body");
        let activeMode = "split";

        function paintModal(mode) {
          activeMode = mode;
          for (const [btn, m] of [[tabSplit, "split"], [tabChanges, "changes"], [tabClean, "clean"]]) {
            btn.classList.toggle("active", mode === m);
          }
          const merged = assembledMarkdown();
          content.replaceChildren();
          if (mode === "clean") {
            const cleanPane = node("div", "", "rp-rw-modal-clean rp-doc");
            RP.renderDoc(cleanPane, merged);
            content.append(cleanPane);
            return;
          }
          const grid = node("div", "", "rp-rw-modal-grid");
          const leftCol = node("div", "", "rp-rw-modal-col");
          const rightCol = node("div", "", "rp-rw-modal-col");
          leftCol.append(node("h4", `原始基准简历（${baselineText ? baselineText.length : 0} 字）`));
          rightCol.append(node("h4", `AI 定向改写稿（当前拼装 ${merged.length} 字）`));
          const leftList = node("div", "", "rp-rw-diff-list");
          const rightList = node("div", "", "rp-rw-diff-list");

          const bItems = diff.baseLines.map((item, idx) => ({ ...item, idx })).filter(x => mode !== "changes" || x.status !== "same");
          const nItems = diff.newLines.map((item, idx) => ({ ...item, idx })).filter(x => mode !== "changes" || x.status !== "same");

          if (!bItems.length) {
            leftList.append(node("p", baselineText ? "原始简历与改写稿无删减行。" : "未加载到原始简历正文，请先在简历库保存。", "rp-doc-empty"));
          } else {
            for (const item of bItems) {
              const row = node("div", "", `rp-diff-line is-${item.status}`);
              row.append(node("span", item.status === "removed" ? "−" : "·", "rp-diff-mark"), node("span", item.text));
              if (item.status === "removed") {
                const kept = Boolean(restoreRemoved.get(item.idx));
                const toggle = node("button", kept ? "已还原" : "还原原句", "rp-diff-pick-btn");
                toggle.type = "button";
                toggle.dataset.active = kept ? "1" : "0";
                toggle.addEventListener("click", () => {
                  restoreRemoved.set(item.idx, !kept);
                  paintModal(activeMode);
                });
                row.append(toggle);
              }
              leftList.append(row);
            }
          }
          if (!nItems.length) {
            rightList.append(node("p", "未检测到新增或改写行。", "rp-doc-empty"));
          } else {
            for (const item of nItems) {
              const row = node("div", "", `rp-diff-line is-${item.status}`);
              const accepted = item.status !== "added" || Boolean(acceptAdded.get(item.idx));
              if (item.status === "added" && !accepted) row.classList.add("is-rejected");
              row.append(node("span", item.status === "added" ? "+" : "·", "rp-diff-mark"), node("span", item.text));
              if (item.status === "added") {
                const toggle = node("button", accepted ? "已采纳" : "已忽略", "rp-diff-pick-btn");
                toggle.type = "button";
                toggle.dataset.active = accepted ? "1" : "0";
                toggle.addEventListener("click", () => {
                  acceptAdded.set(item.idx, !accepted);
                  paintModal(activeMode);
                });
                row.append(toggle);
              }
              rightList.append(row);
            }
          }
          leftCol.append(leftList);
          rightCol.append(rightList);
          grid.append(leftCol, rightCol);
          content.append(grid);
        }

        tabSplit.addEventListener("click", () => paintModal("split"));
        tabChanges.addEventListener("click", () => paintModal("changes"));
        tabClean.addEventListener("click", () => paintModal("clean"));

        const foot = node("footer", "", "rp-rw-modal-foot");
        const mCopy = button("复制拼装成稿", "rp-rw-foot-ghost", "copy");
        mCopy.addEventListener("click", () => copyText(assembledMarkdown(), "拼装成稿已复制。"));
        const mSaveCherry = button("保存当前拼装结果", "rp-rw-foot-ghost", "check");
        mSaveCherry.addEventListener("click", async () => {
          if (!job) return;
          mSaveCherry.disabled = true;
          try {
            const merged = assembledMarkdown();
            await pipelineApi("/rewrite/save", { source: job.source, url_key: job.url_key, markdown: merged });
            rewriteText = merged;
            renderRewriteBody();
            toast("已保存你逐条采纳后的专属改写稿。", "success");
          } catch (err) { toast(err.message, "error"); }
          finally { mSaveCherry.disabled = false; }
        });
        const mSaveCopy = button("存为该公司专属副本（不改原稿）", "rp-rw-foot-primary", "save");
        mSaveCopy.addEventListener("click", () => {
          rewriteText = assembledMarkdown();
          void saveAsCompanyDraft(mSaveCopy);
        });
        foot.append(mCopy, mSaveCherry, mSaveCopy);

        dialog.append(head, content, foot);
        dialog.addEventListener("close", () => dialog.remove());
        document.body.append(dialog);
        paintModal("split");
        dialog.showModal();
      }

      expandBtn.addEventListener("click", openDiffModal);
      previewModalBtn.addEventListener("click", openDiffModal);

      function renderRewriteBody() {
        rewriteDoc.replaceChildren();
        if (!rewriteText) {
          rewriteDoc.append(node("p", "尚未生成改写稿，点击上方按钮批量生成，或直接去简历工坊用 Skill 精修。", "rp-doc-empty"));
          return;
        }
        if (diffHighlightMode && baselineText) {
          const diff = computeResumeDiff(baselineText, rewriteText);
          const list = node("div", "", "rp-rw-diff-list is-compact");
          for (const item of diff.newLines) {
            const row = node("div", "", `rp-diff-line is-${item.status}`);
            row.append(node("span", item.status === "added" ? "+" : "·", "rp-diff-mark"), node("span", item.text));
            list.append(row);
          }
          rewriteDoc.append(list);
          return;
        }
        RP.renderDoc(rewriteDoc, rewriteText);
      }

      btnCompareView.addEventListener("click", () => {
        diffHighlightMode = false;
        btnCompareView.classList.add("active");
        btnDiffView.classList.remove("active");
        renderRewriteBody();
      });
      btnDiffView.addEventListener("click", () => {
        diffHighlightMode = true;
        btnDiffView.classList.add("active");
        btnCompareView.classList.remove("active");
        renderRewriteBody();
      });

      copyBtn.addEventListener("click", () => copyText(rewriteText, "改写稿已复制。"));
      saveCopyBtn.addEventListener("click", () => void saveAsCompanyDraft(saveCopyBtn));
      compareActions.append(previewModalBtn, copyBtn, saveCopyBtn);
      compareSection.append(compareWrap, effectBox, downgrades, compareActions);
      body.append(baselineSection, picker, compareSection);

      function buildRadarSvg(values) {
        const cx = 64, cy = 54, r = 34;
        const labels = ["岗位匹配", "技能覆盖", "篇幅控制", "精准微调", "合规安全"];
        const pt = (i, ratio) => {
          const ang = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
          return [cx + Math.cos(ang) * r * ratio, cy + Math.sin(ang) * r * ratio];
        };
        const poly = (ratio) => labels.map((_, i) => pt(i, ratio).map(n => n.toFixed(1)).join(",")).join(" ");
        const dataPoly = values.map((v, i) => pt(i, Math.max(0.2, Math.min(1, v))).map(n => n.toFixed(1)).join(",")).join(" ");
        const labelNodes = labels.map((lb, i) => {
          const [lx, ly] = pt(i, 1.32);
          return `<text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="middle" font-size="8.5" fill="#64748b">${lb}</text>`;
        }).join("");
        return `<svg class="rp-rw-radar" viewBox="0 0 128 112" aria-hidden="true">
          <polygon points="${poly(1)}" fill="#f8fafc" stroke="#cbd5e1" stroke-width="0.8"/>
          <polygon points="${poly(0.65)}" fill="none" stroke="#e2e8f0" stroke-width="0.7"/>
          <polygon points="${poly(0.35)}" fill="none" stroke="#e2e8f0" stroke-width="0.7"/>
          <polygon points="${dataPoly}" fill="rgba(124,58,237,0.22)" stroke="#7c3aed" stroke-width="1.5"/>
          ${labelNodes}
        </svg>`;
      }

      function paintEffect(job, rewrite) {
        effectBox.replaceChildren();
        const hasRw = Boolean(rewriteText);
        const matched = Array.isArray(rewrite?.matched_skills) ? rewrite.matched_skills.length : 0;
        const missing = Array.isArray(rewrite?.missing_skills) ? rewrite.missing_skills.length : 0;
        const totalSkills = matched + missing;
        const covPct = totalSkills ? Math.round((matched / totalSkills) * 100) : 0;
        const diff = hasRw && baselineText ? computeResumeDiff(baselineText, rewriteText) : { addedCount: 0, removedCount: 0 };
        const lenRatio = hasRw && baselineText ? (rewriteText.length / Math.max(1, baselineText.length)) : 1;
        const lenPct = Math.round(lenRatio * 100);
        const score = Number(job?.score) || 70;
        const downgradesCount = Array.isArray(rewrite?.downgrades) ? rewrite.downgrades.length : 0;

        const left = node("div", "", "rp-rw-effect-title");
        left.append(inlineIcon("chart"), node("strong", "实测指标"));
        const metrics = node("div", "", "rp-rw-effect-metrics");
        const items = [
          ["精准微调", hasRw ? `${diff.addedCount} 处` : "待生成", "green"],
          ["技能覆盖", hasRw ? (totalSkills ? `${matched}/${totalSkills} (${covPct}%)` : "已对齐") : "待生成", "blue"],
          ["篇幅保持", hasRw ? `${lenPct}%` : "待生成", "violet"]
        ];
        for (const [label, val, tone] of items) {
          const tile = node("div", "", `rp-rw-metric tone-${tone}`);
          tile.append(node("span", label), node("strong", val));
          metrics.append(tile);
        }
        const radarWrap = document.createElement("div");
        radarWrap.className = "rp-rw-radar-wrap";
        const radarVals = hasRw ? [
          score / 100,
          totalSkills ? Math.max(0.3, matched / totalSkills) : 0.75,
          Math.max(0.35, 1 - Math.abs(lenRatio - 1) * 3),
          diff.addedCount ? Math.min(1, 0.55 + Math.min(diff.addedCount, 6) * 0.075) : 0.35,
          Math.max(0.6, 0.96 - downgradesCount * 0.08)
        ] : [0.35, 0.35, 0.35, 0.35, 0.35];
        radarWrap.innerHTML = buildRadarSvg(radarVals);
        effectBox.append(left, metrics, radarWrap);
      }

      function paintJobPreview() {
        const job = currentJob();
        jobPreview.replaceChildren();
        jobPreview.hidden = !job;
        if (!job) return;
        const av = node("span", "", "rp-rw-job-avatar");
        av.append(inlineIcon("briefcase"));
        const info = node("div", "", "rp-rw-job-info");
        info.append(node("strong", job.title || "未命名岗位"));
        const metaText = [job.company || "未知公司", RP.sourceLabel(job.source), job.salary].filter(Boolean).join(" · ");
        info.append(node("span", metaText));
        const right = node("div", "", "rp-rw-job-right");
        if (job.grade) {
          const pill = node("span", "", "rp-rw-match-pill");
          pill.append(node("span", "匹配度 "), node("strong", job.grade));
          right.append(pill);
        }
        right.append(node("span", "›", "rp-deep-arrow"));
        jobPreview.append(av, info, right);
      }

      let baselineOptions = [];
      loadConfig().then((data) => {
        if (!alive(token, body)) return;
        const baseline = data.resume_baseline || {};
        baselineOptions = baseline.options || [];
        baselineText = baseline.text || "";
        baselineSelect.replaceChildren(...baselineOptions.map((option) =>
          new Option(`${option.title}（${option.chars} 字）`, option.id)));
        if (!baselineOptions.length) {
          baselineSelect.replaceChildren(new Option("简历库暂无已解析文档", ""));
          baselineInfo.textContent = "请先在简历库保存或上传简历，再选择基准。";
        } else {
          const current = baselineOptions.find((option) => option.title === baseline.name);
          baselineSelect.value = current?.id || baselineOptions[0].id;
          baselineInfo.textContent = baseline.enabled
            ? `当前底稿：${baseline.name}`
            : "选择基准简历后，定向改写阶段即可执行。";
        }
        void loadCompare();
      }).catch((error) => {
        if (alive(token, body)) setFeedback(baselineFeedback, error.message, "error");
      });

      let compareSeq = 0;
      async function loadCompare() {
        const sequence = ++compareSeq;
        paintJobPreview();
        const job = currentJob();
        const selected = baselineOptions.find((option) => option.id === baselineSelect.value);
        baseDoc.replaceChildren();
        if (selected) {
          const top = node("div", "", "rp-rw-base-meta");
          top.append(node("h5", selected.title), node("span", `${selected.chars} 字`, "rp-rw-chars-pill"));
          baseDoc.append(top);
          baseDoc.append(node("p", "已梳理基础经历，包含教育、科研、项目与技能等完整内容。"));
        } else if (baselineOptions.length) {
          baseDoc.append(node("p", "正在同步基准简历…", "rp-doc-empty"));
        } else {
          baseDoc.append(node("p", "尚未选定基准简历。", "rp-doc-empty"));
        }
        const baseLink = node("a", "查看原文 ↗", "rp-rw-link");
        baseLink.href = meta.resumes_url;
        baseDoc.append(baseLink);
        rewriteDoc.replaceChildren(node("p", job ? "正在读取改写稿…" : "请先选择岗位。", "rp-doc-empty"));
        downgrades.hidden = true;
        rewriteText = "";
        lastRewriteObj = null;
        copyBtn.disabled = true;
        expandBtn.disabled = true;
        previewModalBtn.disabled = true;
        saveCopyBtn.disabled = true;
        paintEffect(job, null);
        if (!job) return;
        try {
          const payload = await RP.fetchJobPayload(job);
          if (sequence !== compareSeq || !alive(token, body)) return;
          const rewrite = payloadOf(payload, "rewrite_payload", "rewrite");
          lastRewriteObj = (rewrite && typeof rewrite === "object") ? rewrite : null;
          rewriteText = RP.payloadText(rewrite);
          renderRewriteBody();
          copyBtn.disabled = !rewriteText;
          expandBtn.disabled = !rewriteText;
          previewModalBtn.disabled = !rewriteText;
          saveCopyBtn.disabled = !rewriteText;
          paintEffect(job, lastRewriteObj);
          if (lastRewriteObj) {
            const list = Array.isArray(lastRewriteObj.downgrades) ? lastRewriteObj.downgrades : [];
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
      paintJobPreview();
      paintEffect(currentJob(), null);
    }
  });


})();
