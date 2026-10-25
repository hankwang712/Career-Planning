import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True)
class AIConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str


@dataclass(frozen=True)
class JobRAGConfig:
    base_url: str = "http://127.0.0.1:9621"
    workspace: str = "career_jd"
    api_key: str = field(default="", repr=False)
    timeout: float = 180


def get_job_rag_config() -> JobRAGConfig:
    """Agent 只连接 LightRAG 服务；数据库和 embedding 配置仍由研究目录管理。"""
    values = dotenv_values(ENV_FILE, encoding="utf-8-sig")
    defaults = JobRAGConfig()

    def read(name: str, default: str) -> str:
        value = os.environ.get(name, values.get(name))
        return (default if value is None else value).strip()

    return JobRAGConfig(
        base_url=read("LIGHTRAG_BASE_URL", defaults.base_url).rstrip("/"),
        workspace=read("LIGHTRAG_WORKSPACE", defaults.workspace),
        api_key=read("LIGHTRAG_API_KEY", defaults.api_key),
        timeout=float(read("LIGHTRAG_TIMEOUT", str(defaults.timeout))),
    )


def get_ai_config(capability: str, *, default_base_url: str = "", default_model: str = "") -> AIConfig:
    """例如 chat、embedding、ocr；新增用途可直接复用此入口。"""
    capability = capability.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", capability):
        raise ValueError("AI 用途只能包含英文字母、数字和下划线，且必须以字母开头")
    values = dotenv_values(ENV_FILE, encoding="utf-8-sig")
    prefix = f"AI_{capability}_"

    def read(suffix: str, default: str = "") -> str:
        name = prefix + suffix
        value = os.environ[name] if name in os.environ else values.get(name)
        return (value if value is not None else default).strip()

    settings = {
        "API_KEY": read("API_KEY"),
        "BASE_URL": read("BASE_URL", default_base_url).rstrip("/"),
        "MODEL": read("MODEL", default_model),
    }
    missing = [prefix + name for name, value in settings.items() if not value]
    if missing:
        raise ValueError("请在 experiments/.env 配置：" + ", ".join(missing))
    return AIConfig(api_key=settings["API_KEY"], base_url=settings["BASE_URL"], model=settings["MODEL"])
