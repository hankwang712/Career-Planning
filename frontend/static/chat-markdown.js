/* Chat Markdown: all source text is escaped; generated tags are explicit. */
((root, factory) => {
  const renderer = factory();
  if (typeof module === "object" && module.exports) module.exports = renderer;
  if (root) root.CareerMarkdown = renderer;
})(typeof window === "undefined" ? null : window, () => {
  "use strict";
  const escape = (value) => String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);

  function inline(value, depth = 0) {
    if (depth > 4) return escape(value);
    const tokens = /(`+)([^`\n]*?)\1|\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*/g;
    let html = "", cursor = 0;
    for (const match of value.matchAll(tokens)) {
      html += escape(value.slice(cursor, match.index));
      if (match[1]) html += `<code>${escape(match[2])}</code>`;
      else if (match[3]) {
        const href = match[4];
        html += /^(https?:\/\/|#)/i.test(href)
          ? `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">${inline(match[3], depth + 1)}</a>`
          : escape(match[0]);
      } else if (match[5] || match[6]) html += `<strong>${inline(match[5] || match[6], depth + 1)}</strong>`;
      else html += `<em>${inline(match[7], depth + 1)}</em>`;
      cursor = match.index + match[0].length;
    }
    return html + escape(value.slice(cursor));
  }

  function cells(line) {
    let source = line.trim();
    if (!source.includes("|")) return null;
    if (source.startsWith("|")) source = source.slice(1);
    if (source.endsWith("|") && !source.endsWith("\\|")) source = source.slice(0, -1);
    const result = [];
    let cell = "", fence = 0;
    for (let i = 0; i < source.length; i++) {
      const char = source[i];
      if (char === "\\" && source[i + 1] === "|") { cell += "|"; i++; }
      else if (char === "`") {
        let end = i + 1;
        while (source[end] === "`") end++;
        const length = end - i;
        if (!fence) fence = length;
        else if (length === fence) fence = 0;
        cell += source.slice(i, end);
        i = end - 1;
      } else if (char === "|" && !fence) { result.push(cell.trim()); cell = ""; }
      else cell += char;
    }
    result.push(cell.trim());
    return result.length > 1 ? result : null;
  }

  function tableAt(lines, index) {
    const header = cells(lines[index]);
    if (!header) return null;
    let separator = index + 1;
    while (separator < lines.length && !lines[separator].trim()) separator++;
    const rules = separator < lines.length ? cells(lines[separator]) : null;
    return rules && rules.length === header.length && rules.every((rule) => /^:?-{3,}:?$/.test(rule))
      ? { header, rules, separator } : null;
  }

  const fenceAt = (line) => /^\s{0,3}(`{3,}|~{3,})([^`~]*)$/.exec(line);
  const listAt = (line) => /^(\s*)([-+*]|\d+[.)、])\s+(.+)$/.exec(line);
  const ruleAt = (line) => /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);

  function render(value) {
    const lines = String(value).replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let index = 0;
    const blockAt = (i) => fenceAt(lines[i]) || /^#{1,6}\s|^\s*>/.test(lines[i]) || listAt(lines[i]) || ruleAt(lines[i]) || tableAt(lines, i);
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index++; continue; }
      const fence = fenceAt(line);
      if (fence) {
        const content = [];
        const closing = new RegExp(`^\\s{0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
        index++;
        while (index < lines.length && !closing.test(lines[index])) content.push(lines[index++]);
        if (index < lines.length) index++;
        const language = /^[a-z0-9_+-]+$/i.test(fence[2].trim()) ? fence[2].trim() : "";
        output.push(`<pre><code${language ? ` class="language-${escape(language)}"` : ""}>${escape(content.join("\n"))}</code></pre>`);
        continue;
      }
      const table = tableAt(lines, index);
      if (table) {
        const aligns = table.rules.map((rule) => rule.startsWith(":") && rule.endsWith(":") ? "center" : rule.endsWith(":") ? "right" : "left");
        const row = (values, tag) => `<tr>${table.header.map((_, column) => `<${tag} class="align-${aligns[column]}"${tag === "th" ? ' scope="col"' : ""}>${inline(values[column] || "")}</${tag}>`).join("")}</tr>`;
        const rows = [];
        index = table.separator + 1;
        while (index < lines.length) {
          let next = index;
          // Tolerate model output with blank lines between table rows.
          while (next < lines.length && !lines[next].trim()) next++;
          if (next >= lines.length || fenceAt(lines[next])) break;
          const values = cells(lines[next]);
          if (!values) break;
          if (values.length > table.header.length) values.splice(table.header.length - 1, values.length, values.slice(table.header.length - 1).join(" | "));
          rows.push(row(values, "td"));
          index = next + 1;
        }
        output.push(`<div class="message-table" role="region" aria-label="回答表格，可横向滚动" tabindex="0"><table><thead>${row(table.header, "th")}</thead><tbody>${rows.join("")}</tbody></table></div>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      if (heading) {
        const level = Math.min(heading[1].length + 1, 6);
        output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        index++;
        continue;
      }
      if (ruleAt(line)) { output.push("<hr>"); index++; continue; }
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, ""));
        output.push(`<blockquote>${quote.map((text) => inline(text)).join("<br>")}</blockquote>`);
        continue;
      }
      const list = listAt(line);
      if (list) {
        const ordered = /^\d/.test(list[2]);
        const tag = ordered ? "ol" : "ul";
        const items = [];
        while (index < lines.length) {
          const item = listAt(lines[index]);
          if (!item || /^\d/.test(item[2]) !== ordered) break;
          items.push(`<li>${inline(item[3])}</li>`);
          index++;
        }
        const start = ordered && parseInt(list[2], 10) !== 1 ? ` start="${parseInt(list[2], 10)}"` : "";
        output.push(`<${tag}${start}>${items.join("")}</${tag}>`);
        continue;
      }
      const paragraph = [line];
      index++;
      while (index < lines.length && lines[index].trim() && !blockAt(index)) paragraph.push(lines[index++]);
      output.push(`<p>${paragraph.map((text) => inline(text)).join("<br>")}</p>`);
    }
    return output.join("");
  }
  return { render };
});
