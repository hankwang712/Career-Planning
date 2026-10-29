"""生成有失败分母、配对差值和评测口径说明的本地 HTML/JSON/CSV 报告。"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from html import escape
import itertools
import math
import random
import re
from statistics import mean

from .common import now, read_json, read_jsonl, write_json, write_jsonl
from .runner import run_directory


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    left, right = math.floor(index), math.ceil(index)
    return ordered[left] + (ordered[right] - ordered[left]) * (index - left)


def paired_difference(left, right, seed=42):
    ids = sorted(set(left) & set(right))
    differences = [left[key] - right[key] for key in ids]
    if not differences:
        return {"paired_cases": 0, "mean_delta": None, "ci95": None}
    rng = random.Random(seed)
    estimates = [mean(rng.choices(differences, k=len(differences))) for _ in range(1000)]
    return {"paired_cases": len(ids), "mean_delta": mean(differences),
            "left_mean": mean(left[key] for key in ids), "right_mean": mean(right[key] for key in ids),
            "ci95": [percentile(estimates, .025), percentile(estimates, .975)],
            "note": "题目级配对 bootstrap；同源岗位的相关题目并非独立样本，区间只作探索性参考"}


RAGAS_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
PRIMARY_KEYS = ("retrieved_recall@1", "retrieved_recall@3", "retrieved_recall@5", "retrieved_recall@10", "retrieved_mrr@5",
                "retrieved_ndcg@5", "retrieved_ndcg@10", "context_recall@5", "context_recall@10", *RAGAS_KEYS)


def metric_summary(rows):
    keys = sorted({key for row in rows for key in row["metrics"]})
    result = {}
    for key in keys:
        values = [row["metrics"][key] for row in rows if finite(row["metrics"].get(key))]
        result[key] = {"mean": mean(values) if values else None, "valid_cases": len(values)}
    return result


def pair_scope(rows, strategies):
    values = defaultdict(dict)
    for row in rows:
        for key, value in row["metrics"].items():
            if finite(value):
                values[(row["strategy"], key)][row["id"]] = value
    comparisons = []
    for left, right in itertools.combinations(strategies, 2):
        keys = sorted({key for strategy, key in values if strategy in {left, right}})
        comparisons.append({"left": left, "right": right, "delta_definition": "left_minus_right",
            "metrics": {key: paired_difference(values[(left, key)], values[(right, key)]) for key in keys}})
    return comparisons


def audit_inputs(directory, rows, cases):
    """离线检查题集设计与统计口径；不替代人工语义判分。"""
    question_rows = {row["id"]: row for row in rows}
    answerable = [case for case in cases.values() if case.get("answerable", True)]
    corpus_path = directory.parents[1] / "corpus.jsonl"
    corpus = {row["record"]: row for row in read_jsonl(corpus_path)} if corpus_path.exists() else {}
    normalize = lambda text: re.sub(r"\s+", "", text).casefold()
    full_references, named_questions, full_quotes = [], [], 0
    if corpus:
        from .corpus import field, reference_text
        for case in answerable:
            sources = [corpus[record] for record in case.get("relevant_records", []) if record in corpus]
            if not sources:
                continue
            if normalize(case.get("ground_truth", "")) == normalize("\n\n".join(reference_text(row) for row in sources)):
                full_references.append(case["id"])
            if all(all(normalize(field(row["text"], prefix)) in normalize(case["question"])
                       for prefix in ("岗位名称：", "企业：")) for row in sources):
                named_questions.append(case["id"])
            full_quotes += sum(quote.get("record") in corpus and
                normalize(quote.get("quote", "")) == normalize(reference_text(corpus[quote["record"]]))
                for quote in case.get("evidence_quotes", []))
    strategies = sorted({row["strategy"] for row in rows})
    failures = [{key: row.get(key) for key in ("id", "strategy", "stage", "error")} for row in rows if row["status"] != "ok"]
    review_queue = []
    for row in rows:
        if row["answerable"] and row["status"] == "ok":
            continue
        answer = row.get("answer", {})
        text = answer.get("answer", "")
        mismatch_hint = (not row["answerable"] and answer.get("abstained") is False
            and bool(re.search(r"无法确认|不能确认|无法保证|不能保证|无法判断|不能判断|无法确定|不足以确认", text)))
        review_queue.append({"id": row["id"], "strategy": row["strategy"], "question": row.get("question", ""),
            "answerable": row["answerable"], "status": row["status"], "answer": text,
            "declared_abstained": answer.get("abstained"), "refusal_wording_flag_conflict_hint": mismatch_hint,
            "reference": cases.get(row["id"], {}).get("ground_truth", ""),
            "human_semantic_verdict": None,
            "note": "仅供人工复核；字面提示不能证明语义正确，模型布尔声明也不能代替语义判分。"})
    ceilings, recall_ceilings = {}, {}
    for k in (1, 3, 5, 10):
        counts = [len(set(case.get("relevant_records", []))) for case in answerable if case.get("relevant_records")]
        ceilings[str(k)] = mean(min(k, count) / k for count in counts) if counts else None
        recall_ceilings[str(k)] = mean(min(k, count) / count for count in counts) if counts else None
    findings = []
    if any(not case.get("reviewed", False) for case in cases.values()):
        findings.append("题集尚未全部人工审核，当前结果只适合流程检查与探索性比较。")
    if named_questions:
        findings.append(f"{len(named_questions)}/{len(answerable)} 道可回答题直接写出全部目标公司与岗位名，主要测定向查找，不能代表开放式岗位探索。")
    if full_references:
        findings.append(f"{len(full_references)} 道题使用整篇JD作参考答案，其中条件题可能包含问题未要求的事实；参考答案需按问题人工提炼。")
    if full_quotes:
        findings.append(f"{full_quotes} 条证据引文覆盖整篇JD，证据覆盖率更偏向整岗分块，不能等同于答案完整性。")
    if any(not row["answerable"] for row in rows):
        findings.append("不可回答题单独报告；其 RAGAS 原始分数不纳入可回答题对比，拒答正确性须人工核验。")
    if failures:
        findings.append(f"存在 {len(failures)} 条生成或检索失败；回答评分按两组共同有效的同题比较，失败率单独展示。")
    conflicts = sum(row["refusal_wording_flag_conflict_hint"] for row in review_queue)
    if conflicts:
        findings.append(f"{conflicts} 条回答正文含无法确认/保证等表述但声明未拒答，已加入人工复核；不能据布尔值直接判错。")
    ceiling_signals = []
    for strategy in strategies:
        selected = [row for row in rows if row["strategy"] == strategy and row["answerable"]]
        scores = [row["metrics"].get("retrieved_recall@5") for row in selected]
        valid = [value for value in scores if finite(value)]
        if valid and all(value == 1 for value in valid):
            ceiling_signals.append(strategy)
    if ceiling_signals:
        findings.append("、".join(ceiling_signals) + " 的 Recall@5 已饱和，应补充无公司名的条件筛选、相近岗位干扰及跨岗位综合题。")
    return {"questions": len(question_rows), "answerable_questions": sum(row["answerable"] for row in question_rows.values()),
        "unanswerable_questions": sum(not row["answerable"] for row in question_rows.values()),
        "reviewed_questions": sum(case.get("reviewed") is True for case in cases.values()),
        "named_target_question_ids": named_questions, "full_document_reference_ids": full_references,
        "full_document_evidence_quotes": full_quotes, "precision_label_ceiling": ceilings,
        "recall_label_ceiling": recall_ceilings,
        "failures": failures, "findings": findings, "review_queue": review_queue}


def summarize(directory):
    state = read_json(directory / "run.json")
    if state["state"] not in {"complete", "complete_with_errors"}:
        raise ValueError("实验未完成或快照失效，拒绝生成可比较的指标报告")
    rows = read_jsonl(directory / "results.jsonl")
    pairs = [(row["id"], row["strategy"]) for row in rows]
    if len(pairs) != len(set(pairs)):
        raise ValueError("结果包含重复的题目/策略，拒绝重复计入分母")
    if state.get("question_ids") is not None:
        expected = {(qid, strategy) for qid in state["question_ids"] for strategy in state["config"]["strategies"]}
        if set(pairs) != expected:
            raise ValueError("结果与本轮预期题目/策略不完整，不能生成可比较报告")
    dataset_path = directory / "dataset.used.json"
    cases = {case["id"]: case for case in read_json(dataset_path).get("test_cases", [])} if dataset_path.exists() else {}
    scores = {(item["id"], item["strategy"]): item for path in (directory / "scores").glob("*.json")
              for item in [read_json(path)]}
    groups, values = defaultdict(list), defaultdict(dict)
    detail = []
    for row in rows:
        metrics = {**row["metrics"], **(scores.get((row["id"], row["strategy"]), {}).get("metrics", {}) if row["status"] == "ok" else {})}
        if "abstention_correct" in metrics:
            metrics["abstention_flag_matches_label"] = metrics.pop("abstention_correct")
        answerable = cases.get(row["id"], {}).get("answerable", row.get("answerable", row["category"] != "unanswerable"))
        item = {**row, "metrics": metrics, "answerable": answerable}
        groups[row["strategy"]].append(item)
        detail.append({"id": row["id"], "strategy": row["strategy"], "category": row["category"],
                       "status": row["status"], "reviewed": row["reviewed"], "answerable": answerable, **metrics})
        for key, value in metrics.items():
            if finite(value):
                values[(row["strategy"], key)][row["id"]] = value
    summaries = {}
    for strategy, group in groups.items():
        keys = sorted({key for item in group for key in item["metrics"]})
        durations = [item["retrieval"]["seconds"] for item in group if item.get("retrieval")]
        summaries[strategy] = {
            "attempted_cases": len(group), "successful_cases": sum(item["status"] == "ok" for item in group),
            "failure_rate": sum(item["status"] != "ok" for item in group) / len(group),
            "metrics": {key: {"mean": mean(values[(strategy, key)].values()) if values[(strategy, key)] else None,
                              "valid_cases": len(values[(strategy, key)])} for key in keys},
            "retrieval_seconds_p50": percentile(durations, .5), "retrieval_seconds_p95": percentile(durations, .95),
            "mean_context_tokens": mean(item["context_tokens"] for item in group if "context_tokens" in item)
                                   if any("context_tokens" in item for item in group) else None,
            "score_statuses": dict(Counter(scores[(item["id"], strategy)]["status"]
                if (item["id"], strategy) in scores else "not_scored" for item in group)),
            "by_category": {},
        }
        for category in sorted({item["category"] for item in group}):
            subset = [item for item in group if item["category"] == category]
            summaries[strategy]["by_category"][category] = {
                "cases": len(subset), "metrics": {key: {
                    "mean": mean(valid) if (valid := [item["metrics"].get(key) for item in subset if finite(item["metrics"].get(key))]) else None,
                    "valid_cases": len(valid)} for key in keys}}
    comparisons = []
    for left, right in itertools.combinations(state["config"]["strategies"], 2):
        keys = sorted({key for strategy, key in values if strategy in {left, right}})
        comparisons.append({"left": left, "right": right, "delta_definition": "left_minus_right",
            "metrics": {key: paired_difference(values[(left, key)], values[(right, key)]) for key in keys}})
    enriched = [row for group in groups.values() for row in group]
    answerable_rows = [row for row in enriched if row["answerable"]]
    answerable_summary, unanswerable_summary = {}, {}
    for strategy, group in groups.items():
        selected = [row for row in group if row["answerable"]]
        unknown = [row for row in group if not row["answerable"]]
        declared = [row["answer"]["abstained"] for row in unknown if row["status"] == "ok" and
                    type(row.get("answer", {}).get("abstained")) is bool]
        answerable_summary[strategy] = {"attempted_cases": len(selected),
            "successful_cases": sum(row["status"] == "ok" for row in selected), "metrics": metric_summary(selected)}
        unanswerable_summary[strategy] = {"attempted_cases": len(unknown),
            "successful_cases": sum(row["status"] == "ok" for row in unknown),
            "declared_abstentions": sum(declared), "valid_declarations": len(declared),
            "declared_abstention_rate": mean(declared) if declared else None, "semantic_correctness": None}
    audit = audit_inputs(directory, enriched, cases)
    return {"report_version": 2, "generated_at": now(), "label_status": state["label_status"], "run": state,
            "summary": summaries, "paired_comparisons": comparisons, "details": detail,
            "summary_scope": "legacy_mixed_categories_diagnostics_only",
            "answerable_summary": answerable_summary, "unanswerable_summary": unanswerable_summary,
            "paired_answerable_comparisons": pair_scope(answerable_rows, state["config"]["strategies"]),
            "paired_answerable_by_category": {category: pair_scope(
                [row for row in answerable_rows if row["category"] == category], state["config"]["strategies"])
                for category in sorted({row["category"] for row in answerable_rows})},
            "audit": audit,
            "metric_notes": [
                "Recall/MRR/NDCG/Precision 均按原始岗位 record 去重；不足k条仍以k为Precision分母。",
                "retrieved_* 是返回候选，context_* 是共同token预算后实际交给回答模型的岗位。",
                "检索失败的可回答题以0计入排序指标；不可回答题不计算这些指标。",
                "evidence_span_recall 是标注引文字符范围的覆盖率，不是 RAGAS ContextRecall。",
                "RAGAS失败或NaN为null，并单独报告有效题数；ragas_mean仅在四项均有效时计算。",
                "原abstention_correct更名为abstention_flag_matches_label，仅衡量声明与标签的一致性，不是语义正确率。invalid_citation_rate不验证语义支持。",
                "主表仅比较可回答题，每个指标使用各组共同有效的同题；检索成功但生成失败的题仍参与检索评估。",
                "不可回答题的RAGAS原始分数仅供诊断。AnswerRelevancy会惩罚noncommittal回答，不能据此把正确的无法确认判为质量差。",
                "ragas_mean是四项分数的自定义简单平均，不是标准RAGAS总分；混合题型均值不用于判断优劣。",
                "未经人工审核的草稿只能用于探索性比较，不代表真实业务准确率。",
                "图谱清理前的基线没有保存时，本实验无法反推清理带来的增益。",
            ]}


def report(args):
    directory = run_directory(args.output, args.run_name)
    data = summarize(directory)
    write_json(directory / "comparison.json", data)
    write_json(directory / "audit.json", data["audit"])
    write_jsonl(directory / "review_queue.jsonl", data["audit"]["review_queue"])
    detail = data["details"]
    identity = ["id", "strategy", "category", "status", "reviewed", "answerable"]
    columns = identity + sorted(set().union(*(set(row) for row in detail)) - set(identity))
    with (directory / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(detail)
    strategies = data["run"]["config"]["strategies"]
    keys = sorted({key for summary in data["summary"].values() for key in summary["metrics"]})
    def number(value):
        return f"{value:.4f}" if finite(value) else "—"
    labels = {"retrieved_recall@1": "岗位召回 Recall@1", "retrieved_recall@3": "岗位召回 Recall@3",
        "retrieved_recall@5": "岗位召回 Recall@5", "retrieved_recall@10": "岗位召回 Recall@10", "retrieved_mrr@5": "首个相关岗位 MRR@5",
        "retrieved_ndcg@5": "岗位排序 NDCG@5", "retrieved_ndcg@10": "岗位排序 NDCG@10",
        "context_recall@5": "实际上下文岗位 Recall@5", "context_recall@10": "实际上下文岗位 Recall@10",
        "faithfulness": "RAGAS 忠实度", "answer_relevancy": "RAGAS 回答相关性",
        "context_precision": "RAGAS 上下文精确度", "context_recall": "RAGAS 上下文召回率"}
    def paired_tables(comparisons):
        result = ""
        for pair in comparisons:
            result += (f"<h3>{escape(pair['left'])} / {escape(pair['right'])}</h3><table><tr><th>指标</th>"
                f"<th>{escape(pair['left'])}</th><th>{escape(pair['right'])}</th><th>差值（左−右）</th><th>共同有效题数</th></tr>")
            for key in PRIMARY_KEYS:
                metric = pair["metrics"].get(key)
                if metric is None:
                    continue
                result += (f"<tr><td>{escape(labels.get(key, key))}<small>{escape(key)}</small></td>"
                    f"<td>{number(metric.get('left_mean'))}</td><td>{number(metric.get('right_mean'))}</td>"
                    f"<td>{number(metric.get('mean_delta'))}</td><td>{metric['paired_cases']}</td></tr>")
            result += "</table>"
        return result
    primary = paired_tables(data["paired_answerable_comparisons"])
    category_tables = ""
    for category, comparisons in data["paired_answerable_by_category"].items():
        category_tables += f"<details><summary>{escape(category)}</summary>{paired_tables(comparisons)}</details>"
    table = "<tr><th>指标</th>" + "".join(f"<th>{escape(name)}</th>" for name in strategies) + "</tr>"
    for key in keys:
        table += f"<tr><td>{escape(key)}</td>"
        for strategy in strategies:
            metric = data["summary"].get(strategy, {}).get("metrics", {}).get(key, {})
            table += f"<td>{number(metric.get('mean'))} <small>n={metric.get('valid_cases', 0)}</small></td>"
        table += "</tr>"
    operational = "<tr><th>组别</th><th>全部完成/尝试</th><th>可回答题完成/尝试</th><th>失败率</th><th>检索P50秒</th><th>检索P95秒</th><th>平均上下文tokens</th></tr>"
    for name, summary in data["summary"].items():
        answerable = data["answerable_summary"][name]
        operational += (f"<tr><td>{escape(name)}</td><td>{summary['successful_cases']}/{summary['attempted_cases']}</td>"
            f"<td>{answerable['successful_cases']}/{answerable['attempted_cases']}</td>"
            f"<td>{number(summary['failure_rate'])}</td><td>{number(summary['retrieval_seconds_p50'])}</td>"
            f"<td>{number(summary['retrieval_seconds_p95'])}</td><td>{number(summary['mean_context_tokens'])}</td></tr>")
    unknown_table = "<tr><th>组别</th><th>完成/尝试</th><th>声明拒答数/有效声明数</th><th>声明拒答比例</th><th>语义正确率</th></tr>"
    for name, summary in data["unanswerable_summary"].items():
        unknown_table += (f"<tr><td>{escape(name)}</td><td>{summary['successful_cases']}/{summary['attempted_cases']}</td>"
            f"<td>{summary['declared_abstentions']}/{summary['valid_declarations']}</td>"
            f"<td>{number(summary['declared_abstention_rate'])}</td><td>待人工核验</td></tr>")
    queue = ""
    for row in data["audit"]["review_queue"]:
        hint = "正文与拒答声明可能不一致" if row["refusal_wording_flag_conflict_hint"] else "生成失败" if row["status"] != "ok" else "不可回答题"
        queue += (f"<details><summary>{escape(row['id'])} · {escape(row['strategy'])} · {hint}</summary>"
            f"<p>{escape(row['question'])}</p><p>abstained = {escape(str(row['declared_abstained']))}；语义结论：待人工核验</p>"
            f"<pre>{escape(row['answer'] or '未生成有效回答')}</pre><p>草稿参考：{escape(row['reference'])}</p></details>")
    label = "待审核题集 · 探索性结果" if data["label_status"] != "reviewed" else "已审核题集结果"
    notes = data["metric_notes"] + data["run"].get("notes", [])
    score_manifest = directory / "score_manifest.json"
    if score_manifest.exists() and read_json(score_manifest).get("self_judge"):
        notes.append("评分与生成使用同名模型，存在自评偏差；重要结论需人工抽查或独立评审模型复核。")
    audit = data["audit"]
    warnings = "<ul>" + "".join(f"<li>{escape(note)}</li>" for note in audit["findings"]) + "</ul>"
    ceiling = number(audit["precision_label_ceiling"].get("5"))
    html = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<title>岗位 RAG 对比评估</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 20px;color:#203040}"
        "table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #d4dce3;padding:8px;text-align:left}"
        "th{background:#eff4f8}small{display:block;color:#667}li{margin:8px 0}.label,.audit{background:#fff4ce;padding:12px}"
        "summary{cursor:pointer;font-weight:600}details{margin:14px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:12px}</style>"
        f"<h1>岗位 RAG 对比评估</h1><p class='label'>{label}</p><p>{escape(data['generated_at'])}</p>"
        f"<p>共 {audit['questions']} 题：可回答 {audit['answerable_questions']} 题，不可回答 {audit['unanswerable_questions']} 题；已人工审核 {audit['reviewed_questions']} 题。</p>"
        f"<h2>本次评测的限制</h2><div class='audit'>{warnings}</div>"
        f"<p>按现有相关岗位标注计算，Precision@5 的平均理论上限为 {ceiling}，Recall@5 的平均理论上限为 {number(audit['recall_label_ceiling'].get('5'))}。"
        "相关岗位超过5条时应同时查看Recall@10；排序分数不能直接解释成业务准确率。</p>"
        f"<h2>运行完整性</h2><table>{operational}</table>"
        "<h2>可回答题：相同题目的配对比较</h2><p>每项指标仅比较各组共同有效的同一道题。生成失败单独计入失败率，"
        "不填成RAGAS零分；检索已成功的题仍参与检索指标。以下是匹配样本均值，不是原先40/38条混合样本均值。</p>"
        f"{primary}<h2>可回答题：按题型查看</h2>{category_tables}"
        f"<h2>不可回答题：独立复核</h2><p>声明拒答比例不是语义正确率。正确说明“无法确认”也可能被RAGAS AnswerRelevancy打低分，"
        f"因此这部分不进入上方回答评分。</p><table>{unknown_table}</table>"
        f"<h2>待人工复核的回答</h2><p>字面冲突只是筛查提示，不自动修改模型声明或判定回答正误。</p>{queue}"
        f"<details><summary>原始混合题型诊断指标（不作为总体准确率）</summary><table>{table}</table></details>"
        "<h2>评测口径</h2><ul>" + "".join(f"<li>{escape(note)}</li>" for note in notes) + "</ul>"
        "<p>逐题指标见 metrics.csv；配对差值及探索性95%区间见 comparison.json；审计见 audit.json；人工复核清单见 review_queue.jsonl；原始片段、回答和错误见 cases/。</p></html>")
    (directory / "report.html").write_text(html, encoding="utf-8")
    return {"report": str(directory / "report.html"), "json": str(directory / "comparison.json"),
            "csv": str(directory / "metrics.csv"), "audit": str(directory / "audit.json"),
            "review_queue": str(directory / "review_queue.jsonl"), "label_status": data["label_status"]}
