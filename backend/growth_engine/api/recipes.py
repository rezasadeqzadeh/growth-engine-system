from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy import update as update_
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError, NotFound
from ..models import CHANNEL_TYPES, Post, TagRecipe

router = APIRouter(prefix="/workspaces/{workspace_id}/recipes", tags=["recipes"])

GOALS = ("attract", "trust", "convert")
TIMING_MODES = ("immediate", "next_day_evening", "best_hour")
SUBTITLE_MODES = ("word", "sentence", "none")
OVERLAYS = ("date_price", "title", "name_role", "none")


class RecipeIn(BaseModel):
    tag: str = Field(min_length=2, max_length=60, pattern=r"^[\w\u0600-\u06FF\u200c]+$")
    goal: str
    pillar: str | None = None
    caption_style: str = ""
    cta: str = ""
    video_spec: dict = {}
    channels: list[str] = []
    timing: dict = {"mode": "immediate"}
    low_risk: bool = False

    @field_validator("goal")
    @classmethod
    def _goal(cls, v: str) -> str:
        if v not in GOALS:
            raise ValueError("goal must be attract, trust or convert")
        return v

    @field_validator("channels")
    @classmethod
    def _channels(cls, v: list[str]) -> list[str]:
        if any(c not in CHANNEL_TYPES for c in v):
            raise ValueError("unknown channel")
        return v

    @field_validator("timing")
    @classmethod
    def _timing(cls, v: dict) -> dict:
        if v.get("mode") not in TIMING_MODES:
            raise ValueError("unknown timing mode")
        return v

    @field_validator("video_spec")
    @classmethod
    def _spec(cls, v: dict) -> dict:
        if v.get("subtitle_mode", "sentence") not in SUBTITLE_MODES or v.get("overlay", "none") not in OVERLAYS:
            raise ValueError("unknown subtitle mode or overlay")
        if float(v.get("min_s", 10)) > float(v.get("max_s", 60)):
            raise ValueError("min_s is above max_s")
        return v


def out(r: TagRecipe) -> dict:
    return {"id": r.id, "tag": r.tag, "goal": r.goal, "pillar": r.pillar, "caption_style": r.caption_style,
            "cta": r.cta, "video_spec": r.video_spec, "channels": r.channels, "timing": r.timing, "low_risk": r.low_risk}


@router.get("")
def list_recipes(a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    rows = s.scalars(select(TagRecipe).where(TagRecipe.workspace_id == a.workspace.id).order_by(TagRecipe.tag))
    return {"recipes": [out(r) for r in rows]}


@router.post("")
def create(body: RecipeIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    if s.scalar(select(TagRecipe.id).where(TagRecipe.workspace_id == a.workspace.id, TagRecipe.tag == body.tag)):
        raise AppError("tag_exists", "This tag already has a recipe", 409)
    r = TagRecipe(workspace_id=a.workspace.id, **body.model_dump())
    s.add(r)
    s.flush()
    return out(r)


@router.put("/{recipe_id}")
def update(recipe_id: str, body: RecipeIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    r = s.get(TagRecipe, recipe_id)
    if r is None or r.workspace_id != a.workspace.id:
        raise NotFound("recipe")
    for key, value in body.model_dump().items():
        setattr(r, key, value)
    return out(r)


@router.delete("/{recipe_id}")
def delete(recipe_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("operator")
    r = s.get(TagRecipe, recipe_id)
    if r is None or r.workspace_id != a.workspace.id:
        raise NotFound("recipe")
    # Posts keep their tag text; only the link to the deleted recipe goes.
    s.execute(update_(Post).where(Post.recipe_id == r.id).values(recipe_id=None))
    s.delete(r)
    return {"ok": True}
