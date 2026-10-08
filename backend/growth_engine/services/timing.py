"""When a post goes out, from its recipe's timing (Tehran local time)."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")


def _at(day: datetime, hour: int, minute: int = 30) -> datetime:
    return datetime.combine(day.date(), time(hour, minute), tzinfo=TEHRAN)


def next_at_hour(now: datetime, hour: int, minute: int = 30) -> datetime:
    local = now.astimezone(TEHRAN)
    candidate = _at(local, hour, minute)
    if candidate <= local + timedelta(minutes=5):
        candidate += timedelta(days=1)
    return candidate


def publish_time(timing: dict, *, now: datetime, source_at: datetime, best_hour: int) -> datetime:
    """immediate: now. next_day_evening: the evening after the footage was
    sent (or the next evening if that has passed). best_hour: the
    workspace's best hour (learned from metrics), next time it comes."""
    mode = timing.get("mode", "immediate")
    if mode == "next_day_evening":
        hour = int(timing.get("hour", 18))
        candidate = _at(source_at.astimezone(TEHRAN) + timedelta(days=1), hour)
        return candidate if candidate > now else next_at_hour(now, hour)
    if mode == "best_hour":
        return next_at_hour(now, int(timing.get("hour", best_hour)))
    return now


def quick_choices(now: datetime, best_hour: int) -> list[datetime]:
    """The reschedule buttons: now, tonight at the best hour, tomorrow evening."""
    tonight = next_at_hour(now, best_hour)
    tomorrow = _at(now.astimezone(TEHRAN) + timedelta(days=1), 18)
    return [now, tonight, tomorrow if tomorrow != tonight else tomorrow + timedelta(days=1)]
