"""Remove credentials from any text before it is logged, stored or shown.

Channel credentials (bot tokens, Instagram access tokens, Aparat tokens)
travel inside URLs and provider error bodies. Every error that leaves an
adapter goes through `redact` so none of them reaches the panel, a bot
message or a stored job error.
"""

import re

_PATTERNS = [
    # Telegram/Bale bot tokens: 123456:AA..., also inside /bot<token>/ paths
    (re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}"), "[token]"),
    (re.compile(r"(access_token=|ltoken/|token=|ApiKey=|api_key=)[^&\s\"'/]+", re.I), r"\1[secret]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._-]+", re.I), r"\1[secret]"),
    (re.compile(r"(eitaayar\.ir/api/)[^/\s]+"), r"\1[token]"),
    (re.compile(r"(botapi\.rubika\.ir/v3/)[^/\s]+"), r"\1[token]"),
]


def redact(text: object, secrets: list[str] | tuple[str, ...] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "[secret]")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out
