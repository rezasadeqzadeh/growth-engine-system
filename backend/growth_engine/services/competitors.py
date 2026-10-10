"""Competitors and similar pages: learn from patterns, never copy.

Public pages only, only pages the user added, numbers only (no personal
data about commenters). A page is read from Meta (Business Discovery) on
the `meta` queue, one request at a time for the whole platform, or entered
by hand / from screenshots. Each post is measured against that page's own
average; the AI tags every post with a content type and topic, explains
per page what the audience reacted to, and the best type+topic pairs across
a workspace's competitors become inspiration for its own content.
"""

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..ai.opencode import ImagePart
from ..errors import AppError, NotFound
from ..i18n import t
from ..jobs import queue
from ..models import Competitor, CompetitorAnalysis, CompetitorPost, ContentIdea, Feedback, Workspace
from . import instagram_api, notify

logger = logging.getLogger(__name__)

HOOK_TYPES = ("question", "number", "contrast", "before_after", "silent_scenery", "mistakes_list", "story", "other")
WINNER_RATIO = 2.0
KINDS = ("direct", "substitute", "pattern")
CONTENT_TYPES = ("tutorial", "tips_list", "behind_the_scenes", "product_showcase", "customer_story", "offer",
                 "entertainment", "news", "personal_story", "audience_question", "other")
HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
MAX_FETCH_POSTS = 100
TAG_BATCH = 40

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

TAGS_SYSTEM = f"""Tag each post of a competitor's Instagram page.
content_type is one of: {", ".join(CONTENT_TYPES)}.
topic: 2-4 Persian words naming what the post is about; when a known topic fits, reuse it exactly,
so the same subject always has the same name. hook_type (the caption's opening) is one of: {", ".join(HOOK_TYPES)}.
JSON: {{"items": [{{"id": "...", "content_type": "...", "topic": "...", "hook_type": "..."}}]}}"""

INSIGHT_SYSTEM = f"""You study one competitor page of an Iranian small business, to learn patterns, never to copy.
Each post has its format, content type, topic, likes, comments and ratio to the page's own average.
Say which content types and which topics the audience reacted to most, and why (hook, format, emotion,
length, timing). Persian text. Content types: {", ".join(CONTENT_TYPES)}.
JSON: {{"summary": "...", "best_types": [{{"type": "...", "why": "..."}}], "best_topics": [{{"topic": "...", "why": "..."}}]}}"""

INSPIRE_SYSTEM = """Write one content idea for an Iranian small business, inspired by a pattern that drew the most
reactions on its competitors' pages. Apply the pattern to the business's own real products and story; never copy
a competitor's post. Persian text: a short title line, then the hook, the format and what to film or show.
JSON: {"text": "..."}"""

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


# --- Reading pages from Meta (the `meta` queue) ---

def request_fetch(s: Session, comp: Competitor) -> bool:
    """Queue a read of this page from Meta. False when one is already queued or running."""
    if not instagram_api.discovery_configured():
        raise AppError("meta_not_configured", "Reading pages from Instagram is not set up yet", 503)
    if not HANDLE_RE.match(comp.handle):
        raise AppError("competitor_handle_invalid", "This is not an Instagram username")
    job = queue.enqueue(s, "fetch_competitor", {"competitor_id": comp.id}, dedupe_key=f"meta:competitor:{comp.id}")
    if job is None:
        return False
    comp.fetch_status, comp.fetch_error = "queued", None
    return True


def _set_status(competitor_id: str, status: str, error: str | None = None) -> None:
    with db.session_scope() as s:
        comp = s.get(Competitor, competitor_id)
        if comp:
            comp.fetch_status, comp.fetch_error = status, error


def on_fetch_failed(payload: dict, message: str) -> None:
    _set_status(payload["competitor_id"], "failed", "fetch_failed")


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc) if value else None
    except ValueError:
        return None


def _format(m: dict) -> str:
    if m.get("media_product_type") == "REELS":
        return "reel"
    return {"CAROUSEL_ALBUM": "carousel", "VIDEO": "video"}.get(m.get("media_type") or "", "image")


def save_fetched(s: Session, comp: Competitor, profile: dict, media: list[dict]) -> int:
    """Store the profile and posts (new posts added, known posts' numbers updated). Returns posts added."""
    comp.ig_id = str(profile.get("id") or "") or comp.ig_id
    comp.name = comp.name or str(profile.get("name") or "")[:120]
    comp.biography = str(profile.get("biography") or "")
    comp.website = (str(profile.get("website"))[:300] or None) if profile.get("website") else None
    comp.profile_picture_url = profile.get("profile_picture_url")
    comp.followers = profile.get("followers_count", comp.followers)
    comp.media_count = profile.get("media_count")
    known = {p.url: p for p in s.scalars(select(CompetitorPost).where(CompetitorPost.competitor_id == comp.id))}
    added = 0
    for m in media:
        url = str(m.get("permalink") or f"ig:{m.get('id')}")[:300]
        post = known.get(url)
        if post is None:
            post = known[url] = CompetitorPost(competitor_id=comp.id, url=url)
            s.add(post)
            added += 1
        post.external_id = str(m.get("id") or "")[:40] or None
        post.posted_at = _parse_time(m.get("timestamp")) or post.posted_at
        post.format = _format(m)
        post.likes = m.get("like_count")
        post.comments = m.get("comments_count")
        post.caption = str(m.get("caption") or "")[:2000]
        post.media_url = m.get("thumbnail_url") or m.get("media_url")
    s.flush()
    recompute(s, comp)
    return added


async def fetch(payload: dict) -> None:
    """Job (meta queue): read one page's public profile and latest posts, then queue the AI analysis."""
    competitor_id = payload["competitor_id"]
    with db.session_scope() as s:
        comp = s.get(Competitor, competitor_id)
        if comp is None:
            return
        comp.fetch_status, handle = "fetching", comp.handle
    profile: dict = {}
    media: list[dict] = []
    after = None
    try:
        while len(media) < MAX_FETCH_POSTS:
            page = await instagram_api.business_discovery(handle, media_limit=min(50, MAX_FETCH_POSTS - len(media)),
                                                          after=after)
            profile = profile or page["profile"]
            media += page["media"]
            after = page["next"]
            if not after:
                break
    except instagram_api.DiscoveryNotFound:
        _set_status(competitor_id, "failed", "page_not_found")
        return
    except instagram_api.InstagramAuthExpired:
        logger.error("[competitors] the Meta discovery token has expired; set META_GRAPH_TOKEN again")
        _set_status(competitor_id, "failed", "meta_token_expired")
        return
    with db.session_scope() as s:
        comp = s.get(Competitor, competitor_id)
        if comp is None:
            return
        save_fetched(s, comp, profile, media)
        comp.fetch_status = "analyzing"
        queue.enqueue(s, "analyze_competitor", {"competitor_id": competitor_id},
                      dedupe_key=f"competitor-analysis:{competitor_id}")


async def tag_posts(s: Session, comp: Competitor) -> None:
    """Give every untagged post a content type, topic and hook (the AI, in batches)."""
    for _ in range(MAX_FETCH_POSTS // TAG_BATCH + 2):
        posts = list(s.scalars(select(CompetitorPost).where(CompetitorPost.competitor_id == comp.id,
                                                            CompetitorPost.content_type.is_(None)).limit(TAG_BATCH)))
        if not posts:
            return
        topics = s.scalars(select(CompetitorPost.topic).join(Competitor, Competitor.id == CompetitorPost.competitor_id)
                           .where(Competitor.workspace_id == comp.workspace_id, CompetitorPost.topic.is_not(None))
                           .group_by(CompetitorPost.topic).order_by(func.count().desc()).limit(60)).all()
        user = "Known topics: " + (" | ".join(topics) or "-") + "\n" + "\n".join(
            f"[{p.id}] {p.format}: {p.caption[:400] or '(no caption)'}" for p in posts)
        s.commit()  # the AI router writes usage in its own session
        reply = await router.ask_json("competitor_post_tags", TAGS_SYSTEM, user, workspace_id=comp.workspace_id)
        by_id = {i.get("id"): i for i in (reply.get("items", []) if isinstance(reply, dict) else []) if isinstance(i, dict)}
        for p in posts:
            item = by_id.get(p.id, {})
            p.content_type = item.get("content_type") if item.get("content_type") in CONTENT_TYPES else "other"
            p.topic = str(item.get("topic") or "").strip()[:80] or None
            p.hook_type = item.get("hook_type") if item.get("hook_type") in HOOK_TYPES else (p.hook_type or "other")
        s.flush()


async def analyze_one(payload: dict) -> None:
    """Job: tag one page's posts, then ask the AI what its audience reacted to."""
    competitor_id = payload["competitor_id"]
    with db.session_scope() as s:
        comp = s.get(Competitor, competitor_id)
        if comp is None:
            return
        await tag_posts(s, comp)
        recompute(s, comp)
        posts = list(s.scalars(select(CompetitorPost).where(CompetitorPost.competitor_id == comp.id)
                               .order_by(CompetitorPost.ratio_to_avg.desc().nulls_last()).limit(60)))
        if not posts:
            comp.fetch_status = "done"
            return
        lines = [f"Page @{comp.handle}, {comp.followers or '?'} followers. Bio: {comp.biography[:300]}"]
        lines += [f"ratio={p.ratio_to_avg} format={p.format} type={p.content_type} topic={p.topic} "
                  f"likes={p.likes} comments={p.comments}: {p.caption[:200]}" for p in posts]
        s.commit()
        reply = await router.ask_json("competitor_insight", INSIGHT_SYSTEM, "\n".join(lines),
                                      workspace_id=comp.workspace_id)
        reply = reply if isinstance(reply, dict) else {}
        comp.insight = {
            "summary": str(reply.get("summary") or ""),
            "best_types": [{"type": i.get("type"), "why": str(i.get("why") or "")} for i in reply.get("best_types") or []
                           if isinstance(i, dict) and i.get("type") in CONTENT_TYPES],
            "best_topics": [{"topic": str(i.get("topic")), "why": str(i.get("why") or "")}
                            for i in reply.get("best_topics") or [] if isinstance(i, dict) and i.get("topic")],
            "at": db.utcnow().isoformat(),
        }
        comp.fetch_status = "done"


def post_out(p: CompetitorPost, handle: str | None = None) -> dict:
    out = {"id": p.id, "url": p.url, "posted_at": p.posted_at.isoformat() if p.posted_at else None,
           "format": p.format, "views": p.views, "likes": p.likes, "comments": p.comments, "caption": p.caption,
           "hook_type": p.hook_type, "content_type": p.content_type, "topic": p.topic,
           "ratio_to_avg": p.ratio_to_avg, "media_url": p.media_url}
    if handle is not None:
        out["handle"] = handle
    return out


def best_items(s: Session, workspace_id: str, limit: int = 20) -> dict:
    """The content types and type+topic pairs that drew the most reactions across this workspace's competitors.

    A pair's score is its posts' average ratio to their own page's average, weighted by
    sqrt(post count) so one lucky post does not outrank a pattern that keeps working."""
    rows = s.execute(select(CompetitorPost, Competitor.handle).join(Competitor, Competitor.id == CompetitorPost.competitor_id)
                     .where(Competitor.workspace_id == workspace_id, CompetitorPost.ratio_to_avg.is_not(None),
                            CompetitorPost.content_type.is_not(None))).all()

    def rank(groups: dict[tuple, list], names: tuple[str, ...]) -> list[dict]:
        out = []
        for key, members in groups.items():
            members.sort(key=lambda r: r[0].ratio_to_avg, reverse=True)
            avg = sum(p.ratio_to_avg for p, _ in members) / len(members)
            out.append({**dict(zip(names, key)), "posts": len(members), "avg_ratio": round(avg, 2),
                        "score": round(avg * math.sqrt(len(members)), 2),
                        "reactions": sum((p.likes or 0) + (p.comments or 0) for p, _ in members),
                        "pages": sorted({h for _, h in members}),
                        "examples": [post_out(p, h) for p, h in members[:3]]})
        return sorted(out, key=lambda i: i["score"], reverse=True)[:limit]

    by_type: dict[tuple, list] = defaultdict(list)
    by_pair: dict[tuple, list] = defaultdict(list)
    for p, handle in rows:
        by_type[(p.content_type,)].append((p, handle))
        if p.topic:
            by_pair[(p.content_type, p.topic)].append((p, handle))
    return {"types": rank(by_type, ("content_type",)), "items": rank(by_pair, ("content_type", "topic"))}


async def inspire(s: Session, ws: Workspace, content_type: str, topic: str | None, post_id: str | None) -> ContentIdea:
    """Turn a winning competitor pattern into a content idea for this business (the idea bank)."""
    if content_type not in CONTENT_TYPES:
        raise AppError("content_type_invalid", "Unknown content type")
    q = (select(CompetitorPost).join(Competitor, Competitor.id == CompetitorPost.competitor_id)
         .where(Competitor.workspace_id == ws.id, CompetitorPost.content_type == content_type))
    if topic:
        q = q.where(CompetitorPost.topic == topic)
    if post_id:
        q = q.where(CompetitorPost.id == post_id)
    examples = list(s.scalars(q.order_by(CompetitorPost.ratio_to_avg.desc().nulls_last()).limit(5)))
    if not examples:
        raise NotFound("competitor post")
    user = "\n".join([f"Business: {ws.name} ({ws.vertical})", f"Pattern: type={content_type} topic={topic or '-'}",
                      *[f"Example (ratio {p.ratio_to_avg}, {p.format}): {p.caption[:300]}" for p in examples]])
    s.commit()
    reply = await router.ask_json("competitor_analysis", INSPIRE_SYSTEM, user, workspace_id=ws.id)
    text = str(reply.get("text") or "").strip() if isinstance(reply, dict) else ""
    if not text:
        raise AppError("ai_empty_reply", "The AI did not return an idea, try again", 502)
    idea = ContentIdea(workspace_id=ws.id, text=text[:1000], source="competitor", score=1)
    s.add(idea)
    s.flush()
    return idea


async def order_video(s: Session, ws: Workspace, idea: ContentIdea) -> None:
    """Turn an insight into a content request to the admin, now."""
    sent = await notify.text(s, ws.id, t("competitors.order", text=idea.text, tag=idea.tag or "-"),
                             roles=("owner", "operator", "approver", "sender"))
    if not sent:
        raise AppError("no_bot_recipient", "Nobody in this workspace is connected to the bot yet", 409)
