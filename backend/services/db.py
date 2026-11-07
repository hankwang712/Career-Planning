import json
import os
import sqlite3
import threading
import time

from .paths import APP_DATA_DIR
DB_PATH = os.path.join(APP_DATA_DIR, "app.db")

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
        CREATE TABLE IF NOT EXISTS user_states (
            username TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at REAL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_configs (
            scope TEXT PRIMARY KEY,
            base_url TEXT,
            api_key TEXT,
            model TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_providers (
            id TEXT PRIMARY KEY,
            name TEXT,
            base_url TEXT,
            api_key TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS resume_llm_config (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            base_url TEXT,
            api_key TEXT,
            model TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS community_forum (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            payload TEXT NOT NULL
        )
        """
    )

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
    """)
    from .career import init_schema
    init_schema(conn)
    migrated = cur.execute("SELECT 1 FROM auth_settings WHERE name = 'legacy_json_imported'").fetchone()
    conn.commit()
    conn.close()

    if not migrated:
        _migrate_from_json()
        with _get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO auth_settings VALUES ('legacy_json_imported', '1')")


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
                cur.execute(
                    """
                    INSERT OR IGNORE INTO user_states (username, payload, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (username, json.dumps(payload, ensure_ascii=False), time.time()),
                )
            except Exception:
                pass
        conn.commit()
        conn.close()

    # llm_configs.json
    llm_file = os.path.join(APP_DATA_DIR, "llm_configs.json")
    if os.path.exists(llm_file):
        try:
            with open(llm_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                for scope in ("career_interview", "assessment_hub"):
                    cfg = data.get(scope) or {}
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO llm_configs (scope, base_url, api_key, model)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            scope,
                            str(cfg.get("base_url") or cfg.get("baseUrl") or "").strip(),
                            str(cfg.get("api_key") or cfg.get("apiKey") or "").strip(),
                            str(cfg.get("model") or "gpt-4o-mini").strip(),
                        ),
                    )
                conn.commit()
                conn.close()
        except Exception:
            pass

    # llm_providers.json
    providers_file = os.path.join(APP_DATA_DIR, "llm_providers.json")
    if os.path.exists(providers_file):
        try:
            with open(providers_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            providers = data.get("providers") if isinstance(data, dict) else []
            if isinstance(providers, list):
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                for p in providers:
                    if not isinstance(p, dict):
                        continue
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO llm_providers (id, name, base_url, api_key)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            str(p.get("id") or "").strip(),
                            str(p.get("name") or "未命名").strip(),
                            str(p.get("base_url") or p.get("baseUrl") or "").strip(),
                            str(p.get("api_key") or p.get("apiKey") or "").strip(),
                        ),
                    )
                conn.commit()
                conn.close()
        except Exception:
            pass

    # resume_llm_config.json
    resume_file = os.path.join(APP_DATA_DIR, "resume_llm_config.json")
    if os.path.exists(resume_file):
        try:
            with open(resume_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO resume_llm_config (id, base_url, api_key, model)
                VALUES (1, ?, ?, ?)
                """,
                (
                    str(data.get("base_url") or data.get("baseUrl") or "").strip(),
                    str(data.get("api_key") or data.get("apiKey") or "").strip(),
                    str(data.get("model") or "gpt-4o-mini").strip(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # community_forum.json
    forum_file = os.path.join(APP_DATA_DIR, "community_forum.json")
    if os.path.exists(forum_file):
        try:
            with open(forum_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO community_forum (id, payload)
                VALUES (1, ?)
                """,
                (json.dumps(data, ensure_ascii=False),),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


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
        conn.execute("DELETE FROM user_states WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


# ---------------------------------------------------------------------------
# User state
# ---------------------------------------------------------------------------

def load_user_state(username):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT payload FROM user_states WHERE username = ?",
        (str(username or "").strip(),),
    )
    row = cur.fetchone()
    if row:
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return {}
    return {}


def save_user_state(username, payload):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO user_states (username, payload, updated_at)
        VALUES (?, ?, ?)
        """,
        (
            str(username or "").strip(),
            json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False),
            time.time(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# LLM configs
# ---------------------------------------------------------------------------

def load_llm_configs():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT scope, base_url, api_key, model FROM llm_configs")
    rows = cur.fetchall()
    return {row["scope"]: dict(row) for row in rows}


def save_llm_configs(configs):
    conn = _get_conn()
    cur = conn.cursor()
    for scope, cfg in (configs or {}).items():
        if not isinstance(cfg, dict):
            continue
        cur.execute(
            """
            INSERT OR REPLACE INTO llm_configs (scope, base_url, api_key, model)
            VALUES (?, ?, ?, ?)
            """,
            (
                scope,
                str(cfg.get("base_url") or "").strip(),
                str(cfg.get("api_key") or "").strip(),
                str(cfg.get("model") or "").strip(),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------

def load_providers():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, base_url, api_key FROM llm_providers")
    rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "base_url": r["base_url"],
            "api_key": r["api_key"],
        }
        for r in rows
    ]


def save_providers(providers):
    conn = _get_conn()
    cur = conn.cursor()
    for p in providers:
        if not isinstance(p, dict):
            continue
        cur.execute(
            """
            INSERT OR REPLACE INTO llm_providers (id, name, base_url, api_key)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(p.get("id") or "").strip(),
                str(p.get("name") or "未命名").strip(),
                str(p.get("base_url") or "").strip(),
                str(p.get("api_key") or "").strip(),
            ),
        )
    ids = [p["id"] for p in providers if isinstance(p, dict) and p.get("id")]
    if ids:
        placeholders = ",".join("?" * len(ids))
        cur.execute(
            f"DELETE FROM llm_providers WHERE id NOT IN ({placeholders})",
            ids,
        )
    else:
        cur.execute("DELETE FROM llm_providers")
    conn.commit()


# ---------------------------------------------------------------------------
# Resume LLM config
# ---------------------------------------------------------------------------

def load_resume_llm_config():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT base_url, api_key, model FROM resume_llm_config WHERE id = 1")
    row = cur.fetchone()
    if row:
        return dict(row)
    return {}


def save_resume_llm_config(config):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO resume_llm_config (id, base_url, api_key, model)
        VALUES (1, ?, ?, ?)
        """,
        (
            str(config.get("base_url") or "").strip(),
            str(config.get("api_key") or "").strip(),
            str(config.get("model") or "").strip(),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Community forum
# ---------------------------------------------------------------------------

def load_community_forum():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT payload FROM community_forum WHERE id = 1")
    row = cur.fetchone()
    if row:
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return {}
    return None


def save_community_forum(payload):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO community_forum (id, payload)
        VALUES (1, ?)
        """,
        (json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False),),
    )
    conn.commit()
