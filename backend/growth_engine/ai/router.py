"""Model routing, caching, per-workspace caps and JSON replies.

Every AI call in the service goes through `ask_text` / `ask_json` with a
task name. The task picks the tier (light work to the cheap model, captions
to the strong one, screenshots to the vision model); the tier's model comes
from MODEL_LIGHT / MODEL_STRONG / MODEL_VISION, all served by OpenCode.
"""

import hashlib
import json
import re
from datetime import timedelta
from typing import Protocol

from .. import db
from ..config import get_settings
from ..errors import AppError
from ..models import AICache
from ..services import usage
from .opencode import ImagePart, OpenCodeClient, Prompt

TASK_TIER = {
    "caption": "strong",
    "caption_edit": "strong",
    "brand_kit": "strong",
    "audit": "strong",
    "competitor_analysis": "strong",
    "competitor_insight": "strong",
    "weekly_report": "strong",
    "hashtags": "light",
    "classify_feedback": "light",
    "suggest_reply": "light",
    "guess_tag": "light",
    "hook_type": "light",
    "competitor_post_tags": "light",
    "slot_ideas": "light",
    "read_screenshot": "vision",
    "pick_scene": "vision",
}

CACHE_TTL = timedelta(days=7)


class Completer(Protocol):
    async def complete(self, model: str, prompt: Prompt) -> str: ...


_client: Completer | None = None


def set_client(client: Completer | None) -> None:
    """Swap the OpenCode client (tests use a scripted fake)."""
    global _client
    _client = client


def _get_client() -> Completer:
    global _client
    if _client is None:
        _client = OpenCodeClient()
    return _client


def model_for(task: str) -> str:
    s = get_settings()
    tier = TASK_TIER.get(task)
    if tier is None:
        raise ValueError(f"Unknown AI task: {task}")
    model = {"light": s.model_light, "strong": s.model_strong, "vision": s.model_vision}[tier]
    # A missing light/vision model falls back to the strong one.
    return model or s.model_strong


def _cache_key(model: str, prompt: Prompt) -> str:
    h = hashlib.sha256()
    for piece in (model, prompt.system, prompt.user):
        h.update(piece.encode())
        h.update(b"\0")
    for image in prompt.images:
        h.update(hashlib.sha256(image.data).digest())
    return h.hexdigest()


def _cached(key: str) -> str | None:
    with db.session_scope() as s:
        row = s.get(AICache, key)
        if row and row.created_at > db.utcnow() - CACHE_TTL:
            return row.response
    return None


def _store(key: str, response: str) -> None:
    with db.session_scope() as s:
        row = s.get(AICache, key)
        if row:
            row.response, row.created_at = response, db.utcnow()
        else:
            s.add(AICache(key=key, response=response, created_at=db.utcnow()))


async def ask_text(task: str, system: str, user: str, *, workspace_id: str | None = None,
                   images: list[ImagePart] | None = None, cache: bool = False) -> str:
    model = model_for(task)
    prompt = Prompt(system=system, user=user, images=images or [])
    key = _cache_key(model, prompt)
    if cache and (hit := _cached(key)) is not None:
        return hit
    if workspace_id:
        usage.consume(workspace_id, "ai_calls")
    text = await _get_client().complete(model, prompt)
    if cache:
        _store(key, text)
    return text


def extract_json(text: str) -> dict | list:
    """Parse a JSON reply, tolerating markdown fences and preamble text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No JSON found in the model reply")


async def ask_json(task: str, system: str, user: str, **kwargs) -> dict | list:
    """Like ask_text, but the reply must be JSON. One retry with a stricter
    instruction when the model answers in prose."""
    system = f"{system}\n\nReply with ONLY a JSON document. No prose, no markdown fences."
    text = await ask_text(task, system, user, **kwargs)
    try:
        return extract_json(text)
    except ValueError:
        retry = f"{user}\n\n---\n\nYour previous reply was not JSON. Reply with ONLY the JSON document."
        kwargs.pop("cache", None)
        text = await ask_text(task, system, retry, **kwargs)
        try:
            return extract_json(text)
        except ValueError as exc:
            raise AppError("ai_bad_reply", "The AI did not return a usable answer", 502) from exc
