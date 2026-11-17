"""Evaluate both ranking quality and recall against explicit relevance judgments."""
from math import log2


def ranking_metrics(ranking, judgments):
    ranking = list(dict.fromkeys(ranking))
    relevant = {key for key, grade in judgments.items() if grade > 0}
    grades = sorted(judgments.values(), reverse=True)[:10]
    ideal = sum((2 ** grade - 1) / log2(i + 2) for i, grade in enumerate(grades))
    dcg = sum((2 ** judgments.get(key, 0) - 1) / log2(i + 2) for i, key in enumerate(ranking[:10]))
    return {"ndcg@10": dcg / ideal if ideal else 0.0,
            "recall@100": len(relevant & set(ranking[:100])) / len(relevant) if relevant else 0.0,
            "judged_relevant": len(relevant)}


def evaluate(index, cases):
    """cases: [{query, role?, relevance: {source identity: nonnegative grade}}]."""
    rows = []
    for case in cases:
        judgments = case["relevance"]
        if not judgments or any(not isinstance(value, int) or not 0 <= value <= 4 for value in judgments.values()):
            raise ValueError("Each case needs relevance grades between 0 and 4")
        if not any(value > 0 for value in judgments.values()):
            raise ValueError("Each case needs a relevant document")
        result = index.search(case["query"], role=case.get("role", ""), limit=100)
        metrics = {name: ranking_metrics(ranking, judgments) for name, ranking in result["rankings"].items()}
        rows.append({"query": case["query"], "metrics": metrics,
                     "vector_status": result["scope"]["vector_status"],
                     "recall_regression": metrics["final"]["recall@100"] < metrics["bm25"]["recall@100"],
                     "ranking_regression": metrics["final"]["ndcg@10"] < metrics["bm25"]["ndcg@10"],
                     "rerank_regression": metrics["final"]["ndcg@10"] < metrics["fused"]["ndcg@10"]})
    return {"cases": rows, "mean": {name: {metric: sum(row["metrics"][name][metric] for row in rows) / max(1, len(rows))
            for metric in ("ndcg@10", "recall@100")} for name in ("bm25", "vector", "fused", "final")}}
