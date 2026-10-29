"""项目根目录运行：python -m experiments.run_memory_advisor --start-redis。"""

import argparse
import os
from pathlib import Path
import subprocess

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="启动职业多智能体分层记忆实验（Swagger /docs）")
    parser.add_argument("--start-redis", action="store_true", help="先通过 Docker Compose 启动 Redis")
    parser.add_argument("--redis-image", help="覆盖 Redis 镜像，例如复用已缓存的镜像")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if args.start_redis:
        env = os.environ.copy()
        if args.redis_image:
            env["MEMORY_REDIS_IMAGE"] = args.redis_image
        compose = Path(__file__).resolve().parents[1] / "compose.yml"
        subprocess.run(["docker", "compose", "-f", str(compose), "up", "-d", "--wait", "--wait-timeout", "60", "redis"],
                       env=env, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    uvicorn.run("experiments.memory_app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
