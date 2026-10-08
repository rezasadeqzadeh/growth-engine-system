"""Caption edits by instruction, and voice notes as raw material."""

import tempfile
from pathlib import Path

from sqlalchemy import select

from .. import db
from ..bots.api import BotApi
from ..media import ffmpeg, transcribe
from ..models import Channel, MediaAsset, Post, PostVariant, TagRecipe, TrackedLink, Workspace
from ..jobs import queue
from . import brand_kit, captions, links, quality


def requalify(s, post: Post) -> None:
    """Run quality control again after the captions changed."""
    kit = brand_kit.current(s, post.workspace_id)
    recipe = s.get(TagRecipe, post.recipe_id) if post.recipe_id else None
    asset = s.get(MediaAsset, post.asset_id) if post.asset_id else None
    rows = []
    for variant, channel in s.execute(select(PostVariant, Channel).join(Channel, Channel.id == PostVariant.channel_id)
                                      .where(PostVariant.post_id == post.id)):
        link = s.get(TrackedLink, variant.tracked_link_id) if variant.tracked_link_id else None
        rows.append({"channel_type": channel.type, "kind": variant.kind, "caption": variant.caption,
                     "has_link": bool(link and link.code in variant.caption)})
    # Captions do not change the music; keep its earlier finding ("missing" stays missing).
    previous = {q["check"]: q for q in post.qc or []}
    post.qc = quality.check(rows, glossary=kit.glossary or [], banned=kit.banned or [],
                            cta=recipe.cta if recipe else "", needs_link=bool(recipe and recipe.goal == "convert"),
                            faces=asset.faces_detected if asset else None,
                            uses_music="music" in previous, music_licensed="music" not in previous)


async def edit_captions(payload: dict) -> None:
    with db.session_scope() as s:
        post = s.get(Post, payload["post_id"])
        if post is None or post.status not in ("pending", "scheduled"):
            return
        ws = s.get(Workspace, post.workspace_id)
        kit = brand_kit.current(s, ws.id)
        q = select(PostVariant).where(PostVariant.post_id == post.id)
        if payload.get("channel_id"):
            q = q.where(PostVariant.channel_id == payload["channel_id"])
        for variant in s.scalars(q):
            link = s.get(TrackedLink, variant.tracked_link_id) if variant.tracked_link_id else None
            url = links.short_url(link, links.base_url(s, ws.id)) if link else ""
            # The model edits the text with the {link} placeholder, never the real URL.
            template = variant.caption.replace(url, "{link}") if url else variant.caption
            edited = await captions.edit(ws, kit, template, payload["instruction"])
            variant.caption = edited.replace("{link}", url) if url else edited
            s.commit()  # before the next AI call, which writes usage in its own session
        requalify(s, post)
        if post.status == "pending":
            queue.enqueue(s, "send_approval_card", {"post_id": post.id})


async def transcribe_voice(payload: dict) -> None:
    with db.session_scope() as s:
        post = s.get(Post, payload["post_id"])
        bot = s.get(Channel, payload["channel_id"])
        if post is None or bot is None:
            return
        kit = brand_kit.current(s, post.workspace_id)
        with tempfile.TemporaryDirectory() as tmp:
            voice = await BotApi(bot.type, bot.credentials["bot_token"]).download(payload["file_id"], Path(tmp) / "voice.ogg")
            wav = Path(tmp) / "voice.wav"
            ffmpeg.extract_audio(voice, wav)
            text = transcribe.plain_text(transcribe.transcribe(wav, kit.glossary))
        if not text:
            return
        post.raw_note = f"{post.raw_note}\n{text}".strip()
        if post.status in ("pending", "scheduled"):
            # The captions were already written; work the new facts in.
            queue.enqueue(s, "edit_captions", {"post_id": post.id,
                                               "instruction": f"Work in these facts from the admin's voice note: {text}"})
