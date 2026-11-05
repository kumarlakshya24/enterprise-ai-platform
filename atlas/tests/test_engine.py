"""Engine invariants: durability, approvals, budgets, compensation, replay."""

from __future__ import annotations

import json

import pytest

from atlas.domain import CrashInjected, IdempotencyConflict, StaleLease
from atlas.engine import CrashSpec
from atlas.llm import MockLLM
from tests.conftest import refund


def test_happy_path_charges_once_and_records_the_plan(world) -> None:
    paused = world.engine.start("refund", refund(), idempotency_key="happy")
    assert paused["status"] == "paused_approval"
    assert paused["pending_approval"]["tool"] == "approval.gate"
    done = world.engine.decide(paused["id"], "approved", "morgan")
    assert done["status"] == "completed"
    assert done["effect_counts"] == {"ledger.post": 1, "email.send": 1, "case.close": 1}
    assert done["cost_usd"] == pytest.approx(0.011)
    assert done["output"]["amount_usd"] == 40
    assert done["output"]["citations"][0]["doc_id"] == "POL-REF-014"
    assert done["approved_by"] == "morgan"
    debit = next(effect for effect in done["effects"] if effect["tool"] == "ledger.post")
    assert debit["payload"]["amount_usd"] == 40


def test_small_refund_skips_the_gate(world) -> None:
    done = world.engine.start("refund", refund(amount_usd=10), idempotency_key="small")
    assert done["status"] == "completed"
    gate = next(item for item in done["activities"] if item["id"] == "approve_refund")
    assert gate["status"] == "skipped"
    assert done["approved_by"] == "policy"
    assert done["effect_counts"]["ledger.post"] == 1


def test_denial_has_no_side_effects(world) -> None:
    paused = world.engine.start("refund", refund(), idempotency_key="deny")
    done = world.engine.decide(paused["id"], "denied", "morgan")
    assert done["status"] == "denied"
    assert done["effect_counts"] == {}


def test_budgets_pause_before_side_effects(world) -> None:
    steps = world.engine.start(
        "refund",
        refund(),
        idempotency_key="steps",
        budget={"max_steps": 1, "max_cost_usd": 1, "on_exceeded": "pause"},
    )
    assert steps["status"] == "paused_budget"
    assert steps["effect_counts"] == {}
    cost = world.engine.start(
        "refund",
        refund(),
        idempotency_key="cost",
        budget={"max_steps": 20, "max_cost_usd": 0.0025, "on_exceeded": "pause"},
    )
    assert cost["status"] == "paused_budget"
    assert cost["steps"] == 1


def test_raising_the_budget_continues(world) -> None:
    paused = world.engine.start(
        "refund",
        refund(amount_usd=10),
        idempotency_key="raise",
        budget={"max_steps": 1, "max_cost_usd": 1, "on_exceeded": "pause"},
    )
    assert paused["status"] == "paused_budget"
    done = world.engine.raise_budget(
        paused["id"], {"max_steps": 20, "max_cost_usd": 1, "on_exceeded": "pause"}
    )
    assert done["status"] == "completed"
    assert done["effect_counts"]["ledger.post"] == 1


def test_email_failure_compensates_the_ledger(world) -> None:
    done = world.engine.start(
        "refund",
        refund(fail_tools={"email.send": {"mode": "permanent"}}),
        idempotency_key="comp",
        auto_approve=True,
    )
    assert done["status"] == "compensated"
    assert done["effect_counts"] == {"ledger.post": 1, "ledger.reverse": 1}
    credit = next(effect for effect in done["effects"] if effect["tool"] == "ledger.reverse")
    assert credit["payload"]["direction"] == "credit"
    assert credit["payload"]["amount_usd"] == 40


def test_transient_failure_honors_backoff_and_does_not_double_send(world) -> None:
    parked = world.engine.start(
        "refund",
        refund(fail_tools={"email.send": {"mode": "transient", "times": 1}}),
        idempotency_key="retry",
        auto_approve=True,
    )
    assert parked["status"] == "waiting_retry"
    assert parked["effect_counts"].get("email.send", 0) == 0
    world.clock.advance(0.049)
    still = world.engine.resume(parked["id"])
    assert still["status"] == "waiting_retry"
    world.clock.advance(0.002)
    done = world.engine.resume(still["id"])
    assert done["status"] == "completed"
    assert done["effect_counts"]["email.send"] == 1
    assert done["backoff_ms_honored"] == 50
    email = next(item for item in done["activities"] if item["id"] == "email_customer")
    assert email["attempt"] == 2


def test_timeout_retries_then_posts_once(world) -> None:
    parked = world.engine.start(
        "refund",
        refund(fail_tools={"ledger.post": {"mode": "timeout", "times": 1, "elapsed_ms": 5000}}),
        idempotency_key="timeout",
        auto_approve=True,
    )
    assert parked["status"] == "waiting_retry"
    assert parked["effect_counts"] == {}
    world.clock.advance(1)
    done = world.engine.resume(parked["id"])
    assert done["status"] == "completed"
    assert done["effect_counts"]["ledger.post"] == 1


def test_crash_after_remote_heals_without_a_second_debit(world) -> None:
    with pytest.raises(CrashInjected):
        world.engine.start(
            "refund",
            refund(),
            idempotency_key="remote",
            auto_approve=True,
            crash=CrashSpec("post_ledger", "after_remote"),
        )
    run_id = world.store.find_by_key("remote")["id"]
    mid = world.engine.snapshot(run_id)
    assert mid["effect_counts"] == {"ledger.post": 1}
    assert next(item for item in mid["activities"] if item["id"] == "post_ledger")["status"] == "running"
    done = world.engine.resume(run_id, because_crash=True)
    assert done["status"] == "completed"
    assert done["effect_counts"] == {"ledger.post": 1, "email.send": 1, "case.close": 1}
    assert done["recovery"]["completed_steps_rerun"] == 0
    assert done["recovery"]["inflight_steps_rerun"] == 0
    assert done["recovery"]["catch_up_ms"] == 1
    assert next(item for item in done["activities"] if item["id"] == "post_ledger")["healed"]


def test_crash_after_intent_reruns_only_the_in_flight_step(world) -> None:
    with pytest.raises(CrashInjected) as caught:
        world.engine.start(
            "refund",
            refund(),
            idempotency_key="intent",
            auto_approve=True,
            crash=CrashSpec("post_ledger", "after_intent"),
        )
    done = world.engine.resume(caught.value.run_id, because_crash=True)
    assert done["effect_counts"]["ledger.post"] == 1
    assert done["recovery"]["inflight_steps_rerun"] == 1
    assert done["recovery"]["completed_steps_rerun"] == 0
    assert done["recovery"]["catch_up_ms"] == 45


def test_compensation_crash_does_not_double_credit(world) -> None:
    with pytest.raises(CrashInjected):
        world.engine.start(
            "refund",
            refund(fail_tools={"email.send": {"mode": "permanent"}}),
            idempotency_key="ccrash",
            auto_approve=True,
            crash=CrashSpec.parse("post_ledger:after_remote:compensate"),
        )
    run_id = world.store.find_by_key("ccrash")["id"]
    assert world.effects.counts(run_id) == {"ledger.post": 1, "ledger.reverse": 1}
    done = world.engine.resume(run_id, because_crash=True)
    assert done["status"] == "compensated"
    assert done["effect_counts"] == {"ledger.post": 1, "ledger.reverse": 1}
    assert done["recovery"]["inflight_steps_rerun"] == 0


def test_duplicate_start_returns_the_same_run(world) -> None:
    first = world.engine.start("refund", refund(amount_usd=10), idempotency_key="same")
    second = world.engine.start("refund", refund(amount_usd=10), idempotency_key="same")
    assert first["id"] == second["id"]
    assert second["effect_counts"]["ledger.post"] == 1


def test_vendor_webhook_is_blocked_and_the_safe_path_runs(world) -> None:
    paused = world.engine.start("vendor_onboarding", {"vendor_id": "ven_9"}, idempotency_key="vendor")
    risky = next(item for item in paused["activities"] if item["id"] == "notify_risky")
    assert risky["status"] == "skipped"
    assert risky["result"]["rule"] == "R-TOOL-URL-NOT-ALLOWLISTED"
    done = world.engine.decide(paused["id"], "approved", "morgan")
    assert done["status"] == "completed"
    assert "http.post" not in done["effect_counts"]
    assert done["effect_counts"]["vendor.provision"] == 1


def test_incident_fanout_crash_keeps_one_status_update(world) -> None:
    with pytest.raises(CrashInjected) as caught:
        world.engine.start(
            "incident_response",
            {"incident_id": "inc_441"},
            idempotency_key="inc",
            crash=CrashSpec("status_page", "after_remote"),
        )
    done = world.engine.resume(caught.value.run_id, because_crash=True)
    assert done["effect_counts"] == {"status.publish": 1, "pager.page": 1, "postmortem.publish": 1}


def test_non_idempotent_tool_is_refused(world) -> None:
    done = world.engine.start("sms_notice", {"phone": "+15555550100"}, idempotency_key="sms")
    assert done["status"] == "failed"
    assert done["error"] == "R-TOOL-NOT-IDEMPOTENT"
    assert done["effect_counts"] == {}


def test_lumen_refusal_stops_before_the_ledger(world) -> None:
    done = world.engine.start(
        "refund",
        refund(policy_question="What is the executive bonus formula?"),
        idempotency_key="refuse",
        auto_approve=True,
    )
    assert done["status"] == "failed"
    assert done["effect_counts"] == {}
    assert "Not found" in done["error"]


def test_planner_extras_are_rejected(world) -> None:
    done = world.engine.start(
        "refund",
        refund(amount_usd=10, injected_activities=[{"id": "exfil", "tool": "http.post"}]),
        idempotency_key="extra",
    )
    assert done["rejected_activities"][0]["tool"] == "http.post"
    assert "http.post" not in done["effect_counts"]
    assert done["status"] == "completed"


def test_resume_does_not_redecide_a_recorded_step(world) -> None:
    parked = world.engine.start(
        "refund",
        refund(fail_tools={"email.send": {"mode": "transient", "times": 1}}),
        idempotency_key="replay",
        auto_approve=True,
    )

    class Hostile(MockLLM):
        def complete(self, messages, *, decision_id):
            if decision_id == "email_customer":
                raise AssertionError("email was re-decided on resume")
            return super().complete(messages, decision_id=decision_id)

    world.engine.llm = Hostile()
    world.clock.advance(1)
    done = world.engine.resume(parked["id"])
    assert done["status"] == "completed"
    assert done["llm_replays"] >= 1
    email = next(effect for effect in done["effects"] if effect["tool"] == "email.send")
    assert "HACKED" not in email["payload"]["subject"]
    assert email["payload"]["to"] == "dana.holloway@example.com"


def test_replay_from_the_log_matches_a_checkpoint(world) -> None:
    done = world.engine.start("refund", refund(amount_usd=10), idempotency_key="fold")
    folded = world.engine.rebuild(done["id"])
    assert folded["status"] == "completed"
    assert folded["cost_usd"] == done["cost_usd"]
    checkpoints = world.store.checkpoints(done["id"])
    assert len(checkpoints) >= 2
    world.store.tamper_checkpoint(done["id"], checkpoints[-1]["event_seq"])
    again = world.engine.rebuild(done["id"])
    assert again["status"] == "completed"
    assert again["activities"].keys() == folded["activities"].keys()
    assert json.dumps(again["activities"], sort_keys=True) == json.dumps(folded["activities"], sort_keys=True)


def test_stale_epoch_cannot_complete_a_second_debit(world) -> None:
    seen: dict[str, str] = {}

    def steal(run_id: str, activity_id: str) -> None:
        if seen:
            return
        world.clock.advance(31)
        world.store.claim(run_id, "other", world.clock.now(), 30)
        seen["run_id"] = run_id
        seen["activity"] = activity_id

    world.engine.after_remote_hook = steal
    with pytest.raises(StaleLease):
        world.engine.start(
            "refund",
            refund(),
            idempotency_key="fence",
            auto_approve=True,
            crash=None,
        )
    assert seen["activity"] == "post_ledger"
    assert world.effects.counts(seen["run_id"])["ledger.post"] == 1
    done = world.engine.resume(seen["run_id"], owner="other", because_crash=True)
    assert done["status"] == "completed"
    assert done["effect_counts"]["ledger.post"] == 1


def test_idempotency_key_rejects_a_different_payload(world) -> None:
    world.effects.commit_effect(
        key="k",
        run_id="r",
        tool="ledger.post",
        kind="debit",
        payload={"amount_usd": 1},
        created_at=1,
    )
    with pytest.raises(IdempotencyConflict):
        world.effects.commit_effect(
            key="k",
            run_id="r",
            tool="ledger.post",
            kind="debit",
            payload={"amount_usd": 2},
            created_at=2,
        )


def test_personal_email_is_blocked_and_the_debit_is_reversed(world) -> None:
    done = world.engine.start(
        "refund",
        refund(amount_usd=10, email="dana@gmail.com"),
        idempotency_key="gmail",
    )
    email = next(item for item in done["activities"] if item["id"] == "email_customer")
    assert email["status"] == "failed"
    assert email["error"] == "R-TOOL-PERSONAL-DOMAIN"
    assert "email.send" not in done["effect_counts"]
    assert done["status"] == "compensated"
    assert done["effect_counts"] == {"ledger.post": 1, "ledger.reverse": 1}
