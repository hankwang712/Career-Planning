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
  const importDialog = document.getElementById("resumeImport");
  const importForm = document.getElementById("resumeImportForm");
  const importStatus = document.getElementById("resumeImportStatus");
  const previewDialog = document.getElementById("resumePreview");
  const endpoint = "/api/resume-editor";
  const maxSections = Number(root.dataset.maxSections);
  let id = "";
  let revision = 0;
  let layout = "standard";
  let style = "classic";
  let photo = "";
  let dirty = false;
  let busy = false;

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

  function readDraft() {
    return {
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
    setSectionCaption(card, section.title);
    const content = card.querySelector("[data-section-content]");
    content.value = section.content;
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

  function fillDraft(document) {
    title.value = document.title;
    contact.forEach(input => { input.value = document.contact[input.dataset.contact] || ""; });
    container.replaceChildren();
    document.sections.forEach(section => appendSection(section));
    extras.replaceChildren();
    (document.extras || []).forEach(appendField);
    setPhoto(document.photo || "");
    layout = document.layout;
    style = document.style || "classic";
    updateMoveButtons();
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
  }

  function showDraft(draft) {
    id = draft.id;
    revision = draft.revision;
    fillDraft(draft.document);
    dirty = false;
    badge.textContent = "已保存";
    markSelected();
    status.textContent = "已保存的简历";
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

  async function render(mode, documentData = readDraft(), temporary = false) {
    const response = await request("/render/" + mode, { method: "POST", data: documentData });
    if (mode === "auto" || mode === "preview") {
      const result = await response.json();
      if (!temporary && mode === "auto" && layout !== result.layout) {
        layout = result.layout;
        markChanged();
      } else if (!temporary) {
        status.textContent = dirty ? "有未保存的修改" : "";
      }
      document.getElementById("resumePreviewInfo").textContent =
        `A4 · ${result.page_count} 页 · ${result.layout === "compact" ? "紧凑版式" : "标准版式"}`;
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
    link.download = name + (mode === "pdf" ? ".pdf" : file.type === "application/zip" ? "-图片.zip" : ".png");
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
  const skillPrompt = document.getElementById("resumeSkillPrompt");
  let rewriteDocument;
  let rewriteBusy = false;

  function applyRewriteSettings(data) {
    skillSelect.replaceChildren(...data.skills.map(skill => new Option(`${skill.name} · ${skill.origin}`, skill.id)));
    skillSelect.value = data.settings.skill;
    skillPrompt.textContent = data.prompt;
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
    try {
      const data = await (await request("/rewrite/settings?skill=" + encodeURIComponent(selected))).json();
      if (selected === skillSelect.value) skillPrompt.textContent = data.prompt || "";
    } catch (error) {
      if (selected === skillSelect.value) rewriteStatus.textContent = error.message;
    }
  });
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
    const job = {
      title: rewriteForm.elements.job_title.value,
      description: rewriteForm.elements.job_description.value,
    };
    const useUploaded = rewriteForm.elements.resume_source?.value === "uploaded";
    const draft = readDraft();
    void rewriteAction(async () => {
      rewriteDocument = null;
      rewriteResult.hidden = true;
      await request("/rewrite/settings", { method: "POST", data: settings });
      let base = draft;
      if (useUploaded) {
        const data = new FormData();
        data.append("source", "current");
        base = (await (await request("/import", { method: "POST", data })).json()).document;
      }
      const result = await (await request("/rewrite", { method: "POST", data: { job, document: base } })).json();
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
      rewriteStatus.textContent = result.changes.length ? `已生成临时草稿，共 ${result.changes.length} 处改写。`
        : "没有通过原文核对的改写建议。";
    }, "正在生成临时改写草稿…");
  });
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
        await render(mode, rewriteDocument, true);
        rewriteStatus.textContent = mode === "pdf" ? "已导出改写草稿。" : "已打开草稿预览。";
      }, "正在处理草稿…");
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
      if (name !== previous) markChanged();
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

  function applyFormat(area, kind) {
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
    markChanged();
  }

  quickField.addEventListener("change", () => {
    if (quickField.value) addField(quickField.value);
    quickField.value = "";
  });
  root.addEventListener("input", event => {
    if (event.target !== quickField && !event.target.hasAttribute("data-section-title")) markChanged();
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
    if (section && button.dataset.format) {
      applyFormat(section.querySelector("[data-section-content]"), button.dataset.format);
      return;
    }
    if (section && button.hasAttribute("data-tidy")) {
      const area = section.querySelector("[data-section-content]");
      const clean = area.value.replace(/[ \t]+$/gm, "").replace(/^([ \t]*)[•●·]\s*/gm, "$1- ").replace(/\n{3,}/g, "\n\n").trim();
      if (area.value !== clean) {
        area.value = clean;
        markChanged();
      }
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
      case "add":
        if (container.children.length >= maxSections) {
          status.textContent = `最多支持 ${maxSections} 个栏目。`;
          return;
        }
        const added = appendSection({ title: button.dataset.restore || "自定义模块", content: "" }, true);
        updateMoveButtons();
        markChanged();
        if (button.dataset.restore) added.querySelector("[data-section-content]").focus();
        else renameSection(added);
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
        void run(async () => {
          const document = readDraft();
          const response = id
            ? await request("/drafts/" + id, { method: "PUT", data: { document, revision } })
            : await request("/drafts", { method: "POST", data: document });
          showDraft(await response.json());
          await refreshList();
        }, "正在保存…");
        break;
      case "auto":
      case "preview":
      case "pdf":
      case "image":
        void run(() => render(button.dataset.action), "正在排版…");
        break;
    }
  });

  document.querySelectorAll("[data-close]").forEach(button => {
    button.addEventListener("click", () => { if (!busy || button.closest("dialog") === previewDialog) button.closest("dialog").close(); });
  });
  document.addEventListener("pointerdown", event => {
    if (versions.open && !versions.contains(event.target)) versions.open = false;
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
  void run(async () => {
    const drafts = await refreshList();
    if (drafts.length) showDraft(await (await request("/drafts/" + drafts[0].id)).json());
    else status.textContent = "填写内容或导入已有简历";
  }, "正在读取已保存的简历…");
  if (new URLSearchParams(window.location.search).get("rewrite") === "1") {
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
