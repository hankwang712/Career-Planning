"""Durable chat records and a leased, retryable memory-analysis queue."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import unicodedata
from uuid import uuid4


class ChatError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class ChatStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    summary TEXT NOT NULL DEFAULT '', analyzed_seq INTEGER NOT NULL DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS memory_jobs (
                    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
                    due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    token TEXT, lease_until REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, requested_seq INTEGER NOT NULL DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS resume_documents (
                    owner TEXT NOT NULL, fingerprint TEXT NOT NULL, content TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL, PRIMARY KEY(owner, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS context_traces (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(session_id, request_id)
                );
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
            if "source_at" not in columns:
                conn.execute("ALTER TABLE memories ADD COLUMN source_at REAL NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
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
        row = conn.execute("SELECT * FROM sessions WHERE id=? AND owner=?", (session_id, owner)).fetchone()
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
        with self.connect(write=True) as conn:
            self.owned(conn, owner, session_id)
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def messages(self, owner, session_id, *, before=None, limit=100):
        with self.connect() as conn:
            self.owned(conn, owner, session_id)
            rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq<?
                ORDER BY seq DESC LIMIT ?""", (session_id, before or 2**63-1, limit + 1)).fetchall()
            return {"items": [dict(row) for row in reversed(rows[:limit])], "has_more": len(rows) > limit}

    def begin_turn(self, owner, session_id, request_id, content, selection):
        now = time.time()
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            completed = conn.execute("""SELECT * FROM messages WHERE session_id=? AND request_id=?
                AND role='assistant' AND status='complete'""", (session_id, request_id)).fetchone()
            previous = conn.execute("SELECT * FROM messages WHERE session_id=? AND request_id=? AND role='user'",
                                    (session_id, request_id)).fetchone()
            if previous and previous["content"] != content:
                raise ChatError("同一消息编号不能用于不同内容。", 409)
            if completed:
                return {"replay": dict(completed)}
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
                conn.execute("INSERT INTO messages(id,session_id,request_id,role,content,status,created_at) VALUES(?,?,?,'user',?,'complete',?)",
                             (uuid4().hex, session_id, request_id, content, now))
            token = uuid4().hex
            title = content.replace("\n", " ")[:24] if session["title"] == "新对话" else session["title"]
            conn.execute("UPDATE sessions SET sending_token=?,sending_until=?,selection=?,title=?,updated_at=? WHERE id=?",
                         (token, now + 300, json.dumps(selection), title, now, session_id))
            return {"token": token}

    def finish_turn(self, owner, session_id, request_id, token, content):
        with self.connect(write=True) as conn:
            session = self.owned(conn, owner, session_id)
            if session["sending_token"] != token:
                raise ChatError("本轮回复已失效，请刷新对话。", 409)
            conn.execute("INSERT INTO messages(id,session_id,request_id,role,content,status,created_at) VALUES(?,?,?,'assistant',?,'complete',?)",
                         (uuid4().hex, session_id, request_id, content, time.time()))
            conn.execute("UPDATE sessions SET sending_token=NULL,sending_until=0,updated_at=? WHERE id=?", (time.time(), session_id))

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
            rows = conn.execute("SELECT MAX(seq),COUNT(*) FROM messages WHERE session_id=? AND seq>? AND role='user' AND status='complete'",
                                (session_id, session["analyzed_seq"])).fetchone()
            if not rows[0]:
                return
            maximum = conn.execute("SELECT MAX(seq) FROM messages WHERE session_id=? AND status='complete'", (session_id,)).fetchone()[0]
            due = time.time() if immediate or rows[1] >= 5 else time.time() + 900
            conn.execute("""INSERT INTO memory_jobs(session_id,due_at,requested_seq) VALUES(?,?,?)
                ON CONFLICT(session_id) DO UPDATE SET requested_seq=excluded.requested_seq,
                due_at=CASE WHEN status='queued' THEN MIN(due_at,excluded.due_at) ELSE excluded.due_at END,
                status=CASE WHEN status='running' THEN status ELSE 'queued' END,
                attempts=CASE WHEN status='error' THEN 0 ELSE attempts END""", (session_id, due, maximum))

    def claim_job(self):
        now, token = time.time(), uuid4().hex
        with self.connect(write=True) as conn:
            row = conn.execute("""SELECT j.*,s.owner,s.analyzed_seq,s.summary,s.selection FROM memory_jobs j
                JOIN sessions s ON s.id=j.session_id WHERE (j.status='queued' AND j.due_at<=?)
                OR (j.status='running' AND j.lease_until<?) ORDER BY j.due_at LIMIT 1""", (now, now)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE memory_jobs SET status='running',token=?,lease_until=?,attempts=attempts+1 WHERE session_id=?",
                         (token, now + 300, row["session_id"]))
            return {**dict(row), "token": token, "attempts": row["attempts"] + 1}

    def analysis_messages(self, job):
        with self.connect() as conn:
            rows = conn.execute("""SELECT * FROM messages WHERE session_id=? AND seq>? AND seq<=?
                AND status='complete' ORDER BY seq LIMIT 40""", (job["session_id"], job["analyzed_seq"], job["requested_seq"])).fetchall()
        batch, size = [], 0
        for row in rows:
            if batch and size + len(row["content"]) > 50000:
                break
            batch.append(dict(row))
            size += len(row["content"])
        return batch

    def memory_snapshot(self, owner):
        with self.connect() as conn:
            conn.execute("BEGIN")
            revision = conn.execute("SELECT revision FROM memory_owners WHERE owner=?", (owner,)).fetchone()
            rows = conn.execute("SELECT * FROM memories WHERE owner=? AND status IN ('active','conflict') ORDER BY updated_at DESC", (owner,)).fetchall()
            return revision[0] if revision else 0, [dict(row) for row in rows]

    def apply_analysis(self, job, messages, result, expected_revision):
        owner, now = job["owner"], time.time()
        with self.connect(write=True) as conn:
            current = conn.execute("SELECT * FROM memory_jobs WHERE session_id=? AND token=? AND status='running'", (job["session_id"], job["token"])).fetchone()
            if not current:
                return False
            revision = conn.execute("SELECT revision FROM memory_owners WHERE owner=?", (owner,)).fetchone()
            if (revision[0] if revision else 0) != expected_revision:
                conn.execute("UPDATE memory_jobs SET status='queued',due_at=? WHERE session_id=?", (now, job["session_id"]))
                return False
            source_times = {row["id"]: row["created_at"] for row in messages}
            for item in result["memories"]:
                slot = hashlib.sha256(json.dumps([owner, item["kind"], item["key"], normalized(item["subject"])], ensure_ascii=False).encode()).hexdigest()
                old = conn.execute("SELECT * FROM memories WHERE id=?", (slot,)).fetchone()
                source_at = max(source_times[quote["message_id"]] for quote in item["evidence"])
                if old and old["source_at"] > source_at:
                    continue  # An older conversation cannot replace a more recent user statement.
                operation, status = item["operation"], "active"
                if operation == "retract":
                    if old:
                        conn.execute("UPDATE memories SET status='retracted',revision=revision+1,updated_at=? WHERE id=?", (now, slot))
                    continue
                if old and old["status"] == "retracted" and operation != "correct":
                    continue  # Background retries cannot silently restore a forgotten memory.
                if old and normalized(old["value"]) == normalized(item["value"]):
                    conn.execute("UPDATE memories SET source_at=?,updated_at=?,evidence=?,source_session=? WHERE id=?",
                                 (source_at, now, json.dumps(item["evidence"], ensure_ascii=False), job["session_id"], slot))
                    continue
                if old and old["status"] == "active" and item["kind"] == "fact" and operation != "correct":
                    slot += ":conflict:" + job["token"]
                    status = "conflict"
                if operation == "correct":
                    conn.execute("UPDATE memories SET status='resolved',revision=revision+1 WHERE owner=? AND kind=? AND key=? AND subject=? AND status='conflict'",
                                 (owner, item["kind"], item["key"], item["subject"]))
                conn.execute("""INSERT INTO memories(id,owner,kind,key,subject,value,evidence,source_session,status,created_at,updated_at,source_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value,
                    evidence=excluded.evidence,source_session=excluded.source_session,status=excluded.status,
                    revision=revision+1,updated_at=excluded.updated_at,source_at=excluded.source_at""",
                    (slot, owner, item["kind"], item["key"], item["subject"], item["value"], json.dumps(item["evidence"], ensure_ascii=False),
                     job["session_id"], status, now, now, source_at))
            conn.execute("INSERT INTO memory_owners(owner,revision) VALUES(?,1) ON CONFLICT(owner) DO UPDATE SET revision=revision+1", (owner,))
            last = messages[-1]["seq"]
            conn.execute("UPDATE sessions SET summary=?,analyzed_seq=? WHERE id=?", (result["summary"], last, job["session_id"]))
            conn.execute("UPDATE memory_jobs SET status=?,due_at=?,attempts=0 WHERE session_id=?",
                         ("queued" if current["requested_seq"] > last else "done", now, job["session_id"]))
            return True

    def fail_job(self, job):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memory_jobs SET status=?,due_at=? WHERE session_id=? AND token=? AND status='running'",
                         ("error" if job["attempts"] >= 3 else "queued", time.time() + 60 * job["attempts"], job["session_id"], job["token"]))

    def forget(self, owner, memory_id):
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT * FROM memories WHERE id=? AND owner=? AND status IN ('active','conflict')", (memory_id, owner)).fetchone()
            if not row:
                raise ChatError("记忆不存在。", 404)
            now = time.time()
            conn.execute("UPDATE memories SET status='retracted',revision=revision+1,updated_at=?,source_at=? WHERE id=?", (now, now, memory_id))
            conn.execute("INSERT INTO memory_owners(owner,revision) VALUES(?,1) ON CONFLICT(owner) DO UPDATE SET revision=revision+1", (owner,))

    def memory_status(self, owner):
        with self.connect() as conn:
            rows = conn.execute("SELECT status,COUNT(*) total FROM memory_jobs j JOIN sessions s ON s.id=j.session_id WHERE owner=? GROUP BY status", (owner,)).fetchall()
            return {row["status"]: row["total"] for row in rows}

    def document(self, owner, fingerprint):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM resume_documents WHERE owner=? AND fingerprint=?", (owner, fingerprint)).fetchone()
            return dict(row) if row else None

    def save_document(self, owner, fingerprint, *, status, content="", metadata=None, error=""):
        with self.connect(write=True) as conn:
            conn.execute("""INSERT INTO resume_documents(owner,fingerprint,status,content,metadata,error,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,fingerprint) DO UPDATE SET status=excluded.status,
                content=excluded.content,metadata=excluded.metadata,error=excluded.error,updated_at=excluded.updated_at""",
                (owner, fingerprint, status, content, json.dumps(metadata or {}, ensure_ascii=False), error, time.time()))

    def forget_documents(self, owner):
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM resume_documents WHERE owner=?", (owner,))

    def save_context_trace(self, owner, session_id, request_id, trace):
        with self.connect(write=True) as conn:
            self.owned(conn, owner, session_id)
            conn.execute("INSERT OR REPLACE INTO context_traces VALUES(?,?,?,?)",
                         (session_id, request_id, json.dumps(trace, ensure_ascii=False), time.time()))
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
            return [dict(row) for row in conn.execute("SELECT * FROM memories WHERE revision>indexed_revision LIMIT 100").fetchall()]

    def mark_indexed(self, memory_id, revision):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memories SET indexed_revision=? WHERE id=? AND revision=?", (revision, memory_id, revision))

    def reset_index(self):
        with self.connect(write=True) as conn:
            conn.execute("UPDATE memories SET indexed_revision=0")

    def delete_owner(self, owner):
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE owner=?", (owner,))
            conn.execute("DELETE FROM memories WHERE owner=?", (owner,))
            conn.execute("DELETE FROM memory_owners WHERE owner=?", (owner,))
            conn.execute("DELETE FROM resume_documents WHERE owner=?", (owner,))
