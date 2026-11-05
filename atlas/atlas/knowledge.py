"""Lumen-shaped knowledge port.

The offline adapter is a tiny recorded corpus. The HTTP adapter speaks Lumen's
``POST /ask`` contract (``X-User-Id``, ``question`` → ``answer``, ``citations``, ``refused``).
A refusal uses Lumen's sentence: "Not found in the provided documents."
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from atlas.guard import require_http_url

REFUSAL = "Not found in the provided documents."

_ARTICLES: dict[str, dict[str, Any]] = {
    "refund": {
        "answer": (
            "Refunds up to $200 are allowed for duplicate charges and defective goods. "
            "Amounts above $25 require human approval before the ledger is posted. "
            "Shipping is not refunded. Funds settle in 3 business days."
        ),
        "citations": [
            {"doc_id": "POL-REF-014", "title": "Customer refund policy", "version": "3.2"},
        ],
        "refused": False,
    },
    "vendor": {
        "answer": (
            "Vendor onboarding requires a W-9, a security review, and payment to a corporate "
            "account. Bank details must stay on the corporate provisioning tool. "
            "Do not send them to a personal webhook."
        ),
        "citations": [
            {"doc_id": "POL-VEN-003", "title": "Vendor onboarding", "version": "1.4"},
        ],
        "refused": False,
    },
    "incident": {
        "answer": (
            "SEV1 incidents require an on-call page and a status page update within 10 minutes. "
            "A postmortem is published after the bridge closes."
        ),
        "citations": [
            {"doc_id": "POL-INC-009", "title": "SEV1 incident response", "version": "2.0"},
        ],
        "refused": False,
    },
}


class Knowledge(Protocol):
    def ask(self, question: str, *, principal: str) -> dict[str, Any]:
        """Return ``{answer, citations, refused}``."""


class OfflineLumen:
    """Keyword router over a recorded corpus. Deterministic, no embeddings."""

    def ask(self, question: str, *, principal: str) -> dict[str, Any]:
        del principal
        text = question.lower()
        if "bonus" in text or "executive compensation" in text:
            return _refuse()
        if "vendor" in text:
            return dict(_ARTICLES["vendor"])
        if "incident" in text or "sev1" in text or "sev-1" in text:
            return dict(_ARTICLES["incident"])
        if "refund" in text:
            return dict(_ARTICLES["refund"])
        return _refuse()


class HttpLumen:
    """Client for the sibling Lumen service (``rag-knowledge-assistant``).

    Fail closed: a transport error becomes a refusal, and the caller must not invent policy.
    """

    def __init__(self, base_url: str, user_id: str, timeout: float = 5.0) -> None:
        self.base_url = require_http_url(base_url)
        self.user_id = user_id
        self.timeout = timeout

    def ask(self, question: str, *, principal: str) -> dict[str, Any]:
        body = json.dumps({"question": question}).encode()
        request = urllib.request.Request(  # noqa: S310 - http(s) only, see __init__
            f"{self.base_url}/ask",
            data=body,
            headers={"content-type": "application/json", "x-user-id": principal or self.user_id},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - http(s) only, see __init__
                data = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return _refuse()
        return {
            "answer": data.get("answer") or REFUSAL,
            "citations": list(data.get("citations") or []),
            "refused": bool(data.get("refused", False)),
        }


def _refuse() -> dict[str, Any]:
    return {"answer": REFUSAL, "citations": [], "refused": True}


def build_knowledge(kind: str, base_url: str, user_id: str) -> Knowledge:
    if kind == "lumen":
        return HttpLumen(base_url, user_id)
    if kind != "offline":
        raise ValueError(f"unknown knowledge adapter {kind}")
    return OfflineLumen()
