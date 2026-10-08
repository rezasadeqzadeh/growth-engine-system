"""Brand kit (the business's design tokens) and tag recipes."""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, IdMixin


class BrandKit(IdMixin, Base):
    """One row per version; the newest `is_current` row is the one in use.

    colors   {primary: [hex, hex], accent: [hex, hex], text: hex, names: {...}}
    fonts    {heading, body}           file names under BRAND_FONTS_DIR
    tone     {adjectives[3], anti[3], do[], dont[]}
    pillars  [{key, name, goal}]       goal: attract | trust | convert
    glossary [str]                     proper names spelled correctly
    banned   [str]                     the "never on my page" list
    templates {reel_cover, carousel, story_announce, intro_outro}
    bio      {suggestions[3], highlights[{name, cover}]}
    """

    __tablename__ = "brand_kits"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(default=1)
    is_current: Mapped[bool] = mapped_column(default=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    colors: Mapped[dict] = mapped_column(JSON, default=dict)
    fonts: Mapped[dict] = mapped_column(JSON, default=dict)
    tone: Mapped[dict] = mapped_column(JSON, default=dict)
    pillars: Mapped[list] = mapped_column(JSON, default=list)
    glossary: Mapped[list] = mapped_column(JSON, default=list)
    banned: Mapped[list] = mapped_column(JSON, default=list)
    templates: Mapped[dict] = mapped_column(JSON, default=dict)
    bio: Mapped[dict] = mapped_column(JSON, default=dict)
    logo_key: Mapped[str | None] = mapped_column(String(200))


class TagRecipe(IdMixin, Base):
    """A tag is a full recipe: the admin writes one word, the system knows the rest.

    video_spec {min_s, max_s, aspects[], subtitle_mode: word|sentence|none,
                overlay: date_price|title|name_role|none, music: bool}
    timing     {mode: immediate|next_day_evening|best_hour, hour?, reminder_days?}
    """

    __tablename__ = "tag_recipes"
    __table_args__ = (UniqueConstraint("workspace_id", "tag"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    tag: Mapped[str] = mapped_column(String(60))
    goal: Mapped[str] = mapped_column(String(20))
    pillar: Mapped[str | None] = mapped_column(String(40))
    caption_style: Mapped[str] = mapped_column(String(500), default="")
    cta: Mapped[str] = mapped_column(String(200), default="")
    video_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    timing: Mapped[dict] = mapped_column(JSON, default=dict)
    # Low-risk tags may auto-publish after 24h without an answer, but only
    # when the workspace owner gave that consent beforehand.
    low_risk: Mapped[bool] = mapped_column(default=False)
