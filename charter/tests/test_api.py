"""The demo API returns the same decision the gate locks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from charter.api.app import create_app


def test_residency_block_and_the_weakened_bundle() -> None:
    client = TestClient(create_app())
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "Charter" in page.text

    snapshot = client.get("/api/snapshot")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["counts"]["gap"] == 3
    assert body["audit"]["violation_count"] == 1
    assert body["gate"]["shipped"]["ok"] is True
    assert body["gate"]["weakened"]["ok"] is False

    denied = client.post("/api/decide", json={"case_id": "eu-support-us", "policy": "shipped"})
    assert denied.status_code == 200
    payload = denied.json()
    assert payload["decision"]["effect"] == "deny"
    assert payload["decision"]["primary_rule"] == "R-RESIDENCY-EU"
    assert payload["matches_locked_case"] is True
    assert "R-RESIDENCY-EU" in payload["excerpt"]

    allowed = client.post("/api/decide", json={"case_id": "eu-support-us", "policy": "no-residency"})
    assert allowed.json()["decision"]["effect"] == "allow"
    assert allowed.json()["decision"]["primary_rule"] == "R-PERMIT-HOSTED-SUPPORT"
    assert allowed.json()["matches_locked_case"] is False

    missing = client.post("/api/decide", json={"case_id": "nope"})
    assert missing.status_code == 404
