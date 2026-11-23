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
  const ACTIVE_PROFILE_KEY = "rp_active_profile";
  function rememberedProfile() {
    try {
      const saved = localStorage.getItem(ACTIVE_PROFILE_KEY);
      if (saved && PROFILE_KEYS.includes(saved)) return saved;
    } catch (_) { /* ignore storage errors */ }
    const jobs = state.jobs?.length ? state.jobs : (state.boardJobs || []);
    if (jobs.length) {
      const counts = new Map();
      for (const job of jobs) {
        if (job.profile && PROFILE_KEYS.includes(job.profile)) {
          counts.set(job.profile, (counts.get(job.profile) || 0) + 1);
        }
      }
      const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
      if (top) return top;
    }
    return PROFILE_KEYS[0];
  }
  function setRememberedProfile(value) {
    if (!value || !PROFILE_KEYS.includes(value)) return;
    try { localStorage.setItem(ACTIVE_PROFILE_KEY, value); } catch (_) { /* ignore */ }
  }
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
  /* 八维仪表簇：每维一枚 line-icon + 色板角色，与漏斗 tile 同一套 tone 语义 */
  const DIMENSION_META = {
    role_match: ["target", "accent"], skills_align: ["layers", "info"],
    seniority: ["graduation", "brass"], compensation: ["banknote", "success"],
    interview_prob: ["users", "accent"], company_stage: ["building", "info"],
    market_fit: ["trend", "brass"], growth: ["sprout", "success"]
  };

  /* ---------- 面板小工具 ---------- */
  function alive(token, body) { return token === RP.drawerToken() && body.isConnected; }
  function section(title, iconName, tone) {
    const root = node("section", "", "rp-panel-section");
    if (title) {
      const h = node("h3", title);
      if (iconName) h.prepend(tile(iconName, tone || "accent", true));
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

  /* ---------- 1. 平台实时采集（scraping） ---------- */
  const INLINE_SVGS = {
    chrome: '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><clipPath id="rpChromeClip"><circle cx="12" cy="12" r="10"/></clipPath></defs><g clip-path="url(#rpChromeClip)"><circle cx="12" cy="12" r="10" fill="#4285F4"/><path d="M2 2h20v10H12a5 5 0 0 0-4.33 2.5L2 4.6Z" fill="#EA4335"/><path d="M2 4.6 7.67 14.5A5 5 0 0 0 12 17l-4 7H2Z" fill="#34A853"/><path d="M12 7h10v17H8l4-7a5 5 0 0 0 4.33-7.5Z" fill="#FBBC05"/></g><circle cx="12" cy="12" r="4.5" fill="#fff"/><circle cx="12" cy="12" r="3.4" fill="#4285F4"/></svg>',
    pulse: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 10h3.2l2-5 3.6 10 2.2-5h4"/></svg>',
    trash: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 5.5h13M8 5.5V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5m-6 0 .7 10.2a1.3 1.3 0 0 0 1.3 1.3h4a1.3 1.3 0 0 0 1.3-1.3L14 5.5"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>',
    pencil: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.8 3.6a1.9 1.9 0 0 1 2.7 2.7L7.3 15.5l-3.8 1 1-3.8 9.3-9.1Z"/></svg>',
    pin: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 17.2s5.2-4.6 5.2-8.7a5.2 5.2 0 1 0-10.4 0c0 4.1 5.2 8.7 5.2 8.7Z"/><circle cx="10" cy="8.5" r="1.8"/></svg>',
    briefcase: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.8" y="6" width="14.4" height="10.2" rx="2"/><path d="M7 6V4.6A1.6 1.6 0 0 1 8.6 3h2.8A1.6 1.6 0 0 1 13 4.6V6M2.8 10.5h14.4"/></svg>',
    grid: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3.2" y="3.2" width="5.4" height="5.4" rx="1.2"/><rect x="11.4" y="3.2" width="5.4" height="5.4" rx="1.2"/><rect x="3.2" y="11.4" width="5.4" height="5.4" rx="1.2"/><rect x="11.4" y="11.4" width="5.4" height="5.4" rx="1.2"/></svg>',
    cap: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.2 8.2 10 4.5l7.8 3.7L10 11.9 2.2 8.2Z"/><path d="M5.4 9.8v3.8c0 1.2 2.1 2.2 4.6 2.2s4.6-1 4.6-2.2V9.8"/><path d="M17.8 8.4v4.4"/></svg>',
    bolt: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 2.5 4.8 11h4.7L9 17.5 15.2 9h-4.7L11 2.5Z"/></svg>',
    chart: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 15.5v-4M10 15.5v-8M15.5 15.5v-11"/></svg>',
    doc: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5.5 2.8h6.2l3.8 3.8v10.6a1.3 1.3 0 0 1-1.3 1.3H5.5a1.3 1.3 0 0 1-1.3-1.3V4.1a1.3 1.3 0 0 1 1.3-1.3Z"/><path d="M11.5 2.8V6.8h4M7.2 10.5h5.6M7.2 13.8h3.8"/></svg>',
    ban: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="10" cy="10" r="7.2"/><path d="m5.2 5.2 9.6 9.6"/></svg>',
    code: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6.8 6.5-3.6 3.5 3.6 3.5M13.2 6.5l3.6 3.5-3.6 3.5M11.2 4.5l-2.4 11"/></svg>',
    monitor: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.8" y="3.8" width="14.4" height="9.8" rx="1.6"/><path d="M7.2 16.5h5.6M10 13.6v2.9"/></svg>',
    grip: '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><circle cx="5.5" cy="4" r="1.1"/><circle cx="10.5" cy="4" r="1.1"/><circle cx="5.5" cy="8" r="1.1"/><circle cx="10.5" cy="8" r="1.1"/><circle cx="5.5" cy="12" r="1.1"/><circle cx="10.5" cy="12" r="1.1"/></svg>'
  };
  const PLATFORM_TAGLINES = {
    "51job": "综合类招聘平台 · 岗位覆盖广",
    boss: "互联网招聘 · 沟通高效",
    xiaohongshu: "新兴招聘渠道 · 实习机会多",
    zhilian: "传统招聘平台 · 企业资源丰富"
  };
  function inlineIcon(name, cls) {
    const wrap = node("span", "", "rp-inline-svg" + (cls ? " " + cls : ""));
    wrap.innerHTML = INLINE_SVGS[name] || "";
    return wrap;
  }
  function compactTime(ts) {
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }


  RP.ui = {
    PROFILE_KEYS, rememberedProfile, setRememberedProfile,
    DEEP_KEYS, DIMENSION_LABELS, GRADE_OPTIONS, DIMENSION_META,
    alive, section, note, feedback, setFeedback, field, input, select,
    sourceLabel, sourceEntries, platformLogo, profileSelect, button,
    emptyBlock, gradeBadge, payloadOf, copyText, miniJob, withBusy,
    loadConfig, saveConfig, modeChip,
    INLINE_SVGS, PLATFORM_TAGLINES, inlineIcon, compactTime,
  };
})();
