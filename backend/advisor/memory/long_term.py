import asyncio
import json
import math
import time
import unicodedata

from .recent import digest


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class LongTermMemory:
    def __init__(self, collection, embeddings, *, half_life_days=90, recall_limit=8, clock=time.time):
        self.collection, self.embeddings = collection, embeddings
        self.half_life_days, self.recall_limit, self.clock = half_life_days, recall_limit, clock

    @staticmethod
    def where(user_id: str, status: str | None = None):
        owner = {"owner": digest(user_id)}
        return {"$and": [owner, {"status": status}]} if status else owner

    async def records(self, user_id: str, *, status="active") -> list[dict]:
        result = await asyncio.to_thread(self.collection.get, where=self.where(user_id, status),
                                         include=["metadatas", "documents"])
        return [{"id": key, **metadata, "text": document}
                for key, metadata, document in zip(result["ids"], result["metadatas"], result["documents"])]

    async def event_changes(self, user_id: str, event_id: str):
        owner = digest(user_id)
        result = await asyncio.to_thread(self.collection.get, ids=[f"{owner}:event:{digest(event_id)}"],
                                         where={"owner": owner}, include=["metadatas"])
        return json.loads(result["metadatas"][0]["changes"]) if result["ids"] else None

    async def apply(self, user_id: str, session_id: str, candidates, event_id: str) -> list[dict]:
        """调用方持有用户锁；journal 与各版本在一次 upsert 中提交，重试不回滚较新事实。"""
        owner = digest(user_id)
        journal_id = f"{owner}:event:{digest(event_id)}"
        previous_changes = await self.event_changes(user_id, event_id)
        if previous_changes is not None:
            return previous_changes
        active = {row["id"]: row for row in await self.records(user_id)}
        conflicts = await self.records(user_id, status="conflict")
        writes, changes, slots = {}, [], set()
        now = self.clock()
        for item in candidates:
            slot = digest(json.dumps([item.kind, item.key, normalized(item.subject)], ensure_ascii=False))
            record_id = f"{owner}:slot:{slot}"
            if record_id in slots:
                raise ValueError("同一次提取不能重复更新同一记忆槽位")
            slots.add(record_id)
            old = active.get(record_id)
            if item.operation in {"correct", "retract"}:
                for conflict in conflicts:
                    if conflict["kind"] == item.kind and conflict["key"] == item.key and normalized(conflict["subject"]) == normalized(item.subject):
                        resolved = {key: value for key, value in conflict.items() if key not in {"id", "text"}}
                        resolved["status"] = "resolved"
                        writes[conflict["id"]] = resolved
            metadata = {
                "owner": owner, "kind": item.kind, "key": item.key, "subject": item.subject,
                "value": item.value, "evidence": item.evidence, "status": "active",
                "source_session": session_id, "event_id": event_id, "updated_at": now,
                "created_at": old["created_at"] if old else now,
                "revision": old["revision"] + 1 if old else 1,
            }
            change = {"key": item.key, "subject": item.subject, "value": item.value}
            if item.operation == "retract":
                if old:
                    metadata.update(value=old["value"], status="retracted")
                    writes[record_id] = metadata
                change["action"] = "retracted" if old else "absent"
            elif old and normalized(old["value"]) == normalized(item.value):
                metadata["revision"] = old["revision"]
                writes[record_id] = metadata
                change["action"] = "duplicate"
            elif old and item.kind == "fact" and item.operation != "correct":
                metadata["status"] = "conflict"
                writes[f"{record_id}:conflict:{digest(event_id)}"] = metadata
                change.update(action="conflict", previous=old["value"])
            else:
                if old:
                    archived = {key: value for key, value in old.items() if key not in {"id", "text"}}
                    archived["status"] = "superseded"
                    writes[f"{record_id}:history:{old['revision']}:{digest(event_id)}"] = archived
                writes[record_id] = metadata
                change.update(action="updated" if old else "added")
                if old:
                    change["previous"] = old["value"]
            changes.append(change)
        # 事件日志持久化在 Chroma，防止 Redis TTL 到期后重放旧请求。
        writes[journal_id] = {"owner": owner, "status": "event", "event_id": event_id,
                              "updated_at": now, "changes": json.dumps(changes, ensure_ascii=False)}
        documents = [f"{row['kind']} {row['key']} {row['subject']}: {row['value']}"
                     if "value" in row else "memory update event" for row in writes.values()]
        vectors = await self.embeddings.aembed_documents(documents)
        await asyncio.to_thread(self.collection.upsert, ids=list(writes), metadatas=list(writes.values()),
                                documents=documents, embeddings=vectors)
        return changes

    async def recall(self, user_id: str, query: str) -> list[dict]:
        active = await self.records(user_id)
        if not active or not query.strip():
            return []
        vector = await self.embeddings.aembed_query(query)
        results = await asyncio.to_thread(
            self.collection.query, query_embeddings=[vector], where=self.where(user_id, "active"),
            n_results=min(len(active), max(self.recall_limit * 4, 20)),
            include=["metadatas", "documents", "distances"],
        )
        recalled = []
        for key, meta, text, distance in zip(results["ids"][0], results["metadatas"][0],
                                             results["documents"][0], results["distances"][0]):
            similarity = max(0.0, min(1.0, 1.0 - distance))
            if similarity < .15:
                continue
            days = max(0, self.clock() - meta["updated_at"]) / 86400
            decay = math.exp(-math.log(2) * days / self.half_life_days)
            recalled.append({"id": key, **meta, "text": text, "similarity": similarity,
                             "recency": decay, "score": similarity * (.5 + .5 * decay)})
        return sorted(recalled, key=lambda item: (-item["score"], item["id"]))[:self.recall_limit]
