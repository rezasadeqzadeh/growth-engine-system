"""Self-serve plans, paid through Zarinpal; a paid plan lasts until changed."""

from sqlalchemy.orm import Session

from .. import db
from ..config import get_settings
from ..errors import AppError, NotFound
from ..models import PlanPayment, Workspace
from . import usage, zarinpal


def start(s: Session, ws: Workspace, plan: str, mobile: str | None) -> dict:
    plans = usage.plans()
    if plan not in plans or plan == "free":
        raise AppError("plan_unknown", "Unknown plan")
    if plan == "agency" and not ws.agency_id:
        raise AppError("plan_needs_agency", "The agency plan is for agency workspaces")
    amount = int(plans[plan]["price_toman"])
    payment = PlanPayment(workspace_id=ws.id, plan=plan, amount_toman=amount)
    s.add(payment)
    s.flush()
    callback = f"{get_settings().public_base_url}/api/billing/callback?p={payment.id}"
    try:
        result = zarinpal.request_payment(amount, f"Growth Engine plan {plan}: {ws.name}", callback, mobile)
    except zarinpal.ZarinpalError as exc:
        raise AppError("payment_unavailable", "The payment gateway is not answering", 502) from exc
    payment.authority = result["authority"]
    return {"payment_url": result["payment_url"]}


def verify(s: Session, payment_id: str, authority: str, status: str) -> PlanPayment:
    payment = s.get(PlanPayment, payment_id)
    if payment is None or payment.authority != authority:
        raise NotFound("payment")
    if payment.status == "paid":
        return payment
    if status != "OK":
        payment.status = "failed"
        return payment
    try:
        result = zarinpal.verify_payment(payment.amount_toman, authority)
    except zarinpal.ZarinpalError:
        payment.status = "failed"
        return payment
    payment.status, payment.ref_id, payment.paid_at = "paid", result["ref_id"], db.utcnow()
    ws = s.get(Workspace, payment.workspace_id)
    ws.plan = payment.plan
    return payment
