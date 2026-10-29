import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import json

from redis.asyncio import Redis


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MemoryBusyError(RuntimeError):
    pass


class RecentMemory:
    def __init__(self, redis: Redis, *, ttl: int, recent_turns: int, prefix="career:memory:v1"):
        self.redis, self.ttl, self.recent_turns, self.prefix = redis, ttl, recent_turns, prefix

    def key(self, user_id: str, session_id: str) -> str:
        return f"{self.prefix}:session:{digest(user_id)}:{digest(session_id)}"

    @asynccontextmanager
    async def lock(self, user_id: str, *, scope="profile"):
        # 可续租的跨进程锁；进程退出后最多 60 秒释放，不会留下永久锁。
        lock = self.redis.lock(f"{self.prefix}:lock:{scope}:{digest(user_id)}", timeout=60, thread_local=False)
        if not await lock.acquire(blocking=False):
            raise MemoryBusyError("该用户的记忆正在更新，请稍后重试")
        parent = asyncio.current_task()
        lost = False

        async def renew():
            nonlocal lost
            try:
                while True:
                    await asyncio.sleep(20)
                    await lock.extend(60, replace_ttl=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                lost = True
                parent.cancel()

        heartbeat = asyncio.create_task(renew())
        try:
            yield
        except asyncio.CancelledError:
            if lost:
                raise MemoryBusyError("记忆锁续租失败，已停止执行；请恢复服务后重试") from None
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            with suppress(Exception):
                await lock.release()

    async def load(self, user_id: str, session_id: str) -> dict:
        raw = await self.redis.get(self.key(user_id, session_id))
        return json.loads(raw) if raw else {"summary": "", "turns": []}

    async def append(self, user_id: str, session_id: str, turn: dict, summarizer):
        async with self.lock(user_id):
            key = self.key(user_id, session_id)
            seen = f"{key}:seen:{digest(turn['event_id'])}"
            if await self.redis.exists(seen):
                return
            current = await self.load(user_id, session_id)
            turns = current["turns"] + [turn]
            overflow = max(0, len(turns) - self.recent_turns)
            summary = current["summary"]
            if overflow:
                # 摘要失败时不裁掉历史；该节点可以直接从检查点恢复。
                summary = await summarizer(summary, turns[:overflow])
            updated = {"summary": summary, "turns": turns[overflow:]}
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.set(key, json.dumps(updated, ensure_ascii=False), ex=self.ttl)
                pipe.set(seen, "1", ex=self.ttl)
                await pipe.execute()
