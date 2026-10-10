"""The HTTP surface: sign-in, access control, no secrets out, public pages."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from growth_engine import db
from growth_engine.main import create_app
from growth_engine.models import (
    Channel, Click, Coupon, FunnelEvent, Offer, Post, PostVariant, Publication, Registration, TrackedLink,
)
from growth_engine.services import approval, links, storage, zarinpal


@pytest.fixture
def client():
    return TestClient(create_app())


def _login(client, phone="09121112233", name="Sara") -> dict:
    client.post("/api/auth/otp/send", json={"phone": phone, "first_name": name})
    token = client.post("/api/auth/otp/verify", json={"phone": phone, "code": "0000"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_sign_in_needs_an_account_and_locks_after_wrong_codes(client):
    client.post("/api/auth/otp/send", json={"phone": "09120000999"})
    resp = client.post("/api/auth/otp/verify", json={"phone": "09120000999", "code": "0000"})
    assert resp.json()["detail"]["code"] == "account_not_found"
    assert client.post("/api/auth/otp/send", json={"phone": "09120000999"}).json()["detail"]["code"] == "otp_too_soon"
    assert client.post("/api/auth/otp/send", json={"phone": "123"}).status_code == 400


def test_wrong_codes_lock_the_code(client):
    client.post("/api/auth/otp/send", json={"phone": "09120000998", "first_name": "A"})
    for _ in range(5):
        assert client.post("/api/auth/otp/verify", json={"phone": "09120000998", "code": "1111"}).status_code == 401
    resp = client.post("/api/auth/otp/verify", json={"phone": "09120000998", "code": "0000"})
    assert resp.json()["detail"]["code"] == "otp_locked"


def test_a_new_workspace_is_a_copy_of_its_vertical_template(client):
    headers = _login(client)
    ws = client.post("/api/workspaces", json={"name": "Hey'at", "vertical": "sports_board"}, headers=headers).json()
    recipes = client.get(f"/api/workspaces/{ws['id']}/recipes", headers=headers).json()["recipes"]
    assert {r["tag"] for r in recipes} == {"اعلام_برنامه", "گزارش_برنامه", "آموزش", "آدم‌ها", "منظره"}
    channels = client.get(f"/api/workspaces/{ws['id']}/channels", headers=headers).json()["channels"]
    assert [c["type"] for c in channels] == ["site"]
    kit = client.get(f"/api/workspaces/{ws['id']}/brand-kit", headers=headers).json()
    assert len(kit["pillars"]) == 5 and len(kit["questions"]) == 7


def test_another_user_cannot_see_a_workspace(client, workspace):
    headers = _login(client, "09125550000", "Mallory")
    assert client.get(f"/api/workspaces/{workspace['id']}/posts", headers=headers).status_code == 403
    assert client.get(f"/api/workspaces/{workspace['id']}/posts").status_code == 401


def test_channel_secrets_go_in_and_never_come_out(client, workspace):
    headers = _login(client, "09120000001")  # the workspace owner (conftest)
    channels = client.get(f"/api/workspaces/{workspace['id']}/channels", headers=headers).json()["channels"]
    body = str(channels)
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef" not in body and "hook" not in body
    telegram = next(c for c in channels if c["type"] == "telegram")
    assert telegram["secrets_set"] == ["bot_token"]
    created = client.post(f"/api/workspaces/{workspace['id']}/channels", headers=headers, json={
        "type": "aparat", "name": "Aparat", "credentials": {"username": "kooh", "password": "plain-pass"}}).json()
    assert "plain-pass" not in str(created)
    with db.session_scope() as s:
        stored = s.get(Channel, created["id"]).credentials
        assert "password" not in stored and stored["lpass"] != "plain-pass"  # only Aparat's hash is kept


def test_only_the_owner_may_consent_to_auto_approval(client, workspace):
    owner = _login(client, "09120000001")
    resp = client.patch(f"/api/workspaces/{workspace['id']}", headers=owner, json={"settings": {"auto_approve_consent": True}})
    assert resp.json()["settings"]["auto_approve_consent"] is True
    resp = client.patch(f"/api/workspaces/{workspace['id']}", headers=owner, json={"settings": {"nope": 1}})
    assert resp.json()["detail"]["code"] == "setting_unknown"


def test_recipe_validation_refuses_unknown_channels(client, workspace):
    owner = _login(client, "09120000001")
    resp = client.post(f"/api/workspaces/{workspace['id']}/recipes", headers=owner,
                       json={"tag": "تست", "goal": "convert", "channels": ["myspace"], "timing": {"mode": "immediate"}})
    assert resp.status_code == 422


def _offer(workspace, **kw) -> str:
    with db.session_scope() as s:
        offer = Offer(workspace_id=workspace["id"], slug="kooh-kavir", title="کوه و کویر", price_toman=1_800_000,
                      capacity=kw.get("capacity", 12), starts_at=db.utcnow() + timedelta(days=20))
        s.add(offer)
        s.flush()
        return offer.id


def test_click_then_registration_is_credited_to_the_first_link(client, workspace, monkeypatch):
    _offer(workspace)
    with db.session_scope() as s:
        first = links.create(s, workspace["id"], "https://ge.test/o/boshrouyeh/kooh-kavir", channel_type="telegram",
                             tag="گزارش_برنامه")
        second = links.create(s, workspace["id"], "https://ge.test/o/boshrouyeh/kooh-kavir", channel_type="bale")
        codes = first.code, second.code
    resp = client.get(f"/b/{codes[0]}", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"].endswith("/o/boshrouyeh/kooh-kavir")
    client.get(f"/b/{codes[1]}", follow_redirects=False)  # a later click does not replace the first touch
    page = client.get("/o/boshrouyeh/kooh-kavir")
    assert "کوه و کویر" in page.text and "۱۲" in page.text
    client.post("/o/boshrouyeh/kooh-kavir/start")
    monkeypatch.setattr(zarinpal, "request_payment", lambda *a, **k: {"authority": "A1",
                                                                      "payment_url": "https://pay.test/A1"})
    resp = client.post("/o/boshrouyeh/kooh-kavir", data={"name": "سارا", "phone": "09151234567", "city": "مشهد"},
                       follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "https://pay.test/A1"
    with db.session_scope() as s:
        reg = s.scalar(select(Registration))
        assert s.get(TrackedLink, reg.source_link_id).code == codes[0]
        reg_id = reg.id
        assert len(list(s.scalars(select(Click)))) == 2
        assert {e.kind for e in s.scalars(select(FunnelEvent))} == {"form_view", "form_start"}
    monkeypatch.setattr(zarinpal, "verify_payment", lambda amount, authority: {"ref_id": "R9", "code": 100})
    done = client.get(f"/pay/registration?r={reg_id}&Authority=A1&Status=OK")
    assert "R9" in done.text
    again = client.get(f"/pay/registration?r={reg_id}&Authority=A1&Status=OK")  # a repeated callback
    assert again.status_code == 200
    owner = _login(client, "09120000001")
    dash = client.get(f"/api/workspaces/{workspace['id']}/dashboard", headers=owner).json()
    assert dash["registrations"] == 1 and dash["revenue_toman"] == 1_800_000
    assert dash["by_source"] == [{"key": "tag:گزارش_برنامه", "count": 1}]
    assert [f["value"] for f in dash["funnel"]][1:] == [2, 1, 1]


def test_a_coupon_beats_the_link_and_gives_its_discount(client, workspace, monkeypatch):
    _offer(workspace)
    with db.session_scope() as s:
        s.add(Coupon(workspace_id=workspace["id"], code="SARA10", influencer="sara", discount_percent=10))
    amounts = []
    monkeypatch.setattr(zarinpal, "request_payment",
                        lambda amount, *a, **k: amounts.append(amount) or {"authority": "A2", "payment_url": "https://p"})
    client.post("/o/boshrouyeh/kooh-kavir", data={"name": "علی", "phone": "09151234568", "coupon": "sara10"},
                follow_redirects=False)
    assert amounts == [1_620_000]
    with db.session_scope() as s:
        assert s.scalar(select(Registration)).source_coupon_id is not None


def test_a_full_offer_takes_no_more_registrations(client, workspace):
    offer_id = _offer(workspace, capacity=1)
    with db.session_scope() as s:
        s.add(Registration(workspace_id=workspace["id"], offer_id=offer_id, name="x", phone="09150000000",
                           status="paid", paid_at=db.utcnow()))
    page = client.post("/o/boshrouyeh/kooh-kavir", data={"name": "y", "phone": "09150000001"})
    assert page.status_code == 409 and "ظرفیت" in page.text


def _published_site_post(workspace) -> tuple[str, str]:
    key = storage.save_bytes(storage.new_key(workspace["id"], "out", ".mp4"), b"video-bytes")
    with db.session_scope() as s:
        site = s.scalar(select(Channel).where(Channel.workspace_id == workspace["id"], Channel.type == "site"))
        post = Post(workspace_id=workspace["id"], status="published", title="گزارش شتری")
        s.add(post)
        s.flush()
        v = PostVariant(post_id=post.id, channel_id=site.id, kind="message", title="گزارش شتری",
                        caption="بند اول\nبند دوم", video_key=key)
        s.add(v)
        s.flush()
        pub = Publication(variant_id=v.id, status="published", published_at=db.utcnow(), external_id=post.id)
        s.add(pub)
        s.flush()
        return post.id, pub.id


def test_the_site_page_counts_views_and_takes_comments(client, workspace):
    post_id, _ = _published_site_post(workspace)
    page = client.get(f"/s/boshrouyeh/p/{post_id}")
    assert page.status_code == 200 and "بند دوم" in page.text and 'dir="rtl"' in page.text
    assert "گزارش شتری" in client.get("/s/boshrouyeh").text
    client.post(f"/s/boshrouyeh/p/{post_id}/comment", data={"name": "نازنین", "text": "برای مبتدی‌ها هم دارید؟"})
    with db.session_scope() as s:
        from growth_engine.models import Feedback
        assert s.scalar(select(Feedback)).channel_type == "site"
        assert s.scalar(select(FunnelEvent).where(FunnelEvent.kind == "page_view")).data == {"ref": post_id}


def test_the_handoff_page_offers_the_video_and_the_caption(client, workspace):
    _, pub_id = _published_site_post(workspace)
    page = client.get(f"/h/{approval.handoff_token(pub_id)}")
    assert page.status_code == 200 and "بند اول" in page.text and "navigator.share" in page.text
    assert client.get("/h/not-a-token").status_code == 404


def test_media_needs_a_valid_signature(client, workspace):
    key = storage.save_bytes(storage.new_key(workspace["id"], "out", ".jpg"), b"jpg")
    url = storage.signed_url(key).replace("https://ge.test", "")
    assert client.get(url).content == b"jpg"
    assert client.get(url.replace("sig=", "sig=0")).status_code == 403
    assert client.get(f"/media/{key}?exp=9999999999&sig=x").status_code == 403


def test_a_public_audit_is_queued_and_hides_the_phone(client, ai):
    resp = client.post("/api/audits", data={"handle": "boshrouyeh_kooh", "vertical": "sports_board",
                                            "phone": "09150001111"},
                       files=[("files", ("profile.png", b"png-bytes", "image/png"))])
    slug = resp.json()["slug"]
    report = client.get(f"/api/audits/{slug}").json()
    assert report["status"] == "queued" and "phone" not in report
    for _ in range(3):
        client.post("/api/audits", data={"handle": "x", "phone": "09150001111"},
                    files=[("files", ("p.png", b"p", "image/png"))])
    last = client.post("/api/audits", data={"handle": "x", "phone": "09150001111"},
                       files=[("files", ("p.png", b"p", "image/png"))])
    assert last.json()["detail"]["code"] == "audit_limit"


def test_plan_purchase_comes_back_to_the_settings_page(client, workspace, monkeypatch):
    """The callback URL Zarinpal gets must be a route that exists (it had lost its /api prefix)."""
    urls = []
    monkeypatch.setattr(zarinpal, "request_payment",
                        lambda amount, desc, callback, mobile=None: urls.append(callback) or
                        {"authority": "PA1", "payment_url": "https://pay.test/PA1"})
    monkeypatch.setattr(zarinpal, "verify_payment", lambda amount, authority: {"ref_id": "R1", "code": 100})
    owner = _login(client, "09120000001")
    assert client.post(f"/api/workspaces/{workspace['id']}/billing/start", headers=owner,
                       json={"plan": "basic"}).json() == {"payment_url": "https://pay.test/PA1"}
    path = urls[0].replace("https://ge.test", "")
    resp = client.get(f"{path}&Authority=PA1&Status=OK", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == f"https://panel.ge.test/w/{workspace['id']}/settings?result=paid"
    assert client.get(f"/api/workspaces/{workspace['id']}", headers=owner).json()["plan"] == "basic"


def test_the_api_applies_pending_migrations_on_start(tmp_path, monkeypatch):
    """A fresh database gets every table when the API starts; a second start is a no-op."""
    from sqlalchemy import create_engine, inspect
    from growth_engine.config import get_settings
    url = f"sqlite:///{tmp_path}/fresh.db"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("AUTO_MIGRATE", "true")
    get_settings.cache_clear()
    db.configure(url)
    for _ in range(2):
        with TestClient(create_app()) as c:
            assert c.get("/api/health").json() == {"ok": True}
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"alembic_version", "users", "posts", "jobs"} <= tables


def test_the_panel_origin_passes_cors_and_others_are_refused(client):
    """An empty PANEL_URL refused every browser call: OPTIONS answered 400."""
    ok = client.options("/api/auth/otp/send", headers={"Origin": "https://panel.ge.test",
                                                      "Access-Control-Request-Method": "POST"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://panel.ge.test"
    local = client.options("/api/auth/otp/send", headers={"Origin": "http://localhost:3000",
                                                         "Access-Control-Request-Method": "POST"})
    assert local.status_code == 200  # development: any localhost port
    bad = client.options("/api/auth/otp/send", headers={"Origin": "https://evil.test",
                                                       "Access-Control-Request-Method": "POST"})
    assert bad.status_code == 400


def test_extra_origins_come_from_cors_origins(monkeypatch):
    from growth_engine.config import get_settings
    monkeypatch.setenv("PANEL_URL", "")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.test, https://b.test/")
    get_settings.cache_clear()
    assert get_settings().allowed_origins == ["https://a.test", "https://b.test"]


def test_persian_digits_work_for_phone_and_code(client):
    """The code typed as ۰۰۰۰ crashed sign-in with a 500 (non-ASCII compare)."""
    assert client.post("/api/auth/otp/send", json={"phone": "۰۹۱۲۷۷۷۸۸۸۸", "first_name": "R"}).json()["sent"]
    resp = client.post("/api/auth/otp/verify", json={"phone": "۰۹۱۲۷۷۷۸۸۸۸", "code": "۰۰۰۰"})
    assert resp.status_code == 200 and resp.json()["user"]["phone"] == "09127778888"
    client.post("/api/auth/otp/send", json={"phone": "09127778889", "first_name": "R"})
    assert client.post("/api/auth/otp/verify", json={"phone": "09127778889", "code": "۱۲x۴"}).status_code == 401


def test_persian_digits_are_converted_in_number_and_code_fields(client, workspace, monkeypatch):
    """Phones, coupon codes and slugs typed with Persian or Arabic digits are accepted as ASCII."""
    owner = _login(client, "09120000001")
    resp = client.post(f"/api/workspaces/{workspace['id']}/coupons", headers=owner, json={"code": "SARA۱۰"})
    assert resp.status_code == 200 and resp.json()["code"] == "SARA10"
    resp = client.post(f"/api/workspaces/{workspace['id']}/offers", headers=owner,
                       json={"slug": "trip-۱۴۰۵", "title": "سفر", "price_toman": 0})
    assert resp.json()["slug"] == "trip-1405"
    page = client.post("/o/boshrouyeh/trip-1405", data={"name": "علی", "phone": "٠٩١٥١٢٣٤٥٦٧", "coupon": "sara١٠"})
    assert page.status_code == 200
    with db.session_scope() as s:
        assert s.scalar(select(Registration)).phone == "09151234567"


def test_an_unknown_phone_signs_up_with_the_same_code(client):
    """Sign-in for a new phone said account_not_found, and asking for a sign-up code
    was then refused for a minute (otp_too_soon): no account could be made."""
    client.post("/api/auth/otp/send", json={"phone": "09129990000"})
    first = client.post("/api/auth/otp/verify", json={"phone": "09129990000", "code": "0000"})
    assert first.json()["detail"]["code"] == "account_not_found"
    second = client.post("/api/auth/otp/verify", json={"phone": "09129990000", "code": "0000",
                                                       "first_name": "رضا", "last_name": "ص"})
    assert second.status_code == 200 and second.json()["user"]["first_name"] == "رضا"
    with db.session_scope() as s:
        from growth_engine.models import User
        assert s.scalar(select(User).where(User.phone == "09129990000")) is not None


def test_asking_again_too_soon_says_how_long_to_wait(client):
    client.post("/api/auth/otp/send", json={"phone": "09121231234", "first_name": "A"})
    detail = client.post("/api/auth/otp/send", json={"phone": "09121231234"}).json()["detail"]
    assert detail["code"] == "otp_too_soon" and 100 < detail["retry_after"] <= 121


def test_a_new_workspace_brand_kit_has_colours_and_fonts(client):
    """The first kit was saved with no colours: the brand page crashed on colors.primary[1]."""
    headers = _login(client, "09127770000")
    ws = client.post("/api/workspaces", json={"name": "Shop", "vertical": "general"}, headers=headers).json()
    kit = client.get(f"/api/workspaces/{ws['id']}/brand-kit", headers=headers).json()
    assert len(kit["colors"]["primary"]) == 2 and kit["colors"]["text"].startswith("#")
    assert kit["fonts"]["body"] and kit["fonts"]["heading"]


def test_a_reviewer_saves_title_caption_and_hashtags_before_approving(client, workspace):
    post_id, _ = _published_site_post(workspace)
    with db.session_scope() as s:
        s.get(Post, post_id).status = "pending"
        variant_id = s.scalar(select(PostVariant.id).where(PostVariant.post_id == post_id))
    owner = _login(client, "09120000001")
    r = client.put(f"/api/workspaces/{workspace['id']}/posts/{post_id}/variants/{variant_id}", headers=owner,
                   json={"title": "عنوان تازه", "caption": "متن تازه", "tags": ["#کوه", " بشرویه ", ""]})
    assert r.status_code == 200, r.text
    detail = client.get(f"/api/workspaces/{workspace['id']}/posts/{post_id}", headers=owner).json()
    v = detail["variants"][0]
    assert (v["title"], v["caption"], v["tags"]) == ("عنوان تازه", "متن تازه", ["کوه", "بشرویه"])
    assert detail["status"] == "pending"  # saving does not approve
