"""Security helpers for logging and user-facing errors."""

from __future__ import annotations

import re

_MAX_SAFE_TEXT_LENGTH = 300

_SENSITIVE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsess-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(access_token|refresh_token|id_token|authorization_code|"
        r"code_verifier|api_key|client_secret|password|secret)\b"
        r"([\"'\s:=]+)([^\"'\s,}]{6,})"
    ),
]


def redact_sensitive_text(
    value: object, max_length: int = _MAX_SAFE_TEXT_LENGTH
) -> str:
    """Return a short string with common credential-shaped values redacted."""
    text = str(value)

    for pattern in _SENSITIVE_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(r"\1\2[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)

    if len(text) > max_length:
        text = f"{text[:max_length]}..."

    return text
