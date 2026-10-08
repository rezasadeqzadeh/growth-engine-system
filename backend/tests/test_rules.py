"""Small rule modules: redaction, quality control, timing, calendar maths, audit scores."""

from datetime import date, datetime, timedelta, timezone

from growth_engine.redact import redact
from growth_engine.services import audit, quality, timing
from growth_engine.services.iran_calendar import jalali_month_range, occasions_between, to_hijri
from growth_engine.services.reports import last_week

UTC = timezone.utc


def test_redact_removes_every_kind_of_channel_secret():
    text = ("POST https://api.telegram.org/bot123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabc/sendVideo "
            "https://graph.instagram.com/me?access_token=IGQVJabc123&x=1 "
            "https://eitaayar.ir/api/bot987xyz/sendFile https://botapi.rubika.ir/v3/RUBIKATOKEN/sendFile "
            "Authorization: Bearer abc.def.ghi aparat/login/luser/u/lpass/HASH ltoken/LT123/")
    out = redact(text, ["HASH"])
    for secret in ("ABCDEFGHIJKLMNOPQRSTUVWXYZabc", "IGQVJabc123", "bot987xyz", "RUBIKATOKEN", "abc.def.ghi",
                   "HASH", "LT123"):
        assert secret not in out


def _variant(channel_type, caption, kind="message", has_link=True):
    return {"channel_type": channel_type, "kind": kind, "caption": caption, "has_link": has_link}


def test_quality_flags_misspelled_names_banned_words_and_missing_links():
    results = quality.check(
        [_variant("telegram", "صعود شطری. ثبت‌نام", has_link=False), _variant("instagram", "اعلام می‌دارد", "reel")],
        glossary=["شتری"], banned=["اعلام می‌دارد"], cta="ثبت‌نام", needs_link=True, faces=2,
        uses_music=False, music_licensed=False)
    by_check = {r["check"]: r for r in results}
    assert by_check["glossary"]["level"] == "warn" and "شطری→شتری" in by_check["glossary"]["params"]["words"]
    assert by_check["banned"]["level"] == "fail"
    assert by_check["link"]["level"] == "fail" and by_check["link"]["params"]["channels"] == "telegram"
    assert by_check["cta"]["params"]["channels"] == "instagram"
    assert by_check["faces"]["message"] == "qc.faces_consent"
    assert quality.has_failure(results)


def test_quality_says_so_when_faces_could_not_be_checked():
    results = quality.check([_variant("site", "متن")], glossary=[], banned=[], cta="", needs_link=False,
                            faces=None, uses_music=False, music_licensed=False)
    assert {"check": "faces", "level": "warn", "message": "qc.faces_unknown", "params": {}} in results


def test_report_tag_goes_out_the_evening_after_the_footage():
    sent = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)  # Friday morning, Tehran
    at = timing.publish_time({"mode": "next_day_evening", "hour": 18}, now=sent, source_at=sent, best_hour=20)
    local = at.astimezone(timing.TEHRAN)
    assert (local.day, local.hour, local.minute) == (10, 18, 30)


def test_best_hour_is_the_next_time_that_hour_comes():
    now = datetime(2026, 10, 9, 18, 0, tzinfo=UTC)  # 21:30 in Tehran: tonight's 20:30 has passed
    at = timing.publish_time({"mode": "best_hour"}, now=now, source_at=now, best_hour=20)
    assert at.astimezone(timing.TEHRAN).day == 10


def test_immediate_means_now():
    now = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    assert timing.publish_time({"mode": "immediate"}, now=now, source_at=now, best_hour=20) == now


def test_hijri_conversion_matches_known_dates_within_a_day():
    """The tabular calendar can be a day off the sighted one; never more."""
    year, month, day = to_hijri(date(2024, 7, 16))  # Ashura 1446 in Iran
    assert (year, month) == (1446, 1) and abs(day - 10) <= 1


def test_nowruz_and_ashura_are_occasions_with_the_right_tone():
    start, end = jalali_month_range(1405, 1)
    occ = occasions_between(start, end)
    assert occ[start].name == "نوروز" and occ[start].tone == "festive"
    muharram = occasions_between(date(2024, 7, 6), date(2024, 7, 20))
    assert any(o.tone == "silence" for o in muharram.values())


def test_last_week_is_the_iranian_week_before_today():
    start, end = last_week(date(2026, 10, 10))  # a Saturday
    assert start == date(2026, 10, 3) and end == date(2026, 10, 9)
    assert start.weekday() == 5 and end.weekday() == 4


def test_audit_cadence_counts_recent_posts_and_punishes_a_long_silence():
    now = datetime(2026, 10, 8, tzinfo=UTC)
    regular = [{"date": (now - timedelta(days=2 * i)).date().isoformat()} for i in range(13)]
    points, info = audit.score_cadence(regular, now, benchmark_per_week=3)
    assert points == 15 and info["days_since_last"] == 0
    stale = [{"date": (now - timedelta(days=47)).date().isoformat()}]
    assert audit.score_cadence(stale, now, 3)[0] <= 3


def test_audit_engagement_is_measured_against_the_vertical():
    posts = [{"likes": 60, "comments": 9}, {"likes": 30, "comments": 0}]
    points, info = audit.score_engagement(posts, 2300, benchmark_rate=0.03)
    assert info["rate"] == round(((69 / 2300) + (30 / 2300)) / 2, 4)
    assert 0 < points < 20


def test_price_in_dm_caps_the_conversion_score():
    data = {"bio": "هیئت کوهنوردی", "has_link_in_bio": True,
            "posts": [{"caption_first_line": "برنامه‌ی جمعه. جهت ثبت‌نام دایرکت دهید"}]}
    assert audit.cap_conversion(18, data) == 8
    assert audit.cap_conversion(18, {"bio": "", "has_link_in_bio": False, "posts": []}) == 10
