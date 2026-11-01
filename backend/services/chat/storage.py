"""Durable chat records and a leased, retryable memory-analysis queue."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import unicodedata
from uuid import uuid4

from .policy import MemoryPolicy, estimate_tokens
from .privacy import MemoryControls, SCHEMA as PRIVACY_SCHEMA


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def memory_id(owner, kind, key, subject):
    return hashlib.sha256(json.dumps([owner, kind, key, normalized(subject)], ensure_ascii=False).encode()).hexdigest()


class ChatStore(MemoryControls):
    def __init__(self, path, *, policy=None):
        self.path = Path(path)
        self.policy = policy or MemoryPolicy.from_env()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', analyzed_seq INTEGER NOT NULL DEFAULT 0,
                    memory_seq INTEGER NOT NULL DEFAULT 0,
                    sending_token TEXT, sending_until REAL NOT NULL DEFAULT 0,
                    selection TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner, updated_at);
                CREATE TABLE IF NOT EXISTS messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                    status TEXT NOT NULL, created_at REAL NOT NULL,
                    UNIQUE(session_id, request_id, role)
                );
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, seq);
                CREATE TABLE IF NOT EXISTS chat_images (
                    id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, digest TEXT NOT NULL,
                    UNIQUE(message_id,position));
                CREATE TABLE IF NOT EXISTS memory_jobs (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT 'idle',
                    due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    token TEXT, lease_until REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, requested_seq INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(session_id,kind)
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                    key TEXT NOT NULL, subject TEXT NOT NULL, value TEXT NOT NULL,
                    evidence TEXT NOT NULL, source_session TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    source_at REAL NOT NULL DEFAULT 0,
                    indexed_revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS memories_owner ON memories(owner, status);
                CREATE TABLE IF NOT EXISTS memory_owners (
                    owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, memory_id TEXT,
                    source_session TEXT NOT NULL, operation TEXT NOT NULL, before_value TEXT,
                    after_value TEXT, evidence TEXT NOT NULL, decision TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memory_events_owner ON memory_events(owner,seq);
                CREATE TABLE IF NOT EXISTS context_traces (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(session_id, request_id)
                );
            """ + PRIVACY_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "memory_seq" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN memory_seq INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE sessions SET memory_seq=analyzed_seq")
            if "sending_epoch" not in session_columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN sending_epoch INTEGER NOT NULL DEFAULT 0")
            if "kind" not in {row["name"] for row in conn.execute("PRAGMA table_info(memory_jobs)")}:
                conn.execute("ALTER TABLE memory_jobs RENAME TO legacy_memory_jobs")
                conn.execute("""CREATE TABLE memory_jobs (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT 'migration',
                    due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued', token TEXT,
                    lease_until REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    requested_seq INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(session_id,kind))""")
                for kind in ("memory", "summary"):
                    conn.execute("""INSERT INTO memory_jobs(session_id,kind,due_at,status,requested_seq)
                        SELECT session_id,?,due_at,CASE WHEN status='running' THEN 'queued' ELSE status END,requested_seq
                        FROM legacy_memory_jobs""", (kind,))
                conn.execute("DROP TABLE legacy_memory_jobs")
            conn.execute("CREATE INDEX IF NOT EXISTS memory_jobs_ready ON memory_jobs(status,due_at,priority)")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
            if "source_at" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN source_at REAL NOT NULL DEFAULT 0")
            for row in conn.execute("SELECT * FROM memory_suppressions").fetchall():
                if not row["subject"].startswith("sha256:"):
                    token = self._subject_token(row["owner"], row)
                    conn.execute("""INSERT INTO memory_suppressions VALUES(?,?,?,?,?,?,?)
                        ON CONFLICT(owner,kind,key,subject) DO UPDATE SET source_cutoff_seq=MAX(source_cutoff_seq,excluded.source_cutoff_seq),
                        active=MAX(active,excluded.active),created_at=MAX(created_at,excluded.created_at)""",
                        (row["owner"], row["kind"], row["key"], token, row["source_cutoff_seq"], row["active"], row["created_at"]))
                    conn.execute("DELETE FROM memory_suppressions WHERE owner=? AND kind=? AND key=? AND subject=?",
                        (row["owner"], row["kind"], row["key"], row["subject"]))
            for row in conn.execute("SELECT id,owner,payload FROM cleanup_jobs").fetchall():
                payload = json.loads(row["payload"])
                if any("subject" in slot for slot in payload.get("slots", [])):
                    payload["slots"] = [{"kind": slot["kind"], "key": slot["key"],
                        "subject_hash": self._subject_token(row["owner"], slot),
                        "slot_id": self._subject_token(row["owner"], slot).removeprefix("sha256:")} for slot in payload["slots"]]
                    conn.execute("UPDATE cleanup_jobs SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
            for row in conn.execute("SELECT owner,id,evidence FROM memories UNION ALL SELECT owner,memory_id AS id,evidence FROM memory_events").fetchall():
                for quote in json.loads(row["evidence"]):
                    if isinstance(row["id"], str) and isinstance(quote.get("message_id"), str):
                        conn.execute("INSERT OR IGNORE INTO memory_sources VALUES(?,?,?)", (row["owner"], row["id"], quote["message_id"]))
            for row in conn.execute("SELECT s.owner,t.* FROM context_traces t JOIN sessions s ON s.id=t.session_id").fetchall():
                trace = json.loads(row["payload"])
                identifiers = trace.get("supplied_memory_ids", []) + [item["id"] for item in trace.get("memories", []) if isinstance(item, dict) and isinstance(item.get("id"), str)]
                for identifier in identifiers:
                    conn.execute("INSERT OR IGNORE INTO memory_usages VALUES(?,?,?,?)", (row["owner"], identifier, row["session_id"], row["request_id"]))
            for row in conn.execute("SELECT owner,id FROM memories WHERE status='retracted'").fetchall():
                if conn.execute("SELECT 1 FROM memories WHERE owner=? AND id=?", (row["owner"], row["id"])).fetchone():
                    self._delete_memory(conn, row["owner"], row["id"], mode="forget")

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def owned(conn, owner, session_id):
        row = conn.execute("""SELECT s.*,COALESCE(p.epoch,0) privacy_epoch,COALESCE(p.cutoff_seq,0) context_cutoff_seq
            FROM sessions s LEFT JOIN chat_privacy p ON p.owner=s.owner WHERE s.id=? AND s.owner=?""", (session_id, owner)).fetchone()
        if not row:
            raise ChatError("对话不存在或已删除。", 404)
        return dict(row)

    def create_session(self, owner, title="新对话"):
        now, session_id = time.time(), uuid4().hex
        with self.connect(write=True) as conn:
            conn.execute("INSERT INTO sessions(id,owner,title,created_at,updated_at) VALUES(?,?,?,?,?)",
                         (session_id, owner, title, now, now))
        return self.session(owner, session_id)

    def session(self, owner, session_id):
        with self.connect() as conn:
            return self.owned(conn, owner, session_id)

    def list_sessions(self, owner):
        with self.connect() as conn:
            rows = conn.execute("""SELECT s.id,s.title,s.created_at,s.updated_at,
                (SELECT content FROM messages m WHERE m.session_id=s.id ORDER BY seq DESC LIMIT 1) preview
                FROM sessions s WHERE owner=? ORDER BY updated_at DESC LIMIT 200""", (owner,)).fetchall()
            return [dict(row) for row in rows]

    def rename(self, owner, session_id, title):
        with self.connect(write=True) as conn:
            self.owned(conn, owner, session_id)
            conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))

    def delete_session(self, owner, session_id):
        return self.request_session_deletion(owner, session_id)

    def messages(self, owner, session_id, *, before=None, limit=100):
        with self.connect() as conn:
            self.owned(conn, owner, session_id)
            rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq<?
                ORDER BY seq DESC LIMIT ?""", (session_id, before or 2**63-1, limit + 1)).fetchall()
            items = [dict(row) for row in reversed(rows[:limit])]
            images = {}
            if items:
                marks = ",".join("?" for _ in items)
                for image in conn.execute(f"SELECT message_id,id,name,mime,width,height FROM chat_images WHERE message_id IN ({marks}) ORDER BY position",
                                          [item["id"] for item in items]):
                    metadata = {key: image[key] for key in ("id", "name", "mime", "width", "height")}
                    images.setdefault(image["message_id"], []).append({**metadata, "url": "/api/chat/images/" + image["id"]})
            for item in items:
                item["images"] = images.get(item["id"], [])
            return {"items": items, "has_more": len(rows) > limit}

    def image(self, owner, identifier, *, session_id=None):
        with self.connect() as conn:
            row = conn.execute("""SELECT i.* FROM chat_images i JOIN messages m ON m.id=i.message_id
                JOIN sessions s ON s.id=m.session_id WHERE i.id=? AND s.owner=?""", (identifier, owner)).fetchone()
            if not row:
                raise ChatError("图片不存在或已删除。", 404)
            if session_id and not conn.execute("SELECT 1 FROM messages WHERE id=? AND session_id=?", (row["message_id"], session_id)).fetchone():
                raise ChatError("图片不属于当前会话。", 404)
            return dict(row)

    def turn_image_count(self, owner, session_id, request_id):
        with self.connect() as conn:
            self.owned(conn, owner, session_id)
            return conn.execute("""SELECT COUNT(*) FROM chat_images i JOIN messages m ON m.id=i.message_id
                WHERE m.session_id=? AND m.request_id=? AND m.role='user'""", (session_id, request_id)).fetchone()[0]

    def begin_turn(self, owner, session_id, request_id, content, selection, *, images=None):
        now = time.time()
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            completed = conn.execute("""SELECT * FROM messages WHERE session_id=? AND request_id=?
                AND role='assistant' AND status='complete'""", (session_id, request_id)).fetchone()
            previous = conn.execute("SELECT * FROM messages WHERE session_id=? AND request_id=? AND role='user'",
                                    (session_id, request_id)).fetchone()
            if previous and previous["content"] != content:
                raise ChatError("同一消息编号不能用于不同内容。", 409)
            if previous and previous["seq"] <= session["context_cutoff_seq"]:
                raise ChatError("该历史请求已失效，请用新的消息编号重新发送。", 409)
            if previous and images is not None:
                old = [row[0] for row in conn.execute("SELECT digest FROM chat_images WHERE message_id=? ORDER BY position", (previous["id"],))]
                if old != [hashlib.sha256(image["data"]).hexdigest() for image in images]:
                    raise ChatError("同一消息编号不能用于不同图片。", 409)
            if completed:
                return {"replay": dict(completed), "privacy_epoch": session["privacy_epoch"]}
            if session["sending_until"] > now:
                raise ChatError("当前对话正在回复，请稍后再发送。", 409)
            # A retry is allowed only for the most recent user turn. Older failures remain in history.
            if previous:
                latest = conn.execute("SELECT MAX(seq) FROM messages WHERE session_id=? AND role='user'",
                                      (session_id,)).fetchone()[0]
                if previous["seq"] != latest:
                    raise ChatError("此消息之后已有新对话，请重新发送。", 409)
                conn.execute("UPDATE messages SET status='complete' WHERE seq=?", (previous["seq"],))
            else:
                message_id = uuid4().hex
                conn.execute("INSERT INTO messages(id,session_id,request_id,role,content,status,created_at) VALUES(?,?,?,'user',?,'complete',?)",
                             (message_id, session_id, request_id, content, now))
                for position, image in enumerate(images or []):
                    conn.execute("INSERT INTO chat_images VALUES(?,?,?,?,?,?,?,?,?)",
                        (uuid4().hex, message_id, position, image["name"], image["mime"], image["data"],
                         image["width"], image["height"], hashlib.sha256(image["data"]).hexdigest()))
            token = uuid4().hex
            title = content.replace("\n", " ")[:24] if session["title"] == "新对话" else session["title"]
            conn.execute("UPDATE sessions SET sending_token=?,sending_until=?,selection=?,title=?,updated_at=?,sending_epoch=? WHERE id=?",
                         (token, now + 300, json.dumps(selection), title, now, session["privacy_epoch"], session_id))
            return {"token": token}

    def finish_turn(self, owner, session_id, request_id, token, content):
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            if session["sending_token"] != token or session["sending_epoch"] != session["privacy_epoch"]:
                raise ChatError("本轮回复已失效，请刷新对话。", 409)
            conn.execute("INSERT INTO messages(id,session_id,request_id,role,content,status,created_at) VALUES(?,?,?,'assistant',?,'complete',?)",
                         (uuid4().hex, session_id, request_id, content, time.time()))
            conn.execute("UPDATE sessions SET sending_token=NULL,sending_until=0,updated_at=? WHERE id=?", (time.time(), session_id))

    def check_turn(self, owner, session_id, token):
        with self.connect() as conn:
            row = self.owned(conn, owner, session_id)
            if row["sending_token"] != token or row["sending_epoch"] != row["privacy_epoch"]:
                raise ChatError("资料或记忆已变更，本轮回复已停止，请重新发送。", 409)
            return row["privacy_epoch"]

    def fail_turn(self, owner, session_id, request_id, token):
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT sending_token FROM sessions WHERE id=? AND owner=?", (session_id, owner)).fetchone()
            if row and row[0] == token:
                conn.execute("UPDATE sessions SET sending_token=NULL,sending_until=0 WHERE id=?", (session_id,))
                conn.execute("UPDATE messages SET status='failed' WHERE session_id=? AND request_id=? AND role='user'", (session_id, request_id))

    def enqueue(self, owner, session_id, *, immediate=False):
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            if session["sending_until"] > time.time():
                raise ChatError("请等待当前回复完成后再整理记忆。", 409)
            now = time.time()
            for kind, progress in (("memory", session["memory_seq"]), ("summary", session["analyzed_seq"])):
                cursor = max(progress, session["context_cutoff_seq"])
                rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq>? AND status='complete'
                    ORDER BY seq""", (session_id, cursor)).fetchall()
                if not any(row["role"] == "user" for row in rows):
                    continue
                due, priority, reason = self.policy.trigger(rows, kind=kind, immediate=immediate, now=now)
                conn.execute("""INSERT INTO memory_jobs(session_id,kind,due_at,requested_seq,priority,reason) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(session_id,kind) DO UPDATE SET requested_seq=excluded.requested_seq,
                    due_at=CASE WHEN status IN ('queued','running') AND priority>excluded.priority
                        THEN MIN(due_at,excluded.due_at) ELSE excluded.due_at END,
                    priority=CASE WHEN status IN ('queued','running') THEN MAX(priority,excluded.priority) ELSE excluded.priority END,
                    reason=CASE WHEN status IN ('queued','running') AND priority>excluded.priority THEN reason ELSE excluded.reason END,
                    status=CASE WHEN status='running' THEN status ELSE 'queued' END,
                    attempts=CASE WHEN status IN ('error','done') THEN 0 ELSE attempts END""",
                    (session_id, kind, due, rows[-1]["seq"], priority, reason))

    def claim_job(self, kind=None):
        now, token = time.time(), uuid4().hex
        with self.connect(write=True) as conn:
            row = conn.execute("""SELECT j.*,s.owner,s.analyzed_seq,s.memory_seq,s.summary,s.selection,
                CASE WHEN j.kind='summary' THEN s.analyzed_seq ELSE s.memory_seq END cursor FROM memory_jobs j
                JOIN sessions s ON s.id=j.session_id WHERE ((j.status='queued' AND j.due_at<=?)
                OR (j.status='running' AND j.lease_until<?)) AND (? IS NULL OR j.kind=?)
                ORDER BY j.priority DESC,j.due_at,j.kind LIMIT 1""", (now, now, kind, kind)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE memory_jobs SET status='running',token=?,lease_until=?,attempts=attempts+1 WHERE session_id=? AND kind=?",
                         (token, now + 300, row["session_id"], row["kind"]))
            return {**dict(row), "token": token, "attempts": row["attempts"] + 1}

    def analysis_messages(self, job):
        with self.connect() as conn:
            session = self.owned(conn, job["owner"], job["session_id"])
            rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq>? AND seq<=?
                AND status='complete' ORDER BY seq LIMIT ?""",
                (job["session_id"], max(job["cursor"], session["context_cutoff_seq"]), job["requested_seq"], self.policy.batch_messages)).fetchall()
        batch, size = [], 0
        for row in rows:
            tokens = estimate_tokens(row["content"])
            if batch and size + tokens > self.policy.batch_tokens:
                break
            batch.append(dict(row))
            size += tokens
        return batch

    @staticmethod
    def _current_job(conn, job):
        return conn.execute("""SELECT * FROM memory_jobs WHERE session_id=? AND kind=? AND token=? AND status='running'""",
                            (job["session_id"], job["kind"], job["token"])).fetchone()

    @staticmethod
    def _complete_job(conn, job, current, last):
        more = current["requested_seq"] > last
        conn.execute("UPDATE memory_jobs SET status=?,due_at=?,attempts=0,priority=? WHERE session_id=? AND kind=? AND token=?",
                     ("queued" if more else "done", time.time(), current["priority"] if more else 0,
                      job["session_id"], job["kind"], job["token"]))

    def renew_job(self, job):
        with self.connect(write=True) as conn:
            row = conn.execute("UPDATE memory_jobs SET lease_until=? WHERE session_id=? AND kind=? AND token=? AND status='running'",
                               (time.time() + 300, job["session_id"], job["kind"], job["token"]))
            if not row.rowcount:
                raise ChatError("记忆任务已被其他进程接管。", 409)

    def apply_summary(self, job, messages, summary):
        if job["kind"] != "summary" or not isinstance(summary, str) or len(summary) > 2500 or not messages:
            raise ValueError("Invalid summary result")
        with self.connect(write=True) as conn:
            current = self._current_job(conn, job)
            if not current:
                return False
            self.owned(conn, job["owner"], job["session_id"])
            last = messages[-1]["seq"]
            conn.execute("UPDATE sessions SET summary=?,analyzed_seq=? WHERE id=?", (summary, last, job["session_id"]))
            self._complete_job(conn, job, current, last)
            return True

    def memory_snapshot(self, owner):
        with self.connect() as conn:
            conn.execute("BEGIN")
            revision = conn.execute("SELECT revision FROM memory_owners WHERE owner=?", (owner,)).fetchone()
            rows = conn.execute("SELECT * FROM memories WHERE owner=? AND status IN ('active','conflict') ORDER BY updated_at DESC", (owner,)).fetchall()
            blocked = {(row["kind"], row["key"], row["subject"]) for row in conn.execute(
                "SELECT kind,key,subject FROM memory_suppressions WHERE owner=? AND active=1", (owner,))}
            return revision[0] if revision else 0, [dict(row) for row in rows
                if (row["kind"], row["key"], self._subject_token(owner, row)) not in blocked]

    def slot_memories(self, owner, candidate):
        slot = memory_id(owner, candidate["kind"], candidate["key"], candidate["subject"])
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM memories WHERE owner=? AND (id=? OR id LIKE ?)",
                    (owner, slot, slot + ":conflict:%"))]

    def memories_by_ids(self, owner, ids, *, kind, key):
        with self.connect() as conn:
            rows = [conn.execute("SELECT * FROM memories WHERE owner=? AND id=? AND kind=? AND key=? AND status='active'",
                                 (owner, identifier, kind, key)).fetchone() for identifier in ids[:5]]
            return [dict(row) for row in rows if row and ":conflict:" not in row["id"]]

    def apply_memory_plan(self, job, messages, candidates, decisions, expected_revision):
        from .extraction import validate_candidates
        from .reconciliation import validate_decision

        if job["kind"] != "memory" or len(candidates) != len(decisions) or not messages:
            raise ValueError("Invalid memory plan")
        owner, now, last = job["owner"], time.time(), messages[-1]["seq"]
        with self.connect(write=True) as conn:
            current = self._current_job(conn, job)
            if not current:
                return False
            session = self.owned(conn, owner, job["session_id"])
            revision = conn.execute("SELECT revision FROM memory_owners WHERE owner=?", (owner,)).fetchone()
            if (revision[0] if revision else 0) != expected_revision:
                conn.execute("UPDATE memory_jobs SET status='queued',due_at=? WHERE session_id=? AND kind='memory' AND token=?",
                             (now, job["session_id"], job["token"]))
                return False
            sources = [dict(row) for row in conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq>? AND seq<=?
                AND status='complete' ORDER BY seq""", (job["session_id"], max(job["cursor"], session["context_cutoff_seq"]), last))]
            if not sources or sources[-1]["seq"] != last or last > current["requested_seq"]:
                raise ValueError("Plan is outside the claimed message range")
            validated = validate_candidates({"memories": candidates}, sources)
            if len(validated) != len(decisions) or validated != candidates:
                raise ValueError("All decisions need validated candidates")
            source_times = {row["id"]: row["created_at"] for row in sources if row["role"] == "user"}
            for candidate, raw_decision in zip(candidates, decisions):
                if not isinstance(raw_decision, dict):
                    raise ValueError("Invalid decision object")
                if not self.candidate_allowed(owner, candidate, sources, conn=conn):
                    continue
                slot = memory_id(owner, candidate["kind"], candidate["key"], candidate["subject"])
                target_id = raw_decision.get("target_id")
                old_row = conn.execute("SELECT * FROM memories WHERE owner=? AND id=?", (owner, target_id or slot)).fetchone()
                old = dict(old_row) if old_row else None
                if old:
                    slot = old["id"]
                    if not self.candidate_allowed(owner, {**candidate, "subject": old["subject"]}, sources, conn=conn):
                        continue
                if old and normalized(old["subject"]) != normalized(candidate["subject"]) and candidate["key"] != "experience":
                    raise ValueError("Only experience aliases can use semantic targets")
                decision = validate_decision(raw_decision, candidate, [old] if old else [])
                op, value = decision["operation"], decision["value"]
                source_at = max(source_times[item["message_id"]] for item in candidate["evidence"])
                if old and old["source_at"] > source_at:
                    op, value = "NOOP", old["value"]
                    decision = {**decision, "reason": "older_evidence_ignored"}
                else:
                    if old:
                        slot = old["id"]
                    evidence = list(json.loads(old["evidence"])) if old else []
                    evidence.extend(item for item in candidate["evidence"] if item not in evidence)
                    if op == "RETRACT":
                        self._delete_memory(conn, owner, old["id"] if old else slot, mode="forget", slot_hint=candidate)
                        return True  # The barrier revoked this batch; later candidates must not restore excerpts.
                    elif op == "NOOP":
                        if old:
                            conn.execute("UPDATE memories SET evidence=?,source_at=?,updated_at=?,source_session=? WHERE id=? AND owner=?",
                                (json.dumps(evidence[-20:], ensure_ascii=False), source_at, now, job["session_id"], slot, owner))
                    else:
                        subject = old["subject"] if old else candidate["subject"]
                        if op == "CONFLICT":
                            slot += ":conflict:" + hashlib.sha256(normalized(value).encode()).hexdigest()[:16]
                        if op == "REPLACE":
                            conn.execute("UPDATE memories SET status='resolved',revision=revision+1,updated_at=? WHERE owner=? AND id LIKE ? AND status='conflict'",
                                         (now, owner, slot + ":conflict:%"))
                        conn.execute("""INSERT INTO memories(id,owner,kind,key,subject,value,evidence,source_session,status,created_at,updated_at,source_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value,
                            evidence=excluded.evidence,source_session=excluded.source_session,status=excluded.status,
                            revision=revision+1,updated_at=excluded.updated_at,source_at=excluded.source_at""",
                            (slot, owner, candidate["kind"], candidate["key"], subject, value,
                             json.dumps(evidence[-20:] if op == "ENRICH" else candidate["evidence"], ensure_ascii=False),
                             job["session_id"], "conflict" if op == "CONFLICT" else "active", now, now, source_at))
                    if op in {"ADD", "REPLACE", "ENRICH"}:
                        conn.execute("UPDATE memory_suppressions SET active=0 WHERE owner=? AND kind=? AND key=? AND subject=?",
                                     (owner, candidate["kind"], candidate["key"], self._subject_token(owner, candidate)))
                    for quote in candidate["evidence"]:
                        conn.execute("INSERT OR IGNORE INTO memory_sources VALUES(?,?,?)", (owner, slot, quote["message_id"]))
                conn.execute("""INSERT INTO memory_events(owner,memory_id,source_session,operation,before_value,after_value,evidence,decision,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (owner, slot, job["session_id"], op, old["value"] if old else None,
                    None if op == "RETRACT" else value, json.dumps(candidate["evidence"], ensure_ascii=False),
                    json.dumps({**decision, "confidence": candidate["confidence"]}, ensure_ascii=False), now))
            conn.execute("INSERT INTO memory_owners(owner,revision) VALUES(?,1) ON CONFLICT(owner) DO UPDATE SET revision=revision+1", (owner,))
            conn.execute("UPDATE sessions SET memory_seq=? WHERE id=?", (last, job["session_id"]))
            self._complete_job(conn, job, current, last)
            return True

    def memory_events(self, owner, *, limit=100):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM memory_events WHERE owner=? ORDER BY seq DESC LIMIT ?", (owner, limit))]

    def fail_job(self, job):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memory_jobs SET status=?,due_at=? WHERE session_id=? AND kind=? AND token=? AND status='running'",
                         ("error" if job["attempts"] >= 3 else "queued", time.time() + 60 * job["attempts"],
                          job["session_id"], job["kind"], job["token"]))

    def memory_status(self, owner):
        with self.connect() as conn:
            rows = conn.execute("SELECT j.kind,j.status,COUNT(*) total FROM memory_jobs j JOIN sessions s ON s.id=j.session_id WHERE owner=? GROUP BY j.kind,j.status", (owner,)).fetchall()
            result = {"memory": {}, "summary": {}}
            for row in rows:
                result[row["kind"]][row["status"]] = row["total"]
                result[row["status"]] = result.get(row["status"], 0) + row["total"]
            return result

    def save_context_trace(self, owner, session_id, request_id, trace, *, epoch):
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            if epoch != session["privacy_epoch"]:
                raise ChatError("记忆已变更，上下文快照已失效。", 409)
            conn.execute("INSERT OR REPLACE INTO context_traces VALUES(?,?,?,?)",
                         (session_id, request_id, json.dumps(trace, ensure_ascii=False), time.time()))
            identifiers = set(trace.get("supplied_memory_ids", [])) | {row["id"] for row in trace.get("memories", []) if isinstance(row, dict) and isinstance(row.get("id"), str)}
            for identifier in identifiers:
                if conn.execute("SELECT 1 FROM memories WHERE id=? AND owner=?", (identifier, owner)).fetchone():
                    conn.execute("INSERT OR IGNORE INTO memory_usages VALUES(?,?,?,?)", (owner, identifier, session_id, request_id))
            # Only the latest few audit snapshots are needed; chat history remains separate.
            conn.execute("""DELETE FROM context_traces WHERE session_id=? AND request_id NOT IN
                (SELECT request_id FROM context_traces WHERE session_id=? ORDER BY created_at DESC LIMIT 10)""", (session_id, session_id))

    def context_trace(self, owner, session_id):
        with self.connect() as conn:
            self.owned(conn, owner, session_id)
            row = conn.execute("SELECT payload,created_at,request_id FROM context_traces WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
            return {**json.loads(row["payload"]), "created_at": row["created_at"], "request_id": row["request_id"]} if row else None

    def index_pending(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("""SELECT m.*,COALESCE(p.epoch,0) privacy_epoch FROM memories m
                LEFT JOIN chat_privacy p ON p.owner=m.owner WHERE m.revision>m.indexed_revision
                AND NOT EXISTS(SELECT 1 FROM cleanup_jobs j WHERE j.owner=m.owner AND j.status!='completed') LIMIT 100""").fetchall()]

    def mark_indexed(self, memory_id, revision):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memories SET indexed_revision=? WHERE id=? AND revision=?", (revision, memory_id, revision))

    def reset_index(self):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memories SET indexed_revision=0")

    def delete_owner(self, owner):
        return self.clear_chat_data(owner)
