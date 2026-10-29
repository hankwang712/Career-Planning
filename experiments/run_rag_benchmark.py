"""同一岗位语料上的 LightRAG / Chroma RAG 对照实验。

在项目根目录运行 python -m experiments.run_rag_benchmark --help。
draft/prepare/check 不调用模型；index 会计算 Chroma 向量；run 会检索，
--answers 额外调用统一回答模型；score 调用 RAGAS 评审模型。

推荐步骤（导入与图谱优化结束后再 prepare）：
  python -m experiments.run_rag_benchmark draft --records 300 --questions 40
  python -m experiments.run_rag_benchmark prepare --expected-records 300
  python -m experiments.run_rag_benchmark index
  python -m experiments.run_rag_benchmark run --answers --allow-draft --limit 5
  python -m experiments.run_rag_benchmark score --allow-draft --limit 5
  python -m experiments.run_rag_benchmark report

人工审核：编辑 dataset.draft.json，修订参考答案/全部相关岗位/证据，
把每题 reviewed 设为 true，另存 dataset.reviewed.json。
使用 run --dataset ... --run-name reviewed --answers，不加 --allow-draft。
通过 --strategies lightrag_mix chroma_fixed lightrag_naive chroma_record 加入消融组。
各阶段自动续跑同配置的已有结果；--retry-errors 显式重试失败题。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.rag_benchmark.common import DEFAULT_OUTPUT, RESEARCH, ROOT, Tokens, safe_error


def parser():
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="实验数据目录；扩充/优化后请使用新目录保存新基线")
    shared.add_argument("--env-file", type=Path, default=RESEARCH / ".env")
    commands = root.add_subparsers(dest="command", required=True)
    draft = commands.add_parser("draft", parents=[shared], help="从本地岗位原文生成待审核题集，无模型/数据库调用")
    draft.add_argument("--input", type=Path, default=ROOT / "job_descriptions.txt")
    draft.add_argument("--records", type=int, default=300)
    draft.add_argument("--questions", type=int, default=40)
    draft.add_argument("--seed", type=int, default=42)
    draft.add_argument("--original-count", type=int, default=220)
    prepare = commands.add_parser("prepare", parents=[shared], help="只读冻结已处理岗位全文、chunks 和图谱指纹")
    prepare.add_argument("--workspace", default="career_jd")
    prepare.add_argument("--expected-records", type=int)
    index = commands.add_parser("index", parents=[shared], help="按固定 token 分块并建立 Chroma 基线，可续跑")
    run = commands.add_parser("run", parents=[shared], help="执行同语料、同回答模型的检索/回答对比")
    for child in (index, run):
        child.add_argument("--tokenizer", default="cl100k_base", help="显式固定分块与上下文预算的tokenizer")
        child.add_argument("--chunk-size", type=int, default=512)
        child.add_argument("--overlap", type=int, default=64)
        child.add_argument("--timeout", type=float, default=180)
        child.add_argument("--max-requests", type=int, default=1000, help="本次进程每种模型API的请求上限，不包含LightRAG内部调用")
    index.add_argument("--strategies", nargs="+", choices=["chroma_fixed", "chroma_record"], default=["chroma_fixed"])
    index.add_argument("--batch-size", type=int, default=16)
    run.add_argument("--strategies", nargs="+", choices=["lightrag_mix", "chroma_fixed", "lightrag_naive", "chroma_record"],
                     default=["lightrag_mix", "chroma_fixed"])
    run.add_argument("--dataset", type=Path, help="默认使用 output/dataset.draft.json")
    run.add_argument("--run-name", default="comparison")
    run.add_argument("--retrieve-k", type=int, default=20, help="每组返回的原始chunk候选上限；指标在岗位级去重")
    run.add_argument("--ks", type=int, nargs="+", default=[1, 3, 5, 10])
    run.add_argument("--context-budget", type=int, default=6000, help="双方来源上下文序列化后的共同token上限")
    run.add_argument("--answers", action="store_true", help="使用相同模型和提示词生成回答")
    run.add_argument("--answer-max-tokens", type=int, default=1200)
    run.add_argument("--endpoint", help="LightRAG HTTP 地址；默认使用现有配置")
    run.add_argument("--seed", type=int, default=42)
    score = commands.add_parser("score", parents=[shared], help="使用实际展示的上下文进行四项RAGAS评分")
    score.add_argument("--run-name", default="comparison")
    score.add_argument("--timeout", type=float, default=180)
    score.add_argument("--judge-max-tokens", type=int, default=4096)
    score.add_argument("--metric-workers", type=int, choices=(1, 2, 3, 4), default=1,
                       help="单题RAGAS指标并发数；不改变题目、评审模型或指标定义")
    score.add_argument("--answerable-only", action="store_true",
                       help="仅对可回答题计算RAGAS，不可回答题保留回答供独立语义复核")
    for child in (run, score):
        child.add_argument("--allow-draft", action="store_true", help="允许未审核题目，仅输出探索性结果")
        child.add_argument("--limit", type=int, help="只运行前N题，建议先用5题检查接口与成本")
        child.add_argument("--retry-errors", action="store_true", help="显式重试失败结果，历史失败另存attempts")
    report = commands.add_parser("report", parents=[shared], help="本地汇总HTML、JSON、CSV，不调用模型")
    report.add_argument("--run-name", default="comparison")
    check = commands.add_parser("check", parents=[shared], help="执行临时数据的离线完整性检查")
    check.add_argument("--chroma", action="store_true", help="额外测试真实本地Chroma读写，使用确定性向量")
    check.add_argument("--ragas", action="store_true", help="额外验证真实RAGAS接口与NaN处理，评审结果使用离线替身")
    return root


def main(argv=None):
    command_parser = parser()
    args = command_parser.parse_args(argv)
    for name in ("records", "questions", "batch_size", "retrieve_k", "context_budget", "answer_max_tokens", "max_requests", "timeout", "judge_max_tokens", "expected_records", "limit"):
        value = getattr(args, name, None)
        if value is not None and value <= 0:
            command_parser.error(f"{name.replace('_', '-')} 必须大于0")
    if hasattr(args, "ks") and any(k <= 0 for k in args.ks):
        command_parser.error("ks 必须为正整数")
    if hasattr(args, "chunk_size") and (args.chunk_size < 16 or not 0 <= args.overlap < args.chunk_size):
        command_parser.error("chunk-size 至少16，且 0 <= overlap < chunk-size")
    try:
        if args.command == "draft":
            from experiments.rag_benchmark.corpus import draft
            result = draft(args.output, args.input, args.records, args.questions, args.seed, args.original_count)
        elif args.command == "prepare":
            from experiments.rag_benchmark.corpus import prepare
            result = prepare(args.output, args.env_file, args.workspace, args.expected_records)
        elif args.command == "index":
            from experiments.rag_benchmark.retrieval import build_indexes
            result = build_indexes(args.output, args.env_file, args.strategies, Tokens(args.tokenizer),
                args.chunk_size, args.overlap, args.batch_size, args.timeout, args.max_requests)
        elif args.command == "run":
            from experiments.rag_benchmark.runner import run
            args.dataset = args.dataset or args.output / "dataset.draft.json"
            if len(args.strategies) != len(set(args.strategies)):
                raise ValueError("strategies 不能重复")
            result = run(args)
        elif args.command == "score":
            from experiments.rag_benchmark.runner import score
            result = score(args)
        elif args.command == "report":
            from experiments.rag_benchmark.report import report
            result = report(args)
        else:
            from experiments.rag_benchmark.checks import run_checks
            return 0 if run_checks(args.chroma, args.ragas) else 1
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, RuntimeError, FileNotFoundError) as error:
        # 这些异常由本工具生成；其他SDK异常只打印类型/HTTP状态。
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"操作失败：{safe_error(error)}。请检查依赖、服务和配置；未输出密钥或请求正文。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
