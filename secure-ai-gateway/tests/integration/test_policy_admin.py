"""Policy changes go through the regression gate: weakening protection is refused, tightening is fine."""

from __future__ import annotations

from typing import Any

from tests.conftest import Gateway


def bundle(gw: Gateway) -> dict[str, Any]:
    r = gw.get("/admin/policies", "sam")
    assert r.status_code == 200
    data: dict[str, Any] = r.json()["bundle"]
    return data


def put(gw: Gateway, b: dict[str, Any], note: str = "test") -> Any:
    return gw.client.put("/admin/policies", json={"bundle": b, "note": note}, headers=gw.headers("sam"))


def test_only_security_admin_can_manage_policies(gw: Gateway) -> None:
    assert gw.get("/admin/policies", "avery").status_code == 403
    assert (
        gw.client.put("/admin/policies", json={"bundle": {}}, headers=gw.headers("morgan")).status_code == 403
    )


def test_weakening_card_protection_is_refused(gw: Gateway) -> None:
    b = bundle(gw)
    before = gw.get("/policies", "avery").json()["policy_version"]
    b["base"]["entities"]["CREDIT_CARD"]["action"] = "allow"
    r = put(gw, b, "allow cards, what could go wrong")
    assert r.status_code == 409
    report = r.json()["detail"]["report"]
    assert not report["ok"]
    assert any("CREDIT_CARD" in str(x.get("leaked_entities")) for x in report["protection_regressions"])
    assert gw.get("/policies", "avery").json()["policy_version"] == before  # old policy still active
    events = gw.get("/audit", "sam", event_type="policy_update_rejected").json()["events"]
    assert events and events[0]["details"]["note"] == "allow cards, what could go wrong"


def test_weakening_via_user_override_is_refused(gw: Gateway) -> None:
    b = bundle(gw)
    b["user_overrides"]["acme/u-1001"] = {"routing": {"CONFIDENTIAL": "allow", "RESTRICTED": "allow"}}
    r = put(gw, b)
    assert r.status_code == 409
    assert {x["scope"] for x in r.json()["detail"]["report"]["protection_regressions"]} == {"acme/u-1001"}


def test_opening_the_email_allowlist_to_gmail_is_refused(gw: Gateway) -> None:
    b = bundle(gw)
    b["base"]["tools"]["blocked_email_domains"] = []
    b["base"]["tools"]["allowed_email_domains"] = ["acme.example", "gmail.com"]
    r = put(gw, b)
    assert r.status_code == 409
    assert any(
        x["category"] == "tool_exfiltration" for x in r.json()["detail"]["report"]["protection_regressions"]
    )


def test_tightening_is_accepted_and_takes_effect(gw: Gateway) -> None:
    b = bundle(gw)
    b["base"]["routing"]["CONFIDENTIAL"] = "block"
    r = put(gw, b, "block confidential")
    assert r.status_code == 200, r.text
    assert r.json()["policy_version"].startswith("r2-")
    chat = gw.post(
        "/chat", "avery", {"message": "Our unannounced price increase is 18% in Q3; draft notes."}
    ).json()
    assert chat["decision"]["policy_version"].startswith("r2-")
    assert gw.get("/audit", "sam", event_type="policy_updated").json()["events"]


def test_invalid_policy_is_rejected_before_the_gate(gw: Gateway) -> None:
    b = bundle(gw)
    b["base"]["routing"]["PUBLIC"] = "send_everywhere"
    assert put(gw, b).status_code == 422


def test_dry_run_previews_without_side_effects(gw: Gateway) -> None:
    b = bundle(gw)
    b["base"]["entities"]["ORG"]["action"] = "allow"
    r = gw.post(
        "/admin/policies/dry-run", "sam", {"bundle": b, "message": "Elena Marsh from Northwind Traders"}
    )
    body = r.json()
    assert r.status_code == 200 and {e["entity_type"] for e in body["entities"]} == {"PERSON_NAME"}
    assert len(gw.external.received) == 0


def test_regression_status_endpoint(gw: Gateway) -> None:
    r = gw.get("/admin/regression", "sam").json()
    assert r["ok"] and r["baseline_size"] >= 60
