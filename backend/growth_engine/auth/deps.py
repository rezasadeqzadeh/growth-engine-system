"""FastAPI dependencies: the signed-in user and their access to a workspace."""

from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..errors import AppError, Forbidden, NotFound
from ..models import Agency, Membership, User, Workspace
from .otp import is_superadmin, user_from_token

ROLE_RANK = {"sender": 0, "approver": 1, "operator": 2, "owner": 3}


def current_user(authorization: str | None = Header(default=None), s: Session = Depends(get_session)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("auth_required", "Sign in first", 401)
    return user_from_token(s, authorization[7:])


@dataclass
class Access:
    user: User
    workspace: Workspace
    role: str  # effective role; agency owners and superadmins act as owner
    member: Membership | None

    def require(self, role: str) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[role]:
            raise Forbidden("role_required", f"This needs the {role} role")


def workspace_access(s: Session, user: User, workspace_id: str) -> Access:
    ws = s.get(Workspace, workspace_id)
    if ws is None:
        raise NotFound("workspace")
    member = s.scalar(select(Membership).where(Membership.workspace_id == ws.id, Membership.user_id == user.id))
    if member:
        return Access(user, ws, member.role, member)
    if ws.agency_id:
        agency = s.get(Agency, ws.agency_id)
        if agency and agency.owner_id == user.id:
            return Access(user, ws, "owner", None)
    if is_superadmin(user):
        return Access(user, ws, "owner", None)
    raise Forbidden("workspace_forbidden", "You are not in this workspace")


def access(workspace_id: str, user: User = Depends(current_user), s: Session = Depends(get_session)) -> Access:
    return workspace_access(s, user, workspace_id)
