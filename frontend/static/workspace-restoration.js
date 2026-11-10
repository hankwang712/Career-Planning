(function () {
  const REPORT_POLL_INTERVAL_MS = 4000;
  const PLAN_STORAGE_PREFIX = "dp_overlay_plans_v1_";
  const PLAN_PROGRESS_PREFIX = "dp_plan_progress_v1_";
  const DEFAULT_STAGE_PROGRESS = [
    { key: "resume_analysis", label: "简历分析", status: "pending" },
    { key: "job_analysis", label: "岗位分析", status: "pending" },
    { key: "recruitment_search", label: "招聘雷达", status: "pending" },
    { key: "career_decision", label: "职业决策", status: "pending" },
    { key: "review", label: "补充与确认", status: "pending" },
    { key: "action_planning", label: "行动规划", status: "pending" },
    { key: "report_writer", label: "报告合成", status: "pending" }
  ];

  const reportRuntime = {
    pollTimer: 0,
    renderQueued: false,
    planWrapped: false,
    eventsBound: false,
    previousBodyOverflow: "",
    feedbackVerdict: "",
    feedbackNote: "",
    editorSource: null,
    editorSelection: null,
    editorDiff: null,
    editorConversation: [],
    editorMode: "edit",
    editorViewMode: "rendered",
    /** 正文区：preview | edit | diff（对齐 ai润色.html） */
    editorDocMode: "preview",
    editorSegments: [],
    editorSelectedRange: null,
    editorAnchorIndex: -1,
    /** 最近一次成功加载的 `reportId|snapshotId`，用于会话内跳过重复 GET */
    editorSourceLoadKey: "",
    /** 同 key 并发 in-flight 合并 */
    editorSourceInflight: new Map(),
    /** 右侧栏：chat | changes */
    editorRailView: "chat",
    /** 润色 API 请求中：对话区展示占位加载 */
    editorPolishPending: false,
    /** Keep All 后保留的 diff 快照，供中间区 Diff 与右侧「改动」继续展示增删 */
    editorDiffArchive: null,
    /** 每次「全部采纳」累积的改动条目（右侧列表） */
    appliedChangeBullets: [],
    /** 累计行级增删数（角标用） */
    cumulativeDiffLines: 0,
    /** 与上次成功「保存」或服务端加载一致的 Markdown 基线；未保存的本地修改不会写回阅览室正式稿 */
    editorSavedMarkdown: "",
    editorSavePending: false,
    exportPending: false,
    editorBeforeUnloadBound: false
  };

  function normalizeEditorMarkdownBaseline(value) {
    return String(value ?? "").replace(/\r\n/g, "\n");
  }

  function cloneCareerReportBundleForAppState(bundle) {
    if (!bundle || typeof bundle !== "object") return bundle;
    try {
      return structuredClone(bundle);
    } catch (_) {
      try {
        return JSON.parse(JSON.stringify(bundle));
      } catch {
        return bundle;
      }
    }
  }

  function isCareerReportEditorDirty() {
    const ta = document.getElementById("reportEditorTextarea");
    if (!ta) return false;
    return (
      normalizeEditorMarkdownBaseline(ta.value) !== normalizeEditorMarkdownBaseline(reportRuntime.editorSavedMarkdown)
    );
  }

  function updateCareerReportEditorDirtyUi() {
    const shell = document.querySelector(".report-editor-shell.report-editor-shell--polish-v2");
    const saveBtn = document.getElementById("reportEditorSaveBtn");
    const dirty = isCareerReportEditorDirty();
    shell?.classList.toggle("report-editor-shell--unsaved", dirty);
    if (saveBtn) {
      saveBtn.title = dirty
        ? "\u672a\u4fdd\u5b58\uff1a\u70b9\u300c\u4fdd\u5b58\u300d\u540e\u624d\u4f1a\u5199\u5165\u804c\u4e1a\u62a5\u544a\u6b63\u6587\uff08\u9605\u89c8\u5ba4\uff09"
        : "\u4fdd\u5b58\u7f16\u8f91\u5185\u5bb9\u5e76\u540c\u6b65\u804c\u4e1a\u62a5\u544a\u6b63\u6587\uff08\u82e5\u5f53\u524d\u4e3a\u6b63\u5f0f\u7a3f\uff09";
    }
  }

  function setCareerReportEditorSavePending(pending) {
    reportRuntime.editorSavePending = Boolean(pending);
    const saveBtn = document.getElementById("reportEditorSaveBtn");
    if (!saveBtn) return;
    saveBtn.disabled = reportRuntime.editorSavePending;
    saveBtn.setAttribute("aria-busy", reportRuntime.editorSavePending ? "true" : "false");
    saveBtn.textContent = reportRuntime.editorSavePending ? "保存中..." : "保存";
  }

  function reportEditorBeforeUnloadHandler(event) {
    const overlay = document.getElementById("reportEditorOverlay");
    if (!overlay || overlay.classList.contains("hidden")) return;
    if (!isCareerReportEditorDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  }

  function ensureReportEditorBeforeUnloadListener() {
    if (reportRuntime.editorBeforeUnloadBound) return;
    reportRuntime.editorBeforeUnloadBound = true;
    window.addEventListener("beforeunload", reportEditorBeforeUnloadHandler);
  }

  const avatarRuntime = {
    username: "",
    state: null
  };

  function ensureAppState() {
    if (!window.appState || typeof window.appState !== "object") {
      window.appState = {};
    }
    Object.assign(window.appState, {
      careerReport: window.appState.careerReport || null,
      careerReportState: window.appState.careerReportState || null,
      careerReportTracker: window.appState.careerReportTracker || null,
      careerReportVersions: Array.isArray(window.appState.careerReportVersions) ? window.appState.careerReportVersions : [],
      careerReportCanonicalId: String(window.appState.careerReportCanonicalId || "").trim(),
      careerReportViewingHistorical: Boolean(window.appState.careerReportViewingHistorical),
      reportGenerated: Boolean(window.appState.reportGenerated),
      reportReady: Boolean(window.appState.reportReady)
    });
  }

  function esc(value) {
    if (typeof window.escHtml === "function") return window.escHtml(value);
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatText(value) {
    return esc(String(value || "").trim()).replace(/\n/g, "<br>");
  }

  /**
   * 轻量 Markdown→HTML（职业报告正文）。不引入外部依赖，保持与现有 md 文件兼容。
   * @param {{ wrapProse?: boolean }} [options] wrapProse 默认 true，套一层专业排版容器
   */
  /** 与正文锚点 id 规则一致，供目录树解析 */
  function buildHeadingAnchorQueues(md) {
    const lines = String(md || "").split("\n");
    const h2 = [];
    const h3 = [];
    const h4 = [];
    let h2i = 0;
    let h3i = 0;
    let curH2 = -1;
    let curH3 = -1;
    let h4i = 0;
    for (const raw of lines) {
      const t = raw.trim();
      if (/^## /.test(t) && !/^###/.test(t)) {
        curH2 = h2i++;
        h3i = 0;
        curH3 = -1;
        h4i = 0;
        h2.push(`cr-md-h2-${curH2}`);
      } else if (/^### /.test(t)) {
        curH3 = h3i;
        h4i = 0;
        const id = curH2 < 0 ? `cr-md-h3-0-${h3i++}` : `cr-md-h3-${curH2}-${h3i++}`;
        h3.push(id);
      } else if (/^#### /.test(t)) {
        h4.push(`cr-md-h4-${Math.max(0, curH2)}-${Math.max(0, curH3)}-${h4i++}`);
      }
    }
    return { h2, h3, h4 };
  }

  /**
   * 从阅读态 Markdown 解析 ## / ### 层级，用于树形目录（id 与 buildHeadingAnchorQueues 一致）。
   */
  function buildMarkdownTocBranches(md) {
    const numbered = window.CareerReportReader ? window.CareerReportReader.numberMarkdown(md) : md;
    const lines = String(numbered || "").split("\n");
    let h2i = 0;
    let h3i = 0;
    let curH2 = -1;
    let curH3 = -1;
    let h4i = 0;
    const branches = [];
    let lineNo = 0;
    for (const raw of lines) {
      lineNo += 1;
      const t = raw.trim();
      if (/^## /.test(t) && !/^###/.test(t)) {
        curH2 = h2i++;
        h3i = 0;
        curH3 = -1;
        h4i = 0;
        branches.push({
          id: `cr-md-h2-${curH2}`,
          title: t.replace(/^##\s+/, ""),
          line: lineNo,
          subs: []
        });
      } else if (/^### /.test(t)) {
        curH3 = h3i;
        h4i = 0;
        const title = t.replace(/^###\s+/, "");
        const id = curH2 < 0 ? `cr-md-h3-0-${h3i++}` : `cr-md-h3-${curH2}-${h3i++}`;
        const sub = { id, title, line: lineNo, depth: 3 };
        if (branches.length && branches[branches.length - 1].subs) {
          branches[branches.length - 1].subs.push(sub);
        }
      } else if (/^#### /.test(t) && branches.length) {
        branches[branches.length - 1].subs.push({
          id: `cr-md-h4-${Math.max(0, curH2)}-${Math.max(0, curH3)}-${h4i++}`,
          title: t.replace(/^####\s+/, ""), line: lineNo, depth: 4
        });
      }
    }
    return branches;
  }

  function getCareerReportReadingMarkdown(bundle) {
    let raw = String(bundle?.report_document?.markdown || "").trim();
    if (!raw) raw = String(stitchModularMarkdownFromBundle(bundle) || "").trim();
    return markdownForCareerReportReading(raw);
  }

  function renderMarkdownTocNavHtml(branches, options = {}) {
    const variant = options.variant || "aside";
    if (!branches || !branches.length) return "";
    const subsClip = variant === "aside" ? 80 : 120;
    if (variant === "editor") {
      const rows = branches.map((br, bi) => {
        const hasSubs = Array.isArray(br.subs) && br.subs.length > 0;
        const startExpanded = bi === 0;
        const line = Number(br.line) || 1;
        const collapseCtrl = hasSubs
          ? `<button type="button" class="collapse-icon${startExpanded ? " open" : ""}" aria-expanded="${startExpanded ? "true" : "false"}" aria-label="展开或收起子章节">▶</button>`
          : `<span class="collapse-icon collapse-icon--placeholder" aria-hidden="true"></span>`;
        const subsHtml = hasSubs
          ? `<div class="tree-children${startExpanded ? "" : " collapsed"}">${br.subs
              .map((s) => {
                const shortTitle = s.title.length > subsClip ? `${s.title.slice(0, subsClip)}…` : s.title;
                const sline = Number(s.line) || 1;
                return `<div class="tree-item ${s.depth === 4 ? "level-3" : "level-2"}" data-editor-goto-line="${sline}" role="button" tabindex="0">
              <span class="toc-radio" aria-hidden="true"></span>
              <span class="tree-label">${esc(shortTitle)}</span>
            </div>`;
              })
              .join("")}</div>`
          : "";
        return `<div class="tree-toc-branch">
        <div class="tree-item${hasSubs ? " tree-item--has-subs" : ""}" data-editor-goto-line="${line}" role="button" tabindex="0">
          ${collapseCtrl}
          <span class="toc-radio" aria-hidden="true"></span>
          <span class="tree-label">${esc(br.title)}</span>
        </div>
        ${subsHtml}
      </div>`;
      }).join("");
      return rows;
    }
    const rows = branches.map((br) => {
      const hasSubs = Array.isArray(br.subs) && br.subs.length > 0;
      const startExpanded = variant !== "aside";
      const h2Btn = `<button type="button" class="cr-md-toc-h2${hasSubs ? " has-children" : ""}" data-report-scroll-target="${esc(br.id)}">${esc(br.title)}</button>`;
      const toggle = hasSubs
        ? `<button type="button" class="cr-md-toc-toggle${startExpanded ? " is-open" : ""}" aria-expanded="${startExpanded ? "true" : "false"}" aria-label="展开或收起子章节"></button>`
        : `<span class="cr-md-toc-toggle-spacer" aria-hidden="true"></span>`;
      const subsHtml = hasSubs
        ? `<div class="cr-md-toc-subs"${startExpanded ? "" : " hidden"}>${br.subs
            .map((s) => {
              const shortTitle = s.title.length > subsClip ? `${s.title.slice(0, subsClip)}…` : s.title;
              return `<button type="button" class="${s.depth === 4 ? "cr-md-toc-h4" : "cr-md-toc-h3"}" data-report-scroll-target="${esc(s.id)}">${esc(shortTitle)}</button>`;
            })
            .join("")}</div>`
        : "";
      return `
      <div class="cr-md-toc-branch${startExpanded ? " is-open" : ""}">
        <div class="cr-md-toc-row">
          ${toggle}
          ${h2Btn}
        </div>
        ${subsHtml}
      </div>`;
    }).join("");
    if (variant === "overlay") {
      return `
      <nav class="cr-md-toc cr-md-toc--overlay report-viewer-toc-tree" aria-label="报告目录">
        <div class="report-viewer-toc-label">目录</div>
        <div class="cr-md-toc-body">${rows}</div>
      </nav>`;
    }
    const kicker = "目录";
    return `
    <section class="career-report-side-card career-report-side-card--toc">
      <nav class="cr-md-toc cr-md-toc--${variant}" aria-label="报告目录">
        <p class="cr-md-toc-heading-label">${kicker}</p>
        <div class="cr-md-toc-body">${rows}</div>
      </nav>
    </section>`;
  }

  function initCrMdTocToggles(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll(".cr-md-toc-toggle").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const branch = btn.closest(".cr-md-toc-branch");
        if (!branch) return;
        const subs = branch.querySelector(".cr-md-toc-subs");
        if (!subs) return;
        const open = branch.classList.toggle("is-open");
        btn.classList.toggle("is-open", open);
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        subs.hidden = !open;
      });
    });
  }

  /** ai润色.html 风格章节树：collapse-icon + .tree-children.collapsed */
  function initCareerReportEditorTreeToggles(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("button.collapse-icon").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const branch = btn.closest(".tree-toc-branch");
        if (!branch) return;
        const subs = branch.querySelector(".tree-children");
        if (!subs) return;
        subs.classList.toggle("collapsed");
        const collapsed = subs.classList.contains("collapsed");
        btn.classList.toggle("open", !collapsed);
        btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      });
    });
  }

  function bindMarkdownTocScrollNav(root, scrollRoot) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const main = scrollRoot || document.getElementById("careerReportMain");
    root.querySelectorAll("[data-report-scroll-target]").forEach((button) => {
      button.addEventListener("click", (e) => {
        e.preventDefault();
        const targetId = String(button.dataset.reportScrollTarget || "").trim();
        if (!targetId) return;
        const target =
          main?.querySelector?.(`#${escapeSelectorId(targetId)}`) || document.getElementById(targetId);
        target?.scrollIntoView({ behavior: "auto", block: "start" });
      });
    });
  }

  function scrollMarkdownTextareaToLine(textarea, markdown, lineNo) {
    if (!textarea) return;
    const lines = String(markdown || "").split("\n");
    const n = Math.max(1, Math.min(Number(lineNo) || 1, Math.max(1, lines.length)));
    const offset = resolveEditorLineOffset(lines, n);
    textarea.focus();
    textarea.setSelectionRange(offset, offset);
    window.requestAnimationFrame(() => {
      try {
        const cs = window.getComputedStyle(textarea);
        const lh = parseFloat(cs.lineHeight);
        const fs = parseFloat(cs.fontSize) || 13;
        const lineHeight = Number.isFinite(lh) && lh > 0 ? lh : fs * 1.65;
        const lineIdx = String(markdown || "").slice(0, offset).split("\n").length;
        const targetTop = Math.max(0, (lineIdx - 1) * lineHeight - textarea.clientHeight * 0.25);
        textarea.scrollTop = targetTop;
      } catch (_) {
        /* ignore */
      }
    });
  }

  function scrollCareerReportEditorToLine(lineNo) {
    const n = Math.max(1, Number(lineNo) || 1);
    const textarea = document.getElementById("reportEditorTextarea");
    const host = document.getElementById("reportEditorRenderedDoc");
    const markdown = String(textarea?.value || "");
    const branches = buildMarkdownTocBranches(markdown);
    let targetId = "";
    branches.forEach((branch) => {
      if (Number(branch.line) === n && branch.id) targetId = branch.id;
      (Array.isArray(branch.subs) ? branch.subs : []).forEach((sub) => {
        if (Number(sub.line) === n && sub.id) targetId = sub.id;
      });
    });
    const docMode = normalizeCareerReportEditorDocMode(reportRuntime.editorDocMode);
    if (docMode === "edit") {
      scrollMarkdownTextareaToLine(textarea, markdown, n);
      return;
    }
    if (docMode === "diff") {
      setCareerReportEditorDocMode("preview");
    }
    setCareerReportEditorViewMode("rendered");
    window.requestAnimationFrame(() => {
      if (targetId) {
        host?.querySelector?.(`#${escapeSelectorId(targetId)}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        host?.scrollTo?.({ top: 0, behavior: "smooth" });
      }
    });
  }

  function bindMarkdownTocEditorNav(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-editor-goto-line]").forEach((el) => {
      const go = (e) => {
        if (e && e.target && e.target.closest && e.target.closest("button.collapse-icon")) return;
        if (e && e.preventDefault) e.preventDefault();
        const line = Number(el.dataset.editorGotoLine || el.getAttribute("data-editor-goto-line") || 0);
        if (!line) return;
        scrollCareerReportEditorToLine(line);
      };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        go(e);
      });
    });
  }

  function formatReportReadingMarkdown(markdown) {
    // Reading-only whitespace: keep the saved report, citations and editor source intact.
    const splitParagraph = (block) => {
      if (block.length < 260 || /^(?: {4}|\t)/.test(block) || /(?:^|\n)\s*(?:#{1,6}\s|>|[-*+]\s|\d+[.)]\s|\|)/.test(block) || /^\s*https?:\/\/\S+\s*$/.test(block)) return block;
      const indent = block.match(/^[ \t]*/)[0];
      const text = block.slice(indent.length);
      const ranges = [...text.matchAll(/`[^`\n]*`|!?\[[^\]\n]*\]\([^\n)]*\)|https?:\/\/[^\s<>]+/g)].map(match => [match.index, match.index + match[0].length]);
      const pairs = { "「": "」", "『": "』", "“": "”", "‘": "’", "《": "》", "（": "）", "(": ")", "【": "】", "[": "]" };
      const stack = [], parts = [];
      let start = 0, range = 0;
      for (let index = 0; index < text.length; index++) {
        if (ranges[range]?.[0] === index) { index = ranges[range++][1] - 1; continue; }
        const char = text[index];
        if (char === "\\") { index++; continue; }
        if (pairs[char]) stack.push(pairs[char]);
        else if (stack[stack.length - 1] === char) stack.pop();
        const boundary = /[。！？；]/.test(char) || /[。！？；][”’」』》）】)]*$/.test(text.slice(Math.max(start, index - 12), index + 1));
        if (!stack.length && boundary && index - start >= 150 && text.length - index > 60) {
          parts.push(indent + text.slice(start, index + 1).trim());
          start = index + 1;
        }
      }
      parts.push(indent + text.slice(start).trim());
      return parts.join("\n\n");
    };
    return String(markdown).replace(/\r\n/g, "\n").split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g)
      .map(part => /^(?:```|~~~)/.test(part) ? part : part.split(/\n[ \t]*\n/).map(splitParagraph).join("\n\n")).join("");
  }

  function renderMarkdownBasic(md, options) {
    if (!md) return "";
    const opts = options && typeof options === "object" ? options : {};
    const wrapProse = opts.wrapProse !== false;
    const injectAnchors = opts.injectHeadingAnchors === true;
    const numbered = opts.enhancedLayout && window.CareerReportReader ? window.CareerReportReader.prepare(md) : md;
    let text = opts.readableParagraphs === false ? String(numbered) : formatReportReadingMarkdown(numbered);
    const anchorQueues = injectAnchors ? buildHeadingAnchorQueues(text) : null;
    // Escape HTML（保留 `>`，否则 Markdown 引用行 `> ...` 无法识别）
    text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    // Code blocks (```...```)
    text = text.replace(/```(?:json|python|markdown|md)?\s*([\s\S]*?)```/g, (_, code) =>
      `<pre class="career-report-md-pre"><code>${code.trim()}</code></pre>`);
    // Inline code
    text = text.replace(/`([^`]+)`/g, '<code class="career-report-md-code">$1</code>');
    // Headings（从长到短，避免 # 被提前吃掉）
    if (anchorQueues) {
      let i2 = 0;
      let i3 = 0;
      let i4 = 0;
      text = text.replace(/^#### (.+)$/gm, (m, t) => {
        const id = anchorQueues.h4[i4++] || "";
        return `<h4 class="career-report-md-h4"${id ? ` id="${id}"` : ""}>${t}</h4>`;
      });
      text = text.replace(/^### (.+)$/gm, (m, t) => {
        const id = anchorQueues.h3[i3++] || "";
        return id ? `<h3 class="career-report-md-h3" id="${id}">${t}</h3>` : `<h3 class="career-report-md-h3">${t}</h3>`;
      });
      text = text.replace(/^## (.+)$/gm, (m, t) => {
        const id = anchorQueues.h2[i2++] || "";
        return id ? `<h2 class="career-report-md-h2" id="${id}">${t}</h2>` : `<h2 class="career-report-md-h2">${t}</h2>`;
      });
      text = text.replace(/^# (.+)$/gm, '<h1 class="career-report-md-h1">$1</h1>');
    } else {
      text = text.replace(/^#### (.+)$/gm, '<h4 class="career-report-md-h4">$1</h4>');
      text = text.replace(/^### (.+)$/gm, '<h3 class="career-report-md-h3">$1</h3>');
      text = text.replace(/^## (.+)$/gm, '<h2 class="career-report-md-h2">$1</h2>');
      text = text.replace(/^# (.+)$/gm, '<h1 class="career-report-md-h1">$1</h1>');
    }
    // Bold
    text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/^((?:改进方式|基于已有事实的改写|还需补充|原文依据|待确认|与求职需求的关系)[：:])/gm, '<strong class="career-report-inline-label">$1</strong>');
    // Images ![alt](url) 与 ![alt](url "title") — 块级展示，避免整行仍以纯文本出现
    text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, dest) => {
      let href = String(dest || "").trim();
      let title = "";
      const titled = href.match(/^(.+?)\s+"([^"]*)"$/);
      if (titled) {
        href = titled[1].trim();
        title = titled[2] || "";
      }
      const safeSrc = esc(href);
      const safeAlt = esc(alt);
      const titleAttr = title ? ` title="${esc(title)}"` : "";
      return `<div class="career-report-md-figure"><img class="career-report-md-img" src="${safeSrc}" alt="${safeAlt}"${titleAttr} loading="lazy" decoding="async" /></div>`;
    });
    // Recruiting links remain actionable in the report reader.
    const linkify = (part) => part.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, (original, label, destination) => {
      try {
        const url = new URL(destination.replace(/&amp;/g, "&"));
        if (!["https:", "http:"].includes(url.protocol) || !url.hostname || url.username || url.password) return label;
        return `<a class="career-report-source-link" data-preview-report-id="${esc(opts.previewReportId || "")}" data-preview-snapshot-id="${esc(opts.previewSnapshotId || "")}" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      } catch (_) { return label; }
    });
    text = text.split(/(<pre\b[^>]*>[\s\S]*?<\/pre>|<code\b[^>]*>[\s\S]*?<\/code>|<[^>]+>)/g)
      .map((part) => part.startsWith("<") ? part : linkify(part)).join("");
    // Blockquotes（连续以 > 开头的行）
    text = text.replace(/(?:^>[^\n]*(?:\n|$))+?/gm, (block) => {
      const inner = block
        .trim()
        .split("\n")
        .map((line) => line.replace(/^>\s?/, "").trim())
        .join("<br>");
      return `<blockquote class="career-report-md-bq">${inner}</blockquote>`;
    });
    // Tables: find lines with | separators
    text = text.replace(/((?:\|.+\|\n?)+)/g, (tableBlock) => {
      const lines = tableBlock.trim().split("\n").filter((l) => l.trim());
      if (lines.length < 2) return tableBlock;
      const rows = lines.map((line) => {
        const cells = line.split("|").slice(1, -1).map((c) => c.trim());
        return cells;
      });
      const isSep = (row) => row.every((c) => /^[-:]+$/.test(c));
      let body = "";
      let headerDone = false;
      for (let i = 0; i < rows.length; i++) {
        if (i === 1 && isSep(rows[i])) continue;
        const tag = !headerDone && i === 0 ? "th" : "td";
        if (tag === "th") headerDone = true;
        body += "<tr>" + rows[i].map((c) => `<${tag}>${c}</${tag}>`).join("") + "</tr>";
      }
      return `<div class="career-report-md-table-wrap"><table class="career-report-md-table">${body}</table></div>`;
    });
    // Numbered lists（允许 1. xxx 或 1.  多空格）
    text = text.replace(/((?:^\d+\.\s+.+\n?)+)/gm, (block) => {
      const start = Number(block.trim().match(/^\d+/)?.[0] || 1);
      const items = block.trim().split("\n").map((l) => `<li>${l.replace(/^\d+\.\s+/, "")}</li>`).join("");
      return `<ol class="career-report-md-ol" start="${start}">${items}</ol>`;
    });
    // Unordered lists（* 或 -，允许缩进与 * 后多空格，与常见 md 导出一致）
    text = text.replace(/((?:^\s*[*+-]\s+.+\n?)+)/gm, (block) => {
      const items = block
        .trim()
        .split("\n")
        .map((l) => `<li>${l.replace(/^\s*[*+-]\s+/, "")}</li>`)
        .join("");
      return `<ul class="career-report-md-ul">${items}</ul>`;
    });
    // Horizontal rules
    text = text.replace(/^---+$/gm, '<hr class="career-report-md-hr">');
    // Paragraphs (double newlines)
    text = text.replace(/\n\n+/g, '</p><p class="career-report-md-p">');
    text = `<p class="career-report-md-p">${text}</p>`;
    // Single newlines
    text = text.replace(/\n/g, "<br>");
    // Clean up empty paragraphs
    text = text.replace(/<p class="career-report-md-p">\s*<\/p>/g, "");
    text = text.replace(/<p class="career-report-md-p">(<(?:h[1-4]|ul|ol|div|blockquote|pre|hr)[^>]*>)/g, "$1");
    text = text.replace(/(<\/(?:h[1-4]|ul|ol|div|blockquote|pre|hr)>)<\/p>/g, "$1");
    text = text.replace(/(<\/(?:h[1-4]|ul|ol|div|blockquote|pre)>)(?:<br\s*\/?>|\s)*<\/p>/g, "$1");
    // 兼容：上面替换若未加 class 的残留 p 标签
    text = text.replace(/<p>(<(?:h[1-4]|ul|ol|div|blockquote|pre|hr)[^>]*>)/g, "$1");
    text = text.replace(/(<\/(?:h[1-4]|ul|ol|div|blockquote|pre|hr)>)<\/p>/g, "$1");
    // 独占一行的图片块：去掉外层 p（允许前导 br），避免段落边距挤压观感
    text = text.replace(
      /<p class="career-report-md-p">(?:<br\s*\/?>|\s)*(\s*<div class="career-report-md-figure">[\s\S]*?<\/div>\s*)<\/p>/g,
      "$1"
    );
    text = text.replace(/<p>(?:<br\s*\/?>|\s)*(\s*<div class="career-report-md-figure">[\s\S]*?<\/div>\s*)<\/p>/g, "$1");
    if (opts.enhancedLayout && window.CareerReportReader) {
      text = window.CareerReportReader.enhance(text);
    }
    if (wrapProse) {
      return `<div class="career-report-md-prose">${text}</div>`;
    }
    return text;
  }

  function truncateSummary(text, maxLen = 100) {
    const t = String(text || "").replace(/\s+/g, " ").trim();
    if (!t) return "";
    if (t.length <= maxLen) return t;
    return `${t.slice(0, maxLen)}…`;
  }

  /**
   * 阅读态移除各模块末尾「机器可读*」标题及其子内容（供编排用的 JSON），保留连续可读正文。
   */
  function stripMachineReadableSectionsFromMarkdown(md) {
    const lines = String(md || "").split("\n");
    const out = [];
    let skipDepth = null;
    const headingRe = /^(#{1,6})\s+(.*)$/;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const hm = line.match(headingRe);
      if (hm) {
        const depth = hm[1].length;
        const title = hm[2] || "";
        if (skipDepth !== null) {
          if (depth <= skipDepth) {
            skipDepth = null;
            i -= 1;
            continue;
          }
          continue;
        }
        if (/机器可读/.test(title)) {
          skipDepth = depth;
          continue;
        }
      }
      if (skipDepth !== null) continue;
      out.push(line);
    }
    return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  /** 去掉流水线单行摘要（偶发落在章节外时） */
  function stripPipelineSummaryLines(md) {
    return String(md || "")
      .split("\n")
      .filter((line) => !/^\s*(MATCH_SUMMARY|PATH_SUMMARY)\s*:/i.test(line.trim()))
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function markdownForCareerReportReading(md) {
    const cleaned = stripPipelineSummaryLines(stripMachineReadableSectionsFromMarkdown(md));
    return window.CareerReportReader ? window.CareerReportReader.prepare(cleaned) : cleaned;
  }

  /** 顶层尚无合并正文时，按流水线顺序拼接各模块 Markdown，阅读态与单文件报告一致 */
  function stitchModularMarkdownFromBundle(bundle) {
    const sections = bundle?.report_document?.sections;
    if (!sections || typeof sections !== "object" || Array.isArray(sections)) return "";
    const navOrder = bundle?.report_document?.section_order || [
      "executive_summary",
      "macro_environment",
      "personal_traits",
      "target_job_analysis",
      "matching_decision",
      "gap_action_plan",
      "risk_backup",
      "appendix"
    ];
    const parts = [];
    for (let i = 0; i < navOrder.length; i++) {
      const key = navOrder[i];
      const sec = sections[key];
      if (!sec || typeof sec !== "object") continue;
      const md = String(sec.markdown || "").trim();
      if (!md) continue;
      const label = String(sec.label || SECTION_NAV.find((item) => item.key === key)?.label || key).trim();
      parts.push(/^##\s/m.test(md) ? md : `## ${label}\n\n${md}`);
    }
    return parts.join("\n\n").trim();
  }

  function computeGenerationPercent(progress) {
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    const done = items.filter((x) => x && x.status === "done").length;
    return Math.round((done / Math.max(items.length, 1)) * 100);
  }

  function renderReportGenerationMain(state, progress) {
    const pct = computeGenerationPercent(progress);
    const dash = Math.max(0, Math.min(264, (pct / 100) * 264));
    const detail = esc(String(state?.stage_detail || state?.stage_label || "后台正在按阶段生成结构化职业规划报告，请稍候。").trim());
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    return `
      <div class="career-report-gen">
        <div class="career-report-gen-inner">
          <p class="career-report-gen-kicker">Career Report Pipeline</p>
          <h2 class="career-report-gen-title">正在生成你的职业发展报告</h2>
          <div class="career-report-gen-ring-wrap" aria-hidden="true">
            <svg class="career-report-gen-ring" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(148,163,184,0.28)" stroke-width="8" />
              <circle cx="50" cy="50" r="42" fill="none" stroke="url(#crGenGradPipe)" stroke-width="8"
                stroke-dasharray="${dash} 264" stroke-linecap="round" transform="rotate(-90 50 50)" />
              <defs>
                <linearGradient id="crGenGradPipe" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#2563eb" />
                  <stop offset="100%" stop-color="#38bdf8" />
                </linearGradient>
              </defs>
            </svg>
            <div class="career-report-gen-ring-label">
              <strong>${pct}%</strong>
              <span>阶段完成度</span>
            </div>
          </div>
          <p class="career-report-gen-status">${detail}</p>
          <div class="career-report-gen-stages">
            ${items.map((item) => {
              const done = item.status === "done";
              const active = item.status === "active" || item.status === "running";
              return `
                <div class="career-report-gen-stage${done ? " done" : ""}${active ? " active" : ""}">
                  <span class="career-report-gen-dot"></span>
                  <span class="career-report-gen-stage-label">${esc(item.label || item.key || "阶段")}</span>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      </div>
    `;
  }

  function renderScoreRing(pct) {
    const v = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    const dash = (v / 100) * 264;
    return `
      <div class="cr-v2-score">
        <svg class="cr-v2-score-ring" viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.22)" stroke-width="7" />
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(255,255,255,0.95)" stroke-width="7"
            stroke-dasharray="${dash} 264" stroke-linecap="round" transform="rotate(-90 50 50)" />
        </svg>
        <div class="cr-v2-score-val">${v}%</div>
        <div class="cr-v2-score-cap">综合置信</div>
      </div>
    `;
  }

  function renderReportMagazineLayout(bundle, tracker) {
    const meta = bundle?.meta || {};
    const snap = bundle?.profile_snapshot || {};
    const interest = snap?.interest_profile || {};
    const basics = snap?.basics || {};
    const roles = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const gapMap = bundle?.gap_map || {};
    const gaps = Array.isArray(gapMap.capability_gaps) ? gapMap.capability_gaps.slice(0, 6) : [];
    const phasePlan = bundle?.phase_plan || {};
    const shortPhases = Array.isArray(phasePlan.short_term) ? phasePlan.short_term.slice(0, 2) : [];
    const longPhases = Array.isArray(phasePlan.long_term) ? phasePlan.long_term.slice(0, 1) : [];
    const trend = bundle?.trend_brief || {};
    const workValues = Array.isArray(snap?.work_values) ? snap.work_values : [];
    const exec = String(bundle?.report_document?.executive_summary || meta.summary || snap?.summary || "").trim();
    const focusRole = bundle?.report_document?.focus_role_name || gapMap?.focus_role_name || tracker?.focus_role_name || "待识别";
    const userLabel = esc(currentUser()?.display_name || currentUser()?.username || "用户");
    const conf = Math.max(
      0,
      Math.min(
        100,
        Number(meta.evidence_score ?? tracker?.completion_rate ?? snap?.readiness_score ?? 67) || 0
      )
    );
    const mbtiPill = esc(String(interest.mbti || "MBTI 待补充"));
    const holPill = esc(String(interest.holland || "Holland 待补充"));

    const roleRows = roles.length
      ? roles.map((r) => {
          const score = Math.max(0, Math.min(100, Number(r.overallScore ?? r.overall_score ?? 0)));
          return `
            <div class="cr-v2-role-row">
              <span>${esc(r.name || r.title || "岗位")}</span>
              <span>${score}%</span>
            </div>
          `;
        }).join("")
      : `<div class="cr-v2-role-row"><span>${esc(focusRole)}</span><span>--</span></div>`;

    const gapRows = gaps.length
      ? gaps.map((g) => {
          const cur = g.current != null ? Number(g.current) : 0;
          const req = g.required != null ? Number(g.required) : 85;
          const ratio = req > 0 ? Math.round(Math.min(100, (cur / req) * 100)) : 0;
          return `
            <div class="cr-v2-gap-row">
              <div class="cr-v2-gap-head">
                <span>${esc(g.label || "能力项")}</span>
                <span>${esc(String(cur))}/${esc(String(req))}</span>
              </div>
              <div class="cr-v2-bar"><i style="width:${ratio}%"></i></div>
            </div>
          `;
        }).join("")
      : `<p class="cr-v2-lead" style="margin:0;color:#94a3b8;font-size:0.8rem;">差距分析将在生成完成后显示。</p>`;

    const phaseBlocks = [...shortPhases, ...longPhases]
      .map((ph) => {
        const tasks = Array.isArray(ph.tasks) ? ph.tasks.map((t) => esc(t.text || t.title || "")).filter(Boolean) : [];
        return `
          <div class="cr-v2-phase">
            <h5>${esc(ph.phase || ph.title || "阶段")}</h5>
            <p>${esc(ph.objective || ph.title || "")}</p>
            ${tasks.length ? `<ul>${tasks.slice(0, 4).map((t) => `<li>${t}</li>`).join("")}</ul>` : ""}
          </div>
        `;
      })
      .join("");

    const valueTags = workValues.length
      ? workValues.slice(0, 8).map((w) => `<span class="cr-v2-pill">${esc(w)}</span>`).join("")
      : `<span class="cr-v2-pill neutral">继续补充访谈与简历以丰富价值观标签</span>`;

    const basicsLine = [basics.major, basics.grade, basics.target_city, basics.target_direction]
      .filter(Boolean)
      .map((x) => esc(x))
      .join(" · ");

    const trendSignals = Array.isArray(trend.signals) && trend.signals.length
      ? trend.signals.slice(0, 2).map((s) => `<span class="cr-v2-pill neutral">${esc(s.title || s.summary || s.text || "趋势")}</span>`).join("")
      : `<span class="cr-v2-pill neutral">趋势快照待刷新</span>`;

    // v2: additional data
    const matchOutput = bundle?.match_output || {};
    const fitScore = Number(matchOutput.fit_score || 0);
    const fitBand = String(matchOutput.fit_band || "");
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || "";
    const positioning = bundle?.positioning_output || {};
    const recommendedTracks = Array.isArray(positioning.recommended_tracks) ? positioning.recommended_tracks : [];

    return `
      <div class="cr-v2-wrap">
        <header class="cr-v2-hero">
          <div>
            <p class="cr-v2-hero-kicker">Career Report · 发展规划摘要</p>
            <h2 class="cr-v2-hero-title">${esc(meta.title || "职业生涯发展报告")}</h2>
            <p class="cr-v2-hero-copy">${formatText(exec || "报告已整合测评、画像、岗位匹配与阶段规划，以下为结构化摘要。")}</p>
            <div class="cr-v2-hero-meta">
              <span>主线岗位：${esc(focusRole)}</span>
              <span>生成时间：${esc(meta.generated_at || "--")}</span>
              <span>版本：${esc(meta.version || "--")}</span>
              <span>姓名：${userLabel}</span>
            </div>
          </div>
          ${renderScoreRing(conf)}
        </header>
        <div class="cr-v2-grid">
          <div class="cr-v2-stack" style="display:grid;gap:1rem;">
            <article class="cr-v2-card">
              <h4>测评与画像结论</h4>
              <p class="cr-v2-lead">${formatText(snap.core_thesis || snap.summary || "画像摘要已同步至报告。")}</p>
              <div class="cr-v2-pill-row">
                <span class="cr-v2-pill">MBTI：${mbtiPill}</span>
                <span class="cr-v2-pill">Holland：${holPill}</span>
              </div>
            </article>
            <article class="cr-v2-card">
              <h4>优先岗位方向</h4>
              <div class="cr-v2-role-list">${roleRows}</div>
            </article>
            <article class="cr-v2-card">
              <h4>差距驱动 · 能力对照</h4>
              ${gapRows}
              ${Array.isArray(gapMap.skill_gaps) && gapMap.skill_gaps.length ? `
                <p class="cr-v2-lead" style="margin-top:0.5rem;font-size:0.78rem;color:#64748b;">
                  ${esc(gapMap.skill_gaps.slice(0, 2).join("；"))}
                </p>
              ` : ""}
            </article>
          </div>
          <div class="cr-v2-stack" style="display:grid;gap:1rem;">
            <article class="cr-v2-card">
              <h4>阶段性职业规划</h4>
              ${phaseBlocks || '<p class="cr-v2-lead" style="margin:0;color:#94a3b8;">阶段任务将在生成完成后展示。</p>'}
            </article>
            <article class="cr-v2-card">
              <h4>工作价值观与基础信息</h4>
              <div class="cr-v2-pill-row" style="margin-bottom:0.65rem;">${valueTags}</div>
              <p class="cr-v2-lead" style="margin:0;font-size:0.78rem;">${basicsLine || "专业 / 学历 / 目标城市等可在画像中继续补充。"}</p>
            </article>
            <article class="cr-v2-card">
              <h4>行业信号与待接入能力</h4>
              <div class="cr-v2-pill-row" style="margin-bottom:0.65rem;">${trendSignals}</div>
              <div class="cr-v2-placeholder-grid">
                <div class="cr-v2-placeholder">资源推荐<br/>待接入</div>
                <div class="cr-v2-placeholder">趋势解读<br/>待接入</div>
                <div class="cr-v2-placeholder">提醒追踪<br/>待接入</div>
              </div>
            </article>
            ${renderReportFeedbackCard()}
          </div>
        </div>
      </div>
    `;
  }

  function escapeSelectorId(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
      return CSS.escape(value);
    }
    return String(value || "").replace(/[^a-zA-Z0-9_-]+/g, "\\$&");
  }

  function toast(title, text = "", tone = "info", duration = 2200) {
    if (typeof window.showToast === "function") {
      window.showToast(title, text, tone, duration);
    }
  }

  function currentUser() {
    if (typeof window.getCurrentUser === "function") return window.getCurrentUser();
    return null;
  }

  function isAuthenticated() {
    if (typeof window.isAuthenticatedUser === "function") return window.isAuthenticatedUser();
    return Boolean(currentUser());
  }

  function resolveUrl(path) {
    if (typeof window.resolveApiUrl === "function") {
      return window.resolveApiUrl(path);
    }
    return String(path || "");
  }

  async function requestJsonSafe(path, options = {}) {
    if (typeof window.requestJson === "function") {
      return window.requestJson(path, options);
    }

    const method = String(options.method || "GET").toUpperCase();
    const headers = { ...(options.headers || {}) };
    const init = {
      method,
      headers,
      credentials: options.credentials || "include"
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = headers["Content-Type"] || "application/json";
      init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
    }

    const response = await fetch(resolveUrl(path), init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.message || `请求失败：${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function scheduleRender(withUserCenterRefresh = false) {
    if (reportRuntime.renderQueued) return;
    reportRuntime.renderQueued = true;
    const run = () => {
      reportRuntime.renderQueued = false;
      renderCareerReportPanels();
      if (typeof window.renderReportWorkspace === "function") {
        window.renderReportWorkspace(window.appState?.derivedProfile, window.appState?.matchingRoles || []);
      }
      if (withUserCenterRefresh && typeof window.renderUserCenterDashboard === "function") {
        window.renderUserCenterDashboard();
      }
    };
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(run);
    } else {
      setTimeout(run, 0);
    }
  }

  function setScopedCareerReportState(state) {
    if (!window.userWorkspaceState || typeof window.userWorkspaceState !== "object") return;
    if (!window.userWorkspaceState.scopedData || typeof window.userWorkspaceState.scopedData !== "object") return;
    window.userWorkspaceState.scopedData.career_report = state || null;
    if (window.userWorkspaceState.scopedDataLoaded && typeof window.userWorkspaceState.scopedDataLoaded === "object") {
      window.userWorkspaceState.scopedDataLoaded.career_report = Boolean(state);
    }
  }

  function getCareerReportStateSafe() {
    ensureAppState();
    return window.appState.careerReportState || window.userWorkspaceState?.scopedData?.career_report || null;
  }

  function getCareerReportTracker() {
    ensureAppState();
    const scopedTracker = getCareerReportStateSafe()?.tracker;
    return window.appState.careerReportTracker || scopedTracker || null;
  }

  function getCareerReportFeedback() {
    const feedback = getCareerReportStateSafe()?.feedback;
    return feedback && typeof feedback === "object" ? feedback : null;
  }

  function getFeedbackVerdictLabel(verdict) {
    const key = String(verdict || "").trim().toLowerCase();
    if (key === "accurate") return "基本准确";
    if (key === "off_target") return "明显偏差";
    return "部分准确";
  }

  function normalizeVersions(tracker, bundle) {
    const trackerVersions = Array.isArray(tracker?.versions) ? tracker.versions : [];
    const versions = trackerVersions.slice();
    const reportId = String(bundle?.meta?.report_id || "").trim();
    if (reportId && !versions.some((item) => String(item?.report_id || "").trim() === reportId)) {
      versions.unshift({
        report_id: reportId,
        title: bundle?.meta?.title || "职业规划报告",
        generated_at: bundle?.meta?.generated_at || "",
        focus_role_id: bundle?.meta?.focus_role_id || "",
        focus_role_name: bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || "",
        version: bundle?.meta?.version || ""
      });
    }
    return versions;
  }

  function applyCareerReportState(bundle, tracker, state, options = {}) {
    ensureAppState();

    if (state && typeof state === "object") {
      window.appState.careerReportState = state;
      setScopedCareerReportState(state);
    } else if (state === null && !options.keepState) {
      window.appState.careerReportState = null;
      setScopedCareerReportState(null);
    }

    if (tracker && typeof tracker === "object") {
      window.appState.careerReportTracker = tracker;
    } else if (tracker === null && !options.keepTracker) {
      window.appState.careerReportTracker = null;
    }

    if (bundle && typeof bundle === "object" && bundle.meta) {
      window.appState.careerReport = bundle;
      window.appState.reportReady = Boolean(bundle.report_document);
      window.appState.reportGenerated = Boolean(bundle.report_document);
      if (!options.historical && bundle.meta.focus_role_id) {
        window.appState.focusedRoleId = String(bundle.meta.focus_role_id || "").trim();
      }
    } else if (bundle === null && !options.keepBundle) {
      window.appState.careerReport = null;
      window.appState.reportReady = false;
      window.appState.reportGenerated = false;
    }

    const resolvedTracker = window.appState.careerReportTracker || tracker || state?.tracker || null;
    window.appState.careerReportVersions = normalizeVersions(resolvedTracker, window.appState.careerReport);

    const canonicalId = String(
      options.canonicalReportId
      || window.appState.careerReportCanonicalId
      || state?.report_id
      || resolvedTracker?.report_id
      || window.appState.careerReport?.meta?.report_id
      || ""
    ).trim();
    window.appState.careerReportCanonicalId = canonicalId;
    window.appState.careerReportViewingHistorical = Boolean(options.historical);
    scheduleRender(Boolean(options.userCenterRefresh));
  }

  function primeCareerReportStateFromBootstrap() {
    const scoped = window.userWorkspaceState?.scopedData?.career_report;
    if (!scoped || typeof scoped !== "object") return;
    applyCareerReportState(undefined, scoped.tracker || null, scoped, {
      keepBundle: true,
      userCenterRefresh: false
    });
  }

  function stopCareerReportPolling() {
    if (reportRuntime.pollTimer) {
      clearTimeout(reportRuntime.pollTimer);
      reportRuntime.pollTimer = 0;
    }
  }

  async function loadCurrentCareerReport(options = {}) {
    const payload = await requestJsonSafe("/api/career-report/current");
    applyCareerReportState(payload.data || null, payload.state?.tracker || null, payload.state || null, {
      historical: false,
      canonicalReportId: payload.data?.meta?.report_id || payload.state?.report_id || "",
      userCenterRefresh: options.userCenterRefresh !== false
    });
    return payload;
  }

  function mergeCareerReportStatusForApply(payload) {
    const st = payload?.state && typeof payload.state === "object" ? payload.state : {};
    const jb = payload?.job && typeof payload.job === "object" ? payload.job : {};
    const js = String(jb.status || "").trim().toLowerCase();
    const normalizedJob = js === "completed" ? "ready" : js;
    const merged = {
      ...st,
      status:
        normalizedJob && normalizedJob !== "idle"
          ? normalizedJob
          : String(st.status || "").trim().toLowerCase(),
      job_id: jb.job_id || st.job_id || "",
      report_id: jb.report_id || st.report_id || "",
      stage: jb.stage || st.stage || "",
      stage_label: jb.stage_label || st.stage_label || "",
      stage_detail: jb.stage_detail || jb.message || st.stage_detail || "",
      progress: Array.isArray(jb.progress) && jb.progress.length ? jb.progress : st.progress || [],
      model: jb.model || st.model || "",
      generation_mode: jb.generation_mode || st.generation_mode || "",
      error_message: st.error_message || (normalizedJob === "failed" ? jb.message || "" : "")
    };
    return merged;
  }

  async function syncCareerReportStatus(jobId = "") {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
    const payload = await requestJsonSafe(`/api/career-report/generate/status${suffix}`);
    const merged = mergeCareerReportStatusForApply(payload);
    applyCareerReportState(undefined, merged.tracker || payload.state?.tracker || null, merged, {
      keepBundle: true,
      historical: window.appState?.careerReportViewingHistorical,
      userCenterRefresh: true
    });
    return payload;
  }

  async function pollCareerReportJob(jobId) {
    return window.pollCareerReportJob?.(jobId);
  }

  function getCareerReportVersionList() {
    ensureAppState();
    return {
      versions: Array.isArray(window.appState.careerReportVersions) ? window.appState.careerReportVersions : [],
      reportState: getCareerReportStateSafe(),
      canonicalReportId: String(window.appState.careerReportCanonicalId || "").trim()
    };
  }

  function getDefaultStageProgress() {
    return DEFAULT_STAGE_PROGRESS.map((item) => ({ ...item }));
  }

  function renderReportProgressCards(progress) {
    const items = Array.isArray(progress) && progress.length ? progress : getDefaultStageProgress();
    return `
      <div class="career-report-stage-board">
        ${items.map((item) => {
          const isActive = item.status === "active" || item.status === "running";
          const statusText = item.status === "done"
            ? "已完成"
            : isActive
              ? "进行中"
              : item.status === "failed"
                ? "失败"
                : "待处理";
          return `
            <article class="career-report-stage-card${isActive ? " active" : ""}">
              <span>${esc(statusText)}</span>
              <strong>${esc(item.label || item.key || "阶段")}</strong>
            </article>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderMetricRow(metrics) {
    if (!Array.isArray(metrics) || !metrics.length) return "";
    return `
      <div class="career-report-metric-row">
        ${metrics.map((item) => `
          <div class="career-report-mini-metric">
            <span>${esc(item.label || "指标")}</span>
            <strong>${esc(item.value || "--")}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderVisualization(visualization) {
    if (!visualization || typeof visualization !== "object") return "";
    const type = String(visualization.type || "").trim();
    const items = Array.isArray(visualization.items) ? visualization.items : [];
    if (!items.length) return "";

    if (type === "score-bars") {
      return `
        <div class="career-report-viz">
          ${items.map((item) => {
            const value = Math.max(0, Math.min(100, Number(item.value || 0)));
            return `
              <div class="career-report-score-row">
                <div class="career-report-score-meta">
                  <strong>${esc(item.label || "候选方向")}</strong>
                  <span>${esc(item.hint || "")}</span>
                </div>
                <div class="career-report-score-track">
                  <div class="career-report-score-fill" style="width:${value}%"></div>
                </div>
                <em>${value}%</em>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    if (type === "gap-matrix") {
      return `
        <div class="career-report-viz career-report-gap-grid">
          ${items.map((item) => `
            <article class="career-report-gap-card">
              <span>${esc(item.status || "差距项")}</span>
              <strong>${esc(item.label || "能力维度")}</strong>
              <em>${esc(`${Number(item.current || 0)}/${Number(item.required || 0)}`)}</em>
            </article>
          `).join("")}
        </div>
      `;
    }

    if (type === "timeline") {
      return `
        <div class="career-report-viz career-report-timeline">
          ${items.map((item) => `
            <article class="career-report-timeline-item">
              <span>${esc(item.label || item.phase || "阶段")}</span>
              <strong>${esc(item.title || "行动阶段")}</strong>
              <p>${formatText(item.summary || "")}</p>
            </article>
          `).join("")}
        </div>
      `;
    }

    if (type === "signal-cards") {
      return `
        <div class="career-report-viz career-report-signal-grid">
          ${items.map((item) => `
            <article class="career-report-signal-card">
              <span>${esc(item.source || item.label || "趋势信号")}</span>
              <strong>${esc(item.title || item.label || "观察点")}</strong>
              <p>${formatText(item.summary || item.body || item.hint || "")}</p>
            </article>
          `).join("")}
        </div>
      `;
    }

    return `
      <div class="career-report-viz career-report-signal-grid">
        ${items.map((item) => `
          <article class="career-report-signal-card">
            <span>${esc(item.label || item.phase || "信息")}</span>
            <strong>${esc(item.title || "内容")}</strong>
            <p>${formatText(item.summary || item.body || "")}</p>
          </article>
        `).join("")}
      </div>
    `;
  }

  function renderCardGrid(cards) {
    if (!Array.isArray(cards) || !cards.length) return "";
    return `
      <div class="career-report-card-grid">
        ${cards.map((card) => `
          <article class="career-report-content-card tone-${esc(card.tone || "indigo")}">
            <div class="career-report-content-top">
              <h4>${esc(card.title || "内容卡片")}</h4>
              <span>${esc(card.confidence || card.score || "信息")}</span>
            </div>
            <p>${formatText(card.body || "")}</p>
            ${(Array.isArray(card.tags) && card.tags.length) ? `
              <div class="career-report-content-meta">
                <div class="career-report-chip-row">
                  ${card.tags.slice(0, 8).map((item) => `<span class="career-report-chip">${esc(item)}</span>`).join("")}
                </div>
                ${(Array.isArray(card.evidence_sources) && card.evidence_sources.length) ? `
                  <div class="career-report-chip-row">
                    ${card.evidence_sources.slice(0, 4).map((item) => `<span class="career-report-chip">${esc(item)}</span>`).join("")}
                  </div>
                ` : ""}
              </div>
            ` : ""}
          </article>
        `).join("")}
      </div>
    `;
  }

  function getReportSectionDomId(section, index) {
    const raw = String(section?.id || `section-${index + 1}`).trim() || `section-${index + 1}`;
    return `career-report-section-${raw.replace(/[^a-zA-Z0-9_-]+/g, "-")}`;
  }

  function renderReportSections(bundle, options = {}) {
    const rawSections = bundle?.report_document?.sections;

    // v2: sections is an object keyed by module name
    if (rawSections && !Array.isArray(rawSections) && typeof rawSections === "object") {
      return renderReportSections4(bundle, rawSections, options);
    }

    // Legacy: sections is an array
    const sections = Array.isArray(rawSections) ? rawSections : [];
    if (!sections.length) {
      return `
        <div class="career-report-empty-grid">
          <article class="career-report-empty-card">
            <strong>报告结构尚未就绪</strong>
            <p>当前版本缺少可展示的报告章节，请重新生成职业报告。</p>
          </article>
        </div>
      `;
    }

    return `
      <div class="career-report-sections">
        ${sections.map((section, index) => `
          <section id="${getReportSectionDomId(section, index)}" class="career-report-section-card">
            <div class="career-report-section-head">
              <div>
                <p class="career-report-section-kicker">${esc(section.kicker || `Section ${index + 1}`)}</p>
                <h3 class="career-report-section-title">${esc(section.title || "章节")}</h3>
                ${section.summary ? `<p class="career-report-section-deck">${esc(truncateSummary(section.summary, 140))}</p>` : ""}
              </div>
            </div>
            ${renderMetricRow(section.metrics)}
            ${renderVisualization(section.visualization)}
            ${renderCardGrid(section.cards)}
            ${section.summary ? `<div class="career-report-section-body">${formatText(section.summary)}</div>` : ""}
          </section>
        `).join("")}
      </div>
    `;
  }

  function renderReportSections4(bundle, sections, options = {}) {
    const narrativeLayout = ["narrative-v1", "narrative-v2", "numbered-reader-v3"].includes(bundle?.report_document?.reading_layout);
    const requestedGroup = String(options.group || "").trim().toLowerCase();
    const groupConfig = REPORT_WORKSPACE_GROUPS[requestedGroup] || null;
    const navOrder = bundle?.report_document?.section_order || [
      "executive_summary",
      "macro_environment",
      "personal_traits",
      "target_job_analysis",
      "matching_decision",
      "gap_action_plan",
      "risk_backup",
      "appendix"
    ];
    const navMeta = {
      "executive_summary":    { label: "执行摘要",           icon: "01", anchor: "cr-sec-exec",         kicker: "Executive Summary",            accentClass: "cr-module-purple" },
      "macro_environment":    { label: "宏观就业环境",       icon: "02", anchor: "cr-sec-industry",     kicker: "Industry Analyst",             accentClass: "cr-module-blue" },
      "personal_traits":      { label: "个人特质与潜力",     icon: "03", anchor: "cr-sec-traits",       kicker: "Personal Profile",             accentClass: "cr-module-amber" },
      "target_job_analysis":  { label: "目标企业与岗位分析", icon: "04", anchor: "cr-sec-target",       kicker: "Target Job Analysis",          accentClass: "cr-module-green" },
      "matching_decision":    { label: "人岗匹配与决策建议", icon: "05", anchor: "cr-sec-match",        kicker: "Role Match Officer",           accentClass: "cr-module-indigo" },
      "ability_gaps":         { label: "职业能力差距", icon: "06", anchor: "cr-sec-ability-gaps", kicker: "Capability Gaps", accentClass: "cr-module-indigo" },
      "development_path":     { label: "职业发展与成长路径", icon: "07", anchor: "cr-sec-development", kicker: "Development Roadmap", accentClass: "cr-module-teal" },
      "gap_action_plan":      { label: "差距分析与行动计划", icon: "06", anchor: "cr-sec-gap",          kicker: "Gap & Action Plan",            accentClass: "cr-module-teal" },
      "risk_backup":          { label: "风险管理与备选方案", icon: "07", anchor: "cr-sec-risk",         kicker: "Risk & Backup",                accentClass: "cr-module-rose" },
      "appendix":             { label: "附录",               icon: "08", anchor: "cr-sec-appendix",     kicker: "Appendix",                     accentClass: "cr-module-slate" },
    };

    // ── helpers ──────────────────────────────────────────────────────────────

    function skillBar(label, pct, colorVar) {
      const w = Math.min(100, Math.max(0, Number(pct) || 0));
      return `
        <div class="cr4-skill-item">
          <div class="cr4-skill-header">
            <span class="cr4-skill-name">${esc(label)}</span>
            <span class="cr4-skill-score">${w}</span>
          </div>
          <div class="cr4-skill-bar">
            <div class="cr4-skill-bar-fill" style="width:${w}%;background:${colorVar || "var(--cr4-primary)"};"></div>
          </div>
        </div>`;
    }

    function dimCard(icon, title, desc, pct, colorVar, accentClass) {
      const w = Math.min(100, Math.max(0, Number(pct) || 0));
      return `
        <div class="cr4-dim-card">
          <div class="cr4-dim-header">
            <div class="cr4-dim-icon ${accentClass}">${icon}</div>
            <div class="cr4-dim-score" style="color:${colorVar}">${w}</div>
          </div>
          <div class="cr4-dim-title">${esc(title)}</div>
          <div class="cr4-dim-desc">${esc(desc)}</div>
          <div class="cr4-dim-bar">
            <div class="cr4-dim-bar-fill" style="width:${w}%;background:${colorVar};"></div>
          </div>
        </div>`;
    }

    function statCard(label, value, sub, accentClass) {
      return `
        <div class="cr4-stat-card ${accentClass}">
          <div class="cr4-stat-label">${esc(label)}</div>
          <div class="cr4-stat-value">${esc(String(value))}</div>
          ${sub ? `<div class="cr4-stat-sub">${esc(sub)}</div>` : ""}
        </div>`;
    }

    function gapPill(text, type) {
      const cls = type === "urgent" ? "cr4-gap-urgent" : type === "warn" ? "cr4-gap-warn" : "cr4-gap-info";
      const label = type === "urgent" ? "急需提升" : type === "warn" ? "需要提升" : "建议加强";
      return `
        <div class="cr4-gap-pill ${cls}">
          <div class="cr4-gap-pill-label">${label}</div>
          <div class="cr4-gap-pill-text">${esc(text)}</div>
        </div>`;
    }

    function timelineItem(phase, title, period, desc, tags, state) {
      return `
        <div class="cr4-timeline-item ${state || "future"}">
          <div class="cr4-timeline-dot"></div>
          <div class="cr4-timeline-content">
            <div class="cr4-timeline-phase">${esc(phase)}</div>
            <div class="cr4-timeline-title">${esc(title)}</div>
            ${period ? `<div class="cr4-timeline-period">${esc(period)}</div>` : ""}
            ${desc ? `<div class="cr4-timeline-desc">${esc(desc)}</div>` : ""}
            ${tags && tags.length ? `<div class="cr4-timeline-tags">${tags.map((t) => `<span class="cr4-tag">${esc(String(t))}</span>`).join("")}</div>` : ""}
          </div>
        </div>`;
    }

    // grade → 0-100 score for bar widths
    function gradeToScore(level) {
      return {"S": 96, "A": 85, "B": 70, "C": 55, "D": 35}[String(level).toUpperCase()] || 0;
    }

    function normalizeExplainItem(item) {
      if (item == null) return null;
      if (typeof item === "string" || typeof item === "number") {
        const text = String(item).trim();
        return text ? { title: text, detail: "", meta: "", validate: "" } : null;
      }
      if (typeof item !== "object") return null;
      const title = String(
        item.title
        || item.label
        || item.name
        || item.skill
        || item.competency
        || item.requirement
        || item.track
        || ""
      ).trim();
      const detail = String(
        item.detail
        || item.summary
        || item.reason
        || item.note
        || item.why_important
        || item.priority_reason
        || item.because
        || ""
      ).trim();
      const metaParts = [];
      if (item.source_type) metaParts.push(`来源：${item.source_type}`);
      if (item.time_horizon) metaParts.push(`时效：${item.time_horizon}`);
      if (item.status) metaParts.push(`状态：${item.status}`);
      if (item.evidence) metaParts.push(String(item.evidence).trim());
      if (Array.isArray(item.evidence_ids) && item.evidence_ids.length) {
        metaParts.push(`证据 ID：${item.evidence_ids.join("、")}`);
      }
      const validate = String(item.validate || item.validation_action || "").trim();
      if (!title && !detail && !metaParts.length && !validate) return null;
      return {
        title: title || detail || metaParts[0] || "待补充",
        detail: title ? detail : "",
        meta: metaParts.join(" · "),
        validate,
      };
    }

    function renderExplainList(items, empty = "暂无补充") {
      const normalized = (Array.isArray(items) ? items : [items])
        .map((item) => normalizeExplainItem(item))
        .filter(Boolean);
      if (!normalized.length) {
        return `<p class="cr4-explain-empty">${esc(empty)}</p>`;
      }
      return `
        <ul class="cr4-explain-list">
          ${normalized.map((item) => `
            <li>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
              ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
              ${item.validate ? `<em>验证：${esc(item.validate)}</em>` : ""}
            </li>
          `).join("")}
        </ul>
      `;
    }

    function renderExplainabilityBlock(explainability) {
      const block = explainability && typeof explainability === "object" ? explainability : {};
      const judgement = String(block.judgement || "").trim();
      const because = Array.isArray(block.because) ? block.because : [];
      const evidence = Array.isArray(block.evidence) ? block.evidence : [];
      const validate = Array.isArray(block.validate) ? block.validate : [];
      if (!judgement && !because.length && !evidence.length && !validate.length) return "";
      return `
        <section class="cr4-explain">
          <div class="cr4-explain-head">
            <p class="cr4-explain-kicker">Explainability</p>
            <h4>${esc(judgement || "为什么这么判断")}</h4>
          </div>
          <div class="cr4-explain-grid">
            <div class="cr4-explain-card">
              <span>因为</span>
              ${renderExplainList(because, "当前未补充原因说明")}
            </div>
            <div class="cr4-explain-card">
              <span>依据</span>
              ${renderExplainList(evidence, "当前未补充依据来源")}
            </div>
            <div class="cr4-explain-card">
              <span>可验证动作</span>
              ${renderExplainList(validate, "当前未补充验证动作")}
            </div>
          </div>
        </section>
      `;
    }

    // ── per-section body renderers ────────────────────────────────────────────

    function renderIndustryBody(data) {
      const explainability = data.explainability || {};
      const hotDirs   = Array.isArray(data.hot_directions)   ? data.hot_directions.slice(0, 4)   : [];
      const skillPrios = Array.isArray(data.skill_priorities) ? data.skill_priorities.slice(0, 6) : [];
      const risks      = Array.isArray(data.risk_signals)     ? data.risk_signals.slice(0, 4)     : [];
      const summary    = data.industry_summary || "";

      const statCards = [
        statCard("升温方向", hotDirs.length || "—", "个热点赛道", "cr4-ac-purple"),
        statCard("高优先技能", skillPrios.filter((s) => s.importance === "高").length || skillPrios.length || "—", "项能力投资", "cr4-ac-blue"),
        statCard("风险信号", risks.length || "—", "项待关注", "cr4-ac-amber"),
      ];

      const hotList = hotDirs.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">升温方向</div></div>
          ${hotDirs.map((d) => `
            <div class="cr4-insight-item">
              <div class="cr4-insight-head">
                <span class="cr4-row-label">${esc(d.name || String(d))}</span>
                <span class="cr4-badge ${d.confidence === "高" ? "cr4-badge-green" : d.confidence === "低" ? "cr4-badge-red" : "cr4-badge-amber"}">${esc(d.confidence || "中")}</span>
              </div>
              ${(d.summary || d.why_important) ? `<p>${esc(d.summary || d.why_important || "")}</p>` : ""}
              <div class="cr4-meta-row">
                ${d.source_type ? `<small>${esc(`来源：${d.source_type}`)}</small>` : ""}
                ${d.time_horizon ? `<small>${esc(`时效：${d.time_horizon}`)}</small>` : ""}
              </div>
              ${d.validation_action ? `<em>${esc(`验证：${d.validation_action}`)}</em>` : ""}
            </div>`).join("")}
        </div>` : "";

      const skillList = skillPrios.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">能力投资优先级</div></div>
          ${skillPrios.map((s) => `
            ${skillBar(s.skill || String(s), s.importance === "高" ? 85 : s.importance === "低" ? 40 : 65,
              s.importance === "高" ? "linear-gradient(90deg,var(--cr4-primary),var(--cr4-primary-light))" :
              s.importance === "低" ? "linear-gradient(90deg,#94a3b8,#cbd5e1)" :
              "linear-gradient(90deg,var(--cr4-secondary),#38bdf8)")}
            ${(s.reason || s.priority_reason) ? `<div class="cr4-inline-note">${esc(s.reason || s.priority_reason || "")}</div>` : ""}
          `).join("")}
        </div>` : "";

      const riskList = risks.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">风险信号</div></div>
          <div class="cr4-gap-grid">
            ${risks.map((r, i) => gapPill(String(r), i === 0 ? "urgent" : "warn")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        ${summary ? `<div class="cr4-summary-banner">${esc(summary)}</div>` : ""}
        <div class="cr4-stat-row">${statCards.join("")}</div>
        <div class="cr4-grid-2">${hotList}${skillList}</div>
        ${riskList}`;
    }

    function renderPositioningBody(data) {
      const explainability = data.explainability || {};
      const tracks      = Array.isArray(data.recommended_tracks)       ? data.recommended_tracks      : [];
      const hyps        = Array.isArray(data.hypotheses_for_evidence)  ? data.hypotheses_for_evidence : [];
      const constraints = Array.isArray(data.constraints_hard)         ? data.constraints_hard        : [];
      const summary     = data.user_intent_summary || "";

      const trackCards = tracks.map((t, i) => `
        <div class="cr4-track-card ${i === 0 ? "cr4-track-primary" : ""}">
          <div class="cr4-track-priority">${i === 0 ? "P0 主推荐" : `P${i} 备选`}</div>
          <div class="cr4-track-name">${esc(String(t))}</div>
          ${hyps[i]?.reason ? `<div class="cr4-track-copy">${esc(hyps[i].reason)}</div>` : ""}
          ${hyps[i] ? `<div class="cr4-track-prove">须证明：${esc((hyps[i].must_prove || []).slice(0, 2).join("、"))}</div>` : ""}
        </div>`).join("");

      const constraintBlock = constraints.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">硬约束</div></div>
          <div class="cr4-gap-grid">
            ${constraints.map((c) => gapPill(String(c), "warn")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        ${summary ? `<div class="cr4-summary-banner">${esc(summary)}</div>` : ""}
        <div class="cr4-stat-row">
          ${statCard("推荐方向", tracks.length || "—", "条并行假设", "cr4-ac-purple")}
          ${statCard("硬约束", constraints.length || "0", "项限制条件", "cr4-ac-amber")}
          ${statCard("证据命题", hyps.reduce((n, h) => n + (h.must_prove || []).length, 0) || "—", "项待验证", "cr4-ac-blue")}
        </div>
        ${tracks.length ? `<div class="cr4-track-grid">${trackCards}</div>` : ""}
        ${constraintBlock}`;
    }

    function renderResumeBody(data) {
      const explainability = data.explainability || {};
      const skills  = Array.isArray(data.technical_skills)    ? data.technical_skills.slice(0, 8)   : [];
      const genComp = Array.isArray(data.general_competencies) ? data.general_competencies.slice(0, 6) : [];
      const gaps    = Array.isArray(data.gaps)                 ? data.gaps.slice(0, 4)               : [];
      const hyps    = Array.isArray(data.hypothesis_support)   ? data.hypothesis_support              : [];

      const strengthCount = skills.filter((s) => s.strength === "strong").length;
      const gapCount = gaps.length;

      const skillBars = skills.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">专业技能证据</div><div class="cr4-card-sub">技术能力</div></div>
          ${skills.map((s) => skillBar(s.skill || String(s),
            s.strength === "strong" ? 88 : s.strength === "medium" ? 65 : 38,
            s.strength === "strong" ? "linear-gradient(90deg,var(--cr4-primary),var(--cr4-primary-light))" :
            s.strength === "medium" ? "linear-gradient(90deg,var(--cr4-secondary),#38bdf8)" :
            "linear-gradient(90deg,#f59e0b,#fbbf24)")).join("")}
        </div>` : "";

      const genBars = genComp.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">通用能力证据</div><div class="cr4-card-sub">软技能</div></div>
          ${genComp.map((g) => skillBar(g.competency || String(g),
            g.strength === "strong" ? 85 : g.strength === "medium" ? 62 : 35,
            "linear-gradient(90deg,var(--cr4-success),#34d399)")).join("")}
        </div>` : "";

      const gapBlock = gaps.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">证据缺口</div></div>
          <div class="cr4-gap-grid">
            ${gaps.map((g, i) => gapPill(String(g.claim_in_resume || g.issue || g), i === 0 ? "urgent" : "warn")).join("")}
          </div>
          <div class="cr4-detail-stack">
            ${gaps.map((g) => `
              <div class="cr4-detail-item">
                <strong>${esc(String(g.claim_in_resume || "证据缺口"))}</strong>
                ${g.why_it_matters ? `<p>${esc(g.why_it_matters)}</p>` : ""}
                ${g.suggestion ? `<em>${esc(`建议：${g.suggestion}`)}</em>` : ""}
              </div>
            `).join("")}
          </div>
        </div>` : "";

      const traceBlock = (skills.length || genComp.length) ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">判断依据回指</div><div class="cr4-card-sub">哪些结论能指回简历</div></div>
          <div class="cr4-detail-stack">
            ${skills.slice(0, 3).map((s) => `
              <div class="cr4-detail-item">
                <strong>${esc(s.skill || "")}</strong>
                ${s.note || s.why_counts_as_evidence ? `<p>${esc(s.note || s.why_counts_as_evidence || "")}</p>` : ""}
                ${Array.isArray(s.evidence_ids) && s.evidence_ids.length ? `<small>${esc(`证据 ID：${s.evidence_ids.join("、")}`)}</small>` : `<small>当前未识别到明确证据 ID</small>`}
              </div>
            `).join("")}
            ${genComp.slice(0, 2).map((g) => `
              <div class="cr4-detail-item">
                <strong>${esc(g.competency || "")}</strong>
                ${g.note || g.why_counts_as_evidence ? `<p>${esc(g.note || g.why_counts_as_evidence || "")}</p>` : ""}
                ${Array.isArray(g.evidence_ids) && g.evidence_ids.length ? `<small>${esc(`证据 ID：${g.evidence_ids.join("、")}`)}</small>` : `<small>当前未识别到明确证据 ID</small>`}
              </div>
            `).join("")}
          </div>
        </div>` : "";

      const hypBlock = hyps.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">方向假设对齐</div></div>
          ${hyps.map((h) => `
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(h.track || "")}</span>
              <span class="cr4-badge ${h.status === "supported" ? "cr4-badge-green" : h.status === "partial" ? "cr4-badge-amber" : h.status === "unsupported" ? "cr4-badge-red" : "cr4-badge-muted"}">
                ${esc(h.status === "supported" ? "已支持" : h.status === "partial" ? "部分支持" : h.status === "unsupported" ? "不支持" : "待核实")}
              </span>
            </div>`).join("")}
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("强证据", strengthCount || "—", "项可追溯", "cr4-ac-green")}
          ${statCard("证据缺口", gapCount || "0", "项待补充", "cr4-ac-amber")}
          ${statCard("通用能力", genComp.length || "—", "项", "cr4-ac-blue")}
        </div>
        <div class="cr4-grid-2">${skillBars}${genBars}</div>
        ${gapBlock}
        ${traceBlock}
        ${hypBlock}`;
    }

    function renderCompetencyBody(data) {
      const explainability = data.explainability || {};
      const dims     = data.dimensions || {};
      const strengths = Array.isArray(data.strengths) ? data.strengths.slice(0, 4) : [];
      const gaps     = Array.isArray(data.gaps)       ? data.gaps.slice(0, 4)      : [];

      const DIM_CFG = [
        { key: "professional_skills",       label: "专业技能",  icon: "📚", color: "var(--cr4-primary)",   accent: "cr4-dim-purple" },
        { key: "general_ability",           label: "通用能力",  icon: "💻", color: "var(--cr4-secondary)", accent: "cr4-dim-blue"   },
        { key: "communication_collaboration",label: "沟通协作", icon: "🤝", color: "var(--cr4-accent)",    accent: "cr4-dim-amber"  },
        { key: "learning_agility",          label: "学习力",    icon: "🚀", color: "var(--cr4-success)",   accent: "cr4-dim-green"  },
        { key: "execution",                 label: "执行力",    icon: "⚡", color: "var(--cr4-primary)",   accent: "cr4-dim-purple" },
        { key: "practice_maturity",         label: "实践力",    icon: "🔧", color: "var(--cr4-secondary)", accent: "cr4-dim-blue"   },
      ];

      const dimCards = DIM_CFG.map((cfg) => {
        const d = dims[cfg.key] || {};
        const level = String(d.level || "unknown");
        const score = gradeToScore(level);
        const conf  = String(d.confidence || "low");
        const confLabel = conf === "high" ? "高置信" : conf === "medium" ? "中置信" : "低置信/未知";
        return dimCard(cfg.icon, cfg.label, `等级 ${level.toUpperCase()} · ${confLabel}`, score, cfg.color, cfg.accent);
      }).join("");

      const overallScore = (() => {
        const scored = DIM_CFG.map((cfg) => gradeToScore((dims[cfg.key] || {}).level)).filter((s) => s > 0);
        return scored.length ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : 0;
      })();

      const strengthBlock = strengths.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">核心优势</div></div>
          ${strengths.map((s) => `<div class="cr4-row-item"><span class="cr4-row-label">✓ ${esc(String(s))}</span></div>`).join("")}
        </div>` : "";

      const gapBlock = gaps.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">短板与提升项</div></div>
          ${gaps.map((g, i) => `
            <div class="cr4-row-item">
              <span class="cr4-row-label">${esc(g.dimension || String(g.id || ""))}</span>
              <span class="cr4-badge ${g.severity === "high" ? "cr4-badge-red" : g.severity === "medium" ? "cr4-badge-amber" : "cr4-badge-muted"}">${esc(g.severity === "high" ? "高" : g.severity === "medium" ? "中" : "低")}</span>
            </div>`).join("")}
        </div>` : "";

      const dimExplain = Object.entries(dims).length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">维度判断依据</div></div>
          <div class="cr4-detail-stack">
            ${Object.entries(dims).slice(0, 6).map(([key, value]) => {
              const entry = value && typeof value === "object" ? value : {};
              const reason = String(entry.judgement_reason || "").trim();
              const evidenceIds = Array.isArray(entry.evidence_ids) && entry.evidence_ids.length
                ? `证据 ID：${entry.evidence_ids.join("、")}`
                : "当前缺少明确证据 ID";
              const label = {"professional_skills":"专业技能","general_ability":"通用能力","communication_collaboration":"沟通协作","learning_agility":"学习力","execution":"执行力","practice_maturity":"实践力"}[key] || key;
              return `
                <div class="cr4-detail-item">
                  <strong>${esc(label)}</strong>
                  <p>${esc(reason || `当前等级为 ${String(entry.level || "unknown").toUpperCase()}，置信度 ${String(entry.confidence || "low")}`)}</p>
                  <small>${esc(evidenceIds)}</small>
                </div>
              `;
            }).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("综合能力分", overallScore || "—", "基于证据推算", "cr4-ac-purple")}
          ${statCard("核心优势", strengths.length || "—", "项", "cr4-ac-green")}
          ${statCard("短板项", gaps.length || "0", "项待提升", "cr4-ac-amber")}
        </div>
        <div class="cr4-dim-grid">${dimCards}</div>
        <div class="cr4-grid-2">${strengthBlock}${gapBlock}</div>
        ${dimExplain}`;
    }

    function renderMatchBody(data) {
      const explainability = data.explainability || {};
      const fitScore  = Number(data.fit_score || 0);
      const fitBand   = String(data.fit_band || "not_ready");
      const hardFails = Array.isArray(data.hard_failures) ? data.hard_failures.slice(0, 4) : [];
      const gapsArr   = Array.isArray(data.partial_gaps)  ? data.partial_gaps.slice(0, 5)  : [];
      const bandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || fitBand;
      const bandClass = fitBand === "strong" ? "cr4-badge-green" : fitBand === "moderate" ? "cr4-badge-blue" : fitBand === "weak" ? "cr4-badge-amber" : "cr4-badge-red";
      const scoreColor = fitScore >= 70 ? "#10b981" : fitScore >= 50 ? "#f59e0b" : "#ef4444";
      const circum = 2 * Math.PI * 54;
      const offset = circum * (1 - fitScore / 100);

      const scoreRing = `
        <div class="cr4-card cr4-match-score-card">
          <div class="cr4-card-title" style="margin-bottom:16px">综合契合度</div>
          <div class="cr4-match-circle">
            <svg width="140" height="140" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="54" fill="none" stroke="#e2e8f0" stroke-width="10"/>
              <circle cx="70" cy="70" r="54" fill="none" stroke="${scoreColor}" stroke-width="10"
                stroke-linecap="round" stroke-dasharray="${circum.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
                transform="rotate(-90 70 70)"/>
              <defs>
                <linearGradient id="cr4matchGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="${scoreColor}"/>
                  <stop offset="100%" stop-color="${scoreColor}88"/>
                </linearGradient>
              </defs>
            </svg>
            <div class="cr4-match-circle-text">
              <div class="cr4-match-circle-value" style="color:${scoreColor}">${fitScore}</div>
              <div class="cr4-match-circle-unit">/ 100</div>
            </div>
          </div>
          <div style="margin-top:12px">
            <div style="font-size:14px;font-weight:600;margin-bottom:6px">${esc(data.target_role || "目标岗位")}</div>
            <span class="cr4-badge ${bandClass}">${esc(bandLabel)}</span>
          </div>
          <div class="cr4-match-details">
            <div class="cr4-match-detail"><div class="cr4-match-detail-label">硬门槛缺口</div><div class="cr4-match-detail-val" style="color:var(--cr4-danger)">${hardFails.length}</div></div>
            <div class="cr4-match-detail"><div class="cr4-match-detail-label">待补强项</div><div class="cr4-match-detail-val" style="color:var(--cr4-accent)">${gapsArr.length}</div></div>
          </div>
        </div>`;

      const hardBlock = hardFails.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">硬门槛缺口</div></div>
          <div class="cr4-gap-grid">
            ${hardFails.map((f) => gapPill(String(f), "urgent")).join("")}
          </div>
        </div>` : "";

      const gapBlock = gapsArr.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">待补强项</div></div>
          ${gapsArr.map((g) => `
            <div class="cr4-detail-item">
              <div class="cr4-detail-head">
                <strong>${esc(g.requirement || String(g))}</strong>
                <span class="cr4-badge cr4-badge-amber">${esc(g.remediation_type || "待补充")}</span>
              </div>
              ${g.reason || g.note ? `<p>${esc(g.reason || g.note || "")}</p>` : ""}
              <div class="cr4-meta-row">
                ${g.evidence_basis ? `<small>${esc(`依据：${g.evidence_basis}`)}</small>` : ""}
                ${g.priority_reason ? `<small>${esc(`优先级：${g.priority_reason}`)}</small>` : ""}
              </div>
            </div>`).join("")}
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-match-layout">
          ${scoreRing}
          <div class="cr4-match-right">
            ${hardBlock}
            ${gapBlock}
          </div>
        </div>`;
    }

    function renderPathBody(data) {
      const explainability = data.explainability || {};
      const milestones = Array.isArray(data.milestones)    ? data.milestones    : [];
      const visions    = Array.isArray(data.vision_roles)  ? data.vision_roles  : [];
      const contin     = Array.isArray(data.contingency)   ? data.contingency   : [];
      const hardMust   = ((data.dependencies || {}).must_resolve_hard_failures || []);

      const timelineHtml = milestones.length ? milestones.slice(0, 5).map((m, i) => {
        const stateClass = i === 0 ? "current" : "future";
        return timelineItem(
          m.horizon || `阶段${i + 1}`,
          m.title || "",
          "",
          [m.reason, (m.actions || []).slice(0, 2).join("；")].filter(Boolean).join(" · "),
          [...(m.metrics || []), ...(m.linked_gap ? [`关联差距：${m.linked_gap}`] : [])],
          stateClass
        );
      }).join("") : "";

      const visionBlock = visions.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">长期愿景角色</div></div>
          ${visions.map((v, i) => `
            <div class="cr4-row-item">
              <span class="cr4-badge ${i === 0 ? "cr4-badge-purple" : "cr4-badge-blue"}">${i === 0 ? "主目标" : "远期"}</span>
              <span class="cr4-row-label">${esc(String(v))}</span>
            </div>`).join("")}
        </div>` : "";

      const continBlock = contin.length ? `
        <div class="cr4-card">
          <div class="cr4-card-header"><div class="cr4-card-title">B 计划 / 应急</div></div>
          ${contin.map((c) => `<div class="cr4-row-item"><span class="cr4-row-label">· ${esc(String(c))}</span></div>`).join("")}
        </div>` : "";

      const hardBlock = hardMust.length ? `
        <div class="cr4-card cr4-card-full">
          <div class="cr4-card-header"><div class="cr4-card-title">必须先解决的硬门槛</div></div>
          <div class="cr4-gap-grid">
            ${hardMust.map((h) => gapPill(String(h), "urgent")).join("")}
          </div>
        </div>` : "";

      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-stat-row">
          ${statCard("里程碑", milestones.length || "—", "个阶段", "cr4-ac-blue")}
          ${statCard("长期角色", visions.length || "—", "个愿景", "cr4-ac-purple")}
          ${statCard("B计划", contin.length || "—", "条应急", "cr4-ac-green")}
        </div>
        <div class="cr4-grid-2">
          ${timelineHtml ? `<div class="cr4-card cr4-card-full"><div class="cr4-card-header"><div class="cr4-card-title">成长路径时间线</div></div><div class="cr4-timeline">${timelineHtml}</div></div>` : ""}
        </div>
        <div class="cr4-grid-2">${visionBlock}${continBlock}</div>
        ${hardBlock}`;
    }

    function renderExecutiveBody(data) {
      const dashboard = data.dashboard_summary || {};
      const headline = dashboard.headline || "";
      const because = Array.isArray(dashboard.headline_because) ? dashboard.headline_because : [];
      const cards = Array.isArray(dashboard.decision_cards) ? dashboard.decision_cards : [];
      const fitScore = Number(dashboard.fit_score || 0);
      const fitBandLabel = String(dashboard.fit_band_label || "").trim() || "待评估";
      const scoreColor = fitScore >= 70 ? "#10b981" : fitScore >= 50 ? "#f59e0b" : "#ef4444";
      const circum = 2 * Math.PI * 48;
      const offset = circum * (1 - fitScore / 100);
      const scoreRing = fitScore ? `
        <div class="cr4-card cr4-match-score-card" style="max-width:220px">
          <div class="cr4-match-circle" style="transform:scale(0.85)">
            <svg width="140" height="140" viewBox="0 0 140 140">
              <circle cx="70" cy="70" r="48" fill="none" stroke="#e2e8f0" stroke-width="10"/>
              <circle cx="70" cy="70" r="48" fill="none" stroke="${scoreColor}" stroke-width="10"
                stroke-linecap="round" stroke-dasharray="${circum.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
                transform="rotate(-90 70 70)"/>
            </svg>
            <div class="cr4-match-circle-text">
              <div class="cr4-match-circle-value" style="color:${scoreColor};font-size:28px">${fitScore}</div>
              <div class="cr4-match-circle-unit">/ 100</div>
            </div>
          </div>
          <div style="margin-top:4px;text-align:center"><span class="cr4-badge ${fitScore >= 70 ? 'cr4-badge-green' : fitScore >= 50 ? 'cr4-badge-blue' : 'cr4-badge-amber'}">${esc(fitBandLabel)}</span></div>
        </div>` : "";
      const cardHtml = cards.map((c) => `
        <div class="cr4-card ${c.tone === 'risk' ? 'cr4-card-risk' : ''}">
          <div class="cr4-card-header"><div class="cr4-card-title">${esc(c.label || '决策')}</div><div class="cr4-card-sub">${esc(c.title || '')}</div></div>
          ${c.summary ? `<p class="cr4-inline-note">${esc(c.summary)}</p>` : ''}
          ${Array.isArray(c.items) && c.items.length ? `<div class="cr4-pill-row">${c.items.map(i => `<span class="cr4-tag">${esc(i)}</span>`).join('')}</div>` : ''}
        </div>
      `).join('');
      return `
        <div class="cr4-summary-banner" style="font-size:1.05rem">${esc(headline || data.executive_summary || "报告已整合多智能体分析结果，以下为结构化摘要。")}</div>
        <div class="cr4-match-layout" style="align-items:flex-start;gap:18px;margin-top:10px">
          ${scoreRing}
          <div style="flex:1;min-width:0;display:grid;gap:12px">
            ${because.length ? `<div class="cr4-card"><div class="cr4-card-header"><div class="cr4-card-title">判断依据</div></div>${because.map(b => `<div class="cr4-row-item"><span class="cr4-row-label">· ${esc(b)}</span></div>`).join('')}</div>` : ""}
            ${cardHtml}
          </div>
        </div>`;
    }

    function renderPersonalTraitsBody(data) {
      const pos = data.positioning || {};
      const res = data.resume || {};
      const comp = data.competency || {};
      const posHtml = renderPositioningBody(pos);
      const resHtml = renderResumeBody(res);
      const compHtml = renderCompetencyBody(comp);
      return `
        <div class="cr4-nested-modules">
          <details class="cr4-nested-mod" open>
            <summary>职业定位假设</summary>
            <div class="cr4-nested-body">${posHtml}</div>
          </details>
          <details class="cr4-nested-mod">
            <summary>简历证据链</summary>
            <div class="cr4-nested-body">${resHtml}</div>
          </details>
          <details class="cr4-nested-mod">
            <summary>能力评估画像</summary>
            <div class="cr4-nested-body">${compHtml}</div>
          </details>
        </div>`;
    }

    function renderTargetJobBody(data) {
      const roles = Array.isArray(data.role_rankings) ? data.role_rankings : [];
      const explainability = data.explainability || {};
      const roleCards = roles.map((r, i) => {
        const score = Math.max(0, Math.min(100, Number(r.overall_score ?? r.overallScore ?? 0)));
        return `
          <div class="cr4-card">
            <div class="cr4-card-header">
              <div class="cr4-card-title">${esc(r.name || r.title || "岗位")}</div>
              <div class="cr4-card-sub">匹配得分 ${score}%</div>
            </div>
            ${Array.isArray(r.required_skills) && r.required_skills.length ? `
              <div class="cr4-pill-row" style="margin-bottom:8px">
                ${r.required_skills.map(s => `<span class="cr4-tag">${esc(s)}</span>`).join('')}
              </div>
            ` : ''}
            ${Array.isArray(r.because) && r.because.length ? `<div class="cr4-inline-note">${esc(r.because.join('；'))}</div>` : ''}
          </div>
        `;
      }).join('');
      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-grid-2">${roleCards || '<p class="cr4-module-empty">目标岗位数据待补充</p>'}</div>
      `;
    }

    function renderGapActionBody(data) {
      const milestones = Array.isArray(data.milestones) ? data.milestones : [];
      const gapMap = data.gap_map || {};
      const explainability = data.explainability || {};
      const timelineHtml = milestones.length ? milestones.slice(0, 5).map((m, i) => {
        const stateClass = i === 0 ? "current" : "future";
        return timelineItem(
          m.horizon || `阶段${i + 1}`,
          m.title || "",
          "",
          [m.reason, (m.actions || []).slice(0, 2).join("；")].filter(Boolean).join(" · "),
          [...(m.metrics || []), ...(m.linked_gap ? [`关联差距：${m.linked_gap}`] : [])],
          stateClass
        );
      }).join("") : "";
      const gapPills = [
        ...(Array.isArray(gapMap.risk_alerts) ? gapMap.risk_alerts : []),
        ...(Array.isArray(gapMap.skill_gaps) ? gapMap.skill_gaps : []),
        ...(Array.isArray(gapMap.evidence_gaps) ? gapMap.evidence_gaps : []),
      ].slice(0, 6);
      return `
        ${renderExplainabilityBlock(explainability)}
        <div class="cr4-grid-2">
          ${timelineHtml ? `<div class="cr4-card cr4-card-full"><div class="cr4-card-header"><div class="cr4-card-title">行动计划时间线</div></div><div class="cr4-timeline">${timelineHtml}</div></div>` : ""}
        </div>
        ${gapPills.length ? `
          <div class="cr4-card cr4-card-full" style="margin-top:12px">
            <div class="cr4-card-header"><div class="cr4-card-title">关键差距项</div></div>
            <div class="cr4-gap-grid">${gapPills.map((g, i) => gapPill(String(g), i === 0 ? "urgent" : "warn")).join("")}</div>
          </div>
        ` : ""}
      `;
    }

    function renderRiskBackupBody(data) {
      const industryRisks = Array.isArray(data.industry_risks) ? data.industry_risks : [];
      const hardFails = Array.isArray(data.hard_failures) ? data.hard_failures : [];
      const pathRisks = Array.isArray(data.path_risks) ? data.path_risks : [];
      const contingency = Array.isArray(data.contingency) ? data.contingency : [];
      const riskPills = [
        ...industryRisks.map(r => ({ text: String(r), type: "warn" })),
        ...hardFails.map(r => ({ text: String(r), type: "urgent" })),
        ...pathRisks.map(r => ({ text: String(r), type: "warn" })),
      ].slice(0, 8);
      return `
        <div class="cr4-stat-row">
          ${statCard("宏观风险", industryRisks.length || "—", "项", "cr4-ac-amber")}
          ${statCard("硬门槛缺口", hardFails.length || "0", "项", "cr4-ac-red")}
          ${statCard("备选方案", contingency.length || "—", "条", "cr4-ac-green")}
        </div>
        ${riskPills.length ? `
          <div class="cr4-card cr4-card-full">
            <div class="cr4-card-header"><div class="cr4-card-title">风险清单</div></div>
            <div class="cr4-gap-grid">${riskPills.map(r => gapPill(r.text, r.type)).join("")}</div>
          </div>
        ` : ""}
        ${contingency.length ? `
          <div class="cr4-card cr4-card-full" style="margin-top:12px">
            <div class="cr4-card-header"><div class="cr4-card-title">B 计划 / 应急方案</div></div>
            ${contingency.map(c => `<div class="cr4-row-item"><span class="cr4-row-label">· ${esc(String(c))}</span></div>`).join("")}
          </div>
        ` : ""}
      `;
    }

    function renderAppendixBody(data) {
      const techSkills = Array.isArray(data.technical_skills) ? data.technical_skills : [];
      const genComp = Array.isArray(data.general_competencies) ? data.general_competencies : [];
      const verifications = Array.isArray(data.verification_actions) ? data.verification_actions : [];
      const evidenceRows = [
        ...techSkills.map(s => ({ label: s.skill || "", strength: s.strength || "", ids: s.evidence_ids || [] })),
        ...genComp.map(g => ({ label: g.competency || "", strength: g.strength || "", ids: g.evidence_ids || [] })),
      ].slice(0, 10);
      return `
        ${evidenceRows.length ? `
          <div class="cr4-card cr4-card-full">
            <div class="cr4-card-header"><div class="cr4-card-title">证据映射清单</div></div>
            <div class="cr4-detail-stack">
              ${evidenceRows.map(e => `
                <div class="cr4-detail-item">
                  <div class="cr4-detail-head"><strong>${esc(e.label)}</strong><span class="cr4-badge cr4-badge-muted">${esc(e.strength)}</span></div>
                  ${e.ids.length ? `<small>证据 ID：${esc(e.ids.join("、"))}</small>` : `<small>当前未识别到明确证据 ID</small>`}
                </div>
              `).join("")}
            </div>
          </div>
        ` : ""}
        ${verifications.length ? `
          <div class="cr4-card cr4-card-full" style="margin-top:12px">
            <div class="cr4-card-header"><div class="cr4-card-title">验证建议清单</div></div>
            ${verifications.map(v => `<div class="cr4-row-item"><span class="cr4-row-label">· ${esc(String(v))}</span></div>`).join("")}
          </div>
        ` : ""}
      `;
    }

    // ── render all sections ───────────────────────────────────────────────────

    const bodyRenderers = {
      executive_summary:    renderExecutiveBody,
      macro_environment:    renderIndustryBody,
      personal_traits:      renderPersonalTraitsBody,
      target_job_analysis:  renderTargetJobBody,
      matching_decision:    renderMatchBody,
      gap_action_plan:      renderGapActionBody,
      risk_backup:          renderRiskBackupBody,
      appendix:             renderAppendixBody,
    };

    const allowedKeys = groupConfig ? new Set(groupConfig.sectionKeys || []) : null;
    const availableModules = navOrder
      .filter((key) => navMeta[key])
      .map((key, idx) => ({ key, idx, meta: { ...navMeta[key], icon: String(idx + 1).padStart(2, "0"), label: sections[key]?.label || navMeta[key].label }, section: sections[key] }))
      .filter((item) => Boolean(item.section) && (!allowedKeys || allowedKeys.has(item.key)));

    const groupHeroHtml = groupConfig && !narrativeLayout ? `
      <section class="cr4-group-hero">
        <div class="cr4-group-head">
          <div class="cr4-group-copy">
            <p class="cr4-group-kicker">${esc(groupConfig.label || "Report Module")}</p>
            <h3 class="cr4-group-title">${esc(groupConfig.title || "")}</h3>
            <p class="cr4-group-summary">${esc(groupConfig.summary || "")}</p>
            <div class="cr4-group-meta">
              <span>${esc(bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || "褰撳墠涓荤嚎宀椾綅")}</span>
              <span>${esc(`鐗堟湰 ${bundle?.meta?.version || "--"}`)}</span>
              <span>${esc(bundle?.meta?.generated_at || "--")}</span>
            </div>
          </div>
          <button type="button" class="career-report-secondary-btn cr4-group-action" onclick="openCareerReportEditor()">鏅鸿兘娑﹁壊</button>
        </div>
        <div class="cr4-group-stat-grid">
          ${availableModules.map(({ meta, section }) => {
            const markdown = String(section?.markdown || "").trim();
            const bodyText = String(section?.data?.industry_summary || section?.data?.user_intent_summary || section?.data?.target_role || section?.data?.fit_band || "").trim();
            return `
              <article class="cr4-group-stat">
                <span>${esc(meta.kicker)}</span>
                <strong>${esc(meta.label)}</strong>
                <small>${esc(bodyText || (markdown ? "宸茬敓鎴愭ā鍧楀唴瀹癸紝鍙互缁х画涓嬮捇鏌ョ湅銆?" : "璇ユā鍧楁殏鏃犺緭鍑哄唴瀹广€?"))}</small>
              </article>
            `;
          }).join("")}
        </div>
        <div class="cr4-group-module-strip">
          ${availableModules.map(({ meta }, index) => `
            <button type="button" class="cr4-group-module-pill" data-report-scroll-target="${meta.anchor}">
              <span>${String(index + 1).padStart(2, "0")}</span>
              <strong>${esc(meta.label)}</strong>
              <small>${esc(meta.kicker)}</small>
            </button>
          `).join("")}
        </div>
      </section>
    ` : "";

    const sectionHtml = availableModules.map(({ key, idx, meta, section: sec }) => {
      if (!sec) return "";
      const markdown = String(sec.markdown || "").trim();
      const data     = sec.data || {};
      const renderer = bodyRenderers[key];
      const body     = renderer && !narrativeLayout ? renderer(data) : "";
      const polishTargetId = `cr4-polish-${key}`;

      let bodyHtml = "";
      let tailHtml = "";
      if (markdown) {
        bodyHtml = `
          <div class="cr4-module-markdown cr4-module-markdown--primary career-report-md-article">${renderMarkdownBasic(markdownForCareerReportReading(markdown), { enhancedLayout: true, previewReportId: bundle?.meta?.report_id })}</div>
          ${body ? `
            <details class="cr4-module-structure">
              <summary>结构化摘要（从正文提取，便于扫读）</summary>
              <div class="cr4-module-structure-inner">${body}</div>
            </details>` : ""}`;
        tailHtml = "";
      } else {
        bodyHtml = body || `<p class="cr4-module-empty">该模块尚未生成内容</p>`;
        tailHtml = "";
      }

      return `
        <section id="${meta.anchor}" class="cr4-module ${meta.accentClass}">
          <div class="cr4-module-head">
            <div class="cr4-module-icon">${meta.icon}</div>
            <div class="cr4-module-titles">
              <div class="cr4-module-kicker">${esc(meta.kicker)}</div>
              <h3 class="cr4-module-title">${esc(meta.label)}</h3>
            </div>
            <div class="cr4-module-actions">
              <button type="button" class="cr4-polish-btn" data-report-polish-section="${esc(key)}" data-report-polish-target="${esc(polishTargetId)}">润色本段</button>
            </div>
            <div class="cr4-module-num">${String(idx + 1).padStart(2, "0")}</div>
          </div>
          <div class="cr4-module-body">${bodyHtml}</div>
          <div id="${polishTargetId}" class="cr4-polish-output hidden"></div>
          ${tailHtml}
        </section>`;
    }).filter(Boolean).join("");

    return `<div class="cr4-report-modules ${groupConfig ? "is-grouped" : ""}">${groupConfig ? groupHeroHtml : ""}${sectionHtml}</div>`;
  }

  function renderHistoricalNotice() {
    if (!window.appState?.careerReportViewingHistorical) return "";
    return `
      <div class="career-report-viewing-historical">
        <span>当前正在查看历史版本，进度更新和任务打勾不会写回服务器。</span>
        <button type="button" class="career-report-back-latest-btn" data-report-action="back-latest">返回最新版本</button>
      </div>
    `;
  }

  function renderReportHero(bundle, tracker) {
    const meta = bundle?.meta || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_id || "待识别";
    return `
      <section class="career-report-reader-hero">
        <p class="career-report-reader-kicker">Career Report</p>
        <h2 class="career-report-reader-title">${esc(meta.title || "职业规划报告")}</h2>
        <p class="career-report-reader-copy">${formatText(bundle?.report_document?.executive_summary || meta.summary || "当前报告会根据画像、岗位匹配和职业访谈结果综合输出。")}</p>
        <div class="career-report-reader-meta">
          <span>主岗位：${esc(focusRole)}</span>
          <span>版本：${esc(meta.version || "--")}</span>
          <span>生成时间：${esc(meta.generated_at || "--")}</span>
        </div>
      </section>
      ${renderReportFeedbackCard()}
    `;
  }

  function getUserCenterReportViewModeSafe() {
    return typeof window.getUserCenterReportViewMode === "function"
      ? String(window.getUserCenterReportViewMode() || "report").trim().toLowerCase()
      : "report";
  }

  function getDashboardItemText(item) {
    if (item == null) return "";
    if (typeof item === "string" || typeof item === "number") return String(item).trim();
    if (typeof item === "object") {
      return String(
        item.name
        || item.skill
        || item.requirement
        || item.title
        || item.label
        || item.summary
        || item.text
        || item.claim_in_resume
        || item.competency
        || item.track
        || ""
      ).trim();
    }
    return "";
  }

  function normalizeExplainItem(item) {
    if (item == null) return null;
    if (typeof item === "string" || typeof item === "number") {
      const text = String(item).trim();
      return text ? { title: text, detail: "", meta: "", validate: "" } : null;
    }
    if (typeof item !== "object") return null;
    const title = String(
      item.title
      || item.label
      || item.name
      || item.skill
      || item.competency
      || item.requirement
      || item.track
      || getDashboardItemText(item)
      || ""
    ).trim();
    const detail = String(
      item.detail
      || item.summary
      || item.reason
      || item.note
      || item.why_important
      || item.priority_reason
      || item.because
      || ""
    ).trim();
    const metaParts = [];
    if (item.source_type) metaParts.push(`来源：${item.source_type}`);
    if (item.time_horizon) metaParts.push(`时效：${item.time_horizon}`);
    if (item.status) metaParts.push(`状态：${item.status}`);
    if (item.evidence) metaParts.push(String(item.evidence).trim());
    if (Array.isArray(item.evidence_ids) && item.evidence_ids.length) {
      metaParts.push(`证据 ID：${item.evidence_ids.join("、")}`);
    }
    const validate = String(item.validate || item.validation_action || "").trim();
    if (!title && !detail && !metaParts.length && !validate) return null;
    return {
      title: title || detail || metaParts[0] || "待补充",
      detail: title ? detail : "",
      meta: metaParts.join(" · "),
      validate,
    };
  }

  function renderDashboardList(title, items, placeholder = "暂无补充") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item) || {
        title: getDashboardItemText(item),
        detail: "",
        meta: "",
        validate: "",
      })
      .filter((item) => item.title);
    return `
      <div class="ucrd-list-block">
        <div class="ucrd-list-title">${esc(title)}</div>
        ${normalized.length ? `
          <ul class="ucrd-list">
            ${normalized.map((item) => `
              <li>
                <strong>${esc(item.title)}</strong>
                ${item.detail ? `<span>${esc(item.detail)}</span>` : ""}
                ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
                ${item.validate ? `<em>${esc(`验证：${item.validate}`)}</em>` : ""}
              </li>
            `).join("")}
          </ul>
        ` : `<p class="ucrd-list-empty">${esc(placeholder)}</p>`}
      </div>
    `;
  }

  function renderDashboardItemCluster(title, items, empty = "暂无补充") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item))
      .filter(Boolean);
    return `
      <div class="ucrd-trace-block">
        <div class="ucrd-list-title">${esc(title)}</div>
        ${normalized.length ? normalized.map((item) => `
          <article class="ucrd-trace-item">
            <strong>${esc(item.title)}</strong>
            ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
            ${item.validate ? `<em>${esc(`验证：${item.validate}`)}</em>` : ""}
          </article>
        `).join("") : `<p class="ucrd-list-empty">${esc(empty)}</p>`}
      </div>
    `;
  }

  function renderReasonGroup(label, items, empty = "") {
    const normalized = (Array.isArray(items) ? items : [])
      .map((item) => normalizeExplainItem(item))
      .filter(Boolean);
    if (!normalized.length && !empty) return "";
    return `
      <div class="ucrd-mini-group">
        <span>${esc(label)}</span>
        ${normalized.length ? `
          <ul>
            ${normalized.map((item) => `
              <li>
                <strong>${esc(item.title)}</strong>
                ${item.detail ? `<small>${esc(item.detail)}</small>` : ""}
              </li>
            `).join("")}
          </ul>
        ` : `<p>${esc(empty)}</p>`}
      </div>
    `;
  }

  function renderFullReportHeader(bundle, tracker) {
    const meta = bundle?.meta || {};
    const matchOutput = bundle?.match_output || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(matchOutput.fit_score || 0)));
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(matchOutput.fit_band || "")] || "待评估";
    return `
      <section class="ucrd-full-head">
        <div class="ucrd-full-head-copy">
          <p class="ucrd-kicker">Complete Report</p>
          <h2 class="ucrd-full-head-title">${esc(meta.title || "职业规划报告")}</h2>
          <p class="ucrd-full-head-summary">${formatText(bundle?.report_document?.executive_summary || meta.summary || "")}</p>
        </div>
        <div class="ucrd-full-head-meta">
          <span>主岗位：${esc(focusRole)}</span>
          <span>匹配：${esc(`${fitScore}% · ${fitBandLabel}`)}</span>
          <span>版本：${esc(meta.version || "--")}</span>
          <span>生成时间：${esc(meta.generated_at || "--")}</span>
        </div>
      </section>
    `;
  }

  function getReportFitTone(fitBand, score = 0) {
    const normalized = String(fitBand || "").trim().toLowerCase();
    if (normalized === "strong" || score >= 75) return { label: "较高", tone: "high" };
    if (normalized === "moderate" || score >= 45) return { label: "中等", tone: "medium" };
    if (normalized === "weak" || score > 0) return { label: "较低", tone: "low" };
    return { label: "尚需准备", tone: "blocked" };
  }

  function normalizeReportDimensions(dimensions) {
    const labelMap = {
      professional_skills: "专业技能",
      general_ability: "通用能力",
      communication_collaboration: "沟通协作",
      learning_agility: "学习力",
      execution: "执行力",
      practice_maturity: "实践力",
      user_research: "用户研究",
      data_analysis: "数据分析",
      management: "管理能力",
      ai_application: "AI 应用",
      planning: "产品规划"
    };
    const scoreMap = {
      strong: 86,
      high: 86,
      moderate: 62,
      medium: 62,
      basic: 42,
      low: 42,
      weak: 28,
      unknown: 16
    };
    const levelLabelMap = {
      strong: "优势",
      high: "优势",
      moderate: "中等",
      medium: "中等",
      basic: "待提升",
      low: "待提升",
      weak: "短板",
      unknown: "待补证据"
    };
    const rawEntries = Array.isArray(dimensions)
      ? dimensions.map((item, index) => [item?.key || item?.id || item?.dimension || `dimension_${index}`, item])
      : Object.entries(dimensions || {});
    return rawEntries.slice(0, 6).map(([key, value]) => {
      const level = String(value?.level || value?.status || "unknown").trim().toLowerCase();
      const score = Math.max(0, Math.min(100, Number(value?.score ?? scoreMap[level] ?? 16)));
      const confidence = String(value?.confidence || "").trim();
      const evidenceIds = Array.isArray(value?.evidence_ids) ? value.evidence_ids : [];
      return {
        key,
        label: labelMap[key] || String(value?.label || key).trim(),
        level,
        levelLabel: levelLabelMap[level] || "待判断",
        score,
        confidence,
        reason: String(value?.judgement_reason || value?.reason || value?.summary || "").trim(),
        evidenceIds
      };
    });
  }

  function collectUniqueExplainItems(...sources) {
    const seen = new Set();
    const result = [];
    sources.forEach((source) => {
      (Array.isArray(source) ? source : []).forEach((item) => {
        const normalized = normalizeExplainItem(item) || (() => {
          const title = getDashboardItemText(item);
          return title ? { title, detail: "", meta: "", validate: "" } : null;
        })();
        if (!normalized || !normalized.title) return;
        const key = `${normalized.title}__${normalized.detail}`;
        if (seen.has(key)) return;
        seen.add(key);
        result.push(normalized);
      });
    });
    return result;
  }

  function renderReportDocChips(items) {
    const texts = (Array.isArray(items) ? items : [])
      .map((item) => {
        if (typeof item === "string" || typeof item === "number") return String(item).trim();
        const normalized = normalizeExplainItem(item);
        return normalized ? normalized.title : "";
      })
      .filter(Boolean);
    if (!texts.length) return "";
    return `
      <div class="crdoc-chip-row">
        ${texts.map((text) => `<span class="crdoc-chip">${esc(text)}</span>`).join("")}
      </div>
    `;
  }

  function renderReportDocList(items, emptyText = "暂无补充", limit = 4) {
    const normalized = collectUniqueExplainItems(items).slice(0, limit);
    if (!normalized.length) {
      return `<p class="crdoc-empty">${esc(emptyText)}</p>`;
    }
    return `
      <ul class="crdoc-list">
        ${normalized.map((item) => `
          <li class="crdoc-list-item">
            <strong>${esc(item.title)}</strong>
            ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            ${item.meta ? `<small>${esc(item.meta)}</small>` : ""}
            ${item.validate ? `<em>${esc(`可验证：${item.validate}`)}</em>` : ""}
          </li>
        `).join("")}
      </ul>
    `;
  }

  function renderCapabilityRadar(entries) {
    const normalized = Array.isArray(entries) ? entries.slice(0, 6) : [];
    if (!normalized.length) {
      return `<div class="crdoc-radar-empty">等待能力画像生成</div>`;
    }
    const center = 110;
    const radius = 74;
    const levels = [0.25, 0.5, 0.75, 1];
    const axisCount = normalized.length;
    const toPoint = (value, index, multiplier = 1) => {
      const angle = (-Math.PI / 2) + ((Math.PI * 2 * index) / axisCount);
      const currentRadius = radius * multiplier * value;
      return {
        x: center + Math.cos(angle) * currentRadius,
        y: center + Math.sin(angle) * currentRadius
      };
    };
    const polygon = normalized.map((entry, index) => {
      const point = toPoint(Math.max(0.12, entry.score / 100), index);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    }).join(" ");
    const gridPolygons = levels.map((level) => normalized.map((_, index) => {
      const point = toPoint(1, index, level);
      return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    }).join(" "));
    const axes = normalized.map((entry, index) => {
      const linePoint = toPoint(1, index);
      const labelPoint = toPoint(1, index, 1.18);
      const anchor = labelPoint.x < center - 18 ? "end" : labelPoint.x > center + 18 ? "start" : "middle";
      return `
        <g>
          <line x1="${center}" y1="${center}" x2="${linePoint.x.toFixed(1)}" y2="${linePoint.y.toFixed(1)}"></line>
          <text x="${labelPoint.x.toFixed(1)}" y="${labelPoint.y.toFixed(1)}" text-anchor="${anchor}">${esc(entry.label)}</text>
        </g>
      `;
    }).join("");
    return `
      <svg class="crdoc-radar-svg" viewBox="0 0 220 220" aria-hidden="true">
        <g class="crdoc-radar-grid">
          ${gridPolygons.map((points) => `<polygon points="${points}"></polygon>`).join("")}
          ${axes}
        </g>
        <polygon class="crdoc-radar-area" points="${polygon}"></polygon>
        ${normalized.map((entry, index) => {
          const point = toPoint(Math.max(0.12, entry.score / 100), index);
          return `<circle class="crdoc-radar-dot" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.6"></circle>`;
        }).join("")}
      </svg>
    `;
  }

  function bindReportDocNavigation(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const buttons = Array.from(root.querySelectorAll("[data-report-doc-nav-target]"));
    const sections = buttons
      .map((button) => {
        const targetId = String(button.dataset.reportDocNavTarget || "").trim();
        if (!targetId) return null;
        const target = root.querySelector(`#${targetId}`);
        return target ? { button, target, targetId } : null;
      })
      .filter(Boolean);
    if (!sections.length) return;

    const setActive = (targetId) => {
      buttons.forEach((button) => {
        const active = String(button.dataset.reportDocNavTarget || "").trim() === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    };

    sections.forEach(({ button, target, targetId }) => {
      button.addEventListener("click", () => {
        setActive(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    setActive(sections[0].targetId);
    if (typeof window.IntersectionObserver !== "function") return;

    const observer = new window.IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible?.target?.id) return;
      setActive(visible.target.id);
    }, {
      threshold: [0.25, 0.45, 0.65],
      rootMargin: "-18% 0px -52% 0px"
    });

    sections.forEach(({ target }) => observer.observe(target));
  }

  function renderReportDashboard(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 3) : [];
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? bundle?.match_output?.fit_score ?? 0)));
    const fitBandLabel = String(dashboardSummary.fit_band_label || "").trim()
      || ({"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(bundle?.match_output?.fit_band || "")] || "待评估");
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    const thisWeek = Array.isArray(nextActions.this_week) ? nextActions.this_week : [];
    const next30Days = nextActions.next_30_days || {};
    const marketHot = Array.isArray(marketSignals.hot_directions) ? marketSignals.hot_directions : [];
    const marketSkills = Array.isArray(marketSignals.skill_priorities) ? marketSignals.skill_priorities : [];
    const headlineBecause = Array.isArray(dashboardSummary.headline_because) ? dashboardSummary.headline_because : [];
    const confidenceSources = Array.isArray(dashboardSummary.confidence_sources) ? dashboardSummary.confidence_sources : [];
    const actionItems = Array.isArray(nextActions.action_items) ? nextActions.action_items : [];
    const priorityLogic = Array.isArray(nextActions.priority_logic) ? nextActions.priority_logic : [];
    const evidenceTrace = Array.isArray(evidenceHealth.evidence_trace) ? evidenceHealth.evidence_trace : [];
    const signalCards = Array.isArray(marketSignals.signal_cards) ? marketSignals.signal_cards : [];
    const headline = String(dashboardSummary.headline || meta.summary || reportDocument.executive_summary || "").trim() || `当前建议优先围绕 ${focusRole} 推进。`;
    const rationale = String(dashboardSummary.rationale || reportDocument.executive_summary || meta.summary || "").trim();

    const roleBars = roleRankings.length
      ? roleRankings.map((role) => {
          const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
          const fitSummary = String(role?.fit_summary || role?.summary || "").trim();
          const because = Array.isArray(role?.because) ? role.because : [];
          const requiredSkills = Array.isArray(role?.required_skills) ? role.required_skills.slice(0, 4) : [];
          return `
            <article class="ucrd-role-row">
              <div class="ucrd-role-row-head">
                <strong>${esc(role?.name || role?.title || "候选岗位")}</strong>
                <span>${score}%</span>
              </div>
              <div class="ucrd-role-bar"><i style="width:${score}%"></i></div>
              ${fitSummary ? `<p>${esc(fitSummary)}</p>` : ""}
              ${because.length ? `<div class="ucrd-role-because">${because.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
              ${requiredSkills.length ? `<div class="ucrd-role-tags">${requiredSkills.map((item) => `<span>${esc(item)}</span>`).join("")}</div>` : ""}
            </article>
          `;
        }).join("")
      : `<p class="ucrd-list-empty">候选岗位对比会在匹配结果生成后显示。</p>`;

    return `
      <div class="ucrd-dashboard">
        <section class="ucrd-hero">
          <div class="ucrd-hero-copy">
            <p class="ucrd-kicker">Decision Cockpit</p>
            <h2 class="ucrd-hero-title">${esc(headline)}</h2>
            <p class="ucrd-hero-summary">${formatText(rationale || `当前主线岗位是 ${focusRole}，建议先围绕差距补强和证据补齐再推进求职动作。`)}</p>
            ${headlineBecause.length ? `
              <div class="ucrd-hero-because">
                <span>因为</span>
                <ul>
                  ${headlineBecause.map((item) => `<li>${esc(item)}</li>`).join("")}
                </ul>
              </div>
            ` : ""}
            <div class="ucrd-hero-meta">
              <span>主岗位：${esc(focusRole)}</span>
              <span>匹配判断：${esc(fitBandLabel)}</span>
              <span>生成时间：${esc(meta.generated_at || "--")}</span>
              <span>版本：${esc(meta.version || "--")}</span>
            </div>
            ${confidenceSources.length ? `<div class="ucrd-source-strip">${confidenceSources.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
          </div>
          <div class="ucrd-hero-side">
            <div class="ucrd-score-pod">
              <strong>${fitScore}%</strong>
              <span>${esc(fitBandLabel)}</span>
            </div>
            <button type="button" class="career-report-primary-btn" data-user-center-report-view="report">查看完整报告</button>
          </div>
        </section>

        <section class="ucrd-section">
          <div class="ucrd-section-head">
            <div>
              <p class="ucrd-kicker">Role Comparison</p>
              <h3>候选岗位对比</h3>
            </div>
          </div>
          <div class="ucrd-role-grid">${roleBars}</div>
        </section>

        <div class="ucrd-grid">
          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Decision Logic</p>
                <h3>为什么推荐 / 为什么暂缓</h3>
              </div>
            </div>
            <div class="ucrd-decision-grid">
              ${decisionCards.map((card) => `
                <article class="ucrd-decision-card ${esc(card?.tone || "neutral")}">
                  <span class="ucrd-decision-label">${esc(card?.label || "判断")}</span>
                  <h4>${esc(card?.title || "待补充")}</h4>
                  <p>${esc(card?.summary || "")}</p>
                  ${Array.isArray(card?.items) && card.items.length ? `
                    <ul>
                      ${card.items.map((item) => `<li>${esc(getDashboardItemText(item))}</li>`).join("")}
                    </ul>
                  ` : ""}
                  ${renderReasonGroup("因为", card?.because)}
                  ${renderReasonGroup("依据", card?.evidence)}
                  ${renderReasonGroup("可验证动作", card?.validate)}
                </article>
              `).join("")}
            </div>
          </section>

          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Evidence Health</p>
                <h3>核心差距与证据健康</h3>
              </div>
            </div>
            <p class="ucrd-panel-summary">${esc(String(evidenceHealth.summary || "证据健康度将在报告完成后汇总。"))}</p>
            <div class="ucrd-list-grid">
              ${renderDashboardList("硬门槛缺口", evidenceHealth.hard_failures, "当前未发现明确硬门槛")}
              ${renderDashboardList("待补强技能", evidenceHealth.skill_gaps, "暂未识别到明确补强项")}
              ${renderDashboardList("简历证据缺失", evidenceHealth.evidence_gaps, "当前简历证据已覆盖核心判断")}
              ${renderDashboardList("缺失输入项", evidenceHealth.missing_inputs, "当前没有明显缺失输入")}
            </div>
            ${renderDashboardItemCluster("判断依据回指", evidenceTrace, "等待证据映射生成")}
          </section>
        </div>

        <div class="ucrd-grid">
          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Action Plan</p>
                <h3>下一阶段行动计划</h3>
              </div>
            </div>
            <div class="ucrd-action-grid">
              <article class="ucrd-action-card">
                <span>本周先做什么</span>
                ${thisWeek.length ? `<ul>${thisWeek.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p>等待短期计划生成。</p>`}
              </article>
              <article class="ucrd-action-card">
                <span>30 天目标</span>
                <strong>${esc(String(next30Days.title || "建立短期推进主线"))}</strong>
                ${Array.isArray(next30Days.tasks) && next30Days.tasks.length ? `<ul>${next30Days.tasks.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p>等待阶段任务同步。</p>`}
              </article>
              <article class="ucrd-action-card">
                <span>失败后的 B 计划</span>
                <p>${esc(String(nextActions.plan_b || "先保留次优岗位探索，同时继续补项目和证据。"))}</p>
                ${Array.isArray(nextActions.checkpoints) && nextActions.checkpoints.length ? `
                  <div class="ucrd-checkpoints">
                    ${nextActions.checkpoints.map((item) => `<small>${esc(item.label || "复查节点")} · ${esc(item.summary || "")}</small>`).join("")}
                  </div>
                ` : ""}
              </article>
            </div>
            ${priorityLogic.length ? `<div class="ucrd-source-strip">${priorityLogic.map((item) => `<small>${esc(item)}</small>`).join("")}</div>` : ""}
            ${renderDashboardItemCluster("行动建议为什么这样排", actionItems, "等待阶段动作生成")}
          </section>

          <section class="ucrd-panel">
            <div class="ucrd-section-head">
              <div>
                <p class="ucrd-kicker">Market Signals</p>
                <h3>行业信号与能力投资</h3>
              </div>
            </div>
            ${marketSignals.overview ? `<p class="ucrd-panel-summary">${esc(marketSignals.overview)}</p>` : ""}
            <div class="ucrd-list-grid">
              ${renderDashboardList("热门方向", marketHot, "等待行业热点判断")}
              ${renderDashboardList("能力优先级", marketSkills, "等待能力投资建议")}
              ${renderDashboardList("风险信号", marketSignals.risk_signals, "当前未识别明显风险")}
              ${renderDashboardList("验证动作", marketSignals.verification_actions, "等待验证动作建议")}
            </div>
            ${renderDashboardItemCluster("趋势判断依据", signalCards, "等待趋势依据生成")}
          </section>
        </div>

        <div class="ucrd-feedback">
          ${renderReportFeedbackCard()}
        </div>
      </div>
    `;
  }

  function renderReportDashboardV2(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const next30Days = nextActions.next_30_days || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const industryStory = reportDocument.industry_story || {};
    const roleCards = Array.isArray(reportDocument.role_cards) ? reportDocument.role_cards : [];
    const planBoard = reportDocument.plan_board || {};
    const explainabilitySummary = reportDocument.explainability_summary || {};
    const competencyProfile = bundle?.competency_profile || {};
    const matchOutput = bundle?.match_output || {};
    const pathPlan = bundle?.path_plan || {};
    const explainabilityOverview = reportDocument.explainability_overview || {};
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "待识别";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? matchOutput.fit_score ?? 0)));
    const fitBandLabel = String(dashboardSummary.fit_band_label || "").trim()
      || ({"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[String(matchOutput.fit_band || "")] || "待评估");
    const dimensions = normalizeReportDimensions(competencyProfile.dimensions);
    const headline = String(dashboardSummary.headline || meta.summary || reportDocument.executive_summary || "").trim() || `当前建议优先围绕 ${focusRole} 推进。`;
    const rationale = String(dashboardSummary.rationale || reportDocument.executive_summary || meta.summary || "").trim()
      || `先围绕 ${focusRole} 解决硬门槛和证据缺口，再推进求职动作。`;
    const headlineBecause = Array.isArray(dashboardSummary.headline_because) ? dashboardSummary.headline_because : (Array.isArray(explainabilitySummary.headline_because) ? explainabilitySummary.headline_because : []);
    const strengths = collectUniqueExplainItems(evidenceHealth.strengths, competencyProfile.strengths);
    const gaps = collectUniqueExplainItems(
      evidenceHealth.hard_failures,
      evidenceHealth.skill_gaps,
      evidenceHealth.evidence_gaps,
      evidenceHealth.missing_inputs,
      matchOutput.partial_gaps
    );
    const roles = (roleCards.length
      ? roleCards.map((item) => ({
          name: item?.role_name || "",
          overall_score: item?.fit_score || 0,
          fit_summary: item?.fit_summary || "",
          required_skills: Array.isArray(item?.required_skills) ? item.required_skills : [],
          because: Array.isArray(item?.why_fit) ? item.why_fit : [],
          hard_gaps: Array.isArray(item?.hard_gaps) ? item.hard_gaps : [],
          partial_gaps: Array.isArray(item?.partial_gaps) ? item.partial_gaps : [],
          switch_path: item?.switch_path || "",
          promotion_path: item?.promotion_path || ""
        }))
      : (Array.isArray(bundle?.role_rankings) ? [...bundle.role_rankings] : []))
      .sort((left, right) => {
        const leftName = String(left?.name || left?.title || "").trim();
        const rightName = String(right?.name || right?.title || "").trim();
        const leftFocus = leftName && focusRole && leftName.includes(focusRole);
        const rightFocus = rightName && focusRole && rightName.includes(focusRole);
        if (leftFocus && !rightFocus) return -1;
        if (!leftFocus && rightFocus) return 1;
        return Number(right?.overall_score || 0) - Number(left?.overall_score || 0);
      })
      .slice(0, 3);
    const signals = (Array.isArray(marketSignals.signal_cards) && marketSignals.signal_cards.length
      ? marketSignals.signal_cards
      : Array.isArray(industryStory.highlight_items) && industryStory.highlight_items.length
        ? industryStory.highlight_items.map((item) => ({
            title: item?.title || "",
            summary: item?.summary || "",
            source_type: item?.source || "",
            time_horizon: item?.published_label || "",
            validation_action: item?.topic || ""
          }))
        : collectUniqueExplainItems(marketSignals.hot_directions)).slice(0, 3);
    const milestones = Array.isArray(pathPlan.milestones) ? pathPlan.milestones : [];
    const actionItems = Array.isArray(planBoard.action_items) && planBoard.action_items.length ? planBoard.action_items.slice(0, 4) : (Array.isArray(nextActions.action_items) ? nextActions.action_items.slice(0, 4) : []);
    const planHorizons = Array.isArray(planBoard.horizons) ? planBoard.horizons : [];
    const shortPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "short_term")?.items)
      ? planHorizons.find((item) => item?.key === "short_term").items
      : (Array.isArray(nextActions.this_week) ? nextActions.this_week.map((item) => ({ title: item })) : []);
    const mediumPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "mid_term")?.items)
      ? planHorizons.find((item) => item?.key === "mid_term").items
      : (Array.isArray(next30Days.tasks) ? next30Days.tasks.map((item) => ({ title: item })) : []);
    const longPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "long_term")?.items)
      ? planHorizons.find((item) => item?.key === "long_term").items
      : (Array.isArray(nextActions.checkpoints) ? nextActions.checkpoints : []);
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    const sectionHead = (index, kicker, title, copy) => `
      <div class="crdoc-section-head">
        <span class="crdoc-section-index">${esc(index)}</span>
        <div>
          <p class="crdoc-section-kicker">${esc(kicker)}</p>
          <h3>${esc(title)}</h3>
          ${copy ? `<p>${esc(copy)}</p>` : ""}
        </div>
      </div>
    `;

    const dimensionRows = dimensions.length
      ? dimensions.map((entry) => `
          <article class="crdoc-dimension-row">
            <div class="crdoc-dimension-head">
              <strong>${esc(entry.label)}</strong>
              <span class="crdoc-level-pill ${esc(entry.level)}">${esc(entry.levelLabel)}</span>
            </div>
            <div class="crdoc-progress"><i style="width:${entry.score}%"></i></div>
            ${entry.reason ? `<p>${esc(entry.reason)}</p>` : ""}
          </article>
        `).join("")
      : `<p class="crdoc-empty">等待能力维度生成。</p>`;

    return `
      <div class="crdoc-page">
        <section class="crdoc-hero">
          <div class="crdoc-hero-copy">
            <p class="crdoc-kicker">Career Report</p>
            <h2>${esc(meta.title || "职业发展报告")}</h2>
            <p class="crdoc-hero-summary">${esc(headline)}</p>
            <p class="crdoc-hero-body">${esc(rationale)}</p>
            ${headlineBecause.length ? `<div class="crdoc-why-block"><span>为什么会得出这个结论</span>${renderReportDocList(headlineBecause.map((item) => ({ title: item })), "等待结论依据", 4)}</div>` : ""}
            ${renderReportDocChips(dashboardSummary.confidence_sources)}
          </div>
          <aside class="crdoc-hero-aside">
            <div class="crdoc-stat-card"><span>当前主岗位</span><strong>${esc(focusRole)}</strong></div>
            <div class="crdoc-stat-card"><span>匹配判断</span><strong>${esc(`${fitScore}%`)}</strong><small>${esc(fitBandLabel)}</small></div>
            <div class="crdoc-stat-card"><span>生成时间</span><strong>${esc(meta.generated_at || "--")}</strong><small>版本 ${esc(meta.version || "--")}</small></div>
            <button type="button" class="career-report-primary-btn crdoc-hero-cta" data-user-center-report-view="report">查看完整报告</button>
          </aside>
        </section>

        <nav class="crdoc-nav" aria-label="报告段落导航">
          <button type="button" class="crdoc-nav-btn active" data-report-doc-nav-target="reportDocSection-position" aria-pressed="true">① 当前定位</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-trends" aria-pressed="false">② 行业趋势</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-targets" aria-pressed="false">③ 目标岗位对比</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-path" aria-pressed="false">④ 职业路径图</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-plan" aria-pressed="false">⑤ 提升计划</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-summary" aria-pressed="false">⑥ 关键判断</button>
        </nav>

        <section id="reportDocSection-position" class="crdoc-section">
          ${sectionHead("01", "Current Position", "你现在的定位", "判断、原因、证据回指放在同一屏里。")}
          <div class="crdoc-position-grid">
            <article class="crdoc-card">
              <div class="crdoc-card-topline"><span class="crdoc-card-label">当前判断</span><span class="crdoc-card-meta">${esc(focusRole)}</span></div>
              <h4>${esc(headline)}</h4>
              <p>${esc(rationale)}</p>
              <div class="crdoc-two-col">
                <div class="crdoc-mini-card"><span>已证实的优势</span>${renderReportDocList(strengths, "当前更像是证据不足，不建议把未验证优势当结论。", 4)}</div>
                <div class="crdoc-mini-card"><span>优先补强项</span>${renderReportDocList(gaps, "当前没有额外缺口提示。", 4)}</div>
              </div>
            </article>
            <article class="crdoc-card">
              <div class="crdoc-card-topline"><span class="crdoc-card-label">能力画像</span><span class="crdoc-card-meta">每个维度都附判断理由</span></div>
              <div class="crdoc-radar-wrap">${renderCapabilityRadar(dimensions)}<div class="crdoc-dimension-list">${dimensionRows}</div></div>
            </article>
          </div>
          <article class="crdoc-card">
            <div class="crdoc-card-topline"><span class="crdoc-card-label">判断依据回指</span></div>
            ${renderReportDocList(evidenceHealth.evidence_trace, "当前这份报告的主要限制是输入证据还不够完整。", 4)}
          </article>
        </section>

        <section id="reportDocSection-trends" class="crdoc-section">
          ${sectionHead("02", "Industry Trends", "行业趋势（与你相关）", "把趋势结论、来源类型、时效性和验证动作放在一起。")}
          ${industryStory.narrative ? `
            <article class="crdoc-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">行业现状</span>
                <span class="crdoc-card-meta">${esc(industryStory.snapshot_label || "近期行业动态")}</span>
              </div>
              <h4>${esc(industryStory.refresh_rule || "行业快报")}</h4>
              <p>${esc(industryStory.narrative)}</p>
            </article>
          ` : ""}
          <div class="crdoc-trend-grid">
            ${signals.length ? signals.map((item, index) => {
              const normalized = normalizeExplainItem(item) || { title: getDashboardItemText(item), detail: "", validate: "" };
              const raw = typeof item === "object" && item ? item : {};
              return `
                <article class="crdoc-trend-card">
                  <div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(index === 0 ? "优先关注" : index === 1 ? "重点观察" : "持续跟进")}</span><span class="crdoc-card-meta">${esc(String(raw.time_horizon || "趋势观察"))}</span></div>
                  <h4>${esc(normalized.title)}</h4>
                  ${(raw.summary || raw.why_important || normalized.detail) ? `<p>${esc(raw.summary || raw.why_important || normalized.detail || "")}</p>` : ""}
                  <div class="crdoc-fact-row"><span>来源</span><strong>${esc(String(raw.source_type || "综合判断"))}</strong></div>
                  ${(normalized.validate || raw.validation_action) ? `<div class="crdoc-meaning-box"><span>你可以怎么验证</span><p>${esc(normalized.validate || raw.validation_action || "")}</p></div>` : ""}
                </article>
              `;
            }).join("") : `<article class="crdoc-card"><p class="crdoc-empty">等待行业趋势生成。</p></article>`}
          </div>
          <div class="crdoc-two-col">
            <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">能力投资优先级</span></div>${renderReportDocList(marketSignals.skill_priorities, "等待能力投资建议。", 4)}</article>
            <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">风险与验证</span></div>${renderReportDocList(marketSignals.risk_signals, "当前未识别明确风险。", 3)}${renderReportDocList(marketSignals.verification_actions, "等待验证动作。", 3)}</article>
          </div>
        </section>

        <section id="reportDocSection-targets" class="crdoc-section">
          ${sectionHead("03", "Target Roles", "目标岗位对比", "不只给总分，还拆成为什么进入候选和还差什么。")}
          <div class="crdoc-target-grid-main">
            ${roles.length ? roles.map((role, index) => {
              const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
              return `
                <article class="crdoc-target-card ${esc(getReportFitTone(index === 0 ? matchOutput.fit_band : "", score).tone)}">
                  <div class="crdoc-target-head"><div><h4>${esc(role?.name || role?.title || "候选岗位")}</h4><span>${esc(index === 0 ? "当前主线" : `候选方向 ${index + 1}`)}</span></div><div class="crdoc-target-score"><strong>${score}</strong><small>分</small></div></div>
                  <div class="crdoc-target-bar"><i style="width:${score}%"></i></div>
                  ${role?.fit_summary ? `<p class="crdoc-target-summary">${esc(role.fit_summary)}</p>` : ""}
                  ${Array.isArray(role?.required_skills) && role.required_skills.length ? `<div class="crdoc-chip-row">${role.required_skills.slice(0, 4).map((skill) => `<span class="crdoc-chip crdoc-chip--blue">${esc(skill)}</span>`).join("")}</div>` : ""}
                  <div class="crdoc-two-col">
                    <div class="crdoc-mini-card"><span>${esc(index === 0 ? "为什么推荐" : "为什么会进入候选")}</span>${renderReportDocList(index === 0 ? collectUniqueExplainItems(matchOutput.why_match, role?.because) : role?.because, "当前还缺少明确支持项", 3)}</div>
                    <div class="crdoc-mini-card"><span>${esc(index === 0 ? "还差什么" : "关键要求")}</span>${renderReportDocList(index === 0 ? collectUniqueExplainItems(role?.partial_gaps, role?.hard_gaps, matchOutput.partial_gaps, matchOutput.hard_failures) : collectUniqueExplainItems(role?.hard_gaps, role?.partial_gaps, Array.isArray(role?.required_skills) ? role.required_skills.map((skill) => ({ title: skill, detail: "该岗位的高频硬要求" })) : []), "当前没有额外门槛提示", 3)}</div>
                  </div>
                </article>
              `;
            }).join("") : `<article class="crdoc-card"><p class="crdoc-empty">等待岗位匹配结果生成。</p></article>`}
          </div>
        </section>

        <section id="reportDocSection-path" class="crdoc-section">
          ${sectionHead("04", "Career Path", "职业路径图", "让用户看到推荐这条路的前提条件、里程碑和风险。")}
          <div class="crdoc-path-grid">
            <div class="crdoc-timeline">
              <article class="crdoc-timeline-card done"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><div class="crdoc-card-topline"><span class="crdoc-card-label">当前判断</span><span class="crdoc-card-meta">${esc(meta.generated_at || "--")}</span></div><h4>${esc(focusRole)}</h4><p>${esc(rationale)}</p></div></article>
              ${milestones.length ? milestones.map((item, index) => `<article class="crdoc-timeline-card ${index === 0 ? "current" : ""}"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(index === 0 ? "下一步" : index === 1 ? "中期" : "长期")}</span><span class="crdoc-card-meta">${esc(String(item?.horizon || "--"))}</span></div><h4>${esc(String(item?.title || "阶段目标"))}</h4>${item?.reason ? `<p>${esc(item.reason)}</p>` : ""}${renderReportDocList((Array.isArray(item?.actions) ? item.actions : []).map((action) => ({ title: action, detail: item?.priority_reason || item?.linked_gap || "" })), "等待阶段动作", 4)}</div></article>`).join("") : `<article class="crdoc-timeline-card"><div class="crdoc-timeline-dot"></div><div class="crdoc-timeline-body"><p class="crdoc-empty">等待路径规划生成。</p></div></article>`}
            </div>
            <div class="crdoc-stack">
              <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">路径推荐理由</span></div>${renderReportDocList(pathPlan.path_rationale, "等待路径解释。", 4)}</article>
              <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">前提条件与风险</span></div>${renderReportDocList(pathPlan.dependencies?.must_resolve_hard_failures, "当前未标出必须先解决的硬门槛。", 3)}${renderReportDocList(pathPlan.path_risks, "当前未标出显性路径风险。", 3)}${renderReportDocList(pathPlan.contingency, "当前没有 B 计划提示。", 3)}</article>
            </div>
          </div>
        </section>

        <section id="reportDocSection-plan" class="crdoc-section">
          ${sectionHead("05", "Action Plan", "提升计划", "每条建议都要说明它对应哪个判断，以及为什么排在前面。")}
          <div class="crdoc-plan-grid">
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">短期（0-30 天）</span><span class="crdoc-card-meta">先补硬门槛</span></div>${renderReportDocList(shortPlanActions, "等待短期动作。", 4)}${Array.isArray(nextActions.priority_logic) && nextActions.priority_logic.length ? `<div class="crdoc-meaning-box"><span>为什么先做这些</span><p>${esc(nextActions.priority_logic[0])}</p></div>` : ""}</article>
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">中期（1-6 个月）</span><span class="crdoc-card-meta">${esc(String(milestones[1]?.horizon || "能力沉淀"))}</span></div>${renderReportDocList(mediumPlanActions, "等待中期动作。", 4)}</article>
            <article class="crdoc-plan-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">长期（6-12 个月）</span><span class="crdoc-card-meta">${esc(String(milestones[2]?.horizon || "形成路径闭环"))}</span></div>${renderReportDocList(longPlanActions, "等待长期动作。", 4)}${nextActions.plan_b ? `<div class="crdoc-meaning-box"><span>如果主线受阻</span><p>${esc(String(nextActions.plan_b))}</p></div>` : ""}</article>
          </div>
          <article class="crdoc-card"><div class="crdoc-card-topline"><span class="crdoc-card-label">行动建议与闭环说明</span></div><div class="crdoc-action-detail-grid">${actionItems.length ? actionItems.map((item) => `<article class="crdoc-mini-card"><span>${esc(String(item?.window || "行动建议"))}</span><h4>${esc(String(item?.title || "待补充"))}</h4>${item?.reason ? `<p>${esc(item.reason)}</p>` : ""}${item?.linked_judgement ? `<small>${esc(`对应判断：${item.linked_judgement}`)}</small>` : ""}${item?.priority_reason ? `<em>${esc(`优先级原因：${item.priority_reason}`)}</em>` : ""}</article>`).join("") : `<p class="crdoc-empty">等待行动建议生成。</p>`}</div></article>
        </section>

        <section id="reportDocSection-summary" class="crdoc-section">
          ${sectionHead("06", "Key Judgements", "关键判断", "把“是什么”后面的“为什么”直接写出来，帮助用户建立信任。")}
          <div class="crdoc-insight-grid">
            <article class="crdoc-insight-card breakthrough"><div class="crdoc-card-topline"><span class="crdoc-card-label">最快突破口</span></div><p class="crdoc-insight-summary">${esc(String(decisionCards.find((card) => card?.tone === "positive")?.title || actionItems[0]?.title || "先把最影响投递通过率的硬门槛补齐。"))}</p>${renderReportDocList((decisionCards.find((card) => card?.tone === "positive")?.because || [actionItems[0]?.priority_reason || actionItems[0]?.reason || "优先解决最影响投递反馈的问题。"]).map((item) => ({ title: item })), "等待原因说明", 3)}</article>
            <article class="crdoc-insight-card risk"><div class="crdoc-card-topline"><span class="crdoc-card-label">最需要警惕的风险</span></div><p class="crdoc-insight-summary">${esc(String(decisionCards.find((card) => card?.tone === "risk")?.title || explainabilityOverview.match?.judgement || "不要在证据不足时直接相信岗位匹配结论。"))}</p>${renderReportDocList((decisionCards.find((card) => card?.tone === "risk")?.because || explainabilityOverview.match?.because || []).map((item) => ({ title: item })), "等待原因说明", 3)}</article>
            <article class="crdoc-insight-card strength"><div class="crdoc-card-topline"><span class="crdoc-card-label">${esc(strengths.length ? "当前已能保留的优势" : "当前最值得保留的基础")}</span></div><p class="crdoc-insight-summary">${esc(strengths[0]?.title || decisionCards.find((card) => card?.tone === "neutral")?.title || explainabilityOverview.positioning?.judgement || "当前最有价值的不是盲目扩岗位，而是保持主线聚焦。")}</p>${renderReportDocList((strengths.length ? [strengths[0]] : (decisionCards.find((card) => card?.tone === "neutral")?.because || explainabilityOverview.positioning?.because || []).map((item) => ({ title: item }))), "等待原因说明", 3)}</article>
          </div>
          <div class="crdoc-feedback-wrap">${renderReportFeedbackCard()}</div>
        </section>
      </div>
    `;
  }

  function renderEmptyReportMain() {
    const focusRole = window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "先锁定目标岗位";
    const completion = Number(window.appState?.profileCompletion || 0);
    return `
      <div class="career-report-empty-grid">
        <article class="career-report-empty-card">
          <strong>先补齐画像，再生成职业报告</strong>
          <p>完成测评、简历和访谈后，即可生成职业报告。</p>
        </article>
        <article class="career-report-empty-card">
          <strong>当前主线</strong>
          <p>候选主岗位：${esc(focusRole)}</p>
        </article>
        <article class="career-report-empty-card">
          <strong>画像完成度</strong>
          <p>当前完成度约 ${Math.max(0, Math.min(100, Math.round(completion)))}%。</p>
        </article>
      </div>
    `;
  }

  function renderStatusBanner() {
    const host = document.getElementById("careerReportStatusBanner");
    if (!host) return;

    const state = getCareerReportStateSafe();
    const bundle = window.appState?.careerReport || null;
    const historical = Boolean(window.appState?.careerReportViewingHistorical);
    const status = String(state?.status || "").trim().toLowerCase();

    if (status === "waiting_input") {
      host.innerHTML = `<div class="career-report-banner-main"><div>
        <h3 class="career-report-banner-title">等待补充与确认</h3>
        <p class="career-report-banner-copy">职业决策已保存，请返回生成台确认目标与可投入时间。</p>
        <a href="/#report" class="career-report-secondary-btn">继续生成报告</a>
      </div></div>`;
      return;
    }

    if (status === "queued" || status === "running") {
      host.innerHTML = `
        <div class="career-report-banner-main running">
          <div>
            <h3 class="career-report-banner-title">职业报告正在生成</h3>
            <p class="career-report-banner-copy">${formatText(state?.stage_detail || state?.summary || "后台正在按阶段生成职业报告，请稍候。")}</p>
          </div>
          <div class="career-report-banner-meta">
            <span>阶段：${esc(state?.stage_label || "编排中")}</span>
            <span>主岗位：${esc(bundle?.report_document?.focus_role_name || bundle?.meta?.focus_role_name || state?.focus_role_id || "待识别")}</span>
          </div>
        </div>
      `;
      return;
    }

    if (status === "failed") {
      host.innerHTML = `
        <div class="career-report-banner-main failed">
          <div>
            <h3 class="career-report-banner-title">职业报告生成失败</h3>
            <p class="career-report-banner-copy">${formatText(state?.error_message || "请检查画像输入和模型配置后重试。")}</p>
          </div>
        </div>
      `;
      return;
    }

    if (historical) {
      host.innerHTML = `
        <div class="career-report-banner-main">
          <div>
            <h3 class="career-report-banner-title">当前正在查看历史版本</h3>
            <p class="career-report-banner-copy">历史版本为只读，无法修改计划或进度。</p>
          </div>
          <div class="career-report-banner-meta">
            <span>版本：${esc(bundle?.meta?.version || "--")}</span>
            <span>时间：${esc(bundle?.meta?.generated_at || "--")}</span>
          </div>
        </div>
      `;
      return;
    }

    host.innerHTML = "";
  }

  function renderReportFeedbackCard() {
    const feedback = getCareerReportFeedback();
    const selectedVerdict = reportRuntime.feedbackVerdict || feedback?.latest_verdict || "partial";
    const noteValue = reportRuntime.feedbackNote || "";
    const summary = String(
      feedback?.summary
      || "反馈本版报告的准确性，帮助改进后续建议。"
    ).trim();
    const latestMeta = feedback?.count
      ? `最近一次：${getFeedbackVerdictLabel(feedback?.latest_verdict)}${feedback?.last_updated ? ` · ${feedback.last_updated}` : ""}`
      : "还没有记录过纠偏反馈。";

    return `
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Feedback Loop</p>
        <h3 class="career-report-side-title">纠偏反馈</h3>
        <p class="career-report-side-copy">${formatText(summary)}</p>
        <div class="career-report-feedback-actions" data-report-feedback-root="1">
          ${[
            ["accurate", "基本准确"],
            ["partial", "部分准确"],
            ["off_target", "明显偏差"]
          ].map(([value, label]) => `
            <button
              type="button"
              class="career-report-feedback-pill${selectedVerdict === value ? " active" : ""}"
              data-report-feedback-verdict="${esc(value)}"
            >${esc(label)}</button>
          `).join("")}
        </div>
        <textarea
          class="career-report-feedback-input"
          data-report-feedback-note="1"
          rows="4"
          placeholder="补充哪里不准、漏了什么，或者哪些判断值得保留。"
        >${esc(noteValue)}</textarea>
        <div class="career-report-feedback-foot">
          <span class="career-report-feedback-meta">${esc(latestMeta)}</span>
          <button type="button" class="career-report-primary-btn career-report-feedback-submit" data-report-feedback-submit="1">保存反馈</button>
        </div>
      </section>
    `;
  }

  async function submitCareerReportFeedback(verdict, note) {
    const bundle = window.appState?.careerReport || null;
    const payload = await requestJsonSafe("/api/career-report/feedback", {
      method: "POST",
      body: {
        verdict,
        note,
        report_id: bundle?.meta?.report_id || "",
        focus_role_id: bundle?.meta?.focus_role_id || "",
        focus_role_name: bundle?.report_document?.focus_role_name || ""
      }
    });
    reportRuntime.feedbackVerdict = payload?.feedback?.latest_verdict || verdict;
    reportRuntime.feedbackNote = "";
    applyCareerReportState(undefined, getCareerReportTracker(), payload.state || getCareerReportStateSafe(), {
      keepBundle: true,
      historical: Boolean(window.appState?.careerReportViewingHistorical),
      userCenterRefresh: true
    });
    return payload;
  }

  function bindCareerReportFeedbackHandlers(root) {
    if (!root || typeof root.querySelector !== "function") return;
    const feedbackNoteInput = root.querySelector("[data-report-feedback-note]");
    if (feedbackNoteInput) {
      feedbackNoteInput.addEventListener("input", () => {
        reportRuntime.feedbackNote = feedbackNoteInput.value || "";
      });
    }
    root.querySelectorAll("[data-report-feedback-verdict]").forEach((button) => {
      button.addEventListener("click", () => {
        reportRuntime.feedbackVerdict = String(button.dataset.reportFeedbackVerdict || "partial").trim() || "partial";
        root.querySelectorAll("[data-report-feedback-verdict]").forEach((item) => {
          item.classList.toggle("active", item === button);
        });
      });
    });
    const feedbackSubmitButton = root.querySelector("[data-report-feedback-submit]");
    if (feedbackSubmitButton) {
      feedbackSubmitButton.addEventListener("click", async () => {
        const verdict = reportRuntime.feedbackVerdict || getCareerReportFeedback()?.latest_verdict || "partial";
        const note = String(feedbackNoteInput?.value || reportRuntime.feedbackNote || "").trim();
        try {
          await submitCareerReportFeedback(verdict, note);
          if (feedbackNoteInput) feedbackNoteInput.value = "";
          toast("反馈已记录", "下一次生成职业报告时会优先吸收这条纠偏信息。", "success", 2200);
        } catch (error) {
          toast("反馈保存失败", error.message || "请稍后重试。", "error", 2200);
        }
      });
    }
  }

  async function polishCareerReportSection(sectionKey, targetId, button) {
    const key = String(sectionKey || "").trim();
    const targetIdText = String(targetId || "").trim();
    const targetSelector = targetIdText ? `#${escapeSelectorId(targetIdText)}` : "";
    const target = (targetSelector ? button?.closest(".cr4-module")?.querySelector(targetSelector) : null)
      || document.getElementById(targetIdText);
    const section = window.appState?.careerReport?.report_document?.sections?.[key] || null;
    const text = String(section?.markdown || "").trim();
    if (!key || !text) {
      toast("暂无可润色内容", "该模块还没有完整正文。", "warning", 1800);
      return;
    }
    const originalText = button?.textContent || "";
    if (button) {
      button.disabled = true;
      button.textContent = "润色中";
    }
    try {
      const payload = await requestJsonSafe("/api/career-report/polish", {
        method: "POST",
        body: {
          section_key: key,
          text
        }
      });
      if (target) {
        target.classList.remove("hidden");
        target.innerHTML = `
          <div class="cr4-polish-output-head">
            <strong>润色版本</strong>
            <span>只优化表达，不新增事实</span>
          </div>
          <div class="cr4-polish-output-body">${renderMarkdownBasic(payload.polished || "")}</div>
        `;
      }
      toast("润色完成", "已生成该模块的润色版本。", "success", 1800);
    } catch (error) {
      toast("润色失败", error.message || "请检查模型配置后重试。", "error", 2200);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = originalText || "润色本段";
      }
    }
  }

  function bindReportPolishHandlers(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-report-polish-section]").forEach((button) => {
      button.addEventListener("click", () => {
        void polishCareerReportSection(
          button.dataset.reportPolishSection || "",
          button.dataset.reportPolishTarget || "",
          button
        );
      });
    });
  }

  function bindReportScrollHandlers(root, container) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    root.querySelectorAll("[data-report-scroll-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = String(button.dataset.reportScrollTarget || "").trim();
        if (!targetId) return;
        const target = container?.querySelector?.(`#${escapeSelectorId(targetId)}`) || document.getElementById(targetId);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  // section definitions for nav
  const SECTION_NAV = [
    { key: "executive_summary",    label: "执行摘要",           icon: "01", anchor: "cr-sec-exec" },
    { key: "macro_environment",    label: "宏观就业环境",       icon: "02", anchor: "cr-sec-industry" },
    { key: "personal_traits",      label: "个人特质与潜力",     icon: "03", anchor: "cr-sec-traits" },
    { key: "target_job_analysis",  label: "目标企业与岗位分析", icon: "04", anchor: "cr-sec-target" },
    { key: "matching_decision",    label: "人岗匹配与决策建议", icon: "05", anchor: "cr-sec-match" },
    { key: "ability_gaps",         label: "职业能力差距", icon: "06", anchor: "cr-sec-ability-gaps" },
    { key: "development_path",     label: "职业发展与成长路径", icon: "07", anchor: "cr-sec-development" },
    { key: "gap_action_plan",      label: "差距分析与行动计划", icon: "06", anchor: "cr-sec-gap" },
    { key: "risk_backup",          label: "风险管理与备选方案", icon: "07", anchor: "cr-sec-risk" },
    { key: "appendix",             label: "附录",               icon: "08", anchor: "cr-sec-appendix" },
  ];

  const REPORT_WORKSPACE_GROUPS = {
    trends: {
      label: "\u884c\u4e1a\u8d8b\u52bf",
      title: "\u884c\u4e1a\u5224\u65ad\u4e0e\u5f53\u524d\u804c\u4e1a\u5b9a\u4f4d",
      summary: "\u5148\u770b\u884c\u4e1a\u666f\u6c14\u5ea6\u3001\u5c97\u4f4d\u9700\u6c42\u53d8\u5316\u548c\u4f60\u5f53\u524d\u9002\u5408\u7684\u5207\u5165\u65b9\u5411\uff0c\u907f\u514d\u76f4\u63a5\u628a\u62a5\u544a\u53d8\u6210\u4e00\u6574\u9875\u5806\u5b57\u3002",
      sectionKeys: ["executive_summary", "macro_environment", "personal_traits"]
    },
    matching: {
      label: "\u5c97\u4f4d\u5339\u914d",
      title: "\u8bc1\u636e\u3001\u80fd\u529b\u4e0e\u76ee\u6807\u5c97\u4f4d\u7684\u5339\u914d\u5224\u65ad",
      summary: "\u628a\u7b80\u5386\u8bc1\u636e\u3001\u80fd\u529b\u753b\u50cf\u548c\u76ee\u6807\u5c97\u4f4d\u8981\u6c42\u62c6\u5f00\u5bf9\u7167\uff0c\u6e05\u6670\u770b\u5230\u5f53\u524d\u5dee\u8ddd\u3001\u4f18\u52bf\u4e0e\u9700\u8981\u8865\u8bc1\u7684\u70b9\u3002",
      sectionKeys: ["target_job_analysis", "matching_decision"]
    },
    plan: {
      label: "\u89c4\u5212\u8def\u5f84",
      title: "\u5206\u9636\u6bb5\u8865\u9f50\u80fd\u529b\u5e76\u5f62\u6210\u6267\u884c\u8def\u7ebf",
      summary: "\u628a\u957f\u671f\u76ee\u6807\u62c6\u6210\u8fd1\u671f\u52a8\u4f5c\u3001\u9636\u6bb5\u76ee\u6807\u548c\u91cc\u7a0b\u7891\uff0c\u4fbf\u4e8e\u540e\u7eed\u7ee7\u7eed\u7f16\u8f91\u3001\u68c0\u67e5\u548c\u5bfc\u51fa\u3002",
      sectionKeys: ["ability_gaps", "development_path", "gap_action_plan", "risk_backup", "appendix"]
    }
  };
  window.CAREER_REPORT_WORKSPACE_GROUPS = REPORT_WORKSPACE_GROUPS;

  function isModularBundle(bundle) {
    const sections = bundle?.report_document?.sections;
    return sections && !Array.isArray(sections) && typeof sections === "object";
  }

  function getReportTocItems(bundle) {
    const markdown = String(bundle?.report_document?.markdown || "").trim();
    if (markdown) {
      return [{
        id: "cr-full-markdown-anchor",
        title: "完整 Markdown 报告",
        kicker: "01",
        index: 0
      }];
    }
    const sections = bundle?.report_document?.sections;
    if (sections && !Array.isArray(sections) && typeof sections === "object") {
      return SECTION_NAV
        .filter((item) => Boolean(sections[item.key]))
        .map((item, index) => ({
          id: item.anchor,
          title: item.label,
          kicker: item.icon,
          index
        }));
    }
    const legacySections = Array.isArray(sections) ? sections : [];
    return legacySections.map((section, index) => ({
      id: getReportSectionDomId(section, index),
      title: section.title || section.kicker || `章节 ${index + 1}`,
      kicker: section.kicker || "",
      index
    }));
  }

  function renderReportAside() {
    const aside = document.getElementById("careerReportAside");
    if (!aside) return;

    const state = getCareerReportStateSafe();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";
    const viewMode = getUserCenterReportViewModeSafe();
    if (generating || viewMode !== "report") {
      aside.innerHTML = "";
      aside.classList.add("career-report-aside--hidden");
      return;
    }
    aside.classList.remove("career-report-aside--hidden");

    const bundle = window.appState?.careerReport || null;
    if (!bundle?.report_document) {
      aside.innerHTML = "";
      return;
    }
    const tracker = getCareerReportTracker();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const roleRankings = Array.isArray(bundle?.role_rankings) ? bundle.role_rankings.slice(0, 5) : [];
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || window.jobNameMap?.[window.appState?.focusedRoleId] || window.appState?.focusedRoleId || "待识别";
    const isModular = isModularBundle(bundle);
    const markdownReady = Boolean(String(bundle?.report_document?.markdown || "").trim())
      || Boolean(stitchModularMarkdownFromBundle(bundle));
    const matchOutput = bundle?.match_output || {};
    const fitScore = Number(matchOutput.fit_score || bundle?.role_rankings?.[0]?.overall_score || 0);
    const fitBand = String(matchOutput.fit_band || "");
    const fitBandLabel = {"strong": "强匹配", "moderate": "中等匹配", "weak": "弱匹配", "not_ready": "尚需准备"}[fitBand] || "--";

    const readingMdForToc = markdownReady ? getCareerReportReadingMarkdown(bundle) : "";
    const tocBranches = readingMdForToc ? buildMarkdownTocBranches(readingMdForToc) : [];
    const tocNavHtml = tocBranches.length ? renderMarkdownTocNavHtml(tocBranches, { variant: "aside" }) : "";

    const moduleNavHtml = isModular && !markdownReady ? `
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Contents</p>
        <h3 class="career-report-side-title">章节目录</h3>
        <nav class="cr4-module-nav">
          ${SECTION_NAV.map((sec) => {
            const hasData = Boolean(bundle?.report_document?.sections?.[sec.key]?.markdown);
            return `
              <button type="button" class="cr4-module-nav-btn${hasData ? "" : " muted"}"
                data-report-scroll-target="${sec.anchor}">
                <span class="cr4-module-nav-icon">${sec.icon}</span>
                <span>${esc(sec.label)}</span>
                ${hasData ? "" : '<span class="cr4-module-nav-empty">待生成</span>'}
              </button>
            `;
          }).join("")}
        </nav>
      </section>
    ` : "";

    aside.innerHTML = `
      ${tocNavHtml}
      <section class="career-report-side-card primary">
        <p class="career-report-side-kicker">Snapshot</p>
        <h3 class="career-report-side-title">${esc(bundle?.meta?.title || "职业报告")}</h3>
        <p class="career-report-side-copy">${formatText(bundle?.report_document?.executive_summary || bundle?.meta?.summary || "完整报告将围绕当前主岗位展开。")}</p>
        <div class="career-report-side-metrics">
          <article>
            <span>主岗位</span>
            <strong>${esc(focusRole)}</strong>
          </article>
          <article>
            <span>匹配判断</span>
            <strong>${esc(`${fitScore}% · ${fitBandLabel}`)}</strong>
          </article>
          <article>
            <span>版本</span>
            <strong>${esc(bundle?.meta?.version || tracker?.report_version || "--")}</strong>
          </article>
        </div>
      </section>
      ${moduleNavHtml}
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Pipeline</p>
        <h3 class="career-report-side-title">生成进度</h3>
        <div class="career-report-stage-list">
          ${progress.map((item) => {
            const active = item.status === "active" || item.status === "running";
            return `
              <div class="career-report-stage-item${active ? " active" : ""}">
                <strong>${esc(item.label || item.key || "阶段")}</strong>
                <span>${esc(item.status === "done" ? "已完成" : active ? "进行中" : item.status === "failed" ? "失败" : "待处理")}</span>
              </div>
            `;
          }).join("")}
        </div>
      </section>
      <section class="career-report-side-card">
        <p class="career-report-side-kicker">Top Roles</p>
        <h3 class="career-report-side-title">当前候选岗位</h3>
        <div class="career-report-role-chip-list">
          ${(roleRankings.length ? roleRankings : [{ id: window.appState?.focusedRoleId || "", name: focusRole }]).map((item) => `
            <button type="button" class="career-report-role-chip${String(item.id || "") === String(window.appState?.focusedRoleId || "") ? " active" : ""}" data-report-focus-role="${esc(item.id || "")}">
              ${esc(item.name || item.title || "候选岗位")}
            </button>
          `).join("")}
        </div>
      </section>
      ${renderReportFeedbackCard()}
    `;

    bindMarkdownTocScrollNav(aside, document.getElementById("careerReportMain"));
    initCrMdTocToggles(aside);

    aside.querySelectorAll("[data-report-focus-role]").forEach((button) => {
      button.addEventListener("click", () => {
        const roleId = String(button.dataset.reportFocusRole || "").trim();
        if (!roleId) return;
        window.setCareerReportFocusRole(roleId);
      });
    });

    bindCareerReportFeedbackHandlers(aside);
  }

  function renderReportMain() {
    const main = document.getElementById("careerReportMain");
    if (!main) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const state = getCareerReportStateSafe();
    const progress = Array.isArray(state?.progress) ? state.progress : getDefaultStageProgress();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";

    if (generating) {
      main.innerHTML = renderReportGenerationMain(state, progress);
      return;
    }

    if (!bundle || !bundle.report_document) {
      main.innerHTML = renderEmptyReportMain();
      return;
    }

    const viewMode = getUserCenterReportViewModeSafe();
    main.innerHTML = viewMode === "report"
      ? `
        ${renderHistoricalNotice()}
        ${renderFullReportHeader(bundle, tracker)}
        ${renderFullMarkdownReport(bundle)}
      `
      : `
        ${renderHistoricalNotice()}
        ${renderReportDashboardV2(bundle, tracker)}
      `;

    main.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
    main.querySelectorAll("[data-user-center-report-view]").forEach((button) => {
      button.addEventListener("click", () => {
        window.setUserCenterReportViewMode?.(button.dataset.userCenterReportView || "report");
      });
    });
    bindCareerReportFeedbackHandlers(main);
    if (viewMode === "report") {
      bindReportPolishHandlers(main);
      bindReportScrollHandlers(main, main);
    } else {
      bindReportDocNavigation(main);
    }
  }

  function cycleTrackerStatus(itemType, currentStatus) {
    const status = String(currentStatus || "").trim().toLowerCase();
    if (itemType === "checkpoint") {
      return status === "done" ? "pending" : "done";
    }
    if (status === "pending") return "doing";
    if (status === "doing") return "done";
    return "pending";
  }

  async function updateTrackerItem(itemType, itemId, currentStatus) {
    if (window.appState?.careerReportViewingHistorical) {
      toast("历史版本只读", "请先切回最新版本，再更新任务进度。", "warning", 2000);
      return;
    }

    const payload = await requestJsonSafe("/api/career-report/tracker/item", {
      method: "POST",
      body: {
        item_type: itemType,
        item_id: itemId,
        status: cycleTrackerStatus(itemType, currentStatus)
      }
    });
    applyCareerReportState(undefined, payload.tracker || null, payload.state || getCareerReportStateSafe(), {
      keepBundle: true,
      historical: false,
      userCenterRefresh: true
    });
  }

  function renderReportViewerTasks(tracker) {
    const items = [];
    const rawItems = Array.isArray(tracker?.plan_items) ? tracker.plan_items : [];
    const parentIds = new Set(rawItems.filter((item) => item.is_task).map((item) => item.parent_phase));
    const planItems = rawItems.filter((item) => item.is_task || item.is_action || (!item.is_roadmap && !parentIds.has(item.id)));
    const checkpoints = Array.isArray(tracker?.checkpoints) ? tracker.checkpoints : [];

    if (planItems.length) {
      items.push('<div class="rv-task-phase">行动计划</div>');
      planItems.forEach((item) => {
        items.push(`
          <button type="button" class="rv-task-item ${esc(item.status || "pending")}" data-report-task-type="plan" data-report-task-id="${esc(item.id || "")}" data-report-task-status="${esc(item.status || "pending")}">
            <span class="rv-task-check">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 5.2 3.8 7.5 8.5 2.5" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            <span class="rv-task-text">${esc(item.title || item.objective || "行动项")}</span>
          </button>
        `);
      });
    }

    if (checkpoints.length) {
      items.push('<div class="rv-task-phase">复查节点</div>');
      checkpoints.forEach((item) => {
        items.push(`
          <button type="button" class="rv-task-item ${esc(item.status || "pending")}" data-report-task-type="checkpoint" data-report-task-id="${esc(item.id || "")}" data-report-task-status="${esc(item.status || "pending")}">
            <span class="rv-task-check">
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M1.5 5.2 3.8 7.5 8.5 2.5" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>
            <span class="rv-task-text">${esc(item.label || item.title || "复查项")}</span>
          </button>
        `);
      });
    }

    return items.join("") || '<div class="rv-task-phase">暂无可跟踪任务</div>';
  }

  function renderReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) return;

    const bundle = window.appState?.careerReport || null;
    const tracker = getCareerReportTracker();
    const tocItems = getReportTocItems(bundle);
    const metaTitle = document.getElementById("rvMetaTitle");
    const progressFill = document.getElementById("rvProgressFill");
    const progressLabel = document.getElementById("rvProgressLabel");
    const statDone = document.getElementById("rvStatDone");
    const statTotal = document.getElementById("rvStatTotal");
    const toc = document.getElementById("rvToc");
    const taskList = document.getElementById("rvTaskList");
    const main = document.getElementById("rvMain");

    if (metaTitle) metaTitle.textContent = bundle?.meta?.title || "职业规划报告";
    if (progressFill) progressFill.style.width = `${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`;
    if (progressLabel) progressLabel.textContent = `${Math.max(0, Math.min(100, Number(tracker?.completion_rate || 0)))}%`;
    if (statDone) statDone.textContent = `已完成 ${Number(tracker?.completed_count || 0)} 项`;
    if (statTotal) statTotal.textContent = `共 ${Number(tracker?.total_count || 0)} 项任务`;

    if (toc) {
      const readingMdRv = bundle?.report_document ? getCareerReportReadingMarkdown(bundle) : "";
      const branchesRv = readingMdRv ? buildMarkdownTocBranches(readingMdRv) : [];
      if (branchesRv.length) {
        toc.innerHTML = renderMarkdownTocNavHtml(branchesRv, { variant: "overlay" });
      } else {
        toc.innerHTML = `
        <div class="report-viewer-toc-label">目录</div>
        ${tocItems.map((section, index) => `
          <button type="button" class="rv-toc-item${index === 0 ? " active" : ""}" data-rv-target="${esc(section.id)}">
            <span class="rv-toc-num">${String(index + 1).padStart(2, "0")}</span>
            <span>${esc(section.title || `章节 ${index + 1}`)}</span>
          </button>
        `).join("")}
      `;
      }
    }

    if (taskList) {
      taskList.innerHTML = renderReportViewerTasks(tracker);
      taskList.querySelectorAll("[data-report-task-type]").forEach((button) => {
        button.addEventListener("click", () => {
          const itemType = String(button.dataset.reportTaskType || "").trim();
          const itemId = String(button.dataset.reportTaskId || "").trim();
          const status = String(button.dataset.reportTaskStatus || "").trim();
          if (!itemType || !itemId) return;
          void updateTrackerItem(itemType, itemId, status).catch((error) => {
            toast("任务状态更新失败", error.message || "请稍后重试。", "error", 2200);
          });
        });
      });
    }

    if (main) {
      main.innerHTML = bundle && bundle.report_document
        ? `${renderHistoricalNotice()}${renderFullReportHeader(bundle, tracker)}${renderFullMarkdownReport(bundle)}`
        : renderEmptyReportMain();
      if (bundle && bundle.report_document) {
        bindCareerReportFeedbackHandlers(main);
        bindReportPolishHandlers(main);
        bindReportScrollHandlers(main, main);
        if (toc && toc.querySelector(".cr-md-toc")) {
          bindMarkdownTocScrollNav(toc, main);
          initCrMdTocToggles(toc);
        }
      }
    }

    overlay.querySelectorAll("[data-rv-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const targetId = String(button.dataset.rvTarget || "").trim();
        if (!targetId) return;
        overlay.querySelectorAll(".rv-toc-item").forEach((item) => item.classList.toggle("active", item === button));
        const target = main?.querySelector(`#${escapeSelectorId(targetId)}`);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    overlay.querySelectorAll("[data-report-action='back-latest']").forEach((button) => {
      button.addEventListener("click", () => {
        void window.restoreLatestCareerReportView();
      });
    });
  }

  function renderCareerReportPanels() {
    renderStatusBanner();
    const state = getCareerReportStateSafe();
    const status = String(state?.status || "").trim().toLowerCase();
    const generating = status === "queued" || status === "running";
    const layout = document.querySelector("#report-workspace .career-report-layout");
    if (layout) {
      layout.classList.toggle("career-report-layout--generating", generating);
    }
    renderReportAside();
    const reportLayout = document.querySelector("#report-workspace .career-report-layout");
    if (reportLayout) {
      const asideEl = document.getElementById("careerReportAside");
      const hasMdToc = Boolean(asideEl?.querySelector?.(".cr-md-toc"));
      reportLayout.classList.toggle("career-report-layout--md-toc", hasMdToc);
    }
    renderReportMain();
    renderReportViewer();
    window.applyUserCenterReportReaderGate?.();
  }

  function openReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) {
      window.openUserCenterPage?.("report-workspace");
      return;
    }
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无完整报告", "请先生成职业报告，再查看完整版本。", "warning", 2200);
      return;
    }
    renderReportViewer();
    reportRuntime.previousBodyOverflow = document.body.style.overflow || "";
    document.body.style.overflow = "hidden";
    overlay.classList.remove("hidden");
  }

  function closeReportViewer() {
    const overlay = document.getElementById("reportViewerOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
    document.body.style.overflow = reportRuntime.previousBodyOverflow;
  }

  function renderReportEditorSectionMap(source) {
    const host = document.getElementById("reportEditorSectionMap");
    if (!host) return;
    const md = String(source?.markdown || "").trim();
    const reading = md ? markdownForCareerReportReading(md) : "";
    const branches = reading ? buildMarkdownTocBranches(reading) : [];
    if (branches.length) {
      host.innerHTML = renderMarkdownTocNavHtml(branches, { variant: "editor" });
    } else {
      const items = Array.isArray(source?.section_map) ? source.section_map : [];
      host.innerHTML = items.length
        ? items.map((item, index) => `
          <button type="button" class="tree-item report-editor-section-item" data-editor-scroll-index="${index}">
            <span class="toc-radio" aria-hidden="true"></span>
            <span class="tree-label report-editor-section-item-body">
              <strong>${esc(item?.label || `章节 ${index + 1}`)}</strong>
              <small>${esc(String(item?.markdown || "").slice(0, 60) || "点击快速定位")}</small>
            </span>
          </button>
        `).join("")
        : `<div class="tree-item report-editor-section-item report-editor-section-item--empty active" aria-disabled="true"><span class="toc-radio" aria-hidden="true"></span><span class="tree-label report-editor-section-item-body"><strong>暂无章节</strong><small>等待源文稿加载</small></span></div>`;
      host.querySelectorAll("[data-editor-scroll-index]").forEach((button) => {
        button.addEventListener("click", () => {
          const index = Number(button.dataset.editorScrollIndex || 0);
          const section = items[index];
          if (!section) return;
          const label = String(section.label || "").trim();
          const segments = Array.isArray(reportRuntime.editorSegments) ? reportRuntime.editorSegments : [];
          if (!segments.length) return;
          const hitIndex = segments.findIndex((segment) => String(segment.text || "").includes(label));
          if (hitIndex >= 0) {
            reportRuntime.editorAnchorIndex = hitIndex;
            selectCareerReportEditorSegmentRange(hitIndex, hitIndex);
            const ta = document.getElementById("reportEditorTextarea");
            const seg = segments[hitIndex];
            const docMode = normalizeCareerReportEditorDocMode(reportRuntime.editorDocMode);
            if (docMode === "edit" && ta && seg && Number.isFinite(seg.startOffset)) {
              const md = String(ta.value || "");
              ta.focus();
              ta.setSelectionRange(seg.startOffset, seg.startOffset);
              window.requestAnimationFrame(() => {
                try {
                  const before = md.slice(0, seg.startOffset);
                  const lineIdx = before.split("\n").length;
                  const cs = window.getComputedStyle(ta);
                  const lh = parseFloat(cs.lineHeight);
                  const fs = parseFloat(cs.fontSize) || 13;
                  const lineHeight = Number.isFinite(lh) && lh > 0 ? lh : fs * 1.65;
                  ta.scrollTop = Math.max(0, (lineIdx - 1) * lineHeight - ta.clientHeight * 0.25);
                } catch (_) {
                  /* ignore */
                }
              });
              return;
            }
            const hostEl = document.getElementById("reportEditorRenderedDoc");
            hostEl?.querySelector(`[data-editor-segment-index="${hitIndex}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        });
      });
      return;
    }

    bindMarkdownTocEditorNav(host);
    initCrMdTocToggles(host);
    initCareerReportEditorTreeToggles(host);
  }

  function updateReportEditorNavProgress(payload) {
    const map = Array.isArray(payload?.section_map) ? payload.section_map : [];
    const n = map.length;
    const pctEl = document.getElementById("reportEditorProgressPct");
    const fill = document.getElementById("reportEditorProgressFill");
    const hint = document.getElementById("reportEditorProgressHint");
    if (!pctEl && !fill && !hint) return;
    const target = 8;
    const pct = n ? Math.min(100, Math.round((n / target) * 100)) : 0;
    if (pctEl) pctEl.textContent = n ? `${pct}%` : "—";
    if (fill) fill.style.width = n ? `${pct}%` : "0%";
    if (hint) {
      hint.textContent = n
        ? `已识别 ${n} 个章节区块，可点击左侧快速跳转`
        : "章节结构加载中或暂不可用";
    }
  }

  function setReportEditorRailTab() {
    const chat = document.getElementById("reportEditorRailChat");
    if (chat) chat.classList.remove("hidden");
  }

  function setReportEditorRailView(view) {
    const chatTab = document.getElementById("reportEditorTabChat");
    const chgTab = document.getElementById("reportEditorTabChanges");
    const chatPanel = document.getElementById("reportEditorRailChat");
    const chgPanel = document.getElementById("reportEditorRailViewChanges");
    const v = String(view || "chat").trim().toLowerCase();
    const isChat = v !== "changes";
    if (chatTab) {
      chatTab.classList.toggle("is-active", isChat);
      chatTab.setAttribute("aria-selected", isChat ? "true" : "false");
    }
    if (chgTab) {
      chgTab.classList.toggle("is-active", !isChat);
      chgTab.setAttribute("aria-selected", !isChat ? "true" : "false");
    }
    if (chatPanel) chatPanel.classList.toggle("hidden", !isChat);
    if (chgPanel) chgPanel.classList.toggle("hidden", isChat);
    reportRuntime.editorRailView = isChat ? "chat" : "changes";
  }

  function setReportEditorPolishBusy(on) {
    const shell = document.querySelector(".report-editor-shell.report-editor-shell--polish-v2");
    if (shell) shell.classList.toggle("report-editor-polish-busy", Boolean(on));
    document.querySelectorAll("#reportEditorQuickActionsBar [data-quick-action]").forEach((btn) => {
      btn.disabled = Boolean(on);
    });
    const send = document.getElementById("reportEditorPromptSendBtn");
    const sendIco = document.getElementById("reportEditorPromptSendIconBtn");
    [send, sendIco].forEach((el) => {
      if (el) el.disabled = Boolean(on);
    });
  }

  function updateReportEditorChangesBadge() {
    const badge = document.getElementById("reportEditorChangesBadge");
    if (!badge) return;
    const pending = reportRuntime.editorDiff;
    const blocks = pending && Array.isArray(pending.diff_blocks) ? pending.diff_blocks : [];
    if (blocks.length) {
      const stats = summarizeEditorDiffBlocks(blocks);
      let n = Number(stats.addLines || 0) + Number(stats.delLines || 0);
      if (n < 1) n = Math.max(1, buildFullChangeLogEntries(blocks).length);
      badge.textContent = String(Math.min(99, n));
      badge.classList.remove("is-zero");
      return;
    }
    const cum = Number(reportRuntime.cumulativeDiffLines || 0);
    const histLen = Array.isArray(reportRuntime.appliedChangeBullets) ? reportRuntime.appliedChangeBullets.length : 0;
    const n = cum > 0 ? cum : histLen;
    if (n < 1) {
      badge.textContent = "0";
      badge.classList.add("is-zero");
      return;
    }
    badge.textContent = String(Math.min(99, n));
    badge.classList.remove("is-zero");
  }

  function renderReportEditorSnapshotList(source) {
    const host = document.getElementById("reportEditorSnapshotList");
    if (!host) return;
    const reportId = String(source?.report_id || window.appState?.careerReport?.meta?.report_id || "").trim();
    const snapshots = Array.isArray(window.appState?.careerReport?.draft_snapshots) ? window.appState.careerReport.draft_snapshots : [];
    const activeSnapshotId = String(source?.snapshot_id || "").trim();
    const activeFormal = !activeSnapshotId;
    const formalTitle = esc(window.appState?.careerReport?.meta?.title || "正式职业报告");
    host.innerHTML = `
      <button type="button" class="version-toc-card${activeFormal ? " is-active" : ""}"${activeFormal ? ' aria-current="true"' : ""} data-editor-source-report="${esc(reportId)}">
        <span class="toc-radio" aria-hidden="true"></span>
        <span class="version-card-body">
          <span class="version-card-title">${formalTitle}</span>
          <span class="version-card-meta">正式报告基线</span>
        </span>
      </button>
      ${snapshots.map((snapshot) => `
        <button type="button" class="version-toc-card${String(snapshot?.snapshot_id || "") === activeSnapshotId ? " is-active" : ""}"${String(snapshot?.snapshot_id || "") === activeSnapshotId ? ' aria-current="true"' : ""} data-editor-source-snapshot="${esc(snapshot?.snapshot_id || "")}">
          <span class="toc-radio" aria-hidden="true"></span>
          <span class="version-card-body">
            <span class="version-card-title">${esc(snapshot?.title || snapshot?.label || "编辑快照")}</span>
            <span class="version-card-meta">${esc(snapshot?.updated_at || snapshot?.created_at || "--")}</span>
          </span>
        </button>
      `).join("")}
    `;
    host.querySelector("[data-editor-source-report]")?.addEventListener("click", () => {
      void openCareerReportEditor({ reportId, snapshotId: "" });
    });
    host.querySelectorAll("[data-editor-source-snapshot]").forEach((button) => {
      button.addEventListener("click", () => {
        const snapshotId = String(button.dataset.editorSourceSnapshot || "").trim();
        if (!snapshotId) return;
        void openCareerReportEditor({ reportId, snapshotId });
      });
    });
  }

  function clipReportEditorText(value, limit = 180) {
    const text = String(value || "").trim().replace(/\s+/g, " ");
    if (!text) return "";
    if (text.length <= limit) return text;
    return `${text.slice(0, Math.max(0, limit - 3))}...`;
  }

  function getEditorLineRange(text, start, end) {
    const source = String(text || "");
    const safeStart = Math.max(0, Math.min(Number(start) || 0, source.length));
    const safeEnd = Math.max(safeStart, Math.min(Number(end) || 0, source.length));
    const beforeStart = source.slice(0, safeStart);
    const beforeEnd = source.slice(0, safeEnd);
    const lineStart = beforeStart.split("\n").length;
    const lineEnd = Math.max(lineStart, beforeEnd.split("\n").length);
    return {
      lineStart,
      lineEnd,
      ref: lineStart === lineEnd ? `原始文本第 ${lineStart} 行` : `原始文本第 ${lineStart}-${lineEnd} 行`
    };
  }

  function normalizeCareerReportEditorViewMode(mode) {
    return String(mode || "").trim().toLowerCase() === "markdown" ? "markdown" : "rendered";
  }

  function normalizeCareerReportEditorDocMode(mode) {
    const m = String(mode || "").trim().toLowerCase();
    if (m === "preview" || m === "edit" || m === "diff") return m;
    return "preview";
  }

  function setCareerReportEditorDocMode(mode = "preview") {
    const next = normalizeCareerReportEditorDocMode(mode);
    reportRuntime.editorDocMode = next;
    reportRuntime.editorViewMode = next === "edit" ? "markdown" : "rendered";
    const pv = document.getElementById("reportEditorPanePreview");
    const ed = document.getElementById("reportEditorPaneEdit");
    const df = document.getElementById("reportEditorPaneDiff");
    if (pv) pv.classList.toggle("hidden", next !== "preview");
    if (ed) ed.classList.toggle("hidden", next !== "edit");
    if (df) df.classList.toggle("hidden", next !== "diff");
    document.querySelectorAll(".report-editor-doc-mode-btn[data-doc-mode]").forEach((btn) => {
      const active = String(btn.getAttribute("data-doc-mode") || "") === next;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    const shell = document.getElementById("reportEditorOverlay");
    if (shell) {
      shell.dataset.editorDocMode = next;
      shell.dataset.editorViewMode = reportRuntime.editorViewMode;
    }
    const textarea = document.getElementById("reportEditorTextarea");
    if (next === "edit" && textarea) {
      window.requestAnimationFrame(() => {
        try {
          textarea.focus();
        } catch (_) {
          /* ignore */
        }
      });
    }
  }

  function setCareerReportEditorViewMode(mode = "rendered") {
    const nextMode = normalizeCareerReportEditorViewMode(mode);
    setCareerReportEditorDocMode(nextMode === "markdown" ? "edit" : "preview");
  }

  function escapeRegExp(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function findSelectionRangeInSource(source, selectedText) {
    const text = String(source || "");
    const query = String(selectedText || "").replace(/\u00a0/g, " ").trim();
    if (!text || !query) return null;
    let start = text.indexOf(query);
    if (start >= 0) {
      return { start, end: start + query.length };
    }
    const compact = query.replace(/\s+/g, " ").trim();
    if (!compact) return null;
    const fuzzy = new RegExp(escapeRegExp(compact).replace(/\s+/g, "\\s+"), "m");
    const match = fuzzy.exec(text);
    if (!match) return null;
    return { start: match.index, end: match.index + match[0].length };
  }

  function setCareerReportEditorSelection(start, end, textOverride = "") {
    const textarea = document.getElementById("reportEditorTextarea");
    const source = String(textarea?.value || "");
    const safeStart = Math.max(0, Math.min(Number(start) || 0, source.length));
    const safeEnd = Math.max(safeStart, Math.min(Number(end) || 0, source.length));
    if (safeEnd <= safeStart) {
      clearCareerReportEditorSelection({ render: false });
      return;
    }
    const range = getEditorLineRange(source, safeStart, safeEnd);
    reportRuntime.editorSelectedRange = null;
    reportRuntime.editorAnchorIndex = -1;
    reportRuntime.editorSelection = {
      start: safeStart,
      end: safeEnd,
      text: textOverride || source.slice(safeStart, safeEnd),
      lineStart: range.lineStart,
      lineEnd: range.lineEnd,
      ref: range.ref
    };
    updateCareerReportEditorSelectionInfo();
  }

  function syncCareerReportEditorSelectionFromRendered() {
    const host = document.getElementById("reportEditorRenderedDoc");
    const textarea = document.getElementById("reportEditorTextarea");
    if (!host || !textarea) return;
    const selection = window.getSelection?.();
    if (!selection || selection.rangeCount < 1) return;
    const anchorNode = selection.anchorNode;
    const focusNode = selection.focusNode;
    if (!host.contains(anchorNode) || !host.contains(focusNode)) return;
    if (selection.isCollapsed) {
      clearCareerReportEditorSelection({ render: false });
      return;
    }
    const text = String(selection.toString() || "").trim();
    const hit = findSelectionRangeInSource(String(textarea.value || ""), text);
    if (!hit) return;
    setCareerReportEditorSelection(hit.start, hit.end, text);
  }

  function syncCareerReportEditorSelectionFromTextarea() {
    const textarea = document.getElementById("reportEditorTextarea");
    if (!textarea) return;
    const start = Number(textarea.selectionStart || 0);
    const end = Number(textarea.selectionEnd || 0);
    if (end <= start) {
      clearCareerReportEditorSelection({ render: false });
      return;
    }
    setCareerReportEditorSelection(start, end, textarea.value.slice(start, end));
  }

  function renderReportEditorPromptSelectionPills() {
    const host = document.getElementById("reportEditorPromptSelectionPills");
    if (!host) return;
    const selection = reportRuntime.editorSelection;
    const length = Math.max(0, Number(selection?.end || 0) - Number(selection?.start || 0));
    if (!selection || !length) {
      host.classList.add("hidden");
      host.innerHTML = "";
      return;
    }
    const lineLabel = esc(selection.ref || "原始文本");
    host.classList.remove("hidden");
    host.innerHTML = `
      <button type="button" class="report-editor-selection-pill is-active" data-editor-clear-pill="1">
        <strong>${lineLabel}</strong>
        <span>${length} 字符 · 已附带上下文</span>
        <em>移除</em>
      </button>
    `;
    host.querySelector("[data-editor-clear-pill]")?.addEventListener("click", () => {
      clearCareerReportEditorSelection({ render: false });
      updateCareerReportEditorSelectionInfo();
    });
  }

  function autoResizeReportEditorPromptInput() {
    const promptInput = document.getElementById("reportEditorPromptInput");
    if (!promptInput) return;
    const style = window.getComputedStyle(promptInput);
    const lineHeight = parseFloat(style.lineHeight) || 22;
    const padding = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
    const minHeight = Math.round(lineHeight * 2 + padding);
    const maxHeight = Math.round(lineHeight * 6 + padding);
    promptInput.style.height = "auto";
    const nextHeight = Math.max(minHeight, Math.min(promptInput.scrollHeight, maxHeight));
    promptInput.style.height = `${nextHeight}px`;
    promptInput.style.overflowY = promptInput.scrollHeight > maxHeight ? "auto" : "hidden";
  }

  function normalizeCareerReportEditorMode(mode) {
    return String(mode || "").trim().toLowerCase() === "review" ? "review" : "edit";
  }

  function setCareerReportEditorMode(mode = "edit") {
    const nextMode = normalizeCareerReportEditorMode(mode);
    reportRuntime.editorMode = nextMode;
    const editStage = document.getElementById("reportEditorEditStage");
    const reviewStage = document.getElementById("reportEditorReviewStage");
    if (editStage) editStage.classList.toggle("hidden", nextMode !== "edit");
    if (reviewStage) reviewStage.classList.toggle("hidden", nextMode !== "review");
    document.querySelectorAll("[data-editor-mode]").forEach((button) => {
      const active = String(button.dataset.editorMode || "").trim() === nextMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function resolveEditorLineOffset(lines, lineNumber) {
    let offset = 0;
    const safeLine = Math.max(1, Math.min(Number(lineNumber) || 1, lines.length || 1));
    for (let index = 1; index < safeLine; index += 1) {
      offset += (lines[index - 1] || "").length;
      offset += 1;
    }
    return offset;
  }

  function buildCareerReportEditorSegments(markdown) {
    const lines = String(markdown || "").split("\n");
    const segments = [];
    let cursor = 0;
    while (cursor < lines.length) {
      while (cursor < lines.length && !String(lines[cursor] || "").trim()) {
        cursor += 1;
      }
      if (cursor >= lines.length) break;
      const startIndex = cursor;
      cursor += 1;
      while (cursor < lines.length) {
        const current = String(lines[cursor] || "");
        const previous = String(lines[cursor - 1] || "");
        const headingBreak = /^#{1,4}\s+/.test(current) && previous.trim();
        if (headingBreak || (!current.trim() && previous.trim())) break;
        cursor += 1;
      }
      let endIndex = cursor - 1;
      while (endIndex > startIndex && !String(lines[endIndex] || "").trim()) {
        endIndex -= 1;
      }
      const startLine = startIndex + 1;
      const endLine = endIndex + 1;
      const startOffset = resolveEditorLineOffset(lines, startLine);
      const endOffset = resolveEditorLineOffset(lines, endLine) + String(lines[endLine - 1] || "").length;
      const text = String(markdown || "").slice(startOffset, endOffset);
      segments.push({
        index: segments.length,
        startLine,
        endLine,
        startOffset,
        endOffset,
        text,
        ref: `报告${startLine}-${endLine}行`
      });
      cursor = endIndex + 1;
    }
    return segments;
  }

  function clearCareerReportEditorSelection(options = {}) {
    reportRuntime.editorSelection = null;
    reportRuntime.editorSelectedRange = null;
    reportRuntime.editorAnchorIndex = -1;
    if (options.render !== false) {
      renderCareerReportEditorDocument();
    }
    updateCareerReportEditorSelectionInfo();
  }

  function selectCareerReportEditorSegmentRange(leftIndex, rightIndex) {
    const segments = Array.isArray(reportRuntime.editorSegments) ? reportRuntime.editorSegments : [];
    if (!segments.length) {
      clearCareerReportEditorSelection();
      return;
    }
    const startIndex = Math.max(0, Math.min(Number(leftIndex) || 0, segments.length - 1));
    const endIndex = Math.max(0, Math.min(Number(rightIndex) || 0, segments.length - 1));
    const from = Math.min(startIndex, endIndex);
    const to = Math.max(startIndex, endIndex);
    const first = segments[from];
    const last = segments[to];
    if (!first || !last) return;
    const textarea = document.getElementById("reportEditorTextarea");
    const source = String(textarea?.value || "");
    reportRuntime.editorSelectedRange = { from, to };
    reportRuntime.editorSelection = {
      start: first.startOffset,
      end: last.endOffset,
      text: source.slice(first.startOffset, last.endOffset),
      lineStart: first.startLine,
      lineEnd: last.endLine,
      ref: `报告${first.startLine}-${last.endLine}行`
    };
    renderCareerReportEditorDocument();
    updateCareerReportEditorSelectionInfo();
  }

  function renderCareerReportEditorDocument() {
    const host = document.getElementById("reportEditorRenderedDoc");
    const textarea = document.getElementById("reportEditorTextarea");
    if (!host || !textarea) return;
    const markdown = String(textarea.value || "");
    reportRuntime.editorSegments = buildCareerReportEditorSegments(markdown);
    host.innerHTML = markdown.trim()
      ? `
        <article class="report-editor-md-article report-editor-md-article--bare">
          <div class="report-editor-md-article-body">${renderMarkdownBasic(markdown, { enhancedLayout: true, injectHeadingAnchors: true, previewReportId: reportRuntime.editorSource?.report_id, previewSnapshotId: reportRuntime.editorSource?.snapshot_id })}</div>
        </article>
      `
      : `<div class="report-editor-md-empty-state"><strong>当前报告为空</strong><span>请先生成或加载报告内容。</span></div>`;
    renderReportEditorSectionMap({
      markdown,
      section_map: Array.isArray(reportRuntime.editorSource?.section_map) ? reportRuntime.editorSource.section_map : []
    });
    setCareerReportEditorDocMode(reportRuntime.editorDocMode || "preview");
  }

  function summarizeEditorDiffBlocks(diffBlocks) {
    const blocks = Array.isArray(diffBlocks) ? diffBlocks : [];
    let addLines = 0;
    let delLines = 0;
    const preview = [];
    blocks.forEach((block) => {
      const lines = Array.isArray(block?.lines) ? block.lines : [];
      const type = String(block?.type || "equal").trim().toLowerCase();
      if (type === "add") addLines += lines.length;
      if (type === "delete") delLines += lines.length;
      if (type !== "equal" && preview.length < 3) {
        const text = clipReportEditorText(lines.join(" "), 72);
        if (text) preview.push(`${type === "add" ? "+" : "-"} ${text}`);
      }
    });
    return { addLines, delLines, preview };
  }

  function buildSemanticChangeSummary(diffBlocks) {
    const blocks = Array.isArray(diffBlocks) ? diffBlocks : [];
    const { addLines, delLines, preview } = summarizeEditorDiffBlocks(diffBlocks);
    const intro = `模型对选中范围做了行文调整：约新增 ${addLines} 行、删减 ${delLines} 行（按行级 diff 统计）。`;
    const bullets = [];
    blocks.forEach((block) => {
      const type = String(block?.type || "equal").trim().toLowerCase();
      if (type === "equal") return;
      const lines = Array.isArray(block?.lines) ? block.lines : [];
      const joined = clipReportEditorText(lines.join(" ").replace(/\s+/g, " "), 96);
      if (!joined || bullets.length >= 4) return;
      if (type === "add") bullets.push(`补充或改写：${joined}`);
      if (type === "delete") bullets.push(`删去原表述：${joined}`);
    });
    return { intro, bullets };
  }

  /** 右侧「改动」列表：逐条记录每一处增/删块（与 Diff 行级块一一对应） */
  function buildFullChangeLogEntries(diffBlocks) {
    const blocks = Array.isArray(diffBlocks) ? diffBlocks : [];
    const entries = [];
    const maxEntries = 120;
    blocks.forEach((block) => {
      if (entries.length >= maxEntries) return;
      const type = String(block?.type || "equal").trim().toLowerCase();
      if (type === "equal") return;
      const lines = Array.isArray(block?.lines) ? block.lines : [];
      const joined = clipReportEditorText(lines.join(" ").replace(/\s+/g, " "), 200);
      if (!joined) return;
      if (type === "add") entries.push(`\u65b0\u589e\uff1a${joined}`);
      if (type === "delete") entries.push(`\u5220\u9664\uff1a${joined}`);
    });
    return entries;
  }

  function renderUnifiedDiffMarkup(diffBlocks) {
    const blocks = Array.isArray(diffBlocks) ? diffBlocks : [];
    if (!blocks.length) return "";
    const parts = [];
    blocks.forEach((block) => {
      const type = String(block?.type || "equal").trim().toLowerCase();
      const lines = Array.isArray(block?.lines) ? block.lines : [];
      const cls = type === "add" ? "report-editor-diff-line--add" : type === "delete" ? "report-editor-diff-line--del" : "report-editor-diff-line--eq";
      lines.forEach((line) => {
        parts.push(`<span class="report-editor-diff-line ${cls}">${esc(line)}</span>`);
      });
    });
    return parts.join("\n");
  }

  function openReportEditorReviewPanel() {
    if (!reportRuntime.editorDiff && !reportRuntime.editorDiffArchive) return;
    setCareerReportEditorMode("review");
  }

  const REPORT_EDITOR_CHAT_AVATAR = {
    assistant:
      '<svg class="report-editor-chat-avatar-icon" viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path fill="currentColor" d="M12 2.25l1.65 5.1L18.75 12l-5.1 1.65L12 18.75l-1.65-5.1L5.25 12l5.1-1.65L12 2.25z"/></svg>',
    user: '<span class="report-editor-chat-avatar-me">\u6211</span>',
    system: '<span class="report-editor-chat-avatar-dot" aria-hidden="true"></span>'
  };

  function appendReportEditorMessage(role, label, body, tone = role, extra = {}) {
    const next = {
      role: String(role || "system"),
      tone: String(tone || role || "system"),
      label: String(label || role || "System"),
      body: String(body || "").trim(),
      pill: Boolean(extra.pill),
      selectionRef: extra.selectionRef || "",
      selectionPreview: extra.selectionPreview || "",
      diffSummary: extra.diffSummary && typeof extra.diffSummary === "object" ? extra.diffSummary : null
    };
    reportRuntime.editorConversation = [
      ...(Array.isArray(reportRuntime.editorConversation) ? reportRuntime.editorConversation : []),
      next
    ].slice(-10);
  }

  function renderReportEditorChatLog() {
    const host = document.getElementById("reportEditorChatLog");
    if (!host) return;
    const messages = Array.isArray(reportRuntime.editorConversation) ? reportRuntime.editorConversation : [];
    if (!messages.length) {
      host.innerHTML = `<div class="report-editor-chat-item report-editor-chat-item--empty">
        <div class="report-editor-chat-empty-visual" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.15" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/><path d="M8 10h8"/><path d="M8 14h5"/></svg>
        </div>
        <p>\u6682\u65e0\u5bf9\u8bdd\u8bb0\u5f55\u3002\u53ef\u9009\u4e2d\u5de6\u4fa7\u6b63\u6587\u540e\u4f7f\u7528\u5feb\u6377\u6309\u94ae\uff0c\u6216\u5728\u4e0b\u65b9\u8f93\u5165\u4f18\u5316\u6307\u4ee4\u3002</p>
      </div>`;
      return;
    }
    const rowsHtml = messages.map((item) => {
      const tone = String(item?.tone || item?.role || "system");
      const isUser = tone === "user";
      const isAssistant = tone === "assistant";
      const rowMod = isUser ? "user" : isAssistant ? "assistant" : "system";
      const avHtml = isUser
        ? REPORT_EDITOR_CHAT_AVATAR.user
        : isAssistant
          ? REPORT_EDITOR_CHAT_AVATAR.assistant
          : REPORT_EDITOR_CHAT_AVATAR.system;
      const bodyHtml = item?.pill
        ? `<span class="report-editor-chat-pill">${esc(item?.body || "")}</span>`
        : `<p>${esc(item?.body || "")}</p>`;
      return `
      <div class="report-editor-chat-row report-editor-chat-row--${rowMod}">
        <div class="report-editor-chat-avatar" aria-hidden="true">${avHtml}</div>
        <div class="report-editor-chat-card">
          <span class="report-editor-chat-role">${esc(item?.label || item?.role || "System")}</span>
          ${item?.selectionRef ? `
            <div class="report-editor-selection-ref">
              <strong>${esc(item.selectionRef)}</strong>
              <small>${esc(item.selectionPreview || "\u5df2\u6309\u884c\u9644\u5e26\u539f\u6587\u4e0a\u4e0b\u6587")}</small>
            </div>
          ` : ""}
          ${bodyHtml}
          ${item?.diffSummary ? `
            <div class="report-editor-diff-mini">
              <div class="report-editor-diff-mini-head">
                <div class="report-editor-diff-mini-counts">
                  <span class="plus">+${Number(item.diffSummary.addLines || 0)}</span>
                  <span class="minus">-${Number(item.diffSummary.delLines || 0)}</span>
                </div>
                <button type="button" data-editor-open-review="1">Review \u5168\u5c4f</button>
              </div>
              <ul>
                ${(Array.isArray(item.diffSummary.preview) ? item.diffSummary.preview : []).map((line) => `<li>${esc(line)}</li>`).join("")}
              </ul>
            </div>
          ` : ""}
        </div>
      </div>`;
    }).join("");
    const pendingRow =
      reportRuntime.editorPolishPending
        ? `
      <div class="report-editor-chat-row report-editor-chat-row--assistant report-editor-chat-row--pending">
        <div class="report-editor-chat-avatar" aria-hidden="true">${REPORT_EDITOR_CHAT_AVATAR.assistant}</div>
        <div class="report-editor-chat-card report-editor-chat-card--pending">
          <span class="report-editor-chat-role">${esc("AI \u52a9\u624b")}</span>
          <div class="report-editor-ai-spinner" role="status" aria-live="polite" aria-busy="true">
            <span class="report-editor-ai-spinner-ring" aria-hidden="true"></span>
            <span class="report-editor-ai-spinner-text">\u6b63\u5728\u751f\u6210\u2026</span>
          </div>
        </div>
      </div>`
        : "";
    host.innerHTML = rowsHtml + pendingRow;
    host.querySelectorAll("[data-editor-open-review]").forEach((button) => {
      button.addEventListener("click", () => {
        openReportEditorReviewPanel();
      });
    });
    host.scrollTop = host.scrollHeight;
  }

  function renderReportEditorDiffPanel() {
    const proposedDiff = document.getElementById("reportEditorProposedDiff");
    const proposedEmpty = document.getElementById("reportEditorProposedEmpty");
    const changeSummary = document.getElementById("reportEditorChangeSummary");
    const changeSummaryBody = document.getElementById("reportEditorChangeSummaryBody");
    const changeSummaryList = document.getElementById("reportEditorChangeSummaryList");
    const diffActions = document.getElementById("reportEditorDiffActions");
    const reviewOriginal = document.getElementById("reportEditorReviewOriginalContent");
    const reviewSuggested = document.getElementById("reportEditorReviewSuggestedContent");
    const reviewSelectionRef = document.getElementById("reportEditorReviewSelectionRef");
    const reviewDelta = document.getElementById("reportEditorReviewDeltaList");
    const reviewAdd = document.getElementById("reportEditorReviewAddedStat");
    const reviewDel = document.getElementById("reportEditorReviewDeletedStat");
    const pendingDiff = reportRuntime.editorDiff;
    const archivedDiff = reportRuntime.editorDiffArchive;
    const diff = pendingDiff || archivedDiff;
    const hasDiff = Boolean(diff && Array.isArray(diff.diff_blocks) && diff.diff_blocks.length);
    const isPendingProposal = Boolean(pendingDiff);
    const scopeHint = document.getElementById("reportEditorDiffScopeHint");
    if (!hasDiff) {
      if (scopeHint) {
        scopeHint.textContent = "";
        scopeHint.classList.add("hidden");
      }
      if (proposedDiff) {
        proposedDiff.classList.add("hidden");
        proposedDiff.innerHTML = "";
      }
      if (proposedEmpty) proposedEmpty.classList.remove("hidden");
      if (changeSummary) changeSummary.classList.remove("hidden");
      if (changeSummaryBody) {
        const hist = Array.isArray(reportRuntime.appliedChangeBullets) ? reportRuntime.appliedChangeBullets : [];
        changeSummaryBody.textContent =
          hist.length > 0
            ? `\u672c\u6b21\u4f1a\u8bdd\u5df2\u7d2f\u8ba1 ${hist.length} \u6761\u6539\u52a8\u8bb0\u5f55\uff08\u89c1\u4e0b\u65b9\u5217\u8868\uff09\u3002\u82e5\u9700\u65b0\u7684\u6da6\u8272\u5bf9\u7167\uff0c\u8bf7\u518d\u6b21\u53d1\u9001\u6da6\u8272\u3002`
            : "\u6682\u65e0\u5f85\u5ba1\u9605\u6539\u52a8\u3002\u5728\u300c\u5bf9\u8bdd\u300d\u4e2d\u53d1\u9001\u6da6\u8272\u540e\uff0c\u8fd9\u91cc\u4f1a\u6c47\u603b\u6a21\u578b\u8c03\u6574\u8bf4\u660e\u3002";
      }
      if (changeSummaryList) {
        const histOnly = Array.isArray(reportRuntime.appliedChangeBullets) ? reportRuntime.appliedChangeBullets : [];
        if (histOnly.length) {
          changeSummaryList.classList.remove("hidden");
          changeSummaryList.innerHTML = histOnly.map((line) => `<li>${esc(line)}</li>`).join("");
        } else {
          changeSummaryList.innerHTML = "";
          changeSummaryList.classList.add("hidden");
        }
      }
      if (diffActions) diffActions.classList.add("hidden");
      if (reviewOriginal) reviewOriginal.textContent = "";
      if (reviewSuggested) reviewSuggested.textContent = "";
      if (reviewSelectionRef) reviewSelectionRef.textContent = "报告行段";
      if (reviewDelta) reviewDelta.innerHTML = "<li>暂无待审阅改动</li>";
      if (reviewAdd) reviewAdd.textContent = "+0";
      if (reviewDel) reviewDel.textContent = "-0";
      updateReportEditorChangesBadge();
      return;
    }
    const diffSummary = summarizeEditorDiffBlocks(diff.diff_blocks);
    const semantic = buildSemanticChangeSummary(diff.diff_blocks);
    const changeEntries = isPendingProposal ? buildFullChangeLogEntries(diff.diff_blocks) : [];
    const hist = Array.isArray(reportRuntime.appliedChangeBullets) ? reportRuntime.appliedChangeBullets : [];
    const listCombined = [...hist, ...changeEntries];
    if (scopeHint) {
      if (!isPendingProposal && archivedDiff && archivedDiff.scopeLabel) {
        scopeHint.textContent = `\u5df2\u91c7\u7eb3\u5199\u5165\u6b63\u6587 \u00b7 ${archivedDiff.scopeLabel} \u00b7 \u4ee5\u4e0b\u4e3a\u91c7\u7eb3\u524d\u7684\u884c\u7ea7\u589e\u5220\u5bf9\u7167`;
        scopeHint.classList.remove("hidden");
      } else if (isPendingProposal) {
        const ref = diff.selection && Number.isFinite(diff.selection.start) && Number.isFinite(diff.selection.end)
          ? getEditorLineRange(String(document.getElementById("reportEditorTextarea")?.value || ""), diff.selection.start, diff.selection.end).ref
          : "";
        scopeHint.textContent = ref
          ? `\u5bf9\u7167\u8303\u56f4\uff1a${ref}\uff08\u4e0e Preview \u6b63\u6587\u5bf9\u7167\uff09`
          : "\u5bf9\u7167\u8303\u56f4\uff1a\u6574\u7bc7\u62a5\u544a\u6b63\u6587";
        scopeHint.classList.remove("hidden");
      } else {
        scopeHint.textContent = "";
        scopeHint.classList.add("hidden");
      }
    }
    if (proposedDiff) {
      proposedDiff.classList.remove("hidden");
      proposedDiff.classList.toggle("report-editor-proposed-diff--settled", !isPendingProposal);
      proposedDiff.innerHTML = renderUnifiedDiffMarkup(diff.diff_blocks);
    }
    if (proposedEmpty) proposedEmpty.classList.add("hidden");
    if (changeSummary && changeSummaryBody) {
      changeSummary.classList.remove("hidden");
      if (isPendingProposal) {
        changeSummaryBody.textContent = semantic.intro;
      } else if (archivedDiff) {
        changeSummaryBody.textContent = `${semantic.intro}\n\n\u6539\u52a8\u5df2\u5199\u5165\u6b63\u6587\u3002\u4e0b\u65b9\u5217\u8868\u4e3a\u672c\u6b21\u4f1a\u8bdd\u7d2f\u8ba1\u7684\u6539\u52a8\u8bb0\u5f55\uff08\u542b\u5df2\u91c7\u7eb3\u6761\u76ee\uff09\u3002`;
      } else {
        changeSummaryBody.textContent = semantic.intro;
      }
      if (changeSummaryList) {
        if (listCombined.length) {
          changeSummaryList.classList.remove("hidden");
          changeSummaryList.innerHTML = listCombined.map((line) => `<li>${esc(line)}</li>`).join("");
        } else {
          changeSummaryList.classList.add("hidden");
          changeSummaryList.innerHTML = "";
        }
      }
    }
    if (diffActions) {
      if (isPendingProposal) diffActions.classList.remove("hidden");
      else diffActions.classList.add("hidden");
    }
    if (reviewOriginal) reviewOriginal.textContent = String(diff.original || "");
    if (reviewSuggested) reviewSuggested.textContent = String(diff.proposed || "");
    if (reviewSelectionRef) {
      let ref = "\u6574\u7bc7\u62a5\u544a";
      if (!isPendingProposal && archivedDiff && archivedDiff.scopeLabel) {
        ref = archivedDiff.scopeLabel;
      } else if (diff.selection && Number.isFinite(diff.selection.start) && Number.isFinite(diff.selection.end)) {
        ref = getEditorLineRange(String(document.getElementById("reportEditorTextarea")?.value || ""), diff.selection.start, diff.selection.end).ref;
      }
      reviewSelectionRef.textContent = ref;
    }
    if (reviewDelta) {
      const lines = Array.isArray(diffSummary.preview) && diffSummary.preview.length
        ? diffSummary.preview
        : ["+ \u6539\u52a8\u5df2\u751f\u6210\uff0c\u8bf7\u5728\u4e2d\u95f4\u533a Diff \u67e5\u770b", "- \u539f\u6587\u4ecd\u5728 Preview\uff0c\u53ef\u968f\u65f6 Undo"];
      reviewDelta.innerHTML = lines.map((line) => `<li>${esc(line)}</li>`).join("");
    }
    if (reviewAdd) reviewAdd.textContent = `+${Number(diffSummary.addLines || 0)}`;
    if (reviewDel) reviewDel.textContent = `-${Number(diffSummary.delLines || 0)}`;
    updateReportEditorChangesBadge();
  }

  function updateCareerReportEditorSelectionInfo() {
    const info = document.getElementById("reportEditorSelectionInfo");
    if (!info) return;
    const selection = reportRuntime.editorSelection;
    const length = Math.max(0, Number(selection?.end || 0) - Number(selection?.start || 0));
    info.textContent = selection && length > 0
      ? `${selection.ref || "\u9009\u4e2d\u7247\u6bb5"}（${length} 字符），发送后将作为引用上下文附带给 AI。`
      : "\u672a\u9009\u4e2d\u5185\u5bb9\uff0c\u53d1\u8d77\u6da6\u8272\u65f6\u9ed8\u8ba4\u9488\u5bf9\u6574\u7bc7\u62a5\u544a\u3002";
    renderReportEditorPromptSelectionPills();
    renderReportEditorChatLog();
  }

  function clearCareerReportEditorDiff(options = {}) {
    const hadDiff = Boolean(reportRuntime.editorDiff);
    reportRuntime.editorDiff = null;
    renderReportEditorDiffPanel();
    if (!options.keepMode) {
      setCareerReportEditorMode("edit");
      setCareerReportEditorDocMode("preview");
    }
    if (!options.silent && hadDiff) {
      appendReportEditorMessage("assistant", "Undo", "\u5df2\u64a4\u9500\u5f53\u524d\u6da6\u8272\u63d0\u6848\uff0c\u6b63\u6587\u672a\u53d1\u751f\u53d8\u5316\u3002");
    }
    renderReportEditorChatLog();
    updateCareerReportEditorDirtyUi();
  }

  function applyCareerReportEditorDiff() {
    const textarea = document.getElementById("reportEditorTextarea");
    const diff = reportRuntime.editorDiff;
    if (!textarea || !diff) return;
    const taBefore = String(textarea.value || "");
    const scopeLabel =
      diff.selection && Number.isFinite(diff.selection.start) && Number.isFinite(diff.selection.end)
        ? getEditorLineRange(taBefore, diff.selection.start, diff.selection.end).ref
        : "\u6574\u7bc7\u62a5\u544a\u6b63\u6587";
    const blocks = Array.isArray(diff.diff_blocks) ? diff.diff_blocks : [];
    const stats = summarizeEditorDiffBlocks(blocks);
    const newBullets = buildFullChangeLogEntries(blocks);
    reportRuntime.appliedChangeBullets = [...(Array.isArray(reportRuntime.appliedChangeBullets) ? reportRuntime.appliedChangeBullets : []), ...newBullets].slice(-200);
    reportRuntime.cumulativeDiffLines = Number(reportRuntime.cumulativeDiffLines || 0) + Number(stats.addLines || 0) + Number(stats.delLines || 0);

    const archive = {
      original: String(diff.original || ""),
      proposed: String(diff.proposed || ""),
      diff_blocks: blocks.map((b) => ({
        type: String(b?.type || "equal"),
        lines: Array.isArray(b?.lines) ? [...b.lines] : []
      })),
      selection: diff.selection ? { start: diff.selection.start, end: diff.selection.end } : null,
      scopeLabel,
      settledAt: Date.now()
    };

    if (diff.selection && Number.isFinite(diff.selection.start) && Number.isFinite(diff.selection.end)) {
      textarea.value = `${textarea.value.slice(0, diff.selection.start)}${diff.proposed}${textarea.value.slice(diff.selection.end)}`;
    } else {
      textarea.value = String(diff.proposed || "");
    }

    reportRuntime.editorDiff = null;
    reportRuntime.editorDiffArchive = archive;
    renderReportEditorDiffPanel();
    clearCareerReportEditorSelection({ render: false });
    renderCareerReportEditorDocument();
    setCareerReportEditorMode("edit");
    setCareerReportEditorDocMode("preview");
    updateCareerReportEditorSelectionInfo();
    renderReportEditorChatLog();
    updateReportEditorChangesBadge();
    updateCareerReportEditorDirtyUi();
  }

  function applyCareerReportEditorPayload(payload) {
    reportRuntime.editorSource = payload;
    reportRuntime.editorDiff = null;
    reportRuntime.editorDiffArchive = null;
    reportRuntime.appliedChangeBullets = [];
    reportRuntime.cumulativeDiffLines = 0;
    reportRuntime.editorPolishPending = false;
    reportRuntime.editorConversation = [];
    reportRuntime.editorSelection = null;
    reportRuntime.editorSegments = [];
    reportRuntime.editorSelectedRange = null;
    reportRuntime.editorAnchorIndex = -1;
    reportRuntime.editorMode = "edit";
    reportRuntime.editorViewMode = "rendered";
    reportRuntime.editorDocMode = "preview";
    if (payload?.bundle && payload.bundle.meta) {
      window.appState.careerReport = cloneCareerReportBundleForAppState(payload.bundle);
      window.appState.reportReady = Boolean(payload.bundle.report_document);
      window.appState.reportGenerated = Boolean(payload.bundle.report_document);
    }
    const titleEl = document.getElementById("reportEditorTitle");
    const metaEl = document.getElementById("reportEditorMeta");
    const textarea = document.getElementById("reportEditorTextarea");
    const promptInput = document.getElementById("reportEditorPromptInput");
    const modelSelect = document.getElementById("reportEditorModelSelect");
    if (titleEl) titleEl.textContent = payload?.title || "\u804c\u4e1a\u62a5\u544a";
    if (metaEl) {
      metaEl.textContent = payload?.source_type === "formal_report"
        ? `\u6b63\u5f0f\u62a5\u544a | report_id ${payload?.report_id || "--"}`
        : `\u7f16\u8f91\u5feb\u7167 | snapshot_id ${payload?.snapshot_id || "--"}`;
    }
    const verBadge = document.getElementById("reportEditorVersionBadge");
    if (verBadge) {
      const sid = String(payload?.snapshot_id || "").trim();
      verBadge.textContent = sid ? "\u7f16\u8f91\u5feb\u7167" : "\u6b63\u5f0f\u62a5\u544a";
      verBadge.title = sid
        ? `snapshot_id: ${sid}`
        : `report_id: ${String(payload?.report_id || "--")}`;
    }
    if (textarea) textarea.value = String(payload?.markdown || "");
    reportRuntime.editorSavedMarkdown = normalizeEditorMarkdownBaseline(textarea ? textarea.value : "");
    if (promptInput) promptInput.value = "";
    if (modelSelect) {
      const remembered = String(window.localStorage?.getItem?.("career_report_polish_model") || "").trim();
      modelSelect.value = remembered || "deepseek-chat";
    }
    renderReportEditorSnapshotList(payload);
    updateReportEditorNavProgress(payload);
    renderCareerReportEditorDocument();
    renderReportEditorDiffPanel();
    updateCareerReportEditorSelectionInfo();
    renderReportEditorChatLog();
    autoResizeReportEditorPromptInput();
    setCareerReportEditorMode("edit");
    updateCareerReportEditorDirtyUi();
    ensureReportEditorBeforeUnloadListener();
  }

  async function loadCareerReportEditorSource(options = {}) {
    const reportId = String(options.reportId || window.appState?.careerReport?.meta?.report_id || "").trim();
    const snapshotId = String(options.snapshotId || "").trim();
    if (!reportId && !window.appState?.careerReport?.report_document) {
      throw new Error("\u5f53\u524d\u6ca1\u6709\u53ef\u7f16\u8f91\u7684\u804c\u4e1a\u62a5\u544a\u3002");
    }
    const cacheKey = `${reportId}|${snapshotId}`;
    const forceRefresh = Boolean(options.forceRefresh);

    if (!forceRefresh) {
      const inflight = reportRuntime.editorSourceInflight.get(cacheKey);
      if (inflight) return inflight;
    }

    if (!forceRefresh && reportRuntime.editorSourceLoadKey === cacheKey && reportRuntime.editorSource) {
      const ex = reportRuntime.editorSource;
      if (String(ex?.report_id || "") === reportId && String(ex?.snapshot_id || "") === snapshotId) {
        applyCareerReportEditorPayload(ex);
        return ex;
      }
    }

    const run = (async () => {
      const url = new URL(resolveUrl("/api/career-report/source"), window.location.origin);
      if (reportId) url.searchParams.set("report_id", reportId);
      if (snapshotId) url.searchParams.set("snapshot_id", snapshotId);
      const payload = await requestJsonSafe(`${url.pathname}${url.search}`);
      applyCareerReportEditorPayload(payload);
      reportRuntime.editorSourceLoadKey = cacheKey;
      return payload;
    })();

    if (!forceRefresh) {
      reportRuntime.editorSourceInflight.set(cacheKey, run);
      run.finally(() => {
        reportRuntime.editorSourceInflight.delete(cacheKey);
      });
    }

    return run;
  }

  /**
   * 打开润色页前尽量解析 report_id：界面已展示报告时，appState.careerReport 可能未带 meta，
   * 但 canonical / 版本列表 / tracker 里仍有 id，避免误判「无报告」。
   */
  function resolveCareerReportIdForEditor(preferred = "") {
    const direct = String(preferred || "").trim();
    if (direct) return direct;
    const cr = window.appState?.careerReport;
    const fromMeta = String(cr?.meta?.report_id || "").trim();
    if (fromMeta) return fromMeta;
    const canon = String(window.appState?.careerReportCanonicalId || "").trim();
    if (canon) return canon;
    const pack = getCareerReportVersionList();
    const fromPackCanon = String(pack?.canonicalReportId || "").trim();
    if (fromPackCanon) return fromPackCanon;
    const versions = Array.isArray(pack?.versions) ? pack.versions : [];
    for (let i = 0; i < versions.length; i += 1) {
      const rid = String(versions[i]?.report_id || "").trim();
      if (rid) return rid;
    }
    const tr = window.appState?.careerReportTracker;
    const fromTracker = String(tr?.report_id || "").trim();
    if (fromTracker) return fromTracker;
    const trVers = Array.isArray(tr?.versions) ? tr.versions : [];
    for (let j = 0; j < trVers.length; j += 1) {
      const rid = String(trVers[j]?.report_id || "").trim();
      if (rid) return rid;
    }
    return "";
  }

  async function openCareerReportEditor(options = {}) {
    const onPolishPage = Boolean(window.__CAREER_REPORT_POLISH_PAGE__);

    let reportId = resolveCareerReportIdForEditor(options.reportId);
    let cr = window.appState?.careerReport;
    let hasBundle = Boolean(cr?.report_document);

    if (!hasBundle && !reportId) {
      try {
        await loadCurrentCareerReport({ userCenterRefresh: false });
      } catch (error) {
        console.warn("openCareerReportEditor: loadCurrentCareerReport failed", error);
      }
      cr = window.appState?.careerReport;
      reportId = resolveCareerReportIdForEditor(options.reportId);
      hasBundle = Boolean(cr?.report_document);
    }

    if (!hasBundle && !reportId) {
      toast("\u6682\u65e0\u5b8c\u6574\u62a5\u544a", "\u8bf7\u5148\u751f\u6210\u804c\u4e1a\u62a5\u544a\uff0c\u518d\u8fdb\u5165\u5b8c\u6574\u62a5\u544a\u7684\u6da6\u8272\u4e0e\u7f16\u8f91\u89c6\u56fe\u3002", "warning", 2200);
      return;
    }

    const loadOpts = { ...options };
    if (!String(loadOpts.reportId || "").trim() && reportId) {
      loadOpts.reportId = reportId;
    }

    if (!onPolishPage) {
      // 站内页面路径不要用 resolveUrl：否则会经 resolveApiUrl 拼上 __API_BASE__（如 /api），变成 /api/user-center/... 导致 404
      const url = new URL("/user-center/career-report/polish.html", window.location.origin);
      const ridQ = String(loadOpts.reportId || "").trim();
      if (ridQ) url.searchParams.set("report_id", ridQ);
      const sidQ = String(loadOpts.snapshotId || "").trim();
      if (sidQ) url.searchParams.set("snapshot_id", sidQ);
      window.location.assign(url.toString());
      return;
    }

    const overlay = document.getElementById("reportEditorOverlay");
    if (!overlay) {
      toast(
        "\u65e0\u6cd5\u6253\u5f00\u7f16\u8f91\u5668",
        "\u9875\u9762\u672a\u52a0\u8f7d\u62a5\u544a\u7f16\u8f91\u5c42\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002",
        "error",
        2400
      );
      return;
    }
    const targetRidPre = String(loadOpts.reportId || "").trim();
    const targetSidPre = String(loadOpts.snapshotId || "").trim();
    const overlayAlreadyVisible = !overlay.classList.contains("hidden");
    const prevSrc = reportRuntime.editorSource;
    if (
      onPolishPage &&
      overlayAlreadyVisible &&
      prevSrc &&
      typeof prevSrc === "object" &&
      `${String(prevSrc.report_id || "").trim()}|${String(prevSrc.snapshot_id || "").trim()}` !== `${targetRidPre}|${targetSidPre}` &&
      isCareerReportEditorDirty()
    ) {
      if (
        !window.confirm(
          "\u5f53\u524d\u6b63\u6587\u6709\u672a\u4fdd\u5b58\u7684\u4fee\u6539\uff0c\u5207\u6362\u7248\u672c\u4f1a\u4e22\u5931\u8fd9\u4e9b\u66f4\u6539\u3002\u662f\u5426\u7ee7\u7eed\uff1f"
        )
      ) {
        return;
      }
    }
    reportRuntime.previousBodyOverflow = document.body.style.overflow || "";
    document.body.style.overflow = "hidden";
    overlay.classList.remove("hidden");
    const metaEl = document.getElementById("reportEditorMeta");
    if (metaEl) metaEl.textContent = "\u6b63\u5728\u52a0\u8f7d\u6e90\u6587\u7a3f\u2026";
    try {
      await loadCareerReportEditorSource(loadOpts);
      setReportEditorRailTab();
      setReportEditorRailView("chat");
      setCareerReportEditorMode("edit");
      ensureReportEditorBeforeUnloadListener();
    } catch (error) {
      overlay.classList.add("hidden");
      document.body.style.overflow = reportRuntime.previousBodyOverflow;
      const raw = String(error?.message || error || "").trim() || "\u52a0\u8f7d\u5931\u8d25";
      const msg = raw.length > 220 ? `${raw.slice(0, 220)}\u2026` : raw;
      toast("\u65e0\u6cd5\u6253\u5f00\u6da6\u8272\u754c\u9762", msg, "error", 3600);
    }
  }

  function closeCareerReportEditor() {
    if (isCareerReportEditorDirty()) {
      if (
        !window.confirm(
          "\u5f53\u524d\u7f16\u8f91\u5c1a\u672a\u4fdd\u5b58\u5230\u804c\u4e1a\u62a5\u544a\u6b63\u6587\uff0c\u5173\u95ed\u540e\u672a\u4fdd\u5b58\u7684\u4fee\u6539\u5c06\u4e22\u5931\u3002\u786e\u5b9a\u5173\u95ed\uff1f"
        )
      ) {
        return;
      }
    }
    if (window.__CAREER_REPORT_POLISH_PAGE__) {
      const rid = String(
        reportRuntime.editorSource?.report_id
          || window.appState?.careerReport?.meta?.report_id
          || new URLSearchParams(window.location.search).get("report_id")
          || ""
      ).trim();
      if (rid) {
        const back = new URL("/user-center", window.location.origin);
        back.searchParams.set("report_id", rid);
        back.hash = "#report-workspace";
        window.location.assign(back.toString());
      } else {
        const fallback = String(window.__CAREER_REPORT_POLISH_RETURN__ || "").trim();
        if (fallback) {
          window.location.assign(fallback);
        } else {
          const fb = new URL("/user-center", window.location.origin);
          fb.hash = "#report-workspace";
          window.location.assign(fb.toString());
        }
      }
      return;
    }
    const overlay = document.getElementById("reportEditorOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
    document.body.style.overflow = reportRuntime.previousBodyOverflow;
    setCareerReportEditorMode("edit");
  }

  const REPORT_EDITOR_QUICK_LABELS = {
    professional: "\u66f4\u4e13\u4e1a",
    concise: "\u66f4\u7cbe\u70bc",
    bullets: "\u8f6c\u8981\u70b9",
    evidence: "\u52a0\u5f3a\u8bba\u636e"
  };

  async function polishCareerReportEditorSelection(options = {}) {
    const opts = options && typeof options === "object" ? options : {};
    const quickAction = String(opts.quickAction || "").trim().toLowerCase();
    const source = reportRuntime.editorSource || {};
    const textarea = document.getElementById("reportEditorTextarea");
    const promptInput = document.getElementById("reportEditorPromptInput");
    const modelSelect = document.getElementById("reportEditorModelSelect");
    if (!textarea) return;
    const selection = reportRuntime.editorSelection;
    const targetText = selection?.text || textarea.value || "";
    const instruction = String(promptInput?.value || "").trim();
    const model = String(modelSelect?.value || "deepseek-chat").trim() || "deepseek-chat";
    if (window.localStorage?.setItem) {
      window.localStorage.setItem("career_report_polish_model", model);
    }
    if (quickAction && !(selection && String(selection.text || "").trim())) {
      toast(
        "\u8bf7\u5148\u9009\u4e2d\u6b63\u6587",
        "\u5728\u5de6\u4fa7\u62a5\u544a\u4e2d\u62d6\u52a8\u9009\u62e9\u9700\u8981\u4f18\u5316\u7684\u6bb5\u843d\uff0c\u518d\u70b9\u5feb\u6377\u6309\u94ae\u3002",
        "warning",
        2200
      );
      return;
    }
    if (!String(targetText).trim()) {
      toast("\u6682\u65e0\u53ef\u6da6\u8272\u5185\u5bb9", "\u8bf7\u5148\u9009\u62e9\u4e00\u6bb5\u6b63\u6587\uff0c\u6216\u786e\u4fdd\u7f16\u8f91\u533a\u91cc\u5df2\u6709\u62a5\u544a\u5185\u5bb9\u3002", "warning", 1800);
      return;
    }
    const selectionLabel = selection
      ? `${selection.ref || "\u9009\u4e2d\u7247\u6bb5"}`
      : "\u5f53\u524d\u6309\u6574\u7bc7\u62a5\u544a\u8fdb\u884c\u6da6\u8272";
    const quickLabel = quickAction ? REPORT_EDITOR_QUICK_LABELS[quickAction] || quickAction : "";
    if (quickAction && quickLabel) {
      appendReportEditorMessage("user", "\u4f60", quickLabel, "user", {
        pill: true,
        selectionRef: selection ? (selection.ref || selectionLabel || "") : "",
        selectionPreview: selection?.text
          ? `${Math.max(0, Number(selection.end || 0) - Number(selection.start || 0))} \u5b57\u7b26 \u00b7 \u6309\u884c\u9644\u5e26\u4e0a\u4e0b\u6587`
          : ""
      });
    } else {
      appendReportEditorMessage(
        "user",
        "Prompt",
        instruction
          ? instruction
          : "\u8bf7\u5e2e\u6211\u91cd\u5199\u8fd9\u90e8\u5206\uff0c\u4f46\u4e0d\u8981\u65b0\u589e\u4e8b\u5b9e\u3002",
        "user",
        {
          selectionRef: selection ? (selection.ref || selectionLabel || "") : "",
          selectionPreview: selection?.text
            ? `${Math.max(0, Number(selection.end || 0) - Number(selection.start || 0))} \u5b57\u7b26 \u00b7 \u6309\u884c\u9644\u5e26\u4e0a\u4e0b\u6587`
            : ""
        }
      );
    }
    reportRuntime.editorPolishPending = true;
    renderReportEditorChatLog();
    setReportEditorPolishBusy(true);
    let payload;
    try {
      payload = await requestJsonSafe("/api/career-report/polish", {
        method: "POST",
        body: {
          section_key: source.section_map?.[0]?.key || "",
          selection: selection?.text || "",
          text: selection ? "" : textarea.value,
          instruction,
          quick_action: quickAction || undefined,
          want_ai_summary: true,
          model,
          full_text: textarea.value || "",
          selection_start: selection?.start,
          selection_end: selection?.end
        }
      });
    } finally {
      reportRuntime.editorPolishPending = false;
      setReportEditorPolishBusy(false);
    }
    const diffBlocks = Array.isArray(payload?.diff_blocks) ? payload.diff_blocks : [];
    reportRuntime.editorDiffArchive = null;
    reportRuntime.editorDiff = {
      original: payload?.original || targetText,
      proposed: payload?.proposed || payload?.polished || "",
      diff_blocks: diffBlocks,
      selection: selection ? { start: selection.start, end: selection.end } : null
    };
    const diffSummary = summarizeEditorDiffBlocks(diffBlocks);
    const summaryFromApi = String(payload?.action_summary || "").trim();
    const assistantBody = summaryFromApi
      ? `${summaryFromApi}\n\n\uff08\u5df2\u751f\u6210\u63d0\u6848\uff0c\u8bf7\u5207\u81f3\u4e2d\u95f4\u533a Diff \u67e5\u770b\u884c\u7ea7\u5bf9\u7167\uff1b\u786e\u8ba4\u540e\u53ef\u300c\u5168\u90e8\u91c7\u7eb3\u300d\u6216\u300c\u64a4\u9500\u63d0\u6848\u300d\u3002\uff09`
      : selection
        ? `\u5df2\u751f\u6210 ${selection.ref || "\u9009\u4e2d\u7247\u6bb5"} \u7684\u6da6\u8272\u63d0\u6848\uff08${payload?.model || model}\uff09\u3002\u8bf7\u5207\u6362\u5230\u4e2d\u95f4\u533a Diff \u89c6\u56fe\u67e5\u770b\u884c\u7ea7\u5bf9\u7167\uff0c\u5728\u53f3\u4fa7\u9605\u8bfb\u6458\u8981\u540e\u9009\u62e9\u300c\u5168\u90e8\u91c7\u7eb3\u300d\u6216\u300c\u64a4\u9500\u63d0\u6848\u300d\u3002`
        : `\u5df2\u751f\u6210\u6574\u7bc7\u62a5\u544a\u7684\u6da6\u8272\u63d0\u6848\uff08${payload?.model || model}\uff09\u3002\u8bf7\u5207\u6362\u5230\u4e2d\u95f4\u533a Diff \u89c6\u56fe\u67e5\u770b\u884c\u7ea7\u5bf9\u7167\uff0c\u5728\u53f3\u4fa7\u9605\u8bfb\u6458\u8981\u540e\u9009\u62e9\u300c\u5168\u90e8\u91c7\u7eb3\u300d\u6216\u300c\u64a4\u9500\u63d0\u6848\u300d\u3002`;
    appendReportEditorMessage(
      "assistant",
      "AI \u52a9\u624b",
      assistantBody,
      "assistant",
      { diffSummary }
    );
    renderReportEditorDiffPanel();
    renderReportEditorChatLog();
    setReportEditorRailView("chat");
    setCareerReportEditorMode("edit");
    setCareerReportEditorDocMode("diff");
    toast("\u6da6\u8272\u63d0\u6848\u5df2\u751f\u6210", "\u5df2\u5207\u81f3 Diff \u89c6\u56fe\uff1b\u8bf7\u68c0\u67e5\u5bf9\u7167\u540e\u518d Keep All \u6216\u64a4\u9500\u3002", "success", 1800);
  }

  async function saveCareerReportEditorSnapshot() {
    if (reportRuntime.editorSavePending) {
      return;
    }
    const source = reportRuntime.editorSource || {};
    const textarea = document.getElementById("reportEditorTextarea");
    const markdown = String(textarea?.value || "").trim();
    if (!markdown) {
      toast("\u65e0\u6cd5\u4fdd\u5b58", "\u5f53\u524d\u7f16\u8f91\u533a\u4e3a\u7a7a\u3002", "warning", 1800);
      return;
    }
    setCareerReportEditorSavePending(true);
    const label = source?.snapshot_id
      ? String(source?.title || "\u7f16\u8f91\u5feb\u7167").trim()
      : `\u7f16\u8f91\u5feb\u7167 ${new Date().toLocaleString("zh-CN")}`;
    try {
      const payload = await requestJsonSafe("/api/career-report/snapshot/save", {
        method: "POST",
        body: {
          report_id: source.report_id || window.appState?.careerReport?.meta?.report_id || "",
          snapshot_id: source.snapshot_id || "",
          source: source.source_type === "formal_report" ? "manual" : (source.source_type || "manual"),
          title: label,
          markdown,
          diff_blocks: reportRuntime.editorDiff?.diff_blocks || reportRuntime.editorDiffArchive?.diff_blocks || []
        }
      });
      const formalUpdated = Boolean(payload?.formal_report_updated);
      if (formalUpdated) {
        try {
          await loadCurrentCareerReport({ userCenterRefresh: true });
        } catch (error) {
          console.warn("saveCareerReportEditorSnapshot: refresh bundle failed", error);
        }
      }
      reportRuntime.editorSavedMarkdown = normalizeEditorMarkdownBaseline(
        String(document.getElementById("reportEditorTextarea")?.value || "")
      );
      updateCareerReportEditorDirtyUi();
      reportRuntime.editorSource = {
        ...(reportRuntime.editorSource || {}),
        ...(payload?.snapshot || {}),
        report_id: source.report_id || window.appState?.careerReport?.meta?.report_id || "",
        source_type: payload?.snapshot?.snapshot_id ? "snapshot" : (payload?.snapshot?.source || "manual")
      };
      if (window.appState?.careerReport) {
        window.appState.careerReport.draft_snapshots = Array.isArray(payload?.draft_snapshots) ? payload.draft_snapshots : [];
      }
      clearCareerReportEditorDiff({ silent: true });
      appendReportEditorMessage(
        "assistant",
        "Snapshot",
        formalUpdated
          ? `\u5df2\u4fdd\u5b58\u5e76\u5c06\u6b64\u7a3f\u540c\u6b65\u4e3a\u804c\u4e1a\u62a5\u544a\u6b63\u6587\uff08\u9605\u89c8\u5ba4\u4e0b\u6b21\u6253\u5f00\u5373\u4e3a\u6b64\u7248\u672c\uff09\u3002`
          : `\u5df2\u5c06\u5f53\u524d\u7f16\u8f91\u5185\u5bb9\u4fdd\u5b58\u4e3a\u5feb\u7167\uff1a${label}`
      );
      renderReportEditorSnapshotList(reportRuntime.editorSource);
      renderReportEditorSectionMap({
        ...reportRuntime.editorSource,
        markdown: document.getElementById("reportEditorTextarea")?.value || ""
      });
      renderReportEditorChatLog();
      window.renderUserCenterDashboard?.();
      toast(
        formalUpdated ? "\u5df2\u4fdd\u5b58" : "\u5feb\u7167\u5df2\u4fdd\u5b58",
        formalUpdated
          ? "\u6b63\u6587\u5df2\u66f4\u65b0\uff0c\u804c\u4e1a\u62a5\u544a\u9605\u89c8\u5c06\u663e\u793a\u6b64\u7a3f\u3002"
          : `\u5df2\u6309\u300c${label}\u300d\u4fdd\u5b58\u5f53\u524d\u7f16\u8f91\u5185\u5bb9\u3002`,
        "success",
        2200
      );
    } finally {
      setCareerReportEditorSavePending(false);
    }
  }

  function triggerCareerReportEditorSave(event) {
    if (event?.preventDefault) event.preventDefault();
    if (reportRuntime.editorSavePending) return;
    void saveCareerReportEditorSnapshot().catch((error) => {
      toast("\u4fdd\u5b58\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
    });
  }

  window.triggerCareerReportEditorSave = triggerCareerReportEditorSave;

  async function downloadCareerReport(url, format) {
    const typography = window.CareerReportReader?.getTypography();
    if (typography) url.searchParams.set("typography", JSON.stringify(typography));
    const types = { pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      md: "text/markdown", html: "text/html" };
    if (reportRuntime.exportPending || !Object.hasOwn(types, format)) return false;
    const buttons = ["userCenterExportPdfBtn", "userCenterExportDocxBtn"].map((id) => document.getElementById(id)).filter(Boolean);
    const previousDisabled = buttons.map((button) => button.disabled);
    const owner = currentUser()?.username;
    reportRuntime.exportPending = true;
    buttons.forEach((button) => { button.disabled = true; });
    toast("正在导出", `正在生成 ${format.toUpperCase()} 文件，请稍候。`, "info", 2500);
    try {
      const response = await fetch(url.toString(), { credentials: "include", headers: { Accept: types[format] } });
      const mime = String(response.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
      if (!response.ok || response.redirected || mime !== types[format]) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.message || (response.status === 401 || response.redirected
          ? "登录状态已失效，请重新登录后导出。" : `导出失败（HTTP ${response.status}），请稍后重试。`));
      }
      const blob = await response.blob();
      if (!blob.size || (format === "pdf" && await blob.slice(0, 5).text() !== "%PDF-")) {
        throw new Error("服务器未返回有效文件，请重试导出。");
      }
      if (currentUser()?.username !== owner) return false;
      const disposition = response.headers.get("Content-Disposition") || "";
      const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      const plainName = disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
      let filename = plainName?.[1] || plainName?.[2] || `职业规划报告.${format}`;
      if (utf8Name) {
        try { filename = decodeURIComponent(utf8Name); } catch { /* Keep the safe fallback. */ }
      }
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename.replace(/[\\/\x00-\x1f]/g, "-");
      try {
        document.body.appendChild(anchor);
        anchor.click();
      } finally {
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
      }
      toast("文件已准备好", `${format.toUpperCase()} 文件已开始下载。`, "success", 2200);
      return true;
    } catch (error) {
      if (currentUser()?.username === owner) toast("导出失败", error.message || "请稍后重试。", "error", 4500);
      return false;
    } finally {
      reportRuntime.exportPending = false;
      buttons.forEach((button, index) => { button.disabled = previousDisabled[index]; });
    }
  }

  async function exportCareerReportSource(format = "docx") {
    const source = reportRuntime.editorSource || {};
    if (source?.source_type !== "formal_report" && !source?.snapshot_id) {
      toast("\u8bf7\u5148\u4fdd\u5b58\u5feb\u7167", "\u672a\u4fdd\u5b58\u7684\u7f16\u8f91\u5185\u5bb9\u4e0d\u80fd\u76f4\u63a5\u5bfc\u51fa\uff0c\u8bf7\u5148\u4fdd\u5b58\u4e3a\u7f16\u8f91\u5feb\u7167\u3002", "warning", 2200);
      return;
    }
    const url = new URL(resolveUrl("/api/career-report/export"), window.location.origin);
    url.searchParams.set("format", String(format || "docx").trim().toLowerCase());
    url.searchParams.set("report_id", source.report_id || window.appState?.careerReport?.meta?.report_id || "");
    if (source?.snapshot_id) {
      url.searchParams.set("snapshot_id", source.snapshot_id);
    }
    return downloadCareerReport(url, url.searchParams.get("format"));
  }

  const REPORT_EDITOR_LAYOUT_KEY = "career_report_editor_col_layout_v1";

  function applyReportEditorLayoutVars(shell, layout) {
    if (!shell || !layout || typeof layout !== "object") return;
    const nav = Number(layout.nav);
    const rail = Number(layout.rail);
    const split = Number(layout.split);
    if (Number.isFinite(nav) && nav >= 160 && nav <= 520) {
      shell.style.setProperty("--re-nav-w", `${Math.round(nav)}px`);
    }
    if (Number.isFinite(rail) && rail >= 200 && rail <= 640) {
      shell.style.setProperty("--re-rail-w", `${Math.round(rail)}px`);
    }
    if (Number.isFinite(split) && split >= 22 && split <= 78) {
      shell.style.setProperty("--re-compare-split-pct", `${Math.round(split * 100) / 100}%`);
    }
  }

  function readReportEditorLayoutFromStorage() {
    try {
      const raw = window.localStorage?.getItem?.(REPORT_EDITOR_LAYOUT_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function persistReportEditorLayout(shell) {
    if (!shell) return;
    const cs = getComputedStyle(shell);
    const nav = parseFloat(cs.getPropertyValue("--re-nav-w")) || 240;
    const rail = parseFloat(cs.getPropertyValue("--re-rail-w")) || 300;
    const sp = cs.getPropertyValue("--re-compare-split-pct").trim();
    const split = parseFloat(sp) || 50;
    try {
      window.localStorage?.setItem?.(
        REPORT_EDITOR_LAYOUT_KEY,
        JSON.stringify({
          nav: Math.round(nav),
          rail: Math.round(rail),
          split: Math.round(split * 10) / 10
        })
      );
    } catch (_) {
      /* ignore quota */
    }
  }

  function initReportEditorColumnResizers() {
    const shell = document.querySelector(".report-editor-shell.report-editor-shell--polish-v2");
    if (!shell || shell.dataset.reportEditorResizersBound === "1") return;
    shell.dataset.reportEditorResizersBound = "1";
    applyReportEditorLayoutVars(shell, readReportEditorLayoutFromStorage());

    const getBody = () => shell.querySelector(".report-editor-body");
    const getNav = () => shell.querySelector(".report-editor-nav-rail");
    const getRail = () => shell.querySelector(".report-editor-rail");
    function dragStyle(on) {
      document.body.style.cursor = on ? "col-resize" : "";
      document.body.style.userSelect = on ? "none" : "";
    }

    const navHandle = document.getElementById("reportEditorResizerNav");
    if (navHandle) {
      navHandle.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        const b = getBody();
        const nav = getNav();
        if (!b || !nav) return;
        const startX = e.clientX;
        const startNav = nav.getBoundingClientRect().width;
        const maxNav = Math.min(520, b.getBoundingClientRect().width * 0.48);
        navHandle.classList.add("is-dragging");
        dragStyle(true);
        const onMove = (ev) => {
          const dx = ev.clientX - startX;
          let next = startNav + dx;
          next = Math.max(160, Math.min(next, maxNav));
          shell.style.setProperty("--re-nav-w", `${Math.round(next)}px`);
        };
        const onUp = () => {
          navHandle.classList.remove("is-dragging");
          dragStyle(false);
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          persistReportEditorLayout(shell);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    }

    const railHandle = document.getElementById("reportEditorResizerRail");
    if (railHandle) {
      const onRailPointerDown = (e) => {
        if (!e.isPrimary || e.button !== 0) return;
        e.preventDefault();
        const b = getBody();
        const rail = getRail();
        if (!b || !rail) return;
        const startX = e.clientX;
        const cs = getComputedStyle(shell);
        const parsed = parseFloat(cs.getPropertyValue("--re-rail-w"));
        const startRail = Number.isFinite(parsed) && parsed > 0 ? parsed : rail.getBoundingClientRect().width;
        const maxRail = Math.min(640, b.getBoundingClientRect().width * 0.55);
        railHandle.classList.add("is-dragging");
        dragStyle(true);
        try {
          railHandle.setPointerCapture(e.pointerId);
        } catch (_) {
          /* ignore */
        }
        const onMove = (ev) => {
          if (ev.pointerId !== e.pointerId) return;
          const dx = ev.clientX - startX;
          let next = startRail + dx;
          next = Math.max(200, Math.min(next, maxRail));
          shell.style.setProperty("--re-rail-w", `${Math.round(next)}px`);
        };
        const onUp = (ev) => {
          if (ev && ev.pointerId !== e.pointerId) return;
          try {
            railHandle.releasePointerCapture(e.pointerId);
          } catch (_) {
            /* ignore */
          }
          railHandle.classList.remove("is-dragging");
          dragStyle(false);
          document.removeEventListener("pointermove", onMove);
          document.removeEventListener("pointerup", onUp);
          document.removeEventListener("pointercancel", onUp);
          persistReportEditorLayout(shell);
        };
        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onUp);
        document.addEventListener("pointercancel", onUp);
      };
      railHandle.addEventListener("pointerdown", onRailPointerDown);
    }

  }

  function bindCareerReportEditorEvents() {
    if (reportRuntime.editorEventsBound) return;
    reportRuntime.editorEventsBound = true;
    const promptInput = document.getElementById("reportEditorPromptInput");
    const renderedDoc = document.getElementById("reportEditorRenderedDoc");
    const textarea = document.getElementById("reportEditorTextarea");
    const runPolish = () => {
      void polishCareerReportEditorSelection({}).catch((error) => {
        toast("\u6da6\u8272\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
      });
    };
    document.querySelectorAll("[data-editor-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextMode = String(button.dataset.editorMode || "").trim().toLowerCase();
        if (nextMode === "review" && !reportRuntime.editorDiff && !reportRuntime.editorDiffArchive) {
          toast("\u6682\u65e0\u53ef\u5ba1\u9605\u7684\u6539\u52a8", "\u8bf7\u5148\u53d1\u9001\u6da6\u8272\u8bf7\u6c42\uff0c\u751f\u6210 diff \u540e\u518d\u8fdb\u5165 Review\u3002", "warning", 2000);
          return;
        }
        setCareerReportEditorMode(nextMode);
      });
    });
    document.querySelectorAll(".report-editor-doc-mode-btn[data-doc-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        const next = String(button.getAttribute("data-doc-mode") || "").trim().toLowerCase();
        if (next) setCareerReportEditorDocMode(next);
      });
    });
    document.getElementById("reportEditorBackToReportBtn")?.addEventListener("click", () => {
      closeCareerReportEditor();
    });
    document.getElementById("reportEditorBackToEditBtn")?.addEventListener("click", () => {
      setCareerReportEditorMode("edit");
    });
    document.getElementById("reportEditorUndoBtn")?.addEventListener("click", () => {
      clearCareerReportEditorDiff();
    });
    document.getElementById("reportEditorKeepAllBtn")?.addEventListener("click", () => {
      applyCareerReportEditorDiff();
    });
    document.getElementById("reportEditorUndoInlineBtn")?.addEventListener("click", () => {
      clearCareerReportEditorDiff();
    });
    document.getElementById("reportEditorKeepAllInlineBtn")?.addEventListener("click", () => {
      applyCareerReportEditorDiff();
    });
    document.getElementById("reportEditorClearSelectionBtn")?.addEventListener("click", () => {
      clearCareerReportEditorSelection();
    });
    document.getElementById("reportEditorViewToggleBtn")?.addEventListener("click", () => {
      setCareerReportEditorDocMode(reportRuntime.editorDocMode === "edit" ? "preview" : "edit");
    });
    document.getElementById("reportEditorPromptSendBtn")?.addEventListener("click", runPolish);
    document.getElementById("reportEditorPromptSendIconBtn")?.addEventListener("click", runPolish);
    document.getElementById("reportEditorTabChat")?.addEventListener("click", () => setReportEditorRailView("chat"));
    document.getElementById("reportEditorTabChanges")?.addEventListener("click", () => setReportEditorRailView("changes"));
    document.querySelectorAll("[data-quick-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const qa = String(btn.getAttribute("data-quick-action") || "").trim().toLowerCase();
        if (!qa) return;
        void polishCareerReportEditorSelection({ quickAction: qa }).catch((error) => {
          toast("\u6da6\u8272\u5931\u8d25", error.message || "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002", "error", 2200);
        });
      });
    });
    document.getElementById("reportEditorClearPromptBtn")?.addEventListener("click", () => {
      if (promptInput) {
        promptInput.value = "";
        promptInput.focus();
        autoResizeReportEditorPromptInput();
      }
      appendReportEditorMessage("system", "Prompt", "\u5df2\u6e05\u7a7a\u5f53\u524d\u6da6\u8272\u6307\u4ee4\u3002", "system");
      renderReportEditorChatLog();
    });
    promptInput?.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runPolish();
      }
    });
    promptInput?.addEventListener("input", () => {
      autoResizeReportEditorPromptInput();
    });
    renderedDoc?.addEventListener("mouseup", () => {
      window.setTimeout(() => {
        syncCareerReportEditorSelectionFromRendered();
      }, 0);
    });
    renderedDoc?.addEventListener("dblclick", () => {
      setCareerReportEditorViewMode("markdown");
      const selection = reportRuntime.editorSelection;
      if (textarea && selection && Number.isFinite(selection.start) && Number.isFinite(selection.end)) {
        textarea.setSelectionRange(selection.start, selection.end);
      }
    });
    textarea?.addEventListener("mouseup", syncCareerReportEditorSelectionFromTextarea);
    textarea?.addEventListener("keyup", syncCareerReportEditorSelectionFromTextarea);
    textarea?.addEventListener("input", () => {
      renderCareerReportEditorDocument();
      syncCareerReportEditorSelectionFromTextarea();
      updateCareerReportEditorDirtyUi();
    });
    textarea?.addEventListener("dblclick", () => {
      setCareerReportEditorViewMode("rendered");
    });
    document.getElementById("reportEditorSaveBtn")?.addEventListener("click", triggerCareerReportEditorSave);
    document.getElementById("reportEditorTocSearch")?.addEventListener("input", (event) => {
      const q = String(event.target?.value || "").trim().toLowerCase();
      const host = document.getElementById("reportEditorSectionMap");
      if (!host) return;
      host.querySelectorAll(".tree-toc-branch").forEach((branch) => {
        const text = (branch.textContent || "").toLowerCase().replace(/\s+/g, " ");
        branch.style.display = !q || text.includes(q) ? "" : "none";
      });
      host.querySelectorAll(".cr-md-toc-branch").forEach((branch) => {
        const text = (branch.textContent || "").toLowerCase().replace(/\s+/g, " ");
        branch.style.display = !q || text.includes(q) ? "" : "none";
      });
      host.querySelectorAll(".tree-item.report-editor-section-item").forEach((item) => {
        const text = (item.textContent || "").toLowerCase().replace(/\s+/g, " ");
        item.style.display = !q || text.includes(q) ? "" : "none";
      });
    });
    document.getElementById("reportEditorTocToggleAll")?.addEventListener("click", () => {
      const host = document.getElementById("reportEditorSectionMap");
      if (!host) return;
      const treeBranches = host.querySelectorAll(".tree-toc-branch");
      if (treeBranches.length) {
        const allChildren = host.querySelectorAll(".tree-children");
        const anyCollapsed = Array.from(allChildren).some((tc) => tc.classList.contains("collapsed"));
        allChildren.forEach((tc) => {
          if (anyCollapsed) tc.classList.remove("collapsed");
          else tc.classList.add("collapsed");
        });
        host.querySelectorAll("button.collapse-icon").forEach((btn) => {
          const br = btn.closest(".tree-toc-branch");
          const subs = br?.querySelector(".tree-children");
          if (!subs) return;
          const collapsed = subs.classList.contains("collapsed");
          btn.classList.toggle("open", !collapsed);
          btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
        });
        return;
      }
      const branches = host.querySelectorAll(".cr-md-toc-branch");
      if (!branches.length) return;
      const anyCollapsed = Array.from(branches).some((b) => !b.classList.contains("is-open"));
      branches.forEach((branch) => {
        const subs = branch.querySelector(".cr-md-toc-subs");
        const btn = branch.querySelector(".cr-md-toc-toggle");
        if (anyCollapsed) {
          branch.classList.add("is-open");
          if (subs) subs.hidden = false;
          btn?.classList.add("is-open");
          btn?.setAttribute("aria-expanded", "true");
        } else {
          branch.classList.remove("is-open");
          if (subs) subs.hidden = true;
          btn?.classList.remove("is-open");
          btn?.setAttribute("aria-expanded", "false");
        }
      });
    });
    document.addEventListener(
      "keydown",
      (event) => {
        const overlay = document.getElementById("reportEditorOverlay");
        if (!overlay || overlay.classList.contains("hidden")) return;
        if ((event.metaKey || event.ctrlKey) && event.key === "p") {
          const input = document.getElementById("reportEditorTocSearch");
          if (!input) return;
          event.preventDefault();
          input.focus();
        }
      },
      true
    );
    document.getElementById("reportEditorOverlay")?.addEventListener("click", (event) => {
      if (event.target?.id === "reportEditorOverlay") {
        closeCareerReportEditor();
      }
    });
    ensureReportEditorBeforeUnloadListener();
    autoResizeReportEditorPromptInput();
    initReportEditorColumnResizers();
  }

  async function fetchCareerReportVersion(reportId) {
    const safeId = String(reportId || "").trim();
    if (!safeId) return null;
    const payload = await requestJsonSafe(`/api/career-report/version?report_id=${encodeURIComponent(safeId)}`);
    applyCareerReportState(payload.data || null, payload.tracker || null, getCareerReportStateSafe(), {
      historical: true,
      canonicalReportId: window.appState?.careerReportCanonicalId || getCareerReportVersionList().canonicalReportId,
      userCenterRefresh: true
    });
    return payload;
  }

  async function restoreLatestCareerReportView() {
    const payload = await loadCurrentCareerReport({ userCenterRefresh: true });
    renderReportViewer();
    return payload;
  }

  function setCareerReportFocusRole(roleId) {
    const safeRoleId = String(roleId || "").trim();
    if (!safeRoleId) return;
    ensureAppState();
    window.appState.focusedRoleId = safeRoleId;
    scheduleRender(true);
    const roleName = window.jobNameMap?.[safeRoleId] || safeRoleId;
    toast("已切换主岗位", `下次生成职业报告时将优先使用 ${roleName}。`, "success", 1800);
  }

  function saveReport() {
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无可保存报告", "请先生成完整职业报告。", "warning", 1800);
      return;
    }
    if (window.appState?.careerReportViewingHistorical) {
      toast("历史版本已归档", "当前查看的是历史报告，系统已自动保存该版本。", "info", 1800);
      return;
    }
    toast("报告已自动保存", "每次生成完成后，系统都会自动写入新的报告版本。", "success", 2000);
  }

  async function exportReport(format = "pdf") {
    if (!window.appState?.careerReport?.report_document) {
      toast("暂无可导出报告", "请先生成完整职业报告。", "warning", 1800);
      return;
    }
    const normalized = String(format || "pdf").trim().toLowerCase();
    const allowed = new Set(["md", "docx", "html", "pdf"]);
    const exportFormat = allowed.has(normalized) ? normalized : "pdf";
    const reportId = String(window.appState?.careerReport?.meta?.report_id || "").trim();
    const url = new URL(resolveUrl("/api/career-report/export"), window.location.origin);
    url.searchParams.set("format", exportFormat);
    if (reportId) url.searchParams.set("report_id", reportId);
    return downloadCareerReport(url, exportFormat);
  }

  function normalizeAvatarState(raw) {
    if (!raw || typeof raw !== "object") return null;
    const imageUrl = String(raw.image_url || "").trim();
    if (!imageUrl) return null;
    return {
      source: "uploaded",
      image_url: imageUrl,
      file_name: String(raw.file_name || "").trim(),
      updated_at: String(raw.updated_at || "").trim()
    };
  }

  function applyAvatarToElement(element, avatarState, user) {
    if (!element) return;
    const displayName = user?.display_name || user?.displayName || user?.username || "U";
    const fallback = avatarState ? displayName.charAt(0).toUpperCase() : (user?.role === "super_admin" ? "管" : displayName.charAt(0).toUpperCase());

    element.style.borderRadius = "50%";
    element.style.overflow = "hidden";

    if (avatarState?.image_url) {
      element.textContent = "";
      element.style.backgroundImage = `url("${avatarState.image_url.replace(/"/g, "%22")}")`;
      element.style.backgroundSize = "cover";
      element.style.backgroundPosition = "center";
      element.style.backgroundRepeat = "no-repeat";
      element.style.color = "transparent";
      return;
    }

    element.textContent = fallback;
    element.style.backgroundImage = "";
    element.style.backgroundSize = "";
    element.style.backgroundPosition = "";
    element.style.backgroundRepeat = "";
    element.style.color = "";
  }

  function renderTopbarAvatar() {
    const user = currentUser();
    const avatar = avatarRuntime.state;
    document.querySelectorAll("#currentUserAvatar").forEach((el) => {
      applyAvatarToElement(el, avatar, user);
    });
  }

  function getAccountAvatarState() {
    return avatarRuntime.state;
  }

  async function loadAccountAvatarState(force = false) {
    if (!isAuthenticated()) {
      avatarRuntime.username = "";
      avatarRuntime.state = null;
      renderTopbarAvatar();
      return null;
    }

    const user = currentUser();
    const username = String(user?.username || "").trim();
    if (!force && avatarRuntime.username === username) {
      renderTopbarAvatar();
      return avatarRuntime.state;
    }

    try {
      const data = typeof window.fetchScopedUserState === "function"
        ? await window.fetchScopedUserState("account_avatar", force)
        : null;
      avatarRuntime.username = username;
      avatarRuntime.state = normalizeAvatarState(data);
    } catch (error) {
      console.warn("load account avatar failed", error);
      avatarRuntime.username = username;
      avatarRuntime.state = null;
    }

    renderTopbarAvatar();
    return avatarRuntime.state;
  }

  function getPlanStorageKey() {
    const username = String(currentUser()?.username || "guest").trim().toLowerCase() || "guest";
    return `${PLAN_STORAGE_PREFIX}${username}`;
  }

  function getPlanProgressStorageKey() {
    const username = String(currentUser()?.username || "guest").trim().toLowerCase() || "guest";
    return `${PLAN_PROGRESS_PREFIX}${username}`;
  }

  function readPlans() {
    try {
      const parsed = JSON.parse(localStorage.getItem(getPlanStorageKey()) || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  function readPlanProgress() {
    const fallback = {
      streak: 0,
      best_streak: 0,
      xp: 0,
      last_checkin: "",
      active_days: {}
    };
    try {
      const parsed = JSON.parse(localStorage.getItem(getPlanProgressStorageKey()) || "null");
      if (!parsed || typeof parsed !== "object") return fallback;
      return {
        streak: Math.max(0, Number(parsed.streak || 0)),
        best_streak: Math.max(0, Number(parsed.best_streak || 0)),
        xp: Math.max(0, Number(parsed.xp || 0)),
        last_checkin: String(parsed.last_checkin || "").trim(),
        active_days: parsed.active_days && typeof parsed.active_days === "object" ? parsed.active_days : {}
      };
    } catch (_) {
      return fallback;
    }
  }

  function writePlanProgress(progress) {
    try {
      localStorage.setItem(getPlanProgressStorageKey(), JSON.stringify(progress));
    } catch (_) {
      // ignore storage failures
    }
  }

  function dayKey(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function parseDayKey(value) {
    if (!value) return null;
    const safe = String(value || "").trim();
    const parsed = new Date(`${safe}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  function isSameDay(left, right) {
    return left && right && dayKey(left) === dayKey(right);
  }

  function addDays(date, delta) {
    const next = new Date(date);
    next.setDate(next.getDate() + delta);
    return next;
  }

  function computePlanTaskStats() {
    const plans = readPlans();
    let total = 0;
    let done = 0;
    plans.forEach((plan) => {
      const items = Array.isArray(plan?.items) ? plan.items : [];
      total += items.length;
      done += items.filter((item) => item?.done).length;
    });
    return { total, done };
  }

  function computeUnlockedBadges(progress, doneCount) {
    return [
      { id: "start", name: "开始行动", unlocked: doneCount >= 1 },
      { id: "streak3", name: "连击 3 天", unlocked: progress.streak >= 3 },
      { id: "streak7", name: "连击 7 天", unlocked: progress.best_streak >= 7 },
      { id: "xp100", name: "累计 100 XP", unlocked: progress.xp >= 100 }
    ];
  }

  function renderWeekStrip(progress) {
    const host = document.getElementById("lpWeekStrip");
    if (!host) return;
    const labels = ["一", "二", "三", "四", "五", "六", "日"];
    const today = new Date();
    const monday = addDays(today, 1 - (today.getDay() || 7));
    host.innerHTML = labels.map((label, index) => {
      const date = addDays(monday, index);
      const key = dayKey(date);
      const done = Boolean(progress.active_days[key]);
      const isToday = isSameDay(date, today);
      const isFuture = date > today;
      return `
        <div class="lp-week-day${done ? " done" : ""}${isToday ? " today" : ""}${isFuture ? " future" : ""}">
          <div class="lp-week-dot"></div>
          <div class="lp-week-label">${label}</div>
        </div>
      `;
    }).join("");
  }

  function renderHeatmap(progress) {
    const host = document.getElementById("lpHeatmap");
    if (!host) return;
    const today = new Date();
    host.innerHTML = Array.from({ length: 28 }, (_, index) => {
      const date = addDays(today, index - 27);
      const key = dayKey(date);
      const active = Boolean(progress.active_days[key]);
      return `<span class="lp-heatmap-cell${active ? " active" : ""}" title="${esc(key)}"></span>`;
    }).join("");
  }

  function renderBadgeGrid(progress, doneCount) {
    const host = document.getElementById("lpBadgeGrid");
    if (!host) return;
    const badges = computeUnlockedBadges(progress, doneCount);
    host.innerHTML = badges.map((badge) => `
      <div class="lp-badge-item ${badge.unlocked ? "unlocked" : "locked"}">
        <div class="lp-badge-icon">${badge.unlocked ? "OK" : "--"}</div>
        <div class="lp-badge-name">${esc(badge.name)}</div>
      </div>
    `).join("");

    const unlockedCount = badges.filter((item) => item.unlocked).length;
    const statBadges = document.getElementById("upStatBadges");
    if (statBadges) statBadges.textContent = String(unlockedCount);
  }

  function updatePlanWidgets() {
    const progress = readPlanProgress();
    const stats = computePlanTaskStats();
    const level = Math.max(1, Math.floor(progress.xp / 100) + 1);
    const currentXp = progress.xp % 100;
    const checkedToday = Boolean(progress.last_checkin && isSameDay(parseDayKey(progress.last_checkin), new Date()));

    const streakCount = document.getElementById("lpStreakCount");
    const streakBest = document.getElementById("lpStreakBest");
    const streakIcon = document.getElementById("lpStreakIcon");
    const levelTag = document.getElementById("lpLevel");
    const xpValue = document.getElementById("lpXP");
    const xpNext = document.getElementById("lpXPNext");
    const xpFill = document.getElementById("lpXPFill");
    const checkinBtn = document.getElementById("lpCheckinBtn");
    const checkinHint = document.getElementById("lpCheckinHint");
    const statStreak = document.getElementById("upStatStreak");
    const statXp = document.getElementById("upStatXP");
    const statDone = document.getElementById("upStatDone");

    if (streakCount) streakCount.textContent = String(progress.streak);
    if (streakBest) streakBest.textContent = String(progress.best_streak);
    if (streakIcon) streakIcon.textContent = progress.streak >= 7 ? "++" : progress.streak >= 3 ? "+!" : "+";
    if (levelTag) levelTag.textContent = `Lv.${level}`;
    if (xpValue) xpValue.textContent = String(currentXp);
    if (xpNext) xpNext.textContent = "100";
    if (xpFill) xpFill.style.width = `${currentXp}%`;
    if (checkinBtn) {
      checkinBtn.disabled = checkedToday;
      checkinBtn.classList.toggle("checked", checkedToday);
      checkinBtn.textContent = checkedToday ? "今日已打卡" : "今日打卡 · +10 XP";
    }
    if (checkinHint) {
      checkinHint.textContent = checkedToday
        ? `已完成今日打卡，当前连续 ${progress.streak} 天。`
        : "每天打卡会累积连续记录，并自动带动当前计划任务推进。";
    }
    if (statStreak) statStreak.textContent = `${progress.streak}天`;
    if (statXp) statXp.textContent = `${progress.xp} XP`;
    if (statDone) statDone.textContent = String(stats.done);

    renderWeekStrip(progress);
    renderHeatmap(progress);
    renderBadgeGrid(progress, stats.done);
  }

  function schedulePlanRefresh() {
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(() => {
        updatePlanWidgets();
      });
      return;
    }
    setTimeout(updatePlanWidgets, 0);
  }

  function ensurePlanFunctionsWrapped() {
    if (reportRuntime.planWrapped) return;
    reportRuntime.planWrapped = true;

    const wrap = (name) => {
      if (typeof window[name] !== "function") return;
      const original = window[name];
      window[name] = function wrappedPlanAction() {
        const result = original.apply(this, arguments);
        schedulePlanRefresh();
        return result;
      };
    };

    ["createNewPlan", "addPlanItem", "togglePlanItem", "showPlanList", "showPlanDetail"].forEach(wrap);

    if (typeof window.doCheckin === "function") {
      const originalCheckin = window.doCheckin;
      window.doCheckin = function wrappedCheckin() {
        const progress = readPlanProgress();
        const todayKey = dayKey(new Date());
        if (progress.last_checkin === todayKey) {
          toast("今日已打卡", "今天的打卡奖励已经领取过了。", "info", 1600);
          schedulePlanRefresh();
          return;
        }

        const yesterday = dayKey(addDays(new Date(), -1));
        progress.streak = progress.last_checkin === yesterday ? progress.streak + 1 : 1;
        progress.best_streak = Math.max(progress.best_streak, progress.streak);
        progress.xp += progress.streak % 7 === 0 ? 50 : 10;
        progress.last_checkin = todayKey;
        progress.active_days[todayKey] = true;
        writePlanProgress(progress);

        const result = originalCheckin.apply(this, arguments);
        schedulePlanRefresh();
        return result;
      };
    }
  }

  function loadCareerPlans() {
    updatePlanWidgets();
    if (typeof window.showPlanList === "function") {
      window.showPlanList();
    }
  }

  function bindGlobalRestorationEvents() {
    if (reportRuntime.eventsBound) return;
    reportRuntime.eventsBound = true;

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn && !logoutBtn.dataset.restorationBound) {
      logoutBtn.addEventListener("click", () => {
        stopCareerReportPolling();
        closeReportViewer();
        closeCareerReportEditor();
      });
      logoutBtn.dataset.restorationBound = "1";
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeReportViewer();
        closeCareerReportEditor();
      }
    });
  }

  function getReportUiText(value, fallback = "") {
    const text = value == null ? "" : String(value).trim();
    return text || fallback;
  }

  function normalizeReportDocItems(items) {
    return (Array.isArray(items) ? items : [])
      .map((item) => {
        const normalized = normalizeExplainItem(item);
        if (normalized) return normalized;
        if (typeof item === "string" && item.trim()) {
          return { title: item.trim(), detail: "", validate: "" };
        }
        if (item && typeof item === "object") {
          const title = getReportUiText(item.title || item.label || item.name || item.requirement || item.summary);
          if (!title) return null;
          return {
            title,
            detail: getReportUiText(item.detail || item.reason || item.note || item.summary || item.why_important),
            validate: getReportUiText(item.validate || item.validation_action || item.how_to_validate)
          };
        }
        return null;
      })
      .filter(Boolean);
  }

  function renderReportUiSectionHead(index, kicker, title, copy) {
    return `
      <div class="crdoc-section-head">
        <span class="crdoc-section-index">${esc(index)}</span>
        <div class="crdoc-section-title-group">
          <div class="crdoc-section-title-row">
            <span class="crdoc-section-accent" aria-hidden="true"></span>
            <div>
              <p class="crdoc-section-kicker">${esc(kicker)}</p>
              <h3>${esc(title)}</h3>
            </div>
          </div>
          ${copy ? `<p>${esc(copy)}</p>` : ""}
        </div>
      </div>
    `;
  }

  function getReportIssueTone(item, fallback = "muted") {
    const severity = getReportUiText(item?.severity || item?.priority || item?.type).toLowerCase();
    if (severity.includes("high") || severity.includes("critical") || severity.includes("urgent")) return "danger";
    if (severity.includes("medium") || severity.includes("warn") || severity.includes("partial")) return "warn";
    return fallback;
  }

  function renderReportIssueList(items, emptyText) {
    const normalized = normalizeReportDocItems(items).slice(0, 5);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">${esc(emptyText)}</p>`;
    }
    return `
      <ul class="crdoc-issue-list">
        ${normalized.map((item) => `
          <li class="crdoc-issue-item ${getReportIssueTone(item)}">
            <span class="crdoc-issue-dot" aria-hidden="true"></span>
            <div>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            </div>
          </li>
        `).join("")}
      </ul>
    `;
  }

  function renderReportChipCloud(items, variant = "") {
    const normalized = normalizeReportDocItems(items).slice(0, 10);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">\u6682\u65e0\u53ef\u5c55\u793a\u9879</p>`;
    }
    return `
      <div class="crdoc-chip-cloud">
        ${normalized.map((item) => `
          <span class="crdoc-cloud-chip${variant ? ` ${variant}` : ""}">
            <i aria-hidden="true"></i>
            ${esc(item.title)}
          </span>
        `).join("")}
      </div>
    `;
  }

  function renderReportTaskList(items, emptyText) {
    const normalized = normalizeReportDocItems(items).slice(0, 5);
    if (!normalized.length) {
      return `<p class="crdoc-empty-state">${esc(emptyText)}</p>`;
    }
    return `
      <div class="crdoc-task-list">
        ${normalized.map((item) => `
          <div class="crdoc-task-item">
            <span class="crdoc-task-check" aria-hidden="true"></span>
            <div>
              <strong>${esc(item.title)}</strong>
              ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  function renderReportMetricCard(label, value, meta, tone = "") {
    return `
      <article class="crdoc-header-info-card${tone ? ` ${tone}` : ""}">
        <span>${esc(label)}</span>
        <strong>${esc(value)}</strong>
        ${meta ? `<small>${esc(meta)}</small>` : ""}
      </article>
    `;
  }

  function renderReportTrendTimeline(activeStep) {
    const labels = ["\u73b0\u5728", "\u91cd\u70b9\u9700\u8981", "\u8fd11-3\u5e74", "\u8fd11-5\u5e74"];
    return `
      <div class="crdoc-trend-timeline">
        ${labels.map((label, index) => `
          <span class="crdoc-trend-step${index <= activeStep ? " active" : ""}">
            <i aria-hidden="true"></i>
            <em>${esc(label)}</em>
          </span>
        `).join("")}
      </div>
    `;
  }

  function getReportRoleScoreTone(score) {
    if (score >= 60) return "high";
    if (score >= 44) return "medium";
    return "low";
  }

  function renderReportFullHeaderMeta(bundle, tracker) {
    const meta = bundle?.meta || {};
    const matchOutput = bundle?.match_output || {};
    const focusRole = bundle?.report_document?.focus_role_name || tracker?.focus_role_name || meta.focus_role_name || "\u5f85\u8bc6\u522b";
    const fitScore = Math.max(0, Math.min(100, Number(matchOutput.fit_score || 0)));
    const fitBandLabel = {
      strong: "\u9ad8\u5339\u914d",
      moderate: "\u4e2d\u7b49\u5339\u914d",
      weak: "\u4f4e\u5339\u914d",
      not_ready: "\u5c1a\u9700\u51c6\u5907"
    }[String(matchOutput.fit_band || "")] || "\u5f85\u8bc4\u4f30";
    return `
      <div class="crdoc-header-meta-grid">
        ${renderReportMetricCard("\u76ee\u6807\u5c97\u4f4d", focusRole, "\u5f53\u524d\u62a5\u544a\u4e3b\u7ebf")}
        ${renderReportMetricCard("\u5339\u914d\u5ea6", `${fitScore}%`, fitBandLabel, fitScore < 44 ? "danger" : fitScore < 60 ? "warn" : "success")}
        ${renderReportMetricCard("\u751f\u6210\u65f6\u95f4", meta.generated_at || "--", `v${meta.version || "--"}`)}
      </div>
    `;
  }

  function buildReportDashboardUiData(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const nextActions = reportDocument.next_actions || {};
    const next30Days = nextActions.next_30_days || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const marketSignals = reportDocument.market_signals || {};
    const industryStory = reportDocument.industry_story || {};
    const roleCards = Array.isArray(reportDocument.role_cards) ? reportDocument.role_cards : [];
    const planBoard = reportDocument.plan_board || {};
    const explainabilitySummary = reportDocument.explainability_summary || {};
    const competencyProfile = bundle?.competency_profile || {};
    const matchOutput = bundle?.match_output || {};
    const pathPlan = bundle?.path_plan || {};
    const explainabilityOverview = reportDocument.explainability_overview || {};
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "\u5f85\u8bc6\u522b";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? matchOutput.fit_score ?? 0)));
    const fitBandLabel = getReportUiText(dashboardSummary.fit_band_label) || ({
      strong: "\u9ad8\u5339\u914d",
      moderate: "\u4e2d\u7b49\u5339\u914d",
      weak: "\u4f4e\u5339\u914d",
      not_ready: "\u5c1a\u9700\u51c6\u5907"
    }[String(matchOutput.fit_band || "")] || "\u5f85\u8bc4\u4f30");
    const dimensions = normalizeReportDimensions(competencyProfile.dimensions);
    const headline = getReportUiText(
      dashboardSummary.headline || meta.summary || reportDocument.executive_summary,
      `\u73b0\u9636\u6bb5\u5efa\u8bae\u56f4\u7ed5 ${focusRole} \u96c6\u4e2d\u8865\u8db3\u5173\u952e\u8bc1\u636e\u548c\u7f3a\u53e3\u3002`
    );
    const rationale = getReportUiText(
      dashboardSummary.rationale || reportDocument.executive_summary || meta.summary,
      `\u5148\u89e3\u51b3 ${focusRole} \u5bf9\u5e94\u7684\u786c\u95e8\u69db\u548c\u8bc1\u636e\u7f3a\u53e3\uff0c\u518d\u63a8\u8fdb\u6295\u9012\u548c\u8def\u5f84\u9009\u62e9\u3002`
    );
    const headlineBecause = Array.isArray(dashboardSummary.headline_because)
      ? dashboardSummary.headline_because
      : (Array.isArray(explainabilitySummary.headline_because) ? explainabilitySummary.headline_because : []);
    const strengths = collectUniqueExplainItems(evidenceHealth.strengths, competencyProfile.strengths);
    const gaps = collectUniqueExplainItems(
      evidenceHealth.hard_failures,
      evidenceHealth.skill_gaps,
      evidenceHealth.evidence_gaps,
      evidenceHealth.missing_inputs,
      matchOutput.partial_gaps
    );
    const roles = (roleCards.length
      ? roleCards.map((item) => ({
          name: item?.role_name || "",
          overall_score: item?.fit_score || 0,
          fit_summary: item?.fit_summary || "",
          required_skills: Array.isArray(item?.required_skills) ? item.required_skills : [],
          because: Array.isArray(item?.why_fit) ? item.why_fit : [],
          hard_gaps: Array.isArray(item?.hard_gaps) ? item.hard_gaps : [],
          partial_gaps: Array.isArray(item?.partial_gaps) ? item.partial_gaps : []
        }))
      : (Array.isArray(bundle?.role_rankings) ? [...bundle.role_rankings] : []))
      .sort((left, right) => Number(right?.overall_score || 0) - Number(left?.overall_score || 0))
      .slice(0, 3);
    const signals = (Array.isArray(marketSignals.signal_cards) && marketSignals.signal_cards.length
      ? marketSignals.signal_cards
      : Array.isArray(industryStory.highlight_items) && industryStory.highlight_items.length
        ? industryStory.highlight_items.map((item) => ({
            title: item?.title || "",
            summary: item?.summary || "",
            source_type: item?.source || "",
            time_horizon: item?.published_label || "",
            validation_action: item?.topic || ""
          }))
        : collectUniqueExplainItems(marketSignals.hot_directions)).slice(0, 3);
    const milestones = Array.isArray(pathPlan.milestones) ? pathPlan.milestones : [];
    const actionItems = Array.isArray(planBoard.action_items) && planBoard.action_items.length
      ? planBoard.action_items.slice(0, 6)
      : (Array.isArray(nextActions.action_items) ? nextActions.action_items.slice(0, 6) : []);
    const planHorizons = Array.isArray(planBoard.horizons) ? planBoard.horizons : [];
    const shortPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "short_term")?.items)
      ? planHorizons.find((item) => item?.key === "short_term").items
      : (Array.isArray(nextActions.this_week) ? nextActions.this_week.map((item) => ({ title: item })) : []);
    const mediumPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "mid_term")?.items)
      ? planHorizons.find((item) => item?.key === "mid_term").items
      : (Array.isArray(next30Days.tasks) ? next30Days.tasks.map((item) => ({ title: item })) : []);
    const longPlanActions = Array.isArray(planHorizons.find((item) => item?.key === "long_term")?.items)
      ? planHorizons.find((item) => item?.key === "long_term").items
      : (Array.isArray(nextActions.checkpoints) ? nextActions.checkpoints : []);
    const decisionCards = Array.isArray(dashboardSummary.decision_cards) ? dashboardSummary.decision_cards : [];
    return {
      bundle,
      tracker,
      meta,
      reportDocument,
      nextActions,
      evidenceHealth,
      marketSignals,
      industryStory,
      competencyProfile,
      matchOutput,
      pathPlan,
      explainabilityOverview,
      focusRole,
      fitScore,
      fitBandLabel,
      dimensions,
      headline,
      rationale,
      headlineBecause,
      strengths,
      gaps,
      roles,
      signals,
      milestones,
      actionItems,
      shortPlanActions,
      mediumPlanActions,
      longPlanActions,
      decisionCards
    };
  }

  function renderReportDashboardPositionSection(data) {
    const issueItems = normalizeReportDocItems(data.gaps).slice(0, 4);
    const evidenceTrace = normalizeReportDocItems(data.evidenceHealth.evidence_trace).slice(0, 3);
    const dimensionCards = data.dimensions.length
      ? data.dimensions.map((entry, index) => {
          const pending = String(entry.level || "").toLowerCase() === "unknown";
          const failed = !pending && Number(entry.score || 0) < 58;
          const statusText = pending ? "\u5f85\u9a8c\u8bc1" : failed ? "\u672a\u901a\u8fc7" : "\u5df2\u9a8c\u8bc1";
          const statusClass = pending ? "pending" : failed ? "failed" : "verified";
          return `
            <article class="crdoc-cap-card ${statusClass} crdoc-reveal" style="transition-delay:${Math.min(index, 5) * 60}ms">
              <div class="crdoc-cap-head">
                <strong>${esc(entry.label)}</strong>
                <span class="crdoc-status-pill ${statusClass}">${pending ? `<i aria-hidden="true">&#128274;</i>` : ""}${esc(statusText)}</span>
              </div>
              <div class="crdoc-progress ${pending ? "is-pending" : ""}">
                <i style="width:${Math.max(12, pending ? 32 : entry.score)}%"></i>
              </div>
              <p>${esc(getReportUiText(entry.reason, pending ? "\u9700\u8981\u589e\u52a0\u66f4\u660e\u786e\u7684\u8bc1\u636e\u6216\u9879\u76ee\u8f93\u51fa\u518d\u5b8c\u6210\u5224\u65ad\u3002" : failed ? "\u8fd9\u4e2a\u7ef4\u5ea6\u8fd8\u4e0d\u8db3\u4ee5\u652f\u6491\u5f53\u524d\u76ee\u6807\u5c97\u4f4d\u3002" : "\u5f53\u524d\u5df2\u6709\u4e00\u5b9a\u8bc1\u636e\u652f\u6491\uff0c\u53ef\u4ee5\u7ee7\u7eed\u52a0\u6df1\u3002"))}</p>
            </article>
          `;
        }).join("")
      : `<p class="crdoc-empty-state">\u6682\u65e0\u80fd\u529b\u7ef4\u5ea6\u6570\u636e</p>`;

    return `
      <section id="reportDocSection-position" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("01", "Current Position", "\u5f53\u524d\u72b6\u6001", "\u5148\u770b\u6700\u963b\u585e\u4f60\u7684\u95ee\u9898\uff0c\u518d\u5bf9\u5e94\u5230\u80fd\u529b\u7ef4\u5ea6\u548c\u8bc1\u636e\u72b6\u6001\u3002")}
        <div class="crdoc-position-grid">
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u95ee\u9898\u6e05\u5355</span>
              <span class="crdoc-card-meta">${esc(data.focusRole)}</span>
            </div>
            <h4>\u5f53\u524d\u5b9a\u4f4d\u5224\u65ad</h4>
            <p>${esc(data.rationale)}</p>
            ${renderReportIssueList(issueItems, "\u5f53\u524d\u672a\u68c0\u51fa\u9ad8\u98ce\u9669\u7f3a\u53e3")}
            <div class="crdoc-inline-stack">
              <span class="crdoc-inline-title">\u53ef\u8ffd\u6eaf\u8bc1\u636e</span>
              ${evidenceTrace.length ? evidenceTrace.map((item) => `
                <div class="crdoc-inline-evidence">
                  <strong>${esc(item.title)}</strong>
                  ${item.detail ? `<p>${esc(item.detail)}</p>` : ""}
                </div>
              `).join("") : `<p class="crdoc-empty-state">\u6682\u65e0\u53ef\u8ffd\u6eaf\u8bc1\u636e</p>`}
            </div>
          </article>
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u80fd\u529b\u8bc4\u4f30</span>
              <span class="crdoc-card-meta">\u72b6\u6001 + \u8fdb\u5ea6\u6761</span>
            </div>
            <div class="crdoc-cap-grid">${dimensionCards}</div>
          </article>
        </div>
      </section>
    `;
  }

  function renderReportDashboardTrendSection(data) {
    const skillPriorities = normalizeReportDocItems(data.marketSignals.skill_priorities);
    const verificationActions = normalizeReportDocItems(data.marketSignals.verification_actions);
    const riskSignals = normalizeReportDocItems(data.marketSignals.risk_signals);
    return `
      <section id="reportDocSection-trends" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("02", "Industry Trends", "\u884c\u4e1a\u8d8b\u52bf", "\u628a\u5f53\u524d\u53d8\u5316\u3001\u91cd\u70b9\u80fd\u529b\u548c\u9a8c\u8bc1\u65b9\u5f0f\u653e\u5728\u540c\u4e00\u5c42\u7ea7\u91cc\u3002")}
        <div class="crdoc-trend-grid">
          ${data.signals.length ? data.signals.map((item, index) => {
            const normalized = normalizeExplainItem(item) || { title: getReportUiText(item?.title || item?.summary || item), detail: "", validate: "" };
            const raw = item && typeof item === "object" ? item : {};
            return `
              <article class="crdoc-trend-card crdoc-reveal" style="transition-delay:${index * 70}ms">
                ${renderReportTrendTimeline(Math.min(3, index + 1))}
                <div class="crdoc-card-topline">
                  <span class="crdoc-card-label">${esc(index === 0 ? "\u73b0\u5728" : index === 1 ? "\u91cd\u70b9\u9700\u8981" : "\u4e2d\u957f\u671f")}</span>
                  <span class="crdoc-card-meta">${esc(getReportUiText(raw.time_horizon, "\u8d8b\u52bf\u89c2\u5bdf"))}</span>
                </div>
                <h4>${esc(normalized.title)}</h4>
                <p>${esc(getReportUiText(raw.summary || raw.why_important || normalized.detail, "\u6682\u65e0\u8fd9\u4e2a\u8d8b\u52bf\u7684\u8be6\u7ec6\u8bf4\u660e"))}</p>
                <div class="crdoc-fact-row">
                  <span>\u6765\u6e90</span>
                  <strong>${esc(getReportUiText(raw.source_type, "\u7efc\u5408\u5224\u65ad"))}</strong>
                </div>
                <details class="crdoc-accordion">
                  <summary>\u5982\u4f55\u9a8c\u8bc1</summary>
                  <p>${esc(getReportUiText(normalized.validate || raw.validation_action, "\u53ef\u4ee5\u901a\u8fc7\u9879\u76ee\u4ea7\u51fa\u3001\u5c97\u4f4d\u9700\u6c42\u6216\u8bd5\u6295\u53cd\u9988\u6765\u9a8c\u8bc1\u3002"))}</p>
                </details>
              </article>
            `;
          }).join("") : `<article class="crdoc-card"><p class="crdoc-empty-state">\u6682\u65e0\u884c\u4e1a\u8d8b\u52bf\u6570\u636e</p></article>`}
        </div>
        <article class="crdoc-card">
          <div class="crdoc-card-topline">
            <span class="crdoc-card-label">\u80fd\u529b\u5efa\u8bae</span>
            <span class="crdoc-card-meta">\u6807\u7b7e\u4e91</span>
          </div>
          ${renderReportChipCloud([...skillPriorities, ...verificationActions], "accent")}
          ${riskSignals.length ? `<div class="crdoc-inline-note crdoc-risk-note">${renderReportChipCloud(riskSignals, "warn")}</div>` : ""}
        </article>
      </section>
    `;
  }

  function renderReportDashboardTargetsSection(data) {
    return `
      <section id="reportDocSection-targets" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("03", "Target Roles", "\u76ee\u6807\u5c97\u4f4d\u5bf9\u6bd4", "\u4e0d\u53ea\u770b\u603b\u5206\uff0c\u8fd8\u8981\u770b\u4f60\u5df2\u7ecf\u62ff\u5728\u624b\u91cc\u7684\u80fd\u529b\u548c\u8fd8\u6ca1\u8865\u4e0a\u7684\u7f3a\u53e3\u3002")}
        <div class="crdoc-role-grid">
          ${data.roles.length ? data.roles.map((role, index) => {
            const score = Math.max(0, Math.min(100, Number(role?.overall_score ?? role?.overallScore ?? 0)));
            const tone = getReportRoleScoreTone(score);
            const requiredSkills = Array.isArray(role?.required_skills) ? role.required_skills.slice(0, 8) : [];
            const hardGapText = normalizeReportDocItems(role?.hard_gaps).map((item) => item.title.toLowerCase());
            const partialGapText = normalizeReportDocItems(role?.partial_gaps).map((item) => item.title.toLowerCase());
            return `
              <article class="crdoc-target-card ${tone} crdoc-reveal" style="transition-delay:${index * 70}ms">
                <div class="crdoc-target-head">
                  <div>
                    <h4>${esc(role?.name || role?.title || "\u5019\u9009\u5c97\u4f4d")}</h4>
                    <span>${esc(index === 0 ? "\u4f18\u5148\u65b9\u5411" : `\u5019\u9009\u65b9\u5411 ${index + 1}`)}</span>
                  </div>
                  <div class="crdoc-target-score ${tone}">
                    <strong>${score}</strong>
                    <small>\u5206</small>
                  </div>
                </div>
                <p class="crdoc-target-summary">${esc(getReportUiText(role?.fit_summary, "\u8fd9\u4e2a\u5c97\u4f4d\u7684\u8bf4\u660e\u8fd8\u5728\u8865\u5168\u4e2d\u3002"))}</p>
                <div class="crdoc-skill-system">
                  ${requiredSkills.length ? requiredSkills.map((skill) => {
                    const skillText = String(skill || "").toLowerCase();
                    const chipClass = hardGapText.some((item) => item.includes(skillText) || skillText.includes(item))
                      ? "missing-core"
                      : partialGapText.some((item) => item.includes(skillText) || skillText.includes(item))
                        ? "missing"
                        : "owned";
                    return `<span class="crdoc-skill-chip ${chipClass}">${esc(skill)}</span>`;
                  }).join("") : `<span class="crdoc-skill-chip missing">\u6682\u65e0\u6280\u80fd\u660e\u7ec6</span>`}
                </div>
                <div class="crdoc-target-layout">
                  <div class="crdoc-target-explain">
                    <span class="crdoc-target-mini-title">\u5339\u914d\u4f9d\u636e</span>
                    ${renderReportIssueList(index === 0 ? collectUniqueExplainItems(data.matchOutput.why_match, role?.because) : role?.because, "\u6682\u65e0\u5173\u952e\u652f\u6491\u9879")}
                  </div>
                  <aside class="crdoc-missing-rail">
                    <span class="crdoc-target-mini-title">\u7f3a\u5931\u9700\u6c42</span>
                    ${renderReportIssueList(collectUniqueExplainItems(role?.hard_gaps, role?.partial_gaps), "\u6682\u65e0\u660e\u663e\u7f3a\u53e3")}
                  </aside>
                </div>
              </article>
            `;
          }).join("") : `<article class="crdoc-card"><p class="crdoc-empty-state">\u6682\u65e0\u5c97\u4f4d\u5bf9\u6bd4\u6570\u636e</p></article>`}
        </div>
      </section>
    `;
  }

  function renderReportDashboardPathSection(data) {
    return `
      <section id="reportDocSection-path" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("04", "Career Path", "\u804c\u4e1a\u8def\u5f84", "\u628a\u5f53\u524d\u8282\u70b9\u3001\u4e0b\u4e00\u6b65\u3001\u4e2d\u671f\u548c\u8fdc\u671f\u8def\u5f84\u6536\u5728\u4e00\u6761\u7eb5\u5411\u6d41\u91cc\u3002")}
        <div class="crdoc-path-grid">
          <div class="crdoc-step-flow">
            <article class="crdoc-step-item current">
              <div class="crdoc-step-node"><span>1</span></div>
              <div class="crdoc-step-card">
                <div class="crdoc-step-card-head">
                  <span class="crdoc-time-pill">\u73b0\u5728</span>
                  <small>${esc(data.meta.generated_at || "--")}</small>
                </div>
                <h4>${esc(data.focusRole)}</h4>
                <p>${esc(data.rationale)}</p>
              </div>
            </article>
            ${data.milestones.length ? data.milestones.slice(0, 4).map((item, index) => `
              <article class="crdoc-step-item">
                <div class="crdoc-step-node"><span>${index + 2}</span></div>
                <div class="crdoc-step-card">
                  <div class="crdoc-step-card-head">
                    <span class="crdoc-time-pill">${esc(getReportUiText(item?.horizon, `0-${(index + 1) * 3}m`))}</span>
                    <small>${esc(index === 0 ? "\u4e0b\u4e00\u6b65" : index === 1 ? "\u4e2d\u671f" : "\u540e\u7eed\u9636\u6bb5")}</small>
                  </div>
                  <h4>${esc(getReportUiText(item?.title, "\u9636\u6bb5\u76ee\u6807"))}</h4>
                  <p>${esc(getReportUiText(item?.reason, "\u6682\u65e0\u8be6\u7ec6\u8bf4\u660e"))}</p>
                  ${renderReportTaskList(Array.isArray(item?.actions) ? item.actions.map((action) => ({ title: action, detail: item?.linked_gap || item?.priority_reason || "" })) : [], "\u6682\u65e0\u9636\u6bb5\u52a8\u4f5c")}
                </div>
              </article>
            `).join("") : `<p class="crdoc-empty-state">\u6682\u65e0\u804c\u4e1a\u8def\u5f84\u8282\u70b9</p>`}
          </div>
          <div class="crdoc-stack">
            <article class="crdoc-card crdoc-tip-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">\u63a8\u8350\u4fe1\u606f</span>
              </div>
              <h4>\u4e3a\u4ec0\u4e48\u662f\u8fd9\u6761\u8def</h4>
              ${renderReportIssueList(data.pathPlan.path_rationale, "\u6682\u65e0\u8def\u5f84\u89e3\u91ca")}
            </article>
            <article class="crdoc-card">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">\u98ce\u9669\u4e0e\u524d\u63d0</span>
              </div>
              ${renderReportIssueList(data.pathPlan.dependencies?.must_resolve_hard_failures, "\u6682\u65e0\u5fc5\u987b\u5148\u89e3\u51b3\u7684\u786c\u95e8\u69db")}
              ${renderReportIssueList(data.pathPlan.path_risks, "\u6682\u65e0\u663e\u6027\u98ce\u9669")}
              ${renderReportIssueList(data.pathPlan.contingency, "\u6682\u65e0\u5907\u9009\u8def\u7ebf")}
            </article>
          </div>
        </div>
      </section>
    `;
  }

  function renderReportDashboardPlanSection(data) {
    const stageCards = [
      {
        label: "0-2w",
        title: "\u5f53\u4e0b\u6821\u51c6",
        items: data.shortPlanActions,
        reason: Array.isArray(data.nextActions.priority_logic) ? data.nextActions.priority_logic[0] : ""
      },
      {
        label: "0-30d",
        title: "\u4e00\u4e2a\u6708\u5185",
        items: data.mediumPlanActions.slice(0, 3).length ? data.mediumPlanActions.slice(0, 3) : data.actionItems.slice(0, 3),
        reason: Array.isArray(data.nextActions.priority_logic) ? data.nextActions.priority_logic[1] : ""
      },
      {
        label: "1-3m",
        title: "\u80fd\u529b\u8865\u5f3a",
        items: data.mediumPlanActions.slice(3, 6).length ? data.mediumPlanActions.slice(3, 6) : data.actionItems.slice(3, 6),
        reason: data.milestones[1]?.reason || ""
      },
      {
        label: "3-12m",
        title: "\u8def\u5f84\u6210\u578b",
        items: data.longPlanActions,
        reason: getReportUiText(data.nextActions.plan_b || data.milestones[2]?.reason)
      }
    ];
    return `
      <section id="reportDocSection-plan" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("05", "Action Plan", "\u884c\u52a8\u8ba1\u5212", "\u62c6\u6210\u56db\u4e2a\u65f6\u95f4\u9636\u6bb5\uff0c\u8ba9\u5148\u540e\u987a\u5e8f\u548c\u4f18\u5148\u7ea7\u66f4\u6e05\u695a\u3002")}
        <div class="crdoc-stage-strip">
          ${stageCards.map((stage, index) => `
            <div class="crdoc-stage-node ${index < 2 ? "active" : ""}">
              <span>${esc(stage.label)}</span>
            </div>
          `).join("")}
        </div>
        <div class="crdoc-plan-grid crdoc-plan-grid-4">
          ${stageCards.map((stage, index) => `
            <article class="crdoc-plan-card crdoc-reveal" style="transition-delay:${index * 70}ms">
              <div class="crdoc-card-topline">
                <span class="crdoc-card-label">${esc(stage.label)}</span>
                <span class="crdoc-card-meta">${esc(stage.title)}</span>
              </div>
              ${renderReportTaskList(stage.items, "\u6682\u65e0\u8fd9\u4e2a\u9636\u6bb5\u7684\u4efb\u52a1")}
              <details class="crdoc-accordion muted">
                <summary>\u4e3a\u4ec0\u4e48\u5148\u505a\u8fd9\u6b65</summary>
                <p>${esc(getReportUiText(stage.reason, "\u8fd9\u4e2a\u9636\u6bb5\u4e3b\u8981\u7528\u6765\u8865\u8db3\u6700\u5f71\u54cd\u5339\u914d\u7ed3\u679c\u7684\u5173\u952e\u7f3a\u53e3\u3002"))}</p>
              </details>
            </article>
          `).join("")}
        </div>
        <div class="crdoc-two-col">
          <article class="crdoc-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u884c\u52a8\u5206\u89e3</span>
            </div>
            ${renderReportTaskList(data.actionItems, "\u6682\u65e0\u53ef\u6267\u884c\u52a8\u4f5c")}
          </article>
          <article class="crdoc-alert-card">
            <div class="crdoc-card-topline">
              <span class="crdoc-card-label">\u672a\u901a\u8fc7\u8bf4\u660e</span>
            </div>
            ${renderReportIssueList(data.matchOutput.hard_failures || data.evidenceHealth.hard_failures, "\u6682\u65e0\u660e\u786e\u7684\u672a\u901a\u8fc7\u6761\u76ee")}
          </article>
        </div>
      </section>
    `;
  }

  function renderReportDashboardSummarySection(data) {
    return `
      <section id="reportDocSection-summary" class="crdoc-section crdoc-reveal">
        ${renderReportUiSectionHead("06", "Key Judgements", "\u5173\u952e\u5224\u65ad", "\u628a\u6700\u5f3a\u7f3a\u53e3\u3001\u6700\u5927\u98ce\u9669\u548c\u6700\u503c\u5f97\u4fdd\u7559\u7684\u57fa\u7840\u6536\u62e2\u6210\u4e09\u4e2a\u6807\u51c6\u89c6\u56fe\u3002")}
        <div class="crdoc-insight-grid crdoc-insight-grid-3">
          <article class="crdoc-insight-card breakthrough">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u5f3a\u7f3a\u53e3</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.decisionCards.find((card) => card?.tone === "risk")?.title || data.gaps[0]?.title, "\u76ee\u524d\u6700\u9700\u8981\u5148\u8865\u7684\uff0c\u662f\u6700\u5f71\u54cd\u5c97\u4f4d\u5224\u65ad\u7684\u5173\u952e\u7f3a\u53e3\u3002"))}</p>
            ${renderReportIssueList(data.decisionCards.find((card) => card?.tone === "risk")?.because || data.gaps, "\u6682\u65e0\u5f3a\u7f3a\u53e3\u8bf4\u660e")}
          </article>
          <article class="crdoc-insight-card risk">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u91cd\u8981\u98ce\u9669</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.explainabilityOverview.match?.judgement || data.decisionCards.find((card) => card?.tone === "neutral")?.title, "\u4e0d\u8981\u5728\u8bc1\u636e\u4e0d\u8db3\u65f6\u628a\u5339\u914d\u5ea6\u5f53\u6210\u786e\u8ba4\u7ed3\u8bba\u3002"))}</p>
            ${renderReportIssueList(data.explainabilityOverview.match?.because || data.marketSignals.risk_signals, "\u6682\u65e0\u98ce\u9669\u8bf4\u660e")}
          </article>
          <article class="crdoc-insight-card strength">
            <div class="crdoc-insight-topline"></div>
            <div class="crdoc-card-topline"><span class="crdoc-card-label">\u6700\u503c\u5f97\u4fdd\u7559\u57fa\u7840</span></div>
            <p class="crdoc-insight-summary">${esc(getReportUiText(data.strengths[0]?.title || data.explainabilityOverview.positioning?.judgement, "\u76ee\u524d\u6700\u503c\u5f97\u4fdd\u7559\u7684\uff0c\u662f\u5df2\u88ab\u8bc1\u636e\u652f\u6491\u7684\u4e3b\u7ebf\u80fd\u529b\u57fa\u7840\u3002"))}</p>
            ${renderReportIssueList(data.strengths.length ? data.strengths : (data.explainabilityOverview.positioning?.because || []), "\u6682\u65e0\u57fa\u7840\u4f18\u52bf\u8bf4\u660e")}
          </article>
        </div>
        <div class="crdoc-feedback-wrap">
          ${renderReportFeedbackCard()}
        </div>
      </section>
    `;
  }

  function renderReportReaderTocIcon(targetId = "") {
    const id = String(targetId || "").trim().toLowerCase();
    if (id.includes("industry")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 18h16"></path><path d="M6 18V8"></path><path d="M12 18V5"></path><path d="M18 18v-7"></path></svg>`;
    }
    if (id.includes("position")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20v-6"></path><path d="M12 4 5 9l7 5 7-5-7-5Z"></path></svg>`;
    }
    if (id.includes("resume")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="4" width="14" height="16" rx="2"></rect><path d="M8 9h8M8 13h8M8 17h5"></path></svg>`;
    }
    if (id.includes("competency")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 6 7v5c0 4 2.8 6.5 6 8 3.2-1.5 6-4 6-8V7l-6-3Z"></path><path d="m9.5 12 1.7 1.7 3.3-3.4"></path></svg>`;
    }
    if (id.includes("match")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12.5 9 17l11-11"></path><path d="M4 7.5 9 12"></path></svg>`;
    }
    if (id.includes("path")) {
      return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18c3.5 0 3.5-12 7-12s3.5 12 7 12"></path><circle cx="5" cy="18" r="1.6"></circle><circle cx="12" cy="6" r="1.6"></circle><circle cx="19" cy="18" r="1.6"></circle></svg>`;
    }
    return `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="4" width="14" height="16" rx="2"></rect><path d="M8 9h8M8 13h8M8 17h5"></path></svg>`;
  }

  function renderReportReaderHeroOrb(score = 0, label = "") {
    const safeScore = Math.max(0, Math.min(100, Number(score || 0)));
    const dash = ((safeScore / 100) * 264).toFixed(1);
    return `
      <div class="crdoc-reader-orb">
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(148,163,184,0.24)" stroke-width="8"></circle>
          <circle cx="50" cy="50" r="42" fill="none" stroke="url(#crdocReaderOrbGrad)" stroke-width="8" stroke-linecap="round" stroke-dasharray="${dash} 264" transform="rotate(-90 50 50)"></circle>
          <defs>
            <linearGradient id="crdocReaderOrbGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#2563eb"></stop>
              <stop offset="100%" stop-color="#14b8a6"></stop>
            </linearGradient>
          </defs>
        </svg>
        <div class="crdoc-reader-orb-copy">
          <strong>${Math.round(safeScore)}%</strong>
          <span>${esc(label || "匹配评估")}</span>
        </div>
      </div>
    `;
  }

  function renderReportReaderToc(bundle) {
    const items = getReportTocItems(bundle);
    if (!items.length) return "";
    return `
      <nav class="crdoc-reader-toc" aria-label="职业报告目录">
        ${items.map((item, index) => `
          <button type="button" class="crdoc-reader-toc-btn" data-report-scroll-target="${esc(item.id || "")}">
            <span class="crdoc-reader-toc-icon">${renderReportReaderTocIcon(item.id || item.title || "")}</span>
            <span class="crdoc-reader-toc-copy">
              <small>${String(index + 1).padStart(2, "0")}</small>
              <strong>${esc(item.title || `章节 ${index + 1}`)}</strong>
            </span>
          </button>
        `).join("")}
      </nav>
    `;
  }

  function renderFullReportHeader(bundle, tracker) {
    const meta = bundle?.meta || {};
    const reportDocument = bundle?.report_document || {};
    const dashboardSummary = reportDocument.dashboard_summary || {};
    const evidenceHealth = reportDocument.evidence_health || {};
    const planBoard = reportDocument.plan_board || {};
    const nextActions = reportDocument.next_actions || {};
    const matchOutput = bundle?.match_output || {};
    const focusRole = reportDocument.focus_role_name || meta.focus_role_name || tracker?.focus_role_name || "\u5f85\u8bc6\u522b";
    const fitScore = Math.max(0, Math.min(100, Number(dashboardSummary.fit_score ?? matchOutput.fit_score ?? 0)));
    const fitBandLabel = getReportUiText(dashboardSummary.fit_band_label) || ({
      strong: "\u9ad8\u5339\u914d",
      moderate: "\u4e2d\u7b49\u5339\u914d",
      weak: "\u4f4e\u5339\u914d",
      not_ready: "\u5c1a\u9700\u51c6\u5907"
    }[String(dashboardSummary.fit_band || matchOutput.fit_band || "")] || "\u5f85\u8bc4\u4f30");
    const summaryRaw = String(reportDocument.executive_summary || meta.summary || "").trim();
    const highlights = normalizeReportDocItems(evidenceHealth.strengths).slice(0, 3);
    const evidenceCount = Array.isArray(evidenceHealth.evidence_trace) ? evidenceHealth.evidence_trace.length : 0;
    const actionItems = Array.isArray(planBoard.action_items) && planBoard.action_items.length
      ? planBoard.action_items
      : (Array.isArray(nextActions.action_items) ? nextActions.action_items : []);
    const sectionCount = getReportTocItems(bundle).length || 1;
    return `
      <section class="ucrd-full-head crdoc-full-head crdoc-reader-hero">
        <div class="crdoc-header-main crdoc-header-main--reader">
          <div class="crdoc-header-copy crdoc-header-copy--reader">
            <span class="crdoc-header-bar" aria-hidden="true"></span>
            <div class="crdoc-reader-copy">
              <p class="ucrd-kicker">Formal Career Report</p>
              <h2 class="ucrd-full-head-title">${esc(meta.title || "\u804c\u4e1a\u751f\u6daf\u53d1\u5c55\u62a5\u544a")}</h2>
              ${summaryRaw ? `<details class="uc-report-summary-details"><summary>查看分析摘要</summary><p class="ucrd-full-head-summary">${esc(summaryRaw)}</p></details>` : ""}
              <div class="crdoc-reader-meta">
                <span>\u4e3b\u7ebf\u5c97\u4f4d\u00a0\u00b7\u00a0${esc(focusRole)}</span>
                <span>\u751f\u6210\u65f6\u95f4\u00a0\u00b7\u00a0${esc(meta.generated_at || "--")}</span>
              </div>
              ${highlights.length ? `
                <div class="crdoc-reader-highlights">
                  ${highlights.map((item) => `<span class="crdoc-reader-highlight">${esc(item.title)}</span>`).join("")}
                </div>
              ` : ""}
            </div>
          </div>
          <div class="crdoc-reader-aside">
            ${String(meta.pipeline_version || "").startsWith("experiments-langgraph")
              ? `<span class="crdoc-reader-highlight">${esc(fitBandLabel)}</span>`
              : renderReportReaderHeroOrb(fitScore, fitBandLabel)}
          </div>
        </div>
        <div class="crdoc-reader-statbar">
          ${renderReportMetricCard("决策建议", fitBandLabel, "基于本次材料与岗位样本")}
          ${renderReportMetricCard("\u8bc1\u636e\u7247\u6bb5", String(evidenceCount), evidenceCount ? "\u652f\u6491\u5173\u952e\u5224\u65ad" : "\u7b49\u5f85\u66f4\u591a\u8bc1\u636e", evidenceCount ? "success" : "warn")}
          ${renderReportMetricCard("\u884c\u52a8\u5efa\u8bae", String(actionItems.length || sectionCount), actionItems.length ? "\u5df2\u53ef\u7ee7\u7eed\u6267\u884c" : "\u7ed3\u6784\u5316\u9605\u8bfb", actionItems.length ? "success" : "")}
        </div>
      </section>
    `;
  }

  function renderFullMarkdownReport(bundle) {
    let raw = String(bundle?.report_document?.markdown || "").trim();
    if (!raw) {
      raw = stitchModularMarkdownFromBundle(bundle);
    }
    if (raw) {
      const readingMd = markdownForCareerReportReading(raw);
      return `
        <div class="crdoc-page crdoc-page--reader">
          <section id="cr-full-markdown-anchor" class="career-report-section-card crdoc-article-card career-report-md-wrap">
            <div class="cr4-module-markdown cr4-module-markdown--reader career-report-md-article">${renderMarkdownBasic(readingMd, { enhancedLayout: true, injectHeadingAnchors: true, previewReportId: bundle?.meta?.report_id })}</div>
          </section>
        </div>
      `;
    }
    return `
      <div class="crdoc-page crdoc-page--reader">
        ${renderReportSections(bundle)}
      </div>
    `;
  }

  function renderReportDashboardV2(bundle, tracker) {
    if (String(bundle?.meta?.pipeline_version || "").startsWith("experiments-langgraph")) {
      return renderReportSections(bundle);
    }
    const data = buildReportDashboardUiData(bundle, tracker);
    return `
      <div class="crdoc-page">
        <nav class="crdoc-nav" aria-label="\u62a5\u544a\u6bb5\u843d\u5bfc\u822a">
          <button type="button" class="crdoc-nav-btn active" data-report-doc-nav-target="reportDocSection-position" aria-pressed="true">01 \u5f53\u524d\u72b6\u6001</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-trends" aria-pressed="false">02 \u884c\u4e1a\u8d8b\u52bf</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-targets" aria-pressed="false">03 \u76ee\u6807\u5c97\u4f4d\u5bf9\u6bd4</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-path" aria-pressed="false">04 \u804c\u4e1a\u8def\u5f84</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-plan" aria-pressed="false">05 \u884c\u52a8\u8ba1\u5212</button>
          <button type="button" class="crdoc-nav-btn" data-report-doc-nav-target="reportDocSection-summary" aria-pressed="false">06 \u5173\u952e\u5224\u65ad</button>
        </nav>
        ${renderReportDashboardPositionSection(data)}
        ${renderReportDashboardTrendSection(data)}
        ${renderReportDashboardTargetsSection(data)}
        ${renderReportDashboardPathSection(data)}
        ${renderReportDashboardPlanSection(data)}
        ${renderReportDashboardSummarySection(data)}
      </div>
    `;
  }

  function bindReportDocNavigation(root) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const buttons = Array.from(root.querySelectorAll("[data-report-doc-nav-target]"));
    const sections = buttons
      .map((button) => {
        const targetId = String(button.dataset.reportDocNavTarget || "").trim();
        if (!targetId) return null;
        const target = root.querySelector(`#${targetId}`);
        return target ? { button, target, targetId } : null;
      })
      .filter(Boolean);
    const revealTargets = Array.from(root.querySelectorAll(".crdoc-reveal"));

    const setActive = (targetId) => {
      buttons.forEach((button) => {
        const active = String(button.dataset.reportDocNavTarget || "").trim() === targetId;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    };

    sections.forEach(({ button, target, targetId }) => {
      button.addEventListener("click", () => {
        setActive(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });

    setActive(sections[0]?.targetId || "");

    if (typeof window.IntersectionObserver !== "function") {
      revealTargets.forEach((node) => node.classList.add("is-visible"));
      return;
    }

    const navObserver = new window.IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible?.target?.id) return;
      setActive(visible.target.id);
    }, {
      threshold: [0.25, 0.45, 0.65],
      rootMargin: "-18% 0px -52% 0px"
    });
    sections.forEach(({ target }) => navObserver.observe(target));

    const revealObserver = new window.IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, {
      threshold: 0.18,
      rootMargin: "0px 0px -8% 0px"
    });
    revealTargets.forEach((node) => {
      if (node.classList.contains("is-visible")) return;
      revealObserver.observe(node);
    });
  }

  async function initializeRestoration() {
    ensureAppState();
    ensurePlanFunctionsWrapped();
    primeCareerReportStateFromBootstrap();
    bindGlobalRestorationEvents();
    bindCareerReportEditorEvents();

    await loadAccountAvatarState(false);
    loadCareerPlans();

    if (!isAuthenticated()) {
      applyCareerReportState(null, null, null, {
        historical: false,
        userCenterRefresh: true
      });
      return;
    }

    try {
      const [statusResult, currentResult] = await Promise.allSettled([
        syncCareerReportStatus(),
        loadCurrentCareerReport({ userCenterRefresh: true })
      ]);

      const statusPayload = statusResult.status === "fulfilled" ? statusResult.value : null;
      const state = statusPayload?.state || getCareerReportStateSafe();
      const status = String(state?.status || "").trim().toLowerCase();
      const jobId = String(state?.job_id || statusPayload?.job?.job_id || "").trim();
      if ((status === "queued" || status === "running") && jobId) {
        void pollCareerReportJob(jobId);
      }

      if (currentResult.status === "rejected") {
        console.warn("load current career report failed", currentResult.reason);
      }
    } catch (error) {
      console.warn("workspace restoration init failed", error);
    } finally {
      scheduleRender(true);
      if (window.__CAREER_REPORT_POLISH_PAGE__ && isAuthenticated()) {
        const params = new URLSearchParams(window.location.search);
        void openCareerReportEditor({
          reportId: String(params.get("report_id") || "").trim(),
          snapshotId: String(params.get("snapshot_id") || "").trim()
        });
      }
    }
  }

  window.getCareerReportStateSafe = getCareerReportStateSafe;
  window.getCareerReportTracker = getCareerReportTracker;
  window.getCareerReportVersionList = getCareerReportVersionList;
  window.fetchCareerReportVersion = fetchCareerReportVersion;
  window.restoreLatestCareerReportView = restoreLatestCareerReportView;
  window.loadCurrentCareerReport = loadCurrentCareerReport;
  window.renderCareerReportPanels = renderCareerReportPanels;
  window.openReportViewer = openReportViewer;
  window.closeReportViewer = closeReportViewer;
  window.openCareerReportEditor = openCareerReportEditor;
  window.closeCareerReportEditor = closeCareerReportEditor;
  window.saveReport = saveReport;
  window.exportReport = exportReport;
  window.setCareerReportFocusRole = setCareerReportFocusRole;
  window.getAccountAvatarState = getAccountAvatarState;
  window.loadAccountAvatarState = loadAccountAvatarState;
  window.renderTopbarAvatar = renderTopbarAvatar;
  window._loadCareerPlans = loadCareerPlans;
  window._updateLifeProgress = updatePlanWidgets;
  window._updatePlanStats = updatePlanWidgets;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      const authReady = typeof window.initAuth === "function"
        ? window.initAuth()
        : (typeof initAuth === "function" ? initAuth() : null);
      Promise.resolve(authReady).finally(() => {
        void initializeRestoration();
      });
    }, { once: true });
  } else {
    const authReady = typeof window.initAuth === "function"
      ? window.initAuth()
      : (typeof initAuth === "function" ? initAuth() : null);
    Promise.resolve(authReady).finally(() => {
      void initializeRestoration();
    });
  }

  window.addEventListener("app:auth-changed", () => {
    stopCareerReportPolling();
    closeReportViewer();
    avatarRuntime.username = "";
    avatarRuntime.state = null;
    void initializeRestoration();
  });
})();
