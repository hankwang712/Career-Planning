from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import importlib.util
from itertools import islice
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys

from .common import RESEARCH, ROOT, configuration, digest, now, read_json, read_jsonl, write_json, write_jsonl


@contextmanager
def workspace_read_guard(workspace):
    from hashlib import sha256
    path = RESEARCH / ".job_graph" / (sha256(workspace.encode()).hexdigest()[:16] + ".lock")
    if not path.exists():
        yield
        return
    with path.open("r+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("该工作空间正在导入或优化，请等待当前任务完成后再冻结/核对评测语料") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def local_documents(path: Path, count: int):
    # 复用实际导入器的解析器和 document_id，不复制一套可能切错分隔线的解析逻辑。
    spec = importlib.util.spec_from_file_location("career_job_graph_reader", RESEARCH / "job_graph.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return [{"record": item.index, "id": item.document_id, "text": item.extraction_text,
             "file_path": f"{path.name}#record={item.index}"}
            for item in islice(module.iter_job_documents(path), count)]


def snapshot(env_file: Path, workspace: str, with_documents=True):
    values = configuration(env_file)
    user = values.get("POSTGRES_USER", "career")
    database = values.get("POSTGRES_DATABASE", "career_rag")
    literal = "'" + workspace.replace("'", "''") + "'"
    document_query = f"""COALESCE((SELECT json_agg(json_build_object(
      'id',s.id,'status',s.status,'file_path',s.file_path,'chunk_ids',s.chunks_list,
      'chunks_count',s.chunks_count,'text',f.content,
      'stored_chunks',(SELECT COALESCE(json_agg(json_build_object('id',c.id,'content',c.content)
        ORDER BY c.chunk_order_index),'[]'::json) FROM lightrag_doc_chunks c
        WHERE c.workspace=s.workspace AND c.full_doc_id=s.id)))
      FROM lightrag_doc_status s LEFT JOIN lightrag_doc_full f USING(workspace,id)
      WHERE s.workspace={literal}),'[]'::json)"""
    # REPEATABLE READ 保证文档和图谱摘要来自同一个数据库快照；没有任何 DDL/DML。
    sql = f"""BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
    SELECT json_build_object(
      'workspace',{literal},
      'statuses',(SELECT COALESCE(json_object_agg(status,n),'{{}}'::json) FROM (
        SELECT status,count(*) n FROM lightrag_doc_status WHERE workspace={literal} GROUP BY status)t),
      'documents',{document_query if with_documents else "'[]'::json"},
      'graph',(SELECT json_build_object('nodes',count(*),'digest',md5(COALESCE(
        string_agg(id||properties::text,'' ORDER BY id),'')))
        FROM lightrag_graph_nodes WHERE workspace={literal} AND namespace='chunk_entity_relation'),
      'edges',(SELECT json_build_object('edges',count(*),'digest',md5(COALESCE(
        string_agg(src_id||tgt_id||properties::text,'' ORDER BY src_id,tgt_id),'')))
        FROM lightrag_graph_edges WHERE workspace={literal} AND namespace='chunk_entity_relation'));
    COMMIT;"""
    command = ["docker", "compose", "--env-file", str(env_file), "-f", str(RESEARCH.parents[1] / "compose.yml"),
               "exec", "-T", "postgres", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", database]
    with workspace_read_guard(workspace):
        result = subprocess.run(command, input=sql, capture_output=True, text=True, encoding="utf-8", timeout=90,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError("读取 PostgreSQL 快照失败；请检查 Docker、compose 配置和 research/.env（未打印凭证）")
    return json.loads(result.stdout)


def normalized_documents(raw):
    statuses = raw["statuses"]
    if any(status != "processed" and count for status, count in statuses.items()):
        raise ValueError(f"图谱尚未就绪：{statuses}。等待导入、失败重试和优化完成后再 prepare/run")
    rows, records = [], set()
    for document in raw["documents"]:
        match = re.search(r"#record=(\d+)$", document.get("file_path") or "")
        if not match or not document.get("text"):
            raise ValueError("入库记录缺少 record 来源或全文，无法建立公平对照")
        number = int(match[1])
        if number in records:
            raise ValueError("同一 record 序号对应多条文档，请先整理来源再评测")
        records.add(number)
        chunks = document.get("stored_chunks") or []
        if len(chunks) != document.get("chunks_count") or {c["id"] for c in chunks} != set(document.get("chunk_ids") or []):
            raise ValueError(f"第 {number} 条的文档状态和实际 chunk 不一致")
        if not chunks:
            raise ValueError(f"第 {number} 条没有可检索的 chunk")
        rows.append({"record": number, "id": document["id"], "text": document["text"],
                     "file_path": document["file_path"], "chunks": chunks})
    if not rows:
        raise ValueError("当前工作空间没有已处理岗位")
    return sorted(rows, key=lambda row: row["record"])


def corpus_revision(rows):
    return digest([{key: row[key] for key in ("record", "id", "text", "file_path", "chunks")}
                   for row in sorted(rows, key=lambda item: item["record"])])


def prepare(output: Path, env_file: Path, workspace: str, expected: int | None):
    raw = snapshot(env_file, workspace)
    rows = normalized_documents(raw)
    if expected is not None and len(rows) != expected:
        raise ValueError(f"实际 {len(rows)} 条，预期 {expected} 条；未生成不同规模的对照语料")
    from .common import model_config
    embedding = model_config(configuration(env_file), "embedding")
    manifest = {"schema_version": 1, "created_at": now(), "workspace": workspace,
                "record_count": len(rows), "corpus_revision": corpus_revision(rows),
                "graph": raw["graph"], "edges": raw["edges"], "embedding": embedding.public(),
                "source": "processed PostgreSQL full documents and chunks",
                "local_evaluation_sources": {
                    name: digest((RESEARCH / "LightRAG" / "lightrag" / "evaluation" / name).read_text(encoding="utf-8"))
                    for name in ("eval_rag_quality.py", "README_EVALUASTION_RAGAS.md")}}
    identity = {key: manifest[key] for key in ("corpus_revision", "graph", "edges", "embedding", "workspace")}
    manifest["experiment_revision"] = digest(identity)
    target = output / "manifest.json"
    if target.exists() and read_json(target)["experiment_revision"] != manifest["experiment_revision"]:
        raise ValueError("输出目录已有不同语料/图谱的实验，请使用新的 --output 目录以保留旧基线")
    write_jsonl(output / "corpus.jsonl", rows)
    write_json(target, manifest)
    return manifest


def load_corpus(output: Path):
    manifest = read_json(output / "manifest.json")
    rows = read_jsonl(output / "corpus.jsonl")
    if corpus_revision(rows) != manifest["corpus_revision"]:
        raise ValueError("冻结语料文件已改变，请重新 prepare 到新目录")
    return manifest, rows


def verify_live(output: Path, env_file: Path):
    manifest, _ = load_corpus(output)
    raw = snapshot(env_file, manifest["workspace"])
    rows = normalized_documents(raw)
    if (corpus_revision(rows) != manifest["corpus_revision"] or raw["graph"] != manifest["graph"]
            or raw["edges"] != manifest["edges"]):
        raise ValueError("LightRAG 语料或图谱已变化；本次实验停止，请在新目录重新 prepare/index/run")
    return manifest


def field(text, prefix):
    return next((line[len(prefix):].strip() for line in text.splitlines() if line.startswith(prefix)), "未注明")


def reference_text(row):
    # 地点和学历经常只存在于头部，条件题的参考答案不能漏掉这些真实字段。
    text = row["text"]
    return text.partition("\n")[2].strip() if text.startswith("招聘记录内部键：") else text


def build_draft(rows, questions=40, seed=42, original_count=220):
    if questions < 1:
        raise ValueError("题数必须为正数")
    rng = random.Random(seed)
    # 交替抽取旧批次与新增批次，避免题目都落在文件开头。
    old = [row for row in rows if row["record"] <= original_count]
    added = [row for row in rows if row["record"] > original_count]
    rng.shuffle(old)
    rng.shuffle(added)
    ordered = []
    while old or added:
        if old:
            ordered.append(old.pop())
        if added:
            ordered.append(added.pop())
    groups = defaultdict(list)
    for row in rows:
        title = field(row["text"], "岗位名称：")
        family = next((term for term in ("算法", "测试", "前端", "后端", "产品", "运营", "销售", "软件", "开发") if term in title), "其他")
        groups[family].append(row)
    cases = []
    for number in range(questions):
        row = ordered[number % len(ordered)]
        title, company = field(row["text"], "岗位名称："), field(row["text"], "企业：")
        kind = ("single", "constraints", "single", "comparison", "unanswerable")[number % 5]
        relevant = [row]
        if kind == "single":
            question = f"资料中，{company}的“{title}”有哪些工作职责和任职要求？请保留必需与优先的区别。"
        elif kind == "constraints":
            question = f"{company}的“{title}”明确写了哪些学历、地点、经验或实习安排条件？没有写明的请标为未知。"
        elif kind == "comparison":
            group = next(group for group in groups.values() if row in group)
            candidates = [item for item in group if item["id"] != row["id"] and field(item["text"], "企业：") != company]
            if not candidates:
                candidates = [item for item in rows if item["id"] != row["id"]]
            if candidates:
                other = rng.choice(candidates)
                relevant.append(other)
                question = (f"比较{company}的“{title}”与{field(other['text'], '企业：')}的“{field(other['text'], '岗位名称：')}”："
                            "两者的技能与任职条件有什么异同？请分别归属，不要合并成统一门槛。")
            else:
                kind, question = "single", f"{company}的“{title}”有哪些明确岗位要求？"
        else:
            question = f"仅凭这些岗位资料，能否确认{company}的“{title}”今天仍接受申请，并保证符合要求就会被录用？"
        answerable = kind != "unanswerable"
        cases.append({"id": f"Q{number + 1:03d}", "category": kind, "question": question,
                      "ground_truth": "\n\n".join(reference_text(item) for item in relevant) if answerable
                          else "仅凭静态岗位样本不能确认当前招聘状态，也不能保证录用。",
                      "answerable": answerable, "relevant_records": [item["record"] for item in relevant] if answerable else [],
                      "evidence_quotes": [{"record": item["record"], "quote": reference_text(item)} for item in relevant] if answerable else [],
                      "reviewed": False, "review_notes": "原文提取式参考答案；需核对问题歧义、答案完整性和全部相关岗位，补充自然表达及跨岗位问题。",
                      "cohort": "added" if row["record"] > original_count else "original"})
    return {"schema_version": 1, "created_at": now(), "status": "draft_unreviewed", "seed": seed,
            "notes": ["自动草稿不等于人工金标准。默认 run/score 拒绝未审核题目。",
                      "此题集偏向具体岗位查找，不能单独代表开放式方向探索能力。",
                      "relevant_records 是标注候选；存在其他相关记录时须补齐，未穷尽时 Precision/NDCG 有偏。"],
            "source_records": len(rows), "test_cases": cases}


def draft(output: Path, input_file: Path, records=300, questions=40, seed=42, original_count=220):
    rows = local_documents(input_file, records)
    if len(rows) != records:
        raise ValueError(f"本地语料只有 {len(rows)} 条，无法按预期 {records} 条准备题集")
    target = output / "dataset.draft.json"
    if target.exists():
        raise ValueError("草稿已存在；请换输出目录，避免覆盖人工修改")
    data = build_draft(rows, questions, seed, original_count)
    data["source_input"] = input_file.name
    data["source_revision"] = digest([{key: row[key] for key in ("record", "id", "text")} for row in rows])
    write_json(target, data)
    write_jsonl(output / "draft_sources.jsonl", rows)
    return {"questions": len(data["test_cases"]), "records": len(rows), "dataset": str(target), "status": "draft_unreviewed"}


def load_cases(path: Path, rows, allow_draft=False, limit=None):
    data = read_json(path)
    cases = data.get("test_cases", [])
    if not cases:
        raise ValueError("题集没有 test_cases")
    selected = cases if limit is None else cases[:limit]
    if not selected:
        raise ValueError("没有选中的题目")
    by_record = {row["record"]: row for row in rows}
    seen = set()
    for case in selected:
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", str(case.get("id", "")))
                or case["id"] in seen or not str(case.get("question", "")).strip()):
            raise ValueError("题目 id 必须唯一，question 不能为空")
        seen.add(case["id"])
        if not allow_draft and case.get("reviewed") is not True:
            raise ValueError(f"{case['id']} 尚未人工审核；审核后设置 reviewed=true，或用 --allow-draft 做探索性试跑")
        relevant = case.get("relevant_records")
        if not isinstance(relevant, list) or len(set(relevant)) != len(relevant):
            raise ValueError("每题需提供无重复的 relevant_records")
        if type(case.get("answerable")) is not bool or bool(relevant) != case["answerable"]:
            raise ValueError("可回答题必须有相关岗位；不可回答题的 relevant_records 应为空")
        if any(record not in by_record for record in relevant):
            raise ValueError(f"{case['id']} 引用了未入库岗位；等待对应批次导入后再 prepare")
        for record, grade in case.get("relevance_grades", {}).items():
            if int(record) not in relevant or not isinstance(grade, (int, float)) or not math.isfinite(grade) or not 0 < grade <= 3:
                raise ValueError("relevance_grades 只接受相关岗位的 (0,3] 有限分级")
        for evidence in case.get("evidence_quotes", []):
            record, quote = evidence.get("record"), evidence.get("quote")
            if record not in relevant or not quote or re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", by_record[record]["text"]):
                raise ValueError(f"{case['id']} 的证据不是对应岗位的连续原文")
    return selected
