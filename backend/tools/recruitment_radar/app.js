"use strict";
const $ = (id) => document.getElementById(id);
let page = 1, total = 0, currentJobs = [], controller = null;
const sourceNames = { aggregate: "实时招聘汇总", official_site: "官网 / 固定公众号", snapshot: "仓库快照", import: "文件导入" };
function node(tag, text, cls = "") { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; n.className = cls; return n; }
function link(text, url) { const a = node("a", text); try { const u = new URL(url); if (!/^https?:$/.test(u.protocol)) throw Error(); a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer"; } catch {} return a; }
function message(text) { $("messages").textContent = text; }
async function request(url, options) { const r = await fetch(url, options); const d = await r.json(); if (!r.ok) throw Error(typeof d.detail === "string" ? d.detail : "请求失败"); return d; }
function params() { return new URLSearchParams({ keyword: $("keyword").value.trim(), city: $("city").value.trim(), industry: $("industry").value, source: $("source").value, page, page_size: $("pageSize").value }); }
async function status() { const d = await request("/api/radar/status"); $("capabilities").replaceChildren(...[
  `${d.sites} 个采集节点`, `${d.records} 条本地记录`, `Firecrawl：${d.firecrawl ? "已配置" : "未配置"}`, `AnySearch：${d.anysearch ? "已启用" : "未启用"}`, "CLI：支持文件导入"
].map(t => node("span", t, "badge"))); if ($("industry").options.length === 1) for (const value of d.industries) { const o = node("option", value); o.value = value; $("industry").append(o); } }
async function load() {
  const d = await request("/api/radar/jobs?" + params()); total = d.total; currentJobs = d.jobs;
  $("summary").textContent = `当前筛选 ${total} 条 / 全部 ${d.all_records} 条 · ${d.mode === "snapshot" ? "仓库快照" : "实时同步缓存"} · 最近同步：${d.fetched_at || "尚未同步"}`;
  $("limitations").textContent = d.limitations.join("；"); $("limitations").classList.toggle("hidden", !d.limitations.length);
  $("jobs").replaceChildren();
  for (const job of d.jobs) {
    const row = node("tr"), company = node("td", job.company), role = node("td"), city = node("td"), dates = node("td"), source = node("td");
    role.append(node("strong", job.role), node("p", job.batch || "批次未注明", "muted"));
    const details = node("details"); details.append(node("summary", "查看记录 / 已读正文"), node("pre", JSON.stringify(job, null, 2))); role.append(details);
    city.append(node("p", job.city || "地点未注明"), node("p", job.degree || "学历未注明", "muted"));
    dates.append(node("p", `截止：${job.deadline || "未注明"}`), node("p", `公告发布：${job.published_at || "未核实"}`, "muted"), node("p", `来源更新：${job.updated_at || "未注明"}`, "muted"));
    if (job.snapshot_at) dates.append(node("p", `快照日期：${job.snapshot_at}`, "muted"));
    source.append(node("p", sourceNames[job.source_type] || job.source_type, "badge"));
    if (job.url) source.append(link("投递 / 招聘页面 ↗", job.url)); else source.append(node("p", "未提供投递链接", "muted"));
    if (job.announcement_url && job.announcement_url !== job.url) source.append(node("p"), link("官方公告 ↗", job.announcement_url));
    row.append(company, role, city, dates, source); $("jobs").append(row);
  }
  if (!d.jobs.length) { const row = node("tr"), cell = node("td", "当前筛选没有记录，可同步数据、调整条件或导入文件。"); cell.colSpan = 5; row.append(cell); $("jobs").append(row); }
  $("page").textContent = `${page} / ${Math.max(1, Math.ceil(total / Number($("pageSize").value)))}`;
  $("previous").disabled = page <= 1; $("next").disabled = page * Number($("pageSize").value) >= total;
  const sites = await request("/api/radar/sites?" + new URLSearchParams({ industry: $("industry").value }));
  $("sites").replaceChildren(); for (const site of sites.sites) { const p = node("p"); p.append(link(`${site.company} · ${site.industry}`, site.url)); $("sites").append(p); }
}
async function collect(url, body) {
  if (controller) return;
  controller = new AbortController(); $("sync").disabled = $("crawl").disabled = true; $("stop").disabled = false; message("采集开始…");
  try {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
    if (!r.ok) throw Error((await r.json()).detail || "采集请求失败");
    const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = "";
    function receive(event) {
      if (event.type === "progress") message(event.phase === "crawl" ? `${event.completed}/${event.total} · ${event.company} · ${event.status} · 新增 ${event.count} 条\n${event.error || ""}` : `${event.title}：${event.reason}`);
      if (event.type === "result") message("采集完成：" + JSON.stringify(event.result, null, 2));
      if (event.type === "error") throw Error(event.message);
    }
    while (true) { const {value, done} = await reader.read(); buffer += decoder.decode(value, {stream: !done}); let i;
      while ((i = buffer.indexOf("\n")) >= 0) { const line = buffer.slice(0,i); buffer = buffer.slice(i+1); if(line.trim()) receive(JSON.parse(line)); } if(done) break; }
    if(buffer.trim()) receive(JSON.parse(buffer));
  } catch(e) { message(e.name === "AbortError" ? "已停止采集；已保存的数据仍可浏览。" : e.message); }
  finally { controller = null; $("sync").disabled = $("crawl").disabled = false; $("stop").disabled = true; await status(); await load(); }
}
async function allFiltered() { const p = params(); p.set("page_size", "200"); const rows=[]; for(let n=1;n<=Math.max(1,Math.ceil(total/200));n++){p.set("page",n); rows.push(...(await request("/api/radar/jobs?"+p)).jobs);} return rows; }
function download(content, type, filename) { const url=URL.createObjectURL(new Blob([content],{type})); const a=node("a"); a.href=url; a.download=filename; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
function safe(action) { return async () => {try {await action();} catch(e) {message(e.message);} }; }
$("sync").onclick = () => collect("/api/radar/sync", {});
$("crawl").onclick = () => { const limit=Number($("siteLimit").value); if(!Number.isInteger(limit)||limit<1||limit>856) return message("节点上限应为1—856。"); collect("/api/radar/crawl", {industry:$("industry").value,keyword:$("keyword").value.trim(),limit}); };
$("stop").onclick = () => controller?.abort();
$("filter").onclick = safe(async()=>{page=1;await load();});
$("clear").onclick = safe(async()=>{for(const id of ["keyword","city","industry","source"]) $(id).value="";page=1;await load();});
$("previous").onclick = safe(async()=>{page--;await load();}); $("next").onclick = safe(async()=>{page++;await load();}); $("pageSize").onchange = safe(async()=>{page=1;await load();});
$("import").onchange = safe(async()=>{const f=$("import").files[0]; if(!f)return; if(f.size>3000000)throw Error("文件不能超过3MB"); const d=await request("/api/radar/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:f.name,content:await f.text()})});message(`已导入${d.imported}条，新增${d.added}条。`);page=1;await status();await load();$("import").value="";});
$("exportJson").onclick = safe(async()=>download(JSON.stringify({jobs:await allFiltered()},null,2),"application/json","recruitment-radar.json"));
$("exportCsv").onclick = safe(async()=>{const rows=await allFiltered(),keys=["company","role","city","degree","batch","deadline","updated_at","published_at","url","source_type"];
  const cell=v=>'"'+String(v||"").replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';download("\ufeff"+[keys.join(","),...rows.map(r=>keys.map(k=>cell(r[k])).join(","))].join("\r\n"),"text/csv;charset=utf-8","recruitment-radar.csv");});
safe(async()=>{await status();await load();})();
