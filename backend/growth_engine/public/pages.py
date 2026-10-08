"""Public pages, rendered on the server (they must work without the panel
and be readable by search engines): tracked-link redirects, offer
registration and payment, the site channel, the Instagram handoff page,
direct uploads and signed media files."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..config import get_settings
from ..db import get_session
from ..errors import AppError, NotFound
from ..i18n import catalog, fa_digits, t
from ..models import Channel, FunnelEvent, Membership, Offer, Post, PostVariant, Publication, Workspace
from ..services import agency, approval, feedback, links, offers, storage, uploads
from ..services import posts as post_service

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(t=t, fa=fa_digits)
COOKIE_AGE = 365 * 24 * 3600


def _visitor(request: Request) -> tuple[str, bool]:
    vid = request.cookies.get(links.VISITOR_COOKIE)
    return (vid, False) if vid else (secrets.token_hex(12), True)


def _page(request: Request, name: str, ctx: dict, status: int = 200) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def error_text(code: str) -> str:
    key = f"error.{code}"
    return t(key) if key in catalog() else t("error.generic")


def _error_page(request: Request, exc: AppError) -> HTMLResponse:
    return _page(request, "message.html", {"title": t("page.error_title"), "text": error_text(exc.code)}, exc.status)


def _workspace(s: Session, slug: str) -> Workspace:
    ws = s.scalar(select(Workspace).where(Workspace.slug == slug))
    if ws is None:
        raise NotFound("workspace")
    return ws


# Tracked links --------------------------------------------------------------

@router.get("/b/{code}")
def follow_link(code: str, request: Request, s: Session = Depends(get_session)) -> Response:
    vid, new = _visitor(request)
    try:
        link = links.record_click(s, code, vid, request.headers.get("user-agent", ""))
    except AppError as exc:
        return _error_page(request, exc)
    resp = RedirectResponse(link.target_url, status_code=302)
    if new:
        resp.set_cookie(links.VISITOR_COOKIE, vid, max_age=COOKIE_AGE, httponly=True, samesite="lax")
    resp.set_cookie(links.FIRST_TOUCH_COOKIE, links.remember_first_touch(request.cookies.get(links.FIRST_TOUCH_COOKIE), link),
                    max_age=COOKIE_AGE, httponly=True, samesite="lax")
    return resp


# Offers ---------------------------------------------------------------------

def _offer_ctx(s: Session, ws: Workspace, offer: Offer) -> dict:
    return {"ws": ws, "offer": offer, "seats_left": offers.seats_left(s, offer), "brand": agency.brand_for(s, ws),
            "price": fa_digits(f"{offer.price_toman:,}")}


@router.get("/o/{ws_slug}/{offer_slug}")
def offer_page(ws_slug: str, offer_slug: str, request: Request, s: Session = Depends(get_session)) -> Response:
    try:
        ws, offer = offers.find_offer(s, ws_slug, offer_slug)
    except AppError as exc:
        return _error_page(request, exc)
    vid, new = _visitor(request)
    s.add(FunnelEvent(workspace_id=ws.id, kind="form_view", at=db.utcnow(), visitor_id=vid, data={"offer": offer.id}))
    resp = _page(request, "offer.html", {**_offer_ctx(s, ws, offer), "error": None, "form": {}})
    if new:
        resp.set_cookie(links.VISITOR_COOKIE, vid, max_age=COOKIE_AGE, httponly=True, samesite="lax")
    return resp


@router.post("/o/{ws_slug}/{offer_slug}/start")
def offer_form_started(ws_slug: str, offer_slug: str, request: Request, s: Session = Depends(get_session)) -> dict:
    """Sent once when a visitor starts typing: the 'form started' step of the funnel."""
    ws, offer = offers.find_offer(s, ws_slug, offer_slug)
    vid = request.cookies.get(links.VISITOR_COOKIE)
    s.add(FunnelEvent(workspace_id=ws.id, kind="form_start", at=db.utcnow(), visitor_id=vid, data={"offer": offer.id}))
    return {"ok": True}


@router.post("/o/{ws_slug}/{offer_slug}")
def offer_submit(ws_slug: str, offer_slug: str, request: Request, name: str = Form(""), phone: str = Form(""),
                 city: str = Form(""), coupon: str = Form(""), media_consent: str | None = Form(None),
                 s: Session = Depends(get_session)) -> Response:
    try:
        ws, offer = offers.find_offer(s, ws_slug, offer_slug)
    except AppError as exc:
        return _error_page(request, exc)
    try:
        result = offers.register(s, ws, offer, name=name, phone=phone, city=city, media_consent=bool(media_consent),
                                 coupon_code=coupon, visitor_id=request.cookies.get(links.VISITOR_COOKIE),
                                 first_touch_cookie=request.cookies.get(links.FIRST_TOUCH_COOKIE))
    except AppError as exc:
        s.rollback()
        form = {"name": name, "phone": phone, "city": city, "coupon": coupon}
        return _page(request, "offer.html", {**_offer_ctx(s, ws, offer), "form": form, "error": error_text(exc.code)},
                     exc.status)
    if result["paid"]:
        return _page(request, "message.html", {"title": t("offer.done_title"), "text": t("offer.done_free",
                                                                                          title=offer.title)})
    return RedirectResponse(result["payment_url"], status_code=303)


@router.get("/pay/registration")
def offer_paid(r: str, request: Request, Authority: str = "", Status: str = "", s: Session = Depends(get_session)) -> Response:
    try:
        reg = offers.verify(s, r, Authority, Status)
    except AppError as exc:
        return _error_page(request, exc)
    offer = s.get(Offer, reg.offer_id)
    if reg.status == "paid":
        return _page(request, "message.html", {"title": t("offer.done_title"),
                                               "text": t("offer.done_paid", title=offer.title, ref=reg.ref_id)})
    return _page(request, "message.html", {"title": t("offer.failed_title"), "text": t("offer.failed")}, 402)


# The site channel -----------------------------------------------------------

def _site_posts(s: Session, ws: Workspace) -> list[tuple[Post, PostVariant]]:
    rows = s.execute(select(Post, PostVariant).join(PostVariant, PostVariant.post_id == Post.id)
                     .join(Channel, Channel.id == PostVariant.channel_id)
                     .join(Publication, Publication.variant_id == PostVariant.id)
                     .where(Post.workspace_id == ws.id, Channel.type == "site", Publication.status == "published")
                     .order_by(Publication.published_at.desc()).limit(60))
    return list(rows)


@router.get("/s/{ws_slug}")
def site_index(ws_slug: str, request: Request, s: Session = Depends(get_session)) -> Response:
    try:
        ws = _workspace(s, ws_slug)
    except AppError as exc:
        return _error_page(request, exc)
    items = [{"post": p, "variant": v, "cover": storage.signed_url(v.cover_key) if v.cover_key else None}
             for p, v in _site_posts(s, ws)]
    return _page(request, "site_index.html", {"ws": ws, "items": items, "brand": agency.brand_for(s, ws)})


@router.get("/s/{ws_slug}/p/{post_id}")
def site_post(ws_slug: str, post_id: str, request: Request, s: Session = Depends(get_session)) -> Response:
    try:
        ws = _workspace(s, ws_slug)
        match = next(((p, v) for p, v in _site_posts(s, ws) if p.id == post_id), None)
        if match is None:
            raise NotFound("post")
    except AppError as exc:
        return _error_page(request, exc)
    post, variant = match
    vid, _ = _visitor(request)
    s.add(FunnelEvent(workspace_id=ws.id, kind="page_view", at=db.utcnow(), visitor_id=vid, data={"ref": post.id}))
    link = links.destination_for(s, post)
    return _page(request, "site_post.html", {
        "ws": ws, "post": post, "variant": variant, "brand": agency.brand_for(s, ws), "cta_url": link,
        "video": storage.signed_url(variant.video_key) if variant.video_key else None,
        "cover": storage.signed_url(variant.cover_key) if variant.cover_key else None,
        "paragraphs": [p for p in variant.caption.split("\n") if p.strip()], "sent": request.query_params.get("sent")})


@router.post("/s/{ws_slug}/p/{post_id}/comment")
def site_comment(ws_slug: str, post_id: str, request: Request, name: str = Form(""), text: str = Form(""),
                 s: Session = Depends(get_session)) -> Response:
    try:
        ws = _workspace(s, ws_slug)
    except AppError as exc:
        return _error_page(request, exc)
    if text.strip():
        feedback.ingest_site_comment(s, ws, post_id, name.strip()[:120], text.strip()[:2000])
    return RedirectResponse(f"/s/{ws_slug}/p/{post_id}?sent=1", status_code=303)


# Instagram handoff ----------------------------------------------------------

@router.get("/h/{token}")
def handoff(token: str, request: Request, s: Session = Depends(get_session)) -> Response:
    try:
        pub = s.get(Publication, approval.handoff_publication_id(token))
        if pub is None:
            raise NotFound("publication")
    except AppError as exc:
        return _error_page(request, exc)
    variant = s.get(PostVariant, pub.variant_id)
    post = s.get(Post, variant.post_id)
    return _page(request, "handoff.html", {
        "post": post, "variant": variant, "done": pub.status == "published",
        "video": storage.signed_url(variant.video_key) if variant.video_key else None,
        "brand": agency.brand_for(s, s.get(Workspace, post.workspace_id))})


# Direct upload (videos above the bots' 20 MB download limit) -------------------

@router.get("/up/{token}")
def upload_page(token: str, request: Request) -> Response:
    try:
        uploads.read_token(token)
    except AppError as exc:
        return _error_page(request, exc)
    return _page(request, "upload.html", {"token": token})


@router.post("/up/{token}")
async def upload_submit(token: str, request: Request, file: UploadFile = File(...),
                        s: Session = Depends(get_session)) -> Response:
    try:
        claims = uploads.read_token(token)
        if not (file.content_type or "").startswith("video/"):
            raise AppError("video_required", "Send a video file")
        ws = s.get(Workspace, claims["ws"])
        member = s.get(Membership, claims["member"]) if claims.get("member") else None
        key = storage.new_key(ws.id, "raw", ".mp4")
        await storage.save_upload(file, key)
        post_service.ingest(s, ws, platform="upload", member=member, chat_id=None, msg_id=None,
                            caption_text=claims.get("caption", ""), file_key=key)
    except AppError as exc:
        return _error_page(request, exc)
    return _page(request, "message.html", {"title": t("upload.done_title"), "text": t("upload.done")})


# Signed media ---------------------------------------------------------------

@router.get("/media/{key:path}")
def media(key: str, exp: int = 0, sig: str = "") -> Response:
    if not storage.verify(key, exp, sig):
        return Response(status_code=403)
    path = storage.path_of(key)
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path)


@router.get("/fonts/{name}")
def fonts(name: str) -> Response:
    base = get_settings().brand_fonts_dir.resolve()
    path = (base / name).resolve()
    if base not in path.parents or not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000"})
