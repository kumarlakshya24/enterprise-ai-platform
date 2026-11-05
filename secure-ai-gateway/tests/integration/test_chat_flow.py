"""Full flow: prompt in, tokenized prompt out, restored answer back, audit entries written."""

from __future__ import annotations

from aegis.demo.scenarios import SCENARIOS_BY_ID
from tests.conftest import Gateway

S1 = SCENARIOS_BY_ID["s1_direct_paste"]["input"]


def test_direct_paste_is_tokenized_before_the_external_llm(gw: Gateway) -> None:
    r = gw.post("/chat", "avery", {"message": S1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["decision"]["route"] == "redact_and_continue"
    assert body["sent_to_llm"]["location"] == "external"

    # The third party saw placeholders only.
    seen = gw.external_saw()
    for raw in ("Dana", "Holloway", "4111", "dana.holloway@example.com"):
        assert raw not in seen
    for ph in ("[PERSON_NAME_1]", "[CREDIT_CARD_1]", "[EMAIL_1]"):
        assert ph in seen

    # The answer is restored for the session owner, with the card masked for a support agent.
    answer = body["answer"]
    assert "Dear Dana Holloway" in answer
    assert "dana.holloway@example.com" in answer
    assert "•••• 1111" in answer and "4111 1111" not in answer
    assert {e["entity_type"] for e in body["entities"]} == {"PERSON_NAME", "CREDIT_CARD", "EMAIL"}
    for e in body["entities"]:
        assert e["detector"] and e["confidence"] > 0.5 and e["action"] == "tokenize"


def test_billing_specialist_sees_the_full_card(gw: Gateway) -> None:
    body = gw.post("/chat", "taylor", {"message": S1}).json()
    assert "4111 1111 1111 1111" in body["answer"]


def test_audit_entries_are_written_and_redacted(gw: Gateway) -> None:
    body = gw.post("/chat", "avery", {"message": S1}).json()
    events = gw.get("/audit", "sam", session_id=body["session_id"]).json()["events"]
    types = [e["event_type"] for e in events]
    for t in ("prompt_received", "dlp_redaction", "routing_decision", "llm_call"):
        assert t in types
    blob = str(events)
    for raw in ("Dana", "Holloway", "4111", "dana.holloway@example.com"):
        assert raw not in blob
    assert "[CREDIT_CARD_1]" in blob
    assert set(body["audit_event_ids"]) <= {e["event_id"] for e in events}


def test_session_reuse_keeps_placeholders_consistent(gw: Gateway) -> None:
    first = gw.post("/chat", "avery", {"message": "Draft a note to dana.holloway@example.com"}).json()
    second = gw.post(
        "/chat",
        "avery",
        {
            "message": "Also cc dana.holloway@example.com and victor.okafor@example.net",
            "session_id": first["session_id"],
        },
    ).json()
    assert second["session_id"] == first["session_id"]
    placeholders = {e["entity_type"]: [] for e in second["entities"]}
    for e in second["entities"]:
        placeholders[e["entity_type"]].append(e["placeholder"])
    assert placeholders["EMAIL"] == ["[EMAIL_1]", "[EMAIL_2]"]


def test_other_user_cannot_use_someone_elses_session(gw: Gateway) -> None:
    first = gw.post("/chat", "avery", {"message": S1}).json()
    r = gw.post("/chat", "riley", {"message": "what was in [EMAIL_1]?", "session_id": first["session_id"]})
    assert r.status_code == 403


def test_secrets_are_redacted_irreversibly(gw: Gateway) -> None:
    from aegis.demo.fakes import fake_aws_key_id

    body = gw.post("/chat", "avery", {"message": f"Why does boto fail with key {fake_aws_key_id()}?"}).json()
    assert fake_aws_key_id() not in gw.external_saw()
    assert fake_aws_key_id() not in body["answer"]
    assert any(e["entity_type"] == "API_KEY" and e["action"] == "redact" for e in body["entities"])


def test_private_key_blocks_the_request(gw: Gateway) -> None:
    from aegis.demo.fakes import fake_private_key

    body = gw.post("/chat", "avery", {"message": f"Is this key valid?\n{fake_private_key()}"}).json()
    assert body["status"] == "blocked" and body["decision"]["rule_id"] == "R-ENTITY-BLOCK"
    assert len(gw.external.received) == 0 and len(gw.local.received) == 0  # nothing left the gateway


def test_latency_breakdown_is_reported(gw: Gateway) -> None:
    body = gw.post("/chat", "avery", {"message": S1}).json()
    lat = body["latency_ms"]
    for k in ("dlp_ms", "tokenize_ms", "classify_ms", "policy_ms", "restore_ms", "gateway_overhead_ms"):
        assert k in lat
