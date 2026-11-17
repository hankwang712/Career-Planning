"""Durable result reuse and local cross-process exclusion for report operations.

The OS releases file locks on process exit. An interrupted ledger row can then
be retried immediately, without an expiring lease allowing two live writers.
Provider execution and our SQLite commit cannot form a single transaction:
a crash after provider completion but before commit can still cost another call.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4


class OperationBusy(ValueError):
    pass


def _semantic(value):
    if isinstance(value, dict):
        # Cached/replayed execution metrics do not change the meaning of inputs.
        is_result = isinstance(value.get("agent"), str) and "status" in value and "data" in value
        return {key: _semantic(item) for key, item in value.items()
                if not (is_result and key == "execution")}
    if isinstance(value, (list, tuple)):
        return [_semantic(item) for item in value]
    return value


def revision(value):
    encoded = json.dumps(_semantic(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationResult:
    result: dict
    operation_id: str
    reused: bool
    attempts: int


class OperationStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_dir = self.path.parent / (self.path.stem + "_locks")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS report_operations (
                operation_id TEXT PRIMARY KEY, scope TEXT NOT NULL, stage TEXT NOT NULL,
                input_revision TEXT NOT NULL, context_revision TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
                owner TEXT NOT NULL, attempts INTEGER NOT NULL,
                result_json TEXT, result_revision TEXT, error_type TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS report_operations_scope ON report_operations(scope, stage)")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _lock(self, identity):
        path = self.lock_dir / (sha256(identity.encode()).hexdigest() + ".lock")
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} and getattr(error, "winerror", None) not in {32, 33}:
                    raise
                raise OperationBusy("此报告或分析步骤正在其他任务中执行，请等待完成后重试") from error
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        # Do not unlink lock files: replacing an inode can defeat a live lock.

    def workflow_lock(self, scope):
        return self._lock("workflow:" + scope)

    @contextmanager
    def _operation(self, scope, stage, payload, context):
        if not scope or not stage:
            raise ValueError("操作必须属于明确的报告实例和阶段")
        input_revision, context_revision = revision(payload), revision(context)
        identity = revision({"scope": scope, "stage": stage, "input_revision": input_revision,
                             "context_revision": context_revision})
        owner = uuid4().hex
        with self._lock("operation:" + identity):
            with self._connection() as connection:
                row = connection.execute("SELECT * FROM report_operations WHERE operation_id=?", (identity,)).fetchone()
                if row and row["status"] == "succeeded":
                    # A damaged success record must not silently trigger another paid request.
                    cached = json.loads(row["result_json"])
                    if not isinstance(cached, dict) or sha256(row["result_json"].encode()).hexdigest() != row["result_revision"]:
                        raise ValueError("报告步骤的已保存结果损坏，请检查操作账本")
                    ticket = OperationResult(cached, identity, True, row["attempts"])
                else:
                    now = time.time()
                    attempts = row["attempts"] + 1 if row else 1
                    connection.execute("""INSERT INTO report_operations VALUES (?,?,?,?,?,'running',?,?,NULL,NULL,NULL,?,?)
                        ON CONFLICT(operation_id) DO UPDATE SET status='running',owner=excluded.owner,
                        attempts=excluded.attempts,result_json=NULL,result_revision=NULL,error_type=NULL,updated_at=excluded.updated_at""",
                        (identity, scope, stage, input_revision, context_revision, owner, attempts, now, now))
                    ticket = OperationResult({}, identity, False, attempts)
            try:
                yield ticket, owner
            except BaseException as error:
                if not ticket.reused:
                    with self._connection() as connection:
                        connection.execute("""UPDATE report_operations SET status='failed',error_type=?,updated_at=?
                            WHERE operation_id=? AND owner=? AND status='running'""",
                            (type(error).__name__, time.time(), identity, owner))
                raise

    def _complete(self, ticket, owner, result, reusable=True):
        if not isinstance(result, dict):
            raise ValueError("报告步骤必须返回结构化结果")
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        with self._connection() as connection:
            changed = connection.execute("""UPDATE report_operations SET status='succeeded',result_json=?,
                result_revision=?,error_type=NULL,updated_at=? WHERE operation_id=? AND owner=? AND status='running'""",
                (encoded, sha256(encoded.encode()).hexdigest(), time.time(), ticket.operation_id, owner)).rowcount
            if changed != 1:
                raise RuntimeError("操作已失去写入权限，未覆盖已保存结果")
            if not reusable:
                connection.execute("""UPDATE report_operations SET status='failed',result_json=NULL,
                    result_revision=NULL,error_type='UncacheableResult' WHERE operation_id=? AND owner=?""",
                    (ticket.operation_id, owner))
        return OperationResult(result, ticket.operation_id, False, ticket.attempts)

    async def call(self, scope, stage, payload, context, operation, *, cache_if=None):
        with self._operation(scope, stage, payload, context) as (ticket, owner):
            if ticket.reused:
                return ticket
            result = await operation()
            return self._complete(ticket, owner, result, cache_if(result) if cache_if else True)

    def call_sync(self, scope, stage, payload, context, operation):
        with self._operation(scope, stage, payload, context) as (ticket, owner):
            if ticket.reused:
                return ticket
            return self._complete(ticket, owner, operation())
