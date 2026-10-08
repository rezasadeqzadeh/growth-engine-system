"""Bot API client shared by Telegram and Bale (Bale's bot API follows Telegram's).

Limits that shape the code:
  Telegram: bots download at most 20 MB (larger files need a local Bot API
            server, set TELEGRAM_API_BASE to it); captions at most 1024 chars.
  Bale:     bots download at most 20 MB and upload at most 50 MB; captions
            at most 4096 chars; no channel_post updates, so admins send raw
            media in a private group with the bot or to the bot itself.
"""

import json
import os
from pathlib import Path

import httpx

from ..redact import redact

BASES = {
    # An empty TELEGRAM_API_BASE (as in .env.example) means the public server.
    "telegram": os.environ.get("TELEGRAM_API_BASE") or "https://api.telegram.org",
    "bale": "https://tapi.bale.ai",
}
CAPTION_LIMIT = {"telegram": 1024, "bale": 4096}
DOWNLOAD_LIMIT_MB = {"telegram": 20, "bale": 20}
UPLOAD_LIMIT_MB = {"telegram": 50, "bale": 50}


class BotApiError(RuntimeError):
    def __init__(self, message: str, description: str = "") -> None:
        super().__init__(message)
        self.description = description


class BotApi:
    def __init__(self, platform: str, token: str, timeout: float = 120) -> None:
        if platform not in BASES:
            raise ValueError(f"Unknown bot platform: {platform}")
        self.platform = platform
        self._token = token
        self.timeout = timeout

    @property
    def _base(self) -> str:
        return f"{BASES[self.platform]}/bot{self._token}"

    async def call(self, method: str, data: dict | None = None, files: dict | None = None) -> dict:
        payload = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                   for k, v in (data or {}).items() if v is not None}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if files:
                    resp = await client.post(f"{self._base}/{method}", data=payload, files=files)
                else:
                    resp = await client.post(f"{self._base}/{method}", data=payload)
        except httpx.HTTPError as exc:
            raise BotApiError(redact(f"{self.platform} {method} failed: {exc}", [self._token])) from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise BotApiError(f"{self.platform} {method}: HTTP {resp.status_code}") from exc
        if not body.get("ok"):
            desc = redact(body.get("description", ""), [self._token])
            raise BotApiError(f"{self.platform} {method}: {desc}", desc)
        return body.get("result") or {}

    async def get_me(self) -> dict:
        return await self.call("getMe")

    async def set_webhook(self, url: str, secret: str) -> dict:
        data = {"url": url}
        if self.platform == "telegram":
            data["secret_token"] = secret
            data["allowed_updates"] = ["message", "channel_post", "callback_query", "message_reaction_count"]
        return await self.call("setWebhook", data)

    async def send_message(self, chat_id: str, text: str, keyboard: list | None = None,
                           reply_to: str | None = None) -> dict:
        return await self.call("sendMessage", {
            "chat_id": chat_id, "text": text, "reply_to_message_id": reply_to,
            "reply_markup": {"inline_keyboard": keyboard} if keyboard else None})

    async def edit_message_text(self, chat_id: str, message_id: str, text: str, keyboard: list | None = None) -> dict:
        return await self.call("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "reply_markup": {"inline_keyboard": keyboard} if keyboard is not None else None})

    async def edit_reply_markup(self, chat_id: str, message_id: str, keyboard: list | None = None) -> dict:
        return await self.call("editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": keyboard or []}})

    async def send_file(self, method: str, field: str, chat_id: str, path: Path, caption: str = "",
                        keyboard: list | None = None, extra: dict | None = None) -> dict:
        with path.open("rb") as fh:
            return await self.call(method, {
                "chat_id": chat_id, "caption": caption[: CAPTION_LIMIT[self.platform]] or None,
                "reply_markup": {"inline_keyboard": keyboard} if keyboard else None, **(extra or {})},
                files={field: (path.name, fh)})

    async def send_video(self, chat_id: str, path: Path, caption: str = "", keyboard: list | None = None,
                         cover: Path | None = None) -> dict:
        if cover is None or self.platform != "telegram":
            return await self.send_file("sendVideo", "video", chat_id, path, caption, keyboard,
                                        {"supports_streaming": "true"})
        with path.open("rb") as video, cover.open("rb") as thumb:
            return await self.call("sendVideo", {
                "chat_id": chat_id, "caption": caption[:1024] or None, "supports_streaming": "true",
                "reply_markup": {"inline_keyboard": keyboard} if keyboard else None, "thumbnail": "attach://thumb"},
                files={"video": (path.name, video), "thumb": (cover.name, thumb)})

    async def send_photo(self, chat_id: str, path: Path, caption: str = "", keyboard: list | None = None) -> dict:
        return await self.send_file("sendPhoto", "photo", chat_id, path, caption, keyboard)

    async def send_document(self, chat_id: str, path: Path, caption: str = "") -> dict:
        return await self.send_file("sendDocument", "document", chat_id, path, caption)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text or None})

    async def download(self, file_id: str, dst: Path) -> Path:
        info = await self.call("getFile", {"file_id": file_id})
        file_path = info.get("file_path")
        if not file_path:
            raise BotApiError(f"{self.platform} getFile returned no path")
        url = f"{BASES[self.platform]}/file/bot{self._token}/{file_path}"
        try:
            async with httpx.AsyncClient(timeout=600) as client, client.stream("GET", url) as resp:
                resp.raise_for_status()
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open("wb") as fh:
                    async for chunk in resp.aiter_bytes():
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            raise BotApiError(redact(f"{self.platform} download failed: {exc}", [self._token])) from exc
        return dst
