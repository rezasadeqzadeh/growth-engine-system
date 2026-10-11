"""The tag-driven video pipeline (runs in the media worker).

download -> transcribe -> glossary fix -> (guess tag) -> copy -> smart cut,
subtitles, cover, logo -> variants with tracked links -> QC ->
pending, and the approval card goes to the bot.
"""

import copy
import hashlib
import logging
import shutil
import tempfile
import time
from pathlib import Path

import jdatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import db
from ..ai import router
from ..bots.api import BotApi
from ..config import get_settings
from ..i18n import fa_digits, t
from ..jobs import queue
from ..media import ffmpeg, glossary, render, transcribe
from ..models import (
    BrandKit, Channel, MediaAsset, Offer, Post, PostVariant, Registration, TagRecipe, TrackedLink, Workspace,
)
from . import brand_kit, captions, links, posts, quality, storage, usage
from .timing import TEHRAN

logger = logging.getLogger(__name__)


class _Steps:
    """One log line per pipeline step with its duration: `[video <post>] 3/9 transcribe (12.4s)`."""

    def __init__(self, post_id: str) -> None:
        self.post_id, self.n, self.started, self.at = post_id[:8], 0, time.monotonic(), time.monotonic()

    def done(self, name: str, detail: str = "") -> None:
        self.n += 1
        now = time.monotonic()
        logger.info("[video %s] %d. %s (%.1fs)%s", self.post_id, self.n, name, now - self.at,
                    f": {detail}" if detail else "")
        self.at = now

GUESS_SYSTEM = """Pick the tag that fits this raw video best, from the list only.
JSON: {"tag": "one of the tags", "confidence": 0..1}"""

VARIANT_KINDS = {"instagram": [("reel", "short"), ("story", "story")], "aparat": [("full", "full")]}


def plan_variants(recipe_channels: list[str], channels: list[Channel], rendered: set[str]) -> list[tuple[Channel, str, str]]:
    """(channel, variant kind, rendered file) for every connected channel the recipe names."""
    out = []
    for channel in channels:
        if not channel.enabled or channel.type not in recipe_channels:
            continue
        for kind, file in VARIANT_KINDS.get(channel.type, [("message", "short")]):
            if file not in rendered:
                file = "short"
            out.append((channel, kind, file))
    return out


def offer_line(s: Session, workspace_id: str) -> tuple[str, str | None]:
    """A one-line summary of the next open offer, and its on-screen overlay text."""
    offer = s.scalar(select(Offer).where(Offer.workspace_id == workspace_id, Offer.active,
                                         Offer.starts_at > db.utcnow()).order_by(Offer.starts_at))
    if offer is None:
        return "", None
    taken = s.scalar(select(func.count()).select_from(Registration).where(
        Registration.offer_id == offer.id, Registration.status == "paid")) or 0
    day = jdatetime.datetime.fromgregorian(datetime=offer.starts_at.astimezone(TEHRAN), locale="fa_IR").strftime("%d %B")
    price = fa_digits(f"{offer.price_toman:,}")
    left = f", {offer.capacity - taken} seats left" if offer.capacity else ""
    line = f"{offer.title} on {day}, {offer.price_toman} toman{left}"
    # "|" not a middle dot: next to Persian digits a middle dot reads as the digit zero.
    return line, f"{offer.title} | {fa_digits(day)} | {price} {t('offer.toman')}"


def _music_track(post_id: str) -> Path | None:
    tracks = sorted((get_settings().storage_dir / "music").glob("*.mp3"))
    if not tracks:
        return None
    return tracks[int(hashlib.sha256(post_id.encode()).hexdigest(), 16) % len(tracks)]


async def _download(s: Session, asset: MediaAsset, download: dict | None) -> Path:
    if asset.file_key:
        return storage.path_of(asset.file_key)
    if not download:
        raise ValueError("The asset has no file and nothing to download")
    channel = s.get(Channel, download["channel_id"])
    assert channel is not None
    key = storage.new_key(asset.workspace_id, "raw", ".mp4")
    logger.info("[video] downloading the raw video from %s", channel.type)
    await BotApi(channel.type, channel.credentials["bot_token"]).download(download["file_id"], storage.path_of(key))
    logger.info("[video] downloaded %.1f MB", storage.path_of(key).stat().st_size / 1e6)
    asset.file_key = key
    s.commit()
    return storage.path_of(key)


async def _guess_tag(ws: Workspace, recipes: list[TagRecipe], note: str, text: str) -> str | None:
    listing = "\n".join(f"#{r.tag}: goal {r.goal}; {r.caption_style}" for r in recipes)
    reply = await router.ask_json("guess_tag", GUESS_SYSTEM,
                                  f"Tags:\n{listing}\n\nAdmin's note: {note or '-'}\nTranscript: {text or '-'}",
                                  workspace_id=ws.id)
    tag = reply.get("tag", "").lstrip("#") if isinstance(reply, dict) else ""
    return tag if any(r.tag == tag for r in recipes) else None


def _look(kit: BrandKit) -> render.BrandLook:
    colors = kit.colors or brand_kit.DEFAULT_COLORS
    fonts = kit.fonts or brand_kit.DEFAULT_FONTS
    logo = storage.path_of(kit.logo_key) if kit.logo_key else None
    return render.BrandLook(font=fonts.get("body", "Vazirmatn"), text_color=colors.get("text", "#FFFFFF"),
                            box_color=colors["primary"][1], highlight_color=colors["accent"][0],
                            logo=logo if logo and logo.exists() else None,
                            fonts_dir=get_settings().brand_fonts_dir.resolve())


async def process_video(payload: dict) -> None:
    post_id = payload["post_id"]
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        if post is None or post.status not in ("processing",):
            logger.info("[video %s] skipped: post is %s", post_id[:8], post.status if post else "gone")
            return
        ws = s.get(Workspace, post.workspace_id)
        asset = s.get(MediaAsset, post.asset_id)
        assert ws is not None and asset is not None
        kit = brand_kit.current(s, ws.id)
        rerender = bool(payload.get("rerender"))
        steps = _Steps(post.id)
        logger.info("[video %s] start: tag=%s rerender=%s", post.id[:8], post.tag or "-", rerender)
        src = await _download(s, asset, payload.get("download"))
        probe = ffmpeg.probe(src)
        if not rerender and asset.duration_s is None:
            # Counted once per video: a retried job finds the duration already saved.
            usage.consume(ws.id, "videos")
        asset.duration_s, asset.width, asset.height = probe.duration, probe.width, probe.height
        steps.done("download + probe", f"{probe.duration:.1f}s {probe.width}x{probe.height} audio={probe.has_audio}")
        # Commit before every long step and AI call: the AI router writes usage in
        # its own session, and no transaction should stay open across minutes of FFmpeg.
        s.commit()

        work = Path(tempfile.mkdtemp(prefix="ge-"))
        try:
            if not probe.has_audio:
                logger.warning("[video %s] the video has no audio: no transcript, no subtitles", post.id[:8])
            if asset.transcript is None and probe.has_audio:
                logger.info("[video %s] transcribing with Whisper (%s on %s); the first run downloads the model",
                            post.id[:8], get_settings().whisper_model, get_settings().whisper_device)
                audio = work / "audio.wav"
                ffmpeg.extract_audio(src, audio)
                asset.transcript = transcribe.transcribe(audio, kit.glossary)
            if asset.transcript is not None:
                replacements = payload.get("replacements") or {}
                # A deep copy: JSON edited in place looks unchanged and is never saved.
                asset.transcript = glossary.correct_transcript(copy.deepcopy(asset.transcript), kit.glossary,
                                                               replacements)
                if replacements:
                    # A fix the admin typed once is remembered for every later video.
                    terms = [t for t in replacements.values() if t not in (kit.glossary or [])]
                    if terms:
                        kit = brand_kit.new_version(s, ws.id, {"glossary": [*(kit.glossary or []), *terms]})
            text = transcribe.plain_text(asset.transcript)
            s.commit()
            steps.done("transcribe (Whisper)", f"{len(text)} characters")

            recipes = list(s.scalars(select(TagRecipe).where(TagRecipe.workspace_id == ws.id)))
            if post.recipe_id is None and recipes:
                guessed = await _guess_tag(ws, recipes, post.raw_note, text)
                if guessed:
                    post.tag, post.tag_guessed = guessed, True
                    post.recipe_id = next(r.id for r in recipes if r.tag == guessed)
            recipe = s.get(TagRecipe, post.recipe_id) if post.recipe_id else None
            steps.done("recipe", f"tag={post.tag or '-'} guessed={post.tag_guessed} channels={recipe.channels if recipe else 'all'}")
            spec = (recipe.video_spec if recipe else None) or {"min_s": 15, "max_s": 60, "aspects": ["9:16"],
                                                                "subtitle_mode": "sentence", "overlay": "none"}

            s.commit()
            line, price_overlay = offer_line(s, ws.id)
            texts = await captions.write_all(ws, kit, recipe, post, text, line)
            steps.done("captions (AI)", f"title={post.title or '-'}")
            overlay = price_overlay if spec.get("overlay") == "date_price" else (texts.get("overlay") or None)
            if spec.get("overlay") == "none":
                overlay = None
            post.title = (texts.get("site") or {}).get("title") or texts.get("cover_title") or post.title

            silences = ffmpeg.detect_silences(src, probe.duration) if probe.has_audio else []
            specs = render.plan_renders(probe.duration, silences, asset.transcript, spec)
            music = _music_track(post.id) if spec.get("music") else None
            logger.info("[video %s] rendering %d version(s) with ffmpeg", post.id[:8], len(specs))
            out = render.render(src, work, probe, specs, _look(kit), overlay,
                                texts.get("cover_title") or post.title, music)
            steps.done("render (ffmpeg)", ", ".join(f"{k}={v:.0f}s" for k, v in out.durations.items()))
            post.output_duration_s = out.durations.get("short")

            keys = {name: storage.save_bytes(storage.new_key(ws.id, "out", path.suffix), path.read_bytes())
                    for name, path in out.files.items() if name != "frame"}
            channels = list(s.scalars(select(Channel).where(Channel.workspace_id == ws.id)))
            # A re-render (subtitles edited) keeps what people already wrote and the links they may have shared.
            kept: dict[tuple[str, str], PostVariant] = {}
            for old in s.scalars(select(PostVariant).where(PostVariant.post_id == post.id)):
                if rerender:
                    kept[(old.channel_id, old.kind)] = old
                s.delete(old)
            s.flush()
            destination = links.destination_for(s, post)
            link_base = links.base_url(s, ws.id)
            checked = []
            for channel, kind, file in plan_variants(recipe.channels if recipe else [c.type for c in channels],
                                                     channels, set(keys)):
                old = kept.get((channel.id, kind))
                link = s.get(TrackedLink, old.tracked_link_id) if old and old.tracked_link_id else None
                if link is None:
                    link = links.create(s, ws.id, destination, channel_type=channel.type, post_id=post.id,
                                        tag=post.tag, prefix_key="story" if kind == "story" else channel.type)
                url = links.short_url(link, link_base)
                text_parts = ({"title": old.title, "caption": old.caption, "tags": list(old.tags or [])} if old
                              else captions.compose(texts, channel.type, kind, url))
                s.add(PostVariant(post_id=post.id, channel_id=channel.id, kind=kind, video_key=keys[file],
                                  cover_key=keys.get("cover"), srt_key=keys.get("srt") if kind == "full" else None,
                                  tracked_link_id=link.id, **text_parts))
                checked.append({"channel_type": channel.type, "kind": kind, "caption": text_parts["caption"],
                                "has_link": url in text_parts["caption"]})
            post.qc = quality.check(checked, glossary=kit.glossary or [], banned=kit.banned or [],
                                    cta=recipe.cta if recipe else "", needs_link=bool(recipe and recipe.goal == "convert"),
                                    faces=None, uses_music=bool(spec.get("music")),
                                    music_licensed=music is not None)
            post.status, post.error = "pending", None
            steps.done("variants + quality check", f"{len(checked)} variants: "
                       + ", ".join(f"{c['channel_type']}/{c['kind']}" for c in checked) + f"; qc={post.qc}")
            if recipe and recipe.low_risk and (ws.settings or {}).get("auto_approve_consent"):
                post.auto_approve_at = db.utcnow() + posts.AUTO_APPROVE_AFTER
            queue.enqueue(s, "send_approval_card", {"post_id": post.id})
            logger.info("[video %s] ready in %.1fs; approval card queued", post.id[:8], time.monotonic() - steps.started)
        finally:
            shutil.rmtree(work, ignore_errors=True)
