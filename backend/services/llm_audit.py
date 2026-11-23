"""SQLite-backed LLM token usage & latency audit ledger."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

from . import db

_CURRENT_FEATURE = ContextVar("llm_audit_feature", default="general")
_TABLE_READY = False


def _ensure_table(conn):
    global _TABLE_READY
    if _TABLE_READY:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL DEFAULT '',
            feature TEXT NOT NULL DEFAULT 'general',
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            latency_ms REAL NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL DEFAULT 1,
            error_type TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage_logs(created_at)")
    _TABLE_READY = True


@contextmanager
def track_feature(feature_name):
    token = _CURRENT_FEATURE.set(str(feature_name or "general")[:48])
    try:
        yield
    finally:
        _CURRENT_FEATURE.reset(token)


def record_usage(model, *, prompt_tokens=0, completion_tokens=0, total_tokens=0,
                 latency_ms=0.0, ok=True, error_type="", feature=None):
    feat = str(feature or _CURRENT_FEATURE.get() or "general")[:48]
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(completion_tokens or 0))
    t_tok = max(p_tok + c_tok, int(total_tokens or 0))
    try:
        conn = db._get_conn()
        _ensure_table(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO llm_usage_logs
                    (model, feature, prompt_tokens, completion_tokens, total_tokens, latency_ms, ok, error_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(model or "")[:120], feat, p_tok, c_tok, t_tok, round(float(latency_ms or 0.0), 1),
                 1 if ok else 0, str(error_type or "")[:80], time.time()),
            )
    except Exception:
        # Never block main user request if audit write fails
        pass


def usage_summary(days=7):
    conn = db._get_conn()
    _ensure_table(conn)
    now = time.time()
    day_start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    window_start = now - max(1, int(days)) * 86400

    today_row = conn.execute(
        """
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
               COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
               COALESCE(SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END), 0) AS ok_calls
        FROM llm_usage_logs
        WHERE created_at >= ?
        """,
        (day_start,),
    ).fetchone()

    week_row = conn.execute(
        """
        SELECT COUNT(*) AS calls,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
        FROM llm_usage_logs
        WHERE created_at >= ?
        """,
        (window_start,),
    ).fetchone()

    by_feature = [
        {
            "feature": row["feature"],
            "calls": int(row["calls"]),
            "total_tokens": int(row["total_tokens"]),
            "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
        }
        for row in conn.execute(
            """
            SELECT feature, COUNT(*) AS calls,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM llm_usage_logs
            WHERE created_at >= ?
            GROUP BY feature
            ORDER BY total_tokens DESC, calls DESC
            LIMIT 8
            """,
            (window_start,),
        ).fetchall()
    ]

    recent = [
        {
            "model": row["model"],
            "feature": row["feature"],
            "total_tokens": int(row["total_tokens"]),
            "latency_ms": round(float(row["latency_ms"] or 0), 1),
            "ok": bool(row["ok"]),
            "created_at": row["created_at"],
        }
        for row in conn.execute(
            """
            SELECT model, feature, total_tokens, latency_ms, ok, created_at
            FROM llm_usage_logs
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()
    ]

    today_calls = int(today_row["calls"] or 0)
    ok_calls = int(today_row["ok_calls"] or 0)
    return {
        "today": {
            "calls": today_calls,
            "prompt_tokens": int(today_row["prompt_tokens"] or 0),
            "completion_tokens": int(today_row["completion_tokens"] or 0),
            "total_tokens": int(today_row["total_tokens"] or 0),
            "avg_latency_ms": round(float(today_row["avg_latency_ms"] or 0), 1),
            "success_rate": round((ok_calls / today_calls) * 100, 1) if today_calls else 100.0,
        },
        "window_days": int(days),
        "window": {
            "calls": int(week_row["calls"] or 0),
            "total_tokens": int(week_row["total_tokens"] or 0),
            "avg_latency_ms": round(float(week_row["avg_latency_ms"] or 0), 1),
        },
        "by_feature": by_feature,
        "recent": recent,
    }
