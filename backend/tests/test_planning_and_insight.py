"""Calendar, feedback inbox, audit, competitors, weekly report, scheduler, brand kit."""

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from growth_engine import db
from growth_engine.i18n import catalog
from growth_engine.jobs import scheduler
from growth_engine.models import (
    Audit, CalendarSlot, Competitor, CompetitorAnalysis, ContentIdea, Feedback, Job, Offer, Report, TagRecipe,
    Workspace,
)
from growth_engine.services import audit, brand_kit, calendar, competitors, feedback, reports
from growth_engine.services.iran_calendar import jalali_month_range
from growth_engine.services.timing import TEHRAN

UTC = timezone.utc


def _recipes(s, ws_id):
    return list(s.scalars(select(TagRecipe).where(TagRecipe.workspace_id == ws_id)))


def test_a_month_plan_follows_the_weekly_slots_and_the_goal_mix(workspace):
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        kit = brand_kit.current(s, ws.id)
        start, end = jalali_month_range(1405, 9)  # Azar 1405
        plan = calendar.plan_month(start, end, weekly=ws.settings["weekly_slots"], goal_mix=ws.settings["goal_mix"],
                                   pillars=kit.pillars, recipes=_recipes(s, ws.id), offers=[],
                                   event_tags=ws.settings["event_tags"])
    weeks = 5
    posts = [p for p in plan if p["kind"] == "post"]
    assert len(posts) <= 3 * weeks and len([p for p in plan if p["kind"] == "reel"]) <= weeks
    goals = [p["goal"] for p in plan if p["kind"] != "story"]
    share = {g: goals.count(g) / len(goals) for g in ("attract", "trust", "convert")}
    assert abs(share["attract"] - 0.4) < 0.15 and abs(share["convert"] - 0.2) < 0.15
    assert all(p["tag"] for p in plan if p["kind"] != "story")
    assert all(not p["needs_media"] for p in plan if p["kind"] == "story")


def test_a_business_event_pins_announce_reminder_and_report(workspace):
    event = datetime(2026, 12, 5, 6, 0, tzinfo=UTC)  # 14 Azar 1405
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        offer = Offer(id="o1", workspace_id=ws.id, slug="k", title="کوه و کویر", starts_at=event)
        start, end = jalali_month_range(1405, 9)
        plan = calendar.plan_month(start, end, weekly={"post": 0, "reel": 0, "story": 0}, goal_mix={},
                                   pillars=[], recipes=_recipes(s, ws.id), offers=[offer],
                                   event_tags=ws.settings["event_tags"])
    by_role = {p["role"]: p for p in plan}
    assert by_role["announce"]["day"] == date(2026, 11, 25) and by_role["announce"]["tag"] == "اعلام_برنامه"
    assert by_role["reminder"]["day"] == date(2026, 12, 2) and by_role["reminder"]["kind"] == "story"
    assert by_role["report"]["day"] == date(2026, 12, 6) and by_role["report"]["tag"] == "گزارش_برنامه"


def test_silence_days_get_no_slots(workspace):
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        start, end = date(2024, 7, 13), date(2024, 7, 19)  # around Tasua/Ashura 1446
        plan = calendar.plan_month(start, end, weekly={"post": 7, "reel": 0, "story": 0},
                                   goal_mix={"attract": 1}, pillars=[], recipes=_recipes(s, ws.id), offers=[],
                                   event_tags={})
    from growth_engine.services.iran_calendar import occasions_between
    silent = {d for d, o in occasions_between(start, end).items() if o.tone == "silence"}
    assert silent and not silent & {p["day"] for p in plan}


async def test_generating_a_month_fills_slots_from_the_idea_bank_then_the_ai(workspace, ai):
    ai.on("Suggest one concrete post idea", lambda p: {"ideas": [{"slot": i, "title": f"ایده {i}"}
                                                                 for i in range(40)]})
    with db.session_scope() as s:
        s.add(ContentIdea(workspace_id=workspace["id"], text="مسیرهای مناسب شروع", source="feedback"))
    with db.session_scope() as s:
        rows = await calendar.generate_month(s, s.get(Workspace, workspace["id"]), 1405, 9)
        assert rows and all(r.title for r in rows)
        assert any(r.title == "مسیرهای مناسب شروع" for r in rows)
        assert s.scalar(select(ContentIdea)).used


async def test_content_requests_ask_the_admin_two_days_ahead(workspace, monkeypatch):
    sent = []

    async def fake_text(s, workspace_id, message, roles=(), keyboard=None):
        sent.append(message)
        return [{"ok": True}]
    monkeypatch.setattr(calendar.notify, "text", fake_text)
    tomorrow = (db.utcnow().astimezone(TEHRAN) + timedelta(days=1)).date()
    with db.session_scope() as s:
        s.add(CalendarSlot(workspace_id=workspace["id"], day=tomorrow, kind="reel", tag="آموزش",
                           title="چیدن کوله", needs_media=True))
    await calendar.send_content_requests({"workspace_id": workspace["id"]})
    assert len(sent) == 1 and "چیدن کوله" in sent[0] and "#آموزش" in sent[0]
    await calendar.send_content_requests({"workspace_id": workspace["id"]})
    assert len(sent) == 1  # asked once


async def test_feedback_is_sorted_with_suggested_replies_and_alerts(workspace, ai, monkeypatch):
    alerts = []

    async def fake_text(s, workspace_id, message, roles=(), keyboard=None):
        alerts.append(message)
        return []
    monkeypatch.setattr(feedback.notify, "text", fake_text)
    with db.session_scope() as s:
        rows = [feedback._store(s, workspace["id"], "instagram", str(i), "u", text, db.utcnow())
                for i, text in enumerate(["قیمت چنده؟", "عالی بود", "هماهنگی ضعیف بود", "بخرید ارزان", "برای مبتدی؟"])]
        ids = [r.id for r in rows]
    cats = ["purchase_question", "praise", "criticism", "spam", "idea"]
    ai.on("You sort audience messages", {"items": [
        {"id": i, "category": c, "reply": "پاسخ" if c != "criticism" else "should be dropped",
         "idea": "مسیرهای مبتدی" if c == "idea" else ""} for i, c in zip(ids, cats)]})
    await feedback.classify_pending({"workspace_id": workspace["id"]})
    with db.session_scope() as s:
        by_cat = {f.category: f for f in s.scalars(select(Feedback))}
        assert by_cat["purchase_question"].suggested_reply == "پاسخ"
        assert by_cat["criticism"].suggested_reply is None and by_cat["criticism"].alerted
        assert by_cat["spam"].hidden
        assert s.scalar(select(ContentIdea)).text == "مسیرهای مبتدی"
    assert len(alerts) == 1 and "هماهنگی ضعیف بود" in alerts[0]


async def test_an_audit_scores_six_axes_out_of_100(workspace, ai):
    now = db.utcnow()
    ai.on("Read these Instagram screenshots", {
        "handle": "boshrouyeh_kooh", "bio": "هیئت کوهنوردی شهرستان", "followers": 2300, "posts_count": 180,
        "has_link_in_bio": False, "highlights": [],
        "posts": [{"date": (now - timedelta(days=47)).date().isoformat(), "likes": 60, "comments": 4,
                   "caption_first_line": "برنامه‌ی صعود جمعه. جهت ثبت‌نام دایرکت دهید."}]})
    ai.on("You audit an Iranian", {"scores": {"bio": 6, "hooks": 7, "brand": 5, "conversion": 19},
                                   "fixes": ["f1", "f2", "f3", "f4", "f5", "f6"],
                                   "rewrites": [{"before": "a", "after": "b"}]})
    with db.session_scope() as s:
        a = audit.create(s, handle="@boshrouyeh_kooh", vertical="sports_board", phone="09150002222",
                         input_kind="screenshots", screenshots=[(b"png", "image/png")])
        slug = a.slug
    from growth_engine.jobs import runner
    assert await runner.run_one()
    with db.session_scope() as s:
        a = audit.get_by_slug(s, slug)
        assert a.status == "done"
        assert a.scores["conversion"] == 8  # "DM for registration" caps it
        assert a.scores["cadence"] <= 3      # 47 days without a post
        assert a.total == sum(a.scores.values()) and len(a.fixes) == 5


def test_competitor_posts_are_measured_against_their_own_page(workspace):
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        comp = competitors.add(s, ws, "@yazd_desert_tour", "substitute", followers=10000)
        competitors.add_posts(s, comp, [{"url": "u1", "views": 3400, "likes": 300}, {"url": "u2", "views": 800},
                                        {"url": "u3", "views": 800}])
        ratios = sorted(p.ratio_to_avg for p in s.scalars(select(competitors.CompetitorPost)))
        assert ratios[-1] == round(3400 / ((3400 + 800 + 800) / 3), 2)
        assert competitors.add_posts(s, comp, [{"url": "u1", "views": 1}]) == 0  # no duplicates


async def test_competitor_analysis_turns_suggestions_into_ideas(workspace, ai):
    ai.on("Classify each caption", lambda p: {"items": [{"id": i, "hook_type": "silent_scenery"}
                                                        for i in re.findall(r"\[(\w+)\]", p.user)]})
    ai.on("You study competitors", {"patterns": [{"name": "آسمان شب کویر", "ratio": 3.4}], "gaps": ["مبتدی‌ها"],
                                    "suggestions": [{"text": "ریلز شب در کویر بعد از صعود", "tag": "منظره"}]})
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        comp = competitors.add(s, ws, "yazd", "substitute")
        competitors.add_posts(s, comp, [{"url": "u1", "views": 3400, "caption": "شب کویر"},
                                        {"url": "u2", "views": 600, "caption": "صبح"},
                                        {"url": "u3", "views": 600, "caption": "ظهر"}])
    await competitors.analyze({"workspace_id": workspace["id"]})
    with db.session_scope() as s:
        analysis = s.scalar(select(CompetitorAnalysis))
        assert analysis.gaps == ["مبتدی‌ها"] and analysis.suggestions[0]["idea_id"]
        assert s.scalar(select(ContentIdea)).source == "competitor"
        assert s.scalar(select(Competitor)).best_hook == "silent_scenery"


async def test_the_weekly_report_is_written_once_and_sent(workspace, ai, monkeypatch):
    sent = []

    async def fake_text(s, workspace_id, message, roles=(), keyboard=None):
        sent.append(message)
        return [{"ok": True}]
    monkeypatch.setattr(reports.notify, "text", fake_text)
    ai.on("weekly report", {"worked": "✅ نقل‌قول", "did_not": "⚠ آموزش", "tasks": ["الف", "ب", "ج"]})
    await reports.weekly_report({"workspace_id": workspace["id"]})
    await reports.weekly_report({"workspace_id": workspace["id"]})
    with db.session_scope() as s:
        rows = list(s.scalars(select(Report)))
        assert len(rows) == 1 and rows[0].sent_at is not None
    assert len(sent) == 1 and "✅ نقل‌قول" in sent[0] and "۱. الف" in sent[0]


def test_the_scheduler_enqueues_each_periodic_job_once_per_period(workspace):
    saturday_morning = datetime(2026, 10, 10, 7, 0, tzinfo=UTC)  # 10:30 Tehran
    first = scheduler.tick(saturday_morning)
    again = scheduler.tick(saturday_morning + timedelta(minutes=1))
    with db.session_scope() as s:
        kinds = {j.kind for j in s.scalars(select(Job))}
    assert {"weekly_report", "send_content_requests", "channel_health", "auto_approve"} <= kinds
    assert first > 0 and again == 0


async def test_brand_kit_generation_saves_a_new_version_and_keeps_valid_colours(workspace, ai):
    ai.on("brand strategist", {"colors": {"primary": ["#8B5E3C", "nothex"], "accent": ["#C9A66B", "#4F7942"],
                                          "text": "#FFFFFF"},
                               "tone": {"adjectives": ["صمیمی", "مطمئن", "ماجراجو"], "anti": ["اداری"]},
                               "pillars": [{"key": "routes", "name": "مسیرها", "goal": "attract"},
                                           {"key": "bad", "name": "x", "goal": "sell"}],
                               "glossary": ["شتری", "قلعه دختر"], "banned": ["هیئت محترم"]})
    with db.session_scope() as s:
        kit = await brand_kit.generate(s, workspace["id"], {"one_sentence": "هیئت کوهنوردی بشرویه"})
        assert kit.version == 2 and kit.is_current
        assert kit.colors["primary"] == brand_kit.DEFAULT_COLORS["primary"]  # one bad hex: the pair is refused
        assert [p["key"] for p in kit.pillars] == ["routes"]
        assert brand_kit.current(s, workspace["id"]).id == kit.id


def test_every_i18n_key_used_in_code_exists():
    root = Path(__file__).resolve().parent.parent / "growth_engine"
    used = set()
    for path in list(root.rglob("*.py")) + list(root.rglob("*.html")):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z_]+\.[a-z_.]+)["']""", path.read_text(encoding="utf-8")))
    families = {f"channel.{c}" for c in ("instagram", "bale", "telegram", "aparat", "eitaa", "rubika", "site")}
    families |= {"bot.approved", "bot.rejected", "bot.scheduled", "bot.publish_failed", "bot.processing_failed",
                 "bot.approved_in_panel", "post.reminder", "report.change_down", "handoff.reel", "handoff.story",
                 "handoff.step1", "handoff.step2", "handoff.step3", "handoff.step4", "calendar.announce",
                 "calendar.reminder", "calendar.report", "calendar.tone_festive", "calendar.tone_sober",
                 "calendar.tone_silence"}
    from growth_engine.services import quality
    qc_keys = set(re.findall(r'"(qc\.[a-z_]+)"', Path(quality.__file__).read_text()))
    missing = sorted((used | families | qc_keys) - set(catalog()))
    assert not missing, missing


def test_goals_are_interleaved_through_the_month_not_in_blocks(workspace):
    """Goals used to be handed out in date order until each ran out: all attract first, then trust, then convert."""
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        start, end = jalali_month_range(1405, 9)
        plan = calendar.plan_month(start, end, weekly={"post": 3, "reel": 1, "story": 0}, goal_mix=ws.settings["goal_mix"],
                                   pillars=brand_kit.current(s, ws.id).pillars, recipes=_recipes(s, ws.id), offers=[],
                                   event_tags={})
    first_half = [p["goal"] for p in plan[: len(plan) // 2]]
    assert {"attract", "trust", "convert"} <= set(first_half)
