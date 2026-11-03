from __future__ import annotations

import importlib.metadata
import inspect
import os
from pathlib import Path
import re
import time

from .common import ModelAPI, Tokens, configuration, digest, model_config, write_json
from .corpus import load_corpus


def chroma_client(output: Path):
    # 禁止默认 embedding 函数下载模型，也关闭 Chroma 的匿名遥测。
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError as error:
        raise RuntimeError("请安装 experiments/requirements-rag-eval.txt 中的 Chroma 依赖") from error
    return chromadb.PersistentClient(path=str(output / "chroma"), settings=Settings(anonymized_telemetry=False))


def chunk_rows(rows, strategy: str, tokenizer: Tokens, size=512, overlap=64):
    chunks = []
    for row in rows:
        windows = tokenizer.split(row["text"], size, overlap) if strategy == "chroma_fixed" else [{
            "text": row["text"], "start_token": 0, "end_token": tokenizer.count(row["text"]),
            "start_char": 0, "end_char": len(row["text"])}]
        for order, window in enumerate(windows):
            chunks.append({"id": f"{row['id']}-{strategy}-{order}", "record": row["record"], **window})
    return chunks


def index_spec(manifest, strategy, tokenizer, size, overlap):
    spec = {"corpus_revision": manifest["corpus_revision"], "embedding": manifest["embedding"],
            "strategy": strategy, "tokenizer": tokenizer.name,
            "chunk_size": size if strategy == "chroma_fixed" else None,
            "overlap": overlap if strategy == "chroma_fixed" else 0,
            "chunker_revision": digest(inspect.getsource(Tokens.split)),
            "tokenizer_version": importlib.metadata.version("tiktoken"),
            "distance": "cosine", "document_boundary": "never_cross_records"}
    signature = digest(spec)
    return spec, signature, f"career_{strategy}_{signature[:16]}"


def build_indexes(output: Path, env_file: Path, strategies, tokenizer: Tokens,
                  size=512, overlap=64, batch_size=16, timeout=180, max_requests=1000):
    manifest, rows = load_corpus(output)
    config = model_config(configuration(env_file), "embedding")
    if config.public() != manifest["embedding"]:
        raise ValueError("当前 embedding 配置与冻结语料不同，请恢复配置或使用新实验目录")
    client = chroma_client(output)
    api = ModelAPI(config, output / "embedding_cache.sqlite3", timeout, max_requests)
    summaries = []
    try:
        for strategy in strategies:
            if not strategy.startswith("chroma_"):
                continue
            started = time.perf_counter()
            spec, signature, name = index_spec(manifest, strategy, tokenizer, size, overlap)
            chunks = chunk_rows(rows, strategy, tokenizer, size, overlap)
            collection = client.get_or_create_collection(name, embedding_function=None,
                metadata={"hnsw:space": "cosine", "benchmark_signature": signature})
            if collection.metadata.get("benchmark_signature") != signature:
                raise ValueError("Chroma 集合配置不匹配，拒绝复用")
            for offset in range(0, len(chunks), batch_size):
                batch = chunks[offset:offset + batch_size]
                existing = set(collection.get(ids=[item["id"] for item in batch], include=[])["ids"])
                pending = [item for item in batch if item["id"] not in existing]
                if pending:
                    vectors = api.embed([item["text"] for item in pending])
                    collection.upsert(ids=[item["id"] for item in pending], embeddings=vectors,
                        documents=[item["text"] for item in pending], metadatas=[{
                            "record": item["record"], "start_token": item["start_token"], "end_token": item["end_token"],
                            "start_char": item["start_char"], "end_char": item["end_char"]}
                            for item in pending])
                print(f"{strategy}: {min(offset + batch_size, len(chunks))}/{len(chunks)} chunks", flush=True)
            if collection.count() != len(chunks):
                raise ValueError("Chroma 集合条数与固定分块结果不一致")
            summary = {"spec": spec, "collection": name, "chunks": len(chunks), "signature": signature,
                       "elapsed_seconds": time.perf_counter() - started,
                       "chroma_version": importlib.metadata.version("chromadb")}
            summaries.append(summary)
            write_json(output / f"index_{strategy}.json", summary)
        write_json(output / "index_usage.json", {"requests_this_invocation": api.requests, "usage": api.usage,
            "note": "续跑会复用已有向量；此文件只记录本次进程发起的 embedding 请求"})
    finally:
        api.close()
    return summaries


class ChromaRetriever:
    def __init__(self, output, strategy, manifest, tokenizer, size, overlap, api):
        spec, signature, name = index_spec(manifest, strategy, tokenizer, size, overlap)
        self.collection = chroma_client(output).get_collection(name, embedding_function=None)
        if self.collection.metadata.get("benchmark_signature") != signature:
            raise ValueError("Chroma 索引签名不一致，请重新 index")
        self.api = api

    def retrieve(self, question, count, budget):
        started = time.perf_counter()
        vectors = self.api.embed([question], use_cache=False)
        embedded = time.perf_counter()
        result = self.collection.query(query_embeddings=vectors, n_results=min(count, self.collection.count()),
                                       include=["documents", "metadatas", "distances"])
        chunks = [{"record": metadata["record"], "id": identifier, "text": text, "distance": distance,
                   "start_char": metadata["start_char"]}
                  for identifier, metadata, text, distance in zip(result["ids"][0], result["metadatas"][0],
                        result["documents"][0], result["distances"][0])]
        return {"chunks": chunks, "seconds": time.perf_counter() - started,
                "embedding_seconds": embedded - started, "metadata": {"rerank": False, "query_embedding_cache": False}}


class LightRetriever:
    def __init__(self, values, manifest, rows, mode, timeout=180, endpoint=None, transport=None):
        import httpx
        self.client = httpx.Client(timeout=timeout, trust_env=False, transport=transport)
        self.endpoint = (endpoint or values.get("LIGHTRAG_BASE_URL") or "http://127.0.0.1:9621").rstrip("/")
        self.headers = {"X-API-Key": values["LIGHTRAG_API_KEY"]} if values.get("LIGHTRAG_API_KEY") else {}
        self.mode = mode
        self.manifest = manifest
        self.records = {row["record"]: row for row in rows}
        self.chunk_records = {chunk["id"]: row["record"] for row in rows for chunk in row["chunks"]}
        response = self.client.get(self.endpoint + "/health", headers=self.headers)
        response.raise_for_status()
        health = response.json().get("configuration", {})
        if health.get("workspace") != manifest["workspace"]:
            raise ValueError("LightRAG HTTP 服务 workspace 与 PostgreSQL 冻结快照不一致")
        # 若服务报告模型名称，则同时核对；没有报告时在结果中明确标为未验证。
        remote_model = health.get("embedding_model")
        if remote_model and remote_model != manifest["embedding"]["model"]:
            raise ValueError("LightRAG 服务 embedding 模型与 Chroma 配置不同")
        self.remote_embedding_verified = bool(remote_model)

    def close(self):
        self.client.close()

    def retrieve(self, question, count, budget):
        started = time.perf_counter()
        response = self.client.post(self.endpoint + "/query/data", headers=self.headers, json={
            "query": question, "mode": self.mode, "top_k": count, "chunk_top_k": count,
            "max_entity_tokens": 2000, "max_relation_tokens": 2000,
            "max_total_tokens": budget + 6000, "enable_rerank": False, "include_references": True})
        response.raise_for_status()
        result = response.json()
        no_results = result.get("status") == "failure" and result.get("metadata", {}).get("failure_reason") == "no_results"
        if result.get("status") != "success" and not no_results:
            raise ValueError("LightRAG 未返回成功或明确的 no_results，不能将服务错误计为没有相关资料")
        chunks = []
        for chunk in result.get("data", {}).get("chunks", []):
            if not str(chunk.get("content", "")).strip():
                continue
            record = self.chunk_records.get(chunk.get("chunk_id"))
            if record is None:
                raise ValueError("LightRAG 返回冻结快照之外的 chunk，停止比较")
            original = re.sub(r"\s+", "", self.records[record]["text"])
            if re.sub(r"\s+", "", chunk["content"]) not in original:
                raise ValueError("LightRAG chunk 内容与冻结原文不一致")
            chunks.append({"record": record, "id": chunk["chunk_id"], "text": chunk["content"],
                           "start_char": max(0, self.records[record]["text"].find(chunk["content"]))})
        return {"chunks": chunks, "seconds": time.perf_counter() - started,
                "metadata": {"mode": self.mode, "rerank": False, "server": result.get("metadata", {}),
                             "embedding_model_verified_from_health": self.remote_embedding_verified,
                             "graph_entities_returned": len(result.get("data", {}).get("entities", [])),
                             "graph_relations_returned": len(result.get("data", {}).get("relationships", [])),
                             "answer_context": "source_chunks_only_as_in_current_JobAnalysisAgent",
                             "retrieval_usage": "LightRAG 内部关键词模型与 embedding 用量未通过此接口完整暴露"}}
