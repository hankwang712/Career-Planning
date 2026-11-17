const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({console, escHtml: String, clampPercent: Number});
for (const name of ["app-resume-panels.js", "app-resume-report.js", "app-resume-blocks.js", "app-resume-judge.js", "app-profile-capability.js"]) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static", name), "utf8"), context);
}
assert.equal(vm.runInContext("normalizeResumeScore(null)", context), null);
assert.equal(vm.runInContext("resumeScoreLabel(null)", context), "待验证");
assert.equal(vm.runInContext("resumeScoreLabel(0)", context), "0%");
assert.equal(vm.runInContext("averageResumeScores([null, 0, 50])", context), 25);
assert.equal(vm.runInContext("resumeEvidenceScore({confidence:.99, capability_scores:{matching:50}})", context), 50);
assert.equal(vm.runInContext("resumeJudgeStoryScore({experiences:Array(99)}, {})", context), null);
assert.equal(vm.runInContext("resumeJudgeOverallScore({}, {}, 'job_match', [])", context), null);
const html = vm.runInContext("renderResumeReportHeroMetrics({capability_scores:{matching:0}}, {}, 'job_match', [])", context);
assert(html.includes("0%") && html.includes("待验证"));
assert(!html.includes("null%") && !html.includes("undefined%"));
const metrics = vm.runInContext("resumeSixMetricCardsHtml({profile:{capability_scores:{matching:null}}, matcher:{}})", context);
assert(metrics.includes("待验证") && !metrics.includes(">null<"));
assert(!vm.runInContext("resume6htmlRadarChartHtml()", context).includes("<polygon"));
const risk = vm.runInContext("resumeJudgeRiskRadarHtml({}, {}, 'job_match', {}, null, [])", context);
assert(risk.includes("待验证") && !risk.includes("100%"));
assert.equal(vm.runInContext("(() => {const bag={execution:[]}; addCapabilitySignal(bag,'execution',null,'resume'); return bag.execution.length;})()", context), 0);
console.log("Resume evidence score checks passed");
