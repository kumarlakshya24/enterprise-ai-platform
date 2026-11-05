from switchboard.demo_data import EASY_CHAT, HARD_MATH


def test_health_and_catalog(client) -> None:
    health = client.get("/healthz")
    assert health.status_code == 200
    body = health.json()
    assert body["models"] == ["fast-cheap", "balanced", "premium", "local"]
    catalog = client.get("/v1/catalog").json()
    assert {item["id"] for item in catalog["models"]} == set(body["models"])


def test_route_and_stats(client) -> None:
    first = client.post("/v1/route", json={"prompt": EASY_CHAT, "policy": "default"})
    assert first.status_code == 200
    decision = first.json()
    assert decision["chosen_model"] == "balanced"
    assert decision["comparison"]["savings_usd"] > 0
    stats = client.get("/v1/stats").json()
    assert stats["requests"] == 1
    assert stats["savings_usd"] > 0
    listed = client.get("/v1/decisions").json()["decisions"]
    assert listed[0]["id"] == decision["id"]
    assert "load balancer" in listed[0]["prompt_preview"]


def test_compare_four_policies_on_the_easy_prompt(client) -> None:
    body = client.post("/v1/compare", json={"prompt": EASY_CHAT}).json()
    chosen = {item["policy"]["name"]: item["chosen_model"] for item in body["results"]}
    assert chosen == {
        "default": "balanced",
        "cost-saver": "fast-cheap",
        "latency-first": "fast-cheap",
        "quality-first": "premium",
    }
    assert body["totals"]["savings_usd"] > 0


def test_latency_policy_rejects_hard_math(client) -> None:
    decision = client.post("/v1/route", json={"prompt": HARD_MATH, "policy": "latency-first"}).json()
    assert decision["outcome"] == "rejected"
    assert decision["output"] is None


def test_dry_run_endpoint_accepts_candidate_yaml(client) -> None:
    yaml = """
version: "candidate"
name: candidate
description: force the flagship
selection: highest_capability
weights: {capability: 0.5, cost: 0.25, latency: 0.25}
budget_usd: 1
latency_slo_ms: 5000
min_quality: 0.5
min_headroom: 0
fallback: {order: [premium], allow_local_on_total_failure: false, max_attempts: 1}
"""
    decision = client.post("/v1/policies/dry-run", json={"prompt": EASY_CHAT, "yaml": yaml}).json()
    assert decision["dry_run"] is True
    assert decision["chosen_model"] == "premium"
    assert decision["policy"]["version_id"] == "candidate@candidate"
    assert client.get("/v1/stats").json()["requests"] == 0


def test_unknown_policy_and_empty_prompt(client) -> None:
    assert client.post("/v1/route", json={"prompt": "Hi", "policy": "nope"}).status_code == 404
    assert client.post("/v1/route", json={"prompt": ""}).status_code == 422


def test_active_policy_and_reset(client) -> None:
    changed = client.put("/v1/policies/active", json={"name": "quality-first"})
    assert changed.status_code == 200
    assert client.get("/healthz").json()["policy"] == "quality-first"
    client.post("/v1/route", json={"prompt": EASY_CHAT})
    assert client.get("/v1/stats").json()["requests"] == 1
    assert client.post("/v1/demo/reset").status_code == 200
    assert client.get("/v1/stats").json()["requests"] == 0


def test_ui_shell(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Switchboard" in page.text
    assert client.get("/static/app.js").status_code == 200
