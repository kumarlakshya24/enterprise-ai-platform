"""User-scoped access: a user can only de-tokenize their own sessions, within their role's scope."""

from __future__ import annotations

from aegis.demo.scenarios import SCENARIOS_BY_ID as S
from tests.conftest import Gateway


def test_owner_can_detokenize_own_session(gw: Gateway) -> None:
    sid = gw.post("/chat", "avery", {"message": S["s1_direct_paste"]["input"]}).json()["session_id"]
    r = gw.post(
        "/vault/detokenize", "avery", {"session_id": sid, "text": "[PERSON_NAME_1] / [CREDIT_CARD_1]"}
    )
    assert r.status_code == 200 and r.json()["text"] == "Dana Holloway / •••• 1111"


def test_other_user_is_denied_and_audited(gw: Gateway) -> None:
    sid = gw.post("/chat", "avery", {"message": S["s1_direct_paste"]["input"]}).json()["session_id"]
    r = gw.post("/vault/detokenize", "riley", {"session_id": sid, "text": "[PERSON_NAME_1]"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "session_not_owned"
    events = gw.get("/audit", "sam", event_type="detokenize_denied").json()["events"]
    assert events and events[0]["user_id"] == "u-1004"


def test_security_admin_gets_no_extra_data_access(gw: Gateway) -> None:
    """Separation of duties: admins read the audit log, not customer data."""
    sid = gw.post("/chat", "avery", {"message": S["s1_direct_paste"]["input"]}).json()["session_id"]
    assert gw.post("/vault/detokenize", "sam", {"session_id": sid, "text": "[EMAIL_1]"}).status_code == 403


def test_expired_session(gw: Gateway) -> None:
    r = gw.post("/vault/detokenize", "avery", {"session_id": "deadbeef0000", "text": "[EMAIL_1]"})
    assert r.status_code == 404


def test_runs_are_private_to_owner_and_approvers(gw: Gateway) -> None:
    run = gw.post("/agent/run", "avery", {"task": S["s3a_tool_exfil_personal"]["input"]}).json()
    assert gw.get(f"/agent/runs/{run['id']}", "avery").status_code == 200
    assert gw.get(f"/agent/runs/{run['id']}", "riley").status_code == 404
    assert gw.get(f"/agent/runs/{run['id']}", "morgan").status_code == 200


def test_employee_cannot_change_policies(gw: Gateway) -> None:
    assert gw.client.put("/admin/policies", json={}, headers=gw.headers("avery")).status_code in (
        403,
        404,
        405,
    )
