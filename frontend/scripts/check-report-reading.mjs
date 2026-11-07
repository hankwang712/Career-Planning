import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../static/workspace-restoration.js", import.meta.url), "utf8");
const renderer = source.slice(source.indexOf("  function renderReportSections4("), source.indexOf("  function renderHistoricalNotice("));
const context = vm.createContext({
  REPORT_WORKSPACE_GROUPS: { trends: { sectionKeys: ["executive_summary", "personal_traits"], title: "Old generic heading" } },
  esc: (value) => String(value),
  renderMarkdownBasic: (value) => `<p>${value}</p>`,
  markdownForCareerReportReading: (value) => value
});
vm.runInContext(renderer, context);
const labels = {
  executive_summary: "核心结论", personal_traits: "个人经历与求职方向", matching_decision: "岗位适配与准备重点",
  gap_action_plan: "近期行动安排", development_path: "后续成长与调整", appendix: "参考依据与适用范围"
};
const sections = Object.fromEntries(Object.entries(labels).map(([key, label]) => [key, { label, markdown: `Narrative ${key}`, data: {} }]));
const bundle = { report_document: { reading_layout: "narrative-v1", section_order: Object.keys(labels), sections } };
const html = context.renderReportSections4(bundle, sections);
assert.equal((html.match(/<section id=/g) || []).length, 6);
for (const label of Object.values(labels)) assert.ok(html.includes(label));
for (const marker of ["结构化摘要", "综合能力分", "当前缺少明确证据", "cr4-match-circle", "cr4-module-empty"]) {
  assert.ok(!html.includes(marker));
}
const grouped = context.renderReportSections4(bundle, sections, { group: "trends" });
assert.equal((grouped.match(/<section id=/g) || []).length, 2);
assert.ok(!grouped.includes("cr4-group-stat"));
assert.ok(!grouped.includes("Old generic heading"));
assert.ok(grouped.includes("Narrative executive_summary"));
assert.ok(!grouped.includes("Narrative appendix"));
console.log("Report reading: narrative chapters, real labels, no empty structural summaries or generic module filler PASS");
