"""Zarinpal v4 (the only payment gateway). Amounts in Toman; the API takes Rial."""

import time

import httpx

from ..config import get_settings


class ZarinpalError(RuntimeError):
    code = "zarinpal_error"


def _base() -> str:
    return "https://sandbox.zarinpal.com" if get_settings().zarinpal_sandbox else "https://payment.zarinpal.com"


def _post(url: str, payload: dict) -> dict:
    last: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(1)
        try:
            resp = httpx.post(url, json=payload, timeout=15)
            if resp.status_code >= 500:
                last = ZarinpalError(f"Zarinpal returned HTTP {resp.status_code}")
                continue
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
    raise ZarinpalError(f"Zarinpal request failed: {last}")


def request_payment(amount_toman: int, description: str, callback_url: str, mobile: str | None = None) -> dict:
    payload = {"merchant_id": get_settings().zarinpal_merchant_id, "amount": amount_toman * 10,
               "description": description, "callback_url": callback_url}
    if mobile:
        payload["metadata"] = {"mobile": mobile}
    data = _post(f"{_base()}/pg/v4/payment/request.json", payload)
    if data.get("errors"):
        raise ZarinpalError(f"Zarinpal refused the request: {data['errors']}")
    authority = data["data"]["authority"]
    return {"authority": authority, "payment_url": f"{_base()}/pg/StartPay/{authority}"}


def verify_payment(amount_toman: int, authority: str) -> dict:
    data = _post(f"{_base()}/pg/v4/payment/verify.json", {
        "merchant_id": get_settings().zarinpal_merchant_id, "amount": amount_toman * 10, "authority": authority})
    if data.get("errors"):
        raise ZarinpalError(f"Zarinpal refused the verification: {data['errors']}")
    result = data["data"]
    # 100 = verified now, 101 = already verified (a repeated callback).
    if result.get("code") not in (100, 101):
        raise ZarinpalError(f"Zarinpal verification code {result.get('code')}")
    return {"ref_id": str(result.get("ref_id")), "code": result.get("code")}
