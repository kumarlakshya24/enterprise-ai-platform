"""Request features. Rules and weights, no model call.

The router has to explain a choice in a few milliseconds, so the features are
deterministic patterns. A missed task is a wrong route; the eval set measures
that directly. An LLM judge would generalize further and would also hide the
reason and add its own bill. See ADR 0002.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from switchboard.catalog import estimate_tokens

SENSITIVITY_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

_LEAD: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("summarize", re.compile(r"^\s*(summarize|summarise|sum up|tl;dr|tldr)\b", re.I)),
    ("extract", re.compile(r"^\s*(extract|pull out)\b", re.I)),
    ("math", re.compile(r"^\s*(prove|solve|calculate|integrate|derive)\b", re.I)),
    ("code", re.compile(r"^\s*(refactor|debug|implement|fix|write a function|write a python)\b", re.I)),
)

_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code", re.compile(r"```|\b(traceback|stack trace|refactor|compile error)\b", re.I)),
    ("math", re.compile(r"\b(prove|theorem|integral|derivative|equation|modulo)\b", re.I)),
    ("summarize", re.compile(r"\b(summarize|summarise|tl;dr|tldr|synopsis)\b", re.I)),
    ("extract", re.compile(r"\b(extract the|json schema|key-value)\b", re.I)),
)

_HARD_PHRASES = (
    "edge case",
    "prove",
    "optimize",
    "distributed",
    "formal",
    "concurrent",
    "migration",
    "production",
    "theorem",
    "asymptotic",
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+1[-.\s])?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_REALTIME = re.compile(r"\b(asap|real-time|realtime|right away|low latency)\b", re.I)
_BATCH = re.compile(r"\b(batch|overnight|whenever)\b", re.I)
_RESTRICTED = re.compile(r"\b(restricted|top secret|secret key)\b", re.I)
_CONFIDENTIAL = re.compile(r"\b(confidential|attorney-client|privileged)\b", re.I)
_INTERNAL = re.compile(r"\binternal only\b", re.I)


@dataclass
class Features:
    task: str
    complexity: float
    tokens_in: int
    latency_sensitivity: str
    sensitivity: str
    pii_types: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    def public(self, tokens_out: int) -> dict[str, object]:
        return {
            "task": self.task,
            "complexity": self.complexity,
            "tokens_in": self.tokens_in,
            "tokens_out": tokens_out,
            "latency_sensitivity": self.latency_sensitivity,
            "sensitivity": self.sensitivity,
            "pii_types": list(self.pii_types),
            "signals": list(self.signals),
        }


def luhn_ok(raw: str) -> bool:
    digits = [int(ch) for ch in raw if ch.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def detect_task(text: str) -> tuple[str, str]:
    for task, pattern in _LEAD:
        if pattern.search(text):
            return task, f"lead:{task}"
    for task, pattern in _KEYWORDS:
        if pattern.search(text):
            return task, f"keyword:{task}"
    return "chat", "default:chat"


def estimate_complexity(text: str) -> tuple[float, list[str]]:
    signals: list[str] = []
    tokens = estimate_tokens(text)
    length = min(0.50, max(0.0, (tokens - 40) / 600))
    if length > 0:
        signals.append(f"length:{tokens}tok")
    lowered = text.lower()
    hits = [phrase for phrase in _HARD_PHRASES if phrase in lowered]
    hard = min(0.36, 0.12 * len(hits))
    if hits:
        signals.append("hard:" + ",".join(hits))
    struct = 0.0
    if "```" in text:
        struct += 0.12
        signals.append("code-fence")
    if lowered.count("step") >= 2:
        struct += 0.08
        signals.append("multi-step")
    value = min(0.97, max(0.05, length + hard + struct))
    return round(value, 4), signals


def detect_latency_sensitivity(text: str) -> str:
    if _REALTIME.search(text):
        return "high"
    if _BATCH.search(text):
        return "low"
    return "normal"


def detect_sensitivity(text: str) -> tuple[str, list[str]]:
    pii: list[str] = []
    level = "public"
    if _EMAIL.search(text):
        pii.append("email")
        level = _higher(level, "internal")
    if _PHONE.search(text):
        pii.append("phone")
        level = _higher(level, "internal")
    if any(luhn_ok(match.group(0)) for match in _CARD.finditer(text)):
        pii.append("card")
        level = _higher(level, "confidential")
    if _SSN.search(text):
        pii.append("ssn")
        level = _higher(level, "restricted")
    if _INTERNAL.search(text):
        level = _higher(level, "internal")
    if _CONFIDENTIAL.search(text):
        level = _higher(level, "confidential")
    if _RESTRICTED.search(text):
        level = _higher(level, "restricted")
    return level, pii


def _higher(left: str, right: str) -> str:
    return left if SENSITIVITY_RANK[left] >= SENSITIVITY_RANK[right] else right


def redact_preview(text: str, limit: int = 96) -> str:
    redacted = _EMAIL.sub("[email]", text)
    redacted = _SSN.sub("[ssn]", redacted)
    redacted = _PHONE.sub("[phone]", redacted)

    def _card(match: re.Match[str]) -> str:
        return "[card]" if luhn_ok(match.group(0)) else match.group(0)

    redacted = _CARD.sub(_card, redacted)
    flat = " ".join(redacted.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def classify(text: str) -> Features:
    task, task_signal = detect_task(text)
    complexity, complexity_signals = estimate_complexity(text)
    sensitivity, pii = detect_sensitivity(text)
    signals = [task_signal, *complexity_signals]
    if pii:
        signals.append("pii:" + ",".join(pii))
    signals.append(f"sensitivity:{sensitivity}")
    latency = detect_latency_sensitivity(text)
    if latency != "normal":
        signals.append(f"latency:{latency}")
    return Features(
        task=task,
        complexity=complexity,
        tokens_in=estimate_tokens(text),
        latency_sensitivity=latency,
        sensitivity=sensitivity,
        pii_types=pii,
        signals=signals,
    )
