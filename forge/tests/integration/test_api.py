from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from forge.api.app import create_app


def test_health_scenarios_and_protected_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "ws", tmp_path / "audit.jsonl")
    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["policy"] == "forge-1"
    scenarios = client.get("/scenarios").json()["scenarios"]
    assert any(item["id"] == "s4-traversal" for item in scenarios)
    page = client.get("/")
    assert page.status_code == 200
    assert "Forge" in page.text

    allowed = client.post("/run", json={"scenario_id": "s1-sum"})
    body = allowed.json()
    assert body["demo_pass"] is True
    assert body["steps"][0]["stdout"].strip() == "5050"
    assert body["steps"][0]["preview"]["executed"] is False

    blocked = client.post("/run", json={"scenario_id": "s5-import"})
    denied = blocked.json()
    assert denied["demo_pass"] is True
    assert all(step["outcome"] == "deny" and step["spawned"] is False for step in denied["steps"])
    assert all("RAN" not in step["stdout"] for step in denied["steps"])

    custom = client.post("/run", json={"tool": "python", "code": "import socket\nprint('RAN')"})
    assert custom.json()["steps"][0]["rule"] == "R-IMPORT-HARD-DENY"
    verify = client.get("/audit/verify").json()
    assert verify["ok"] is True
    assert verify["events"] >= 3


def test_ui_static_assets(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "ws", tmp_path / "audit.jsonl"))
    css = client.get("/static/styles.css")
    js = client.get("/static/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert "--ember" in css.text
