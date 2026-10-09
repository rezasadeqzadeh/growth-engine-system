"""Phone + one-time-code sign in (same mechanics as app-builder's user_auth).

A send with a name is a sign-up; a bare phone is a sign-in, refused with
`account_not_found` when no account exists so the panel can offer sign-up.
"""

import re
import secrets
from datetime import timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db
from ..config import get_settings
from ..errors import AppError
from ..models import OtpCode, User
from . import sms

PHONE_RE = re.compile(r"^09[0-9]{9}$")
# Persian (U+06F0..) and Arabic-Indic (U+0660..) digits, as phone keyboards type them.
_DIGITS = str.maketrans({**{chr(0x06F0 + i): str(i) for i in range(10)}, **{chr(0x0660 + i): str(i) for i in range(10)}})


def ascii_digits(value: str) -> str:
    return value.translate(_DIGITS).strip()


LOCAL_OTP = "0000"
OTP_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)


def _check_phone(phone: str) -> None:
    if not PHONE_RE.match(phone):
        raise AppError("phone_invalid", "Phone must match 09xxxxxxxxx")


def send_otp(s: Session, phone: str, first_name: str | None = None, last_name: str | None = None) -> dict:
    phone = ascii_digits(phone)
    _check_phone(phone)
    previous = s.get(OtpCode, phone)
    if previous and previous.expires_at - OTP_TTL > db.utcnow() - RESEND_AFTER:
        raise AppError("otp_too_soon", "Wait a minute before asking for another code", 429)
    if sms.is_configured():
        code = f"{secrets.randbelow(100000):05d}"
        if not sms.send_otp(phone, code):
            raise AppError("sms_failed", "Could not deliver the SMS code", 502)
        via_sms = True
    elif get_settings().is_development:
        code, via_sms = LOCAL_OTP, False
    else:
        raise AppError("sms_not_configured", "SMS gateway is not configured", 500)
    row = previous or OtpCode(phone=phone)
    row.code, row.expires_at, row.attempts = code, db.utcnow() + OTP_TTL, 0
    row.pending_first_name, row.pending_last_name = first_name, last_name
    s.add(row)
    return {"sent": True, "via_sms": via_sms}


def verify_otp(s: Session, phone: str, code: str) -> dict:
    phone, code = ascii_digits(phone), ascii_digits(code)
    _check_phone(phone)
    row = s.get(OtpCode, phone)
    if row is None:
        raise AppError("otp_invalid", "Verification code is incorrect", 401)
    if row.attempts >= MAX_ATTEMPTS:
        raise AppError("otp_locked", "Too many wrong codes; request a new one", 429)
    # Bytes: compare_digest refuses str with non-ASCII characters (it raised TypeError -> 500).
    if not secrets.compare_digest(row.code.encode(), code.encode()):
        row.attempts += 1
        s.commit()
        raise AppError("otp_invalid", "Verification code is incorrect", 401)
    if row.expires_at < db.utcnow():
        raise AppError("otp_expired", "Verification code has expired", 401)

    user = s.scalar(select(User).where(User.phone == phone))
    if user is None:
        if not (row.pending_first_name or row.pending_last_name):
            raise AppError("account_not_found", "No account for this phone; sign up first", 404)
        user = User(phone=phone, first_name=row.pending_first_name, last_name=row.pending_last_name)
        s.add(user)
        s.flush()
    s.delete(row)
    return {"token": issue_token(user), "user": user_out(user)}


def issue_token(user: User) -> str:
    s = get_settings()
    claims = {"scope": "user", "user_id": user.id, "exp": db.utcnow() + timedelta(days=s.token_ttl_days)}
    return jwt.encode(claims, s.jwt_secret, algorithm="HS256")


def user_from_token(s: Session, token: str) -> User:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError("token_invalid", "Token is invalid or expired", 401) from exc
    if claims.get("scope") != "user":
        raise AppError("token_wrong_scope", "Not a user session token", 401)
    user = s.get(User, claims.get("user_id", ""))
    if user is None:
        raise AppError("user_not_found", "User no longer exists", 401)
    return user


def is_superadmin(user: User) -> bool:
    return user.role == "superadmin" or user.phone in get_settings().superadmins


def user_out(user: User) -> dict:
    return {"id": user.id, "phone": user.phone, "first_name": user.first_name,
            "last_name": user.last_name, "superadmin": is_superadmin(user)}
