"""Run every protected scenario, then prove no synthetic PII or secret is in the audit table or app logs."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from aegis.db import agent_runs, approvals, audit_events
from aegis.demo.data import CUSTOMERS
from aegis.demo.fakes import fake_aws_key_id, fake_openai_key
from aegis.demo.scenarios import SCENARIOS
from tests.conftest import Gateway

SENSITIVE = [
    "Dana Holloway",
    "Holloway",
    "dana.holloway@example.com",
    "4111 1111 1111 1111",
    "4111111111111111",
    "312-555-0142",
    "avery-quill-personal@gmail.com",
    "Starter tier",  # the confidential note's content
    fake_openai_key(),
    fake_aws_key_id(),
]


def test_audit_and_logs_contain_no_raw_sensitive_values(
    gw: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    for s in SCENARIOS:
        path = "/chat" if s["kind"] == "chat" else "/agent/run"
        key = "message" if s["kind"] == "chat" else "task"
        r = gw.post(path, s["user"], {key: s["input"]}).json()
        if r.get("approval_id"):
            gw.post(f"/approvals/{r['approval_id']}/approve", "morgan", {})
    gw.post(
        "/chat", "avery", {"message": f"debug: OPENAI_API_KEY={fake_openai_key()} and {fake_aws_key_id()}"}
    )

    with gw.container.engine.connect() as conn:
        rows = [
            str(r._mapping) for t in (audit_events, approvals, agent_runs) for r in conn.execute(select(t))
        ]
    blob = "\n".join(rows) + "\n" + caplog.text
    for value in SENSITIVE:
        assert value not in blob, f"leaked {value[:12]}..."
    for c in CUSTOMERS.values():
        assert c["email"] not in blob and c["name"] not in blob
    assert gw.get("/audit/verify", "sam").json()["ok"]
