"""Persistent job queue (SQLite) with one worker thread per lane.

Lanes: "transfer" (download/upload) and "gpu" (preview/process) run in parallel; within a lane jobs run one
at a time in creation order. A job with depends_on waits until that job is done, and fails if it failed.
"""

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from remastr.ftp import TransferCancelled
from remastr.models import Job, JobStatus, JobType
from remastr.pipeline import Cancelled

log = logging.getLogger(__name__)

LANES: dict[str, tuple[JobType, ...]] = {
    "transfer": (JobType.download, JobType.upload),
    "gpu": (JobType.preview, JobType.process),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    rating_key TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL DEFAULT '{}',
    depends_on INTEGER REFERENCES jobs(id),
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    @staticmethod
    def _to_job(row: sqlite3.Row) -> Job:
        d = dict(row)
        d["params"] = json.loads(d["params"])
        d["result"] = json.loads(d["result"])
        return Job.model_validate(d)

    def create(
        self,
        type: JobType,
        rating_key: str,
        title: str = "",
        params: dict[str, Any] | None = None,
        depends_on: int | None = None,
    ) -> Job:
        now = _now()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO jobs (type, status, rating_key, title, params, depends_on, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (type, JobStatus.queued, rating_key, title, json.dumps(params or {}), depends_on, now, now),
            )
            job_id = cur.lastrowid
        assert job_id is not None
        return self.get(job_id)

    def get(self, job_id: int) -> Job:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return self._to_job(row)

    def list(self, limit: int = 100, rating_key: str | None = None, active_only: bool = False) -> list[Job]:
        sql, args = "SELECT * FROM jobs WHERE 1=1", []
        if rating_key:
            sql += " AND rating_key = ?"
            args.append(rating_key)
        if active_only:
            sql += " AND status IN ('queued', 'running')"
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [self._to_job(r) for r in rows]

    def update(self, job_id: int, **fields: Any) -> None:
        for key in ("params", "result"):
            if key in fields:
                fields[key] = json.dumps(fields[key])
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._db.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def claim_next(self, types: tuple[JobType, ...]) -> Job | None:
        """Atomically pick the oldest runnable queued job of the given types and mark it running."""
        marks = ",".join("?" * len(types))
        with self._lock:
            # Jobs whose dependency failed can never run
            self._db.execute(
                f"UPDATE jobs SET status = 'failed', message = 'Dependency failed or was cancelled', updated_at = ?"
                f" WHERE status = 'queued' AND type IN ({marks}) AND depends_on IN"
                f" (SELECT id FROM jobs WHERE status IN ('failed', 'cancelled'))",
                (_now(), *types),
            )
            row = self._db.execute(
                f"SELECT * FROM jobs WHERE status = 'queued' AND type IN ({marks})"
                f" AND (depends_on IS NULL OR depends_on IN (SELECT id FROM jobs WHERE status = 'done'))"
                f" ORDER BY id LIMIT 1",
                types,
            ).fetchone()
            if row is None:
                return None
            self._db.execute("UPDATE jobs SET status = 'running', updated_at = ? WHERE id = ?", (_now(), row["id"]))
        return self.get(row["id"])

    def mark_interrupted(self) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE jobs SET status = 'failed', message = 'Interrupted by restart', updated_at = ?"
                " WHERE status = 'running'",
                (_now(),),
            )


@dataclass
class JobContext:
    job: Job
    store: JobStore
    cancel: threading.Event = field(default_factory=threading.Event)
    _last_write: float = 0.0

    def progress(self, fraction: float, message: str = "") -> None:
        """Throttled progress update (at most ~2 writes/second)."""
        now = time.monotonic()
        if now - self._last_write < 0.5 and fraction < 1.0:
            return
        self._last_write = now
        self.store.update(self.job.id, progress=round(max(0.0, min(fraction, 1.0)), 4), message=message)


Handler = Callable[[JobContext], dict[str, Any] | None]


class JobRunner:
    def __init__(self, store: JobStore, handlers: dict[JobType, Handler]):
        self.store = store
        self._handlers = handlers
        self._wake = threading.Condition()
        self._stop = threading.Event()
        self._running: dict[int, JobContext] = {}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.store.mark_interrupted()
        for lane, types in LANES.items():
            t = threading.Thread(target=self._loop, args=(types,), name=f"jobs-{lane}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for ctx in list(self._running.values()):
            ctx.cancel.set()
        self.notify()
        for t in self._threads:
            t.join(timeout=10)

    def notify(self) -> None:
        with self._wake:
            self._wake.notify_all()

    def submit(
        self,
        type: JobType,
        rating_key: str,
        title: str = "",
        params: dict[str, Any] | None = None,
        depends_on: int | None = None,
    ) -> Job:
        job = self.store.create(type, rating_key, title, params, depends_on)
        self.notify()
        return job

    def cancel(self, job_id: int) -> Job:
        job = self.store.get(job_id)
        if job.status == JobStatus.queued:
            self.store.update(job_id, status=JobStatus.cancelled, message="Cancelled")
        elif job.status == JobStatus.running and job_id in self._running:
            self._running[job_id].cancel.set()
        return self.store.get(job_id)

    def _loop(self, types: tuple[JobType, ...]) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next(types)
            if job is None:
                with self._wake:
                    self._wake.wait(timeout=2)
                continue
            self._execute(job)
            self.notify()  # dependents in the other lane may be runnable now

    def _execute(self, job: Job) -> None:
        ctx = JobContext(job=job, store=self.store)
        self._running[job.id] = ctx
        try:
            result = self._handlers[job.type](ctx) or {}
            self.store.update(
                job.id, status=JobStatus.done, progress=1.0, result=result, message=result.get("message", "Done")
            )
        except (Cancelled, TransferCancelled):
            self.store.update(job.id, status=JobStatus.cancelled, message="Cancelled")
        except Exception as e:
            log.exception("Job %s failed", job.id)
            self.store.update(job.id, status=JobStatus.failed, message=f"{type(e).__name__}: {e}")
        finally:
            self._running.pop(job.id, None)
