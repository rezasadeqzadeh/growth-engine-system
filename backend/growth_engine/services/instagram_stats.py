"""The latest statistics of a workspace's connected Instagram account.

Profile and recent posts always come back; the account totals need the
insights permission and a page Instagram has enough data for, so a refusal
there leaves `period` empty with a reason instead of failing the page.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..errors import AppError
from ..models import Channel, Workspace
from . import instagram_api

logger = logging.getLogger(__name__)
PERIOD_DAYS = 28
RECENT_POSTS = 12


def _channel(s: Session, ws: Workspace) -> Channel:
    c = s.scalar(select(Channel).where(Channel.workspace_id == ws.id, Channel.type == "instagram", Channel.enabled))
    if c is None or not (c.credentials or {}).get("access_token") or not (c.config or {}).get("ig_user_id"):
        raise AppError("instagram_not_connected", "Connect Instagram first", 409)
    return c


async def latest(s: Session, ws: Workspace) -> dict:
    c = _channel(s, ws)
    token, user_id = c.credentials["access_token"], c.config["ig_user_id"]
    try:
        prof = await instagram_api.profile(token)
        media = await instagram_api.recent_media(token, RECENT_POSTS)
    except instagram_api.InstagramAuthExpired as exc:
        raise AppError("instagram_token_expired", "Reconnect Instagram", 409) from exc
    except instagram_api.InstagramError as exc:
        raise AppError("instagram_unreachable", str(exc), 502) from exc

    until = db.utcnow()
    period: dict[str, int] = {}
    period_error = None
    try:
        period = await instagram_api.account_insights(token, user_id, int((until - timedelta(days=PERIOD_DAYS)).timestamp()),
                                                      int(until.timestamp()))
    except instagram_api.InstagramError as exc:
        logger.info("instagram account insights unavailable for %s: %s", ws.id, exc)
        period_error = "insights_unavailable"

    followers = prof.get("followers_count")
    posts = [{"id": m.get("id"), "type": m.get("media_type"), "caption": (m.get("caption") or "")[:140],
              "at": m.get("timestamp"), "likes": m.get("like_count") or 0, "comments": m.get("comments_count") or 0,
              "url": m.get("permalink")} for m in media]
    rate = None
    if followers and posts:
        rate = round(sum(p["likes"] + p["comments"] for p in posts) / len(posts) / followers * 100, 2)
    c.config = {**c.config, "username": prof.get("username"), "followers": followers}  # keep the channel card fresh
    return {"username": prof.get("username"), "account_type": prof.get("account_type"), "followers": followers,
            "media_count": prof.get("media_count"), "engagement_rate": rate, "period_days": PERIOD_DAYS,
            "period": period, "period_error": period_error, "posts": posts, "fetched_at": until.isoformat()}
