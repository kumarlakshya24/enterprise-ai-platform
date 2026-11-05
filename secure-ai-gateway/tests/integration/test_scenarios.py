"""The five demo scenarios, unprotected path vs protected path. All must pass.

The evidence is what the third-party mock model received and what the sandbox saw leave.
"""

from __future__ import annotations

from aegis.demo.scenarios import SCENARIOS_BY_ID as S
from tests.conftest import Gateway

RAW_S1 = ("Dana Holloway", "4111 1111 1111 1111", "dana.holloway@example.com")


def test_scenario_1_direct_paste(gw: Gateway) -> None:
    text = S["s1_direct_paste"]["input"]
    # Unprotected: everything reaches the third party.
    u = gw.post("/demo/unprotected/chat", "avery", {"message": text}).json()
    assert all(v in gw.external_saw() for v in RAW_S1)
    assert "4111 1111 1111 1111" in u["answer"]  # the provider even echoes it back
    gw.external.reset()
    # Protected: placeholders only, answer restored for Avery.
    p = gw.post("/chat", "avery", {"message": text}).json()
    seen = gw.external_saw()
    assert not any(v in seen for v in RAW_S1)
    assert {"[PERSON_NAME_1]", "[EMAIL_1]", "[CREDIT_CARD_1]"} <= set(p["sent_to_llm"]["prompt"].split()) | {
        w.strip(".,") for w in p["sent_to_llm"]["prompt"].split()
    }
    assert "Dana Holloway" in p["answer"] and "dana.holloway@example.com" in p["answer"]


def test_scenario_2_context_leak(gw: Gateway) -> None:
    text = S["s2_context_leak"]["input"]
    gw.post("/demo/unprotected/chat", "avery", {"message": text})
    assert "Starter tier" in gw.external_saw()
    gw.external.reset()
    p = gw.post("/chat", "avery", {"message": text}).json()
    assert p["entities"] == [] and p["decision"]["regex_only_baseline"]["sends_to_external_llm"]
    assert p["decision"]["route"] == "local_only"
    assert "Starter tier" not in gw.external_saw()


def test_scenario_2_policy_toggle_to_block(gw: Gateway) -> None:
    """Same prompt, tenant override CONFIDENTIAL -> block (the policy console does this live)."""
    c = gw.container
    bundle = c.policies.active().bundle.model_copy(deep=True)
    bundle.tenant_overrides["acme"] = {"routing": {"CONFIDENTIAL": "block"}}
    c.policies.activate(bundle, "test", "toggle")
    p = gw.post("/chat", "avery", {"message": S["s2_context_leak"]["input"]}).json()
    assert p["status"] == "blocked" and len(gw.local.received) == 0


def test_scenario_3_tool_exfiltration(gw: Gateway) -> None:
    # Unprotected: the summary lands in a personal Gmail outbox with raw customer data.
    gw.post("/demo/unprotected/agent", "avery", {"task": S["s3a_tool_exfil_personal"]["input"]})
    leaked = gw.container.sandbox.outbox[-1]
    assert leaked["to"].endswith("@gmail.com") and "4111 1111 1111 1111" in leaked["body"]
    gw.container.sandbox.reset()
    gw.external.reset()

    # Protected, personal address: blocked by the domain rule, nothing sent.
    a = gw.post("/agent/run", "avery", {"task": S["s3a_tool_exfil_personal"]["input"]}).json()
    assert a["status"] == "blocked"
    send = next(s for s in a["steps"] if s.get("tool") == "send_email")
    assert any(r["rule"] == "R-TOOL-PERSONAL-DOMAIN" for r in send["guard"]["reasons"])
    assert gw.container.sandbox.outbox == []

    # Protected, corporate address: queued, cannot self-approve, approved by Morgan, then delivered.
    b = gw.post("/agent/run", "avery", {"task": S["s3b_tool_exfil_corporate"]["input"]}).json()
    assert b["status"] == "pending_approval" and gw.container.sandbox.outbox == []
    aid = b["approval_id"]
    assert gw.post(f"/approvals/{aid}/approve", "avery", {}).json()["detail"]["code"] == "four_eyes"
    ok = gw.post(f"/approvals/{aid}/approve", "morgan", {}).json()
    assert ok["status"] == "executed"
    mail = gw.container.sandbox.outbox[-1]
    assert mail["to"] == "avery.quill@acme.example"
    assert "Dana Holloway" in mail["body"] and "•••• 1111" in mail["body"] and "4111 1111" not in mail["body"]
    assert gw.get(f"/agent/runs/{b['id']}", "avery").json()["status"] == "completed"
    # The third party only ever saw placeholders.
    assert not any(v in gw.external_saw() for v in RAW_S1)


def test_scenario_4_prompt_injection(gw: Gateway) -> None:
    task = S["s4_injection"]["input"]
    gw.post("/demo/unprotected/agent", "avery", {"task": task})
    exfil = gw.container.sandbox.egress[-1]
    assert exfil["host"] == "img-cdn.evil.example" and "dana.holloway@example.com" in exfil["url"]
    gw.container.sandbox.reset()

    r = gw.post("/agent/run", "avery", {"task": task}).json()
    assert r["status"] == "blocked"
    read = next(s for s in r["steps"] if s.get("tool") == "read_wiki")
    assert read["result"]["injection"]["flagged"] is True
    render = next(s for s in r["steps"] if s.get("tool") == "render_image")
    assert {"R-TOOL-URL-NOT-ALLOWLISTED", "R-TOOL-DATA-IN-URL", "R-TOOL-TAINTED-SESSION"} <= {
        x["rule"] for x in render["guard"]["reasons"]
    }
    assert gw.container.sandbox.egress == []
    assert "No data left the gateway" in r["final_answer"]
    events = gw.get("/audit", "sam", session_id=r["session_id"]).json()["events"]
    assert {"injection_detected", "tool_call_blocked"} <= {e["event_type"] for e in events}


def test_scenario_5_legitimate_work(gw: Gateway) -> None:
    text = S["s5_legit"]["input"]
    p = gw.post("/chat", "avery", {"message": text}).json()
    assert p["status"] == "ok" and p["decision"]["route"] == "allow" and p["entities"] == []
    assert p["sent_to_llm"]["prompt"] == text and "backoff" in p["answer"]
    assert p["latency_ms"]["gateway_overhead_ms"] < 300


def test_unprotected_path_is_refused_for_real_providers(gateway_factory) -> None:  # type: ignore[no-untyped-def]
    from aegis.llm.providers import OpenAICompatibleProvider

    gw = gateway_factory()
    gw.container.external_llm = OpenAICompatibleProvider(
        "external", "external", "https://api.openai.example/v1", "m"
    )
    r = gw.post("/demo/unprotected/chat", "avery", {"message": "hi"})
    assert r.status_code == 403
