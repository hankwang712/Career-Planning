"""A job table that survives restarts.

Report and resume jobs used to live only in module-level dicts, so a restart made a running task vanish
and left the user's saved state saying "running" forever. `JobRegistry` is a drop-in dict: every
assignment is written through to SQLite, and `restore()` brings recent jobs back after a restart, turning
anything that was still queued or running into a clear "interrupted" failure.
"""
import time

from . import db

ACTIVE = {"queued", "running"}
INTERRUPTED_MESSAGE = "服务重启，本次任务被中断，请重新发起。"
KEEP_SECONDS = 7 * 86400


class JobRegistry(dict):
    def __init__(self, kind, *, throttle=2.0):
        super().__init__()
        self.kind = kind
        self.throttle = throttle
        self._written = {}  # job_id -> (status, monotonic time) of the last write

    def __setitem__(self, job_id, job):
        super().__setitem__(job_id, job)
        self._persist(job_id, job)

    def pop(self, job_id, *default):
        self._written.pop(job_id, None)
        job = super().pop(job_id, *default)
        db.delete_job(job_id)
        return job

    def touch(self, job_id):
        """Persist now, for code that edits a job dict in place without reassigning it."""
        job = self.get(job_id)
        if isinstance(job, dict):
            self._persist(job_id, job, force=True)

    def _persist(self, job_id, job, force=False):
        if not isinstance(job, dict):
            return
        status = str(job.get("status") or "")
        last = self._written.get(job_id)
        now = time.monotonic()
        # Progress updates arrive many times a second; only status changes are written immediately.
        if not force and last and last[0] == status and now - last[1] < self.throttle:
            return
        self._written[job_id] = (status, now)
        db.save_job(job_id, self.kind, str(job.get("username") or ""), status, job)

    def restore(self):
        """Reload recent jobs. Returns the jobs that were interrupted by the restart."""
        interrupted = []
        for job in db.load_jobs(self.kind, time.time() - KEEP_SECONDS):
            if str(job.get("status") or "") in ACTIVE:
                now = int(time.time())
                job.update(status="failed", finished_at=now, message=INTERRUPTED_MESSAGE,
                           stage_detail=INTERRUPTED_MESSAGE, cancel_requested=False)
                db.save_job(job["job_id"], self.kind, str(job.get("username") or ""), "failed", job)
                interrupted.append(dict(job))
            dict.__setitem__(self, job["job_id"], job)
        db.prune_jobs(time.time() - KEEP_SECONDS)
        return interrupted
