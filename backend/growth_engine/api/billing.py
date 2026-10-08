from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..config import get_settings
from ..db import get_session
from ..services import billing, usage

router = APIRouter(tags=["billing"])


class PlanIn(BaseModel):
    plan: str


@router.get("/plans")
def plans() -> dict:
    return {"plans": usage.plans()}


@router.post("/workspaces/{workspace_id}/billing/start")
def start(body: PlanIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("owner")
    return billing.start(s, a.workspace, body.plan, a.user.phone)


@router.get("/billing/callback")
def callback(p: str, Authority: str = "", Status: str = "", s: Session = Depends(get_session)) -> RedirectResponse:
    payment = billing.verify(s, p, Authority, Status)
    result = "paid" if payment.status == "paid" else "failed"
    return RedirectResponse(f"{get_settings().panel_url}/w/{payment.workspace_id}/settings?result={result}")
