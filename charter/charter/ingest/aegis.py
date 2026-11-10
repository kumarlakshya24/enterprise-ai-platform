"""Aegis-shaped audit stubs.

The record fields, event types, routes, and HMAC construction follow Aegis
(`audit_events` plus `hmac(prev_hash + canonical_json(hashed fields))`).
Charter does not import Aegis. Details carry the governance join the control
plane needs: label, data_residency, region, model. Those are not all columns
on Aegis's table; they are the exporter's job. The chain key in this repo is
a published demo key, not Aegis's.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from charter.config import DEMO_AUDIT_KEY

GENESIS = "0" * 64
HASHED = (
    "event_id",
    "ts",
    "tenant_id",
    "user_id",
    "session_id",
    "request_id",
    "event_type",
    "policy_version",
    "route",
    "outcome",
    "details",
)
REQUIRED = ("seq", *HASHED, "prev_hash", "hash")
EXTERNAL_ROUTES = frozenset({"allow", "redact_and_continue"})
SENSITIVE = frozenset({"CONFIDENTIAL", "RESTRICTED"})
EU_REGION = "eu-central-1"

# One planted leak. DLP redacts the card, then the route still leaves the EU.
VIOLATION_REQUEST = "req-leak-01"


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def event_hash(key: bytes, prev_hash: str, record: Mapping[str, Any]) -> str:
    payload = {field: record.get(field) for field in HASHED}
    message = (prev_hash + canonical_json(payload)).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Violation:
    event_id: str
    request_id: str
    ts: str
    label: str
    route: str
    region: str
    model: str
    data_residency: str

    def as_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "request_id": self.request_id,
            "ts": self.ts,
            "label": self.label,
            "route": self.route,
            "region": self.region,
            "model": self.model,
            "data_residency": self.data_residency,
        }


@dataclass(frozen=True)
class AuditSummary:
    events: tuple[dict[str, Any], ...]
    chain_ok: bool
    chain_error: str
    violations: tuple[Violation, ...]
    by_type: dict[str, int]
    by_route: dict[str, int]
    by_outcome: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "event_count": len(self.events),
            "chain_ok": self.chain_ok,
            "chain_error": self.chain_error,
            "head_hash": str(self.events[-1]["hash"]) if self.events else "",
            "violation_count": len(self.violations),
            "violations": [item.as_dict() for item in self.violations],
            "by_type": self.by_type,
            "by_route": self.by_route,
            "by_outcome": self.by_outcome,
        }


def verify_chain(events: list[dict[str, Any]], key: bytes = DEMO_AUDIT_KEY) -> str:
    """Return "" when the chain matches, otherwise the first reason it does not."""
    prev = GENESIS
    seen: set[int] = set()
    for index, record in enumerate(events, start=1):
        missing = [field for field in REQUIRED if field not in record]
        if missing:
            return f"seq {record.get('seq', index)} missing {', '.join(missing)}"
        seq = record["seq"]
        if seq != index or seq in seen:
            return f"sequence broke at {seq}"
        seen.add(seq)
        if record.get("prev_hash") != prev:
            return f"prev_hash mismatch at seq {seq}"
        expect = event_hash(key, prev, record)
        if record.get("hash") != expect:
            return f"hash mismatch at seq {seq}"
        prev = str(record["hash"])
    return ""


def _details(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = record.get("details")
    if isinstance(raw, str):
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _violation(record: Mapping[str, Any]) -> Violation | None:
    if record.get("event_type") != "routing_decision":
        return None
    route = str(record.get("route") or "")
    if route not in EXTERNAL_ROUTES:
        return None
    details = _details(record)
    label = str(details.get("context_label") or "")
    residency = str(details.get("data_residency") or "")
    region = str(details.get("region") or "")
    if label not in SENSITIVE or residency != "EU" or region == EU_REGION:
        return None
    return Violation(
        event_id=str(record.get("event_id")),
        request_id=str(record.get("request_id")),
        ts=str(record.get("ts")),
        label=label,
        route=route,
        region=region,
        model=str(details.get("model") or ""),
        data_residency=residency,
    )


def summarize(events: list[dict[str, Any]], *, key: bytes = DEMO_AUDIT_KEY) -> AuditSummary:
    error = verify_chain(events, key)
    by_type: dict[str, int] = {}
    by_route: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    violations: list[Violation] = []
    for record in events:
        event_type = str(record.get("event_type"))
        by_type[event_type] = by_type.get(event_type, 0) + 1
        route = record.get("route")
        if isinstance(route, str):
            by_route[route] = by_route.get(route, 0) + 1
        outcome = record.get("outcome")
        if isinstance(outcome, str):
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        found = _violation(record)
        if found is not None:
            violations.append(found)
    return AuditSummary(
        events=tuple(events),
        chain_ok=error == "",
        chain_error=error,
        violations=tuple(violations),
        by_type=by_type,
        by_route=by_route,
        by_outcome=by_outcome,
    )


def load_audit(path: Path, *, key: bytes = DEMO_AUDIT_KEY) -> AuditSummary:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            loaded = json.loads(line)
            if isinstance(loaded, dict):
                events.append(loaded)
    return summarize(events, key=key)


def _record(
    *,
    event_id: str,
    ts: str,
    user_id: str,
    session_id: str | None,
    request_id: str | None,
    event_type: str,
    policy_version: str | None,
    route: str | None,
    outcome: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "ts": ts,
        "tenant_id": "acme",
        "user_id": user_id,
        "session_id": session_id,
        "request_id": request_id,
        "event_type": event_type,
        "policy_version": policy_version,
        "route": route,
        "outcome": outcome,
        "details": canonical_json(details),
    }


def _seal(records: list[dict[str, Any]], key: bytes = DEMO_AUDIT_KEY) -> list[dict[str, Any]]:
    prev = GENESIS
    sealed: list[dict[str, Any]] = []
    for seq, record in enumerate(records, start=1):
        body = dict(record)
        body["prev_hash"] = prev
        body["hash"] = event_hash(key, prev, body)
        body["seq"] = seq
        prev = str(body["hash"])
        sealed.append(body)
    return sealed


def build_events() -> list[dict[str, Any]]:
    """Deterministic synthetic log. Same bytes every run."""
    rows: list[dict[str, Any]] = []
    counter = 0

    def add(**kwargs: Any) -> None:
        nonlocal counter
        counter += 1
        rows.append(_record(event_id=f"evt-{counter:04d}", **kwargs))

    chats: list[dict[str, Any]] = [
        {
            "request_id": "req-support-01",
            "ts": "2026-10-22T09:14:00Z",
            "user": "acme/u-support",
            "session": "ses-100",
            "purpose": "customer_support",
            "label": "CONFIDENTIAL",
            "residency": "EU",
            "route": "local_only",
            "rule": "R-ROUTE-LOCAL",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": ["EMAIL"],
            "dlp": "redacted",
            "final": "llm_call",
        },
        {
            "request_id": "req-support-02",
            "ts": "2026-10-23T11:02:00Z",
            "user": "acme/u-support",
            "session": "ses-104",
            "purpose": "customer_support",
            "label": "CONFIDENTIAL",
            "residency": "EU",
            "route": "local_only",
            "rule": "R-ROUTE-LOCAL",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": ["PERSON_NAME"],
            "dlp": "redacted",
            "final": "llm_call",
        },
        {
            "request_id": "req-faq-01",
            "ts": "2026-10-24T08:41:00Z",
            "user": "acme/u-help",
            "session": "ses-110",
            "purpose": "public_faq",
            "label": "PUBLIC",
            "residency": "EU",
            "route": "allow",
            "rule": "R-ROUTE-ALLOW",
            "region": "us-east-1",
            "model": "frontier-us-large",
            "provider": "hosted",
            "entities": [],
            "dlp": "clean",
            "final": "llm_call",
        },
        {
            "request_id": "req-wiki-01",
            "ts": "2026-10-27T15:18:00Z",
            "user": "acme/u-eng",
            "session": "ses-120",
            "purpose": "customer_support",
            "label": "INTERNAL",
            "residency": "EU",
            "route": "redact_and_continue",
            "rule": "R-ROUTE-REDACT",
            "region": "us-east-1",
            "model": "frontier-us-large",
            "provider": "hosted",
            "entities": ["ORG"],
            "dlp": "redacted",
            "final": "llm_call",
        },
        {
            "request_id": "req-block-01",
            "ts": "2026-10-28T10:05:00Z",
            "user": "acme/u-support",
            "session": "ses-130",
            "purpose": "customer_support",
            "label": "RESTRICTED",
            "residency": "EU",
            "route": "block",
            "rule": "R-BLOCK-RESTRICTED",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": ["CREDIT_CARD"],
            "dlp": "redacted",
            "final": "blocked",
        },
        {
            "request_id": VIOLATION_REQUEST,
            "ts": "2026-11-03T16:42:00Z",
            "user": "acme/u-support",
            "session": "ses-188",
            "purpose": "customer_support",
            "label": "RESTRICTED",
            "residency": "EU",
            "route": "allow",
            "rule": "R-ROUTE-ALLOW",
            "region": "us-east-1",
            "model": "frontier-us-large",
            "provider": "hosted",
            "entities": ["CREDIT_CARD"],
            "dlp": "redacted",
            "final": "llm_call",
        },
        {
            "request_id": "req-hold-01",
            "ts": "2026-11-01T13:27:00Z",
            "user": "acme/u-support",
            "session": "ses-160",
            "purpose": "customer_support",
            "label": "CONFIDENTIAL",
            "residency": "EU",
            "route": "require_approval",
            "rule": "R-BULK-APPROVAL",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": ["EMAIL", "PERSON_NAME"],
            "dlp": "redacted",
            "final": "held",
        },
        {
            "request_id": "req-err-01",
            "ts": "2026-11-02T19:04:00Z",
            "user": "acme/u-support",
            "session": "ses-170",
            "purpose": "customer_support",
            "label": "INTERNAL",
            "residency": "EU",
            "route": "local_only",
            "rule": "R-ROUTE-LOCAL",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": [],
            "dlp": "clean",
            "final": "llm_error",
        },
        {
            "request_id": "req-support-03",
            "ts": "2026-11-04T09:12:00Z",
            "user": "acme/u-support",
            "session": "ses-190",
            "purpose": "customer_support",
            "label": "CONFIDENTIAL",
            "residency": "EU",
            "route": "local_only",
            "rule": "R-ROUTE-LOCAL",
            "region": "eu-central-1",
            "model": "atlas-eu-mini",
            "provider": "local",
            "entities": ["PHONE"],
            "dlp": "redacted",
            "final": "llm_call",
        },
    ]

    # Stable order is timestamp, then the id assigned at construction.
    for chat in chats:
        add(
            ts=chat["ts"],
            user_id=chat["user"],
            session_id=chat["session"],
            request_id=chat["request_id"],
            event_type="prompt_received",
            policy_version="acme-default@7",
            route=None,
            outcome=None,
            details={
                "kind": "chat",
                "purpose": chat["purpose"],
                "data_residency": chat["residency"],
            },
        )
        add(
            ts=chat["ts"],
            user_id=chat["user"],
            session_id=chat["session"],
            request_id=chat["request_id"],
            event_type="dlp_redaction",
            policy_version="acme-default@7",
            route=None,
            outcome=chat["dlp"],
            details={"entities": chat["entities"], "context_label": chat["label"]},
        )
        add(
            ts=chat["ts"],
            user_id=chat["user"],
            session_id=chat["session"],
            request_id=chat["request_id"],
            event_type="routing_decision",
            policy_version="acme-default@7",
            route=chat["route"],
            outcome=chat["route"],
            details={
                "route": chat["route"],
                "rule_id": chat["rule"],
                "context_label": chat["label"],
                "effective_label": chat["label"],
                "data_residency": chat["residency"],
                "region": chat["region"],
                "model": chat["model"],
                "provider": chat["provider"],
                "purpose": chat["purpose"],
            },
        )
        if chat["final"] == "blocked":
            add(
                ts=chat["ts"],
                user_id=chat["user"],
                session_id=chat["session"],
                request_id=chat["request_id"],
                event_type="request_blocked",
                policy_version="acme-default@7",
                route=chat["route"],
                outcome="blocked",
                details={"rule_id": chat["rule"]},
            )
        elif chat["final"] == "llm_error":
            add(
                ts=chat["ts"],
                user_id=chat["user"],
                session_id=chat["session"],
                request_id=chat["request_id"],
                event_type="llm_error",
                policy_version="acme-default@7",
                route=chat["route"],
                outcome="error",
                details={"provider": chat["provider"], "error": "local model timed out"},
            )
        elif chat["final"] == "llm_call":
            add(
                ts=chat["ts"],
                user_id=chat["user"],
                session_id=chat["session"],
                request_id=chat["request_id"],
                event_type="llm_call",
                policy_version="acme-default@7",
                route=chat["route"],
                outcome="ok",
                details={
                    "provider": chat["provider"],
                    "location": chat["region"],
                    "model": chat["model"],
                    "region": chat["region"],
                },
            )
    add(
        ts="2026-10-29T07:55:00Z",
        user_id="acme/u-unknown",
        session_id=None,
        request_id=None,
        event_type="auth_failed",
        policy_version=None,
        route=None,
        outcome="denied",
        details={"reason": "bad_token"},
    )
    add(
        ts="2026-10-30T12:11:00Z",
        user_id="acme/u-agent",
        session_id="ses-150",
        request_id="req-tool-01",
        event_type="tool_call",
        policy_version="acme-default@7",
        route="local_only",
        outcome="block",
        details={"tool": "send_email", "guard": {"verdict": "block", "rule": "R-TOOL-EXTERNAL-DOMAIN"}},
    )
    add(
        ts="2026-10-30T12:11:01Z",
        user_id="acme/u-agent",
        session_id="ses-150",
        request_id="req-tool-01",
        event_type="tool_call_blocked",
        policy_version="acme-default@7",
        route="local_only",
        outcome="blocked",
        details={"tool": "send_email", "rules": ["R-TOOL-EXTERNAL-DOMAIN"]},
    )
    rows.sort(key=lambda record: (str(record["ts"]), str(record["event_id"])))
    return _seal(rows)


def serialize(events: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events)


def write_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(build_events()), encoding="utf-8")
