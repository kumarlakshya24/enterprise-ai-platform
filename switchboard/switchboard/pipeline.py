"""Classify, constrain, score, call, fall back, record."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from switchboard.catalog import (
    Catalog,
    estimate_cost,
    estimate_latency_ms,
    estimate_output_tokens,
)
from switchboard.classify import Features, classify, redact_preview
from switchboard.policy import Policy
from switchboard.provider import Completion, Fault, MockProvider, ProviderError
from switchboard.score import Candidate, build_candidates, resolve_constraints, select
from switchboard.store import Store


@dataclass
class RouteRequest:
    prompt: str
    policy_name: str | None = None
    budget_usd: float | None = None
    latency_slo_ms: float | None = None
    sensitivity: str | None = None
    task: str | None = None
    fault: Fault | None = None
    dry_run: bool = False
    record: bool = True


def route(
    *,
    catalog: Catalog,
    policy: Policy,
    provider: MockProvider,
    store: Store | None,
    request: RouteRequest,
    fault_injection: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    features = classify(request.prompt)
    overrides: list[str] = []
    if request.task and request.task != features.task:
        overrides.append(f"task {features.task} -> {request.task}")
        features.task = request.task
        features.signals.append("override:task")
    if request.sensitivity and request.sensitivity != features.sensitivity:
        overrides.append(f"sensitivity {features.sensitivity} -> {request.sensitivity}")
        features.sensitivity = request.sensitivity
        features.signals.append("override:sensitivity")

    tokens_out = estimate_output_tokens(catalog, features.task, features.tokens_in)
    constraints = resolve_constraints(
        policy,
        features,
        catalog,
        budget_usd=request.budget_usd,
        latency_slo_ms=request.latency_slo_ms,
    )
    candidates = build_candidates(catalog, features, constraints, tokens_out)
    chosen = select(candidates, policy)
    fault = request.fault if fault_injection else None
    fault_note = None
    if request.fault and not fault_injection:
        fault_note = "Fault injection is disabled; the fault on this request was ignored."

    attempts: list[dict[str, Any]] = []
    completion: Completion | None = None
    degraded = False

    if request.dry_run:
        outcome = "rejected" if chosen is None else "dry_run"
    elif constraints.pin and constraints.stop_fallback:
        completion, attempts, degraded, outcome = _call_pinned(
            catalog, provider, features, request.prompt, constraints, candidates, fault
        )
    else:
        completion, attempts, degraded, outcome = _call_with_fallback(
            catalog, provider, policy, features, request.prompt, constraints, candidates, chosen, fault
        )
    for attempt in attempts:
        attempt.pop("_text", None)
    if completion is not None:
        for item in candidates:
            item.selected = item.model == completion.model

    spend = round(sum(float(item["cost_usd"]) for item in attempts if item["status"] != "skipped"), 6)
    premium_cost = _premium_cost(catalog, features, tokens_out)
    simulated = completion.simulated_latency_ms if completion else 0.0
    overhead_ms = round((time.perf_counter() - started) * 1000, 3)
    why = _why(
        features,
        policy,
        constraints,
        candidates,
        chosen,
        attempts,
        outcome,
        degraded,
        overrides,
        fault_note,
        tokens_out,
    )
    record = {
        "id": "dec_" + uuid.uuid4().hex[:12],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dry_run": request.dry_run,
        "outcome": outcome,
        "degraded": degraded,
        "output": (
            None
            if completion is None
            else {"text": completion.text, "model": completion.model, "quality": completion.quality}
        ),
        "features": features.public(tokens_out),
        "policy": {
            "name": policy.name,
            "version": policy.version,
            "version_id": policy.version_id,
            "selection": policy.selection,
        },
        "constraints": constraints.public(),
        "candidates": [item.public() for item in candidates],
        "chosen_model": _chosen_model(completion, chosen, request.dry_run),
        "attempts": attempts,
        "why": why,
        "comparison": _comparison(spend, premium_cost, candidates),
        "timing": {
            "router_overhead_ms": overhead_ms,
            "simulated_latency_ms": simulated,
            "total_estimated_ms": round(overhead_ms + simulated, 3),
        },
        "prompt_preview": redact_preview(request.prompt),
        "prompt_sha256": hashlib.sha256(request.prompt.encode()).hexdigest(),
        "overrides": overrides,
    }
    # Dry-runs still carry the would-be price of the selected model so the UI can
    # compare policies without writing them into the spend totals.
    if request.dry_run and chosen is not None:
        record["comparison"]["spend_usd"] = round(chosen.cost_usd, 6)
        record["comparison"]["savings_usd"] = round(premium_cost - chosen.cost_usd, 6)
        record["comparison"]["savings_pct"] = _pct(premium_cost - chosen.cost_usd, premium_cost)
        record["timing"]["simulated_latency_ms"] = round(chosen.latency_ms, 2)
        record["timing"]["total_estimated_ms"] = round(overhead_ms + chosen.latency_ms, 3)
    if store is not None and request.record and not request.dry_run:
        store.save(record)
    return record


def _call_pinned(
    catalog: Catalog,
    provider: MockProvider,
    features: Features,
    prompt: str,
    constraints: Any,
    candidates: list[Candidate],
    fault: Fault | None,
) -> tuple[Completion | None, list[dict[str, Any]], bool, str]:
    model_id = constraints.pin
    by_id = {item.model: item for item in candidates}
    candidate = by_id.get(model_id)
    if candidate is None or not candidate.eligible:
        reason = "pin target is not eligible" if candidate is None else "; ".join(candidate.reject_reasons)
        return None, [_skipped(model_id or "?", reason)], False, "rejected"
    completion, attempt = _invoke(catalog, provider, features, prompt, model_id, fault, constraints)
    if attempt["status"] == "low_quality" and "quality" in constraints.waivers:
        completion = _completion_from_attempt(model_id, attempt)
        attempt["status"] = "ok"
        attempt["note"] = "quality gate waived by the pin"
    if completion is None:
        return None, [attempt], False, "failed"
    candidate = by_id[model_id]
    degraded = candidate.capability + 1e-9 < constraints.required_capability or (
        float(attempt["quality"]) + 1e-9 < constraints.min_quality
    )
    return completion, [attempt], degraded, "success"


def _call_with_fallback(
    catalog: Catalog,
    provider: MockProvider,
    policy: Policy,
    features: Features,
    prompt: str,
    constraints: Any,
    candidates: list[Candidate],
    chosen: Candidate | None,
    fault: Fault | None,
) -> tuple[Completion | None, list[dict[str, Any]], bool, str]:
    by_id = {item.model: item for item in candidates}
    queue: list[str] = []
    if chosen is not None:
        queue.append(chosen.model)
    for model_id in policy.fallback.order:
        if model_id not in queue:
            queue.append(model_id)
    attempts: list[dict[str, Any]] = []
    calls = 0
    completion: Completion | None = None
    for model_id in queue:
        candidate = by_id[model_id]
        if calls >= policy.fallback.max_attempts:
            attempts.append(_skipped(model_id, "max attempts reached"))
            continue
        if not candidate.eligible:
            attempts.append(_skipped(model_id, "; ".join(candidate.reject_reasons) or "ineligible"))
            continue
        calls += 1
        completion, attempt = _invoke(catalog, provider, features, prompt, model_id, fault, constraints)
        attempts.append(attempt)
        if attempt["status"] == "ok":
            outcome = "success" if calls == 1 else "fallback"
            return completion, attempts, False, outcome
        completion = None
    local_called = any(item["model"] == "local" and item["status"] != "skipped" for item in attempts)
    escape = (
        policy.fallback.allow_local_on_total_failure and calls > 0 and "local" in by_id and not local_called
    )
    if escape:
        calls += 1
        completion, attempt = _invoke(catalog, provider, features, prompt, "local", fault, constraints)
        attempt["escape"] = True
        if attempt["status"] == "low_quality":
            completion = _completion_from_attempt("local", attempt)
            attempt["status"] = "ok"
            attempt["note"] = "local escape accepted below the quality gate; hosted calls had already failed"
        if attempt["status"] == "ok" and completion is not None:
            weak = by_id["local"].capability + 1e-9 < constraints.required_capability
            low = float(attempt["quality"]) + 1e-9 < constraints.min_quality
            if weak or low:
                attempt["note"] = "local escape returned a degraded answer; hosted calls had already failed"
            attempts.append(attempt)
            return completion, attempts, weak or low, "fallback"
        attempts.append(attempt)
    real = any(item["status"] != "skipped" for item in attempts)
    return None, attempts, False, "failed" if real else "rejected"


def _invoke(
    catalog: Catalog,
    provider: MockProvider,
    features: Features,
    prompt: str,
    model_id: str,
    fault: Fault | None,
    constraints: Any,
) -> tuple[Completion | None, dict[str, Any]]:
    spec = catalog.model(model_id)
    tokens_out = estimate_output_tokens(catalog, features.task, features.tokens_in)
    try:
        completion = provider.complete(model_id, features, prompt, fault)
    except ProviderError as exc:
        cost = estimate_cost(spec, features.tokens_in, tokens_out, output=False)
        return None, {
            "model": model_id,
            "status": exc.kind,
            "quality": None,
            "cost_usd": round(cost, 6),
            "simulated_latency_ms": round(estimate_latency_ms(spec, features.tokens_in), 2),
            "reason": f"mock {exc.kind}",
        }
    full_cost = estimate_cost(spec, features.tokens_in, tokens_out, output=True)
    if completion.quality + 1e-9 < constraints.min_quality and "quality" not in set(constraints.waivers):
        return None, {
            "model": model_id,
            "status": "low_quality",
            "quality": completion.quality,
            "cost_usd": round(full_cost, 6),
            "simulated_latency_ms": completion.simulated_latency_ms,
            "reason": (
                f"quality {completion.quality:.2f} < gate {constraints.min_quality:.2f}; "
                "billed as a completed generation"
            ),
            "_text": completion.text,
        }
    return completion, {
        "model": model_id,
        "status": "ok",
        "quality": completion.quality,
        "cost_usd": round(full_cost, 6),
        "simulated_latency_ms": completion.simulated_latency_ms,
        "reason": "accepted",
    }


def _chosen_model(completion: Completion | None, chosen: Candidate | None, dry_run: bool) -> str | None:
    if completion is not None:
        return completion.model
    if dry_run and chosen is not None:
        return chosen.model
    return None


def _completion_from_attempt(model_id: str, attempt: dict[str, Any]) -> Completion:
    return Completion(
        model=model_id,
        text=str(attempt.get("_text") or ""),
        quality=float(attempt["quality"]),
        simulated_latency_ms=float(attempt["simulated_latency_ms"]),
    )


def _skipped(model_id: str, reason: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "status": "skipped",
        "quality": None,
        "cost_usd": 0.0,
        "simulated_latency_ms": None,
        "reason": reason,
    }


def _premium_cost(catalog: Catalog, features: Features, tokens_out: int) -> float:
    return round(estimate_cost(catalog.model("premium"), features.tokens_in, tokens_out), 6)


def _comparison(spend: float, premium_cost: float, candidates: list[Candidate]) -> dict[str, Any]:
    premium = next(item for item in candidates if item.model == "premium")
    savings = premium_cost - spend
    return {
        "spend_usd": round(spend, 6),
        "always_premium_cost_usd": premium_cost,
        "savings_usd": round(savings, 6),
        "savings_pct": _pct(savings, premium_cost),
        "premium_eligible": premium.eligible,
    }


def _pct(savings: float, premium: float) -> float:
    if premium <= 0:
        return 0.0
    return round(100 * savings / premium, 2)


def _why(
    features: Features,
    policy: Policy,
    constraints: Any,
    candidates: list[Candidate],
    chosen: Candidate | None,
    attempts: list[dict[str, Any]],
    outcome: str,
    degraded: bool,
    overrides: list[str],
    fault_note: str | None,
    tokens_out: int,
) -> list[str]:
    lines = [
        (
            f"Classified as {features.task}, complexity {features.complexity:.2f}, "
            f"sensitivity {features.sensitivity}, latency sensitivity {features.latency_sensitivity}. "
            f"About {features.tokens_in} input tokens and {tokens_out} output tokens. "
            f"Signals: {', '.join(features.signals)}."
        )
    ]
    if overrides:
        lines.append("Overrides: " + "; ".join(overrides) + ".")
    lines.append(
        f"Policy {policy.version_id}, selection {policy.selection}, "
        f"weights capability {policy.weights['capability']:.2f} / "
        f"cost {policy.weights['cost']:.2f} / latency {policy.weights['latency']:.2f}. "
        f"Budget ${constraints.budget_usd:.4f}, SLO {constraints.latency_slo_ms:.0f} ms, "
        f"capability floor {constraints.required_capability:.2f}, "
        f"headroom {constraints.min_headroom:.2f}, "
        f"quality gate {constraints.min_quality:.2f}."
    )
    lines.extend(constraints.notes)
    eligible = [item.model for item in candidates if item.eligible]
    rejected = [
        f"{item.model} ({'; '.join(item.reject_reasons)})" for item in candidates if not item.eligible
    ]
    lines.append(
        "Eligible: " + (", ".join(eligible) if eligible else "none") + ". "
        "Out: " + ("; ".join(rejected) if rejected else "none") + "."
    )
    if chosen is not None:
        ranked = sorted(
            (item for item in candidates if item.eligible and item.total is not None),
            key=lambda item: item.total or 0,
            reverse=True,
        )
        blend = ", ".join(f"{item.model} {item.total:.3f}" for item in ranked)
        lines.append(
            f"Selection {policy.selection} picked {chosen.model} "
            f"(capability {chosen.capability:.2f}, catalog {chosen.latency_ms:.0f} ms, "
            f"${chosen.cost_usd:.5f}). Weighted ranking: {blend or 'n/a'}."
        )
    else:
        lines.append("No model cleared the constraints, so nothing was called.")
    for attempt in attempts:
        if attempt["status"] == "skipped":
            continue
        lines.append(
            f"Attempt {attempt['model']}: {attempt['status']} "
            f"(${attempt['cost_usd']:.5f}). {attempt.get('reason') or attempt.get('note') or ''}"
        )
    if degraded:
        lines.append("The answer is marked degraded: it missed the capability floor or the quality gate.")
    if fault_note:
        lines.append(fault_note)
    lines.append(f"Outcome: {outcome}.")
    return lines
