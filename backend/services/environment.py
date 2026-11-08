"""Shared root environment for the application, collectors and Agent tools."""
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_environment():
    """Keep explicit process variables ahead of local configuration."""
    load_dotenv(ENV_FILE, override=False, encoding="utf-8-sig")
