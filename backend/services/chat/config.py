import os

from ..paths import PROJECT_ROOT


def model_runtime(prefix):
    from dotenv import dotenv_values
    values = {**dotenv_values(PROJECT_ROOT / "experiments" / ".env", encoding="utf-8-sig"), **os.environ}
    return tuple(str(values.get(prefix + key) or "").strip() for key in ("BASE_URL", "API_KEY", "MODEL"))


def fallback_chat_runtime():
    return model_runtime("AI_CHAT_")


def embedding_runtime():
    return model_runtime("AI_EMBEDDING_")
