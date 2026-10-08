"""Periodic upkeep: auto-approvals, adapter health, token refresh, learning
the best hour, next month's calendar."""

import logging
from datetime import timedelta

import jdatetime
from sqlalchemy import select

from .. import db
from ..channels.registry import adapter
from ..models import Channel, Workspace
from ..redact import redact
from . import calendar, instagram_api, metrics
from . import posts as post_service
from .timing import TEHRAN

logger = logging.getLogger(__name__)
TOKEN_REFRESH_BEFORE = timedelta(days=15)


async def auto_approve(payload: dict) -> None:
    """Low-risk tags whose owner consented: published after 24 hours without an answer."""
    with db.session_scope() as s:
        for post in post_service.due_auto_approvals(s):
            ws = s.get(Workspace, post.workspace_id)
            if not (ws.settings or {}).get("auto_approve_consent"):
                post.auto_approve_at = None
                continue
            post_service.approve(s, post, None, auto=True)


async def channel_health(payload: dict) -> None:
    """A daily check of every adapter, so a broken API is seen before a post fails."""
    with db.session_scope() as s:
        for channel in s.scalars(select(Channel).where(Channel.enabled)):
            try:
                await adapter(channel.type).health(channel)
                channel.health_ok, channel.health_error = True, None
            except Exception as exc:  # noqa: BLE001 - any failure is the finding
                channel.health_ok, channel.health_error = False, redact(exc, channel.secrets())[:300]
            channel.health_checked_at = db.utcnow()


async def refresh_instagram_tokens(payload: dict) -> None:
    with db.session_scope() as s:
        for channel in s.scalars(select(Channel).where(Channel.type == "instagram", Channel.enabled)):
            creds = dict(channel.credentials or {})
            expires = creds.get("expires_at")
            if not creds.get("access_token") or not expires:
                continue
            if float(expires) - db.utcnow().timestamp() > TOKEN_REFRESH_BEFORE.total_seconds():
                continue
            try:
                fresh = await instagram_api.refresh_token(creds["access_token"])
            except instagram_api.InstagramError as exc:
                logger.warning("[ig] refresh failed for %s: %s", channel.id, exc)
                continue
            creds["access_token"] = fresh["access_token"]
            creds["expires_at"] = str(int(db.utcnow().timestamp()) + int(fresh.get("expires_in", 0)))
            channel.credentials = creds


async def learn_best_hour(payload: dict) -> None:
    with db.session_scope() as s:
        for ws in s.scalars(select(Workspace)):
            hour = metrics.learn_best_hour(s, ws)
            if hour is not None:
                ws.settings = {**(ws.settings or {}), "best_hour": hour}


async def generate_next_month(payload: dict) -> None:
    today = jdatetime.date.fromgregorian(date=db.utcnow().astimezone(TEHRAN).date())
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    with db.session_scope() as s:
        ws = s.get(Workspace, payload["workspace_id"])
        if ws is not None:
            await calendar.generate_month(s, ws, year, month)
