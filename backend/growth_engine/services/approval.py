"""What the bot sends approvers: the draft card, the Instagram handoff, the SRT."""

import logging
import time

import jwt
from sqlalchemy import select

from .. import db
from ..bots import cards
from ..bots.api import BotApi, BotApiError
from ..config import get_settings
from ..errors import AppError
from ..i18n import t
from ..redact import redact
from ..models import Channel, MediaAsset, Post, PostVariant, Publication, TagRecipe
from . import captions, notify, storage
from . import posts as post_service

logger = logging.getLogger(__name__)

HANDOFF_TTL_S = 7 * 24 * 3600


def handoff_token(publication_id: str) -> str:
    return jwt.encode({"purpose": "handoff", "pub": publication_id, "exp": int(time.time()) + HANDOFF_TTL_S},
                      get_settings().jwt_secret, algorithm="HS256")


def handoff_publication_id(token: str) -> str:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError("handoff_invalid", "This link has expired", 404) from exc
    if claims.get("purpose") != "handoff":
        raise AppError("handoff_invalid", "This link has expired", 404)
    return claims["pub"]


def build_card(s, post: Post) -> tuple[str, list]:
    asset = s.get(MediaAsset, post.asset_id) if post.asset_id else None
    variants = post_service.variants_of(s, post.id)
    channel_types = sorted({c.type for _, c in variants})
    guessed = []
    if post.tag_guessed:
        guessed = sorted(s.scalars(select(TagRecipe.tag).where(TagRecipe.workspace_id == post.workspace_id)))
    text = cards.card_text(
        title=post.title, duration_s=post.output_duration_s,
        has_subtitles=bool(asset and asset.transcript), cover_title=post.title, channels=channel_types,
        publish_at=post.scheduled_at, qc=post.qc or [], tag=post.tag, tag_guessed=post.tag_guessed,
        auto_approve_at=post.auto_approve_at)
    keyboard = cards.card_keyboard(post.id, bool(asset and asset.transcript), guessed)
    return text, keyboard


async def send_approval_card(payload: dict) -> None:
    with db.session_scope() as s:
        post = s.get(Post, payload["post_id"])
        if post is None or post.status != "pending":
            logger.info("[approval] card skipped for post %s: status is %s", payload["post_id"][:8],
                        post.status if post else "gone")
            return
        text, keyboard = build_card(s, post)
        preview, preview_type = next(((v, c.type) for v, c in post_service.variants_of(s, post.id)
                                      if v.kind in ("reel", "message")), (None, ""))
        sent = []
        recipients = list(notify.recipients(s, post.workspace_id, notify.APPROVERS))
        if not recipients:
            logger.warning("[approval] post %s: nobody to send the card to. A member with role owner/operator/"
                           "approver must be linked to the bot (/start CODE)", post.id[:8])
        for bot, chat in recipients:
            api = BotApi(bot.type, bot.credentials["bot_token"])
            try:
                if preview and preview.video_key:
                    await api.send_video(chat, storage.path_of(preview.video_key), captions.published_text(preview.caption, preview.tags, preview_type,
                                                                     preview.kind)[:900])
                msg = await api.send_message(chat, text, keyboard)
                sent.append({"platform": bot.type, "channel_id": bot.id, "chat_id": chat,
                             "message_id": str(msg.get("message_id"))})
            except BotApiError as exc:
                logger.warning("[approval] post %s: card to %s chat %s failed: %s", post.id[:8], bot.type, chat,
                               redact(exc, bot.secrets()))
                continue
            logger.info("[approval] post %s: card sent to %s chat %s%s", post.id[:8], bot.type, chat,
                        " with the video" if preview and preview.video_key else "")
        post.cards = sent


async def close_cards(post_id: str, note_key: str) -> None:
    """After a decision, every approver's card loses its buttons and says what happened."""
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        if post is None:
            return
        for ref in post.cards or []:
            bot = s.get(Channel, ref["channel_id"])
            if bot is None:
                continue
            api = BotApi(bot.type, bot.credentials["bot_token"])
            try:
                await api.edit_reply_markup(ref["chat_id"], ref["message_id"], [])
                await api.send_message(ref["chat_id"], t(note_key, title=post.title), reply_to=ref["message_id"])
            except BotApiError:
                continue


async def send_handoff(payload: dict) -> None:
    """Instagram without the API: at publish time the admin gets a page that
    saves the video and copies the caption, then sends back the post link."""
    with db.session_scope() as s:
        pub = s.get(Publication, payload["publication_id"])
        if pub is None or pub.status != "handoff_pending":
            return
        variant = s.get(PostVariant, pub.variant_id)
        post = s.get(Post, variant.post_id)
        url = f"{get_settings().public_base_url}/h/{handoff_token(pub.id)}"
        key = "handoff.story" if variant.kind == "story" else "handoff.reel"
        keyboard = [[{"text": t("btn.open_handoff"), "url": url}]]
        await notify.text(s, post.workspace_id, t(key, title=post.title), notify.APPROVERS, keyboard)


async def send_srt(payload: dict) -> None:
    with db.session_scope() as s:
        variant = s.get(PostVariant, payload["variant_id"])
        if variant is None or not variant.srt_key:
            return
        post = s.get(Post, variant.post_id)
        await notify.document(s, post.workspace_id, storage.path_of(variant.srt_key),
                              t("bot.srt_for_aparat", url=payload.get("url") or ""))
