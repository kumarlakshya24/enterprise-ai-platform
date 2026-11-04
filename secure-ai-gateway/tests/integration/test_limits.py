"""Abuse limits: body size, field length, agent step bound, fail-closed dependencies, headers."""

from __future__ import annotations

from aegis.vault.backends import BackendUnavailable
from tests.conftest import Gateway


def test_body_too_large(gw: Gateway) -> None:
    big = "a" * (70 * 1024)
    r = gw.client.post(
        "/chat",
        content=f'{{"message": "{big}"}}',
        headers={**gw.headers("avery"), "content-type": "application/json"},
    )
    assert r.status_code == 413


def test_message_length_validated(gw: Gateway) -> None:
    assert gw.post("/chat", "avery", {"message": ""}).status_code == 422


def test_security_headers(gw: Gateway) -> None:
    r = gw.client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_vault_outage_fails_closed(gw: Gateway) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise BackendUnavailable("down")

    gw.kv.incr = boom  # type: ignore[method-assign]
    r = gw.post("/chat", "avery", {"message": "email dana.holloway@example.com"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "vault_unavailable"
    assert len(gw.external.received) == 0


def test_agent_step_limit(gateway_factory) -> None:  # type: ignore[no-untyped-def]
    gw = gateway_factory(agent_max_steps=1)
    r = gw.post(
        "/agent/run",
        "avery",
        {
            "task": "Look up customer C-1042, check the wiki refund policy, and tell me which refund timeline applies."
        },
    ).json()
    assert r["status"] == "stopped"


def test_healthz_reports_components(gw: Gateway) -> None:
    h = gw.client.get("/healthz").json()
    assert h["ner_backend"] == "spacy" and h["classifier"].startswith("tfidf-lr-")
