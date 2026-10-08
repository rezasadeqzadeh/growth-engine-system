"""Measurement in three layers: attention (views...), interest (clicks, bot
messages, purchase questions), result (registrations, payments, revenue
by source). The result layer is ours entirely; it does not depend on any
platform's API."""

import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..ai.opencode import ImagePart
from ..bots.api import BotApi
from ..channels.base import NotSupported
from ..channels.registry import adapter
from ..i18n import t
from ..jobs.runner import PermanentError
from ..models import (
    AuditLog, Channel, Click, Coupon, FunnelEvent, MetricSnapshot, Post, PostVariant, Publication, Registration,
    TrackedLink, Workspace,
)
from . import feedback as feedback_service
from .timing import TEHRAN

# Minutes of admin work each logged action stands for (estimate shown as such).
ACTION_MINUTES = {"approve": 1, "reject": 1, "reschedule": 1, "set_tag": 1, "subtitle_fix": 2, "caption_edit": 2,
                  "handoff": 2, "upload": 1}

OCR_SYSTEM = """Read this Instagram Insights screenshot. Return the numbers exactly as shown
(convert Persian digits and K/M suffixes to plain integers); null when not visible.
JSON: {"views": int|null, "reach": int|null, "likes": int|null, "comments": int|null,
       "saves": int|null, "shares": int|null, "caption_start": "first words of the post caption if visible"}"""


async def collect_metrics(payload: dict) -> None:
    with db.session_scope() as s:
        pub = s.get(Publication, payload["publication_id"])
        if pub is None or pub.status != "published" or not pub.external_id:
            return
        variant = s.get(PostVariant, pub.variant_id)
        channel = s.get(Channel, variant.channel_id)
        try:
            m = await adapter(channel.type).fetch_metrics(channel, pub.external_id)
        except NotSupported:
            return
        s.add(MetricSnapshot(publication_id=pub.id, at=db.utcnow(), views=m.views, reach=m.reach, likes=m.likes,
                             comments=m.comments, saves=m.saves, shares=m.shares, source="api"))


async def collect_comments(payload: dict) -> None:
    """Pull comments for the last 14 days of publications on channels that expose them."""
    with db.session_scope() as s:
        since = db.utcnow() - timedelta(days=14)
        rows = s.execute(select(Publication, Channel).join(PostVariant, PostVariant.id == Publication.variant_id)
                         .join(Channel, Channel.id == PostVariant.channel_id)
                         .where(Channel.workspace_id == payload["workspace_id"], Publication.status == "published",
                                Publication.published_at > since, Publication.external_id.is_not(None)))
        for pub, channel in rows:
            if adapter(channel.type).capabilities().comments != "api":
                continue
            try:
                found = await adapter(channel.type).fetch_comments(channel, pub.external_id)
            except NotSupported:
                continue
            for comment in found:
                feedback_service.ingest_comment(s, channel.workspace_id, channel.type, pub.id, comment)


def _parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def read_insights(payload: dict) -> None:
    """An Insights screenshot sent to the bot -> a snapshot for the matching post."""
    with db.session_scope() as s:
        bot = s.get(Channel, payload["channel_id"])
        api = BotApi(bot.type, bot.credentials["bot_token"])
        with tempfile.TemporaryDirectory() as tmp:
            path = await api.download(payload["file_id"], Path(tmp) / "insights.jpg")
            image = ImagePart(path.read_bytes(), "image/jpeg", "insights.jpg")
        data = await router.ask_json("read_screenshot", OCR_SYSTEM, "Read the numbers.",
                                     workspace_id=payload["workspace_id"], images=[image])
        if not isinstance(data, dict):
            raise PermanentError("Unreadable screenshot")
        pub = _match_instagram_publication(s, payload["workspace_id"], payload.get("publication_id"),
                                           str(data.get("caption_start") or ""))
        if pub is None:
            await api.send_message(payload["chat_id"], t("bot.insights_no_post"))
            return
        s.add(MetricSnapshot(publication_id=pub.id, at=db.utcnow(), source="ocr",
                             **{k: _parse_int(data.get(k)) for k in ("views", "reach", "likes", "comments",
                                                                     "saves", "shares")}))
        await api.send_message(payload["chat_id"], t("bot.insights_saved", views=data.get("views") or "-"))


def _match_instagram_publication(s: Session, workspace_id: str, publication_id: str | None,
                                 caption_start: str) -> Publication | None:
    q = (select(Publication, PostVariant).join(PostVariant, PostVariant.id == Publication.variant_id)
         .join(Channel, Channel.id == PostVariant.channel_id)
         .where(Channel.workspace_id == workspace_id, Channel.type == "instagram", Publication.status == "published")
         .order_by(Publication.published_at.desc()).limit(20))
    rows = list(s.execute(q))
    if publication_id:
        return next((p for p, _ in rows if p.id == publication_id), None)
    words = caption_start.strip()[:30]
    if words:
        for pub, variant in rows:
            if words in variant.caption:
                return pub
    return rows[0][0] if rows else None


def latest_snapshots(s: Session, workspace_id: str, since: datetime) -> list[tuple[MetricSnapshot, str, str | None]]:
    """The newest snapshot per publication: (snapshot, channel type, post tag)."""
    latest = (select(MetricSnapshot.publication_id, func.max(MetricSnapshot.at).label("at"))
              .group_by(MetricSnapshot.publication_id).subquery())
    q = (select(MetricSnapshot, Channel.type, Post.tag)
         .join(latest, (latest.c.publication_id == MetricSnapshot.publication_id) & (latest.c.at == MetricSnapshot.at))
         .join(Publication, Publication.id == MetricSnapshot.publication_id)
         .join(PostVariant, PostVariant.id == Publication.variant_id)
         .join(Channel, Channel.id == PostVariant.channel_id)
         .join(Post, Post.id == PostVariant.post_id)
         .where(Channel.workspace_id == workspace_id, Publication.published_at >= since))
    return [(m, ch, tag) for m, ch, tag in s.execute(q)]


def attribution_key(reg: Registration, link: TrackedLink | None, coupon: Coupon | None) -> str:
    if coupon is not None:
        return f"coupon:{coupon.influencer or coupon.code}"
    if link is not None:
        return f"tag:{link.tag}" if link.tag else f"channel:{link.channel_type or 'direct'}"
    return "direct"


def dashboard(s: Session, ws: Workspace, days: int = 30) -> dict:
    since = db.utcnow() - timedelta(days=days)
    snaps = latest_snapshots(s, ws.id, since)
    views = sum(m.views or 0 for m, _, _ in snaps)
    clicks = s.scalar(select(func.count()).select_from(Click).join(TrackedLink, TrackedLink.id == Click.link_id)
                      .where(TrackedLink.workspace_id == ws.id, Click.at >= since)) or 0
    form_starts = s.scalar(select(func.count()).select_from(FunnelEvent).where(
        FunnelEvent.workspace_id == ws.id, FunnelEvent.kind == "form_start", FunnelEvent.at >= since)) or 0
    regs = list(s.execute(select(Registration, TrackedLink, Coupon)
                          .outerjoin(TrackedLink, TrackedLink.id == Registration.source_link_id)
                          .outerjoin(Coupon, Coupon.id == Registration.source_coupon_id)
                          .where(Registration.workspace_id == ws.id, Registration.status == "paid",
                                 Registration.paid_at >= since)))
    paid = len(regs)
    revenue = sum(r.amount_toman for r, _, _ in regs)
    tracked_revenue = sum(r.amount_toman for r, link, coupon in regs if link or coupon)
    by_source = Counter(attribution_key(r, link, coupon) for r, link, coupon in regs)
    by_channel = Counter((link.channel_type or "direct") if link else "direct" for _, link, _ in regs)
    home = (ws.settings or {}).get("home_city", "")
    outside = sum(1 for r, _, _ in regs if home and r.city and r.city.strip() != home)

    funnel = [("views", views), ("clicks", clicks), ("form_starts", form_starts), ("payments", paid)]
    bottleneck = None
    worst = 2.0
    for (name_a, a), (name_b, b) in zip(funnel, funnel[1:]):
        if a > 0:
            rate = b / a
            if rate < worst:
                worst, bottleneck = rate, {"from": name_a, "to": name_b, "rate": round(rate, 3)}

    weeks = max(days / 7, 1)
    actions = Counter(a for (a,) in s.execute(select(AuditLog.action).where(
        AuditLog.workspace_id == ws.id, AuditLog.created_at >= since)))
    admin_minutes = round(sum(ACTION_MINUTES.get(a, 1) * n for a, n in actions.items()) / weeks)
    baseline = (ws.settings or {}).get("baseline", {})
    return {
        "days": days,
        "registrations": paid, "revenue_toman": revenue, "tracked_revenue_toman": tracked_revenue,
        "outside_city": outside, "admin_minutes_per_week": admin_minutes,
        "baseline": baseline,
        "funnel": [{"step": n, "value": v} for n, v in funnel], "bottleneck": bottleneck,
        "by_source": [{"key": k, "count": v} for k, v in by_source.most_common()],
        "by_channel": [{"key": k, "count": v} for k, v in by_channel.most_common()],
        "attention": {k: sum(getattr(m, k) or 0 for m, _, _ in snaps)
                      for k in ("views", "reach", "likes", "comments", "saves", "shares")},
    }


def learn_best_hour(s: Session, ws: Workspace) -> int | None:
    """The Tehran hour whose posts got the most views per post (needs 8+ posts)."""
    rows = s.execute(select(Publication.published_at, func.max(MetricSnapshot.views))
                     .join(MetricSnapshot, MetricSnapshot.publication_id == Publication.id)
                     .join(PostVariant, PostVariant.id == Publication.variant_id)
                     .join(Channel, Channel.id == PostVariant.channel_id)
                     .where(Channel.workspace_id == ws.id, Publication.published_at.is_not(None))
                     .group_by(Publication.id, Publication.published_at))
    per_hour: dict[int, list[int]] = defaultdict(list)
    for published_at, views in rows:
        if views is not None:
            at = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
            per_hour[at.astimezone(TEHRAN).hour].append(views)
    if sum(len(v) for v in per_hour.values()) < 8:
        return None
    return max(per_hour, key=lambda h: sum(per_hour[h]) / len(per_hour[h]))
