from __future__ import annotations

import json
from pathlib import Path

from forge.audit import AuditLog
from forge.audit.redact import scrub_text


def test_scrub_email_and_long_number() -> None:
    text = scrub_text("mail alex@example.com card 4111111111111111")
    assert "alex@example.com" not in text
    assert "4111111111111111" not in text
    assert "[redacted-email]" in text
    assert "[redacted-number]" in text


def test_chain_verifies_and_detects_tamper(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", b"k")
    log.append("tool_decision", actor="t", tool="python", outcome="allow", rule="R-ALLOW", detail={"n": 1})
    log.append(
        "tool_decision",
        actor="t",
        tool="python",
        outcome="deny",
        rule="R-IMPORT-HARD-DENY",
        detail={"code_preview": "import os user@example.com"},
    )
    assert log.verify()["ok"] is True
    stored = log.path.read_text(encoding="utf-8")
    assert "user@example.com" not in stored
    tampered = stored.replace('"deny"', '"allow"', 1)
    log.path.write_text(tampered, encoding="utf-8")
    report = log.verify()
    assert report["ok"] is False
    assert report["reason"] == "hash"


def test_empty_log_verifies(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "empty.jsonl", b"k")
    report = log.verify()
    assert report["ok"] is True
    assert report["events"] == 0


def test_records_are_json(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", b"k")
    log.append("tool_decision", actor="t", tool="read_file", outcome="deny", rule="R-PATH-TRAVERSAL", detail={})
    row = json.loads(log.path.read_text(encoding="utf-8"))
    assert row["prev_hash"]
    assert row["hash"] != row["prev_hash"]
