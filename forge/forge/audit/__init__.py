"""Append-only HMAC-SHA256 JSONL audit log."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge.audit.redact import scrub

GENESIS = "0" * 64


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(key: bytes, body: dict[str, Any]) -> str:
    return hmac.new(key, canonical(body).encode("utf-8"), hashlib.sha256).hexdigest()


class AuditLog:
    def __init__(self, path: Path, key: bytes) -> None:
        self.path = path
        self._key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def append(
        self,
        event_type: str,
        *,
        actor: str,
        tool: str,
        outcome: str,
        rule: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        scrubbed = scrub(detail)
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            lines = [line for line in handle.read().splitlines() if line.strip()]
            if lines:
                last = json.loads(lines[-1])
                seq = int(last["seq"]) + 1
                prev = str(last["hash"])
            else:
                seq = 1
                prev = GENESIS
            body: dict[str, Any] = {
                "seq": seq,
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "event_type": event_type,
                "actor": actor,
                "tool": tool,
                "outcome": outcome,
                "rule": rule,
                "detail": scrubbed,
                "prev_hash": prev,
            }
            body["hash"] = chain_hash(self._key, body)
            handle.seek(0, 2)
            handle.write(canonical(body) + "\n")
            handle.flush()
        return body

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        text = self.path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def verify(self) -> dict[str, Any]:
        prev = GENESIS
        count = 0
        for index, record in enumerate(self.records(), start=1):
            count = index
            if record.get("seq") != index:
                return {"ok": False, "broken_seq": index, "reason": "sequence", "events": count}
            if record.get("prev_hash") != prev:
                return {"ok": False, "broken_seq": index, "reason": "prev_hash", "events": count}
            body = {key: value for key, value in record.items() if key != "hash"}
            expected = chain_hash(self._key, body)
            if not hmac.compare_digest(expected, str(record.get("hash", ""))):
                return {"ok": False, "broken_seq": index, "reason": "hash", "events": count}
            prev = str(record["hash"])
        return {"ok": True, "events": count, "head": prev, "broken_seq": None}
