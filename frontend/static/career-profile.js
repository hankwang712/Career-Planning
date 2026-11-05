(function () {
  "use strict";
  const API = "/api/career-profile";
  const kinds = { education: "教育背景", experience: "项目与工作经历", certificate: "证书与资格", interest: "职业兴趣", preference: "求职偏好" };
  const stages = { student: "在校学习", graduate: "应届求职", employed: "在职发展", transition: "职业转型" };
  const tests = { mbti: "MBTI 性格倾向", holland: "霍兰德职业兴趣", deep: "深层 MBTI", friends: "老友记角色", insideout: "情绪主导", sbti: "SBTI 人格扩展" };
  const sources = { manual: "本人填写", resume: "简历提取", assessment: "测评中心", local_assessment: "浏览器测评记录" };
  const statuses = { active: "进行中", completed: "已达成", paused: "已暂停" };
  let data = null, editing = null, loading = false, loadedOwner = "";
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const date = value => {
    if (!value) return "尚未记录";
    const numeric = Number(value);
    const parsed = new Date(Number.isFinite(numeric) && numeric > 0 ? numeric * (numeric < 1e12 ? 1000 : 1) : value);
    return Number.isNaN(parsed.getTime()) ? "尚未记录" : parsed.toLocaleDateString("zh-CN");
  };
  const empty = (title, copy) => `<div class="cp-empty"><strong>${esc(title)}</strong><p>${esc(copy)}</p></div>`;
  const button = (action, text, key = "", id = "") => `<button type="button" class="cp-text-btn" data-cp-action="${action}" data-key="${key}" data-id="${esc(id)}">${text}</button>`;
  const metadata = row => `<p class="cp-meta">${esc(sources[row.source_type] || row.source_type)} · 更新于 ${date(row.updated_at)} · v${row.version}</p>`;
  const actions = (key, row) => row.source_type === "manual" ? `<div class="cp-actions">${button("edit", "编辑", key, row.id)}${button("history", "修改记录", key, row.id)}${button("delete", "移除", key, row.id)}</div>` : "";
  const card = (title, content, action = "") => `<section class="uc-surface cp-card"><div class="cp-card-head"><h3>${title}</h3>${action}</div>${content}</section>`;
  function status(message, error = false) { el("cpStatus").textContent = message; el("cpStatus").classList.toggle("is-error", error); }

  function render() {
    if (!data) return;
    const profile = data.profile || {};
    const user = window.getCurrentUser?.();
    el("cpSkillCount").textContent = data.skills.length;
    const updated = [profile, ...data.entries, ...data.skills, ...data.evidence, ...data.goals, ...data.assessments, ...data.resumes].map(row => row.updated_at).filter(Boolean).sort().at(-1);
    el("cpUpdated").textContent = updated ? `最近更新 ${date(updated)} · 资料按来源保留，可持续补充` : "从一段经历或一项技能开始，建立你的第一份职业档案。";
    const basics = `<h3 class="cp-name">${esc(profile.display_name || user?.display_name || "我的职业画像")}</h3><p class="cp-headline">${esc(profile.headline || "写下一句话，介绍你正在探索的职业方向。")}</p><div class="cp-facts">${[stages[profile.stage], profile.city].filter(Boolean).map(text => `<span class="cp-tag">${esc(text)}</span>`).join("")}</div><p>${esc(profile.summary || "还没有个人简介。可以描述你的背景、擅长的工作，以及希望发展的方向。")}</p>${profile.id ? metadata(profile) + button("history", "查看资料修改记录", "profile", profile.id) : ""}`;
    const entryCards = Object.entries(kinds).map(([kind, label]) => {
      const rows = data.entries.filter(row => row.kind === kind);
      const content = rows.length ? rows.map(row => `<article class="cp-row"><h4>${esc(row.title)}</h4><p>${esc(row.description)}</p>${metadata(row)}${actions("entries", row)}</article>`).join("") : empty(`补充${label}`, { education: "学校、专业、学历与毕业时间", experience: "你的职责、完成的工作与具体成果", certificate: "证书名称、颁发机构与取得时间", interest: "你愿意持续投入的领域与活动", preference: "期望城市、工作方式与行业偏好" }[kind]);
      return card(label, content, `<button type="button" class="cp-text-btn" data-cp-action="add-entry" data-kind="${kind}">＋ 添加</button>`);
    });
    const goals = data.goals.filter(row => row.status === "active");
    const summary = `<div class="cp-note">${data.skills.length} 项技能 · ${data.evidence.length} 条证据 · ${goals.length} 个进行中的目标</div><p>经历、测评和对话提供不同角度的线索。技能是否经过验证，以对应证据为准。</p><div class="cp-actions">${button("tab-skills", "维护技能证据 ↗")}${button("tab-goals", "管理职业目标 ↗")}</div>`;
    const memoryLabels = { education: "教育背景", major: "专业", graduation: "毕业时间", skill: "技能", experience: "经历", preference: "职业偏好" };
    const memoryRows = (data.memories || []).map(row => `<article class="cp-row"><h4>${esc(row.subject === "profile" ? memoryLabels[row.key] || "职业线索" : row.subject)}</h4><p>${esc(row.value)}</p><span class="cp-tag ${row.status === "conflict" ? "is-warning" : ""}">${row.status === "conflict" ? "存在冲突，待确认" : "对话自述"}</span><p class="cp-meta">来源：生涯助手记忆 · ${date(row.updated_at)} · 尚未核验</p></article>`).join("");
    el("cpOverview").innerHTML = `<div class="cp-grid"><div class="cp-stack">${card("基础职业画像", basics)}${entryCards[0]}${entryCards[1]}</div><aside class="cp-stack">${card("档案概况", summary)}${entryCards.slice(2).join("")}${card("对话中的职业线索", memoryRows || empty("暂时没有职业记忆", "与生涯助手交流后，已保存的事实会在这里显示。"), '<a class="cp-text-btn" href="/assistant.html">管理记忆 ↗</a>')}</aside></div>`;
    renderSkills();
    el("cpGoals").innerHTML = card("职业发展目标", data.goals.length ? data.goals.map(row => `<article class="cp-row"><div class="cp-row-top"><h4>${esc(row.title)}</h4><span class="cp-tag">${statuses[row.status]}</span></div><p>${esc(row.description)}</p><span class="cp-goal-date">目标日期：${row.target_date ? esc(row.target_date) : "尚未设定"}</span>${metadata(row)}${actions("goals", row)}</article>`).join("") : empty("你想走向哪里？", "设定一个目标方向，再写下希望达成的成果与时间。"), button("add", "＋ 添加目标", "goals"));
    const assessments = [...data.assessments].sort((a, b) => b.completed_at.localeCompare(a.completed_at));
    const assessmentRows = assessments.map(row => `<article class="cp-row"><div class="cp-row-top"><h4>${esc(tests[row.test] || row.test)}</h4><time class="cp-meta">${date(row.completed_at)}</time></div><p>${esc(row.result)}</p>${metadata(row)}</article>`).join("");
    const resumes = [...data.resumes].sort((a, b) => Number(b.uploaded_at) - Number(a.uploaded_at));
    const resumeRows = resumes.map((row, index) => `<article class="cp-row"><div class="cp-row-top"><h4>${esc(row.name)}</h4><span class="cp-tag">${index === 0 ? "最近上传" : "历史版本"}</span></div><p>上传于 ${date(row.uploaded_at)}</p><p class="cp-meta">${esc(row.status === "ready" ? "已分析" : row.status === "archived" ? "已归档" : row.status === "uploaded" ? "待分析" : "简历记录")} · 独立保存的版本记录</p></article>`).join("");
    el("cpRecords").innerHTML = `<div class="cp-note">测评用于了解兴趣与偏好；简历记录用于回溯经历。这些资料不会自动证明你已掌握某项技能。</div><div class="cp-grid">${card("测评结果", assessmentRows || empty("还没有完成的测评", "完成测评后，结果与完成时间会归入档案。"), '<a class="cp-text-btn" href="/#profile">前往测评 ↗</a>')}${card("简历版本", resumeRows || empty("还没有简历版本", "上传简历后，这里会保留每次上传记录。"), '<a class="cp-text-btn" href="/#report">管理简历 ↗</a>')}</div>`;
  }

  function renderSkills() {
    const levels = [["01", "用户自述", "本人填写或简历中提及"], ["02", "经历支持", "有具体项目、证书或工作经历"], ["03", "成果验证", "代码、项目或测试成果经过检查"], ["04", "实际评估", "经过面试、测试或任务验收"]];
    const cards = data.skills.map(skill => {
      const evidence = data.evidence.filter(row => row.skill_id === skill.id);
      const rows = evidence.map(row => `<article class="cp-evidence"><div class="cp-row-top"><strong>${esc(row.title)}</strong><span class="cp-tag">${esc(data.evidence_levels[row.kind])}</span></div><p>${esc(row.description)}</p>${row.url ? `<a href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">查看证据材料 ↗</a>` : ""}${metadata(row)}${actions("evidence", row)}</article>`).join("");
      return card(esc(skill.name), `<div class="cp-facts"><span class="cp-tag ${skill.evidence_level !== "self_report" ? "is-supported" : ""}">${esc(data.evidence_levels[skill.evidence_level])}</span>${skill.category ? `<span class="cp-tag">${esc(skill.category)}</span>` : ""}<span class="cp-meta">${evidence.length} 条证据</span></div>${metadata(skill)}${rows || '<p>这项技能暂时只有自述信息，添加一条经历来说明你具体做过什么。</p>'}<div class="cp-actions" style="margin-top:16px">${button("add-evidence", "＋ 补充证据", "evidence", skill.id)}${actions("skills", skill)}</div>`);
    }).join("");
    el("cpSkills").innerHTML = `<div class="cp-levels">${levels.map(([number, title, description]) => `<div class="cp-level"><span>${number}</span><strong>${title}</strong><p>${description}</p></div>`).join("")}</div><div class="cp-note">填写经历或提交链接后，资料仍待核验。“成果验证”和“实际评估”需要有真实的检查与评估记录，不能手动选取。</div>${card("我的技能", `<p>从你实际使用过的工具、方法或专业能力开始，逐项补充相关证据。</p>`, button("add", "＋ 添加技能", "skills"))}<div class="cp-skill-grid" style="margin-top:18px">${cards || empty("把能力写清楚，也把依据留下来", "例如：添加 LangGraph，再记录你参与的项目与具体贡献。")}</div>`;
  }

  async function load() {
    if (loading || !window.getCurrentUser?.()) return;
    loading = true;
    const owner = window.getCurrentUser().username;
    const reload = el("cpStatus").querySelector("button");
    if (reload) reload.disabled = true;
    status("正在同步职业档案…");
    try {
      let history = [];
      try { history = JSON.parse(localStorage.getItem("career_assessment_history_v1_" + owner) || "[]"); } catch (_) { /* 浏览器存储不可用时仍可读取服务端档案。 */ }
      if (Array.isArray(history) && history.length) {
        const records = history.slice(0, 50).filter(row => tests[row?.test] && typeof row.result === "string" && row.result.trim() && Number.isFinite(row.completedAt) && row.completedAt > 0 && !Number.isNaN(new Date(row.completedAt).getTime())).map(row => ({ test: row.test, result: row.result.trim().slice(0, 120), completed_at: new Date(row.completedAt).toISOString() }));
        if (records.length) await window.requestJson(API + "/assessment-import", { method: "POST", body: { records } });
      }
      const response = await window.requestJson(API);
      if (owner !== window.getCurrentUser?.()?.username) return;
      data = response.data;
      loadedOwner = owner;
      render();
      status("");
    } catch (error) {
      status(error.message || "档案读取失败，请重试。", true);
      el("cpStatus").insertAdjacentHTML("beforeend", ` ${button("reload", "重新加载")}`);
    } finally { loading = false; }
  }

  function tab(name) {
    document.querySelectorAll("[data-cp-tab]").forEach(item => {
      const active = item.dataset.cpTab === name;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-cp-view]").forEach(item => { item.hidden = item.dataset.cpView !== name; });
  }

  function field(name, label, value = "", options = {}) {
    const attrs = `name="${name}" id="cpField-${name}" ${options.required ? "required" : ""}`;
    const control = options.values ? `<select ${attrs}>${Object.entries(options.values).map(([key, text]) => `<option value="${key}" ${value === key ? "selected" : ""}>${esc(text)}</option>`).join("")}</select>`
      : options.multiline ? `<textarea ${attrs} maxlength="2000" rows="4">${esc(value)}</textarea>`
      : `<input ${attrs} type="${options.type || "text"}" maxlength="${options.required ? 120 : 2000}" value="${esc(value)}">`;
    return `<label for="cpField-${name}">${label}${options.required ? " *" : ""}${control}</label>`;
  }

  function openEditor(key, row = {}, defaults = {}) {
    if (!data || loadedOwner !== window.getCurrentUser?.()?.username) return;
    const value = { ...defaults, ...row };
    editing = { key, id: row.id, version: row.version || 0, defaults, owner: loadedOwner };
    const titles = { profile: "基础职业画像", entries: kinds[value.kind], skills: "技能", evidence: "技能证据", goals: "职业目标" };
    el("cpEditorTitle").textContent = `${row.id ? "编辑" : "添加"}${titles[key]}`;
    let fields = "";
    if (key === "profile") fields = field("display_name", "姓名 / 昵称", value.display_name) + field("headline", "一句话职业定位", value.headline) + field("city", "所在城市", value.city) + field("stage", "当前阶段", value.stage || "", { values: { "": "请选择", ...stages } }) + field("summary", "个人简介", value.summary, { multiline: true });
    if (key === "entries") fields = field("title", value.kind === "education" ? "学校 / 教育经历" : "名称", value.title, { required: true }) + field("description", "详细说明", value.description, { multiline: true });
    if (key === "skills") fields = field("name", "技能名称", value.name, { required: true }) + field("category", "所属领域（选填）", value.category);
    if (key === "evidence") fields = field("kind", "证据类型", value.kind || "self_report", { values: { self_report: "用户自述", experience_support: "经历支持（待核验）" } }) + field("title", "证据标题", value.title, { required: true }) + field("description", "你完成的工作、取得的结果与对应材料", value.description, { multiline: true }) + field("url", "项目 / 证书 / 作品链接（选填）", value.url, { type: "url" });
    if (key === "goals") fields = field("title", "目标岗位 / 发展方向", value.title, { required: true }) + field("description", "期望成果与衡量方式", value.description, { multiline: true }) + field("target_date", "目标日期（选填）", value.target_date, { type: "date" }) + field("status", "当前状态", value.status || "active", { values: statuses });
    el("cpEditorFields").innerHTML = fields;
    el("cpEditorMessage").textContent = "";
    el("cpSave").hidden = false;
    el("cpSave").disabled = false;
    el("cpEditor").showModal();
  }

  async function submit(event) {
    event.preventDefault();
    if (!editing || editing.owner !== window.getCurrentUser?.()?.username) return;
    const context = editing;
    const payload = { version: context.version, ...Object.fromEntries(new FormData(event.target)) };
    if (context.key === "entries") payload.kind = context.defaults.kind || data.entries.find(row => row.id === context.id)?.kind;
    if (context.key === "evidence") payload.skill_id = context.defaults.skill_id || data.evidence.find(row => row.id === context.id)?.skill_id;
    if (context.key === "goals" && !payload.target_date) payload.target_date = null;
    el("cpSave").disabled = true;
    el("cpEditorMessage").textContent = "正在保存…";
    try {
      await window.requestJson(`${API}/${context.key}${context.id ? "/" + encodeURIComponent(context.id) : ""}`, { method: context.id || context.key === "profile" ? "PUT" : "POST", body: payload });
      el("cpEditor").close();
      await load();
    } catch (error) { el("cpEditorMessage").textContent = error.message; }
    finally { el("cpSave").disabled = false; }
  }

  async function history(row) {
    el("cpEditorTitle").textContent = "修改记录";
    el("cpEditorFields").innerHTML = "正在读取…";
    el("cpEditorMessage").textContent = "";
    el("cpSave").hidden = true;
    editing = null;
    el("cpEditor").showModal();
    try {
      const response = await window.requestJson(`${API}/history/${encodeURIComponent(row.id)}`);
      const labels = { display_name: "姓名", headline: "职业定位", city: "城市", stage: "阶段", summary: "简介", title: "名称", description: "说明", name: "技能", category: "领域", target_date: "目标日期", status: "状态", kind: "类型", url: "证据链接" };
      el("cpEditorFields").innerHTML = `<div class="cp-history">${response.data.map(item => `<article><strong>v${item.version} · ${{ create: "创建", update: "修改", delete: "移除" }[item.action]}</strong><p class="cp-meta">${esc(new Date(item.created_at).toLocaleString("zh-CN"))}</p><pre>${esc(Object.entries(item.snapshot).filter(([key]) => labels[key]).map(([key, value]) => `${labels[key]}：${statuses[value] || stages[value] || data.evidence_levels[value] || value || "—"}`).join("\n"))}</pre></article>`).join("") || empty("还没有修改记录", "保存后的资料变更会在这里显示。")}</div>`;
    } catch (error) { el("cpEditorFields").textContent = error.message; }
  }

  document.addEventListener("click", async event => {
    const target = event.target.closest("[data-cp-action], [data-cp-tab]");
    if (!target) return;
    if (target.dataset.cpTab) return tab(target.dataset.cpTab);
    const { cpAction: action, key, id, kind } = target.dataset;
    if (action === "reload") return void load();
    if (action === "close-editor") return el("cpEditor").close();
    if (!data) return;
    if (action.startsWith("tab-")) return tab(action.slice(4));
    if (action === "edit-profile") return openEditor("profile", data.profile || {});
    if (action === "add-entry") return openEditor("entries", {}, { kind });
    if (action === "add-evidence") return openEditor("evidence", {}, { skill_id: id });
    if (action === "add") return openEditor(key);
    const row = key === "profile" ? data.profile : data[key]?.find(row => row.id === id);
    if (!row) return;
    if (action === "edit") return openEditor(key, row);
    if (action === "history") return void history(row);
    if (action === "delete") {
      if (!window.confirm(`移除“${row.title || row.name}”？${key === "skills" ? "关联证据也会一并移除。" : ""}`)) return;
      target.disabled = true;
      try {
        await window.requestJson(`${API}/${key}/${encodeURIComponent(id)}`, { method: "DELETE", body: { version: row.version } });
        await load();
      } catch (error) { status(error.message, true); }
      finally { target.disabled = false; }
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    el("cpEditorForm").addEventListener("submit", submit);
    // User-center loads auth first and calls this when entering the section.
  });
  window.loadCareerProfile = load;
})();
