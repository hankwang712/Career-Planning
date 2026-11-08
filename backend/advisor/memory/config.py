import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from ..config import ENV_FILE


@dataclass(frozen=True)
class MemoryConfig:
    redis_url: str = "redis://127.0.0.1:6380/0"
    data_dir: Path = Path(__file__).resolve().parents[3] / "data" / "app_data" / "advisor-memory"
    recent_turns: int = 6
    session_ttl: int = 604800
    half_life_days: float = 90
    recall_limit: int = 8

    def __post_init__(self):
        if not 1 <= self.recent_turns <= 30 or self.session_ttl < 60:
            raise ValueError("近期轮数应为 1~30，缓存 TTL 至少 60 秒")
        if self.half_life_days <= 0 or not 1 <= self.recall_limit <= 30:
            raise ValueError("记忆半衰期必须为正，召回数量应为 1~30")


def get_memory_config() -> MemoryConfig:
    values = {**dotenv_values(ENV_FILE, encoding="utf-8-sig"), **os.environ}
    defaults = MemoryConfig()
    return MemoryConfig(
        redis_url=values.get("MEMORY_REDIS_URL") or defaults.redis_url,
        data_dir=Path(values.get("MEMORY_DATA_DIR") or defaults.data_dir).resolve(),
        recent_turns=int(values.get("MEMORY_RECENT_TURNS") or defaults.recent_turns),
        session_ttl=int(values.get("MEMORY_SESSION_TTL") or defaults.session_ttl),
        half_life_days=float(values.get("MEMORY_HALF_LIFE_DAYS") or defaults.half_life_days),
        recall_limit=int(values.get("MEMORY_RECALL_LIMIT") or defaults.recall_limit),
    )
