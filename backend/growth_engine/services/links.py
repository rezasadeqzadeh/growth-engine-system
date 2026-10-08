"""Tracked links: the backbone of measurement.

<base>/b/r1203 -> tenant, channel, post, tag. A visitor's first tracked
link in a workspace is remembered in a cookie (first touch); a registration
is credited to it unless the registrant enters a coupon code.
"""

import secrets
import string

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..config import get_settings
from ..errors import NotFound
from ..models import Agency, Click, Offer, Post, TrackedLink, Workspace

# One letter says where the link sits: r = reel, t = telegram, ...
CHANNEL_PREFIX = {"instagram": "r", "story": "s", "telegram": "t", "bale": "b", "aparat": "a",
                  "eitaa": "e", "rubika": "k", "site": "w", "influencer": "i", "bot": "m"}
_ALPHABET = string.ascii_lowercase + string.digits
FIRST_TOUCH_COOKIE = "ge_ft"
VISITOR_COOKIE = "ge_vid"


def base_url(s: Session, workspace_id: str) -> str:
    """An agency's white-label link domain when it has one (DNS must point here)."""
    ws = s.get(Workspace, workspace_id)
    agency = s.get(Agency, ws.agency_id) if ws and ws.agency_id else None
    domain = ((agency.white_label or {}).get("link_domain") if agency else None)
    return f"https://{domain}" if domain else get_settings().public_base_url


def short_url(link: TrackedLink, base: str | None = None) -> str:
    return f"{base or get_settings().public_base_url}/b/{link.code}"


def _new_code(s: Session, prefix: str) -> str:
    while True:
        code = prefix + "".join(secrets.choice(_ALPHABET) for _ in range(5))
        if not s.scalar(select(TrackedLink.id).where(TrackedLink.code == code)):
            return code


def create(s: Session, workspace_id: str, target_url: str, *, channel_type: str | None = None,
           post_id: str | None = None, tag: str | None = None, influencer: str | None = None,
           label: str = "", prefix_key: str | None = None) -> TrackedLink:
    prefix = CHANNEL_PREFIX.get(prefix_key or channel_type or "", "x")
    link = TrackedLink(code=_new_code(s, prefix), workspace_id=workspace_id, target_url=target_url,
                       channel_type=channel_type, post_id=post_id, tag=tag, influencer=influencer, label=label)
    s.add(link)
    s.flush()
    return link


def site_url(ws: Workspace, path: str = "") -> str:
    return f"{get_settings().public_base_url}/s/{ws.slug}{path}"


def offer_url(ws: Workspace, offer: Offer) -> str:
    return f"{get_settings().public_base_url}/o/{ws.slug}/{offer.slug}"


def destination_for(s: Session, post: Post) -> str:
    """Where a post sends people: the next open offer for a selling post,
    otherwise the post's own page on the site."""
    ws = s.get(Workspace, post.workspace_id)
    assert ws is not None
    offer = s.scalar(select(Offer).where(Offer.workspace_id == ws.id, Offer.active,
                                         (Offer.starts_at.is_(None)) | (Offer.starts_at > db.utcnow()))
                     .order_by(Offer.starts_at.is_(None), Offer.starts_at))
    if offer is not None:
        return offer_url(ws, offer)
    return site_url(ws, f"/p/{post.id}")


def record_click(s: Session, code: str, visitor_id: str, user_agent: str) -> TrackedLink:
    link = s.scalar(select(TrackedLink).where(TrackedLink.code == code))
    if link is None:
        raise NotFound("link")
    s.add(Click(link_id=link.id, at=db.utcnow(), visitor_id=visitor_id, user_agent=user_agent[:300]))
    return link


def first_touch(s: Session, workspace_id: str, cookie_value: str | None) -> TrackedLink | None:
    """The cookie holds `<workspace>:<code>,...` pairs; one first link per workspace."""
    for pair in (cookie_value or "").split(","):
        ws, _, code = pair.partition(":")
        if ws == workspace_id and code:
            return s.scalar(select(TrackedLink).where(TrackedLink.code == code,
                                                      TrackedLink.workspace_id == workspace_id))
    return None


def remember_first_touch(cookie_value: str | None, link: TrackedLink) -> str:
    pairs = [p for p in (cookie_value or "").split(",") if p]
    if any(p.startswith(f"{link.workspace_id}:") for p in pairs):
        return ",".join(pairs)
    return ",".join(pairs[-9:] + [f"{link.workspace_id}:{link.code}"])
