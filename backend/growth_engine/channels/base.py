"""One interface for every channel. A new channel is a new adapter, not a
change to the system; a broken adapter never stops the others."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..models import Channel


class NotSupported(Exception):
    """The channel cannot do this through its API."""


class PublishError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Capabilities:
    auto_publish: bool
    metrics: str        # full | limited | screenshot | none
    comments: str       # api | push | public | none
    dm: bool
    max_video_mb: int
    aspects: tuple[str, ...]
    kinds: tuple[str, ...]  # variant kinds this channel takes


@dataclass
class PublishItem:
    kind: str
    caption: str
    title: str
    tags: list[str]
    video: Path | None
    cover: Path | None
    srt: Path | None
    video_url: str | None      # signed public URL (Instagram fetches from it)
    cover_url: str | None
    page_url: str | None       # this post's page on the site channel


@dataclass
class PublicationResult:
    status: str                # published | handoff_pending
    external_id: str | None = None
    external_url: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Metrics:
    views: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None


@dataclass
class Comment:
    external_id: str
    author: str
    text: str
    at: datetime


class ChannelAdapter(Protocol):
    type: str

    def capabilities(self) -> Capabilities: ...

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult: ...

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics: ...

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]: ...

    async def health(self, channel: Channel) -> None: ...


def check_size(item: PublishItem, caps: Capabilities) -> None:
    if item.video and item.video.exists() and item.video.stat().st_size > caps.max_video_mb * 1024 * 1024:
        raise PublishError(f"Video is larger than {caps.max_video_mb} MB for this channel", retryable=False)
