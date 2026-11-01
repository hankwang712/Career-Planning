"""Rebuildable Chroma index for semantic retrieval of saved memories."""

import hashlib
import logging
import os
from pathlib import Path
import threading
import time

from openai import OpenAI

from .config import embedding_runtime

logger = logging.getLogger(__name__)


def chroma_settings():
    from chromadb.config import Settings
    options = {"chroma_api_impl": "chromadb.api.segment.SegmentAPI"} if os.name == "nt" else {}
    return Settings(anonymized_telemetry=False, **options)


class VectorMemory:
    def __init__(self, directory):
        self.directory = Path(directory) / ("python-segments" if os.name == "nt" else "rust-segments")
        self.collection = None
        self.embeddings = None
        self.model = ""
        self.retry_at = 0
        self.lock = threading.Lock()
        self.needs_reindex = False
        self.last_error = ""
        self.error_code = ""

    def status(self):
        degraded = bool(self.last_error)
        return {"state": "degraded" if degraded else "ready" if self.collection is not None else "pending",
                "message": self.last_error if degraded else "语义索引可用。" if self.collection is not None else "语义索引尚未就绪，个人资料和已保存记忆仍可使用。",
                "error_code": self.error_code if degraded else "",
                "fallback": "直接使用已保存记忆和当前工作台资料"}

    def unavailable(self, error=None, *, phase="index"):
        self.error_code = type(error).__name__ if error else "missing_embedding_config"
        if isinstance(error, ModuleNotFoundError) and error.name == "hnswlib":
            self.error_code = "missing_hnswlib"
            self.last_error = "当前运行环境缺少 hnswlib，本地 Chroma 索引未启动。"
        elif error is None:
            self.last_error = "尚未配置完整的向量模型连接。"
        elif phase == "embedding":
            self.last_error = "向量模型连接或索引同步暂不可用。"
        else:
            self.last_error = "本地 Chroma 索引暂不可用（" + self.error_code + "）。"
        self.retry_at = time.monotonic() + 60

    def ready(self):
        if self.collection is not None:
            return True
        if time.monotonic() < self.retry_at:
            return False
        with self.lock:
            if self.collection is not None:
                return True
            if time.monotonic() < self.retry_at:
                return False
            try:
                base, key, model = embedding_runtime()
                if not all((key, base, model)):
                    self.unavailable()
                    return False
                import chromadb
                client = chromadb.PersistentClient(path=str(self.directory), settings=chroma_settings())
                namespace = hashlib.sha256((base + "\n" + model).encode()).hexdigest()[:16]
                collection = client.get_or_create_collection("assistant_memory_" + namespace + "_p2",
                    embedding_function=None, metadata={"hnsw:space": "cosine"})
                self.needs_reindex = collection.count() == 0
                self.embeddings = OpenAI(api_key=key, base_url=base, timeout=20, max_retries=0)
                self.model = model
                self.collection = collection
                self.last_error, self.error_code = "", ""
                return True
            except Exception as error:
                self.collection = None
                self.unavailable(error)
                logger.warning("聊天向量索引暂不可用：%s 已保存的用户记忆仍可使用。", self.last_error)
                return False

    def search(self, owner, query, *, epoch=0):
        if time.monotonic() < self.retry_at or not self.ready():
            return []
        try:
            count = self.collection.count()
            if not count:
                return []
            vector = self.embeddings.embeddings.create(model=self.model, input=[query[:6000]]).data[0].embedding
            result = self.collection.query(query_embeddings=[vector], n_results=min(12, count),
                where={"$and": [{"owner": owner}, {"status": "active"}, {"privacy_epoch": epoch}]}, include=[])
            self.last_error, self.error_code = "", ""
            return result["ids"][0]
        except Exception as error:
            self.unavailable(error, phase="embedding")
            return []

    def sync(self, store):
        if time.monotonic() < self.retry_at or not self.ready():
            return
        if self.needs_reindex:
            store.reset_index()
            self.needs_reindex = False
        pending = store.index_pending()
        if not pending:
            return
        for owner in {row["owner"] for row in pending}:
            lease = store.begin_artifact(owner, "index")
            if not lease:
                continue
            try:
                batch = [row for row in pending if row["owner"] == owner and row["privacy_epoch"] == lease["epoch"]]
                active = [row for row in batch if row["status"] == "active"]
                removed = [row["id"] for row in batch if row["status"] != "active"]
                if removed:
                    self.collection.delete(ids=removed)
                if active:
                    docs = [f"{row['kind']} {row['key']} {row['subject']}: {row['value']}" for row in active]
                    response = self.embeddings.embeddings.create(model=self.model, input=docs)
                    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
                    if not store.artifact_valid(lease):
                        continue
                    self.collection.upsert(ids=[row["id"] for row in active], documents=docs, embeddings=vectors,
                        metadatas=[{"owner": owner, "status": "active", "revision": row["revision"], "privacy_epoch": lease["epoch"]} for row in active])
                    if not store.artifact_valid(lease):
                        self.delete_epoch(owner, lease["epoch"])
                        store.repair_artifacts(owner)
                        continue
                for row in batch:
                    store.mark_indexed(row["id"], row["revision"])
                self.last_error, self.error_code = "", ""
            except Exception as error:
                if not store.artifact_valid(lease):
                    store.repair_artifacts(owner)
                logger.warning("聊天向量索引同步稍后重试；原始记忆已经持久保存")
                self.unavailable(error, phase="embedding")
            finally:
                store.end_artifact(lease)

    def delete_epoch(self, owner, epoch):
        if self.collection is not None:
            self.collection.delete(where={"$and": [{"owner": owner}, {"privacy_epoch": epoch}]})

    def delete_owner(self, owner):
        # Remove all model namespaces without using embedding credentials or touching experiments.
        for directory in {self.directory, self.directory.parent / "python-segments", self.directory.parent / "rust-segments"}:
            if not directory.exists():
                continue
            import chromadb
            client = chromadb.PersistentClient(path=str(directory), settings=chroma_settings())
            for collection in client.list_collections():
                client.get_collection(collection.name, embedding_function=None).delete(where={"owner": owner})

    def close(self):
        with self.lock:
            if self.embeddings is not None:
                self.embeddings.close()
                self.embeddings = None
            self.collection = None
