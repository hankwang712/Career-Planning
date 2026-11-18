"""Local overrides for the models that the web app can reload on demand."""
import sqlite3
from contextlib import closing

from .paths import APP_DATA_DIR


GROUPS = (
    ("chat", "对话模型", "用于 AI 对话、简历分析、职业报告和职业访谈。", (
        ("AI_CHAT_BASE_URL", "接口地址"), ("AI_CHAT_API_KEY", "API Key"), ("AI_CHAT_MODEL", "模型名称"),
    )),
    ("embedding", "技能向量模型", "用于技能文本的语义匹配。未设置专用模型时沿用部署配置。", (
        ("AI_EMBEDDING_BASE_URL", "接口地址"), ("AI_EMBEDDING_API_KEY", "API Key"), ("AI_EMBEDDING_MODEL", "模型名称"),
    )),
    ("image", "职业头像", "用于生成职业头像。接口地址留空时使用默认 OpenRouter 地址。", (
        ("TEXT_TO_IMAGE_BASE_URL", "接口地址"), ("TEXT_TO_IMAGE_API_KEY", "API Key"),
    )),
)
KEYS = frozenset(key for _, _, _, fields in GROUPS for key, _ in fields)


def read():
    path = APP_DATA_DIR / "model-settings.sqlite3"
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'model_settings'").fetchone():
            return {}
        return {key: value for key, value in conn.execute("SELECT name, value FROM model_settings") if key in KEYS}


def save(changes):
    path = APP_DATA_DIR / "model-settings.sqlite3"
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS model_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        for key, value in changes.items():
            if value:
                conn.execute("INSERT OR REPLACE INTO model_settings VALUES (?, ?)", (key, value))
            else:
                conn.execute("DELETE FROM model_settings WHERE name = ?", (key,))
