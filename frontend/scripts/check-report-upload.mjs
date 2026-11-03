import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
const functions = source.slice(source.indexOf("function renderReportResumePanel("), source.indexOf("async function submitCareerReportWorkflow("));

function environment() {
  const elements = new Map();
  const classes = new Map();
  const node = (id) => {
    if (!elements.has(id)) elements.set(id, {
      dataset: {}, textContent: "", disabled: false, value: "", title: "",
      setAttribute() {}, scrollIntoView() {}, click() {}, querySelectorAll() { return []; },
      classList: { toggle(name, enabled) { classes.set(`${id}:${name}`, enabled); }, remove() {} }
    });
    return elements.get(id);
  };
  const calls = [];
  const empty = () => ({ file_name: "", has_resume_source_text: false });
  const uploaded = { file_name: "stored_resume.docx", original_file_name: "resume.docx", document_id: "document-1", file_type: "docx", file_size: 300, has_resume_source_text: false };
  const state = { failUpload: false, failGeneration: false, cache: empty(), running: false, beforeGenerate: null };
  const context = vm.createContext({
    FormData, File, console,
    document: { getElementById: node }, window: { location: {} },
    reportResumeUiState: { pending: false, phase: "", error: "" }, reportGenerationStarting: false, reportGenerationError: "",
    resumeTaskState: { uploadInFlight: false, analyzeInFlight: false }, accountRequestEpoch: 0,
    userWorkspaceState: { scopedData: {}, scopedDataLoaded: {} },
    getResumeProfileFromCache: () => state.cache,
    getCareerReportStateSafe: () => ({ status: state.running ? "running" : "idle" }),
    isCareerReportRunningStatus: (value) => ["running", "queued"].includes(value),
    isAuthenticatedUser: () => true, emptyResumeProfile: empty,
    loadResumeProfile: async () => state.cache,
    renderResumeProfileSection: (data) => { state.cache = data; },
    refreshUnifiedExperience() {}, showToast() {},
    appState: { derivedProfile: {}, matchingRoles: [] }, deriveUnifiedProfile: () => ({}),
    buildCareerReportGenerationPayload: () => ({ workflow: { targets: ["Python developer"] } }),
    async submitCareerReportWorkflow() {
      calls.push("generate");
      state.beforeGenerate?.();
      if (state.failGeneration) throw new Error("Model not configured");
      state.running = true;
    },
    async requestJson(url, options) {
      if (url.endsWith("/upload")) {
        calls.push("upload");
        assert.ok(options.body instanceof FormData);
        assert.equal(options.body.get("file").name, "resume.docx");
        if (state.failUpload) throw new Error("Upload failed");
        return { data: { ...uploaded } };
      }
      throw new Error(`Unexpected request: ${url}`);
    }
  });
  vm.runInContext(functions, context);
  context.updateResumeActionButtons = () => context.renderReportResumePanel();
  context.renderReportWorkspace = () => context.renderReportResumePanel();
  context.showSection = () => {};
  return { context, state, node, calls, classes, uploaded };
}

{
  const { context, node, calls, state } = environment();
  context.renderReportResumePanel();
  assert.equal(node("reportLaunchBtn").disabled, true);
  await context.uploadReportResumeFile(new File(["sample"], "resume.docx"));
  assert.deepEqual(calls, ["upload"]);
  assert.equal(state.cache.has_resume_source_text, false);
  assert.equal(node("reportResumePanel").dataset.state, "ready");
  assert.equal(node("reportLaunchBtn").disabled, false);
  assert.equal(context.resumeTaskState.uploadInFlight, false);
  await context.startCareerReportGeneration();
  assert.deepEqual(calls, ["upload", "generate"]);
  assert.equal(node("reportLaunchBtn").disabled, true);
}

{
  const { context, state, node, calls } = environment();
  state.failUpload = true;
  await context.uploadReportResumeFile(new File(["sample"], "resume.docx"));
  assert.equal(state.cache.has_resume_source_text, false);
  assert.equal(node("reportResumePanel").dataset.state, "error");
  assert.equal(context.reportResumeUiState.pending, false);
  state.failUpload = false;
  await context.uploadReportResumeFile(new File(["sample"], "resume.docx"));
  assert.equal(state.cache.file_name, "stored_resume.docx");
  assert.deepEqual(calls, ["upload", "upload"]);
}

{
  const { context, state, uploaded, calls } = environment();
  state.cache = { ...uploaded };
  await context.startCareerReportGeneration();
  assert.deepEqual(calls, ["generate"]);
}

{
  const { context, state, calls } = environment();
  await context.uploadReportResumeFile(new File(["sample"], "resume.exe"));
  assert.deepEqual(calls, []);
  state.running = true;
  await context.uploadReportResumeFile(new File(["sample"], "resume.docx"));
  assert.deepEqual(calls, []);
}

{
  const { context, state, node, uploaded, calls } = environment();
  state.cache = { ...uploaded };
  state.failGeneration = true;
  state.beforeGenerate = () => {
    assert.equal(node("reportLaunchFeedback").hidden, false);
    assert.equal(node("reportLaunchFeedback").dataset.state, "starting");
    assert.equal(node("reportLaunchBtn").disabled, true);
  };
  await context.startCareerReportGeneration();
  assert.equal(node("reportLaunchFeedback").hidden, false);
  assert.equal(node("reportLaunchFeedback").dataset.state, "error");
  assert.ok(node("reportLaunchFeedback").textContent.includes("Model not configured"));
  assert.equal(node("reportStatusHint").textContent, "Model not configured");
  assert.equal(node("reportLaunchBtn").disabled, false);
  // Refreshing the upload panel must not hide a rejected launch request.
  await context.refreshReportResumePanel();
  assert.equal(node("reportLaunchFeedback").hidden, false);
  state.failGeneration = false;
  await context.startCareerReportGeneration();
  assert.equal(node("reportLaunchFeedback").hidden, true);
  assert.deepEqual(calls, ["generate", "generate"]);
}

console.log("Report upload: multipart upload, direct Agent handoff, task guards, launch feedback and retry PASS");
