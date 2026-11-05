"""Audit store: hash chain, tamper detection, append-only triggers, scrubber."""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy import text

from aegis.audit.store import AuditStore
from aegis.db import init_db, make_engine


@pytest.fixture
def store() -> AuditStore:
    engine = make_engine("sqlite://")
    init_db(engine)
    return AuditStore(engine, secrets.token_bytes(32))


def fill(store: AuditStore, n: int = 5) -> None:
    for i in range(n):
        store.append("routing_decision", tenant_id="acme", user_id="u-1", route="allow", details={"i": i})


def test_chain_verifies(store: AuditStore) -> None:
    fill(store)
    v = store.verify()
    assert v["ok"] and v["checked"] == 5


def test_update_and_delete_are_rejected_by_the_database(store: AuditStore) -> None:
    fill(store, 2)
    with pytest.raises(Exception, match="append-only"), store.engine.begin() as conn:
        conn.execute(text("UPDATE audit_events SET outcome='x' WHERE seq=1"))
    with pytest.raises(Exception, match="append-only"), store.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE seq=1"))


def test_tampering_is_detected_even_if_triggers_are_dropped(store: AuditStore) -> None:
    """An attacker with DB admin rights drops the trigger and edits a row: verify catches it."""
    fill(store)
    with store.engine.begin() as conn:
        conn.execute(text("DROP TRIGGER audit_no_update"))
        conn.execute(text("UPDATE audit_events SET route='block' WHERE seq=3"))
    v = store.verify()
    assert not v["ok"] and v["first_bad_seq"] == 3


def test_deleting_the_tail_is_detected(store: AuditStore) -> None:
    fill(store)
    with store.engine.begin() as conn:
        conn.execute(text("DROP TRIGGER audit_no_delete"))
        conn.execute(text("DELETE FROM audit_events WHERE seq=5"))
    v = store.verify()
    assert not v["ok"] and v["reason"] == "head does not match tail"


def test_rehashing_without_the_key_fails(store: AuditStore) -> None:
    """Recomputing hashes with a guessed key does not produce a valid chain."""
    fill(store, 3)
    forger = AuditStore(store.engine, secrets.token_bytes(32))
    assert not forger.verify()["ok"]


def test_scrubber_masks_anything_that_slipped_through(store: AuditStore) -> None:
    ev = store.append(
        "debug",
        tenant_id="acme",
        user_id="u-1",
        details={"note": "customer said dana.holloway@example.com and 4111 1111 1111 1111"},
    )
    blob = str(ev["details"])
    assert "dana.holloway" not in blob and "4111" not in blob
    assert ev["details"]["_scrubbed"] == 2 and "[SCRUBBED:EMAIL]" in blob


def test_query_filters_by_tenant(store: AuditStore) -> None:
    store.append("x", tenant_id="acme", user_id="u-1")
    store.append("x", tenant_id="globex", user_id="u-2")
    assert {e["tenant_id"] for e in store.query("acme")} == {"acme"}


def test_content_fingerprint_is_keyed(store: AuditStore) -> None:
    other = AuditStore(store.engine, secrets.token_bytes(32))
    assert store.fingerprint("roadmap") != other.fingerprint("roadmap")
    assert store.fingerprint("roadmap") == store.fingerprint("roadmap")
