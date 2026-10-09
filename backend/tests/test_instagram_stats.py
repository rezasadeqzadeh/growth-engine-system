"""The Instagram statistics page: members only, real numbers, and a page that
still shows profile and posts when Instagram refuses the account insights."""

import pytest
from fastapi.testclient import TestClient

from growth_engine import db
from growth_engine.main import create_app
from growth_engine.models import Channel
from growth_engine.services import instagram_api


@pytest.fixture
def client():
    return TestClient(create_app())


def _login(client, phone: str) -> dict:
    client.post("/api/auth/otp/send", json={"phone": phone})
    return {"Authorization": f"Bearer {client.post('/api/auth/otp/verify', json={'phone': phone, 'code': '0000'}).json()['token']}"}


def _connect(workspace_id: str) -> None:
    with db.session_scope() as s:
        s.add(Channel(workspace_id=workspace_id, type="instagram", name="@shop", enabled=True,
                      config={"mode": "api", "ig_user_id": "1784", "username": "shop"},
                      credentials={"access_token": "IGQ-secret-token"}))


def _fake_instagram(monkeypatch, insights_fail=False):
    async def profile(token):
        return {"username": "shop", "account_type": "BUSINESS", "followers_count": 1000, "media_count": 40}

    async def recent_media(token, limit=30):
        return [{"id": "m1", "media_type": "VIDEO", "caption": "سلام", "timestamp": "2026-10-01T10:00:00+0000",
                 "like_count": 40, "comments_count": 10, "permalink": "https://instagram.com/p/1"},
                {"id": "m2", "media_type": "IMAGE", "timestamp": "2026-10-03T10:00:00+0000",
                 "like_count": 20, "comments_count": 10}]

    async def account_insights(token, user_id, since, until):
        if insights_fail:
            raise instagram_api.InstagramError("(#10) Application does not have permission")
        assert until - since == 28 * 86400
        return {"reach": 5000, "views": 12000, "follows_and_unfollows": 30}

    monkeypatch.setattr(instagram_api, "profile", profile)
    monkeypatch.setattr(instagram_api, "recent_media", recent_media)
    monkeypatch.setattr(instagram_api, "account_insights", account_insights)


def test_a_member_sees_the_latest_numbers(client, workspace, monkeypatch):
    _connect(workspace["id"])
    _fake_instagram(monkeypatch)
    body = client.get(f"/api/workspaces/{workspace['id']}/instagram/stats", headers=_login(client, "09120000001")).json()
    assert body["followers"] == 1000 and body["period"]["reach"] == 5000
    assert body["engagement_rate"] == 4.0  # (50 + 30) / 2 posts / 1000 followers
    assert [p["id"] for p in body["posts"]] == ["m1", "m2"]
    assert "IGQ-secret-token" not in str(body)


def test_refused_insights_still_show_profile_and_posts(client, workspace, monkeypatch):
    _connect(workspace["id"])
    _fake_instagram(monkeypatch, insights_fail=True)
    body = client.get(f"/api/workspaces/{workspace['id']}/instagram/stats", headers=_login(client, "09120000001")).json()
    assert body["period"] == {} and body["period_error"] == "insights_unavailable" and len(body["posts"]) == 2


def test_needs_sign_in_and_a_connected_account(client, workspace):
    assert client.get(f"/api/workspaces/{workspace['id']}/instagram/stats").status_code == 401
    resp = client.get(f"/api/workspaces/{workspace['id']}/instagram/stats", headers=_login(client, "09120000001"))
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "instagram_not_connected"
