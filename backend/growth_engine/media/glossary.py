"""Correct transcribed proper names with the brand glossary (a misheard
letter in a mountain's or a person's name) and the admin's explicit fixes."""

import difflib
import re

# Arabic yeh/kaf/teh marbuta -> Persian forms; ZWNJ dropped for comparison.
_ARABIC_TO_PERSIAN = str.maketrans({"\u064a": "\u06cc", "\u0649": "\u06cc", "\u0643": "\u06a9", "\u0629": "\u0647", "\u06c0": "\u0647", "\u200c": ""})
_PUNCT = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)
THRESHOLD = 0.75  # one wrong letter in a four-letter name is 0.75


def normalize(word: str) -> str:
    return word.translate(_ARABIC_TO_PERSIAN).strip()


def _match(word: str, glossary: list[str]) -> str | None:
    norm = normalize(word)
    if len(norm) < 3:
        return None
    best, best_ratio = None, THRESHOLD
    for term in glossary:
        if " " in term:
            continue
        ratio = difflib.SequenceMatcher(None, norm, normalize(term)).ratio()
        if ratio >= best_ratio and (best is None or ratio > best_ratio):
            best, best_ratio = term, ratio
    return best


def correct_word(word: str, glossary: list[str]) -> str:
    lead, core, trail = _PUNCT.match(word).groups()  # type: ignore[union-attr]
    match = _match(core, glossary)
    return f"{lead}{match}{trail}" if match else word


def correct_text(text: str, glossary: list[str], replacements: dict[str, str] | None = None) -> str:
    """Single words fuzzy-match glossary terms; multi-word terms and the
    admin's explicit fixes ({"wrong": "right"}) replace exactly."""
    for wrong, right in (replacements or {}).items():
        text = text.replace(wrong, right)
    return " ".join(correct_word(w, glossary) for w in text.split(" "))


def correct_transcript(transcript: dict, glossary: list[str], replacements: dict[str, str] | None = None) -> dict:
    for seg in transcript.get("segments", []):
        seg["text"] = correct_text(seg["text"], glossary, replacements)
        for word in seg.get("words") or []:
            word["word"] = correct_text(word["word"], glossary, replacements)
    return transcript
