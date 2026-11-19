"""Resolve runtime model settings, including local administrator overrides."""
import os

from .environment import ENV_FILE
from . import runtime_settings


def _values():
    from dotenv import dotenv_values
    return {**dotenv_values(ENV_FILE, encoding="utf-8-sig"), **os.environ, **runtime_settings.read()}


def runtime(prefix):
    """(base_url, api_key, model) for variables such as AI_CHAT_BASE_URL / AI_CHAT_API_KEY / AI_CHAT_MODEL."""
    values = _values()
    return tuple(str(values.get(prefix + key) or "").strip() for key in ("BASE_URL", "API_KEY", "MODEL"))


def chat_runtime():
    """Text model used by chat, reports, resume analysis and the interview."""
    base_url, api_key, model = runtime("AI_CHAT_")
    if base_url and api_key and not model:
        model = "deepseek-chat" if "deepseek" in base_url.lower() else "gpt-4o-mini"
    return base_url, api_key, model


def chat_configured():
    return all(chat_runtime())


def recruitment_cleaner_runtime():
    cleaner = runtime("CLEANER_LLM_")
    return cleaner if all(cleaner) else chat_runtime()


def status():
    """Safe to show to any signed-in user: no credentials, not even the endpoint."""
    base_url, api_key, model = chat_runtime()
    return {"configured": bool(base_url and api_key and model), "model": model}


def image_runtime(default_base_url, default_model):
    """OpenRouter image model shared by the portrait and text-to-image features."""
    values = _values()
    base_url = str(values.get("TEXT_TO_IMAGE_BASE_URL") or "").strip() or default_base_url
    return base_url, str(values.get("TEXT_TO_IMAGE_API_KEY") or "").strip(), default_model
