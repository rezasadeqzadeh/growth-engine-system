"""What the bot does with each update; outgoing bot calls are recorded, not sent."""

import itertools
from datetime import timedelta

import pytest
from sqlalchemy import select

from growth_engine import db
from growth_engine.bots import api as bot_api
from growth_engine.bots import gateway
from growth_engine.models import (
    Channel, Feedback, Job, KeywordReply, Lead, MediaAsset, Membership, Post, PostVariant, Publication, TagRecipe,
)
from growth_engine.services import storage

_ids = itertools.count(1)


@pytest.fixture
def sent(monkeypatch):
    """Every outgoing bot API call: (method, data)."""
    calls: list[tuple[str, dict]] = []

    async def fake_call(self, method, data=None, files=None):
        calls.append((method, data or {}))
        return {"message_id": 900 + len(calls)}

    monkeypatch.setattr(bot_api.BotApi, "call", fake_call)
    return calls


def _update(**payload) -> dict:
    return {"update_id": next(_ids), **payload}


def _message(user_id: int, text: str = "", chat_id: int | None = None, chat_type: str = "private", **extra) -> dict:
    return {"message_id": next(_ids), "from": {"id": user_id, "first_name": "Ali"},
            "chat": {"id": chat_id or user_id, "type": chat_type}, "text": text, **extra}


def _texts(sent) -> list[str]:
    return [d.get("text", "") for m, d in sent if m == "sendMessage"]


async def test_start_with_a_link_code_binds_the_member(workspace, sent):
    with db.session_scope() as s:
        s.add(Membership(workspace_id=workspace["id"], display_name="Coach", role="approver", link_code="AB12CD34"))
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(4242, "/start ab12cd34")))
    with db.session_scope() as s:
        m = s.scalar(select(Membership).where(Membership.display_name == "Coach"))
        assert m.telegram_user_id == "4242" and m.link_code is None
    assert "Coach" in _texts(sent)[0]


async def test_a_link_code_typed_with_persian_digits_binds_the_member(workspace, sent):
    with db.session_scope() as s:
        s.add(Membership(workspace_id=workspace["id"], display_name="Coach", role="approver", link_code="61D2022E"))
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(4242, "/start \u200f۶۱D۲۰۲۲E\u200e")))
    with db.session_scope() as s:
        assert s.scalar(select(Membership.telegram_user_id).where(Membership.display_name == "Coach")) == "4242"


async def test_a_tagged_video_from_a_member_starts_a_post(workspace, sent):
    msg = _message(777, caption="#گزارش_برنامه برنامه‌ی جمعه", video={"file_id": "F1", "file_size": 5_000_000})
    await gateway.handle_update(workspace["bot_id"], _update(message=msg))
    with db.session_scope() as s:
        post = s.scalar(select(Post))
        assert post.tag == "گزارش_برنامه" and post.status == "processing"
        job = s.scalar(select(Job).where(Job.kind == "process_video"))
        assert job.payload["download"] == {"channel_id": workspace["bot_id"], "file_id": "F1"}
    assert "دریافت شد" in _texts(sent)[0]


async def test_a_video_too_big_for_the_bot_gets_a_direct_upload_link(workspace, sent):
    msg = _message(777, caption="#آموزش", video={"file_id": "F2", "file_size": 80 * 1024 * 1024})
    await gateway.handle_update(workspace["bot_id"], _update(message=msg))
    with db.session_scope() as s:
        assert s.scalar(select(Post)) is None
    assert "https://ge.test/up/" in _texts(sent)[0]


async def test_the_same_update_twice_is_handled_once(workspace, sent):
    update = _update(message=_message(777, caption="#آموزش", video={"file_id": "F3", "file_size": 10}))
    await gateway.handle_update(workspace["bot_id"], update)
    await gateway.handle_update(workspace["bot_id"], update)
    with db.session_scope() as s:
        assert len(list(s.scalars(select(Post)))) == 1


async def test_raw_channel_posts_are_ingested_but_our_own_posts_are_not(workspace, sent):
    raw = {"message_id": 5, "chat": {"id": -100999, "type": "channel"}, "caption": "#منظره",
           "video": {"file_id": "F4"}}
    ours = {**raw, "message_id": 6, "chat": {"id": -100200, "type": "channel"}}
    await gateway.handle_update(workspace["bot_id"], _update(channel_post=ours))
    await gateway.handle_update(workspace["bot_id"], _update(channel_post=raw))
    with db.session_scope() as s:
        assert [p.tag for p in s.scalars(select(Post))] == ["منظره"]


def _pending_post(workspace) -> str:
    with db.session_scope() as s:
        recipe = s.scalar(select(TagRecipe).where(TagRecipe.tag == "منظره"))
        asset = MediaAsset(workspace_id=workspace["id"], source_platform="telegram",
                           transcript={"segments": [{"start": 0, "end": 1, "text": "x"}]})
        s.add(asset)
        s.flush()
        post = Post(workspace_id=workspace["id"], asset_id=asset.id, tag="منظره", recipe_id=recipe.id,
                    status="pending", title="طلوع")
        s.add(post)
        s.flush()
        return post.id


async def test_the_approve_button_schedules_and_closes_the_card(workspace, sent):
    post_id = _pending_post(workspace)
    cq = {"id": "cb1", "from": {"id": 777}, "data": f"a:{post_id}", "message": {"chat": {"id": 777}, "message_id": 3}}
    await gateway.handle_update(workspace["bot_id"], _update(callback_query=cq))
    with db.session_scope() as s:
        assert s.get(Post, post_id).status == "scheduled"
    methods = [m for m, _ in sent]
    assert methods[0] == "answerCallbackQuery"
    assert any("از ۱ تا ۵" in t for t in _texts(sent))  # asks for a rating


async def test_a_sender_pressing_approve_is_refused(workspace, sent):
    post_id = _pending_post(workspace)
    cq = {"id": "cb2", "from": {"id": 888}, "data": f"a:{post_id}", "message": {"chat": {"id": 888}, "message_id": 3}}
    await gateway.handle_update(workspace["bot_id"], _update(callback_query=cq))
    with db.session_scope() as s:
        assert s.get(Post, post_id).status == "pending"
    assert "تأییدکننده" in _texts(sent)[0]


async def test_edit_caption_waits_for_the_instruction_then_queues_the_edit(workspace, sent):
    post_id = _pending_post(workspace)
    cq = {"id": "cb3", "from": {"id": 777}, "data": f"e:{post_id}", "message": {"chat": {"id": 777}, "message_id": 3}}
    await gateway.handle_update(workspace["bot_id"], _update(callback_query=cq))
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(777, "اسم آقای رضایی را هم بیاور")))
    with db.session_scope() as s:
        job = s.scalar(select(Job).where(Job.kind == "edit_captions"))
        assert job.payload["instruction"] == "اسم آقای رضایی را هم بیاور"


async def test_the_time_menu_reschedules_to_the_chosen_slot(workspace, sent):
    post_id = _pending_post(workspace)
    cq = {"id": "cb4", "from": {"id": 777}, "data": f"T:{post_id}:1", "message": {"chat": {"id": 777}, "message_id": 3}}
    await gateway.handle_update(workspace["bot_id"], _update(callback_query=cq))
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.status == "scheduled" and post.scheduled_at > db.utcnow()


async def test_a_keyword_from_the_audience_gets_its_reply_and_becomes_a_lead(workspace, sent):
    with db.session_scope() as s:
        s.add(KeywordReply(workspace_id=workspace["id"], keyword="کویر", reply_text="برنامه‌ی کوه و کویر: لینک"))
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(5555, "کویر")))
    with db.session_scope() as s:
        lead = s.scalar(select(Lead))
        assert lead.keyword == "کویر" and lead.platform_user_id == "5555"
    assert _texts(sent) == ["برنامه‌ی کوه و کویر: لینک"]


async def test_any_other_audience_message_lands_in_the_inbox(workspace, sent):
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(5556, "قیمت برنامه چنده؟")))
    with db.session_scope() as s:
        fb = s.scalar(select(Feedback))
        assert fb.text == "قیمت برنامه چنده؟" and fb.external_id.startswith("5556:")
        assert s.scalar(select(Job).where(Job.kind == "classify_feedback"))


async def test_a_reply_in_the_discussion_group_is_a_comment(workspace, sent):
    msg = _message(6000, "عالی بود", chat_id=-100300, chat_type="supergroup",
                   reply_to_message={"message_id": 1, "is_automatic_forward": True})
    await gateway.handle_update(workspace["bot_id"], _update(message=msg))
    with db.session_scope() as s:
        assert s.scalar(select(Feedback)).text == "عالی بود"
    assert _texts(sent) == []  # no reply in a public group


async def test_an_instagram_link_completes_the_waiting_handoff(workspace, sent):
    post_id = _pending_post(workspace)
    with db.session_scope() as s:
        ig = Channel(workspace_id=workspace["id"], type="instagram", config={"mode": "handoff"})
        s.add(ig)
        s.flush()
        v = PostVariant(post_id=post_id, channel_id=ig.id, kind="reel", caption="c")
        s.add(v)
        s.flush()
        s.add(Publication(variant_id=v.id, status="handoff_pending"))
    await gateway.handle_update(workspace["bot_id"], _update(
        message=_message(777, "https://www.instagram.com/reel/C9xYz12/?igsh=abc")))
    with db.session_scope() as s:
        pub = s.scalar(select(Publication))
        assert pub.status == "published" and pub.external_id == "C9xYz12"
        assert s.scalar(select(Job).where(Job.kind == "collect_metrics"))


async def test_an_insights_screenshot_is_queued_for_reading(workspace, sent):
    msg = _message(777, caption="#آمار", photo=[{"file_id": "small", "file_size": 10}, {"file_id": "big", "file_size": 99}])
    await gateway.handle_update(workspace["bot_id"], _update(message=msg))
    with db.session_scope() as s:
        assert s.scalar(select(Job).where(Job.kind == "read_insights")).payload["file_id"] == "big"


async def test_a_voice_note_after_a_video_is_raw_material_for_it(workspace, sent):
    await gateway.handle_update(workspace["bot_id"], _update(
        message=_message(777, caption="#گزارش_برنامه", video={"file_id": "V", "file_size": 10})))
    await gateway.handle_update(workspace["bot_id"], _update(message=_message(777, voice={"file_id": "VOICE"})))
    with db.session_scope() as s:
        job = s.scalar(select(Job).where(Job.kind == "transcribe_voice"))
        assert job.payload["file_id"] == "VOICE" and job.queue == "media"


async def test_webhook_refuses_a_wrong_secret(workspace, sent):
    from fastapi.testclient import TestClient
    from growth_engine.main import create_app
    client = TestClient(create_app())
    body = _update(message=_message(5557, "سلام"))
    assert client.post(f"/bots/{workspace['bot_id']}/wrong", json=body).json() == {"ok": False}
    assert client.post(f"/bots/{workspace['bot_id']}/hook", json=body).json() == {"ok": True}
    with db.session_scope() as s:
        assert s.scalar(select(Feedback)) is not None
