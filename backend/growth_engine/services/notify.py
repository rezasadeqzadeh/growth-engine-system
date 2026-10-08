"""Messages to a workspace's people, through the workspace's own bots.

A member is reachable on a platform once they bound their account with
/start <code>; their user id is their private chat id with the bot.
"""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..bots.api import BotApi, BotApiError
from ..models import Channel, Membership

logger = logging.getLogger(__name__)


def bots(s: Session, workspace_id: str) -> list[Channel]:
    return [c for c in s.scalars(select(Channel).where(Channel.workspace_id == workspace_id,
                                                       Channel.type.in_(("bale", "telegram")), Channel.enabled))
            if (c.credentials or {}).get("bot_token")]


def recipients(s: Session, workspace_id: str, roles: tuple[str, ...]) -> list[tuple[Channel, str]]:
    """(bot channel, chat id) for each member with one of `roles` reachable by a bot."""
    out = []
    members = list(s.scalars(select(Membership).where(Membership.workspace_id == workspace_id,
                                                      Membership.role.in_(roles))))
    for bot in bots(s, workspace_id):
        for m in members:
            chat = m.bale_user_id if bot.type == "bale" else m.telegram_user_id
            if chat:
                out.append((bot, chat))
    return out


APPROVERS = ("owner", "operator", "approver")
MANAGERS = ("owner", "operator")


async def text(s: Session, workspace_id: str, message: str, roles: tuple[str, ...] = MANAGERS,
               keyboard: list | None = None) -> list[dict]:
    """Send to everyone in `roles`; returns [{platform, chat_id, message_id}] of what arrived."""
    sent = []
    for bot, chat in recipients(s, workspace_id, roles):
        try:
            result = await BotApi(bot.type, bot.credentials["bot_token"]).send_message(chat, message, keyboard)
            sent.append({"platform": bot.type, "channel_id": bot.id, "chat_id": chat,
                         "message_id": str(result.get("message_id"))})
        except BotApiError as exc:
            logger.warning("[notify] %s", exc)
    return sent


async def document(s: Session, workspace_id: str, path: Path, caption: str, roles: tuple[str, ...] = MANAGERS) -> None:
    for bot, chat in recipients(s, workspace_id, roles):
        try:
            await BotApi(bot.type, bot.credentials["bot_token"]).send_document(chat, path, caption)
        except BotApiError as exc:
            logger.warning("[notify] %s", exc)
