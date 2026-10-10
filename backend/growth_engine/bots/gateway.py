"""Bot gateway: every update from a workspace's Bale or Telegram bot.

Members (bound with /start <code>) send raw media and approve drafts.
Everyone else is an audience member: keywords get their reply and become
leads, anything else lands in the feedback inbox.
"""

import logging
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..errors import AppError
from ..i18n import catalog, patterns, t
from ..textnorm import ascii_digits
from ..jobs import queue
from ..models import (
    BotSession, BotUpdate, Channel, FunnelEvent, KeywordReply, Lead, MediaAsset, Membership, MetricSnapshot,
    Post, PostVariant, Publication, TagRecipe, Workspace,
)
from ..services import feedback as feedback_service
from ..services import posts as post_service
from ..services import timing, uploads
from ..services.approval import close_cards
from ..services.publishing import schedule_metrics
from .api import DOWNLOAD_LIMIT_MB, BotApi
from .cards import parse_callback, rating_keyboard, time_keyboard

logger = logging.getLogger(__name__)

INSTAGRAM_URL = re.compile(r"https?://(?:www\.)?instagram\.com/(?:reel|p|stories/[^/]+)/([\w-]+)")
STATS_TAG = patterns()["stats_tag"]
NOTE_WINDOW = timedelta(minutes=30)


class Reply:
    """What the gateway wants to send back; executed after the DB commit."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, list | None]] = []  # (chat_id, text, keyboard)
        self.callback: tuple[str, str] | None = None
        self.after: list[tuple[str, str]] = []  # (post_id, note key): close approval cards

    def say(self, chat_id: str, text: str, keyboard: list | None = None) -> None:
        self.messages.append((str(chat_id), text, keyboard))


def _seen(s: Session, channel: Channel, update_id: object) -> bool:
    key = (channel.type, channel.id, str(update_id))
    if s.get(BotUpdate, key):
        return True
    s.add(BotUpdate(platform=channel.type, channel_id=channel.id, update_id=str(update_id), at=db.utcnow()))
    return False


def _member(s: Session, channel: Channel, user_id: object) -> Membership | None:
    column = Membership.bale_user_id if channel.type == "bale" else Membership.telegram_user_id
    return s.scalar(select(Membership).where(Membership.workspace_id == channel.workspace_id,
                                             column == str(user_id)))


def _session(s: Session, channel: Channel, chat_id: str) -> BotSession:
    row = s.get(BotSession, (channel.type, str(chat_id)))
    if row is None:
        row = BotSession(platform=channel.type, chat_id=str(chat_id), state={})
        s.add(row)
    return row


def _video_of(message: dict) -> dict | None:
    if message.get("video"):
        return message["video"]
    doc = message.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("video/"):
        return doc
    return None


async def handle_update(channel_id: str, update: dict) -> None:
    reply = Reply()
    with db.session_scope() as s:
        channel = s.get(Channel, channel_id)
        if channel is None or not channel.enabled:
            return
        if _seen(s, channel, update.get("update_id")):
            return
        try:
            _route(s, channel, update, reply)
        except AppError as exc:
            chat = _chat_of(update)
            if chat:
                key = f"error.{exc.code}"
                reply.say(chat, t(key) if key in catalog() else t("error.generic"))
        token = channel.credentials["bot_token"]
        platform = channel.type
    await _deliver(platform, token, reply)


def _chat_of(update: dict) -> str | None:
    msg = update.get("message") or (update.get("callback_query") or {}).get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    return str(chat) if chat is not None else None


async def _deliver(platform: str, token: str, reply: Reply) -> None:
    api = BotApi(platform, token)
    if reply.callback:
        try:
            await api.answer_callback(*reply.callback)
        except Exception:  # noqa: BLE001 - a stale button must not block the reply
            logger.warning("[gateway] answerCallbackQuery failed")
    for chat_id, text, keyboard in reply.messages:
        try:
            await api.send_message(chat_id, text, keyboard)
        except Exception:  # noqa: BLE001
            logger.warning("[gateway] sendMessage failed")
    if reply.after:
        for post_id, note in reply.after:
            await close_cards(post_id, note)


def _route(s: Session, channel: Channel, update: dict, reply: Reply) -> None:
    if "callback_query" in update:
        _on_callback(s, channel, update["callback_query"], reply)
    elif "message_reaction_count" in update:
        _on_reactions(s, channel, update["message_reaction_count"])
    elif "channel_post" in update:
        _on_channel_post(s, channel, update["channel_post"])
    elif "message" in update:
        _on_message(s, channel, update["message"], reply)


def _on_channel_post(s: Session, channel: Channel, post: dict) -> None:
    """Telegram only: raw videos sent to the private raw-content channel."""
    chat_id = str((post.get("chat") or {}).get("id"))
    if chat_id != str((channel.config or {}).get("raw_chat_id")):
        return  # our own published posts come back as channel_post too
    video = _video_of(post)
    if video:
        ws = s.get(Workspace, channel.workspace_id)
        post_service.ingest(s, ws, platform=channel.type, member=None, chat_id=chat_id,
                            msg_id=str(post.get("message_id")), caption_text=post.get("caption", ""),
                            download={"channel_id": channel.id, "file_id": video["file_id"]})


def _on_message(s: Session, channel: Channel, msg: dict, reply: Reply) -> None:
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id"))
    sender = msg.get("from") or {}
    text = msg.get("text") or ""
    member = _member(s, channel, sender.get("id"))

    if text.startswith("/start"):
        return _bind(s, channel, sender, text, chat_id, reply)

    raw_chat = str((channel.config or {}).get("raw_chat_id") or "")
    if _is_discussion_comment(channel, msg):
        feedback_service.ingest_message(s, channel, msg)
        return
    if member is None:
        if chat.get("type") == "private":
            _on_audience_message(s, channel, msg, reply)
        elif chat_id == raw_chat:
            logger.info("[bot] ignored a message in the raw-content group from user %s: not linked to a member "
                        "(send /start CODE to the bot)", sender.get("id"))
        return
    if chat.get("type") != "private" and chat_id != raw_chat:
        logger.info("[bot] ignored chat %s: not the raw-content group (raw_chat_id=%s)", chat_id, raw_chat or "-")
        return

    ws = s.get(Workspace, channel.workspace_id)
    session = _session(s, channel, chat_id)
    video = _video_of(msg)
    if video:
        return _on_video(s, channel, ws, member, msg, video, chat_id, reply)
    if msg.get("voice") or msg.get("audio"):
        return _on_voice(s, channel, member, msg, chat_id, reply)
    if msg.get("photo"):
        return _on_photo(s, channel, member, msg, chat_id, session, reply)
    if text:
        return _on_member_text(s, channel, ws, member, text, chat_id, session, reply)


def _bind(s: Session, channel: Channel, sender: dict, text: str, chat_id: str, reply: Reply) -> None:
    # Persian digits and invisible direction marks come along when the code is copied from RTL text.
    code = re.sub(r"[^0-9A-Z]", "", ascii_digits(text.partition(" ")[2]).upper())
    if not code:
        reply.say(chat_id, t("bot.welcome"))
        return
    member = s.scalar(select(Membership).where(Membership.workspace_id == channel.workspace_id,
                                               Membership.link_code == code))
    if member is None:
        logger.info("[bot] /start with an unknown or used code %r in workspace %s", code,
                    channel.workspace_id[:8])
        reply.say(chat_id, t("bot.bind_unknown"))
        return
    if channel.type == "bale":
        member.bale_user_id = str(sender.get("id"))
    else:
        member.telegram_user_id = str(sender.get("id"))
    member.link_code = None
    reply.say(chat_id, t("bot.bound", name=member.display_name or sender.get("first_name", "")))
    if chat_id != str(sender.get("id")):
        # Linked from a group: the bot still may not write to this person until they press Start in private.
        reply.say(chat_id, t("bot.bound_open_private"))


def _on_video(s, channel, ws, member, msg, video, chat_id, reply) -> None:
    size_mb = (video.get("file_size") or 0) / (1024 * 1024)
    if size_mb > DOWNLOAD_LIMIT_MB[channel.type]:
        logger.info("[bot] video of %.1f MB is over the %s MB bot download limit; sent an upload link",
                    size_mb, DOWNLOAD_LIMIT_MB[channel.type])
        # Bots cannot download it; a direct upload link takes it instead.
        reply.say(chat_id, t("bot.too_big", limit=DOWNLOAD_LIMIT_MB[channel.type],
                             url=uploads.upload_url(ws.id, member.id, msg.get("caption", ""))))
        return
    post = post_service.ingest(s, ws, platform=channel.type, member=member, chat_id=chat_id,
                               msg_id=str(msg.get("message_id")), caption_text=msg.get("caption", ""),
                               download={"channel_id": channel.id, "file_id": video["file_id"]})
    logger.info("[bot] video from %s (%.1f MB) -> post %s, tag=%s; process_video queued (media worker)",
                member.display_name, size_mb, post.id[:8], post.tag or "none")
    reply.say(chat_id, t("bot.received") if post.tag else t("bot.received_no_tag"))


def _recent_post(s: Session, member: Membership) -> Post | None:
    return s.scalar(select(Post).join(MediaAsset, MediaAsset.id == Post.asset_id)
                    .where(MediaAsset.sender_member_id == member.id,
                           Post.status.in_(("processing", "pending")),
                           Post.created_at > db.utcnow() - NOTE_WINDOW)
                    .order_by(Post.created_at.desc()))


def _on_voice(s, channel, member, msg, chat_id, reply) -> None:
    """A voice note right after a video is raw material for its caption."""
    post = _recent_post(s, member)
    if post is None:
        reply.say(chat_id, t("bot.voice_no_post"))
        return
    voice = msg.get("voice") or msg.get("audio")
    queue.enqueue(s, "transcribe_voice", {"post_id": post.id, "channel_id": channel.id, "file_id": voice["file_id"]})
    reply.say(chat_id, t("bot.voice_received"))


def _on_photo(s, channel, member, msg, chat_id, session, reply) -> None:
    caption = msg.get("caption") or ""
    if STATS_TAG not in caption and session.state.get("await") != "insights":
        reply.say(chat_id, t("bot.photo_hint"))
        return
    largest = max(msg["photo"], key=lambda p: p.get("file_size", 0))
    queue.enqueue(s, "read_insights", {"workspace_id": channel.workspace_id, "channel_id": channel.id,
                                       "file_id": largest["file_id"], "chat_id": chat_id,
                                       "publication_id": session.state.get("publication_id")})
    session.state = {}
    reply.say(chat_id, t("bot.insights_received"))


def _on_member_text(s, channel, ws, member, text, chat_id, session, reply) -> None:
    state = dict(session.state or {})
    waiting = state.get("await")
    if waiting in ("caption", "subtitle"):
        post = post_service.get(s, state["post_id"], ws.id)
        session.state = {}
        if waiting == "caption":
            post_service.request_caption_edit(s, post, member, text)
            reply.say(chat_id, t("bot.caption_editing"))
        else:
            wrong, right = post_service.request_subtitle_fix(s, post, member, text)
            reply.say(chat_id, t("bot.subtitle_fixing", wrong=wrong, right=right))
        return
    if m := INSTAGRAM_URL.search(text):
        return _complete_handoff(s, ws, m.group(0), m.group(1), chat_id, reply)
    post = _recent_post(s, member)
    if post is not None and post.status == "processing":
        tags = list(s.scalars(select(TagRecipe.tag).where(TagRecipe.workspace_id == ws.id)))
        tag, note = post_service.parse_caption(text, tags)
        if tag and not post.tag:
            recipe = post_service.recipe_for(s, ws.id, tag)
            post.tag, post.recipe_id = tag, recipe.id if recipe else None
        post.raw_note = f"{post.raw_note}\n{note}".strip()
        reply.say(chat_id, t("bot.note_added"))
        return
    reply.say(chat_id, t("bot.help"))


def _complete_handoff(s, ws, url: str, shortcode: str, chat_id: str, reply: Reply) -> None:
    """The admin sent the link of the post they published by hand."""
    pub = s.scalar(select(Publication).join(PostVariant, PostVariant.id == Publication.variant_id)
                   .join(Post, Post.id == PostVariant.post_id)
                   .where(Post.workspace_id == ws.id, Publication.status == "handoff_pending")
                   .order_by(Publication.created_at))
    if pub is None:
        reply.say(chat_id, t("bot.handoff_none"))
        return
    pub.status, pub.external_url, pub.external_id, pub.published_at = "published", url, shortcode, db.utcnow()
    schedule_metrics(s, pub)
    reply.say(chat_id, t("bot.handoff_done"))


def _on_callback(s: Session, channel: Channel, cq: dict, reply: Reply) -> None:
    reply.callback = (cq["id"], "")
    chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id"))
    member = _member(s, channel, (cq.get("from") or {}).get("id"))
    if member is None:
        reply.callback = (cq["id"], t("bot.not_member"))
        return
    try:
        action, post_id, index = parse_callback(cq.get("data", ""))
    except ValueError:
        return
    post = post_service.get(s, post_id, channel.workspace_id)
    ws = s.get(Workspace, channel.workspace_id)
    best_hour = int((ws.settings or {}).get("best_hour", 20))
    session = _session(s, channel, chat_id)

    if action == "a":
        post_service.approve(s, post, member)
        reply.after.append((post.id, "bot.approved"))
        reply.say(chat_id, t("bot.rate_prompt"), rating_keyboard(post.id))
    elif action == "r":
        post_service.reject(s, post, member)
        reply.after.append((post.id, "bot.rejected"))
    elif action == "e":
        session.state = {"await": "caption", "post_id": post.id}
        reply.say(chat_id, t("bot.caption_prompt"))
    elif action == "s":
        session.state = {"await": "subtitle", "post_id": post.id}
        reply.say(chat_id, t("bot.subtitle_prompt"))
    elif action == "t":
        reply.say(chat_id, t("bot.time_prompt"), time_keyboard(post.id, timing.quick_choices(db.utcnow(), best_hour)))
    elif action == "T" and index is not None:
        choices = timing.quick_choices(db.utcnow(), best_hour)
        at = choices[min(index, len(choices) - 1)]
        post_service.reschedule(s, post, member, at)
        reply.after.append((post.id, "bot.scheduled"))
    elif action == "g" and index is not None:
        tags = sorted(s.scalars(select(TagRecipe.tag).where(TagRecipe.workspace_id == channel.workspace_id)))
        if index < len(tags):
            post_service.set_tag(s, post, member, tags[index])
            reply.say(chat_id, t("bot.tag_set", tag=tags[index]))
    elif action == "k" and index is not None:
        post_service.rate(s, post, member, index)
        reply.callback = (cq["id"], t("bot.rated"))


def _on_reactions(s: Session, channel: Channel, update: dict) -> None:
    """Telegram reaction counts on a channel post we published."""
    message_id = str(update.get("message_id"))
    pub = s.scalar(select(Publication).join(PostVariant, PostVariant.id == Publication.variant_id)
                   .where(PostVariant.channel_id == channel.id, Publication.external_id == message_id))
    if pub is None:
        return
    total = sum(int(r.get("total_count", 0)) for r in update.get("reactions", []))
    s.add(MetricSnapshot(publication_id=pub.id, at=db.utcnow(), likes=total, source="api"))


def _is_discussion_comment(channel: Channel, msg: dict) -> bool:
    """A reply in the channel's discussion group to one of our channel posts."""
    group = str((channel.config or {}).get("discussion_chat_id") or "")
    if not group or str((msg.get("chat") or {}).get("id")) != group:
        return False
    return bool((msg.get("reply_to_message") or {}).get("is_automatic_forward")) or bool(msg.get("message_thread_id"))


def _on_audience_message(s: Session, channel: Channel, msg: dict, reply: Reply) -> None:
    chat_id = str(msg["chat"]["id"])
    sender = msg.get("from") or {}
    text = (msg.get("text") or "").strip()
    s.add(FunnelEvent(workspace_id=channel.workspace_id, kind="bot_message", at=db.utcnow(),
                      data={"platform": channel.type}))
    keyword = s.scalar(select(KeywordReply).where(KeywordReply.workspace_id == channel.workspace_id,
                                                  KeywordReply.keyword == text))
    if keyword is not None:
        s.add(Lead(workspace_id=channel.workspace_id, platform=channel.type, platform_user_id=str(sender.get("id")),
                   name=" ".join(filter(None, [sender.get("first_name"), sender.get("last_name")])),
                   keyword=keyword.keyword, at=db.utcnow()))
        reply.say(chat_id, keyword.reply_text)
        return
    if text:
        feedback_service.ingest_message(s, channel, msg)
        reply.say(chat_id, t("bot.audience_thanks"))
