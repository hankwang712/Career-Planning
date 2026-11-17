// 回归测试：还没有报告的新账号打开工作台时，报告智能体控制台不能因空数据抛错。
// 不需要浏览器：从 app.js 截出函数，用桩对象在 vm 里执行。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const start = source.indexOf("function reportAgentConsoleResult(key)");
const end = source.indexOf("function reportAgentConsoleSummary(", start);
assert.ok(start > 0 && end > start, "找不到 reportAgentConsoleResult");

function load({ report, state, snapshot = null }) {
  const sandbox = {
    appState: { careerReport: report },
    reportAgentConsoleState: { snapshot },
    getReportRuntimeState: () => state,
  };
  vm.createContext(sandbox);
  vm.runInContext(source.slice(start, end), sandbox);
  return sandbox.reportAgentConsoleResult;
}

const keys = ["resume_analysis", "job_analysis", "recruitment_search", "career_decision", "review", "action_planning", "report_writer"];

// 没有报告、没有运行状态：每个节点都应返回 null，而不是抛 TypeError。
const empty = load({ report: null, state: null });
for (const key of keys) assert.equal(empty(key), null, `${key} 在无数据时应返回 null`);

// 有报告且与当前运行状态属于同一份：返回报告文档。
const document = { sections: [] };
const matching = load({ report: { meta: { report_id: "r1" }, report_document: document }, state: { report_id: "r1" } });
assert.equal(matching("report_writer"), document);

// 报告与当前运行状态不是同一份：不能把旧报告当成本次结果。
const stale = load({ report: { meta: { report_id: "old" }, report_document: document }, state: { report_id: "new" } });
assert.equal(stale("report_writer"), null);

// 已有快照时优先使用快照里的节点结果。
const snapshot = { results: { job_analysis: { data: { targets: [] } } } };
assert.equal(load({ report: null, state: null, snapshot })("job_analysis"), snapshot.results.job_analysis);

console.log("PASS: report agent console tolerates missing report/state and never shows a stale report.");
