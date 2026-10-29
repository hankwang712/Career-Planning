"""分阶段运行检索、统一生成和 RAGAS 评分；每题结果落盘以便续跑。"""

from __future__ import annotations

from collections import Counter
import importlib.metadata
import inspect
import json
from pathlib import Path
import random
import re
import time

from .common import (ModelAPI, Tokens, configuration, digest, model_config, now, pack_context,
                     read_json, read_jsonl, safe_error, write_json, write_jsonl)
from .corpus import load_cases, load_corpus, verify_live
from .metrics import case_metrics
from .retrieval import ChromaRetriever, LightRetriever


STRATEGIES = ("lightrag_mix", "chroma_fixed", "lightrag_naive", "chroma_record")


def run_directory(output, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
        raise ValueError("run-name 只接受以字母/数字开头的短名称")
    return output / "runs" / name


def versions():
    result = {}
    for package in ("chromadb", "tiktoken", "openai", "httpx", "ragas", "datasets", "langchain-openai"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return result


def run(args):
    manifest, rows = load_corpus(args.output)
    cases = load_cases(args.dataset, rows, args.allow_draft, args.limit)
    values = configuration(args.env_file)
    embedding = model_config(values, "embedding")
    if embedding.public() != manifest["embedding"]:
        raise ValueError("embedding 配置与快照不一致")
    if args.retrieve_k < max(args.ks):
        raise ValueError("retrieve-k 不得小于要计算的最大 k")
    tokenizer = Tokens(args.tokenizer)
    config = {
        "experiment_revision": manifest["experiment_revision"], "dataset_revision": digest(cases),
        "strategies": args.strategies, "retrieve_k": args.retrieve_k, "ks": args.ks,
        "context_budget": args.context_budget, "chunk_size": args.chunk_size, "overlap": args.overlap,
        "tokenizer": args.tokenizer, "answers": args.answers, "answer_max_tokens": args.answer_max_tokens,
        "seed": args.seed, "embedding": embedding.public(), "timeout": args.timeout,
        "max_requests": args.max_requests, "versions": versions(),
        "code_revisions": {path.name: digest(path.read_text(encoding="utf-8"))
                           for path in sorted(Path(__file__).parent.glob("*.py"))},
        "answer_prompt_revision": digest(inspect.getsource(ModelAPI.answer)),
        "allow_draft": args.allow_draft,
    }
    answer_config = model_config(values, "answer") if args.answers else None
    config["answer_model"] = answer_config.public() if answer_config else None
    directory = run_directory(args.output, args.run_name)
    target = directory / "run.json"
    if target.exists() and read_json(target)["config"] != config:
        raise ValueError("该 run-name 已有不同配置或代码版本，请使用新的 --run-name")
    light_names = [name for name in args.strategies if name.startswith("lightrag_")]
    if light_names:
        verify_live(args.output, args.env_file)
    state = {"state": "running", "started_at": now(), "config": config,
             "question_ids": [case["id"] for case in cases],
             "label_status": "reviewed" if all(case.get("reviewed") for case in cases) else "draft_unreviewed",
             "notes": [
                 "共同生成器只读取来源 chunk，与当前项目 JobAnalysisAgent 行为一致；不把图谱摘要额外送给其中一组。",
                 "本对比测量检索+分块组合效果；不能直接把差异归因于图谱清理或数据库品牌。",
                 "LightRAG 服务端关键词/embedding 缓存未清除；延迟不代表统一冷启动性能。",
                 "LightRAG服务+Docker数据库与本地Chroma的部署不同；延迟反映端到端配置，不能单独归因于算法。",
                 "双方使用同一来源语料、embedding 配置、生成器和来源上下文 token 上限；k 在岗位级去重。",
                 "LightRAG 内部检索用量和历史建图成本未完整统计，不能据此宣称总成本优势。",
             ]}
    write_json(target, state)
    write_json(directory / "dataset.used.json", {"test_cases": cases})
    embedding_api = ModelAPI(embedding, args.output / "embedding_cache.sqlite3", args.timeout, args.max_requests)
    answer_api = ModelAPI(answer_config, args.output / "embedding_cache.sqlite3", args.timeout, args.max_requests) if answer_config else None
    retrievers = {}
    results = []
    try:
        for strategy in args.strategies:
            if strategy.startswith("lightrag_"):
                retrievers[strategy] = LightRetriever(values, manifest, rows, strategy.split("_", 1)[1],
                                                      args.timeout, args.endpoint)
            else:
                retrievers[strategy] = ChromaRetriever(args.output, strategy, manifest, tokenizer,
                                                      args.chunk_size, args.overlap, embedding_api)
        for number, case in enumerate(cases):
            order = list(args.strategies)
            random.Random(args.seed + number).shuffle(order)
            for strategy in order:
                path = directory / "cases" / f"{case['id']}.{strategy}.json"
                if path.exists():
                    previous = read_json(path)
                    if previous["status"] == "ok" or not args.retry_errors:
                        results.append(previous)
                        continue
                    write_json(directory / "attempts" / f"{case['id']}.{strategy}.{time.time_ns()}.json", previous)
                row = {"id": case["id"], "category": case.get("category", "custom"), "cohort": case.get("cohort", "unknown"),
                       "question": case["question"], "strategy": strategy, "reviewed": case.get("reviewed", False),
                       "answerable": case["answerable"], "status": "error", "stage": "retrieval",
                       "metrics": case_metrics(case, [], [], rows, args.ks), "contexts": []}
                try:
                    retrieved = retrievers[strategy].retrieve(case["question"], args.retrieve_k, args.context_budget)
                    contexts = pack_context(retrieved["chunks"], tokenizer, args.context_budget)
                    row.update(retrieval=retrieved, contexts=contexts,
                        context_tokens=tokenizer.count(json.dumps(contexts, ensure_ascii=False)),
                        metrics=case_metrics(case, retrieved["chunks"], contexts, rows, args.ks), status="ok")
                    if answer_api:
                        row["stage"] = "answer"
                        answer = answer_api.answer(case["question"], contexts, args.answer_max_tokens)
                        row["answer"] = answer
                        row["metrics"]["abstention_correct"] = float(answer["abstained"] == (not case["answerable"]))
                        cited = {int(record) for record in re.findall(r"\[JD-(\d+)\]", answer["answer"])}
                        supplied = {int(re.fullmatch(r"\[JD-(\d+)\]", context["source"])[1]) for context in contexts}
                        row["metrics"]["invalid_citation_rate"] = len(cited - supplied) / len(cited) if cited else None
                except Exception as error:
                    row.update(status="error", error=safe_error(error))
                write_json(path, row)
                results.append(row)
                write_jsonl(directory / "results.jsonl", sorted(results, key=lambda result: (result["id"], result["strategy"])))
                print(f"{case['id']} {strategy}: {row['status']}", flush=True)
        write_jsonl(directory / "results.jsonl", sorted(results, key=lambda result: (result["id"], result["strategy"])))
        if light_names:
            verify_live(args.output, args.env_file)
        state["state"] = "complete" if all(row["status"] == "ok" for row in results) else "complete_with_errors"
    except BaseException as error:
        state.update(state="invalid_or_incomplete", error=safe_error(error))
        raise
    finally:
        for retriever in retrievers.values():
            if hasattr(retriever, "close"):
                retriever.close()
        state.update(finished_at=now(), finished_results=len(results),
                     baseline_embedding_requests_this_invocation=embedding_api.requests,
                     answer_requests_this_invocation=answer_api.requests if answer_api else 0)
        embedding_api.close()
        if answer_api:
            answer_api.close()
        write_json(target, state)
    return {"run": str(directory), "state": state["state"], "results": len(results)}


def score(args):
    import asyncio
    import httpx
    # RAGAS 的同步 evaluate 每次都会新建事件循环。逐题续跑时共用一个循环，
    # 并在该循环中关闭异步连接，避免复用绑定到上一条样本已关闭循环的连接。
    with asyncio.Runner() as evaluation_runner, httpx.Client(timeout=args.timeout) as http_client:
        http_async_client = httpx.AsyncClient(timeout=args.timeout)
        try:
            return _score(args, evaluation_runner, http_client, http_async_client)
        finally:
            evaluation_runner.run(http_async_client.aclose())


def _score(args, evaluation_runner, http_client, http_async_client):
    import os
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    from datasets import Dataset
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import aevaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness
    from ragas.run_config import RunConfig
    from urllib.parse import urlsplit
    import math

    directory = run_directory(args.output, args.run_name)
    state = read_json(directory / "run.json")
    if state["state"] not in {"complete", "complete_with_errors"}:
        raise ValueError("检索实验未完成或快照已失效，不能评分")
    if not state["config"]["answers"]:
        raise ValueError("此运行没有生成回答，请使用新 run-name 执行 run --answers")
    _, corpus = load_corpus(args.output)
    cases = load_cases(directory / "dataset.used.json", corpus, args.allow_draft)
    by_id = {case["id"]: case for case in cases}
    results = read_jsonl(directory / "results.jsonl")
    if args.limit is not None:
        chosen = {case["id"] for case in cases[:args.limit]}
        results = [row for row in results if row["id"] in chosen]
    values = configuration(args.env_file)
    judge, embedding = model_config(values, "judge"), model_config(values, "judge_embedding")
    options = {}
    hostname = urlsplit(judge.base_url).hostname or ""
    if hostname == "deepseek.com" or hostname.endswith(".deepseek.com"):
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    llm = LangchainLLMWrapper(ChatOpenAI(model=judge.model, base_url=judge.base_url, api_key=judge.api_key,
        temperature=0, timeout=args.timeout, max_retries=0, max_tokens=args.judge_max_tokens,
        http_client=http_client, http_async_client=http_async_client, **options))
    embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=embedding.model, base_url=embedding.base_url,
        api_key=embedding.api_key, check_embedding_ctx_length=False, request_timeout=args.timeout, max_retries=0,
        http_client=http_client, http_async_client=http_async_client))
    spec = {"judge": judge.public(), "embedding": embedding.public(), "versions": versions(),
            "answer_relevancy_strictness": 1, "judge_max_tokens": args.judge_max_tokens,
            "metrics": ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]}
    metric_workers = getattr(args, "metric_workers", 1)
    if metric_workers != 1:
        spec["metric_workers"] = metric_workers
    if getattr(args, "answerable_only", False):
        spec["sample_scope"] = "answerable_only"
    scores = []
    for row in results:
        path = directory / "scores" / f"{row['id']}.{row['strategy']}.json"
        revision = digest({"spec": spec, "result": row, "case": by_id[row["id"]]})
        if path.exists():
            previous = read_json(path)
            if previous["revision"] != revision:
                raise ValueError("评分模型、题目或回答已改变；请使用新 run-name，避免混合不同评审器")
            if previous["status"] == "ok" or not args.retry_errors:
                scores.append(previous)
                continue
        result = {"id": row["id"], "strategy": row["strategy"], "revision": revision, "spec": spec,
                  "status": "skipped", "metrics": {}, "reference_is_reviewed": by_id[row["id"]].get("reviewed", False)}
        if spec.get("sample_scope") == "answerable_only" and not by_id[row["id"]]["answerable"]:
            result["reason"] = "unanswerable_requires_separate_semantic_review"
        elif row["status"] != "ok" or not row.get("answer") or not row["contexts"]:
            result["reason"] = "generation_failed_or_empty_context"
        else:
            case = by_id[row["id"]]
            if not str(case.get("ground_truth", "")).strip():
                raise ValueError(f"{row['id']} 没有可用于 ContextRecall/Precision 的参考答案")
            sample = Dataset.from_dict({"question": [row["question"]], "answer": [row["answer"]["answer"]],
                "contexts": [[item["source"] + " " + item["text"] for item in row["contexts"]]],
                "ground_truth": [case["ground_truth"]]})
            started = time.perf_counter()
            try:
                evaluated = evaluation_runner.run(aevaluate(sample,
                    metrics=[Faithfulness(), AnswerRelevancy(strictness=1), ContextRecall(), ContextPrecision()],
                    llm=llm, embeddings=embeddings, run_config=RunConfig(timeout=args.timeout, max_retries=1, max_workers=metric_workers),
                    raise_exceptions=False, show_progress=False))
                values_row = evaluated.to_pandas().iloc[0]
                result["metrics"] = {key: float(values_row[key]) if key in values_row and math.isfinite(float(values_row[key])) else None
                                     for key in spec["metrics"]}
                finite = [value for value in result["metrics"].values() if value is not None]
                result["metrics"]["ragas_mean"] = sum(finite) / 4 if len(finite) == 4 else None
                result["status"] = "ok" if len(finite) == 4 else "partial" if finite else "error"
            except Exception as error:
                result.update(status="error", error=safe_error(error))
            result["seconds"] = time.perf_counter() - started
        write_json(path, result)
        scores.append(result)
        print(f"RAGAS {row['id']} {row['strategy']}: {result['status']}", flush=True)
    write_json(directory / "score_manifest.json", {"spec": spec, "scored_at": now(),
        "async_runtime": "one_event_loop_and_explicit_client_cleanup_per_invocation",
        "self_judge": judge.model == state["config"]["answer_model"]["model"],
        "label_status": state["label_status"], "statuses": dict(Counter(item["status"] for item in scores)),
        "note": "RAGAS 多次内部调用的用量未完整计量；NaN 保存为 null，不计作0，也不以剩余指标补算完整均分。"})
    return {"scored_results": len(scores), "statuses": dict(Counter(item["status"] for item in scores))}
