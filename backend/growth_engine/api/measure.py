"""Measurement and the things it counts: offers, coupons, links, keywords,
leads, registrations, ideas and weekly reports."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError, NotFound
from ..jobs import queue
from ..models import Click, ContentIdea, Coupon, KeywordReply, Lead, Offer, Registration, Report, TrackedLink
from ..services import links, metrics, offers

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["measure"])


class OfferIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]{2,60}$")
    title: str = Field(min_length=2, max_length=200)
    description: str = ""
    price_toman: int = Field(ge=0)
    capacity: int | None = Field(default=None, ge=1)
    starts_at: datetime | None = None
    active: bool = True


class CouponIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{2,30}$")
    influencer: str | None = None
    discount_percent: int = Field(default=0, ge=0, le=100)
    active: bool = True


class LinkIn(BaseModel):
    target_url: str = Field(min_length=8, max_length=500)
    label: str = ""
    influencer: str | None = None
    channel_type: str | None = None


class KeywordIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=60)
    reply_text: str = Field(min_length=1, max_length=4000)
    offer_id: str | None = None


class IdeaIn(BaseModel):
    text: str = Field(min_length=2, max_length=1000)
    pillar: str | None = None
    tag: str | None = None


def _own(s: Session, model, a: Access, row_id: str, what: str):
    row = s.get(model, row_id)
    if row is None or row.workspace_id != a.workspace.id:
        raise NotFound(what)
    return row


@router.get("/dashboard")
def dashboard(days: int = 30, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    return metrics.dashboard(s, a.workspace, min(max(days, 1), 365))


# Offers -------------------------------------------------------------------

def offer_out(s: Session, a: Access, o: Offer) -> dict:
    return {"id": o.id, "slug": o.slug, "title": o.title, "description": o.description, "price_toman": o.price_toman,
            "capacity": o.capacity, "seats_left": offers.seats_left(s, o), "active": o.active,
            "starts_at": o.starts_at.isoformat() if o.starts_at else None, "url": links.offer_url(a.workspace, o)}


@router.get("/offers")
def list_offers(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Offer).where(Offer.workspace_id == a.workspace.id).order_by(Offer.starts_at.desc()))
    return {"offers": [offer_out(s, a, o) for o in rows]}


@router.post("/offers")
def create_offer(body: OfferIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if s.scalar(select(Offer.id).where(Offer.workspace_id == a.workspace.id, Offer.slug == body.slug)):
        raise AppError("slug_taken", "This address is taken", 409)
    o = Offer(workspace_id=a.workspace.id, **body.model_dump())
    s.add(o)
    s.flush()
    return offer_out(s, a, o)


@router.put("/offers/{offer_id}")
def update_offer(offer_id: str, body: OfferIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    o = _own(s, Offer, a, offer_id, "offer")
    for key, value in body.model_dump().items():
        setattr(o, key, value)
    return offer_out(s, a, o)


@router.get("/registrations")
def registrations(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.execute(select(Registration, Offer.title, TrackedLink.code, TrackedLink.tag, Coupon.code)
                     .join(Offer, Offer.id == Registration.offer_id)
                     .outerjoin(TrackedLink, TrackedLink.id == Registration.source_link_id)
                     .outerjoin(Coupon, Coupon.id == Registration.source_coupon_id)
                     .where(Registration.workspace_id == a.workspace.id)
                     .order_by(Registration.created_at.desc()).limit(500))
    return {"registrations": [{
        "id": r.id, "offer": title, "name": r.name, "phone": r.phone, "city": r.city, "status": r.status,
        "amount_toman": r.amount_toman, "media_consent": r.media_consent, "source_link": code, "tag": tag,
        "coupon": coupon, "paid_at": r.paid_at.isoformat() if r.paid_at else None} for r, title, code, tag, coupon in rows]}


# Coupons and links ----------------------------------------------------------

@router.get("/coupons")
def list_coupons(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Coupon).where(Coupon.workspace_id == a.workspace.id).order_by(Coupon.code))
    return {"coupons": [{"id": c.id, "code": c.code, "influencer": c.influencer,
                         "discount_percent": c.discount_percent, "active": c.active} for c in rows]}


@router.post("/coupons")
def create_coupon(body: CouponIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if s.scalar(select(Coupon.id).where(Coupon.workspace_id == a.workspace.id,
                                        func.upper(Coupon.code) == body.code.upper())):
        raise AppError("coupon_exists", "This code exists", 409)
    c = Coupon(workspace_id=a.workspace.id, **body.model_dump())
    s.add(c)
    s.flush()
    return {"id": c.id, "code": c.code}


@router.get("/links")
def list_links(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    clicks = (select(Click.link_id, func.count().label("n")).group_by(Click.link_id).subquery())
    rows = s.execute(select(TrackedLink, clicks.c.n).outerjoin(clicks, clicks.c.link_id == TrackedLink.id)
                     .where(TrackedLink.workspace_id == a.workspace.id)
                     .order_by(TrackedLink.created_at.desc()).limit(300))
    base = links.base_url(s, a.workspace.id)
    return {"links": [{"id": link.id, "url": links.short_url(link, base), "target": link.target_url,
                       "channel_type": link.channel_type, "tag": link.tag, "influencer": link.influencer,
                       "label": link.label, "clicks": n or 0} for link, n in rows]}


@router.post("/links")
def create_link(body: LinkIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    """Links outside posts: an influencer's link, the bio link, a printed QR code."""
    a.require("operator")
    link = links.create(s, a.workspace.id, body.target_url, channel_type=body.channel_type, influencer=body.influencer,
                        label=body.label, prefix_key="influencer" if body.influencer else body.channel_type)
    return {"id": link.id, "url": links.short_url(link, links.base_url(s, a.workspace.id))}


# Bot keywords and leads -----------------------------------------------------

@router.get("/keywords")
def list_keywords(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(KeywordReply).where(KeywordReply.workspace_id == a.workspace.id))
    return {"keywords": [{"id": k.id, "keyword": k.keyword, "reply_text": k.reply_text, "offer_id": k.offer_id}
                         for k in rows]}


@router.post("/keywords")
def create_keyword(body: KeywordIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if s.scalar(select(KeywordReply.id).where(KeywordReply.workspace_id == a.workspace.id,
                                              KeywordReply.keyword == body.keyword.strip())):
        raise AppError("keyword_exists", "This keyword exists", 409)
    k = KeywordReply(workspace_id=a.workspace.id, keyword=body.keyword.strip(), reply_text=body.reply_text,
                     offer_id=body.offer_id)
    s.add(k)
    s.flush()
    return {"id": k.id}


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    s.delete(_own(s, KeywordReply, a, keyword_id, "keyword"))
    return {"ok": True}


@router.get("/leads")
def list_leads(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Lead).where(Lead.workspace_id == a.workspace.id).order_by(Lead.at.desc()).limit(500))
    return {"leads": [{"id": x.id, "platform": x.platform, "name": x.name, "keyword": x.keyword,
                       "at": x.at.isoformat()} for x in rows]}


# Ideas and reports ----------------------------------------------------------

@router.get("/ideas")
def list_ideas(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(ContentIdea).where(ContentIdea.workspace_id == a.workspace.id)
                     .order_by(ContentIdea.used, ContentIdea.created_at.desc()).limit(300))
    return {"ideas": [{"id": i.id, "text": i.text, "pillar": i.pillar, "tag": i.tag, "source": i.source,
                       "used": i.used} for i in rows]}


@router.post("/ideas")
def create_idea(body: IdeaIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    idea = ContentIdea(workspace_id=a.workspace.id, source="manual", **body.model_dump())
    s.add(idea)
    s.flush()
    return {"id": idea.id}


@router.get("/reports")
def list_reports(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Report).where(Report.workspace_id == a.workspace.id).order_by(Report.period_start.desc()))
    return {"reports": [{"id": r.id, "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(),
                         "text": r.text, "sent": r.sent_at is not None} for r in rows]}


@router.post("/reports/run")
def run_report(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    queue.enqueue(s, "weekly_report", {"workspace_id": a.workspace.id}, dedupe_key=f"report-now:{a.workspace.id}")
    return {"queued": True}
