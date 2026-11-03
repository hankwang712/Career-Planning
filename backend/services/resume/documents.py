from hashlib import sha256
import json
from pathlib import Path
import re
import threading

from .repository import ResumeRepository
from .facts import facts_from_structured


def redact_contacts(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", str(text or ""))
    text = re.sub(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)", "[电话已隐藏]", text)
    return re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[证件号码已隐藏]", text)


class ResumeDocuments:
    def __init__(self, path, reader=None, current_source=None, profile_extractor=None):
        self.repository = ResumeRepository(path)
        self.profile_extractor = profile_extractor
        self.reader = reader or self.read_document
        self.guard = threading.Lock()
        self.locks = {}
        self.tasks = {}
        self.read_ready = {}
        self.profile_locks = {}
        self.current_source = current_source

    def forget(self, owner):
        self.repository.delete_owner(owner)

    def _profile(self, owner, fingerprint, source, text):
        with self.guard:
            lock = self.profile_locks.setdefault((owner, fingerprint), threading.Lock())
        if not lock.acquire(blocking=False):
            return
        try:
            self._build_profile(owner, fingerprint, source, text)
        finally:
            lock.release()

    def _build_profile(self, owner, fingerprint, source, text):
        row = self.repository.get(owner, fingerprint)
        if not row:
            return
        provided = facts_from_structured(source.get("structured_profile"))
        if provided:
            if self.is_current(owner, fingerprint) and (json.loads(row["facts"]) != provided or row["profile_status"] != "ready"):
                self.repository.save_profile(owner, fingerprint, facts=provided)
            return
        if row["profile_status"] in {"ready", "failed"}:
            return
        try:
            if not self.profile_extractor:
                return
            facts = self.profile_extractor(text, source.get("selection") or {})
            if self.is_current(owner, fingerprint):
                self.repository.save_profile(owner, fingerprint, facts=facts)
        except Exception:
            if self.is_current(owner, fingerprint):
                self.repository.save_profile(owner, fingerprint, status="failed", error="结构化资料提取未完成，可手动重新同步。")

    def is_current(self, owner, fingerprint):
        return self.current_source is None or self.fingerprint(self.current_source(owner) or {}) == fingerprint

    @staticmethod
    def read_document(path):
        from experiments.news_advisor.tools.document import read_document
        return read_document.invoke({"file_path": path, "max_pages": 20})

    @staticmethod
    def fingerprint(source):
        path = Path(source.get("path") or "")
        try:
            if not path.is_file():
                return ""
            digest = sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            return ""
        return digest.hexdigest()

    def snapshot(self, owner, source):
        source = source or {}
        fingerprint = self.fingerprint(source)
        if not fingerprint:
            return {"status": "missing", "file_name": "", "character_count": 0,
                    "message": "尚未找到当前账户的可用简历。"}
        row = self.repository.get(owner, fingerprint)
        status = row["status"] if row else "uploaded"
        metadata = json.loads(row["metadata"]) if row else {}
        original = row["content"] if row and status == "ready" else source.get("text", "")
        preview = redact_contacts(original)
        if source.get("text") and status != "ready":
            status = "available"
        partial = len(preview) > 16000 or metadata.get("status") == "partial"
        return {"status": status, "file_name": Path(source.get("name") or source["path"]).name,
                "character_count": len(row["content"]) if row and status == "ready" else len(source.get("text") or ""),
                "updated_at": row["updated_at"] if row else None,
                "message": row["error"] if row and status == "failed" else {
                    "ready": "简历原文已接入；当前上下文使用部分正文。" if partial else "简历原文已接入，可用于后续聊天。", "available": "已有可读取的简历原文，首次聊天会自动接入。",
                    "reading": "正在调用现有文档工具读取简历。", "uploaded": "文件已上传，首次聊天时读取；也可以现在同步。",
                }.get(status, ""),
                "preview": preview[:16000], "truncated": partial,
                "fingerprint": fingerprint, "document_id": source.get("document_id", ""),
                "facts": facts_from_structured(source.get("structured_profile")) or (json.loads(row["facts"]) if row else []),
                "profile_status": row["profile_status"] if row else "pending",
                "profile_error": row["profile_error"] if row else "",
                "warnings": metadata.get("warnings", [])}

    def read(self, owner, source, *, extract_profile=True):
        fingerprint = self.fingerprint(source)
        with self.guard:
            ready = self.read_ready.setdefault((owner, fingerprint), threading.Event())
        try:
            document = self._read_text(owner, source)
        finally:
            # Text becomes usable before the separate profile model call finishes.
            ready.set()
        if extract_profile:
            self._profile(owner, fingerprint, source, document["markdown"])
        return document

    def _read_text(self, owner, source):
        fingerprint = self.fingerprint(source)
        if not fingerprint:
            raise ValueError("当前简历文件不存在，请重新上传。")
        key = owner, fingerprint
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            if not self.is_current(owner, fingerprint):
                raise ValueError("简历已更换或移除，请使用当前简历重试。")
            row = self.repository.get(owner, fingerprint)
            if row and row["status"] == "ready":
                return {**json.loads(row["metadata"]), "markdown": row["content"]}
            self.repository.save(owner, fingerprint, status="reading", source=source)
            try:
                document = {"status": "ok", "markdown": source["text"]} if source.get("text") else self.reader(source["path"])
                text = str(document.get("markdown") or "").strip()
                if document.get("status") not in {"ok", "partial"} or not text:
                    raise ValueError("文档工具未返回有效正文，请检查文件和 OCR 配置。")
                if len(text) > 100000:
                    raise ValueError("简历正文过长，请上传精简后的简历。")
                metadata = {key: document[key] for key in ("status", "warnings", "processed_pages", "total_pages") if key in document}
                if not self.is_current(owner, fingerprint):
                    raise ValueError("简历已更换或移除，请使用当前简历重试。")
                self.repository.save(owner, fingerprint, status="ready", content=text, metadata=metadata, source=source)
                return {**metadata, "markdown": text}
            except Exception:
                if self.is_current(owner, fingerprint):
                    self.repository.save(owner, fingerprint, status="failed", error="简历读取未完成，请检查文件或 OCR 配置后重试。")
                raise

    def start(self, owner, source, *, retry=False, extract_profile=True):
        fingerprint = self.fingerprint(source)
        if not fingerprint:
            raise ValueError("请先在工作台上传简历。")
        key = owner, fingerprint, extract_profile
        read_key = owner, fingerprint
        with self.guard:
            if key in self.tasks and self.tasks[key].is_alive():
                return
            row = self.repository.get(owner, fingerprint)
            if row and not retry and (row["status"] == "failed" or
                    row["status"] == "ready" and (not extract_profile or row["profile_status"] in {"ready", "failed"})):
                return
            if row and retry and row["profile_status"] == "failed":
                self.repository.save_profile(owner, fingerprint, status="pending")
            self.read_ready.setdefault(read_key, threading.Event()).clear()
            def work():
                try:
                    self.read(owner, source, extract_profile=extract_profile)
                except Exception:
                    pass  # The source status exposes a sanitized failure message.
                finally:
                    with self.guard:
                        self.tasks.pop(key, None)
            task = threading.Thread(target=work, name="assistant-resume", daemon=True)
            self.tasks[key] = task
            task.start()

    def prepare(self, owner, source, *, wait_seconds=0, extract_profile=False):
        """Warm the source; optionally wait for text, never for profile extraction."""
        self.start(owner, source, extract_profile=extract_profile)
        key = owner, self.fingerprint(source)
        with self.guard:
            ready = self.read_ready.get(key)
        if ready and wait_seconds > 0:
            ready.wait(wait_seconds)
