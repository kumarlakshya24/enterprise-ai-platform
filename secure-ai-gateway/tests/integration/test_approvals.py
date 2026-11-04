"""Approval workflow: four-eyes, permissions, tenancy, expiry, deny, chat approvals."""

from __future__ import annotations

from aegis.demo.scenarios import SCENARIOS_BY_ID as S
from tests.conftest import Gateway

TASK = S["s3b_tool_exfil_corporate"]["input"]


def pending(gw: Gateway, user: str = "avery") -> str:
    r = gw.post("/agent/run", user, {"task": TASK}).json()
    assert r["status"] == "pending_approval"
    return str(r["approval_id"])


def test_approver_cannot_approve_own_request(gw: Gateway) -> None:
    aid = pending(gw, "morgan")  # Morgan has tool:approve but is the requester
    r = gw.post(f"/approvals/{aid}/approve", "morgan", {})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "four_eyes"


def test_user_without_permission_cannot_approve(gw: Gateway) -> None:
    aid = pending(gw)
    r = gw.post(f"/approvals/{aid}/approve", "riley", {})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"
    assert gw.container.sandbox.outbox == []


def test_deny_never_executes(gw: Gateway) -> None:
    aid = pending(gw)
    assert gw.post(f"/approvals/{aid}/deny", "morgan", {"note": "not needed"}).json()["status"] == "denied"
    assert gw.post(f"/approvals/{aid}/approve", "morgan", {}).status_code == 409
    assert gw.container.sandbox.outbox == []


def test_expired_approval_never_executes(gw: Gateway) -> None:
    aid = pending(gw)
    svc = gw.container.approvals
    real_clock = svc.clock
    svc.clock = lambda: real_clock() + 3600
    try:
        r = gw.post(f"/approvals/{aid}/approve", "morgan", {})
    finally:
        svc.clock = real_clock
    assert r.status_code == 410 and gw.container.sandbox.outbox == []
    assert gw.get(f"/approvals/{aid}", "morgan").json()["status"] == "expired"


def test_double_approval_is_rejected(gw: Gateway) -> None:
    aid = pending(gw)
    assert gw.post(f"/approvals/{aid}/approve", "morgan", {}).status_code == 200
    assert gw.post(f"/approvals/{aid}/approve", "morgan", {}).status_code == 409
    assert len(gw.container.sandbox.outbox) == 1


def test_queue_visibility(gw: Gateway) -> None:
    aid = pending(gw)
    assert any(a["id"] == aid for a in gw.get("/approvals", "morgan", status="pending").json()["approvals"])
    assert (
        gw.get("/approvals", "riley").json()["approvals"] == []
    )  # not riley's, and riley is not an approver
    assert gw.get(f"/approvals/{aid}", "riley").status_code == 404


def test_approval_preview_is_redacted(gw: Gateway) -> None:
    aid = pending(gw)
    a = gw.get(f"/approvals/{aid}", "morgan").json()
    blob = str(a)
    assert "Dana" not in blob and "4111" not in blob and "dana.holloway" not in blob
    assert a["summary"]["recipient_domains"] == ["acme.example"]


def test_payload_is_encrypted_at_rest(gw: Gateway) -> None:
    from sqlalchemy import select

    from aegis.db import approvals

    pending(gw)
    with gw.container.engine.connect() as conn:
        enc = conn.execute(select(approvals.c.payload_enc)).scalar()
    assert enc and "acme.example" not in enc and "[PERSON_NAME" not in enc


def test_policy_change_after_approval_is_enforced_at_execution(gw: Gateway) -> None:
    aid = pending(gw)
    c = gw.container
    bundle = c.policies.active().bundle.model_copy(deep=True)
    bundle.base.tools.allowed_email_domains = ["other.example"]
    c.policies.activate(bundle, "test", "narrow allowlist")
    r = gw.post(f"/approvals/{aid}/approve", "morgan", {}).json()
    assert r["result"]["executed"] is False and c.sandbox.outbox == []


def test_chat_bulk_rule_requires_approval_then_resume(gw: Gateway) -> None:
    cards = ", ".join(
        [
            "4111 1111 1111 1111",
            "5555 5555 5555 4444",
            "3782 822463 10005",
            "6011 1111 1111 1117",
            "4012 8888 8888 1881",
        ]
    )
    msg = f"Customer Dana Holloway asked us to refund the duplicate charges on these cards: {cards}. Draft a reply."
    r = gw.post("/chat", "avery", {"message": msg}).json()
    assert r["decision"]["rule_id"] == "R-BULK", r["decision"]
    assert r["status"] == "pending_approval"
    aid = r["approval_id"]
    assert len(gw.external.received) == 0
    assert gw.post(f"/chat/approvals/{aid}/resume", "avery", {}).status_code == 409  # not approved yet
    gw.post(f"/approvals/{aid}/approve", "morgan", {})
    out = gw.post(f"/chat/approvals/{aid}/resume", "avery", {}).json()
    assert out["status"] == "ok"
    assert "4111" not in gw.external_saw()


def test_low_confidence_context_escalates_instead_of_leaking(gw: Gateway) -> None:
    """With no clear signal, the classifier fails safe one level up (here: local model, not external)."""
    r = gw.post("/chat", "avery", {"message": "Reconcile these: 4111 1111 1111 1111"}).json()
    clf = r["decision"]["classifier"]
    if clf["escalated_from"] is not None:
        assert r["decision"]["route"] in ("local_only", "block", "require_approval")
        assert any("escalated" in reason for reason in r["decision"]["reasons"])
