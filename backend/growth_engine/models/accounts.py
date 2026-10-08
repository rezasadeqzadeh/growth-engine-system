"""People, agencies and workspaces (one workspace per business: the tenant)."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin


class User(IdMixin, Base):
    __tablename__ = "users"
    phone: Mapped[str] = mapped_column(String(11), unique=True)
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | superadmin


class OtpCode(Base):
    __tablename__ = "otp_codes"
    phone: Mapped[str] = mapped_column(String(11), primary_key=True)
    code: Mapped[str] = mapped_column(String(8))
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(default=0)
    pending_first_name: Mapped[str | None] = mapped_column(String(80))
    pending_last_name: Mapped[str | None] = mapped_column(String(80))


class Agency(IdMixin, Base):
    """An operator business that runs many workspaces (P3 agency panel).

    `white_label` = {display_name, logo_key, primary_color, link_domain}:
    what clients of the agency see instead of the Growth Engine brand.
    """

    __tablename__ = "agencies"
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    white_label: Mapped[dict] = mapped_column(JSON, default=dict)


class Workspace(IdMixin, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    vertical: Mapped[str] = mapped_column(String(40))
    plan: Mapped[str] = mapped_column(String(20), default="free")
    agency_id: Mapped[str | None] = mapped_column(ForeignKey("agencies.id"))
    # {auto_approve_consent, best_hour, home_city, weekly_slots{post, reel, story},
    #  goal_mix{attract, trust, convert}, event_tags{announce, report},
    #  baseline{registrations, admin_hours_per_week, outside_city}}
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Membership(IdMixin, Base):
    """A person in a workspace. A bot-only admin has no `user_id`.

    Roles: owner (everything), operator (panel work), approver (may approve
    in the bot), sender (may only send raw media).
    """

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="sender")
    bale_user_id: Mapped[str | None] = mapped_column(String(32))
    telegram_user_id: Mapped[str | None] = mapped_column(String(32))
    # One-time code the person sends to the bot (/start CODE) to bind it.
    link_code: Mapped[str | None] = mapped_column(String(12), unique=True)

    def can_approve(self) -> bool:
        return self.role in ("owner", "operator", "approver")
