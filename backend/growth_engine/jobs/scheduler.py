"""The scheduler: puts periodic jobs on the queue, once per period.

`python -m growth_engine.jobs.scheduler` (one process). Publishing at a
time needs nothing here: a publish job simply carries its run_at.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import jdatetime
from sqlalchemy import select

from .. import db
from ..models import Workspace
from ..services.timing import TEHRAN
from . import queue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Periodic:
    kind: str
    per_workspace: bool
    # The period key when the job is due at local time `local`, else None.
    due: Callable[[datetime], str | None]


def _every_minutes(n: int):
    return lambda local: local.strftime("%Y%m%d%H") + f"{local.minute // n:02d}"


def _daily_at(hour: int):
    return lambda local: local.strftime("%Y%m%d") if local.hour >= hour else None


def _weekly_saturday_at(hour: int):
    # Python: Monday=0 ... Saturday=5; the Iranian week starts on Saturday.
    return lambda local: local.strftime("%G%V") if local.weekday() == 5 and local.hour >= hour else None


def _monthly_jalali_day(day: int):
    def due(local: datetime):
        j = jdatetime.date.fromgregorian(date=local.date())
        return f"{j.year}{j.month:02d}" if j.day >= day else None
    return due


PERIODIC = (
    Periodic("auto_approve", False, _every_minutes(10)),
    Periodic("collect_comments", True, _every_minutes(60)),
    Periodic("send_content_requests", True, _daily_at(10)),
    Periodic("channel_health", False, _daily_at(6)),
    Periodic("learn_best_hour", False, _daily_at(4)),
    Periodic("refresh_instagram_tokens", False, _daily_at(3)),
    Periodic("weekly_report", True, _weekly_saturday_at(9)),
    Periodic("generate_calendar", True, _monthly_jalali_day(25)),
)


def tick(now: datetime | None = None) -> int:
    """Enqueue whatever is due; returns how many jobs were added."""
    local = (now or db.utcnow()).astimezone(TEHRAN)
    added = 0
    with db.session_scope() as s:
        workspace_ids = list(s.scalars(select(Workspace.id)))
        for job in PERIODIC:
            period = job.due(local)
            if period is None:
                continue
            targets = workspace_ids if job.per_workspace else [None]
            for ws_id in targets:
                key = f"periodic:{job.kind}:{ws_id or '-'}:{period}"
                payload = {"workspace_id": ws_id} if ws_id else {}
                if queue.enqueue(s, job.kind, payload, dedupe_key=key, once=True, max_attempts=1):
                    added += 1
    return added


async def run_forever(interval_s: int = 60) -> None:
    while True:
        try:
            tick()
        except Exception:  # noqa: BLE001 - the scheduler must keep ticking
            logger.exception("[scheduler] tick failed")
        await asyncio.sleep(interval_s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
