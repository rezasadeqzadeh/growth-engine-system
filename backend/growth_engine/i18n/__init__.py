"""Persian text for bot messages, SMS and public pages.

Source code stays English; every user-facing sentence lives in fa.json and
is looked up by key (tests/test_i18n.py fails on a key used but missing).
"""

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache
def catalog() -> dict[str, str]:
    return json.loads((_DIR / "fa.json").read_text(encoding="utf-8"))


def t(key: str, **values: object) -> str:
    text = catalog().get(key)
    if text is None:
        raise KeyError(f"Missing i18n key: {key}")
    return text.format(**values) if values else text


_FA_DIGITS = str.maketrans("0123456789", "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9")


def fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


@lru_cache
def patterns() -> dict[str, str]:
    """Persian keywords and regexes the code matches (data/fa_patterns.json)."""
    return json.loads((_DIR.parent / "data" / "fa_patterns.json").read_text(encoding="utf-8"))
