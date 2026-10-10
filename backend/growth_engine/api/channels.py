"""Channels. Credentials go in and are never sent back out: the panel only
learns whether a secret is set."""

import secrets
import time

import jwt
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..auth.deps import Access, access
from ..bots.api import BotApi, BotApiError
from ..channels.aparat import hash_password
from ..channels.registry import adapter
from ..config import get_settings
from ..db import get_session
from ..errors import AppError, NotFound
from ..models import CHANNEL_TYPES, Channel
from ..redact import redact
from ..services import instagram_api

router = APIRouter(tags=["channels"])

# What each type accepts: (config keys, credential keys).
FIELDS = {
    "bale": (("chat_id", "username", "raw_chat_id"), ("bot_token",)),
    "telegram": (("chat_id", "username", "raw_chat_id", "discussion_chat_id"), ("bot_token",)),
    "eitaa": (("chat_id",), ("token",)),
    "rubika": (("chat_id",), ("token",)),
    "aparat": (("category",), ("username", "password")),
    "instagram": (("mode",), ()),
    "site": ((), ()),
}
STATE_TTL_S = 600


class ChannelIn(BaseModel):
    type: str
    name: str = ""
    config: dict = {}
    credentials: dict = {}
    enabled: bool = True


def channel_out(c: Channel) -> dict:
    caps = adapter(c.type).capabilities()
    return {"id": c.id, "type": c.type, "name": c.name, "config": c.config, "enabled": c.enabled,
            "secrets_set": sorted(k for k, v in (c.credentials or {}).items() if v and k != "webhook_secret"),
            "health_ok": c.health_ok, "health_error": c.health_error,
            "health_checked_at": c.health_checked_at.isoformat() if c.health_checked_at else None,
            "capabilities": {"auto_publish": caps.auto_publish, "metrics": caps.metrics, "comments": caps.comments,
                             "max_video_mb": caps.max_video_mb}}


def _apply(c: Channel, body: ChannelIn) -> None:
    config_keys, secret_keys = FIELDS[c.type]
    c.name = body.name or c.name
    c.enabled = body.enabled
    c.config = {**(c.config or {}), **{k: v for k, v in body.config.items() if k in config_keys}}
    creds = dict(c.credentials or {})
    for key in secret_keys:
        value = body.credentials.get(key)
        if not value:
            continue  # an empty field keeps the stored secret
        if c.type == "aparat" and key == "password":
            creds["lpass"] = hash_password(value)  # Aparat's login takes this hash, never the password
        else:
            creds[key] = value
    c.credentials = creds


async def _register_webhook(c: Channel) -> None:
    """Point the bot's webhook at us (Bale and Telegram)."""
    creds = dict(c.credentials or {})
    creds.setdefault("webhook_secret", secrets.token_urlsafe(24))
    c.credentials = creds
    url = f"{get_settings().public_base_url}/bots/{c.id}/{creds['webhook_secret']}"
    api = BotApi(c.type, creds["bot_token"])
    try:
        await api.get_me()
    except BotApiError as exc:
        raise AppError("bot_token_invalid", redact(exc, c.secrets()), 400) from None
    settings = get_settings()
    if settings.is_development and not settings.public_base_url.startswith("https://"):
        return  # local run without a public URL: `python -m growth_engine.bots.poll` takes the updates
    try:
        await api.set_webhook(url, creds["webhook_secret"])
    except BotApiError as exc:
        raise AppError("bot_webhook_failed", redact(exc, c.secrets()), 400) from None


def _get(s: Session, a: Access, channel_id: str) -> Channel:
    c = s.get(Channel, channel_id)
    if c is None or c.workspace_id != a.workspace.id:
        raise NotFound("channel")
    return c


@router.get("/workspaces/{workspace_id}/channels")
def list_channels(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Channel).where(Channel.workspace_id == a.workspace.id).order_by(Channel.type))
    return {"channels": [channel_out(c) for c in rows]}


@router.post("/workspaces/{workspace_id}/channels")
async def create_channel(body: ChannelIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if body.type not in CHANNEL_TYPES or body.type == "site":
        raise AppError("channel_type_invalid", "Unknown channel type")
    c = Channel(workspace_id=a.workspace.id, type=body.type)
    _apply(c, body)
    s.add(c)
    s.flush()
    if c.type in ("bale", "telegram") and c.credentials.get("bot_token"):
        await _register_webhook(c)
    return channel_out(c)


@router.patch("/workspaces/{workspace_id}/channels/{channel_id}")
async def update_channel(channel_id: str, body: ChannelIn, a: Access = Depends(access),
                         s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    c = _get(s, a, channel_id)
    old_token = (c.credentials or {}).get("bot_token")
    body.type = c.type
    _apply(c, body)
    if c.type in ("bale", "telegram") and c.credentials.get("bot_token") != old_token:
        await _register_webhook(c)
    return channel_out(c)


@router.delete("/workspaces/{workspace_id}/channels/{channel_id}")
def delete_channel(channel_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    c = _get(s, a, channel_id)
    if c.type == "site":
        raise AppError("site_channel_required", "The site channel cannot be removed")
    c.enabled = False  # publications keep pointing at it; it is only switched off
    c.credentials = {}
    return {"ok": True}


@router.post("/workspaces/{workspace_id}/channels/{channel_id}/test")
async def test_channel(channel_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    c = _get(s, a, channel_id)
    try:
        await adapter(c.type).health(c)
        c.health_ok, c.health_error = True, None
    except Exception as exc:  # noqa: BLE001 - the error is the answer
        c.health_ok, c.health_error = False, redact(exc, c.secrets())[:300]
    c.health_checked_at = db.utcnow()
    return channel_out(c)


# Instagram: connect through Instagram Login; the redirect URI is fixed, so
# the channel travels in a signed state.

@router.post("/workspaces/{workspace_id}/channels/instagram/connect")
def instagram_connect(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if not instagram_api.is_configured():
        raise AppError("instagram_not_configured", "Instagram login is not configured", 503)
    c = s.scalar(select(Channel).where(Channel.workspace_id == a.workspace.id, Channel.type == "instagram"))
    if c is None:
        c = Channel(workspace_id=a.workspace.id, type="instagram", name="Instagram", config={"mode": "api"})
        s.add(c)
        s.flush()
    state = jwt.encode({"purpose": "ig_oauth", "channel": c.id, "nonce": secrets.token_hex(8),
                        "exp": int(time.time()) + STATE_TTL_S}, get_settings().jwt_secret, algorithm="HS256")
    return {"authorize_url": instagram_api.authorize_url(state)}


@router.get("/instagram/callback")
async def instagram_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                             s: Session = Depends(get_session)) -> RedirectResponse:
    panel = get_settings().panel_url
    if error or not code or not state:
        return RedirectResponse(f"{panel}/?instagram=failed")
    try:
        claims = jwt.decode(state, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return RedirectResponse(f"{panel}/?instagram=failed")
    c = s.get(Channel, claims.get("channel", "")) if claims.get("purpose") == "ig_oauth" else None
    if c is None:
        return RedirectResponse(f"{panel}/?instagram=failed")
    try:
        token = await instagram_api.exchange_code(code)
        profile = await instagram_api.profile(token["access_token"])
    except instagram_api.InstagramError:
        return RedirectResponse(f"{panel}/w/{c.workspace_id}/channels?instagram=failed")
    c.credentials = {"access_token": token["access_token"],
                     "expires_at": str(int(db.utcnow().timestamp()) + token["expires_in"])}
    c.config = {**(c.config or {}), "ig_user_id": str(profile.get("user_id") or profile.get("id") or token["user_id"]),
                "username": profile.get("username"), "followers": profile.get("followers_count"), "mode": "api"}
    c.name, c.enabled = f"@{profile.get('username', '')}", True
    return RedirectResponse(f"{panel}/w/{c.workspace_id}/channels?instagram=connected")
