"""Platform admin: the job queue at a glance, and retrying a failed job."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..auth.deps import current_user
from ..auth.otp import is_superadmin
from ..db import get_session
from ..errors import Forbidden, NotFound
from ..models import Job, User

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(user: User) -> None:
    if not is_superadmin(user):
        raise Forbidden("superadmin_required", "Only a platform admin can see this")


@router.get("/jobs")
def jobs(status: str = "failed", user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    _require_admin(user)
    counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    rows = s.scalars(select(Job).where(Job.status == status).order_by(Job.created_at.desc()).limit(100))
    # last_error was redacted when it was recorded (jobs/runner.py).
    return {"counts": counts, "jobs": [{"id": j.id, "kind": j.kind, "queue": j.queue, "status": j.status,
                                        "attempts": j.attempts, "error": j.last_error,
                                        "created_at": j.created_at.isoformat()} for j in rows]}


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    _require_admin(user)
    job = s.get(Job, job_id)
    if job is None:
        raise NotFound("job")
    job.status, job.attempts, job.run_at, job.last_error = "queued", 0, db.utcnow(), None
    return {"ok": True}
