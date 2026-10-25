"""用简历和职业取向验证决策 Agent，保存真实输入、证据和待人工复核结果。

python -m experiments.run_career_decision "简历.pdf" --preferences "AI Agent 应用开发实习"
python -m experiments.run_career_decision --replay-input "结果目录/decision_input.json"
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CachedJobRetriever:
    """重放时读取已保存的 JD；与在线检索器提供相同接口，不注册为 Agent 工具。"""

    def __init__(self, result: dict):
        self.sources = result["sources"]
        self.scope = result.get("scope", {})

    async def retrieve(self, request) -> dict:
        return {"sources": self.sources, "scope": self.scope}


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_result(payload: dict, result: dict) -> dict:
    """自动核对结构和证据；不把这些检查当作业务正确性的评判。"""
    from pydantic import ValidationError
    from experiments.news_advisor.agents.career_decision import verify_career_decision

    available = [target for target in payload["targets"]
                 if target["job_analysis"].get("status") == "ok" and target["job_analysis"].get("sources")]
    upstream_errors = [{"target_id": target["target_id"], "status": target["job_analysis"].get("status"),
                        "error": target["job_analysis"].get("error") or "未返回可用岗位原文"}
                       for target in payload["targets"] if target not in available]
    errors = []
    if result.get("status") != "ok":
        if upstream_errors and not available:
            errors.append("岗位分析阶段未提供可用证据，决策 Agent 未执行模型分析。")
        else:
            errors.append(f"决策 Agent 未成功：{result.get('status')}；{result.get('error') or '无有效分析'}")
    else:
        try:
            errors = verify_career_decision(result.get("data", {}), {
                "sources": result.get("sources", []), "targets": available,
            })
        except ValidationError as error:
            errors = [str(error)]
    expected = {target["target_id"] for target in payload["targets"]}
    assessed = {item["target_id"] for item in result.get("data", {}).get("assessments", [])}
    missing = sorted(expected - assessed)
    return {
        "status": "failed" if errors else "partial" if missing else "passed",
        "deterministic_checks_passed": not errors,
        "errors": errors, "unassessed_target_ids": missing,
        "upstream_errors": upstream_errors,
        "failed_stage": "job_analysis" if upstream_errors and not available else "career_decision" if errors else None,
        "upstream_status": {target["target_id"]: target["job_analysis"].get("status") for target in payload["targets"]},
        "resume_analysis_status": payload.get("resume_analysis", {}).get("status"),
        "document_status": payload.get("resume_analysis", {}).get("document", {}).get("status"),
        "semantic_correctness": "not_evaluated",
        "note": "自动通过只证明输出结构、引用与部分硬约束一致；引文是否支持结论、要求是否遗漏、偏好是否被尊重仍需人工复核。",
    }


def build_review(result: dict) -> dict:
    return {
        "status": "pending" if result.get("data", {}).get("assessments") else "unavailable",
        "instructions": "对照 report.md 的原文，把 verdict 填为 correct / incorrect / uncertain，说明原因；不要仅因自动校验通过就判正确。",
        "checks": [{
            "target_id": assessment["target_id"], "check_id": check["check_id"],
            "requirement": check["requirement"], "model_status": check["status"],
            "verdict": None, "notes": "",
        } for assessment in result.get("data", {}).get("assessments", []) for check in assessment["checks"]],
        "overall": {
            "hard_conditions_fully_covered": None, "preferences_respected": None,
            "recommendation_supported": None, "actions_feasible": None, "notes": "",
        },
    }


def render_report(payload: dict, result: dict, verification: dict, run_info: dict) -> str:
    data = result.get("data", {})
    titles = {target["target_id"]: target["title"] for target in payload["targets"]}
    review_status = "待人工复核" if data.get("assessments") else "未生成决策，无法评估"
    lines = ["# 职业决策验证报告", "", f"自动检查：{verification['status']}；业务正确性：{review_status}。",
             f"模型：{run_info['model']}；耗时：{run_info['elapsed_seconds']} 秒。", "",
             "## 用户职业取向", "", payload.get("preferences", ""), "", "## 决策摘要", "",
             data.get("summary") or result.get("error") or "未获得有效决策。", ""]
    for assessment in data.get("assessments", []):
        lines.extend([f"## {titles.get(assessment['target_id'], assessment['target_id'])}", "",
                      f"结论：{assessment['decision']}。{assessment['conclusion']}", ""])
        for check in assessment["checks"]:
            lines.extend([f"### {check['check_id']}：{check['requirement']}", "",
                          f"类型：{check['kind']}；要求：{check['importance']}；判断：{check['status']}。",
                          check["reasoning"], ""])
            for label, field in (("岗位原文", "job_evidence"), ("学生原文", "candidate_evidence")):
                quotes = check.get(field, [])
                lines.extend(f"- {label} [{item['source_id']}]：{item['quote']}" for item in quotes)
                if not quotes:
                    lines.append(f"- {label}：未提供；不能据此推断学生不会。")
            lines.append("")
    if data.get("comparison"):
        lines.extend(["## 方向比较", "", data["comparison"], ""])
    lines.extend(["## 下一步行动", ""])
    for action in data.get("next_actions", []):
        lines.extend([f"- [{action['target_id']} / {action['check_id']}] {action['action']}",
                      f"  产物：{action['deliverable']}；验收：{action['acceptance_criteria']}"])
    lines.extend(["", "## 关键追问", "", *[f"- {item}" for item in data.get("followup_questions", [])],
                  "", "## 自动检查与限制", "", verification["note"]])
    limits = list(dict.fromkeys(result.get("input_limitations", []) + data.get("limitations", [])))
    lines.extend(f"- {item}" for item in verification["errors"] + limits)
    for failure in verification.get("upstream_errors", []):
        lines.append(f"- 上游岗位分析 [{failure['target_id']} / {failure['status']}]：{failure['error']}")
    if verification["unassessed_target_ids"]:
        lines.append(f"- 未完成评估的目标：{', '.join(verification['unassessed_target_ids'])}")
    lines.extend(["", "## 人工复核", "", "在 review.json 中记录：引文是否支持判断、缺少证据是否被误判为能力不足、",
                  "硬条件是否遗漏、职业取向是否被尊重、行动是否具体可执行。", "",
                  "## 本次可追溯来源", ""])
    for source in result.get("sources", []):
        lines.append(f"- {source['source_id']}：{source['kind']}；{source.get('file_path') or '用户输入'}")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_openai import ChatOpenAI
    from experiments.news_advisor.agents import CareerDecisionAgent, JobAnalysisAgent, ResumeAnalysisAgent
    from experiments.news_advisor.config import get_ai_config
    from experiments.news_advisor.prompt.career_decision import CAREER_DECISION_PROMPT, CAREER_DIRECTION_PROMPT
    from experiments.news_advisor.schemas.career_decision import CareerDecisionInput, CareerDirectionPlan

    settings = get_ai_config("chat")
    model = ChatOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=0, timeout=args.timeout, max_retries=0,
        extra_body={"thinking": {"type": "disabled"}, "max_tokens": 16384},
    )
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
    output = args.output_dir or Path(__file__).resolve().parent / "output" / "career_decision" / stamp
    output.mkdir(parents=True, exist_ok=True)
    started, stage = perf_counter(), "准备输入"
    run_info = {"model": settings.model, "mode": "replay" if args.replay_input else "end_to_end",
                "prompt_sha256": hashlib.sha256(CAREER_DECISION_PROMPT.encode()).hexdigest(),
                "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}

    class Capture(BaseCallbackHandler):
        document = None

        def __init__(self):
            self.calls = 0
            self.responses = []
            self.errors = []

        def on_tool_end(self, output, **kwargs):
            if isinstance(output, dict) and "markdown" in output:
                self.document = output

        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.calls += 1
            print(f"{stage}：模型调用 {self.calls}", flush=True)

        def on_llm_end(self, response, **kwargs):
            for batch in response.generations:
                for generation in batch:
                    message = getattr(generation, "message", None)
                    if message is not None:
                        self.responses.append({"stage": stage, "content": message.content,
                                               "tool_calls": getattr(message, "tool_calls", []),
                                               "invalid_tool_calls": getattr(message, "invalid_tool_calls", []),
                                               "metadata": message.response_metadata})

        def on_llm_error(self, error, **kwargs):
            self.errors.append({"stage": stage, "type": type(error).__name__})

    capture = Capture()
    config = {"callbacks": [capture]}

    async def analyze_job(title, preferences, cached=None):
        agent = JobAnalysisAgent(model, max_model_calls=args.max_model_calls,
                                 retriever=CachedJobRetriever(cached) if cached else None)
        return await agent.arun({
            "target_role": title,
            "question": f"只分析本目标的职责、必备条件和加分项，保留学历、城市、出勤和时长限定。其他方向不是本目标的要求。用户完整职业取向：{preferences}",
            "chunk_top_k": args.chunk_top_k,
        }, config=config)

    try:
        if args.replay_input:
            payload = CareerDecisionInput.model_validate(json.loads(args.replay_input.read_text(encoding="utf-8-sig"))).model_dump()
            if args.retry_failed_jobs:
                for index, target in enumerate(payload["targets"], 1):
                    cached = target["job_analysis"]
                    if cached.get("status") == "ok":
                        continue
                    stage = f"修复岗位分析 {index}/{len(payload['targets'])}"
                    # 旧输入的 title 可能是一整段偏好；用 question 保留它，避免岗位名超长。
                    title = target["title"] if len(target["title"]) <= 300 else ""
                    target["job_analysis"] = await analyze_job(title, payload["preferences"], cached if cached.get("sources") else None)
                    write_json(output / f"job_analysis_{index}.json", target["job_analysis"])
        else:
            stage = "简历读取与分析"
            print(f"{stage}……", flush=True)
            source = args.file_path.resolve()
            is_text = source.suffix.lower() in {".md", ".txt"}
            raw_resume = source.read_text(encoding="utf-8-sig").strip() if is_text else ""
            if is_text and not raw_resume:
                raise ValueError("简历正文为空")
            resume = await ResumeAnalysisAgent(model, max_model_calls=args.max_model_calls).arun({
                "raw_resume": raw_resume, "file_path": "" if is_text else str(source), "max_pages": args.max_pages,
            }, config=config)
            document = {"status": "ok", "file_path": str(source), "markdown": raw_resume, "warnings": []} if is_text else capture.document
            if document:
                resume["document"] = {key: value for key, value in document.items() if key != "markdown"}
            write_json(output / "resume_analysis.json", resume)
            write_json(output / "document.json", document or {})
            if not document or document.get("status") not in {"ok", "partial"} or not document.get("markdown", "").strip():
                raise ValueError("没有成功读取简历正文，不能验证决策 Agent")
            raw_resume = document["markdown"].strip()
            (output / "resume.md").write_text(raw_resume + "\n", encoding="utf-8")
            stage = "拆分职业方向"
            preferences = "\n".join(args.preferences)
            plan = await model.with_structured_output(CareerDirectionPlan, method="function_calling").ainvoke([
                ("system", CAREER_DIRECTION_PROMPT), ("human", preferences),
            ], config=config)
            if not isinstance(plan, CareerDirectionPlan):
                raise ValueError("职业方向提取未返回有效结构")
            directions = list(dict.fromkeys(plan.directions))
            write_json(output / "directions.json", {"preferences": preferences, "directions": directions})
            targets = []
            for index, direction in enumerate(directions, 1):
                stage = f"岗位检索与分析 {index}/{len(directions)}"
                print(f"{stage}……", flush=True)
                job = await analyze_job(direction, preferences)
                write_json(output / f"job_analysis_{index}.json", job)
                targets.append({"target_id": f"direction_{index}", "title": direction,
                                "target_type": "direction", "job_analysis": job})
            payload = CareerDecisionInput(
                raw_resume=raw_resume, preferences=preferences,
                resume_analysis=resume, targets=targets,
            ).model_dump()

        # 固定真实简历、偏好和 JD 结果，重跑时不重新读取文档或检索。
        write_json(output / "decision_input.json", payload)
        stage = "职业决策"
        print(f"{stage}……", flush=True)
        result = await CareerDecisionAgent(model, max_model_calls=args.max_model_calls).arun(payload, config=config)
        write_json(output / "decision.json", result)
        stage = "结果验证"
        verification = verify_result(payload, result)
        run_info["elapsed_seconds"] = round(perf_counter() - started, 2)
        run_info["input_sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        write_json(output / "verification.json", verification)
        write_json(output / "review.json", build_review(result))
        (output / "report.md").write_text(render_report(payload, result, verification, run_info), encoding="utf-8")
        review_status = "待人工复核" if result.get("data", {}).get("assessments") else "未生成决策，无法评估"
        print(f"自动检查：{verification['status']}；业务正确性：{review_status}。\n结果目录：{output.resolve()}")
        return 0 if verification["status"] == "passed" else 1
    except Exception as error:
        # 不保存 SDK 原始异常或请求头，避免把接口凭据写入结果文件。
        run_info.update(elapsed_seconds=round(perf_counter() - started, 2), failed_stage=stage)
        write_json(output / "error.json", {"stage": stage, "error_type": type(error).__name__})
        print(f"{stage}失败：{type(error).__name__}。已保留完成阶段的结果：{output.resolve()}", file=sys.stderr)
        return 1
    finally:
        run_info["model_calls"] = capture.calls
        write_json(output / "run_info.json", run_info)
        diagnostics = json.dumps({"model_calls": capture.calls, "responses": capture.responses,
                                  "errors": capture.errors}, ensure_ascii=False, indent=2, default=str)
        (output / "diagnostics.json").write_text(diagnostics.replace(settings.api_key, "[REDACTED]") + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="用简历与职业取向运行真实 Agent，验证证据并生成复核报告")
    parser.add_argument("file_path", type=Path, nargs="?", help="简历 PDF、DOCX、图片或 UTF-8 TXT/Markdown")
    parser.add_argument("--preferences", action="append", default=[], help="职业取向；可重复传入 1—5 个方向分别比较")
    parser.add_argument("--replay-input", type=Path, help="复用已有 decision_input.json，仅重跑决策 Agent")
    parser.add_argument("--retry-failed-jobs", action="store_true", help="重放时重试失败的岗位分析，优先复用已保存 JD，不重新 OCR")
    parser.add_argument("--output-dir", type=Path, help="结果目录；默认按时间创建")
    parser.add_argument("--max-pages", type=int, default=20, choices=range(1, 101), metavar="1..100")
    parser.add_argument("--chunk-top-k", type=int, default=8, choices=range(1, 31), metavar="1..30")
    parser.add_argument("--max-model-calls", type=int, default=5, choices=range(1, 11), metavar="1..10")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    if args.retry_failed_jobs and not args.replay_input:
        parser.error("--retry-failed-jobs 需要与 --replay-input 一起使用")
    if args.replay_input:
        if args.file_path or args.preferences:
            parser.error("重放时只传 --replay-input，不同时传新简历或职业取向")
        if not args.replay_input.is_file():
            parser.error("重放输入文件不存在")
    else:
        if not args.file_path or not args.file_path.is_file():
            parser.error("请提供存在的简历文件")
        args.preferences = [value.strip() for value in args.preferences]
        if not 1 <= len(args.preferences) <= 5 or any(not value or len(value) > 1500 for value in args.preferences):
            parser.error("请用 --preferences 提供 1—5 个非空职业取向，每项不超过 1500 字")
        if len("\n".join(args.preferences)) > 1500:
            parser.error("职业取向总长度不能超过 1500 字")
    if args.timeout <= 0:
        parser.error("timeout 必须大于 0")
    try:
        return asyncio.run(run(args))
    except ImportError as error:
        parser.exit(2, f"缺少依赖 {error.name}；请执行 python -m pip install -r experiments/requirements-resume.txt\n")
    except (OSError, ValueError) as error:
        parser.exit(2, f"配置或文件错误：{error}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
