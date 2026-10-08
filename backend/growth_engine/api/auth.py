from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import otp
from ..auth.deps import current_user
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SendIn(BaseModel):
    phone: str
    first_name: str | None = None
    last_name: str | None = None


class VerifyIn(BaseModel):
    phone: str
    code: str


@router.post("/otp/send")
def send(body: SendIn, s: Session = Depends(get_session)) -> dict:
    return otp.send_otp(s, body.phone, body.first_name, body.last_name)


@router.post("/otp/verify")
def verify(body: VerifyIn, s: Session = Depends(get_session)) -> dict:
    return otp.verify_otp(s, body.phone, body.code)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return otp.user_out(user)
