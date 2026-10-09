"""Page audit, the lead magnet: a growth score out of 100, the 5 changes
with the most effect, and 3 of the page's own posts rewritten.

Six axes (weights):  bio and profile 15 · posting cadence 15 · hooks 20 ·
engagement 20 · brand consistency 10 · path to purchase 20.
Cadence and engagement are counted by rules; the other four are judged
by the AI against a fixed rubric, and conversion is capped by rule when
the page answers prices only in DMs.

Page data comes through a source adapter: screenshots read by the vision
model (no login, cannot be sanctioned), the official API for a connected
account, or numbers typed by an operator.
"""

import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..ai.opencode import ImagePart
from ..auth.otp import PHONE_RE
from ..errors import AppError, NotFound
from ..i18n import patterns
from ..textnorm import ascii_digits
from ..jobs import queue
from ..models import Audit, Channel
from . import instagram_api, storage, workspaces

AUDITS_PER_PHONE_PER_DAY = 3
WEIGHTS = {"bio": 15, "cadence": 15, "hooks": 20, "engagement": 20, "brand": 10, "conversion": 20}
DM_PRICE = re.compile(patterns()["dm_price"])  # "price in DM" phrasings

EXTRACT_SYSTEM = """Read these Instagram screenshots (profile, post grid, Insights) and return what is visible.
Numbers as plain integers (convert Persian digits and K/M). Dates as YYYY-MM-DD when shown or inferable, else null.
JSON: {"handle": str, "bio": str, "followers": int|null, "posts_count": int|null, "has_link_in_bio": bool,
       "highlights": [str], "posts": [{"date": str|null, "likes": int|null, "comments": int|null,
       "views": int|null, "format": "reel|carousel|image", "caption_first_line": str}]}"""

JUDGE_SYSTEM = """You audit an Iranian small business's Instagram page. Score with this rubric (integers):
bio 0-15: is it clear who it is for, is there a CTA and a link, are highlights organised?
hooks 0-20: first caption lines and reel openings: do they stop the scroll?
brand 0-10: consistent colours, templates, image quality (judge from what is described).
conversion 0-20: does the audience know how to buy or register? "price in DM" lowers it.
Then the 5 changes with the most effect, most important first, concrete and short (Persian),
and rewrite 3 of the page's real captions (before = the original first line, after = your rewrite
in Persian, outcome-focused, with a CTA; never invent facts).
JSON: {"scores": {"bio": n, "hooks": n, "brand": n, "conversion": n},
       "fixes": [5 strings], "rewrites": [{"before": "...", "after": "..."}]}"""


def _parse_date(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def score_cadence(posts: list[dict], now: datetime, benchmark_per_week: float) -> tuple[int, dict]:
    """15 points: posts per week over the last 30 days against the vertical's
    benchmark, minus a penalty for the days since the last post."""
    dates = sorted((d for d in (_parse_date(p.get("date")) for p in posts) if d), reverse=True)
    if not dates:
        return 0, {"posts_per_week": 0, "days_since_last": None}
    recent = [d for d in dates if d >= now - timedelta(days=30)]
    per_week = len(recent) / (30 / 7)
    days_since = (now - dates[0]).days
    points = WEIGHTS["cadence"] * min(per_week / benchmark_per_week, 1.0)
    if days_since > 14:
        points *= 0.5
    if days_since > 30:
        points = min(points, 3)
    return round(points), {"posts_per_week": round(per_week, 1), "days_since_last": days_since}


def score_engagement(posts: list[dict], followers: int | None, benchmark_rate: float) -> tuple[int, dict]:
    """20 points: average (likes + comments) / followers against the vertical's average."""
    if not followers:
        return 0, {"rate": None}
    rates = [((p.get("likes") or 0) + (p.get("comments") or 0)) / followers
             for p in posts if p.get("likes") is not None]
    if not rates:
        return 0, {"rate": None}
    rate = sum(rates) / len(rates)
    return round(WEIGHTS["engagement"] * min(rate / benchmark_rate, 1.0)), {"rate": round(rate, 4)}


def cap_conversion(points: int, data: dict) -> int:
    texts = [data.get("bio", "")] + [p.get("caption_first_line", "") for p in data.get("posts", [])]
    if any(DM_PRICE.search(t or "") for t in texts):
        points = min(points, 8)
    if not data.get("has_link_in_bio"):
        points = min(points, 10)
    return points


def create(s: Session, *, handle: str, vertical: str, phone: str, input_kind: str,
           screenshots: list[tuple[bytes, str]] | None = None, manual: dict | None = None,
           agency_id: str | None = None, channel_id: str | None = None) -> Audit:
    handle, phone = ascii_digits(handle).lstrip("@"), ascii_digits(phone)
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
        raise AppError("handle_invalid", "Enter the page id, e.g. boshrouyeh_kooh")
    if not PHONE_RE.match(phone):
        raise AppError("phone_invalid", "Phone must match 09xxxxxxxxx")
    workspaces.vertical(vertical)
    # Public and AI-backed: a phone gets a few audits a day, not unlimited model time.
    recent = s.scalars(select(Audit.id).where(Audit.phone == phone,
                                              Audit.created_at > db.utcnow() - timedelta(days=1))).all()
    if len(recent) >= AUDITS_PER_PHONE_PER_DAY:
        raise AppError("audit_limit", "You have asked for enough audits today", 429)
    if input_kind == "screenshots" and not screenshots:
        raise AppError("screenshots_required", "Send at least one screenshot")
    audit = Audit(slug=f"{handle.lower()}-{secrets.token_hex(3)}", handle=handle, vertical=vertical, phone=phone,
                  agency_id=agency_id, input_kind=input_kind, data=manual or {})
    s.add(audit)
    s.flush()
    keys = []
    for data, mime in (screenshots or [])[:6]:
        suffix = ".png" if "png" in mime else ".jpg"
        keys.append(storage.save_bytes(storage.new_key("audits", audit.id, suffix), data))
    audit.screenshot_keys = keys
    queue.enqueue(s, "run_audit", {"audit_id": audit.id, "channel_id": channel_id})
    return audit


async def _gather(s: Session, audit: Audit, channel_id: str | None) -> dict:
    if audit.input_kind == "manual":
        return audit.data
    if audit.input_kind == "instagram_api":
        channel = s.get(Channel, channel_id) if channel_id else None
        token = (channel.credentials or {}).get("access_token") if channel else None
        if not token:
            raise AppError("instagram_not_connected", "Instagram is not connected", 409)
        prof = await instagram_api.profile(token)
        media = await instagram_api.recent_media(token, 30)
        return {"handle": prof.get("username"), "bio": "", "followers": prof.get("followers_count"),
                "posts_count": prof.get("media_count"), "has_link_in_bio": False, "highlights": [],
                "posts": [{"date": m.get("timestamp", "")[:10], "likes": m.get("like_count"),
                           "comments": m.get("comments_count"),
                           "format": {"VIDEO": "reel", "CAROUSEL_ALBUM": "carousel"}.get(m.get("media_type"), "image"),
                           "caption_first_line": (m.get("caption") or "").split("\n")[0][:200]} for m in media]}
    images = [ImagePart(storage.read_bytes(k), "image/png" if k.endswith(".png") else "image/jpeg", k.rsplit("/", 1)[-1])
              for k in audit.screenshot_keys]
    data = await router.ask_json("read_screenshot", EXTRACT_SYSTEM, f"Page: @{audit.handle}", images=images)
    return data if isinstance(data, dict) else {}


async def run(payload: dict) -> None:
    with db.session_scope() as s:
        audit = s.get(Audit, payload["audit_id"])
        if audit is None:
            return
        audit.status = "running"
        s.commit()
        bench = workspaces.vertical(audit.vertical)["audit_benchmark"]
        data = await _gather(s, audit, payload.get("channel_id"))
        posts = data.get("posts") or []
        now = db.utcnow()
        cadence, cadence_info = score_cadence(posts, now, float(bench["posts_per_week"]))
        engagement, engagement_info = score_engagement(posts, data.get("followers"), float(bench["engagement_rate"]))
        summary = {**data, "cadence": cadence_info, "engagement": engagement_info}
        s.commit()
        judged = await router.ask_json("audit", JUDGE_SYSTEM, f"Page data:\n{summary}")
        judged = judged if isinstance(judged, dict) else {}
        ai_scores = judged.get("scores") or {}
        scores = {"cadence": cadence, "engagement": engagement}
        for axis in ("bio", "hooks", "brand", "conversion"):
            try:
                scores[axis] = max(0, min(int(ai_scores.get(axis, 0)), WEIGHTS[axis]))
            except (TypeError, ValueError):
                scores[axis] = 0
        scores["conversion"] = cap_conversion(scores["conversion"], data)
        audit.data = summary
        audit.scores = scores
        audit.total = sum(scores.values())
        audit.fixes = [str(f) for f in (judged.get("fixes") or [])][:5]
        audit.rewrites = [r for r in (judged.get("rewrites") or []) if isinstance(r, dict)][:3]
        audit.status = "done"


def on_failed(payload: dict, message: str) -> None:
    with db.session_scope() as s:
        audit = s.get(Audit, payload["audit_id"])
        if audit:
            audit.status, audit.error = "failed", message[:300]


def get_by_slug(s: Session, slug: str) -> Audit:
    audit = s.scalar(select(Audit).where(Audit.slug == slug))
    if audit is None:
        raise NotFound("audit")
    return audit


def to_dict(audit: Audit) -> dict:
    bench = workspaces.vertical(audit.vertical)["audit_benchmark"]
    return {"slug": audit.slug, "handle": audit.handle, "vertical": audit.vertical, "status": audit.status,
            "total": audit.total, "scores": audit.scores, "weights": WEIGHTS, "benchmark": bench["score"],
            "followers": (audit.data or {}).get("followers"), "posts_count": (audit.data or {}).get("posts_count"),
            "cadence": (audit.data or {}).get("cadence"), "fixes": audit.fixes, "rewrites": audit.rewrites,
            "wants_service": audit.wants_service, "created_at": audit.created_at.isoformat()}
