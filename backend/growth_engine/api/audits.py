"""Page audits: public (the lead magnet) and from the panel."""

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access, current_user
from ..auth.otp import is_superadmin
from ..db import get_session
from ..errors import AppError, Forbidden
from ..i18n import t
from ..models import Agency, Audit, Channel, User
from ..services import audit as audit_service

router = APIRouter(prefix="/audits", tags=["audits"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024


@router.post("")
async def create(handle: str = Form(...), vertical: str = Form("general"), phone: str = Form(...),
                 agency_id: str | None = Form(None), manual: str | None = Form(None),
                 files: list[UploadFile] = File(default=[]), s: Session = Depends(get_session)) -> dict:
    screenshots = []
    for f in files[:6]:
        if f.content_type not in ("image/png", "image/jpeg"):
            raise AppError("image_required", "Screenshots must be PNG or JPEG")
        data = await f.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise AppError("file_too_large", "A screenshot must be under 8 MB")
        screenshots.append((data, f.content_type))
    if agency_id and s.get(Agency, agency_id) is None:
        agency_id = None
    try:
        manual_data = json.loads(manual) if manual else None
    except json.JSONDecodeError as exc:
        raise AppError("manual_data_invalid", "The typed page data is not valid") from exc
    kind = "manual" if manual_data and not screenshots else "screenshots"
    audit = audit_service.create(s, handle=handle, vertical=vertical, phone=phone, input_kind=kind,
                                 screenshots=screenshots, manual=manual_data, agency_id=agency_id)
    return {"slug": audit.slug, "status": audit.status}


@router.get("/{slug}")
def get(slug: str, s: Session = Depends(get_session)) -> dict:
    return audit_service.to_dict(audit_service.get_by_slug(s, slug))


@router.post("/{slug}/want-service")
def want_service(slug: str, s: Session = Depends(get_session)) -> dict:
    """'Do these for me': the audit becomes a sales lead in the operator's audit list."""
    audit_service.get_by_slug(s, slug).wants_service = True
    return {"ok": True, "message": t("audit.lead_received")}


@router.get("")
def list_for_operator(user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    """Audit leads: an agency sees its own, a platform admin sees all."""
    q = select(Audit).order_by(Audit.created_at.desc()).limit(300)
    if not is_superadmin(user):
        agency_ids = list(s.scalars(select(Agency.id).where(Agency.owner_id == user.id)))
        if not agency_ids:
            raise Forbidden()
        q = q.where(Audit.agency_id.in_(agency_ids))
    return {"audits": [{**audit_service.to_dict(a), "phone": a.phone} for a in s.scalars(q)]}


@router.post("/own/{workspace_id}")
def audit_own_page(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    """Audit the workspace's own connected Instagram account through the official API."""
    channel = s.scalar(select(Channel).where(Channel.workspace_id == a.workspace.id, Channel.type == "instagram",
                                             Channel.enabled))
    if channel is None or not (channel.config or {}).get("username"):
        raise AppError("instagram_not_connected", "Connect Instagram first", 409)
    owner_phone = a.user.phone
    audit = audit_service.create(s, handle=channel.config["username"], vertical=a.workspace.vertical,
                                 phone=owner_phone, input_kind="instagram_api", agency_id=a.workspace.agency_id,
                                 channel_id=channel.id)
    return {"slug": audit.slug, "status": audit.status}
