import asyncio
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx

from .config import JobRAGConfig

RESEARCH_DIR = Path(__file__).resolve().parents[2] / "artifacts/research"
_start_lock = asyncio.Lock()


class LightRAGStartupError(RuntimeError):
    """可展示给调用方的启动错误，不包含环境文件或密钥。"""


def _start_local(settings: JobRAGConfig, port: int) -> None:
    """Docker Desktop 由用户打开；代码确保数据库容器和 LightRAG 服务运行。"""
    print("[岗位图谱] 正在启动数据库容器和 LightRAG…", file=sys.stderr, flush=True)
    commands = [
        ["docker.exe" if os.name == "nt" else "docker", "compose", "--env-file", str(RESEARCH_DIR / ".env"),
         "-f", str(RESEARCH_DIR / "compose.postgres.yml"), "up", "-d", "--wait", "--wait-timeout", "60", "postgres"],
        [sys.executable, "-X", "utf8", str(RESEARCH_DIR / "job_graph.py"), "serve", "--background",
         "--workspace", settings.workspace, "--env-file", str(RESEARCH_DIR / ".env"), "--webui-port", str(port)],
    ]
    for index, command in enumerate(commands):
        message = (
            "数据库启动失败，请先打开 Docker Desktop，并确认 research/.env 和 compose.postgres.yml 配置正确"
            if index == 0 else
            "LightRAG 启动失败，请使用 yolov11 环境，并查看 artifacts/research/.job_graph/logs/webui.log"
        )
        try:
            result = subprocess.run(
                command, cwd=RESEARCH_DIR, capture_output=True, timeout=90 if index == 0 else 45,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LightRAGStartupError(message) from error
        if result.returncode:
            raise LightRAGStartupError(message)


async def ensure_lightrag(client: httpx.AsyncClient, settings: JobRAGConfig) -> None:
    """实际检索时才启动；已运行则直接复用，不需要打开网页。"""
    async def ready() -> bool:
        try:
            response = await client.get("health", timeout=3)
        except httpx.ConnectError:
            return False
        response.raise_for_status()
        health = response.json()
        if health.get("configuration", {}).get("workspace") != settings.workspace:
            raise LightRAGStartupError("LightRAG 知识库与 LIGHTRAG_WORKSPACE 不匹配，未启动或停止其他服务")
        return health.get("status") in {"healthy", "ok"}

    if await ready():
        return
    async with _start_lock:
        if await ready():
            return
        parsed = urlsplit(settings.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"}:
            raise LightRAGStartupError("该 LightRAG 地址无法自动在本地启动，请确认目标服务已运行")
        await asyncio.to_thread(_start_local, settings, parsed.port or 80)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if await ready():
                print("[岗位图谱] LightRAG 已就绪", file=sys.stderr, flush=True)
                return
            await asyncio.sleep(.5)
        raise LightRAGStartupError("LightRAG 健康检查超时，请查看 artifacts/research/.job_graph/logs/webui.log")
