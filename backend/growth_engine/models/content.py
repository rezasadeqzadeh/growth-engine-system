"""Raw media, posts, per-channel variants, publications and their metrics."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin

POST_STATUSES = ("processing", "draft", "pending", "approved", "scheduled", "published", "rejected", "failed")


class MediaAsset(IdMixin, Base):
    """A video (or voice note) the admin sent. `transcript` is
    {language, segments: [{start, end, text, words: [{start, end, word}]}]}."""

    __tablename__ = "media_assets"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    source_platform: Mapped[str] = mapped_column(String(20))  # bale | telegram | upload
    source_chat_id: Mapped[str | None] = mapped_column(String(40))
    source_msg_id: Mapped[str | None] = mapped_column(String(40))
    sender_member_id: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"))
    file_key: Mapped[str | None] = mapped_column(String(200))
    duration_s: Mapped[float | None]
    width: Mapped[int | None]
    height: Mapped[int | None]
    transcript: Mapped[dict | None] = mapped_column(JSON)
    faces_detected: Mapped[int] = mapped_column(default=0)
    note_text: Mapped[str] = mapped_column(Text, default="")


class Post(IdMixin, Base):
    __tablename__ = "posts"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"))
    recipe_id: Mapped[str | None] = mapped_column(ForeignKey("tag_recipes.id"))
    tag: Mapped[str | None] = mapped_column(String(60))
    tag_guessed: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    title: Mapped[str] = mapped_column(String(200), default="")
    raw_note: Mapped[str] = mapped_column(Text, default="")
    output_duration_s: Mapped[float | None]  # length of the short version
    qc: Mapped[list] = mapped_column(JSON, default=list)  # [{check, ok, message}]
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"))
    approved_at: Mapped[datetime | None]
    scheduled_at: Mapped[datetime | None]
    auto_approve_at: Mapped[datetime | None]
    rejected_reason: Mapped[str | None] = mapped_column(String(300))
    rating: Mapped[int | None]  # admin's 1..5 score, feeds the content bank
    error: Mapped[str | None] = mapped_column(String(500))
    # Where the approval card was sent: [{platform, chat_id, message_id}]
    cards: Mapped[list] = mapped_column(JSON, default=list)


class PostVariant(IdMixin, Base):
    """What one channel gets. kind: reel | story | full | message."""

    __tablename__ = "post_variants"
    __table_args__ = (UniqueConstraint("post_id", "channel_id", "kind"),)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"))
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"))
    kind: Mapped[str] = mapped_column(String(20), default="reel")
    video_key: Mapped[str | None] = mapped_column(String(200))
    cover_key: Mapped[str | None] = mapped_column(String(200))
    srt_key: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    tracked_link_id: Mapped[str | None] = mapped_column(ForeignKey("tracked_links.id"))


class Publication(IdMixin, Base):
    """status: published | failed | handoff_pending (Instagram one-click handoff)."""

    __tablename__ = "publications"
    variant_id: Mapped[str] = mapped_column(ForeignKey("post_variants.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[datetime | None]
    external_id: Mapped[str | None] = mapped_column(String(120))
    external_url: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(default=0)


class MetricSnapshot(IdMixin, Base):
    __tablename__ = "metric_snapshots"
    publication_id: Mapped[str] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"))
    at: Mapped[datetime]
    views: Mapped[int | None]
    reach: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    saves: Mapped[int | None]
    shares: Mapped[int | None]
    source: Mapped[str] = mapped_column(String(10))  # api | ocr | public


class ContentIdea(IdMixin, Base):
    """The idea and content bank: fills empty calendar slots.

    source: feedback | competitor | ai | manual | approved_caption
    """

    __tablename__ = "content_ideas"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    pillar: Mapped[str | None] = mapped_column(String(40))
    tag: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20))
    used: Mapped[bool] = mapped_column(default=False)
    score: Mapped[int] = mapped_column(default=0)
