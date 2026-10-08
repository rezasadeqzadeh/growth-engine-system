"""The approval queue in the panel: same actions as the bot card, plus a
tab per channel and a direct caption editor."""

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import Access, access
from ..db import get_session
from ..errors import AppError, NotFound
from ..jobs import queue
from ..media.subtitles import build_cues, build_srt
from ..models import MediaAsset, Post, PostVariant, Publication, TrackedLink
from ..services import links, storage
from ..services import posts as post_service
from ..services.caption_jobs import requalify

router = APIRouter(prefix="/workspaces/{workspace_id}/posts", tags=["posts"])


class ScheduleIn(BaseModel):
    at: datetime


class RejectIn(BaseModel):
    reason: str = ""


class TagIn(BaseModel):
    tag: str


class InstructionIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=1000)
    channel_id: str | None = None


class CaptionIn(BaseModel):
    caption: str = Field(max_length=20000)
    title: str | None = None


class RateIn(BaseModel):
    score: int


def post_summary(p: Post) -> dict:
    return {"id": p.id, "title": p.title, "tag": p.tag, "tag_guessed": p.tag_guessed, "status": p.status,
            "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
            "created_at": p.created_at.isoformat(), "qc": p.qc, "duration_s": p.output_duration_s,
            "auto_approve_at": p.auto_approve_at.isoformat() if p.auto_approve_at else None,
            "rating": p.rating, "failed": p.status == "failed"}


@router.get("")
def list_posts(status: str | None = None, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    q = select(Post).where(Post.workspace_id == a.workspace.id)
    if status:
        q = q.where(Post.status.in_(status.split(",")))
    rows = s.scalars(q.order_by(Post.created_at.desc()).limit(100))
    return {"posts": [post_summary(p) for p in rows]}


@router.get("/{post_id}")
def get_post(post_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    p = post_service.get(s, post_id, a.workspace.id)
    asset = s.get(MediaAsset, p.asset_id) if p.asset_id else None
    variants = []
    base = links.base_url(s, a.workspace.id)
    for v, c in post_service.variants_of(s, p.id):
        link = s.get(TrackedLink, v.tracked_link_id) if v.tracked_link_id else None
        pubs = s.scalars(select(Publication).where(Publication.variant_id == v.id).order_by(Publication.created_at))
        variants.append({
            "id": v.id, "channel": {"id": c.id, "type": c.type, "name": c.name}, "kind": v.kind, "title": v.title,
            "caption": v.caption, "tags": v.tags,
            "video_url": storage.signed_url(v.video_key) if v.video_key else None,
            "cover_url": storage.signed_url(v.cover_key) if v.cover_key else None,
            "srt_url": storage.signed_url(v.srt_key) if v.srt_key else None,
            "tracked_link": links.short_url(link, base) if link else None,
            "publications": [{"status": pub.status, "url": pub.external_url, "error": pub.error,
                              "at": pub.published_at.isoformat() if pub.published_at else None} for pub in pubs],
        })
    preview_srt = None
    if asset and asset.transcript and asset.duration_s:
        whole = [(0.0, asset.duration_s)]
        preview_srt = build_srt(build_cues(asset.transcript, whole, "sentence"))
    return {**post_summary(p), "raw_note": p.raw_note, "variants": variants, "subtitles": preview_srt,
            "faces": asset.faces_detected if asset else 0, "error": "processing_failed" if p.status == "failed" else None}


@router.post("/{post_id}/approve")
def approve(post_id: str, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    p = post_service.approve(s, post_service.get(s, post_id, a.workspace.id), a.member)
    queue.enqueue(s, "notify_text", {"workspace_id": a.workspace.id, "key": "bot.approved_in_panel",
                                     "values": {"title": p.title}})
    return post_summary(p)


@router.post("/{post_id}/schedule")
def schedule(post_id: str, body: ScheduleIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    if body.at.tzinfo is None:
        raise AppError("time_needs_zone", "Send the time with its timezone")
    return post_summary(post_service.reschedule(s, post_service.get(s, post_id, a.workspace.id), a.member, body.at))


@router.post("/{post_id}/reject")
def reject(post_id: str, body: RejectIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    return post_summary(post_service.reject(s, post_service.get(s, post_id, a.workspace.id), a.member, body.reason))


@router.post("/{post_id}/tag")
def set_tag(post_id: str, body: TagIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    return post_summary(post_service.set_tag(s, post_service.get(s, post_id, a.workspace.id), a.member, body.tag))


@router.post("/{post_id}/caption-edit")
def caption_edit(post_id: str, body: InstructionIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    post_service.request_caption_edit(s, post_service.get(s, post_id, a.workspace.id), a.member, body.instruction,
                                      body.channel_id)
    return {"queued": True}


@router.post("/{post_id}/subtitle-fix")
def subtitle_fix(post_id: str, body: InstructionIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    wrong, right = post_service.request_subtitle_fix(s, post_service.get(s, post_id, a.workspace.id), a.member,
                                                     body.instruction)
    return {"queued": True, "wrong": wrong, "right": right}


@router.put("/{post_id}/variants/{variant_id}")
def edit_variant(post_id: str, variant_id: str, body: CaptionIn, a: Access = Depends(access),
                 s: Session = Depends(get_session)) -> dict:
    a.require("approver")
    p = post_service.get(s, post_id, a.workspace.id)
    if p.status not in post_service.EDITABLE_STATUSES:
        raise AppError("post_not_editable", "This post can no longer be changed", 409)
    v = s.get(PostVariant, variant_id)
    if v is None or v.post_id != p.id:
        raise NotFound("variant")
    v.caption = body.caption
    if body.title is not None:
        v.title = body.title[:200]
    requalify(s, p)
    return post_summary(p)


@router.post("/{post_id}/rate")
def rate(post_id: str, body: RateIn, a: Access = Depends(access), s: Session = Depends(get_session)) -> dict:
    post_service.rate(s, post_service.get(s, post_id, a.workspace.id), a.member, body.score)
    return {"ok": True}


@router.post("/upload")
async def upload(file: UploadFile = File(...), caption: str = Form(""), a: Access = Depends(access),
                 s: Session = Depends(get_session)) -> dict:
    """Raw video from the panel (no size limit of a bot)."""
    if not (file.content_type or "").startswith("video/"):
        raise AppError("video_required", "Send a video file")
    key = storage.new_key(a.workspace.id, "raw", ".mp4")
    await storage.save_upload(file, key)
    p = post_service.ingest(s, a.workspace, platform="upload", member=a.member, chat_id=None, msg_id=None,
                            caption_text=caption, file_key=key)
    return post_summary(p)
