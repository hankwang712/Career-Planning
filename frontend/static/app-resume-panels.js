// 简历诊断：评分、目标、差距、行动与卡片堆叠面板
// 由原来的 app.js 拆出，仍是普通脚本、共享全局作用域；加载顺序见 templates/partials/app_scripts.html。

function previewTagValues(items, limit = 8) {
  const values = [...new Set((Array.isArray(items) ? items : []).map((item) => String(item || "").trim()).filter(Boolean))];
  if (values.length <= limit) return values;
  return [...values.slice(0, limit), `+${values.length - limit}`];
}

function resumeModeMeta(analysisMode) {
  if (analysisMode === "resume_review") {
    return {
      badge: "简历诊断模式",
      title: "先看方向，再看优势和短板",
      description: "没有填写 JD 时，系统会优先给出通用竞争力判断和建议职业方向。"
    };
  }
  return {
    badge: "岗位匹配模式",
    title: "先看匹配度，再看风险和改法",
    description: "系统会先理解岗位文本，再把简历证据、缺口和建议整理成可操作结论。"
  };
}

function normalizeResumeScore(value) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) return null;
  return Math.max(0, Math.min(100, Math.round(Number(value))));
}

function resumeEvidenceScore(profile) {
  return normalizeResumeScore(profile?.capability_scores?.matching);
}

function resumeScoreLabel(value) {
  const score = normalizeResumeScore(value);
  return score == null ? "待验证" : `${score}%`;
}

function shortenResumeText(value, max = 92) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function humanizeResumeErrorMessage(raw) {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (text.includes("未能从简历中提取到有效文本")) {
    return "这份简历更像扫描版图片，系统暂时没有拿到可分析文本。建议优先上传文字版 PDF 或 DOCX；如果继续使用扫描版 PDF，识别结果可能会有偏差。";
  }
  return text;
}

function resumeProfileSummaryText(state, profile) {
  if (profile?.candidate_summary) return profile.candidate_summary;
  const status = String(state?.status || "").trim();
  const hasFile = Boolean(state?.file_name);
  const errorText = humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "");
  if (status === "failed" && hasFile) {
    return errorText || "简历已上传，但本次分析失败。请检查文件内容后重新开始匹配。";
  }
  if (hasFile) {
    return "简历已上传，当前还没有生成分析结果。点击“开始匹配”后即可查看摘要和详细报告。";
  }
  return "上传简历后会在这里显示摘要，开始匹配后可查看完整结果。";
}

function resumeQuickBoardHtml(profile, matcher, analysisMode, recommendedDirections) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const resumeOverview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const focusValue = analysisMode === "resume_review"
    ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
    : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别");
  const cards = [
    {
      label: "分析模式",
      value: analysisMode === "resume_review" ? "简历诊断" : "岗位匹配",
      note: analysisMode === "resume_review" ? "未绑定单一 JD" : "基于岗位文本判断"
    },
    {
      label: analysisMode === "resume_review" ? "建议方向" : "目标焦点",
      value: focusValue,
      note: analysisMode === "resume_review" ? "可后续再补充 JD" : (jobOverview.company_name || "直接提炼自输入文本")
    },
    {
      label: "地点信息",
      value: normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确",
      note: normalizeResumeBasicValue(jobOverview.employment_type) || "当前简历未给出稳定偏好"
    },
    {
      label: "经历体量",
      value: `${Number(resumeOverview.experience_count || 0)} 段经历`,
      note: `${Number(resumeOverview.project_count || 0)} 个项目 · ${Number(resumeOverview.skill_count || 0)} 项技能`
    }
  ];

  return cards
    .map((item) => `
      <article class="resume-quick-card">
        <p class="resume-quick-label">${escHtml(item.label)}</p>
        <p class="resume-quick-value">${escHtml(item.value)}</p>
        <p class="resume-quick-note">${escHtml(item.note)}</p>
      </article>
    `)
    .join("");
}

function resumeOverviewCardsHtml(profile, matcher, analysisMode, recommendedDirections) {
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const resumeOverview = matcher?.resume_overview && typeof matcher.resume_overview === "object" ? matcher.resume_overview : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const cards = [
    {
      label: "候选人",
      value: resumeOverview.candidate_name || normalizeResumeBasicValue(basics.name) || "未识别",
      note: resumeOverview.headline || "等待识别当前角色"
    },
    {
      label: "教育背景",
      value: normalizeResumeBasicValue(basics.grade) || "待补充",
      note: normalizeResumeBasicValue(basics.major) || "未识别专业"
    },
    {
      label: analysisMode === "resume_review" ? "建议方向" : "目标岗位",
      value: analysisMode === "resume_review"
        ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
        : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别"),
      note: analysisMode === "resume_review"
        ? (recommendedDirections.slice(1, 3).join(" / ") || "后续可补充明确 JD")
        : (jobOverview.company_name || "直接提炼自岗位文本")
    },
    {
      label: "地点",
      value: normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确",
      note: normalizeResumeBasicValue(jobOverview.employment_type) || "未识别用工方式"
    },
    {
      label: "项目数量",
      value: `${Number(resumeOverview.project_count || 0)} 个`,
      note: `${Number(resumeOverview.skill_count || 0)} 项技能被识别`
    },
    {
      label: "经历数量",
      value: `${Number(resumeOverview.experience_count || 0)} 段`,
      note: analysisMode === "resume_review" ? "用于判断方向适配" : "用于判断岗位匹配"
    }
  ];

  return `<div class="resume-overview-grid">${cards.map((item) => `
    <article class="resume-meta-card">
      <p class="resume-meta-label">${escHtml(item.label)}</p>
      <p class="resume-meta-value">${escHtml(item.value)}</p>
      <p class="resume-meta-note">${escHtml(item.note)}</p>
    </article>
  `).join("")}</div>`;
}

function resumeEvidenceCardsHtml(profile) {
  const groups = [
    {
      label: "来自简历",
      tone: "neutral",
      items: (Array.isArray(profile?.evidence_spans) ? profile.evidence_spans : []).slice(0, 4).map((item) => ({
        title: shortenResumeText(item.quote || "", 68) || "待补充证据",
        copy: "直接来自简历原文的关键片段。"
      }))
    },
    {
      label: "行为信号",
      tone: "brand",
      items: (Array.isArray(profile?.leadership_signals) ? profile.leadership_signals : []).slice(0, 3).map((item) => ({
        title: shortenResumeText(item.signal || item, 68) || "待识别",
        copy: "系统识别到的推进、主导或跨团队协作信号。"
      }))
    },
    {
      label: "待确认",
      tone: "warning",
      items: (Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : []).slice(0, 3).map((item) => ({
        title: item.item || "信息缺口",
        copy: [item.reason, item.needed_evidence ? `待补：${item.needed_evidence}` : ""].filter(Boolean).join(" ")
      }))
    }
  ];

  if (!groups.some((group) => group.items.length)) {
    return `<div class="career-list-empty">暂无证据片段</div>`;
  }
  return `<div class="resume-evidence-grid">${groups.map((group) => `
    <section class="resume-evidence-group ${escHtml(group.tone)}">
      <div class="resume-evidence-group-head">
        <p class="resume-evidence-group-title">${escHtml(group.label)}</p>
        <span class="resume-evidence-group-count">${group.items.length}</span>
      </div>
      <div class="resume-evidence-group-list">
        ${group.items.length ? group.items.map((item) => `
          <article class="resume-evidence-entry">
            <p class="resume-evidence-title">${escHtml(item.title)}</p>
            <p class="resume-evidence-copy">${escHtml(shortenResumeText(item.copy, 116))}</p>
          </article>
        `).join("") : `<div class="career-list-empty">暂无内容</div>`}
      </div>
    </section>
  `).join("")}</div>`;
}

function averageResumeScores(values) {
  const numbers = (Array.isArray(values) ? values : [])
    .filter((item) => item != null && item !== "")
    .map(Number)
    .filter(Number.isFinite);
  if (!numbers.length) return null;
  return normalizeResumeScore(numbers.reduce((sum, item) => sum + item, 0) / numbers.length);
}

function resumeConfidenceTone(score) {
  const safeScore = normalizeResumeScore(score);
  if (safeScore == null) return { tone: "muted", label: "待验证", note: "缺少可比较的岗位技能证据，暂不计算覆盖率。" };
  if (safeScore < 50) {
    return {
      tone: "danger",
      label: "证据较少",
      note: "已识别岗位技能的简历证据较少，未体现不等于不会。"
    };
  }
  if (safeScore < 70) {
    return {
      tone: "warning",
      label: "部分体现",
      note: "部分技能已有文本证据，其余需要核实或补充成果。"
    };
  }
  if (safeScore < 85) {
    return {
      tone: "success",
      label: "多数体现",
      note: "多数已识别技能有文本证据，熟练程度仍需验证。"
    };
  }
  return {
    tone: "brand",
    label: "覆盖较全",
    note: "已识别技能的文本覆盖较全，不代表胜任或录用概率。"
  };
}

function resumeCapabilityMetrics(profile, analysisMode) {
  const scores = profile?.capability_scores && typeof profile.capability_scores === "object" ? profile.capability_scores : {};
  return [
    {
      key: "matching",
      label: "技能证据覆盖",
      value: resumeEvidenceScore(profile),
      note: "已识别岗位技能中，简历有对应文本证据的比例"
    },
    {
      key: "execution",
      label: "执行交付",
      value: normalizeResumeScore(scores.execution),
      note: "项目推进、落地和结果产出"
    },
    {
      key: "communication",
      label: "沟通协作",
      value: averageResumeScores([scores.communication, scores.collaboration]),
      note: "表达、协作和跨团队配合"
    },
    {
      key: "resilience",
      label: "抗压稳定",
      value: normalizeResumeScore(scores.stress_resilience),
      note: "面对节奏变化和不确定性的稳定度"
    },
    {
      key: "innovation",
      label: "创新成长",
      value: normalizeResumeScore(scores.innovation),
      note: "学习迁移、新方向理解和吸收速度"
    },
    {
      key: "leadership",
      label: "主动推进",
      value: normalizeResumeScore(scores.leadership),
      note: "主导意识、承担责任和推进能力"
    }
  ];
}

function resumeGaugeCardHtml(profile, matcher, analysisMode, recommendedDirections) {
  const score = resumeEvidenceScore(profile);
  const tone = resumeConfidenceTone(score);
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const matchedCount = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords.length : 0;
  const jobCount = matchedCount + (Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords.length : 0);
  const focusValue = analysisMode === "resume_review"
    ? (recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "待探索")
    : (jobOverview.job_title || normalizeResumeBasicValue(basics.target_direction) || "待识别");
  const subValue = analysisMode === "resume_review"
    ? (recommendedDirections.length ? `${recommendedDirections.length} 个建议方向` : "待生成建议方向")
    : `${matchedCount}/${jobCount || 0} 已识别技能有文本证据`;
  return `
    <section class="resume-bento-card resume-bento-span-4 resume-gauge-card">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Match Gauge</p>
          <p class="resume-bento-title">技能证据覆盖</p>
        </div>
        <span class="resume-score-chip ${tone.tone}">${escHtml(tone.label)}</span>
      </div>
      <div class="resume-gauge-shell">
        <div class="resume-gauge-ring ${tone.tone}" style="--score-angle:${((score || 0) * 3.6).toFixed(1)}deg;">
          <div class="resume-gauge-core">
            <strong>${resumeScoreLabel(score)}</strong>
            <span>技能证据覆盖</span>
          </div>
        </div>
      </div>
      <p class="resume-gauge-caption">${escHtml(tone.note)}</p>
      <div class="resume-gauge-metrics">
        <article class="resume-gauge-metric">
          <span>目标焦点</span>
          <strong>${escHtml(focusValue)}</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>当前状态</span>
          <strong>${escHtml(subValue)}</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>地点信息</span>
          <strong>${escHtml(normalizeResumeBasicValue(basics.target_city) || jobOverview.location || "未明确")}</strong>
        </article>
      </div>
    </section>
  `;
}

function resumeTargetPanelHtml(profile, matcher, analysisMode, recommendedDirections) {
  const jobOverview = matcher?.job_overview && typeof matcher.job_overview === "object" ? matcher.job_overview : {};
  const matchedKeywords = Array.isArray(matcher?.matched_keywords) ? matcher.matched_keywords : [];
  const missingKeywords = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const jobKeywords = Array.isArray(matcher?.job_keywords) ? matcher.job_keywords : [];
  const directionTags = previewTagValues(recommendedDirections, 8);
  const previewMatched = previewTagValues(matchedKeywords, 8);
  const previewMissing = previewTagValues(missingKeywords, 8);
  const fullMatched = previewTagValues(matchedKeywords, 120);
  const fullMissing = previewTagValues(missingKeywords, 120);
  const fullJobKeywords = previewTagValues(jobKeywords, 120);
  if (analysisMode === "resume_review") {
    return `
      <section class="resume-bento-card resume-bento-span-8 resume-target-panel">
        <div class="resume-bento-head">
          <div>
            <p class="resume-bento-kicker">Direction Suggestion</p>
            <p class="resume-bento-title">建议岗位方向</p>
          </div>
          <span class="resume-score-chip muted">无明确 JD</span>
        </div>
        <p class="resume-target-copy">系统会基于简历经历、技能和行为信号给出可尝试方向，并同步指出当前短板与下一步改写重点。</p>
        <div class="resume-target-tags">
          ${directionTags.length ? directionTags.map((tag) => `<span class="resume-analysis-tag">${escHtml(tag)}</span>`).join("") : `<span class="resume-radar-pill">正在生成建议方向</span>`}
        </div>
        <details class="resume-target-details" open>
          <summary>查看全部建议方向</summary>
          <div class="resume-target-detail-content">
            ${recommendedDirections.length ? recommendedDirections.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无方向</span>`}
          </div>
        </details>
      </section>
    `;
  }
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-target-panel">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Role Matching</p>
          <p class="resume-bento-title">岗位匹配要点</p>
        </div>
        <span class="resume-score-chip brand">${matchedKeywords.length}/${matchedKeywords.length + missingKeywords.length} 已识别技能有证据</span>
      </div>
      <div class="resume-target-stats">
        <article class="resume-target-stat">
          <span>目标岗位</span>
          <strong>${escHtml(jobOverview.job_title || "未识别")}</strong>
        </article>
        <article class="resume-target-stat">
          <span>公司 / 地点</span>
          <strong>${escHtml(jobOverview.company_name || "--")} · ${escHtml(jobOverview.location || "--")}</strong>
        </article>
        <article class="resume-target-stat">
          <span>待补技能证据</span>
          <strong>${missingKeywords.length} 项</strong>
        </article>
      </div>
      <div class="resume-target-group">
        <p class="resume-target-label">命中关键词</p>
        <div class="resume-target-tags">
          ${previewMatched.length ? previewMatched.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无命中</span>`}
        </div>
      </div>
      <div class="resume-target-group">
        <p class="resume-target-label">简历未体现的技能（待补证据）</p>
        <div class="resume-target-tags">
          ${previewMissing.length ? previewMissing.map((item) => `<span class="resume-radar-pill warning">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill positive">已识别技能暂无未体现项，仍需验证</span>`}
        </div>
      </div>
      <details class="resume-target-details">
        <summary>查看完整关键词清单</summary>
        <div class="resume-target-detail-content stacked">
          <div>
            <p class="resume-target-label">岗位关键词（全部）</p>
            <div class="resume-target-tags">
              ${fullJobKeywords.length ? fullJobKeywords.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无</span>`}
            </div>
          </div>
          <div>
            <p class="resume-target-label">命中关键词（全部）</p>
            <div class="resume-target-tags">
              ${fullMatched.length ? fullMatched.map((item) => `<span class="resume-analysis-tag">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill">暂无</span>`}
            </div>
          </div>
          <div>
            <p class="resume-target-label">简历未体现的技能（待补证据）（全部）</p>
            <div class="resume-target-tags">
              ${fullMissing.length ? fullMissing.map((item) => `<span class="resume-radar-pill warning">${escHtml(item)}</span>`).join("") : `<span class="resume-radar-pill positive">暂无</span>`}
            </div>
          </div>
        </div>
      </details>
    </section>
  `;
}

function resumeGaugePlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-4 resume-gauge-card is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Match Gauge</p>
          <p class="resume-bento-title">匹配度仪表盘</p>
        </div>
        <span class="resume-score-chip muted">等待分析</span>
      </div>
      <div class="resume-gauge-shell">
        <div class="resume-gauge-ring muted" style="--score-angle:0deg;">
          <div class="resume-gauge-core">
            <strong>--</strong>
            <span>综合判断</span>
          </div>
        </div>
      </div>
      <p class="resume-gauge-caption">上传简历并开始匹配后，这里会显示综合匹配度、状态分级和关键焦点。</p>
      <div class="resume-gauge-metrics">
        <article class="resume-gauge-metric">
          <span>目标焦点</span>
          <strong>等待识别</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>当前状态</span>
          <strong>等待分析</strong>
        </article>
        <article class="resume-gauge-metric">
          <span>地点信息</span>
          <strong>待补充</strong>
        </article>
      </div>
    </section>
  `;
}

function resumeTargetPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-target-panel is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Direction / Role</p>
          <p class="resume-bento-title">方向或岗位匹配要点</p>
        </div>
        <span class="resume-score-chip muted">等待分析</span>
      </div>
      <p class="resume-target-copy">无目标岗位时会显示建议方向；有岗位文本时会显示命中项、缺口项和完整关键词清单。</p>
      <div class="resume-target-tags">
        <span class="resume-radar-pill">等待解析</span>
      </div>
    </section>
  `;
}

function resumeScoreCardsHtml(profile, analysisMode) {
  const definitions = resumeCapabilityMetrics(profile, analysisMode).filter((item) => ["matching", "execution", "communication", "leadership"].includes(item.key));
  return definitions.map((item) => {
    const toneClass = {
      matching: "brand",
      execution: "success",
      communication: "warning",
      leadership: "muted"
    }[item.key] || "brand";
    const score = normalizeResumeScore(item.value);
    return `
      <article class="resume-score-card ${toneClass}">
        <div class="resume-score-head">
          <p class="resume-score-label">${escHtml(item.label)}</p>
          <span class="resume-score-value">${resumeScoreLabel(score)}</span>
        </div>
        <div class="resume-score-track">
          <div class="resume-score-fill" style="width:${score || 0}%"></div>
        </div>
        <p class="resume-score-note">${escHtml(item.note)}</p>
      </article>
    `;
  }).join("");
}

function resumeScorePlaceholderHtml() {
  const definitions = [
    ["方向适配", "和建议方向或岗位的贴合度"],
    ["执行交付", "项目推进、落地和结果产出"],
    ["沟通协作", "表达、协作和跨团队配合"],
    ["主动推进", "主导意识和推进能力"]
  ];
  return definitions.map((item) => `
    <article class="resume-score-card muted is-placeholder">
      <div class="resume-score-head">
        <p class="resume-score-label">${escHtml(item[0])}</p>
        <span class="resume-score-value">--</span>
      </div>
      <div class="resume-score-track">
        <div class="resume-score-fill" style="width:0%"></div>
      </div>
      <p class="resume-score-note">${escHtml(item[1])}</p>
    </article>
  `).join("");
}

function resumeStackDeckHtml(deckId, items, options = {}) {
  const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!safeItems.length) {
    return `<div class="career-list-empty">${escHtml(options.emptyText || "暂无内容")}</div>`;
  }
  const safeDeckId = String(deckId || "resume-deck").replace(/'/g, "\\'");
  const variantClass = options.variant ? ` ${options.variant}` : "";
  const isSingle = safeItems.length <= 1;
  return `
    <div class="resume-stack-deck${variantClass}" data-resume-deck="${escHtml(deckId)}" data-total="${safeItems.length}">
      <div class="resume-stack-stage">
        ${!isSingle ? `<button type="button" class="resume-stack-arrow prev" onclick="shiftResumeStackDeck('${safeDeckId}', -1)" aria-label="上一张卡片">‹</button>` : ""}
        ${safeItems.map((item, index) => `
          <article
            class="resume-stack-card ${escHtml(item.tone || options.tone || "tone-brand")}"
            data-card-index="${index}"
            data-position="hidden"
            role="button"
            tabindex="0"
            onclick="advanceResumeStackDeck('${safeDeckId}')"
            onkeydown="handleResumeStackDeckKey(event, '${safeDeckId}')"
          >
            <div class="resume-stack-card-head">
              <span class="resume-stack-order">${String(index + 1).padStart(2, "0")}</span>
              ${item.badge ? `<span class="resume-stack-badge">${escHtml(item.badge)}</span>` : ""}
            </div>
            ${item.label ? `<p class="resume-stack-label">${escHtml(item.label)}</p>` : ""}
            <p class="resume-stack-title">${escHtml(item.title || "待生成")}</p>
            <p class="resume-stack-copy">${escHtml(item.copy || "等待生成内容")}</p>
            ${item.note ? `<p class="resume-stack-note">${escHtml(item.note)}</p>` : ""}
          </article>
        `).join("")}
        ${!isSingle ? `<button type="button" class="resume-stack-arrow next" onclick="shiftResumeStackDeck('${safeDeckId}', 1)" aria-label="下一张卡片">›</button>` : ""}
      </div>
      <div class="resume-stack-footer ${isSingle ? "single" : ""}">
        <div class="resume-stack-dots">
          ${safeItems.map((_, index) => `<button type="button" class="resume-stack-dot" data-dot-index="${index}" onclick="setResumeStackDeck('${safeDeckId}', ${index})" aria-label="查看第 ${index + 1} 张卡片"></button>`).join("")}
        </div>
        <span class="resume-stack-progress">1 / ${safeItems.length}</span>
      </div>
    </div>
  `;
}

function getResumeStackDeck(deckId) {
  return document.querySelector(`[data-resume-deck="${String(deckId || "").replace(/"/g, '\\"')}"]`);
}

function updateResumeStackDeck(deckId, nextIndex = 0) {
  const deck = getResumeStackDeck(deckId);
  if (!deck) return;
  const cards = Array.from(deck.querySelectorAll(".resume-stack-card"));
  if (!cards.length) return;
  const total = cards.length;
  const normalizedIndex = ((Number(nextIndex) % total) + total) % total;
  resumeTaskState.deckIndices[deckId] = normalizedIndex;
  cards.forEach((card, index) => {
    const offset = (index - normalizedIndex + total) % total;
    const position = offset === 0 ? "active" : offset === 1 ? "next" : offset === 2 ? "later" : "hidden";
    card.dataset.position = position;
    card.setAttribute("aria-hidden", position === "active" ? "false" : "true");
  });
  deck.querySelectorAll(".resume-stack-dot").forEach((dot, index) => {
    dot.classList.toggle("active", index === normalizedIndex);
  });
  const progress = deck.querySelector(".resume-stack-progress");
  if (progress) progress.textContent = `${normalizedIndex + 1} / ${total}`;
}

function setResumeStackDeck(deckId, nextIndex) {
  updateResumeStackDeck(deckId, nextIndex);
}

function shiftResumeStackDeck(deckId, delta) {
  const current = Number(resumeTaskState.deckIndices[deckId] || 0);
  updateResumeStackDeck(deckId, current + Number(delta || 0));
}

function advanceResumeStackDeck(deckId) {
  shiftResumeStackDeck(deckId, 1);
}

function handleResumeStackDeckKey(event, deckId) {
  if (!event) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    advanceResumeStackDeck(deckId);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    shiftResumeStackDeck(deckId, -1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    shiftResumeStackDeck(deckId, 1);
  }
}

/** @param {Document | HTMLElement} [root] */
function initResumeStackDecks(root = document) {
  root.querySelectorAll("[data-resume-deck]").forEach((deck) => {
    const deckId = String(deck.dataset.resumeDeck || "").trim();
    if (!deckId) return;
    const savedIndex = Number(resumeTaskState.deckIndices[deckId] || 0);
    updateResumeStackDeck(deckId, savedIndex);
  });
}

function resumeInsightCardsHtml(profile) {
  const items = Array.isArray(profile?.capability_layer) ? profile.capability_layer.slice(0, 3) : [];
  if (!items.length) {
    return `<div class="career-list-empty">等待生成重点判断</div>`;
  }
  const tones = ["tone-brand", "tone-calm", "tone-warm"];
  return resumeStackDeckHtml("resume-insights", items.map((item, index) => ({
    tone: tones[index % tones.length],
    label: item.dimension || "重点判断",
    badge: item.confidence == null ? "待验证" : `${Math.round(Math.max(0, Math.min(1, Number(item.confidence))) * 100)}%`,
    title: item.conclusion || "等待生成结论",
    copy: shortenResumeText(item.reasoning || item.evidence || "", 144),
    note: item.boundary ? `边界：${shortenResumeText(item.boundary, 84)}` : ""
  })), {
    variant: "analysis",
    emptyText: "等待生成重点判断"
  });
}

function resumeInsightPlaceholderHtml() {
  const items = [
    ["岗位理解", "这里会出现系统提炼的第一条重点判断。"],
    ["能力结构", "这里会总结简历最强和最弱的维度。"],
    ["风险判断", "这里会明确告诉你最值得优先修复的问题。"]
  ];
  return resumeStackDeckHtml("resume-insights", items.map((item, index) => ({
    tone: ["tone-brand", "tone-calm", "tone-warm"][index],
    label: item[0],
    badge: "--",
    title: "等待生成判断",
    copy: item[1]
  })), {
    variant: "analysis"
  });
}

function buildResumeGapItems(profile, matcher, analysisMode) {
  const gapItems = [];
  if (analysisMode !== "resume_review") {
    (Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : []).slice(0, 4).forEach((item) => {
      gapItems.push({
        title: String(item || "").trim(),
        copy: "岗位侧明确提到，但当前简历没有给出足够证据。"
      });
    });
  }
  (Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : []).slice(0, 4).forEach((item) => {
    gapItems.push({
      title: String(item?.item || item?.reason || "待确认信息").trim(),
      copy: String(item?.needed_evidence || item?.reason || "建议补充更直接的项目、结果或量化证据。").trim()
    });
  });
  const deduped = [];
  const seen = new Set();
  gapItems.forEach((item) => {
    const key = `${item.title}::${item.copy}`;
    if (!item.title || seen.has(key)) return;
    seen.add(key);
    deduped.push(item);
  });
  return deduped.slice(0, 4);
}

function resumeGapPanelHtml(profile, matcher, analysisMode) {
  const items = buildResumeGapItems(profile, matcher, analysisMode);
  const deckItems = items.length ? items.map((item, index) => ({
    tone: ["tone-warm", "tone-rose", "tone-calm", "tone-brand"][index % 4],
    label: index === 0 ? "优先补强" : "补强项",
    badge: `0${index + 1}`,
    title: item.title,
    copy: shortenResumeText(item.copy, 126),
    note: index === 0 ? "建议优先补齐这张卡，再继续看下一项。" : ""
  })) : [{
    tone: "tone-mint",
    label: "当前状态",
    badge: "OK",
    title: "已识别技能暂无未体现项，仍需验证熟练度",
    copy: "系统暂时没有识别出高优先级缺口，可以把注意力放到投递和面试反馈上。"
  }];
  return `
    <section class="resume-bento-card resume-bento-span-4">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Gap Focus</p>
          <p class="resume-bento-title">待补技能证据</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-gaps", deckItems, {
        variant: "compact",
        emptyText: "已识别技能暂无未体现项，仍需验证熟练度"
      })}
    </section>
  `;
}

function resumeGapPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-4 is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Gap Focus</p>
          <p class="resume-bento-title">待补技能证据</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-gaps", [{
        tone: "tone-warm",
        label: "待补技能证据",
        badge: "01",
        title: "等待分析",
        copy: "系统会把岗位缺口、简历信息空白和待确认风险拆成更直接的补强项。"
      }], {
        variant: "compact"
      })}
    </section>
  `;
}

function buildResumeActionItems(profile, matcher, analysisMode, recommendedDirections) {
  const actions = [];
  const basics = profile?.basics && typeof profile.basics === "object" ? profile.basics : {};
  const missingKeywords = Array.isArray(matcher?.missing_keywords) ? matcher.missing_keywords : [];
  const uncertainty = Array.isArray(profile?.uncertainty_layer) ? profile.uncertainty_layer : [];
  const projectHighlights = Array.isArray(profile?.project_highlights) ? profile.project_highlights : [];
  const leadershipSignals = Array.isArray(profile?.leadership_signals) ? profile.leadership_signals : [];
  const targetDirection = recommendedDirections[0] || normalizeResumeBasicValue(basics.target_direction) || "目标方向";

  if (analysisMode === "resume_review") {
    actions.push({
      label: "方向收敛",
      title: `先验证 ${targetDirection}`,
      copy: "先用 1 到 2 个岗位名称收敛投递范围，再围绕这些岗位改写简历关键词和项目标题。"
    });
  } else if (missingKeywords.length) {
    actions.push({
      label: "补关键词",
      title: `优先补进 ${missingKeywords.slice(0, 2).join(" / ")}`,
      copy: "不要只堆技能词，直接把动作、场景和结果写进经历句子里，让岗位要求和简历证据对上。"
    });
  }

  if (uncertainty.length) {
    actions.push({
      label: "补证据",
      title: `把“${String(uncertainty[0]?.item || uncertainty[0]?.reason || "关键信号").trim()}”写实`,
      copy: "优先补充项目规模、角色边界、具体动作和量化结果，减少 HR 对真实性和深度的疑问。"
    });
  }

  if (projectHighlights.length < 2) {
    actions.push({
      label: "补经历",
      title: "增加一段可量化项目",
      copy: "优先写最能证明执行力和业务理解的经历，格式尽量变成“做了什么 + 结果如何 + 影响多大”。"
    });
  }

  if (leadershipSignals.length < 2) {
    actions.push({
      label: "强化表达",
      title: "把主动动作写在句首",
      copy: "少用参与、协助，多用主导、推进、负责、完成，并补上对象、方法和结果。"
    });
  }

  if (!actions.length) {
    actions.push({
      label: "继续推进",
      title: "保持当前版本并开始投递",
      copy: "当前画像没有明显短板，建议优先投递最匹配的岗位，同时根据面试反馈做小步快改。"
    });
  }

  return actions.slice(0, 3);
}

function resumeActionPanelHtml(profile, matcher, analysisMode, recommendedDirections, wide = false) {
  const items = buildResumeActionItems(profile, matcher, analysisMode, recommendedDirections);
  const deckItems = items.map((item, index) => ({
    tone: ["tone-brand", "tone-mint", "tone-calm"][index % 3],
    label: item.label,
    badge: `0${index + 1}`,
    title: item.title,
    copy: shortenResumeText(item.copy, wide ? 168 : 132),
    note: index === 0 ? "点击卡片可继续看下一条建议，适合一步步执行。" : ""
  }));
  return `
    <section class="resume-bento-card ${wide ? "resume-bento-span-8" : "resume-bento-span-4"} resume-action-panel">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Action Plan</p>
          <p class="resume-bento-title">操作建议</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-actions", deckItems, {
        variant: wide ? "analysis" : "compact"
      })}
    </section>
  `;
}

function resumeActionPlaceholderHtml() {
  return `
    <section class="resume-bento-card resume-bento-span-8 resume-action-panel is-placeholder">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Action Plan</p>
          <p class="resume-bento-title">操作建议</p>
        </div>
      </div>
      ${resumeStackDeckHtml("resume-actions", [
        {
          tone: "tone-brand",
          label: "上传简历",
          badge: "01",
          title: "先完成简历文本解析",
          copy: "上传 PDF 或 DOCX 后，系统会提取经历、项目、技能和关键信号，开始建立能力画像。"
        },
        {
          tone: "tone-mint",
          label: "补充方向",
          badge: "02",
          title: "JD 可写可不写",
          copy: "如果你没有明确目标岗位，可以先留空，系统会先从简历本身给出方向判断和改写建议。"
        }
      ], {
        variant: "analysis"
      })}
    </section>
  `;
}

function resumeProjectHighlightsHtml(profile) {
  const items = Array.isArray(profile?.project_highlights) ? profile.project_highlights.slice(0, 3) : [];
  if (!items.length) return "";
  return `
    <section class="resume-bento-card resume-bento-span-8">
      <div class="resume-bento-head">
        <div>
          <p class="resume-bento-kicker">Highlights</p>
          <p class="resume-bento-title">亮点经历</p>
        </div>
      </div>
      <div class="resume-project-grid">
        ${items.map((item) => {
          const impactTags = previewTagValues(String(item.impact || "").split(/[、,，]/).map((part) => part.trim()).filter(Boolean), 3);
          return `
            <article class="resume-project-card">
              <div class="resume-project-head">
                <p class="resume-project-title">${escHtml(item.project || "项目亮点")}</p>
                ${item.role ? `<span class="resume-project-role">${escHtml(item.role)}</span>` : ""}
              </div>
              ${impactTags.length ? `<div class="resume-project-tags">${impactTags.map((tag) => `<span class="resume-project-tag">${escHtml(tag)}</span>`).join("")}</div>` : ""}
              <p class="resume-project-copy">${escHtml(shortenResumeText(item.evidence || "等待补充项目说明", 132))}</p>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function resumeEmptyDashboardHtml(state) {
  const status = String(state?.status || "").trim();
  const hasFile = Boolean(state?.file_name);
  const bannerTitle = status === "failed"
    ? "本次分析未生成结果"
    : hasFile
      ? "简历已上传，等待开始匹配"
      : "等待生成诊断报告";
  const bannerCopy = status === "failed"
    ? (humanizeResumeErrorMessage(state?.error_message || state?.analysis_meta?.stage_detail || "") || "当前没有得到可展示的分析结果，建议检查文件内容后重试。")
    : hasFile
      ? "点击“开始匹配”生成简历诊断报告。"
      : "上传简历后开始匹配。";
  return `
    <div class="resume-judge-shell is-placeholder">
      <section class="resume-judge-hero is-placeholder">
        <div class="resume-judge-hero-main">
          <div class="resume-judge-hero-top">
            <div>
              <span class="resume-judge-badge muted">待生成</span>
              <h4 class="resume-judge-title">${escHtml(bannerTitle)}</h4>
              <p class="resume-judge-copy">${escHtml(bannerCopy)}</p>
            </div>
            <div class="resume-judge-actions">
              <button type="button" class="resume-judge-action-btn primary" onclick="pickResumeFile()">上传简历</button>
              <button type="button" class="resume-judge-action-btn" onclick="analyzeResumeMatch()" ${hasFile ? "" : "disabled"}>开始匹配</button>
            </div>
          </div>
          <p class="resume-judge-meta">${hasFile ? `文件：${escHtml(state.file_name || "")}` : "上传 PDF 或 DOCX 后，这里会生成完整分析。"}</p>
          <div class="resume-judge-score-grid">
            <article class="resume-judge-score-card primary"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">综合评分</span></article>
            <article class="resume-judge-score-card"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">岗位匹配</span></article>
            <article class="resume-judge-score-card warm"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">故事线</span></article>
            <article class="resume-judge-score-card success"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">技术深度</span></article>
            <article class="resume-judge-score-card"><span class="resume-judge-score-value">--</span><span class="resume-judge-score-label">格式规范</span></article>
          </div>
        </div>
      </section>

      <div class="resume-judge-empty-card">
        <div class="resume-judge-empty-copy">
          <p class="resume-judge-empty-title">${escHtml(status === "failed" ? "请先修正文件后再重新匹配" : "等待简历分析")}</p>
          <p class="resume-judge-empty-text">${escHtml(bannerCopy)}</p>
        </div>
        <div class="resume-judge-tabbar is-placeholder">
          <button type="button" class="resume-judge-tab-btn active" disabled>01 30 秒结论</button>
          <button type="button" class="resume-judge-tab-btn" disabled>02 详细诊断</button>
          <button type="button" class="resume-judge-tab-btn" disabled>03 优化建议</button>
          <button type="button" class="resume-judge-tab-btn" disabled>04 简历范本</button>
          <button type="button" class="resume-judge-tab-btn" disabled>05 最终裁决</button>
        </div>
      </div>
    </div>
  `;
}

function resumeEvidencePlaceholderHtml() {
  const groups = [
    ["来自简历", "系统会从简历原文中截取关键证据片段。"],
    ["行为信号", "这里会聚合推进、主导、沟通协作等行为信号。"],
    ["待确认", "这里会列出需要继续补证据的空白点。"]
  ];
  return `<div class="resume-evidence-grid">${groups.map((item) => `
    <section class="resume-evidence-group neutral is-placeholder">
      <div class="resume-evidence-group-head">
        <p class="resume-evidence-group-title">${escHtml(item[0])}</p>
        <span class="resume-evidence-group-count">--</span>
      </div>
      <div class="resume-evidence-group-list">
        <article class="resume-evidence-entry">
          <p class="resume-evidence-title">等待生成</p>
          <p class="resume-evidence-copy">${escHtml(item[1])}</p>
        </article>
      </div>
    </section>
  `).join("")}</div>`;
}

function resumePlainText(raw) {
  return decodeHtmlEntities(String(raw || "").replace(/<[^>]+>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}
