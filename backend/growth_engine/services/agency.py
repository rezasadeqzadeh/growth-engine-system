"""Agencies (P3): one operator runs many client workspaces, optionally
under its own brand (white label: name, logo, colour, link domain)."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..errors import AppError, Forbidden, NotFound
from ..i18n import t
from ..models import Agency, Feedback, Post, Registration, User, Workspace

WHITE_LABEL_KEYS = ("display_name", "logo_key", "primary_color", "link_domain")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9-]+\.)+[a-z]{2,}$")


def create(s: Session, owner: User, name: str) -> Agency:
    if not name.strip():
        raise AppError("name_required", "Name is required")
    agency = Agency(name=name.strip()[:120], owner_id=owner.id, white_label={})
    s.add(agency)
    s.flush()
    return agency


def owned(s: Session, user: User, agency_id: str) -> Agency:
    agency = s.get(Agency, agency_id)
    if agency is None:
        raise NotFound("agency")
    if agency.owner_id != user.id:
        raise Forbidden("agency_forbidden", "Not your agency")
    return agency


def set_white_label(agency: Agency, values: dict) -> Agency:
    out = dict(agency.white_label or {})
    for key in WHITE_LABEL_KEYS:
        if key not in values:
            continue
        value = values[key]
        if key == "primary_color" and value and not HEX.match(value):
            raise AppError("color_invalid", "Colour must be #RRGGBB")
        if key == "link_domain" and value and not DOMAIN.match(value.lower()):
            raise AppError("domain_invalid", "Enter a domain like go.example.ir")
        out[key] = value
    agency.white_label = out
    return agency


def overview(s: Session, agency: Agency) -> list[dict]:
    """Every client at a glance: drafts waiting, registrations this month, unanswered questions."""
    month_start = db.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for ws in s.scalars(select(Workspace).where(Workspace.agency_id == agency.id).order_by(Workspace.name)):
        rows.append({
            "id": ws.id, "name": ws.name, "slug": ws.slug, "plan": ws.plan,
            "pending": s.scalar(select(func.count()).select_from(Post).where(
                Post.workspace_id == ws.id, Post.status == "pending")) or 0,
            "registrations_month": s.scalar(select(func.count()).select_from(Registration).where(
                Registration.workspace_id == ws.id, Registration.status == "paid",
                Registration.paid_at >= month_start)) or 0,
            "open_questions": s.scalar(select(func.count()).select_from(Feedback).where(
                Feedback.workspace_id == ws.id, Feedback.category == "purchase_question",
                Feedback.handled.is_(False))) or 0,
        })
    return rows


def brand_for(s: Session, ws: Workspace) -> dict:
    """What a workspace's public pages and panel show as the product brand."""
    agency = s.get(Agency, ws.agency_id) if ws.agency_id else None
    label = (agency.white_label if agency else {}) or {}
    return {"display_name": label.get("display_name") or t("brand.product_name"),
            "primary_color": label.get("primary_color") or "#8B5E3C",
            "logo_key": label.get("logo_key")}
