import gzip
import json
import os
import sqlite3
import tempfile
import zlib
from contextlib import closing
from pathlib import Path

from flask import Blueprint, jsonify, request

from .paths import DATA_DIR


MERGED_DIR = DATA_DIR / "cleaned" / "merged"
DATASETS = {
    "city_jobs": ("城市招聘样本", "job", "原有城市数据，已去重清洗"),
    "other_city": ("补充城市岗位", "job", "补充城市招聘记录，已去重清洗"),
    "job_research_hub": ("公开招聘快照", "job", "历史采集快照，不代表岗位仍在招聘；原始内容权利归各来源所有"),
    "occupation": ("职业分类知识", "occupation", "职业分类名称、编码及所属分类；社区整理，部分条目没有详细说明"),
    "industry": ("行业分类知识", "industry", "国民经济行业分类及解释，职业与行业分开展示"),
}


def source_signature(directory):
    return json.dumps([(name, (directory / name).stat().st_size, (directory / name).stat().st_mtime_ns)
                       for name in ("jobs.jsonl.gz", "knowledge.jsonl", "summary.json")])


def build_index(directory=MERGED_DIR):
    directory = Path(directory)
    signature = source_signature(directory)
    descriptor, temporary_name = tempfile.mkstemp(prefix="browse-", suffix=".sqlite3", dir=directory)
    os.close(descriptor)
    temporary = Path(temporary_name)
    counts = dict.fromkeys(DATASETS, 0)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.executescript("""
                CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE records (
                    id TEXT PRIMARY KEY, dataset TEXT NOT NULL, search_text TEXT NOT NULL,
                    summary TEXT NOT NULL, detail BLOB NOT NULL
                );
            """)
            for filename, opener in (("jobs.jsonl.gz", gzip.open), ("knowledge.jsonl", open)):
                with opener(directory / filename, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        record = json.loads(line)
                        sources = record.get("sources") or []
                        kind = record.get("kind", "job")
                        dataset = sources[0]["dataset"] if kind == "job" else kind
                        if dataset not in DATASETS:
                            continue
                        summary = {"id": record["id"], "kind": kind,
                                   "title": record.get("title") or record.get("name"),
                                   "company": record.get("company", ""),
                                   "locations": record.get("locations", []),
                                   "salary": record.get("salary", ""),
                                   "education": record.get("education", ""),
                                   "skills": record.get("skills", [])[:6],
                                   "preview": record.get("description", "")[:180],
                                   "codes": list(dict.fromkeys(item["code"] for item in sources if item.get("code"))),
                                   "parents": list(dict.fromkeys(item["parent_name"] for item in sources if item.get("parent_name")))}
                        searchable = " ".join(str(record.get(field) or "") for field in
                                              ("title", "name", "company", "locations", "skills", "industry", "description"))
                        searchable += " " + " ".join(summary["codes"] + summary["parents"])
                        detail = zlib.compress(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                        connection.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?)",
                                           (record["id"], dataset, searchable.casefold(), json.dumps(summary, ensure_ascii=False), detail))
                        counts[dataset] += 1
            connection.execute("CREATE INDEX records_dataset_id ON records(dataset, id)")
            connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                   [("signature", signature), ("counts", json.dumps(counts))])
            connection.commit()
        if signature != source_signature(directory):
            raise ValueError("清洗数据在建索引期间发生变化，请重新运行索引命令。")
        os.replace(temporary, directory / "browse.sqlite3")
    finally:
        temporary.unlink(missing_ok=True)
    return counts


def open_index():
    path = MERGED_DIR / "browse.sqlite3"
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        signature = connection.execute("SELECT value FROM metadata WHERE name = 'signature'").fetchone()
        if not signature or signature[0] != source_signature(MERGED_DIR):
            raise ValueError("数据索引已过期")
    except Exception:
        connection.close()
        raise
    return connection


def create_blueprint(login_required):
    blueprint = Blueprint("datasets", __name__, url_prefix="/api/datasets")

    @blueprint.errorhandler(sqlite3.Error)
    @blueprint.errorhandler(FileNotFoundError)
    @blueprint.errorhandler(ValueError)
    def unavailable(error):
        return jsonify(message="数据暂不可用，请运行 python backend/scripts/build_dataset_index.py 更新索引。"), 503

    @blueprint.get("")
    @login_required
    def catalog():
        summary = json.loads((MERGED_DIR / "summary.json").read_text(encoding="utf-8"))
        job_counts = summary["jobs"]["output_by_source"]
        knowledge_counts = summary["knowledge"]["output_by_kind"]
        return jsonify(datasets=[{"id": key, "name": values[0], "kind": values[1], "note": values[2],
                                  "count": (job_counts if values[1] == "job" else knowledge_counts).get(key, 0)}
                                 for key, values in DATASETS.items()])

    @blueprint.get("/<dataset>/records")
    @login_required
    def records(dataset):
        if dataset not in DATASETS:
            return jsonify(message="未找到该数据分类。"), 404
        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "12"))
            if not 1 <= page <= 1000000 or not 1 <= page_size <= 60:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify(message="分页参数无效，每页最多 60 条。"), 400
        query = request.args.get("q", "").strip()
        if len(query) > 100:
            return jsonify(message="搜索词最多 100 字。"), 400
        conditions = ["dataset = ?"]
        parameters = [dataset]
        for term in query.casefold().split()[:5]:
            conditions.append("search_text LIKE ? ESCAPE '\\'")
            parameters.append("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        where = " AND ".join(conditions)
        with closing(open_index()) as connection:
            if query:
                total = connection.execute(f"SELECT COUNT(*) FROM records WHERE {where}", parameters).fetchone()[0]
            else:
                total = json.loads(connection.execute("SELECT value FROM metadata WHERE name = 'counts'").fetchone()[0])[dataset]
            page = min(page, max(1, (total + page_size - 1) // page_size))
            rows = connection.execute(f"SELECT summary FROM records WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
                                      [*parameters, page_size, (page - 1) * page_size]).fetchall()
        response = jsonify(items=[json.loads(row[0]) for row in rows], total=total, page=page, page_size=page_size)
        response.headers["Cache-Control"] = "private, max-age=60"
        return response

    @blueprint.get("/<dataset>/records/<record_id>")
    @login_required
    def detail(dataset, record_id):
        if dataset not in DATASETS:
            return jsonify(message="未找到该数据分类。"), 404
        with closing(open_index()) as connection:
            row = connection.execute("SELECT detail FROM records WHERE dataset = ? AND id = ?", (dataset, record_id)).fetchone()
        if not row:
            return jsonify(message="未找到该条记录。"), 404
        return jsonify(json.loads(zlib.decompress(row[0])))

    return blueprint
