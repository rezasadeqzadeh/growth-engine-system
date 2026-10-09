"""Persian and Arabic-Indic digits -> ASCII, for fields that carry numbers or codes.

Phone keyboards in Iran type ۰۹۱۲… or ٠٩١٢…; phones, sign-in codes, coupon
codes, page ids and slugs are matched and validated as ASCII. Free text
(captions, replies, names) is left as written.
"""

from typing import Annotated

from pydantic import BeforeValidator

_DIGITS = str.maketrans({**{chr(0x06F0 + i): str(i) for i in range(10)},
                         **{chr(0x0660 + i): str(i) for i in range(10)}})


def ascii_digits(value: str) -> str:
    return value.translate(_DIGITS).strip()


def _normalize(value: object) -> object:
    return ascii_digits(value) if isinstance(value, str) else value


# A request field whose digits are converted before validation.
DigitStr = Annotated[str, BeforeValidator(_normalize)]
