from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.opencode import ImagePart
from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError, NotFound
from ..jobs import queue
from ..models import Competitor, CompetitorAnalysis, CompetitorPost, ContentIdea
from ..services import competitors as service

router = APIRouter(prefix="/workspaces/{workspace_id}/competitors", tags=["competitors"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class CompetitorIn(BaseModel):
    handle: str = Field(min_length=1, max_length=80)
    kind: str = "direct"
    name: str = ""
    followers: int | None = None


class PostIn(BaseModel):
    url: str | None = None
    posted_at: datetime | None = None
    format: str | None = None
    duration_s: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    caption: str = ""
    offer_price: str | None = None


class PostsIn(BaseModel):
    posts: list[PostIn] = Field(max_length=50)


class OrderIn(BaseModel):
    idea_id: str


def out(c: Competitor) -> dict:
    return {"id": c.id, "handle": c.handle, "name": c.name, "kind": c.kind, "followers": c.followers,
            "posts_per_week": c.posts_per_week, "engagement_rate": c.engagement_rate, "best_hook": c.best_hook,
            "last_collected_at": c.last_collected_at.isoformat() if c.last_collected_at else None}


@router.get("")
def list_all(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(Competitor).where(Competitor.workspace_id == a.workspace.id).order_by(Competitor.handle))
    analysis = s.scalar(select(CompetitorAnalysis).where(CompetitorAnalysis.workspace_id == a.workspace.id)
                        .order_by(CompetitorAnalysis.created_at.desc()))
    return {"competitors": [out(c) for c in rows],
            "analysis": {"patterns": analysis.patterns, "gaps": analysis.gaps, "suggestions": analysis.suggestions,
                         "at": analysis.created_at.isoformat()} if analysis else None}


@router.post("")
def add(body: CompetitorIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    return out(service.add(s, a.workspace, body.handle, body.kind, body.name, body.followers))


@router.get("/{competitor_id}/posts")
def posts(competitor_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    c = service.get(s, a.workspace.id, competitor_id)
    rows = s.scalars(select(CompetitorPost).where(CompetitorPost.competitor_id == c.id)
                     .order_by(CompetitorPost.ratio_to_avg.desc().nulls_last()))
    return {"posts": [{"id": p.id, "url": p.url, "format": p.format, "views": p.views, "likes": p.likes,
                       "comments": p.comments, "caption": p.caption, "hook_type": p.hook_type,
                       "ratio_to_avg": p.ratio_to_avg} for p in rows]}


@router.post("/{competitor_id}/posts")
def add_posts(competitor_id: str, body: PostsIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    c = service.get(s, a.workspace.id, competitor_id)
    return {"added": service.add_posts(s, c, [p.model_dump() for p in body.posts]), "competitor": out(c)}


@router.post("/{competitor_id}/screenshots")
async def add_screenshots(competitor_id: str, files: list[UploadFile] = File(...), a: Access = Depends(access),
                          s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    c = service.get(s, a.workspace.id, competitor_id)
    images = []
    for f in files[:6]:
        if f.content_type not in ("image/png", "image/jpeg"):
            raise AppError("image_required", "Screenshots must be PNG or JPEG")
        data = await f.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise AppError("file_too_large", "A screenshot must be under 8 MB")
        images.append(ImagePart(data, f.content_type, f.filename or "screen.png"))
    return {"added": await service.add_from_screenshots(s, c, images), "competitor": out(c)}


@router.delete("/{competitor_id}")
def remove(competitor_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    s.delete(service.get(s, a.workspace.id, competitor_id))
    return {"ok": True}


@router.post("/analyze")
def analyze(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    queue.enqueue(s, "analyze_competitors", {"workspace_id": a.workspace.id},
                  dedupe_key=f"competitors:{a.workspace.id}")
    return {"queued": True}


@router.post("/order-video")
async def order_video(body: OrderIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    idea = s.get(ContentIdea, body.idea_id)
    if idea is None or idea.workspace_id != a.workspace.id:
        raise NotFound("idea")
    await service.order_video(s, a.workspace, idea)
    return {"sent": True}
