"""Local development without a public URL: long-poll every Telegram/Bale bot
and hand each update to the same gateway the webhook uses.

`python -m growth_engine.bots.poll` (from backend/). It removes the bot's
webhook first (Telegram refuses getUpdates while one is set); saving the
channel in the panel sets it again, so restart this after a save.
"""

import asyncio
import logging

from sqlalchemy import select

from .. import db
from ..config import get_settings
from ..models import Channel
from . import gateway
from .api import BotApi, BotApiError

logger = logging.getLogger(__name__)
ALLOWED = ["message", "channel_post", "callback_query", "message_reaction_count"]


def pick_channel(channels: list[dict], update: dict) -> dict:
    """Several channels may share one bot token (other workspaces in the same database).
    The update belongs to the channel whose raw-content group it came from; else the newest one."""
    chat = gateway._chat_of(update)
    for c in channels:
        if chat and chat == str(c["raw_chat_id"] or ""):
            return c
    return channels[0]


async def poll_token(platform: str, token: str, channels: list[dict]) -> None:
    api = BotApi(platform, token, timeout=70)
    await api.call("deleteWebhook")
    if len(channels) > 1:
        logger.warning("[poll] %d channels share one %s bot token: %s. Updates from a raw-content group go to "
                       "its channel, everything else (private chats, /start) to the newest: %s", len(channels),
                       platform, ", ".join(f"{c['id']} (workspace {c['workspace_id']})" for c in channels),
                       channels[0]["id"])
    logger.info("[poll] %s bot of channel %s (workspace %s): polling", platform, channels[0]["id"],
                channels[0]["workspace_id"])
    offset = None
    while True:
        try:
            updates = await api.call("getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ALLOWED})
        except BotApiError as exc:
            logger.warning("[poll] %s: %s", channels[0]["id"], exc)
            await asyncio.sleep(5)
            continue
        for update in updates if isinstance(updates, list) else []:
            offset = update["update_id"] + 1
            channel = pick_channel(channels, update)
            logger.info("[poll] update %s from chat %s -> channel %s (workspace %s)", update["update_id"],
                        gateway._chat_of(update), channel["id"], channel["workspace_id"])
            try:
                await gateway.handle_update(channel["id"], update)
            except Exception:  # noqa: BLE001 - one broken update must not stop polling
                logger.exception("[poll] update failed for channel %s", channel["id"])


async def main() -> None:
    if not get_settings().is_development:
        raise SystemExit("Polling is for local development only (ENVIRONMENT=development)")
    by_token: dict[tuple[str, str], list[dict]] = {}
    with db.session_scope() as s:
        rows = s.scalars(select(Channel).where(Channel.type.in_(("telegram", "bale")), Channel.enabled)
                         .order_by(Channel.created_at.desc()))
        for c in rows:
            token = (c.credentials or {}).get("bot_token")
            if token:
                by_token.setdefault((c.type, token), []).append(
                    {"id": c.id, "workspace_id": c.workspace_id, "raw_chat_id": (c.config or {}).get("raw_chat_id")})
    if not by_token:
        raise SystemExit("No Telegram/Bale channel with a bot token yet; add one in the panel first")
    # One getUpdates loop per bot: two loops on one token steal each other's updates.
    await asyncio.gather(*(poll_token(platform, token, chans) for (platform, token), chans in by_token.items()))


if __name__ == "__main__":
    from ..logs import setup

    setup()  # timestamps and LOG_LEVEL, as in the API
    asyncio.run(main())
