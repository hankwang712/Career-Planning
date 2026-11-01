(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { sessions: [], active: null, messages: [], hasMore: false, configured: false,
    pending: new Map(), retries: new Map(), view: 0, remoteBusy: false, creating: false, memoryTab: "sources" };
  let csrfPromise, memoryTimer, toastTimer;
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const apiUrl = (path) => `${String(window.__API_BASE__ || "").replace(/\/+$/, "")}${path}`;

  async function api(path, options = {}) {
    const method = options.method || "GET";
    const headers = { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers };
    if (method !== "GET") {
      csrfPromise ||= window.CareerAuth.headers().catch((error) => { csrfPromise = null; throw error; });
      Object.assign(headers, await csrfPromise);
    }
    const response = await fetch(apiUrl(path), { ...options, method, headers, credentials: "include", cache: "no-store" });
    if (response.status === 401) {
      window.location.assign("/main.html");
      throw new Error("登录已过期，请重新登录。");
    }
    if (!response.ok) {
      if (response.status === 403) csrfPromise = null;
      const data = await response.json().catch(() => ({}));
      throw new Error(data.message || "暂时无法完成操作，请稍后重试。");
    }
    return options.stream ? response : response.json();
  }

  function toast(message) {
    $("toast").textContent = message;
    $("toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3500);
  }

  function notice(message = "") {
    $("conversationNotice").textContent = message;
    $("conversationNotice").hidden = !message;
  }

  function sidebar(open) {
    $("chatSidebar").classList.toggle("open", open);
    $("sidebarScrim").hidden = !open;
    $("toggleSidebar").setAttribute("aria-expanded", String(open));
  }

  function updateComposer() {
    const busy = state.pending.has(state.active) || state.remoteBusy || state.creating;
    $("sendMessage").disabled = busy || !state.configured || !$("chatInput").value.trim();
    $("stopReply").hidden = !state.pending.has(state.active);
    $("retryMessage").hidden = busy || !state.retries.has(state.active);
    $("chatInput").disabled = !state.configured;
    $("chatInput").placeholder = state.configured ? "说说你在想什么…" : "配置对话模型后，即可开始聊天";
  }

  function renderSessions() {
    const query = $("sessionSearch").value.trim().toLocaleLowerCase();
    const rows = state.sessions.filter((row) => row.title.toLocaleLowerCase().includes(query));
    $("sessionCount").textContent = state.sessions.length;
    $("sessionList").replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "sidebar-empty";
      empty.textContent = query ? "没有找到相关对话" : "你的想法，从第一段对话开始。";
      $("sessionList").append(empty);
    }
    for (const row of rows) {
      const wrapper = document.createElement("div");
      wrapper.className = `session-row${row.id === state.active ? " active" : ""}`;
      const button = document.createElement("button");
      button.className = "session-open";
      button.textContent = row.title;
      button.title = row.title;
      button.setAttribute("aria-current", row.id === state.active ? "page" : "false");
      button.addEventListener("click", () => void openSession(row.id));
      const actions = document.createElement("span");
      actions.className = "session-actions";
      for (const [name, label, handler] of [["edit", "重命名对话", renameSession], ["trash", "删除对话", deleteSession]]) {
        const action = document.createElement("button");
        action.innerHTML = icon(name);
        action.setAttribute("aria-label", `${label}：${row.title}`);
        action.title = label;
        action.addEventListener("click", () => void handler(row));
        actions.append(action);
      }
      wrapper.append(button, actions);
      $("sessionList").append(wrapper);
    }
  }

  async function refreshSessions() {
    const data = await api("/api/chat/sessions");
    state.sessions = data.items;
    state.configured = data.configured;
    $("modelName").textContent = data.model;
    $("modelName").title = data.model;
    $("configurationNote").hidden = data.configured;
    $("userName").textContent = data.display_name || "我的工作区";
    $("userAvatar").textContent = (data.display_name || "我").slice(0, 1);
    renderSessions();
    updateComposer();
  }

  // Escape all source first. Only this small, explicit Markdown subset produces HTML.
  function inlineMarkdown(value) {
    return escape(value).replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  }

  function markdown(value) {
    const chunks = String(value).split(/```[^\n]*\n([\s\S]*?)```/g);
    return chunks.map((chunk, index) => {
      if (index % 2) return `<pre><code>${escape(chunk)}</code></pre>`;
      const blocks = chunk.split(/\n\s*\n/);
      return blocks.filter(Boolean).map((block) => {
        const lines = block.trim().split("\n");
        if (lines.every((line) => /^\s*[-*] /.test(line))) return `<ul>${lines.map((line) => `<li>${inlineMarkdown(line.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
        if (lines.every((line) => /^\s*\d+[.)、] /.test(line))) return `<ol>${lines.map((line) => `<li>${inlineMarkdown(line.replace(/^\s*\d+[.)、] /, ""))}</li>`).join("")}</ol>`;
        return lines.map((line) => {
          const heading = /^(#{1,4})\s+(.+)$/.exec(line);
          return heading ? `<h3>${inlineMarkdown(heading[2])}</h3>` : `<p>${inlineMarkdown(line)}</p>`;
        }).join("");
      }).join("");
    }).join("");
  }

  function messageElement(row, streaming = false) {
    const node = document.createElement("article");
    node.className = `message ${row.role}${streaming ? " streaming" : ""}${row.status === "failed" ? " failed" : ""}`;
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    avatar.innerHTML = icon("spark");
    const body = document.createElement("div");
    body.className = "message-body";
    const author = document.createElement("div");
    author.className = "message-author";
    author.textContent = "智航生涯";
    const content = document.createElement("div");
    content.className = "message-content";
    if (row.role === "user" || streaming) content.textContent = row.content;
    else content.innerHTML = markdown(row.content);
    body.append(author, content);
    if (row.status === "failed") {
      const failed = document.createElement("span");
      failed.className = "message-failed-note";
      failed.textContent = "本轮未完成回复";
      body.append(failed);
    }
    if (row.role === "assistant" && !streaming) {
      const copy = document.createElement("button");
      copy.className = "copy-message";
      copy.innerHTML = `${icon("copy")}复制`;
      copy.setAttribute("aria-label", "复制回答");
      copy.addEventListener("click", () => {
        if (!navigator.clipboard) return toast("当前浏览器暂不支持复制，请选中文字复制。");
        navigator.clipboard.writeText(row.content).then(() => toast("已复制回答"), () => toast("复制失败，请选中文字复制。"));
      });
      body.append(copy);
    }
    node.append(avatar, body);
    return node;
  }

  function scrollBottom() { $("conversationScroll").scrollTop = $("conversationScroll").scrollHeight; }
  function nearBottom() { const element = $("conversationScroll"); return element.scrollHeight - element.scrollTop - element.clientHeight < 120; }

  function renderMessages() {
    const pending = state.pending.get(state.active);
    const hasContent = state.messages.length || pending;
    $("welcome").hidden = Boolean(hasContent);
    $("conversation").hidden = !hasContent;
    $("messageList").replaceChildren(...state.messages.map((row) => messageElement(row)));
    $("loadEarlier").hidden = !state.hasMore;
    if (pending) {
      if (!state.messages.some((row) => row.request_id === pending.requestId && row.role === "user")) {
        $("messageList").append(messageElement({ role: "user", content: pending.content }));
      }
      $("messageList").append(messageElement({ role: "assistant", content: pending.answer }, true));
    }
  }

  async function refreshMessages(sessionId, scroll = false) {
    const view = state.view;
    const data = await api(`/api/chat/sessions/${sessionId}/messages`);
    if (state.active !== sessionId || view !== state.view) return;
    state.messages = data.items;
    state.hasMore = data.has_more;
    state.remoteBusy = data.generating && !state.pending.has(sessionId);
    const last = data.items.filter((row) => row.role === "user").at(-1);
    if (last?.status === "failed") state.retries.set(sessionId, { content: last.content, requestId: last.request_id });
    else if (!state.pending.has(sessionId)) state.retries.delete(sessionId);
    renderMessages();
    updateComposer();
    if (scroll) scrollBottom();
    if (state.remoteBusy) notice("这个对话正在另一个窗口回复，完成后会自动更新。");
    else if (!state.retries.has(sessionId)) notice();
  }

  function finishSession(id, keepalive = false) {
    if (!id || state.pending.has(id)) return;
    void api(`/api/chat/sessions/${id}/finish`, { method: "POST", keepalive }).catch(() => {});
  }

  async function openSession(id) {
    if (state.active !== id) finishSession(state.active);
    state.active = id;
    state.view += 1;
    state.messages = [];
    state.remoteBusy = false;
    state.hasMore = false;
    history.replaceState(null, "", `${location.pathname}?session=${encodeURIComponent(id)}`);
    sidebar(false);
    notice();
    renderSessions();
    renderMessages();
    updateComposer();
    void refreshMemories().catch(() => {});
    try { await refreshMessages(id, true); }
    catch (error) { if (state.active === id) notice(error.message); }
  }

  function newConversation() {
    finishSession(state.active);
    state.active = null;
    state.view += 1;
    state.messages = [];
    state.hasMore = false;
    state.remoteBusy = false;
    history.replaceState(null, "", location.pathname);
    sidebar(false);
    notice();
    $("chatInput").value = "";
    $("chatInput").style.height = "auto";
    renderSessions();
    renderMessages();
    updateComposer();
    $("chatInput").focus();
    void refreshMemories().catch(() => {});
  }

  async function send(retry = null) {
    const content = retry?.content || $("chatInput").value.trim();
    if (!content || !state.configured || state.pending.has(state.active) || state.remoteBusy || state.creating) return;
    let id = state.active;
    $("sendMessage").disabled = true;
    try {
      if (!id) {
        state.creating = true;
        const row = await api("/api/chat/sessions", { method: "POST", body: "{}" });
        id = row.id;
        state.active = id;
        state.view += 1;
        history.replaceState(null, "", `${location.pathname}?session=${id}`);
      }
    } catch (error) { notice(error.message); state.creating = false; updateComposer(); return; }
    state.creating = false;
    const pending = { content, requestId: retry?.requestId || crypto.randomUUID(), answer: "", controller: new AbortController() };
    state.pending.set(id, pending);
    state.retries.delete(id);
    $("chatInput").value = "";
    $("chatInput").style.height = "auto";
    notice();
    renderMessages();
    updateComposer();
    scrollBottom();
    let done = false;
    try {
      const response = await api(`/api/chat/sessions/${id}/messages`, { method: "POST", stream: true,
        signal: pending.controller.signal, body: JSON.stringify({ content, request_id: pending.requestId }) });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      function processEvent(frame) {
        const line = frame.split("\n").filter((part) => part.startsWith("data: ")).map((part) => part.slice(6)).join("\n");
        if (!line) return;
        const event = JSON.parse(line);
        if (event.type === "start") void refreshSessions().catch(() => {});
        if (event.type === "status" && state.active === id) notice(event.message);
        if (event.type === "context" && state.active === id) {
          notice();
          $("contextStatus").textContent = `本轮已提供 ${event.source_count} 项资料、${event.memory_count} 条记忆 · 查看详情`;
        }
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "done") done = true;
        if (event.type === "delta") {
          pending.answer += event.text;
          if (state.active === id) {
            const shouldScroll = nearBottom();
            const target = $("messageList").querySelector(".message.streaming .message-content");
            if (target) target.textContent = pending.answer;
            if (shouldScroll) scrollBottom();
          }
        }
      }
      try {
        while (true) {
          const part = await reader.read();
          buffer += decoder.decode(part.value || new Uint8Array(), { stream: !part.done }).replace(/\r\n/g, "\n");
          let boundary;
          while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            processEvent(frame);
          }
          if (part.done) break;
        }
      } finally { await reader.cancel().catch(() => {}); }
      if (!done) throw new Error("连接中断，请重试上一条消息。");
    } catch (error) {
      state.retries.set(id, { content, requestId: pending.requestId });
      if (state.active === id) notice(error.name === "AbortError" ? "已停止回复，可以重试或发送新消息。" : error.message);
    } finally {
      state.pending.delete(id);
      if (state.active === id) {
        try { await refreshMessages(id, true); } catch (_) { renderMessages(); }
      }
      updateComposer();
      void refreshSessions().catch(() => {});
      void refreshMemories().catch(() => {});
    }
  }

  function askAction({ title, description, initial, danger = false, maxLength = 80, confirmLabel }) {
    return new Promise((resolve) => {
      $("actionTitle").textContent = title;
      $("actionDescription").textContent = description || "";
      $("actionInput").hidden = initial === undefined;
      $("actionInput").value = initial || "";
      $("actionInput").maxLength = maxLength;
      $("actionInput").setAttribute("aria-label", title);
      $("actionInput").required = initial !== undefined;
      $("confirmAction").classList.toggle("danger", danger);
      $("confirmAction").textContent = confirmLabel || (danger ? "删除" : "保存");
      $("actionDialog").returnValue = "";
      $("actionForm").onsubmit = (event) => {
        event.preventDefault();
        resolve(initial === undefined ? true : $("actionInput").value.trim());
        $("actionDialog").close("confirm");
      };
      $("actionDialog").addEventListener("close", () => resolve($("actionDialog").returnValue === "confirm" ? (initial === undefined ? true : $("actionInput").value.trim()) : null), { once: true });
      $("actionDialog").showModal();
      if (initial !== undefined) $("actionInput").select();
    });
  }

  async function renameSession(row) {
    const title = await askAction({ title: "重命名对话", initial: row.title });
    if (!title) return;
    try { await api(`/api/chat/sessions/${row.id}`, { method: "PATCH", body: JSON.stringify({ title }) }); await refreshSessions(); }
    catch (error) { toast(error.message); }
  }

  async function deleteSession(row) {
    if (!await askAction({ title: "删除这个对话？", description: "聊天记录将被删除。已提取的长期记忆可在“我的记忆”中单独移除。", danger: true })) return;
    try {
      state.pending.get(row.id)?.controller.abort();
      const result = await api(`/api/chat/sessions/${row.id}`, { method: "DELETE" });
      state.retries.delete(row.id);
      if (state.active === row.id) { state.active = null; newConversation(); }
      await refreshSessions();
      toast(result.task.status === "completed" ? "对话及缓存清理完成，长期记忆保留" : "对话已移除，缓存清理已受理；长期记忆保留");
    } catch (error) { toast(error.message); }
  }

  function memoryTime(value) {
    return value ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "short", timeStyle: "short" }).format(new Date(value * 1000)) : "";
  }

  function memoryTab(tab) {
    state.memoryTab = tab;
    const panels = { sources: "memorySourcesPanel", memories: "memorySavedPanel", context: "memoryContextPanel" };
    for (const [key, id] of Object.entries(panels)) $(id).hidden = key !== tab;
    document.querySelectorAll("[data-memory-tab]").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.memoryTab === tab)));
  }

  function memoryDetails(key, label, text, expanded) {
    const details = document.createElement("details");
    details.dataset.memoryDetail = key;
    details.open = expanded.has(key);
    const summary = document.createElement("summary");
    summary.textContent = label;
    const content = document.createElement("pre");
    content.textContent = text;
    details.append(summary, content);
    return details;
  }

  function renderMemorySources(data, expanded) {
    const resume = data.resume || {};
    $("memoryResumeTitle").textContent = resume.file_name || "当前简历";
    $("memoryResumeStatus").textContent = [resume.message, resume.profile_error].filter(Boolean).join(" ") || "请重启更新后的后端服务，再刷新资料状态。";
    const sync = $("syncResumeMemory");
    sync.hidden = !resume.status || resume.status === "missing" || (resume.status === "ready" && resume.profile_status !== "failed");
    sync.disabled = resume.status === "reading";
    sync.textContent = resume.status === "reading" ? "正在读取…" : resume.profile_status === "failed" ? "重试资料提取" : resume.status === "failed" ? "重试读取" : "读取当前简历";
    $("memorySources").replaceChildren();
    for (const source of data.sources || []) {
      const card = document.createElement("article");
      card.className = "memory-source";
      const heading = document.createElement("div");
      heading.className = "memory-source-heading";
      const title = document.createElement("strong");
      title.textContent = source.title;
      const badge = document.createElement("span");
      badge.className = ["user_upload", "user_statement"].includes(source.kind) ? "memory-source-badge original" : "memory-source-badge";
      badge.textContent = source.kind === "user_upload" ? "用户上传原文" : source.kind === "user_statement" ? "用户填写 / 选择" : source.kind === "profile" ? "用户资料 · 可核对来源" : "历史分析 / 工作台资料";
      heading.append(title, badge);
      card.append(heading, memoryDetails(`source:${source.title}`, "查看实际载入的内容", source.preview, expanded));
      $("memorySources").append(card);
    }
    if (!(data.sources || []).length) $("memorySources").textContent = "暂未载入可用的背景资料。上传的简历读取完成后，会在这里显示原文。";
  }

  function renderMemoryContext(trace, expanded) {
    $("memoryContext").replaceChildren();
    const description = document.createElement("p");
    description.className = "memory-context-note";
    description.textContent = !state.active ? "选择一个对话后，可查看该对话最近一轮提供给模型的信息。"
      : !trace ? "这个对话还没有新的上下文记录。更新后发送一条消息，即可在这里查看。"
      : `${memoryTime(trace.created_at)} · ${trace.status === "prepared" ? "本轮已准备上下文，模型请求尚未确认发出" : "本轮已提供以下信息"}。这表示提供给了模型，不代表每条信息都影响了回答。`;
    $("memoryContext").append(description);
    if (!trace) return;
    const sources = document.createElement("div");
    sources.className = "memory-context-sources";
    for (const title of trace.source_titles || []) {
      const chip = document.createElement("span");
      chip.textContent = title;
      sources.append(chip);
    }
    const info = document.createElement("p");
    info.className = "memory-context-note";
    info.textContent = `${trace.retrieval === "vector" ? "本轮有语义检索命中" : "本轮直接选取已保存记忆"} · 提供 ${trace.recent_messages} 条近期消息${trace.has_conversation_summary ? "和一份会话摘要" : ""}`;
    $("memoryContext").append(sources, info);
    if (trace.resume_source?.file_name) {
      const resume = document.createElement("p");
      resume.className = "memory-context-note";
      resume.textContent = `本轮简历：${trace.resume_source.file_name} · 当时已读取 ${trace.resume_source.character_count || 0} 字`;
      $("memoryContext").append(resume);
    }
    if (trace.memories?.length) {
      $("memoryContext").append(memoryDetails("context:memories", `查看本轮提供的 ${trace.memories.length} 条记忆`, trace.memories.map((row) => `${row.value}${row.matched_by_vector ? "（语义检索命中）" : ""}`).join("\n\n"), expanded));
    }
  }

  async function refreshMemories() {
    const sessionId = state.active, view = state.view;
    const data = await api(`/api/chat/memories${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`);
    if (sessionId !== state.active || view !== state.view) return;
    const active = data.items.filter((row) => row.status === "active");
    $("memoryCount").textContent = active.length;
    $("headerMemoryLabel").textContent = `资料 ${(data.sources || []).length} · 记忆 ${active.length}`;
    $("headerMemory").dataset.indexState = data.index?.state || "pending";
    if (!state.pending.has(state.active)) $("contextStatus").textContent = data.context
      ? `最近一轮${data.context.status === "prepared" ? "已准备" : "已提供"} ${(data.context.source_titles || []).length} 项资料、${data.context.memories.length} 条记忆 · 查看详情`
      : "查看助手当前了解的资料与记忆";
    if (!$("memoryDialog").open) return;
    const expanded = new Set([...$("memoryDialog").querySelectorAll("details[open][data-memory-detail]")].map((node) => node.dataset.memoryDetail));
    $("memoryMetrics").innerHTML = `<div><span>长期记忆</span><strong>${active.length}<small> 条</small></strong></div><div><span>已载入资料</span><strong>${(data.sources || []).length}<small> 项</small></strong></div><div><span>${data.context?.status === "prepared" ? "本轮准备记忆" : "本轮提供记忆"}</span><strong>${data.context?.memories.length || 0}<small> 条</small></strong></div>`;
    const index = data.index || { state: "pending", message: "后端状态尚未更新，请重启服务后刷新。" };
    $("memoryIndexStatus").dataset.state = index.state;
    $("memoryIndexStatus").textContent = `${index.state === "ready" ? "语义检索正常" : index.state === "degraded" ? "语义检索已降级" : "语义检索待就绪"} · ${index.message} ${index.state === "ready" ? `已同步 ${index.indexed}/${index.total} 条记忆。` : "当前简历与已保存记忆仍可直接使用。"}`;
    renderMemorySources(data, expanded);
    $("resumeSourceEnabled").checked = Boolean(data.controls?.resume_enabled ?? true);
    $("workspaceSourceEnabled").checked = Boolean(data.controls?.workspace_enabled ?? true);
    const cleanup = data.cleanup || [];
    const pendingCleanup = cleanup.filter((task) => task.status !== "completed");
    $("memoryCleanupStatus").textContent = pendingCleanup.length
      ? `有 ${data.cleanup_pending_count ?? pendingCleanup.length} 项清理尚未完成，相关记忆已停止使用。${pendingCleanup.some((task) => task.error_code === "LegacyCachePending") ? "部分旧缓存等待原有效期结束，后台会继续核对。" : pendingCleanup.some((task) => task.status === "retrying") ? "部分存储暂不可用，后台会继续重试。" : "后台正在处理。"}`
      : cleanup.length ? "当前应用内的清理任务已完成。外部备份、日志和独立资料不在清理范围内。" : "";
    renderMemoryContext(data.context, expanded);
    memoryTab(state.memoryTab);
    const labels = { fact: "职业事实", preference: "职业偏好", communication: "交流偏好" };
    const keys = { education: "教育背景", graduation: "毕业时间", major: "专业", experience: "经历", skill: "技能", target_city: "目标城市", target_role: "目标方向", salary: "薪资期待", work_style: "工作方式", industry: "行业", availability: "到岗安排", constraint: "个人限制", answer_length: "回答长度", answer_structure: "回答结构", language: "语言", tone: "语气", explanation_style: "解释方式" };
    const jobLabel = (jobs = {}) => jobs.running ? "正在整理" : jobs.error ? "整理失败，可以重试" : jobs.queued ? "等待整理" : jobs.done ? "已完成" : "暂无待处理内容";
    $("memoryJobStatus").textContent = data.jobs.memory || data.jobs.summary
      ? `长期记忆：${jobLabel(data.jobs.memory)}；会话摘要：${jobLabel(data.jobs.summary)}。`
      : jobLabel(data.jobs);
    $("memoryList").replaceChildren();
    for (const row of data.items) {
      const item = document.createElement("article");
      item.className = `memory-item ${row.status}`;
      const body = document.createElement("div");
      const label = document.createElement("small");
      label.textContent = `${labels[row.kind] || "用户记忆"} · ${keys[row.key] || row.key}${row.status === "conflict" ? " · 存在冲突，暂不作为已确认事实" : ""}`;
      const value = document.createElement("p");
      value.textContent = row.value;
      body.append(label, value);
      const source = document.createElement("p");
      source.className = "memory-evidence-label";
      const provided = data.context?.memories.some((item) => item.id === row.id);
      source.textContent = `来源：${row.source_title || "用户对话"} · ${memoryTime(row.updated_at)}${provided ? " · 已列入本轮上下文" : ""}`;
      body.append(source);
      if (row.evidence?.length) body.append(memoryDetails(`memory:${row.id}`, "核对用户原话", row.evidence.map((item) => item.quote).join("\n\n"), expanded));
      item.append(body, memoryActions(row));
      $("memoryList").append(item);
    }
    if (!data.items.length) {
      const empty = document.createElement("p");
      empty.className = "memory-empty";
      empty.textContent = "还没有需要长期保存的记忆。\n在交流中明确告诉我你的偏好，就从这里开始。";
      $("memoryList").append(empty);
    }
    $("consolidateMemory").disabled = !state.active || state.pending.has(state.active);
  }

  function memoryActions(row) {
    const actions = document.createElement("div");
    actions.className = "memory-actions";
    for (const [mode, label] of [["edit", "纠正"], ["forget", "忘记"], ["purge", "彻底删除"]]) {
      if (mode === "edit" && !["active", "conflict"].includes(row.status)) continue;
      const button = document.createElement("button");
      button.textContent = label;
      button.setAttribute("aria-label", `${label}记忆：${row.value}`);
      button.addEventListener("click", async () => {
        const description = mode === "edit" ? "新内容会成为当前值，旧聊天上下文将失效。"
          : mode === "forget" ? "清除这条聊天记忆的值、证据和旧上下文，原聊天记录保留。旧资料引用会暂停。若要恢复记忆，请明确说“请重新记住……”。"
          : "还将删除已记录的证据消息、对应回复和由这些消息提取的其他记忆，无法恢复。独立简历和已有报告保留。";
        const result = await askAction({ title: `${label}这条记忆？`, description, confirmLabel: label,
          ...(mode === "edit" ? { initial: row.value, maxLength: 1000 } : { danger: true }) });
        if (!result) return;
        button.disabled = true;
        try {
          for (const pending of state.pending.values()) pending.controller.abort();
          await api(`/api/chat/memories/${encodeURIComponent(row.id)}${mode === "edit" ? "" : `?mode=${mode}`}`, {
            method: mode === "edit" ? "PATCH" : "DELETE", ...(mode === "edit" ? { body: JSON.stringify({ value: result }) } : {}) });
          state.retries.clear();
          await refreshMemories();
          if (mode === "purge") { await refreshSessions(); if (state.active) await refreshMessages(state.active, false); }
          toast(mode === "edit" ? "记忆已纠正，缓存与索引更新已受理" : "相关记忆已停止使用，清理已受理，可在此查看进度");
        } catch (error) { toast(error.message); button.disabled = false; }
      });
      actions.append(button);
    }
    return actions;
  }

  function openMemories() {
    $("memoryDialog").showModal();
    void refreshMemories().catch((error) => toast(error.message));
    clearInterval(memoryTimer);
    memoryTimer = setInterval(() => { if ($("memoryDialog").open) void refreshMemories().catch(() => {}); }, 5000);
  }

  $("chatForm").addEventListener("submit", (event) => { event.preventDefault(); void send(); });
  $("chatInput").addEventListener("input", () => { $("chatInput").style.height = "auto"; $("chatInput").style.height = `${Math.min($("chatInput").scrollHeight, 180)}px`; updateComposer(); });
  $("chatInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send(); } });
  $("newChat").addEventListener("click", newConversation);
  $("sessionSearch").addEventListener("input", renderSessions);
  $("stopReply").addEventListener("click", () => state.pending.get(state.active)?.controller.abort());
  $("retryMessage").addEventListener("click", () => void send(state.retries.get(state.active)));
  $("toggleSidebar").addEventListener("click", () => sidebar(!$("chatSidebar").classList.contains("open")));
  $("sidebarScrim").addEventListener("click", () => sidebar(false));
  $("openMemory").addEventListener("click", openMemories);
  $("headerMemory").addEventListener("click", openMemories);
  $("contextStatus").addEventListener("click", () => { state.memoryTab = "context"; openMemories(); });
  document.querySelectorAll("[data-memory-tab]").forEach((button) => button.addEventListener("click", () => memoryTab(button.dataset.memoryTab)));
  $("syncResumeMemory").addEventListener("click", async () => {
    $("syncResumeMemory").disabled = true;
    try { await api("/api/chat/sources/resume/sync", { method: "POST" }); toast("已安排读取当前简历"); await refreshMemories(); }
    catch (error) { toast(error.message); $("syncResumeMemory").disabled = false; }
  });
  $("closeMemory").addEventListener("click", () => $("memoryDialog").close());
  $("memoryDialog").addEventListener("close", () => clearInterval(memoryTimer));
  $("clearChatData").addEventListener("click", async () => {
    if (!await askAction({ title: "清除全部 Chat 数据？", description: "删除当前账号的聊天、摘要、记忆与快照，并后台清理缓存和向量。独立简历及已有报告保留，旧资料引用会暂停。", danger: true })) return;
    try {
      for (const pending of state.pending.values()) pending.controller.abort();
      await api("/api/chat/chat-data", { method: "DELETE" });
      state.active = null;
      state.sessions = [];
      state.retries.clear();
      newConversation();
      await refreshSessions();
      await refreshMemories();
      toast("Chat 数据已停止使用，全部清理请求已受理");
    } catch (error) { toast(error.message); }
  });
  for (const id of ["resumeSourceEnabled", "workspaceSourceEnabled"]) {
    $(id).addEventListener("change", async () => {
      const desired = { resume_enabled: $("resumeSourceEnabled").checked, workspace_enabled: $("workspaceSourceEnabled").checked };
      if ($(id).checked && !await askAction({ title: "重新引用独立资料？", description: "这些资料可能仍包含你已从聊天记忆中删除的信息。启用后，助手可以再次使用这些独立来源。" })) { $(id).checked = false; return; }
      try {
        await api("/api/chat/source-settings", { method: "PATCH", body: JSON.stringify(desired) });
        await refreshMemories();
      } catch (error) { toast(error.message); await refreshMemories(); }
    });
  }
  $("cancelAction").addEventListener("click", () => $("actionDialog").close("cancel"));
  $("consolidateMemory").addEventListener("click", async () => {
    if (!state.active) return;
    $("consolidateMemory").disabled = true;
    try { await api(`/api/chat/sessions/${state.active}/finish`, { method: "POST" }); toast("已安排整理，稍后会显示有价值的新记忆"); await refreshMemories(); }
    catch (error) { toast(error.message); $("consolidateMemory").disabled = false; }
  });
  $("loadEarlier").addEventListener("click", async () => {
    const id = state.active, view = state.view;
    if (!id || !state.messages.length) return;
    $("loadEarlier").disabled = true;
    try {
      const before = state.messages[0].seq;
      const data = await api(`/api/chat/sessions/${id}/messages?before=${before}`);
      if (view !== state.view) return;
      const oldHeight = $("conversationScroll").scrollHeight;
      state.messages = [...data.items, ...state.messages];
      state.hasMore = data.has_more;
      renderMessages();
      $("conversationScroll").scrollTop += $("conversationScroll").scrollHeight - oldHeight;
    } catch (error) { toast(error.message); }
    finally { $("loadEarlier").disabled = false; }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { $("chatInput").value = button.dataset.prompt; $("chatInput").dispatchEvent(new Event("input")); $("chatInput").focus(); }));
  window.addEventListener("pagehide", () => { finishSession(state.active, true); for (const pending of state.pending.values()) pending.controller.abort(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") sidebar(false); });
  setInterval(() => { if (state.active && state.remoteBusy && !document.hidden) void refreshMessages(state.active, nearBottom()).catch(() => {}); }, 3000);

  async function init() {
    try {
      await refreshSessions();
      const requested = new URLSearchParams(location.search).get("session");
      if (requested && state.sessions.some((row) => row.id === requested)) await openSession(requested);
      await refreshMemories();
      $("chatInput").focus();
    } catch (error) { notice(error.message); }
  }
  void init();
})();
