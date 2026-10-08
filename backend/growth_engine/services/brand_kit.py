"""Brand kit: the business's design tokens. Every output of the pipeline
reads the current version (font, colours, tone lock, glossary, banned list)."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import router
from ..errors import NotFound
from ..models import BrandKit, Workspace

QUESTIONS = ("one_sentence", "ideal_customer", "three_am_worry", "three_words", "never_list",
             "liked_pages", "assets_note")
EDITABLE = ("colors", "fonts", "tone", "pillars", "glossary", "banned", "templates", "bio", "logo_key")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Font family names as libass sees them; the files sit in BRAND_FONTS_DIR.
DEFAULT_FONTS = {"heading": "Vazirmatn", "body": "Vazirmatn"}
DEFAULT_COLORS = {"primary": ["#8B5E3C", "#1F2A44"], "accent": ["#C9A66B", "#4F7942"], "text": "#FFFFFF"}

SYSTEM = """You are a brand strategist for small Iranian businesses on social media.
From the owner's answers, produce the brand kit. All human-readable values in Persian.
JSON shape:
{"colors": {"primary": ["#hex", "#hex"], "accent": ["#hex", "#hex"], "text": "#hex",
            "names": {"#hex": "Persian colour name"}},
 "tone": {"adjectives": [3 words], "anti": [3 words it must never sound like],
          "do": [2 example sentences in the right voice], "dont": [2 example sentences in the wrong voice]},
 "pillars": [{"key": "latin_snake", "name": "Persian", "goal": "attract|trust|convert"}] (3 to 5),
 "glossary": [proper names that must be spelled exactly: places, people, products],
 "banned": [words or topics never to publish],
 "templates": {"reel_cover": "short Persian title style", "carousel": "...", "story_announce": "...",
               "intro_outro": "..."},
 "bio": {"suggestions": [3 Persian bio texts, outcome-focused, each with a call to action],
         "highlights": [{"name": "Persian", "cover": "one emoji"}]}}
The text colour must contrast with both primary colours enough to read burned-in subtitles."""


def current(s: Session, workspace_id: str) -> BrandKit:
    kit = s.scalar(select(BrandKit).where(BrandKit.workspace_id == workspace_id, BrandKit.is_current)
                   .order_by(BrandKit.version.desc()))
    if kit is None:
        raise NotFound("brand_kit")
    return kit


def _clean_colors(colors: dict) -> dict:
    out = dict(DEFAULT_COLORS)
    for key in ("primary", "accent"):
        values = [c for c in (colors.get(key) or []) if isinstance(c, str) and HEX.match(c)]
        if len(values) >= 2:
            out[key] = values[:2]
    if isinstance(colors.get("text"), str) and HEX.match(colors["text"]):
        out["text"] = colors["text"]
    if isinstance(colors.get("names"), dict):
        out["names"] = colors["names"]
    return out


def new_version(s: Session, workspace_id: str, changes: dict) -> BrandKit:
    """Save a new version with `changes` applied; the old one stays as history."""
    old = current(s, workspace_id)
    data = {field: getattr(old, field) for field in EDITABLE}
    data["answers"] = old.answers
    for field, value in changes.items():
        if field in EDITABLE or field == "answers":
            data[field] = value
    data["colors"] = _clean_colors(data.get("colors") or {})
    data["fonts"] = data.get("fonts") or DEFAULT_FONTS
    old.is_current = False
    kit = BrandKit(workspace_id=workspace_id, version=old.version + 1, is_current=True, **data)
    s.add(kit)
    s.flush()
    return kit


async def generate(s: Session, workspace_id: str, answers: dict) -> BrandKit:
    ws = s.get(Workspace, workspace_id)
    if ws is None:
        raise NotFound("workspace")
    lines = [f"Business: {ws.name} (vertical: {ws.vertical})"]
    lines += [f"{q}: {answers.get(q, '')}" for q in QUESTIONS]
    reply = await router.ask_json("brand_kit", SYSTEM, "\n".join(lines), workspace_id=workspace_id)
    if not isinstance(reply, dict):
        reply = {}
    changes = {k: reply[k] for k in ("colors", "tone", "pillars", "glossary", "banned", "templates", "bio")
               if k in reply}
    changes["pillars"] = [p for p in changes.get("pillars", []) if isinstance(p, dict)
                          and p.get("goal") in ("attract", "trust", "convert")] or current(s, workspace_id).pillars
    changes["answers"] = answers
    return new_version(s, workspace_id, changes)


def to_dict(kit: BrandKit) -> dict:
    return {"version": kit.version, "answers": kit.answers, **{f: getattr(kit, f) for f in EDITABLE}}
