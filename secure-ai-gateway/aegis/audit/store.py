"""Append-only, HMAC hash-chained, redacted audit log."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert, select, update

from aegis.db import GENESIS_HASH, audit_events, audit_head
from aegis.dlp.base import Detector
from aegis.dlp.regex_detectors import (
    CreditCardDetector,
    EmailDetector,
    PhoneDetector,
    SecretDetector,
    SSNDetector,
)

_HASHED_FIELDS = (
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


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class AuditScrubber:
    """Last line of defense: mask anything that still looks like PII or a secret."""

    _SKIP_KEYS = frozenset(
        {"event_id", "hash", "prev_hash", "fingerprint", "policy_version", "approval_id", "run_id"}
    )

    def __init__(self) -> None:
        self._detectors: list[Detector] = [
            EmailDetector(),
            CreditCardDetector(),
            SSNDetector(),
            PhoneDetector(),
            SecretDetector(),
        ]
        self.hits = 0

    def scrub_text(self, s: str) -> tuple[str, int]:
        spans: list[tuple[int, int, str]] = []
        for d in self._detectors:
            for f in d.detect(s):
                if f.confidence >= 0.6:
                    spans.append((f.start, f.end, f.entity_type.value))
        if not spans:
            return s, 0
        spans.sort()
        merged: list[tuple[int, int, str]] = []
        for st, en, ty in spans:
            if merged and st < merged[-1][1]:
                if en > merged[-1][1]:
                    merged[-1] = (merged[-1][0], en, merged[-1][2])
                continue
            merged.append((st, en, ty))
        out = s
        for st, en, ty in reversed(merged):
            out = out[:st] + f"[SCRUBBED:{ty}]" + out[en:]
        return out, len(merged)

    def scrub(self, obj: Any, key: str = "") -> tuple[Any, int]:
        if isinstance(obj, str):
            if key in self._SKIP_KEYS or not re.search(
                r"[@\d]|key|token|pass|secret|BEGIN", obj, re.IGNORECASE
            ):
                return obj, 0
            return self.scrub_text(obj)
        if isinstance(obj, dict):
            total = 0
            out_d: dict[str, Any] = {}
            for k, v in obj.items():
                out_d[k], n = self.scrub(v, str(k))
                total += n
            return out_d, total
        if isinstance(obj, list | tuple):
            total = 0
            out_l: list[Any] = []
            for v in obj:
                sv, n = self.scrub(v, key)
                out_l.append(sv)
                total += n
            return out_l, total
        return obj, 0


class AuditWriteError(RuntimeError):
    pass


class AuditStore:
    def __init__(self, engine: Engine, hmac_key: bytes, scrubber: AuditScrubber | None = None) -> None:
        self.engine = engine
        self._key = hmac_key
        self.scrubber = scrubber or AuditScrubber()
        self._lock = threading.Lock()

    def _hash(self, prev_hash: str, record: dict[str, Any]) -> str:
        msg = (prev_hash + canonical_json({k: record.get(k) for k in _HASHED_FIELDS})).encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def fingerprint(self, content: str) -> str:
        """Keyed fingerprint: proves later that a given text was sent, without storing it."""
        return hmac.new(self._key, b"content\x1f" + content.encode(), hashlib.sha256).hexdigest()[:24]

    def append(
        self,
        event_type: str,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str | None = None,
        request_id: str | None = None,
        policy_version: str | None = None,
        route: str | None = None,
        outcome: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scrubbed, hits = self.scrubber.scrub(details or {})
        if hits:
            self.scrubber.hits += hits
            scrubbed["_scrubbed"] = hits
        record: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "ts": datetime.now(UTC).isoformat(timespec="microseconds"),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "request_id": request_id,
            "event_type": event_type,
            "policy_version": policy_version,
            "route": route,
            "outcome": outcome,
            "details": canonical_json(scrubbed),
        }
        try:
            with self._lock, self.engine.begin() as conn:
                head = conn.execute(select(audit_head).where(audit_head.c.id == 1).with_for_update()).first()
                prev = head.hash if head else GENESIS_HASH
                record["prev_hash"] = prev
                record["hash"] = self._hash(prev, record)
                result = conn.execute(insert(audit_events).values(**record))
                pk = result.inserted_primary_key
                seq = int(pk[0]) if pk is not None else 0
                conn.execute(
                    update(audit_head).where(audit_head.c.id == 1).values(seq=seq, hash=record["hash"])
                )
        except Exception as exc:
            raise AuditWriteError("audit write failed") from exc
        record["seq"] = seq
        return self._public(record)

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["details"] = (
            json.loads(out["details"]) if isinstance(out.get("details"), str) else out.get("details")
        )
        return out

    def query(
        self,
        tenant_id: str,
        *,
        user_id: str | None = None,
        event_type: str | None = None,
        session_id: str | None = None,
        after_seq: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        q = select(audit_events).where(audit_events.c.tenant_id == tenant_id)
        if user_id:
            q = q.where(audit_events.c.user_id == user_id)
        if event_type:
            q = q.where(audit_events.c.event_type == event_type)
        if session_id:
            q = q.where(audit_events.c.session_id == session_id)
        if after_seq is not None:
            q = q.where(audit_events.c.seq > after_seq)
        q = q.order_by(audit_events.c.seq.desc()).limit(min(max(limit, 1), 1000))
        with self.engine.connect() as conn:
            return [self._public(dict(r._mapping)) for r in conn.execute(q)]

    def verify(self) -> dict[str, Any]:
        """Recompute the whole chain. Detects edits, deletions, insertions, and reordering."""
        prev = GENESIS_HASH
        checked = 0
        last_seq = 0
        with self.engine.connect() as conn:
            for r in conn.execute(select(audit_events).order_by(audit_events.c.seq)):
                row = dict(r._mapping)
                if row["prev_hash"] != prev or self._hash(prev, row) != row["hash"]:
                    return {
                        "ok": False,
                        "checked": checked,
                        "first_bad_seq": row["seq"],
                        "reason": "hash mismatch",
                    }
                prev = row["hash"]
                last_seq = row["seq"]
                checked += 1
            head = conn.execute(select(audit_head).where(audit_head.c.id == 1)).first()
        if head is not None and (head.hash != prev or head.seq != last_seq):
            return {
                "ok": False,
                "checked": checked,
                "first_bad_seq": last_seq,
                "reason": "head does not match tail",
            }
        return {"ok": True, "checked": checked, "head_seq": last_seq, "head_hash": prev}

    def count(self) -> int:
        with self.engine.connect() as conn:
            head = conn.execute(select(audit_head.c.seq).where(audit_head.c.id == 1)).scalar()
        return int(head or 0)
