"""Aegis-shaped tool guard.

Verdict vocabulary matches Aegis (``secure-ai-gateway``): ``allow``, ``require_approval``,
``block``. Rule ids use the same ``R-TOOL-...`` style. The offline stub is what the demo
runs. The HTTP adapter fail-closes when the gateway cannot be reached.

This module does not import Aegis. The sibling service is a separate deployable.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

PERSONAL_EMAIL_DOMAINS = frozenset(
    {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"}
)
ALLOWED_EMAIL_DOMAINS = frozenset({"example.com", "acme.example"})
URL_ALLOWLIST = frozenset({"status.acme.example", "hooks.acme.example", "api.acme.example"})


def require_http_url(base_url: str) -> str:
    """Return ``base_url`` without a trailing slash, or raise if it is not http(s).

    ``urllib`` also opens ``file://`` and other schemes; a sibling-service URL that came from the
    environment must not be able to point the adapter at the local filesystem.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"expected an http(s) base URL, got {base_url!r}")
    return base_url.rstrip("/")


@dataclass(frozen=True)
class GuardDecision:
    verdict: str
    rule: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"verdict": self.verdict, "rule": self.rule, "message": self.message}


class ToolGuard(Protocol):
    def evaluate(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        risk: str,
        idempotent: bool,
        approved: bool,
        rationale: str,
    ) -> GuardDecision:
        """Return a single verdict. Block outranks approval, approval outranks allow."""


class OfflineAegisGuard:
    """Deterministic rules. The model is not consulted."""

    def evaluate(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        risk: str,
        idempotent: bool,
        approved: bool,
        rationale: str,
    ) -> GuardDecision:
        if not idempotent:
            return GuardDecision(
                "block",
                "R-TOOL-NOT-IDEMPOTENT",
                f"{tool} has no idempotency key, so Atlas will not run it.",
            )
        if tool == "email.send":
            domain = str(args.get("to", "")).rsplit("@", 1)[-1].lower()
            if domain in PERSONAL_EMAIL_DOMAINS:
                return GuardDecision(
                    "block",
                    "R-TOOL-PERSONAL-DOMAIN",
                    f"Refusing personal mailbox domain {domain}.",
                )
            if domain not in ALLOWED_EMAIL_DOMAINS:
                return GuardDecision(
                    "block",
                    "R-TOOL-DOMAIN-NOT-ALLOWLISTED",
                    f"Email domain {domain} is not on the allowlist.",
                )
        if tool == "http.post":
            host = urlparse(str(args.get("url", ""))).hostname or ""
            if host not in URL_ALLOWLIST:
                extra = ""
                if "ignore previous instructions" in rationale.lower():
                    extra = " The model rationale followed an injected instruction."
                return GuardDecision(
                    "block",
                    "R-TOOL-URL-NOT-ALLOWLISTED",
                    f"Host {host or '(missing)'} is not on the URL allowlist.{extra}",
                )
        if risk == "high" and not approved:
            return GuardDecision(
                "require_approval",
                "R-TOOL-HIGH-RISK",
                f"{tool} is high risk and this run has no approval yet.",
            )
        return GuardDecision("allow", "R-TOOL-ALLOW", "Call is within policy.")


class HttpAegisGuard:
    """POST ``{AEGIS_BASE_URL}/v1/tool-guard/evaluate``. Fail closed on any error."""

    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base_url = require_http_url(base_url)
        self.timeout = timeout

    def evaluate(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        risk: str,
        idempotent: bool,
        approved: bool,
        rationale: str,
    ) -> GuardDecision:
        body = json.dumps(
            {
                "tool": tool,
                "args": args,
                "risk": risk,
                "idempotent": idempotent,
                "approved": approved,
                "rationale": rationale,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - http(s) only, see __init__
            f"{self.base_url}/v1/tool-guard/evaluate",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - http(s) only, see __init__
                data = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return GuardDecision(
                "block",
                "R-AEGIS-UNAVAILABLE",
                "Aegis did not answer. Failing closed.",
            )
        verdict = str(data.get("verdict", "block"))
        if verdict not in {"allow", "block", "require_approval"}:
            verdict = "block"
        return GuardDecision(
            verdict,
            str(data.get("rule") or "R-AEGIS-DECISION"),
            str(data.get("message") or ""),
        )


def build_guard(kind: str, base_url: str) -> ToolGuard:
    if kind == "aegis":
        return HttpAegisGuard(base_url)
    if kind != "offline":
        raise ValueError(f"unknown guard adapter {kind}")
    return OfflineAegisGuard()
