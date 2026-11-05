"""The demo API drives the same engine the CLI does."""

from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.config import Settings


def _client(tmp_path) -> TestClient:
    settings = Settings(
        db_path=str(tmp_path / "atlas.db"),
        effects_path=str(tmp_path / "effects.db"),
        lease_seconds=30,
        guard="offline",
        aegis_base_url="http://127.0.0.1:9",
        knowledge="offline",
        lumen_base_url="http://127.0.0.1:9",
        lumen_user_id="atlas-worker",
        host="127.0.0.1",
        port=8096,
    )
    return TestClient(create_app(settings.db_path, settings.effects_path, settings))


def test_ui_and_kill_window(tmp_path) -> None:
    client = _client(tmp_path)
    assert client.get("/health").json()["guard"] == "offline"
    assert "Durable runs" in client.get("/").text
    workflows = client.get("/api/workflows").json()
    assert any(item["id"] == "refund" for item in workflows)
    started = client.post(
        "/api/runs",
        json={
            "workflow_id": "refund",
            "idempotency_key": "api-1",
            "inputs": {
                "customer_id": "cus_1042",
                "amount_usd": 40,
                "email": "dana.holloway@example.com",
            },
        },
    ).json()
    assert started["status"] == "paused_approval"
    crashed = client.post(
        f"/api/runs/{started['id']}/decision",
        json={"decision": "approved", "actor": "morgan", "crash_after": "post_ledger:after_remote"},
    ).json()
    assert crashed["crashed"] is True
    assert crashed["effect_counts"]["ledger.post"] == 1
    assert crashed["effect_counts"].get("email.send", 0) == 0
    resumed = client.post(f"/api/runs/{started['id']}/resume").json()
    assert resumed["status"] == "completed"
    assert resumed["effect_counts"] == {"ledger.post": 1, "email.send": 1, "case.close": 1}
    baseline = client.post(
        "/api/baseline",
        json={
            "inputs": {
                "customer_id": "cus_1042",
                "amount_usd": 40,
                "email": "dana.holloway@example.com",
                "policy_question": "What is the customer refund policy?",
            },
            "crash_after": "post_ledger:after_remote",
        },
    ).json()
    assert baseline["effect_counts"]["ledger.post"] == 2
