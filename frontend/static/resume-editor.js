(() => {
  const root = document.getElementById("resumeWorkshop");
  const list = document.getElementById("resumeDraftList");
  const container = document.getElementById("resumeSections");
  const status = document.getElementById("resumeEditorStatus");
  const title = root.querySelector("[name=title]");
  const contact = [...root.querySelectorAll("[data-contact]")];
  const sectionType = document.getElementById("resumeSectionType");
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
      sections: [...container.children].map(section => ({
        title: section.querySelector("[data-section-title]").value,
        content: section.querySelector("[data-section-content]").value
      })),
      layout
    };
  }

  function updateMoveButtons() {
    [...container.children].forEach((section, index, sections) => {
      section.querySelector("[data-move='-1']").disabled = index === 0;
      section.querySelector("[data-move='1']").disabled = index === sections.length - 1;
    });
  }

  function appendSection(section) {
    const card = sectionTemplate.content.firstElementChild.cloneNode(true);
    card.querySelector("[data-section-title]").value = section.title;
    card.querySelector("[data-section-content]").value = section.content;
    container.append(card);
  }

  function fillDraft(document) {
    title.value = document.title;
    contact.forEach(input => { input.value = document.contact[input.dataset.contact] || ""; });
    container.replaceChildren();
    document.sections.forEach(appendSection);
    layout = document.layout;
    updateMoveButtons();
  }

  function markChanged() {
    dirty = true;
    status.textContent = "有未保存的修改";
  }

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
    markSelected();
    status.textContent = "已保存的简历";
  }

  function startDraft() {
    id = "";
    revision = 0;
    fillDraft({
      title: "未命名简历", contact: {}, layout: "standard",
      sections: [...sectionType.options].slice(0, -1).map(option => ({ title: option.value, content: "" }))
    });
    dirty = false;
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
    for (const [key, value] of Object.entries(imported.contact)) {
      if (!current.contact[key]?.trim() && value) current.contact[key] = value;
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
      const edited = replace ? { ...result.document, title: current.title, layout: current.layout }
        : mergeDraft(current, result.document);
      if (edited.sections.length > maxSections) throw new Error(`合并后超过 ${maxSections} 个栏目，请先移除空栏目或选择替换。`);
      fillDraft(edited);
      markChanged();
      importDialog.close();
      status.textContent = [result.ocr_used ? "已通过 OCR 填入，请核对识别结果。" : "已填入，请检查后保存。", result.warning].filter(Boolean).join(" ");
    }, "正在识别简历…", importStatus).finally(() => { submit.disabled = false; });
  });

  async function render(mode) {
    const response = await request("/render/" + mode, { method: "POST", data: readDraft() });
    if (mode === "auto" || mode === "preview") {
      const result = await response.json();
      if (mode === "auto" && layout !== result.layout) {
        layout = result.layout;
        markChanged();
      } else {
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
    const name = readDraft().title.trim().replace(/[\\/:*?"<>|\x00-\x1f]/g, "_") || "简历";
    link.href = url;
    link.download = name + (mode === "pdf" ? ".pdf" : file.type === "application/zip" ? "-图片.zip" : ".png");
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    status.textContent = dirty ? "已导出当前内容，修改尚未保存" : "已导出";
  }

  root.addEventListener("input", markChanged);
  root.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || busy) return;
    if (button.dataset.draftId && button.dataset.draftId !== id && canLeaveDraft()) {
      void run(async () => showDraft(await (await request("/drafts/" + button.dataset.draftId)).json()), "正在打开简历…");
      return;
    }
    const section = button.closest(".re-section");
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
    switch (button.dataset.action) {
      case "new":
        if (canLeaveDraft()) startDraft();
        break;
      case "add":
        if (container.children.length >= maxSections) {
          status.textContent = `最多支持 ${maxSections} 个栏目。`;
          return;
        }
        appendSection({ title: sectionType.value, content: "" });
        updateMoveButtons();
        markChanged();
        container.lastElementChild.querySelector("[data-section-title]").focus();
        break;
      case "import":
        importStatus.textContent = "";
        importDialog.showModal();
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
})();
