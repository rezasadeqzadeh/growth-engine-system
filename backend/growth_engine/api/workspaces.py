from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access, current_user
from ..db import get_session
from ..errors import AppError, NotFound
from ..models import Membership, User, Workspace
from ..services import agency as agency_service
from ..services import usage, workspaces
from ..textnorm import DigitStr

router = APIRouter(tags=["workspaces"])

SETTING_KEYS = ("auto_approve_consent", "best_hour", "home_city", "weekly_slots", "goal_mix", "baseline")
ROLES = ("owner", "operator", "approver", "sender")


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    vertical: str
    slug: DigitStr | None = Field(default=None, pattern=r"^[a-z0-9-]{3,60}$")
    agency_id: str | None = None


class SettingsIn(BaseModel):
    name: str | None = None
    settings: dict = {}


class MemberIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    role: str


def workspace_out(s: Session, ws: Workspace, role: str | None = None) -> dict:
    return {"id": ws.id, "name": ws.name, "slug": ws.slug, "vertical": ws.vertical, "plan": ws.plan,
            "agency_id": ws.agency_id, "settings": ws.settings, "role": role,
            "brand": agency_service.brand_for(s, ws)}


def member_out(m: Membership) -> dict:
    return {"id": m.id, "display_name": m.display_name, "role": m.role, "user_id": m.user_id,
            "bale_bound": bool(m.bale_user_id), "telegram_bound": bool(m.telegram_user_id), "link_code": m.link_code}


@router.get("/verticals")
def verticals() -> dict:
    return {"verticals": workspaces.verticals()}


@router.get("/workspaces")
def list_workspaces(user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return {"workspaces": [workspace_out(s, ws) for ws in workspaces.workspaces_for(s, user)]}


@router.post("/workspaces")
def create_workspace(body: WorkspaceIn, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    ws = workspaces.create_workspace(s, user, body.name, body.vertical, body.slug, body.agency_id)
    return workspace_out(s, ws, "owner")


@router.get("/workspaces/{workspace_id}")
def get_workspace(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    out = workspace_out(s, a.workspace, a.role)
    out["usage"] = {m: {"used": usage.used(a.workspace.id, m), "limit": usage.limit_for(a.workspace.plan, m)}
                    for m in ("videos", "ai_calls")}
    return out


@router.patch("/workspaces/{workspace_id}")
def update_workspace(body: SettingsIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if "auto_approve_consent" in body.settings:
        a.require("owner")  # consent to publish unanswered drafts is the owner's alone
    ws = a.workspace
    if body.name:
        ws.name = body.name[:120]
    unknown = set(body.settings) - set(SETTING_KEYS)
    if unknown:
        raise AppError("setting_unknown", f"Unknown settings: {', '.join(sorted(unknown))}")
    ws.settings = {**(ws.settings or {}), **body.settings}
    return workspace_out(s, ws, a.role)


@router.get("/workspaces/{workspace_id}/members")
def members(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Membership).where(Membership.workspace_id == a.workspace.id).order_by(Membership.created_at))
    return {"members": [member_out(m) for m in rows]}


@router.post("/workspaces/{workspace_id}/members")
def add_member(body: MemberIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    """A bot-only member: they bind their Bale/Telegram account with the code."""
    a.require("owner")
    if body.role not in ROLES:
        raise AppError("role_invalid", "Unknown role")
    m = Membership(workspace_id=a.workspace.id, display_name=body.display_name, role=body.role,
                   link_code=workspaces.new_link_code(s))
    s.add(m)
    s.flush()
    return member_out(m)


@router.patch("/workspaces/{workspace_id}/members/{member_id}")
def update_member(member_id: str, body: MemberIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("owner")
    m = s.get(Membership, member_id)
    if m is None or m.workspace_id != a.workspace.id:
        raise NotFound("member")
    if body.role not in ROLES:
        raise AppError("role_invalid", "Unknown role")
    m.display_name, m.role = body.display_name, body.role
    return member_out(m)


@router.post("/workspaces/{workspace_id}/members/{member_id}/link-code")
def new_link_code(member_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("owner")
    m = s.get(Membership, member_id)
    if m is None or m.workspace_id != a.workspace.id:
        raise NotFound("member")
    m.link_code = workspaces.new_link_code(s)
    return member_out(m)


@router.delete("/workspaces/{workspace_id}/members/{member_id}")
def remove_member(member_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("owner")
    m = s.get(Membership, member_id)
    if m is None or m.workspace_id != a.workspace.id:
        raise NotFound("member")
    if m.role == "owner" and m.user_id == a.user.id:
        raise AppError("cannot_remove_self", "You cannot remove yourself")
    s.delete(m)
    return {"ok": True}
