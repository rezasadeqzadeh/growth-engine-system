"""Rubika bot API v3 (the bot is an admin of the channel).

A file is sent in three steps: requestSendFile -> upload to the returned
upload_url -> sendFile with the file_id.
"""

import httpx

from ..models import Channel
from ..redact import redact
from .base import Capabilities, Comment, Metrics, NotSupported, PublicationResult, PublishError, PublishItem, check_size

BASE = "https://botapi.rubika.ir/v3"


class RubikaAdapter:
    type = "rubika"

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="limited", comments="none", dm=True,
                            max_video_mb=50, aspects=("9:16",), kinds=("message",))

    def _token(self, channel: Channel) -> str:
        token = (channel.credentials or {}).get("token")
        if not token:
            raise PublishError("The channel has no Rubika bot token", retryable=False)
        return token

    async def _call(self, channel: Channel, method: str, payload: dict) -> dict:
        token = self._token(channel)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{BASE}/{token}/{method}", json=payload)
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PublishError(redact(f"rubika {method} failed: {exc}", [token])) from exc
        if body.get("status") != "OK":
            raise PublishError(redact(f"rubika {method}: {body}", [token]), retryable=resp.status_code >= 500)
        return body.get("data") or {}

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        check_size(item, self.capabilities())
        chat_id = (channel.config or {}).get("chat_id")
        if not chat_id:
            raise PublishError("The channel has no chat id", retryable=False)
        if item.video:
            upload_url = (await self._call(channel, "requestSendFile", {"type": "Video"})).get("upload_url")
            if not upload_url:
                raise PublishError("rubika returned no upload url")
            try:
                async with httpx.AsyncClient(timeout=600) as client:
                    with item.video.open("rb") as fh:
                        resp = await client.post(upload_url, files={"file": (item.video.name, fh, "video/mp4")})
                file_id = (resp.json().get("data") or {}).get("file_id")
            except (httpx.HTTPError, ValueError) as exc:
                raise PublishError(redact(f"rubika upload failed: {exc}", [self._token(channel)])) from exc
            if not file_id:
                raise PublishError("rubika upload returned no file id")
            result = await self._call(channel, "sendFile", {"chat_id": chat_id, "file_id": file_id,
                                                            "text": item.caption})
        else:
            result = await self._call(channel, "sendMessage", {"chat_id": chat_id, "text": item.caption})
        return PublicationResult("published", str(result.get("message_id", "")) or None)

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        raise NotSupported("Rubika bot API does not expose post statistics")

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        raise NotSupported("Rubika bot API does not expose comments")

    async def health(self, channel: Channel) -> None:
        await self._call(channel, "getMe", {})
