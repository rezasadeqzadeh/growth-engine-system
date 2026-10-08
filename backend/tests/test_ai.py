"""The OpenCode client (the only LLM path) and the router in front of it."""

import json

import httpx
import pytest
import respx

from growth_engine import db
from growth_engine.ai import router
from growth_engine.ai.opencode import EmptyModelResponseError, ImagePart, OpenCodeClient, Prompt
from growth_engine.errors import AppError
from growth_engine.models import UsageCounter

BASE = "https://opencode.test"


def _assistant(text: str | None, completed: bool = True, parts: list | None = None) -> dict:
    info = {"role": "assistant", "time": {"created": 1, **({"completed": 2} if completed else {})}}
    return {"info": info, "parts": parts if parts is not None else ([{"type": "text", "text": text}] if text else [])}


@respx.mock
async def test_prompt_async_then_poll_until_the_newest_assistant_answers():
    respx.post(f"{BASE}/session").respond(200, json={"id": "ses1"})
    sent = respx.post(f"{BASE}/session/ses1/prompt_async").respond(204)
    respx.get(f"{BASE}/session/ses1/message").mock(side_effect=[
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json={"data": [{"info": {"role": "user"}, "parts": []},
                                           _assistant(None, completed=False, parts=[{"type": "step-start"}])]}),
        httpx.Response(200, json=[_assistant("سلام")]),
    ])
    client = OpenCodeClient(BASE, "user", "pw", poll_budget_s=30)
    text = await client.complete("opencode/strong-model", Prompt("sys", "hi", [ImagePart(b"png", "image/png")]))
    assert text == "سلام"
    body = json.loads(sent.calls[0].request.content)
    assert body["model"] == {"providerID": "opencode", "modelID": "strong-model"}
    assert body["parts"][0]["text"].startswith("System: sys")
    assert body["parts"][1]["type"] == "file" and body["parts"][1]["url"].startswith("data:image/png;base64,")


@respx.mock
async def test_a_finished_turn_without_text_fails_at_once():
    respx.post(f"{BASE}/session").respond(200, json={"id": "ses1"})
    respx.post(f"{BASE}/session/ses1/prompt_async").respond(204)
    respx.get(f"{BASE}/session/ses1/message").respond(200, json=[_assistant(None, parts=[{"type": "reasoning"}])])
    with pytest.raises(EmptyModelResponseError):
        await OpenCodeClient(BASE, "", "", poll_budget_s=30).complete("m", Prompt("s", "u"))


@respx.mock
async def test_an_older_answer_is_never_returned_for_a_new_turn():
    """Only the newest assistant message counts; an earlier one with text is ignored."""
    respx.post(f"{BASE}/session").respond(200, json={"id": "ses1"})
    respx.post(f"{BASE}/session/ses1/prompt_async").respond(204)
    respx.get(f"{BASE}/session/ses1/message").mock(side_effect=[
        httpx.Response(200, json=[_assistant("old"), _assistant(None, completed=False, parts=[{"type": "tool"}])]),
        httpx.Response(200, json=[_assistant("old"), _assistant("new")]),
    ])
    assert await OpenCodeClient(BASE, "", "", poll_budget_s=30).complete("m", Prompt("s", "u")) == "new"


@respx.mock
async def test_password_never_appears_in_an_error():
    respx.post(f"{BASE}/session").respond(401, json={})
    with pytest.raises(Exception) as info:
        await OpenCodeClient(BASE, "user", "s3cret-pass", poll_budget_s=1).complete("m", Prompt("s", "u"))
    assert "s3cret-pass" not in str(info.value)


def test_tasks_route_to_their_tier_and_fall_back_to_the_strong_model(monkeypatch):
    assert router.model_for("hashtags") == "opencode/light-model"
    assert router.model_for("caption") == "opencode/strong-model"
    assert router.model_for("read_screenshot") == "opencode/vision-model"
    monkeypatch.setenv("MODEL_LIGHT", "")
    from growth_engine.config import get_settings
    get_settings.cache_clear()
    assert router.model_for("hashtags") == "opencode/strong-model"


async def test_ask_json_retries_once_when_the_model_answers_in_prose(ai):
    replies = iter(["Sure! Here is my thinking...", '```json\n{"tag": "منظره"}\n```'])
    ai.on("Pick the tag", lambda p: next(replies))
    assert await router.ask_json("guess_tag", "Pick the tag", "x") == {"tag": "منظره"}
    assert len(ai.calls) == 2


async def test_cached_tasks_do_not_call_the_model_twice(ai):
    ai.on("hashtags", {"hashtags": ["#کویر"]})
    for _ in range(2):
        await router.ask_json("hashtags", "Suggest hashtags", "same", cache=True)
    assert len(ai.calls) == 1


async def test_each_call_counts_against_the_workspace_plan(ai, workspace):
    ai.on("x", "ok")
    with db.session_scope() as s:
        s.add(UsageCounter(workspace_id=workspace["id"], month=db.utcnow().strftime("%Y-%m"), metric="ai_calls",
                           value=150))
    with pytest.raises(AppError) as info:
        await router.ask_text("caption", "x", "y", workspace_id=workspace["id"])
    assert info.value.code == "plan_limit_reached"
    assert ai.calls == []
