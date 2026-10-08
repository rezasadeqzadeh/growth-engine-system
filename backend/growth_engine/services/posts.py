"""The post lifecycle: propose, wait, then execute.

processing -> pending -> scheduled -> published
pending or scheduled -> rejected
Nothing is published without a human approval, except a low-risk tag
whose owner consented beforehand to auto-approval after 24 hours.
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..errors import AppError, NotFound
from ..i18n import patterns
from ..jobs import queue
from ..models import AuditLog, Channel, MediaAsset, Membership, Post, PostVariant, TagRecipe, Workspace
from . import calendar, timing

HASHTAG = re.compile(r"#([\w\u0600-\u06FF\u200c]+)")
AUTO_APPROVE_AFTER = timedelta(hours=24)
EDITABLE_STATUSES = ("pending", "scheduled")
# The admin's subtitle fix: "<wrong> ra <right> kon" in Persian (data/fa_patterns.json), or "<wrong> -> <right>".
_FIX_FA = re.compile(patterns()["subtitle_fix"])
_FIX_ARROW = re.compile(r"^\s*(.+?)\s*(?:->|→|=>)\s*(.+?)\s*$")


def parse_caption(text: str, known_tags: list[str]) -> tuple[str | None, str]:
    """The first hashtag that names a recipe is the tag; the rest is the note."""
    tag = None
    for found in HASHTAG.findall(text or ""):
        if found in known_tags:
            tag = found
            break
    note = HASHTAG.sub(lambda m: "" if m.group(1) == tag else m.group(0), text or "").strip()
    return tag, re.sub(r"\s{2,}", " ", note)


def parse_subtitle_fix(text: str) -> tuple[str, str] | None:
    for pattern in (_FIX_FA, _FIX_ARROW):
        m = pattern.match(text)
        if m and m.group(1).strip() != m.group(2).strip():
            return m.group(1).strip(), m.group(2).strip()
    return None


def recipe_for(s: Session, workspace_id: str, tag: str | None) -> TagRecipe | None:
    if not tag:
        return None
    return s.scalar(select(TagRecipe).where(TagRecipe.workspace_id == workspace_id, TagRecipe.tag == tag))


def ingest(s: Session, ws: Workspace, *, platform: str, member: Membership | None, chat_id: str | None,
           msg_id: str | None, caption_text: str, download: dict | None = None,
           file_key: str | None = None) -> Post:
    """A raw video arrived. `download` = {channel_id, file_id} for a bot file."""
    tags = list(s.scalars(select(TagRecipe.tag).where(TagRecipe.workspace_id == ws.id)))
    tag, note = parse_caption(caption_text, tags)
    asset = MediaAsset(workspace_id=ws.id, source_platform=platform, source_chat_id=chat_id, source_msg_id=msg_id,
                       sender_member_id=member.id if member else None, file_key=file_key, note_text=note)
    s.add(asset)
    s.flush()
    recipe = recipe_for(s, ws.id, tag)
    post = Post(workspace_id=ws.id, asset_id=asset.id, tag=tag, recipe_id=recipe.id if recipe else None,
                raw_note=note, status="processing")
    s.add(post)
    s.flush()
    queue.enqueue(s, "process_video", {"post_id": post.id, "download": download}, dedupe_key=f"process:{post.id}")
    return post


def get(s: Session, post_id: str, workspace_id: str | None = None) -> Post:
    post = s.get(Post, post_id)
    if post is None or (workspace_id and post.workspace_id != workspace_id):
        raise NotFound("post")
    return post


def _log(s: Session, post: Post, member: Membership | None, action: str, **detail: object) -> None:
    s.add(AuditLog(workspace_id=post.workspace_id, actor_member_id=member.id if member else None,
                   action=action, subject_id=post.id, detail=detail))


def _require_editable(post: Post) -> None:
    if post.status not in EDITABLE_STATUSES:
        raise AppError("post_not_editable", f"A {post.status} post cannot be changed", 409)


def _require_approver(member: Membership | None) -> None:
    if member is not None and not member.can_approve():
        raise AppError("approver_required", "Only approvers can approve", 403)


def approve(s: Session, post: Post, member: Membership | None, *, at: datetime | None = None,
            auto: bool = False) -> Post:
    if post.status != "pending":
        raise AppError("post_not_pending", "Only a pending post can be approved", 409)
    _require_approver(member)
    ws = s.get(Workspace, post.workspace_id)
    recipe = s.get(TagRecipe, post.recipe_id) if post.recipe_id else None
    now = db.utcnow()
    if at is None:
        asset = s.get(MediaAsset, post.asset_id) if post.asset_id else None
        at = timing.publish_time((recipe.timing if recipe else {}) or {}, now=now,
                                 source_at=asset.created_at if asset else now,
                                 best_hour=int((ws.settings or {}).get("best_hour", 20)))
    post.status, post.approved_at, post.scheduled_at = "scheduled", now, at
    post.approved_by = member.id if member else None
    post.auto_approve_at = None
    _schedule_variants(s, post, at)
    calendar.attach_post(s, post, at)
    if recipe and recipe.goal == "convert" and recipe.timing.get("reminder_days"):
        queue.enqueue(s, "publish_reminder", {"post_id": post.id},
                      run_at=at + timedelta(days=int(recipe.timing["reminder_days"])), dedupe_key=f"reminder:{post.id}")
    _log(s, post, member, "auto_approve" if auto else "approve", at=at.isoformat())
    return post


def _schedule_variants(s: Session, post: Post, at: datetime) -> None:
    for variant in s.scalars(select(PostVariant).where(PostVariant.post_id == post.id)):
        queue.enqueue(s, "publish_variant", {"variant_id": variant.id, "at": at.isoformat()}, run_at=at,
                      dedupe_key=f"publish:{variant.id}:{at.isoformat()}")


def reschedule(s: Session, post: Post, member: Membership | None, at: datetime) -> Post:
    _require_editable(post)
    if post.status == "pending":
        return approve(s, post, member, at=at)
    _require_approver(member)
    # Queued publish jobs carry the old time; they check scheduled_at and step aside.
    post.scheduled_at = at
    _schedule_variants(s, post, at)
    _log(s, post, member, "reschedule", at=at.isoformat())
    return post


def reject(s: Session, post: Post, member: Membership | None, reason: str = "") -> Post:
    _require_editable(post)
    _require_approver(member)
    post.status, post.rejected_reason, post.auto_approve_at = "rejected", reason[:300] or None, None
    _log(s, post, member, "reject", reason=reason)
    return post


def set_tag(s: Session, post: Post, member: Membership | None, tag: str) -> Post:
    """Confirm or change the tag; a different recipe means a new render."""
    _require_editable(post)
    recipe = recipe_for(s, post.workspace_id, tag)
    if recipe is None:
        raise AppError("tag_unknown", "No recipe for this tag")
    changed = recipe.id != post.recipe_id
    post.tag, post.recipe_id, post.tag_guessed = tag, recipe.id, False
    if changed:
        post.status = "processing"
        queue.enqueue(s, "process_video", {"post_id": post.id, "rerender": True}, dedupe_key=f"process:{post.id}")
    _log(s, post, member, "set_tag", tag=tag)
    return post


def request_caption_edit(s: Session, post: Post, member: Membership | None, instruction: str,
                         channel_id: str | None = None) -> None:
    _require_editable(post)
    queue.enqueue(s, "edit_captions", {"post_id": post.id, "instruction": instruction, "channel_id": channel_id,
                                       "member_id": member.id if member else None})


def request_subtitle_fix(s: Session, post: Post, member: Membership | None, text: str) -> tuple[str, str]:
    _require_editable(post)
    fix = parse_subtitle_fix(text)
    if fix is None:
        raise AppError("subtitle_fix_unclear", "Write it as: <wrong> -> <right>")
    asset = s.get(MediaAsset, post.asset_id) if post.asset_id else None
    if asset is None or not asset.transcript:
        raise AppError("no_transcript", "This post has no subtitles")
    post.status = "processing"
    queue.enqueue(s, "process_video", {"post_id": post.id, "rerender": True, "replacements": {fix[0]: fix[1]}},
                  dedupe_key=f"process:{post.id}")
    _log(s, post, member, "subtitle_fix", wrong=fix[0], right=fix[1])
    return fix


def rate(s: Session, post: Post, member: Membership | None, score: int) -> None:
    if not 1 <= score <= 5:
        raise AppError("rating_invalid", "Rating is 1 to 5")
    post.rating = score
    _log(s, post, member, "rate", score=score)


def due_auto_approvals(s: Session) -> list[Post]:
    return list(s.scalars(select(Post).where(Post.status == "pending", Post.auto_approve_at.is_not(None),
                                             Post.auto_approve_at <= db.utcnow())))


def variants_of(s: Session, post_id: str) -> list[tuple[PostVariant, Channel]]:
    rows = s.execute(select(PostVariant, Channel).join(Channel, Channel.id == PostVariant.channel_id)
                     .where(PostVariant.post_id == post_id).order_by(Channel.type, PostVariant.kind))
    return [(v, c) for v, c in rows]
