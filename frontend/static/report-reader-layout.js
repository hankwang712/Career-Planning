(function () {
  "use strict";
  const typographyKey = "career-report-typography-v1";
  const defaults = { title: 28, h2: 22, h3: 18, h4: 16, body: 14 };
  let typography = {};
  try { typography = JSON.parse(localStorage.getItem(typographyKey) || "{}"); } catch (_) {}
  typography = Object.fromEntries(Object.entries(defaults).map(([key, value]) =>
    [key, Number.isFinite(typography?.[key]) && typography[key] >= 10 && typography[key] <= 48 ? typography[key] : value]));
  function applyTypography() {
    Object.entries(typography).forEach(([key, value]) => document.documentElement.style.setProperty(`--report-font-${key}`, `${value}px`));
    document.querySelectorAll("[data-report-font]").forEach(input => { input.value = typography[input.dataset.reportFont]; });
  }
  function typographyControls() {
    return `<details class="cr-reader-typography"><summary>报告字号</summary><div class="cr-reader-typography-fields">${Object.entries({ title: "报告标题", h2: "一级标题", h3: "二级标题", h4: "三级标题", body: "正文" }).map(([key, label]) =>
      `<label>${label}<input type="number" min="10" max="48" step="1" value="${typography[key]}" data-report-font="${key}" aria-label="${label}字号（像素）"><span>px</span></label>`).join("")}<button type="button" data-report-font-reset>恢复默认</button></div></details>`;
  }
  document.addEventListener("change", event => {
    const key = event.target.dataset?.reportFont;
    if (!Object.hasOwn(defaults, key)) return;
    const value = Number(event.target.value);
    if (Number.isInteger(value) && value >= 10 && value <= 48) {
      typography[key] = value;
      try { localStorage.setItem(typographyKey, JSON.stringify(typography)); } catch (_) {}
    }
    applyTypography();
  });
  document.addEventListener("click", event => {
    if (!event.target.closest("[data-report-font-reset]")) return;
    typography = { ...defaults };
    try { localStorage.removeItem(typographyKey); } catch (_) {}
    applyTypography();
  });
  applyTypography();
  function shortHeading(value, limit = 38) {
    const chars = Array.from(String(value).trim().replace(/\s+/g, " "));
    const pairs = { "（": "）", "(": ")", "“": "”", "「": "」", "《": "》" };
    const stack = [];
    let safe = 0;
    for (let index = 0; index < chars.length; index++) {
      const char = chars[index];
      if (pairs[char]) stack.push(pairs[char]);
      else if (stack.length && stack[stack.length - 1] === char) stack.pop();
      if (!stack.length) {
        if ("：:，,。；;".includes(char)) return index <= limit ? chars.slice(0, index).join("") : chars.slice(0, safe).join("") + "…";
        if (index < limit) safe = index + 1;
      }
      if (index >= limit) return chars.slice(0, safe || limit).join("") + "…";
    }
    return chars.join("");
  }
  function numberMarkdown(markdown) {
    const counts = [0, 0, 0];
    let fence = null;
    return String(markdown || "").split(/\r?\n/).map(line => {
      const marker = line.match(/^\s*(`{3,}|~{3,})/);
      if (marker) { const token = marker[1][0]; fence = fence === token ? null : fence === null ? token : fence; }
      const match = !fence && line.match(/^(#{2,4})\s+(.+)$/);
      if (!match) return line;
      const level = match[1].length - 2;
      counts[level]++;
      counts.fill(0, level + 1);
      const title = match[2].replace(/^\d{1,2}(?:\.\d{1,2})*[.、．]?\s+/, "");
      return `${match[1]} ${counts.slice(0, level + 1).map(n => n || 1).join(".")} ${title}`;
    }).join("\n");
  }
  function prepare(markdown) {
    const pending = [];
    const hasIndependentWork = String(markdown || "").includes("独立开发");
    const parts = String(markdown || "").split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g).map(part => {
      if (/^(?:```|~~~)/.test(part)) return part;
      return part.replace(/(^###\s+(?:\d{1,2}(?:\.\d{1,2})*[.、]?\s+)?优先修改(?:顺序)?\s*\n)([\s\S]*?)(?=^#{1,3}\s|(?![\s\S]))/gm, (whole, heading, body) => {
        if (/^####\s/m.test(body)) return whole;
        const blocks = [];
        body.trim().split(/\n\s*\n/).forEach(paragraph => {
          if (!paragraph.trim()) return;
          if (paragraph.trim().startsWith("仍需核实的材料：")) pending.push(paragraph.trim());
          else if (/^\s*(?:\d+\.\s|[-*+]\s|>)/.test(paragraph)) blocks.push(paragraph);
          else {
            const pieces = paragraph.trim().split(/[，；。]\s*完成标准[为是：:]/);
            const action = hasIndependentWork ? pieces[0].replace(/(?:所有|全部|[两二三四五六七八九十]+段)经历的个人分工/g, "团队经历的个人分工") : pieces[0];
            const title = shortHeading(action);
            blocks.push(`#### ${title}`);
            const detail = action.startsWith(title) ? action.slice(title.length).replace(/^[：:，,。；; ]+/, "") : action;
            if (detail && !/^(?:便于|以便|从而)/.test(detail)) blocks.push(detail);
            if (pieces.length > 1) blocks.push("**验收要点：**" + pieces.slice(1).join("完成标准").replace(/^[：: ]+/, ""));
          }
        });
        return heading + "\n" + blocks.join("\n\n") + "\n\n";
      });
    });
    let text = parts.join("");
    if (pending.length) text = text.trimEnd() + "\n\n### 待补材料备查\n\n" + pending.join("\n\n");
    return numberMarkdown(text);
  }
  // Enhance only HTML produced by the escaped Markdown renderer, never model-provided raw HTML.
  function enhance(html) {
    const host = document.createElement("div");
    host.innerHTML = html;
    const output = document.createElement("div");
    output.className = "cr-reader-layout";
    let chapter = output;
    let group = null;
    let mode = "";
    const labelKinds = [
      [/^问题[：:]/, "problem"],
      [/^(?:改进方式|突出建议|这项优势还没有表达充分)[：:]/, "improve"],
      [/^(?:基于已有事实的改写|改写示例)[：:]/, "rewrite"],
      [/^(?:还需补充|待确认|后续仍需确认|进入条件|复核与调整)[：:]/, "pending"],
      [/^(?:交付物|完成标准|验收要点|对应要求|岗位要求|对照判断)[：:]/, "action"]
    ];
    Array.from(host.childNodes).forEach(node => {
      if (node.nodeType !== Node.ELEMENT_NODE) {
        (group || chapter).append(node);
        return;
      }
      const tag = node.tagName;
      const text = node.textContent.trim();
      if (tag === "P" && !text && !node.querySelector("img")) return;
      if (tag === "H1") {
        node.classList.add("cr-reader-document-title");
        output.append(node);
        return;
      }
      if (tag === "H2") {
        chapter = document.createElement("section");
        chapter.className = "cr-reader-chapter";
        mode = /核心结论/.test(text) ? "conclusion" : /简历/.test(text) ? "resume" : /招聘|岗位对照/.test(text) ? "jobs" : /成长|规划/.test(text) ? "plan" : "";
        chapter.dataset.kind = mode;
        group = null;
        chapter.append(node);
        output.append(chapter);
        return;
      }
      if (tag === "H3") {
        group = null;
        if (mode === "jobs" && !/岗位要求与你的经历对照/.test(text)) {
          group = document.createElement("article");
          group.className = "cr-reader-opportunity";
          chapter.append(group);
        }
      }
      if (tag === "H4") {
        group = document.createElement("article");
        group.className = mode === "plan" ? "cr-reader-task" : "cr-reader-issue";
        chapter.append(group);
      }
      if (mode === "plan" && tag === "OL" && node.children.length === 1) {
        group = document.createElement("article");
        group.className = "cr-reader-task";
        chapter.append(group);
      }
      if (tag === "P") {
        if (mode === "plan" && /^(?:进入条件|复核与调整|如果每周|暂缓的事项|后续仍需确认)/.test(text)) group = null;
        if (/^(?:原文依据|原文)[：:]/.test(text)) {
          const disclosure = document.createElement("details");
          disclosure.className = "cr-reader-evidence";
          const summary = document.createElement("summary");
          summary.textContent = "查看原文依据";
          const quote = document.createElement("blockquote");
          quote.append(...Array.from(node.childNodes));
          disclosure.append(summary, quote);
          (group || chapter).append(disclosure);
          return;
        }
        const kind = labelKinds.find(([pattern]) => pattern.test(text))?.[1];
        if (kind) node.classList.add("cr-reader-note", `cr-reader-note--${kind}`);
        if (mode === "conclusion") node.classList.add("cr-reader-conclusion");
        if (/^来源[：:]|^地点[：:]/.test(text)) node.classList.add("cr-reader-source-meta");
      }
      (group || chapter).append(node);
    });
    return typographyControls() + output.outerHTML;
  }
  window.CareerReportReader = { enhance, prepare, numberMarkdown, getTypography: () => ({ ...typography }) };
})();
