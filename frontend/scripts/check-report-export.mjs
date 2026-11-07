import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../static/workspace-restoration.js", import.meta.url), "utf8");
const helpers = source.slice(source.indexOf("  async function downloadCareerReport("), source.indexOf("  const REPORT_EDITOR_LAYOUT_KEY"));
const exportFunction = source.slice(source.indexOf("  async function exportReport("), source.indexOf("  function normalizeAvatarState("));

function environment() {
  const state = { requests: [], downloads: [], notices: [], urls: [], revoked: [], timers: [], owner: "alice", beforeReply: null };
  const buttons = new Map(["userCenterExportPdfBtn", "userCenterExportDocxBtn"].map((id) => [id, { disabled: false }]));
  let reply = { ok: true, status: 200, type: "application/pdf", data: "%PDF-1.7\nsynthetic", message: "" };
  class DownloadURL extends URL {
    static createObjectURL(blob) { assert.ok(blob.size); state.urls.push("blob:export"); return "blob:export"; }
    static revokeObjectURL(url) { state.revoked.push(url); }
  }
  const runtime = { exportPending: false, editorSource: { source_type: "formal_report", report_id: "report-current" } };
  const context = vm.createContext({
    URL: DownloadURL, Blob, reportRuntime: runtime,
    window: { location: { origin: "https://offline.invalid" }, appState: {
      careerReport: { report_document: {}, meta: { report_id: "report-current" } }
    } },
    document: {
      getElementById: (id) => buttons.get(id),
      body: { appendChild(anchor) { anchor.attached = true; } },
      createElement() { return { click() { assert.ok(this.attached); state.downloads.push({ href: this.href, name: this.download, target: this.target }); }, remove() {} }; }
    },
    currentUser: () => ({ username: state.owner }), resolveUrl: (value) => value,
    toast: (...args) => state.notices.push(args), setTimeout: (callback) => state.timers.push(callback),
    async fetch(url, options) {
      state.requests.push({ url: new URL(url), options });
      await state.beforeReply?.();
      const value = { ...reply };
      return { ok: value.ok, status: value.status, redirected: value.redirected || false,
        headers: { get: (key) => key === "Content-Type" ? value.type : value.disposition || "attachment; filename=report.pdf" },
        async json() { if (!value.message) throw new Error("not JSON"); return { message: value.message }; },
        async blob() { return new Blob([value.data], { type: value.type }); }
      };
    }
  });
  vm.runInContext(helpers + exportFunction, context);
  return { state, buttons, context, runtime, reply: (values) => { reply = { ...reply, ...values }; } };
}

{
  const { state, context, buttons, reply } = environment();
  reply({ disposition: "attachment; filename=report.pdf; filename*=UTF-8''%E8%81%8C%E4%B8%9A%E6%8A%A5%E5%91%8A.pdf" });
  assert.equal(await context.exportReport("pdf"), true);
  assert.equal(state.requests[0].url.searchParams.get("report_id"), "report-current");
  assert.equal(state.requests[0].options.credentials, "include");
  assert.equal(state.downloads[0].name, "职业报告.pdf");
  assert.equal(state.downloads[0].href, "blob:export");
  assert.equal(state.downloads[0].target, undefined);
  assert.ok([...buttons.values()].every((button) => !button.disabled));
  state.timers.forEach((callback) => callback());
  assert.deepEqual(state.revoked, ["blob:export"]);
}

for (const failure of [
  { ok: false, status: 500, type: "application/json", message: "无法分页，请精简内容" },
  { ok: false, status: 401, type: "application/json", message: "请重新登录" },
  { ok: true, status: 200, type: "text/html", data: "<html>login</html>" },
  { ok: true, status: 200, type: "application/pdf", data: "not a PDF" },
  { ok: true, status: 200, type: "application/pdf", data: "" }
]) {
  const { state, context, runtime, buttons, reply } = environment();
  reply(failure);
  assert.equal(await context.exportReport("pdf"), false);
  assert.equal(state.downloads.length, 0);
  assert.equal(state.notices.at(-1)[0], "导出失败");
  if (failure.message) assert.equal(state.notices.at(-1)[1], failure.message);
  assert.equal(runtime.exportPending, false);
  assert.ok([...buttons.values()].every((button) => !button.disabled));
  reply({ ok: true, status: 200, type: "application/pdf", data: "%PDF-1.7\nretry", message: "" });
  assert.equal(await context.exportReport("pdf"), true);
}

{
  const { state, context, runtime } = environment();
  let release;
  state.beforeReply = () => new Promise((resolve) => { release = resolve; });
  const first = context.exportReport("pdf");
  assert.equal(runtime.exportPending, true);
  assert.equal(await context.exportReport("pdf"), false);
  assert.equal(state.requests.length, 1);
  release();
  assert.equal(await first, true);
}

{
  const { state, context } = environment();
  state.beforeReply = () => { state.owner = "bob"; };
  assert.equal(await context.exportReport("pdf"), false);
  assert.equal(state.downloads.length, 0);
}

{
  const { state, context, runtime } = environment();
  runtime.editorSource = { source_type: "snapshot", report_id: "report-history", snapshot_id: "edit-1" };
  assert.equal(await context.exportCareerReportSource("pdf"), true);
  assert.equal(state.requests[0].url.searchParams.get("report_id"), "report-history");
  assert.equal(state.requests[0].url.searchParams.get("snapshot_id"), "edit-1");
}

console.log("Report export: validated downloads, visible errors, retry, duplicate guard, account changes and saved snapshots PASS");
