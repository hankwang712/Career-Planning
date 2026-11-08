import os

from ..environment import ENV_FILE


def model_runtime(prefix):
    from dotenv import dotenv_values
    values = {**dotenv_values(ENV_FILE, encoding="utf-8-sig"), **os.environ}
    return tuple(str(values.get(prefix + key) or "").strip() for key in ("BASE_URL", "API_KEY", "MODEL"))


def fallback_chat_runtime():
    return model_runtime("AI_CHAT_")


def embedding_runtime():
    return model_runtime("AI_EMBEDDING_")
