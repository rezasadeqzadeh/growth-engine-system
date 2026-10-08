from .aparat import AparatAdapter
from .base import ChannelAdapter
from .eitaa import EitaaAdapter
from .instagram import InstagramAdapter
from .messenger import MessengerAdapter
from .rubika import RubikaAdapter
from .site import SiteAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    "bale": MessengerAdapter("bale"),
    "telegram": MessengerAdapter("telegram"),
    "eitaa": EitaaAdapter(),
    "rubika": RubikaAdapter(),
    "aparat": AparatAdapter(),
    "instagram": InstagramAdapter(),
    "site": SiteAdapter(),
}


def adapter(channel_type: str) -> ChannelAdapter:
    return _ADAPTERS[channel_type]


def override(channel_type: str, impl: ChannelAdapter) -> None:
    """Replace an adapter (tests)."""
    _ADAPTERS[channel_type] = impl
