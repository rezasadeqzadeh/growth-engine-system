"""The worker as it is started: `python -m growth_engine.jobs.runner` (a second copy of the module)."""

import runpy

from sqlalchemy import select

from growth_engine import db
from growth_engine.jobs import queue
from growth_engine.models import Job


async def test_a_worker_started_as_a_script_finds_the_handlers(workspace):
    with db.session_scope() as s:
        queue.enqueue(s, "process_video", {"post_id": "missing"})  # the handler returns at once for an unknown post
    script = runpy.run_module("growth_engine.jobs.runner", run_name="as_script")  # what -m loads beside the package
    assert await script["run_one"]("media")
    with db.session_scope() as s:
        job = s.scalar(select(Job))
        assert (job.status, job.last_error) == ("done", None)
