"""Webhook endpoint for every workspace bot: /bots/<channel_id>/<secret>."""

import hmac
import logging

from fastapi import APIRouter, Request

from .. import db
from ..models import Channel
from . import gateway

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bots"])


@router.post("/bots/{channel_id}/{secret}")
async def receive(channel_id: str, secret: str, request: Request) -> dict:
    with db.session_scope() as s:
        channel = s.get(Channel, channel_id)
        expected = ((channel.credentials or {}).get("webhook_secret") if channel else None) or ""
    if not expected or not hmac.compare_digest(expected, secret):
        return {"ok": False}
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if header is not None and not hmac.compare_digest(header, expected):
        return {"ok": False}
    try:
        update = await request.json()
    except ValueError:
        return {"ok": False}
    try:
        await gateway.handle_update(channel_id, update)
    except Exception:  # noqa: BLE001 - answer 200 so the platform does not retry a broken update forever
        logger.exception("[bot] update failed for channel %s", channel_id)
    return {"ok": True}
