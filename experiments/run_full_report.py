import argparse
import asyncio
from datetime import datetime
from html import escape
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from zoneinfo import ZoneInfo

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from .news_advisor.config import get_ai_config
from .news_advisor.graph import AgentExecutionError
from .news_advisor.report_workflow import ReportInput, build_report_graph, validate_review
from .news_advisor.tools.document import read_document


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def html_report(markdown_text: str, title: str):
    import markdown
    import bleach

    body = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])
    body = bleach.clean(body, tags={"p", "h1", "h2", "h3", "h4", "ul", "ol", "li", "strong", "em",
                                    "blockquote", "pre", "code", "a", "table", "thead", "tbody", "tr", "th", "td", "hr", "br"},
                        attributes={"a": ["href", "title"]}, protocols={"https", "http"}, strip=True)
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + escape(title) + """</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f9;color:#17283a;font:16px/1.85 'Microsoft YaHei','Segoe UI',sans-serif}
main{max-width:1060px;margin:36px auto;padding:42px 56px;background:white;border-top:6px solid #087f8c;box-shadow:0 6px 30px #1b334010}
h1{font-size:30px;line-height:1.45;color:#123754}h2{font-size:23px;margin-top:42px;border-bottom:1px solid #dce6ec;padding-bottom:8px}
h3{font-size:18px;margin-top:28px;color:#126c79}p,li{overflow-wrap:anywhere}li{margin:7px 0}blockquote{margin:18px 0;padding:12px 20px;background:#f5f8fb;border-left:4px solid #7fa5bc}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{border:1px solid #dce6ec;padding:10px;text-align:left;vertical-align:top}th{background:#edf5f7}
pre{white-space:pre-wrap;background:#f4f7f9;padding:16px}a{color:#087f8c}code{font-family:Consolas,monospace}hr{border:0;border-top:1px solid #dce6ec;margin:30px 0}
@media(max-width:700px){main{margin:0;padding:22px}h1{font-size:25px}}@media print{body{background:white}main{margin:0;padding:0;box-shadow:none}h2,h3{break-after:avoid}blockquote,table{break-inside:avoid}}
</style><main>""" + body + "</main></html>"


def save_readable(output, state, metadata, *, completed):
    results = state.get("results", {})
    if completed:
        from backend.services.report.workflow_report import build_report_bundle

        bundle = build_report_bundle("local-case", metadata["report_id"], {}, state, metadata["model"])
        save_json(output / "report-bundle.json", bundle)
        text = bundle["report_document"]["markdown"]
        constraints = state["review"]["constraints"]
        facts_path = output / "user-constraints.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8")) if facts_path.exists() else {}
        title, remainder = text.split("\n", 1)
        conditions = "\n\n## 本次已确认条件\n\n| 条件 | 内容 |\n|---|---|\n"
        if facts:
            conditions += "| 求职类型 | " + facts.get("employment_type", "待确认") + " |\n"
            conditions += "| 到岗时间 | " + facts.get("can_start", "待确认") + " |\n"
            conditions += "| 每周到岗 | " + str(facts.get("onsite_days_per_week", "待确认")) + " 天 |\n"
        conditions += f"| 每周求职准备 | {constraints['weekly_hours']:g} 小时，与到岗时间分开计算 |\n"
        conditions += f"| 本阶段准备窗口 | {constraints['start_date']} 至 {constraints['deadline']} |\n"
        conditions += "| 准备预算 | " + ("暂不确定" if constraints.get("budget") is None else str(constraints["budget"]) + " 元") + " |\n"
        conditions += "| 城市、可连续实习月数 | 未确认，逐岗位核实 |\n\n"
        conditions += "这是边核实边准备的阶段安排，不是承诺在该窗口内入职。\n"
        text = title + conditions + remainder
        text += "\n\n## 本次运行与证据边界\n\n"
        text += "本报告来自用户提供的简历和本次真实 Agent 运行。简历中的经历、论文、专利及实验指标属于用户材料陈述，未做独立真实性核验。\n\n"
        text += "计划约束及补充回答见 review-response.json；模型结论仍需人工复核，不能视为录用保证。\n"
        name = "career-report"
    else:
        decision = results.get("career_decision", {}).get("data", {})
        text = "# 大模型算法方向职业报告 · 待补充与确认\n\n"
        text += "当前已完成简历、岗位、招聘与职业决策阶段。行动规划等待用户提供真实约束。\n\n"
        text += "## 决策摘要\n\n" + decision.get("summary", "尚未完成职业决策") + "\n\n"
        from .run_career_decision import render_report, verify_result

        payload = state.get("decision_input")
        if payload:
            rendered = render_report(payload, results["career_decision"], verify_result(payload, results["career_decision"]),
                                     {"model": metadata["model"], "elapsed_seconds": metadata.get("elapsed_seconds", 0)})
            text += rendered.replace("# 职业决策验证报告", "## 岗位适配明细", 1)
        recruitment = results.get("recruitment_search", {})
        text += "\n\n## 招聘搜索结果\n\n" + recruitment.get("data", {}).get("summary", "未获得可用搜索结论") + "\n"
        for finding in recruitment.get("data", {}).get("findings", []):
            text += "\n- " + finding["summary"] + "\n"
        for source in recruitment.get("sources", []):
            text += f"\n- {source.get('source_id', '')}：{source.get('title', '')} {source.get('url', '')}\n"
        name = "career-review"
    observations = output / "run-observations.json"
    if observations.exists():
        notes = json.loads(observations.read_text(encoding="utf-8"))
        if completed and notes.get("executive_review"):
            text = text.replace("## 执行摘要\n\n", "## 执行摘要\n\n> 人工复核补充：" + notes["executive_review"] + "\n\n", 1)
        text += "\n\n## 本次运行的人工阅读提示\n\n"
        text += "\n".join("- " + note for note in notes.get("semantic_review", [])) + "\n"
        if completed:
            text += "\n" + notes.get("phase_policy", "") + "\n"
    (output / (name + ".md")).write_text(text, encoding="utf-8")
    (output / (name + ".html")).write_text(html_report(text, "大模型算法职业报告"), encoding="utf-8")
    from .news_advisor.telemetry import summarize_executions
    execution = summarize_executions(results)
    save_json(output / "execution-summary.json", execution)
    labels = {"resume_analysis": "简历分析", "job_analysis": "岗位分析", "recruitment_search": "招聘搜索",
              "career_decision": "职业决策", "action_planning": "行动规划"}
    flow = "# 职业报告流程实跑记录\n\n"
    flow += "简历 PDF → OCR 与目视复核 → 简历分析 → 岗位检索与分析 → 招聘搜索 → 职业决策 → 人工补充 → 行动规划 → 报告合成。\n\n"
    flow += "当前目标：**" + state["input"]["targets"][0] + "**。\n\n"
    flow += "本次使用完整报告工作流；独立咨询入口的 Redis/Chroma 分层记忆未接入本流程。\n\n"
    flow += "| 阶段 | 状态 | 主要产出 |\n|---|---|---|\n"
    for key, label in labels.items():
        result = results.get(key, {})
        data = result.get("data", {})
        if key == "job_analysis":
            targets = data.get("targets", [])
            detail = str(sum(len(target["job_analysis"].get("sources", [])) for target in targets)) + " 条原始岗位片段及其引用"
        elif key == "career_decision":
            detail = str(sum(len(item.get("checks", [])) for item in data.get("assessments", []))) + " 项要求与候选人证据对照"
        elif key == "recruitment_search":
            detail = str(len(data.get("findings", []))) + " 条招聘线索；有效性以报告中的待核实说明为准"
        elif key == "action_planning":
            detail = str(len(data.get("tasks", []))) + " 项任务" if result else "等待用户提供真实准备时间"
        else:
            detail = str(len(data.get("experiences", []))) + " 段经历分析与改进建议"
        flow += f"| {label} | {result.get('status', '待执行')} | {detail} |\n"
    for key, label in labels.items():
        result = results.get(key, {})
        data = result.get("data", {})
        flow += "\n\n## " + label + "\n\n"
        if key == "job_analysis":
            for target in data.get("targets", []):
                flow += target["job_analysis"].get("data", {}).get("summary", "") + "\n\n"
        else:
            flow += data.get("summary", "等待执行") + "\n\n"
        if key == "career_decision":
            flow += "用户到岗条件通过 review-response.json 中的实际回答进入复核，未回答的个人贡献、实习月数及城市等问题继续保持未知。\n"
    flow += "\n\n## 可追溯记录\n\n"
    flow += "- 每阶段输入输出：stages/\n- 人工复核请求：review-request.json\n- 实际补充回答与计划约束：review-response.json\n- 原始 OCR 与目视更正：document.json、document-visual-review.json\n- 阶段事件：trace.jsonl\n- LangGraph 持久化检查点：checkpoints.sqlite3\n"
    flow += f"\n最终保留结果累计业务模型调用 {execution['model_calls']} 次，已报告的总 Token 为 {execution['total_tokens']}。"
    flow += "此口径不包含被后续修订替换的旧结果，也不包含 OCR 和 LightRAG 服务内部调用；不是完整账单。\n"
    (output / "pipeline-run.md").write_text(flow, encoding="utf-8")
    (output / "pipeline-run.html").write_text(html_report(flow, "职业报告流程实跑记录"), encoding="utf-8")
    if completed:
        from .news_advisor.report_presentation import write_reader_report
        write_reader_report(output, state, metadata)


async def run(args):
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "stages").mkdir(exist_ok=True)
    if args.render_only:
        state = json.loads((output / "state.json").read_text(encoding="utf-8"))
        metadata = json.loads((output / "run.json").read_text(encoding="utf-8"))
        save_readable(output, state, metadata, completed=metadata.get("status") == "completed")
        print("阅读报告已更新：" + str(output / "career-report.html"), flush=True)
        return
    settings = get_ai_config("chat")
    model = ChatOpenAI(api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
                       temperature=0, timeout=180, max_retries=0,
                       extra_body={"thinking": {"type": "disabled"}, "max_tokens": 16384})
    metadata_path = output / "run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {
        "thread_id": "full-report-" + uuid4().hex,
        "report_id": "report-" + uuid4().hex[:12],
        "model": settings.model,
        "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "user_request": args.preferences,
    }
    config = {"configurable": {"thread_id": metadata["thread_id"]}, "recursion_limit": 100}
    started = perf_counter()

    def event(kind, **fields):
        entry = {"time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "kind": kind, **fields}
        with (output / "trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    class Capture(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            event("model_call", run_id=str(kwargs.get("run_id", "")))

        def on_tool_start(self, serialized, input_str, **kwargs):
            event("tool_call", tool=(serialized or {}).get("name", "unknown"))

        def on_llm_end(self, response, **kwargs):
            diagnostics = []
            for group in response.generations:
                for generation in group:
                    message = getattr(generation, "message", None)
                    if message is not None:
                        diagnostics.append({"content": message.content, "tool_calls": message.tool_calls,
                                            "invalid_tool_calls": message.invalid_tool_calls,
                                            "metadata": message.response_metadata})
            folder = output / "model-responses"
            folder.mkdir(exist_ok=True)
            save_json(folder / (str(kwargs.get("run_id", uuid4())) + ".json"), diagnostics)

        def on_tool_end(self, result, **kwargs):
            content = getattr(result, "content", None)
            if isinstance(content, str) and ("Error" in content or "错误" in content):
                event("validation_feedback", message=content[:3000])

    config["callbacks"] = [Capture()]
    save_json(metadata_path, metadata)
    try:
        async with AsyncSqliteSaver.from_conn_string(str(output / "checkpoints.sqlite3")) as saver:
            graph = build_report_graph(lambda: model, checkpointer=saver,
                                       stage_callback=lambda key, label, detail: event("stage", key=key, label=label, detail=detail))
            previous = await graph.aget_state(config)
            if previous.values:
                if args.update_input:
                    inputs = ReportInput.model_validate(json.loads(args.update_input.read_text(encoding="utf-8-sig"))).model_dump(mode="json")
                    from backend.services.report.provenance import capture_provenance
                    save_json(output / "state-before-input-update.json", dict(previous.values))
                    await graph.aupdate_state(config, {"input": inputs, "profile_snapshot": {},
                                                       "provenance": capture_provenance(inputs, {}, settings.model)}, as_node="__start__")
                    save_json(output / "report-input.json", inputs)
                    event("input_updated", targets=inputs["targets"])
                    value = None
                elif args.review_file:
                    response = json.loads(args.review_file.read_text(encoding="utf-8-sig"))
                    from .news_advisor.report_workflow import review_request
                    response = validate_review(response, review_request(previous.values))
                    save_json(output / "review-response.json", response)
                    value = Command(resume=response)
                elif previous.next:
                    if previous.next == ("review",):
                        event("waiting_for_review", path=str(output / "review-request.json"))
                        return 0
                    value = None
                else:
                    event("already_completed")
                    return 0
            else:
                if not args.resume_file or not args.preferences:
                    raise ValueError("首次运行必须提供 --resume-file 和 --preferences")
                event("document", status="reading")
                document = await read_document.ainvoke({"file_path": str(args.resume_file.resolve()), "max_pages": 20})
                save_json(output / "document.json", document)
                if document.get("status") not in {"ok", "partial"} or not document.get("markdown", "").strip():
                    raise ValueError("简历读取失败")
                (output / "resume.md").write_text(document["markdown"], encoding="utf-8")
                event("document", status=document["status"], warnings=document.get("warnings", []))
                inputs = ReportInput(raw_resume=document["markdown"], targets=args.target or ["大模型算法工程师"],
                                     preferences=args.preferences, recruitment={
                                         "request": args.preferences + " 请搜索相关方向的公开招聘信息。城市、薪资、毕业届别和工作类型未明确限定时不要自行添加过滤条件。",
                                         "channel": "all", "limit": 3,
                                     }).model_dump(mode="json")
                save_json(output / "report-input.json", inputs)
                from backend.services.report.provenance import capture_provenance
                value = {"input": inputs, "profile_snapshot": {}, "provenance": capture_provenance(inputs, {}, settings.model)}

            async for update in graph.astream(value, config, stream_mode="updates", durability="sync"):
                for node, payload in update.items():
                    if node == "__interrupt__":
                        save_json(output / "review-request.json", [item.value for item in payload])
                        event("interrupt", path=str(output / "review-request.json"))
                    else:
                        save_json(output / "stages" / (node + ".json"), payload)
                        event("node_completed", node=node)
            snapshot = await graph.aget_state(config)
            state = dict(snapshot.values)
            save_json(output / "state.json", state)
            for name, result in state.get("results", {}).items():
                save_json(output / "stages" / (name + "-result.json"), result)
            metadata.update(elapsed_seconds=round(perf_counter() - started, 2), next=list(snapshot.next),
                            status="awaiting_review" if snapshot.next else "completed")
            save_json(metadata_path, metadata)
            save_readable(output, state, metadata, completed=not snapshot.next)
            event("finished", status=metadata["status"], output=str(output))
    except Exception as error:
        metadata.update(status="failed", error_type=type(error).__name__, elapsed_seconds=round(perf_counter() - started, 2))
        save_json(metadata_path, metadata)
        if isinstance(error, AgentExecutionError):
            save_json(output / "failed-agent.json", error.result)
            event("failed", agent=error.result.get("agent"), status=error.result.get("status"))
        else:
            event("failed", error_type=type(error).__name__)
        raise


def main():
    parser = argparse.ArgumentParser(description="执行完整职业报告 LangGraph，并在人工复核后恢复")
    parser.add_argument("--resume-file", type=Path)
    parser.add_argument("--preferences", default="")
    parser.add_argument("--target", action="append")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--render-only", action="store_true", help="只重建阅读报告，复用已保存的结果")
    parser.add_argument("--update-input", type=Path, help="用户更新目标或原始材料后，保存旧状态并重新执行报告流程")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
