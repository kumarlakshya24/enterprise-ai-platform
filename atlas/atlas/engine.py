"""Durable workflow engine.

A run is an append-only event log plus checkpoints. Resume replays the log.
Side effects live in a separate store and are keyed, so a worker killed after the
remote commit and before the completion event does not do the work twice.
"""

from __future__ import annotations

import copy
import json
import os
import signal
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from atlas.catalog import load_workflow
from atlas.clock import SystemClock
from atlas.domain import CHECKPOINT_EVENTS, HEAL_MS, TERMINAL, CrashInjected, PlanError
from atlas.guard import ToolGuard
from atlas.jsonutil import canon, money
from atlas.knowledge import Knowledge
from atlas.llm import LLM
from atlas.replay import apply_event, blank_state, fold
from atlas.store import EffectStore, Store
from atlas.tools import TOOL_META, ToolContext, call_tool

CrashHook = Callable[[str, str], None]


class _Park(Exception):
    """The run cannot make progress until a human or a timer moves."""


@dataclass
class CrashSpec:
    activity_id: str
    phase: str
    mode: str = "raise"  # raise | sigkill
    compensation: bool = False

    @classmethod
    def parse(cls, text: str | None, mode: str = "raise") -> CrashSpec | None:
        if not text:
            return None
        parts = text.split(":")
        if len(parts) == 2:
            activity_id, phase = parts
            compensation = False
        elif len(parts) == 3 and parts[2] == "compensate":
            activity_id, phase = parts[0], parts[1]
            compensation = True
        else:
            raise ValueError(f"crash spec must be activity:phase or activity:phase:compensate, got {text}")
        if phase not in {"after_intent", "after_remote"}:
            raise ValueError(f"unknown crash phase {phase}")
        return cls(activity_id, phase, mode, compensation)


@dataclass
class ResumeStats:
    """Accounting for the pass that follows a crash. Simulated time, not wall clock."""

    crashed_activity: str | None = None
    running_before: set[str] = field(default_factory=set)
    completed_before: set[str] = field(default_factory=set)
    completed_steps_rerun: int = 0
    inflight_steps_rerun: int = 0
    recovery_ms: int = 0
    catch_up_ms: int = 0
    catch_up_done: bool = False
    _reran: set[str] = field(default_factory=set)

    def note_heal(self, activity_id: str) -> None:
        self.recovery_ms += HEAL_MS
        if not self.catch_up_done and activity_id == self.crashed_activity:
            self.catch_up_ms += HEAL_MS
            self.catch_up_done = True

    def note_body(self, activity_id: str, latency_ms: int, *, rerun: bool) -> None:
        if rerun and activity_id in self.completed_before:
            self.completed_steps_rerun += 1
        if rerun and activity_id in self.running_before and activity_id not in self._reran:
            self._reran.add(activity_id)
            self.inflight_steps_rerun += 1
        self.recovery_ms += latency_ms
        if not self.catch_up_done:
            self.catch_up_ms += latency_ms
            if activity_id == self.crashed_activity:
                self.catch_up_done = True

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "crashed_activity": self.crashed_activity,
            "completed_steps_rerun": self.completed_steps_rerun,
            "inflight_steps_rerun": self.inflight_steps_rerun,
            "recovery_ms": self.recovery_ms,
            "catch_up_ms": self.catch_up_ms,
        }


class Engine:
    def __init__(
        self,
        store: Store,
        effects: EffectStore,
        *,
        llm: LLM,
        guard: ToolGuard,
        knowledge: Knowledge,
        clock: SystemClock | None = None,
        lease_ttl: float = 30.0,
        after_remote_hook: CrashHook | None = None,
    ) -> None:
        self.store = store
        self.effects = effects
        self.llm = llm
        self.guard = guard
        self.knowledge = knowledge
        self.clock = clock or SystemClock()
        self.lease_ttl = lease_ttl
        self.after_remote_hook = after_remote_hook
        self._replayed_this_drive: set[str] = set()

    def start(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
        *,
        idempotency_key: str,
        budget: dict[str, Any] | None = None,
        crash: CrashSpec | None = None,
        auto_approve: bool = False,
        owner: str = "worker",
    ) -> dict[str, Any]:
        inputs = dict(inputs)
        inputs.setdefault("policy_question", "What is the customer refund policy?")
        inputs.setdefault("principal", "atlas-worker")
        existing = self.store.find_by_key(idempotency_key)
        if existing:
            return self.resume(existing["id"], owner=owner, crash=crash, auto_approve=auto_approve)
        workflow = load_workflow(workflow_id)
        budget = copy.deepcopy(budget or workflow["budget"])
        run_id = "run_" + uuid.uuid4().hex[:12]
        now = self.clock.now()
        self.store.create_run(
            run_id=run_id,
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
            inputs=inputs,
            budget=budget,
            now=now,
        )
        epoch = self.store.claim(run_id, owner, now, self.lease_ttl)
        state = blank_state(run_id=run_id, workflow_id=workflow_id, inputs=inputs, budget=budget)
        self._append(
            state,
            "run_started",
            {"workflow_id": workflow_id, "inputs": inputs, "budget": budget},
            epoch,
        )
        plan = self._decide(state, epoch, "plan", None)
        rejected = []
        for extra in plan.get("extra_activities") or []:
            rejected.append({"id": extra.get("id", "extra"), "tool": extra.get("tool")})
        self._append(
            state,
            "plan_recorded",
            {
                "activities": workflow["activities"],
                "rationale": plan.get("rationale"),
                "rejected_activities": rejected,
                "on_failure": workflow["on_failure"],
            },
            epoch,
        )
        state["on_failure"] = workflow["on_failure"]
        return self._drive(state, epoch, crash=crash, auto_approve=auto_approve, stats=None, owner=owner)

    def resume(
        self,
        run_id: str,
        *,
        owner: str = "worker",
        crash: CrashSpec | None = None,
        auto_approve: bool = False,
        because_crash: bool = False,
    ) -> dict[str, Any]:
        now = self.clock.now()
        epoch = self.store.claim(run_id, owner, now, self.lease_ttl)
        state = self.rebuild(run_id)
        stats = None
        if because_crash:
            running = [i for i, act in state["activities"].items() if act["status"] == "running"]
            comp_running = [job["activity_id"] for job in state["comp_jobs"] if job["status"] == "running"]
            crashed = (running or comp_running or [None])[0]
            stats = ResumeStats(
                crashed_activity=crashed,
                running_before=set(running) | set(comp_running),
                completed_before={i for i, act in state["activities"].items() if act["status"] == "completed"},
            )
        self._heal_forward(state, epoch, stats)
        return self._drive(state, epoch, crash=crash, auto_approve=auto_approve, stats=stats, owner=owner)

    def decide(
        self,
        run_id: str,
        decision: str,
        actor: str,
        *,
        owner: str = "worker",
        crash: CrashSpec | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approved", "denied"}:
            raise ValueError("decision must be approved or denied")
        epoch = self.store.claim(run_id, owner, self.clock.now(), self.lease_ttl)
        state = self.rebuild(run_id)
        activity_id = _pending_approval(state)
        if activity_id is None:
            raise PlanError("this run is not waiting for approval")
        closes = state["defs"][activity_id]["tool"] == "approval.gate"
        self._append(
            state,
            "approval_decided",
            {
                "activity_id": activity_id,
                "decision": decision,
                "actor": actor,
                "auto": False,
                "closes_activity": closes,
            },
            epoch,
        )
        if decision == "denied":
            self._stop_forward(state, epoch, "denied")
            if _completed_side_effects(state):
                self._begin_compensation(state, epoch, "denied")
                return self._drive(state, epoch, crash=crash, auto_approve=False, stats=None, owner=owner)
            self._append(state, "run_status", {"status": "denied", "error": "denied by " + actor}, epoch)
            return self._finish(state, None)
        self._append(state, "run_status", {"status": "running"}, epoch)
        return self._drive(state, epoch, crash=crash, auto_approve=False, stats=None, owner=owner)

    def raise_budget(
        self,
        run_id: str,
        budget: dict[str, Any],
        *,
        owner: str = "worker",
    ) -> dict[str, Any]:
        epoch = self.store.claim(run_id, owner, self.clock.now(), self.lease_ttl)
        state = self.rebuild(run_id)
        self._append(state, "budget_updated", {"budget": budget}, epoch)
        return self._drive(state, epoch, crash=None, auto_approve=False, stats=None, owner=owner)

    def rebuild(self, run_id: str) -> dict[str, Any]:
        checkpoint = self.store.latest_valid_checkpoint(run_id)
        if checkpoint is not None:
            state = json.loads(checkpoint["state_json"])
            tail = self.store.events(run_id, after_seq=int(checkpoint["event_seq"]))
            return fold(tail, state)
        events = self.store.events(run_id)
        if not events:
            raise KeyError(run_id)
        return fold(events)

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        state = self.rebuild(run_id)
        events = self.store.events(run_id)
        wave = _waves(state)
        activities = []
        for activity_id in state["activity_order"]:
            act = state["activities"][activity_id]
            definition = state["defs"][activity_id]
            activities.append(
                {
                    "id": activity_id,
                    "status": act["status"],
                    "attempt": act["attempt"],
                    "tool": definition["tool"],
                    "agent": definition.get("agent"),
                    "wave": wave[activity_id],
                    "order": definition["order"],
                    "result": act["result"],
                    "error": act["error"],
                    "healed": act["healed"],
                    "retry_at": act.get("retry_at"),
                    "rationale": act.get("rationale"),
                    "side_effect": definition["side_effect"],
                    "latency_ms": definition["latency_ms"],
                    "cost_usd": definition["cost_usd"],
                }
            )
        now = self.clock.now()
        expires = run["lease_expires_at"]
        return {
            "id": run_id,
            "workflow_id": state["workflow_id"],
            "idempotency_key": run["idempotency_key"],
            "status": state["status"],
            "inputs": state["inputs"],
            "budget": state["budget"],
            "cost_usd": state["cost_usd"],
            "steps": state["steps"],
            "error": state["error"],
            "output": state["output"],
            "approved": state["approved"],
            "approved_by": state["approved_by"],
            "plan_rationale": state["plan_rationale"],
            "rejected_activities": state["rejected_activities"],
            "activities": activities,
            "events": events,
            "effects": self.effects.list(run_id),
            "effect_counts": self.effects.counts(run_id),
            "comp_jobs": state["comp_jobs"],
            "llm_calls": state["llm_calls"],
            "llm_replays": state["llm_replays"],
            "backoff_ms_honored": state["backoff_ms_honored"],
            "lease": {
                "owner": run["lease_owner"],
                "expires_at": expires,
                "epoch": run["lease_epoch"],
                "expired": not expires or expires <= now,
            },
            "pending_approval": _approval_payload(state, events),
        }

    def _drive(
        self,
        state: dict[str, Any],
        epoch: int,
        *,
        crash: CrashSpec | None,
        auto_approve: bool,
        stats: ResumeStats | None,
        owner: str,
    ) -> dict[str, Any]:
        del owner
        self._replayed_this_drive = set()
        while True:
            if state["status"] in TERMINAL or state["status"] in {"paused_approval", "paused_budget"}:
                return self._finish(state, stats)
            if state["status"] == "compensating":
                self._step_compensation(state, epoch, crash, stats)
                continue
            self._promote(state, epoch)
            if state["status"] in TERMINAL:
                return self._finish(state, stats)
            nxt = _next_activity(state, self.clock.now())
            if nxt is None:
                if _future_retry(state, self.clock.now()):
                    if state["status"] != "waiting_retry":
                        self._append(state, "run_status", {"status": "waiting_retry"}, epoch)
                    return self._finish(state, stats)
                self._settle(state, epoch)
                if state["status"] == "compensating":
                    continue
                return self._finish(state, stats)
            definition = state["defs"][nxt]
            if state["activities"][nxt]["status"] != "running":
                reason = _budget_block(state, definition)
                if reason:
                    self._append(state, "budget_paused", {"reason": reason}, epoch)
                    return self._finish(state, stats)
            try:
                self._step(state, epoch, nxt, crash, auto_approve, stats)
            except _Park:
                return self._finish(state, stats)

    def _finish(self, state: dict[str, Any], stats: ResumeStats | None) -> dict[str, Any]:
        snap = self.snapshot(state["run_id"])
        snap["recovery"] = stats.as_dict() if stats else None
        return snap

    def _append(self, state: dict[str, Any], etype: str, payload: dict[str, Any], epoch: int) -> None:
        payload = json.loads(canon(payload))
        ts = self.clock.now()
        trial = copy.deepcopy(state)
        apply_event(trial, {"seq": 0, "type": etype, "payload": payload, "ts": ts, "run_id": state["run_id"]})
        checkpoint_state = trial if etype in CHECKPOINT_EVENTS else None
        seq = self.store.append(
            run_id=state["run_id"],
            epoch=epoch,
            ts=ts,
            etype=etype,
            payload=payload,
            projection={
                "status": trial["status"],
                "cost_usd": trial["cost_usd"],
                "steps": trial["steps"],
                "output": trial["output"],
                "error": trial["error"],
            },
            checkpoint_state=checkpoint_state,
        )
        trial["last_event_seq"] = seq
        state.clear()
        state.update(trial)

    def _decide(
        self,
        state: dict[str, Any],
        epoch: int,
        decision_id: str,
        definition: dict[str, Any] | None,
    ) -> dict[str, Any]:
        recorded = state["llm_decisions"].get(decision_id)
        if recorded is not None:
            if decision_id not in self._replayed_this_drive:
                self._replayed_this_drive.add(decision_id)
                self._append(
                    state,
                    "llm_decision",
                    {
                        "decision_id": decision_id,
                        "activity_id": definition["id"] if definition else None,
                        "completion": recorded,
                        "replayed": True,
                    },
                    epoch,
                )
            return state["llm_decisions"][decision_id]
        completion = self.llm.complete(_messages(state, decision_id, definition), decision_id=decision_id)
        self._append(
            state,
            "llm_decision",
            {
                "decision_id": decision_id,
                "activity_id": definition["id"] if definition else None,
                "completion": completion,
                "replayed": False,
            },
            epoch,
        )
        return completion

    def _promote(self, state: dict[str, Any], epoch: int) -> None:
        while True:
            promoted = False
            for activity_id in list(state["activity_order"]):
                act = state["activities"][activity_id]
                if act["status"] != "pending":
                    continue
                definition = state["defs"][activity_id]
                dep_status = [state["activities"][dep]["status"] for dep in definition["deps"]]
                if any(status in {"failed", "compensated"} for status in dep_status):
                    self._append(
                        state,
                        "activity_skipped",
                        {"activity_id": activity_id, "reason": "blocked_by_dependency"},
                        epoch,
                    )
                    promoted = True
                    break
                if any(status not in {"completed", "skipped"} for status in dep_status):
                    continue
                if not _when(definition.get("when"), state):
                    if definition["tool"] == "approval.gate":
                        # The policy gate does not apply. Downstream high-risk tools are cleared.
                        self._append(
                            state,
                            "approval_decided",
                            {
                                "activity_id": activity_id,
                                "decision": "approved",
                                "actor": "policy",
                                "auto": True,
                                "closes_activity": False,
                            },
                            epoch,
                        )
                    self._append(
                        state,
                        "activity_skipped",
                        {"activity_id": activity_id, "reason": "when", "result": {"skipped": True}},
                        epoch,
                    )
                    promoted = True
                    break
                self._append(state, "activity_ready", {"activity_id": activity_id}, epoch)
                promoted = True
                break
            if not promoted:
                return

    def _step(
        self,
        state: dict[str, Any],
        epoch: int,
        activity_id: str,
        crash: CrashSpec | None,
        auto_approve: bool,
        stats: ResumeStats | None,
    ) -> None:
        definition = state["defs"][activity_id]
        act = state["activities"][activity_id]
        if definition["tool"] == "approval.gate":
            self._step_gate(state, epoch, activity_id, auto_approve)
            return
        if act["status"] == "running":
            self._execute_body(state, epoch, activity_id, crash, stats, continuing=True)
            return
        if act["status"] == "waiting_retry":
            delay = int(act.get("delay_ms") or 0)
            self._append(state, "backoff_honored", {"activity_id": activity_id, "delay_ms": delay}, epoch)
        completion = self._decide(state, epoch, activity_id, definition)
        args = _bind_args(state, definition, completion)
        idempotent = bool(definition["idempotent"] and TOOL_META[definition["tool"]]["idempotent"])
        decision = self.guard.evaluate(
            tool=definition["tool"],
            args=args,
            risk=str(definition.get("risk") or "low"),
            idempotent=idempotent,
            approved=bool(state["approved"]),
            rationale=str(completion.get("rationale") or ""),
        )
        self._append(
            state,
            "guard_decision",
            {"activity_id": activity_id, "args": args, **decision.as_dict()},
            epoch,
        )
        if decision.verdict == "block":
            if definition.get("on_block") == "skip":
                self._append(
                    state,
                    "activity_skipped",
                    {
                        "activity_id": activity_id,
                        "reason": decision.rule,
                        "result": decision.as_dict(),
                    },
                    epoch,
                )
                return
            self._append(state, "activity_failed", {"activity_id": activity_id, "error": decision.rule}, epoch)
            self._begin_compensation(state, epoch, decision.rule)
            return
        if decision.verdict == "require_approval" and not state["approved"]:
            self._append(
                state,
                "approval_requested",
                {
                    "activity_id": activity_id,
                    "approval_id": "appr_" + uuid.uuid4().hex[:10],
                    "tool": definition["tool"],
                    "summary": decision.message,
                },
                epoch,
            )
            raise _Park()
        self._execute_body(state, epoch, activity_id, crash, stats, continuing=False, args=args)

    def _step_gate(self, state: dict[str, Any], epoch: int, activity_id: str, auto_approve: bool) -> None:
        if auto_approve or state["approved"]:
            self._append(
                state,
                "approval_decided",
                {
                    "activity_id": activity_id,
                    "decision": "approved",
                    "actor": state["approved_by"] or "morgan",
                    "auto": auto_approve and not state["approved"],
                    "closes_activity": True,
                },
                epoch,
            )
            return
        self._append(
            state,
            "approval_requested",
            {
                "activity_id": activity_id,
                "approval_id": "appr_" + uuid.uuid4().hex[:10],
                "tool": "approval.gate",
                "summary": "Amount is above the policy threshold.",
            },
            epoch,
        )
        raise _Park()

    def _execute_body(
        self,
        state: dict[str, Any],
        epoch: int,
        activity_id: str,
        crash: CrashSpec | None,
        stats: ResumeStats | None,
        *,
        continuing: bool,
        args: dict[str, Any] | None = None,
    ) -> None:
        definition = state["defs"][activity_id]
        act = state["activities"][activity_id]
        if args is None:
            recorded = state["llm_decisions"].get(activity_id) or {}
            args = state["guard_decisions"].get(activity_id, {}).get("args") or _bind_args(state, definition, recorded)
        if not continuing:
            attempt = int(act["attempt"]) + 1
            self._append(
                state,
                "activity_started",
                {"activity_id": activity_id, "attempt": attempt, "steps": state["steps"] + 1},
                epoch,
            )
            self._maybe_crash(state, epoch, activity_id, "after_intent", crash, committed=True, compensation=False)
        elif stats is not None:
            stats.note_body(activity_id, int(definition["latency_ms"]), rerun=True)
        result = call_tool(definition["tool"], self._ctx(state, activity_id), args)
        timed_out = result.elapsed_ms > int(definition["timeout_ms"]) and not result.committed
        if result.committed:
            self._after_remote(state, activity_id)
            self._maybe_crash(state, epoch, activity_id, "after_remote", crash, committed=True, compensation=False)
        if timed_out or (not result.ok and not result.permanent):
            attempt = int(state["activities"][activity_id]["attempt"])
            if attempt < int(definition["max_attempts"]):
                delay = int(definition["backoff_ms"]) * (2 ** max(attempt - 1, 0))
                self._append(
                    state,
                    "activity_retry_scheduled",
                    {
                        "activity_id": activity_id,
                        "retry_at": self.clock.now() + delay / 1000.0,
                        "delay_ms": delay,
                        "error": result.output.get("error", "retryable"),
                    },
                    epoch,
                )
                return
            self._append(
                state,
                "activity_failed",
                {"activity_id": activity_id, "error": result.output.get("error", "attempts exhausted")},
                epoch,
            )
            self._begin_compensation(state, epoch, "attempts exhausted")
            return
        if not result.ok:
            self._append(
                state,
                "activity_failed",
                {"activity_id": activity_id, "error": result.output.get("error", "failed")},
                epoch,
            )
            self._begin_compensation(state, epoch, str(result.output.get("error")))
            return
        if stats is not None and not continuing:
            stats.note_body(activity_id, int(definition["latency_ms"]), rerun=False)
        self._append(
            state,
            "activity_completed",
            {
                "activity_id": activity_id,
                "result": result.output,
                "cost_usd": definition["cost_usd"],
                "charge_cost": True,
            },
            epoch,
        )

    def _after_remote(self, state: dict[str, Any], activity_id: str) -> None:
        if self.after_remote_hook is not None:
            self.after_remote_hook(state["run_id"], activity_id)

    def _maybe_crash(
        self,
        state: dict[str, Any],
        epoch: int,
        activity_id: str,
        phase: str,
        crash: CrashSpec | None,
        *,
        committed: bool,
        compensation: bool,
    ) -> None:
        if crash is None or crash.activity_id != activity_id or crash.phase != phase:
            return
        if crash.compensation != compensation:
            return
        if phase == "after_remote" and not committed:
            return
        self.store.heartbeat(state["run_id"], epoch, self.clock.now() + self.lease_ttl)
        if crash.mode == "sigkill":
            self.store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.effects.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            os.kill(os.getpid(), signal.SIGKILL)
        raise CrashInjected(state["run_id"], activity_id, phase)

    def _heal_forward(self, state: dict[str, Any], epoch: int, stats: ResumeStats | None) -> None:
        for activity_id in list(state["activity_order"]):
            act = state["activities"][activity_id]
            if act["status"] != "running":
                continue
            row = self.effects.get(act["idempotency_key"])
            if row is None:
                continue
            definition = state["defs"][activity_id]
            self._append(
                state,
                "activity_healed",
                {
                    "activity_id": activity_id,
                    "result": row["payload"],
                    "cost_usd": definition["cost_usd"],
                    "bookkeeping_ms": HEAL_MS,
                },
                epoch,
            )
            if stats is not None:
                stats.note_heal(activity_id)

    def _ctx(self, state: dict[str, Any], activity_id: str) -> ToolContext:
        upstream = {}
        for dep in state["defs"][activity_id]["deps"]:
            upstream[dep] = state["activities"][dep]["result"] or {}
        # quote reads lookup_policy by name even if the dep id differs
        if "lookup_policy" in state["activities"] and state["activities"]["lookup_policy"]["result"]:
            upstream["lookup_policy"] = state["activities"]["lookup_policy"]["result"]
        return ToolContext(
            effects=self.effects,
            run_id=state["run_id"],
            idempotency_key=state["activities"][activity_id]["idempotency_key"],
            inputs=state["inputs"],
            upstream=upstream,
            attempt=int(state["activities"][activity_id]["attempt"] or 1),
            now=self.clock.now(),
            knowledge=self.knowledge,
        )

    def _begin_compensation(self, state: dict[str, Any], epoch: int, error: str) -> None:
        self._stop_forward(state, epoch, "stopped")
        if state.get("on_failure", "compensate") == "halt" or not _completed_side_effects(state):
            self._append(state, "run_status", {"status": "failed", "error": error}, epoch)
            return
        jobs = []
        for activity_id in reversed(state["activity_order"]):
            definition = state["defs"][activity_id]
            act = state["activities"][activity_id]
            if act["status"] == "completed" and definition.get("compensate"):
                jobs.append(
                    {
                        "activity_id": activity_id,
                        "tool": definition["compensate"],
                        "idempotency_key": f"{state['run_id']}:{activity_id}:compensate",
                    }
                )
        if not jobs:
            self._append(state, "run_status", {"status": "failed", "error": error}, epoch)
            return
        self._append(state, "compensation_planned", {"jobs": jobs, "error": error}, epoch)

    def _stop_forward(self, state: dict[str, Any], epoch: int, reason: str) -> None:
        for activity_id in list(state["activity_order"]):
            status = state["activities"][activity_id]["status"]
            if status in {"pending", "ready", "waiting_retry", "waiting_approval"}:
                self._append(
                    state,
                    "activity_skipped",
                    {"activity_id": activity_id, "reason": reason},
                    epoch,
                )

    def _step_compensation(
        self,
        state: dict[str, Any],
        epoch: int,
        crash: CrashSpec | None,
        stats: ResumeStats | None,
    ) -> None:
        job = next((item for item in state["comp_jobs"] if item["status"] != "done"), None)
        if job is None:
            self._append(
                state,
                "run_status",
                {"status": "compensated", "output": _collect_output(state)},
                epoch,
            )
            return
        activity_id = job["activity_id"]
        key = job["idempotency_key"]
        if job["status"] != "running":
            self._append(state, "compensation_started", {"activity_id": activity_id}, epoch)
        existing = self.effects.get(key)
        if existing is not None:
            self._append(
                state,
                "compensation_completed",
                {"activity_id": activity_id, "result": existing["payload"], "healed": True},
                epoch,
            )
            if stats is not None and activity_id in stats.running_before:
                stats.note_heal(activity_id)
            return
        if stats is not None and activity_id in stats.running_before:
            latency = int(state["defs"][activity_id]["latency_ms"])
            stats.note_body(activity_id, latency, rerun=True)
        args = _compensation_args(state, activity_id, job["tool"])
        # The compensation uses its own idempotency key and attempt 1.
        ctx = ToolContext(
            effects=self.effects,
            run_id=state["run_id"],
            idempotency_key=key,
            inputs=state["inputs"],
            upstream={},
            attempt=1,
            now=self.clock.now(),
            knowledge=self.knowledge,
        )
        result = call_tool(job["tool"], ctx, args)
        if result.committed:
            self._after_remote(state, activity_id)
            self._maybe_crash(state, epoch, activity_id, "after_remote", crash, committed=True, compensation=True)
        if not result.ok:
            self._append(
                state,
                "compensation_failed",
                {"activity_id": activity_id, "error": result.output.get("error", "compensation failed")},
                epoch,
            )
            self._append(
                state,
                "run_status",
                {"status": "compensation_failed", "error": result.output.get("error", "compensation failed")},
                epoch,
            )
            return
        self._append(
            state,
            "compensation_completed",
            {"activity_id": activity_id, "result": result.output, "healed": False},
            epoch,
        )

    def _settle(self, state: dict[str, Any], epoch: int) -> None:
        statuses = [act["status"] for act in state["activities"].values()]
        if any(status == "failed" for status in statuses) and state["status"] not in TERMINAL:
            self._begin_compensation(state, epoch, state["error"] or "activity failed")
            return
        if state["status"] in TERMINAL:
            return
        if any(status in {"pending", "ready", "running", "waiting_retry", "waiting_approval"} for status in statuses):
            self._append(state, "run_status", {"status": "failed", "error": "run stalled"}, epoch)
            return
        self._append(
            state,
            "run_status",
            {"status": "completed", "output": _collect_output(state)},
            epoch,
        )


def _messages(state: dict[str, Any], decision_id: str, definition: dict[str, Any] | None) -> list[dict[str, str]]:
    if decision_id == "plan" or definition is None:
        content: dict[str, Any] = {
            "workflow_id": state["workflow_id"],
            "inputs": state["inputs"],
            "injected_activities": state["inputs"].get("injected_activities") or [],
        }
    else:
        content = {
            "activity_id": definition["id"],
            "tool": definition["tool"],
            "inputs": state["inputs"],
            "template_args": definition.get("args") or {},
            "upstream": {
                dep: {"output": state["activities"][dep]["result"]}
                for dep in definition["deps"]
                if state["activities"][dep]["result"] is not None
            },
        }
    return [
        {"role": "system", "content": "Reply with a JSON object. You are the deterministic Atlas mock model."},
        {"role": "user", "content": json.dumps(content, sort_keys=True, default=str)},
    ]


def _bind_args(state: dict[str, Any], definition: dict[str, Any], completion: dict[str, Any]) -> dict[str, Any]:
    args = _render(definition.get("args") or {}, state)
    model_args = completion.get("args") or {}
    tool = definition["tool"]
    if tool == "http.post":
        for key in ("url", "body"):
            if key in model_args:
                args[key] = model_args[key]
    if tool == "email.send":
        if model_args.get("subject"):
            args["subject"] = _render(str(model_args["subject"]), state)
        if model_args.get("body"):
            args["body"] = _render(str(model_args["body"]), state)
    if tool == "ledger.post":
        quote = state["activities"]["quote_refund"]["result"]
        args = {"customer_id": state["inputs"]["customer_id"], "amount_usd": quote["amount_usd"]}
    if tool == "case.close":
        args = {"case_id": f"case-{state['inputs']['customer_id']}"}
    if tool == "vendor.provision":
        args = {"vendor_id": state["inputs"]["vendor_id"]}
    if tool in {"status.publish", "pager.page", "postmortem.publish", "postmortem.draft"}:
        args = {"incident_id": state["inputs"]["incident_id"]}
    if tool == "sms.send":
        args.setdefault("to", state["inputs"].get("phone", ""))
        args.setdefault("body", "notice")
    return args


def _compensation_args(state: dict[str, Any], activity_id: str, tool: str) -> dict[str, Any]:
    if tool == "ledger.reverse":
        return {
            "customer_id": state["inputs"]["customer_id"],
            "amount_usd": state["activities"]["quote_refund"]["result"]["amount_usd"],
            "reverses": f"{state['run_id']}:{activity_id}",
        }
    if tool == "case.reopen":
        return {"case_id": f"case-{state['inputs']['customer_id']}"}
    if tool == "vendor.deprovision":
        return {"vendor_id": state["inputs"]["vendor_id"]}
    return {}


def _render(value: Any, state: dict[str, Any]) -> Any:
    if isinstance(value, str):
        import re

        def repl(match: re.Match[str]) -> str:
            return str(_lookup(match.group(1), state))

        return re.sub(r"\{\{([^}]+)\}\}", repl, value)
    if isinstance(value, dict):
        return {key: _render(item, state) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, state) for item in value]
    return value


def _lookup(path: str, state: dict[str, Any]) -> Any:
    parts = path.split(".")
    if parts[0] == "input":
        current: Any = state["inputs"]
        parts = parts[1:]
    elif parts[0] == "activity":
        current = state["activities"][parts[1]]["result"] or {}
        parts = parts[3:]
    else:
        raise KeyError(path)
    for part in parts:
        current = current[part]
    return current


def _when(expr: str | None, state: dict[str, Any]) -> bool:
    if not expr or expr == "always":
        return True
    import re

    match = re.fullmatch(r"activity\.([A-Za-z0-9_]+)\.output\.([A-Za-z0-9_]+) == (true|false)", expr)
    if not match:
        raise PlanError(f"unsupported when expression: {expr}")
    result = state["activities"][match.group(1)]["result"] or {}
    return bool(result[match.group(2)]) is (match.group(3) == "true")


def _budget_block(state: dict[str, Any], definition: dict[str, Any]) -> str | None:
    budget = state["budget"]
    if state["steps"] + 1 > int(budget["max_steps"]):
        return f"step budget {budget['max_steps']} would be exceeded"
    projected = money(state["cost_usd"] + float(definition["cost_usd"]))
    if projected > money(float(budget["max_cost_usd"])):
        return f"cost budget {budget['max_cost_usd']} would be exceeded"
    return None


def _next_activity(state: dict[str, Any], now: float) -> str | None:
    for activity_id in state["activity_order"]:
        if state["activities"][activity_id]["status"] == "running":
            return activity_id
    ready: list[str] = []
    for activity_id in state["activity_order"]:
        act = state["activities"][activity_id]
        if act["status"] == "ready" or (
            act["status"] == "waiting_retry" and act.get("retry_at") is not None and act["retry_at"] <= now
        ):
            ready.append(activity_id)
    if not ready:
        return None
    return sorted(ready, key=lambda activity_id: (state["defs"][activity_id]["order"], activity_id))[0]


def _future_retry(state: dict[str, Any], now: float) -> bool:
    return any(
        act["status"] == "waiting_retry" and act.get("retry_at") is not None and act["retry_at"] > now
        for act in state["activities"].values()
    )


def _completed_side_effects(state: dict[str, Any]) -> bool:
    for activity_id, act in state["activities"].items():
        if act["status"] == "completed" and state["defs"][activity_id].get("side_effect"):
            return True
    return False


def _pending_approval(state: dict[str, Any]) -> str | None:
    for activity_id, act in state["activities"].items():
        if act["status"] == "waiting_approval":
            return activity_id
    return None


def _approval_payload(state: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if state["status"] != "paused_approval":
        return None
    for event in reversed(events):
        if event["type"] == "approval_requested":
            return event["payload"]
    return None


def _collect_output(state: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in ("lookup_policy", "policy", "runbook"):
        result = (state["activities"].get(key) or {}).get("result")
        if result:
            output["citations"] = result.get("citations")
            output["refused"] = result.get("refused")
            break
    quote = (state["activities"].get("quote_refund") or {}).get("result") or {}
    if quote.get("amount_usd") is not None:
        output["amount_usd"] = quote["amount_usd"]
    return output


def _waves(state: dict[str, Any]) -> dict[str, int]:
    memo: dict[str, int] = {}

    def walk(activity_id: str) -> int:
        if activity_id in memo:
            return memo[activity_id]
        deps = state["defs"][activity_id]["deps"]
        memo[activity_id] = 0 if not deps else 1 + max(walk(dep) for dep in deps)
        return memo[activity_id]

    for activity_id in state["activity_order"]:
        walk(activity_id)
    return memo
