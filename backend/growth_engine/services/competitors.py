"""Competitors and similar pages: learn from patterns, never copy.

Public pages only, only pages the user added, numbers only (no personal
data about commenters). v1 is semi-manual: an operator enters a page's top
posts (link, numbers, caption) or sends screenshots; the system measures
each post against that page's own average and the AI explains why the
winners held attention.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..ai.opencode import ImagePart
from ..errors import AppError, NotFound
from ..i18n import t
from ..models import Competitor, CompetitorAnalysis, CompetitorPost, ContentIdea, Feedback, Workspace
from . import notify

HOOK_TYPES = ("question", "number", "contrast", "before_after", "silent_scenery", "mistakes_list", "story", "other")
WINNER_RATIO = 2.0
KINDS = ("direct", "substitute", "pattern")

HOOK_SYSTEM = f"""Classify each caption's opening hook. Types: {", ".join(HOOK_TYPES)}.
JSON: {{"items": [{{"id": "...", "hook_type": "..."}}]}}"""

ANALYSIS_SYSTEM = """You study competitors of an Iranian small business to find patterns, not to copy them.
From the posts (each with its ratio to its own page's average), say why the winners held attention
(hook structure, length, rhythm, emotion), which formats and lengths work in this field, how often
and when they post, what they offer at what price, and which audience questions nobody covers.
Every suggestion applies a pattern to the business's own real content. Persian text.
JSON: {"patterns": [{"name": "...", "ratio": number, "why": "..."}],
       "gaps": ["..."],
       "suggestions": [{"text": "...", "tag": "one of the business's tags or null"}]}"""

SCREEN_SYSTEM = """Read these screenshots of a public page's posts. JSON: {"followers": int|null,
"posts": [{"url": str|null, "date": "YYYY-MM-DD"|null, "format": "reel|carousel|image", "views": int|null,
"likes": int|null, "comments": int|null, "caption": "first line"}]}"""


def add(s: Session, ws: Workspace, handle: str, kind: str, name: str = "", followers: int | None = None) -> Competitor:
    if kind not in KINDS:
        raise AppError("competitor_kind_invalid", "Kind is direct, substitute or pattern")
    handle = handle.strip().lstrip("@")
    if s.scalar(select(Competitor.id).where(Competitor.workspace_id == ws.id, Competitor.handle == handle)):
        raise AppError("competitor_exists", "This page is already watched", 409)
    comp = Competitor(workspace_id=ws.id, handle=handle, kind=kind, name=name, followers=followers)
    s.add(comp)
    s.flush()
    return comp


def get(s: Session, workspace_id: str, competitor_id: str) -> Competitor:
    comp = s.get(Competitor, competitor_id)
    if comp is None or comp.workspace_id != workspace_id:
        raise NotFound("competitor")
    return comp


def _signal(p: CompetitorPost) -> int | None:
    if p.views is not None:
        return p.views
    if p.likes is not None:
        return (p.likes or 0) + (p.comments or 0)
    return None


def recompute(s: Session, comp: Competitor) -> None:
    posts = list(s.scalars(select(CompetitorPost).where(CompetitorPost.competitor_id == comp.id)))
    signals = [v for v in (_signal(p) for p in posts) if v is not None]
    avg = sum(signals) / len(signals) if signals else 0
    for p in posts:
        value = _signal(p)
        p.ratio_to_avg = round(value / avg, 2) if value is not None and avg else None
    dated = sorted(p.posted_at for p in posts if p.posted_at)
    if len(dated) >= 2:
        span_weeks = max((dated[-1] - dated[0]).days / 7, 1)
        comp.posts_per_week = round(len(dated) / span_weeks, 1)
    if comp.followers:
        eng = [((p.likes or 0) + (p.comments or 0)) / comp.followers for p in posts if p.likes is not None]
        comp.engagement_rate = round(sum(eng) / len(eng), 4) if eng else None
    hooks = Counter(p.hook_type for p in posts if p.hook_type and (p.ratio_to_avg or 0) >= WINNER_RATIO)
    comp.best_hook = hooks.most_common(1)[0][0] if hooks else None
    comp.last_collected_at = db.utcnow()


def add_posts(s: Session, comp: Competitor, rows: list[dict]) -> int:
    added = 0
    for row in rows:
        url = str(row.get("url") or f"manual:{db.new_id()[:10]}")[:300]
        if s.scalar(select(CompetitorPost.id).where(CompetitorPost.competitor_id == comp.id, CompetitorPost.url == url)):
            continue
        s.add(CompetitorPost(competitor_id=comp.id, url=url, posted_at=row.get("posted_at"), format=row.get("format"),
                             duration_s=row.get("duration_s"), views=row.get("views"), likes=row.get("likes"),
                             comments=row.get("comments"), caption=str(row.get("caption") or "")[:2000],
                             offer_price=row.get("offer_price")))
        added += 1
    s.flush()
    recompute(s, comp)
    return added


async def add_from_screenshots(s: Session, comp: Competitor, images: list[ImagePart]) -> int:
    data = await router.ask_json("read_screenshot", SCREEN_SYSTEM, f"Page @{comp.handle}",
                                 workspace_id=comp.workspace_id, images=images)
    if not isinstance(data, dict):
        return 0
    if data.get("followers"):
        comp.followers = int(data["followers"])
    rows = []
    for p in data.get("posts") or []:
        try:
            posted = datetime.fromisoformat(str(p.get("date"))).replace(tzinfo=timezone.utc) if p.get("date") else None
        except ValueError:
            posted = None
        rows.append({**p, "posted_at": posted})
    return add_posts(s, comp, rows)


async def classify_hooks(s: Session, workspace_id: str) -> None:
    posts = list(s.scalars(select(CompetitorPost).join(Competitor, Competitor.id == CompetitorPost.competitor_id)
                           .where(Competitor.workspace_id == workspace_id, CompetitorPost.hook_type.is_(None),
                                  CompetitorPost.caption != "").limit(40)))
    if not posts:
        return
    user = "\n".join(f"[{p.id}] {p.caption[:300]}" for p in posts)
    reply = await router.ask_json("hook_type", HOOK_SYSTEM, user, workspace_id=workspace_id, cache=True)
    by_id = {i.get("id"): i.get("hook_type") for i in (reply.get("items", []) if isinstance(reply, dict) else [])}
    for p in posts:
        p.hook_type = by_id.get(p.id) if by_id.get(p.id) in HOOK_TYPES else "other"
    for comp in s.scalars(select(Competitor).where(Competitor.workspace_id == workspace_id)):
        recompute(s, comp)


async def analyze(payload: dict) -> None:
    workspace_id = payload["workspace_id"]
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace_id)
        await classify_hooks(s, workspace_id)
        rows = s.execute(select(CompetitorPost, Competitor).join(Competitor, Competitor.id == CompetitorPost.competitor_id)
                         .where(Competitor.workspace_id == workspace_id)
                         .order_by(CompetitorPost.ratio_to_avg.desc().nulls_last()).limit(60))
        lines = [f"Business: {ws.name} ({ws.vertical})"]
        for p, comp in rows:
            lines.append(f"@{comp.handle} [{comp.kind}] ratio={p.ratio_to_avg} format={p.format} "
                         f"len={p.duration_s}s hook={p.hook_type} price={p.offer_price or '-'} "
                         f"date={p.posted_at.date() if p.posted_at else '-'}: {p.caption[:200]}")
        if len(lines) == 1:
            raise AppError("no_competitor_posts", "Add some competitor posts first", 409)
        asked = s.scalars(select(Feedback.text).where(
            Feedback.workspace_id == workspace_id, Feedback.category.in_(("purchase_question", "idea")),
            Feedback.at > db.utcnow() - timedelta(days=60)).limit(40)).all()
        lines.append("Questions the audience asked: " + " | ".join(a[:150] for a in asked))
        s.commit()  # hook types are saved; the AI router writes usage in its own session
        reply = await router.ask_json("competitor_analysis", ANALYSIS_SYSTEM, "\n".join(lines), workspace_id=workspace_id)
        reply = reply if isinstance(reply, dict) else {}
        suggestions = []
        for item in reply.get("suggestions") or []:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            idea = ContentIdea(workspace_id=workspace_id, text=str(item["text"])[:1000], tag=item.get("tag"),
                               source="competitor", score=1)
            s.add(idea)
            s.flush()
            suggestions.append({"text": idea.text, "tag": idea.tag, "idea_id": idea.id})
        s.add(CompetitorAnalysis(workspace_id=workspace_id, patterns=reply.get("patterns") or [],
                                 gaps=[str(g) for g in reply.get("gaps") or []], suggestions=suggestions))


async def order_video(s: Session, ws: Workspace, idea: ContentIdea) -> None:
    """Turn an insight into a content request to the admin, now."""
    sent = await notify.text(s, ws.id, t("competitors.order", text=idea.text, tag=idea.tag or "-"),
                             roles=("owner", "operator", "approver", "sender"))
    if not sent:
        raise AppError("no_bot_recipient", "Nobody in this workspace is connected to the bot yet", 409)
