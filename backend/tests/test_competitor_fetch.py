"""Competitor pages read from Meta on the single-flight `meta` queue, tagged and ranked by the AI."""

import httpx
import pytest
import respx
from sqlalchemy import select

from growth_engine import db
from growth_engine.config import get_settings
from growth_engine.errors import AppError, NotFound
from growth_engine.jobs import queue
from growth_engine.models import Competitor, CompetitorPost, ContentIdea, Job, User, Workspace
from growth_engine.services import competitors

DISCOVERY = "https://graph.facebook.com/v23.0/17841400000000000"


@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setenv("META_GRAPH_TOKEN", "EAAG-platform-token-secret")
    monkeypatch.setenv("META_IG_USER_ID", "17841400000000000")
    monkeypatch.setenv("META_MIN_INTERVAL_S", "0")
    get_settings.cache_clear()


def _media(i: int, likes: int, comments: int = 0) -> dict:
    return {"id": f"m{i}", "caption": f"post {i}", "media_type": "VIDEO", "media_product_type": "REELS",
            "timestamp": f"2026-09-{i:02d}T10:00:00+0000", "like_count": likes, "comments_count": comments,
            "permalink": f"https://www.instagram.com/reel/m{i}/", "thumbnail_url": f"https://cdn/m{i}.jpg"}


def _add(workspace_id: str, handle: str = "yazd_desert_tour") -> str:
    with db.session_scope() as s:
        return competitors.add(s, s.get(Workspace, workspace_id), handle, "direct").id


def test_meta_jobs_run_one_at_a_time(workspace):
    with db.session_scope() as s:
        first = queue.enqueue(s, "fetch_competitor", {"competitor_id": "a"})
        queue.enqueue(s, "fetch_competitor", {"competitor_id": "b"})
        queue.enqueue(s, "analyze_competitor", {"competitor_id": "a"})
        assert first.queue == "meta"
    taken = queue.claim("meta")
    assert taken.id == first.id
    assert queue.claim("meta") is None  # the other Meta request waits while one is in flight
    assert queue.claim("default").kind == "analyze_competitor"  # other queues are not held up
    queue.finish(taken.id)
    assert queue.claim("meta").payload == {"competitor_id": "b"}


def test_fetch_needs_the_platform_token_and_a_real_username(workspace, meta, monkeypatch):
    comp_id = _add(workspace["id"], "bad handle!")
    with db.session_scope() as s:
        with pytest.raises(AppError) as err:
            competitors.request_fetch(s, s.get(Competitor, comp_id))
        assert err.value.code == "competitor_handle_invalid"
    monkeypatch.setenv("META_GRAPH_TOKEN", "")
    get_settings.cache_clear()
    with db.session_scope() as s:
        with pytest.raises(AppError) as err:
            competitors.request_fetch(s, s.get(Competitor, comp_id))
        assert err.value.code == "meta_not_configured"


@respx.mock
async def test_fetch_saves_the_public_page_and_queues_the_analysis(workspace, meta):
    comp_id = _add(workspace["id"])
    with db.session_scope() as s:
        assert competitors.request_fetch(s, s.get(Competitor, comp_id))
        assert not competitors.request_fetch(s, s.get(Competitor, comp_id))  # already queued
    profile = {"id": "1784", "username": "yazd_desert_tour", "name": "Yazd Desert", "biography": "tours",
               "followers_count": 5000, "media_count": 3}
    route = respx.get(DISCOVERY).mock(side_effect=[
        httpx.Response(200, json={"business_discovery": {**profile, "media": {
            "data": [_media(1, 900, 100), _media(2, 100)],
            "paging": {"cursors": {"after": "CUR"}, "next": "https://graph.facebook.com/next"}}}}),
        httpx.Response(200, json={"business_discovery": {**profile, "media": {"data": [_media(3, 200)]}}}),
    ])
    await competitors.fetch({"competitor_id": comp_id})
    assert route.call_count == 2
    assert "media.limit(50).after(CUR)" in route.calls[1].request.url.params["fields"]
    with db.session_scope() as s:
        comp = s.get(Competitor, comp_id)
        assert (comp.followers, comp.biography, comp.fetch_status) == (5000, "tours", "analyzing")
        posts = {p.external_id: p for p in s.scalars(select(CompetitorPost))}
        assert set(posts) == {"m1", "m2", "m3"}
        assert posts["m1"].format == "reel" and posts["m1"].ratio_to_avg == 2.31
        assert s.scalar(select(Job.kind).where(Job.queue == "default")) == "analyze_competitor"
        # Reading again updates numbers instead of adding duplicates.
        competitors.save_fetched(s, comp, profile, [_media(1, 1000, 100)])
        assert s.scalar(select(CompetitorPost.likes).where(CompetitorPost.external_id == "m1")) == 1000
        assert len(s.scalars(select(CompetitorPost)).all()) == 3


@respx.mock
async def test_a_private_or_missing_page_fails_without_retrying(workspace, meta):
    comp_id = _add(workspace["id"])
    respx.get(DISCOVERY).respond(400, json={"error": {"message": "Invalid user id", "code": 110}})
    await competitors.fetch({"competitor_id": comp_id})
    with db.session_scope() as s:
        comp = s.get(Competitor, comp_id)
        assert (comp.fetch_status, comp.fetch_error) == ("failed", "page_not_found")


async def test_ai_finds_the_best_types_and_topics_and_they_become_ideas(workspace, ai):
    comp_id = _add(workspace["id"])
    with db.session_scope() as s:
        comp = s.get(Competitor, comp_id)
        competitors.save_fetched(s, comp, {"followers_count": 5000},
                                 [_media(1, 900), _media(2, 800), _media(3, 50), _media(4, 50)])
        ids = {p.external_id: p.id for p in s.scalars(select(CompetitorPost))}
    tags = {"m1": ("tutorial", "شب کویر"), "m2": ("tutorial", "شب کویر"), "m3": ("offer", "تخفیف"),
            "m4": ("offer", "تخفیف")}
    ai.on("Tag each post", {"items": [{"id": ids[k], "content_type": t, "topic": tp, "hook_type": "question"}
                                      for k, (t, tp) in tags.items()]})
    ai.on("You study one competitor page", {"summary": "آموزش‌ها برنده‌اند",
                                            "best_types": [{"type": "tutorial", "why": "کاربردی"}, {"type": "bogus"}],
                                            "best_topics": [{"topic": "شب کویر", "why": "زیبا"}]})
    await competitors.analyze_one({"competitor_id": comp_id})
    with db.session_scope() as s:
        comp = s.get(Competitor, comp_id)
        assert comp.fetch_status == "done"
        assert comp.insight["best_types"] == [{"type": "tutorial", "why": "کاربردی"}]
        best = competitors.best_items(s, workspace["id"])
        assert [(i["content_type"], i["topic"]) for i in best["items"]] == [("tutorial", "شب کویر"), ("offer", "تخفیف")]
        assert best["items"][0]["examples"][0]["handle"] == "yazd_desert_tour"
        assert best["types"][0]["content_type"] == "tutorial"

    ai.on("Write one content idea", {"text": "آموزش عکاسی از آسمان شب در کارگاه خودمان"})
    with db.session_scope() as s:
        idea = await competitors.inspire(s, s.get(Workspace, workspace["id"]), "tutorial", "شب کویر", None)
        assert idea.source == "competitor"
    with db.session_scope() as s:
        assert s.scalar(select(ContentIdea.text)) == "آموزش عکاسی از آسمان شب در کارگاه خودمان"


def test_a_workspace_sees_only_its_own_competitors(workspace, owner):
    from growth_engine.services import workspaces

    comp_id = _add(workspace["id"])
    with db.session_scope() as s:
        other = workspaces.create_workspace(s, s.get(User, owner.id), "Other shop", "sports_board", slug="other")
        other_id = other.id
    with db.session_scope() as s:
        with pytest.raises(NotFound):
            competitors.get(s, other_id, comp_id)
        assert competitors.best_items(s, other_id) == {"types": [], "items": []}
