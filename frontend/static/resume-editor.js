(() => {
  const root = document.getElementById("resumeWorkshop");
  const list = document.getElementById("resumeDraftList");
  const versions = document.getElementById("resumeVersions");
  const container = document.getElementById("resumeSections");
  const status = document.getElementById("resumeEditorStatus");
  const title = root.querySelector("[name=title]");
  const contact = [...root.querySelectorAll("[data-contact]")];
  const photoPreview = document.getElementById("resumePhoto");
  const photoPicker = document.getElementById("resumePickPhoto");
  const photoPlaceholder = document.getElementById("resumePhotoPlaceholder");
  const photoRemove = document.getElementById("resumeRemovePhoto");
  const restoreButtons = [...root.querySelectorAll("[data-restore]")];
  const extras = document.getElementById("resumeContactExtras");
  const extraTemplate = document.getElementById("resumeContactTemplate");
  const quickField = document.getElementById("resumeQuickField");
  const badge = document.getElementById("resumeVersionBadge");
  const sectionTemplate = document.getElementById("resumeSectionTemplate");
  const entryTemplate = document.getElementById("resumeEntryTemplate");
  const itemTemplate = document.getElementById("resumeItemTemplate");
  const importDialog = document.getElementById("resumeImport");
  const importForm = document.getElementById("resumeImportForm");
  const importStatus = document.getElementById("resumeImportStatus");
  const previewDialog = document.getElementById("resumePreview");
  const appearance = document.getElementById("resumeAppearance");
  const styleSelect = document.getElementById("resumeStyleSelect");
  const layoutSelect = document.getElementById("resumeLayoutSelect");
  const showPhotoCheck = document.getElementById("resumeShowPhoto");
  const setDefaultBtn = document.getElementById("resumeSetDefault");
  const workspace = document.getElementById("resumeWorkspace");
  const splitToggle = document.getElementById("resumeSplitToggle");
  const splitPane = document.getElementById("resumeSplitPane");
  const splitMeta = document.getElementById("resumeSplitMeta");
  const splitPages = document.getElementById("resumeSplitPages");
  const endpoint = "/api/resume-editor";
  const maxSections = Number(root.dataset.maxSections);
  let id = "";
  let revision = 0;
  let layout = "standard";
  let style = "classic";
  let fontScale = 1.0;
  let showPhoto = true;
  let photo = "";
  let dirty = false;
  let busy = false;
  let splitTimer = 0;
  let splitLoading = false;
  let toastTimer = 0;
  const historyStack = [];
  let historyIndex = -1;
  let historyTimer = 0;
  let restoringHistory = false;

  function pushHistory(immediate = false) {
    if (restoringHistory) return;
    const capture = () => {
      const snap = JSON.stringify(readDraft());
      if (historyIndex >= 0 && historyStack[historyIndex] === snap) return;
      historyStack.splice(historyIndex + 1);
      historyStack.push(snap);
      if (historyStack.length > 40) historyStack.shift();
      historyIndex = historyStack.length - 1;
    };
    window.clearTimeout(historyTimer);
    if (immediate) capture();
    else historyTimer = window.setTimeout(capture, 450);
  }

  function applyHistoryStep(delta) {
    const next = historyIndex + delta;
    if (next < 0 || next >= historyStack.length) {
      showToast(delta < 0 ? "已到达最早撤销点" : "没有可重做的修改", "info");
      return;
    }
    historyIndex = next;
    restoringHistory = true;
    try {
      fillDraft(JSON.parse(historyStack[historyIndex]));
      dirty = true;
      badge.textContent = "未保存";
      status.textContent = delta < 0 ? "已撤销上一步修改" : "已重做修改";
      showToast(delta < 0 ? "↶ 已撤销" : "↷ 已重做", "info");
    } finally {
      restoringHistory = false;
    }
  }

  function showToast(message, tone = "info") {
    let el = document.getElementById("resumeToast");
    if (!el) {
      el = document.createElement("div");
      el.id = "resumeToast";
      el.className = "re-toast";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      document.body.append(el);
    }
    el.textContent = message;
    el.dataset.tone = tone;
    el.classList.remove("is-open");
    void el.offsetWidth;
    el.classList.add("is-open");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => el.classList.remove("is-open"), 2400);
  }

  async function request(path, { method = "GET", data } = {}) {
    const headers = method === "GET" ? {} : await window.CareerAuth.headers();
    let body = data;
    if (data && !(data instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(data);
    }
    const response = await fetch(endpoint + path, { method, headers, body, cache: "no-store" });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || "请求未完成，请稍后重试。");
    }
    return response;
  }

  // 表单式栏目：经历条目（名称/角色/起止时间/内容）与逐条清单。
  // 表单内容实时序列化回原有 Markdown 文本，预览、导出、导入和改写共用同一份数据。
  const ENTRY_FORMS = {
    "项目经历": {
      kind: "entry", bullets: true,
      labels: { name: "项目名称", role: "项目角色", start: "开始时间", end: "结束时间", content: "项目内容" },
      placeholders: { name: "例如：校园二手交易平台", role: "例如：后端负责人", start: "2025.01", end: "2025.06 或 至今", content: "- 负责了什么\n- 取得了什么成果" },
    },
    "工作经历": {
      kind: "entry", bullets: true,
      labels: { name: "公司名称", role: "担任职位", start: "开始时间", end: "结束时间", content: "工作内容" },
      placeholders: { name: "例如：某某科技有限公司", role: "例如：数据分析实习生", start: "2025.03", end: "2025.09 或 至今", content: "- 负责了什么\n- 取得了什么成果" },
    },
    "教育经历": {
      kind: "entry", bullets: false,
      labels: { name: "学校", role: "专业与学历", start: "开始时间", end: "结束时间", content: "补充说明（可选）" },
      placeholders: { name: "例如：示例大学", role: "例如：计算机科学与技术 · 本科", start: "2022.09", end: "2026.06", content: "GPA、主修课程、荣誉等" },
    },
  };
  const LIST_FORMS = {
    "获奖情况": { kind: "list", pair: true, placeholder: "例如：国家奖学金（2024.10）" },
    "资格证书": { kind: "list", pair: false, placeholder: "例如：CET-6（2024.06）" },
    "科研成果": { kind: "list", pair: false, placeholder: "例如：论文标题 · 期刊 · 2025" },
  };
  const FORM_ALIASES = {
    "项目经验": "项目经历", "工作经验": "工作经历", "职业经历": "工作经历", "实习经历": "工作经历", "实习经验": "工作经历",
    "教育背景": "教育经历", "获奖经历": "获奖情况", "荣誉奖项": "获奖情况", "职业证书": "资格证书", "学术成果": "科研成果",
  };
  const BULLET_LINE = /^([-*•]\s+|\d+\.\s+|#{1,6}\s+)/;

  function schemaFor(title) {
    const key = FORM_ALIASES[title] || title;
    return ENTRY_FORMS[key] || LIST_FORMS[key] || null;
  }

  function sectionSchema(card) {
    return schemaFor(card.querySelector("[data-section-title]").value.trim());
  }

  function splitDateRange(text) {
    const value = text.trim();
    if (!value) return { start: "", end: "" };
    for (const sep of ["–", "—", "～", "~", "至"]) {
      const index = value.indexOf(sep);
      if (index > 0) return { start: value.slice(0, index).trim(), end: value.slice(index + sep.length).trim() };
    }
    let parts = value.split(/\s+-\s+/);
    if (parts.length === 2) return { start: parts[0].trim(), end: parts[1].trim() };
    parts = value.split("-");
    if (parts.length === 2) return { start: parts[0].trim(), end: parts[1].trim() };
    if (parts.length === 4 && parts.every(part => /^\d+$/.test(part.trim()))) {
      return { start: parts.slice(0, 2).join("-"), end: parts.slice(2).join("-") };
    }
    return { start: value, end: "" };
  }

  function headerFields(line) {
    if (BULLET_LINE.test(line) || !/[|｜]/.test(line)) return null;
    const cols = line.split(/[|｜]/).map(cell => cell.trim());
    if (cols.length < 2 || cols.length > 3 || !cols.some(Boolean)) return null;
    if (cols.length === 3) return { name: cols[0], role: cols[1], ...splitDateRange(cols[2]) };
    if (/\d{4}|至今|present/i.test(cols[1])) return { name: cols[0], role: "", ...splitDateRange(cols[1]) };
    return { name: cols[0], role: cols[1], start: "", end: "" };
  }

  function parseEntries(content) {
    const entries = [];
    let current = null;
    let blockStart = true;
    for (const raw of content.split("\n")) {
      const line = raw.trim();
      if (!line) {
        blockStart = true;
        if (current) current.lines.push("");
        continue;
      }
      const header = headerFields(line);
      if (header) {
        current = { ...header, lines: [] };
        entries.push(current);
      } else if (blockStart && !BULLET_LINE.test(line) && line.length <= 120) {
        current = { name: line, role: "", start: "", end: "", lines: [] };
        entries.push(current);
      } else {
        if (!current) {
          current = { name: "", role: "", start: "", end: "", lines: [] };
          entries.push(current);
        }
        current.lines.push(line);
      }
      blockStart = false;
    }
    return entries.map(({ lines, ...entry }) => ({ ...entry, content: lines.join("\n").replace(/^\n+|\n+$/g, "") }));
  }

  function serializeEntries(entries, schema) {
    const blocks = [];
    for (const entry of entries) {
      const name = entry.name.trim();
      const role = entry.role.trim();
      const date = [entry.start.trim(), entry.end.trim()].filter(Boolean).join("–");
      const cols = [name, role, date];
      const lines = [];
      if (cols.every(Boolean)) lines.push(cols.join(" | "));
      else if (name && (role || date)) lines.push(cols.filter(Boolean).join(" | "));
      else if (name) lines.push(name);
      else if (role || date) lines.push(cols.join(" | "));
      let body = entry.content.replace(/\n[ \t]*\n+/g, "\n").trim();
      if (schema.bullets) {
        body = body.split("\n").map(line => {
          const text = line.trim();
          return !text || BULLET_LINE.test(text) ? text : "- " + text;
        }).join("\n");
      }
      if (body) lines.push(body);
      if (lines.length) blocks.push(lines.join("\n"));
    }
    return blocks.join("\n\n");
  }

  function parseItems(content, schema) {
    const items = [];
    for (const raw of content.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const parts = schema.pair ? line.split(/[|｜]/) : [line];
      for (const part of parts) {
        const text = part.trim().replace(/^[-*•]\s+/, "");
        if (text) items.push(text);
      }
    }
    return items;
  }

  function serializeItems(items, schema) {
    const clean = items.map(item => item.trim()).filter(Boolean);
    if (!schema.pair) return clean.join("\n");
    const rows = [];
    for (let index = 0; index < clean.length; index += 2) {
      rows.push(clean.slice(index, index + 2).map(text => "- " + text).join(" | "));
    }
    return rows.join("\n");
  }

  function blankEntry() {
    return { name: "", role: "", start: "", end: "", content: "" };
  }

  function entryCard(card, entry) {
    const schema = sectionSchema(card);
    const node = entryTemplate.content.firstElementChild.cloneNode(true);
    for (const key of ["name", "role", "start", "end", "content"]) {
      node.querySelector(`[data-entry-label="${key}"]`).textContent = schema.labels[key];
      const field = node.querySelector(`[data-entry="${key}"]`);
      field.value = entry[key] || "";
      field.placeholder = schema.placeholders[key] || "";
    }
    return node;
  }

  function itemCard(card, text) {
    const node = itemTemplate.content.firstElementChild.cloneNode(true);
    const field = node.querySelector("[data-entry=text]");
    field.value = text;
    field.placeholder = sectionSchema(card).placeholder;
    return node;
  }

  function renumberEntries(card) {
    const schema = sectionSchema(card);
    const title = card.querySelector("[data-section-title]").value.trim();
    const nodes = [...card.querySelectorAll("[data-entries] > .re-entry")];
    nodes.forEach((node, index) => {
      node.querySelector("[data-entry-index]").textContent = schema.kind === "list" ? `${index + 1}.` : `${title} ${index + 1}`;
      const up = node.querySelector("[data-entry-move='-1']");
      const down = node.querySelector("[data-entry-move='1']");
      if (up) up.disabled = index === 0;
      if (down) down.disabled = index === nodes.length - 1;
    });
  }

  function syncForm(card) {
    const schema = sectionSchema(card);
    const nodes = [...card.querySelectorAll("[data-entries] > .re-entry")];
    const content = schema.kind === "list"
      ? serializeItems(nodes.map(node => node.querySelector("[data-entry=text]").value), schema)
      : serializeEntries(nodes.map(node => ({
        name: node.querySelector("[data-entry=name]").value,
        role: node.querySelector("[data-entry=role]").value,
        start: node.querySelector("[data-entry=start]").value,
        end: node.querySelector("[data-entry=end]").value,
        content: node.querySelector("[data-entry=content]").value,
      })), schema);
    card.querySelector("[data-section-content]").value = content;
  }

  function buildForm(card) {
    const schema = sectionSchema(card);
    const entries = card.querySelector("[data-entries]");
    const content = card.querySelector("[data-section-content]").value;
    entries.replaceChildren();
    if (schema.kind === "list") {
      const items = parseItems(content, schema);
      (items.length ? items : [""]).forEach(text => entries.append(itemCard(card, text)));
    } else {
      const parsed = parseEntries(content);
      (parsed.length ? parsed : [blankEntry()]).forEach(entry => entries.append(entryCard(card, entry)));
    }
    renumberEntries(card);
  }

  function applyMode(card) {
    const form = card.dataset.mode === "form";
    card.querySelector("[data-form-area]").hidden = !form;
    card.querySelector("[data-text-area]").hidden = form;
  }

  function setupSectionForm(card) {
    const schema = sectionSchema(card);
    const area = card.querySelector("[data-form-area]");
    if (!schema) {
      card.dataset.mode = "text";
      applyMode(card);
      return;
    }
    if (!area.querySelector("[data-entries]")) {
      const list = document.createElement("div");
      list.className = "re-entries";
      list.dataset.entries = "";
      const add = document.createElement("button");
      add.type = "button";
      add.className = "re-button re-add-entry";
      add.dataset.addEntry = "";
      area.append(list, add);
    }
    const title = card.querySelector("[data-section-title]").value.trim();
    area.querySelector("[data-add-entry]").textContent = schema.kind === "list" ? "＋ 新增一条" : `＋ 添加${title}`;
    card.dataset.mode = "form";
    buildForm(card);
    applyMode(card);
  }

  function readDraft() {
    const doc = {
      title: title.value,
      contact: Object.fromEntries(contact.map(input => [input.dataset.contact, input.value])),
      photo,
      extras: [...extras.children].map(row => ({
        label: row.querySelector("[data-field-label]").value,
        value: row.querySelector("[data-field-value]").value
      })).filter(field => field.label.trim() || field.value.trim()),
      sections: [...container.children].map(section => ({
        title: section.querySelector("[data-section-title]").value,
        content: section.querySelector("[data-section-content]").value
      })),
      layout, style
    };
    if (!showPhoto) doc.show_photo = false;
    if (fontScale && fontScale !== 1.0) doc.font_scale = fontScale;
    return doc;
  }

  function updateMoveButtons() {
    [...container.children].forEach((section, index, sections) => {
      section.querySelector("[data-move='-1']").disabled = index === 0;
      section.querySelector("[data-move='1']").disabled = index === sections.length - 1;
    });
    const used = new Set([...container.querySelectorAll("[data-section-title]")].map(input => input.value.trim()));
    restoreButtons.forEach(button => { button.hidden = used.has(button.dataset.restore); });
  }

  function toggleSection(card, open) {
    card.querySelector("[data-toggle-section]").setAttribute("aria-expanded", String(open));
    card.querySelector(".re-section-body").hidden = !open;
  }

  function setSectionCaption(card, title) {
    card.querySelector("[data-section-name]").textContent = title;
    const examples = {
      "项目经历": "项目名称 | 项目角色 | 2025.01–2025.06\n- 填写职责与项目成果",
      "教育经历": "学校 | 专业与学历 | 2022.09–2026.06",
      "专业技能": "专业技能，支持 Markdown"
    };
    card.querySelector("[data-section-content]").placeholder = Object.hasOwn(examples, title)
      ? examples[title] : `在此填写${title}的内容…`;
  }

  function appendSection(section, open = false) {
    const card = sectionTemplate.content.firstElementChild.cloneNode(true);
    card.querySelector("[data-section-title]").value = section.title;
    card.querySelector("[data-section-content]").value = section.content;
    setSectionCaption(card, section.title);
    setupSectionForm(card);
    toggleSection(card, open || Boolean(section.content) || ["个人总结", "专业技能", "附加信息"].includes(section.title));
    container.append(card);
    return card;
  }

  function appendField(field) {
    const row = extraTemplate.content.firstElementChild.cloneNode(true);
    row.querySelector("[data-field-label]").value = field.label;
    row.querySelector("[data-field-value]").value = field.value;
    extras.append(row);
    return row;
  }

  function syncAppearanceControls() {
    if (styleSelect) styleSelect.value = style || "classic";
    if (layoutSelect) layoutSelect.value = layout || "standard";
    if (showPhotoCheck) showPhotoCheck.checked = showPhoto !== false;
  }

  function fillDraft(document) {
    title.value = document.title;
    contact.forEach(input => { input.value = document.contact[input.dataset.contact] || ""; });
    container.replaceChildren();
    document.sections.forEach(section => appendSection(section));
    extras.replaceChildren();
    (document.extras || []).forEach(appendField);
    setPhoto(document.photo || "");
    layout = document.layout || "standard";
    style = document.style || "classic";
    fontScale = Number(document.font_scale) || 1.0;
    showPhoto = document.show_photo !== false;
    syncAppearanceControls();
    updateMoveButtons();
    scheduleSplitPreview();
  }

  function setPhoto(data) {
    photo = data;
    photoPreview.hidden = photoRemove.hidden = !photo;
    photoPlaceholder.hidden = Boolean(photo);
    photoPicker.setAttribute("aria-label", photo ? "更换简历照片" : "上传简历照片");
    photoPicker.title = photoPicker.getAttribute("aria-label");
    if (photo) photoPreview.src = "data:image/jpeg;base64," + photo;
    else photoPreview.removeAttribute("src");
  }

  function markChanged() {
    dirty = true;
    badge.textContent = "未保存";
    status.textContent = "有未保存的修改";
    scheduleSplitPreview();
    pushHistory(false);
  }

  photoPicker.addEventListener("resume:photo-cropped", event => {
    setPhoto(event.detail);
    markChanged();
  });

  function markSelected() {
    list.querySelectorAll("[data-draft-id]").forEach(button => {
      if (button.dataset.draftId === id) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
    root.querySelector("[data-action=delete]").hidden = !id;
    if (setDefaultBtn) setDefaultBtn.hidden = !id;
  }

  function showDraft(draft) {
    id = draft.id;
    revision = draft.revision;
    fillDraft(draft.document);
    dirty = false;
    badge.textContent = "已保存";
    markSelected();
    status.textContent = "已保存的简历";
    historyStack.length = 0;
    historyIndex = -1;
    pushHistory(true);
  }

  function startDraft() {
    id = "";
    revision = 0;
    fillDraft({
      title: "新建简历版本", contact: {}, layout: "standard",
      sections: restoreButtons.map(button => ({ title: button.dataset.restore, content: "" }))
    });
    dirty = false;
    badge.textContent = "草稿";
    markSelected();
    status.textContent = "填写内容或导入已有简历";
  }

  async function refreshList() {
    const data = await (await request("/drafts")).json();
    list.replaceChildren();
    data.drafts.forEach(draft => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.draftId = draft.id;
      button.textContent = draft.title;
      list.append(button);
    });
    markSelected();
    return data.drafts;
  }

  async function run(task, message, output = status) {
    if (busy) return;
    busy = true;
    root.inert = true;
    output.textContent = message;
    try {
      await task();
    } catch (error) {
      output.textContent = error.message;
    } finally {
      root.inert = false;
      busy = false;
    }
  }

  function canLeaveDraft() {
    return !dirty || window.confirm("当前修改还未保存。要放弃修改并切换简历吗？");
  }

  function mergeDraft(current, imported) {
    if (!Object.values(current.contact).some(value => value.trim()) && !current.sections.some(part => part.content.trim())) {
      current.layout = imported.layout;
    }
    for (const [key, value] of Object.entries(imported.contact)) {
      if (!current.contact[key]?.trim() && value) current.contact[key] = value;
    }
    if (!current.photo && imported.photo) current.photo = imported.photo;
    for (const field of imported.extras || []) {
      if (!current.extras.some(item => item.label === field.label)) {
        if (current.extras.length >= 8) throw new Error("合并后个人信息字段超过上限，请移除一些空字段后重试。");
        current.extras.push(field);
      }
    }
    for (const part of imported.sections) {
      const match = current.sections.find(section => section.title.trim() === part.title);
      if (match) {
        if (match.content.trim() !== part.content) match.content = [match.content.trim(), part.content].filter(Boolean).join("\n\n");
      } else {
        current.sections.push(part);
      }
    }
    return current;
  }

  importForm.elements.source.addEventListener("change", () => {
    importForm.querySelectorAll("[data-source]").forEach(field => {
      field.hidden = field.dataset.source !== importForm.elements.source.value;
      field.querySelector("input, textarea").disabled = field.hidden;
    });
  });
  importForm.elements.source.dispatchEvent(new Event("change"));
  importForm.addEventListener("submit", event => {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(importForm);
    const submit = importForm.querySelector("[type=submit]");
    const replace = document.getElementById("resumeReplace").checked;
    submit.disabled = true;
    void run(async () => {
      const result = await (await request("/import", { method: "POST", data })).json();
      const current = readDraft();
      const edited = replace ? { ...result.document, title: current.title }
        : mergeDraft(current, result.document);
      if (edited.sections.length > maxSections) throw new Error(`合并后超过 ${maxSections} 个栏目，请先移除空栏目或选择替换。`);
      fillDraft(edited);
      markChanged();
      importDialog.close();
      status.textContent = [result.ocr_used ? "已通过 OCR 填入，请核对识别结果。" : "已填入，请检查后保存。", result.warning].filter(Boolean).join(" ");
    }, "正在识别简历…", importStatus).finally(() => { submit.disabled = false; });
  });

  function pageOccupancyText(result) {
    const modeText = result.layout === "compact" ? "紧凑" : "标准";
    if (result.page_count === 1 && typeof result.fill_percent === "number") {
      return `1 页 · 占满 ${result.fill_percent}% · ${modeText}`;
    }
    if (result.page_count > 1 && result.overflow_lines) {
      return `${result.page_count} 页（超出 ${result.overflow_lines} 行）· ${modeText}`;
    }
    return `A4 · ${result.page_count} 页 · ${modeText}`;
  }

  async function refreshSplitPreview() {
    if (!workspace || workspace.dataset.split !== "1" || splitLoading) return;
    const doc = readDraft();
    const hasContent = Object.values(doc.contact).some(Boolean) || doc.sections.some(s => s.content.trim());
    if (!hasContent) {
      splitMeta.textContent = "填写内容后自动预览";
      splitPages.replaceChildren();
      return;
    }
    splitLoading = true;
    splitMeta.textContent = "正在更新预览…";
    try {
      const result = await (await request("/render/preview", { method: "POST", data: doc })).json();
      splitMeta.textContent = pageOccupancyText(result);
      splitMeta.dataset.overflow = result.page_count > 1 ? "1" : "0";
      splitPages.replaceChildren(...result.images.map((source, index) => {
        const image = document.createElement("img");
        image.src = "data:image/png;base64," + source;
        image.alt = `简历第 ${index + 1} 页`;
        return image;
      }));
    } catch (error) {
      splitMeta.textContent = error.message || "预览更新失败";
    } finally {
      splitLoading = false;
    }
  }

  function scheduleSplitPreview() {
    if (!workspace || workspace.dataset.split !== "1") return;
    clearTimeout(splitTimer);
    splitTimer = setTimeout(() => { void refreshSplitPreview(); }, 650);
  }

  function setSplitPreview(open) {
    if (!workspace || !splitPane || !splitToggle) return;
    workspace.dataset.split = open ? "1" : "0";
    splitPane.hidden = !open;
    splitToggle.setAttribute("aria-pressed", String(open));
    if (open) void refreshSplitPreview();
  }

  if (styleSelect) styleSelect.addEventListener("change", () => { style = styleSelect.value; markChanged(); });
  if (layoutSelect) layoutSelect.addEventListener("change", () => { layout = layoutSelect.value; markChanged(); });
  if (showPhotoCheck) showPhotoCheck.addEventListener("change", () => { showPhoto = showPhotoCheck.checked; markChanged(); });

  async function render(mode, documentData = readDraft(), temporary = false) {
    const response = await request("/render/" + mode, { method: "POST", data: documentData });
    if (mode === "auto" || mode === "preview") {
      const result = await response.json();
      if (!temporary && mode === "auto") {
        const nextScale = Number(result.font_scale) || 1.0;
        if (layout !== result.layout || fontScale !== nextScale) {
          layout = result.layout;
          fontScale = nextScale;
          syncAppearanceControls();
          markChanged();
        }
      } else if (!temporary) {
        status.textContent = dirty ? "有未保存的修改" : "";
      }
      document.getElementById("resumePreviewInfo").textContent = pageOccupancyText(result);
      document.getElementById("resumePreviewPages").replaceChildren(...result.images.map((source, index) => {
        const image = document.createElement("img");
        image.src = "data:image/png;base64," + source;
        image.alt = `简历第 ${index + 1} 页`;
        return image;
      }));
      previewDialog.showModal();
      return;
    }
    const file = await response.blob();
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    const name = documentData.title.trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, "_") || "简历";
    link.href = url;
    const ext = mode === "pdf" ? ".pdf" : mode === "docx" ? ".docx" : file.type === "application/zip" ? "-图片.zip" : ".png";
    link.download = name + ext;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    if (!temporary) status.textContent = dirty ? "已导出当前内容，修改尚未保存" : "已导出";
  }

  const rewriteDialog = document.getElementById("resumeRewrite");
  const rewriteForm = document.getElementById("resumeRewriteForm");
  const rewriteStatus = document.getElementById("resumeRewriteStatus");
  const rewriteResult = document.getElementById("resumeRewriteResult");
  const skillSelect = document.getElementById("resumeRewriteSkill");
  const skillDeleteBtn = document.getElementById("resumeSkillDelete");
  const skillPrompt = document.getElementById("resumeSkillPrompt");
  let loadedSkills = [];
  const rewriteModeTabs = [...rewriteForm.querySelectorAll("[data-rewrite-mode]")];
  const rewriteSkillCard = document.getElementById("resumeRewriteSkillCard");
  const rewriteJobCard = document.getElementById("resumeRewriteJobCard");
  let rewriteMode = "skill";
  let rewriteDocument;
  let rewriteBusy = false;

  function updateSkillDeleteState() {
    if (!skillDeleteBtn) return;
    const current = loadedSkills.find(item => item.id === skillSelect.value);
    skillDeleteBtn.hidden = !current || current.builtin !== false;
  }

  function setRewriteMode(mode) {
    rewriteMode = mode === "job" ? "job" : "skill";
    rewriteModeTabs.forEach(tab => tab.setAttribute("aria-selected", String(tab.dataset.rewriteMode === rewriteMode)));
    if (rewriteSkillCard) rewriteSkillCard.hidden = rewriteMode !== "skill";
    if (rewriteJobCard) rewriteJobCard.hidden = rewriteMode !== "job";
    if (rewriteForm.elements.job_title) rewriteForm.elements.job_title.required = rewriteMode === "job";
    if (rewriteForm.elements.job_description) rewriteForm.elements.job_description.required = rewriteMode === "job";
  }
  setRewriteMode("skill");
  rewriteModeTabs.forEach(tab => tab.addEventListener("click", () => setRewriteMode(tab.dataset.rewriteMode)));

  function applyRewriteSettings(data) {
    loadedSkills = data.skills || [];
    skillSelect.replaceChildren(...loadedSkills.map(skill => new Option(`${skill.name} · ${skill.origin}`, skill.id)));
    skillSelect.value = data.settings.skill;
    skillPrompt.textContent = data.prompt;
    updateSkillDeleteState();
  }

  async function rewriteAction(task, progress) {
    if (rewriteBusy) return;
    rewriteBusy = true;
    const enabled = [...rewriteForm.querySelectorAll("button, input, textarea, select")].filter(control => !control.disabled);
    enabled.forEach(control => { control.disabled = true; });
    rewriteStatus.textContent = progress;
    try {
      await task();
    } catch (error) {
      rewriteStatus.textContent = error.message;
    } finally {
      enabled.forEach(control => { control.disabled = false; });
      rewriteBusy = false;
    }
  }

  async function openRewrite() {
    if (!rewriteDialog.open) rewriteDialog.showModal();
    await rewriteAction(async () => {
      applyRewriteSettings(await (await request("/rewrite/settings")).json());
      rewriteStatus.textContent = "";
    }, "正在读取改写设置…");
  }

  function setRewriteJob(job) {
    if (!job || typeof job.title !== "string") return;
    setRewriteMode("job");
    rewriteForm.elements.job_title.value = job.title.slice(0, 120);
    rewriteForm.elements.job_description.value = String(job.description || "").slice(0, 12000);
    if (rewriteForm.elements.resume_source && !readDraft().sections.some(section => section.content.trim())) {
      rewriteForm.elements.resume_source.value = "uploaded";
    }
  }

  document.querySelector("[data-rewrite-close]").onclick = () => { if (!rewriteBusy) rewriteDialog.close(); };
  rewriteDialog.addEventListener("cancel", event => { if (rewriteBusy) event.preventDefault(); });
  skillSelect.addEventListener("change", async () => {
    const selected = skillSelect.value;
    updateSkillDeleteState();
    try {
      const data = await (await request("/rewrite/settings?skill=" + encodeURIComponent(selected))).json();
      if (selected === skillSelect.value) skillPrompt.textContent = data.prompt || "";
    } catch (error) {
      if (selected === skillSelect.value) rewriteStatus.textContent = error.message;
    }
  });
  if (skillDeleteBtn) {
    skillDeleteBtn.onclick = () => {
      const target = skillSelect.value;
      if (!target || !window.confirm("删除当前选中的自定义 Skill？")) return;
      void rewriteAction(async () => {
        const data = await (await request("/rewrite/skills/" + encodeURIComponent(target), { method: "DELETE" })).json();
        applyRewriteSettings(data);
        rewriteStatus.textContent = "已删除该自定义 Skill。";
      }, "正在删除 Skill…");
    };
  }
  document.getElementById("resumeSkillImport").onclick = () => {
    const location = document.getElementById("resumeSkillLocation");
    const file = document.getElementById("resumeSkillFile");
    const data = new FormData();
    data.set("location", location.value);
    if (file.files.length) data.set("skill_file", file.files[0]);
    void rewriteAction(async () => {
      applyRewriteSettings(await (await request("/rewrite/skills", { method: "POST", data })).json());
      location.value = file.value = "";
      rewriteStatus.textContent = "已导入并选用此 Skill。";
    }, "正在导入 Skill…");
  };
  document.getElementById("resumeRewriteSaveSettings").onclick = () => {
    const data = { skill: skillSelect.value };
    void rewriteAction(async () => {
      applyRewriteSettings(await (await request("/rewrite/settings", { method: "POST", data })).json());
      rewriteStatus.textContent = "设置已保存。";
    }, "正在保存设置…");
  };
  rewriteForm.addEventListener("submit", event => {
    event.preventDefault();
    const settings = { skill: skillSelect.value };
    const job = rewriteMode === "job" ? {
      title: rewriteForm.elements.job_title.value,
      description: rewriteForm.elements.job_description.value,
    } : {};
    const instruction = rewriteMode === "skill" ? (rewriteForm.elements.instruction?.value || "") : "";
    const useUploaded = rewriteForm.elements.resume_source?.value === "uploaded";
    const draft = readDraft();
    void rewriteAction(async () => {
      rewriteDocument = null;
      rewriteResult.hidden = true;
      const tracker = startProgress([
        "读取基准简历与当前 Skill",
        "调用对话 AI 重构简历正文",
        "核验真实数字与原项目标题",
        "整理改写对比结果"
      ]);
      try {
        await request("/rewrite/settings", { method: "POST", data: settings });
        let base = draft;
        if (useUploaded) {
          const data = new FormData();
          data.append("source", "current");
          base = (await (await request("/import", { method: "POST", data })).json()).document;
        }
        tracker.step(1);
        const result = await (await request("/rewrite", {
          method: "POST",
          data: { mode: rewriteMode, job, instruction, document: base }
        })).json();
        tracker.step(3);
        rewriteDocument = result.document;
        const changes = document.getElementById("resumeRewriteChanges");
        changes.replaceChildren(...result.changes.map(change => {
          const entry = document.createElement("div");
          entry.className = "re-rewrite-change";
          const entries = [["strong", change.section]];
          if (change.before) entries.push(["p", "原文：" + change.before]);
          entries.push(["p", change.after ? "改写：" + change.after : "本版省略"]);
          for (const [tag, value] of entries) {
            const element = document.createElement(tag);
            element.textContent = value;
            entry.append(element);
          }
          return entry;
        }));
        rewriteResult.hidden = !result.changes.length;
        tracker.done(result.changes.length ? `已生成 ${result.changes.length} 处改写` : "已完成核验");
        rewriteStatus.textContent = result.changes.length ? `已生成临时草稿，共 ${result.changes.length} 处改写。`
          : "没有通过原文核对的改写建议。";
      } catch (error) {
        tracker.fail("改写失败");
        throw error;
      }
    }, "正在生成临时改写草稿…");
  });
  const htmlPreviewDialog = document.getElementById("resumeHtmlPreview");
  const htmlFrame = document.getElementById("resumeHtmlFrame");
  const progressBox = document.getElementById("resumeRewriteProgress");
  const progressLabel = document.getElementById("resumeProgressLabel");
  const progressMeta = document.getElementById("resumeProgressMeta");
  const progressBar = document.getElementById("resumeProgressBar");
  const progressSteps = document.getElementById("resumeProgressSteps");
  let lastGeneratedHtml = "";
  let lastGeneratedTitle = "简历";

  function startProgress(steps) {
    if (!progressBox) return { step() {}, done() {}, fail() {} };
    const started = Date.now();
    let current = 0;
    progressBox.hidden = false;
    progressBox.dataset.state = "running";
    progressSteps.replaceChildren(...steps.map((text, idx) => {
      const li = document.createElement("li");
      li.dataset.step = String(idx);
      li.textContent = text;
      return li;
    }));
    const paint = () => {
      const secs = Math.max(0, Math.round((Date.now() - started) / 1000));
      progressMeta.textContent = `${secs}s`;
      progressLabel.textContent = steps[Math.min(current, steps.length - 1)] || "正在处理…";
      const pct = Math.min(94, Math.round(((current + 0.5) / steps.length) * 100));
      progressBar.style.width = `${pct}%`;
      [...progressSteps.children].forEach((li, idx) => {
        li.dataset.status = idx < current ? "done" : idx === current ? "active" : "pending";
      });
    };
    paint();
    const timer = setInterval(() => {
      const secs = Math.round((Date.now() - started) / 1000);
      progressMeta.textContent = `${secs}s`;
      if (current === 1 && secs >= 12 && steps.length >= 3) {
        current = 2;
        paint();
      }
    }, 1000);
    return {
      step(index) {
        current = Math.max(current, Math.min(index, steps.length - 1));
        paint();
      },
      done(label = "已完成") {
        clearInterval(timer);
        progressBox.dataset.state = "done";
        progressLabel.textContent = label;
        progressBar.style.width = "100%";
        [...progressSteps.children].forEach(li => { li.dataset.status = "done"; });
      },
      fail(label = "生成未完成") {
        clearInterval(timer);
        progressBox.dataset.state = "error";
        progressLabel.textContent = label;
      }
    };
  }

  async function generateSkillHtml(baseDoc) {
    const tracker = startProgress([
      "读取基准简历与 Skill 样式规范",
      "调用对话 AI 生成现代 HTML/CSS 排版",
      "执行安全清洗与证件照注入",
      "渲染网页版预览"
    ]);
    try {
      const instruction = rewriteMode === "skill" ? (rewriteForm.elements.instruction?.value || "") : "";
      await request("/rewrite/settings", { method: "POST", data: { skill: skillSelect.value } });
      tracker.step(1);
      const result = await (await request("/render/skill-html", {
        method: "POST",
        data: { document: baseDoc, skill: skillSelect.value, instruction }
      })).json();
      tracker.step(3);
      lastGeneratedHtml = result.html || "";
      lastGeneratedTitle = result.title || baseDoc.title || "简历";
      htmlFrame.srcdoc = lastGeneratedHtml;
      tracker.done("网页版简历已生成");
      htmlPreviewDialog.showModal();
      rewriteStatus.textContent = "已按当前 Skill 生成网页版简历，可直接打印/另存 PDF 或下载 HTML。";
    } catch (error) {
      tracker.fail("网页版生成失败");
      throw error;
    }
  }

  document.getElementById("resumeSkillHtmlBtn").onclick = () => {
    const useUploaded = rewriteForm.elements.resume_source?.value === "uploaded";
    const draft = readDraft();
    void rewriteAction(async () => {
      let base = draft;
      if (useUploaded) {
        const data = new FormData();
        data.append("source", "current");
        base = (await (await request("/import", { method: "POST", data })).json()).document;
      }
      await generateSkillHtml(base);
    }, "正在按 Skill 风格生成网页版简历…");
  };

  document.getElementById("resumeHtmlPrint").onclick = () => {
    if (!lastGeneratedHtml) return;
    htmlFrame.contentWindow?.focus();
    htmlFrame.contentWindow?.print();
  };

  document.getElementById("resumeHtmlDocx").onclick = async () => {
    if (!lastGeneratedHtml) return;
    const btn = document.getElementById("resumeHtmlDocx");
    btn.disabled = true;
    const oldText = btn.textContent;
    btn.textContent = "正在生成 Word…";
    try {
      const response = await request("/render/skill-docx", {
        method: "POST",
        data: { html: lastGeneratedHtml, title: lastGeneratedTitle }
      });
      const file = await response.blob();
      const url = URL.createObjectURL(file);
      const link = document.createElement("a");
      const safeName = lastGeneratedTitle.trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, "_") || "简历";
      link.href = url;
      link.download = safeName + "-Skill版.docx";
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) {
      rewriteStatus.textContent = error.message;
    } finally {
      btn.textContent = oldText;
      btn.disabled = false;
    }
  };

  rewriteResult.querySelectorAll("[data-rewrite-output]").forEach(button => {
    button.onclick = () => {
      if (!rewriteDocument) return;
      const mode = button.dataset.rewriteOutput;
      void rewriteAction(async () => {
        if (mode === "save") {
          await request("/drafts", { method: "POST", data: rewriteDocument });
          await refreshList();
          rewriteStatus.textContent = "已另存为新版本，可在「简历版本」中打开编辑。";
          return;
        }
        if (mode === "skill-html") {
          await generateSkillHtml(rewriteDocument);
          return;
        }
        await render(mode, rewriteDocument, true);
        rewriteStatus.textContent = (mode === "pdf" || mode === "docx") ? "已导出改写草稿。" : "已打开草稿预览。";
      }, mode === "skill-html" ? "正在按 Skill 风格生成网页版简历…" : "正在处理草稿…");
    };
  });

  function addField(label = "") {
    if (extras.children.length >= 8) {
      status.textContent = "最多可添加 8 个个人信息字段。";
      return;
    }
    const row = appendField({ label, value: "" });
    row.querySelector(label ? "[data-field-value]" : "[data-field-label]").focus();
    markChanged();
  }

  function renameSection(section) {
    const input = section.querySelector("[data-section-title]");
    const toggle = section.querySelector("[data-toggle-section]");
    if (!input.hidden) return;
    const previous = input.value;
    input.hidden = false;
    toggle.hidden = true;
    input.focus();
    input.select();
    const finish = name => {
      input.value = name;
      input.onkeydown = null;
      setSectionCaption(section, name);
      input.hidden = true;
      toggle.hidden = false;
      if (name !== previous) {
        setupSectionForm(section);
        markChanged();
      }
      updateMoveButtons();
    };
    input.onkeydown = event => {
      if (event.key !== "Enter" && event.key !== "Escape") return;
      event.preventDefault();
      if (event.key === "Escape") input.value = previous;
      input.blur();
      toggle.focus();
    };
    input.addEventListener("blur", () => finish(input.value.trim() || previous), { once: true });
  }

  function appendInlineMarkdown(parent, text) {
    const pattern = /\[([^\]\n]{1,180})\]\((https?:\/\/[^\s()]{1,2048})\)|(\*\*|\*|~~)([^\n]{1,2048}?)\3/g;
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > offset) parent.append(document.createTextNode(text.slice(offset, match.index)));
      const [, label, url, marker, inner] = match;
      if (url) {
        const link = document.createElement("a");
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        if (/^https?:\/\/(?:www\.)?github\.com\b/i.test(url)) {
          link.innerHTML = `<svg viewBox="0 0 16 16" style="width:12px;height:12px;vertical-align:-2px;margin-right:3px;fill:currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>`;
          link.append(document.createTextNode(label));
        } else {
          link.textContent = label;
        }
        parent.append(link);
      } else {
        const tag = marker === "**" ? "strong" : marker === "*" ? "em" : "del";
        const el = document.createElement(tag);
        el.textContent = inner;
        parent.append(el);
      }
      offset = match.index + match[0].length;
    }
    if (offset < text.length) parent.append(document.createTextNode(text.slice(offset)));
  }

  function renderMarkdownPreview(box, text) {
    box.replaceChildren();
    const lines = String(text || "").split("\n").map(line => line.trim()).filter(Boolean);
    if (!lines.length) {
      const empty = document.createElement("p");
      empty.className = "re-md-empty";
      empty.textContent = "暂无内容，支持 **加粗**、- 要点、[链接](https://...)";
      box.append(empty);
      return;
    }
    for (const line of lines) {
      if (/^#{1,6}\s+/.test(line)) {
        const h = document.createElement("h4");
        appendInlineMarkdown(h, line.replace(/^#{1,6}\s+/, ""));
        box.append(h);
      } else if (/^[-*•]\s+/.test(line)) {
        const p = document.createElement("p");
        p.className = "re-md-bullet";
        p.append(document.createTextNode("• "));
        appendInlineMarkdown(p, line.replace(/^[-*•]\s+/, ""));
        box.append(p);
      } else {
        const p = document.createElement("p");
        appendInlineMarkdown(p, line);
        box.append(p);
      }
    }
  }

  function toggleInlinePreview(button, area, box) {
    const show = button.getAttribute("aria-pressed") !== "true";
    button.setAttribute("aria-pressed", String(show));
    button.textContent = show ? "编辑" : "预览";
    area.hidden = show;
    box.hidden = !show;
    if (show) renderMarkdownPreview(box, area.value);
  }

  function applyFormat(area, kind, onChanged) {
    const start = area.selectionStart;
    const end = area.selectionEnd;
    const text = area.value.slice(start, end);
    const wraps = { bold: "**", italic: "*", strike: "~~" };
    let offset = start;
    let replacement;
    if (wraps[kind]) {
      const mark = wraps[kind];
      replacement = mark + (text || "文字") + mark;
    } else if (kind === "link") {
      const url = window.prompt("输入链接（https:// 或 http://）", "https://");
      if (!url || !/^https?:\/\/[^\s()[\]]+$/i.test(url)) return;
      replacement = `[${text.replace(/[\[\]]/g, "") || "链接"}](${url})`;
    } else {
      offset = start === 0 ? 0 : area.value.lastIndexOf("\n", start - 1) + 1;
      replacement = area.value.slice(offset, end).split("\n").map((line, index) => {
        const prefix = kind === "heading" ? "### " : kind === "ordered" ? `${index + 1}. ` : "- ";
        return prefix + line;
      }).join("\n");
    }
    if (area.value.length + replacement.length - (end - offset) > area.maxLength) return;
    area.setRangeText(replacement, offset, end, "end");
    area.focus();
    if (onChanged) onChanged();
    markChanged();
  }

  quickField.addEventListener("change", () => {
    if (quickField.value) addField(quickField.value);
    quickField.value = "";
  });
  root.addEventListener("input", event => {
    if (event.target !== quickField && !event.target.hasAttribute("data-section-title")) markChanged();
    const card = event.target.closest(".re-section");
    if (card && event.target.closest("[data-form-area]")) syncForm(card);
  });
  root.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || busy) return;
    if (button.dataset.draftId) {
      if (button.dataset.draftId === id) versions.open = false;
      else if (canLeaveDraft()) {
        versions.open = false;
        void run(async () => showDraft(await (await request("/drafts/" + button.dataset.draftId)).json()), "正在打开简历…");
      }
      return;
    }
    const section = button.closest(".re-section");
    if (section && button.hasAttribute("data-toggle-section")) {
      toggleSection(section, button.getAttribute("aria-expanded") !== "true");
      return;
    }
    if (section && button.hasAttribute("data-rename")) {
      renameSection(section);
      return;
    }
    if (section && button.hasAttribute("data-add-entry")) {
      const schema = sectionSchema(section);
      const node = schema.kind === "list" ? itemCard(section, "") : entryCard(section, blankEntry());
      section.querySelector("[data-entries]").append(node);
      renumberEntries(section);
      syncForm(section);
      markChanged();
      node.querySelector("input, textarea").focus();
      return;
    }
    if (section && button.hasAttribute("data-entry-remove")) {
      button.closest(".re-entry").remove();
      renumberEntries(section);
      syncForm(section);
      markChanged();
      return;
    }
    if (section && button.dataset.entryMove) {
      const node = button.closest(".re-entry");
      if (button.dataset.entryMove === "-1") node.previousElementSibling?.before(node);
      else node.nextElementSibling?.after(node);
      renumberEntries(section);
      syncForm(section);
      markChanged();
      return;
    }
    if (section && button.dataset.entryPolish) {
      const entry = button.closest(".re-entry");
      const area = entry.querySelector("[data-entry=content]");
      const undoBtn = entry.querySelector("[data-entry-undo]");
      const previewBtn = entry.querySelector("[data-entry-preview]");
      const previewBox = entry.querySelector("[data-entry-preview-box]");
      const rawContent = area.value.trim();
      if (!rawContent) {
        status.textContent = "请先填写这段经历的内容后再润色。";
        area.focus();
        return;
      }
      const action = button.dataset.entryPolish;
      const oldLabel = button.textContent;
      button.disabled = true;
      button.textContent = action === "shorten" ? "精简中…" : action === "evidence" ? "审计中…" : "润色中…";
      void (async () => {
        try {
          const resp = await request("/polish-entry", {
            method: "POST",
            data: {
              section: section.querySelector("[data-section-title]").value.trim(),
              name: entry.querySelector("[data-entry=name]")?.value || "",
              role: entry.querySelector("[data-entry=role]")?.value || "",
              content: area.value,
              action
            }
          });
          const data = await resp.json();
          entry.dataset.prevContent = area.value;
          area.value = data.content || area.value;
          if (undoBtn) undoBtn.hidden = false;
          if (previewBtn?.getAttribute("aria-pressed") === "true") renderMarkdownPreview(previewBox, area.value);
          syncForm(section);
          markChanged();
          status.textContent = action === "shorten"
            ? "已完成局部精简，不满意可点「撤销」。"
            : action === "evidence"
              ? "已完成证据护卫改写（已收敛虚夸表述），不满意可点「撤销」。"
              : "已完成 STAR 局部润色，不满意可点「撤销」。";
        } catch (error) {
          status.textContent = error.message;
        } finally {
          button.textContent = oldLabel;
          button.disabled = false;
        }
      })();
      return;
    }
    if (section && button.hasAttribute("data-entry-undo")) {
      const entry = button.closest(".re-entry");
      const area = entry.querySelector("[data-entry=content]");
      const previewBtn = entry.querySelector("[data-entry-preview]");
      const previewBox = entry.querySelector("[data-entry-preview-box]");
      if (entry.dataset.prevContent != null) {
        area.value = entry.dataset.prevContent;
        delete entry.dataset.prevContent;
        button.hidden = true;
        if (previewBtn?.getAttribute("aria-pressed") === "true") renderMarkdownPreview(previewBox, area.value);
        syncForm(section);
        markChanged();
        status.textContent = "已恢复该段经历润色前的内容。";
      }
      return;
    }
    if (section && button.dataset.entryFormat) {
      const entry = button.closest(".re-entry");
      const area = entry.querySelector("[data-entry=content]");
      const previewBtn = entry.querySelector("[data-entry-preview]");
      const previewBox = entry.querySelector("[data-entry-preview-box]");
      if (previewBtn?.getAttribute("aria-pressed") === "true") toggleInlinePreview(previewBtn, area, previewBox);
      applyFormat(area, button.dataset.entryFormat, () => syncForm(section));
      return;
    }
    if (section && button.hasAttribute("data-entry-preview")) {
      const entry = button.closest(".re-entry");
      toggleInlinePreview(button, entry.querySelector("[data-entry=content]"), entry.querySelector("[data-entry-preview-box]"));
      return;
    }
    if (section && button.hasAttribute("data-section-preview")) {
      toggleInlinePreview(button, section.querySelector("[data-section-content]"), section.querySelector("[data-section-preview-box]"));
      return;
    }
    if (section && button.dataset.format) {
      const area = section.querySelector("[data-section-content]");
      const previewBtn = section.querySelector("[data-section-preview]");
      const previewBox = section.querySelector("[data-section-preview-box]");
      if (previewBtn?.getAttribute("aria-pressed") === "true") toggleInlinePreview(previewBtn, area, previewBox);
      applyFormat(area, button.dataset.format);
      return;
    }
    if (section && button.hasAttribute("data-tidy")) {
      const area = section.querySelector("[data-section-content]");
      const formMode = section.dataset.mode === "form";
      if (formMode) syncForm(section);
      const clean = area.value.replace(/[ \t]+$/gm, "").replace(/^([ \t]*)[•●·]\s*/gm, "$1- ").replace(/\n{3,}/g, "\n\n").trim();
      if (area.value !== clean) {
        area.value = clean;
        markChanged();
      }
      if (formMode) buildForm(section);
      status.textContent = "栏目格式已整理";
      return;
    }
    if (button.hasAttribute("data-remove-field")) {
      button.closest(".re-extra").remove();
      markChanged();
      return;
    }
    if (section && button.hasAttribute("data-remove")) {
      section.remove();
      updateMoveButtons();
      markChanged();
      return;
    }
    if (section && button.dataset.move) {
      if (button.dataset.move === "-1") section.previousElementSibling?.before(section);
      else section.nextElementSibling?.after(section);
      updateMoveButtons();
      markChanged();
      return;
    }
    switch (button.dataset.restore ? "add" : button.dataset.action) {
      case "new":
        if (canLeaveDraft()) {
          versions.open = false;
          startDraft();
          title.focus();
        }
        break;
      case "duplicate":
        versions.open = false;
        void run(async () => {
          const copy = readDraft();
          copy.title = ((copy.title || "未命名简历").slice(0, 72) + " 副本").slice(0, 80);
          const created = await (await request("/drafts", { method: "POST", data: copy })).json();
          showDraft(created);
          await refreshList();
          status.textContent = `已复制为新版本「${created.document.title}」。`;
        }, "正在复制版本…");
        break;
      case "set-default":
        if (!id) return;
        versions.open = false;
        void run(async () => {
          await request("/drafts/" + id + "/set-default", { method: "POST" });
          await refreshList();
          status.textContent = "已设为岗位探索与投递默认简历。";
        }, "正在设为默认简历…");
        break;
      case "split-preview":
        setSplitPreview(workspace?.dataset.split !== "1");
        break;
      case "split-refresh":
        void refreshSplitPreview();
        break;
      case "split-close":
        setSplitPreview(false);
        break;
      case "add":
        if (container.children.length >= maxSections) {
          status.textContent = `最多支持 ${maxSections} 个栏目。`;
          return;
        }
        const added = appendSection({ title: button.dataset.restore || "自定义模块", content: "" }, true);
        updateMoveButtons();
        markChanged();
        if (button.dataset.restore) {
          const target = added.dataset.mode === "form"
            ? added.querySelector("[data-entries] input") : added.querySelector("[data-section-content]");
          target?.focus();
        } else renameSection(added);
        break;
      case "add-field":
        addField();
        break;
      case "remove-photo":
        setPhoto("");
        markChanged();
        break;
      case "import":
        importStatus.textContent = "";
        importDialog.showModal();
        break;
      case "undo-doc":
        applyHistoryStep(-1);
        break;
      case "redo-doc":
        applyHistoryStep(1);
        break;
      case "jd-report":
        void openJdHeatmapDialog();
        break;
      case "rewrite":
        void openRewrite();
        break;
      case "delete":
        if (!id || !window.confirm("删除这份已保存的简历？")) return;
        void run(async () => {
          await request("/drafts/" + id, { method: "DELETE", data: { revision } });
          startDraft();
          await refreshList();
        }, "正在删除…");
        break;
      case "save":
        if (id && !dirty) {
          showToast("✓ 当前内容已保存，无需重复保存", "info");
          break;
        }
        void run(async () => {
          const document = readDraft();
          const response = id
            ? await request("/drafts/" + id, { method: "PUT", data: { document, revision } })
            : await request("/drafts", { method: "POST", data: document });
          showDraft(await response.json());
          await refreshList();
          showToast("✓ 简历已保存", "success");
        }, "正在保存…");
        break;
      case "auto":
      case "preview":
      case "pdf":
      case "docx":
      case "image":
        void run(() => render(button.dataset.action), "正在排版…");
        break;
    }
  });

  /* 全局 Ctrl+Z / Ctrl+Y 撤销重做 + 考官拷打 (Grill-me) + 多岗位 JD 共性热力图 */
  window.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    if (document.querySelector("dialog[open]")) return;
    const tag = (event.target?.tagName || "").toUpperCase();
    // Inside an active input/textarea let native undo work unless Shift+Z or Ctrl+Y
    const key = event.key.toLowerCase();
    if (key === "z" && !event.shiftKey && tag !== "INPUT" && tag !== "TEXTAREA") {
      event.preventDefault();
      applyHistoryStep(-1);
    } else if ((key === "y" || (key === "z" && event.shiftKey)) && tag !== "INPUT" && tag !== "TEXTAREA") {
      event.preventDefault();
      applyHistoryStep(1);
    }
  });

  async function openGrillDialog(entryEl) {
    const sectionEl = entryEl.closest(".re-section");
    const sectionTitle = sectionEl?.querySelector("[data-section-name]")?.textContent?.trim() || "项目经历";
    const nameInput = entryEl.querySelector("[data-entry='name']");
    const roleInput = entryEl.querySelector("[data-entry='role']");
    const contentArea = entryEl.querySelector("[data-entry='content']");
    const undoBtn = entryEl.querySelector("[data-entry-undo]");
    const name = nameInput?.value?.trim() || "";
    const role = roleInput?.value?.trim() || "";
    const content = contentArea?.value?.trim() || "";
    if (!content) { showToast("请先填写该段经历的内容再进行考官拷打", "info"); return; }

    const dialog = document.createElement("dialog");
    dialog.className = "re-dialog";
    dialog.style.cssText = "width:min(680px,94vw);max-width:94vw;padding:20px;border-radius:16px;border:1px solid #cbd5e1;";

    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;";
    const hTitle = document.createElement("strong");
    hTitle.textContent = `考官拷打（Grill-me）· ${name || sectionTitle}`;
    hTitle.style.cssText = "font-size:15px;color:#0f172a;";
    const closeX = document.createElement("button");
    closeX.type = "button"; closeX.textContent = "×";
    closeX.style.cssText = "border:1px solid #e2e8f0;background:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;font-size:16px;";
    closeX.addEventListener("click", () => dialog.close());
    head.append(hTitle, closeX);

    const logBox = document.createElement("div");
    logBox.style.cssText = "display:grid;gap:10px;max-height:320px;overflow-y:auto;padding:12px;border-radius:12px;background:#f8fafc;border:1px solid #e2e8f0;margin-bottom:12px;";
    const ansInput = document.createElement("textarea");
    ansInput.rows = 3;
    ansInput.placeholder = "用你自己的话如实回答面试官追问（可补充测试集规模、方案对比、异常兜底等细节）…";
    ansInput.style.cssText = "width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #cbd5e1;border-radius:10px;font-size:13px;line-height:1.6;margin-bottom:10px;";

    const foot = document.createElement("div");
    foot.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;";
    const statusTxt = document.createElement("span");
    statusTxt.style.cssText = "font-size:12px;color:#64748b;";
    const btnGroup = document.createElement("div");
    btnGroup.style.cssText = "display:flex;gap:8px;";
    const nextBtn = document.createElement("button");
    nextBtn.type = "button"; nextBtn.className = "re-button"; nextBtn.textContent = "提交回答 · 下一轮深挖";
    const synthBtn = document.createElement("button");
    synthBtn.type = "button"; synthBtn.className = "re-button re-primary"; synthBtn.textContent = "提炼干货回写这段经历";
    synthBtn.disabled = true;
    btnGroup.append(nextBtn, synthBtn);
    foot.append(statusTxt, btnGroup);

    dialog.append(head, logBox, ansInput, foot);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();

    const qaHistory = [];
    let currentQuestion = "";

    function appendMsg(roleLabel, text, sub, extra = null) {
      const box = document.createElement("div");
      const isInterviewer = roleLabel.includes("考官");
      box.style.cssText = isInterviewer
        ? "padding:11px 13px;border-radius:10px;background:#ffffff;border:1px solid #dbeafe;"
        : "padding:9px 12px;border-radius:10px;background:#eef2ff;color:#1e1b4b;";
      const whoRow = document.createElement("div");
      whoRow.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:5px;";
      const who = document.createElement("div");
      who.textContent = roleLabel;
      who.style.cssText = "font-size:11px;font-weight:700;color:#4f46e5;";
      whoRow.append(who);
      if (extra?.verdict) {
        const badge = document.createElement("span");
        const tone = extra.verdict === "可以写"
          ? "background:#ecfdf5;color:#047857;border:1px solid #a7f3d0;"
          : extra.verdict === "不能写"
            ? "background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;"
            : "background:#fffbeb;color:#b45309;border:1px solid #fde68a;";
        badge.textContent = `证据评级：${extra.verdict}`;
        badge.style.cssText = `font-size:11px;font-weight:700;padding:1px 8px;border-radius:999px;${tone}`;
        whoRow.append(badge);
      }
      const body = document.createElement("div");
      body.textContent = text;
      body.style.cssText = "font-size:13px;line-height:1.65;color:#0f172a;white-space:pre-wrap;";
      box.append(whoRow, body);
      if (sub) {
        const hint = document.createElement("div");
        hint.textContent = sub;
        hint.style.cssText = "font-size:11.5px;color:#64748b;margin-top:6px;";
        box.append(hint);
      }
      if (extra?.danger_answer || extra?.strong_answer) {
        const cards = document.createElement("div");
        cards.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-top:8px;";
        if (extra.danger_answer) {
          const dCard = document.createElement("div");
          dCard.style.cssText = "padding:8px 10px;border-radius:8px;background:#fef2f2;border:1px solid #fecaca;font-size:11.5px;line-height:1.55;color:#991b1b;";
          const dTitle = document.createElement("div");
          dTitle.textContent = "✕ 危险回答（易翻车）";
          dTitle.style.cssText = "font-weight:700;margin-bottom:3px;";
          const dBody = document.createElement("div");
          dBody.textContent = extra.danger_answer;
          dCard.append(dTitle, dBody);
          cards.append(dCard);
        }
        if (extra.strong_answer) {
          const sCard = document.createElement("div");
          sCard.style.cssText = "padding:8px 10px;border-radius:8px;background:#ecfdf5;border:1px solid #a7f3d0;font-size:11.5px;line-height:1.55;color:#065f46;";
          const sTitle = document.createElement("div");
          sTitle.textContent = "✓ 强回答思路卡";
          sTitle.style.cssText = "font-weight:700;margin-bottom:3px;";
          const sBody = document.createElement("div");
          sBody.textContent = extra.strong_answer;
          sCard.append(sTitle, sBody);
          cards.append(sCard);
        }
        box.append(cards);
      }
      logBox.append(box);
      logBox.scrollTop = logBox.scrollHeight;
    }

    async function askNext() {
      nextBtn.disabled = true;
      statusTxt.textContent = "面试官正在审阅你的经历并构思追问…";
      try {
        const res = await request("/grill", {
          method: "POST",
          data: { section: sectionTitle, name, role, content, history: qaHistory, synthesize: false },
        });
        const data = await res.json();
        currentQuestion = data.question || "";
        const meta = [data.weakness ? `薄弱点：${data.weakness}` : "", data.tip ? `思路：${data.tip}` : ""].filter(Boolean).join(" ｜ ");
        appendMsg(`第 ${data.round || qaHistory.length + 1} 轮 · 考官`, currentQuestion, meta, data);
        statusTxt.textContent = qaHistory.length ? `已回答 ${qaHistory.length} 轮，可继续深挖或一键提炼回写` : "请作答第 1 轮追问";
      } catch (err) {
        statusTxt.textContent = err.message;
      } finally { nextBtn.disabled = false; }
    }

    nextBtn.addEventListener("click", async () => {
      const answer = ansInput.value.trim();
      if (!answer) { showToast("请先输入你的回答", "info"); return; }
      qaHistory.push({ q: currentQuestion, a: answer });
      appendMsg("我的回答", answer, "");
      ansInput.value = "";
      synthBtn.disabled = false;
      await askNext();
    });

    synthBtn.addEventListener("click", async () => {
      const pending = ansInput.value.trim();
      if (pending && currentQuestion) {
        qaHistory.push({ q: currentQuestion, a: pending });
        ansInput.value = "";
      }
      if (!qaHistory.length) { showToast("请先回答至少一轮问题", "info"); return; }
      synthBtn.disabled = true;
      statusTxt.textContent = "正在将你回答的真实细节提炼回写到简历要点…";
      try {
        const res = await request("/grill", {
          method: "POST",
          data: { section: sectionTitle, name, role, content, history: qaHistory, synthesize: true },
        });
        const data = await res.json();
        if (data.improved_content && contentArea) {
          pushHistory(true);
          contentArea.dataset.prevPolish = contentArea.value;
          contentArea.value = data.improved_content;
          contentArea.dispatchEvent(new Event("input", { bubbles: true }));
          if (undoBtn) undoBtn.hidden = false;
          showToast("✓ 已将拷打提炼的干货回写到该段经历", "success");
          dialog.close();
        }
      } catch (err) {
        statusTxt.textContent = err.message;
        synthBtn.disabled = false;
      }
    });

    void askNext();
  }

  async function openJdHeatmapDialog() {
    const dialog = document.createElement("dialog");
    dialog.className = "re-dialog";
    dialog.style.cssText = "width:min(700px,94vw);max-width:94vw;padding:20px;border-radius:16px;border:1px solid #cbd5e1;";

    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;";
    const hTitle = document.createElement("strong");
    hTitle.textContent = "目标岗位群 JD 高频技能共性报告";
    hTitle.style.cssText = "font-size:15px;color:#0f172a;";
    const closeX = document.createElement("button");
    closeX.type = "button"; closeX.textContent = "×";
    closeX.style.cssText = "border:1px solid #e2e8f0;background:#fff;width:30px;height:30px;border-radius:8px;cursor:pointer;font-size:16px;";
    closeX.addEventListener("click", () => dialog.close());
    head.append(hTitle, closeX);

    const body = document.createElement("div");
    body.style.cssText = "display:grid;gap:12px;max-height:70vh;overflow-y:auto;";
    body.textContent = "正在聚合分析岗位库中的目标 JD…";
    dialog.append(head, body);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();

    try {
      const res = await request("/jd-report", { method: "POST", data: { document: readDraft() } });
      const data = await res.json();
      body.replaceChildren();
      const summary = document.createElement("div");
      summary.style.cssText = "padding:10px 12px;border-radius:10px;background:#eef2ff;color:#1e1b4b;font-size:13px;font-weight:600;";
      summary.textContent = `${data.summary || ""}${data.total_jobs ? ` · 基准简历覆盖率 ${data.coverage_rate}%` : ""}`;
      body.append(summary);

      if (Array.isArray(data.skills) && data.skills.length) {
        const list = document.createElement("div");
        list.style.cssText = "display:grid;gap:8px;";
        for (const item of data.skills) {
          const row = document.createElement("div");
          row.style.cssText = "display:grid;grid-template-columns:120px 1fr 90px;align-items:center;gap:10px;font-size:12.5px;";
          const name = document.createElement("strong");
          name.textContent = item.skill;
          name.style.cssText = "color:#0f172a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
          const track = document.createElement("div");
          track.style.cssText = "height:8px;border-radius:999px;background:#e2e8f0;overflow:hidden;";
          const fill = document.createElement("div");
          fill.style.cssText = `height:100%;width:${item.percent}%;border-radius:999px;background:${item.covered ? "linear-gradient(90deg,#10b981,#34d399)" : "linear-gradient(90deg,#f59e0b,#fbbf24)"};`;
          track.append(fill);
          const tag = document.createElement("span");
          tag.textContent = `${item.percent}% ${item.covered ? "✓ 已覆盖" : "○ 缺失"}`;
          tag.style.cssText = `font-size:11.5px;font-weight:600;text-align:right;color:${item.covered ? "#047857" : "#b45309"};`;
          row.append(name, track, tag);
          list.append(row);
        }
        body.append(list);
      }

      if (Array.isArray(data.recommendations) && data.recommendations.length) {
        const recBox = document.createElement("div");
        recBox.style.cssText = "display:grid;gap:6px;padding:12px;border-radius:10px;background:#f8fafc;border:1px solid #e2e8f0;font-size:12.5px;color:#334155;line-height:1.6;";
        for (const line of data.recommendations) {
          const p = document.createElement("div");
          p.textContent = `• ${line}`;
          recBox.append(p);
        }
        body.append(recBox);
      }

      if (Array.isArray(data.evidence_plans) && data.evidence_plans.length) {
        const scoutBox = document.createElement("div");
        scoutBox.style.cssText = "display:grid;gap:8px;padding:12px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;";
        const scoutHead = document.createElement("strong");
        scoutHead.textContent = "补证据与开源复现切入点（Project Scout · 拒绝硬凑关键词）";
        scoutHead.style.cssText = "font-size:12.5px;color:#92400e;";
        scoutBox.append(scoutHead);
        for (const plan of data.evidence_plans) {
          const item = document.createElement("div");
          item.style.cssText = "font-size:12px;line-height:1.6;color:#78350f;";
          const sk = document.createElement("strong");
          sk.textContent = `[${plan.skill} · ${plan.percent}%] `;
          item.append(sk, document.createTextNode(plan.action));
          scoutBox.append(item);
        }
        body.append(scoutBox);
      }
    } catch (err) {
      body.textContent = err.message || "生成共性报告失败";
    }
  }

  root.addEventListener("click", event => {
    const grillBtn = event.target.closest("[data-entry-grill]");
    if (grillBtn) {
      const entryEl = grillBtn.closest(".re-entry");
      if (entryEl) void openGrillDialog(entryEl);
    }
  });

  document.querySelectorAll("[data-close]").forEach(button => {
    button.addEventListener("click", () => { if (!busy || button.closest("dialog") === previewDialog) button.closest("dialog").close(); });
  });
  document.addEventListener("pointerdown", event => {
    if (versions.open && !versions.contains(event.target)) versions.open = false;
    if (appearance?.open && !appearance.contains(event.target)) appearance.open = false;
  });
  versions.addEventListener("keydown", event => {
    if (event.key === "Escape" && versions.open) {
      versions.open = false;
      versions.querySelector("summary").focus();
    }
  });
  importDialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
  previewDialog.addEventListener("close", () => document.getElementById("resumePreviewPages").replaceChildren());
  window.addEventListener("beforeunload", event => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  startDraft();
  const initialParams = new URLSearchParams(window.location.search);
  const requestedDraftId = initialParams.get("draft");
  void run(async () => {
    const drafts = await refreshList();
    const target = (requestedDraftId && drafts.find(d => d.id === requestedDraftId)) || drafts[0];
    if (target) showDraft(await (await request("/drafts/" + target.id)).json());
    else status.textContent = "填写内容或导入已有简历";
  }, "正在读取已保存的简历…");
  if (initialParams.get("rewrite") === "1") {
    try {
      const handoff = sessionStorage.getItem("career:resume-rewrite-job");
      sessionStorage.removeItem("career:resume-rewrite-job");
      if (handoff) setRewriteJob(JSON.parse(handoff));
    } catch (_) {
      // The drawer also supports entering the target job manually.
    }
    void openRewrite();
  }
})();
