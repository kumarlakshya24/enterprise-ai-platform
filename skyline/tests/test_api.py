"""The console serves the synth."""

from fastapi.testclient import TestClient

from skyline.dashboard.app import create_app


def test_health_and_state() -> None:
    client = TestClient(create_app())
    assert client.get("/healthz").json() == {"ok": True}
    response = client.get("/api/state", params={"rpd": 10000})
    assert response.status_code == 200
    body = response.json()
    assert body["violationCount"] == 0
    assert body["finops"]["requests_per_day"] == 10000
    assert body["guardrail"]["passed"] is True
    page = client.get("/")
    assert page.status_code == 200
    assert "Per 1,000 requests" in page.text
    broken = client.get("/api/state", params={"mutation": "open-sg"})
    assert broken.status_code == 200
    assert broken.json()["violationCount"] >= 1
    assert client.get("/api/state", params={"mutation": "nope"}).status_code == 400
