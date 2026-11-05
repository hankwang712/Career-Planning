"""Career records: independent entities, attributable evidence, and revision checks."""
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from . import db
from .resume.facts import facts_from_structured

Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=2000)]
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=0, ge=0, strict=True)


class UserProfile(Input):
    display_name: Text = ""
    headline: Text = ""
    city: Text = ""
    stage: Literal["", "student", "graduate", "employed", "transition"] = ""
    summary: Text = ""


class ProfileEntry(Input):
    kind: Literal["education", "experience", "certificate", "interest", "preference"]
    title: Name
    description: Text = ""


class UserSkill(Input):
    name: Name
    category: Text = ""


class SkillEvidence(Input):
    skill_id: Name
    kind: Literal["self_report", "experience_support"]
    title: Name
    description: Text = ""
    url: Text = ""


class CareerGoal(Input):
    title: Name
    target_date: date | None = None
    status: Literal["active", "completed", "paused"] = "active"
    description: Text = ""


class AssessmentResult(Input):
    test: Literal["mbti", "holland", "deep", "friends", "insideout", "sbti"]
    result: Name
    completed_at: datetime


class AssessmentImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[AssessmentResult] = Field(max_length=50)


class ResumeVersion(Input):
    """Metadata references an existing upload; files remain owned by resume service."""
    document_id: Name
    name: Name


MODELS = {"profile": UserProfile, "entries": ProfileEntry, "skills": UserSkill,
          "evidence": SkillEvidence, "goals": CareerGoal, "assessments": AssessmentResult}
TABLES = {"profile": "career_profiles", "entries": "career_entries", "skills": "career_skills",
          "evidence": "career_evidence", "goals": "career_goals", "assessments": "career_assessments",
          "resumes": "career_resumes"}
LEVELS = {"self_report": "用户自述", "experience_support": "经历支持",
          "artifact_verified": "成果验证", "assessed": "实际评估"}


def init_schema(conn):
    # JSON is used only for an immutable per-entity audit snapshot, never the live profile.
    common = """id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        source_type TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1"""
    columns = {
        "profile": "display_name TEXT NOT NULL, headline TEXT NOT NULL, city TEXT NOT NULL, stage TEXT NOT NULL, summary TEXT NOT NULL, UNIQUE(owner)",
        "entries": "kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL",
        "skills": "name TEXT NOT NULL, category TEXT NOT NULL, name_key TEXT NOT NULL, UNIQUE(owner, name_key), UNIQUE(owner, id)",
        "evidence": """skill_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('self_report','experience_support','artifact_verified','assessed')),
            title TEXT NOT NULL, description TEXT NOT NULL, url TEXT NOT NULL,
            FOREIGN KEY(owner,skill_id) REFERENCES career_skills(owner,id) ON DELETE CASCADE""",
        "goals": "title TEXT NOT NULL, target_date TEXT, status TEXT NOT NULL, description TEXT NOT NULL",
        "assessments": "test TEXT NOT NULL, result TEXT NOT NULL, completed_at TEXT NOT NULL",
        "resumes": "document_id TEXT NOT NULL, name TEXT NOT NULL, uploaded_at TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(owner,document_id)",
    }
    for key, table in TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({common}, {columns[key]})")
        conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_owner ON {table}(owner)")
    conn.execute("""CREATE TABLE IF NOT EXISTS career_revisions (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, version INTEGER NOT NULL,
        action TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS career_revision_owner ON career_revisions(owner,entity_id)")


class CareerError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def now():
    return datetime.now(timezone.utc).isoformat()


def stable_id(owner, key, source):
    return hashlib.sha256(f"{owner}\0{key}\0{source}".encode()).hexdigest()[:32]


def audit(conn, key, row, action):
    conn.execute("INSERT INTO career_revisions VALUES (?,?,?,?,?,?,?,?)", (
        uuid4().hex, row["owner"], key, row["id"], row["version"], action,
        json.dumps(dict(row), ensure_ascii=False), now()))


def save_record(owner, key, payload, entity_id=None, *, source_type="manual", source_ref="", conn=None):
    conn = conn if conn is not None else db._get_conn()
    table = TABLES[key]
    old = conn.execute(f"SELECT * FROM {table} WHERE owner=? AND id=?", (owner, entity_id)).fetchone() if entity_id else None
    if entity_id and not old:
        raise CareerError("记录不存在。", 404)
    if old and old["source_type"] != "manual":
        raise CareerError("来源记录请在原模块维护。", 409)
    fields = MODELS[key].model_validate(payload).model_dump(mode="json")
    version = fields.pop("version")
    if old and old["version"] != version:
        raise CareerError("这条记录已更新，请刷新后再编辑。", 409)
    if key == "skills":
        fields["name_key"] = fields["name"].casefold()
        duplicate = conn.execute("SELECT id FROM career_skills WHERE owner=? AND name_key=?", (owner, fields["name_key"])).fetchone()
        if duplicate and (not old or duplicate["id"] != entity_id):
            raise CareerError("该技能已存在，请为已有技能补充证据。", 409)
    if key == "evidence":
        if not conn.execute("SELECT 1 FROM career_skills WHERE owner=? AND id=?", (owner, fields["skill_id"])).fetchone():
            raise CareerError("关联技能不存在。", 404)
        if fields["url"]:
            from urllib.parse import urlsplit
            try:
                parsed = urlsplit(fields["url"])
                valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid:
                raise CareerError("证据链接须为有效的 HTTP 或 HTTPS 地址。")
        if fields["kind"] == "experience_support" and not fields["description"]:
            raise CareerError("请描述具体经历与本人完成的工作。")
    stamp = now()
    row = {"id": old["id"] if old else uuid4().hex, "owner": owner,
           "source_type": old["source_type"] if old else source_type,
           "source_ref": old["source_ref"] if old else source_ref,
           "created_at": old["created_at"] if old else stamp, "updated_at": stamp,
           "version": version + 1 if old else 1, **fields}
    if old:
        columns = [name for name in row if name not in {"id", "owner", "created_at"}]
        cursor = conn.execute(f"UPDATE {table} SET {','.join(name+'=?' for name in columns)} WHERE owner=? AND id=? AND version=?",
                              [row[name] for name in columns] + [owner, entity_id, version])
        if cursor.rowcount != 1:
            raise CareerError("这条记录已更新，请刷新后再编辑。", 409)
    else:
        conn.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
    audit(conn, key, row, "update" if old else "create")
    return row


def imported(conn, owner, key, source_ref, fields, source_type):
    stamp = now()
    row = {"id": stable_id(owner, key, source_ref), "owner": owner, "source_type": source_type,
           "source_ref": source_ref, "created_at": stamp, "updated_at": stamp, "version": 1, **fields}
    cursor = conn.execute(f"INSERT OR IGNORE INTO {TABLES[key]} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))
    return row["id"] if cursor.rowcount else None


def sync_sources(owner, state):
    """Idempotent migration from existing source modules; never infer capability."""
    conn = db._get_conn()
    resume = state.get("resume_profile") if isinstance(state.get("resume_profile"), dict) else {}
    history = state.get("resume_versions") if isinstance(state.get("resume_versions"), list) else []
    versions = [*history, resume]
    with conn:
        valid_ids = []
        for item in versions:
            if not isinstance(item, dict) or not isinstance(item.get("document_id"), str) or not item["document_id"]:
                continue
            document_id = item["document_id"]
            valid_ids.append(document_id)
            imported(conn, owner, "resumes", document_id, {
                "document_id": document_id, "name": str(item.get("original_file_name") or item.get("file_name") or "简历")[:120],
                "uploaded_at": str(item.get("uploaded_at") or ""), "status": str(item.get("status") or "archived")}, "resume")
            status = str(item.get("status") or "archived")
            conn.execute("UPDATE career_resumes SET status=?,updated_at=?,version=version+1 WHERE owner=? AND document_id=? AND status<>?", (
                status, now(), owner, document_id, status))
        # Source deletion propagates to every derived record, including old versions.
        records = conn.execute("SELECT document_id FROM career_resumes WHERE owner=?", (owner,)).fetchall()
        for record in records:
            if record["document_id"] not in valid_ids:
                reference = "resume:" + record["document_id"]
                for key in ("entries", "evidence"):
                    conn.execute(f"DELETE FROM {TABLES[key]} WHERE owner=? AND source_type='resume' AND source_ref LIKE ?", (owner, reference + ":%"))
                conn.execute("DELETE FROM career_resumes WHERE owner=? AND document_id=?", (owner, record["document_id"]))
        if isinstance(resume.get("document_id"), str) and resume["document_id"]:
            doc = "resume:" + resume["document_id"]
            facts = facts_from_structured(resume.get("structured_resume") or {})
            for fact in facts:
                ref = f"{doc}:" + stable_id(owner, fact["key"], fact["subject"] + fact["value"])
                if fact["key"] == "skill":
                    name = fact["subject"]
                    imported(conn, owner, "skills", name.casefold(), {"name": name, "name_key": name.casefold(), "category": ""}, "resume")
                    skill = conn.execute("SELECT id FROM career_skills WHERE owner=? AND name_key=?", (owner, name.casefold())).fetchone()
                    imported(conn, owner, "evidence", ref, {"skill_id": skill["id"], "kind": "self_report",
                        "title": "简历中列出的技能", "description": "简历字段：" + fact["evidence"]["field"], "url": ""}, "resume")
                else:
                    kind = "experience" if fact["key"] == "experience" else "education"
                    imported(conn, owner, "entries", ref, {"kind": kind, "title": fact["subject"] if kind == "experience" else {"major": "专业", "education": "学历", "graduation": "毕业时间"}[fact["key"]],
                        "description": fact["value"]}, "resume")
        # Remove only imported skill shells whose final evidence has been forgotten.
        conn.execute("DELETE FROM career_skills WHERE owner=? AND source_type='resume' AND NOT EXISTS (SELECT 1 FROM career_evidence WHERE career_evidence.skill_id=career_skills.id)", (owner,))
        hub = state.get("assessment_hub") if isinstance(state.get("assessment_hub"), dict) else {}
        for test in ("mbti", "holland"):
            scope = hub.get(test) if isinstance(hub.get(test), dict) else {}
            runs = scope.get("historyRuns", scope.get("history_runs", []))
            for run in runs if isinstance(runs, list) else []:
                if not isinstance(run, dict):
                    continue
                result = run.get("displayType") if test == "mbti" else run.get("code")
                completed = run.get("recordedAt")
                if result and isinstance(completed, (int, float)) and 0 < completed < 253402300799000:
                    imported(conn, owner, "assessments", f"{test}:{completed}", {"test": test,
                        "result": str(result)[:120], "completed_at": datetime.fromtimestamp(completed / 1000, timezone.utc).isoformat()}, "assessment")


def snapshot(owner):
    conn = db._get_conn()
    result = {}
    for key, table in TABLES.items():
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} WHERE owner=? ORDER BY updated_at DESC,id", (owner,))]
        result[key] = rows[0] if key == "profile" and rows else None if key == "profile" else rows
    for skill in result["skills"]:
        evidence = [item for item in result["evidence"] if item["skill_id"] == skill["id"]]
        skill["evidence_level"] = max((item["kind"] for item in evidence), key=lambda value: list(LEVELS).index(value), default="self_report")
        skill["evidence_count"] = len(evidence)
    result["evidence_levels"] = LEVELS
    return result


def create_blueprint(login_required, current_user, state_provider, memory_provider=None):
    blueprint = Blueprint("career", __name__, url_prefix="/api/career-profile")

    @blueprint.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        response.vary.add("Cookie")
        return response

    @blueprint.errorhandler(CareerError)
    def handle_error(error):
        return jsonify(message=error.message), error.status

    @blueprint.errorhandler(ValidationError)
    def handle_validation(error):
        return jsonify(message="请检查必填内容、日期和字段长度。", fields=[".".join(map(str, item["loc"])) for item in error.errors()]), 400

    @blueprint.errorhandler(sqlite3.IntegrityError)
    def handle_conflict(error):
        return jsonify(message="记录已存在或关联资料已更新，请刷新后重试。"), 409

    @blueprint.route("", methods=["GET"])
    @login_required
    def get_profile():
        owner = current_user()["username"]
        sync_sources(owner, state_provider(owner))
        result = snapshot(owner)
        # Read current memory live, so removal/correction is immediately respected.
        result["memories"] = memory_provider(owner) if memory_provider else []
        return jsonify(data=result)

    @blueprint.route("/<key>", methods=["POST", "PUT"])
    @blueprint.route("/<key>/<entity_id>", methods=["PUT", "DELETE"])
    @login_required
    def mutate(key, entity_id=None):
        if key not in MODELS:
            raise CareerError("未知的档案记录。", 404)
        owner = current_user()["username"]
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise CareerError("请求必须是 JSON 对象。")
        conn = db._get_conn()
        with conn:
            if key == "profile" and not entity_id:
                existing = conn.execute("SELECT id FROM career_profiles WHERE owner=?", (owner,)).fetchone()
                entity_id = existing["id"] if existing else None
            if request.method == "DELETE":
                if not entity_id:
                    raise CareerError("缺少记录标识。")
                row = conn.execute(f"SELECT * FROM {TABLES[key]} WHERE owner=? AND id=?", (owner, entity_id)).fetchone()
                if not row:
                    raise CareerError("记录不存在。", 404)
                if row["source_type"] != "manual":
                    raise CareerError("来源记录请在原模块维护。", 409)
                if payload.get("version") != row["version"]:
                    raise CareerError("记录已更新，请刷新后再操作。", 409)
                if key == "skills":
                    linked = conn.execute("SELECT * FROM career_evidence WHERE owner=? AND skill_id=?", (owner, entity_id)).fetchall()
                    if any(item["source_type"] != "manual" for item in linked):
                        raise CareerError("该技能仍有简历来源，请先在简历模块移除来源，或仅移除本人补充的证据。", 409)
                    for item in linked:
                        audit(conn, "evidence", item, "delete")
                audit(conn, key, row, "delete")
                conn.execute(f"DELETE FROM {TABLES[key]} WHERE owner=? AND id=?", (owner, entity_id))
                return jsonify(message="记录已移除。")
            row = save_record(owner, key, payload, entity_id, conn=conn)
        return jsonify(data=row)

    @blueprint.route("/history/<entity_id>")
    @login_required
    def history(entity_id):
        rows = db._get_conn().execute("SELECT entity_type,version,action,created_at,snapshot FROM career_revisions WHERE owner=? AND entity_id=? ORDER BY created_at DESC LIMIT 50", (current_user()["username"], entity_id)).fetchall()
        return jsonify(data=[{**dict(row), "snapshot": json.loads(row["snapshot"])} for row in rows])

    @blueprint.route("/assessment-import", methods=["POST"])
    @login_required
    def import_assessments():
        body = AssessmentImport.model_validate(request.get_json(silent=True))
        owner = current_user()["username"]
        conn = db._get_conn()
        with conn:
            for record in body.records:
                if record.completed_at.tzinfo is None:
                    raise CareerError("测评完成时间须包含时区。")
                completed = record.completed_at.astimezone(timezone.utc)
                fields = record.model_dump(mode="json", exclude={"version"})
                fields["completed_at"] = completed.isoformat()
                imported(conn, owner, "assessments", f"{record.test}:{int(completed.timestamp() * 1000)}", fields, "local_assessment")
        return jsonify(message="测评记录已同步。")

    return blueprint
