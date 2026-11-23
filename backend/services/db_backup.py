"""Automatic WAL-safe rolling SQLite snapshot backups."""
from pathlib import Path
import sqlite3
import time

from . import db
from .paths import APP_DATA_DIR

BACKUP_DIR = Path(APP_DATA_DIR) / "backups"
MAX_BACKUPS = 5
MIN_INTERVAL_SECONDS = 600


def list_backups():
    if not BACKUP_DIR.is_dir():
        return []
    files = sorted(BACKUP_DIR.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "created_at": f.stat().st_mtime,
        }
        for f in files
    ]


def create_rolling_backup(*, force=False, max_keep=MAX_BACKUPS):
    src_path = Path(db.DB_PATH)
    if not src_path.is_file():
        return {"ok": False, "skipped": True, "reason": "db_missing"}
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(BACKUP_DIR.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not force and existing and (time.time() - existing[0].stat().st_mtime) < MIN_INTERVAL_SECONDS:
        return {"ok": True, "skipped": True, "latest": existing[0].name, "count": len(existing)}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_path = BACKUP_DIR / f"app-{stamp}.db"
    tmp_path = BACKUP_DIR / f".app-{stamp}.tmp"
    src_conn = sqlite3.connect(str(src_path), timeout=10)
    dst_conn = sqlite3.connect(str(tmp_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    tmp_path.replace(dest_path)

    all_files = sorted(BACKUP_DIR.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in all_files[max(1, int(max_keep)):]:
        try:
            stale.unlink()
        except OSError:
            pass
    kept = sorted(BACKUP_DIR.glob("app-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "ok": True,
        "skipped": False,
        "latest": dest_path.name,
        "size_kb": round(dest_path.stat().st_size / 1024, 1),
        "count": len(kept),
    }
