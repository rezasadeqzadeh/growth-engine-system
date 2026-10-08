"""The Iranian calendar for planning: occasions, holidays, and the days when
happy content does not fit (tone sober) or nothing should go out (silence)."""

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import jdatetime

DATA = Path(__file__).resolve().parent.parent / "data" / "iran_occasions.json"
TONE_RANK = {"festive": 0, "sober": 1, "silence": 2}


@dataclass(frozen=True)
class Occasion:
    day: date
    name: str
    tone: str
    holiday: bool


def to_hijri(d: date) -> tuple[int, int, int]:
    """Tabular (arithmetic) Islamic calendar; may differ from the sighted one by a day."""
    jd = d.toordinal() + 1721425  # Julian day number at noon
    days = jd - 1948440 + 10632
    n = (days - 1) // 10631
    days = days - 10631 * n + 354
    j = ((10985 - days) // 5316) * ((50 * days) // 17719) + (days // 5670) * ((43 * days) // 15238)
    days = days - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    month = (24 * days) // 709
    day = days - (709 * month) // 24
    year = 30 * n + j - 30
    return year, month, day


@lru_cache
def _rules() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def occasions_between(start: date, end: date) -> dict[date, Occasion]:
    """Every occasion day in [start, end]; on a day with two, the stricter tone wins."""
    out: dict[date, Occasion] = {}

    def put(day: date, rule: dict) -> None:
        current = out.get(day)
        if current is None or TONE_RANK[rule["tone"]] > TONE_RANK[current.tone]:
            out[day] = Occasion(day, rule["name"], rule["tone"], rule["holiday"])

    day = start
    while day <= end:
        j = jdatetime.date.fromgregorian(date=day)
        h = to_hijri(day)
        for rule in _rules()["jalali"]:
            first = jdatetime.date(j.year, rule["month"], rule["day"]).togregorian()
            if first <= day < first + timedelta(days=rule["days"]):
                put(day, rule)
        for rule in _rules()["hijri"]:
            if h[1] == rule["month"] and rule["day"] <= h[2] < rule["day"] + rule["days"]:
                put(day, rule)
        day += timedelta(days=1)
    return out


def jalali_month_range(year: int, month: int) -> tuple[date, date]:
    first = jdatetime.date(year, month, 1)
    next_first = jdatetime.date(year + (month == 12), month % 12 + 1, 1)
    return first.togregorian(), next_first.togregorian() - timedelta(days=1)
