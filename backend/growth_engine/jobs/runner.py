"""Worker: claims jobs and runs their handlers.

`python -m growth_engine.jobs.runner default` runs the main worker;
`... media` runs the media worker (FFmpeg + Whisper) on the media server.
"""

import asyncio
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..errors import AppError
from ..redact import redact
from . import queue

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class PermanentError(Exception):
    """Retrying cannot help (bad input, missing file)."""


@dataclass
class Registered:
    run: Handler
    on_final_failure: Callable[[dict, str], None] | None


HANDLERS: dict[str, Registered] = {}


def handler(kind: str, on_final_failure: Callable[[dict, str], None] | None = None):
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = Registered(fn, on_final_failure)
        return fn
    return wrap


def _load_handlers() -> dict[str, Registered]:
    """The registry the handlers filled. `python -m growth_engine.jobs.runner` runs this file as
    `__main__`, a second copy of the module; tasks.py registers into `growth_engine.jobs.runner`,
    so the copy must read that module's HANDLERS, not its own (every job failed "No handler")."""
    from . import runner, tasks  # noqa: F401  (tasks registers every handler)
    return runner.HANDLERS


async def run_one(queue_name: str = "default") -> bool:
    """Run the next due job. Returns False when there was none."""
    handlers = _load_handlers()
    job = queue.claim(queue_name)
    if job is None:
        return False
    reg = handlers.get(job.kind)
    if reg is None:
        logger.error("[job] %s %s failed: no handler registered for this kind", job.kind, job.id)
        queue.fail(job.id, f"No handler for {job.kind}", retry=False)
        return True
    started = time.monotonic()
    logger.info("[job] start %s %s (attempt %d/%d) payload=%s", job.kind, job.id, job.attempts, job.max_attempts,
                redact(job.payload))
    try:
        await reg.run(job.payload)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded on the job
        permanent = isinstance(exc, PermanentError) or (isinstance(exc, AppError) and exc.status < 500)
        message = redact(f"{type(exc).__name__}: {exc}")
        logger.exception("[job] %s %s failed", job.kind, job.id)
        retried = queue.fail(job.id, message, retry=not permanent)
        logger.warning("[job] %s %s failed after %.1fs: %s -> %s", job.kind, job.id, time.monotonic() - started,
                       message, "will retry" if retried else "gave up")
        if not retried and reg.on_final_failure:
            reg.on_final_failure(job.payload, message)
    else:
        queue.finish(job.id)
        logger.info("[job] done %s %s in %.1fs", job.kind, job.id, time.monotonic() - started)
    return True


async def run_forever(queue_name: str, idle_sleep: float = 2.0) -> None:
    while True:
        try:
            ran = await run_one(queue_name)
        except Exception:  # noqa: BLE001 - the loop must survive a DB hiccup
            logger.exception("[worker] loop error")
            ran = False
        if not ran:
            await asyncio.sleep(idle_sleep)


if __name__ == "__main__":
    from ..logs import setup

    setup()  # timestamps and LOG_LEVEL, as in the API
    name = sys.argv[1] if len(sys.argv) > 1 else "default"
    logger.info("[worker] %s queue: waiting for jobs", name)
    asyncio.run(run_forever(name))
