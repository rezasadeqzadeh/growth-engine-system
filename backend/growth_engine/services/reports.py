"""The weekly report, sent in the bot every Saturday morning:
what went out, what it brought, what worked, what did not, and the
three things to do next week."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..i18n import fa_digits, t
from ..models import CalendarSlot, Feedback, Offer, Post, PostVariant, Publication, Registration, Report, TrackedLink, Workspace
from . import notify, offers
from .metrics import latest_snapshots
from .timing import TEHRAN

SYSTEM = """You write a short weekly report in Persian for the owner of a small business.
Use only the numbers given. Structure, each a single line:
"✅ what worked: ..." (the best post and why, with its number),
"⚠ what did not: ..." (the weakest, and the likely reason),
"🎯 3 tasks for next week: 1. ... 2. ... 3. ..." (concrete; use the missing raw media,
unanswered purchase questions and seats left when given).
JSON: {"worked": "...", "did_not": "...", "tasks": ["...", "...", "..."]}"""


def last_week(today: date) -> tuple[date, date]:
    """The Iranian week (Saturday to Friday) that ended before `today`."""
    days_since_saturday = (today.weekday() + 2) % 7
    this_saturday = today - timedelta(days=days_since_saturday)
    return this_saturday - timedelta(days=7), this_saturday - timedelta(days=1)


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (datetime.combine(start, time.min, tzinfo=TEHRAN), datetime.combine(end + timedelta(days=1), time.min, tzinfo=TEHRAN))


def week_numbers(s: Session, ws: Workspace, start: date, end: date) -> dict:
    a, b = _bounds(start, end)
    snaps = latest_snapshots(s, ws.id, a)
    pubs_in = {p.id: (p, v) for p, v in s.execute(
        select(Publication, PostVariant).join(PostVariant, PostVariant.id == Publication.variant_id)
        .join(Post, Post.id == PostVariant.post_id)
        .where(Post.workspace_id == ws.id, Publication.status == "published",
               Publication.published_at >= a, Publication.published_at < b))}
    views_by_post: dict[str, int] = {}
    saves_by_post: dict[str, int] = {}
    for m, _, _ in snaps:
        if m.publication_id in pubs_in:
            post_id = pubs_in[m.publication_id][1].post_id
            views_by_post[post_id] = views_by_post.get(post_id, 0) + (m.views or 0)
            saves_by_post[post_id] = saves_by_post.get(post_id, 0) + (m.saves or 0)
    posts = {p.id: p for p in s.scalars(select(Post).where(Post.id.in_({v.post_id for _, v in pubs_in.values()})))}
    kinds = {}
    for _, v in pubs_in.values():
        kinds[v.kind] = kinds.get(v.kind, 0) + 1
    regs = list(s.execute(select(Registration, TrackedLink).outerjoin(TrackedLink, TrackedLink.id == Registration.source_link_id)
                          .where(Registration.workspace_id == ws.id, Registration.status == "paid",
                                 Registration.paid_at >= a, Registration.paid_at < b)))
    by_tag: dict[str, int] = {}
    for _, link in regs:
        key = link.tag if link and link.tag else "-"
        by_tag[key] = by_tag.get(key, 0) + 1
    ranked = sorted(views_by_post.items(), key=lambda kv: kv[1], reverse=True)
    best = ranked[0] if ranked else None
    worst = ranked[-1] if len(ranked) > 1 else None
    return {
        "posts": len(posts), "videos": sum(1 for p in posts.values() if p.asset_id),
        "variants_by_kind": kinds, "views": sum(views_by_post.values()), "registrations": len(regs),
        "registrations_by_tag": by_tag,
        "best": {"title": posts[best[0]].title, "tag": posts[best[0]].tag, "views": best[1],
                 "saves": saves_by_post.get(best[0], 0)} if best else None,
        "worst": {"title": posts[worst[0]].title, "tag": posts[worst[0]].tag, "views": worst[1]} if worst else None,
    }


async def weekly_report(payload: dict) -> None:
    with db.session_scope() as s:
        ws = s.get(Workspace, payload["workspace_id"])
        today = db.utcnow().astimezone(TEHRAN).date()
        start, end = last_week(today)
        if s.scalar(select(Report.id).where(Report.workspace_id == ws.id, Report.period_start == start)):
            return
        this = week_numbers(s, ws, start, end)
        before = week_numbers(s, ws, start - timedelta(days=7), start - timedelta(days=1))
        unanswered = s.scalar(select(func.count()).select_from(Feedback).where(
            Feedback.workspace_id == ws.id, Feedback.category == "purchase_question", Feedback.handled.is_(False))) or 0
        missing = list(s.scalars(select(CalendarSlot).where(
            CalendarSlot.workspace_id == ws.id, CalendarSlot.needs_media, CalendarSlot.post_id.is_(None),
            CalendarSlot.day > end, CalendarSlot.day <= end + timedelta(days=7))))
        offer = s.scalar(select(Offer).where(Offer.workspace_id == ws.id, Offer.active,
                                             Offer.starts_at > db.utcnow()).order_by(Offer.starts_at))
        seats = offers.seats_left(s, offer) if offer else None
        facts = {**this, "views_last_week": before["views"], "unanswered_purchase_questions": unanswered,
                 "raw_media_needed_next_week": [f"{m.day} {m.title} #{m.tag}" for m in missing],
                 "next_offer": {"title": offer.title, "seats_left": seats} if offer else None}
        reply = await router.ask_json("weekly_report", SYSTEM, str(facts), workspace_id=ws.id)
        reply = reply if isinstance(reply, dict) else {}
        change = ""
        if before["views"]:
            pct = round(100 * (this["views"] - before["views"]) / before["views"])
            change = t("report.change_up" if pct >= 0 else "report.change_down", pct=fa_digits(abs(pct)))
        tasks = reply.get("tasks") or []
        text = "\n".join(filter(None, [
            t("report.title", name=ws.name),
            t("report.summary", posts=fa_digits(this["posts"]), views=fa_digits(f"{this['views']:,}"), change=change,
              regs=fa_digits(this["registrations"])),
            reply.get("worked", ""), reply.get("did_not", ""),
            t("report.tasks", tasks=" ".join(f"{fa_digits(i)}. {task}" for i, task in enumerate(tasks[:3], 1))) if tasks else "",
        ]))
        report = Report(workspace_id=ws.id, period_start=start, period_end=end, metrics=facts,
                        insights=reply, text=text)
        s.add(report)
        if await notify.text(s, ws.id, text):
            report.sent_at = db.utcnow()
