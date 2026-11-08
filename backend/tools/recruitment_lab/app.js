"use strict";
const $ = (id) => document.getElementById(id);
let controller = null;
let lastRun = null;
let lastInput = null;
let timer = null;
let currentAction = "正在启动";
const toolRows = new Map();
const trace = [];
const candidateQueries = new Map();
const toolNames = { verify_recruitment_radar_candidates: "核验岗位初筛通过的候选原文", search_recruitment_radar: "从招聘汇总召回候选岗位" };

function element(tag, text, className = "") {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function link(text, url) {
  const node = element("a", text);
  try {
    const parsed = new URL(url);
    if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("invalid protocol");
    node.href = parsed.href;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
  } catch { node.removeAttribute("href"); }
  return node;
}
function errorMessage(message = "") {
  $("formError").textContent = message;
  $("formError").classList.toggle("hidden", !message);
}
function showVerification(state) {
  const node = $("verificationNotice");
  if (!node || !state) return;
  node.replaceChildren(element("strong", "需要你在浏览器中完成验证"),
    element("p", "验证页已保留在Chrome标签页中。请切换到该页手动完成验证，再回到这里重新搜索。"));
  if (state.url) node.append(link("打开验证页面 ↗", state.url));
  const retry = element("button", "已完成验证，重新搜索", "secondary");
  retry.type = "button";
  retry.addEventListener("click", () => {
    if (controller) return errorMessage("请等待本轮结束，再重新搜索。");
    if (lastInput) run(lastInput);
  });
  node.append(document.createTextNode(" "), retry);
  node.classList.remove("hidden");
}
function log(title, detail = "", seconds = 0) {
  const row = element("div", undefined, "log");
  const head = element("div", undefined, "log-head");
  head.append(element("span", title, "log-title"), element("span", `+${seconds.toFixed(1)}s`, "log-time"));
  row.append(head);
  if (detail) row.append(element("pre", detail));
  $("timeline").append(row);
  $("timeline").scrollTop = $("timeline").scrollHeight;
  return row;
}
async function refreshStatus() {
  $("refreshStatus").disabled = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("状态服务不可用");
    const state = await response.json();
    $("modelStatus").textContent = `模型 · ${state.model.name}`;
    $("modelStatus").className = `badge ${state.model.ready ? "ok" : "bad"}`;
    $("radarStatus").textContent = state.radar ? `招聘雷达 · ${state.radar.records} 条记录` : "招聘雷达 · 已接入";
    $("radarStatus").className = "badge ok";
    $("connectionMessage").textContent = state.model.ready ? "" : state.model.message;
  } catch {
    $("connectionMessage").textContent = "无法连接测试服务，请通过 README 的启动命令打开页面。";
  } finally { $("refreshStatus").disabled = false; }
}
function setBusy(busy) {
  $("startButton").disabled = busy;
  $("stopButton").disabled = !busy;
  document.body.classList.toggle("busy", busy);
  document.querySelectorAll("#result button").forEach((node) => { node.disabled = busy; });
}
function addSources(parent, sources, title) {
  if (!sources.length) return;
  const details = element("details");
  details.append(element("summary", `${title}（${sources.length}）`));
  for (const source of sources) {
    const row = element("div", undefined, "source");
    row.append(link(`${source.source_id} · ${source.title || "未命名文章"}`, source.url));
    row.append(element("p", [source.publisher, `公告日期：${source.published_at || "未核实"}`, source.updated_at ? `来源更新：${source.updated_at}` : "", ({ read: "已读原文", listing: "招聘汇总线索", preview: "搜索线索", image_only: "以图片为主" })[source.read_state] || source.read_state].filter(Boolean).join(" · "), "small muted"));
    if (source.excluded_reason) row.append(element("p", "未采用原因：" + source.excluded_reason, "small muted"));
    if (source.semantic_review) {
      const review = source.semantic_review;
      const contentType = { recruitment: "招聘公告", promotion: "推广或引流", tutorial: "教程或经验", news: "新闻资讯", unrelated: "无关内容", uncertain: "内容未确认" };
      row.append(element("p", `内容类型：${contentType[review.content_type] || "未确认"}`, "small muted"));
      row.append(element("p", `正文核对：${({ qualified: "有效招聘", lead: "待核实线索", rejected: "不符合需求" })[review.verdict]} · 招聘类别：${review.recruitment_types?.join("、") || "未确认"} · ${review.reason}`, "small muted"));
      if (review.category_evidence) row.append(element("blockquote", "类别依据：" + review.category_evidence));
    }
    row.append(element("pre", source.content || "没有可读取的正文"));
    details.append(row);
  }
  parent.append(details);
}
function renderCandidateArticles(audits, sources = []) {
  const parent = $("candidateList");
  if (!parent) return;
  parent.replaceChildren();
  const sourceMap = new Map(sources.map((source) => [source.url, source]));
  const statuses = { retained: "已读取，待核对", excluded: "规则排除", old: "超出时间范围", future: "日期异常", failed: "读取失败，未确认内容", duplicate: "重复文章", not_checked: "尚未检查" };
  let total = 0;
  for (const audit of audits) {
    parent.append(element("h3", audit.query || "本轮检索"));
    for (const candidate of audit.candidates || []) {
      total += 1;
      const source = sources.find((row) => candidate.source_id && row.source_id === candidate.source_id) || sourceMap.get(candidate.article_url) || (candidate.url ? sourceMap.get(candidate.url) : null);
      const review = source?.semantic_review;
      const status = review ? ({ qualified: "符合本轮需求", lead: "待核实", rejected: "不符合本轮需求" })[review.verdict] : statuses[candidate.status] || candidate.status;
      const row = element("article", undefined, "source");
      row.append(element("span", `第${candidate.page}页 · 第${candidate.rank}条 · ${status}`, "badge"));
      const heading = element("h3");
      heading.append(link(candidate.title || "未命名文章", candidate.article_url || candidate.url));
      row.append(heading, element("p", `原文发布日期：${candidate.published_at || source?.published_at || "未核实"}`, "small muted"));
      if (candidate.updated_at || source?.updated_at) row.append(element("p", `来源更新日期：${candidate.updated_at || source.updated_at}（不等于公告发布日期）`, "small muted"));
      row.append(element("p", `处理原因：${review?.reason || candidate.reason || "等待核对"}`, "small"));
      const links = element("p", undefined, "small");
      if (candidate.article_url && candidate.article_url !== candidate.url) links.append(link("打开公众号原文", candidate.article_url), document.createTextNode(" · "));
      links.append(link("打开搜索结果链接", candidate.url));
      row.append(links);
      const preview = source?.content || candidate.content_preview;
      if (preview) {
        const details = element("details");
        details.append(element("summary", "查看已读取的正文片段"), element("pre", preview.slice(0, 1500)));
        row.append(details);
      } else row.append(element("p", "尚未取得可核对正文；不能据此认定文章不是招聘。", "small muted"));
      parent.append(row);
    }
  }
  $("candidateCount").textContent = `${total} 条列表结果`;
  if (!total) parent.append(element("p", "本轮尚未取得文章列表。", "small muted"));
}
function renderResult(event) {
  lastRun = { ...event, trace: [...trace] };
  $("downloadButton").disabled = false;
  $("resultEmpty").classList.add("hidden");
  const parent = $("result");
  parent.replaceChildren();
  const result = event.result;
  if (result.verification) showVerification(result.verification);
  renderCandidateArticles(result.search_audits || [...candidateQueries.values()], result.sources || []);
  const data = result.data || {};
  if (result.coverage?.requested) {
    const count = result.coverage;
    parent.append(element("p", result.radar ? `展示 ${count.displayed} 条岗位相关线索 · 原文已读 ${count.displayed_content_read ?? 0} 条 · 时间范围已确认 ${count.displayed_time_verified ?? 0} 条` : `有效招聘 ${count.qualified} / 目标 ${count.requested} 条`, "summary-text"));
    parent.append(element("p", `执行 ${count.queries_executed} 组查询，检查 ${count.checked_candidates} 条候选，读取 ${count.unique_sources} 篇去重原文，完成核对 ${count.reviewed_sources ?? count.unique_sources} 篇。`, "small muted"));
    if (count.qualified < count.requested) {
      const stops = { radar_complete: "本轮招聘汇总召回与核对已完成，待确认线索另行展示", search_budget: "搜索预算已用完", model_budget: "模型调用预算已用完", plan_exhausted: "本轮计划的查询已检查完成", review_failed: "补查核对未完成，保留前轮已核实结果", blocked: "网站要求验证，已停止继续访问" };
      parent.append(element("p", result.radar ? `全部关键条件已核对 ${count.qualified} 条；其余线索的具体缺项分别标注，未知不等于不匹配。` : `未达到目标：${stops[count.stop_reason] || count.stop_reason}。待核实线索不计入有效数量。`, "small muted"));
    }
  }
  const labels = { found: "找到招聘线索", no_match: "本轮未找到匹配内容", needs_clarification: "需要补充信息", unavailable: "检索暂不可用" };
  parent.append(element("h3", labels[data.outcome] || (result.status === "ok" ? "本轮完成" : "本轮未成功")));
  if (result.error) parent.append(element("p", result.error, "notice error"));
  if (data.summary) parent.append(element("p", data.summary, "summary-text"));
  const intent = data.intent || {};
  const chips = element("div", undefined, "intent");
  for (const [key, label] of [["direction", "方向"], ["roles", "岗位"], ["expanded_roles", "展开岗位"], ["cities", "城市"], ["companies", "指定企业"], ["recruitment_types", "招聘类型"], ["graduation_cohorts", "届别"]]) {
    const value = Array.isArray(intent[key]) ? intent[key].join("、") : intent[key];
    if (value) chips.append(element("span", `${label}：${value}`));
  }
  if (intent.days) chips.append(element("span", `时间窗口：${intent.days} 天`));
  parent.append(chips);
  const sources = result.sources || [];
  const sourceMap = new Map(sources.map((source) => [source.source_id, source]));
  for (const finding of data.findings || []) {
    const source = sourceMap.get(finding.source_id) || {};
    const article = element("article", undefined, "finding");
    article.append(element("span", finding.match_status === "matches_request" ? "需求条件已核对" : result.radar ? "岗位方向相关" : "仍有条件待确认", "badge"));
    if (source.verification_details) {
      const details = source.verification_details;
      const row = element("div", undefined, "intent");
      row.append(element("span", `正文：${details.content === "read" ? "已读取" : details.content === "failed" ? "读取受阻" : "仅有招聘汇总"}`),
        element("span", `时间：${({ within_window: "符合要求", outside_window: "超出范围", unknown: "未提供可核对日期" })[details.publication] || "未确认"}`),
        element("span", `投递：${details.application === "link_provided" ? "已提供入口" : "未提供入口"}`));
      article.append(row);
    }
    const title = element("h3");
    title.append(link(finding.summary || source.title || finding.source_id, source.url));
    article.append(title, element("p", finding.relevance || "", "small muted"));
    if (finding.recruitment_evidence) article.append(element("blockquote", "招聘依据：" + finding.recruitment_evidence));
    for (const quote of finding.evidence_quotes || []) {
      if (quote !== finding.recruitment_evidence) article.append(element("blockquote", quote));
    }
    if (finding.unverified_conditions?.length) article.append(element("p", "待核实：" + finding.unverified_conditions.join("；"), "small muted"));
    article.append(element("p", [source.publisher, source.published_at || "日期未核实", finding.source_id].filter(Boolean).join(" · "), "small muted"));
    parent.append(article);
  }
  if (data.limitations?.length) {
    const list = element("ul", undefined, "limitations");
    data.limitations.forEach((text) => list.append(element("li", text)));
    parent.append(list);
  }
  const used = new Set((data.findings || []).map((finding) => finding.source_id));
  addSources(parent, sources.filter((source) => used.has(source.source_id)), "本轮采用的招聘来源");
  addSources(parent, sources.filter((source) => !used.has(source.source_id)), "未采用的检索候选 · 不作为本轮招聘推荐");
  if (result.search_plan?.queries?.length) {
    const plan = element("details");
    plan.append(element("summary", "用户需求 → 岗位语义查询计划"));
    for (const query of result.search_plan.queries) plan.append(element("p", `${query.query} · ${query.recruitment_type} — ${query.purpose}`, "small"));
    parent.append(plan);
  }
  if (result.search_audits?.length) {
    const audit = element("details");
    audit.append(element("summary", "本轮逐条候选检查记录 · 含跳过与未检查原因"));
    const statuses = { retained: "保留待语义核对", excluded: "已排除", old: "原文日期超出范围", future: "原文日期异常", failed: "读取失败", duplicate: "重复来源", not_checked: "未检查" };
    for (const search of result.search_audits) {
      const row = element("div", undefined, "source");
      const count = search.coverage || {};
      row.append(element("h3", search.query), element("p", `检查 ${count.pages_checked || 0} 页；识别 ${count.indexed_candidates || 0} 条，检查 ${count.checked_candidates || 0} 条，读取 ${count.read_articles || 0} 篇。`, "small muted"));
      const list = element("ul", undefined, "limitations");
      for (const candidate of search.candidates || []) list.append(element("li", `第${candidate.page}页第${candidate.rank}条 · ${candidate.title} · ${statuses[candidate.status] || candidate.status}：${candidate.reason}`));
      row.append(list);
      audit.append(row);
    }
    parent.append(audit);
  }
  if (result.discarded_sources?.length) {
    const discarded = element("details");
    discarded.append(element("summary", `已排除的内容（${result.discarded_sources.length}）`));
    for (const source of result.discarded_sources) {
      const row = element("div", undefined, "source");
      row.append(element("p", source.title || "未命名文章"), element("p", source.reason, "small muted"));
      discarded.append(row);
    }
    parent.append(discarded);
  }
  if (result.tool_runs?.length) {
    const actual = element("details");
    actual.append(element("summary", "实际工具调用记录"), element("pre", JSON.stringify(result.tool_runs, null, 2), "json"));
    parent.append(actual);
  }
  const raw = element("details");
  raw.append(element("summary", "完整输入与输出 JSON"), element("pre", JSON.stringify(lastRun, null, 2), "json"));
  parent.append(raw);
  if (data.followup_questions?.length) {
    const form = element("form", undefined, "followup");
    form.append(element("h3", "补充回答，再试一次"));
    const fields = data.followup_questions.map((question, index) => {
      const label = element("label", question);
      const input = element("textarea");
      input.id = `answer-${index}`;
      input.maxLength = 10000;
      label.htmlFor = input.id;
      form.append(label, input);
      return { question, input };
    });
    const button = element("button", "带着补充回答重新搜索 →", "primary");
    button.type = "submit";
    button.disabled = Boolean(controller);
    form.append(button);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const answers = fields.filter(({ input }) => input.value.trim()).map(({ question, input }) => ({ question, answer: input.value.trim() }));
      if (!answers.length) return errorMessage("请至少填写一项补充回答。");
      const merged = new Map((lastInput.clarifications || []).map((item) => [item.question, item]));
      answers.forEach((answer) => merged.set(answer.question, answer));
      run({ ...lastInput, clarifications: [...merged.values()] });
    });
    parent.append(form);
  }
}
function receive(event) {
  trace.push(event);
  const seconds = Number(event.elapsed_seconds || 0);
  if (event.type === "start") log(event.message);
  if (event.type === "model_start") {
    currentAction = event.message || "核对招聘需求与搜索结果";
    log(event.round === 1 ? "理解你的招聘需求" : "核对招聘候选与用户条件", currentAction, seconds);
  }
  if (event.type === "progress") {
    if (event.phase === "verification") showVerification(event);
    if (event.phase === "candidate") {
      const audit = candidateQueries.get(event.query) || { query: event.query, candidates: [] };
      audit.candidates.push(event);
      candidateQueries.set(event.query, audit);
      renderCandidateArticles([...candidateQueries.values()]);
    }
    const labels = { search: "按岗位需求搜索招聘公告", read: `核实候选原文 ${event.index}/${event.total}`,
      excluded: "排除非招聘或未确认的内容", retained: "保留招聘候选，继续核对用户条件", scope: "保留用户明确条件，移除擅自增加的限制", rejected: "排除不符合用户要求的候选",
      planning: "理解岗位与招聘类别", plan: "已生成岗位语义查询计划", collecting: "按查询计划收集多条候选", verifying: "优先核验岗位相关候选的原文与入口", reviewing: "批量核对正文与用户需求",
      review_complete: `正文核对完成：有效 ${event.qualified}/${event.target} 条`, expanding: "有效招聘不足，补查对应岗位", page: `继续检查第${event.page}页`,
      candidate: `第${event.page}页第${event.rank}条 · ${({retained:"保留候选",excluded:"已排除",old:"日期超出范围",future:"日期异常",failed:"读取失败",duplicate:"重复",not_checked:"未检查"})[event.status] || "核对"}`,
      coverage: `本次查询：检查 ${event.checked_candidates} 条，保留 ${event.retained} 条候选`, sync: "同步腾讯文档公开招聘汇总", validation: "正在修正正文核对结果", verification: "需要手动完成浏览器验证，已暂停搜索" };
    currentAction = labels[event.phase] || "核对招聘信息";
    let detail = event.phase === "search" ? `实际搜索词：${event.query}` : [event.title, event.reason].filter(Boolean).join("\n");
    if (event.queries) detail = event.queries.map((query, index) => `${index + 1}. ${query.query} · ${query.recruitment_type}\n${query.purpose}`).join("\n");
    if (event.phase === "review_complete") detail = (event.reviews || []).map((review) => `${review.source_id} · ${({qualified:"有效招聘",lead:"待核实",rejected:"排除"})[review.verdict]} · ${review.reason}`).join("\n");
    log(currentAction, detail, seconds);
  }
  if (event.type === "validation") log("输出校验反馈", event.message, seconds);
  if (event.type === "tool_start") {
    const purpose = event.arguments?.purpose || (event.tool === "search_recruitment_radar"
      ? "从招聘汇总召回与需求相关的岗位" : "优先核验初筛相关候选的原文与投递信息");
    currentAction = purpose;
    const row = log(toolNames[event.tool] || event.tool, purpose, seconds);
    const parameters = element("details", undefined, "tool-arguments");
    parameters.append(element("summary", "查看工具参数"), element("pre", JSON.stringify(event.arguments, null, 2)));
    row.append(parameters);
    row.append(element("div", "执行中…", "log-state"));
    toolRows.set(event.id, row);
  }
  if (event.type === "tool_arguments") {
    const row = toolRows.get(event.id);
    if (row) row.querySelector(".tool-arguments pre").textContent = JSON.stringify(event.arguments, null, 2);
  }
  if (event.type === "tool_end") {
    const row = toolRows.get(event.id);
    if (row) {
      const status = row.querySelector(".log-state");
      const labels = { empty: "本次未找到可保留的招聘公告", blocked: "网站要求验证，尚未完成搜索", browser_unavailable: "浏览器连接不可用",
        search_limit: "已达到本轮搜索上限，开始整理已有信息", already_running: "相同查询正在执行，不重复访问", execution_limit: "调用预算已用尽" };
      status.textContent = event.reused ? "复用已有结果，未重复访问网站" : labels[event.status]
        || `${event.source_count || 0} 个招聘候选${event.excluded_count ? `，排除 ${event.excluded_count} 条非招聘或未确认内容` : ""}`;
      if (event.error) status.textContent += " · " + event.error;
      if (!["ok", "empty", "partial", "image_only"].includes(event.status)) status.classList.add("error");
    }
  }
  if (event.type === "result") { renderResult(event); return true; }
  if (event.type === "error") throw new Error(event.message);
  return false;
}
async function run(input) {
  if (controller) return;
  controller = new AbortController();
  lastInput = structuredClone(input);
  lastRun = null;
  trace.length = 0;
  $("verificationNotice")?.classList.add("hidden");
  candidateQueries.clear();
  renderCandidateArticles([]);
  toolRows.clear();
  $("timeline").replaceChildren();
  $("result").replaceChildren();
  $("resultEmpty").classList.remove("hidden");
  $("downloadButton").disabled = true;
  errorMessage();
  setBusy(true);
  const started = Date.now();
  currentAction = "正在启动";
  timer = setInterval(() => { $("runState").textContent = `${currentAction} · ${Math.floor((Date.now() - started) / 1000)}s`; }, 500);
  $("runState").textContent = "正在启动…";
  let completed = false;
  try {
    const response = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input), signal: controller.signal });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(typeof payload.detail === "string" ? payload.detail : "输入格式不正确，请检查输入和调用预算。");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        if (line) completed = receive(JSON.parse(line)) || completed;
      }
      if (done) break;
    }
    if (buffer.trim()) completed = receive(JSON.parse(buffer)) || completed;
    if (!completed) throw new Error("连接中断，尚未收到完整结果。");
    $("runState").textContent = `${lastRun.result.status === "ok" ? "已完成" : "未成功"} · ${((Date.now() - started) / 1000).toFixed(1)}s`;
  } catch (error) {
    const message = error.name === "AbortError" ? "已停止本轮测试。" : error.message;
    errorMessage(message);
    log(error.name === "AbortError" ? "停止测试" : "本轮中断", message, (Date.now() - started) / 1000);
    $("runState").textContent = error.name === "AbortError" ? "已停止" : "执行失败";
  } finally {
    clearInterval(timer);
    if (!completed) {
      for (const row of toolRows.values()) {
        const status = row.querySelector(".log-state");
        if (status?.textContent === "执行中…") status.textContent = "本轮已中止";
      }
    }
    controller = null;
    setBusy(false);
    refreshStatus();
  }
}
$("requestForm").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!$("request").value.trim()) return errorMessage("请输入搜索需求。");
  run({ request: $("request").value.trim(), channel: "radar", days: $("days").value ? Number($("days").value) : null,
    limit: Number($("limit").value), max_model_calls: Number($("modelCalls").value),
    max_tool_calls: Number($("toolCalls").value), timeout: Number($("timeout").value), clarifications: [] });
});
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", () => { $("request").value = button.dataset.example; $("request").focus(); }));
$("refreshStatus").addEventListener("click", refreshStatus);
$("stopButton").addEventListener("click", () => controller?.abort());
$("downloadButton").addEventListener("click", () => {
  if (!lastRun) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastRun, null, 2)], { type: "application/json" }));
  const anchor = element("a");
  anchor.href = url;
  anchor.download = `recruitment-radar-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
refreshStatus();
