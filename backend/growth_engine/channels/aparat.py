"""Aparat through its `etc/api` endpoints.

login       GET /etc/api/login/luser/<user>/lpass/<sha1(md5(password))>  -> login.ltoken
uploadform  GET /etc/api/uploadform/luser/<user>/ltoken/<ltoken>       -> uploadform.formAction, frm-id
upload      POST multipart to formAction: video, frm-id, data[title], data[category], data[tags], data[descr]
video       GET /etc/api/video/videohash/<uid>                          -> video.visit_cnt
comments    GET /etc/api/commentByVideos/videohash/<uid>/perpage/<n>

The API takes no subtitle file, so the SRT is handed to the admin with the
result (PublicationResult.notes) for upload in the Aparat panel.
Credentials: {"username", "lpass"} where lpass is the sha1(md5()) hash.
"""

import hashlib
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from ..models import Channel
from ..redact import redact
from .base import Capabilities, Comment, Metrics, PublicationResult, PublishError, PublishItem, check_size

BASE = "https://www.aparat.com/etc/api"


def hash_password(password: str) -> str:
    return hashlib.sha1(hashlib.md5(password.encode()).hexdigest().encode()).hexdigest()


class AparatAdapter:
    type = "aparat"

    def capabilities(self) -> Capabilities:
        return Capabilities(auto_publish=True, metrics="full", comments="api", dm=False,
                            max_video_mb=2048, aspects=("16:9",), kinds=("full",))

    def _creds(self, channel: Channel) -> tuple[str, str]:
        c = channel.credentials or {}
        if not c.get("username") or not c.get("lpass"):
            raise PublishError("The Aparat channel has no login", retryable=False)
        return c["username"], c["lpass"]

    async def _get(self, path: str, secrets: list[str]) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(f"{BASE}/{path}")
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PublishError(redact(f"aparat request failed: {exc}", secrets)) from exc

    async def _ltoken(self, channel: Channel) -> str:
        user, lpass = self._creds(channel)
        data = await self._get(f"login/luser/{quote(user)}/lpass/{lpass}", [lpass])
        token = (data.get("login") or {}).get("ltoken")
        if not token:
            raise PublishError("Aparat login was refused", retryable=False)
        return token

    async def publish(self, channel: Channel, item: PublishItem) -> PublicationResult:
        check_size(item, self.capabilities())
        if not item.video:
            raise PublishError("Aparat needs a video", retryable=False)
        user, lpass = self._creds(channel)
        ltoken = await self._ltoken(channel)
        form = (await self._get(f"uploadform/luser/{quote(user)}/ltoken/{ltoken}", [lpass, ltoken])).get("uploadform") or {}
        action, frm_id = form.get("formAction"), form.get("frm-id")
        if not action or not frm_id:
            raise PublishError("Aparat returned no upload form")
        data = {"frm-id": frm_id, "data[title]": item.title[:100], "data[descr]": item.caption,
                "data[category]": str((channel.config or {}).get("category", 22)),
                # Aparat tags are dash-separated, 3 to 5 of them.
                "data[tags]": "-".join(t.replace("-", " ") for t in item.tags[:5]), "data[comment]": "yes"}
        try:
            async with httpx.AsyncClient(timeout=1800) as client:
                with item.video.open("rb") as fh:
                    resp = await client.post(action, data=data, files={"video": (item.video.name, fh, "video/mp4")})
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PublishError(redact(f"aparat upload failed: {exc}", [lpass, ltoken])) from exc
        uid = (body.get("uploadpost") or {}).get("uid")
        if not uid:
            raise PublishError(redact(f"aparat upload rejected: {body}", [lpass, ltoken]))
        notes = ["aparat_srt_manual"] if item.srt else []
        return PublicationResult("published", uid, f"https://www.aparat.com/v/{uid}", notes)

    async def fetch_metrics(self, channel: Channel, external_id: str) -> Metrics:
        video = (await self._get(f"video/videohash/{external_id}", [])).get("video") or {}
        return Metrics(views=_int(video.get("visit_cnt")), likes=_int(video.get("like_cnt")))

    async def fetch_comments(self, channel: Channel, external_id: str) -> list[Comment]:
        rows = (await self._get(f"commentByVideos/videohash/{external_id}/perpage/50", [])).get("commentbyvideos") or []
        out = []
        for row in rows:
            at = datetime.now(timezone.utc)
            out.append(Comment(str(row.get("id")), str(row.get("name") or row.get("username") or ""),
                               str(row.get("body") or ""), at))
        return [c for c in out if c.text]

    async def health(self, channel: Channel) -> None:
        await self._ltoken(channel)


def _int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
