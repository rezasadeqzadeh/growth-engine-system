"""The core loop, end to end with FFmpeg/Whisper replaced: a tagged video
becomes per-channel drafts, waits for approval, and is published."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from growth_engine import db
from growth_engine.channels import registry
from growth_engine.channels.base import Capabilities, Metrics, PublicationResult, PublishError
from growth_engine.errors import AppError
from growth_engine.jobs import runner
from growth_engine.media import ffmpeg, render
from growth_engine.models import (
    Channel, Job, Membership, Offer, Post, PostVariant, Publication, TrackedLink, Workspace,
)
from growth_engine.services import pipeline, posts, publishing, storage

COPY = {
    "instagram": {"caption": "از قله‌ی شتری، کویر تا افق پیداست. لینک ثبت‌نام در بیو. برنامه‌ی بعدی"},
    "messenger": {"text": "جمعه ۱۸ نفر شتری را صعود کردیم. برنامه‌ی بعدی: {link}"},
    "aparat": {"title": "صعود قله شتری بشرویه", "description": "گزارش برنامه {link}", "tags": ["کوهنوردی", "بشرویه"]},
    "story": {"text": "ثبت‌نام"}, "site": {"title": "گزارش برنامه‌ی شتری", "body": "متن کامل"},
    "cover_title": "صعود شتری", "overlay": "",
}


@pytest.fixture
def media_stubs(monkeypatch, tmp_path):
    """FFmpeg, Whisper and OpenCV are replaced; everything else runs for real."""
    def fake_render(src, work, probe, specs, look, overlay, cover_title, music):
        out = render.Rendered()
        for spec in specs:
            path = work / f"{spec.name}.mp4"
            path.write_bytes(b"video")
            out.files[spec.name] = path
            out.durations[spec.name] = 30.0
        for name in ("cover", "frame"):
            (work / f"{name}.jpg").write_bytes(b"jpg")
            out.files[name] = work / f"{name}.jpg"
        out.files["srt"] = work / "full.srt"
        out.files["srt"].write_text("1\n")
        return out

    monkeypatch.setattr(ffmpeg, "probe", lambda p: ffmpeg.Probe(160.0, 1920, 1080, True))
    monkeypatch.setattr(ffmpeg, "extract_audio", lambda src, dst: dst.write_bytes(b"wav"))
    monkeypatch.setattr(ffmpeg, "detect_silences", lambda p, d: [(40.0, 45.0)])
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(pipeline.transcribe, "transcribe", lambda audio, glossary=None: {"segments": [
        {"start": 1.0, "end": 3.0, "text": "از قله‌ی شطری", "words": []}]})


@pytest.fixture
def scripted_ai(ai):
    ai.on("You write social media copy", COPY)
    ai.on("Suggest Persian Instagram hashtags", {"hashtags": ["#کوهنوردی", "#بشرویه", "spam"]})
    ai.on("Pick the tag", {"tag": "منظره"})
    return ai


class RecordingAdapter:
    def __init__(self, type_: str, result: PublicationResult | Exception) -> None:
        self.type, self.result, self.items = type_, result, []

    def capabilities(self):
        return Capabilities(True, "limited", "none", False, 50, ("9:16",), ("message",))

    async def publish(self, channel, item):
        self.items.append(item)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def fetch_metrics(self, channel, external_id):
        return Metrics(views=10)

    async def fetch_comments(self, channel, external_id):
        return []

    async def health(self, channel):
        return None


def _ingest(workspace, caption: str) -> str:
    key = storage.save_bytes(storage.new_key(workspace["id"], "raw", ".mp4"), b"raw video")
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        member = s.scalar(select(Membership).where(Membership.telegram_user_id == "777"))
        return posts.ingest(s, ws, platform="telegram", member=member, chat_id="777", msg_id="1",
                            caption_text=caption, file_key=key).id


async def _run_all(queue_name: str = "default", limit: int = 20) -> None:
    for _ in range(limit):
        if not await runner.run_one(queue_name):
            return


async def test_a_tagged_video_becomes_a_draft_for_every_channel_of_its_recipe(workspace, media_stubs, scripted_ai):
    post_id = _ingest(workspace, "#گزارش_برنامه برنامه‌ی جمعه شتری، ۱۸ نفر")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.tag == "گزارش_برنامه" and post.raw_note == "برنامه‌ی جمعه شتری، ۱۸ نفر"
        job = s.scalar(select(Job).where(Job.kind == "process_video"))
        assert job.queue == "media"  # FFmpeg/Whisper work goes to the media worker

    assert await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.status == "pending", post.error
        rows = posts.variants_of(s, post_id)
        kinds = {(c.type, v.kind) for v, c in rows}
        # The recipe names more channels, but only telegram and site are connected.
        assert kinds == {("telegram", "message"), ("site", "message")}
        telegram = next(v for v, c in rows if c.type == "telegram")
        link = s.get(TrackedLink, telegram.tracked_link_id)
        assert link.code.startswith("t") and f"https://ge.test/b/{link.code}" in telegram.caption
        assert link.tag == "گزارش_برنامه" and link.post_id == post_id
        checks = {q["check"]: q for q in post.qc}
        assert checks["faces"]["message"] == "qc.faces_unknown"  # no face detection: the approver looks
        assert s.scalar(select(Job).where(Job.kind == "send_approval_card"))


async def test_without_a_tag_the_ai_guesses_and_the_card_asks(workspace, media_stubs, scripted_ai):
    post_id = _ingest(workspace, "طلوع روی کویر")
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.tag == "منظره" and post.tag_guessed and post.status == "pending"


async def test_approval_schedules_one_publish_job_per_variant(workspace, media_stubs, scripted_ai):
    post_id = _ingest(workspace, "#گزارش_برنامه برنامه")
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        approver = s.scalar(select(Membership).where(Membership.role == "approver"))
        posts.approve(s, post, approver)
        assert post.status == "scheduled"
        local = post.scheduled_at.astimezone(posts.timing.TEHRAN)
        assert (local.hour, local.minute) == (18, 30)  # report tag: the next evening
        jobs = list(s.scalars(select(Job).where(Job.kind == "publish_variant")))
        assert len(jobs) == 2 and all(j.run_at == post.scheduled_at for j in jobs)


async def test_a_sender_cannot_approve(workspace, media_stubs, scripted_ai):
    post_id = _ingest(workspace, "#منظره طلوع")
    await runner.run_one("media")
    with db.session_scope() as s:
        sender = s.scalar(select(Membership).where(Membership.role == "sender"))
        with pytest.raises(AppError) as info:
            posts.approve(s, s.get(Post, post_id), sender)
        assert info.value.code == "approver_required"


async def test_publishing_records_each_channel_and_finishes_the_post(workspace, media_stubs, scripted_ai):
    tele = RecordingAdapter("telegram", PublicationResult("published", "55", "https://t.me/boshrouyeh_kooh/55"))
    registry.override("telegram", tele)
    post_id = _ingest(workspace, "#منظره طلوع")
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        posts.approve(s, post, None, at=db.utcnow() - timedelta(seconds=1))
    await _run_all()
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.status == "published"
        pubs = list(s.scalars(select(Publication)))
        # #منظره goes to instagram and telegram; only telegram is connected.
        assert [p.status for p in pubs] == ["published"]
        assert s.scalar(select(Job).where(Job.kind == "collect_metrics"))
    assert tele.items[0].video is not None and "https://ge.test/b/t" in tele.items[0].caption


async def test_a_rescheduled_post_ignores_its_old_publish_jobs(workspace, media_stubs, scripted_ai):
    tele = RecordingAdapter("telegram", PublicationResult("published", "1"))
    registry.override("telegram", tele)
    post_id = _ingest(workspace, "#منظره طلوع")
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        posts.approve(s, post, None, at=db.utcnow() - timedelta(seconds=1))
        posts.reschedule(s, post, None, db.utcnow() + timedelta(days=1))
    await _run_all()
    assert tele.items == []  # the old jobs ran and stepped aside
    with db.session_scope() as s:
        assert s.get(Post, post_id).status == "scheduled"


async def test_a_channel_that_refuses_is_recorded_and_the_others_still_publish(workspace, media_stubs, scripted_ai):
    registry.override("telegram", RecordingAdapter(
        "telegram", PublishError("telegram sendVideo: Forbidden: bot 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", False)))
    post_id = _ingest(workspace, "#گزارش_برنامه برنامه")  # goes to telegram and the site
    await runner.run_one("media")
    with db.session_scope() as s:
        posts.approve(s, s.get(Post, post_id), None, at=db.utcnow() - timedelta(seconds=1))
    await _run_all()
    with db.session_scope() as s:
        by_type = {c.type: p for p, v, c in s.execute(
            select(Publication, PostVariant, Channel).join(PostVariant, PostVariant.id == Publication.variant_id)
            .join(Channel, Channel.id == PostVariant.channel_id))}
        assert by_type["site"].status == "published"
        assert by_type["telegram"].status == "failed"
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef" not in by_type["telegram"].error  # the bot token never leaks
        assert s.get(Post, post_id).status == "published"
        assert all("ABCDEFGHIJ" not in (j.last_error or "") for j in s.scalars(select(Job)))


async def test_instagram_without_the_api_waits_for_the_one_click_handoff(workspace, media_stubs, scripted_ai):
    with db.session_scope() as s:
        s.add(Channel(workspace_id=workspace["id"], type="instagram", name="ig", config={"mode": "handoff"}))
    post_id = _ingest(workspace, "#منظره طلوع")
    await runner.run_one("media")
    with db.session_scope() as s:
        kinds = {(c.type, v.kind) for v, c in posts.variants_of(s, post_id)}
        assert {("instagram", "reel"), ("instagram", "story")} <= kinds
        posts.approve(s, s.get(Post, post_id), None, at=db.utcnow() - timedelta(seconds=1))
    registry.override("telegram", RecordingAdapter("telegram", PublicationResult("published", "9")))
    await _run_all()
    with db.session_scope() as s:
        pending = list(s.scalars(select(Publication).where(Publication.status == "handoff_pending")))
        assert len(pending) == 2
        assert s.scalar(select(Job).where(Job.kind == "send_handoff"))


async def test_auto_approval_needs_the_owners_prior_consent(workspace, media_stubs, scripted_ai):
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        ws.settings = {**ws.settings, "auto_approve_consent": True}
    post_id = _ingest(workspace, "#منظره طلوع")  # a low-risk tag
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.auto_approve_at is not None
        post.auto_approve_at = db.utcnow() - timedelta(minutes=1)
        ws = s.get(Workspace, workspace["id"])
        ws.settings = {**ws.settings, "auto_approve_consent": False}  # consent withdrawn
    from growth_engine.services import maintenance
    await maintenance.auto_approve({})
    with db.session_scope() as s:
        assert s.get(Post, post_id).status == "pending"


async def test_a_convert_post_links_to_the_next_open_offer(workspace, media_stubs, scripted_ai):
    with db.session_scope() as s:
        s.add(Offer(workspace_id=workspace["id"], slug="kooh-kavir", title="کوه و کویر", price_toman=1800000,
                    capacity=12, starts_at=db.utcnow() + timedelta(days=20)))
    post_id = _ingest(workspace, "#اعلام_برنامه آخر هفته‌ی کوه و کویر")
    await runner.run_one("media")
    with db.session_scope() as s:
        v, _ = posts.variants_of(s, post_id)[0]
        link = s.get(TrackedLink, v.tracked_link_id)
        assert link.target_url == "https://ge.test/o/boshrouyeh/kooh-kavir"
        post = s.get(Post, post_id)
        posts.approve(s, post, None, at=db.utcnow() + timedelta(hours=1))
        reminder = s.scalar(select(Job).where(Job.kind == "publish_reminder"))
        assert reminder.run_at - post.scheduled_at == timedelta(days=3)


async def test_a_subtitle_fix_rerenders_and_is_remembered_in_the_glossary(workspace, media_stubs, scripted_ai):
    post_id = _ingest(workspace, "#گزارش_برنامه برنامه")
    await runner.run_one("media")
    with db.session_scope() as s:
        posts.request_subtitle_fix(s, s.get(Post, post_id), None, "شطری را شتری کن")
    await runner.run_one("media")
    with db.session_scope() as s:
        from growth_engine.models import MediaAsset
        from growth_engine.services import brand_kit
        post = s.get(Post, post_id)
        assert post.status == "pending"
        assert s.get(MediaAsset, post.asset_id).transcript["segments"][0]["text"] == "از قله‌ی شتری"
        assert "شتری" in brand_kit.current(s, workspace["id"]).glossary


def test_subtitle_fix_phrases():
    assert posts.parse_subtitle_fix("شطری را شتری کن") == ("شطری", "شتری")
    assert posts.parse_subtitle_fix("ارسک -> ارسک‌کوه") == ("ارسک", "ارسک‌کوه")
    assert posts.parse_subtitle_fix("سلام") is None


async def test_a_retried_video_counts_once_against_the_plan(workspace, media_stubs, scripted_ai, monkeypatch):
    from growth_engine.models import Job
    from growth_engine.services import usage

    calls = []

    def flaky(audio, glossary=None):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("whisper crashed")
        return {"segments": [{"start": 0, "end": 2, "text": "سلام", "words": []}]}

    monkeypatch.setattr(pipeline.transcribe, "transcribe", flaky)
    post_id = _ingest(workspace, "#گزارش_برنامه جمعه")
    assert await runner.run_one("media")  # fails, will retry
    with db.session_scope() as s:
        s.scalar(select(Job).where(Job.kind == "process_video")).run_at = db.utcnow()
    assert await runner.run_one("media")
    with db.session_scope() as s:
        assert s.get(Post, post_id).status == "pending"
    assert usage.used(workspace["id"], "videos") == 1


def test_whisper_gets_samples_not_a_path(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    import wave

    from growth_engine.media import transcribe

    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    seen = {}

    class Model:
        def transcribe(self, audio, **kwargs):
            seen["audio"] = audio
            return [], type("Info", (), {"language": "fa"})()

    monkeypatch.setattr(transcribe, "_model", lambda: Model())
    transcribe.transcribe(wav)
    assert seen["audio"].tolist() == [0.0, 0.5, -1.0]  # decoded here, PyAV is never asked


async def test_edited_subtitles_rerender_and_keep_the_edited_captions(workspace, media_stubs, scripted_ai):
    from growth_engine.models import MediaAsset

    post_id = _ingest(workspace, "#گزارش_برنامه برنامه")
    await runner.run_one("media")
    with db.session_scope() as s:
        v, _ = posts.variants_of(s, post_id)[0]
        v.caption, v.tags = "متن ویرایش‌شده‌ی من", ["کوه"]
        link_id = v.tracked_link_id
        lines = posts.subtitle_lines(s.get(MediaAsset, s.get(Post, post_id).asset_id))
        assert lines
        lines[0]["text"] = "از قله‌ی شتری بالا رفتیم"
        posts.edit_subtitles(s, s.get(Post, post_id), None, lines)
        assert s.get(Post, post_id).status == "processing"
    await runner.run_one("media")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        assert post.status == "pending"
        seg = s.get(MediaAsset, post.asset_id).transcript["segments"][0]
        assert seg["text"] == "از قله‌ی شتری بالا رفتیم"
        assert [w["word"] for w in seg["words"]] == ["از", "قله‌ی", "شتری", "بالا", "رفتیم"]
        kept = next(v for v, _ in posts.variants_of(s, post_id) if v.tracked_link_id == link_id)
        assert (kept.caption, kept.tags) == ("متن ویرایش‌شده‌ی من", ["کوه"])  # the re-render kept the edit


def test_subtitle_lines_must_keep_their_times(workspace, media_stubs):
    from growth_engine.models import MediaAsset

    post_id = _ingest(workspace, "#گزارش_برنامه برنامه")
    with db.session_scope() as s:
        post = s.get(Post, post_id)
        post.status = "pending"
        asset = s.get(MediaAsset, post.asset_id)
        asset.duration_s = 10.0
        asset.transcript = {"segments": [{"start": 1, "end": 2, "text": "سلام", "words": []}]}
        with pytest.raises(AppError) as err:
            posts.edit_subtitles(s, post, None, [{"start": 5, "end": 30, "text": "x"}])
        assert err.value.code == "subtitle_time_invalid"


async def test_the_routing_tag_never_reaches_the_audience(workspace, ai):
    from growth_engine.models import TagRecipe
    from growth_engine.services import brand_kit, captions

    ai.on("You write social media copy", {"instagram": {"caption": "صعود شتری #up #کوه"},
                                          "aparat": {"title": "صعود", "description": "گزارش", "tags": ["up", "#کوه"]}})
    ai.on("Suggest Persian Instagram hashtags", {"hashtags": ["#UP", "#کوهنوردی", "#بشرویه"]})
    with db.session_scope() as s:
        ws = s.get(Workspace, workspace["id"])
        recipe = TagRecipe(workspace_id=ws.id, tag="up", goal="engage", caption_style="", cta="", video_spec={})
        post = Post(workspace_id=ws.id, tag="up", status="processing")
        copy = await captions.write_all(ws, brand_kit.current(s, ws.id), recipe, post, "متن", "")
    assert copy["hashtags"] == ["#کوهنوردی", "#بشرویه"]
    assert copy["instagram"]["caption"] == "صعود شتری #کوه"
    assert copy["aparat"]["tags"] == ["#کوه"]


def test_tags_are_stored_bare_and_added_to_the_text_when_published():
    from growth_engine.services import captions

    copy = {**COPY, "hashtags": ["#کوهنوردی", "#بشرویه"]}
    reel = captions.compose(copy, "instagram", "reel", "https://ge.test/b/x")
    tg = captions.compose(copy, "telegram", "message", "https://ge.test/b/x")
    story = captions.compose(copy, "instagram", "story", "https://ge.test/b/x")
    site = captions.compose(copy, "site", "message", "https://ge.test/b/x")
    assert reel["tags"] == tg["tags"] == site["tags"] == ["کوهنوردی", "بشرویه"]  # no '#' stored: the panel adds one
    assert "#" not in reel["caption"] and story["tags"] == []
    assert captions.published_text(reel["caption"], ["کوه"], "instagram", "reel").endswith("\n\n#کوه")
    assert captions.published_text(tg["caption"], ["کوه"], "telegram", "message").endswith("#کوه")
    assert captions.published_text("متن", ["کوه"], "instagram", "story") == "متن"
    assert captions.published_text("متن", ["کوه"], "site", "message") == "متن"
    assert captions.published_text("متن #کوه", ["کوه"], "telegram", "message") == "متن #کوه"  # never twice
