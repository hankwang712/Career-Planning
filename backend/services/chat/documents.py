"""Cache the existing document reader's result per account and file content."""

from hashlib import sha256
import json
from pathlib import Path
import re
import threading


def redact_contacts(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", str(text or ""))
    text = re.sub(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)", "[电话已隐藏]", text)
    return re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[证件号码已隐藏]", text)


class ResumeDocuments:
    def __init__(self, store, reader=None, current_source=None):
        self.store = store
        self.reader = reader or self.read_document
        self.guard = threading.Lock()
        self.locks = {}
        self.tasks = {}
        self.current_source = current_source

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
        row = self.store.document(owner, fingerprint)
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
                "warnings": metadata.get("warnings", [])}

    def read(self, owner, source):
        fingerprint = self.fingerprint(source)
        if not fingerprint:
            raise ValueError("当前简历文件不存在，请重新上传。")
        key = owner, fingerprint
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            if not self.is_current(owner, fingerprint):
                raise ValueError("简历已更换或移除，请使用当前简历重试。")
            row = self.store.document(owner, fingerprint)
            if row and row["status"] == "ready":
                return {**json.loads(row["metadata"]), "markdown": row["content"]}
            self.store.save_document(owner, fingerprint, status="reading")
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
                self.store.save_document(owner, fingerprint, status="ready", content=text, metadata=metadata)
                return {**metadata, "markdown": text}
            except Exception:
                if self.is_current(owner, fingerprint):
                    self.store.save_document(owner, fingerprint, status="failed", error="简历读取未完成，请检查文件或 OCR 配置后重试。")
                raise

    def start(self, owner, source):
        fingerprint = self.fingerprint(source)
        if not fingerprint:
            raise ValueError("请先在工作台上传简历。")
        key = owner, fingerprint
        with self.guard:
            if key in self.tasks and self.tasks[key].is_alive():
                return
            def work():
                try:
                    self.read(owner, source)
                except Exception:
                    pass  # The source status exposes a sanitized failure message.
                finally:
                    with self.guard:
                        self.tasks.pop(key, None)
            task = threading.Thread(target=work, name="assistant-resume", daemon=True)
            self.tasks[key] = task
            task.start()
