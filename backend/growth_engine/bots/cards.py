"""The approval card: preview, captions summary, QC and one-tap buttons.

Callback data stays under the 64-byte limit: "<action>:<post_id>[:<n>]".
  a approve · r reject · e edit caption · s fix subtitle · t time menu
  T pick time n · g set tag n (index in the sorted recipe list) · k rate n
"""

from datetime import datetime

import jdatetime

from ..i18n import fa_digits, patterns, t
from ..services.timing import TEHRAN


def jalali(at: datetime) -> str:
    local = jdatetime.datetime.fromgregorian(datetime=at.astimezone(TEHRAN), locale="fa_IR")
    return fa_digits(local.strftime("%A %d %B · %H:%M"))


def card_text(*, title: str, duration_s: float | None, has_subtitles: bool, cover_title: str,
              channels: list[str], publish_at: datetime | None, qc: list[dict], tag: str | None,
              tag_guessed: bool, auto_approve_at: datetime | None) -> str:
    lines = [t("card.ready"), title]
    meta = []
    if duration_s:
        meta.append(t("card.seconds", n=fa_digits(int(round(duration_s)))))
    if has_subtitles:
        meta.append(t("card.subtitles"))
    if cover_title:
        meta.append(t("card.cover", title=cover_title))
    if meta:
        lines.append(" · ".join(meta))
    lines.append(t("card.channels", names=patterns()["list_separator"].join(t(f"channel.{c}") for c in channels)))
    if publish_at:
        lines.append(t("card.publish_at", at=jalali(publish_at)))
    if tag:
        lines.append(t("card.tag_guessed", tag=tag) if tag_guessed else f"#{tag}")
    for item in qc:
        if item["level"] != "ok":
            mark = "⚠" if item["level"] == "warn" else "✗"
            lines.append(f"{mark} {t(item['message'], **item.get('params', {}))}")
    if auto_approve_at:
        lines.append(t("card.auto_approve", at=jalali(auto_approve_at)))
    return "\n".join(lines)


def card_keyboard(post_id: str, can_fix_subtitles: bool, guessed_tags: list[str] | None = None) -> list:
    rows = [
        [{"text": t("btn.approve"), "callback_data": f"a:{post_id}"},
         {"text": t("btn.edit_caption"), "callback_data": f"e:{post_id}"}],
        [{"text": t("btn.change_time"), "callback_data": f"t:{post_id}"},
         {"text": t("btn.reject"), "callback_data": f"r:{post_id}"}],
    ]
    if can_fix_subtitles:
        rows.append([{"text": t("btn.fix_subtitle"), "callback_data": f"s:{post_id}"}])
    if guessed_tags:
        rows.append([{"text": f"#{tag}", "callback_data": f"g:{post_id}:{i}"} for i, tag in enumerate(guessed_tags)][:3])
    return rows


def time_keyboard(post_id: str, choices: list[datetime]) -> list:
    labels = [t("btn.now")] + [jalali(c) for c in choices[1:]]
    return [[{"text": label, "callback_data": f"T:{post_id}:{i}"}] for i, label in enumerate(labels)]


def rating_keyboard(post_id: str) -> list:
    return [[{"text": fa_digits(n), "callback_data": f"k:{post_id}:{n}"} for n in range(1, 6)]]


def parse_callback(data: str) -> tuple[str, str, int | None]:
    parts = data.split(":")
    if len(parts) < 2 or not parts[1]:
        raise ValueError("bad callback data")
    index = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    return parts[0], parts[1], index
