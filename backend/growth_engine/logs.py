"""Logging: one format for every process, and one line per HTTP request.

Request lines carry method, path, status, duration and the browser's
Origin, never the query string or body (they can hold codes, tokens and
signed-URL signatures). A refused CORS preflight says which origin was
refused and how to allow it.
"""

import logging
import time

from fastapi import Request

from .config import get_settings

logger = logging.getLogger("growth_engine.http")


def setup() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", force=True)
    # Request lines come from our middleware; uvicorn's access log would repeat them.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # httpx logs every request URL; Telegram/Bale URLs carry the bot token. Our own lines say what was called.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def log_requests(request: Request, call_next):
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("%s %s -> unhandled error", request.method, request.url.path)
        raise
    ms = (time.monotonic() - started) * 1000
    origin = request.headers.get("origin", "-")
    line = "%s %s -> %s (%.0f ms) origin=%s"
    args = (request.method, request.url.path, response.status_code, ms, origin)
    if request.method == "OPTIONS" and response.status_code == 400:
        logger.warning(line + " | CORS refused this origin: add it to CORS_ORIGINS or set PANEL_URL", *args)
    elif response.status_code >= 500:
        logger.error(line, *args)
    elif response.status_code >= 400:
        logger.warning(line, *args)
    else:
        logger.info(line, *args)
    return response
