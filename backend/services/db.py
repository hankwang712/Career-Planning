import json
import logging
import os
import sqlite3
import threading
import time

from werkzeug.security import check_password_hash

from .paths import APP_DATA_DIR
DB_PATH = os.path.join(APP_DATA_DIR, "app.db")

logger = logging.getLogger(__name__)

_local = threading.local()


def _get_conn():
    """Return a thread-local sqlite3 connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def init_db():
    """Create tables and run one-time JSON migration if needed."""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            display_name TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_state_sections (
            username TEXT NOT NULL,
            section TEXT NOT NULL,
            payload TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (username, section)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            username TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS background_jobs_kind ON background_jobs(kind, status, updated_at)")

    existing_columns = {row[1] for row in cur.execute("PRAGMA table_info(users)")}
    for column, definition in {
        "disabled": "INTEGER NOT NULL DEFAULT 0",
        "created_at": "REAL NOT NULL DEFAULT 0",
        "last_login_at": "REAL",
    }.items():
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS auth_settings (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(username);
        CREATE TABLE IF NOT EXISTS auth_challenges (
            id TEXT PRIMARY KEY,
            owner_hash TEXT NOT NULL,
            purpose TEXT NOT NULL,
            answer_hash TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS auth_challenges_owner ON auth_challenges(owner_hash, purpose);
        CREATE TABLE IF NOT EXISTS auth_rate_limits (
            bucket TEXT PRIMARY KEY,
            started_at REAL NOT NULL,
            attempts INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resume_drafts (
            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            title TEXT NOT NULL,
            document TEXT NOT NULL,
            updated_at REAL NOT NULL,
            revision INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS resume_drafts_owner ON resume_drafts(owner, updated_at DESC);
    """)
    from .career import init_schema
    from .recruitment import init_schema as init_recruitment_schema
    from .resume.rewrite import init_schema as init_resume_rewrite_schema
    init_schema(conn)
    init_recruitment_schema(conn)
    init_resume_rewrite_schema(conn)
    _split_legacy_user_states(conn)
    _scrub_legacy_llm_secrets(conn)
    migrated = cur.execute("SELECT 1 FROM auth_settings WHERE name = 'legacy_json_imported'").fetchone()
    conn.commit()
    conn.close()

    if not migrated:
        _migrate_from_json()
        with _get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO auth_settings VALUES ('legacy_json_imported', '1')")

    # Retire the community and built-in demo accounts after any legacy import.
    with _get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS community_forum")
    for username in ("23030134", "24110403", "24030115", "24151007"):
        user = find_user(username)
        if user and check_password_hash(user["password_hash"], "123456"):
            delete_user(username)
    delete_user("system")


def _migrate_from_json():
    """One-shot migration from legacy JSON files into SQLite."""
    import glob

    # users.json
    users_file = os.path.join(APP_DATA_DIR, "users.json")
    if os.path.exists(users_file):
        try:
            with open(users_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                for u in data:
                    if not isinstance(u, dict):
                        continue
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO users (username, password_hash, role, display_name)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            str(u.get("username") or "").strip(),
                            str(u.get("password_hash") or "").strip(),
                            str(u.get("role") or "user").strip() or "user",
                            str(u.get("display_name") or u.get("username") or "").strip(),
                        ),
                    )
                conn.commit()
                conn.close()
        except Exception:
            pass

    # user_state/*.json
    user_state_dir = os.path.join(APP_DATA_DIR, "user_state")
    if os.path.isdir(user_state_dir):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for path in glob.glob(os.path.join(user_state_dir, "*.json")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                username = os.path.splitext(os.path.basename(path))[0]
                if isinstance(payload, dict):
                    for section, value in payload.items():
                        cur.execute(
                            """
                            INSERT OR IGNORE INTO user_state_sections (username, section, payload, version, updated_at)
                            VALUES (?, ?, ?, 1, ?)
                            """,
                            (username, str(section), _dump(value), time.time()),
                        )
            except Exception:
                pass
        conn.commit()
        conn.close()

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def load_users():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, password_hash, role, display_name FROM users ORDER BY role != 'super_admin', username"
    )
    rows = cur.fetchall()
    return [dict(row) for row in rows]


def find_user(username):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT username, password_hash, role, display_name FROM users WHERE username = ?",
        (str(username or "").strip(),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def delete_user(username):
    with _get_conn() as conn:
        conn.execute("DELETE FROM user_state_sections WHERE username = ?", (username,))
        conn.execute("DELETE FROM background_jobs WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


# ---------------------------------------------------------------------------
# User state
# ---------------------------------------------------------------------------

def _dump(value):
    """Stable serialisation so "did this section change" is a plain string comparison."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:  # mixed-type keys cannot be sorted
        return json.dumps(value, ensure_ascii=False, default=str)


class TrackedState(dict):
    """A user's state as loaded, remembering each section so a save writes only what this caller changed.

    Callers read the whole state, change one scope and save it back. Storing one row per scope means a save
    touches only the scopes that actually changed, and a concurrent request that changed another scope in
    the meantime is no longer overwritten by this caller's stale copy.
    """

    loaded = None


def load_user_state(username):
    name = str(username or "").strip()
    rows = _get_conn().execute(
        "SELECT section, payload FROM user_state_sections WHERE username = ?", (name,)
    ).fetchall()
    state, snapshot = TrackedState(), {}
    for row in rows:
        try:
            state[row["section"]] = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        snapshot[row["section"]] = row["payload"]
    state.loaded = snapshot
    return state


def save_user_state(username, payload):
    name = str(username or "").strip()
    new = payload if isinstance(payload, dict) else {}
    serialized = {str(section): _dump(value) for section, value in new.items()}
    baseline = payload.loaded if isinstance(payload, TrackedState) else None
    conn = _get_conn()
    now = time.time()
    with conn:
        if baseline is None:
            # A freshly built dict replaces the user's state, as before.
            baseline = {row["section"]: row["payload"] for row in conn.execute(
                "SELECT section, payload FROM user_state_sections WHERE username = ?", (name,))}
        changed = {section: text for section, text in serialized.items() if baseline.get(section) != text}
        removed = [section for section in baseline if section not in serialized]
        for section, text in changed.items():
            conn.execute(
                """
                INSERT INTO user_state_sections (username, section, payload, version, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(username, section) DO UPDATE SET
                    payload = excluded.payload, version = version + 1, updated_at = excluded.updated_at
                """,
                (name, section, text, now),
            )
        for section in removed:
            conn.execute("DELETE FROM user_state_sections WHERE username = ? AND section = ?", (name, section))
    if isinstance(payload, TrackedState):
        known = {**payload.loaded, **changed}
        for section in removed:
            known.pop(section, None)
        payload.loaded = known


def _split_legacy_user_states(conn):
    """Move the old one-row-per-user JSON blob into per-scope rows, keeping the old table as a backup."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_states'").fetchone():
        return
    for row in conn.execute("SELECT username, payload, updated_at FROM user_states").fetchall():
        try:
            data = json.loads(row[1])
        except (TypeError, json.JSONDecodeError):
            logger.warning("用户数据无法解析，保留在 user_states_legacy 中：%s", row[0])
            continue
        if not isinstance(data, dict):
            continue
        for section, value in data.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO user_state_sections (username, section, payload, version, updated_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (row[0], str(section), _dump(value), row[2] or time.time()),
            )
    conn.execute("ALTER TABLE user_states RENAME TO user_states_legacy")


def _scrub_legacy_llm_secrets(conn):
    """Credentials now live only in .env. Remove the old plaintext copies once .env can replace them."""
    legacy = [name for name in ("llm_configs", "llm_providers", "resume_llm_config")
              if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()]
    if not legacy:
        return
    from . import llm_env
    if not llm_env.chat_configured():
        logger.warning("数据库里还留有旧的 API 配置，但 .env 尚未配置 AI_CHAT_BASE_URL / AI_CHAT_API_KEY / AI_CHAT_MODEL；"
                       "请先补全 .env 并重启，旧的明文密钥会在那时自动清除。")
        return
    conn.execute("PRAGMA secure_delete = ON")
    for name in legacy:
        conn.execute(f"DROP TABLE {name}")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    logger.warning("已清除数据库中旧的 API 配置（%s）。", "、".join(legacy))


# ---------------------------------------------------------------------------
# Background jobs (long-running report / resume tasks)
# ---------------------------------------------------------------------------

def save_job(job_id, kind, username, status, payload):
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO background_jobs (job_id, kind, username, status, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status, payload = excluded.payload, updated_at = excluded.updated_at
            """,
            (job_id, kind, username, status, json.dumps(payload, ensure_ascii=False, default=str), time.time()),
        )


def delete_job(job_id):
    with _get_conn() as conn:
        conn.execute("DELETE FROM background_jobs WHERE job_id = ?", (job_id,))


def load_jobs(kind, since):
    rows = _get_conn().execute(
        "SELECT payload FROM background_jobs WHERE kind = ? AND updated_at >= ? ORDER BY updated_at",
        (kind, since),
    ).fetchall()
    jobs = []
    for row in rows:
        try:
            job = json.loads(row["payload"])
        except json.JSONDecodeError:
            continue
        if isinstance(job, dict) and job.get("job_id"):
            jobs.append(job)
    return jobs


def prune_jobs(before):
    with _get_conn() as conn:
        conn.execute("DELETE FROM background_jobs WHERE updated_at < ? AND status NOT IN ('queued', 'running')", (before,))
