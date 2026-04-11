(function () {
  let reportDoc = null;

  const $ = (s) => document.querySelector(s);
  const esc = (v) => String(v || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const strip = (v) => String(v || "").replace(/\[(.+?)\]\((.+?)\)/g, "$1").replace(/\*\*(.+?)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/^#+\s+/gm, "").trim();
  const inline = (v) => esc(v).replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>').replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const api = (p) => {
    const b = String(window.__API_BASE__ || "").trim().replace(/\/+$/, "");
    if (!b || /^https?:\/\//i.test(p)) return p;
    return p.startsWith("/") ? `${b}${p}` : `${b}/${p}`;
  };

  async function json(path, options) {
    const r = await fetch(api(path), {
      credentials: "include",
      ...options,
      headers: { "Content-Type": "application/json", ...(options && options.headers ? options.headers : {}) },
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(String(d.message || "请求失败"));
    return d;
  }

  function md(text) {
    const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let items = [], type = "", code = [], inCode = false;
    const flushList = () => {
      if (!items.length) return;
      const tag = type === "ol" ? "ol" : "ul";
      out.push(`<${tag}>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</${tag}>`);
      items = []; type = "";
    };
    const flushCode = () => {
      if (!code.length) return;
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      code = [];
    };
    lines.forEach((raw) => {
      const t = raw.trimEnd(), s = t.trim();
      if (s.startsWith("```")) { flushList(); inCode ? flushCode() : 0; inCode = !inCode; return; }
      if (inCode) { code.push(raw); return; }
      if (!s) { flushList(); return; }
      if (s === "---") { flushList(); return; }
      if (/^\s*\d+\.\s+/.test(raw)) { if (type && type !== "ol") flushList(); type = "ol"; items.push(s.replace(/^\d+\.\s+/, "")); return; }
      if (/^\s*[-*]\s+/.test(raw)) { if (type && type !== "ul") flushList(); type = "ul"; items.push(s.replace(/^[-*]\s+/, "")); return; }
      flushList();
      if (/^####\s+/.test(s)) out.push(`<h4>${inline(s.slice(5))}</h4>`);
      else if (/^###\s+/.test(s)) out.push(`<h3>${inline(s.slice(4))}</h3>`);
      else if (/^##\s+/.test(s)) out.push(`<h3>${inline(s.slice(3))}</h3>`);
      else if (/^#\s+/.test(s)) out.push(`<h2>${inline(s.slice(2))}</h2>`);
      else out.push(`<p>${inline(s)}</p>`);
    });
    flushList(); flushCode();
    return out.join("");
  }

  const bullets = (lines) => (lines || []).filter((x) => /^\s*[-*]\s+/.test(String(x || ""))).map((x) => String(x).trim().replace(/^[-*]\s+/, ""));
  const ordered = (lines) => (lines || []).filter((x) => /^\s*\d+\.\s+/.test(String(x || ""))).map((x) => String(x).trim().replace(/^\d+\.\s+/, ""));
  const summary = (lines, n = 150) => {
    const t = strip((lines || []).join(" ").replace(/---/g, " "));
    return !t ? "" : (t.length > n ? `${t.slice(0, n)}...` : t);
  };

  function blocks(lines) {
    const arr = []; let cur = null;
    (lines || []).forEach((raw) => {
      const s = String(raw || "").trim();
      if (!s || s === "---") return;
      if (/^\d+\.\s+/.test(s)) {
        if (cur) arr.push(cur);
        cur = { title: s.replace(/^\d+\.\s+/, ""), lines: [] };
        return;
      }
      if (cur) cur.lines.push(raw);
    });
    if (cur) arr.push(cur);
    return arr.map((b, idx) => ({ ...b, idx: idx + 1, html: md((b.lines || []).join("\n")) }));
  }

  function pair(text) {
    const c = strip(text).replace(/^[\d.\-\s]+/, "");
    const m = c.match(/^([^：:]{2,30})[：:]\s*(.+)$/);
    return m ? { label: m[1].trim(), body: m[2].trim() } : null;
  }

  function mode(resume) {
    const m = resume && typeof resume.matcher === "object" ? resume.matcher : {};
    return String(m.analysis_mode || resume?.analysis_meta?.analysis_mode || "").trim() || "resume_review";
  }

  function has(resume) {
    return String(resume?.status || "") === "analyzed" && Boolean(String(resume?.analysis_result || "").trim() || String(resume?.analysis_html || "").trim());
  }

  function markdown(resume) {
    const direct = String(resume?.analysis_result || "").trim();
    if (direct) return direct;
    const html = String(resume?.analysis_html || "").trim();
    if (!html) return "";
    const box = document.createElement("div");
    box.innerHTML = html;
    const code = box.querySelector("pre code");
    return String(code?.textContent || box.textContent || "").trim();
  }

  function titleOf(raw) {
    return strip(raw).replace(/^step\s*\d+\s*:\s*/i, "").replace(/\s*\(([A-Za-z][^)]*)\)\s*$/g, "").replace(/[：:]\s*$/, "").trim();
  }

  function doc(resume) {
    const text = markdown(resume), lines = text.replace(/\r\n/g, "\n").split("\n");
    const out = { markdown: text, intro: [], sections: [] };
    let sec = null, sub = null, inCode = false;
    const push = () => { if (sec) out.sections.push(sec); sec = null; sub = null; };
    lines.forEach((raw) => {
      const s = raw.trim();
      if (s.startsWith("```")) inCode = !inCode;
      if (!inCode && /^###\s+/.test(s)) { push(); sec = { id: `tab-${out.sections.length}`, index: out.sections.length + 1, title: titleOf(s.slice(4)), lines: [], lead: [], subs: [] }; return; }
      if (!inCode && /^####\s+/.test(s) && sec) { sub = { title: titleOf(s.slice(5)), lines: [] }; sec.subs.push(sub); return; }
      if (!sec) { if (s) out.intro.push(raw); return; }
      sec.lines.push(raw); sub ? sub.lines.push(raw) : sec.lead.push(raw);
    });
    push();
    if (!out.sections.length && text) out.sections.push({ id: "tab-0", index: 1, title: "完整诊断", lines, lead: lines, subs: [] });
    out.sections = out.sections.map((s) => ({
      ...s,
      html: md((s.lines || []).join("\n")),
      leadHtml: md((s.lead || []).join("\n")),
      bullets: bullets(s.lead.length ? s.lead : s.lines),
      ordered: ordered(s.lead.length ? s.lead : s.lines),
      blocks: blocks(s.lines),
      sum: summary(s.lead.length ? s.lead : s.lines),
      subs: (s.subs || []).map((x) => ({ ...x, html: md((x.lines || []).join("\n")), bullets: bullets(x.lines), blocks: blocks(x.lines), sum: summary(x.lines, 120) })),
    }));
    return out;
  }

  function stats(resume, d) {
    const p = resume && typeof resume.profile === "object" ? resume.profile : {};
    const m = resume && typeof resume.matcher === "object" ? resume.matcher : {};
    const conf = p.confidence ? Math.round(Number(p.confidence) * 100) : 95;
    const matched = Array.isArray(m.matched_keywords) ? m.matched_keywords.length : 0;
    const all = Array.isArray(m.job_keywords) ? m.job_keywords.length : 0;
    const focus = mode(resume) === "job_match" ? (all ? Math.round((matched / all) * 100) : 88) : Math.min(88, 48 + d.sections.length * 8);
    const action = d.sections.find((x) => /行动|蓝图|建议|裁决/.test(x.title));
    const actionCount = (action?.blocks || []).length || (action?.ordered || []).length || 2;
    const project = Array.isArray(p.project_highlights) ? p.project_highlights.length : 3;
    return [
      { label: "综合判断", value: conf, note: "结构化候选人画像信心值" },
      { label: mode(resume) === "job_match" ? "岗位匹配度" : "方向清晰度", value: focus, note: mode(resume) === "job_match" ? "与 JD 的关键词命中情况" : "对目标方向的判断强度" },
      { label: "项目推进力", value: Math.min(99, 42 + project * 8), note: "经历中的落地、推进与结果表达" },
      { label: "软技能展示", value: Math.min(95, 24 + actionCount * 10), note: "协作、沟通、故事线与业务表达" },
    ];
  }

  function radar(resume, d) {
    const arr = stats(resume, d);
    const dims = [
      ["学术背景", arr[0].value, "var(--accent-cyan)"],
      ["技术匹配", arr[1].value, "var(--accent-green)"],
      ["项目推进", arr[2].value, "var(--accent-orange)"],
      ["软技能", arr[3].value, "var(--accent-purple)"],
      ["一致性", /时间信息矛盾|未来时间/.test(d.markdown) ? 45 : 82, "var(--accent-pink)"],
      ["内容精炼", 74, "var(--accent-red)"],
    ];
    const cx = 160, cy = 160, r = 108, n = dims.length;
    const pt = (lv, idx) => {
      const a = -Math.PI / 2 + (Math.PI * 2 / n) * idx;
      return { x: cx + Math.cos(a) * r * lv, y: cy + Math.sin(a) * r * lv };
    };
    const poly = (lv) => dims.map((_, idx) => { const p = pt(lv, idx); return `${p.x},${p.y}`; }).join(" ");
    const data = dims.map((x, idx) => ({ ...pt(x[1] / 100, idx), c: x[2] }));
    return `<svg width="320" height="320" viewBox="0 0 320 320">
      ${[1, 0.75, 0.5, 0.25].map((lv) => `<polygon points="${poly(lv)}" fill="none" stroke="rgba(0,0,0,0.06)" stroke-width="1"></polygon>`).join("")}
      ${dims.map((_, idx) => { const p = pt(1, idx); return `<line x1="${cx}" y1="${cy}" x2="${p.x}" y2="${p.y}" stroke="rgba(0,0,0,0.08)" stroke-width="1"></line>`; }).join("")}
      <polygon points="${data.map((p) => `${p.x},${p.y}`).join(" ")}" fill="rgba(14,165,233,0.15)" stroke="var(--accent-cyan)" stroke-width="2"></polygon>
      ${data.map((p) => `<circle cx="${p.x}" cy="${p.y}" r="4" fill="${p.c}"></circle>`).join("")}
      ${dims.map((x, idx) => { const p = pt(1.14, idx); const a = idx === 0 || idx === 3 ? "middle" : (p.x > cx ? "start" : "end"); return `<text x="${p.x}" y="${p.y}" text-anchor="${a}" font-size="11" fill="var(--text-secondary)" font-weight="600">${esc(x[0])}</text>`; }).join("")}
    </svg>`;
  }

  const metricHtml = (resume, d) => `<div class="dashboard-grid">${stats(resume, d).map((x) => `<div class="metric-card"><div class="metric-value">${x.value}</div><div class="metric-label">${esc(x.label)}</div><div class="metric-note">${esc(x.note)}</div><div class="metric-bar"><div class="metric-bar-fill" style="width:${x.value}%"></div></div></div>`).join("")}</div>`;
  const leadCard = (item, kind) => {
    const p = pair(item) || { label: kind === "b" ? "30秒定论" : "目标定位判断", body: strip(item) };
    return `<div class="liquid-card ${kind === "a" ? "liquid-border" : ""}"${kind === "b" ? ' style="border-left:4px solid var(--accent-green);"' : ""}>
      <h3 class="card-title ${kind === "b" ? "green" : "cyan"}"><span>${kind === "b" ? "⚡" : "🎯"}</span><span>${esc(p.label)}</span></h3>
      <p>${inline(p.body)}</p>
    </div>`;
  };

  function auditGroups(items) {
    const out = []; let cur = null;
    (items || []).forEach((t) => {
      const c = String(t || "").trim();
      if (!c) return;
      if (/^❓/.test(c) || /^问题/.test(strip(c))) { if (cur) out.push(cur); cur = { q: c, a: "", s: "" }; return; }
      if (!cur) cur = { q: c, a: "", s: "" };
      if (/^🤔/.test(c) || /负面影响/.test(strip(c))) cur.a = c;
      else if (/^💡/.test(c) || /建议/.test(strip(c))) cur.s = c;
      else if (!cur.a) cur.a = c;
      else if (!cur.s) cur.s = c;
    });
    if (cur) out.push(cur);
    return out;
  }

  const auditCard = (g) => `<div class="liquid-card"><div class="audit-item"><div class="audit-question"><span class="audit-icon">❓</span><span>${inline((pair(g.q)?.body) || strip(g.q))}</span></div>${g.a ? `<div class="audit-impact"><span class="audit-impact-label">负面影响</span>${inline((pair(g.a)?.body) || strip(g.a).replace(/^🤔\s*/, ""))}</div>` : ""}${g.s ? `<div class="audit-suggestion"><span class="audit-suggestion-label">建议</span>${inline((pair(g.s)?.body) || strip(g.s).replace(/^💡\s*/, ""))}</div>` : ""}</div></div>`;

  function resumeTpl(section) {
    const m = String(section.markdown || section.lines?.join("\n") || "").match(/```(?:markdown|md)?\n([\s\S]*?)```/i);
    const text = String(m?.[1] || "").trim();
    if (!text) return `<div class="markdown-body">${section.html}</div>`;
    const lines = text.split("\n"); let name = "", contact = "", cur = null; const secs = [];
    const push = () => { if (cur) secs.push(cur); cur = null; };
    lines.forEach((raw) => {
      const s = raw.trim();
      if (!s) return;
      if (/^#\s+/.test(s) && !name) { name = strip(s.replace(/^#\s+/, "")); return; }
      if (/^##\s+/.test(s)) { push(); cur = { title: strip(s.replace(/^##\s+/, "")), lines: [] }; return; }
      if (!cur && !contact) { contact = strip(s); return; }
      if (cur) cur.lines.push(raw);
    });
    push();
    return `<div class="resume-header"><h3 class="resume-name">${esc(name || "修改后的简历")}</h3>${contact ? `<div class="resume-contact">${esc(contact)}</div>` : ""}</div>${secs.map((x) => `<section class="resume-section"><h4 class="resume-section-title">${esc(x.title)}</h4><div class="markdown-body">${md((x.lines || []).join("\n"))}</div></section>`).join("")}`;
  }

  function panel(section, idx, resume, d) {
    const head = `<div class="section-header"><div class="section-step">STEP ${String(idx + 1).padStart(2, "0")}</div><h2 class="section-title">${esc(section.title)}</h2>${(idx === 0 && summary(d.intro, 180)) || (idx > 0 && section.sum) ? `<p class="section-desc">${esc(idx === 0 ? summary(d.intro, 180) : section.sum)}</p>` : ""}</div>`;
    if (idx === 0 || /第一印象|初步诊断/.test(section.title)) {
      const items = section.bullets.length ? section.bullets : [section.sum];
      return `<div class="tab-panel ${idx === 0 ? "active" : ""}" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}${metricHtml(resume, d)}<div class="two-col">${leadCard(items[0] || "目标定位判断：系统已生成核心判断。", "a")}${leadCard(items[1] || "30秒定论：这份报告将按 Step 1-5 独立展示。", "b")}</div><div class="liquid-card" style="margin-top:24px;"><h3 class="card-title"><span>📊</span><span>能力维度雷达图</span></h3><div class="radar-wrap">${radar(resume, d)}</div></div></div>`;
    }
    if (idx === 1 || /深度审计|审计与指导/.test(section.title)) {
      const subs = section.subs.length ? section.subs : [{ title: "审计内容", bullets: bullets(section.lines), html: section.html }];
      return `<div class="tab-panel" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}${subs.map((sub) => `<section class="subsection"><h3 class="subsection-title">${esc(sub.title || "审计模块")}</h3>${auditGroups(sub.bullets).length ? `<div class="subsection-grid">${auditGroups(sub.bullets).map(auditCard).join("")}</div>` : `<div class="liquid-card"><div class="markdown-body">${sub.html}</div></div>`}</section>`).join("")}</div>`;
    }
    if (idx === 2 || /蓝图|修改/.test(section.title)) {
      return `<div class="tab-panel" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}<div class="liquid-card"><h3 class="subsection-title">战略修改蓝图</h3>${section.leadHtml ? `<div class="markdown-body">${section.leadHtml}</div>` : ""}${section.blocks.length ? `<div class="timeline">${section.blocks.map((b) => `<div class="timeline-item"><h4 class="timeline-title">${inline(b.title)}</h4><div class="markdown-body">${b.html}</div></div>`).join("")}</div>` : `<div class="markdown-body">${section.html}</div>`}</div></div>`;
    }
    if (idx === 3 || /简历范本|重构与展示|修改后的简历/.test(section.title)) {
      return `<div class="tab-panel" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}<div class="resume-template">${resumeTpl(section)}</div></div>`;
    }
    if (idx === 4 || /最终裁决|行动清单/.test(section.title)) {
      const bs = section.blocks.length ? section.blocks : section.ordered.map((x, i) => ({ title: x, idx: i + 1, html: "" }));
      return `<div class="tab-panel" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}${bs.slice(0, 2).length ? `<div class="summary-grid">${bs.slice(0, 2).map((b, i) => `<div class="liquid-card"><h3 class="card-title ${i === 0 ? "orange" : "cyan"}"><span>${i === 0 ? "⚠️" : "✅"}</span><span>${inline(b.title)}</span></h3><div class="markdown-body">${b.html}</div></div>`).join("")}</div>` : ""}<div class="liquid-card"><h3 class="subsection-title">行动清单</h3><ul class="checklist">${bs.map((b) => `<li class="checklist-item"><div class="check-icon">${String(b.idx).padStart(2, "0")}</div><div class="check-text"><span class="check-label">${inline(b.title)}</span>${b.html ? `<div class="markdown-body">${b.html}</div>` : ""}</div></li>`).join("")}</ul></div></div>`;
    }
    return `<div class="tab-panel" id="${section.id}" data-tab-index="${idx}"><div class="float-element"></div><div class="float-element"></div>${head}<div class="liquid-card"><div class="markdown-body">${section.html}</div></div></div>`;
  }

  function setStatus(text, tone) {
    const box = $(".nav-status");
    const t = $("#rrStatusText");
    if (t) t.textContent = text;
    if (!box) return;
    box.classList.remove("status-warning", "status-danger");
    if (tone === "warning") box.classList.add("status-warning");
    if (tone === "danger") box.classList.add("status-danger");
  }

  function renderTabs(d) {
    const root = $("#rrNavTabs");
    if (!root) return;
    root.innerHTML = d.sections.length
      ? d.sections.map((s, i) => `<button type="button" class="nav-tab ${i === 0 ? "active" : ""}" data-tab-index="${i}"><span class="tab-num">${String(i + 1).padStart(2, "0")}</span>${esc(s.title)}</button>`).join("")
      : '<div class="empty-tabs">当前还没有可切换的章节</div>';
  }

  function renderState(title, body, meta) {
    $("#rrNavTabs").innerHTML = '<div class="empty-tabs">完整诊断将在分析完成后解锁</div>';
    $("#rrMainContent").innerHTML = `<div class="state-shell"><div class="liquid-card state-card"><h2>${esc(title)}</h2><p>${esc(body)}</p>${meta ? `<p>${esc(meta)}</p>` : ""}<div class="state-actions"><a class="state-btn primary" href="/main.html#profile" data-return-last="1">返回上一界面</a><button type="button" class="state-btn secondary" data-rr-action="user-center">打开个人中心</button></div></div></div>`;
  }

  function switchTab(i) {
    document.querySelectorAll(".nav-tab").forEach((x, idx) => x.classList.toggle("active", idx === i));
    document.querySelectorAll(".tab-panel").forEach((x, idx) => x.classList.toggle("active", idx === i));
  }

  function setUser(user) {
    const name = String(user?.display_name || user?.displayName || user?.username || "未登录");
    const chip = $("#rrCurrentUser"), avatar = $("#rrAvatarBtn");
    if (chip) chip.textContent = name;
    if (avatar) avatar.textContent = name.slice(0, 1).toUpperCase();
  }

  function renderReport(resume) {
    reportDoc = doc(resume);
    renderTabs(reportDoc);
    $("#rrMainContent").innerHTML = reportDoc.sections.map((s, i) => panel(s, i, resume, reportDoc)).join("");
    setStatus(`AI 分析完成 · ${mode(resume) === "job_match" ? "岗位匹配" : "简历诊断"}`, "");
    switchTab(0);
  }

  function bind() {
    $("#rrNavTabs")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".nav-tab");
      if (btn) switchTab(Number(btn.dataset.tabIndex || 0));
    });
    $("#rrLogoutBtn")?.addEventListener("click", async () => {
      try { await json("/api/auth/logout", { method: "POST" }); } catch (_) {}
      window.location.href = "/main.html";
    });
    $("#rrAvatarBtn")?.addEventListener("click", () => { window.location.href = "/user-center.html#report-workspace"; });
    document.addEventListener("click", (e) => {
      const el = e.target.closest("[data-rr-action]");
      if (!el) return;
      if (el.dataset.rrAction === "user-center") window.location.href = "/user-center.html#report-workspace";
    });
  }

  async function init() {
    bind();
    setStatus("正在加载报告", "");
    const auth = await json("/api/auth/status?bootstrap=1").catch(() => null);
    if (!auth || !auth.authenticated || !auth.user) { window.location.href = "/main.html"; return; }
    setUser(auth.user);
    const resume = auth?.scoped_data?.resume_profile || await json("/api/resume/profile").catch(() => ({}));
    if (has(resume || {})) {
      renderReport(resume || {});
      return;
    }
    if (String(resume?.status || "") === "failed") {
      setStatus("分析生成失败", "danger");
      renderState("这次没有生成完整诊断页", String(resume?.error_message || resume?.analysis_meta?.stage_detail || "当前没有可展示的分析内容。"), resume?.file_name ? `文件：${resume.file_name}` : "");
      return;
    }
    if (resume?.file_name) {
      setStatus("等待开始分析", "warning");
      renderState("简历已上传，但还没有生成完整诊断", "回到上一界面点击“开始匹配”后，这里会按 6.html 的标签页结构显示 Step 1 到 Step 5。", resume.file_name);
      return;
    }
    setStatus("等待上传简历", "warning");
    renderState("当前账号还没有可展示的简历报告", "先上传简历并完成分析，完整深度诊断页才会解锁。", "");
  }

  window.switchResumeReportTab = switchTab;
  document.addEventListener("DOMContentLoaded", init);
})();
