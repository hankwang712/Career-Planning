"""在项目根目录运行：python -m experiments.run_job_analysis --target-role "AI Agent 开发工程师"。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.news_advisor.config import get_ai_config
from experiments.news_advisor.schemas.job import JobAnalysisInput
from experiments.news_advisor.tools.job_retrieval import LightRAGJobRetriever


async def run(args) -> dict:
    request = JobAnalysisInput(
        target_role=args.target_role, question=args.question, mode=args.mode,
        top_k=args.top_k, chunk_top_k=args.chunk_top_k,
    )
    retriever = LightRAGJobRetriever()
    if args.retrieval_only:
        # 仅跳过最终分析；LightRAG 检索本身仍可能调用关键词模型和 embedding。
        retrieval = await retriever.retrieve(request)
        return {"status": "ok" if retrieval["sources"] else "insufficient_evidence", **retrieval}

    from langchain_openai import ChatOpenAI
    from experiments.news_advisor.agents import JobAnalysisAgent

    settings = get_ai_config("chat")
    model = ChatOpenAI(
        api_key=settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=0, timeout=args.timeout, max_retries=0,
        extra_body={"thinking": {"type": "disabled"}, "max_tokens": 8192},
    )
    return await JobAnalysisAgent(model, retriever=retriever).arun(request.model_dump())


def main() -> int:
    parser = argparse.ArgumentParser(description="复用现有 LightRAG 图谱进行岗位分析")
    parser.add_argument("--target-role", default="", help="目标岗位")
    parser.add_argument("--question", default="", help="希望分析的问题")
    parser.add_argument("--mode", choices=["mix", "hybrid", "local", "global", "naive"], default="mix")
    parser.add_argument("--top-k", type=int, default=20, help="图实体/关系或向量检索候选数量")
    parser.add_argument("--chunk-top-k", type=int, default=10, help="提供给 Agent 的 JD 文本块数量上限")
    parser.add_argument("--timeout", type=float, default=180, help="最终分析模型超时秒数；检索超时由 LIGHTRAG_TIMEOUT 配置")
    parser.add_argument("--retrieval-only", action="store_true", help="只检索，检查 JD 原文和来源，不运行最终分析模型")
    parser.add_argument("--output", type=Path, help="可选：将结果保存为一个 JSON 文件")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        # 不直接打印 SDK 异常，避免意外输出请求头或密钥。
        from experiments.news_advisor.tools.job_retrieval import JobRetrievalError
        from pydantic import ValidationError
        message = str(error) if isinstance(error, (JobRetrievalError, ValidationError)) else f"运行失败：{type(error).__name__}，请检查配置和服务"
        print(message, file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"已保存：{args.output}")
    else:
        print(text)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
