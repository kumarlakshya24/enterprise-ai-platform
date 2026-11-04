"""URL parsing and decoding used to find data smuggled out in URLs."""

from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import unquote_plus, urlsplit

_TOKEN_SPLIT = re.compile(r"[/?&=|#;,:+\s]")
_B64 = re.compile(r"^[A-Za-z0-9+/_-]{8,}={0,2}$")
_HEX = re.compile(r"^(?:[0-9a-fA-F]{2}){8,}$")


def host_of(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return parts.hostname.lower().rstrip(".")


def domain_allowed(host: str | None, allowed: list[str]) -> bool:
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed)


def _printable(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not s:
        return None
    ok = sum(1 for ch in s if ch.isprintable())
    return s if ok / len(s) >= 0.9 else None


def decoded_views(value: str, max_rounds: int = 3) -> list[str]:
    """Return the value plus percent-, base64-, and hex-decoded variants of its pieces."""
    views = [value]
    current = value
    for _ in range(max_rounds):
        nxt = unquote_plus(current)
        if nxt == current:
            break
        views.append(nxt)
        current = nxt
    extra: list[str] = []
    for view in views:
        for tok in _TOKEN_SPLIT.split(view):
            if len(tok) < 8:
                continue
            if _HEX.match(tok):
                s = _printable(bytes.fromhex(tok))
                if s:
                    extra.append(s)
                continue
            if _B64.match(tok):
                padded = tok + "=" * (-len(tok) % 4)
                for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                    try:
                        s = _printable(decoder(padded))
                    except (binascii.Error, ValueError):
                        s = None
                    if s:
                        extra.append(s)
                        break
    return views + extra
