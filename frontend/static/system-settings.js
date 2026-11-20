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
    const ready = tally(required);
    const missing = required.filter(node => !fields[node.dataset.settingKey]?.configured);
    const available = required.length;
    document.getElementById("settingsProgress").value = ready;
    document.getElementById("settingsProgressText").textContent = `对话模型已配置 ${ready}/${available}`;
    document.getElementById("settingsRequiredCount").textContent = `${ready}/${available}`;
    document.getElementById("settingsOptionalCount").textContent = `${tally(optional)}/${optional.length}`;
    document.getElementById("settingsMissing").textContent = missing.length
      ? "还缺必填项：" + missing.map(node => node.dataset.label).join("、") : "";
    const bar = document.getElementById("settingsOverviewBar");
    bar.style.width = `${100 * ready / available}%`;
    bar.dataset.status = missing.length ? "partial" : "ready";
    for (const card of cards) {
      const nodes = [...card.querySelectorAll("[data-setting-key]")];
      const configured = tally(nodes);
      const count = `${configured}/${nodes.length}`;
      const state = configured === nodes.length ? "ready" : configured ? "partial" : "empty";
      const link = groupLinks.find(item => item.dataset.groupLink === card.dataset.settingsGroup);
      link.dataset.status = state;
      link.querySelector("[data-nav-count]").textContent = count;
      card.querySelector("[data-group-count]").textContent = count + " 项已配置";
      const badge = card.querySelector("[data-group-ready]");
      if (badge) {
        badge.hidden = false;
        badge.dataset.status = missing.length ? "partial" : "ready";
        badge.textContent = missing.length ? `缺 ${missing.length} 项` : "✓ 已配齐";
      }
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
})();
