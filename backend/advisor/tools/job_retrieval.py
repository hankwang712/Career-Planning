"""Metadata-first hybrid retrieval; LightRAG is an optional additional channel."""
import asyncio
from functools import lru_cache
import hashlib
import os
import re
from pathlib import Path

import httpx

from ..config import JobRAGConfig, get_job_rag_config
from ..runtime import LightRAGStartupError, ensure_lightrag
from ..schemas.job import JobAnalysisInput, JobSource
from ...services.retrieval.filters import filter_sources
from ...services.retrieval.hybrid import HybridIndex, identity
from ...services.skills.embeddings import CachedEmbeddings, default_embedder


class JobRetrievalError(RuntimeError):
    """Safe retrieval failure without provider bodies or credentials."""


class JobWorkspaceError(JobRetrievalError):
    """A workspace mismatch must not silently switch data sources."""


def source_path():
    return Path(os.environ.get("JOB_JD_SOURCE_PATH") or Path(__file__).resolve().parents[3] / "job_descriptions.txt")


@lru_cache(maxsize=2)
def _local_sources(path_text, modified):
    from artifacts.research.job_graph import iter_job_documents
    return [{"chunk_id": "local-jd-" + hashlib.sha256(doc.text.encode()).hexdigest()[:32],
             "file_path": Path(path_text).as_posix() + f"#record={doc.index}", "reference_id": "local_export",
             "content": f"招聘记录内部键：{doc.document_id}\n{doc.text}"}
            for doc in iter_job_documents(Path(path_text))]


def local_sources():
    path = source_path()
    try:
        return _local_sources(str(path.resolve()), path.stat().st_mtime_ns)
    except (OSError, ValueError):
        return []


def _search(sources, request, graph_ranking=(), limit=None):
    embedder = default_embedder()
    index = HybridIndex(sources, embedder=embedder,
                        vector_cache=CachedEmbeddings(embedder) if embedder else None)
    role = re.sub(r"工程师|实习生|方向|高级|资深|招聘", " ", request.target_role)
    query = "\n".join(part for part in (role, request.question) if part.strip())
    return index.search(query or request.target_role, role=role,
                        limit=limit or request.chunk_top_k, graph_ranking=graph_ranking)


def local_job_candidates(request, limit=3):
    eligible, _ = filter_sources(local_sources(), request.filters.model_dump())
    return _search(eligible, request, limit=limit)["sources"]


class LightRAGJobRetriever:
    def __init__(self, settings: JobRAGConfig | None = None, *, transport=None):
        self.settings = settings or get_job_rag_config()
        self.transport = transport

    async def _graph(self, request):
        headers = {"X-API-Key": self.settings.api_key} if self.settings.api_key else {}
        async with httpx.AsyncClient(base_url=self.settings.base_url + "/", headers=headers,
            timeout=self.settings.timeout, trust_env=False, transport=self.transport) as client:
            await ensure_lightrag(client, self.settings)
            response = await client.post("query/data", json={
                "query": request.retrieval_query(), "mode": request.mode,
                "top_k": request.top_k, "chunk_top_k": 100,
                "max_entity_tokens": 2000, "max_relation_tokens": 2000,
                "max_total_tokens": 12000, "enable_rerank": False, "include_references": True})
            response.raise_for_status()
            raw = response.json()
            if raw.get("status") != "success" and not (
                raw.get("status") == "failure" and raw.get("metadata", {}).get("failure_reason") == "no_results"):
                raise JobRetrievalError("LightRAG 未成功完成检索")
            data = raw.get("data") or {}
            graph = [JobSource.model_validate(row).model_dump() for row in data.get("chunks", []) if row.get("content", "").strip()]
            ledger, offset, seen = [], 0, set()
            while True:
                response = await client.post("career/evidence", json={
                    "target_role": request.target_role or request.question,
                    "question": request.question, **request.filters.model_dump(),
                    "candidate_pool": True, "offset": offset, "limit": 1000})
                if response.status_code in {404, 422}:
                    return graph, data, {"ledger_status": "upgrade_required"}, graph
                response.raise_for_status()
                envelope = response.json()
                if envelope.get("workspace") != self.settings.workspace:
                    raise JobWorkspaceError("岗位事实库工作空间与报告配置不一致")
                page = envelope["data"]
                if not page.get("scope", {}).get("candidate_pool"):
                    raise JobRetrievalError("岗位服务未返回完整候选，请更新职业模块补丁")
                rows = [JobSource.model_validate(row).model_dump() for row in page["sources"]]
                keys = {identity(row) for row in rows}
                if seen & keys:
                    raise JobRetrievalError("岗位事实库分页包含重复记录，请重试")
                seen.update(keys)
                ledger.extend(rows)
                offset += len(rows)
                if not page["scope"].get("has_more"):
                    return ledger, data, page["scope"], graph
                if not rows:
                    raise JobRetrievalError("岗位事实库分页未前进")

    async def retrieve(self, request: JobAnalysisInput) -> dict:
        local = await asyncio.to_thread(local_sources)
        graph, graph_hits, graph_rank, data, graph_scope, graph_error = [], [], [], {}, {}, None
        enabled = os.environ.get("JOB_RETRIEVAL_GRAPH_ENABLED", "1").casefold() not in {"0", "false", "no"}
        if enabled:
            try:
                graph, data, graph_scope, graph_hits = await self._graph(request)
                graph_rank = [identity(source) for source in graph_hits]
            except JobWorkspaceError:
                raise
            except (JobRetrievalError, LightRAGStartupError, httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                graph_error = type(error).__name__
                if not local:
                    raise JobRetrievalError("岗位图检索不可用，且没有本地 JD 语料；请检查服务或 JOB_JD_SOURCE_PATH") from error
        elif not local:
            raise JobRetrievalError("已关闭岗位图检索，且没有本地 JD 语料；请配置 JOB_JD_SOURCE_PATH")
        combined = {identity(source): source for source in [*graph_hits, *local, *graph]}
        eligible, excluded = filter_sources(list(combined.values()), request.filters.model_dump())
        result = await asyncio.to_thread(_search, eligible, request, graph_rank)
        sources = result["sources"]
        scope = {**graph_scope, **result["scope"], "workspace": self.settings.workspace,
                 "mode": request.mode, "filters": request.filters.model_dump(),
                 "chunk_count": len(sources), "retrieved_chunk_count": result["scope"]["candidate_count"],
                 "jd_record_count": sum("#record=" in source["file_path"] for source in sources),
                 "unidentified_source_count": sum("#record=" not in source["file_path"] for source in sources),
                 "local_export_candidates": sum(source["reference_id"] == "local_export" for source in sources),
                 "metadata_filters_applied": True, "metadata_excluded_count": excluded,
                 "graph_status": "failed" if graph_error else ("active" if enabled else "disabled"),
                 "graph_error_type": graph_error,
                 "retrieval_methods": ["bm25", "rrf", "feature_rerank"]
                      + (["dense"] if result["scope"].get("vector_status") == "active" else [])
                      + (["lightrag"] if graph_rank else []),
                 "entity_count": len(data.get("entities", [])), "relationship_count": len(data.get("relationships", [])),
                 "description": "本次检索样本；排序分数不代表岗位匹配概率，未召回不代表市场不存在。",
                 "completeness": "本地与事实库来源保留整条 JD；图来源可能为片段。"}
        return {"sources": sources, "scope": scope}
