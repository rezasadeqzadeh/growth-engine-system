"""Feedback inbox, calendar, page audits, competitors, weekly reports."""

from datetime import date, datetime

from sqlalchemy import JSON, Date, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin

FEEDBACK_CATEGORIES = ("purchase_question", "praise", "criticism", "spam", "idea", "other")


class Feedback(IdMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("workspace_id", "channel_type", "external_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    channel_type: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    publication_id: Mapped[str | None] = mapped_column(ForeignKey("publications.id"))
    author: Mapped[str] = mapped_column(String(120), default="")
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime]
    category: Mapped[str | None] = mapped_column(String(30))
    suggested_reply: Mapped[str | None] = mapped_column(Text)
    handled: Mapped[bool] = mapped_column(default=False)
    hidden: Mapped[bool] = mapped_column(default=False)
    alerted: Mapped[bool] = mapped_column(default=False)


class CalendarSlot(IdMixin, Base):
    """kind: post | reel | story. needs_media: waiting for raw media from the admin."""

    __tablename__ = "calendar_slots"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10), default="post")
    pillar: Mapped[str | None] = mapped_column(String(40))
    goal: Mapped[str | None] = mapped_column(String(20))
    tag: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    occasion: Mapped[str | None] = mapped_column(String(120))
    offer_id: Mapped[str | None] = mapped_column(ForeignKey("offers.id"))
    post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id"))
    idea_id: Mapped[str | None] = mapped_column(ForeignKey("content_ideas.id"))
    needs_media: Mapped[bool] = mapped_column(default=True)
    request_sent_at: Mapped[datetime | None]


class Audit(IdMixin, Base):
    """A page audit (the lead magnet). Anyone may request one; a phone is
    required. input_kind: screenshots | instagram_api | manual."""

    __tablename__ = "audits"
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    handle: Mapped[str] = mapped_column(String(60))
    vertical: Mapped[str] = mapped_column(String(40))
    phone: Mapped[str] = mapped_column(String(11))
    agency_id: Mapped[str | None] = mapped_column(ForeignKey("agencies.id"))
    input_kind: Mapped[str] = mapped_column(String(20))
    screenshot_keys: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    total: Mapped[int | None]
    fixes: Mapped[list] = mapped_column(JSON, default=list)
    rewrites: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    error: Mapped[str | None] = mapped_column(String(300))
    wants_service: Mapped[bool] = mapped_column(default=False)


class Competitor(IdMixin, Base):
    """kind: direct | substitute | pattern."""

    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("workspace_id", "handle"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    handle: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(20), default="direct")
    followers: Mapped[int | None]
    posts_per_week: Mapped[float | None]
    engagement_rate: Mapped[float | None]
    best_hook: Mapped[str | None] = mapped_column(String(120))
    last_collected_at: Mapped[datetime | None]
    # Public profile, read from Meta (Business Discovery).
    ig_id: Mapped[str | None] = mapped_column(String(40))
    biography: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str | None] = mapped_column(String(300))
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    media_count: Mapped[int | None]
    # idle | queued | fetching | analyzing | done | failed
    fetch_status: Mapped[str] = mapped_column(String(20), default="idle")
    fetch_error: Mapped[str | None] = mapped_column(String(500))
    # {"summary": str, "best_types": [{type, why}], "best_topics": [{topic, why}], "at": iso}
    insight: Mapped[dict | None] = mapped_column(JSON)


class CompetitorPost(IdMixin, Base):
    """Public numbers only; no personal data about commenters is stored."""

    __tablename__ = "competitor_posts"
    __table_args__ = (UniqueConstraint("competitor_id", "url"),)
    competitor_id: Mapped[str] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(300))
    posted_at: Mapped[datetime | None]
    format: Mapped[str | None] = mapped_column(String(20))  # reel | carousel | image
    duration_s: Mapped[int | None]
    views: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    caption: Mapped[str] = mapped_column(Text, default="")
    offer_price: Mapped[str | None] = mapped_column(String(120))
    hook_type: Mapped[str | None] = mapped_column(String(40))
    ratio_to_avg: Mapped[float | None]
    external_id: Mapped[str | None] = mapped_column(String(40))
    media_url: Mapped[str | None] = mapped_column(Text)
    # Set by the AI: what kind of content (CONTENT_TYPES) and what it is about.
    content_type: Mapped[str | None] = mapped_column(String(40))
    topic: Mapped[str | None] = mapped_column(String(80))


class CompetitorAnalysis(IdMixin, Base):
    """patterns [{name, ratio, example}], suggestions [{text, tag, idea_id}], gaps [str]."""

    __tablename__ = "competitor_analyses"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    patterns: Mapped[list] = mapped_column(JSON, default=list)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)


class Report(IdMixin, Base):
    __tablename__ = "reports"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    insights: Mapped[dict] = mapped_column(JSON, default=dict)
    text: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime | None]
