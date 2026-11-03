(() => {
  "use strict";
  const HOURS = [2, 4, 6, 8, 10, 15, 20];
  const WEEKS = [2, 4, 8, 12];
  const DECISIONS = { recommended: "建议优先考虑", conditional: "满足条件后考虑", not_recommended: "暂不建议", insufficient_information: "信息不足" };
  let current = null;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  function stepsFor(snapshot) {
    const review = snapshot.review;
    const steps = review.targets.length > 1 ? [{ kind: "target" }] : [];
    const cards = snapshot.review_ui?.questions || [];
    const seen = new Set();
    for (const card of cards) {
      if (!(review.questions?.[card.agent] || []).includes(card.question)) continue;
      const key = `${card.agent}:${card.question}`;
      if (seen.has(key)) continue;
      seen.add(key);
      steps.push({ kind: "question", card, answerKey: key });
      if (seen.size === 2) break;
    }
    steps.push({ kind: "planning" });
    return steps;
  }

  function todayInShanghai() {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  function responseFor(snapshot, values, today = todayInShanghai()) {
    const targets = snapshot.review.targets;
    const target = values.target || (targets.length === 1 ? targets[0].target_id : "");
    if (!targets.some((item) => item.target_id === target)) throw new Error("请选择本次规划的目标方向。");
    const hours = Number(values.hours), weeks = Number(values.weeks);
    if (!HOURS.includes(hours) || !WEEKS.includes(weeks)) throw new Error("请选择每周准备时间和计划周期。");
    const answers = {};
    for (const step of stepsFor(snapshot)) {
      if (step.kind !== "question") continue;
      const answer = String(values.answers[step.answerKey] || "").trim();
      if (!answer) continue;
      (answers[step.card.agent] ||= []).push({ question: step.card.question, answer });
    }
    const deadline = new Date(`${today}T00:00:00Z`);
    deadline.setUTCDate(deadline.getUTCDate() + weeks * 7 - 1);
    return { target_id: target, answers, constraints: { weekly_hours: hours, start_date: today,
      deadline: deadline.toISOString().slice(0, 10), budget: null, completed_tasks: [],
      student_stage: ["exploration", "employment"].includes(values.student_stage) ? values.student_stage : "unspecified" } };
  }

  function close() {
    if (current?.dialog?.open) current.dialog.close();
  }

  function reset() {
    close();
    current?.dialog?.remove();
    current = null;
  }

  function autoOpen(active) {
    if (active && current && !current.autoOpened) {
      current.autoOpened = true;
      open();
    }
  }

  function open() {
    if (!current || current.dialog.open) return;
    renderStep();
    current.dialog.showModal();
  }

  function showError(message) {
    const error = current?.dialog?.querySelector("[data-review-error]");
    if (error) { error.hidden = false; error.textContent = message; }
  }

  function capture() {
    const form = current.dialog.querySelector("form");
    const values = new FormData(form);
    const step = current.steps[current.index];
    if (step.kind === "question") current.values.answers[step.answerKey] = String(values.get("answer") || "");
    if (step.kind === "target") current.values.target = String(values.get("target") || "");
    if (step.kind === "planning") {
      current.values.hours = values.get("hours");
      current.values.weeks = values.get("weeks");
      current.values.student_stage = values.get("student_stage");
    }
  }

  function radio(name, value, label, selected) {
    return `<label class="report-review-choice"><input type="radio" name="${name}" value="${esc(value)}" ${selected === value ? "checked" : ""} ${name === "target" ? "required" : ""}><span>${esc(label)}</span></label>`;
  }

  function renderStep() {
    const { snapshot, values, index, steps, dialog } = current;
    const step = steps[index];
    let title, body;
    if (step.kind === "target") {
      title = "这次想优先推进哪个方向？";
      body = snapshot.review.targets.map((target) => {
        const assessment = (snapshot.review.assessments || []).find((item) => item.target_id === target.target_id);
        return radio("target", target.target_id, `${target.title} · ${DECISIONS[assessment?.decision] || "待确认"}`, values.target);
      }).join("");
    } else if (step.kind === "question") {
      title = step.card.question;
      const answer = values.answers[step.answerKey] || "";
      body = '<p class="report-review-note">只补充你尚未说明的信息，也可以跳过。</p>';
      body += step.card.choices?.length
        ? step.card.choices.map((choice) => radio("answer", choice, choice, answer)).join("")
        : `<textarea name="answer" rows="3" maxlength="600" placeholder="简单补充即可，可留空">${esc(answer)}</textarea>`;
    } else {
      title = "最后，安排一个可执行的准备计划";
      const target = snapshot.review.targets.find((item) => item.target_id === values.target) || snapshot.review.targets[0];
      body = `<div class="report-review-recorded"><strong>${esc(target.title)}</strong><p>${esc(snapshot.review_ui?.availability_summary || "实习安排尚未确定，将按未知信息保留。")}</p></div>
        <p class="report-review-note">下面选择用于学习、完善简历和求职的时间，与每周实习天数分开计算。</p>
        <label class="report-review-field">当前学习阶段<select name="student_stage"><option value="unspecified">暂不说明</option><option value="exploration" ${values.student_stage === "exploration" ? "selected" : ""}>大一、大二 · 职业探索</option><option value="employment" ${values.student_stage === "employment" ? "selected" : ""}>大三、大四及研究生 · 就业准备</option></select></label>
        <label class="report-review-field">每周可用于准备的时间<select name="hours" required><option value="">请选择</option>${HOURS.map((hours) => `<option value="${hours}" ${Number(values.hours) === hours ? "selected" : ""}>${hours} 小时 / 周</option>`).join("")}</select></label>
        <label class="report-review-field">近期任务安排多久？<select name="weeks" required><option value="">请选择</option>${WEEKS.map((weeks) => `<option value="${weeks}" ${Number(values.weeks) === weeks ? "selected" : ""}>${weeks} 周</option>`).join("")}</select></label><p class="report-review-note">另外生成1—3个月、3—12个月和1—3年的成长路线，后续按阶段复核调整。</p>`;
    }
    dialog.innerHTML = `<form class="report-review-card">
      <div class="report-review-top"><span>确认 ${index + 1} / ${steps.length}</span><button type="button" class="report-review-close" data-action="close" aria-label="关闭，稍后继续">×</button></div>
      <progress max="${steps.length}" value="${index + 1}" aria-label="确认进度"></progress>
      <h3 id="reportReviewCardTitle" tabindex="-1">${esc(title)}</h3><div class="report-review-content">${body}</div>
      <p class="report-review-error" data-review-error role="alert" hidden></p>
      <div class="report-review-footer"><button type="button" class="report-launch-secondary" data-action="back" ${index ? "" : "hidden"}>上一步</button>
      ${step.kind === "question" ? '<button type="button" class="report-review-skip" data-action="skip">暂时跳过</button>' : ""}
      <button type="submit" class="report-launch-primary">${step.kind === "planning" ? "确认并生成计划" : "下一步"}</button></div>
    </form>`;
    dialog.querySelector("form").addEventListener("submit", advance);
    if (dialog.open) dialog.querySelector("h3").focus();
  }

  async function advance(event) {
    event.preventDefault();
    if (!current || current.busy || !current.dialog.querySelector("form").reportValidity()) return;
    capture();
    if (current.index < current.steps.length - 1) {
      current.index += 1;
      renderStep();
      return;
    }
    const owner = current;
    try {
      const response = responseFor(owner.snapshot, owner.values);
      owner.busy = true;
      owner.dialog.querySelectorAll("button, select, textarea, input").forEach((el) => { el.disabled = true; });
      owner.dialog.querySelector('[type="submit"]').textContent = "正在提交…";
      const success = await owner.onSubmit(response);
      if (success && current === owner) close();
    } catch (error) {
      if (current === owner) showError(error.message || "提交失败，请重试。");
    } finally {
      owner.busy = false;
      if (current === owner) {
        owner.dialog.querySelectorAll("button, select, textarea, input").forEach((el) => { el.disabled = false; });
        owner.dialog.querySelector('[type="submit"]').textContent = "确认并生成计划";
      }
    }
  }

  function mount(container, snapshot, { onSubmit, active = false }) {
    reset();
    const count = stepsFor(snapshot).filter((step) => step.kind === "question").length;
    container.innerHTML = `<div class="report-review-overview"><div><span class="report-input-step">03 · 确认与计划</span><h3>分析已完成，确认后继续</h3><p>${count ? `只需补充 ${count} 项尚未明确的信息，可逐条跳过。` : "无需额外补充，选择准备时间即可继续。"}</p></div><button type="button" class="report-launch-primary" data-review-open>继续确认</button></div>
      <details class="report-review-analysis"><summary>查看职业决策依据</summary><p>${esc(snapshot.review.summary || "")}</p>${(snapshot.review.assessments || []).map((item) => `<p>${esc(item.conclusion)}</p>`).join("")}</details>`;
    const dialog = document.createElement("dialog");
    dialog.className = "report-review-dialog";
    dialog.setAttribute("aria-labelledby", "reportReviewCardTitle");
    container.append(dialog);
    current = { snapshot, dialog, steps: stepsFor(snapshot), index: 0, autoOpened: false, busy: false, onSubmit,
      values: { target: snapshot.review.targets.length === 1 ? snapshot.review.targets[0].target_id : "", answers: {}, hours: "", weeks: "" } };
    dialog.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (!action || !current || current.busy) return;
      capture();
      if (action === "close") return close();
      if (action === "back") current.index = Math.max(0, current.index - 1);
      if (action === "skip") {
        current.values.answers[current.steps[current.index].answerKey] = "";
        current.index += 1;
      }
      renderStep();
    });
    dialog.addEventListener("cancel", (event) => { if (current?.busy) event.preventDefault(); else capture(); });
    container.querySelector("[data-review-open]").addEventListener("click", open);
    autoOpen(active);
  }

  window.ReportReview = { mount, open, close, reset, autoOpen, showError, stepsFor, responseFor };
})();
