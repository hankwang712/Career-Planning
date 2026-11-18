(() => {
  const form = document.getElementById("systemModelSettings");
  const fieldset = form.querySelector("fieldset");
  const submit = form.querySelector("[type=submit]");
  const result = document.getElementById("settingsResult");
  const pending = new Map();
  const canEdit = form.dataset.canEdit === "true";
  let fields = {};

  function updateProgress() {
    const ready = Object.keys(fields).filter(key => key.startsWith("AI_CHAT_") && fields[key].configured).length;
    document.getElementById("settingsProgress").value = ready;
    document.getElementById("settingsProgressText").textContent = `对话模型已配置 ${ready}/3`;
  }

  function renderField(key) {
    const field = fields[key];
    const input = form.elements.namedItem(key);
    const status = document.getElementById("state-" + key);
    if (!status) return;
    status.textContent = field.override ? "网页已配置" : field.configured ? "已配置" : "未配置";
    if (status.hasAttribute("data-deployment") && field.value) status.textContent = field.value;
    if (input) {
      input.value = field.value || "";
      input.placeholder = input.type === "password" && field.configured ? "已配置 · 输入新密钥可替换" : "";
      form.querySelector(`[data-reset="${key}"]`).hidden = !field.override;
    }
  }

  async function load(method = "GET") {
    fieldset.disabled = true;
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
    const { name, value, type } = event.target;
    if (!fields[name]) return;
    const original = fields[name].value || "";
    const clean = value.trim();
    if (clean && (type === "password" || clean !== original)) pending.set(name, clean);
    else pending.delete(name);
    document.getElementById("state-" + name).textContent = pending.has(name) ? "待保存" :
      fields[name].configured ? "已配置" : "未配置";
      if (submit) submit.disabled = !pending.size;
  });
  form.addEventListener("click", event => {
    const key = event.target.dataset.reset;
    if (!key || !fields[key]?.override) return;
    form.elements.namedItem(key).value = "";
    pending.set(key, "");
    document.getElementById("state-" + key).textContent = "保存后移除网页值";
    submit.disabled = false;
  });
  form.addEventListener("submit", event => {
    event.preventDefault();
    if (pending.size) void load("PATCH");
  });
  form.querySelectorAll("[data-test-group]").forEach(button => {
    button.addEventListener("click", async () => {
      const status = button.nextElementSibling;
      if (pending.size) {
        status.textContent = "请先保存修改，再测试连通性。";
        return;
      }
      button.disabled = true;
      status.textContent = "正在测试已保存的配置…";
      try {
        const response = await fetch("/api/system-settings/test/" + button.dataset.testGroup, {
          method: "POST", headers: await window.CareerAuth.headers(), cache: "no-store"
        });
        const data = await response.json();
        status.textContent = response.ok ? `${data.message}  ${data.duration_ms} ms` : data.message;
      } catch {
        status.textContent = "暂时无法完成测试，请稍后重试。";
      } finally {
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll(".ca-settings-layout nav a").forEach(link => {
    link.addEventListener("click", () => { document.querySelector(link.hash).open = true; });
  });
  const target = document.getElementById(location.hash.slice(1));
  if (target instanceof HTMLDetailsElement) target.open = true;
  void load();
})();
