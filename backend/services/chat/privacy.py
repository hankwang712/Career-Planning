"""User controls and durable cleanup outbox, sharing ChatStore transactions.

Receipts and suppressions keep identifiers/cursors only, never forgotten values.
Cleanup completion covers managed application stores, not external logs/backups
or data already sent to a model provider. Resume files and reports are separate.
"""

import json
import time
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_privacy (
    owner TEXT PRIMARY KEY, epoch INTEGER NOT NULL DEFAULT 0, cutoff_seq INTEGER NOT NULL DEFAULT 0,
    workspace_enabled INTEGER NOT NULL DEFAULT 1, resume_enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS memory_suppressions (
    owner TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, subject TEXT NOT NULL,
    source_cutoff_seq INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
    PRIMARY KEY(owner,kind,key,subject));
CREATE TABLE IF NOT EXISTS memory_sources (
    owner TEXT NOT NULL, memory_id TEXT NOT NULL, message_id TEXT NOT NULL,
    PRIMARY KEY(owner,memory_id,message_id));
CREATE TABLE IF NOT EXISTS memory_usages (
    owner TEXT NOT NULL, memory_id TEXT NOT NULL, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
    PRIMARY KEY(owner,memory_id,session_id,request_id));
CREATE TABLE IF NOT EXISTS cleanup_jobs (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL, target_id TEXT NOT NULL,
    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', due_at REAL NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until REAL NOT NULL DEFAULT 0,
    error_code TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, completed_at REAL);
CREATE INDEX IF NOT EXISTS cleanup_owner ON cleanup_jobs(owner,scope,target_id,created_at);
CREATE INDEX IF NOT EXISTS cleanup_ready ON cleanup_jobs(status,due_at);
CREATE TABLE IF NOT EXISTS artifact_leases (
    token TEXT PRIMARY KEY, owner TEXT NOT NULL, epoch INTEGER NOT NULL, kind TEXT NOT NULL, lease_until REAL NOT NULL);
"""

SCOPE = {
    "managed": ["SQLite聊天记录、图片附件及衍生数据", "Redis聊天缓存", "Chroma记忆索引"],
    "excluded": ["独立简历文件与解析资料", "已有规划报告", "外部日志和备份", "模型服务商已接收的数据"],
    "retained_metadata": "仅保留任务回执、删除保护槽位与游标，不保留已忘记的值或原文证据。",
    "restore_rule": "已忘记的属性只接受删除之后新的明确“请重新记住”授权；旧消息不能恢复记忆。",
}


class MemoryControls:
    """Mixin: connect()/owned() are supplied by the SQLite chat repository."""

    @staticmethod
    def _subject_token(owner, slot):
        from .storage import memory_id
        slot = dict(slot)
        return slot.get("subject_hash") or "sha256:" + memory_id(owner, slot["kind"], slot["key"], slot["subject"])

    def privacy(self, owner):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM chat_privacy WHERE owner=?", (owner,)).fetchone()
            return dict(row) if row else {"owner": owner, "epoch": 0, "cutoff_seq": 0,
                                          "workspace_enabled": 1, "resume_enabled": 1}

    @staticmethod
    def _latest_cleanup(conn, owner, target, scopes):
        marks = ",".join("?" for _ in scopes)
        return conn.execute(f"SELECT * FROM cleanup_jobs WHERE owner=? AND target_id=? AND scope IN ({marks}) ORDER BY created_at DESC,rowid DESC LIMIT 1",
                            (owner, target, *scopes)).fetchone()

    @staticmethod
    def _queue_cleanup(conn, owner, scope, target, payload):
        identifier, now = uuid4().hex, time.time()
        conn.execute("INSERT INTO cleanup_jobs(id,owner,scope,target_id,payload,due_at,created_at) VALUES(?,?,?,?,?,?,?)",
                     (identifier, owner, scope, target, json.dumps(payload, ensure_ascii=False), now, now))
        return identifier

    @staticmethod
    def _barrier(conn, owner, *, disable_sources=True):
        conn.execute("INSERT OR IGNORE INTO chat_privacy(owner) VALUES(?)", (owner,))
        cutoff = conn.execute("SELECT COALESCE(MAX(m.seq),0) FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.owner=?", (owner,)).fetchone()[0]
        conn.execute("""UPDATE chat_privacy SET epoch=epoch+1,cutoff_seq=MAX(cutoff_seq,?),
            workspace_enabled=CASE WHEN ? THEN 0 ELSE workspace_enabled END,
            resume_enabled=CASE WHEN ? THEN 0 ELSE resume_enabled END WHERE owner=?""", (cutoff, disable_sources, disable_sources, owner))
        cutoff = conn.execute("SELECT cutoff_seq FROM chat_privacy WHERE owner=?", (owner,)).fetchone()[0]
        sessions = [row[0] for row in conn.execute("SELECT id FROM sessions WHERE owner=?", (owner,))]
        conn.execute("DELETE FROM memory_jobs WHERE session_id IN (SELECT id FROM sessions WHERE owner=?)", (owner,))
        conn.execute("DELETE FROM context_traces WHERE session_id IN (SELECT id FROM sessions WHERE owner=?)", (owner,))
        conn.execute("""UPDATE messages SET status='failed' WHERE role='user' AND seq IN
            (SELECT MAX(m.seq) FROM messages m JOIN sessions s ON s.id=m.session_id
             WHERE s.owner=? AND s.sending_token IS NOT NULL AND m.role='user' GROUP BY s.id)""", (owner,))
        conn.execute("""UPDATE sessions SET summary='',analyzed_seq=MAX(analyzed_seq,?),memory_seq=MAX(memory_seq,?),sending_token=NULL,
            sending_until=0,updated_at=? WHERE owner=?""", (cutoff, cutoff, time.time(), owner))
        conn.execute("UPDATE memories SET revision=revision+1,indexed_revision=0 WHERE owner=?", (owner,))
        conn.execute("INSERT INTO memory_owners(owner,revision) VALUES(?,1) ON CONFLICT(owner) DO UPDATE SET revision=revision+1", (owner,))
        return cutoff, sessions

    def _suppress(self, conn, owner, slot, cutoff, *, active=True):
        conn.execute("""INSERT INTO memory_suppressions(owner,kind,key,subject,source_cutoff_seq,active,created_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,kind,key,subject) DO UPDATE SET
            source_cutoff_seq=MAX(source_cutoff_seq,excluded.source_cutoff_seq),active=excluded.active,created_at=excluded.created_at""",
            (owner, slot["kind"], slot["key"], self._subject_token(owner, slot), cutoff, active, time.time()))

    def candidate_allowed(self, owner, candidate, messages, *, conn=None):
        import re
        if conn is None:
            with self.connect() as connection:
                return self.candidate_allowed(owner, candidate, messages, conn=connection)
        source = {row["id"]: row for row in messages if row["role"] == "user"}
        evidence = [source.get(item["message_id"]) for item in candidate["evidence"]]
        if not evidence or any(row is None for row in evidence):
            return False
        seq = min(row["seq"] for row in evidence)
        suppression = conn.execute("SELECT * FROM memory_suppressions WHERE owner=? AND kind=? AND key=? AND subject=?",
            (owner, candidate["kind"], candidate["key"], self._subject_token(owner, candidate))).fetchone()
        if not suppression:
            return True
        if seq <= suppression["source_cutoff_seq"]:
            return False
        explicit = candidate["operation"] == "correct" and bool(re.search(r"重新.*记|恢复.*记|再记住|记回|restore", " ".join(row["content"] for row in evidence), re.I))
        return not suppression["active"] or explicit or candidate["operation"] == "retract"

    def request_memory_deletion(self, owner, identifier, *, mode="forget"):
        if mode not in {"forget", "purge"}:
            raise ValueError("Unknown deletion mode")
        with self.connect(write=True) as conn:
            return self._delete_memory(conn, owner, identifier, mode=mode)

    def _delete_memory(self, conn, owner, identifier, *, mode, slot_hint=None):
        from .storage import ChatError, memory_id, normalized
        import re
        row = conn.execute("SELECT * FROM memories WHERE owner=? AND id=?", (owner, identifier)).fetchone()
        previous = self._latest_cleanup(conn, owner, identifier, ("forget", "purge"))
        if not row:
            if previous and slot_hint is None and (mode == "forget" or previous["scope"] == "purge"):
                return previous["id"]
            if not previous and slot_hint is None:
                raise ChatError("记忆不存在。", 404)
        slots = [dict(row)] if row else [slot_hint] if slot_hint else json.loads(previous["payload"]).get("slots", [])
        base = slots[0].get("slot_id") or memory_id(owner, slots[0]["kind"], slots[0]["key"], slots[0]["subject"])
        rows = [dict(item) for item in conn.execute("SELECT * FROM memories WHERE owner=?", (owner,))]
        removed = {item["id"] for item in rows if item["id"] == base or item["id"].startswith(base + ":conflict:")}
        source_ids = set(json.loads(previous["payload"]).get("message_ids", [])) if previous else set()
        if slot_hint:
            source_ids.update(item["message_id"] for item in slot_hint.get("evidence", []))
        messages = [dict(item) for item in conn.execute("SELECT m.* FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.owner=?", (owner,))]
        by_turn = {}
        for message in messages:
            by_turn.setdefault((message["session_id"], message["request_id"]), set()).add(message["id"])
        # Legacy transcripts predate usage tracking; identify literal copies while
        # the value is still available, then retain only IDs for later escalation.
        terms = {normalized(term) for item in rows if item["id"] in removed
                 for term in re.split(r"[、,，;；/]", item["value"]) if len(term.strip()) >= 2}
        if slot_hint:
            terms.update(normalized(term) for term in re.split(r"[、,，;；/]", slot_hint.get("value", "")) if len(term.strip()) >= 2)
        for message in messages:
            if any(term in normalized(message["content"]) for term in terms):
                source_ids.add(message["id"])
        # Provenance references survive excerpt scrubbing, but contain no message text.
        references = {}
        for item in conn.execute("SELECT memory_id,message_id FROM memory_sources WHERE owner=?", (owner,)):
            references.setdefault(item["memory_id"], set()).add(item["message_id"])
        for item in rows:
            references.setdefault(item["id"], set()).update(quote["message_id"] for quote in json.loads(item["evidence"]) if "message_id" in quote)
        for event in conn.execute("SELECT memory_id,evidence FROM memory_events WHERE owner=?", (owner,)):
            references.setdefault(event["memory_id"], set()).update(quote["message_id"] for quote in json.loads(event["evidence"]) if "message_id" in quote)
        usages = list(conn.execute("SELECT memory_id,session_id,request_id FROM memory_usages WHERE owner=?", (owner,)))
        while True:
            before = (len(removed), len(source_ids))
            for memory in removed:
                source_ids.update(references.get(memory, set()))
            for usage in usages:
                if usage["memory_id"] in removed:
                    source_ids.update(by_turn.get((usage["session_id"], usage["request_id"]), set()))
            for message in messages:
                if message["id"] in source_ids:
                    source_ids.update(by_turn[(message["session_id"], message["request_id"])])
            if mode == "purge":
                removed.update(memory for memory, refs in references.items() if refs & source_ids)
            if before == (len(removed), len(source_ids)):
                break
        cutoff, sessions = self._barrier(conn, owner)
        slots = [{key: item[key] for key in ("kind", "key", "subject")} for item in rows if item["id"] in removed] or slots
        for slot in slots:
            self._suppress(conn, owner, slot, cutoff)
        for memory in removed:
            conn.execute("DELETE FROM memories WHERE owner=? AND id=?", (owner, memory))
            conn.execute("DELETE FROM memory_sources WHERE owner=? AND memory_id=?", (owner, memory))
            conn.execute("DELETE FROM memory_usages WHERE owner=? AND memory_id=?", (owner, memory))
        # Quotes and prior audit payloads can mention other slots in the same sentence.
        conn.execute("UPDATE memories SET evidence='[]' WHERE owner=?", (owner,))
        conn.execute("DELETE FROM memory_events WHERE owner=?", (owner,))
        if mode == "purge" and source_ids:
            for message_id in source_ids:
                source = conn.execute("SELECT m.* FROM messages m JOIN sessions s ON s.id=m.session_id WHERE m.id=? AND s.owner=?", (message_id, owner)).fetchone()
                if source:
                    conn.execute("DELETE FROM memory_usages WHERE owner=? AND session_id=? AND request_id=?", (owner, source["session_id"], source["request_id"]))
                    conn.execute("DELETE FROM messages WHERE session_id=? AND request_id=?", (source["session_id"], source["request_id"]))
            conn.execute("UPDATE sessions SET title='新对话' WHERE owner=?", (owner,))
        safe_slots = [{"kind": slot["kind"], "key": slot["key"], "subject_hash": self._subject_token(owner, slot),
                       "slot_id": self._subject_token(owner, slot).removeprefix("sha256:")} for slot in slots]
        payload = {"cache_sessions": sessions, "cache_owner": True, "vector_owner": True,
                   "message_ids": sorted(source_ids), "slots": safe_slots}
        return self._queue_cleanup(conn, owner, mode, identifier, payload)

    def forget(self, owner, identifier):
        return self.request_memory_deletion(owner, identifier)

    def correct_memory(self, owner, identifier, value):
        from .storage import ChatError, memory_id
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
            raise ChatError("请输入 1～1000 字的记忆内容。")
        with self.connect(write=True) as conn:
            selected = conn.execute("SELECT * FROM memories WHERE owner=? AND id=?", (owner, identifier)).fetchone()
            row = None if not selected else conn.execute("SELECT * FROM memories WHERE owner=? AND id=? AND status='active'",
                (owner, memory_id(owner, selected["kind"], selected["key"], selected["subject"]))).fetchone()
            if not row:
                raise ChatError("只能纠正当前账号的有效记忆。", 404)
            canonical = row["id"]
            previous = self._latest_cleanup(conn, owner, identifier, ("edit",))
            conflicts = conn.execute("SELECT 1 FROM memories WHERE owner=? AND id LIKE ? AND status='conflict' LIMIT 1", (owner, canonical + ":conflict:%")).fetchone()
            if row["value"] == value.strip() and previous and not conflicts:
                return previous["id"]
            cutoff, sessions = self._barrier(conn, owner, disable_sources=False)
            self._suppress(conn, owner, row, cutoff, active=False)
            conn.execute("UPDATE memories SET value=?,evidence='[]',source_at=?,updated_at=? WHERE owner=? AND id=?",
                         (value.strip(), time.time(), time.time(), owner, canonical))
            conn.execute("UPDATE memories SET status='resolved',revision=revision+1 WHERE owner=? AND id LIKE ? AND status='conflict'",
                         (owner, canonical + ":conflict:%"))
            conn.execute("""INSERT INTO memory_events(owner,memory_id,source_session,operation,before_value,after_value,evidence,decision,created_at)
                VALUES(?,?,?,'REPLACE',?,?,'[]','{"reason":"user_correction"}',?)""",
                (owner, canonical, row["source_session"], row["value"], value.strip(), time.time()))
            return self._queue_cleanup(conn, owner, "edit", identifier,
                {"cache_sessions": sessions, "cache_owner": True, "vector_owner": True})

    def request_session_deletion(self, owner, session_id):
        from .storage import ChatError
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE owner=? AND id=?", (owner, session_id)).fetchone()
            if not row:
                previous = self._latest_cleanup(conn, owner, session_id, ("session",))
                if previous:
                    return previous["id"]
                raise ChatError("对话不存在或已删除。", 404)
            conn.execute("DELETE FROM sessions WHERE owner=? AND id=?", (owner, session_id))
            return self._queue_cleanup(conn, owner, "session", session_id,
                {"cache_sessions": [session_id], "cache_owner": False, "vector_owner": False})

    def clear_chat_data(self, owner):
        with self.connect(write=True) as conn:
            previous = self._latest_cleanup(conn, owner, owner, ("chat",))
            exists = conn.execute("""SELECT 1 FROM sessions WHERE owner=? UNION ALL SELECT 1 FROM memories WHERE owner=?
                UNION ALL SELECT 1 FROM memory_suppressions WHERE owner=? UNION ALL SELECT 1 FROM memory_events WHERE owner=?
                UNION ALL SELECT 1 FROM memory_sources WHERE owner=? UNION ALL SELECT 1 FROM memory_usages WHERE owner=? LIMIT 1""", (owner,) * 6).fetchone()
            privacy = conn.execute("SELECT workspace_enabled,resume_enabled FROM chat_privacy WHERE owner=?", (owner,)).fetchone()
            pending = conn.execute("SELECT 1 FROM cleanup_jobs WHERE owner=? AND status!='completed' AND scope!='chat' LIMIT 1", (owner,)).fetchone()
            if previous and not exists and privacy and not any(privacy) and (previous["status"] != "completed" or not pending):
                return previous["id"]
            cutoff, sessions = self._barrier(conn, owner)
            for row in conn.execute("SELECT payload FROM cleanup_jobs WHERE owner=?", (owner,)):
                sessions.extend(json.loads(row["payload"]).get("cache_sessions", []))
            conn.execute("DELETE FROM sessions WHERE owner=?", (owner,))
            for table in ("memories", "memory_events", "memory_sources", "memory_usages", "memory_suppressions", "cleanup_jobs"):
                conn.execute(f"DELETE FROM {table} WHERE owner=?", (owner,))
            return self._queue_cleanup(conn, owner, "chat", owner,
                {"cache_sessions": sorted(set(sessions)), "cache_owner": True, "vector_owner": True})

    def source_settings(self, owner, *, workspace_enabled, resume_enabled):
        with self.connect(write=True) as conn:
            _, sessions = self._barrier(conn, owner, disable_sources=False)
            conn.execute("UPDATE chat_privacy SET workspace_enabled=?,resume_enabled=? WHERE owner=?",
                         (workspace_enabled, resume_enabled, owner))
            return self._queue_cleanup(conn, owner, "sources", owner,
                {"cache_sessions": sessions, "cache_owner": True, "vector_owner": True})

    def cleanup_status(self, owner, identifier=None):
        from .storage import ChatError
        with self.connect() as conn:
            if identifier:
                row = conn.execute("SELECT * FROM cleanup_jobs WHERE owner=? AND id=?", (owner, identifier)).fetchone()
                if not row:
                    raise ChatError("清理任务不存在。", 404)
                return {key: row[key] for key in ("id", "scope", "status", "attempts", "error_code", "created_at", "completed_at")}
            return [self.cleanup_status(owner, row[0]) for row in conn.execute("SELECT id FROM cleanup_jobs WHERE owner=? ORDER BY (status='completed'),created_at DESC LIMIT 20", (owner,))]

    def cleanup_count(self, owner):
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM cleanup_jobs WHERE owner=? AND status!='completed'", (owner,)).fetchone()[0]

    def claim_cleanup(self):
        now, token = time.time(), uuid4().hex
        with self.connect(write=True) as conn:
            row = conn.execute("""SELECT j.* FROM cleanup_jobs j WHERE
                ((j.status IN ('queued','retrying') AND j.due_at<=?) OR (j.status='running' AND j.lease_until<?))
                AND NOT EXISTS(SELECT 1 FROM artifact_leases l WHERE l.owner=j.owner AND l.kind='cleanup' AND l.lease_until>?)
                ORDER BY j.created_at LIMIT 1""", (now, now, now)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE cleanup_jobs SET status='running',token=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                         (token, now + 300, row["id"]))
            epoch = conn.execute("SELECT epoch FROM chat_privacy WHERE owner=?", (row["owner"],)).fetchone()
            conn.execute("INSERT INTO artifact_leases VALUES(?,?,?,?,?)", (token, row["owner"], epoch[0] if epoch else 0, "cleanup", now + 300))
            return {**dict(row), "token": token, "attempts": row["attempts"] + 1, "payload": json.loads(row["payload"])}

    def finish_cleanup(self, job, *, error=None):
        with self.connect(write=True) as conn:
            current = conn.execute("SELECT status,token FROM cleanup_jobs WHERE id=? AND owner=?", (job["id"], job["owner"])).fetchone()
            if not current or current["token"] != job["token"]:
                conn.execute("DELETE FROM artifact_leases WHERE token=?", (job["token"],))
                if not error and not conn.execute("SELECT 1 FROM cleanup_jobs WHERE owner=? AND status!='completed'", (job["owner"],)).fetchone():
                    conn.execute("UPDATE memories SET revision=revision+1,indexed_revision=0 WHERE owner=?", (job["owner"],))
                    self._queue_cleanup(conn, job["owner"], "repair", job["owner"],
                        {"cache_sessions": [], "cache_owner": True, "vector_owner": True})
                return False
            if current["status"] == "completed":
                return False
            if error:
                conn.execute("UPDATE cleanup_jobs SET status='retrying',due_at=?,error_code=? WHERE id=? AND token=?",
                    (time.time() + min(3600, 2 ** min(job["attempts"], 11)), type(error).__name__, job["id"], job["token"]))
            else:
                conn.execute("UPDATE cleanup_jobs SET status='completed',completed_at=?,error_code='' WHERE id=? AND token=?",
                             (time.time(), job["id"], job["token"]))
                if job["scope"] == "chat":
                    conn.execute("UPDATE cleanup_jobs SET payload='{}' WHERE id=? AND token=?", (job["id"], job["token"]))
            conn.execute("DELETE FROM artifact_leases WHERE token=?", (job["token"],))
            conn.execute("DELETE FROM artifact_leases WHERE owner=? AND lease_until<?", (job["owner"], time.time()))
            return not error

    def begin_artifact(self, owner, kind, *, epoch=None):
        with self.connect(write=True) as conn:
            row = conn.execute("SELECT epoch FROM chat_privacy WHERE owner=?", (owner,)).fetchone()
            current = row[0] if row else 0
            pending = conn.execute("SELECT 1 FROM cleanup_jobs WHERE owner=? AND status!='completed' LIMIT 1", (owner,)).fetchone()
            if pending or epoch is not None and epoch != current:
                return None
            token = uuid4().hex
            conn.execute("INSERT INTO artifact_leases VALUES(?,?,?,?,?)", (token, owner, current, kind, time.time() + 300))
            return {"token": token, "owner": owner, "epoch": current}

    def artifact_valid(self, lease):
        with self.connect() as conn:
            row = conn.execute("""SELECT 1 FROM artifact_leases l LEFT JOIN chat_privacy p ON p.owner=l.owner
                WHERE l.token=? AND l.epoch=COALESCE(p.epoch,0) AND l.lease_until>?""", (lease["token"], time.time())).fetchone()
            return bool(row)

    def end_artifact(self, lease):
        with self.connect(write=True) as conn:
            conn.execute("DELETE FROM artifact_leases WHERE token=?", (lease["token"],))

    def cleanup_blocked(self, owner, *, exclude_token=""):
        with self.connect() as conn:
            return bool(conn.execute("SELECT 1 FROM artifact_leases WHERE owner=? AND token!=? AND lease_until>? LIMIT 1", (owner, exclude_token, time.time())).fetchone())

    def cleanup_pending(self, owner):
        with self.connect() as conn:
            return bool(conn.execute("SELECT 1 FROM cleanup_jobs WHERE owner=? AND status!='completed' LIMIT 1", (owner,)).fetchone())

    def checkpoint_cleanup(self):
        with self.connect() as conn:
            if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise RuntimeError("SQLite checkpoint is still busy")

    def repair_artifacts(self, owner):
        with self.connect(write=True) as conn:
            previous = self._latest_cleanup(conn, owner, owner, ("repair",))
            if previous and previous["status"] != "completed":
                return previous["id"]
            conn.execute("UPDATE memories SET revision=revision+1,indexed_revision=0 WHERE owner=?", (owner,))
            return self._queue_cleanup(conn, owner, "repair", owner,
                {"cache_sessions": [], "cache_owner": True, "vector_owner": True})
