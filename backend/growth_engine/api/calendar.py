from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError, NotFound
from ..models import CalendarSlot
from ..services import calendar, iran_calendar

router = APIRouter(prefix="/workspaces/{workspace_id}/calendar", tags=["calendar"])


class MonthIn(BaseModel):
    year: int = Field(ge=1400, le=1500)
    month: int = Field(ge=1, le=12)


class MoveIn(BaseModel):
    day: date


class SlotIn(BaseModel):
    day: date
    kind: str = "post"
    tag: str | None = None
    title: str = ""
    needs_media: bool = True


def slot_out(sl: CalendarSlot) -> dict:
    return {"id": sl.id, "day": sl.day.isoformat(), "kind": sl.kind, "pillar": sl.pillar, "goal": sl.goal,
            "tag": sl.tag, "title": sl.title, "note": sl.note, "occasion": sl.occasion, "post_id": sl.post_id,
            "needs_media": sl.needs_media, "requested": sl.request_sent_at is not None}


@router.get("")
def month(year: int, month: int, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    start, end = iran_calendar.jalali_month_range(year, month)
    slots = list(s.scalars(select(CalendarSlot).where(CalendarSlot.workspace_id == a.workspace.id,
                                                      CalendarSlot.day >= start, CalendarSlot.day <= end)
                           .order_by(CalendarSlot.day)))
    occasions = iran_calendar.occasions_between(start, end)
    return {"start": start.isoformat(), "end": end.isoformat(), "slots": [slot_out(x) for x in slots],
            "balance": calendar.balance(slots),
            "occasions": [{"day": o.day.isoformat(), "name": o.name, "tone": o.tone, "holiday": o.holiday}
                          for o in occasions.values()]}


@router.post("/generate")
async def generate(body: MonthIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    rows = await calendar.generate_month(s, a.workspace, body.year, body.month)
    return {"created": len(rows)}


@router.post("/slots")
def create_slot(body: SlotIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if body.kind not in ("post", "reel", "story"):
        raise AppError("slot_kind_invalid", "Kind is post, reel or story")
    sl = CalendarSlot(workspace_id=a.workspace.id, **body.model_dump())
    s.add(sl)
    s.flush()
    return slot_out(sl)


@router.patch("/slots/{slot_id}")
def move_slot(slot_id: str, body: MoveIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    return slot_out(calendar.move(s, a.workspace.id, slot_id, body.day))


@router.delete("/slots/{slot_id}")
def delete_slot(slot_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    sl = s.get(CalendarSlot, slot_id)
    if sl is None or sl.workspace_id != a.workspace.id:
        raise NotFound("slot")
    s.delete(sl)
    return {"ok": True}
