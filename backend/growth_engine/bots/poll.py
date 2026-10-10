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


async def poll_channel(channel_id: str, platform: str, token: str) -> None:
    api = BotApi(platform, token, timeout=70)
    await api.call("deleteWebhook")
    logger.info("[poll] %s channel %s: polling", platform, channel_id)
    offset = None
    while True:
        try:
            updates = await api.call("getUpdates", {"offset": offset, "timeout": 50, "allowed_updates": ALLOWED})
        except BotApiError as exc:
            logger.warning("[poll] %s: %s", channel_id, exc)
            await asyncio.sleep(5)
            continue
        for update in updates if isinstance(updates, list) else []:
            offset = update["update_id"] + 1
            try:
                await gateway.handle_update(channel_id, update)
            except Exception:  # noqa: BLE001 - one broken update must not stop polling
                logger.exception("[poll] update failed for channel %s", channel_id)


async def main() -> None:
    if not get_settings().is_development:
        raise SystemExit("Polling is for local development only (ENVIRONMENT=development)")
    with db.session_scope() as s:
        bots = [(c.id, c.type, (c.credentials or {}).get("bot_token"))
                for c in s.scalars(select(Channel).where(Channel.type.in_(("telegram", "bale")), Channel.enabled))]
    bots = [b for b in bots if b[2]]
    if not bots:
        raise SystemExit("No Telegram/Bale channel with a bot token yet; add one in the panel first")
    await asyncio.gather(*(poll_channel(*b) for b in bots))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
