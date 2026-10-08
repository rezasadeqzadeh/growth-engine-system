"""The owned channel: every post gets its own page on the workspace's site
(public/site.py serves it). Views and comments are ours, so this is the
one channel with complete numbers."""

from sqlalchemy import func, select

from .. import db
from ..models import Channel, FunnelEvent
from .base import Capabilities, Comment, Metrics, NotSupported, PublicationResult, PublishError, PublishItem


class SiteAdapter:
    type = "site"

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="full", comments="push", dm=False,
                            max_video_mb=2048, aspects=("9:16", "16:9"), kinds=("message",))

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        if not item.page_url:
            raise PublishError("The post has no page address", retryable=False)
        # The page renders from the variant itself; publishing makes it public.
        return PublicationResult("published", item.page_url.rsplit("/", 1)[-1], item.page_url)

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        with db.session_scope() as s:
            views = s.scalar(select(func.count()).select_from(FunnelEvent).where(
                FunnelEvent.workspace_id == channel.workspace_id, FunnelEvent.kind == "page_view",
                FunnelEvent.data["ref"].as_string() == external_id)) or 0
        return Metrics(views=views)

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        raise NotSupported("Site comments are pushed by the page form")

    async def health(self, channel: Channel) -> None:
        return None
