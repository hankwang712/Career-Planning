import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import numpy as np
import pytest

from services.retrieval.hybrid import BM25, HybridIndex, identity, rrf, tokens
from services.retrieval.evaluation import ranking_metrics, evaluate
from services.retrieval.filters import filter_sources
from backend.advisor.tools.job_retrieval import LightRAGJobRetriever, JobRetrievalError
from backend.advisor.schemas.job import JobAnalysisInput


def source(key, text, title="", city="杭州"):
    return {"chunk_id": key, "file_path": f"jobs.txt#record={key}", "reference_id": "test",
            "content": f"岗位名称：{title}\n城市：{city}\n学历：本科\n岗位描述：\n{text}"}


def test_bm25_uses_term_frequency_and_inverse_document_frequency():
    scores = BM25(["Python Python Redis", "Python", "marketing sales"]).scores("Redis")
    assert scores[0] > 0 and scores[1] == scores[2] == 0
    assert "跨部" in tokens("跨部门协作")
    assert rrf([["a", "a", "b"], ["b"]])["b"] > rrf([["a", "a", "b"], ["b"]])["a"]


def test_dense_recall_finds_synonym_without_literal_overlap():
    class Embedder:
        def embed(self, texts):
            return np.asarray([[1., 0.] if "协调" in text or "cooperation" in text else [0., 1.] for text in texts])
    rows = [source("1", "cooperation"), source("2", "sales")]
    result = HybridIndex(rows, embedder=Embedder()).search("协调", limit=2)
    assert result["rankings"]["bm25"] == []
    assert result["sources"][0]["chunk_id"] == "1"
    assert result["scope"]["vector_status"] == "active"


def test_vector_failure_degrades_to_bm25_and_is_visible():
    class Broken:
        def embed(self, texts):
            raise RuntimeError("secret should not be exposed")
    result = HybridIndex([source("1", "Python")], embedder=Broken()).search("Python")
    assert result["sources"][0]["chunk_id"] == "1"
    assert result["scope"]["vector_error_type"] == "RuntimeError"
    assert "secret" not in str(result)


def test_reranker_preserves_fused_top_100_membership_and_tail():
    rows = [source(str(i), "Python " * (i % 7 + 1), title="Python" if i % 3 else "Sales") for i in range(240)]
    result = HybridIndex(rows).search("Python", role="Python", limit=240)
    assert len(result["rankings"]["final"]) == 240
    assert set(result["rankings"]["final"][:100]) == set(result["rankings"]["fused"][:100])
    assert result["rankings"]["final"][100:] == result["rankings"]["fused"][100:]
    assert all("retrieval" in row["metadata"] for row in result["sources"])


def test_title_reranking_and_duplicate_record_handling():
    rows = [source("1", "Python " * 20, title="营销"), source("2", "Python API", title="Python后端")]
    result = HybridIndex([*rows, rows[0]]).search("Python", role="Python", limit=10)
    assert result["scope"]["corpus_count"] == 2
    assert result["sources"][0]["chunk_id"] == "2"


def test_standard_skill_signal_avoids_java_backend_false_positive():
    rows = [source("1", "Java API", title="Java后端"), source("2", "Python API", title="后端开发")]
    result = HybridIndex(rows).search("Python后端 API", role="Python后端")
    assert result["sources"][0]["chunk_id"] == "2"
    assert result["sources"][0]["metadata"]["retrieval"]["skill_coverage"] == 1


def test_metrics_report_good_top10_and_bad_recall_separately():
    judgments = {str(i): 1 for i in range(100)}
    scores = ranking_metrics([str(i) for i in range(10)], judgments)
    assert scores["ndcg@10"] == 1
    assert scores["recall@100"] == .1
    assert ranking_metrics(["x", "x"], judgments)["recall@100"] == 0
    rows = [source(str(i), "Python", title="Python") for i in range(120)]
    report = evaluate(HybridIndex(rows), [{"query": "Python", "relevance": {identity(rows[0]): 3}}])
    assert set(report["mean"]["final"]) == {"ndcg@10", "recall@100"}


def test_filters_apply_before_ranking_and_unknown_is_not_zero_salary():
    rows = [source("1", "Python", city="上海"), source("2", "Python"), source("3", "Python", city="未知")]
    eligible, excluded = filter_sources(rows, {"cities": ["杭州"], "include_unknown": True, "min_monthly_salary": 10000})
    assert excluded == 1
    assert [row["chunk_id"] for row in eligible] == ["2", "3"]
    assert eligible[0]["metadata"]["unverified_conditions"] == ["salary"]
    assert filter_sources(rows, {"cities": ["杭州"], "include_unknown": False, "min_monthly_salary": 10000})[0] == []


def test_graph_disabled_and_graph_failure_both_use_filtered_local_corpus(monkeypatch):
    from backend.advisor.tools import job_retrieval as module
    monkeypatch.setattr(module, "local_sources", lambda: [source("1", "Python", city="上海"), source("2", "Python")])
    monkeypatch.setenv("JOB_RETRIEVAL_GRAPH_ENABLED", "0")
    request = JobAnalysisInput(target_role="Python", filters={"cities": ["杭州"]})
    result = asyncio.run(LightRAGJobRetriever().retrieve(request))
    assert [row["chunk_id"] for row in result["sources"]] == ["2"]
    assert result["scope"]["graph_status"] == "disabled"
    monkeypatch.setenv("JOB_RETRIEVAL_GRAPH_ENABLED", "1")
    retriever = LightRAGJobRetriever()
    monkeypatch.setattr(retriever, "_graph", AsyncMock(side_effect=JobRetrievalError("offline")))
    result = asyncio.run(retriever.retrieve(request))
    assert result["scope"]["graph_status"] == "failed"
    assert len(result["sources"]) == 1


def test_full_ledger_pagination_keeps_semantic_miss_and_filters_before_fusion(monkeypatch):
    from backend.advisor.tools import job_retrieval as module
    monkeypatch.setattr(module, "local_sources", lambda: [])
    monkeypatch.setattr(module, "ensure_lightrag", AsyncMock())
    seen = []
    def handler(request):
        import json
        payload = json.loads(request.content)
        if request.url.path == "/query/data":
            return httpx.Response(200, json={"status": "success", "data": {"chunks": []}})
        seen.append(payload)
        row = source(str(len(seen)), "Python", city="杭州" if len(seen) == 2 else "上海")
        return httpx.Response(200, json={"workspace": "career_jd", "data": {
            "sources": [row], "scope": {"candidate_pool": True, "has_more": len(seen) == 1}}})
    request = JobAnalysisInput(target_role="Python", filters={"cities": ["杭州"]})
    result = asyncio.run(LightRAGJobRetriever(transport=httpx.MockTransport(handler)).retrieve(request))
    assert [item["offset"] for item in seen] == [0, 1]
    assert all(item["candidate_pool"] for item in seen)
    assert result["sources"][0]["chunk_id"] == "2"


def test_empty_corpus_and_broken_graph_fail_explicitly(monkeypatch):
    from backend.advisor.tools import job_retrieval as module
    monkeypatch.setattr(module, "local_sources", lambda: [])
    monkeypatch.setenv("JOB_RETRIEVAL_GRAPH_ENABLED", "0")
    with pytest.raises(JobRetrievalError):
        asyncio.run(LightRAGJobRetriever().retrieve(JobAnalysisInput(target_role="Python")))


def test_workspace_mismatch_never_silently_falls_back_to_local(monkeypatch):
    from backend.advisor.tools import job_retrieval as module
    monkeypatch.setattr(module, "local_sources", lambda: [source("1", "Python")])
    monkeypatch.setenv("JOB_RETRIEVAL_GRAPH_ENABLED", "1")
    retriever = LightRAGJobRetriever()
    monkeypatch.setattr(retriever, "_graph", AsyncMock(side_effect=module.JobWorkspaceError("workspace mismatch")))
    with pytest.raises(module.JobWorkspaceError):
        asyncio.run(retriever.retrieve(JobAnalysisInput(target_role="Python")))


def test_graph_only_sources_are_preserved_when_absent_from_ledger(monkeypatch):
    from backend.advisor.tools import job_retrieval as module
    monkeypatch.setattr(module, "local_sources", lambda: [])
    monkeypatch.setenv("JOB_RETRIEVAL_GRAPH_ENABLED", "1")
    retriever = LightRAGJobRetriever()
    row = source("1", "Python")
    monkeypatch.setattr(retriever, "_graph", AsyncMock(return_value=([], {}, {"candidate_pool": True}, [row])))
    result = asyncio.run(retriever.retrieve(JobAnalysisInput(target_role="Python")))
    assert result["sources"][0]["chunk_id"] == "1"
    assert result["scope"]["graph_candidate_count"] == 1


def test_shipped_lightrag_patch_enumerates_filtered_pool_without_query_preselection(monkeypatch):
    """Exercise the actual deployable patch without requiring a local LightRAG checkout."""
    import sys
    import types
    from types import SimpleNamespace
    from pydantic import BaseModel, ConfigDict
    package = types.ModuleType("pool_test")
    package.__path__ = []
    models = types.ModuleType("pool_test.models")
    class StrictModel(BaseModel):
        model_config = ConfigDict(extra="forbid")
    models.StrictModel = StrictModel
    aggregate = types.ModuleType("pool_test.aggregate")
    aggregate.chunk_id = lambda job: str(job.record)
    for name, module in (("pool_test", package), (models.__name__, models), (aggregate.__name__, aggregate)):
        monkeypatch.setitem(sys.modules, name, module)
    patch_path = Path(__file__).resolve().parents[2] / "artifacts/research/patches/career-module.patch"
    section = patch_path.read_text(encoding="utf-8").split("+++ b/lightrag/career/evidence.py\n", 1)[1]
    section = section.split("\ndiff --git ", 1)[0]
    code = "\n".join(line[1:] for line in section.splitlines() if line.startswith("+") and not line.startswith("+++"))
    module = types.ModuleType("pool_test.evidence")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(code, str(patch_path), "exec"), module.__dict__)
    class Store:
        def documents(self, raw):
            return [{"job": SimpleNamespace(record=i, salary="12k-20k", city=city, education="本科",
                     title="不同名称", text="没有查询中的技能", chunk_text="完整岗位原文", file_path=f"jobs.txt#record={i}")}
                    for i, city in enumerate(("杭州", "上海", "杭州"), 1)]
    first = module.retrieve_evidence(Store(), module.EvidenceQuery(
        target_role="semantic-only", candidate_pool=True, cities=["杭州"], limit=1))
    second = module.retrieve_evidence(Store(), module.EvidenceQuery(
        target_role="semantic-only", candidate_pool=True, cities=["杭州"], limit=1, offset=1))
    assert first["sources"][0]["chunk_id"] == "1"
    assert second["sources"][0]["chunk_id"] == "3"
    assert first["scope"]["has_more"] and not second["scope"]["has_more"]
    assert first["scope"]["metadata_excluded_count"] == 1
