#!/usr/bin/env python3
import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

from flask import render_template

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import server  # noqa: E402


WATCH_EXTENSIONS = {".html", ".css", ".js", ".json"}


def export_once() -> None:
    base_dir = Path(server.BASE_DIR)
    out_dir = base_dir / "deploy" / "static-site"
    static_src = Path(server.STATIC_DIR)
    main_html_src = base_dir / "frontend" / "main.html"

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 渲染当前模板为静态 index.html
    with server.app.app_context():
        with server.app.test_request_context("/"):
            html = render_template("base.html")
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # The assistant has its own document, while authenticated chat APIs stay on Flask.
    with server.app.test_request_context("/assistant.html"):
        assistant_html = render_template("assistant.html")
    (out_dir / "assistant.html").write_text(assistant_html, encoding="utf-8")

    # 2) 复制 static 目录
    if static_src.exists():
        shutil.copytree(static_src, out_dir / "static")
    shutil.copytree(server.PUBLIC_DATA_DIR, out_dir / "static", dirs_exist_ok=True)

    # 3) 兼容保留 main.html（可选）
    if main_html_src.exists():
        shutil.copy2(main_html_src, out_dir / "main.html")

    print(f"[ok] static site exported to: {out_dir}")
    print("[tip] place this folder behind Nginx root.")


def _iter_watch_files(base_dir: Path):
    roots = [
        base_dir / "frontend" / "templates",
        base_dir / "frontend" / "static",
        base_dir / "data" / "public",
        base_dir / "frontend" / "main.html",
        base_dir / "backend" / "server.py",
    ]
    for root in roots:
        if root.is_file():
            yield root
            continue
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in WATCH_EXTENSIONS:
                    yield p


def _snapshot(base_dir: Path) -> str:
    hasher = hashlib.sha256()
    for p in sorted(_iter_watch_files(base_dir)):
        try:
            stat = p.stat()
        except OSError:
            continue
        rel = p.relative_to(base_dir).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("utf-8"))
    return hasher.hexdigest()


def watch_mode(interval: float = 1.0) -> None:
    base_dir = Path(server.BASE_DIR)
    print("[watch] start watching frontend, public data and backend/server.py ...")
    export_once()
    last_sig = _snapshot(base_dir)
    while True:
        time.sleep(interval)
        curr_sig = _snapshot(base_dir)
        if curr_sig != last_sig:
            print("[watch] change detected, re-exporting ...")
            export_once()
            last_sig = curr_sig


def main():
    parser = argparse.ArgumentParser(description="导出静态站点")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="监听前端文件改动并自动重新导出",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="watch 模式轮询间隔（秒），默认 1.0",
    )
    args = parser.parse_args()

    if args.watch:
        watch_mode(interval=max(0.2, args.interval))
    else:
        export_once()


if __name__ == "__main__":
    main()

