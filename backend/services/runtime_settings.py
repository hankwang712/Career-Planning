"""Local overrides for the models that the web app can reload on demand."""
import sqlite3
from contextlib import closing

from .paths import APP_DATA_DIR


GROUPS = (
    ("chat", "对话模型", "全站共用模型：用于 AI 对话、简历分析与定向改写、岗位评估、打招呼语微调、职业报告和职业访谈。", (
        ("AI_CHAT_BASE_URL", "接口地址"), ("AI_CHAT_API_KEY", "API Key"), ("AI_CHAT_MODEL", "模型名称"),
    )),
    ("cleaner", "招聘清洗模型", "用于岗位语义清洗。提取小红书配图时使用同一模型，请填写支持图文输入的模型。三项留空可沿用对话模型。", (
        ("CLEANER_LLM_BASE_URL", "接口地址"), ("CLEANER_LLM_API_KEY", "API Key"),
        ("CLEANER_LLM_MODEL", "模型名称"),
    )),
    ("embedding", "技能向量模型", "用于技能文本的语义匹配。未设置专用模型时沿用部署配置。", (
        ("AI_EMBEDDING_BASE_URL", "接口地址"), ("AI_EMBEDDING_API_KEY", "API Key"), ("AI_EMBEDDING_MODEL", "模型名称"),
    )),
    ("image", "职业头像", "用于生成职业头像。接口地址留空时使用默认 OpenRouter 地址。", (
        ("TEXT_TO_IMAGE_BASE_URL", "接口地址"), ("TEXT_TO_IMAGE_API_KEY", "API Key"),
    )),
    ("news", "资讯向量", "用于职业资讯的语义检索，使用 OpenRouter 的 BGE-M3。", (
        ("NEWS_EMBEDDING_API_KEY", "OpenRouter API Key"),
    )),
)
KEYS = frozenset(key for _, _, _, fields in GROUPS for key, _ in fields)

DEPLOYMENT_GROUPS = (
    ("ocr", "OCR 与文档识别", "主站文档识别使用本机 OCR。这里显示环境模板中的外部 OCR 字段。", (
        ("AI_OCR_BASE_URL", "接口地址"), ("AI_OCR_API_KEY", "API Key"), ("AI_OCR_MODEL", "模型名称"),
        ("TESSERACT_CMD", "Tesseract 路径"),
    )),
    ("rag-models", "LightRAG 模型", "构建图谱、向量索引和岗位检索所使用的环境配置。", (
        ("LLM_BINDING", "语言模型协议"), ("LLM_BINDING_HOST", "语言模型地址"),
        ("LLM_BINDING_API_KEY", "语言模型密钥"), ("LLM_MODEL", "语言模型名称"),
        ("EMBEDDING_BINDING", "向量协议"), ("EMBEDDING_BINDING_HOST", "向量接口地址"),
        ("EMBEDDING_BINDING_API_KEY", "向量密钥"), ("EMBEDDING_MODEL", "向量模型名称"),
        ("EMBEDDING_DIM", "向量维度"), ("EMBEDDING_TOKEN_LIMIT", "分词上限"),
    )),
    ("rag-storage", "LightRAG 存储", "由图谱运行环境读取。", (
        ("LIGHTRAG_WORKSPACE", "图谱工作区"), ("WORKSPACE", "存储工作区"),
        ("LIGHTRAG_KV_STORAGE", "键值存储"), ("LIGHTRAG_VECTOR_STORAGE", "向量存储"),
        ("LIGHTRAG_GRAPH_STORAGE", "图存储"), ("LIGHTRAG_DOC_STATUS_STORAGE", "文档状态存储"),
        ("SUMMARY_LANGUAGE", "摘要语言"),
    )),
    ("postgres", "PostgreSQL / pgvector", "启用图谱数据库时配置。容器和数据库启动时读取这些值。", (
        ("POSTGRES_HOST", "主机"), ("POSTGRES_PORT", "端口"), ("POSTGRES_USER", "用户名"),
        ("POSTGRES_PASSWORD", "数据库密码"), ("POSTGRES_DATABASE", "数据库名称"),
        ("POSTGRES_VECTOR_INDEX_TYPE", "向量索引类型"),
    )),
    ("retrieval", "岗位检索", "用于控制图谱检索和本地岗位描述语料。", (
        ("JOB_RETRIEVAL_GRAPH_ENABLED", "启用图谱检索"), ("JOB_JD_SOURCE_PATH", "岗位描述文件"),
    )),
)
DEPLOYMENT_KEYS = frozenset(key for _, _, _, fields in DEPLOYMENT_GROUPS for key, _ in fields)


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
