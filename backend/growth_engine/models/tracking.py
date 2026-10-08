"""Measurement: tracked links, clicks, coupons, offers, registrations."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin


class TrackedLink(IdMixin, Base):
    """eng.ir/b/<code> -> target. Carries the attribution of whatever it is on."""

    __tablename__ = "tracked_links"
    code: Mapped[str] = mapped_column(String(16), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    target_url: Mapped[str] = mapped_column(String(500))
    channel_type: Mapped[str | None] = mapped_column(String(20))
    post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id"))
    tag: Mapped[str | None] = mapped_column(String(60))
    influencer: Mapped[str | None] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(120), default="")


class Click(IdMixin, Base):
    __tablename__ = "clicks"
    link_id: Mapped[str] = mapped_column(ForeignKey("tracked_links.id", ondelete="CASCADE"))
    at: Mapped[datetime]
    visitor_id: Mapped[str] = mapped_column(String(32))
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class Coupon(IdMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (UniqueConstraint("workspace_id", "code"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(30))
    influencer: Mapped[str | None] = mapped_column(String(80))
    discount_percent: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)


class Offer(IdMixin, Base):
    """Something people register and pay for (a program, a course).
    Its date is also a business event the calendar pins."""

    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("workspace_id", "slug"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    price_toman: Mapped[int] = mapped_column(default=0)
    capacity: Mapped[int | None]
    starts_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(default=True)


class Registration(IdMixin, Base):
    """status: pending_payment | paid | failed. Attribution is first touch:
    the visitor's first tracked link (cookie) unless a coupon is entered."""

    __tablename__ = "registrations"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.id"))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(11))
    city: Mapped[str] = mapped_column(String(80), default="")
    media_consent: Mapped[bool] = mapped_column(default=False)
    amount_toman: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending_payment")
    visitor_id: Mapped[str | None] = mapped_column(String(32))
    source_link_id: Mapped[str | None] = mapped_column(ForeignKey("tracked_links.id"))
    source_coupon_id: Mapped[str | None] = mapped_column(ForeignKey("coupons.id"))
    authority: Mapped[str | None] = mapped_column(String(64), unique=True)
    ref_id: Mapped[str | None] = mapped_column(String(64))
    paid_at: Mapped[datetime | None]


class FunnelEvent(IdMixin, Base):
    """Steps between a click and a payment that no other row records
    (kind: form_view | form_start | bot_message | purchase_question)."""

    __tablename__ = "funnel_events"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    at: Mapped[datetime]
    visitor_id: Mapped[str | None] = mapped_column(String(32))
    link_id: Mapped[str | None] = mapped_column(ForeignKey("tracked_links.id"))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class KeywordReply(IdMixin, Base):
    """'Send the word X to our bot': the bot's answer and the lead it records."""

    __tablename__ = "keyword_replies"
    __table_args__ = (UniqueConstraint("workspace_id", "keyword"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(60))
    reply_text: Mapped[str] = mapped_column(Text)
    offer_id: Mapped[str | None] = mapped_column(ForeignKey("offers.id"))


class Lead(IdMixin, Base):
    __tablename__ = "leads"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    platform_user_id: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120), default="")
    keyword: Mapped[str | None] = mapped_column(String(60))
    at: Mapped[datetime]
