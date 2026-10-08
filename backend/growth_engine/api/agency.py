from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import current_user
from ..db import get_session
from ..errors import AppError
from ..models import Agency, User
from ..services import agency as service
from ..services import storage

router = APIRouter(prefix="/agencies", tags=["agency"])


class AgencyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class WhiteLabelIn(BaseModel):
    display_name: str | None = None
    primary_color: str | None = None
    link_domain: str | None = None


def out(a: Agency) -> dict:
    label = dict(a.white_label or {})
    logo = label.pop("logo_key", None)
    return {"id": a.id, "name": a.name, "white_label": label, "logo_url": storage.signed_url(logo) if logo else None}


@router.get("")
def mine(user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return {"agencies": [out(a) for a in s.scalars(select(Agency).where(Agency.owner_id == user.id))]}


@router.post("")
def create(body: AgencyIn, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    return out(service.create(s, user, body.name))


@router.get("/{agency_id}/overview")
def overview(agency_id: str, user: User = Depends(current_user), s: Session = Depends(get_session)) -> dict:
    agency = service.owned(s, user, agency_id)
    return {"agency": out(agency), "clients": service.overview(s, agency)}


@router.patch("/{agency_id}/white-label")
def white_label(agency_id: str, body: WhiteLabelIn, user: User = Depends(current_user),
                s: Session = Depends(get_session)) -> dict:
    agency = service.owned(s, user, agency_id)
    return out(service.set_white_label(agency, body.model_dump(exclude_none=True)))


@router.post("/{agency_id}/logo")
async def logo(agency_id: str, file: UploadFile = File(...), user: User = Depends(current_user),
               s: Session = Depends(get_session)) -> dict:
    agency = service.owned(s, user, agency_id)
    if file.content_type != "image/png":
        raise AppError("logo_png_required", "The logo must be a PNG")
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise AppError("file_too_large", "The logo must be under 2 MB")
    key = storage.save_bytes(storage.new_key(f"agency-{agency.id}", "brand", ".png"), data)
    return out(service.set_white_label(agency, {"logo_key": key}))
