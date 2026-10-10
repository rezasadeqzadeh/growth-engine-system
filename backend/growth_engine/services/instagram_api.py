"""Instagram API with Instagram Login (graph.instagram.com), as in app-builder.

Business/Creator accounts only. Publishing, comments and insights work
with the official API; receiving DMs does not (the app-builder integration
never got webhook messages), so DMs are moved to the Bale/Telegram bot by
the calls to action instead.
"""

import asyncio
import logging
import re
import time
from urllib.parse import urlencode

import httpx

from ..config import get_settings
from ..redact import redact

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"
GRAPH_V = f"{GRAPH}/v23.0"
SCOPES = ",".join([
    "instagram_business_basic", "instagram_business_manage_comments",
    "instagram_business_content_publish", "instagram_business_manage_insights",
])
_TOKEN_IN_URL = re.compile(r"(access_token=)[^&\"\\ ]+")


class InstagramError(RuntimeError):
    code = "instagram_error"


class InstagramAuthExpired(InstagramError):
    """Graph error 190: the token is dead; the owner must reconnect."""

    code = "instagram_token_expired"


def is_configured() -> bool:
    s = get_settings()
    return bool(s.ig_app_id and s.ig_app_secret and s.ig_redirect_uri)


def authorize_url(state: str) -> str:
    s = get_settings()
    return f"{AUTHORIZE_URL}?" + urlencode({"client_id": s.ig_app_id, "redirect_uri": s.ig_redirect_uri,
                                             "scope": SCOPES, "response_type": "code", "state": state})


async def _request(method: str, url: str, secrets: list[str], **kwargs) -> dict:
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.request(method, url, **kwargs)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
            data = resp.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 2:
                raise InstagramError(redact(_TOKEN_IN_URL.sub(r"\1[secret]", f"Instagram request failed: {exc}"),
                                            secrets)) from exc
            await asyncio.sleep(1 + attempt)
    error = data.get("error") if isinstance(data, dict) else None
    if error:
        message = redact(str(error.get("message", "Instagram API error")), secrets)
        if error.get("code") == 190:
            raise InstagramAuthExpired(message)
        raise InstagramError(message)
    return data


async def exchange_code(code: str) -> dict:
    """Code -> long-lived token (~60 days) and the account id."""
    s = get_settings()
    short = await _request("POST", TOKEN_URL, [s.ig_app_secret], data={
        "client_id": s.ig_app_id, "client_secret": s.ig_app_secret, "grant_type": "authorization_code",
        "redirect_uri": s.ig_redirect_uri, "code": code})
    long = await _request("GET", f"{GRAPH}/access_token", [s.ig_app_secret, short["access_token"]], params={
        "grant_type": "ig_exchange_token", "client_secret": s.ig_app_secret, "access_token": short["access_token"]})
    return {"access_token": long["access_token"], "expires_in": int(long.get("expires_in", 0)),
            "user_id": str(short.get("user_id", ""))}


async def refresh_token(token: str) -> dict:
    return await _request("GET", f"{GRAPH}/refresh_access_token", [token],
                          params={"grant_type": "ig_refresh_token", "access_token": token})


async def profile(token: str) -> dict:
    return await _request("GET", f"{GRAPH_V}/me", [token], params={
        "fields": "user_id,username,account_type,media_count,followers_count", "access_token": token})


# Account totals for a period (Instagram Login API, metric_type=total_value).
ACCOUNT_METRICS = ("reach", "views", "accounts_engaged", "total_interactions", "likes", "comments", "shares",
                   "saves", "follows_and_unfollows", "profile_links_taps")


async def account_insights(token: str, ig_user_id: str, since: int, until: int) -> dict[str, int]:
    """Totals of ACCOUNT_METRICS between two unix times (at most 30 days apart)."""
    data = await _request("GET", f"{GRAPH_V}/{ig_user_id}/insights", [token], params={
        "metric": ",".join(ACCOUNT_METRICS), "period": "day", "metric_type": "total_value",
        "since": since, "until": until, "access_token": token})
    out: dict[str, int] = {}
    for row in data.get("data", []):
        total = (row.get("total_value") or {}).get("value")
        if isinstance(total, (int, float)):
            out[row.get("name", "")] = int(total)
    return out


async def recent_media(token: str, limit: int = 30) -> list[dict]:
    data = await _request("GET", f"{GRAPH_V}/me/media", [token], params={
        "fields": "id,caption,media_type,timestamp,like_count,comments_count,permalink", "limit": limit,
        "access_token": token})
    return data.get("data", [])


async def publish_video(token: str, ig_user_id: str, video_url: str, caption: str, *, story: bool = False,
                        cover_url: str | None = None, poll_s: float = 5, max_wait_s: float = 600) -> dict:
    """Create a container, wait until Instagram has fetched and processed
    the video, then publish it. Returns {id, permalink}."""
    params: dict = {"media_type": "STORIES" if story else "REELS", "video_url": video_url, "access_token": token}
    if not story:
        params.update({"caption": caption, "share_to_feed": "true"})
        if cover_url:
            params["cover_url"] = cover_url
    container = await _request("POST", f"{GRAPH_V}/{ig_user_id}/media", [token], data=params)
    container_id = container["id"]
    waited = 0.0
    while True:
        status = await _request("GET", f"{GRAPH_V}/{container_id}", [token],
                                params={"fields": "status_code,status", "access_token": token})
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Instagram could not process the video: {status.get('status', code)}")
        if waited >= max_wait_s:
            raise InstagramError("Instagram did not finish processing the video in time")
        await asyncio.sleep(poll_s)
        waited += poll_s
    published = await _request("POST", f"{GRAPH_V}/{ig_user_id}/media_publish", [token],
                               data={"creation_id": container_id, "access_token": token})
    media = await _request("GET", f"{GRAPH_V}/{published['id']}", [token],
                           params={"fields": "permalink", "access_token": token})
    return {"id": published["id"], "permalink": media.get("permalink")}


async def insights(token: str, media_id: str) -> dict:
    data = await _request("GET", f"{GRAPH_V}/{media_id}/insights", [token], params={
        "metric": "views,reach,likes,comments,saved,shares", "access_token": token})
    out = {}
    for row in data.get("data", []):
        values = row.get("values") or [{}]
        out[row.get("name")] = row.get("total_value", {}).get("value", values[0].get("value"))
    return out


async def comments(token: str, media_id: str) -> list[dict]:
    data = await _request("GET", f"{GRAPH_V}/{media_id}/comments", [token], params={
        "fields": "id,text,username,timestamp", "access_token": token})
    return data.get("data", [])


# Business Discovery: another business/creator account's public profile and posts.
# Only the Facebook Login API has it, so it runs on the platform's own token
# (META_GRAPH_TOKEN / META_IG_USER_ID), never a customer's.
FB_GRAPH_V = "https://graph.facebook.com/v23.0"
DISCOVERY_MEDIA_FIELDS = ("id,caption,media_type,media_product_type,timestamp,like_count,comments_count,"
                          "permalink,media_url,thumbnail_url")
_last_meta_call = 0.0
_meta_lock = asyncio.Lock()


class DiscoveryNotFound(InstagramError):
    """The page does not exist, is private, or is a personal account."""

    code = "competitor_page_not_found"


def discovery_configured() -> bool:
    s = get_settings()
    return bool(s.meta_graph_token and s.meta_ig_user_id)


async def _throttled(method: str, url: str, secrets: list[str], **kwargs) -> dict:
    """One Meta call at a time, at least META_MIN_INTERVAL_S apart (the token's hourly budget is shared)."""
    global _last_meta_call
    async with _meta_lock:
        wait = get_settings().meta_min_interval_s - (time.monotonic() - _last_meta_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await _request(method, url, secrets, **kwargs)
        finally:
            _last_meta_call = time.monotonic()


async def business_discovery(username: str, *, media_limit: int = 50, after: str | None = None) -> dict:
    """Profile fields plus one page of media: {"profile": {...}, "media": [...], "next": cursor | None}."""
    s = get_settings()
    page = f".after({after})" if after else ""
    fields = (f"business_discovery.username({username}){{id,username,name,biography,website,profile_picture_url,"
              f"followers_count,media_count,media.limit({media_limit}){page}{{{DISCOVERY_MEDIA_FIELDS}}}}}")
    try:
        data = await _throttled("GET", f"{FB_GRAPH_V}/{s.meta_ig_user_id}", [s.meta_graph_token],
                                params={"fields": fields, "access_token": s.meta_graph_token})
    except InstagramAuthExpired:
        raise
    except InstagramError as exc:
        # Graph answers 110/100 "Invalid user id" / "Cannot find User" for unknown, private or personal pages.
        if "cannot find" in str(exc).lower() or "invalid user id" in str(exc).lower():
            raise DiscoveryNotFound(str(exc)) from exc
        raise
    found = data.get("business_discovery") or {}
    media = found.pop("media", None) or {}
    cursors = (media.get("paging") or {}).get("cursors") or {}
    has_next = bool((media.get("paging") or {}).get("next"))
    return {"profile": found, "media": media.get("data") or [], "next": cursors.get("after") if has_next else None}
