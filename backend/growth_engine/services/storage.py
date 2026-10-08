"""Self-hosted file storage (no third-party storage clouds).

Files live under STORAGE_DIR by key (`<workspace>/<area>/<name>`). A key is
handed out only as a signed, expiring URL: Instagram fetches the video
from it and the handoff page downloads from it.
"""

import hashlib
import hmac
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from ..config import get_settings
from ..errors import AppError

URL_TTL_S = 24 * 3600
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024


def root() -> Path:
    path = get_settings().storage_dir.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_key(workspace_id: str, area: str, suffix: str) -> str:
    return f"{workspace_id}/{area}/{uuid.uuid4().hex}{suffix}"


def path_of(key: str) -> Path:
    base = root()
    path = (base / key).resolve()
    if base not in path.parents:
        raise AppError("storage_key_invalid", "Invalid storage key")
    return path


def save_bytes(key: str, data: bytes) -> str:
    path = path_of(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def read_bytes(key: str) -> bytes:
    return path_of(key).read_bytes()


def _sign(key: str, exp: int) -> str:
    msg = f"{key}:{exp}".encode()
    return hmac.new(get_settings().jwt_secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def signed_url(key: str, ttl_s: int = URL_TTL_S) -> str:
    exp = int(time.time()) + ttl_s
    return f"{get_settings().public_base_url}/media/{quote(key)}?exp={exp}&sig={_sign(key, exp)}"


def verify(key: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(_sign(key, exp), sig)


async def save_upload(upload, key: str) -> str:
    """Stream an uploaded file to disk, refusing anything over 2 GB."""
    path = path_of(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with path.open("wb") as fh:
        while chunk := await upload.read(CHUNK):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                break
            fh.write(chunk)
    if size > MAX_UPLOAD_BYTES:
        path.unlink(missing_ok=True)
        raise AppError("file_too_large", "The video must be under 2 GB")
    return key
