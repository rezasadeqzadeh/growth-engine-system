"""Instagram: official API when the account is connected, otherwise the
one-click handoff (the bot sends the admin a page that saves the video and
copies the caption; the admin sends back the post link)."""

from datetime import datetime

from ..models import Channel
from ..services import instagram_api as ig
from .base import (
    Capabilities, Comment, Metrics, NotSupported, PublicationResult, PublishError, PublishItem, check_size,
)


def connected(channel: Channel) -> bool:
    return bool((channel.credentials or {}).get("access_token") and (channel.config or {}).get("ig_user_id"))


class InstagramAdapter:
    type = "instagram"

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="full", comments="api", dm=False,
                            max_video_mb=300, aspects=("9:16",), kinds=("reel", "story"))

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        check_size(item, self.capabilities())
        if not connected(channel) or (channel.config or {}).get("mode") == "handoff":
            return PublicationResult("handoff_pending")
        if not item.video_url:
            raise PublishError("Instagram needs a public video URL", retryable=False)
        token, user_id = channel.credentials["access_token"], channel.config["ig_user_id"]
        try:
            result = await ig.publish_video(token, user_id, item.video_url, item.caption,
                                            story=item.kind == "story", cover_url=item.cover_url)
        except ig.InstagramAuthExpired as exc:
            raise PublishError(str(exc), retryable=False) from exc
        except ig.InstagramError as exc:
            raise PublishError(str(exc)) from exc
        return PublicationResult("published", result["id"], result.get("permalink"))

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        if not connected(channel):
            # Not connected: numbers come from Insights screenshots (OCR) instead.
            raise NotSupported("Instagram is not connected")
        data = await ig.insights(channel.credentials["access_token"], external_id)
        return Metrics(views=data.get("views"), reach=data.get("reach"), likes=data.get("likes"),
                       comments=data.get("comments"), saves=data.get("saved"), shares=data.get("shares"))

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        if not connected(channel):
            raise NotSupported("Instagram is not connected")
        rows = await ig.comments(channel.credentials["access_token"], external_id)
        return [Comment(r["id"], r.get("username", ""), r.get("text", ""),
                        datetime.fromisoformat(r["timestamp"].replace("+0000", "+00:00")))
                for r in rows if r.get("text")]

    async def health(self, channel: Channel) -> None:
        if connected(channel):
            await ig.profile(channel.credentials["access_token"])
