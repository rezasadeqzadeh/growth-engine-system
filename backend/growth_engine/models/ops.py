"""Operational tables: job queue, AI cache and usage, plan payments, bot dedupe."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin


class Job(IdMixin, Base):
    """A unit of background work. queue: default | media (the media worker
    runs on its own server and only claims `media`)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "queue", "status", "run_at"),)
    queue: Mapped[str] = mapped_column(String(20), default="default")
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    run_at: Mapped[datetime]
    locked_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    # Same key = same work; enqueue is a no-op while one is queued/running.
    dedupe_key: Mapped[str | None] = mapped_column(String(160), index=True)


class AICache(Base):
    __tablename__ = "ai_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    response: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class UsageCounter(IdMixin, Base):
    """Per workspace per month: what the plan caps (videos, ai_calls)."""

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("workspace_id", "month", "metric"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))  # 2026-10
    metric: Mapped[str] = mapped_column(String(20))
    value: Mapped[int] = mapped_column(default=0)


class PlanPayment(IdMixin, Base):
    """Self-serve plan purchase through Zarinpal."""

    __tablename__ = "plan_payments"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    plan: Mapped[str] = mapped_column(String(20))
    amount_toman: Mapped[int]
    authority: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    ref_id: Mapped[str | None] = mapped_column(String(64))
    paid_at: Mapped[datetime | None]


class BotUpdate(Base):
    """Seen bot updates: webhooks are retried, an update is handled once."""

    __tablename__ = "bot_updates"
    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    update_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    at: Mapped[datetime]


class BotSession(Base):
    """What a bot user is in the middle of (e.g. typing a caption edit)."""

    __tablename__ = "bot_sessions"
    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(IdMixin, Base):
    """Who did what (approve, reject, publish); also feeds admin-time estimates."""

    __tablename__ = "audit_log"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_member_id: Mapped[str | None] = mapped_column(ForeignKey("memberships.id"))
    action: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
