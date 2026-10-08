"""Shared fixtures: a fresh SQLite database and storage dir per test, and a
scripted stand-in for the OpenCode server (no test reaches a real model)."""

import json
import os
from collections.abc import Callable

import pytest

from growth_engine import db
from growth_engine.ai import router
from growth_engine.ai.opencode import Prompt
from growth_engine.channels import registry
from growth_engine.config import get_settings
from growth_engine.models import Channel, Membership, User


class FakeAI:
    """Answers by the first rule whose text appears in the system prompt."""

    def __init__(self) -> None:
        self.rules: list[tuple[str, object]] = []
        self.calls: list[tuple[str, Prompt]] = []

    def on(self, needle: str, reply: object) -> None:
        self.rules.insert(0, (needle, reply))

    async def complete(self, model: str, prompt: Prompt) -> str:
        self.calls.append((model, prompt))
        for needle, reply in self.rules:
            if needle in prompt.system:
                value = reply(prompt) if isinstance(reply, Callable) else reply
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        raise AssertionError(f"No fake AI rule for: {prompt.system[:80]}")


# GE_TEST_DATABASE_URL runs the suite on Postgres (production's database);
# by default every test gets its own SQLite file.
PG_URL = os.environ.get("GE_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    url = PG_URL or f"sqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("BRAND_FONTS_DIR", str(tmp_path / "fonts"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://ge.test")
    monkeypatch.setenv("PANEL_URL", "https://panel.ge.test")
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-0123")
    monkeypatch.setenv("MODEL_LIGHT", "opencode/light-model")
    monkeypatch.setenv("MODEL_STRONG", "opencode/strong-model")
    monkeypatch.setenv("MODEL_VISION", "opencode/vision-model")
    monkeypatch.setenv("SMS_WEBSERVICE_API_KEY", "")
    monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    db.configure(url)
    if PG_URL:
        db.Base.metadata.drop_all(db.engine())
    db.Base.metadata.create_all(db.engine())
    saved = dict(registry._ADAPTERS)
    yield
    registry._ADAPTERS.clear()
    registry._ADAPTERS.update(saved)
    router.set_client(None)
    get_settings.cache_clear()


@pytest.fixture
def ai():
    fake = FakeAI()
    router.set_client(fake)
    return fake


@pytest.fixture
def owner():
    with db.session_scope() as s:
        user = User(phone="09120000001", first_name="Reza", last_name="Owner")
        s.add(user)
    return user


@pytest.fixture
def workspace(owner):
    """A sports-board workspace with a connected Telegram bot and a bound approver."""
    from growth_engine.services import workspaces

    with db.session_scope() as s:
        user = s.get(User, owner.id)
        ws = workspaces.create_workspace(s, user, "Boshrouyeh Board", "sports_board", slug="boshrouyeh")
        bot = Channel(workspace_id=ws.id, type="telegram", name="Board channel",
                      config={"chat_id": "-100200", "username": "boshrouyeh_kooh", "raw_chat_id": "-100999",
                              "discussion_chat_id": "-100300"},
                      credentials={"bot_token": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", "webhook_secret": "hook"})
        s.add(bot)
        s.add(Membership(workspace_id=ws.id, display_name="Admin", role="approver", telegram_user_id="777"))
        s.add(Membership(workspace_id=ws.id, display_name="Sender", role="sender", telegram_user_id="888"))
        s.flush()
        return {"id": ws.id, "slug": ws.slug, "bot_id": bot.id}
