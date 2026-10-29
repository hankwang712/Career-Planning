"""指标、语料一致性、API适配和本地Chroma的确定性回归，不调用付费服务。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from .common import ModelAPI, ModelConfig, Tokens, digest, pack_context, read_json, write_json, write_jsonl
from .corpus import build_draft, corpus_revision, load_cases, normalized_documents, verify_live
from .metrics import case_metrics, evidence_coverage, ranking_metrics
from .report import paired_difference, summarize
from .retrieval import ChromaRetriever, LightRetriever, chroma_client, index_spec


def documents():
    return [{"record": 1, "id": "jd-one", "file_path": "jobs.txt#record=1", "text": "岗位名称：后端实习\n企业：甲公司\n城市：上海\n学历：本科\n岗位描述：\n使用 Python 开发 API，Docker 优先。",
             "chunks": [{"id": "chunk-one", "content": "使用 Python 开发 API，Docker 优先。"}]},
            {"record": 2, "id": "jd-two", "file_path": "jobs.txt#record=2", "text": "岗位名称：后端工程师\n企业：乙公司\n城市：杭州\n学历：本科\n岗位描述：\n使用 Java 开发服务。",
             "chunks": [{"id": "chunk-two", "content": "使用 Java 开发服务。"}]}]


class MetricChecks(unittest.TestCase):
    def test_ranking_deduplicates_records_and_penalizes_short_results(self):
        result = ranking_metrics([2, 2, 1], [1, 3], (1, 3))
        self.assertEqual(result["hit@1"], 0)
        self.assertEqual(result["recall@3"], .5)
        self.assertEqual(result["precision@3"], 1 / 3)
        self.assertEqual(result["mrr@3"], .5)
        self.assertAlmostEqual(result["ndcg@3"], (1 / math.log2(3)) / (1 + 1 / math.log2(3)))
        self.assertEqual(ranking_metrics([1], [], (1,)), {})

    def test_unicode_split_and_context_budget(self):
        tokenizer = Tokens()
        text = "中文数据🧭中包含 Python 与 API。" * 100
        chunks = tokenizer.split(text, 64, 12)
        self.assertTrue(all(tokenizer.count(item["text"]) <= 64 for item in chunks))
        self.assertTrue(all("�" not in item["text"] for item in chunks))
        self.assertEqual(chunks[0]["start_char"], 0)
        self.assertEqual(chunks[-1]["end_char"], len(text))
        self.assertTrue(all(left["end_char"] >= right["start_char"] for left, right in zip(chunks, chunks[1:])))
        packed = pack_context([{"record": 1, **item} for item in chunks], tokenizer, 128)
        self.assertLessEqual(tokenizer.count(json.dumps(packed, ensure_ascii=False)), 128)

    def test_evidence_coverage_unions_overlapping_windows(self):
        text = "甲乙丙丁戊己庚辛壬癸"
        case = {"evidence_quotes": [{"record": 1, "quote": text}]}
        contexts = [{"source": "[JD-1]", "start_char": 0, "text": text[:6]},
                    {"source": "[JD-1]", "start_char": 4, "text": text[4:]}]
        self.assertEqual(evidence_coverage(case, contexts, {1: {"text": text}}), 1)
        self.assertEqual(evidence_coverage(case, contexts[:1], {1: {"text": text}}), .6)

    def test_duplicate_text_offsets_do_not_lose_coverage(self):
        text = "重复文本重复文本重复文本"
        contexts = [{"source": "[JD-1]", "start_char": start, "text": text[start:start + 4]} for start in (0, 4, 8)]
        self.assertEqual(evidence_coverage({"evidence_quotes": [{"record": 1, "quote": text}]}, contexts, {1: {"text": text}}), 1)

    def test_pairwise_comparison_only_uses_same_case_ids(self):
        result = paired_difference({"Q1": 1, "Q2": 0}, {"Q1": .5, "Q3": 1})
        self.assertEqual(result["paired_cases"], 1)
        self.assertEqual(result["mean_delta"], .5)


class CorpusChecks(unittest.TestCase):
    def test_challenge_conditions_preserve_word_boundaries_and_explicit_constraints(self):
        from .challenge import explicit_remote, has, six_months_four_days, time_three_months
        self.assertFalse(has("LangGraph", "RAG"))
        self.assertFalse(has("Django", "Go"))
        self.assertFalse(has("JavaScript", "Java"))
        self.assertTrue(has("熟悉Dockerfile", "Docker"))
        self.assertTrue(has("RAG检索增强生成", "RAG"))
        self.assertTrue(has("K8s部署", "Kubernetes"))
        self.assertTrue(six_months_four_days({"text": "Python\n6个月的实习时间,每周至少4天"}))
        self.assertFalse(six_months_four_days({"text": "Python\n每周至少4天，连续实习4-6个月以上"}))
        self.assertFalse(six_months_four_days({"text": "Python\n每周至少4天，实习6个月以上优先"}))
        self.assertTrue(time_three_months({"text": "Python\n实习期3-6个月，每周不少于3个工作日"}))
        self.assertFalse(time_three_months({"text": "Python\n每周实习3天以上，实习期不少于6个月"}))
        self.assertFalse(explicit_remote({"text": "Python\n完成项目远程支持工作"}))
        self.assertFalse(explicit_remote({"text": "Python\n上海线下，不接受远程办公"}))
        self.assertTrue(explicit_remote({"text": "Python\n可以远程实习，优秀可以转正"}))

    def test_pending_ingestion_prevents_freezing(self):
        with self.assertRaises(ValueError):
            normalized_documents({"statuses": {"processed": 220, "processing": 1}, "documents": []})

    def test_draft_rejects_unreviewed_missing_records_and_wrong_quotes(self):
        rows = documents()
        draft = build_draft(rows, questions=5)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dataset.json"
            write_json(path, draft)
            with self.assertRaisesRegex(ValueError, "尚未人工审核"):
                load_cases(path, rows)
            self.assertEqual(len(load_cases(path, rows, True)), 5)
            draft["test_cases"][0]["relevant_records"] = [999]
            write_json(path, draft)
            with self.assertRaisesRegex(ValueError, "未入库岗位"):
                load_cases(path, rows, True)
            draft = build_draft(rows, questions=1)
            draft["test_cases"][0]["evidence_quotes"][0]["quote"] = "不存在的原文"
            write_json(path, draft)
            with self.assertRaisesRegex(ValueError, "连续原文"):
                load_cases(path, rows, True)

    def test_snapshot_changes_are_detected(self):
        rows = documents()
        manifest = {"corpus_revision": corpus_revision(rows), "workspace": "career_jd", "graph": {}, "edges": {}}
        with patch("experiments.rag_benchmark.corpus.load_corpus", return_value=(manifest, rows)), \
             patch("experiments.rag_benchmark.corpus.normalized_documents", return_value=rows), \
             patch("experiments.rag_benchmark.corpus.snapshot", return_value={"graph": {"digest": "changed"}, "edges": {}}):
            with self.assertRaisesRegex(ValueError, "已变化"):
                verify_live(Path("unused"), Path("unused.env"))


class AdapterChecks(unittest.TestCase):
    def test_answer_repairs_missing_field_and_counts_both_requests(self):
        from types import SimpleNamespace
        def response(content):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
                message=SimpleNamespace(content=content))], usage=None)
        api = ModelAPI.__new__(ModelAPI)
        api.config = ModelConfig("offline-answer", "https://other.invalid", "offline-placeholder")
        api.requests, api.max_requests = 0, 2
        create = Mock(side_effect=[response('{"answer":"资料不足"}'),
                                   response('{"answer":"资料不足","abstained":true}')])
        api.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        result = api.answer("测试问题", [], 1200)
        self.assertTrue(result["abstained"])
        self.assertEqual(result["structured_retries"], 1)
        self.assertEqual(len(result["attempt_usage"]), 2)
        self.assertEqual(api.requests, 2)

    def test_answer_request_disables_deepseek_thinking_without_changing_other_providers(self):
        from types import SimpleNamespace
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
            message=SimpleNamespace(content='{"answer":"资料不足","abstained":true}'))], usage=None)
        for host in ("https://api.deepseek.com/v1", "https://other.invalid/v1"):
            with self.subTest(host=host):
                api = ModelAPI.__new__(ModelAPI)
                api.config = ModelConfig("offline-answer", host, "offline-placeholder")
                api.requests, api.max_requests = 0, 1
                create = Mock(return_value=response)
                api.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                self.assertTrue(api.answer("测试问题", [], 1200)["abstained"])
                options = create.call_args.kwargs
                if "deepseek.com" in host:
                    self.assertEqual(options["extra_body"], {"thinking": {"type": "disabled"}})
                else:
                    self.assertNotIn("extra_body", options)
                self.assertEqual(options["max_tokens"], 1200)

    def test_lightrag_adapter_uses_actual_chunks_and_rejects_foreign_sources(self):
        import httpx
        rows = documents()
        response = {"status": "success", "data": {"chunks": [{"chunk_id": "chunk-one", "content": "使用 Python 开发 API，Docker 优先。"}]}}
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"configuration": {"workspace": "career_jd"}})
            payload = json.loads(request.content)
            self.assertFalse(payload["enable_rerank"])
            return httpx.Response(200, json=response)
        client = LightRetriever({}, {"workspace": "career_jd", "embedding": {"model": "offline"}}, rows, "mix",
                                endpoint="http://offline.invalid", transport=httpx.MockTransport(handler))
        try:
            result = client.retrieve("Python 岗位要求", 10, 1000)
            self.assertEqual(result["chunks"][0]["record"], 1)
            response["data"]["chunks"][0]["chunk_id"] = "foreign"
            with self.assertRaisesRegex(ValueError, "快照之外"):
                client.retrieve("Python 岗位要求", 10, 1000)
        finally:
            client.close()

    def test_report_retains_failures_and_null_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_json(directory / "run.json", {"state": "complete_with_errors", "label_status": "draft_unreviewed",
                "config": {"strategies": ["lightrag_mix", "chroma_fixed"]}})
            rows = []
            for strategy, status, score in (("lightrag_mix", "ok", 1), ("chroma_fixed", "error", 0)):
                rows.append({"id": "Q1", "strategy": strategy, "category": "single", "reviewed": False,
                    "status": status, "metrics": {"retrieved_recall@1": score, "ragas_mean": None}})
            write_jsonl(directory / "results.jsonl", rows)
            result = summarize(directory)
            self.assertEqual(result["summary"]["chroma_fixed"]["failure_rate"], 1)
            self.assertEqual(result["summary"]["chroma_fixed"]["metrics"]["retrieved_recall@1"]["mean"], 0)
            self.assertIsNone(result["summary"]["lightrag_mix"]["metrics"]["ragas_mean"]["mean"])

    def test_report_separates_unanswerable_cases_and_pairs_the_same_valid_answers(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            directory = output / "runs" / "fixture"
            strategies = ["lightrag_mix", "chroma_fixed"]
            write_json(directory / "run.json", {"state": "complete_with_errors", "label_status": "draft_unreviewed",
                "question_ids": ["Q1", "Q2", "Q3"], "config": {"strategies": strategies}})
            corpus = documents()
            write_jsonl(output / "corpus.jsonl", corpus)
            cases = [{"id": f"Q{i}", "question": question, "answerable": i != 3, "reviewed": False,
                "relevant_records": [i] if i != 3 else [], "ground_truth": corpus[i - 1]["text"] if i != 3 else "无法确认",
                "evidence_quotes": [{"record": i, "quote": corpus[i - 1]["text"]}] if i != 3 else []}
                for i, question in enumerate(("甲公司的后端实习有哪些要求？", "乙公司的后端工程师有哪些要求？", "今天仍招聘吗？"), 1)]
            write_json(directory / "dataset.used.json", {"test_cases": cases})
            rows = []
            for i in (1, 2, 3):
                for strategy in strategies:
                    failed = i == 2 and strategy == "chroma_fixed"
                    rows.append({"id": f"Q{i}", "strategy": strategy, "category": "unanswerable" if i == 3 else "single",
                        "question": cases[i - 1]["question"], "reviewed": False, "status": "error" if failed else "ok",
                        "stage": "answer", "metrics": {"retrieved_recall@5": 1 if i != 3 else None, "abstention_correct": 0 if i == 3 else 1},
                        "answer": {} if failed else {"answer": "无法确认招聘状态", "abstained": False}})
                    if not failed:
                        score = 0 if i == 3 else 1 if i == 2 else .2 if strategy == "lightrag_mix" else .6
                        write_json(directory / "scores" / f"Q{i}.{strategy}.json", {"id": f"Q{i}", "strategy": strategy,
                            "status": "ok", "metrics": {key: score for key in ("faithfulness", "answer_relevancy", "context_precision", "context_recall")}})
            write_jsonl(directory / "results.jsonl", rows)
            result = summarize(directory)
            pair = result["paired_answerable_comparisons"][0]["metrics"]
            self.assertEqual(pair["faithfulness"]["paired_cases"], 1)
            self.assertEqual(pair["faithfulness"]["left_mean"], .2)
            self.assertEqual(pair["faithfulness"]["right_mean"], .6)
            self.assertEqual(pair["retrieved_recall@5"]["paired_cases"], 2, "generation failure must not erase successful retrieval")
            self.assertEqual(result["answerable_summary"]["lightrag_mix"]["metrics"]["faithfulness"]["valid_cases"], 2)
            self.assertIsNone(result["unanswerable_summary"]["lightrag_mix"]["semantic_correctness"])
            self.assertNotIn("abstention_correct", result["summary"]["lightrag_mix"]["metrics"])
            self.assertEqual(len(result["audit"]["full_document_reference_ids"]), 2)
            self.assertEqual(len(result["audit"]["named_target_question_ids"]), 2)
            queue = result["audit"]["review_queue"]
            self.assertEqual(sum(item["refusal_wording_flag_conflict_hint"] for item in queue), 2)
            self.assertTrue(all(item["human_semantic_verdict"] is None for item in queue))

    def test_report_rejects_duplicate_pairs_and_missing_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_json(directory / "run.json", {"state": "complete", "label_status": "draft_unreviewed",
                "question_ids": ["Q1", "Q2"], "config": {"strategies": ["lightrag_mix"]}})
            row = {"id": "Q1", "strategy": "lightrag_mix"}
            write_jsonl(directory / "results.jsonl", [row, row])
            with self.assertRaisesRegex(ValueError, "重复"):
                summarize(directory)
            write_jsonl(directory / "results.jsonl", [row])
            with self.assertRaisesRegex(ValueError, "不完整"):
                summarize(directory)


class ChromaChecks(unittest.TestCase):
    def test_real_local_chroma_with_explicit_vectors(self):
        # Chroma/HNSW 在 Windows 会持有文件句柄；子进程退出后由父进程清理临时目录。
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-c",
                "from pathlib import Path; import sys; from experiments.rag_benchmark.checks import chroma_smoke; chroma_smoke(Path(sys.argv[1]))",
                temporary], capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])

    def test_full_benchmark_pipeline_with_real_chroma_and_offline_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "-c",
                "from pathlib import Path; import sys; from experiments.rag_benchmark.checks import pipeline_smoke; pipeline_smoke(Path(sys.argv[1]))",
                temporary], capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])


def chroma_smoke(output):
    rows, tokenizer = documents(), Tokens()
    manifest = {"corpus_revision": corpus_revision(rows), "embedding": {"model": "deterministic-test-vector"}}
    _, signature, name = index_spec(manifest, "chroma_fixed", tokenizer, 64, 8)
    client = chroma_client(output)
    collection = client.get_or_create_collection(name, embedding_function=None,
        metadata={"hnsw:space": "cosine", "benchmark_signature": signature})
    collection.upsert(ids=["one", "two"], documents=[rows[0]["text"], rows[1]["text"]],
        embeddings=[[1., 0., .1], [0., 1., .1]], metadatas=[{"record": 1, "start_char": 0}, {"record": 2, "start_char": 0}])
    class OfflineEmbedding:
        def embed(self, texts, use_cache=False):
            return [[1., 0., .1] for text in texts]
    retriever = ChromaRetriever(output, "chroma_fixed", manifest, tokenizer, 64, 8, OfflineEmbedding())
    result = retriever.retrieve("Python", 2, 1000)
    assert result["chunks"][0]["record"] == 1


def pipeline_smoke(output):
    from .common import ModelConfig
    from .retrieval import build_indexes
    from .runner import run
    from .report import report
    from experiments.run_rag_benchmark import parser
    rows = documents()
    values = {"EMBEDDING_MODEL": "offline-embedding", "EMBEDDING_BINDING_HOST": "https://offline.invalid",
              "EMBEDDING_BINDING_API_KEY": "offline-placeholder", "EMBEDDING_DIM": "3",
              "LLM_MODEL": "offline-answer", "LLM_BINDING_HOST": "https://offline.invalid", "LLM_BINDING_API_KEY": "offline-placeholder"}
    model = ModelConfig("offline-embedding", "https://offline.invalid", "offline-placeholder", 3)
    manifest = {"workspace": "career_jd", "corpus_revision": corpus_revision(rows), "experiment_revision": "offline-experiment",
                "embedding": model.public(), "graph": {}, "edges": {}}
    write_json(output / "manifest.json", manifest)
    write_jsonl(output / "corpus.jsonl", rows)
    write_json(output / "dataset.draft.json", build_draft(rows, 5))
    seen = []
    class OfflineAPI:
        def __init__(self, *args, **kwargs):
            self.requests, self.usage = 0, []
        def embed(self, texts, use_cache=True):
            self.requests += 1
            return [[1.0 if "Python" in text else .1, 1.0 if "Java" in text else .1, .1] for text in texts]
        def answer(self, question, contexts, maximum):
            self.requests += 1
            seen.append((question, contexts))
            return {"answer": "请核实具体条件 [JD-1]", "abstained": False, "seconds": .01, "usage": None}
        def close(self):
            pass
    class OfflineLight:
        def __init__(self, *args, **kwargs):
            pass
        def retrieve(self, question, count, budget):
            return {"chunks": [{"record": row["record"], "text": row["text"], "id": row["id"], "start_char": 0} for row in rows],
                    "seconds": .01, "metadata": {"test_only": True}}
        def close(self):
            pass
    with patch("experiments.rag_benchmark.retrieval.configuration", return_value=values), \
         patch("experiments.rag_benchmark.runner.configuration", return_value=values), \
         patch("experiments.rag_benchmark.retrieval.ModelAPI", OfflineAPI), \
         patch("experiments.rag_benchmark.runner.ModelAPI", OfflineAPI), \
         patch("experiments.rag_benchmark.runner.LightRetriever", OfflineLight), \
         patch("experiments.rag_benchmark.runner.verify_live", return_value=manifest):
        build_indexes(output, Path("offline.env"), ["chroma_fixed", "chroma_record"], Tokens(), 64, 8)
        args = parser().parse_args(["run", "--output", str(output), "--answers", "--allow-draft", "--chunk-size", "64",
            "--overlap", "8", "--context-budget", "128", "--strategies", "lightrag_mix", "chroma_fixed", "lightrag_naive", "chroma_record"])
        args.dataset = output / "dataset.draft.json"
        assert run(args)["state"] == "complete"
        assert len(seen) == 20
        run_path = output / "runs" / "comparison"
        (run_path / "results.jsonl").unlink()
        assert run(args)["state"] == "complete"
        assert len(seen) == 20, "resume must not regenerate cached answers"
        summary = report(args)
        assert Path(summary["report"]).is_file()
        assert len(read_json(run_path / "comparison.json")["details"]) == 20
        assert all(Tokens().count(json.dumps(context, ensure_ascii=False)) <= 128 for _, context in seen)


class RagasChecks(unittest.TestCase):
    def test_real_ragas_adapters_receive_contexts_and_preserve_nan(self):
        import os
        os.environ["RAGAS_DO_NOT_TRACK"] = "true"
        from types import SimpleNamespace
        import pandas as pd
        from .runner import score
        rows = documents()
        values = {"EMBEDDING_MODEL": "offline-embedding", "EMBEDDING_BINDING_HOST": "https://offline.invalid",
                  "EMBEDDING_BINDING_API_KEY": "offline-placeholder", "LLM_MODEL": "offline-judge",
                  "LLM_BINDING_HOST": "https://offline.invalid", "LLM_BINDING_API_KEY": "offline-placeholder"}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            directory = output / "runs" / "comparison"
            write_json(output / "manifest.json", {"corpus_revision": corpus_revision(rows)})
            write_jsonl(output / "corpus.jsonl", rows)
            write_json(directory / "run.json", {"state": "complete", "config": {"answers": True, "answer_model": {"model": "offline-answer"}},
                                               "label_status": "draft_unreviewed"})
            draft = build_draft(rows, 1)
            draft["test_cases"][0]["ground_truth"] = "REFERENCE_ONLY_NOT_CONTEXT"
            draft["test_cases"].append(build_draft(rows, 5)["test_cases"][-1])
            write_json(directory / "dataset.used.json", draft)
            write_jsonl(directory / "results.jsonl", [{"id": "Q001", "strategy": strategy, "status": "ok", "question": "Python要求？",
                "contexts": [{"source": "[JD-1]", "text": "ACTUAL_RETRIEVED_CONTEXT"}], "answer": {"answer": "有Python要求"}}
                for strategy in ("chroma_fixed", "lightrag_mix")] + [{"id": "Q005", "strategy": "chroma_fixed", "status": "ok",
                    "question": "目前还招聘吗？", "contexts": [{"source": "[JD-1]", "text": "静态岗位资料"}],
                    "answer": {"answer": "无法确认", "abstained": True}}])
            loops = []
            async def offline_evaluate(dataset, **kwargs):
                import asyncio
                loops.append(asyncio.get_running_loop())
                self.assertEqual(dataset.to_dict()["contexts"], [["[JD-1] ACTUAL_RETRIEVED_CONTEXT"]])
                self.assertEqual(dataset.to_dict()["ground_truth"], ["REFERENCE_ONLY_NOT_CONTEXT"])
                self.assertEqual(kwargs["run_config"].max_workers, 4)
                return SimpleNamespace(to_pandas=lambda: pd.DataFrame([{"faithfulness": 1., "answer_relevancy": float("nan"),
                                                                       "context_precision": .5, "context_recall": .75}]))
            with patch("experiments.rag_benchmark.runner.configuration", return_value=values), patch("ragas.aevaluate", offline_evaluate):
                result = score(SimpleNamespace(output=output, run_name="comparison", allow_draft=True, limit=None,
                    env_file=Path("offline.env"), timeout=20, judge_max_tokens=1000, retry_errors=False,
                    metric_workers=4, answerable_only=True))
            self.assertEqual(result["statuses"], {"partial": 2, "skipped": 1})
            self.assertEqual(len(loops), 2)
            self.assertIs(loops[0], loops[1], "samples must share one async event loop")
            saved = read_json(directory / "scores" / "Q001.chroma_fixed.json")
            self.assertIsNone(saved["metrics"]["answer_relevancy"])
            self.assertIsNone(saved["metrics"]["ragas_mean"])
            self.assertEqual(saved["spec"]["metric_workers"], 4)
            boundary = read_json(directory / "scores" / "Q005.chroma_fixed.json")
            self.assertEqual(boundary["reason"], "unanswerable_requires_separate_semantic_review")


def run_checks(with_chroma=False, with_ragas=False):
    suite = unittest.TestSuite()
    for cls in (MetricChecks, CorpusChecks, AdapterChecks) + ((ChromaChecks,) if with_chroma else ()) + ((RagasChecks,) if with_ragas else ()):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
