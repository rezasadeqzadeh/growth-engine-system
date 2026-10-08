"""Direct upload links: for videos larger than a bot may download (20 MB)."""

import time

import jwt

from ..config import get_settings
from ..errors import AppError

UPLOAD_TTL_S = 24 * 3600


def upload_token(workspace_id: str, member_id: str | None, caption: str) -> str:
    return jwt.encode({"purpose": "upload", "ws": workspace_id, "member": member_id, "caption": caption[:1000],
                       "exp": int(time.time()) + UPLOAD_TTL_S}, get_settings().jwt_secret, algorithm="HS256")


def upload_url(workspace_id: str, member_id: str | None, caption: str) -> str:
    return f"{get_settings().public_base_url}/up/{upload_token(workspace_id, member_id, caption)}"


def read_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError("upload_link_invalid", "This upload link has expired", 404) from exc
    if claims.get("purpose") != "upload":
        raise AppError("upload_link_invalid", "This upload link has expired", 404)
    return claims
