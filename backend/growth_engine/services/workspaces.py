"""Workspaces: each new business is a copy of its vertical's template."""

import json
import re
import secrets
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import Agency, BrandKit, Channel, Membership, TagRecipe, User, Workspace
from . import brand_kit, usage

VERTICALS_DIR = Path(__file__).resolve().parent.parent / "data" / "verticals"


@lru_cache
def vertical(name: str) -> dict:
    path = VERTICALS_DIR / f"{name}.json"
    if not path.is_file():
        raise AppError("vertical_unknown", f"Unknown vertical: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def verticals() -> dict[str, str]:
    return {p.stem: vertical(p.stem)["title"] for p in sorted(VERTICALS_DIR.glob("*.json"))}


def _slugify(name: str, s: Session) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "ws"
    slug = base
    while s.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def create_workspace(s: Session, owner: User, name: str, vertical_name: str, slug: str | None = None,
                     agency_id: str | None = None) -> Workspace:
    template = vertical(vertical_name)
    if agency_id:
        agency = s.get(Agency, agency_id)
        if agency is None or agency.owner_id != owner.id:
            raise AppError("agency_forbidden", "Not your agency", 403)
        count = s.scalar(select(func.count()).select_from(Workspace).where(Workspace.agency_id == agency_id)) or 0
        if count >= usage.limit_for("agency", "workspaces"):
            raise AppError("plan_limit_reached", "The agency plan's workspace limit is reached", 402)
    if slug and s.scalar(select(Workspace.id).where(Workspace.slug == slug)):
        raise AppError("slug_taken", "This address is taken")
    ws = Workspace(
        name=name, vertical=vertical_name, slug=slug or _slugify(name, s), agency_id=agency_id,
        plan="agency" if agency_id else "free",
        settings={"weekly_slots": template["weekly_slots"], "goal_mix": template["goal_mix"],
                  "event_tags": template["event_tags"],
                  "best_hour": 20, "auto_approve_consent": False},
    )
    s.add(ws)
    s.flush()
    s.add(Membership(workspace_id=ws.id, user_id=owner.id, role="owner",
                     display_name=" ".join(filter(None, [owner.first_name, owner.last_name]))))
    s.add(BrandKit(workspace_id=ws.id, version=1, pillars=template["pillars"],
                   colors=dict(brand_kit.DEFAULT_COLORS), fonts=dict(brand_kit.DEFAULT_FONTS)))
    for recipe in template["recipes"]:
        s.add(TagRecipe(workspace_id=ws.id, **recipe))
    # The site is the owned channel every workspace has from day one.
    s.add(Channel(workspace_id=ws.id, type="site", name=name, config={}))
    s.flush()
    return ws


def workspaces_for(s: Session, user: User) -> list[Workspace]:
    member_of = select(Membership.workspace_id).where(Membership.user_id == user.id)
    agencies = select(Agency.id).where(Agency.owner_id == user.id)
    return list(s.scalars(select(Workspace).where(
        Workspace.id.in_(member_of) | Workspace.agency_id.in_(agencies)).order_by(Workspace.created_at)))


def new_link_code(s: Session) -> str:
    while True:
        code = secrets.token_hex(4).upper()
        if not s.scalar(select(Membership.id).where(Membership.link_code == code)):
            return code
