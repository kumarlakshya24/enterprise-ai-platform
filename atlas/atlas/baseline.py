"""Single-agent baseline.

Same catalog, same mock model, none of the durability machinery: no event log,
no idempotency key, no approval wait, no compensation, no retry, no budget.
A crash restarts the agent from the first activity, so completed side effects run again.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from atlas.catalog import load_workflow
from atlas.domain import CrashInjected
from atlas.engine import CrashSpec
from atlas.jsonutil import money
from atlas.knowledge import Knowledge
from atlas.llm import LLM
from atlas.store import EffectStore
from atlas.tools import TOOL_META


class BaselineAgent:
    def __init__(self, effects: EffectStore, llm: LLM, knowledge: Knowledge) -> None:
        self.effects = effects
        self.llm = llm
        self.knowledge = knowledge
        self.run_id = "base_" + uuid.uuid4().hex[:12]
        self.steps = 0
        self.cost_usd = 0.0
        self.llm_calls = 0
        self.status = "running"
        self.error: str | None = None
        self.finished: list[str] = []
        self.started_unfinished: list[str] = []
        self.completed_steps_rerun = 0
        self.inflight_steps_rerun = 0
        self.recovery_ms = 0
        self.catch_up_ms = 0
        self._crashed = False
        self._crash_activity: str | None = None

    def run(
        self,
        workflow_id: str,
        inputs: dict[str, Any],
        *,
        crash: CrashSpec | None = None,
        now: float = 0.0,
    ) -> dict[str, Any]:
        replay = self._crashed
        self._crashed = False
        if crash is not None:
            self._crash_activity = crash.activity_id
        crashed_id = self._crash_activity if replay else (crash.activity_id if crash else None)
        workflow = load_workflow(workflow_id)
        activities = sorted(workflow["activities"], key=lambda item: (item["order"], item["id"]))
        catch_up_done = False
        try:
            for definition in activities:
                self._account(definition, replay=replay, catch_up_done=catch_up_done, crashed_id=crashed_id)
                self.llm_calls += 1
                self.llm.complete(
                    [
                        {"role": "system", "content": "single-agent baseline"},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "workflow_id": workflow_id,
                                    "inputs": inputs,
                                    "activity_id": definition["id"],
                                    "tool": definition["tool"],
                                    "template_args": definition.get("args") or {},
                                    "upstream": {},
                                },
                                default=str,
                            ),
                        },
                    ],
                    decision_id=definition["id"],
                )
                if replay and not catch_up_done and definition["id"] == crashed_id:
                    catch_up_done = True
                if definition["tool"] == "approval.gate":
                    self.finished.append(definition["id"])
                    continue
                if definition["tool"] == "lumen.ask":
                    question = definition.get("args", {}).get("question") or inputs.get("policy_question", "")
                    self.knowledge.ask(str(question), principal="baseline")
                    self.finished.append(definition["id"])
                    continue
                if not definition["side_effect"]:
                    self.finished.append(definition["id"])
                    continue
                if crash and crash.activity_id == definition["id"] and crash.phase == "after_intent":
                    self.started_unfinished.append(definition["id"])
                    raise CrashInjected(self.run_id, definition["id"], "after_intent")
                spec = (inputs.get("fail_tools") or {}).get(definition["tool"])
                if spec and spec.get("mode") in {"permanent", "transient", "timeout"}:
                    self.status = "failed"
                    self.error = spec.get("error", spec["mode"])
                    self.started_unfinished.append(definition["id"])
                    return self.report()
                if definition["tool"] == "sms.send" or not definition["idempotent"] or not TOOL_META[definition["tool"]]["idempotent"]:
                    self._raw_effect(definition, inputs, now)
                    self.finished.append(definition["id"])
                    continue
                self._raw_effect(definition, inputs, now)
                if crash and crash.activity_id == definition["id"] and crash.phase == "after_remote":
                    self.finished.append(definition["id"])
                    raise CrashInjected(self.run_id, definition["id"], "after_remote")
                self.finished.append(definition["id"])
        except CrashInjected:
            self._crashed = True
            self.status = "crashed"
            raise
        self.status = "completed"
        return self.report()

    def _account(self, definition: dict[str, Any], *, replay: bool, catch_up_done: bool, crashed_id: str | None) -> None:
        self.steps += 1
        self.cost_usd = money(self.cost_usd + float(definition["cost_usd"]))
        if not replay:
            return
        self.recovery_ms += int(definition["latency_ms"])
        if not catch_up_done:
            self.catch_up_ms += int(definition["latency_ms"])
        if definition["id"] in self.finished:
            self.completed_steps_rerun += 1
        elif definition["id"] in self.started_unfinished:
            self.inflight_steps_rerun += 1

    def _raw_effect(self, definition: dict[str, Any], inputs: dict[str, Any], now: float) -> None:
        """A fresh key every call. The external system cannot dedupe this."""
        tool = definition["tool"]
        payload = _payload(tool, inputs)
        key = f"{self.run_id}:{definition['id']}:{uuid.uuid4().hex}"
        self.effects.commit_effect(
            key=key,
            run_id=self.run_id,
            tool=tool,
            kind=TOOL_META[tool]["kind"],
            payload=payload,
            created_at=now,
        )

    def report(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "status": self.status,
            "steps": self.steps,
            "cost_usd": self.cost_usd,
            "llm_calls": self.llm_calls,
            "effect_counts": self.effects.counts(self.run_id),
            "error": self.error,
            "recovery": {
                "completed_steps_rerun": self.completed_steps_rerun,
                "inflight_steps_rerun": self.inflight_steps_rerun,
                "recovery_ms": self.recovery_ms,
                "catch_up_ms": self.catch_up_ms,
                "crashed_activity": None,
            },
        }


def _payload(tool: str, inputs: dict[str, Any]) -> dict[str, Any]:
    if tool == "ledger.post":
        return {
            "customer_id": inputs.get("customer_id"),
            "amount_usd": inputs.get("amount_usd"),
            "direction": "debit",
            "currency": "USD",
        }
    if tool == "email.send":
        return {"to": inputs.get("email") or inputs.get("vendor_email") or "ap-vendors@acme.example", "subject": "baseline", "body": ""}
    if tool == "case.close":
        return {"case_id": f"case-{inputs.get('customer_id')}", "action": "close"}
    if tool == "http.post":
        return {"url": "https://hook.personal.test/vendor", "body": "bank account 000111222"}
    if tool == "vendor.provision":
        return {"vendor_id": inputs.get("vendor_id"), "action": "provision"}
    if tool == "status.publish":
        return {"incident_id": inputs.get("incident_id"), "state": "investigating"}
    if tool == "pager.page":
        return {"incident_id": inputs.get("incident_id"), "who": "oncall-primary"}
    if tool == "postmortem.publish":
        return {"incident_id": inputs.get("incident_id")}
    if tool == "sms.send":
        return {"to": inputs.get("phone", ""), "body": "notice"}
    return {"tool": tool}
