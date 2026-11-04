"""Answer sanitizer. Runs before restoration, so restored values can never land inside a URL.

Markdown and HTML images are fetched automatically by most chat clients. An image URL that
carries data is a zero-click exfiltration channel, even if the user never clicks anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from aegis.guard.urls import decoded_views, domain_allowed, host_of
from aegis.vault.vault import PLACEHOLDER_RE

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HTML_IMG = re.compile(r"<img\b[^>]*\bsrc\s*=\s*[\"']?([^\"'\s>]+)[^>]*>", re.IGNORECASE)
_MD_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_BARE_URL = re.compile(r"https?://[^\s<>\"')\]]+(?:\[[A-Z_]+_\d+\][^\s<>\"')]*)*", re.IGNORECASE)
_RAW_DATA = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?:\d[ -]?){12,18}\d")


@dataclass
class SanitizeResult:
    text: str
    removed: list[dict[str, str]] = field(default_factory=list)


def url_carries_data(url: str) -> bool:
    return any(PLACEHOLDER_RE.search(v) or _RAW_DATA.search(v) for v in decoded_views(url))


class OutputSanitizer:
    def clean(self, text: str, allowed_domains: list[str]) -> SanitizeResult:
        removed: list[dict[str, str]] = []

        def verdict(url: str) -> str | None:
            host = host_of(url)
            if url_carries_data(url):
                return "url carries sensitive data or placeholders"
            if not domain_allowed(host, allowed_domains):
                return f"{host or 'unknown host'} is not an allowlisted domain"
            return None

        def image(m: re.Match[str], url_group: int) -> str:
            url = m.group(url_group)
            why = verdict(url)
            if why is None:
                return m.group(0)
            removed.append({"kind": "image", "host": host_of(url) or "", "reason": why})
            return f"[image removed by policy: {why}]"

        text = _MD_IMAGE.sub(lambda m: image(m, 2), text)
        text = _HTML_IMG.sub(lambda m: image(m, 1), text)

        def link(m: re.Match[str]) -> str:
            url = m.group(2)
            if not url_carries_data(url):
                return m.group(0)
            removed.append(
                {"kind": "link", "host": host_of(url) or "", "reason": "url carries sensitive data"}
            )
            return f"{m.group(1)} [link removed by policy]"

        text = _MD_LINK.sub(link, text)

        def bare(m: re.Match[str]) -> str:
            url = m.group(0)
            if not url_carries_data(url):
                return url
            removed.append(
                {"kind": "url", "host": host_of(url) or "", "reason": "url carries sensitive data"}
            )
            return "[url removed by policy]"

        text = _BARE_URL.sub(bare, text)
        return SanitizeResult(text, removed)
