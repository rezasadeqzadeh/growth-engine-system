from collections import Counter

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import NotFound
from ..models import ContentIdea, Feedback
from ..services import feedback as feedback_service

router = APIRouter(prefix="/workspaces/{workspace_id}/feedback", tags=["feedback"])


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def out(f: Feedback) -> dict:
    return {"id": f.id, "channel_type": f.channel_type, "author": f.author, "text": f.text, "at": f.at.isoformat(),
            "category": f.category, "suggested_reply": f.suggested_reply, "handled": f.handled,
            "alerted": f.alerted, "can_send": f.channel_type in ("bale", "telegram")}


def _get(s: Session, a: Access, feedback_id: str) -> Feedback:
    f = s.get(Feedback, feedback_id)
    if f is None or f.workspace_id != a.workspace.id:
        raise NotFound("feedback")
    return f


@router.get("")
def inbox(category: str | None = None, handled: bool | None = None, a: Access = Depends(access),
          s: Session = Depends(get_session)) -> dict:
    base = select(Feedback).where(Feedback.workspace_id == a.workspace.id, Feedback.hidden.is_(False))
    counts = Counter(f.category or "unsorted" for f in s.scalars(base.where(Feedback.handled.is_(False))))
    q = base
    if category:
        q = q.where(Feedback.category == category)
    if handled is not None:
        q = q.where(Feedback.handled.is_(handled))
    # Purchase questions first: an unanswered one is a lost customer.
    rows = s.scalars(q.order_by((Feedback.category == "purchase_question").desc(), Feedback.at.desc()).limit(200))
    return {"items": [out(f) for f in rows], "counts": dict(counts)}


@router.post("/{feedback_id}/handled")
def mark_handled(feedback_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    f = _get(s, a, feedback_id)
    f.handled = True
    return out(f)


@router.post("/{feedback_id}/reply")
async def reply(feedback_id: str, body: ReplyIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    f = _get(s, a, feedback_id)
    await feedback_service.send_reply(s, f, body.text)
    return out(f)


@router.post("/{feedback_id}/to-idea")
def to_idea(feedback_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    f = _get(s, a, feedback_id)
    s.add(ContentIdea(workspace_id=a.workspace.id, text=f.text[:1000], source="feedback"))
    f.handled = True
    return out(f)
