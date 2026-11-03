import hashlib
import json
import os
import threading
import time


class LegacyCachePending(Exception):
    """An unidentifiable legacy entry must expire before deletion can be certified."""


class RecentCache:
    def __init__(self, *, url=None, ttl=604800, client=None):
        self.url = url or os.getenv("CHAT_REDIS_URL", "redis://127.0.0.1:6380/0")
        self.ttl = ttl
        self.client = client
        self.retry_at = 0
        self.lock = threading.Lock()

    @staticmethod
    def legacy_key(owner, session_id):
        identity = json.dumps([owner, session_id]).encode()
        return "career:chat:v1:" + hashlib.sha256(identity).hexdigest()

    @staticmethod
    def owner_prefix(owner):
        return "career:chat:v2:" + hashlib.sha256(owner.encode()).hexdigest() + ":"

    @classmethod
    def key(cls, owner, session_id, *, epoch=0):
        return cls.owner_prefix(owner) + str(epoch) + ":" + hashlib.sha256(session_id.encode()).hexdigest()

    def call(self, operation, *args):
        if time.monotonic() < self.retry_at:
            return None
        try:
            with self.lock:
                if self.client is None:
                    from redis import Redis
                    self.client = Redis.from_url(self.url, decode_responses=True,
                                                 socket_timeout=1, socket_connect_timeout=1)
                client = self.client
            return getattr(client, operation)(*args)
        except Exception:
            self.retry_at = time.monotonic() + 30
            return None

    def get(self, owner, session_id, *, epoch=0):
        raw = self.call("get", self.key(owner, session_id, epoch=epoch))
        try:
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError):
            return None

    def put(self, owner, session_id, value, *, epoch=0):
        self.call("setex", self.key(owner, session_id, epoch=epoch), self.ttl, json.dumps(value, ensure_ascii=False))

    def delete(self, owner, session_id):
        self.call("delete", self.key(owner, session_id), self.legacy_key(owner, session_id))

    def cleanup(self, owner, sessions, *, entire_owner):
        """Unlike cache reads, deletion must raise until Redis acknowledges it."""
        with self.lock:
            if self.client is None:
                from redis import Redis
                self.client = Redis.from_url(self.url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
            client = self.client
        client.ping()
        known = {self.legacy_key(owner, session_id) for session_id in sessions}
        wanted = {hashlib.sha256(session_id.encode()).hexdigest() for session_id in sessions}
        for key in client.scan_iter(match=self.owner_prefix(owner) + "*", count=200):
            if entire_owner or key.rsplit(":", 1)[-1] in wanted:
                client.delete(key)
        # Migrate/clear identifiable legacy cache entries, including orphaned sessions.
        if entire_owner:
            unidentified = False
            for key in client.scan_iter(match="career:chat:v1:*", count=200):
                if key in known:
                    continue
                try:
                    value = json.loads(client.get(key) or "{}")
                    identified = False
                    for row in value.get("items", []):
                        session_id = row.get("session_id") if isinstance(row, dict) else None
                        if isinstance(session_id, str):
                            identified = True
                            if key == self.legacy_key(owner, session_id):
                                known.add(key)
                                break
                    if value.get("items") and not identified or set(value) - {"items", "version"}:
                        unidentified = True
                except (ValueError, TypeError, AttributeError):
                    unidentified = True
        for key in known:
            client.delete(key)
        if entire_owner and unidentified:
            raise LegacyCachePending()

    def close(self):
        with self.lock:
            if self.client is not None:
                self.client.close()
                self.client = None
