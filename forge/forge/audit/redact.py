"""Redact values before they are written to the audit log."""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DIGITS = re.compile(r"\d{13,}")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*\S+")


def scrub_text(value: str) -> str:
    value = _SECRET.sub(r"\1=[redacted]", value)
    value = _EMAIL.sub("[redacted-email]", value)
    value = _DIGITS.sub("[redacted-number]", value)
    return value


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {str(key): scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def preview(value: str, limit: int = 160) -> str:
    cleaned = scrub_text(value).replace("\n", "\\n")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."
