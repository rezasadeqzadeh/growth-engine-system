from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError
from ..models import BrandKit
from ..services import brand_kit, storage

router = APIRouter(prefix="/workspaces/{workspace_id}/brand-kit", tags=["brand"])
MAX_LOGO_BYTES = 2 * 1024 * 1024


class GenerateIn(BaseModel):
    answers: dict[str, str]


@router.get("")
def get_kit(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    kit = brand_kit.current(s, a.workspace.id)
    out = brand_kit.to_dict(kit)
    out["questions"] = list(brand_kit.QUESTIONS)
    out["logo_url"] = storage.signed_url(kit.logo_key) if kit.logo_key else None
    return out


@router.get("/versions")
def versions(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(BrandKit).where(BrandKit.workspace_id == a.workspace.id).order_by(BrandKit.version.desc()))
    return {"versions": [{"version": k.version, "created_at": k.created_at.isoformat(), "current": k.is_current}
                         for k in rows]}


@router.post("/generate")
async def generate(body: GenerateIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    return brand_kit.to_dict(await brand_kit.generate(s, a.workspace.id, body.answers))


@router.put("")
def save(body: dict, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    changes = {k: v for k, v in body.items() if k in brand_kit.EDITABLE and k != "logo_key"}
    return brand_kit.to_dict(brand_kit.new_version(s, a.workspace.id, changes))


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...), a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if file.content_type != "image/png":
        raise AppError("logo_png_required", "The logo must be a PNG (transparent background works best)")
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise AppError("file_too_large", "The logo must be under 2 MB")
    key = storage.save_bytes(storage.new_key(a.workspace.id, "brand", ".png"), data)
    return brand_kit.to_dict(brand_kit.new_version(s, a.workspace.id, {"logo_key": key}))
