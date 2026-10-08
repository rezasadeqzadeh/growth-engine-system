"""Offers and registrations: where a post turns into a sign-up and a payment.

Attribution: a coupon entered on the form wins (influencer codes);
otherwise the visitor's first tracked link in this workspace.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..auth.otp import PHONE_RE
from ..config import get_settings
from ..errors import AppError, NotFound
from ..models import Coupon, Offer, Registration, Workspace
from . import links, zarinpal


def seats_taken(s: Session, offer: Offer) -> int:
    return s.scalar(select(func.count()).select_from(Registration).where(
        Registration.offer_id == offer.id, Registration.status == "paid")) or 0


def seats_left(s: Session, offer: Offer) -> int | None:
    return None if offer.capacity is None else max(offer.capacity - seats_taken(s, offer), 0)


def find_offer(s: Session, ws_slug: str, offer_slug: str) -> tuple[Workspace, Offer]:
    ws = s.scalar(select(Workspace).where(Workspace.slug == ws_slug))
    offer = ws and s.scalar(select(Offer).where(Offer.workspace_id == ws.id, Offer.slug == offer_slug))
    if not ws or not offer:
        raise NotFound("offer")
    return ws, offer


def price_after(offer: Offer, coupon: Coupon | None) -> int:
    if coupon is None or not coupon.discount_percent:
        return offer.price_toman
    return offer.price_toman * (100 - min(coupon.discount_percent, 100)) // 100


def register(s: Session, ws: Workspace, offer: Offer, *, name: str, phone: str, city: str, media_consent: bool,
             coupon_code: str, visitor_id: str | None, first_touch_cookie: str | None) -> dict:
    if not offer.active:
        raise AppError("offer_closed", "Registration is closed", 409)
    if not name.strip():
        raise AppError("name_required", "Name is required")
    if not PHONE_RE.match(phone):
        raise AppError("phone_invalid", "Phone must match 09xxxxxxxxx")
    left = seats_left(s, offer)
    if left is not None and left <= 0:
        raise AppError("offer_full", "No seats left", 409)
    coupon = None
    if coupon_code.strip():
        coupon = s.scalar(select(Coupon).where(Coupon.workspace_id == ws.id, Coupon.active,
                                               func.upper(Coupon.code) == coupon_code.strip().upper()))
        if coupon is None:
            raise AppError("coupon_invalid", "This code is not valid")
    link = None if coupon else links.first_touch(s, ws.id, first_touch_cookie)
    amount = price_after(offer, coupon)
    reg = Registration(workspace_id=ws.id, offer_id=offer.id, name=name.strip()[:120], phone=phone,
                       city=city.strip()[:80], media_consent=media_consent, amount_toman=amount,
                       visitor_id=visitor_id, source_link_id=link.id if link else None,
                       source_coupon_id=coupon.id if coupon else None)
    s.add(reg)
    s.flush()
    if amount == 0:
        reg.status, reg.paid_at = "paid", db.utcnow()
        return {"registration_id": reg.id, "paid": True}
    callback = f"{get_settings().public_base_url}/pay/registration?r={reg.id}"
    try:
        pay = zarinpal.request_payment(amount, f"{ws.name}: {offer.title}", callback, phone)
    except zarinpal.ZarinpalError as exc:
        raise AppError("payment_unavailable", "The payment gateway is not answering", 502) from exc
    reg.authority = pay["authority"]
    return {"registration_id": reg.id, "paid": False, "payment_url": pay["payment_url"]}


def verify(s: Session, registration_id: str, authority: str, status: str) -> Registration:
    reg = s.get(Registration, registration_id)
    if reg is None or reg.authority != authority:
        raise NotFound("registration")
    if reg.status == "paid":
        return reg  # a repeated callback
    if status != "OK":
        reg.status = "failed"
        return reg
    try:
        result = zarinpal.verify_payment(reg.amount_toman, authority)
    except zarinpal.ZarinpalError:
        reg.status = "failed"
        return reg
    reg.status, reg.ref_id, reg.paid_at = "paid", result["ref_id"], db.utcnow()
    return reg
