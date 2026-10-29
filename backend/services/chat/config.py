"""Read existing model settings without importing or modifying experimental code."""

import os

from ..paths import PROJECT_ROOT


def fallback_chat_runtime():
    from dotenv import dotenv_values
    values = {**dotenv_values(PROJECT_ROOT / "experiments" / ".env", encoding="utf-8-sig"), **os.environ}
    return tuple(str(values.get("AI_CHAT_" + key) or "").strip() for key in ("BASE_URL", "API_KEY", "MODEL"))
