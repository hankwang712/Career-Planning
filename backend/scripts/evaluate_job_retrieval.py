"""Offline evaluation: --corpus sources.jsonl --cases judgments.json [--dense].

Corpus rows use JobSource fields. Cases are a JSON array of
{query, role?, relevance: {file_path#record=N: grade}}. Grades range from 0 to 4.
Omit --corpus to evaluate the configured local JD export. --dense uses the
configured embedding endpoint; the default requires no network access.
Exit 1 on either NDCG@10 or Recall@100 regression versus BM25.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.advisor.tools.job_retrieval import local_sources
from services.retrieval.hybrid import HybridIndex
from services.retrieval.evaluation import evaluate
from services.skills.embeddings import CachedEmbeddings, default_embedder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    sources = ([json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
               if args.corpus else local_sources())
    if not sources:
        parser.error("The corpus is empty")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        parser.error("Supply at least one judged query")
    embedder = default_embedder() if args.dense else None
    if args.dense and embedder is None:
        parser.error("Embedding configuration is missing")
    index = HybridIndex(sources, embedder=embedder, vector_cache=CachedEmbeddings(embedder) if embedder else None)
    unknown = set().union(*(set(case["relevance"]) for case in cases)) - set(index.keys)
    if unknown:
        parser.error("Judgments reference documents absent from the corpus")
    report = evaluate(index, cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return int(any(row["recall_regression"] or row["ranking_regression"] or row["rerank_regression"]
                   or (args.dense and row["vector_status"] != "active") for row in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
