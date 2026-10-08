"""SMS through sms-webservice.com (V3 Send API), as in app-builder.

When SMS_WEBSERVICE_API_KEY is unset, nothing is sent and development
login uses the fixed code 0000.
"""

import time

import httpx

from ..config import get_settings
from ..i18n import t

API_URL = "https://api.sms-webservice.com/api/V3/Send"
MAX_RETRIES = 2


def is_configured() -> bool:
    return bool(get_settings().sms_webservice_api_key)


def send(recipient: str, text: str) -> bool:
    """True when the gateway accepted the message. Never raises."""
    s = get_settings()
    if not s.sms_webservice_api_key:
        return False
    params = {"ApiKey": s.sms_webservice_api_key, "Text": text, "Sender": s.sms_sender, "Recipients": recipient}
    for attempt in range(1 + MAX_RETRIES):
        if attempt:
            time.sleep(1)
        try:
            resp = httpx.get(API_URL, params=params, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue
        # The body is an integer: positive = sent, zero or negative = error.
        try:
            return int(resp.text.strip()) > 0
        except ValueError:
            return resp.status_code == 200
    return False


def send_otp(recipient: str, code: str) -> bool:
    return send(recipient, t("sms.otp", code=code))
