import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np


class EmbeddingCache:
    def __init__(self, path, *, endpoint, model, dimension, version="1"):
        self.path = Path(path)
        self.dimension = dimension
        self.scope = json.dumps([endpoint.rstrip("/"), model, dimension, version])
        self.lock = asyncio.Lock()
        self.hits = self.misses = self.requests = 0

    def usage(self):
        return {"reused_texts": self.hits, "embedded_texts": self.misses,
                "provider_batches": self.requests}

    async def embed(self, texts, fetch, *, context="document"):
        if not texts:
            return np.empty((0, self.dimension))
        # Serialize overlapping batches so identical in-flight texts are paid for once.
        async with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=30)
            try:
                db.execute("CREATE TABLE IF NOT EXISTS embeddings "
                           "(cache_key TEXT PRIMARY KEY, vector TEXT NOT NULL)")
                keys = [hashlib.sha256(json.dumps(
                    [self.scope, context, text], ensure_ascii=False,
                    separators=(",", ":")
                ).encode()).hexdigest() for text in texts]
                found, missing = {}, {}
                for key, text in zip(keys, texts):
                    if key in found or key in missing:
                        continue
                    row = db.execute("SELECT vector FROM embeddings WHERE cache_key=?", (key,)).fetchone()
                    if row:
                        try:
                            vector = np.asarray(json.loads(row[0]), dtype=float)
                            if vector.shape != (self.dimension,) or not np.isfinite(vector).all():
                                raise ValueError("Invalid cached embedding")
                            found[key] = vector
                            continue
                        except (ValueError, TypeError):
                            pass
                    missing[key] = text
                self.hits += len(texts) - len(missing)
                if missing:
                    vectors = np.asarray(await fetch(list(missing.values())), dtype=float)
                    if vectors.shape != (len(missing), self.dimension) or not np.isfinite(vectors).all():
                        raise ValueError("Embedding response shape or values do not match the cache configuration")
                    with db:
                        db.executemany("INSERT OR REPLACE INTO embeddings VALUES (?,?)", [
                            (key, json.dumps(vector.tolist(), separators=(",", ":")))
                            for key, vector in zip(missing, vectors)
                        ])
                    found.update(zip(missing, vectors))
                    self.misses += len(missing)
                    self.requests += 1
                return np.stack([found[key] for key in keys])
            finally:
                db.close()
