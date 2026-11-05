"""Fold the event log into run state. Resume replays this function; it does not re-decide."""

from __future__ import annotations

import json
from typing import Any

from atlas.jsonutil import money


def blank_state(
    *,
    run_id: str,
    workflow_id: str,
    inputs: dict[str, Any],
    budget: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": "starting",
        "inputs": inputs,
        "budget": budget,
        "cost_usd": 0.0,
        "steps": 0,
        "activities": {},
        "activity_order": [],
        "defs": {},
        "llm_decisions": {},
        "guard_decisions": {},
        "approved": False,
        "approved_by": None,
        "comp_jobs": [],
        "last_event_seq": 0,
        "error": None,
        "output": None,
        "plan_rationale": None,
        "rejected_activities": [],
        "llm_calls": 0,
        "llm_replays": 0,
        "backoff_ms_honored": 0,
        "on_failure": "compensate",
    }


def apply_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    """Apply one event in place. ``event`` is ``{seq, type, payload, ts}``."""
    etype = event["type"]
    payload = event["payload"]
    state["last_event_seq"] = int(event["seq"])
    if etype == "run_started":
        state["status"] = "running"
        state["inputs"] = payload["inputs"]
        state["budget"] = payload["budget"]
        state["workflow_id"] = payload["workflow_id"]
    elif etype == "plan_recorded":
        defs = {item["id"]: item for item in payload["activities"]}
        state["defs"] = defs
        state["activity_order"] = [item["id"] for item in payload["activities"]]
        state["plan_rationale"] = payload.get("rationale")
        state["rejected_activities"] = list(payload.get("rejected_activities") or [])
        state["on_failure"] = payload.get("on_failure", "compensate")
        for item in payload["activities"]:
            state["activities"][item["id"]] = {
                "status": "pending",
                "attempt": 0,
                "result": None,
                "error": None,
                "retry_at": None,
                "delay_ms": 0,
                "idempotency_key": f"{state['run_id']}:{item['id']}",
                "healed": False,
                "agent": item.get("agent"),
                "tool": item["tool"],
                "rationale": None,
            }
    elif etype == "llm_decision":
        state["llm_decisions"][payload["decision_id"]] = payload["completion"]
        if payload.get("replayed"):
            state["llm_replays"] += 1
        else:
            state["llm_calls"] += 1
        activity_id = payload.get("activity_id")
        if activity_id and activity_id in state["activities"]:
            state["activities"][activity_id]["rationale"] = payload["completion"].get("rationale")
    elif etype == "guard_decision":
        state["guard_decisions"][payload["activity_id"]] = payload
    elif etype == "activity_ready":
        _act(state, payload["activity_id"])["status"] = "ready"
    elif etype == "activity_started":
        act = _act(state, payload["activity_id"])
        act["status"] = "running"
        act["attempt"] = int(payload["attempt"])
        state["steps"] = int(payload["steps"])
    elif etype == "activity_completed":
        act = _act(state, payload["activity_id"])
        act["status"] = "completed"
        act["result"] = payload.get("result")
        act["error"] = None
        act["healed"] = False
        if payload.get("charge_cost", True):
            state["cost_usd"] = money(state["cost_usd"] + float(payload.get("cost_usd") or 0))
    elif etype == "activity_healed":
        act = _act(state, payload["activity_id"])
        act["status"] = "completed"
        act["result"] = payload.get("result")
        act["error"] = None
        act["healed"] = True
        if not payload.get("cost_already_charged", False):
            state["cost_usd"] = money(state["cost_usd"] + float(payload.get("cost_usd") or 0))
    elif etype == "activity_failed":
        act = _act(state, payload["activity_id"])
        act["status"] = "failed"
        act["error"] = payload.get("error")
    elif etype == "activity_skipped":
        act = _act(state, payload["activity_id"])
        act["status"] = "skipped"
        act["result"] = payload.get("result")
        act["error"] = payload.get("reason")
    elif etype == "activity_retry_scheduled":
        act = _act(state, payload["activity_id"])
        act["status"] = "waiting_retry"
        act["retry_at"] = payload["retry_at"]
        act["delay_ms"] = int(payload.get("delay_ms") or 0)
        act["error"] = payload.get("error")
    elif etype == "activity_waiting_approval":
        _act(state, payload["activity_id"])["status"] = "waiting_approval"
    elif etype == "approval_requested":
        state["status"] = "paused_approval"
        _act(state, payload["activity_id"])["status"] = "waiting_approval"
    elif etype == "approval_decided":
        approved = payload["decision"] == "approved"
        state["approved"] = approved
        state["approved_by"] = payload.get("actor")
        act = _act(state, payload["activity_id"])
        if not approved:
            act["status"] = "failed"
            act["error"] = "denied"
            act["result"] = {"approved": False, "actor": payload.get("actor")}
        elif payload.get("closes_activity"):
            act["status"] = "completed"
            act["result"] = {
                "approved": True,
                "actor": payload.get("actor"),
                "auto": bool(payload.get("auto")),
            }
        elif act["status"] == "waiting_approval":
            act["status"] = "ready"
    elif etype == "compensation_planned":
        state["status"] = "compensating"
        state["comp_jobs"] = [
            {
                "activity_id": job["activity_id"],
                "tool": job["tool"],
                "status": "pending",
                "idempotency_key": job["idempotency_key"],
                "result": None,
                "error": None,
            }
            for job in payload["jobs"]
        ]
    elif etype == "compensation_started":
        job = _job(state, payload["activity_id"])
        job["status"] = "running"
    elif etype == "compensation_completed":
        job = _job(state, payload["activity_id"])
        job["status"] = "done"
        job["result"] = payload.get("result")
        act = state["activities"].get(payload["activity_id"])
        if act and act["status"] == "completed":
            act["status"] = "compensated"
    elif etype == "compensation_failed":
        job = _job(state, payload["activity_id"])
        job["status"] = "failed"
        job["error"] = payload.get("error")
    elif etype == "backoff_honored":
        state["backoff_ms_honored"] = int(state["backoff_ms_honored"]) + int(payload["delay_ms"])
    elif etype == "budget_paused":
        state["status"] = "paused_budget"
        state["error"] = payload.get("reason")
    elif etype == "budget_updated":
        state["budget"] = payload["budget"]
        if state["status"] == "paused_budget":
            state["status"] = "running"
            state["error"] = None
    elif etype == "run_status":
        state["status"] = payload["status"]
        if "error" in payload:
            state["error"] = payload["error"]
        if payload.get("output") is not None:
            state["output"] = payload["output"]
    else:
        raise ValueError(f"unknown event type {etype}")


def fold(events: list[dict[str, Any]], state: dict[str, Any] | None = None) -> dict[str, Any]:
    if state is None:
        if not events:
            raise ValueError("cannot fold an empty log without a seed state")
        first = events[0]
        if first["type"] != "run_started":
            raise ValueError("event log does not start with run_started")
        payload = first["payload"]
        state = blank_state(
            run_id=first["run_id"],
            workflow_id=payload["workflow_id"],
            inputs=payload["inputs"],
            budget=payload["budget"],
        )
    for event in events:
        apply_event(state, event)
    return state


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    """JSON-ready state. Defs are included so a checkpoint can resume without the YAML."""
    return json.loads(json.dumps(state))


def _act(state: dict[str, Any], activity_id: str) -> dict[str, Any]:
    try:
        return state["activities"][activity_id]
    except KeyError as exc:
        raise KeyError(f"activity {activity_id} is not in the plan") from exc


def _job(state: dict[str, Any], activity_id: str) -> dict[str, Any]:
    for job in state["comp_jobs"]:
        if job["activity_id"] == activity_id:
            return job
    raise KeyError(activity_id)
