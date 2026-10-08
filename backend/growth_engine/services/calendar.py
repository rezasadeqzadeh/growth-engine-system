"""The content calendar.

for each week in the month:
    slots = workspace.weekly_slots                  (e.g. 3 posts + 1 reel + 5 stories)
    pin business events                             announce = event - 10d, reminder = event - 3d,
                                                    report = event + 1d
    apply the Iranian calendar                      occasions set the tone; silence days stay empty
    balance goals                                   attract 40% / trust 40% / convert 20%
    fill empty slots                                idea bank, then AI ideas (with competitor patterns)
    slots that need raw media                       the bot asks the admin for them in advance
"""

from collections import Counter
from datetime import date, datetime, timedelta

import jdatetime
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..errors import NotFound
from ..i18n import fa_digits, t
from ..models import BrandKit, CalendarSlot, CompetitorAnalysis, ContentIdea, Offer, Post, TagRecipe, Workspace
from . import brand_kit, iran_calendar, notify
from .timing import TEHRAN

# Weekday index from Saturday (the Iranian week): 0 Sat ... 6 Fri.
POST_DAYS = (0, 2, 4, 1, 3, 5, 6)
REEL_DAYS = (5, 1, 3)
STORY_DAYS = (0, 1, 2, 3, 5, 4, 6)
REQUEST_AHEAD = timedelta(days=2)

IDEAS_SYSTEM = """Suggest one concrete post idea per slot for an Iranian small business, in Persian.
Use real things about the business (from its pillars and the competitor patterns), never invented facts.
Each idea says what to film in one short line (e.g. "a 30-second video of packing a backpack").
JSON: {"ideas": [{"slot": index, "title": "..."}]}"""


def _iran_weekday(d: date) -> int:
    return (d.weekday() + 2) % 7  # Monday=0 -> Saturday=0


def _weeks(start: date, end: date) -> list[list[date]]:
    weeks, current = [], []
    day = start
    while day <= end:
        current.append(day)
        if _iran_weekday(day) == 6:
            weeks.append(current)
            current = []
        day += timedelta(days=1)
    if current:
        weeks.append(current)
    return weeks


def _pick(days: list[date], order: tuple[int, ...], count: int) -> list[date]:
    by_weekday = {_iran_weekday(d): d for d in days}
    chosen = [by_weekday[w] for w in order if w in by_weekday][:count]
    return sorted(chosen)


def _recipe_by_goal(recipes: list[TagRecipe], goal: str, pillar: str | None) -> TagRecipe | None:
    return (next((r for r in recipes if r.pillar == pillar), None)
            or next((r for r in recipes if r.goal == goal), None))


def plan_month(start: date, end: date, *, weekly: dict, goal_mix: dict, pillars: list[dict],
               recipes: list[TagRecipe], offers: list[Offer], event_tags: dict) -> list[dict]:
    """Pure planning: the slots for [start, end] as dicts (tested without a DB)."""
    occasions = iran_calendar.occasions_between(start, end)
    slots: list[dict] = []

    def free_day(d: date) -> date | None:
        # A silence day publishes nothing; the slot moves to the next free day.
        for _ in range(7):
            if d > end:
                return None
            occ = occasions.get(d)
            if occ is None or occ.tone != "silence":
                return d
            d += timedelta(days=1)
        return None

    recipe_by_tag = {r.tag: r for r in recipes}
    for offer in offers:
        if offer.starts_at is None:
            continue
        event = offer.starts_at.astimezone(TEHRAN).date()
        pins = [(event - timedelta(days=10), "post", event_tags.get("announce"), "announce"),
                (event - timedelta(days=3), "story", event_tags.get("announce"), "reminder"),
                (event + timedelta(days=1), "reel", event_tags.get("report"), "report")]
        for day, kind, tag, role in pins:
            if not tag or not start <= day <= end:
                continue
            day = free_day(day)
            if day is None:
                continue
            recipe = recipe_by_tag.get(tag)
            slots.append({"day": day, "kind": kind, "tag": tag, "goal": recipe.goal if recipe else "convert",
                          "pillar": recipe.pillar if recipe else None, "offer_id": offer.id, "role": role,
                          "pinned": True, "needs_media": role != "reminder"})

    for week in _weeks(start, end):
        taken = Counter((s["day"], s["kind"]) for s in slots)
        for kind, order in (("post", POST_DAYS), ("reel", REEL_DAYS), ("story", STORY_DAYS)):
            count = int(weekly.get(kind, 0)) - sum(1 for s in slots if s["kind"] == kind and s["day"] in week)
            for day in _pick(week, order, max(count, 0)):
                day = free_day(day)
                if day is None or taken[(day, kind)]:
                    continue
                taken[(day, kind)] += 1
                slots.append({"day": day, "kind": kind, "tag": None, "goal": None, "pillar": None,
                              "offer_id": None, "role": "regular", "pinned": False,
                              # Stories are cut from the week's posts; they need no new footage.
                              "needs_media": kind != "story"})

    # Balance: give the open slots the goals that bring the month to the target mix.
    open_slots = sorted((s for s in slots if not s["pinned"] and s["kind"] != "story"), key=lambda s: s["day"])
    have = Counter(s["goal"] for s in slots if s["pinned"] and s["kind"] != "story")
    target = {g: float(goal_mix.get(g, 0)) for g in ("attract", "trust", "convert")}
    pillar_turn = Counter()
    for done, slot in enumerate(open_slots, start=1):
        # Interleave through the month: each slot takes the goal furthest behind its share so far.
        goal = max(target, key=lambda g: target[g] * (done + sum(have.values())) - have[g])
        have[goal] += 1
        choices = [p for p in pillars if p.get("goal") == goal] or pillars
        pillar = choices[pillar_turn[goal] % len(choices)] if choices else None
        pillar_turn[goal] += 1
        recipe = _recipe_by_goal(recipes, goal, pillar.get("key") if pillar else None)
        slot.update(goal=goal, pillar=pillar.get("key") if pillar else None, tag=recipe.tag if recipe else None)

    for slot in slots:
        occ = occasions.get(slot["day"])
        slot["occasion"] = occ.name if occ else None
        slot["tone"] = occ.tone if occ else None
    return sorted(slots, key=lambda s: (s["day"], s["kind"]))


def balance(slots: list[CalendarSlot]) -> dict[str, int]:
    counted = [s.goal for s in slots if s.goal and s.kind != "story"]
    if not counted:
        return {"attract": 0, "trust": 0, "convert": 0}
    c = Counter(counted)
    return {g: round(100 * c[g] / len(counted)) for g in ("attract", "trust", "convert")}


async def generate_month(s: Session, ws: Workspace, jalali_year: int, jalali_month: int) -> list[CalendarSlot]:
    start, end = iran_calendar.jalali_month_range(jalali_year, jalali_month)
    kit: BrandKit = brand_kit.current(s, ws.id)
    recipes = list(s.scalars(select(TagRecipe).where(TagRecipe.workspace_id == ws.id)))
    window_start = datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=TEHRAN)
    window_end = datetime.combine(end + timedelta(days=11), datetime.min.time(), tzinfo=TEHRAN)
    offers = list(s.scalars(select(Offer).where(Offer.workspace_id == ws.id, Offer.active,
                                                Offer.starts_at >= window_start, Offer.starts_at <= window_end)))
    settings = ws.settings or {}
    planned = plan_month(start, end, weekly=settings.get("weekly_slots", {}), goal_mix=settings.get("goal_mix", {}),
                         pillars=kit.pillars or [], recipes=recipes, offers=offers,
                         event_tags=settings.get("event_tags", {}))
    # Regenerating keeps every slot already tied to a post or already requested from the admin.
    s.execute(delete(CalendarSlot).where(CalendarSlot.workspace_id == ws.id, CalendarSlot.day >= start,
                                         CalendarSlot.day <= end, CalendarSlot.post_id.is_(None),
                                         CalendarSlot.request_sent_at.is_(None)))
    kept = {(sl.day, sl.kind) for sl in s.scalars(select(CalendarSlot).where(
        CalendarSlot.workspace_id == ws.id, CalendarSlot.day >= start, CalendarSlot.day <= end))}
    offers_by_id = {o.id: o for o in offers}
    rows: list[CalendarSlot] = []
    for p in planned:
        if (p["day"], p["kind"]) in kept:
            continue
        title = ""
        if p["role"] in ("announce", "reminder", "report") and p["offer_id"]:
            title = t(f"calendar.{p['role']}", title=offers_by_id[p["offer_id"]].title)
        elif p["kind"] == "story":
            title = t("calendar.story")
        row = CalendarSlot(workspace_id=ws.id, day=p["day"], kind=p["kind"], pillar=p["pillar"], goal=p["goal"],
                           tag=p["tag"], title=title, occasion=p["occasion"], offer_id=p["offer_id"],
                           needs_media=p["needs_media"], note=t(f"calendar.tone_{p['tone']}") if p["tone"] else "")
        s.add(row)
        rows.append(row)
    s.commit()  # the AI router writes usage in its own session
    await _fill(s, ws, kit, [r for r in rows if not r.title])
    return rows


async def _fill(s: Session, ws: Workspace, kit: BrandKit, empty: list[CalendarSlot]) -> None:
    if not empty:
        return
    ideas = list(s.scalars(select(ContentIdea).where(ContentIdea.workspace_id == ws.id, ContentIdea.used.is_(False))
                           .order_by(ContentIdea.score.desc(), ContentIdea.created_at)))
    remaining = []
    for slot in empty:
        idea = next((i for i in ideas if not i.used and (i.pillar in (None, slot.pillar)) and (i.tag in (None, slot.tag))),
                    None)
        if idea is None:
            remaining.append(slot)
            continue
        idea.used = True
        slot.title, slot.idea_id = idea.text[:200], idea.id
    if not remaining:
        return
    s.commit()  # the AI router writes usage in its own session
    analysis = s.scalar(select(CompetitorAnalysis).where(CompetitorAnalysis.workspace_id == ws.id)
                        .order_by(CompetitorAnalysis.created_at.desc()))
    patterns = ", ".join(p.get("name", "") for p in (analysis.patterns if analysis else [])[:5])
    pillar_names = {p["key"]: p["name"] for p in kit.pillars or []}
    lines = [f"Business: {ws.name}", f"Winning patterns among similar pages: {patterns or '-'}"]
    lines += [f"[{i}] {sl.day.isoformat()} {sl.kind} pillar={pillar_names.get(sl.pillar or '', sl.pillar)} "
              f"tag=#{sl.tag} occasion={sl.occasion or '-'}" for i, sl in enumerate(remaining)]
    reply = await router.ask_json("slot_ideas", IDEAS_SYSTEM, "\n".join(lines), workspace_id=ws.id)
    for item in reply.get("ideas", []) if isinstance(reply, dict) else []:
        index = item.get("slot")
        if isinstance(index, int) and 0 <= index < len(remaining) and item.get("title"):
            remaining[index].title = str(item["title"])[:200]


def move(s: Session, workspace_id: str, slot_id: str, day: date) -> CalendarSlot:
    slot = s.get(CalendarSlot, slot_id)
    if slot is None or slot.workspace_id != workspace_id:
        raise NotFound("slot")
    slot.day = day
    return slot


def attach_post(s: Session, post: Post, at: datetime) -> None:
    """An approved post fills the nearest open slot with its tag (within 3 days)."""
    day = at.astimezone(TEHRAN).date()
    slots = list(s.scalars(select(CalendarSlot).where(
        CalendarSlot.workspace_id == post.workspace_id, CalendarSlot.post_id.is_(None), CalendarSlot.tag == post.tag,
        CalendarSlot.day >= day - timedelta(days=3), CalendarSlot.day <= day + timedelta(days=3))))
    if slots:
        best = min(slots, key=lambda sl: abs((sl.day - day).days))
        best.post_id, best.needs_media = post.id, False


async def send_content_requests(payload: dict) -> None:
    """"For Thursday we need a 30-second video of ..., with tag #..." — so raw media never runs out."""
    with db.session_scope() as s:
        ws = s.get(Workspace, payload["workspace_id"])
        today = db.utcnow().astimezone(TEHRAN).date()
        due = list(s.scalars(select(CalendarSlot).where(
            CalendarSlot.workspace_id == ws.id, CalendarSlot.needs_media, CalendarSlot.post_id.is_(None),
            CalendarSlot.request_sent_at.is_(None), CalendarSlot.day > today,
            CalendarSlot.day <= today + REQUEST_AHEAD)))
        recipes = {r.tag: r for r in s.scalars(select(TagRecipe).where(TagRecipe.workspace_id == ws.id))}
        for slot in due:
            recipe = recipes.get(slot.tag or "")
            seconds = fa_digits((recipe.video_spec or {}).get("max_s", 30)) if recipe else fa_digits(30)
            day_name = _day_name(slot.day)
            sent = await notify.text(s, ws.id, t("calendar.request", day=day_name, seconds=seconds,
                                                 title=slot.title or "-", tag=slot.tag or "-"),
                                     roles=("owner", "operator", "approver", "sender"))
            if sent:
                slot.request_sent_at = db.utcnow()


def _day_name(d: date) -> str:
    return fa_digits(jdatetime.date.fromgregorian(date=d, locale="fa_IR").strftime("%A %d %B"))
