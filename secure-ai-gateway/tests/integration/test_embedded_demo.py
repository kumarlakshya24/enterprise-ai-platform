"""Embedded demo mode (single process, used by the hosted demo) and the restore-default flow."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from aegis.config import ConfigError, Settings
from aegis.demo.scenarios import SCENARIOS_BY_ID as S
from aegis.gateway.app import create_app
from aegis.gateway.container import build_embedded_demo_container
from tests.conftest import Gateway, make_settings


def login(client: TestClient, user: str) -> dict[str, str]:
    r = client.post("/demo/login", json={"username": user})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_single_process_demo_serves_the_scenarios() -> None:
    settings = make_settings(embedded_demo=True, oidc_issuer="aegis-embedded-idp")
    with TestClient(create_app(build_embedded_demo_container(settings))) as client:
        assert client.get("/healthz").json()["mode"] == "embedded-demo"
        assert client.get("/").status_code == 200
        avery = login(client, "avery")
        body = client.post("/chat", json={"message": S["s1_direct_paste"]["input"]}, headers=avery).json()
        assert body["status"] == "ok" and "[CREDIT_CARD_1]" in body["sent_to_llm"]["prompt"]
        run = client.post("/agent/run", json={"task": S["s4_injection"]["input"]}, headers=avery).json()
        assert run["status"] == "blocked"
        # The in-process IdP still issues tokens the gateway rejects for the wrong tenant / no SSO.
        assert (
            client.post("/chat", json={"message": "hi"}, headers=login(client, "personal")).status_code == 403
        )


def test_embedded_demo_is_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError):
        build_embedded_demo_container(make_settings(env="prod", embedded_demo=True))
    monkeypatch.setenv("AEGIS_ENV", "prod")
    monkeypatch.setenv("AEGIS_EMBEDDED_DEMO", "true")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_restore_default_policy_after_a_visitor_changes_it(gw: Gateway) -> None:
    def put(bundle: dict[str, Any], note: str) -> Any:
        return gw.client.put(
            "/admin/policies", json={"bundle": bundle, "note": note}, headers=gw.headers("sam")
        )

    changed = gw.get("/admin/policies", "sam").json()["bundle"]
    changed["base"]["routing"]["CONFIDENTIAL"] = "block"
    assert put(changed, "visitor tightened it").status_code == 200
    assert gw.get("/policies", "avery").json()["policy"]["routing"]["CONFIDENTIAL"] == "block"

    assert gw.get("/admin/policies/default", "avery").status_code == 403
    default = gw.get("/admin/policies/default", "sam").json()["bundle"]
    r = put(default, "restore default policy")
    assert r.status_code == 200 and r.json()["policy_version"].startswith("r3-")
    assert gw.get("/policies", "avery").json()["policy"]["routing"]["CONFIDENTIAL"] == "local_only"
