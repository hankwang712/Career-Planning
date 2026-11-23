(() => {
  const form = document.getElementById("systemModelSettings");
  const fieldset = form.querySelector("fieldset");
  const submit = document.getElementById("settingsSave");
  const result = document.getElementById("settingsResult");
  const pending = new Map();
  const probeButtons = [...form.querySelectorAll("[data-test-group]")];
  const probeRequests = new WeakMap();
  const revealed = new Map();
  const eyeButtons = [...form.querySelectorAll("[data-reveal]")];
  let revealEpoch = 0;
  const canEdit = form.dataset.canEdit === "true";
  const cards = [...form.querySelectorAll("[data-settings-group]")];
  const groupLinks = [...document.querySelectorAll("[data-group-link]")];
  const required = [...form.querySelectorAll("[data-required-field]")];
  const optional = [...form.querySelectorAll("[data-optional-field]")];
  let fields = {};

  function tally(nodes) {
    return nodes.filter(node => fields[node.dataset.settingKey]?.configured).length;
  }

  function updateProgress() {
    const requiredReady = tally(required);
    const optionalReady = tally(optional);
    const missing = required.filter(node => !fields[node.dataset.settingKey]?.configured);
    const configured = requiredReady + optionalReady;
    const total = required.length + optional.length;
    const percent = total ? Math.round(configured * 100 / total) : 0;
    const readiness = document.getElementById("settingsReadiness");
    readiness.dataset.status = missing.length ? "partial" : "ready";
    readiness.textContent = missing.length ? "必填待补齐" : "必填已配齐";
    readiness.hidden = false;
    const progress = document.getElementById("settingsProgress");
    progress.max = required.length;
    progress.value = requiredReady;
    document.getElementById("settingsProgressText").textContent = `对话模型已配置 ${requiredReady}/${required.length}`;
    document.getElementById("settingsRequiredCount").textContent = `${requiredReady}/${required.length}`;
    document.getElementById("settingsOptionalCount").textContent = `${optionalReady}/${optional.length}`;
    const completion = document.getElementById("settingsCompletion");
    completion.style.setProperty("--sc-completion", `${percent}%`);
    completion.dataset.status = configured === total ? "ready" : "partial";
    document.getElementById("settingsCompletionPercent").textContent = `${percent}%`;
    document.getElementById("settingsCompletionCount").textContent = `${configured}/${total} 项已配置`;
    document.getElementById("settingsMissing").textContent = missing.length
      ? "还缺必填项：" + missing.map(node => node.dataset.label).join("、") : "";
    for (const card of cards) {
      const nodes = [...card.querySelectorAll("[data-setting-key]")];
      const configured = tally(nodes);
      const count = `${configured}/${nodes.length}`;
      const state = configured === nodes.length ? "ready" : configured ? "partial" : "empty";
      const link = groupLinks.find(item => item.dataset.groupLink === card.dataset.settingsGroup);
      link.dataset.status = state;
      link.querySelector("[data-nav-count]").textContent = count;
      const status = card.querySelector("[data-group-count]");
      status.dataset.status = state;
      status.textContent = `${configured ? "已配置" : "未配置"} ${count}`;
    }
  }

  function fieldStatus(status, label, state) {
    status.textContent = label;
    status.dataset.status = state;
  }

  function setEye(button, open) {
    const label = button.getAttribute("aria-label").replace(/^(显示|隐藏)/, open ? "隐藏" : "显示");
    button.setAttribute("aria-pressed", String(open));
    button.setAttribute("aria-label", label);
    button.title = label;
  }

  function hideSecret(button) {
    const key = button.dataset.reveal;
    const input = form.elements.namedItem(key);
    if (revealed.delete(key) && !pending.has(key)) input.value = "";
    input.type = "password";
    setEye(button, false);
  }

  function hideAllSecrets() {
    revealEpoch += 1;
    eyeButtons.forEach(hideSecret);
  }

  eyeButtons.forEach(button => {
    button.addEventListener("click", async () => {
      const key = button.dataset.reveal;
      const input = form.elements.namedItem(key);
      if (button.getAttribute("aria-pressed") === "true") {
        hideSecret(button);
        return;
      }
      if (!input.value && !fields[key]?.configured) {
        result.textContent = "此密钥尚未配置。";
        return;
      }
      if (!input.value) {
        const epoch = revealEpoch;
        button.disabled = true;
        try {
          const response = await fetch("/api/system-settings/reveal", {
            method: "POST", cache: "no-store",
            headers: { ...await window.CareerAuth.headers(), "Content-Type": "application/json" },
            body: JSON.stringify({ key })
          });
          const data = await response.json();
          if (epoch !== revealEpoch) return;
          if (!response.ok) throw new Error(data.message || "暂时无法显示密钥。");
          if (!input.value && !pending.has(key)) {
            revealed.set(key, data.value);
            input.value = data.value;
          }
        } catch (error) {
          if (epoch === revealEpoch) result.textContent = error.message;
          return;
        } finally {
          button.disabled = false;
        }
      }
      if (input.value) {
        result.textContent = "";
        input.type = "text";
        setEye(button, true);
      }
    });
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) hideAllSecrets(); });
  window.addEventListener("pagehide", hideAllSecrets);

  function renderField(key) {
    const field = fields[key];
    const input = form.elements.namedItem(key);
    const status = document.getElementById("state-" + key);
    if (!status) return;
    fieldStatus(status, field.configured ? "已配置" : "未配置", field.configured ? "ready" : "empty");
    const readout = status.closest("[data-setting-key]").querySelector("[data-readout]");
    if (readout) readout.textContent = field.value || (field.configured ? "配置已就绪" : "—");
    if (input) {
      input.value = field.value || "";
      input.placeholder = input.type === "password" && field.configured ? "已配置 · 输入新密钥可替换" : "";
    }
  }

  async function load(method = "GET") {
    hideAllSecrets();
    if (method === "PATCH") probeButtons.forEach(resetProbe);
    fieldset.disabled = true;
    if (submit) submit.disabled = true;
    result.textContent = method === "GET" ? "正在读取配置…" : "正在保存…";
    try {
      const options = { method, cache: "no-store" };
      if (method === "PATCH") {
        options.headers = { ...await window.CareerAuth.headers(), "Content-Type": "application/json" };
        options.body = JSON.stringify(Object.fromEntries(pending));
      }
      const response = await fetch(canEdit && method === "PATCH" ? "/api/system-settings/models" : "/api/system-settings/status", options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "暂时无法读取或保存配置。");
      fields = data.fields;
      pending.clear();
      Object.keys(fields).forEach(renderField);
      updateProgress();
      result.textContent = method === "PATCH" ? "配置已保存。" : "";
    } catch (error) {
      result.textContent = error.message;
    } finally {
      fieldset.disabled = !Object.keys(fields).length;
      if (submit) submit.disabled = !pending.size;
    }
  }

  form.addEventListener("input", event => {
    const { name, value } = event.target;
    if (!fields[name]) return;
    const original = event.target.hasAttribute("data-secret-input") ? revealed.get(name) || "" : fields[name].value || "";
    const clean = value.trim();
    if (clean && clean !== original) pending.set(name, clean);
    else pending.delete(name);
    const status = document.getElementById("state-" + name);
    if (pending.has(name)) {
      fieldStatus(status, "待保存", "pending");
      resetProbe(event.target.closest("[data-settings-group]").querySelector("[data-test-group]"));
    } else {
      fieldStatus(status, fields[name].configured ? "已配置" : "未配置", fields[name].configured ? "ready" : "empty");
    }
    if (submit) updateSaveState();
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (pending.size) void load("PATCH");
  });
  function updateSaveState() {
    submit.disabled = !pending.size;
    result.textContent = pending.size ? "有未保存的修改" : "";
  }
  function renderProbe(button, state, message = "", duration = null) {
    const actions = button.parentElement;
    const line = document.getElementById(button.getAttribute("aria-describedby"));
    const label = button.querySelector("[data-probe-label]");
    const success = actions.querySelector(".sc-probe-success");
    actions.dataset.state = state;
    button.disabled = state === "running";
    label.textContent = state === "running" ? "正在测试…" :
      (state === "success" || state === "error") ? "重新测试" : "测试连通性";
    success.querySelector("[data-probe-result]").textContent = state === "success"
      ? `已连通${Number.isFinite(duration) ? ` · ${duration} ms` : ""}` : "";
    success.hidden = state !== "success";
    line.dataset.state = state;
    line.textContent = message;
  }

  function resetProbe(button) {
    if (!button) return;
    probeRequests.get(button)?.abort();
    probeRequests.delete(button);
    renderProbe(button, "idle");
  }

  probeButtons.forEach(button => {
    button.addEventListener("click", async () => {
      if (pending.size) {
        document.getElementById(button.getAttribute("aria-describedby")).textContent = "请先保存修改，再测试连通性。";
        return;
      }
      const request = new AbortController();
      probeRequests.set(button, request);
      renderProbe(button, "running");
      try {
        const response = await fetch("/api/system-settings/test/" + button.dataset.testGroup, {
          method: "POST", headers: await window.CareerAuth.headers(), cache: "no-store", signal: request.signal
        });
        const data = await response.json();
        if (request.signal.aborted) return;
        if (response.ok) renderProbe(button, "success", "", data.duration_ms);
        else renderProbe(button, "error", data.message || "连通性测试失败。");
      } catch {
        if (!request.signal.aborted) renderProbe(button, "error", "暂时无法完成测试，请稍后重试。");
      } finally {
        if (probeRequests.get(button) === request) probeRequests.delete(button);
      }
    });
  });
  function activate(id) {
    groupLinks.forEach(link => {
      if (link.dataset.groupLink === id) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }
  function syncHash() {
    const card = cards.find(item => "#" + item.id === location.hash);
    if (!card) return;
    card.querySelector("details").open = true;
    activate(card.dataset.settingsGroup);
  }
  groupLinks.forEach(link => link.addEventListener("click", () => {
    const card = cards.find(item => "#" + item.id === link.hash);
    card.querySelector("details").open = true;
    activate(link.dataset.groupLink);
  }));
  cards.forEach(card => card.querySelector("summary").addEventListener("click", () => activate(card.dataset.settingsGroup)));
  window.addEventListener("hashchange", syncHash);
  syncHash();
  void load();

  /* 一键环境体检 + SQLite 备份 + LLM Token 审计 */
  const diagList = document.getElementById("diagList");
  const diagSummaryPill = document.getElementById("diagSummaryPill");
  const navDiagCount = document.getElementById("navDiagCount");
  const navUsageCount = document.getElementById("navUsageCount");
  const usageSummary = document.getElementById("usageSummary");
  const runDiagBtn = document.getElementById("runDiagBtn");
  const runBackupBtn = document.getElementById("runBackupBtn");

  function renderDiagnostics(data) {
    if (diagList && Array.isArray(data.checks)) {
      const okCount = data.checks.filter(c => c.ok).length;
      const total = data.checks.length;
      if (diagSummaryPill) {
        diagSummaryPill.textContent = okCount === total ? `全部通过 ${okCount}/${total}` : `已就绪 ${okCount}/${total}`;
        diagSummaryPill.dataset.state = okCount === total ? "ok" : "warn";
      }
      if (navDiagCount) navDiagCount.textContent = `${okCount}/${total}`;
      diagList.replaceChildren(...data.checks.map(item => {
        const row = document.createElement("div");
        row.className = "sc-diag-item";
        const copy = document.createElement("div");
        copy.className = "sc-diag-copy";
        const title = document.createElement("strong");
        title.textContent = item.label;
        const detail = document.createElement("span");
        detail.textContent = item.detail;
        copy.append(title, detail);
        if (!item.ok && item.fix) {
          const fix = document.createElement("div");
          fix.className = "sc-diag-fix";
          fix.textContent = `修复建议：${item.fix}`;
          copy.append(fix);
        }
        const pill = document.createElement("span");
        pill.className = "sc-diag-pill";
        pill.dataset.ok = item.ok ? "1" : "0";
        pill.textContent = item.ok ? "正常" : "待处理";
        row.append(copy, pill);
        return row;
      }));
    }
    if (usageSummary && data.usage) {
      const t = data.usage.today || {};
      const w = data.usage.window || {};
      if (navUsageCount) navUsageCount.textContent = `${t.calls || 0}次`;
      usageSummary.replaceChildren();
      const kpis = document.createElement("div");
      kpis.className = "sc-usage-kpis";
      for (const [label, val] of [
        ["今日调用次数", `${t.calls || 0} 次`],
        ["今日 Token 消耗", `${(t.total_tokens || 0).toLocaleString()}`],
        ["今日平均耗时", t.avg_latency_ms ? `${(t.avg_latency_ms / 1000).toFixed(2)}s` : "—"],
        ["近 7 日总 Token", `${(w.total_tokens || 0).toLocaleString()}`],
      ]) {
        const box = document.createElement("div");
        box.className = "sc-usage-kpi";
        const s1 = document.createElement("span");
        s1.textContent = label;
        const s2 = document.createElement("strong");
        s2.textContent = val;
        box.append(s1, s2);
        kpis.append(box);
      }
      usageSummary.append(kpis);
      const feats = data.usage.by_feature || [];
      if (feats.length) {
        const row = document.createElement("div");
        row.className = "sc-usage-feats";
        for (const f of feats.slice(0, 6)) {
          const chip = document.createElement("span");
          chip.className = "sc-usage-feat-chip";
          const b = document.createElement("b");
          b.textContent = `${f.calls}次 / ${f.total_tokens.toLocaleString()} tok`;
          chip.append(document.createTextNode(`${f.feature} `), b);
          row.append(chip);
        }
        usageSummary.append(row);
      }
    }
  }

  async function loadDiagnostics() {
    if (!diagList) return;
    try {
      const res = await fetch("/api/system-settings/diagnostics", { cache: "no-store" });
      if (res.ok) renderDiagnostics(await res.json());
    } catch { /* ignore */ }
  }
  if (runDiagBtn) {
    runDiagBtn.addEventListener("click", async () => {
      runDiagBtn.disabled = true;
      runDiagBtn.textContent = "体检中…";
      await loadDiagnostics();
      runDiagBtn.disabled = false;
      runDiagBtn.textContent = "一键体检";
    });
  }
  if (runBackupBtn) {
    runBackupBtn.addEventListener("click", async () => {
      runBackupBtn.disabled = true;
      runBackupBtn.textContent = "备份中…";
      try {
        const res = await fetch("/api/system-settings/backup", {
          method: "POST", headers: await window.CareerAuth.headers(), cache: "no-store"
        });
        const data = await res.json();
        result.textContent = data.result?.ok ? `已创建备份：${data.result.latest}（共 ${data.result.count} 份）` : "备份失败";
        await loadDiagnostics();
      } catch {
        result.textContent = "备份请求失败。";
      } finally {
        runBackupBtn.disabled = false;
        runBackupBtn.textContent = "立即备份";
      }
    });
  }
  void loadDiagnostics();

  /* 常用厂商一键预设（填充 Base URL & Model，不改动已有 API Key） */
  const presetBar = document.getElementById("chatProviderPresets");
  if (presetBar) {
    presetBar.addEventListener("click", event => {
      const btn = event.target.closest("[data-preset-url]");
      if (!btn) return;
      const urlInput = form.elements.namedItem("AI_CHAT_BASE_URL");
      const modelInput = form.elements.namedItem("AI_CHAT_MODEL");
      if (urlInput) {
        urlInput.value = btn.dataset.presetUrl || "";
        urlInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (modelInput) {
        modelInput.value = btn.dataset.presetModel || "";
        modelInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      result.textContent = `已填入 ${btn.textContent} 预设，请核对 API Key 后点击保存。`;
    });
  }

  /* 底部悬浮「未保存变更条」 */
  const dirtyBar = document.createElement("div");
  dirtyBar.className = "sc-dirty-bar";
  dirtyBar.hidden = true;
  const dirtyText = document.createElement("span");
  const discardBtn = document.createElement("button");
  discardBtn.type = "button"; discardBtn.className = "sc-dirty-discard"; discardBtn.textContent = "放弃修改";
  const quickSaveBtn = document.createElement("button");
  quickSaveBtn.type = "button"; quickSaveBtn.className = "sc-dirty-save"; quickSaveBtn.textContent = "保存配置";
  dirtyBar.append(dirtyText, discardBtn, quickSaveBtn);
  document.body.append(dirtyBar);

  function syncDirtyBar() {
    const count = pending.size;
    dirtyBar.hidden = count === 0;
    if (count > 0) dirtyText.textContent = `有 ${count} 项未保存修改`;
  }
  form.addEventListener("input", () => setTimeout(syncDirtyBar, 0));
  form.addEventListener("submit", () => setTimeout(syncDirtyBar, 400));
  discardBtn.addEventListener("click", () => { pending.clear(); void load(); syncDirtyBar(); });
  quickSaveBtn.addEventListener("click", () => { if (submit && !submit.disabled) submit.click(); });
})();
