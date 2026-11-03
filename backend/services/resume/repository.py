from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time


class ResumeRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""CREATE TABLE IF NOT EXISTS resume_documents (
                owner TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL,
                PRIMARY KEY(owner, fingerprint))""")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(resume_documents)")}
            for name, definition in {
                "facts": "TEXT NOT NULL DEFAULT '[]'",
                "profile_status": "TEXT NOT NULL DEFAULT 'pending'",
                "profile_error": "TEXT NOT NULL DEFAULT ''",
                "document_id": "TEXT NOT NULL DEFAULT ''",
                "file_name": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE resume_documents ADD COLUMN {name} {definition}")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, owner, fingerprint):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM resume_documents WHERE owner=? AND fingerprint=?", (owner, fingerprint)).fetchone()
            return dict(row) if row else None

    def save(self, owner, fingerprint, *, status, content="", metadata=None, error="", source=None):
        source = source or {}
        with self.connect() as conn:
            conn.execute("""INSERT INTO resume_documents(owner,fingerprint,status,content,metadata,error,updated_at,document_id,file_name)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,fingerprint) DO UPDATE SET status=excluded.status,
                content=excluded.content,metadata=excluded.metadata,error=excluded.error,updated_at=excluded.updated_at,
                document_id=excluded.document_id,file_name=excluded.file_name""",
                (owner, fingerprint, status, content, json.dumps(metadata or {}, ensure_ascii=False), error, time.time(),
                 source.get("document_id", ""), Path(source.get("name") or source.get("path") or "").name))

    def save_profile(self, owner, fingerprint, *, facts=None, status="ready", error=""):
        with self.connect() as conn:
            # Never INSERT here: an in-flight extraction must not recreate a deleted document.
            conn.execute("""UPDATE resume_documents SET facts=?,profile_status=?,profile_error=?,updated_at=?
                WHERE owner=? AND fingerprint=?""",
                (json.dumps(facts or [], ensure_ascii=False), status, error, time.time(), owner, fingerprint))

    def delete_owner(self, owner):
        with self.connect() as conn:
            conn.execute("DELETE FROM resume_documents WHERE owner=?", (owner,))
