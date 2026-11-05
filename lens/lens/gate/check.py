"""CI gate. Compares one candidate's judge scores to the locked baseline on the frozen gold set.

Production drift pages a human. It does not, by itself, fail a deploy: a bad hour in
prod is not a property of the artifact under review. The gate fails the artifact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from lens.models import Verdict


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    detail: str


@dataclass
class GateResult:
    name: str
    passed: bool
    rules: list[RuleResult] = field(default_factory=list)
    safety_regressions: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    flips: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "rules": [
                {"rule_id": rule.rule_id, "passed": rule.passed, "detail": rule.detail} for rule in self.rules
            ],
            "safety_regressions": list(self.safety_regressions),
            "metrics": dict(self.metrics),
            "baseline_metrics": dict(self.baseline_metrics),
            "flips": list(self.flips),
        }


def _rate(flags: list[bool]) -> float:
    if not flags:
        return 1.0
    return sum(1 for flag in flags if flag) / len(flags)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return float(ordered[rank])


def score_metrics(
    verdicts: list[Verdict],
    latencies: list[int],
    safety_critical: list[bool],
) -> dict[str, float]:
    safe_flags = [
        verdict.safe for verdict, critical in zip(verdicts, safety_critical, strict=True) if critical
    ]
    return {
        "n": float(len(verdicts)),
        "pass_rate": _rate([verdict.passed for verdict in verdicts]),
        "faithfulness_rate": _rate([verdict.faithful for verdict in verdicts]),
        "relevance_rate": _rate([verdict.relevant for verdict in verdicts]),
        "safety_rate": _rate(safe_flags),
        "refusal_correct_rate": _rate([verdict.refusal_correct for verdict in verdicts]),
        "latency_p50_ms": percentile([float(v) for v in latencies], 0.50),
        "latency_p95_ms": percentile([float(v) for v in latencies], 0.95),
    }


def evaluate_gate(
    *,
    name: str,
    ids: list[str],
    baseline: list[Verdict],
    candidate: list[Verdict],
    baseline_latency: list[int],
    candidate_latency: list[int],
    safety_critical: list[bool],
    kappa: float,
    config: dict[str, Any],
) -> GateResult:
    base_metrics = score_metrics(baseline, baseline_latency, safety_critical)
    cand_metrics = score_metrics(candidate, candidate_latency, safety_critical)
    rules: list[RuleResult] = []

    def drop(rule_id: str, metric: str, limit: float) -> None:
        delta = base_metrics[metric] - cand_metrics[metric]
        ok = delta <= limit + 1e-12
        rules.append(
            RuleResult(
                rule_id,
                ok,
                f"{metric} baseline {base_metrics[metric]:.4f} candidate {cand_metrics[metric]:.4f} drop {delta:.4f} limit {limit:.4f}",
            )
        )

    drop("pass_rate", "pass_rate", float(config["max_pass_drop"]))
    drop("faithfulness", "faithfulness_rate", float(config["max_faithfulness_drop"]))

    floor = float(config["min_safety_rate"])
    safety_ok = cand_metrics["safety_rate"] + 1e-12 >= floor
    rules.append(
        RuleResult(
            "safety_floor",
            safety_ok,
            f"safety_rate {cand_metrics['safety_rate']:.4f} floor {floor:.4f}",
        )
    )

    regressions: list[str] = []
    flips: list[dict[str, str]] = []
    for item_id, base, cand, critical in zip(ids, baseline, candidate, safety_critical, strict=True):
        if critical and base.safe and not cand.safe:
            regressions.append(item_id)
        if base.passed and not cand.passed:
            flips.append(
                {
                    "id": item_id,
                    "reasons": ",".join(cand.reasons),
                    "kind": "safety" if critical else "quality",
                }
            )
    rules.append(
        RuleResult(
            "safety_no_new_failures",
            not regressions,
            "new unsafe ids: " + (", ".join(regressions) if regressions else "none"),
        )
    )

    ratio_limit = float(config["max_latency_p95_ratio"])
    base_p95 = base_metrics["latency_p95_ms"]
    cand_p95 = cand_metrics["latency_p95_ms"]
    ratio = cand_p95 / base_p95 if base_p95 else 1.0
    rules.append(
        RuleResult(
            "latency_p95",
            ratio <= ratio_limit + 1e-12,
            f"p95 {cand_p95:.1f}ms / baseline {base_p95:.1f}ms = {ratio:.3f} limit {ratio_limit:.2f}",
        )
    )

    kappa_floor = float(config["min_kappa"])
    rules.append(
        RuleResult(
            "judge_kappa",
            kappa + 1e-12 >= kappa_floor,
            f"kappa {kappa:.4f} floor {kappa_floor:.2f}",
        )
    )

    return GateResult(
        name=name,
        passed=all(rule.passed for rule in rules),
        rules=rules,
        safety_regressions=regressions,
        metrics=cand_metrics,
        baseline_metrics=base_metrics,
        flips=flips,
    )
