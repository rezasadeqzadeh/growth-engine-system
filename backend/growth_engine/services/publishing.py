"""Publishing approved variants through the channel adapters."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..channels.base import PublishError, PublishItem
from ..channels.registry import adapter
from ..i18n import fa_digits, t
from ..jobs import queue
from ..jobs.runner import PermanentError
from ..models import Channel, Offer, Post, PostVariant, Publication, Registration, TrackedLink, Workspace
from ..redact import redact
from . import links, notify, storage

# When metrics are collected after publishing.
METRIC_DELAYS = (timedelta(hours=1), timedelta(days=1), timedelta(days=3), timedelta(days=7))


def _item(s: Session, ws: Workspace, post: Post, variant: PostVariant) -> PublishItem:
    def path(key: str | None):
        return storage.path_of(key) if key else None

    return PublishItem(
        kind=variant.kind, caption=variant.caption, title=variant.title or post.title, tags=variant.tags or [],
        video=path(variant.video_key), cover=path(variant.cover_key), srt=path(variant.srt_key),
        video_url=storage.signed_url(variant.video_key) if variant.video_key else None,
        cover_url=storage.signed_url(variant.cover_key) if variant.cover_key else None,
        page_url=links.site_url(ws, f"/p/{post.id}"))


def _finish_post_if_done(s: Session, post: Post) -> None:
    total = s.scalar(select(func.count()).select_from(PostVariant).where(PostVariant.post_id == post.id)) or 0
    done = s.scalar(select(func.count(func.distinct(Publication.variant_id))).join(
        PostVariant, PostVariant.id == Publication.variant_id).where(PostVariant.post_id == post.id)) or 0
    if done >= total:
        post.status = "published"


async def publish_variant(payload: dict) -> None:
    with db.session_scope() as s:
        variant = s.get(PostVariant, payload["variant_id"])
        if variant is None:
            return
        post = s.get(Post, variant.post_id)
        channel = s.get(Channel, variant.channel_id)
        assert post is not None and channel is not None
        # A rescheduled post leaves older publish jobs behind; they step aside.
        if post.status != "scheduled" or (payload.get("at") and post.scheduled_at
                                          and payload["at"] != post.scheduled_at.isoformat()):
            return
        if s.scalar(select(Publication.id).where(Publication.variant_id == variant.id,
                                                 Publication.status.in_(("published", "handoff_pending")))):
            return
        ws = s.get(Workspace, post.workspace_id)
        assert ws is not None
        try:
            result = await adapter(channel.type).publish(channel, _item(s, ws, post, variant))
        except PublishError as exc:
            message = redact(exc, channel.secrets())
            # The failure is recorded by on_publish_failed once retries are over
            # (this session rolls back on the raise).
            raise (RuntimeError(message) if exc.retryable else PermanentError(message)) from None
        pub = Publication(variant_id=variant.id, status=result.status, external_id=result.external_id,
                          external_url=result.external_url,
                          published_at=db.utcnow() if result.status == "published" else None)
        s.add(pub)
        s.flush()
        if result.status == "handoff_pending":
            queue.enqueue(s, "send_handoff", {"publication_id": pub.id})
        else:
            schedule_metrics(s, pub)
        if "aparat_srt_manual" in result.notes and variant.srt_key:
            queue.enqueue(s, "send_srt", {"variant_id": variant.id, "url": result.external_url})
        _finish_post_if_done(s, post)


def schedule_metrics(s: Session, pub: Publication) -> None:
    now = db.utcnow()
    for delay in METRIC_DELAYS:
        queue.enqueue(s, "collect_metrics", {"publication_id": pub.id}, run_at=now + delay,
                      dedupe_key=f"metrics:{pub.id}:{int(delay.total_seconds())}")


def _record_failure(s: Session, variant: PostVariant, message: str) -> None:
    s.add(Publication(variant_id=variant.id, status="failed", error=message[:500]))
    post = s.get(Post, variant.post_id)
    if post is not None:
        s.flush()
        _finish_post_if_done(s, post)


def on_publish_failed(payload: dict, message: str) -> None:
    """Final failure of a publish job: record it and tell the managers."""
    with db.session_scope() as s:
        variant = s.get(PostVariant, payload["variant_id"])
        if variant is None:
            return
        if not s.scalar(select(Publication.id).where(Publication.variant_id == variant.id)):
            _record_failure(s, variant, message)
        channel = s.get(Channel, variant.channel_id)
        post = s.get(Post, variant.post_id)
        queue.enqueue(s, "notify_text", {"workspace_id": post.workspace_id, "key": "bot.publish_failed",
                                         "values": {"channel": channel.name or channel.type, "title": post.title}})


async def publish_reminder(payload: dict) -> None:
    """The reminder a selling post gets N days later, on the messengers:
    seats left and the same tracked link."""
    with db.session_scope() as s:
        post = s.get(Post, payload["post_id"])
        if post is None or post.status != "published":
            return
        offer = s.scalar(select(Offer).where(Offer.workspace_id == post.workspace_id, Offer.active,
                                             Offer.starts_at > db.utcnow()).order_by(Offer.starts_at))
        if offer is None:
            return
        taken = s.scalar(select(func.count()).select_from(Registration).where(
            Registration.offer_id == offer.id, Registration.status == "paid")) or 0
        if offer.capacity and taken >= offer.capacity:
            return
        for variant, channel in s.execute(select(PostVariant, Channel).join(Channel, Channel.id == PostVariant.channel_id)
                                          .where(PostVariant.post_id == post.id, PostVariant.kind == "message",
                                                 Channel.type.in_(("bale", "telegram", "eitaa", "rubika")))):
            link = s.get(TrackedLink, variant.tracked_link_id) if variant.tracked_link_id else None
            left = fa_digits(offer.capacity - taken) if offer.capacity else ""
            text = t("post.reminder_with_seats" if left else "post.reminder", title=offer.title, left=left,
                     link=links.short_url(link) if link else "")
            item = PublishItem(kind="message", caption=text, title="", tags=[], video=None, cover=None, srt=None,
                               video_url=None, cover_url=None, page_url=None)
            try:
                await adapter(channel.type).publish(channel, item)
            except PublishError:
                continue  # one channel down never stops the others


async def notify_text(payload: dict) -> None:
    with db.session_scope() as s:
        await notify.text(s, payload["workspace_id"], t(payload["key"], **payload.get("values", {})))
