"""Eitaa through the eitaayar.ir API (token from eitaayar.ir, bot admin of the channel).

POST https://eitaayar.ir/api/<token>/sendFile  (chat_id, caption, file)
POST https://eitaayar.ir/api/<token>/sendMessage (chat_id, text)
POST https://eitaayar.ir/api/<token>/getMe
"""

import httpx

from ..models import Channel
from ..redact import redact
from .base import Capabilities, Comment, Metrics, NotSupported, PublicationResult, PublishError, PublishItem, check_size

BASE = "https://eitaayar.ir/api"


class EitaaAdapter:
    type = "eitaa"

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="limited", comments="none", dm=False,
                            max_video_mb=50, aspects=("9:16",), kinds=("message",))

    def _token(self, channel: Channel) -> str:
        token = (channel.credentials or {}).get("token")
        if not token:
            raise PublishError("The channel has no eitaayar token", retryable=False)
        return token

    async def _call(self, channel: Channel, method: str, data: dict, files: dict | None = None) -> dict:
        token = self._token(channel)
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{BASE}/{token}/{method}", data=data, files=files)
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PublishError(redact(f"eitaa {method} failed: {exc}", [token])) from exc
        if not body.get("ok"):
            raise PublishError(redact(f"eitaa {method}: {body.get('description', body)}", [token]),
                               retryable=resp.status_code >= 500)
        return body.get("result") or {}

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        check_size(item, self.capabilities())
        chat_id = (channel.config or {}).get("chat_id")
        if not chat_id:
            raise PublishError("The channel has no chat id", retryable=False)
        if item.video:
            with item.video.open("rb") as fh:
                result = await self._call(channel, "sendFile", {"chat_id": chat_id, "caption": item.caption},
                                          files={"file": (item.video.name, fh, "video/mp4")})
        else:
            result = await self._call(channel, "sendMessage", {"chat_id": chat_id, "text": item.caption})
        message_id = str(result.get("message_id", ""))
        url = f"https://eitaa.com/{str(chat_id).lstrip('@')}/{message_id}" if message_id else None
        return PublicationResult("published", message_id, url)

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        raise NotSupported("eitaayar does not expose post statistics")

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        raise NotSupported("eitaayar does not expose comments")

    async def health(self, channel: Channel) -> None:
        await self._call(channel, "getMe", {})
