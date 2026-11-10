"""Aegis-shaped redaction. Raw identifiers do not enter a vector.

The in-process redactor is the offline stand-in. Aegis itself tokenizes on
`/chat` and does not expose `POST /v1/redact`. If `CONDUIT_AEGIS_URL` is set,
the HTTP adapter calls that route and quarantines the event on any failure.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol

from conduit.errors import RedactorError
from conduit.models import Finding, RedactionResult, Subject

_UNAVAILABLE = "[[REDACTOR_UNAVAILABLE]]"
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")

# kind, priority. Person tokens outrank a generic email so the subject link survives.
_KIND_PRIORITY = {"person": 100, "card": 90, "ssn": 80, "email": 70, "phone": 60}


class Redactor(Protocol):
    def redact(self, text: str, subjects: tuple[Subject, ...]) -> RedactionResult: ...


def _luhn_ok(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for index, char in enumerate(reverse):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _spans(text: str, subjects: tuple[Subject, ...]) -> list[tuple[int, int, int, str, str]]:
    found: list[tuple[int, int, int, str, str]] = []
    for subject in subjects:
        token = f"[PERSON:{subject.id}]"
        name = re.compile(re.escape(subject.name), re.IGNORECASE)
        for match in name.finditer(text):
            found.append((match.start(), match.end(), _KIND_PRIORITY["person"], "person", token))
        email = re.compile(re.escape(subject.email), re.IGNORECASE)
        for match in email.finditer(text):
            found.append((match.start(), match.end(), _KIND_PRIORITY["person"], "person", token))
    for match in _CARD.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            found.append((match.start(), match.end(), _KIND_PRIORITY["card"], "card", "[CARD]"))
    for match in _SSN.finditer(text):
        found.append((match.start(), match.end(), _KIND_PRIORITY["ssn"], "ssn", "[SSN]"))
    for match in _EMAIL.finditer(text):
        found.append((match.start(), match.end(), _KIND_PRIORITY["email"], "email", "[EMAIL]"))
    for match in _PHONE.finditer(text):
        found.append((match.start(), match.end(), _KIND_PRIORITY["phone"], "phone", "[PHONE]"))
    return found


def _resolve(spans: list[tuple[int, int, int, str, str]]) -> list[tuple[int, int, int, str, str]]:
    ordered = sorted(spans, key=lambda span: (-span[2], span[0], -(span[1] - span[0])))
    chosen: list[tuple[int, int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for span in ordered:
        start, end = span[0], span[1]
        if any(not (end <= left or start >= right) for left, right in occupied):
            continue
        chosen.append(span)
        occupied.append((start, end))
    chosen.sort(key=lambda span: span[0])
    return chosen


def apply_spans(text: str, spans: list[tuple[int, int, int, str, str]]) -> RedactionResult:
    chosen = _resolve(spans)
    pieces: list[str] = []
    findings: list[Finding] = []
    cursor = 0
    for start, end, _priority, kind, replacement in chosen:
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        findings.append(Finding(kind, replacement))
        cursor = end
    pieces.append(text[cursor:])
    return RedactionResult("".join(pieces), tuple(findings))


class InProcessRedactor:
    """Deterministic stand-in for an Aegis redact call."""

    def redact(self, text: str, subjects: tuple[Subject, ...]) -> RedactionResult:
        if _UNAVAILABLE in text:
            raise RedactorError("redactor unavailable")
        return apply_spans(text, _spans(text, subjects))


def scrub_body(text: str, subject: Subject, declared: set[str], subjects: tuple[Subject, ...]) -> str:
    """Remove one subject from a stored log body.

    An event declared to be only about forgotten subjects is replaced wholesale.
    A mixed event loses the paragraphs that mention the subject, then any
    leftover name or email. Future generations replay this text, so the scrub
    is what stops a rebuild from re-embedding the person.
    """
    if declared and declared <= {subject.id}:
        return "[erased]"
    redactor = InProcessRedactor()
    paragraphs = re.split(r"(\n\s*\n)", text)
    rewritten: list[str] = []
    for part in paragraphs:
        if part.strip() == "" or part.isspace() or part.startswith("\n"):
            rewritten.append(part)
            continue
        try:
            redacted = redactor.redact(part, subjects).text
        except RedactorError:
            redacted = part
        mentions = (
            f"[PERSON:{subject.id}]" in redacted
            or subject.name.lower() in part.lower()
            or subject.email.lower() in part.lower()
        )
        rewritten.append("[erased]" if mentions else part)
    body = "".join(rewritten)
    body = re.compile(re.escape(subject.name), re.IGNORECASE).sub("[erased]", body)
    body = re.compile(re.escape(subject.email), re.IGNORECASE).sub("[erased]", body)
    return body


class HttpRedactor:
    """POST `{base}/v1/redact`. Any error fails closed."""

    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self._url = base_url.rstrip("/") + "/v1/redact"
        self._timeout = timeout

    def redact(self, text: str, subjects: tuple[Subject, ...]) -> RedactionResult:
        payload = {
            "text": text,
            "subjects": [
                {"id": subject.id, "name": subject.name, "email": subject.email} for subject in subjects
            ],
        }
        raw = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310
            self._url,
            data=raw,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise RedactorError(f"aegis redact failed: {exc}") from exc
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise RedactorError("aegis redact returned an unexpected body")
        findings_raw = body.get("findings") or []
        findings: list[Finding] = []
        if isinstance(findings_raw, list):
            for item in findings_raw:
                if isinstance(item, dict) and isinstance(item.get("kind"), str):
                    replacement = item.get("replacement")
                    findings.append(
                        Finding(str(item["kind"]), replacement if isinstance(replacement, str) else "")
                    )
        return RedactionResult(str(body["text"]), tuple(findings))


def build_redactor(aegis_url: str | None = None) -> Redactor:
    if aegis_url:
        return HttpRedactor(aegis_url)
    return InProcessRedactor()
