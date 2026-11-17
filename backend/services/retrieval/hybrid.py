"""BM25 + dense retrieval + RRF, followed by an explicit feature reranker.

Reranking only permutes the first 100 fused results, preserving Recall@100.
Scores are retrieval signals, never probabilities of employment or ability.
"""
from collections import Counter, defaultdict
from math import log
import re

import numpy as np


def tokens(text):
    words = re.findall(r"[a-z][a-z0-9+#.]*|[\u4e00-\u9fff]+", str(text).casefold())
    result = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        else:
            result.append(word)
    return result


def identity(source):
    path = source.get("file_path", "")
    return path if re.search(r"#record=\d+$", path) else source["chunk_id"]


def title(source):
    match = re.search(r"(?:岗位名称|职位名称)[：:]\s*([^\n]+)", source["content"])
    return match[1] if match else source.get("metadata", {}).get("title", "")


class BM25:
    def __init__(self, texts, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.lengths, self.postings = [], defaultdict(list)
        for index, text in enumerate(texts):
            counts = Counter(tokens(text))
            self.lengths.append(sum(counts.values()))
            for term, count in counts.items():
                self.postings[term].append((index, count))
        self.average = sum(self.lengths) / max(1, len(self.lengths)) or 1

    def scores(self, query):
        result = np.zeros(len(self.lengths), dtype=np.float64)
        n = len(self.lengths)
        for term in set(tokens(query)):
            rows = self.postings.get(term, ())
            idf = log(1 + (n - len(rows) + 0.5) / (len(rows) + 0.5))
            for index, frequency in rows:
                norm = self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average)
                result[index] += idf * frequency * (self.k1 + 1) / (frequency + norm)
        return result


def rrf(rankings, constant=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, identifier in enumerate(dict.fromkeys(ranking), 1):
            scores[identifier] += 1 / (constant + rank)
    return dict(scores)


class HybridIndex:
    def __init__(self, sources, *, embedder=None, vector_cache=None):
        # Whole local/ledger records supersede partial graph chunks with the same record key.
        self.sources = list({identity(item): item for item in sources}.values())
        self.keys = [identity(item) for item in self.sources]
        self.bm25 = BM25([item["content"] for item in self.sources])
        self.embedder, self.vector_cache = embedder, vector_cache

    def search(self, query, *, role="", limit=10, graph_ranking=(), depth=200):
        if not self.sources:
            return {"sources": [], "scope": {"ranking_method": "bm25_rrf_features", "candidate_count": 0,
                    "corpus_count": 0, "vector_status": "not_configured"},
                    "rankings": {"bm25": [], "vector": [], "fused": [], "final": []}}
        depth = max(depth, limit, 100)
        lexical = self.bm25.scores(query)
        bm25_order = [self.keys[i] for i in np.argsort(-lexical, kind="stable") if lexical[i] > 0][:depth]
        dense, vector_order, failure = np.zeros(len(self.sources)), [], None
        if self.embedder is not None:
            try:
                documents = [item["content"] for item in self.sources]
                matrix = (self.vector_cache.embed(documents) if self.vector_cache else self.embedder.embed(documents))
                vector = self.embedder.embed([query])[0]
                dense = np.asarray(matrix, dtype=np.float32) @ np.asarray(vector, dtype=np.float32)
                if dense.shape != lexical.shape or not np.isfinite(dense).all():
                    raise ValueError("Invalid embedding matrix")
                dense = np.clip(dense, -1, 1)
                vector_order = [self.keys[i] for i in np.argsort(-dense, kind="stable")][:depth]
            except Exception as error:
                failure = type(error).__name__
        available = set(self.keys)
        graph_order = list(dict.fromkeys(key for key in graph_ranking if key in available))[:depth]
        rankings = [ranking for ranking in (bm25_order, vector_order, graph_order) if ranking]
        fused = rrf(rankings)
        by_key = dict(zip(self.keys, range(len(self.keys))))
        order = sorted(fused, key=lambda key: (-fused[key], key))
        role_tokens = set(tokens(role or query))
        query_tokens = set(tokens(query))
        from ..skills.taxonomy import load_taxonomy
        taxonomy = load_taxonomy()
        query_skills = {skill.id for skill in taxonomy.find_in_text(query) if skill.category != "domain"}
        max_bm25, max_rrf = max(lexical.max(), 1e-12), max(fused.values(), default=1)
        features = {}
        for key in order:
            i = by_key[key]
            heading = len(role_tokens & set(tokens(title(self.sources[i])))) / max(1, len(role_tokens))
            coverage = len(query_tokens & set(tokens(self.sources[i]["content"]))) / max(1, len(query_tokens))
            document_skills = {skill.id for skill in taxonomy.find_in_text(self.sources[i]["content"])} if query_skills else set()
            skill_coverage = len(query_skills & document_skills) / len(query_skills) if query_skills else None
            # All factors are in [0,1]; the model never modifies these scores or the ranking.
            score = ((0.45 if query_skills else 0.65) * fused[key] / max_rrf + 0.20 * heading
                     + 0.20 * (skill_coverage or 0) + 0.05 * lexical[i] / max_bm25
                     + 0.05 * max(0, float(dense[i])) + 0.05 * coverage)
            features[key] = {"bm25": round(float(lexical[i]), 6),
                             "cosine": round(float(dense[i]), 6) if vector_order else None,
                             "rrf": round(fused[key], 8), "title_coverage": round(heading, 6),
                             "query_coverage": round(coverage, 6), "skill_coverage": skill_coverage,
                             "score": round(score, 8)}
        # Never let a reranker improve top 10 by dropping members of the fused top 100.
        window = 100
        ranked = sorted(order[:window], key=lambda key: (-features[key]["score"], key)) + order[window:]
        output = []
        for rank, key in enumerate(ranked[:limit], 1):
            source = self.sources[by_key[key]]
            output.append({**source, "metadata": {**source.get("metadata", {}),
                           "retrieval": {**features[key], "rank": rank}}})
        return {"sources": output, "scope": {
            "ranking_method": "bm25_dense_rrf_features" if vector_order else "bm25_rrf_features",
            "candidate_count": len(order), "corpus_count": len(self.sources),
            "bm25_candidate_count": len(bm25_order), "vector_candidate_count": len(vector_order),
            "graph_candidate_count": len(graph_order), "candidate_depth": depth,
            "rerank_window": window, "vector_status": "failed" if failure else ("active" if vector_order else "not_configured"),
            "vector_error_type": failure, "rrf_constant": 60,
            "score_meaning": "retrieval relevance signals; not calibrated probabilities",
        }, "rankings": {"bm25": bm25_order, "vector": vector_order, "fused": order, "final": ranked}}
