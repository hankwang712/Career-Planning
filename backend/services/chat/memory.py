"""Application entry point for LLM memory: recall, extraction and background work.

SQLite owns durable records. Redis and Chroma are replaceable acceleration layers.
This module has no dependency on FastAPI, Flask or the chat response format.
"""

from dataclasses import dataclass
import json
import logging
import re
import threading

from .cache import RecentCache
from .extraction import EXTRACTION_PROMPT, SUMMARY_PROMPT, validate_candidates
from .policy import estimate_tokens, message_windows
from .reconciliation import RELATION_PROMPT, automatic_decision, validate_decision
from .schemas import DecisionOutput, ExtractionOutput, SummaryOutput, response_format
from .storage import normalized
from .vector import VectorMemory

logger = logging.getLogger(__name__)


class CleanupBusy(Exception):
    pass


@dataclass
class MemoryContext:
    summary: str
    recent: list[dict]
    memories: list[dict]
    conflicts: list[dict]
    vector_matches: set[str]


class MemoryManager:
    RECENT_LIMIT = 40
    RECENT_CHARACTERS = 32000

    def __init__(self, store, directory, *, runtime, client_factory, cache=None, vector=None):
        self.store = store
        self.cache = cache if cache is not None else RecentCache()
        self.vector = vector if vector is not None else VectorMemory(directory)
        self.runtime = runtime
        self.client_factory = client_factory
        self.policy = store.policy
        self._worker = None
        self._worker_lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stopping = threading.Event()
        self._resources_closed = False

    def _recent(self, owner, session):
        epoch = session["privacy_epoch"]
        version = [session["updated_at"], session["analyzed_seq"], epoch]
        cached = self.cache.get(owner, session["id"], epoch=epoch)
        items = cached.get("items") if isinstance(cached, dict) and cached.get("version") == version else None
        valid = isinstance(items, list) and len(items) <= self.RECENT_LIMIT and all(
            isinstance(row, dict) and type(row.get("seq")) is int
            and row.get("role") in ("user", "assistant")
            and isinstance(row.get("content"), str) and row.get("status") in ("complete", "failed")
            for row in items)
        if not valid:
            items = self.store.messages(owner, session["id"], limit=self.RECENT_LIMIT)["items"]
            lease = self.store.begin_artifact(owner, "cache", epoch=epoch)
            if lease:
                try:
                    if self.store.artifact_valid(lease):
                        self.cache.put(owner, session["id"], {"version": version, "items": items}, epoch=epoch)
                    if not self.store.artifact_valid(lease):
                        try:
                            self.cache.cleanup(owner, [session["id"]], entire_owner=False)
                        except Exception:
                            self.store.repair_artifacts(owner)
                finally:
                    self.store.end_artifact(lease)
        recent, size = [], 0
        for row in reversed(items):
            if row["seq"] <= max(session["analyzed_seq"], session["context_cutoff_seq"]) or row["status"] != "complete":
                continue
            if size + len(row["content"]) > self.RECENT_CHARACTERS:
                break
            recent.append({"role": row["role"], "content": row["content"]})
            size += len(row["content"])
        return list(reversed(recent))

    @staticmethod
    def confirmed(memories):
        disputed = {(row["kind"], row["key"], normalized(row["subject"]))
                    for row in memories if row["status"] == "conflict"}
        return [row for row in memories if row["status"] == "active" and
                (row["kind"], row["key"], normalized(row["subject"])) not in disputed]

    def context(self, owner, session_id, query):
        session = self.store.session(owner, session_id)  # Check ownership before reading any cache.
        _, memories = self.store.memory_snapshot(owner)
        active = self.confirmed(memories)
        identity_query = bool(re.search(r"我是谁|我的(?:背景|学校|学历|专业|毕业|情况|简历)|了解我", query))
        ids = self.vector.search(owner, query, epoch=session["privacy_epoch"]) if active and not identity_query and not self.store.cleanup_pending(owner) else []
        ranks = {memory_id: rank for rank, memory_id in enumerate(ids)}
        core = [row for row in active if row["kind"] in {"preference", "communication"}][:20]
        core_ids = {row["id"] for row in core}
        related = sorted((row for row in active if row["id"] not in core_ids), key=lambda row: (
            ranks.get(row["id"], len(ranks)),
            not (identity_query and row["key"] in {"education", "graduation", "major"}), -row["updated_at"]))[:12]
        conflicts = [{"key": row["key"], "subject": row["subject"]} for row in memories if row["status"] == "conflict"]
        return MemoryContext(session["summary"], self._recent(owner, session), core + related, conflicts, set(ids))

    def overview(self, owner, session_id=None):
        trace = self.store.context_trace(owner, session_id) if session_id else None
        _, rows = self.store.memory_snapshot(owner)
        titles = {row["id"]: row["title"] for row in self.store.list_sessions(owner)}
        items = [{**{key: row[key] for key in ("id", "kind", "key", "subject", "value", "status", "updated_at")},
                  "source_session": row["source_session"], "source_title": titles.get(row["source_session"], "原对话已删除"),
                  "evidence": [{"quote": item["quote"][:600]} for item in json.loads(row["evidence"])[:5]]} for row in rows]
        active = [row for row in rows if row["status"] == "active"]
        session = self.store.session(owner, session_id) if session_id else None
        return {"items": items, "jobs": self.store.memory_status(owner), "cleanup": self.store.cleanup_status(owner),
                "cleanup_pending_count": self.store.cleanup_count(owner),
                "controls": self.store.privacy(owner),
                "index": {**self.vector.status(), "indexed": sum(row["indexed_revision"] >= row["revision"] for row in active),
                          "total": len(active)}, "context": trace,
                "progress": {key: session[key] for key in ("analyzed_seq", "memory_seq")} if session else None}

    def career_context(self, owner, *, disputed=()):
        """Expose confirmed facts and preferences to report Agents, without transcripts."""
        _, memories = self.store.memory_snapshot(owner)
        active = [row for row in self.confirmed(memories) if (row["key"], normalized(row["subject"])) not in disputed]
        preferences = "；".join(row["value"] for row in active if row["kind"] == "preference")[:4000]
        facts = [quote["quote"] for row in active if row["kind"] == "fact" for quote in json.loads(row["evidence"])]
        return {"preferences": preferences, "evidence": "\n".join(dict.fromkeys(facts))[:6000]}

    def invalidate(self, owner, session_id):
        self.cache.delete(owner, session_id)

    def delete_session(self, owner, session_id):
        identifier = self.store.request_session_deletion(owner, session_id)
        self.start()
        return identifier

    def delete_owner(self, owner):
        identifier = self.store.clear_chat_data(owner)
        self.start()
        return identifier

    def queue(self, owner, session_id, *, immediate=False):
        self.store.enqueue(owner, session_id, immediate=immediate)
        self.start()

    def forget(self, owner, memory_id, *, mode="forget"):
        identifier = self.store.request_memory_deletion(owner, memory_id, mode=mode)
        self.start()
        return identifier

    def correct(self, owner, memory_id, value):
        identifier = self.store.correct_memory(owner, memory_id, value)
        self.start()
        return identifier

    def analyze(self, job):
        messages = self.store.analysis_messages(job)
        if not messages:
            raise ValueError("Analysis job has no messages")
        if job["kind"] == "summary":
            summary = job["summary"]
            for window in message_windows(messages, self.policy.batch_tokens):
                result = self._request_json(SUMMARY_PROMPT, {"previous_summary": summary, "messages": window}, job)
                summary = result.get("summary")
                if not isinstance(summary, str) or len(summary) > 2500:
                    raise ValueError("Invalid conversation summary")
            return self.store.apply_summary(job, messages, summary)
        collected = {}
        for window in message_windows(messages, self.policy.batch_tokens):
            if not any(row["role"] == "user" for row in window):
                continue
            result = self._request_json(EXTRACTION_PROMPT, {"messages": window}, job)
            for candidate in validate_candidates(result, window):
                slot = candidate["kind"], candidate["key"], normalized(candidate["subject"])
                previous = collected.get(slot)
                if previous and normalized(previous["value"]) != normalized(candidate["value"]) and candidate["operation"] == "assert":
                    raise ValueError("Conflicting candidate windows need explicit reconciliation")
                if previous and previous["operation"] == candidate["operation"] and previous["value"] == candidate["value"]:
                    candidate["evidence"] = (previous["evidence"] + [item for item in candidate["evidence"] if item not in previous["evidence"]])[-5:]
                if not previous or previous["operation"] == "assert" or candidate["operation"] in {"correct", "retract"}:
                    collected[slot] = candidate
        candidates = validate_candidates({"memories": list(collected.values())}, messages)
        return self.commit_candidates(job, messages, candidates)

    def _request_json(self, prompt, payload, job):
        content = json.dumps(payload, ensure_ascii=False)
        output_model = {EXTRACTION_PROMPT: ExtractionOutput, SUMMARY_PROMPT: SummaryOutput,
                        RELATION_PROMPT: DecisionOutput}[prompt]
        output_format = response_format(output_model)
        schema_tokens = estimate_tokens(json.dumps(output_format, ensure_ascii=False)) if output_format["type"] == "json_schema" else 0
        if estimate_tokens(prompt) + estimate_tokens(content) + schema_tokens > self.policy.input_tokens:
            raise ValueError("Extraction request exceeds the configured input token budget")
        self.store.renew_job(job)
        runtime = self.runtime(json.loads(job["selection"]))
        client = self.client_factory(runtime)
        try:
            response = client.chat.completions.create(model=runtime[2], response_format=output_format,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}], max_tokens=4500)
            choice = response.choices[0]
            if getattr(choice, "finish_reason", None) in {"length", "content_filter"} or getattr(choice.message, "refusal", None):
                raise ValueError("Incomplete or refused memory output")
            result = json.loads(choice.message.content)
            return output_model.model_validate(result).model_dump()
        finally:
            client.close()

    def commit_candidates(self, job, messages, candidates, expected_revision=None):
        revision = self.store.memory_snapshot(job["owner"])[0] if expected_revision is None else expected_revision
        decisions = []
        accepted = []
        for candidate in candidates:
            if not self.store.candidate_allowed(job["owner"], candidate, messages):
                continue
            matches = self.store.slot_memories(job["owner"], candidate)
            if not matches and candidate["key"] == "experience":
                ids = self.vector.search(job["owner"], candidate["subject"] + ": " + candidate["value"], epoch=self.store.privacy(job["owner"])["epoch"])
                matches = self.store.memories_by_ids(job["owner"], ids, kind="fact", key="experience")
            decision = automatic_decision(candidate, matches)
            if decision is None:
                existing = [{key: row[key] for key in ("id", "kind", "key", "subject", "value", "status", "revision")} for row in matches[:5]]
                decision = self._request_json(RELATION_PROMPT, {"candidate": candidate, "existing": existing}, job)
            decisions.append(validate_decision(decision, candidate, matches))
            accepted.append(candidate)
        return self.store.apply_memory_plan(job, messages, accepted, decisions, revision)

    def run_once(self):
        """Process one persisted job or synchronize the index; return whether a job ran."""
        cleanup = self.store.claim_cleanup()
        if cleanup:
            try:
                if self.store.cleanup_blocked(cleanup["owner"], exclude_token=cleanup["token"]):
                    raise CleanupBusy()
                payload = cleanup["payload"]
                if payload.get("vector_owner"):
                    self.vector.delete_owner(cleanup["owner"])
                self.cache.cleanup(cleanup["owner"], payload.get("cache_sessions", []), entire_owner=payload.get("cache_owner", False))
                self.store.checkpoint_cleanup()
            except Exception as error:
                self.store.finish_cleanup(cleanup, error=error)
            else:
                self.store.finish_cleanup(cleanup)
            return True
        job = self.store.claim_job()
        if not job:
            self.vector.sync(self.store)
            return False
        try:
            self.analyze(job)
        except Exception:
            logger.warning("助手记忆分析失败，任务将按策略重试", exc_info=False)
            self.store.fail_job(job)
        return True

    def start(self):
        with self._worker_lock:
            if self._stopping.is_set():
                return
            if self._worker and self._worker.is_alive():
                self._wakeup.set()
                return
            self._worker = threading.Thread(target=self._work, name="assistant-memory", daemon=True)
            self._worker.start()

    def _work(self):
        try:
            while not self._stopping.is_set():
                try:
                    if self.run_once():
                        continue
                except Exception:
                    logger.warning("助手记忆后台任务暂不可用", exc_info=False)
                self._wakeup.wait(30)
                self._wakeup.clear()
        finally:
            self._close_resources()

    def _close_resources(self):
        with self._worker_lock:
            if self._resources_closed:
                return
            self._resources_closed = True
        try:
            self.cache.close()
        finally:
            self.vector.close()

    def close(self):
        with self._worker_lock:
            self._stopping.set()
            self._wakeup.set()
            worker = self._worker
        if worker:
            worker.join(timeout=5)
        if not worker or not worker.is_alive():
            self._close_resources()
        # A running model call releases resources in _work's finally when it exits.
