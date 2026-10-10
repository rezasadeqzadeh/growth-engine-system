"""A job queue in the database.

The work is minutes of FFmpeg/Whisper/LLM time per item at a few items an
hour per workspace, so the queue lives next to the data it changes: a job
and the rows it creates commit together, and there is no second store to
lose jobs in. Postgres claims with FOR UPDATE SKIP LOCKED, so several
workers (and the media worker on its own server) never take the same job.
"""

from datetime import datetime, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from .. import db
from ..models import Job

# A running job whose worker died is taken again after this long.
STALE_AFTER = timedelta(minutes=30)
MEDIA_KINDS = {"process_video", "transcribe_voice"}
# Jobs that call Meta's Graph API share one platform token, so they run one at a time.
META_KINDS = {"fetch_competitor"}
SINGLE_FLIGHT = {"meta"}
SINGLE_FLIGHT_LOCK = 0x6D65_7461  # Postgres advisory lock for claiming single-flight queues


def queue_for(kind: str) -> str:
    if kind in MEDIA_KINDS:
        return "media"
    if kind in META_KINDS:
        return "meta"
    return "default"


def enqueue(s: Session, kind: str, payload: dict | None = None, *, run_at: datetime | None = None,
            dedupe_key: str | None = None, max_attempts: int = 3, once: bool = False) -> Job | None:
    """`dedupe_key` skips the enqueue while the same work is queued or running;
    with `once`, also when it already ran (periodic jobs: once per period)."""
    if dedupe_key:
        q = select(Job.id).where(Job.dedupe_key == dedupe_key)
        if not once:
            q = q.where(Job.status.in_(("queued", "running")))
        if s.scalar(q.limit(1)):
            return None
    job = Job(kind=kind, payload=payload or {}, queue=queue_for(kind),
              run_at=run_at or db.utcnow(), dedupe_key=dedupe_key, max_attempts=max_attempts)
    s.add(job)
    s.flush()
    return job


def claim(queue: str) -> Job | None:
    now = db.utcnow()
    with db.session_scope() as s:
        if queue in SINGLE_FLIGHT:
            if s.get_bind().dialect.name == "postgresql":
                # Held to commit: two workers cannot both see "nothing running".
                s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SINGLE_FLIGHT_LOCK})
            if s.scalar(select(Job.id).where(Job.queue == queue, Job.status == "running",
                                             Job.locked_at >= now - STALE_AFTER).limit(1)):
                return None
        job = s.scalar(
            select(Job)
            .where(Job.queue == queue, Job.run_at <= now,
                   or_(Job.status == "queued", (Job.status == "running") & (Job.locked_at < now - STALE_AFTER)))
            .order_by(Job.run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        job.status, job.locked_at, job.attempts = "running", now, job.attempts + 1
        s.flush()
        s.expunge(job)
        return job


def finish(job_id: str) -> None:
    with db.session_scope() as s:
        job = s.get(Job, job_id)
        if job:
            job.status, job.finished_at = "done", db.utcnow()


def fail(job_id: str, error: str, *, retry: bool = True) -> bool:
    """Record a failure. Returns True when the job will be retried."""
    with db.session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return False
        job.last_error = error[:2000]
        if retry and job.attempts < job.max_attempts:
            job.status = "queued"
            job.run_at = db.utcnow() + timedelta(seconds=30 * 2 ** job.attempts)
            return True
        job.status, job.finished_at = "failed", db.utcnow()
        return False
