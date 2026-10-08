"""Channel adapters against their (mocked) HTTP APIs."""

import hashlib
import json

import httpx
import pytest
import respx

from growth_engine.channels.aparat import AparatAdapter, hash_password
from growth_engine.channels.base import PublishError, PublishItem
from growth_engine.channels.eitaa import EitaaAdapter
from growth_engine.channels.instagram import InstagramAdapter
from growth_engine.channels.messenger import MessengerAdapter
from growth_engine.channels.rubika import RubikaAdapter
from growth_engine.models import Channel

TOKEN = "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"


def _item(tmp_path, caption="متن", kind="message", **kw) -> PublishItem:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 100)
    return PublishItem(kind=kind, caption=caption, title=kw.get("title", "عنوان"), tags=kw.get("tags", []),
                       video=video, cover=None, srt=kw.get("srt"), video_url=kw.get("video_url"), cover_url=None,
                       page_url=None)


@respx.mock
async def test_telegram_sends_a_long_caption_as_a_reply_message(tmp_path):
    send_video = respx.post(f"https://api.telegram.org/bot{TOKEN}/sendVideo").respond(
        200, json={"ok": True, "result": {"message_id": 41}})
    send_text = respx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage").respond(
        200, json={"ok": True, "result": {"message_id": 42}})
    channel = Channel(type="telegram", config={"chat_id": "-100200", "username": "@kooh"},
                      credentials={"bot_token": TOKEN})
    result = await MessengerAdapter("telegram").publish(channel, _item(tmp_path, caption="ا" * 1500))
    assert result.external_id == "41" and result.external_url == "https://t.me/kooh/41"
    assert send_video.called and send_text.called  # 1500 chars is over Telegram's 1024 caption limit
    assert "reply_to_message_id=41" in send_text.calls[0].request.content.decode()


@respx.mock
async def test_bale_uses_its_own_host_and_keeps_the_caption_on_the_video(tmp_path):
    route = respx.post(f"https://tapi.bale.ai/bot{TOKEN}/sendVideo").respond(
        200, json={"ok": True, "result": {"message_id": 7}})
    channel = Channel(type="bale", config={"chat_id": "@kooh"}, credentials={"bot_token": TOKEN})
    await MessengerAdapter("bale").publish(channel, _item(tmp_path, caption="ا" * 1500))
    assert route.called  # Bale's caption limit is 4096: one message


@respx.mock
async def test_a_bot_api_refusal_never_carries_the_token(tmp_path):
    respx.post(f"https://api.telegram.org/bot{TOKEN}/sendVideo").respond(
        403, json={"ok": False, "description": f"Forbidden: bot {TOKEN} is not a member"})
    channel = Channel(type="telegram", config={"chat_id": "-1"}, credentials={"bot_token": TOKEN})
    with pytest.raises(PublishError) as info:
        await MessengerAdapter("telegram").publish(channel, _item(tmp_path))
    assert TOKEN not in str(info.value) and info.value.retryable is False


@respx.mock
async def test_eitaa_posts_the_file_with_its_caption(tmp_path):
    route = respx.post("https://eitaayar.ir/api/EITAATOKEN/sendFile").respond(
        200, json={"ok": True, "result": {"message_id": 12}})
    channel = Channel(type="eitaa", config={"chat_id": "kooh"}, credentials={"token": "EITAATOKEN"})
    result = await EitaaAdapter().publish(channel, _item(tmp_path))
    assert result.external_url == "https://eitaa.com/kooh/12"
    assert b'name="chat_id"' in route.calls[0].request.content


@respx.mock
async def test_rubika_uploads_in_three_steps(tmp_path):
    respx.post("https://botapi.rubika.ir/v3/RTOKEN/requestSendFile").respond(
        200, json={"status": "OK", "data": {"upload_url": "https://up.rubika.test/u1"}})
    respx.post("https://up.rubika.test/u1").respond(200, json={"data": {"file_id": "FID"}})
    send = respx.post("https://botapi.rubika.ir/v3/RTOKEN/sendFile").respond(
        200, json={"status": "OK", "data": {"message_id": "88"}})
    channel = Channel(type="rubika", config={"chat_id": "c1"}, credentials={"token": "RTOKEN"})
    result = await RubikaAdapter().publish(channel, _item(tmp_path))
    assert result.external_id == "88"
    assert json.loads(send.calls[0].request.content)["file_id"] == "FID"


@respx.mock
async def test_aparat_logs_in_gets_the_form_and_uploads(tmp_path):
    lpass = hash_password("secret")
    respx.get(f"https://www.aparat.com/etc/api/login/luser/kooh/lpass/{lpass}").respond(
        200, json={"login": {"ltoken": "LT"}})
    respx.get("https://www.aparat.com/etc/api/uploadform/luser/kooh/ltoken/LT").respond(
        200, json={"uploadform": {"formAction": "https://upload.aparat.test/post", "frm-id": 991}})
    upload = respx.post("https://upload.aparat.test/post").respond(200, json={"uploadpost": {"uid": "abC12"}})
    channel = Channel(type="aparat", config={"category": 22}, credentials={"username": "kooh", "lpass": lpass})
    srt = tmp_path / "full.srt"
    srt.write_text("1\n")
    result = await AparatAdapter().publish(channel, _item(tmp_path, kind="full", tags=["کوه-نوردی", "بشرویه"], srt=srt))
    assert result.external_url == "https://www.aparat.com/v/abC12"
    assert result.notes == ["aparat_srt_manual"]  # the API takes no subtitles
    body = upload.calls[0].request.content.decode()
    assert "991" in body and "کوه نوردی-بشرویه" in body


def test_aparat_password_hash_is_sha1_of_md5():
    assert hash_password("x") == hashlib.sha1(hashlib.md5(b"x").hexdigest().encode()).hexdigest()


@respx.mock
async def test_instagram_creates_a_container_waits_then_publishes(tmp_path, monkeypatch):
    from growth_engine.services import instagram_api
    graph = instagram_api.GRAPH_V
    create = respx.post(f"{graph}/1784/media").respond(200, json={"id": "C1"})
    respx.get(f"{graph}/C1").mock(side_effect=[httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
                                               httpx.Response(200, json={"status_code": "FINISHED"})])
    respx.post(f"{graph}/1784/media_publish").respond(200, json={"id": "M1"})
    respx.get(f"{graph}/M1").respond(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
    original = instagram_api.publish_video

    async def quick(*a, **k):
        return await original(*a, **{**k, "poll_s": 0})
    monkeypatch.setattr(instagram_api, "publish_video", quick)
    channel = Channel(type="instagram", config={"ig_user_id": "1784"}, credentials={"access_token": "IGTOKEN"})
    result = await InstagramAdapter().publish(channel, _item(tmp_path, kind="reel", video_url="https://ge.test/media/v"))
    assert result.status == "published" and result.external_url == "https://www.instagram.com/reel/abc/"
    sent = create.calls[0].request.content.decode()
    assert "media_type=REELS" in sent and "share_to_feed=true" in sent


async def test_instagram_without_a_connection_is_a_handoff(tmp_path):
    result = await InstagramAdapter().publish(Channel(type="instagram", config={}, credentials={}), _item(tmp_path))
    assert result.status == "handoff_pending"


@respx.mock
async def test_instagram_errors_do_not_carry_the_access_token(tmp_path):
    from growth_engine.services import instagram_api
    respx.post(f"{instagram_api.GRAPH_V}/1784/media").respond(
        400, json={"error": {"code": 100, "message": "Invalid parameter access_token=IGTOKEN"}})
    channel = Channel(type="instagram", config={"ig_user_id": "1784"}, credentials={"access_token": "IGTOKEN"})
    with pytest.raises(PublishError) as info:
        await InstagramAdapter().publish(channel, _item(tmp_path, kind="reel", video_url="https://x"))
    assert "IGTOKEN" not in str(info.value)


async def test_a_video_over_the_channel_limit_is_refused_before_upload(tmp_path):
    item = _item(tmp_path)
    item.video.write_bytes(b"x" * (51 * 1024 * 1024))
    channel = Channel(type="eitaa", config={"chat_id": "k"}, credentials={"token": "T"})
    with pytest.raises(PublishError) as info:
        await EitaaAdapter().publish(channel, item)
    assert info.value.retryable is False
