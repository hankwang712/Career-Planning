"""In-memory ring buffer capturing clean backend business & request logs for the global terminal drawer."""
from collections import deque
import logging
from threading import Lock
import time

_LOCK = Lock()
_SEQ = 0
_RING = deque(maxlen=300)


def append_log(level, text):
    global _SEQ
    clean = str(text or "").strip()
    if not clean:
        return
    if len(clean) > 2000:
        clean = clean[:2000] + " …(已截断)"
    with _LOCK:
        _SEQ += 1
        _RING.append({
            "seq": _SEQ,
            "time": time.strftime("%H:%M:%S"),
            "level": str(level or "INFO").upper()[:5].strip(),
            "text": clean,
        })


def read_logs(after_seq=0, limit=150):
    with _LOCK:
        items = [entry for entry in _RING if entry["seq"] > after_seq]
        return items[-max(1, min(300, int(limit or 150))):]


def clear_logs():
    with _LOCK:
        _RING.clear()


class _RingLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            append_log(record.levelname, msg)
        except Exception:
            pass


_HANDLER_INSTALLED = False


def install_logging_handler():
    global _HANDLER_INSTALLED
    if _HANDLER_INSTALLED:
        return
    handler = _RingLogHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(name)s · %(message)s"))
    logging.getLogger().addHandler(handler)
    _HANDLER_INSTALLED = True
