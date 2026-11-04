"""Scenario 2 and friends: label, classify, route."""

from __future__ import annotations

from aegis.demo.scenarios import SCENARIOS_BY_ID
from tests.conftest import Gateway

S2 = SCENARIOS_BY_ID["s2_context_leak"]["input"]
S5 = SCENARIOS_BY_ID["s5_legit"]["input"]


def test_confidential_context_never_reaches_the_external_llm(gw: Gateway) -> None:
    body = gw.post("/chat", "avery", {"message": S2}).json()
    d = body["decision"]
    assert body["entities"] == []  # regex and NER found nothing
    assert d["regex_only_baseline"]["sends_to_external_llm"] is True  # a pattern-only DLP would leak it
    assert d["context_label"] == "CONFIDENTIAL"
    assert d["route"] == "local_only"
    assert body["sent_to_llm"]["location"] == "local"
    assert "Starter tier" not in gw.external_saw()
    assert len(gw.external.received) == 0 and len(gw.local.received) == 1
    assert d["classifier"]["top_features"], "routing must be explainable"


def test_audit_withholds_confidential_content(gw: Gateway) -> None:
    body = gw.post("/chat", "avery", {"message": S2}).json()
    events = gw.get("/audit", "sam", session_id=body["session_id"], event_type="prompt_received").json()[
        "events"
    ]
    details = events[0]["details"]
    assert details["withheld"] is True and details["fingerprint"] and "prompt_tokenized" not in details
    assert "Starter tier" not in str(events)


def test_legitimate_question_passes_untouched(gw: Gateway) -> None:
    body = gw.post("/chat", "avery", {"message": S5}).json()
    assert body["decision"]["route"] == "allow"
    assert body["decision"]["context_label"] == "PUBLIC"
    assert body["entities"] == []
    assert body["sent_to_llm"]["prompt"] == S5  # byte-for-byte: no false redaction
    assert body["latency_ms"]["gateway_overhead_ms"] < 300


def test_restricted_marker_blocks(gw: Gateway) -> None:
    body = gw.post(
        "/chat", "avery", {"message": "Attorney-client privileged: summarize counsel's view."}
    ).json()
    assert body["status"] == "blocked" and body["decision"]["route"] == "block"
    assert len(gw.external.received) == 0 and len(gw.local.received) == 0


def test_per_user_override_routes_internal_work_locally(gw: Gateway) -> None:
    msg = "Draft a reply to [PERSON_NAME] about the delayed shipment."
    assert gw.post("/chat", "avery", {"message": msg}).json()["decision"]["route"] == "redact_and_continue"
    assert gw.post("/chat", "legal-bot", {"message": msg}).json()["decision"]["route"] == "local_only"


def test_policies_endpoint_shows_effective_policy(gw: Gateway) -> None:
    body = gw.get("/policies", "legal-bot").json()
    assert body["policy"]["routing"]["INTERNAL"] == "local_only"
    assert body["policy_version"].startswith("r1-")
