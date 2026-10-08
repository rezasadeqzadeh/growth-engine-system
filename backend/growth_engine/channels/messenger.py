"""Telegram and Bale channels: the bot posts as an admin of the channel.

View counts are not readable through the bot API; reactions arrive as
`message_reaction_count` updates (Telegram) and comments as replies in the
channel's discussion group, both pushed to the bot gateway.
"""

from ..bots.api import CAPTION_LIMIT, UPLOAD_LIMIT_MB, BotApi, BotApiError
from ..models import Channel
from .base import Capabilities, Comment, Metrics, NotSupported, PublicationResult, PublishError, PublishItem, check_size


class MessengerAdapter:
    def __init__(self, platform: str) -> None:
        self.type = platform

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="limited",
                            comments="push" if self.type == "telegram" else "none", dm=True,
                            max_video_mb=UPLOAD_LIMIT_MB[self.type], aspects=("9:16",), kinds=("message",))

    def _api(self, channel: Channel) -> BotApi:
        token = (channel.credentials or {}).get("bot_token")
        if not token:
            raise PublishError("The channel has no bot token", retryable=False)
        return BotApi(self.type, token)

    def _post_url(self, channel: Channel, message_id: str) -> str | None:
        username = (channel.config or {}).get("username")
        if not username:
            return None
        host = "t.me" if self.type == "telegram" else "ble.ir"
        return f"https://{host}/{username.lstrip('@')}/{message_id}"

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        caps = self.capabilities()
        check_size(item, caps)
        chat_id = (channel.config or {}).get("chat_id")
        if not chat_id:
            raise PublishError("The channel has no chat id", retryable=False)
        api = self._api(channel)
        limit = CAPTION_LIMIT[self.type]
        try:
            if item.video:
                first = item.caption if len(item.caption) <= limit else ""
                result = await api.send_video(chat_id, item.video, first, cover=item.cover)
                if not first and item.caption:
                    await api.send_message(chat_id, item.caption, reply_to=str(result.get("message_id")))
            else:
                result = await api.send_message(chat_id, item.caption)
        except BotApiError as exc:
            retryable = "chat not found" not in exc.description.lower() and "forbidden" not in exc.description.lower()
            raise PublishError(str(exc), retryable=retryable) from exc
        message_id = str(result.get("message_id", ""))
        return PublicationResult("published", message_id, self._post_url(channel, message_id))

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        raise NotSupported("Bot API does not expose view counts")

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        raise NotSupported("Comments are pushed to the gateway")

    async def health(self, channel: Channel) -> None:
        await self._api(channel).get_me()
