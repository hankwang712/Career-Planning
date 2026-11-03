import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const popup = { classList: { add() {}, remove() {} } };
const context = vm.createContext({
  window: { setTimeout() { return 1; }, clearTimeout() {} }, console, Date,
  document: { readyState: "loading", addEventListener() {}, getElementById(id) { return id === "lpAchievementPopup" ? popup : null; } },
  localStorage: { setItem() {}, getItem() { return null; } }
});
const source = fs.readFileSync(new URL("../static/user-center-learning-path.js", import.meta.url), "utf8");
vm.runInContext(source.replace("  bindGlobalExports();", "  window.testPlan = { buildTrackerPlans, mergeTrackerPlans, milestoneNodes, normalizeStore, runtime, doCheckin };\n  bindGlobalExports();"), context);
const { buildTrackerPlans, mergeTrackerPlans, milestoneNodes, normalizeStore, runtime, doCheckin } = context.window.testPlan;
const tracker = { report_id: "report-one", plan_items: Array.from({ length: 7 }, (_, index) => ({
  id: `T0${index + 1}`, is_phase: true, is_action: true, phase_key: "short", phase: "核实硬条件",
  title: `完成准备事项 ${index + 1}`, objective: "交付成果", focus_points: ["C1"], signals: ["验收通过"],
  deliverable: "交付成果", acceptance_criteria: "验收通过", deadline: "2026-11-04", hours: 2
})) };
const plans = buildTrackerPlans(tracker);
assert.equal(plans.length, 7);
assert.ok(plans.every((plan) => plan.phase_key === "short" && plan.items.length === 1));
assert.equal(plans[0].items[0].id, "T01");
assert.ok(plans[0].items[0].note.includes("交付物：交付成果"));
assert.ok(plans[0].items[0].note.includes("验收：验收通过"));
assert.ok(!JSON.stringify(plans).includes("推进 C1"));
assert.equal(milestoneNodes("short", [plans[0]]).length, 1);
assert.equal(milestoneNodes("short", plans).length, 1);
assert.equal(milestoneNodes("short", []).length, 0);
assert.equal(normalizeStore({}).plans.length, 0);
const example = { title: "待识别 中期进阶", source: "manual", summary: "把方向判断逐步变成稳定输出和可复用能力。",
  items: [{ title: "围绕目标岗位补一轮作品集" }, { title: "完成一次周复盘并更新路径判断" }] };
assert.equal(normalizeStore({ plans: [example] }).plans.length, 0);
assert.equal(normalizeStore({ plans: [{ ...example, summary: "我自己修改的计划" }] }).plans.length, 1);
assert.equal(normalizeStore({ plans: [{ ...example, items: [{ ...example.items[0], done: true }, example.items[1]] }] }).plans.length, 1);

tracker.plan_items.push({ id: "roadmap-mid", is_phase: true, is_roadmap: true, phase_key: "mid", title: "完成可展示项目", objective: "完成可展示项目", entry_conditions: "完成基础练习" },
  { id: "roadmap-mid-1", parent_phase: "roadmap-mid", is_task: true, title: "实现测试与部署", deliverable: "仓库与测试报告", acceptance_criteria: "可独立部署", conditional: true });
tracker.checkpoints = [{ id: "review-mid", label: "中期阶段评估", due_date: "2027-11-03", summary: "无法演示时延长练习" }];
const withRoadmap = buildTrackerPlans(tracker);
const roadmap = withRoadmap.find((plan) => plan.id === "report_roadmap-mid");
assert.equal(roadmap.phase_key, "mid");
assert.equal(roadmap.items.length, 1);
assert.ok(roadmap.items[0].note.includes("进入条件：完成基础练习"));
assert.ok(withRoadmap.find((plan) => plan.items.some((item) => item.id === "checkpoint_review-mid")).phase_key === "mid");

plans[0].items[0].done = true;
assert.equal(mergeTrackerPlans({ plans }, tracker).plans[0].items[0].done, true);
const legacyPlans = structuredClone(plans);
legacyPlans[0].items[0].id = "T01_objective";
assert.equal(mergeTrackerPlans({ plans: legacyPlans }, tracker).plans[0].items[0].done, true);
assert.equal(mergeTrackerPlans({ plans }, { ...tracker, report_id: "report-two" }).plans[0].items[0].done, false);
runtime.store = normalizeStore({ plans });
const before = runtime.store.plans.flatMap((plan) => plan.items).filter((item) => item.done).length;
await doCheckin();
assert.equal(runtime.store.plans.flatMap((plan) => plan.items).filter((item) => item.done).length, before);
console.log("Learning plans: actual tasks, horizons, deliverables, reviews, report isolation and check-in progress PASS");
