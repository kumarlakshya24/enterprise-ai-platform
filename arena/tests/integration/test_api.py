"""The page and the CLI read the same saved report."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_and_saved_report(client: TestClient) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["lumen"] == "stub"
    assert body["switchboard"] == "stub"
    assert body["report_stale"] is False
    report = client.get("/v1/report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["source"] == "saved"
    assert payload["report"]["scenarios"][0]["winner"] == "rag"


def test_saved_scenario_is_not_recomputed(client: TestClient) -> None:
    response = client.post("/v1/decide", json={"scenario_id": "weekly-cited"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "saved"
    assert body["decision"]["winner"] == "rag"
    assert "Do not fine-tune" in body["decision"]["memo_md"]


def test_slider_uses_saved_metrics(client: TestClient) -> None:
    response = client.post(
        "/v1/decide",
        json={
            "scenario_id": "weekly-cited",
            "change_rate": "stable",
            "citations_required": False,
            "monthly_requests": 2_000_000,
            "scope": "full",
            "latency_slo_ms": 2000,
            "monthly_budget_usd": 8000,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "saved-metrics"
    assert body["decision"]["winner"] == "lora"
    assert body["decision"]["quality"]["lora"] == 0.95


def test_compare_refund_window(client: TestClient) -> None:
    response = client.post("/v1/compare", json={"question_id": "st-refund-window"})
    assert response.status_code == 200
    arms = response.json()["arms"]
    assert arms["prompt"]["refused"] is True
    assert "30 days" in arms["rag"]["text"]
    assert arms["rag"]["citations"][0]["doc_id"] == "billing-refunds"
    assert arms["rag"]["reason_current"] == "ok"
    assert "14 days" in arms["lora"]["text"]
    assert arms["lora"]["reason_current"] == "stale"
    assert arms["lora"]["reason_freeze"] == "ok"
    assert arms["lora"]["citations"] == []
    assert arms["distilled"]["reason_current"] == "stale"


def test_unknown_question_and_bad_scenario(client: TestClient) -> None:
    assert client.post("/v1/compare", json={"question_id": "missing"}).status_code == 404
    assert client.post("/v1/compare", json={"question_id": "tr-credit-1"}).status_code == 404
    bad = client.post("/v1/decide", json={"scenario_id": "weekly-cited", "change_rate": "daily"})
    assert bad.status_code == 422


def test_ports_stay_on_stubs_without_urls(client: TestClient) -> None:
    body = client.get("/v1/ports").json()
    assert body["lumen"]["source"] == "lumen-stub"
    assert body["switchboard"]["source"] == "switchboard-stub"
    assert body["switchboard"]["arms"]["distilled"]["switchboard_model"] == "fast-cheap"
    pipeline = client.get("/v1/pipeline").json()["pipeline"]
    assert "webhook.sign" in pipeline["unseen_at_train"]
    assert pipeline["lumen"].startswith("POST /ask")
