(() => {
  const form = document.getElementById("systemModelSettings");
  const fieldset = form.querySelector("fieldset");
  const submit = form.querySelector("[type=submit]");
  const result = document.getElementById("settingsResult");
  const pending = new Map();
  let fields = {};

  function updateProgress() {
    const ready = Object.keys(fields).filter(key => key.startsWith("AI_CHAT_") && fields[key].configured).length;
    document.getElementById("settingsProgress").value = ready;
    document.getElementById("settingsProgressText").textContent = `对话模型已配置 ${ready}/3`;
  }

  function renderField(key) {
    const field = fields[key];
    const input = form.elements.namedItem(key);
    input.value = field.value || "";
    input.placeholder = input.type === "password" && field.configured ? "已配置 · 输入新密钥可替换" : "";
    document.getElementById("state-" + key).textContent = field.override ? "网页已配置" :
      field.configured ? "使用部署值或默认值" : "未配置";
    form.querySelector(`[data-reset="${key}"]`).hidden = !field.override;
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
      const response = await fetch("/api/system-settings/models", options);
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
      submit.disabled = !pending.size;
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
    submit.disabled = !pending.size;
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
  document.querySelectorAll(".ca-settings-layout nav a").forEach(link => {
    link.addEventListener("click", () => { document.querySelector(link.hash).open = true; });
  });
  const target = document.getElementById(location.hash.slice(1));
  if (target instanceof HTMLDetailsElement) target.open = true;
  void load();
})();
