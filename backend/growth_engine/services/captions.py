"""Channel-specific text from one post, under the brand's tone lock.

Instagram: link only in the bio (a link in a caption does not work).
Messengers: shorter text with the direct tracked link.
Aparat: SEO title, description with the link, tags.
Story: one line for the link sticker. Site: title and body.
"""

import re

from ..ai import router
from ..models import BrandKit, Post, TagRecipe, Workspace

MESSENGERS = ("bale", "telegram", "eitaa", "rubika")
HASHTAG_TOKEN = re.compile(r"#([\w\u200c]+)")

SYSTEM = """You write social media copy in Persian for an Iranian small business.
Hard rules:
- Follow the tone lock exactly: sound like the adjectives, never like the anti-adjectives.
- Use only facts from the transcript, the admin's note and the offer. Never invent names, numbers, prices or dates.
- Spell every glossary term exactly as given. Never use a banned word or topic.
- Follow the recipe's caption style and end with its call to action.
- Instagram captions never contain a URL; they say the link is in the bio.
JSON shape:
{"instagram": {"caption": "..."},
 "messenger": {"text": "... (short, ends with {link})"},
 "aparat": {"title": "SEO title, max 100 chars", "description": "... includes {link}", "tags": ["3 to 5 tags"]},
 "story": {"text": "one short line for the link sticker"},
 "site": {"title": "...", "body": "a few paragraphs"},
 "cover_title": "2 to 4 words for the cover",
 "overlay": "the on-screen text the recipe asks for, or empty"}
Write {link} literally where the link goes; the system puts the tracked link there."""

HASHTAG_SYSTEM = """Suggest Persian Instagram hashtags for this post: specific to the place and
topic, no generic spam tags. JSON: {"hashtags": ["#...", ...]} with 5 to 8 items."""

EDIT_SYSTEM = """You edit one Persian social media caption by the admin's instruction.
Change only what the instruction asks; keep the tone lock, the glossary spellings, the
call to action and any {link} placeholder. JSON: {"text": "..."}"""


def _context(ws: Workspace, kit: BrandKit, recipe: TagRecipe | None, post: Post, transcript_text: str,
             offer_line: str) -> str:
    tone = kit.tone or {}
    lines = [
        f"Business: {ws.name}",
        f"Tone lock: be {', '.join(tone.get('adjectives', []))}; never {', '.join(tone.get('anti', []))}.",
        f"Write like: {' | '.join(tone.get('do', []))}",
        f"Never like: {' | '.join(tone.get('dont', []))}",
        f"Glossary: {', '.join(kit.glossary or [])}",
        f"Banned: {', '.join(kit.banned or [])}",
    ]
    if recipe:
        lines += [f"Recipe (an internal name; never write it in the copy or the hashtags): {recipe.tag}",
                  f"Goal: {recipe.goal}", f"Caption style: {recipe.caption_style}",
                  f"Call to action: {recipe.cta}", f"On-screen overlay kind: {recipe.video_spec.get('overlay', 'none')}"]
    lines += [f"Offer: {offer_line or 'none'}", f"Admin's note: {post.raw_note or '-'}",
              f"Transcript: {transcript_text or '- (no speech)'}"]
    return "\n".join(lines)


async def write_all(ws: Workspace, kit: BrandKit, recipe: TagRecipe | None, post: Post, transcript_text: str,
                    offer_line: str) -> dict:
    context = _context(ws, kit, recipe, post, transcript_text, offer_line)
    copy = await router.ask_json("caption", SYSTEM, context, workspace_id=ws.id)
    if not isinstance(copy, dict):
        copy = {}
    tags = await router.ask_json("hashtags", HASHTAG_SYSTEM, context, workspace_id=ws.id, cache=True)
    copy["hashtags"] = [h for h in (tags.get("hashtags", []) if isinstance(tags, dict) else [])
                        if isinstance(h, str) and h.startswith("#")][:8]
    internal = {x for x in (recipe.tag if recipe else None, post.tag) if x}
    return strip_internal_tags(copy, internal)


def strip_internal_tags(value, internal: set[str]):
    """The tag that routed the video (#up) is ours, not the audience's: drop it from every hashtag list
    and every text the AI wrote."""
    if not internal:
        return value
    names = {t.lstrip("#").casefold() for t in internal}
    if isinstance(value, dict):
        return {k: strip_internal_tags(v, internal) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_internal_tags(v, internal) for v in value
                if not (isinstance(v, str) and v.strip().lstrip("#").casefold() in names)]
    if isinstance(value, str):
        out = HASHTAG_TOKEN.sub(lambda m: "" if m.group(1).casefold() in names else m.group(0), value)
        return re.sub(r"[ \t]{2,}", " ", out).strip() if out != value else value
    return value


async def edit(ws: Workspace, kit: BrandKit, caption: str, instruction: str) -> str:
    tone = kit.tone or {}
    user = (f"Tone lock: {', '.join(tone.get('adjectives', []))}\nGlossary: {', '.join(kit.glossary or [])}\n"
            f"Caption:\n{caption}\n\nInstruction: {instruction}")
    reply = await router.ask_json("caption_edit", EDIT_SYSTEM, user, workspace_id=ws.id)
    text = reply.get("text") if isinstance(reply, dict) else None
    return text if isinstance(text, str) and text.strip() else caption


def fill_link(text: str, url: str) -> str:
    return text.replace("{link}", url) if "{link}" in text else f"{text}\n{url}"


def _bare(tags) -> list[str]:
    """Tags are stored without '#'; the '#' is added where a tag is shown or published."""
    return [t.strip().lstrip("#") for t in tags or [] if isinstance(t, str) and t.strip().lstrip("#")]


def compose(copy: dict, channel_type: str, kind: str, url: str) -> dict:
    """The final title/caption/tags for one variant. Hashtags stay out of the caption: `published_text`
    adds them when the post goes out, so an edited tag list is what gets published."""
    hashtags = _bare(copy.get("hashtags"))
    if channel_type == "instagram":
        if kind == "story":  # a story's text is its link sticker: no hashtags
            return {"title": "", "caption": (copy.get("story") or {}).get("text", ""), "tags": []}
        caption = (copy.get("instagram") or {}).get("caption", "").replace("{link}", "").strip()
        return {"title": "", "caption": caption, "tags": hashtags}
    if channel_type == "aparat":
        a = copy.get("aparat") or {}
        return {"title": a.get("title", "")[:100], "caption": fill_link(a.get("description", ""), url),
                "tags": _bare(a.get("tags"))[:5]}
    if channel_type == "site":
        site = copy.get("site") or {}
        return {"title": site.get("title", ""), "caption": site.get("body", ""), "tags": hashtags}
    return {"title": "", "caption": fill_link((copy.get("messenger") or {}).get("text", ""), url), "tags": hashtags}


def published_text(caption: str, tags: list[str] | None, channel_type: str, kind: str) -> str:
    """The caption as it goes out: Instagram (not stories) and the messengers carry the hashtags at the end.
    Aparat sends its tags as a field; the site page keeps them out of the body."""
    if channel_type not in ("instagram", *MESSENGERS) or kind == "story":
        return caption
    present = {m.group(1).casefold() for m in HASHTAG_TOKEN.finditer(caption)}
    extra = [f"#{t}" for t in _bare(tags) if t.casefold() not in present]
    return f"{caption}\n\n{' '.join(extra)}".strip() if extra else caption
