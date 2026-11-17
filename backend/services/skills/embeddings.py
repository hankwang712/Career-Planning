"""向量模型（OpenAI 兼容的 /embeddings 接口）及标准技能表的向量缓存。

模型来自 .env 的 AI_EMBEDDING_BASE_URL / AI_EMBEDDING_API_KEY / AI_EMBEDDING_MODEL；没配置时整个向量环节跳过，
技能对齐与岗位检索退回纯字面方法，结果仍然可用。
"""
import hashlib
import json
import logging
import re
import threading
import sqlite3

import numpy as np

from .. import llm_env
from ..paths import APP_DATA_DIR

logger = logging.getLogger(__name__)


def embedding_runtime():
    configured = llm_env.runtime("AI_EMBEDDING_")
    if any(configured):
        return configured  # Never mix credentials from different providers.
    values = llm_env._values()
    return tuple(str(values.get(key) or "").strip() for key in
                 ("EMBEDDING_BINDING_HOST", "EMBEDDING_BINDING_API_KEY", "EMBEDDING_MODEL"))


def embedding_input(text):
    text = str(text or " ")
    # Preserve the heading and trailing requirements of unusually long JDs.
    return text if len(text) <= 6000 else text[:3000] + "\n" + text[-2999:]


class OpenAIEmbedder:
    """批量取向量并做 L2 归一化，之后点积就是余弦相似度。"""

    def __init__(self, base_url, api_key, model, *, batch_size=32, timeout=30):
        from openai import OpenAI

        from services.llm_calls import normalize_sdk_base_url

        self.model = model
        self.namespace = hashlib.sha256(f"{base_url.rstrip('/')}:{model}".encode()).hexdigest()
        self.batch_size = batch_size
        self._client = OpenAI(api_key=api_key, base_url=normalize_sdk_base_url(base_url), timeout=timeout, max_retries=1)

    def embed(self, texts):
        texts = [embedding_input(text) for text in texts]
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            response = self._client.embeddings.create(model=self.model, input=texts[start:start + self.batch_size])
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or len(matrix) != len(texts) or not np.isfinite(matrix).all():
            raise ValueError("Invalid embedding response")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("Zero embedding")
        return matrix / np.where(norms == 0, 1, norms)


def default_embedder():
    base_url, api_key, model = embedding_runtime()
    if not (base_url and api_key and model):
        return None
    return OpenAIEmbedder(base_url, api_key, model)


def skill_text(skill):
    """给向量模型看的技能描述：名称加几个常见别名。"""
    aliases = [alias for alias in skill.aliases[:4] if alias != skill.name]
    return skill.name + (f"（{'，'.join(aliases)}）" if aliases else "")


class TaxonomyVectors:
    """标准技能表的向量，按（模型，技能表版本）缓存到运行数据目录，只在第一次使用时计算。"""

    def __init__(self, taxonomy, embedder, directory=None):
        self.taxonomy = taxonomy
        self.embedder = embedder
        self.directory = directory or (APP_DATA_DIR / "skills")
        self._lock = threading.Lock()
        self._ids = None
        self._matrix = None

    def _paths(self):
        slug = re.sub(r"[^0-9A-Za-z]+", "-", getattr(self.embedder, "model", "model"))[:40]
        namespace = getattr(self.embedder, "namespace", slug)
        digest = hashlib.sha256(f"{namespace}:{self.taxonomy.version}".encode()).hexdigest()[:12]
        return self.directory / f"vectors-{slug}-{digest}.npy", self.directory / f"vectors-{slug}-{digest}.json"

    def _ensure(self):
        if self._matrix is not None:
            return
        with self._lock:
            if self._matrix is not None:
                return
            matrix_path, ids_path = self._paths()
            if matrix_path.is_file() and ids_path.is_file():
                self._ids = json.loads(ids_path.read_text(encoding="utf-8"))
                self._matrix = np.load(matrix_path)
                return
            skills = list(self.taxonomy.skills.values())
            matrix = self.embedder.embed([skill_text(skill) for skill in skills]).astype(np.float16)
            self.directory.mkdir(parents=True, exist_ok=True)
            np.save(matrix_path, matrix)
            ids_path.write_text(json.dumps([skill.id for skill in skills], ensure_ascii=False), encoding="utf-8")
            self._ids, self._matrix = [skill.id for skill in skills], matrix

    def nearest(self, texts, limit=8):
        """每条文本最相近的技能：[[(Skill, 余弦相似度), ...], ...]。"""
        if not texts or not len(self.taxonomy):
            return [[] for _ in texts]
        self._ensure()
        queries = self.embedder.embed(list(texts))
        scores = queries @ self._matrix.astype(np.float32).T
        results = []
        for row in scores:
            top = np.argsort(-row)[:limit]
            results.append([(self.taxonomy.get(self._ids[index]), round(float(row[index]), 4)) for index in top])
        return results


class CachedEmbeddings:
    """Content-addressed vectors in local SQLite; no model secrets or source text stored."""

    def __init__(self, embedder, path=None):
        self.embedder = embedder
        self.path = path or (APP_DATA_DIR / "retrieval" / "vectors.sqlite3")
        self.namespace = getattr(embedder, "namespace", embedder.model)

    def embed(self, texts):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = [hashlib.sha256(f"{self.namespace}:{embedding_input(text)}".encode()).hexdigest() for text in texts]
        found = {}
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            for key in set(keys):
                row = db.execute("SELECT value FROM vectors WHERE key=?", (key,)).fetchone()
                if row:
                    found[key] = json.loads(row[0])
        missing = dict((key, text) for key, text in zip(keys, texts) if key not in found)
        if missing:
            matrix = self.embedder.embed(list(missing.values()))
            with sqlite3.connect(self.path, timeout=30) as db:
                for key, vector in zip(missing, matrix):
                    found[key] = np.asarray(vector, dtype=np.float32).tolist()
                    db.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?)", (key, json.dumps(found[key])))
        return np.asarray([found[key] for key in keys], dtype=np.float32)
