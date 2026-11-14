from dataclasses import dataclass, field
import json
import logging
import re
import threading
import time

from pydantic import ValidationError

from .extraction import EXTRACTION_PROMPT, MEMORY_KEYS, NOTE_PROMPT, merge_note, validate_candidates
from .history import (DIGEST_PROMPT, MAX_NOTES, NOTE_LIMIT, SELECT_PROMPT, choose_fallback, date_of, needs_history,
                      render_digest)
from .policy import estimate_tokens, message_windows
from .reconciliation import automatic_decision, validate_decision
from .schemas import DigestOutput, ExtractionOutput, NoteOutput, SelectionOutput, response_format
from .storage import normalized

logger = logging.getLogger(__name__)

MAINTENANCE_INTERVAL = 6 * 3600
MODEL_OUTPUTS = {EXTRACTION_PROMPT: ExtractionOutput, NOTE_PROMPT: NoteOutput,
                 DIGEST_PROMPT: DigestOutput, SELECT_PROMPT: SelectionOutput}


def analysis_error_detail(error):
    """Useful diagnostics without provider bodies, API keys or private excerpts."""
    if isinstance(error, ValidationError):
        fields = {"title", "gist", "goal", "decisions", "corrections", "open_questions", "advice", "goals", "focus",
                  "selected", "memories", "kind", "key", "subject", "value", "operation",
                  "evidence", "message_id", "quote", "confidence", "scope", "reason", "target_id", "requires_confirmation"}
        details = []
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:3]:
            location = ".".join(str(part) if isinstance(part, int) or part in fields else "*" for part in item["loc"])
            code = item["type"] if re.fullmatch(r"[a-z_]{1,60}", item["type"]) else "invalid"
            details.append(location + ":" + code)
        return "输出字段校验失败[" + ", ".join(details) + "]"
    if isinstance(error, json.JSONDecodeError):
        return f"JSON解析失败[行{error.lineno},列{error.colno}]"
    status = getattr(error, "status_code", None)
    if type(status) is int:
        return f"模型接口HTTP状态码={status}"
    return {
        "Incomplete or refused memory output": "模型输出被截断、过滤或拒绝",
        "Extraction request exceeds the configured input token budget": "输入超过记忆分析Token预算",
        "Invalid conversation summary": "会话笔记格式无效",
        "Model must return a JSON object": "模型输出不是JSON对象",
        "Evidence must be verbatim user text": "候选证据不属于本批用户原文",
    }.get(str(error), "未记录原始异常文本，以免泄露聊天内容或密钥")


class CleanupBusy(Exception):
    pass


@dataclass
class MemoryContext:
    summary: str
    recent: list[dict]
    memories: list[dict]
    conflicts: list[dict]
    uncovered: int = 0
    history: dict = field(default_factory=lambda: {"used": False})


class MemoryManager:
    LANES = ("urgent", "bulk")

    def __init__(self, store, directory=None, *, runtime, client_factory):
        self.store = store
        self.runtime = runtime
        self.client_factory = client_factory
        self.policy = store.policy
        self._workers = {}
        self._worker_lock = threading.Lock()
        self._wakeups = {lane: threading.Event() for lane in self.LANES}
        self._stopping = threading.Event()
        self._last_maintenance = 0.0

    # ---- 近期窗口与上下文 ----

    def _recent(self, owner, session):
        """Newest whole turns that fit the token budget; never cut a turn in half.

        Returns the rows plus how many unsummarised messages did not fit, so the caller can flag the gap.
        """
        items = self.store.messages(owner, session["id"], limit=self.policy.window_messages)["items"]
        cursor = max(session["analyzed_seq"], session["context_cutoff_seq"])
        turns = []
        for row in reversed([row for row in items if row["seq"] > cursor and row["status"] == "complete"]):
            if turns and turns[-1][0]["request_id"] == row["request_id"]:
                turns[-1].insert(0, row)
            else:
                turns.append([row])
        chosen, used = [], 0
        for turn in turns:
            cost = sum(estimate_tokens(row["content"]) for row in turn)
            # The newest turn is always kept, even when it alone exceeds the budget.
            if chosen and used + cost > self.policy.window_tokens:
                break
            chosen.append(turn)
            used += cost
        rows = [row for turn in reversed(chosen) for row in turn]
        recent = [{"role": row["role"], "content": row["content"], **({"images": row["images"]} if row.get("images") else {})}
                  for row in rows]
        return recent, max(0, self.store.pending_count(session["id"], cursor) - len(rows))

    @staticmethod
    def confirmed(memories):
        disputed = {(row["kind"], row["key"], normalized(row["subject"]))
                    for row in memories if row["status"] == "conflict"}
        # 旧版本可能已保存 skill/experience 记忆；不再属于基础画像，不进入聊天或报告上下文。
        return [row for row in memories if row["status"] == "active" and row["key"] in MEMORY_KEYS.get(row["kind"], ()) and
                (row["kind"], row["key"], normalized(row["subject"])) not in disputed]

    def context(self, owner, session_id, query):
        session = self.store.session(owner, session_id)  # Check ownership before reading any session data.
        settings = self.store.privacy(owner)
        _, memories = self.store.memory_snapshot(owner)
        saved = bool(settings["saved_enabled"])
        active = self.confirmed(memories) if saved else []
        identity_query = bool(re.search(r"我是谁|我的(?:背景|学校|学历|专业|毕业|情况|简历)|了解我", query))
        # 基础画像很小，全部放进上下文；身份类问题时事实排在前面。
        ordered = sorted(active, key=lambda row: (row["kind"] == "fact" and not identity_query,
                                                  row["kind"] == "fact", -row["updated_at"]))[:32]
        conflicts = [{"key": row["key"], "subject": row["subject"]} for row in memories if row["status"] == "conflict"] if saved else []
        recent, uncovered = self._recent(owner, session)
        return MemoryContext(session["summary"], recent, ordered, conflicts, uncovered,
                             self.history(owner, session, query, settings))

    # ---- 参考聊天记录：按相关性才使用 ----

    def history(self, owner, session, query, settings):
        if not settings["history_enabled"] or self.store.cleanup_pending(owner):
            return {"used": False}
        digest = self.store.digest(owner)
        reason = needs_history(query, digest["topics"])
        if not reason:
            return {"used": False}
        candidates = self.store.history_candidates(owner, session["id"])
        if not digest["summary"] and not candidates:
            return {"used": False}
        chosen = self._select_notes(owner, session, query, candidates)
        notes = [{"id": row["id"], "title": row["note_title"], "date": date_of(row["updated_at"]), "note": row["summary"][:NOTE_LIMIT]}
                 for row in self.store.session_notes(owner, chosen)]
        return {"used": True, "reason": reason, "digest": digest["summary"], "notes": notes}

    def _select_notes(self, owner, session, query, candidates):
        if len(candidates) <= MAX_NOTES:
            return [row["id"] for row in candidates]
        finished, result = threading.Event(), []

        def pick():
            try:
                payload = {"query": query[:500], "sessions": [
                    {"id": row["id"], "date": date_of(row["updated_at"]), "title": row["note_title"], "gist": row["note_gist"]}
                    for row in candidates]}
                answer = self._complete(SELECT_PROMPT, SelectionOutput, payload, json.loads(session["selection"] or "{}"),
                                        owner=owner, max_tokens=200)
                valid = {row["id"] for row in candidates}
                result.extend(item for item in answer["selected"] if item in valid)
            except Exception as error:
                logger.info("旧会话选择未完成，改用关键词匹配：%s", analysis_error_detail(error))
            finally:
                finished.set()

        threading.Thread(target=pick, name="assistant-history", daemon=True).start()
        # A slow selector must not hold up the reply; late results are simply discarded.
        if finished.wait(self.policy.history_wait_ms / 1000) and result:
            return result[:MAX_NOTES]
        return choose_fallback(query, candidates)

    # ---- 对外概览 ----

    def overview(self, owner, session_id=None):
        trace = self.store.context_trace(owner, session_id) if session_id else None
        _, rows = self.store.memory_snapshot(owner)
        titles = self.store.session_titles(owner)
        items = [{**{key: row[key] for key in ("id", "kind", "key", "subject", "value", "status", "updated_at")},
                  "source_session": row["source_session"], "source_title": titles.get(row["source_session"], "原对话已删除"),
                  "evidence": [{"quote": item["quote"][:600]} for item in json.loads(row["evidence"])[:5]]} for row in rows]
        session = self.store.session(owner, session_id) if session_id else None
        digest = self.store.digest(owner)
        return {"items": items, "jobs": self.store.memory_status(owner), "cleanup": self.store.cleanup_status(owner),
                "cleanup_pending_count": self.store.cleanup_count(owner),
                "controls": self.store.privacy(owner), "context": trace, "quota": self.store.quota(owner),
                "history": {"summary": digest["summary"], "topics": digest["topics"], "updated_at": digest["updated_at"],
                            "updating": bool(digest["dirty"])},
                "progress": {key: session[key] for key in ("analyzed_seq", "memory_seq")} if session else None}

    def career_context(self, owner, *, disputed=()):
        """Expose confirmed facts and preferences to report Agents, without transcripts or reference history."""
        if not self.store.privacy(owner)["saved_enabled"]:
            return {"preferences": "", "evidence": ""}
        _, memories = self.store.memory_snapshot(owner)
        active = [row for row in self.confirmed(memories) if (row["key"], normalized(row["subject"])) not in disputed]
        preferences = "；".join(row["value"] for row in active if row["kind"] == "preference")[:4000]
        facts = [row["value"] for row in active if row["kind"] == "fact"]
        return {"preferences": preferences, "evidence": "\n".join(dict.fromkeys(facts))[:6000]}

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

    def correct(self, owner, memory_id, value, *, expected_value=None):
        identifier = self.store.correct_memory(owner, memory_id, value, expected_value=expected_value)
        self.start()
        return identifier

    # ---- 后台分析 ----

    def analyze(self, job):
        messages = self.store.analysis_messages(job)
        if not messages:
            raise ValueError("Analysis job has no messages")
        if job["kind"] == "summary":
            return self._write_note(job, messages)
        if job.get("incognito") or not self.store.privacy(job["owner"])["saved_enabled"]:
            return self.store.skip_memory(job, messages)
        _, snapshot = self.store.memory_snapshot(job["owner"])
        existing = [{key: row[key] for key in ("kind", "key", "subject", "value")} for row in self.confirmed(snapshot)][:32]
        collected = {}
        for window in message_windows(messages, self.policy.batch_tokens):
            if not any(row["role"] == "user" for row in window):
                continue
            result = self._request_json(EXTRACTION_PROMPT, {"messages": window, "existing": existing}, job)
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

    def _write_note(self, job, messages):
        previous = json.loads(job["notes"]) if job.get("notes") else {}
        legacy = job["summary"] if job.get("summary") and not previous else ""
        note = None
        for window in message_windows(messages, self.policy.batch_tokens):
            result = self._request_json(NOTE_PROMPT, {"previous_notes": previous, "legacy_summary": legacy, "messages": window}, job)
            note = merge_note(result, previous)
            previous, legacy = note["notes"], ""
        return self.store.apply_note(job, messages, note)

    def rebuild_digest(self, claim):
        """Regenerate the user-level background digest from the current (non-incognito) session notes."""
        owner = claim["owner"]
        sessions = self.store.digest_sessions(owner)
        if not sessions:
            return self.store.finish_digest(owner, claim["version"], "", [])
        topics = [{"id": row["id"], "title": row["note_title"], "date": date_of(row["updated_at"])} for row in sessions]
        _, snapshot = self.store.memory_snapshot(owner)
        payload = {"previous_digest": claim["previous"],
                   "saved_memories": [{"key": row["key"], "value": row["value"]} for row in self.confirmed(snapshot)],
                   "sessions": [{"date": date_of(row["updated_at"]), "title": row["note_title"], "gist": row["note_gist"],
                                 "goal": (json.loads(row["notes"]).get("goal", "") if row["notes"] else "")} for row in sessions]}
        result = self._complete(DIGEST_PROMPT, DigestOutput, payload, json.loads(claim["selection"] or "{}"), owner=owner, max_tokens=900)
        self.store.finish_digest(owner, claim["version"], render_digest(result["goals"], result["focus"], topics), topics)

    def _request_json(self, prompt, payload, job):
        return self._complete(prompt, MODEL_OUTPUTS[prompt], payload, json.loads(job["selection"]), owner=job["owner"],
                              max_tokens=6000 if prompt == NOTE_PROMPT else 4500, job=job)

    def _complete(self, prompt, output_model, payload, selection, *, owner, max_tokens, job=None):
        content = json.dumps(payload, ensure_ascii=False)
        output_format = response_format(output_model)
        schema_tokens = estimate_tokens(json.dumps(output_format, ensure_ascii=False)) if output_format["type"] == "json_schema" else 0
        if estimate_tokens(prompt) + estimate_tokens(content) + schema_tokens > self.policy.input_tokens:
            raise ValueError("Extraction request exceeds the configured input token budget")
        if job:
            self.store.renew_job(job)
        runtime = self.runtime(selection)
        client = self.client_factory(runtime)
        try:
            response = client.chat.completions.create(model=runtime[2], response_format=output_format,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": content}], max_tokens=max_tokens)
            choice = response.choices[0]
            used = getattr(getattr(response, "usage", None), "total_tokens", None)
            self.store.add_usage(owner, used if type(used) is int else
                                 estimate_tokens(prompt) + estimate_tokens(content) + estimate_tokens(str(choice.message.content or "")))
            if getattr(choice, "finish_reason", None) in {"length", "content_filter"} or getattr(choice.message, "refusal", None):
                raise ValueError("Incomplete or refused memory output")
            return output_model.model_validate(json.loads(choice.message.content)).model_dump()
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
            decision = automatic_decision(candidate, matches)
            if decision is None:
                logger.info("该属性存在未解决的冲突，暂不写入：%s", candidate["key"])
                continue
            try:
                decisions.append(validate_decision(decision, candidate, matches))
            except ValueError:
                # 宁可不记，也不让一条无法判定的候选拖垮整批任务。
                logger.info("无法安全判定该候选与旧记忆的关系，已忽略：%s", candidate["key"])
                continue
            accepted.append(candidate)
        return self.store.apply_memory_plan(job, messages, accepted, decisions, revision)

    # ---- 工作线程 ----

    def _claim(self, lane):
        if lane == "urgent":
            return self.store.claim_job(min_priority=self.policy.urgent_priority)
        return self.store.claim_job(max_priority=self.policy.urgent_priority)

    def run_once(self, lane="urgent"):
        """Process one persisted task for a lane; return whether anything ran."""
        if lane == "urgent":
            cleanup = self.store.claim_cleanup()
            if cleanup:
                try:
                    if self.store.cleanup_blocked(cleanup["owner"], exclude_token=cleanup["token"]):
                        raise CleanupBusy()
                    self.store.checkpoint_cleanup()
                except Exception as error:
                    self.store.finish_cleanup(cleanup, error=error)
                else:
                    self.store.finish_cleanup(cleanup)
                return True
        job = self._claim(lane)
        if not job:
            return self._idle(lane)
        if self.store.quota(job["owner"])["state"] != "ok":
            self.store.defer_job(job, 3600)
            logger.info("用户今日额度已用尽，后台%s任务推迟一小时", job["kind"])
            return True
        started, outcome = time.monotonic(), "ok"
        try:
            self.analyze(job)
        except Exception as error:
            outcome = "failed"
            action = "已达上限，停止自动重试" if job["attempts"] >= 3 else f"约{60 * job['attempts']}秒后重试"
            logger.warning("助手%s失败：%s；异常=%s；尝试=%d/3；%s",
                           "会话笔记" if job["kind"] == "summary" else "长期记忆提取",
                           analysis_error_detail(error), type(error).__name__, job["attempts"], action)
            self.store.fail_job(job)
        logger.info("memory_job %s", json.dumps({"lane": lane, "kind": job["kind"], "reason": job["reason"], "priority": job["priority"],
                                                  "wait_s": round(job["wait_seconds"], 1), "run_s": round(time.monotonic() - started, 2),
                                                  "attempt": job["attempts"], "outcome": outcome}, ensure_ascii=False))
        return True

    def _idle(self, lane):
        """No job in this lane: refresh the background digest (bulk) or run retention housekeeping."""
        if lane != "bulk":
            return False
        claim = self.store.claim_digest()
        if claim:
            try:
                if self.store.quota(claim["owner"])["state"] != "ok":
                    self.store.release_digest(claim["owner"])
                else:
                    self.rebuild_digest(claim)
            except Exception as error:
                self.store.release_digest(claim["owner"])
                logger.warning("用户背景摘要更新失败：%s；异常=%s", analysis_error_detail(error), type(error).__name__)
            return True
        if time.monotonic() - self._last_maintenance > MAINTENANCE_INTERVAL or not self._last_maintenance:
            self._last_maintenance = time.monotonic() or 1.0
            result = self.store.maintenance()
            logger.info("retention %s", json.dumps(result))
        return False

    def start(self):
        with self._worker_lock:
            if self._stopping.is_set():
                return
            for lane in self.LANES:
                worker = self._workers.get(lane)
                if worker and worker.is_alive():
                    self._wakeups[lane].set()
                    continue
                self._workers[lane] = threading.Thread(target=self._work, args=(lane,), name=f"assistant-memory-{lane}", daemon=True)
                self._workers[lane].start()

    def _work(self, lane):
        wakeup = self._wakeups[lane]
        while not self._stopping.is_set():
            try:
                if self.run_once(lane):
                    continue
            except Exception:
                logger.warning("助手记忆后台任务暂不可用", exc_info=False)
            wakeup.wait(30)
            wakeup.clear()

    def close(self):
        with self._worker_lock:
            self._stopping.set()
            workers = list(self._workers.values())
            for wakeup in self._wakeups.values():
                wakeup.set()
        for worker in workers:
            worker.join(timeout=5)
