"""Tool implementations.

Side effects go to the effect store (a separate SQLite file) under an idempotency key.
Money amounts are not taken from the model. The engine binds them from upstream results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from atlas.knowledge import REFUSAL, Knowledge
from atlas.store import EffectStore

TOOL_META: dict[str, dict[str, Any]] = {
    "lumen.ask": {"idempotent": True, "side_effect": False, "kind": "read"},
    "finance.quote": {"idempotent": True, "side_effect": False, "kind": "pure"},
    "approval.gate": {"idempotent": True, "side_effect": False, "kind": "control"},
    "ledger.post": {"idempotent": True, "side_effect": True, "kind": "debit"},
    "ledger.reverse": {"idempotent": True, "side_effect": True, "kind": "credit"},
    "email.send": {"idempotent": True, "side_effect": True, "kind": "email"},
    "case.close": {"idempotent": True, "side_effect": True, "kind": "case"},
    "case.reopen": {"idempotent": True, "side_effect": True, "kind": "case"},
    "http.post": {"idempotent": True, "side_effect": True, "kind": "webhook"},
    "vendor.provision": {"idempotent": True, "side_effect": True, "kind": "provision"},
    "vendor.deprovision": {"idempotent": True, "side_effect": True, "kind": "provision"},
    "status.publish": {"idempotent": True, "side_effect": True, "kind": "status"},
    "pager.page": {"idempotent": True, "side_effect": True, "kind": "page"},
    "postmortem.draft": {"idempotent": True, "side_effect": False, "kind": "pure"},
    "postmortem.publish": {"idempotent": True, "side_effect": True, "kind": "postmortem"},
    "sms.send": {"idempotent": False, "side_effect": True, "kind": "sms"},
}


@dataclass
class ToolContext:
    effects: EffectStore
    run_id: str
    idempotency_key: str
    inputs: dict[str, Any]
    upstream: dict[str, Any]
    attempt: int
    now: float
    knowledge: Knowledge


@dataclass
class ToolResult:
    ok: bool
    permanent: bool = False
    output: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 5
    committed: bool = False


def call_tool(name: str, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    spec = _failure_spec(ctx, name)
    if spec is not None and spec.get("mode") == "permanent":
        return ToolResult(ok=False, permanent=True, output={"error": spec.get("error", "permanent failure")})
    if spec is not None and spec.get("mode") == "transient":
        return ToolResult(ok=False, permanent=False, output={"error": spec.get("error", "transient failure")})
    if spec is not None and spec.get("mode") == "timeout":
        return ToolResult(
            ok=False,
            permanent=False,
            output={"error": "deadline exceeded before the remote call"},
            elapsed_ms=int(spec.get("elapsed_ms", 10_000)),
            committed=False,
        )
    handler = _HANDLERS.get(name)
    if handler is None:
        return ToolResult(ok=False, permanent=True, output={"error": f"unknown tool {name}"})
    return handler(ctx, args)


def _failure_spec(ctx: ToolContext, name: str) -> dict[str, Any] | None:
    spec = (ctx.inputs.get("fail_tools") or {}).get(name)
    if not spec:
        return None
    times = int(spec.get("times", 1))
    if ctx.attempt <= times:
        return spec
    return None


def _once(ctx: ToolContext, tool: str, kind: str, payload: dict[str, Any]) -> ToolResult:
    row, created = ctx.effects.commit_effect(
        key=ctx.idempotency_key,
        run_id=ctx.run_id,
        tool=tool,
        kind=kind,
        payload=payload,
        created_at=ctx.now,
    )
    output = dict(row["payload"])
    output["effect_key"] = row["effect_key"]
    output["replayed"] = not created
    return ToolResult(ok=True, output=output, committed=True, elapsed_ms=5)


def _lumen(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    question = str(args["question"])
    answer = ctx.knowledge.ask(question, principal=str(ctx.inputs.get("principal", "atlas-worker")))
    return ToolResult(ok=True, output=answer, elapsed_ms=8)


def _quote(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    del args
    policy = ctx.upstream.get("lookup_policy") or {}
    if policy.get("refused"):
        return ToolResult(
            ok=False,
            permanent=True,
            output={"error": REFUSAL, "refused": True},
        )
    text = str(policy.get("answer") or "")
    max_match = re.search(r"up to \$([0-9]+(?:\.[0-9]+)?)", text)
    above_match = re.search(r"above \$([0-9]+(?:\.[0-9]+)?)", text)
    if not max_match or not above_match:
        return ToolResult(ok=False, permanent=True, output={"error": "policy text has no refund limits"})
    cap = float(max_match.group(1))
    threshold = float(above_match.group(1))
    requested = float(ctx.inputs["amount_usd"])
    amount = min(requested, cap)
    return ToolResult(
        ok=True,
        output={
            "amount_usd": amount,
            "requested_usd": requested,
            "capped": amount < requested,
            "approval_required": amount > threshold,
            "policy_doc": (policy.get("citations") or [{}])[0].get("doc_id"),
        },
    )


def _ledger_post(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(
        ctx,
        "ledger.post",
        "debit",
        {
            "customer_id": args["customer_id"],
            "amount_usd": args["amount_usd"],
            "direction": "debit",
            "currency": "USD",
        },
    )


def _ledger_reverse(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(
        ctx,
        "ledger.reverse",
        "credit",
        {
            "customer_id": args["customer_id"],
            "amount_usd": args["amount_usd"],
            "direction": "credit",
            "currency": "USD",
            "reverses": args.get("reverses"),
        },
    )


def _email(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(
        ctx,
        "email.send",
        "email",
        {"to": args["to"], "subject": args["subject"], "body": args.get("body", "")},
    )


def _case_close(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "case.close", "case", {"case_id": args["case_id"], "action": "close"})


def _case_reopen(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "case.reopen", "case", {"case_id": args["case_id"], "action": "reopen"})


def _http(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "http.post", "webhook", {"url": args["url"], "body": args.get("body", "")})


def _provision(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "vendor.provision", "provision", {"vendor_id": args["vendor_id"], "action": "provision"})


def _deprovision(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(
        ctx, "vendor.deprovision", "provision", {"vendor_id": args["vendor_id"], "action": "deprovision"}
    )


def _status(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "status.publish", "status", {"incident_id": args["incident_id"], "state": "investigating"})


def _page(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "pager.page", "page", {"incident_id": args["incident_id"], "who": "oncall-primary"})


def _draft(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    del args
    return ToolResult(ok=True, output={"draft": "Timeline, impact, and follow-ups."})


def _publish(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return _once(ctx, "postmortem.publish", "postmortem", {"incident_id": args["incident_id"]})


def _sms(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    # Reached only if a caller bypasses the engine's idempotency refusal.
    return _once(ctx, "sms.send", "sms", {"to": args.get("to", ""), "body": args.get("body", "")})


_HANDLERS = {
    "lumen.ask": _lumen,
    "finance.quote": _quote,
    "ledger.post": _ledger_post,
    "ledger.reverse": _ledger_reverse,
    "email.send": _email,
    "case.close": _case_close,
    "case.reopen": _case_reopen,
    "http.post": _http,
    "vendor.provision": _provision,
    "vendor.deprovision": _deprovision,
    "status.publish": _status,
    "pager.page": _page,
    "postmortem.draft": _draft,
    "postmortem.publish": _publish,
    "sms.send": _sms,
}
