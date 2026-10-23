"""按用途读取 AI_<用途>_{API_KEY,BASE_URL,MODEL}，环境变量优先于 .env。"""

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
