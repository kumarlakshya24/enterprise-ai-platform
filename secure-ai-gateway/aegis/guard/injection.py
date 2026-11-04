"""Prompt-injection detection for untrusted content (tool outputs, documents, wiki pages, web pages).

Weighted, explainable signals combined with a noisy-OR. Not a silver bullet: the tool guard and
taint tracking are what stop the exfiltration; this detector decides when to taint.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Any

from aegis.audit.store import AuditScrubber
from aegis.dlp.normalize import has_zero_width, normalize

_I = re.IGNORECASE
SIGNALS: list[tuple[str, float, re.Pattern[str], str]] = [
    (
        "override_instructions",
        0.6,
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system)\b"
            r"[^.\n]{0,20}\b(instructions?|directions?|rules|prompts?|guidelines|guardrails)\b",
            _I,
        ),
        "tries to override the agent's instructions",
    ),
    (
        "role_hijack",
        0.4,
        re.compile(
            r"(you are now\b|from now on,? you\b|new instructions\s*:|system prompt\s*:|<\|im_start\|>|\[system\]"
            r"|###\s*(system|instruction))",
            _I,
        ),
        "tries to redefine the agent's role",
    ),
    (
        "addressed_to_ai",
        0.35,
        re.compile(
            r"\b(AI|assistant|agent|LLM|chatbot|language model|copilot)\b\s*[:,]?\s*[^.\n]{0,30}"
            r"\b(must|should|need to|are required to|always|now)\b",
            _I,
        ),
        "addresses the AI directly with an imperative",
    ),
    (
        "vocative_command",
        0.35,
        re.compile(
            r"\b(AI|assistant|agent|LLM|chatbot|model|copilot)\b\s*[:,-]\s*(please\s+)?"
            r"(ignore|forward|send|append|include|email|post|render|call|reveal|print|output|disregard|delete"
            r"|exfiltrate|upload|share)\b",
            _I,
        ),
        "gives the AI a direct command",
    ),
    (
        "conceal_from_user",
        0.45,
        re.compile(
            r"\b(do not|don't|never)\s+(tell|inform|mention|reveal|show)\b[^.\n]{0,40}\b(user|human|anyone|them)\b"
            r"|\bwithout (telling|informing) the user\b",
            _I,
        ),
        "asks the agent to hide actions from the user",
    ),
    (
        "exfil_to_url",
        0.55,
        re.compile(
            r"\b(append|add|include|attach|encode|embed|insert|put)\b[^.\n]{0,80}"
            r"\b(url|link|image|query|parameter|webhook|endpoint)\b",
            _I,
        ),
        "asks for data to be placed in a URL, image, or webhook",
    ),
    (
        "exfil_send",
        0.4,
        re.compile(
            r"\b(send|forward|email|post|upload|exfiltrate|transmit)\b[^.\n]{0,60}\b(to|at)\b\s*"
            r"(https?://|[\w.+-]+@[\w-]+\.[\w.]+)",
            _I,
        ),
        "asks for data to be sent to an address or URL",
    ),
    (
        "templated_url",
        0.4,
        re.compile(r"https?://[^\s\"'<>]*(\{[a-z_]+\}|<[a-z_]+>|%7B[a-z_]+%7D|\$\{?[a-z_]+\}?)", _I),
        "contains a URL template waiting to be filled with data",
    ),
    ("markdown_image_external", 0.2, re.compile(r"!\[[^\]]*\]\(https?://", _I), "embeds an external image"),
    (
        "hidden_html_comment",
        0.25,
        re.compile(r"<!--[\s\S]*?\b(ignore|instructions?|assistant|AI|must|append|send)\b[\s\S]*?-->", _I),
        "hides instructions in an HTML comment",
    ),
    (
        "hidden_css",
        0.25,
        re.compile(
            r"(display\s*:\s*none|font-size\s*:\s*0|visibility\s*:\s*hidden|color\s*:\s*(white|#fff\b))", _I
        ),
        "hides text with CSS",
    ),
    (
        "tool_invocation",
        0.3,
        re.compile(
            r"\b(call|use|invoke|run|execute)\s+(the\s+)?\w*\s*(tool|function)\b"
            r"|\b(send_email|render_image|http_get|post_webhook|share_document)\b",
            _I,
        ),
        "tells the agent which tool to call",
    ),
]
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


@dataclass
class InjectionResult:
    score: float
    flagged: bool
    threshold: float
    signals: list[dict[str, Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "flagged": self.flagged,
            "threshold": self.threshold,
            "signals": self.signals,
        }


class InjectionDetector:
    def __init__(self) -> None:
        self._scrub = AuditScrubber()

    def _snippet(self, s: str) -> str:
        cleaned, _ = self._scrub.scrub_text(" ".join(s.split())[:140])
        return cleaned

    def _signals(self, text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid, weight, rx, why in SIGNALS:
            m = rx.search(text)
            if m:
                out.append({"id": sid, "weight": weight, "why": why, "snippet": self._snippet(m.group(0))})
        return out

    def scan(self, content: str, threshold: float = 0.6) -> InjectionResult:
        norm = normalize(content).text  # zero-width and fullwidth tricks do not hide keywords
        signals = self._signals(norm)
        if has_zero_width(content):
            signals.append(
                {
                    "id": "zero_width_text",
                    "weight": 0.3,
                    "why": "contains invisible zero-width characters",
                    "snippet": "",
                }
            )
        for blob in _B64_BLOB.findall(norm)[:10]:
            try:
                decoded = base64.b64decode(blob + "=" * (-len(blob) % 4)).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
            inner = self._signals(decoded)
            if any(
                s["id"] in ("override_instructions", "exfil_to_url", "exfil_send", "role_hijack")
                for s in inner
            ):
                signals.append(
                    {
                        "id": "encoded_instructions",
                        "weight": 0.7,  # decodes to an override or exfil instruction: never benign
                        "why": "base64 text that decodes to injected instructions",
                        "snippet": "",
                    }
                )
                break
        remaining = 1.0
        for s in signals:
            remaining *= 1.0 - s["weight"]
        score = 1.0 - remaining
        return InjectionResult(score, score >= threshold, threshold, signals)
