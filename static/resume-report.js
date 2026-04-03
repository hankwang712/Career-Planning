(function () {
  let tocObserver = null;
  let currentResume = null;
  let currentDoc = null;
  let activeSectionId = "";

  function esc(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function stripMarkdown(value) {
    return String(value || "")
      .replace(/\[(.+?)\]\((.+?)\)/g, "$1")
      .replace(/\*\*(.+?)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .trim();
  }

  function inlineMarkdown(value) {
    return esc(value)
      .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function resolveApiUrl(path) {
    const rawBase = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
    const target = String(path || "").trim();
    if (!target) return target;
    if (/^https?:\/\//i.test(target)) return target;
    if (!rawBase) return target;
    return target.startsWith("/") ? `${rawBase}${target}` : `${rawBase}/${target}`;
  }

  async function requestJson(path, options) {
    const response = await fetch(resolveApiUrl(path), {
      credentials: "include",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options && options.headers ? options.headers : {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(String(data.message || "请求失败"));
    }
    return data;
  }

  function formatTime(ts) {
    const value = Number(ts || 0);
    if (!value) return "未生成";
    return new Date(value * 1000).toLocaleString("zh-CN", {
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function getAnalysisMode(resume) {
    const matcher = resume && typeof resume.matcher === "object" ? resume.matcher : {};
    return String(matcher.analysis_mode || resume?.analysis_meta?.analysis_mode || "").trim() || "resume_review";
  }

  function getModeLabel(mode) {
    return mode === "job_match" ? "岗位匹配" : "简历诊断";
  }

  function getFriendlyError(raw) {
    const text = String(raw || "").trim();
    if (!text) return "";
    if (text.includes("未能从简历中提取到有效文本")) {
      return "这份简历更像扫描版图片，系统暂时没有拿到可分析文本。建议优先上传文字版 PDF 或 DOCX；如果继续使用扫描版 PDF，识别结果可能会有偏差。";
    }
    return text;
  }

  function fallbackMarkdownToHtml(markdownText) {
    const lines = String(markdownText || "").replace(/\r\n/g, "\n").split("\n");
    const result = [];
    let listItems = [];
    let listType = "";
    let inCode = false;
    let codeBuffer = [];

    function flushList() {
      if (!listItems.length) return;
      const tag = listType === "ol" ? "ol" : "ul";
      result.push(`<${tag}>${listItems.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</${tag}>`);
      listItems = [];
      listType = "";
    }

    function flushCode() {
      if (!codeBuffer.length) return;
      result.push(`<pre><code>${esc(codeBuffer.join("\n"))}</code></pre>`);
      codeBuffer = [];
    }

    lines.forEach((rawLine) => {
      const line = rawLine.replace(/\s+$/, "");
      const stripped = line.trim();
      if (stripped.startsWith("```")) {
        flushList();
        if (inCode) {
          flushCode();
          inCode = false;
        } else {
          inCode = true;
        }
        return;
      }
      if (inCode) {
        codeBuffer.push(rawLine);
        return;
      }
      if (!stripped) {
        flushList();
        return;
      }
      if (stripped === "---") {
        flushList();
        result.push("<hr>");
        return;
      }
      if (/^\d+\.\s+/.test(stripped)) {
        if (listType && listType !== "ol") flushList();
        listType = "ol";
        listItems.push(stripped.replace(/^\d+\.\s+/, "").trim());
        return;
      }
      if (/^[-*]\s+/.test(stripped)) {
        if (listType && listType !== "ul") flushList();
        listType = "ul";
        listItems.push(stripped.replace(/^[-*]\s+/, "").trim());
        return;
      }
      flushList();
      if (stripped.startsWith("### ")) {
        result.push(`<h4>${inlineMarkdown(stripped.slice(4))}</h4>`);
      } else if (stripped.startsWith("## ")) {
        result.push(`<h3>${inlineMarkdown(stripped.slice(3))}</h3>`);
      } else if (stripped.startsWith("# ")) {
        result.push(`<h2>${inlineMarkdown(stripped.slice(2))}</h2>`);
      } else {
        result.push(`<p>${inlineMarkdown(stripped)}</p>`);
      }
    });

    flushList();
    flushCode();
    return result.join("");
  }

  function hasReport(resume) {
    return String(resume?.status || "").trim() === "analyzed"
      && Boolean(String(resume?.analysis_html || "").trim() || String(resume?.analysis_result || "").trim());
  }

  function extractReportMarkdown(resume) {
    const direct = String(resume?.analysis_result || "").trim();
    if (direct) return direct;
    const rawHtml = String(resume?.analysis_html || "").trim();
    if (!rawHtml) return "";
    const shell = document.createElement("div");
    shell.innerHTML = rawHtml;
    const preCode = shell.querySelector("pre code");
    if (preCode && String(preCode.textContent || "").trim()) {
      return String(preCode.textContent || "").trim();
    }
    return String(shell.textContent || "").trim();
  }

  function slugify(value, prefix, index) {
    const base = String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return `rr-${prefix}-${base || index + 1}`;
  }

  function extractOrderedItems(lines) {
    return (lines || [])
      .map((line) => String(line || "").trim())
      .filter((line) => /^\d+\.\s+/.test(line))
      .map((line) => line.replace(/^\d+\.\s+/, "").trim());
  }

  function extractBulletItems(lines) {
    return (lines || [])
      .map((line) => String(line || "").trim())
      .filter((line) => /^[-*]\s+/.test(line))
      .map((line) => line.replace(/^[-*]\s+/, "").trim());
  }

  function extractLabelValue(text) {
    const clean = stripMarkdown(text).replace(/^[\d.\-\s]+/, "").trim();
    if (!clean) return null;
    const match = clean.match(/^([^：:]{2,24})[：:]\s*(.+)$/);
    if (!match) return null;
    return {
      label: String(match[1] || "").trim(),
      body: String(match[2] || "").trim(),
    };
  }

  function getSectionTone(title) {
    const text = String(title || "");
    if (/风险|缺口|问题|短板/.test(text)) return "danger";
    if (/建议|行动|优化/.test(text)) return "warm";
    if (/优势|亮点|长处/.test(text)) return "positive";
    return "accent";
  }

  function buildReportDocument(resume) {
    const markdown = extractReportMarkdown(resume);
    const doc = {
      title: "",
      metadata: [],
      intro: [],
      sections: [],
      markdown,
    };
    if (!markdown) return doc;

    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    let currentSection = null;
    let currentSubsection = null;

    function pushSection() {
      if (!currentSection) return;
      doc.sections.push(currentSection);
      currentSection = null;
      currentSubsection = null;
    }

    lines.forEach((rawLine) => {
      const line = rawLine.replace(/\s+$/, "");
      const stripped = line.trim();

      if (/^#\s+/.test(stripped)) {
        if (!doc.title) doc.title = stripMarkdown(stripped.slice(2));
        return;
      }

      if (/^##\s+/.test(stripped)) {
        pushSection();
        currentSection = {
          index: doc.sections.length + 1,
          id: slugify(stripped.slice(3), "section", doc.sections.length),
          title: stripMarkdown(stripped.slice(3)),
          allLines: [],
          leadLines: [],
          subsections: [],
        };
        return;
      }

      if (!currentSection) {
        const meta = stripped.match(/^\*\*([^*]+?)\*\*\s*(.+)$/);
        if (meta) {
          doc.metadata.push({
            label: stripMarkdown(meta[1]).replace(/[：:]\s*$/, ""),
            value: stripMarkdown(meta[2]),
          });
        } else if (stripped && stripped !== "---") {
          doc.intro.push(stripped);
        }
        return;
      }

      if (/^###\s+/.test(stripped)) {
        currentSubsection = {
          id: slugify(stripped.slice(4), "topic", currentSection.subsections.length),
          title: stripMarkdown(stripped.slice(4)),
          lines: [],
        };
        currentSection.subsections.push(currentSubsection);
        return;
      }

      currentSection.allLines.push(line);
      if (currentSubsection) currentSubsection.lines.push(line);
      else currentSection.leadLines.push(line);
    });

    pushSection();

    if (!doc.sections.length && markdown) {
      doc.sections.push({
        index: 1,
        id: "rr-section-full",
        title: doc.title || "完整报告",
        allLines: lines,
        leadLines: lines,
        subsections: [],
      });
    }

    doc.sections = doc.sections.map((section) => {
      const leadMarkdown = section.leadLines.join("\n").trim();
      const allMarkdown = section.allLines.join("\n").trim();
      const subsections = section.subsections.map((sub) => {
        const markdownText = sub.lines.join("\n").trim();
        return {
          ...sub,
          markdown: markdownText,
          html: fallbackMarkdownToHtml(markdownText),
          orderedItems: extractOrderedItems(sub.lines),
          bulletItems: extractBulletItems(sub.lines),
        };
      });
      return {
        ...section,
        leadMarkdown,
        markdown: allMarkdown,
        leadHtml: fallbackMarkdownToHtml(leadMarkdown),
        html: fallbackMarkdownToHtml(allMarkdown),
        orderedItems: extractOrderedItems(section.leadLines.length ? section.leadLines : section.allLines),
        bulletItems: extractBulletItems(section.leadLines.length ? section.leadLines : section.allLines),
        subsections,
      };
    });

    return doc;
  }

  function buildOverviewStats(resume, doc) {
    const mode = getAnalysisMode(resume);
    const matcher = resume && typeof resume.matcher === "object" ? resume.matcher : {};
    const profile = resume && typeof resume.profile === "object" ? resume.profile : {};
    const firstRole = Array.isArray(profile.roles_detected) && profile.roles_detected[0]
      ? String(profile.roles_detected[0].role || "").trim()
      : String(profile?.basics?.target_direction || "").trim();
    const suggestionsSection = (doc.sections || []).find((section) => /建议|优化|行动/.test(section.title));
    const projectCount = Array.isArray(profile.project_highlights) ? profile.project_highlights.length : 0;
    const matchedCount = Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.length : 0;
    const jobCount = Array.isArray(matcher.job_keywords) ? matcher.job_keywords.length : 0;
    return [
      {
        label: "综合判断",
        value: profile.confidence ? `${Math.round(Number(profile.confidence || 0) * 100)}%` : "--",
        note: "结构化画像置信度",
        tone: "primary",
      },
      {
        label: mode === "job_match" ? "岗位命中" : "推荐方向",
        value: mode === "job_match" ? `${matchedCount}/${jobCount || 0}` : `${(Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions.length : 0) || (firstRole ? 1 : 0)} 个`,
        note: mode === "job_match" ? "已命中关键词 / JD 关键词" : "当前报告给出的优先方向",
        tone: "warm",
      },
      {
        label: "角色焦点",
        value: firstRole || "待生成",
        note: "当前最贴近的候选方向",
        tone: "",
        textual: true,
      },
      {
        label: "项目证据",
        value: `${projectCount || 0} 项`,
        note: "结构化提取到的重点项目",
        tone: "positive",
      },
      {
        label: "建议动作",
        value: `${(suggestionsSection?.orderedItems || suggestionsSection?.bulletItems || []).length || 0} 条`,
        note: resume?.analysis_meta?.ocr_used ? "当前结果含 OCR 识别" : "可直接执行的修改动作",
        tone: "",
      },
    ];
  }

  function buildHeroMeta(resume, doc) {
    const stats = buildOverviewStats(resume, doc);
    const matcher = resume && typeof resume.matcher === "object" ? resume.matcher : {};
    const profile = resume && typeof resume.profile === "object" ? resume.profile : {};
    const roleTags = Array.isArray(profile.roles_detected)
      ? profile.roles_detected.map((item) => item?.role).filter(Boolean).slice(0, 3)
      : [];
    const focusTags = getAnalysisMode(resume) === "job_match"
      ? (Array.isArray(matcher.matched_keywords) ? matcher.matched_keywords.filter(Boolean).slice(0, 5) : [])
      : (Array.isArray(matcher.recommended_directions) ? matcher.recommended_directions.filter(Boolean).slice(0, 5) : []);
    const chips = [
      ...roleTags.map((item) => ({ tone: "accent", label: item })),
      ...focusTags.map((item, index) => ({ tone: index < 2 ? "warm" : "", label: item })),
      ...(resume?.analysis_meta?.ocr_used ? [{ tone: "muted", label: "OCR 识别" }] : []),
    ];

    return `
      <div class="rr-score-grid">
        ${stats.map((item) => `
          <article class="rr-score-card ${esc(item.tone || "")}">
            <p class="rr-score-label">${esc(item.label)}</p>
            <strong class="rr-score-value ${item.textual ? "textual" : ""}">${esc(item.value)}</strong>
            <small class="rr-score-note">${esc(item.note || "")}</small>
          </article>
        `).join("")}
      </div>
      <div class="rr-chip-row">
        ${chips.length ? chips.map((item) => `<span class="rr-chip ${esc(item.tone || "")}">${esc(item.label)}</span>`).join("") : '<span class="rr-chip muted">分析完成后，这里会显示角色标签和焦点关键词</span>'}
      </div>
    `;
  }

  function renderHero(resume, doc) {
    const mode = getAnalysisMode(resume);
    const profile = resume && typeof resume.profile === "object" ? resume.profile : null;
    const topbarKicker = document.getElementById("rrTopbarKicker");
    const topbarTitle = document.getElementById("rrTopbarTitle");
    const topbarSubtitle = document.getElementById("rrTopbarSubtitle");
    const heroKicker = document.getElementById("rrHeroKicker");
    const heroTitle = document.getElementById("rrHeroTitle");
    const heroSummary = document.getElementById("rrHeroSummary");
    const heroMeta = document.getElementById("rrHeroMeta");
    const sidebarHint = document.getElementById("rrSidebarHint");

    if (topbarKicker) topbarKicker.textContent = mode === "job_match" ? "Job Match Report" : "Resume Review";
    if (topbarTitle) topbarTitle.textContent = mode === "job_match" ? "岗位匹配详细分析" : "简历诊断详细分析";
    if (topbarSubtitle) {
      topbarSubtitle.textContent = resume?.file_name
        ? `${resume.file_name} · ${formatTime(resume?.analyzed_at || resume?.uploaded_at)}`
        : "完成分析后，这里会展示结构化摘要、重点判断和完整建议。";
    }

    if (heroKicker) heroKicker.textContent = hasReport(resume) ? "报告摘要" : "结果状态";
    if (heroTitle) {
      if (hasReport(resume)) heroTitle.textContent = mode === "job_match" ? "完整岗位匹配报告" : "完整简历诊断报告";
      else if (String(resume?.status || "").trim() === "failed") heroTitle.textContent = "这份简历暂时没有生成分析结果";
      else if (resume?.file_name) heroTitle.textContent = "简历已上传，等待开始分析";
      else heroTitle.textContent = "还没有简历分析结果";
    }

    if (heroSummary) {
      if (profile?.candidate_summary) heroSummary.textContent = profile.candidate_summary;
      else if (String(resume?.status || "").trim() === "failed") heroSummary.textContent = getFriendlyError(resume?.error_message || resume?.analysis_meta?.stage_detail);
      else if (resume?.file_name) heroSummary.textContent = "当前只完成了上传，系统还没有开始生成摘要和详细报告。回到画像页点击“开始匹配”后，这里会自动更新。";
      else heroSummary.textContent = "上传简历并完成分析后，这里会把关键信息压缩成可快速浏览的摘要，再按章节展示完整内容。";
    }

    if (heroMeta) heroMeta.innerHTML = buildHeroMeta(resume, doc);

    if (sidebarHint) {
      sidebarHint.textContent = hasReport(resume)
        ? "先看顶部摘要和评分概览，再切到你最关心的章节。右侧导航只保留当前章节的小标题，阅读会更干净。"
        : "这里不会直接显示上传结果。只有完成“开始匹配”之后，章节导航和详细分析才会出现。";
    }
  }

  function renderOverviewCard(resume, doc) {
    const root = document.getElementById("rrSidebarMeta");
    if (!root) return;
    const profile = resume && typeof resume.profile === "object" ? resume.profile : {};
    const metaMap = new Map((doc.metadata || []).map((item) => [item.label, item.value]));
    const rows = [
      { label: "文件", value: resume?.file_name || "未上传" },
      { label: "模式", value: getModeLabel(getAnalysisMode(resume)) },
      { label: "状态", value: String(resume?.status || "empty") },
      { label: "分析对象", value: metaMap.get("分析对象") || profile?.basics?.name || "未识别" },
      { label: "更新时间", value: formatTime(resume?.analyzed_at || resume?.uploaded_at) },
    ];

    root.innerHTML = `
      <p class="rr-overview-kicker">报告概览</p>
      <h3 class="rr-overview-title">${esc(profile?.candidate_summary || (resume?.file_name ? "这份简历已上传到当前账号。" : "等待上传简历。"))}</h3>
      <p class="rr-overview-copy">${esc(doc.title || "分析完成后，这里会同步显示报告标题和核心背景信息。")}</p>
      <div class="rr-overview-meta">
        ${rows.map((row) => `
          <div class="rr-meta-row">
            <span>${esc(row.label)}</span>
            <strong>${esc(row.value)}</strong>
          </div>
        `).join("")}
      </div>
    `;
  }

  function setUser(user) {
    const displayName = String(user?.display_name || user?.displayName || user?.username || "未登录");
    const currentUser = document.getElementById("rrCurrentUser");
    const avatar = document.getElementById("rrAvatarBtn");
    if (currentUser) currentUser.textContent = displayName;
    if (avatar) avatar.textContent = displayName.slice(0, 1).toUpperCase();
  }

  function renderStatusBanner(resume) {
    const root = document.getElementById("rrStatusBanner");
    if (!root) return;
    const status = String(resume?.status || "").trim();
    const stageDetail = String(resume?.analysis_meta?.stage_detail || "").trim();
    if (status === "failed") {
      root.innerHTML = `
        <div class="rr-status-banner danger">
          <div>
            <strong>本次分析没有成功生成报告</strong>
            <p>${esc(getFriendlyError(resume?.error_message || stageDetail || "请检查文件内容后重试。"))}</p>
          </div>
        </div>
      `;
      return;
    }
    if (resume?.analysis_meta?.ocr_used) {
      root.innerHTML = `
        <div class="rr-status-banner warning">
          <div>
            <strong>本次结果来自 OCR 识别</strong>
            <p>当前 PDF 更接近扫描版图片，系统通过 OCR 读取后再生成分析。若你发现中文识别有误，建议优先上传文字版 PDF 或 DOCX。</p>
          </div>
        </div>
      `;
      return;
    }
    if (hasReport(resume)) {
      root.innerHTML = `
        <div class="rr-status-banner">
          <div>
            <strong>完整报告已生成</strong>
            <p>这页现在按章节展示完整分析，顶部看摘要，切换标签看详细诊断，右侧只保留当前章节的小标题导航。</p>
          </div>
        </div>
      `;
      return;
    }
    root.innerHTML = "";
  }

  function renderEmptyState(resume) {
    const root = document.getElementById("rrContentRoot");
    const tabs = document.getElementById("rrSectionTabs");
    const toc = document.getElementById("rrToc");
    if (!root) return;
    if (tabs) tabs.innerHTML = "";
    if (toc) toc.innerHTML = '<div class="rr-toc-empty">当前没有可阅读的章节导航。</div>';

    const status = String(resume?.status || "").trim();
    const isFailure = status === "failed";
    const hasFile = Boolean(resume?.file_name);
    const failureHint = getFriendlyError(resume?.error_message || resume?.analysis_meta?.stage_detail);
    root.innerHTML = `
      <div class="rr-empty-state">
        <section class="rr-empty-card">
          <h3>${isFailure ? "这次分析为什么没有结果？" : hasFile ? "现在处于什么状态？" : "先完成简历上传"}</h3>
          <p>${esc(
            isFailure
              ? failureHint || "系统没有生成可展示的分析内容，请返回画像页重新开始匹配。"
              : hasFile
                ? "当前只完成了上传，系统还没有开始生成摘要和详细报告。回到画像页点击“开始匹配”后，这里会自动更新。"
                : "你还没有在当前账号下上传简历。上传后才能生成摘要、章节导航和详细分析结果。"
          )}</p>
          <ul>
            ${isFailure ? "<li>如果是扫描版 PDF，优先导出文字版 PDF 或 DOCX 后重新上传。</li>" : ""}
            ${hasFile ? "<li>如果已经上传成功，但没点“开始匹配”，前端会显示“待分析”，不会直接生成结果。</li>" : "<li>支持 PDF 和 DOCX，建议优先使用可复制文字的版本。</li>"}
            <li>分析完成后，当前页会按章节重排结果，不再整段堆叠 Markdown。</li>
          </ul>
        </section>
        <div class="rr-empty-actions">
          <button type="button" class="rr-empty-btn primary" data-rr-action="back-profile">返回画像页</button>
          <button type="button" class="rr-empty-btn" data-rr-action="open-user-center">打开个人中心</button>
        </div>
      </div>
    `;
  }

  function renderTabs(doc, activeId) {
    const root = document.getElementById("rrSectionTabs");
    if (!root) return;
    root.innerHTML = (doc.sections || []).map((section, index) => `
      <button type="button" class="rr-tab-btn ${section.id === activeId ? "active" : ""}" data-section="${esc(section.id)}">
        <small>${String(index + 1).padStart(2, "0")}</small>
        <span>${esc(section.title)}</span>
      </button>
    `).join("");
  }

  function renderToc(section) {
    const root = document.getElementById("rrToc");
    if (!root) return;
    if (!section) {
      root.innerHTML = '<div class="rr-toc-empty">当前没有可阅读的章节导航。</div>';
      return;
    }
    if (Array.isArray(section.subsections) && section.subsections.length) {
      root.innerHTML = section.subsections.map((item, index) => `
        <button type="button" class="rr-toc-btn" data-target="${esc(item.id)}">
          <small>${String(index + 1).padStart(2, "0")}</small>
          <span>${esc(item.title)}</span>
        </button>
      `).join("");
      return;
    }
    const orderedItems = Array.isArray(section.orderedItems) ? section.orderedItems : [];
    if (orderedItems.length > 1) {
      root.innerHTML = orderedItems.map((item, index) => `
        <button type="button" class="rr-toc-btn" data-target="${esc(`${section.id}-item-${index + 1}`)}">
          <small>${String(index + 1).padStart(2, "0")}</small>
          <span>${esc(stripMarkdown(item).slice(0, 26) || `建议 ${index + 1}`)}</span>
        </button>
      `).join("");
      return;
    }
    root.innerHTML = '<div class="rr-toc-empty">当前章节没有额外小节，内容会以摘要块方式直接展示。</div>';
  }

  function setActiveToc(targetId) {
    document.querySelectorAll(".rr-toc-btn").forEach((button) => {
      button.classList.toggle("active", button.dataset.target === targetId);
    });
  }

  function bindTocObserver() {
    if (tocObserver) {
      tocObserver.disconnect();
      tocObserver = null;
    }
    const targets = Array.from(document.querySelectorAll('#rrContentRoot [data-rr-anchor="topic"]'));
    if (!targets.length || !("IntersectionObserver" in window)) {
      if (targets[0]?.id) setActiveToc(targets[0].id);
      return;
    }
    tocObserver = new IntersectionObserver((entries) => {
      const activeEntry = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (activeEntry?.target?.id) setActiveToc(activeEntry.target.id);
    }, {
      rootMargin: "-12% 0px -72% 0px",
      threshold: [0, 1],
    });
    targets.forEach((target) => tocObserver.observe(target));
    if (targets[0]?.id) setActiveToc(targets[0].id);
  }

  function renderConclusionBody(section) {
    const sourceItems = section.bulletItems.length ? section.bulletItems : extractOrderedItems(section.leadLines);
    const cards = sourceItems.length
      ? sourceItems.map((item, index) => {
        const parsed = extractLabelValue(item) || { label: `重点 ${index + 1}`, body: stripMarkdown(item) };
        const tones = ["positive", "danger", "warm"];
        return `
          <article class="rr-highlight-card ${tones[index % tones.length]}">
            <p class="rr-highlight-label">${esc(parsed.label)}</p>
            <p class="rr-highlight-body">${inlineMarkdown(parsed.body)}</p>
          </article>
        `;
      }).join("")
      : "";
    const followUp = Array.isArray(section.orderedItems) && section.orderedItems.length
      ? `
        <ol class="rr-action-list">
          ${section.orderedItems.map((item, index) => `
            <li id="${esc(`${section.id}-item-${index + 1}`)}" class="rr-action-item" data-rr-anchor="topic">
              <span class="rr-action-index">${index + 1}</span>
              <div class="rr-action-copy rr-markdown-body">${fallbackMarkdownToHtml(item)}</div>
            </li>
          `).join("")}
        </ol>
      `
      : "";

    return `
      ${cards ? `<div class="rr-highlight-grid">${cards}</div>` : ""}
      ${followUp}
      ${section.leadHtml && !cards ? `<div class="rr-markdown-body">${section.leadHtml}</div>` : ""}
    `;
  }

  function renderSubsectionBody(section) {
    return `
      ${section.leadHtml ? `<div class="rr-markdown-body">${section.leadHtml}</div>` : ""}
      <div class="rr-topic-grid">
        ${section.subsections.map((sub) => {
          const tone = getSectionTone(sub.title);
          const items = sub.bulletItems.length ? sub.bulletItems : sub.orderedItems;
          const bodyHtml = items.length
            ? `<ul class="rr-compact-list">${items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`
            : `<div class="rr-markdown-body">${sub.html}</div>`;
          return `
            <section id="${esc(sub.id)}" class="rr-topic-card ${esc(tone)}" data-rr-anchor="topic">
              <h4 class="rr-topic-title">${esc(sub.title)}</h4>
              <div class="rr-topic-body">${bodyHtml}</div>
            </section>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderActionBody(section) {
    const items = section.orderedItems.length ? section.orderedItems : section.bulletItems;
    if (!items.length) {
      return `<div class="rr-markdown-body">${section.leadHtml || section.html}</div>`;
    }
    return `
      <ol class="rr-action-list">
        ${items.map((item, index) => `
          <li id="${esc(`${section.id}-item-${index + 1}`)}" class="rr-action-item" data-rr-anchor="topic">
            <span class="rr-action-index">${index + 1}</span>
            <div class="rr-action-copy rr-markdown-body">${fallbackMarkdownToHtml(item)}</div>
          </li>
        `).join("")}
      </ol>
    `;
  }

  function renderGenericBody(section) {
    return `<div class="rr-markdown-body">${section.html || section.leadHtml}</div>`;
  }

  function renderActiveSection(section, doc) {
    const root = document.getElementById("rrContentRoot");
    if (!root || !section) return;
    const sectionIntro = doc.intro.length
      ? `<p class="rr-panel-subtitle">${esc(doc.intro.join(" "))}</p>`
      : "";
    let body = renderGenericBody(section);
    if (/30\s*秒/.test(section.title)) body = renderConclusionBody(section);
    else if (section.subsections.length) body = renderSubsectionBody(section);
    else if (section.orderedItems.length >= 2 || /建议|优化|行动/.test(section.title)) body = renderActionBody(section);

    root.innerHTML = `
      <section class="rr-panel">
        <header class="rr-panel-head">
          <div>
            <p class="rr-panel-kicker">Section ${String(section.index).padStart(2, "0")} / ${String((doc.sections || []).length).padStart(2, "0")}</p>
            <h3 class="rr-panel-title">${esc(section.title)}</h3>
            ${sectionIntro}
          </div>
        </header>
        <div class="rr-panel-body">${body}</div>
      </section>
    `;
    renderToc(section);
    bindTocObserver();
  }

  function switchSection(sectionId) {
    if (!currentDoc || !Array.isArray(currentDoc.sections) || !currentDoc.sections.length) return;
    const target = currentDoc.sections.find((section) => section.id === sectionId) || currentDoc.sections[0];
    activeSectionId = target.id;
    renderTabs(currentDoc, activeSectionId);
    renderActiveSection(target, currentDoc);
  }

  function renderReport(resume) {
    const doc = buildReportDocument(resume);
    currentResume = resume;
    currentDoc = doc;
    renderHero(resume, doc);
    renderOverviewCard(resume, doc);
    activeSectionId = doc.sections[0]?.id || "";
    renderTabs(doc, activeSectionId);
    switchSection(activeSectionId);
  }

  function bindGlobalEvents() {
    const logoutBtn = document.getElementById("rrLogoutBtn");
    const avatarBtn = document.getElementById("rrAvatarBtn");
    const tocRoot = document.getElementById("rrToc");
    const tabsRoot = document.getElementById("rrSectionTabs");

    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        try {
          await requestJson("/api/auth/logout", { method: "POST" });
        } catch (_) {}
        window.location.href = "/main.html";
      });
    }

    if (avatarBtn) {
      avatarBtn.addEventListener("click", () => {
        window.location.href = "/user-center.html#report-workspace";
      });
    }

    if (tabsRoot) {
      tabsRoot.addEventListener("click", (event) => {
        const button = event.target.closest(".rr-tab-btn");
        if (!button) return;
        const sectionId = String(button.dataset.section || "").trim();
        if (!sectionId) return;
        switchSection(sectionId);
      });
    }

    if (tocRoot) {
      tocRoot.addEventListener("click", (event) => {
        const button = event.target.closest(".rr-toc-btn");
        if (!button) return;
        const targetId = String(button.dataset.target || "").trim();
        const target = targetId ? document.getElementById(targetId) : null;
        if (!target) return;
        setActiveToc(targetId);
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }

    document.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-rr-action]");
      if (!trigger) return;
      const action = String(trigger.dataset.rrAction || "").trim();
      if (action === "back-profile") {
        if (typeof window.goBackToLastInterface === "function") {
          window.goBackToLastInterface("/main.html#profile");
        } else {
          window.location.href = "/main.html#profile";
        }
      }
      if (action === "open-user-center") {
        window.location.href = "/user-center.html#report-workspace";
      }
    });
  }

  async function init() {
    bindGlobalEvents();
    const auth = await requestJson("/api/auth/status?bootstrap=1").catch(() => null);
    if (!auth || !auth.authenticated || !auth.user) {
      window.location.href = "/main.html";
      return;
    }

    setUser(auth.user);
    const resume = auth?.scoped_data?.resume_profile || await requestJson("/api/resume/profile").catch(() => ({}));
    renderStatusBanner(resume || {});
    if (hasReport(resume || {})) {
      renderReport(resume || {});
    } else {
      const emptyDoc = buildReportDocument(resume || {});
      renderHero(resume || {}, emptyDoc);
      renderOverviewCard(resume || {}, emptyDoc);
      renderEmptyState(resume || {});
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
