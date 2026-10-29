"""按原始岗位去重计算排序指标；证据覆盖使用实际送入生成器的文本。"""

from __future__ import annotations

import math
import re


def unique_records(chunks):
    return list(dict.fromkeys(chunk["record"] for chunk in chunks))


def ranking_metrics(ranking, relevant, ks=(1, 3, 5, 10), grades=None):
    ranking = list(dict.fromkeys(ranking))
    relevant = set(relevant)
    if not relevant:
        return {}
    grades = grades or {}
    gains = {record: float(grades.get(str(record), 1)) for record in relevant}
    metrics = {}
    for k in ks:
        top = ranking[:k]
        hits = sum(record in relevant for record in top)
        metrics[f"hit@{k}"] = float(hits > 0)
        metrics[f"recall@{k}"] = hits / len(relevant)
        # 分母固定为 k，返回不足 k 个岗位时不会虚增 precision。
        metrics[f"precision@{k}"] = hits / k
        metrics[f"mrr@{k}"] = next((1 / rank for rank, record in enumerate(top, 1) if record in relevant), 0.0)
        dcg = sum((2 ** gains.get(record, 0) - 1) / math.log2(rank + 1) for rank, record in enumerate(top, 1))
        ideal = sum((2 ** gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(sorted(gains.values(), reverse=True)[:k], 1))
        metrics[f"ndcg@{k}"] = dcg / ideal if ideal else 0.0
    return metrics


def evidence_coverage(case, contexts, by_record):
    quotes = case.get("evidence_quotes", [])
    if not quotes:
        return None
    coverage = []
    for evidence in quotes:
        original = re.sub(r"\s+", "", by_record[evidence["record"]]["text"])
        quote = re.sub(r"\s+", "", evidence["quote"])
        start = original.find(quote)
        if start < 0:
            raise ValueError("评测证据与冻结原文不符")
        end = start + len(quote)
        intervals = []
        for context in contexts:
            if context["source"] != f"[JD-{evidence['record']}]":
                continue
            text = re.sub(r"\s+", "", context["text"])
            offset = context.get("start_char", 0)
            position = len(re.sub(r"\s+", "", by_record[evidence["record"]]["text"][:offset]))
            if original[position:position + len(text)] != text:
                position = original.find(text)
            if position >= 0:
                a, b = max(start, position), min(end, position + len(text))
                if a < b:
                    intervals.append((a, b))
        merged = []
        for a, b in sorted(intervals):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        coverage.append(sum(b - a for a, b in merged) / len(quote))
    return sum(coverage) / len(coverage)


def context_records(contexts):
    return list(dict.fromkeys(int(re.fullmatch(r"\[JD-(\d+)\]", item["source"])[1]) for item in contexts))


def case_metrics(case, retrieved, contexts, rows, ks):
    by_record = {row["record"]: row for row in rows}
    result = {"retrieved_" + key: value for key, value in ranking_metrics(
        unique_records(retrieved), case["relevant_records"], ks, case.get("relevance_grades")).items()}
    result.update({"context_" + key: value for key, value in ranking_metrics(
        context_records(contexts), case["relevant_records"], ks, case.get("relevance_grades")).items()})
    result["evidence_span_recall"] = evidence_coverage(case, contexts, by_record)
    return result
