"""Connected channels. Credentials never leave the backend."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin

CHANNEL_TYPES = ("bale", "telegram", "aparat", "eitaa", "rubika", "instagram", "site")


class Channel(IdMixin, Base):
    """config: non-secret settings (chat_id, username, aparat category...).
    credentials: secrets (bot token, access token). Never serialized out."""

    __tablename__ = "channels"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120), default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    credentials: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    health_ok: Mapped[bool | None]
    health_checked_at: Mapped[datetime | None]
    health_error: Mapped[str | None] = mapped_column(String(300))

    def secrets(self) -> list[str]:
        return [str(v) for v in (self.credentials or {}).values() if v]
