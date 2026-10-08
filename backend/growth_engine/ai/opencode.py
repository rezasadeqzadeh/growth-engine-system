"""OpenCode server client: the only way this service talks to an LLM.

Same protocol as app-builder's `ai_service._call_opencode_direct`:
create a session, POST /session/{id}/prompt_async (answers 204 at once, so
no proxy timeout on long turns), then poll GET /session/{id}/message until
the newest assistant message has text.
"""

import asyncio
import base64
import logging
from dataclasses import dataclass, field

import httpx

from ..config import get_settings
from ..redact import redact

logger = logging.getLogger(__name__)

_POLL_START = 0.4
_POLL_MAX = 2.0
_POLL_GROWTH = 1.35
_TRANSIENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError)


class OpenCodeError(RuntimeError):
    pass


class EmptyModelResponseError(OpenCodeError):
    """The turn finished without text; waiting longer cannot help."""


@dataclass
class ImagePart:
    data: bytes
    mime: str = "image/png"
    filename: str = "image.png"


@dataclass
class Prompt:
    system: str
    user: str
    images: list[ImagePart] = field(default_factory=list)


def _model_obj(model: str) -> dict:
    if "/" in model:
        provider, model_id = model.split("/", 1)
        return {"providerID": provider, "modelID": model_id}
    return {"providerID": "opencode", "modelID": model}


def _latest_assistant(messages: list) -> dict | None:
    # Never fall back to an older assistant message: on a slow turn that
    # would return a previous answer as this one.
    for msg in reversed(messages):
        if isinstance(msg, dict) and (msg.get("info") or {}).get("role") == "assistant":
            return msg
    return None


def _turn_finished(msg: dict) -> bool:
    info = msg.get("info") or {}
    return bool((info.get("time") or {}).get("completed") or info.get("finish"))


def _has_tool_calls(msg: dict) -> bool:
    return any(isinstance(p, dict) and p.get("type") == "tool" for p in msg.get("parts", []))


def _text_of(msg: dict) -> str:
    return "".join(p.get("text", "") for p in msg.get("parts", []) if isinstance(p, dict) and p.get("type") == "text")


class OpenCodeClient:
    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None,
                 poll_budget_s: int | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url if base_url is not None else s.opencode_server_url).rstrip("/")
        user = username if username is not None else s.opencode_server_username
        pwd = password if password is not None else s.opencode_server_password
        self.auth = (user, pwd) if user else None
        self.poll_budget_s = poll_budget_s if poll_budget_s is not None else s.ai_poll_budget_s
        self._secrets = [pwd] if pwd else []

    async def complete(self, model: str, prompt: Prompt) -> str:
        if not self.base_url:
            raise OpenCodeError("OPENCODE_SERVER_URL is not set")
        if not model:
            raise OpenCodeError("No model configured for this task")
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                session_id = await self._create_session()
                await self._send(session_id, model, prompt)
                return await self._wait_for_text(session_id)
            except EmptyModelResponseError:
                raise
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500:
                    raise OpenCodeError(redact(f"OpenCode HTTP {exc.response.status_code}", self._secrets)) from exc
            except _TRANSIENT as exc:
                last_exc = exc
            logger.warning("[OpenCode] attempt %d failed: %s", attempt + 1, redact(last_exc, self._secrets))
            await asyncio.sleep(2**attempt)
        raise OpenCodeError(redact(f"OpenCode failed after retries: {last_exc}", self._secrets))

    async def _create_session(self) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/session", auth=self.auth, json={"title": "growth-engine"})
            resp.raise_for_status()
            session_id = resp.json().get("id", "")
        if not session_id:
            raise OpenCodeError("OpenCode returned a session without an id")
        return session_id

    async def _send(self, session_id: str, model: str, prompt: Prompt) -> None:
        parts: list[dict] = [{"type": "text", "text": f"System: {prompt.system}\n\n---\n\n{prompt.user}"}]
        for image in prompt.images:
            encoded = base64.b64encode(image.data).decode()
            parts.append({"type": "file", "mime": image.mime, "filename": image.filename,
                          "url": f"data:{image.mime};base64,{encoded}"})
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/session/{session_id}/prompt_async", auth=self.auth,
                                     json={"parts": parts, "model": _model_obj(model)})
            if resp.status_code != 204:
                resp.raise_for_status()

    async def _wait_for_text(self, session_id: str) -> str:
        interval, elapsed = _POLL_START, 0.0
        while elapsed < self.poll_budget_s:
            msgs = await self._messages(session_id)
            latest = _latest_assistant(msgs)
            if latest is not None:
                text = _text_of(latest)
                if text.strip():
                    return text
                if _turn_finished(latest) and not _has_tool_calls(latest):
                    raise EmptyModelResponseError("The model finished its turn without returning any text")
            await asyncio.sleep(interval)
            elapsed += interval
            interval = min(interval * _POLL_GROWTH, _POLL_MAX)
        raise OpenCodeError("OpenCode did not answer within the time budget")

    async def _messages(self, session_id: str) -> list:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(f"{self.base_url}/session/{session_id}/message", auth=self.auth)
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        body = resp.json()
        msgs = body.get("data", body) if isinstance(body, dict) else body
        return msgs if isinstance(msgs, list) else []
