/* 岗位全链路流水线 · 单岗位三栏联动作战室（柔光紫蓝三栏工作台） */
(() => {
  "use strict";
  const RP = window.RP;
  if (!RP || !RP.ui) return;
  const { node, toast, pipelineApi } = RP;
  const { button, gradeBadge, payloadOf, copyText, loadConfig } = RP.ui;

  const DRAFT_LABELS = { boss: "BOSS", zhilian: "智联", "51job": "前程无忧" };
  const KNOWN_TECH_TAGS = [
    "LangGraph", "LightRAG", "RAG", "MCP", "Dify", "FastAPI", "PostgreSQL", "pgvector",
    "PyTorch", "LoRA", "DoRA", "AdaLoRA", "Qwen2.5-7B", "Qwen", "Transformer", "Docker",
    "Python", "SQLite", "CARLA", "LSTM", "Deep SVDD", "FVAE", "Playwright", "RAGAS",
    "Chroma", "Agent", "多智能体", "知识图谱", "微调", "AIGC", "Linux", "Git",
  ];

  const CR_SVG = {
    ringIcon: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 9h10M7 13h6"/></svg>',
    warn: '<svg viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><path d="M12 9v4M12 17h.01"/></svg>',
    bulb: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.7.6 1 1.4 1 2.3h6c0-.9.3-1.7 1-2.3A7 7 0 0 0 12 2Z"/></svg>',
    doc: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>',
    edu: '<svg viewBox="0 0 24 24"><path d="M22 10 12 5 2 10l10 5 10-5Z"/><path d="M6 12v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5"/></svg>',
    briefcase: '<svg viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>',
    award: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="5"/><path d="m8.2 13.9-1.2 7.1 5-2.5 5 2.5-1.2-7.1"/></svg>',
    cpu: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21 7 14.2 2 9.3l6.9-1L12 2Z"/></svg>',
    pen: '<svg viewBox="0 0 24 24"><path d="M17 3a2.8 2.8 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>',
    sliders: '<svg viewBox="0 0 24 24"><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M2 14h4M10 8h4M18 16h4"/></svg>',
    sparkles: '<svg viewBox="0 0 24 24"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>',
    chat: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/></svg>',
  };

  function svgBadge(key, cls = "rp-cr-sec-ico") {
    const el = node("span", "", cls);
    el.innerHTML = CR_SVG[key] || CR_SVG.doc;
    return el;
  }

  function appendRichInline(target, text) {
    const re = /\[([^\]\n]+)\]\((https?:\/\/[^\s()]+)\)|\*\*([^\n*]+)\*\*/g;
    let last = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) target.append(document.createTextNode(text.slice(last, m.index)));
      if (m[1] && m[2]) {
        const a = node("a", `(${m[1]} ↗)`, "rp-cr-md-link");
        a.href = m[2]; a.target = "_blank"; a.rel = "noopener noreferrer";
        target.append(document.createTextNode(" "), a);
      } else if (m[3]) {
        target.append(node("strong", m[3]));
      }
      last = re.lastIndex;
    }
    if (last < text.length) target.append(document.createTextNode(text.slice(last)));
  }

  function extractTagsFromText(text) {
    const found = [];
    const lower = text.toLowerCase();
    for (const tag of KNOWN_TECH_TAGS) {
      if (lower.includes(tag.toLowerCase()) && !found.includes(tag)) {
        found.push(tag);
        if (found.length >= 6) break;
      }
    }
    return found;
  }

  function renderRichResume(container, markdown) {
    container.replaceChildren();
    const raw = String(markdown || "").trim();
    if (!raw) {
      container.append(node("p", "尚未生成该岗位改写稿，点击上方「AI 微调」即可生成。", "rp-cr-status"));
      return;
    }
    const lines = raw.split(/\r?\n/);
    let currentSection = "";
    let currentEntryBox = null;
    let currentEntryBullets = null;
    let currentEntryText = "";
    let currentEntryTagSlot = null;

    function flushEntryTags() {
      if (!currentEntryTagSlot || !currentEntryText) return;
      const tags = extractTagsFromText(currentEntryText);
      if (tags.length) {
        currentEntryTagSlot.replaceChildren(...tags.map(t => node("span", t, "rp-cr-tech-pill")));
        currentEntryTagSlot.hidden = false;
      }
    }

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;

      if (/^#{1,2}\s+/.test(line)) {
        flushEntryTags();
        currentEntryBox = null; currentEntryBullets = null; currentEntryText = ""; currentEntryTagSlot = null;
        const headingText = line.replace(/^#{1,2}\s+/, "").trim();
        if (headingText.startsWith("求职意向")) {
          const banner = node("div", "", "rp-cr-intent-line");
          appendRichInline(banner, headingText);
          container.append(banner);
          continue;
        }
        currentSection = headingText;
        const h = node("div", "", "rp-cr-res-sec-head");
        const icoKey = /教育/.test(headingText) ? "edu" : /项目|工作|实习/.test(headingText) ? "briefcase" : /奖|荣誉|科研/.test(headingText) ? "award" : "cpu";
        h.append(svgBadge(icoKey, "rp-cr-res-ico"), node("strong", headingText));
        container.append(h);
        continue;
      }

      if (line.startsWith("求职意向")) {
        const banner = node("div", "", "rp-cr-intent-line");
        appendRichInline(banner, line);
        container.append(banner);
        continue;
      }

      const isBullet = /^[-*•]\s+/.test(line);
      const isProjectSec = /项目|工作|实习/.test(currentSection);
      const cols = line.split(/[|｜]/).map(s => s.trim()).filter(Boolean);

      if (!isBullet && isProjectSec && (cols.length >= 2 || /^###\s+/.test(line))) {
        flushEntryTags();
        const entry = node("div", "", "rp-cr-res-entry");
        const top = node("div", "", "rp-cr-res-entry-top");
        const leftTitle = node("div", "", "rp-cr-res-entry-title");
        const titleRaw = line.replace(/^###\s+/, "");
        if (cols.length >= 2) {
          appendRichInline(leftTitle, cols[0]);
          const dateText = cols[cols.length - 1];
          top.append(leftTitle, node("span", dateText, "rp-cr-res-date"));
        } else {
          appendRichInline(leftTitle, titleRaw);
          top.append(leftTitle);
        }
        const tagSlot = node("div", "", "rp-cr-tech-row");
        tagSlot.hidden = true;
        const ul = node("ul", "", "rp-cr-res-ul");
        entry.append(top, tagSlot, ul);
        container.append(entry);
        currentEntryBox = entry;
        currentEntryTagSlot = tagSlot;
        currentEntryBullets = ul;
        currentEntryText = titleRaw;
        continue;
      }

      if (isBullet) {
        const content = line.replace(/^[-*•]\s+/, "");
        currentEntryText += " " + content;
        const li = node("li", "");
        appendRichInline(li, content);
        if (currentEntryBullets) {
          currentEntryBullets.append(li);
        } else {
          const ul = node("ul", "", "rp-cr-res-ul");
          ul.append(li);
          container.append(ul);
          currentEntryBullets = ul;
        }
        continue;
      }

      const p = node("p", "", "rp-cr-res-p");
      appendRichInline(p, line);
      container.append(p);
      currentEntryBullets = null;
    }
    flushEntryTags();
  }

  function scoreRingSvg(score) {
    const pct = score != null ? Math.max(0, Math.min(100, Number(score))) : 0;
    const r = 24;
    const circ = 2 * Math.PI * r;
    const offset = circ * (1 - pct / 100);
    const wrap = node("div", "", "rp-cr-ring-wrap");
    wrap.innerHTML =
      `<svg viewBox="0 0 60 60" class="rp-cr-ring-svg">` +
      `<defs><linearGradient id="rpCrRingG" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#60a5fa"/><stop offset="100%" stop-color="#4f46e5"/></linearGradient></defs>` +
      `<circle cx="30" cy="30" r="${r}" class="rp-cr-ring-bg"/>` +
      `<circle cx="30" cy="30" r="${r}" class="rp-cr-ring-fg" stroke="url(#rpCrRingG)" stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"/>` +
      `</svg>` +
      `<span class="rp-cr-ring-val">${score != null ? pct + "%" : "—"}</span>`;
    return wrap;
  }

  RP.openCombatRoom = async function openCombatRoom(job) {
    if (!job) return;
    const existing = document.getElementById("rpCombatDialog");
    if (existing) existing.remove();

    const dialog = document.createElement("dialog");
    dialog.id = "rpCombatDialog";
    dialog.className = "rp-cr-dialog";

    /* Top Header */
    const head = node("header", "", "rp-cr-head");
    const headWave = node("div", "", "rp-cr-head-wave");
    headWave.setAttribute("aria-hidden", "true");
    headWave.innerHTML = `<svg viewBox="0 0 1200 120" preserveAspectRatio="none"><defs><linearGradient id="rpCrWaveG" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="#c7d2fe" stop-opacity="0.35"/><stop offset="48%" stop-color="#818cf8" stop-opacity="0.45"/><stop offset="100%" stop-color="#93c5fd" stop-opacity="0.35"/></linearGradient></defs><path d="M260,0 C480,10 560,72 740,52 C920,32 1030,0 1200,0 L1200,120 L0,120 L0,0 Z" fill="url(#rpCrWaveG)" opacity="0.55"/><path d="M0,18 C220,5 420,98 690,58 C880,30 1020,8 1200,14 L1200,120 L0,120 Z" fill="#ffffff" fill-opacity="0.62"/></svg>`;

    const headBrand = node("div", "", "rp-cr-head-brand");
    const monogramChar = (String(job.title || "A").replace(/^[^A-Za-z\u4e00-\u9fff]+/, "")[0] || "A").toUpperCase();
    const monogram = node("span", monogramChar, "rp-cr-monogram");
    const titleWrap = node("div", "", "rp-cr-head-left");
    titleWrap.append(
      node("strong", job.title || "未命名岗位"),
      node("span", [job.company, RP.sourceLabel(job.source), job.location, job.salary].filter(Boolean).join(" · "), "rp-cr-sub")
    );
    headBrand.append(monogram, titleWrap);

    const headRight = node("div", "", "rp-cr-head-right");
    if (job.grade) {
      const gPill = node("span", job.grade, "rp-cr-grade-circle");
      gPill.dataset.grade = job.grade;
      headRight.append(gPill);
    }
    if (job.score != null) headRight.append(node("span", `${job.score} 分`, "rp-cr-score"));
    const approveBtn = button("放行投递", "rp-rv-approve-btn", "send");
    const closeBtn = node("button", "×", "rp-rw-modal-close");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "关闭作战室");
    closeBtn.addEventListener("click", () => dialog.close());
    headRight.append(approveBtn, closeBtn);
    head.append(headWave, headBrand, headRight);

    /* 3-Column Linked Grid */
    const grid = node("div", "", "rp-cr-grid");

    /* ====== Pane 1: 岗位 JD 与深度诊断 ====== */
    const paneLeft = node("section", "", "rp-cr-pane");
    const leftHead = node("div", "", "rp-cr-pane-head");
    leftHead.append(node("strong", "1. 岗位 JD 与深度诊断"));
    const leftBody = node("div", "", "rp-cr-pane-body");
    leftBody.textContent = "正在加载岗位详情与深评诊断…";
    paneLeft.append(leftHead, leftBody);

    /* ====== Pane 2: 专属简历 ====== */
    const paneMid = node("section", "", "rp-cr-pane");
    const midHead = node("div", "", "rp-cr-pane-head rp-cr-pane-head-tabs");
    const midLeft = node("div", "", "rp-cr-tabs-left");
    midLeft.append(node("strong", "2. 专属简历"));
    const rwTabView = node("button", "成稿预览", "rp-cr-utab");
    const rwTabEdit = node("button", "编辑源码", "rp-cr-utab");
    rwTabView.type = "button"; rwTabEdit.type = "button";
    rwTabView.dataset.active = "1"; rwTabEdit.dataset.active = "0";
    midLeft.append(rwTabView, rwTabEdit);

    const midHeadBtns = node("div", "", "rp-cr-btn-group");
    const rwRunBtn = button("AI 微调", "rp-btn-sm rp-btn-primary", "sparkles");
    const rwSaveBtn = button("保存", "rp-btn-sm rp-btn-ghost", "check");
    const rwCopyDraftBtn = button("存副本", "rp-btn-sm rp-btn-ghost", "save");
    midHeadBtns.append(rwRunBtn, rwSaveBtn, rwCopyDraftBtn);
    midHead.append(midLeft, midHeadBtns);

    const midBody = node("div", "", "rp-cr-pane-body rp-cr-mid-body");
    const rwPreview = node("div", "", "rp-cr-resume-sheet");
    const rwEditor = node("textarea", "", "rp-cr-editor");
    rwEditor.hidden = true;
    rwEditor.placeholder = "点击上方「AI 微调」生成该岗位专属改写稿，也可切换到「编辑源码」手动微调并保存。";
    const rwStatus = node("div", "", "rp-cr-status");
    midBody.append(rwPreview, rwEditor, rwStatus);
    paneMid.append(midHead, midBody);

    function syncRwPreview() { renderRichResume(rwPreview, rwEditor.value); }
    rwTabView.addEventListener("click", () => {
      rwTabView.dataset.active = "1"; rwTabEdit.dataset.active = "0";
      syncRwPreview();
      rwPreview.hidden = false; rwEditor.hidden = true;
    });
    rwTabEdit.addEventListener("click", () => {
      rwTabView.dataset.active = "0"; rwTabEdit.dataset.active = "1";
      rwPreview.hidden = true; rwEditor.hidden = false;
      rwEditor.focus();
    });

    /* ====== Pane 3: 打招呼语 & 面试押题 ====== */
    const paneRight = node("section", "", "rp-cr-pane");
    const rightHead = node("div", "", "rp-cr-pane-head rp-cr-pane-head-tabs");
    const rightTabs = node("div", "", "rp-cr-tabs-left");
    const tabGreet = node("button", "3. 打招呼语", "rp-cr-utab");
    const tabPrep = node("button", "面试押题", "rp-cr-utab");
    tabGreet.type = "button"; tabPrep.type = "button";
    tabGreet.dataset.active = "1"; tabPrep.dataset.active = "0";
    rightTabs.append(tabGreet, tabPrep);
    rightHead.append(rightTabs);

    const rightBody = node("div", "", "rp-cr-pane-body");

    /* Tab A: Greeting */
    const greetPane = node("div", "", "rp-cr-stack");
    const hero = node("div", "", "rp-cr-gr-hero");
    const heroCopy = node("div", "", "rp-cr-gr-hero-copy");
    heroCopy.append(node("strong", "AI 微调打招呼语"), node("span", "基于岗位 JD 与原始母本生成自然开场白"));
    const heroDeco = node("div", "", "rp-cr-gr-hero-deco");
    heroDeco.innerHTML = CR_SVG.sparkles;
    hero.append(heroCopy, heroDeco);

    const greetCtrl = node("div", "", "rp-cr-btn-group");
    const styleSel = node("select", "", "rp-cr-select");
    for (const [k, l] of [["standard", "标准微调"], ["concise", "精炼直击"], ["project", "突出项目"]]) {
      const o = node("option", l); o.value = k; styleSel.append(o);
    }
    const grRunBtn = button("AI 生成", "rp-btn-sm rp-btn-primary", "sparkles");
    const grSaveBtn = button("保存", "rp-btn-sm rp-btn-ghost", "check");
    const grCopyBtn = button("复制", "rp-btn-sm rp-btn-ghost", "copy");
    const grClearBtn = button("清空", "rp-btn-sm rp-btn-ghost");
    const grResetBtn = button("母本", "rp-btn-sm rp-btn-ghost");
    grResetBtn.hidden = true;
    greetCtrl.append(styleSel, grRunBtn, grSaveBtn, grCopyBtn, grClearBtn, grResetBtn);

    const grBoxWrap = node("div", "", "rp-cr-gr-box");
    const grEditor = node("textarea", "", "rp-cr-gr-textarea");
    grEditor.rows = 7;
    grEditor.placeholder = "默认预填你的原始打招呼语母本；可直接清空粘贴新文案，再点「AI 生成」按 JD 关键词微调。";
    const grCounter = node("span", "0 字", "rp-cr-gr-counter");
    grBoxWrap.append(grEditor, grCounter);
    const syncCounter = () => { grCounter.textContent = `${grEditor.value.replace(/\s/g, "").length} 字`; };
    grEditor.addEventListener("input", syncCounter);

    const grKwBar = node("div", "", "rp-gr-kw-row");
    const grBottom = node("div", "", "rp-cr-stack");
    const grStatus = node("div", "", "rp-cr-status");
    if (DRAFT_LABELS[job.source]) {
      const pLabel = DRAFT_LABELS[job.source];
      const draftBtn = node("button", "", "rp-cr-cta-btn");
      draftBtn.type = "button";
      draftBtn.innerHTML = `${CR_SVG.chat}<span>一键填入 ${pLabel} 草稿（不发送）</span>`;
      draftBtn.addEventListener("click", async () => {
        draftBtn.disabled = true;
        grStatus.textContent = `正在 Chrome 打开${pLabel}岗位聊天框并填入草稿…`;
        try {
          const res = await pipelineApi("/deliver_draft", { source: job.source, url_key: job.url_key });
          grStatus.textContent = res.message || "已填入草稿（未发送）。";
          toast("已填入聊天草稿，切换 Chrome 按 Enter 发送。", "success");
        } catch (err) {
          grStatus.textContent = err.message;
          toast(err.message, "error");
        } finally { draftBtn.disabled = false; }
      });
      grBottom.append(draftBtn);
    }

    /* 3-Tile Quick Optimization Shortcuts */
    const quickSec = node("div", "", "rp-cr-quick-sec");
    const quickTitle = node("div", "", "rp-cr-quick-head");
    quickTitle.append(svgBadge("bulb", "rp-cr-mini-ico"), node("span", "快捷一键微调"));
    const quickGrid = node("div", "", "rp-cr-quick-grid");
    const quickTiles = [
      ["star", "亮点提炼", "project"],
      ["pen", "表达润色", "standard"],
      ["sliders", "长度控制", "concise"],
    ].map(([ico, label, st]) => {
      const tile = node("button", "", "rp-cr-quick-tile");
      tile.type = "button";
      tile.append(svgBadge(ico, "rp-cr-tile-ico"), node("span", label));
      tile.addEventListener("click", () => {
        styleSel.value = st;
        grRunBtn.click();
      });
      return tile;
    });
    quickGrid.append(...quickTiles);
    quickSec.append(quickTitle, quickGrid);

    greetPane.append(hero, greetCtrl, grBoxWrap, grKwBar, grBottom, grStatus, quickSec);

    /* Tab B: Interview Prep */
    const prepPane = node("div", "", "rp-cr-stack");
    prepPane.hidden = true;
    const prepBtn = button("生成该岗位专属面试押题", "rp-btn-sm rp-btn-primary", "sparkles");
    const prepOut = node("div", "", "rp-cr-prep-out");
    prepOut.append(node("p", "结合当前岗位 JD、你的定制简历与深评红旗，预测高频技术追问与反问清单。", "rp-cr-status"));
    prepPane.append(prepBtn, prepOut);

    tabGreet.addEventListener("click", () => {
      tabGreet.dataset.active = "1"; tabPrep.dataset.active = "0";
      greetPane.hidden = false; prepPane.hidden = true;
    });
    tabPrep.addEventListener("click", () => {
      tabGreet.dataset.active = "0"; tabPrep.dataset.active = "1";
      greetPane.hidden = true; prepPane.hidden = false;
    });

    rightBody.append(greetPane, prepPane);
    paneRight.append(rightHead, rightBody);

    grid.append(paneLeft, paneMid, paneRight);
    dialog.append(head, grid);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();

    /* Load Data */
    let savedBaseGreeting = "";

    function renderLeft(data) {
      leftBody.replaceChildren();
      const deep = payloadOf(data, "deep_payload", "deep") || {};

      /* 1. 匹配概览卡片 */
      const matchCard = node("div", "", "rp-cr-match-card");
      const mcTitle = node("div", "", "rp-cr-card-label");
      mcTitle.append(svgBadge("ringIcon", "rp-cr-mini-ico"), node("span", "匹配概览"));
      const mcRow = node("div", "", "rp-cr-match-row");
      const mcCopy = node("div", "", "rp-cr-match-copy");
      mcCopy.append(
        node("strong", "岗位匹配度"),
        node("span", job.grade ? `${job.grade} 级 · 与岗位要求的综合匹配程度` : "与岗位要求的综合匹配程度")
      );
      mcRow.append(scoreRingSvg(job.score), mcCopy);
      matchCard.append(mcTitle, mcRow);

      const matched = Array.isArray(deep.matched_skills) ? deep.matched_skills : [];
      const missing = Array.isArray(deep.missing_skills) ? deep.missing_skills : [];
      if (matched.length || missing.length) {
        const chips = node("div", "", "rp-gr-kw-row");
        matched.slice(0, 8).forEach(s => { const c = node("span", `✓ ${s}`, "rp-gr-kw-chip"); c.dataset.hit = "1"; chips.append(c); });
        missing.slice(0, 6).forEach(s => { const c = node("span", `缺口: ${s}`, "rp-gr-kw-chip"); chips.append(c); });
        matchCard.append(chips);
      }
      leftBody.append(matchCard);

      /* 2. 风险红旗卡片 */
      if (deep.risk_red_flags) {
        const riskCard = node("div", "", "rp-cr-risk-card");
        const rHead = node("div", "", "rp-cr-risk-head");
        rHead.append(svgBadge("warn", "rp-cr-warn-ico"), node("strong", "风险红旗"));
        riskCard.append(rHead, node("p", String(deep.risk_red_flags)));
        leftBody.append(riskCard);
      }

      /* 3. 行动建议可勾选清单 */
      const actionRaw = String(deep.deep_action_plan || deep.strong_fit_assessment || "").trim();
      if (actionRaw) {
        const actCard = node("div", "", "rp-cr-box rp-cr-check-card");
        const aHead = node("div", "", "rp-cr-card-label");
        aHead.append(svgBadge("bulb", "rp-cr-mini-ico"), node("strong", "行动建议"));
        actCard.append(aHead);
        const items = actionRaw.split(/\r?\n/).map(s => s.replace(/^[\d.)、\-*•\s]+/, "").trim()).filter(Boolean).slice(0, 5);
        const checklist = node("div", "", "rp-cr-checklist");
        items.forEach((txt, i) => {
          const lbl = node("label", "", "rp-cr-check-item");
          const cb = node("input"); cb.type = "checkbox";
          if (i === 0 && job.hasRewrite) cb.checked = true;
          lbl.append(cb, node("span", txt));
          checklist.append(lbl);
        });
        actCard.append(checklist);
        leftBody.append(actCard);
      }

      /* 4. 原始岗位 JD 折叠卡 */
      const jdFold = node("details", "", "rp-cr-jd-fold");
      jdFold.open = true;
      const jdSum = node("summary", "");
      jdSum.append(svgBadge("doc", "rp-cr-mini-ico"), node("strong", "原始岗位 JD"));
      jdFold.append(jdSum, node("p", data.description || "暂无岗位描述"));
      leftBody.append(jdFold);
    }

    function renderGreetKw(greetingObj) {
      const kws = Array.isArray(greetingObj?.matched_keywords) ? greetingObj.matched_keywords : [];
      if (!kws.length) { grKwBar.replaceChildren(); return; }
      const lower = grEditor.value.toLowerCase();
      grKwBar.replaceChildren(
        node("span", "JD 命中：", "rp-gr-kw-label"),
        ...kws.map(kw => {
          const c = node("span", kw, "rp-gr-kw-chip");
          c.dataset.hit = lower.includes(String(kw).toLowerCase()) ? "1" : "0";
          return c;
        })
      );
    }

    try {
      const [payloadData, cfgData] = await Promise.all([
        RP.fetchJobPayload(job),
        loadConfig().catch(() => ({})),
      ]);
      savedBaseGreeting = String(cfgData?.settings?.mass_greeting || "").trim();
      grResetBtn.hidden = !savedBaseGreeting;
      renderLeft(payloadData);
      const rw = payloadOf(payloadData, "rewrite_payload", "rewrite");
      rwEditor.value = RP.payloadText(rw) || "";
      syncRwPreview();
      rwStatus.textContent = rwEditor.value ? `已加载改写稿 · ${rwEditor.value.length} 字` : "尚未生成改写稿";
      const gr = payloadOf(payloadData, "greeting_payload", "greeting");
      const existingGr = RP.payloadText(gr) || "";
      if (existingGr) {
        grEditor.value = existingGr;
        renderGreetKw(gr);
        grStatus.textContent = "当前为该岗位已保存打招呼语";
      } else if (savedBaseGreeting) {
        grEditor.value = savedBaseGreeting;
        grStatus.textContent = "已默认载入原始母本，可直接微调或清空换新";
      } else {
        grEditor.value = "";
        grStatus.textContent = "可直接输入文案或点击「AI 生成」";
      }
      syncCounter();
    } catch (err) {
      leftBody.textContent = err.message || "加载失败";
    }

    /* Actions */
    rwRunBtn.addEventListener("click", async () => {
      rwRunBtn.disabled = true;
      rwStatus.textContent = "AI 正在结合 JD 精准微调简历…";
      try {
        await pipelineApi("/run", { stage: "rewrite", source: job.source, url_key: job.url_key });
        const fresh = await RP.fetchJobPayload(job);
        const rw = payloadOf(fresh, "rewrite_payload", "rewrite");
        rwEditor.value = RP.payloadText(rw) || "";
        syncRwPreview();
        rwStatus.textContent = `微调完成 · ${rwEditor.value.length} 字`;
        toast("已完成简历精准微调。", "success");
        void RP.refresh({ silent: true });
      } catch (err) { rwStatus.textContent = err.message; toast(err.message, "error"); }
      finally { rwRunBtn.disabled = false; }
    });

    rwSaveBtn.addEventListener("click", async () => {
      const md = rwEditor.value.trim();
      if (!md) { toast("简历内容为空。", "warning"); return; }
      rwSaveBtn.disabled = true;
      try {
        await pipelineApi("/rewrite/save", { source: job.source, url_key: job.url_key, markdown: md });
        syncRwPreview();
        rwStatus.textContent = `已保存 · ${md.length} 字`;
        toast("定制简历修改已保存。", "success");
      } catch (err) { toast(err.message, "error"); }
      finally { rwSaveBtn.disabled = false; }
    });

    rwCopyDraftBtn.addEventListener("click", async () => {
      const md = rwEditor.value.trim();
      if (!md) { toast("请先生成或填写简历内容。", "warning"); return; }
      rwCopyDraftBtn.disabled = true;
      try {
        const res = await fetch("/api/resume-editor/from-markdown", {
          method: "POST",
          headers: { ...(window.CareerAuth ? await window.CareerAuth.headers() : {}), "Content-Type": "application/json" },
          body: JSON.stringify({ title: `${job.company || job.title} · 专属简历`, markdown: md }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.message || "创建副本失败");
        toast("已存为该公司专属副本（不破坏原始简历）。", "success");
        if (data.id) window.open(`/user-center/resumes?draft=${encodeURIComponent(data.id)}`, "_blank");
      } catch (err) { toast(err.message, "error"); }
      finally { rwCopyDraftBtn.disabled = false; }
    });

    grClearBtn.addEventListener("click", () => {
      grEditor.value = "";
      syncCounter();
      grEditor.focus();
      grStatus.textContent = "已清空，可直接粘贴新文案再点「AI 生成」或「保存」。";
    });
    grResetBtn.addEventListener("click", () => {
      if (!savedBaseGreeting) return;
      grEditor.value = savedBaseGreeting;
      syncCounter();
      grStatus.textContent = "已恢复原始母本。";
    });

    grRunBtn.addEventListener("click", async () => {
      grRunBtn.disabled = true;
      grStatus.textContent = "AI 正在基于当前文案结合 JD 关键词微调…";
      try {
        const draftBase = grEditor.value.trim();
        const data = await pipelineApi("/run", {
          stage: "greet",
          source: job.source,
          url_key: job.url_key,
          style: styleSel.value,
          ...(draftBase ? { base_greeting: draftBase } : {}),
        });
        grEditor.value = RP.payloadText(data.greeting) || "";
        syncCounter();
        renderGreetKw(data.greeting);
        grStatus.textContent = "微调完成";
        toast("打招呼语已微调完成。", "success");
        void RP.refresh({ silent: true });
      } catch (err) { grStatus.textContent = err.message; toast(err.message, "error"); }
      finally { grRunBtn.disabled = false; }
    });

    grSaveBtn.addEventListener("click", async () => {
      const txt = grEditor.value.trim();
      if (!txt) { toast("打招呼语为空。", "warning"); return; }
      grSaveBtn.disabled = true;
      try {
        const data = await pipelineApi("/greeting/save", { source: job.source, url_key: job.url_key, text: txt });
        renderGreetKw(data.greeting);
        grStatus.textContent = "已保存";
        toast("打招呼语已保存。", "success");
        void RP.refresh({ silent: true });
      } catch (err) { toast(err.message, "error"); }
      finally { grSaveBtn.disabled = false; }
    });

    grCopyBtn.addEventListener("click", () => copyText(grEditor.value.trim(), "打招呼语已复制。"));

    prepBtn.addEventListener("click", async () => {
      prepBtn.disabled = true;
      prepOut.replaceChildren(node("p", "正在结合 JD 与定制简历生成高频技术拷打题…", "rp-cr-status"));
      try {
        const data = await pipelineApi("/interview-prep", { source: job.source, url_key: job.url_key });
        const prep = data.prep || {};
        prepOut.replaceChildren();
        if (Array.isArray(prep.tech_questions) && prep.tech_questions.length) {
          const box = node("div", "", "rp-cr-box");
          box.append(node("h4", "高频技术追问"));
          prep.tech_questions.forEach((q, i) => {
            const item = node("div", "", "rp-cr-qa");
            item.append(
              node("strong", `${i + 1}. ${q.question || ""}`),
              node("span", `考察：${q.focus || ""}`, "rp-cr-qa-focus"),
              node("p", `答题要点：${q.tip || ""}`)
            );
            box.append(item);
          });
          prepOut.append(box);
        }
        if (Array.isArray(prep.red_flag_defenses) && prep.red_flag_defenses.length) {
          const box = node("div", "", "rp-cr-box");
          box.append(node("h4", "潜在质疑与应对策略"));
          prep.red_flag_defenses.forEach(r => {
            const item = node("div", "", "rp-cr-qa");
            item.append(node("strong", `风险：${r.risk || ""}`), node("p", r.strategy || ""));
            box.append(item);
          });
          prepOut.append(box);
        }
        if (Array.isArray(prep.reverse_questions) && prep.reverse_questions.length) {
          const box = node("div", "", "rp-cr-box");
          box.append(node("h4", "反问面试官建议"));
          prep.reverse_questions.forEach(q => box.append(node("p", `• ${q}`)));
          prepOut.append(box);
        }
      } catch (err) {
        prepOut.replaceChildren(node("p", err.message || "生成失败", "rp-cr-status"));
      } finally { prepBtn.disabled = false; }
    });

    approveBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      try {
        await pipelineApi("/approve", { source: job.source, url_key: job.url_key, decision: "approve" });
        toast("已放行进入待投递队列。", "success");
        void RP.refresh({ silent: true });
        dialog.close();
      } catch (err) {
        toast(err.message, "error");
        approveBtn.disabled = false;
      }
    });
  };
})();
