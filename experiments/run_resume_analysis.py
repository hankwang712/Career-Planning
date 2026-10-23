"""在项目根目录运行：python -m experiments.run_resume_analysis "简历.pdf"。"""

import argparse
import asyncio
import json
import logging
import sys
import traceback
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

# 同时支持 python -m experiments.run_resume_analysis 和直接运行此文件。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def describe_error(error: BaseException) -> dict:
    """保留异常原因链及 HTTP 诊断信息，不记录请求头或带查询参数的 URL。"""
    causes, seen = [], set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        request = getattr(current, "request", None)
        causes.append({
            "type": type(current).__name__, "module": type(current).__module__,
            "message": str(current), "status_code": getattr(current, "status_code", None),
            "request_id": getattr(current, "request_id", None) or (response.headers.get("x-request-id") if response is not None else None),
            "request_method": request.method if request is not None else None,
            "request_path": request.url.path if request is not None else None,
            "body": getattr(current, "body", None),
            "response_text": response.text if response is not None else None,
        })
        current = current.__cause__ or (current.__context__ if not current.__suppress_context__ else None)
    return {**causes[0], "causes": causes[1:], "traceback": "".join(traceback.format_exception(error))}


def render_report(result: dict) -> str:
    """生成供人工核对的摘要；全部字段及证据另存于 analysis.json。"""
    data = result.get("data", {})
    run = result["run_info"]
    lines = [
        "# 简历分析结果", "",
        f"状态：{result['status']}；模型：{run['model']}；模型调用：{run['model_calls']} 次；耗时：{run['elapsed_seconds']} 秒", "",
    ]

    def assessment(item: dict) -> None:
        lines.append(item.get("assessment", ""))
        for evidence in item.get("evidence", []):
            lines.append(f"- 证据 [{evidence['source']} / {evidence['status']}]：{evidence.get('quote') or '待补充'}")
        lines.append("")

    def issue(item: dict) -> None:
        lines.extend([f"- 问题：{item['problem']}", f"  建议：{item['suggestion']}"])
        for evidence in item["evidence"]:
            lines.append(f"  证据 [{evidence['source']} / {evidence['status']}]：{evidence.get('quote') or '待补充'}")
        if item.get("rewrite"):
            lines.append(f"  改写：{item['rewrite']}")
        for fact in item.get("missing_evidence", []):
            lines.append(f"  待补事实：{fact}")
        lines.append("")

    if result.get("error"):
        lines.extend([f"执行信息：{result['error']}", ""])
    if result.get("error_detail"):
        lines.extend([f"接口详情：{result['error_detail']['message']}", ""])
    document = result.get("document", {})
    lines.extend([f"文档读取状态：{document.get('status', '直接输入正文')}", ""])
    for warning in document.get("warnings", []):
        lines.append(f"- 读取提示：{warning}")
    if not data:
        return "\n".join(lines) + "\n"

    score = data.get("score")
    score_text = f"{score} / 100" if score is not None else "未计算（评分维度不完整）"
    lines.extend(["## 总体判断", "", data["summary"], "", f"材料描述与证据质量分：{score_text}", ""])
    for dimension in data["dimensions"]:
        lines.extend([f"### {dimension['key']}（等级 {dimension['level']} / 4）", ""])
        assessment(dimension)

    lines.extend(["## 经历分析", ""])
    for experience in data["experiences"]:
        score = experience.get("score")
        score_text = str(score) if score is not None else "未计算（评分维度不完整）"
        lines.extend([f"### {experience['name']}（{experience['experience_type']}，证据质量分 {score_text}）", ""])
        for dimension in experience["dimensions"]:
            lines.extend([f"**{dimension['key']}：{dimension['level']} / 4**", ""])
            assessment(dimension)
        for item in experience["issues"]:
            issue(item)
        for question in experience["followup_questions"]:
            lines.append(f"- 追问：{question}")
        lines.append("")

    lines.extend(["## 简历整体问题", ""])
    for item in data["issues"]:
        issue(item)
    for label, items in [
        ("修改建议", data["recommendations"]),
        ("待补充信息", data["missing_information"]),
    ]:
        lines.extend([f"## {label}", ""])
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_openai import ChatOpenAI

    from experiments.news_advisor.agents import ResumeAnalysisAgent
    from experiments.news_advisor.config import get_ai_config

    class Capture(BaseCallbackHandler):
        def __init__(self):
            self.document = None
            self.model_calls = 0
            self.errors = []
            self.responses = []
            self.requests = []
            self.seen_errors = set()

        def record_error(self, stage, error, **kwargs):
            if id(error) in self.seen_errors:
                return
            self.seen_errors.add(id(error))
            detail = {"stage": stage, "model_call": self.model_calls, "run_id": str(kwargs.get("run_id")), **describe_error(error)}
            self.errors.append(detail)
            print(f"{stage} 失败：{detail['type']}：{detail['message']}".replace(settings.api_key, "[REDACTED]"), flush=True)

        def on_tool_end(self, output, **kwargs):
            if isinstance(output, dict) and "markdown" in output:
                self.document = output
                print(f"文档读取：{output['status']}", flush=True)

        def on_chat_model_start(self, serialized, messages, **kwargs):
            self.model_calls += 1
            params = kwargs.get("invocation_params", {})
            self.requests.append({
                "model_call": self.model_calls, "run_id": str(kwargs.get("run_id")),
                "parameters": {key: params[key] for key in ("model", "max_tokens", "max_completion_tokens", "temperature", "tool_choice", "response_format", "extra_body") if key in params},
                "message_types": [[message.type for message in batch] for batch in messages],
                "tool_call_ids": [[call.get("id") for message in batch for call in getattr(message, "tool_calls", []) + getattr(message, "invalid_tool_calls", [])] for batch in messages],
                "tool_response_ids": [[message.tool_call_id for message in batch if hasattr(message, "tool_call_id")] for batch in messages],
            })
            print(f"正在分析，第 {self.model_calls} 次模型调用……", flush=True)

        def on_llm_error(self, error, **kwargs):
            self.record_error("model", error, **kwargs)

        def on_chain_error(self, error, **kwargs):
            self.record_error("agent", error, **kwargs)

        def on_tool_error(self, error, **kwargs):
            self.record_error("tool", error, **kwargs)

        def on_llm_end(self, response, **kwargs):
            for generations in response.generations:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    if message is not None:
                        self.responses.append({
                            "content": message.content,
                            "tool_calls": message.tool_calls,
                            "invalid_tool_calls": message.invalid_tool_calls,
                            "metadata": message.response_metadata,
                        })

    settings = get_ai_config("chat")

    def write_json(path: Path, value: dict) -> None:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        path.write_text(text.replace(settings.api_key, "[REDACTED]"), encoding="utf-8")

    model = ChatOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=0, timeout=args.timeout, max_retries=0,
        # ChatOpenAI 会把顶层 max_tokens 改名；兼容接口需要保留原始字段。
        extra_body={"thinking": {"type": "disabled"}, "max_tokens": args.max_tokens},
    )
    source_path = str(args.file_path.resolve())
    is_text = args.file_path.suffix.lower() in {".md", ".txt"}
    raw_resume = args.file_path.read_text(encoding="utf-8-sig").strip() if is_text else ""
    if is_text and not raw_resume:
        raise ValueError("简历正文文件为空")
    payload = {
        "file_path": "" if is_text else source_path,
        "raw_resume": raw_resume, "max_pages": args.max_pages,
        "target_role": args.target_role, "candidate_level": args.candidate_level,
        "job_description": args.jd_file.read_text(encoding="utf-8-sig") if args.jd_file else "",
        "education_context": args.education_context_file.read_text(encoding="utf-8-sig") if args.education_context_file else "",
    }
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S-%f")
    output = args.output_dir or Path(__file__).resolve().parent / "output" / "resume_analysis" / f"{args.file_path.stem}-{stamp}"
    output.mkdir(parents=True, exist_ok=True)
    capture = Capture()
    if is_text:
        capture.document = {"file_path": source_path, "status": "ok", "markdown": raw_resume, "warnings": [], "input_type": "text"}
    started = perf_counter()
    print("使用已有正文进行分析……" if is_text else "正在通过 read_document 读取简历……", flush=True)
    class RedactedFormatter(logging.Formatter):
        def format(self, record):
            return super().format(record).replace(settings.api_key, "[REDACTED]")

    handler = logging.FileHandler(output / "execution.log", encoding="utf-8")
    handler.setFormatter(RedactedFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger = logging.getLogger("experiments.news_advisor")
    logger.addHandler(handler)
    try:
        result = await ResumeAnalysisAgent(model, max_model_calls=args.max_model_calls).arun(payload, config={"callbacks": [capture]})
    except Exception as error:
        capture.record_error("runner", error)
        logger.exception("运行失败")
        result = {"agent": "resume_analysis", "status": "model_error", "data": {}, "error": f"运行失败：{type(error).__name__}"}
    finally:
        logger.removeHandler(handler)
        handler.close()
    result["run_info"] = {
        "model": settings.model, "model_calls": capture.model_calls,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "python": sys.executable,
        "versions": {name: version(name) for name in ("langchain", "langchain-core", "langchain-openai", "langgraph", "openai")},
    }
    if result["status"] != "ok" and capture.errors:
        result["error_detail"] = capture.errors[-1]
    if capture.document is not None:
        if "document" not in result:
            result["document"] = {key: value for key, value in capture.document.items() if key != "markdown"}
        write_json(output / "document.json", capture.document)
        (output / "resume.md").write_text(capture.document.get("markdown", ""), encoding="utf-8")
    write_json(output / "diagnostics.json", {"run_info": result["run_info"], "requests": capture.requests, "errors": capture.errors, "responses": capture.responses})
    write_json(output / "analysis.json", result)
    (output / "report.md").write_text(render_report(result).replace(settings.api_key, "[REDACTED]"), encoding="utf-8")
    print(f"执行状态：{result['status']}\n结果目录：{output.resolve()}")
    if result["status"] != "ok":
        print(f"详细诊断：{(output / 'diagnostics.json').resolve()}\n异常堆栈：{(output / 'execution.log').resolve()}")
    return 0 if result["status"] == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="读取简历文件并运行真实的 ResumeAnalysisAgent")
    parser.add_argument("file_path", type=Path, help="简历 PDF、DOCX、图片，或已读取的 Markdown/TXT")
    parser.add_argument("--output-dir", type=Path, help="结果目录，默认在 experiments/output/resume_analysis 下新建")
    parser.add_argument("--target-role", default="", help="可选；未填写时尝试读取简历内明确标注的意向")
    parser.add_argument("--candidate-level", default="", help="可选，如本科大三、应届硕士")
    parser.add_argument("--jd-file", type=Path, help="可选，UTF-8 JD 文本，仅作为简历诊断背景")
    parser.add_argument("--education-context-file", type=Path, help="可选，附来源和时间的学校/学科资料文本")
    parser.add_argument("--max-pages", type=int, default=20, choices=range(1, 101), metavar="1..100")
    parser.add_argument("--max-model-calls", type=int, default=5, choices=range(1, 11), metavar="1..10")
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--timeout", type=float, default=180, help="单次聊天模型请求超时秒数")
    args = parser.parse_args()
    if not args.file_path.is_file():
        parser.error("简历文件不存在或不是普通文件")
    try:
        return asyncio.run(run(args))
    except ImportError as error:
        parser.exit(2, f"缺少依赖 {error.name}，请执行：python -m pip install -r experiments/requirements-resume.txt\n")
    except (OSError, ValueError) as error:
        parser.exit(2, f"运行配置或文件错误：{error}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
