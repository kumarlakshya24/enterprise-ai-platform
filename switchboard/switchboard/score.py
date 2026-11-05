"""Eligibility and selection.

Hard constraints remove models. The policy's selection mode ranks whatever
remains. Weighted scores are always computed so a cheapest or fastest decision
can still show what the blend would have done.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from switchboard.catalog import (
    Catalog,
    estimate_cost,
    estimate_latency_ms,
    required_capability,
)
from switchboard.classify import Features
from switchboard.policy import Constraints, Policy, Rule


@dataclass
class Candidate:
    model: str
    peer: bool
    capability: float
    cost_usd: float
    latency_ms: float
    eligible: bool
    reject_reasons: list[str] = field(default_factory=list)
    cap_score: float | None = None
    cost_score: float | None = None
    lat_score: float | None = None
    total: float | None = None
    selected: bool = False

    def public(self) -> dict[str, object]:
        return {
            "model": self.model,
            "peer": self.peer,
            "capability": round(self.capability, 4),
            "cost_usd": self.cost_usd,
            "latency_ms": round(self.latency_ms, 2),
            "eligible": self.eligible,
            "reject_reasons": list(self.reject_reasons),
            "scores": {
                "capability": self.cap_score,
                "cost": self.cost_score,
                "latency": self.lat_score,
                "total": None if self.total is None else round(self.total, 4),
            },
            "selected": self.selected,
        }


def rule_matches(rule: Rule, features: Features) -> bool:
    when = rule.when
    if "sensitivity_in" in when and features.sensitivity not in when["sensitivity_in"]:
        return False
    if "sensitivity" in when and features.sensitivity != when["sensitivity"]:
        return False
    if "task" in when and features.task != when["task"]:
        return False
    if "task_in" in when and features.task not in when["task_in"]:
        return False
    if "min_complexity" in when and features.complexity + 1e-9 < float(when["min_complexity"]):
        return False
    return not ("latency_sensitivity" in when and features.latency_sensitivity != when["latency_sensitivity"])


def resolve_constraints(
    policy: Policy,
    features: Features,
    catalog: Catalog,
    *,
    budget_usd: float | None,
    latency_slo_ms: float | None,
) -> Constraints:
    """Company policy is a ceiling. A request may tighten budget or SLO, not loosen them."""
    required = required_capability(catalog, features.task, features.complexity)
    budget = policy.budget_usd
    slo = policy.latency_slo_ms
    notes: list[str] = []
    if budget_usd is not None:
        if budget_usd > policy.budget_usd + 1e-12:
            notes.append(
                f"Request budget ${budget_usd:.4f} is above the policy ceiling "
                f"${policy.budget_usd:.4f}; the ceiling stands."
            )
        else:
            budget = budget_usd
            notes.append(f"Request tightened the budget to ${budget:.4f}.")
    if latency_slo_ms is not None:
        if latency_slo_ms > policy.latency_slo_ms + 1e-9:
            notes.append(
                f"Request SLO {latency_slo_ms:.0f} ms is looser than the policy "
                f"{policy.latency_slo_ms:.0f} ms; the policy SLO stands."
            )
        else:
            slo = latency_slo_ms
            notes.append(f"Request tightened the SLO to {slo:.0f} ms.")

    constraints = Constraints(
        budget_usd=budget,
        latency_slo_ms=slo,
        required_capability=required,
        min_quality=policy.min_quality,
        min_headroom=policy.min_headroom,
        notes=notes,
    )
    pins: list[str] = []
    for rule in policy.rules:
        if not rule_matches(rule, features):
            continue
        constraints.applied_rules.append(rule.id)
        if rule.pin:
            pins.append(rule.pin)
            constraints.pin = rule.pin
            constraints.stop_fallback = constraints.stop_fallback or rule.stop_fallback
            for waiver in rule.waive:
                if waiver not in constraints.waivers:
                    constraints.waivers.append(waiver)
            constraints.notes.append(f"{rule.id} pins {rule.pin}. {rule.description.strip()}")
        if rule.exclude:
            constraints.exclude.update(rule.exclude)
            constraints.notes.append(f"{rule.id} excludes {', '.join(rule.exclude)}.")
        if rule.max_latency_ms is not None and rule.max_latency_ms < constraints.latency_slo_ms:
            constraints.latency_slo_ms = rule.max_latency_ms
            constraints.notes.append(f"{rule.id} tightens the SLO to {rule.max_latency_ms:.0f} ms.")
    if len(set(pins)) > 1:
        constraints.notes.append(
            "Conflicting pin rules fired (" + ", ".join(pins) + "). The request will be rejected."
        )
        constraints.pin = None
        constraints.exclude.update(pins)
    return constraints


def build_candidates(
    catalog: Catalog,
    features: Features,
    constraints: Constraints,
    tokens_out: int,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for model_id in catalog.order:
        spec = catalog.model(model_id)
        capability = spec.capability_for(features.task)
        cost = estimate_cost(spec, features.tokens_in, tokens_out)
        latency = estimate_latency_ms(spec, features.tokens_in)
        reasons: list[str] = []
        pinned_here = constraints.pin == model_id
        if constraints.pin and not pinned_here:
            reasons.append(f"pinned away by {', '.join(constraints.applied_rules)}")
        if model_id in constraints.exclude:
            reasons.append("excluded by policy rule")
        if not spec.peer and not pinned_here:
            reasons.append("not a peer; local is a pin or an escape hatch, not a normal candidate")
        waive = set(constraints.waivers) if pinned_here else set()
        if "capability" not in waive and capability + 1e-9 < constraints.required_capability:
            reasons.append(f"capability {capability:.2f} < required {constraints.required_capability:.2f}")
        if "budget" not in waive and cost > constraints.budget_usd + 1e-12:
            reasons.append(f"estimated cost ${cost:.4f} > budget ${constraints.budget_usd:.4f}")
        if "latency" not in waive and latency > constraints.latency_slo_ms + 1e-9:
            reasons.append(f"catalog latency {latency:.0f} ms > SLO {constraints.latency_slo_ms:.0f} ms")
        candidates.append(
            Candidate(
                model=model_id,
                peer=spec.peer,
                capability=capability,
                cost_usd=cost,
                latency_ms=latency,
                eligible=not reasons,
                reject_reasons=reasons,
            )
        )
    _apply_headroom(candidates, constraints)
    _score(candidates, constraints)
    return candidates


def _apply_headroom(candidates: list[Candidate], constraints: Constraints) -> None:
    """Drop models that only barely clear the floor, when a safer one exists.

    If nobody clears required + headroom, keep the models that clear the floor
    and say so. Otherwise a hard prompt whose only capable model sits inside
    the band would be rejected.
    """
    if constraints.min_headroom <= 0:
        return
    band = constraints.required_capability + constraints.min_headroom
    clearing = [item for item in candidates if item.eligible and item.capability + 1e-9 >= band]
    if not clearing:
        constraints.notes.append(
            "Headroom relaxed: no eligible model cleared "
            f"required {constraints.required_capability:.2f} + headroom {constraints.min_headroom:.2f}."
        )
        return
    for item in candidates:
        if not item.eligible or item.capability + 1e-9 >= band:
            continue
        gap = item.capability - constraints.required_capability
        item.eligible = False
        item.reject_reasons.append(
            f"headroom {gap:.2f} < policy {constraints.min_headroom:.2f} "
            "and a model with more room is eligible"
        )


def _relative(value: float, low: float, high: float) -> float:
    if high == low:
        return 1.0
    return 1 - (value - low) / (high - low)


def _score(candidates: list[Candidate], _constraints: Constraints) -> None:
    eligible = [item for item in candidates if item.eligible]
    if not eligible:
        return
    costs = [item.cost_usd for item in eligible]
    lats = [item.latency_ms for item in eligible]
    min_cost, max_cost = min(costs), max(costs)
    min_lat, max_lat = min(lats), max(lats)
    for item in eligible:
        item.cap_score = item.capability
        item.cost_score = _relative(item.cost_usd, min_cost, max_cost)
        item.lat_score = _relative(item.latency_ms, min_lat, max_lat)


def apply_weights(candidates: list[Candidate], policy: Policy) -> None:
    weights = policy.weights
    for item in candidates:
        if not item.eligible or item.cap_score is None or item.cost_score is None or item.lat_score is None:
            item.total = None
            continue
        item.total = (
            weights["capability"] * item.cap_score
            + weights["cost"] * item.cost_score
            + weights["latency"] * item.lat_score
        )


def select(candidates: list[Candidate], policy: Policy) -> Candidate | None:
    apply_weights(candidates, policy)
    eligible = [item for item in candidates if item.eligible]
    if not eligible:
        return None
    if policy.selection == "cheapest":
        key = lambda item: (item.cost_usd, -item.capability, item.latency_ms, item.model)  # noqa: E731
    elif policy.selection == "fastest":
        key = lambda item: (item.latency_ms, -item.capability, item.cost_usd, item.model)  # noqa: E731
    elif policy.selection == "highest_capability":
        key = lambda item: (-item.capability, item.cost_usd, item.latency_ms, item.model)  # noqa: E731
    else:
        key = lambda item: (  # noqa: E731
            -(item.total if item.total is not None else -1),
            item.cost_usd,
            item.latency_ms,
            item.model,
        )
    chosen = sorted(eligible, key=key)[0]
    chosen.selected = True
    return chosen
