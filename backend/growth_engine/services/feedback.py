"""The feedback inbox: comments and messages from every channel in one place,
classified, with a suggested reply. A human sends the reply.

purchase_question -> high priority, reply suggested with the link
praise            -> thanks, and ask permission to use it
criticism         -> the manager is alerted; no automatic reply
spam              -> hidden
idea              -> into the idea bank (e.g. "routes for beginners?" = next how-to post)
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..bots.api import BotApi
from ..channels.base import Comment
from ..errors import AppError, NotFound
from ..i18n import t
from ..jobs import queue
from ..models import FEEDBACK_CATEGORIES, Channel, ContentIdea, Feedback, FunnelEvent, Offer, Workspace
from . import brand_kit, links, notify

SYSTEM = """You sort audience messages for an Iranian small business and draft replies in Persian.
Categories: purchase_question (price, capacity, date, how to buy), praise, criticism, spam, idea
(a question or wish that could become content), other.
Replies follow the tone lock, use only the facts given, and for purchase questions end with the link.
Criticism and spam get no reply (empty string). For praise: thank them and ask permission to quote it.
For an idea: also write the content idea in one line.
JSON: {"items": [{"id": "...", "category": "...", "reply": "...", "idea": "..."}]}"""


def _store(s: Session, workspace_id: str, channel_type: str, external_id: str, author: str, text: str,
           at: datetime, publication_id: str | None = None) -> Feedback | None:
    exists = s.scalar(select(Feedback.id).where(Feedback.workspace_id == workspace_id,
                                                Feedback.channel_type == channel_type,
                                                Feedback.external_id == external_id))
    if exists or not text.strip():
        return None
    row = Feedback(workspace_id=workspace_id, channel_type=channel_type, external_id=external_id,
                   author=author[:120], text=text[:4000], at=at, publication_id=publication_id)
    s.add(row)
    s.flush()
    queue.enqueue(s, "classify_feedback", {"workspace_id": workspace_id}, dedupe_key=f"classify:{workspace_id}")
    return row


def ingest_message(s: Session, channel: Channel, msg: dict) -> Feedback | None:
    """A DM to the bot, or a comment in the channel's discussion group.
    external_id keeps "<chat>:<message>" so a reply can be sent back."""
    sender = msg.get("from") or {}
    author = sender.get("username") or " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
    return _store(s, channel.workspace_id, channel.type, f"{msg['chat']['id']}:{msg['message_id']}",
                  author, msg.get("text") or msg.get("caption") or "", db.utcnow())


def ingest_comment(s: Session, workspace_id: str, channel_type: str, publication_id: str, c: Comment) -> Feedback | None:
    return _store(s, workspace_id, channel_type, c.external_id, c.author, c.text, c.at, publication_id)


def ingest_site_comment(s: Session, ws: Workspace, ref: str, name: str, text: str) -> Feedback | None:
    return _store(s, ws.id, "site", f"{ref}:{db.new_id()[:8]}", name, text, db.utcnow())


async def classify_pending(payload: dict) -> None:
    workspace_id = payload["workspace_id"]
    with db.session_scope() as s:
        rows = list(s.scalars(select(Feedback).where(Feedback.workspace_id == workspace_id,
                                                     Feedback.category.is_(None)).limit(30)))
        if not rows:
            return
        ws = s.get(Workspace, workspace_id)
        kit = brand_kit.current(s, workspace_id)
        offer = s.scalar(select(Offer).where(Offer.workspace_id == workspace_id, Offer.active,
                                             Offer.starts_at > db.utcnow()).order_by(Offer.starts_at))
        facts = (f"Next offer: {offer.title}, {offer.price_toman} toman, link {links.offer_url(ws, offer)}"
                 if offer else "No open offer.")
        user = "\n".join([
            f"Business: {ws.name}", f"Tone: {', '.join((kit.tone or {}).get('adjectives', []))}", facts, "",
            *[f"[{r.id}] ({r.channel_type}, {r.author}): {r.text}" for r in rows]])
        reply = await router.ask_json("classify_feedback", SYSTEM, user, workspace_id=workspace_id)
        by_id = {item.get("id"): item for item in (reply.get("items", []) if isinstance(reply, dict) else [])}
        alerts = []
        for row in rows:
            item = by_id.get(row.id) or {}
            category = item.get("category") if item.get("category") in FEEDBACK_CATEGORIES else "other"
            row.category = category
            row.suggested_reply = (item.get("reply") or None) if category not in ("criticism", "spam") else None
            if category == "spam":
                row.hidden = True
            elif category == "idea" and item.get("idea"):
                s.add(ContentIdea(workspace_id=workspace_id, text=item["idea"], source="feedback"))
            elif category == "purchase_question":
                s.add(FunnelEvent(workspace_id=workspace_id, kind="purchase_question", at=row.at,
                                  data={"feedback_id": row.id}))
            elif category == "criticism":
                row.alerted = True
                alerts.append(row)
        # More rows may be waiting beyond this batch.
        if len(rows) == 30:
            queue.enqueue(s, "classify_feedback", {"workspace_id": workspace_id})
        for row in alerts:
            await notify.text(s, workspace_id, t("feedback.criticism_alert", author=row.author,
                                                 channel=t(f"channel.{row.channel_type}"), text=row.text[:500]))


async def send_reply(s: Session, feedback: Feedback, text: str) -> None:
    """Send a reply where the platform lets us (bot DMs and discussion comments)."""
    if feedback.channel_type not in ("bale", "telegram"):
        raise AppError("reply_not_supported", "Copy the reply and send it in the app", 400)
    chat_id, _, message_id = feedback.external_id.partition(":")
    bot = s.scalar(select(Channel).where(Channel.workspace_id == feedback.workspace_id,
                                         Channel.type == feedback.channel_type, Channel.enabled))
    if bot is None or not (bot.credentials or {}).get("bot_token"):
        raise NotFound("bot")
    await BotApi(bot.type, bot.credentials["bot_token"]).send_message(chat_id, text, reply_to=message_id)
    feedback.handled = True
