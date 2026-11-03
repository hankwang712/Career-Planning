// Offline checks for the real card sequencing and continuation payload.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const context = vm.createContext({ window: {}, Intl, Date, console });
vm.runInContext(fs.readFileSync(new URL("../static/report-review.js", import.meta.url), "utf8"), context);
const { stepsFor, responseFor } = context.window.ReportReview;
const question = "是否接受较长的工作时间？";
const snapshot = {
  review: { targets: [{ target_id: "T1", title: "算法实习" }], questions: { career_decision: [question, "是否接受出差？", "是否接受异地？"] } },
  review_ui: { availability_summary: "随时到岗，每周可实习 5 天", questions: [
    { agent: "career_decision", question, choices: ["可以接受", "不接受"] },
    { agent: "career_decision", question: "是否接受出差？", choices: ["可以接受", "不接受"] },
    { agent: "career_decision", question: "是否接受异地？", choices: [] }
  ] }
};
const steps = stepsFor(snapshot);
assert.equal(steps.length, 3);
assert.equal(steps.at(-1).kind, "planning");
const values = { hours: "6", weeks: "4", answers: { [`career_decision:${question}`]: "不接受" } };
const response = responseFor(snapshot, values, "2026-10-29");
assert.equal(response.target_id, "T1");
assert.equal(response.answers.career_decision.length, 1);
assert.equal(response.answers.career_decision[0].question, question);
assert.equal(response.answers.career_decision[0].answer, "不接受");
assert.equal(response.constraints.weekly_hours, 6);
assert.equal(response.constraints.deadline, "2026-11-25");
assert.equal(response.constraints.budget, null);
assert.equal(Object.keys(response.constraints).includes("days_per_week"), false);
assert.equal(response.constraints.student_stage, "unspecified");
assert.equal(responseFor(snapshot, { ...values, student_stage: "exploration" }).constraints.student_stage, "exploration");
assert.equal(responseFor(snapshot, { ...values, student_stage: "employment" }).constraints.student_stage, "employment");

const skip = responseFor(snapshot, { hours: "2", weeks: "2", answers: {} }, "2026-12-28");
assert.equal(Object.keys(skip.answers).length, 0);
assert.equal(skip.constraints.deadline, "2027-01-10");
assert.throws(() => responseFor(snapshot, { ...values, hours: "40" }, "2026-10-29"));
assert.throws(() => responseFor(snapshot, { ...values, weeks: "100" }, "2026-10-29"));

const multi = structuredClone(snapshot);
multi.review.targets.push({ target_id: "T2", title: "后端实习" });
assert.equal(stepsFor(multi)[0].kind, "target");
assert.throws(() => responseFor(multi, values, "2026-10-29"));
assert.equal(responseFor(multi, { ...values, target: "T2" }, "2026-10-29").target_id, "T2");

const noQuestions = structuredClone(snapshot);
noQuestions.review_ui.questions = [];
assert.equal(stepsFor(noQuestions).length, 1);
const untrusted = structuredClone(snapshot);
untrusted.review_ui.questions = [{ agent: "career_decision", question: "invented question" }, snapshot.review_ui.questions[0], snapshot.review_ui.questions[0]];
assert.equal(stepsFor(untrusted).filter((step) => step.kind === "question").length, 1);

console.log("Report cards: at most two questions, optional skips, target choice, original question mapping, explicit preparation hours and dates PASS");
