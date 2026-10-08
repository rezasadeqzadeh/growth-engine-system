"""Automatic quality control shown under the approval card.

Each check is {check, level: ok|warn|fail, message, params}; `message` is
an i18n key. A `fail` keeps the approve button but says what is wrong:
the human decides, the system never publishes silently.
"""

import re

from ..media import glossary as gl

CAPTION_LIMITS = {"instagram": 2200, "telegram": 4096, "bale": 4096, "eitaa": 4096, "rubika": 4096,
                  "aparat": 5000, "site": 20000}
_WORD = re.compile(r"[\w\u0600-\u06FF\u200c]+")


def _misspelled(text: str, glossary: list[str]) -> list[str]:
    """Words close to a glossary term but not equal to it (one misheard letter in a name)."""
    terms = {gl.normalize(t) for t in glossary}
    out = []
    for word in _WORD.findall(text):
        if gl.normalize(word) in terms:
            continue
        fixed = gl.correct_word(word, glossary)
        if fixed != word:
            out.append(f"{word}→{fixed}")
    return out


def check(variants: list[dict], *, glossary: list[str], banned: list[str], cta: str, needs_link: bool,
          faces: int | None, uses_music: bool, music_licensed: bool) -> list[dict]:
    """variants: [{channel_type, kind, caption, has_link}]"""
    results: list[dict] = []

    def add(check_name: str, level: str, message: str, **params: object) -> None:
        results.append({"check": check_name, "level": level, "message": message, "params": params})

    long = [v["channel_type"] for v in variants
            if len(v["caption"]) > CAPTION_LIMITS.get(v["channel_type"], 4096)]
    add("length", "fail" if long else "ok", "qc.length_bad" if long else "qc.length_ok", channels=", ".join(long))

    wrong = sorted({w for v in variants for w in _misspelled(v["caption"], glossary)})
    if glossary:
        add("glossary", "warn" if wrong else "ok", "qc.glossary_bad" if wrong else "qc.glossary_ok",
            words=", ".join(wrong))

    found = sorted({b for v in variants for b in banned if b and b in v["caption"]})
    add("banned", "fail" if found else "ok", "qc.banned_bad" if found else "qc.banned_ok", words=", ".join(found))

    if cta:
        missing = [v["channel_type"] for v in variants
                   if v["kind"] != "story" and v["channel_type"] != "site" and cta not in v["caption"]]
        add("cta", "warn" if missing else "ok", "qc.cta_bad" if missing else "qc.cta_ok", channels=", ".join(missing))

    if needs_link:
        no_link = [v["channel_type"] for v in variants
                   if v["channel_type"] not in ("instagram", "site") and not v["has_link"]]
        add("link", "fail" if no_link else "ok", "qc.link_bad" if no_link else "qc.link_ok",
            channels=", ".join(no_link))

    if faces is None:
        add("faces", "warn", "qc.faces_unknown")
    elif faces > 0:
        add("faces", "warn", "qc.faces_consent", count=faces)

    # Music only ever comes from the licensed library (MUSIC_DIR); when the
    # recipe wants music and the library is empty, the video goes without.
    if uses_music and not music_licensed:
        add("music", "warn", "qc.music_missing")
    return results


def has_failure(results: list[dict]) -> bool:
    return any(r["level"] == "fail" for r in results)
