"""Eval runner. Gold labels live in eval/corpus.yaml. This module does not invent them."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from switchboard.pipeline import RouteRequest, route
from switchboard.provider import Fault
from switchboard.runtime import Runtime
from switchboard.store import percentile

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "eval" / "corpus.yaml"
REPORT_DIR = ROOT / "reports"


@dataclass
class Row:
    case: dict[str, Any]
    decision: dict[str, Any]
    oracle_model: str | None
    heuristic_model: str | None

    @property
    def gold_hit(self) -> bool:
        return (
            self.decision["chosen_model"] == self.case["expected_model"]
            and self.decision["outcome"] == self.case["expected_outcome"]
            and (
                "expected_degraded" not in self.case
                or bool(self.decision["degraded"]) == bool(self.case["expected_degraded"])
            )
        )


def load_corpus(path: Path | None = None) -> dict[str, Any]:
    return yaml.safe_load((path or CORPUS_PATH).read_text())


def oracle_model(decision: dict[str, Any]) -> str | None:
    """Cheapest eligible model under the same constraints the router used.

    Eligibility is the published spec, one implementation. Selection here is
    not the router's: it ignores weights and picks the minimum estimated cost.
    """
    eligible = [item for item in decision["candidates"] if item["eligible"]]
    if not eligible:
        return None
    best = min(eligible, key=lambda item: (item["cost_usd"], -item["capability"], item["model"]))
    return str(best["model"])


def heuristic_model(case: dict[str, Any], decision: dict[str, Any]) -> str | None:
    """A short task map, so the report can show what the floor adds."""
    features = decision["features"]
    if features["sensitivity"] in {"confidential", "restricted"}:
        return "local"
    if case["policy"] == "latency-first" or features["latency_sensitivity"] == "high":
        return "fast-cheap"
    if case["policy"] == "quality-first":
        return "premium"
    if features["task"] in {"code", "math", "extract"}:
        return "balanced" if case["policy"] == "cost-saver" else "premium"
    if case["policy"] == "cost-saver":
        return "fast-cheap"
    return "balanced"


def run_case(runtime: Runtime, case: dict[str, Any]) -> Row:
    fault = Fault(**case["fault"]) if case.get("fault") else None
    decision = route(
        catalog=runtime.catalog,
        policy=runtime.policy(case["policy"]),
        provider=runtime.provider,
        store=None,
        request=RouteRequest(
            prompt=case["prompt"],
            budget_usd=case.get("budget_usd"),
            latency_slo_ms=case.get("latency_slo_ms"),
            fault=fault,
            record=False,
        ),
    )
    return Row(
        case=case,
        decision=decision,
        oracle_model=oracle_model(decision),
        heuristic_model=heuristic_model(case, decision),
    )


def _rate(hits: int, total: int) -> float:
    return 0.0 if total == 0 else hits / total


def summarize(rows: list[Row]) -> dict[str, Any]:
    gold_hits = sum(row.gold_hit for row in rows)
    routed = [row for row in rows if not row.case.get("fault")]
    faults = [row for row in rows if row.case.get("fault")]
    oracle_hits = sum(row.decision["chosen_model"] == row.oracle_model for row in routed)
    heuristic_hits = sum(
        row.heuristic_model == row.case["expected_model"]
        for row in routed
        if row.case["expected_outcome"] != "rejected"
    )
    heuristic_total = sum(row.case["expected_outcome"] != "rejected" for row in routed)
    spend = sum(row.decision["comparison"]["spend_usd"] for row in routed)
    premium = sum(row.decision["comparison"]["always_premium_cost_usd"] for row in routed)
    answered = [row for row in routed if row.decision["chosen_model"]]
    answered_spend = sum(row.decision["comparison"]["spend_usd"] for row in answered)
    answered_premium = sum(row.decision["comparison"]["always_premium_cost_usd"] for row in answered)
    by_policy: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[Row]] = defaultdict(list)
    for row in routed:
        grouped[row.case["policy"]].append(row)
    for name, group in grouped.items():
        hits = sum(row.decision["chosen_model"] == row.oracle_model for row in group)
        gold = sum(row.gold_hit for row in group)
        group_spend = sum(row.decision["comparison"]["spend_usd"] for row in group)
        group_premium = sum(row.decision["comparison"]["always_premium_cost_usd"] for row in group)
        by_policy[name] = {
            "n": len(group),
            "gold_accuracy": round(_rate(gold, len(group)), 4),
            "oracle_agreement": round(_rate(hits, len(group)), 4),
            "spend_usd": round(group_spend, 6),
            "always_premium_cost_usd": round(group_premium, 6),
            "savings_pct": _savings_pct(group_spend, group_premium),
        }
    by_category: dict[str, dict[str, Any]] = {}
    categories: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        categories[row.case["category"]].append(row)
    for name, group in sorted(categories.items()):
        by_category[name] = {
            "n": len(group),
            "gold_accuracy": round(_rate(sum(row.gold_hit for row in group), len(group)), 4),
        }
    misses = [
        {
            "id": row.case["id"],
            "expected_model": row.case["expected_model"],
            "expected_outcome": row.case["expected_outcome"],
            "chosen_model": row.decision["chosen_model"],
            "outcome": row.decision["outcome"],
            "oracle_model": row.oracle_model,
        }
        for row in rows
        if not row.gold_hit
    ]
    disagreements = [
        {
            "id": row.case["id"],
            "policy": row.case["policy"],
            "router": row.decision["chosen_model"],
            "oracle": row.oracle_model,
            "outcome": row.decision["outcome"],
        }
        for row in routed
        if row.decision["chosen_model"] != row.oracle_model
    ]
    overhead = [row.decision["timing"]["router_overhead_ms"] for row in rows]
    fallback_hits = sum(row.gold_hit for row in faults)
    return {
        "n": len(rows),
        "gold_hits": gold_hits,
        "gold_accuracy": round(_rate(gold_hits, len(rows)), 4),
        "routed_n": len(routed),
        "oracle_agreement": round(_rate(oracle_hits, len(routed)), 4),
        "heuristic_accuracy_on_answered_gold": round(_rate(heuristic_hits, heuristic_total), 4),
        "spend_usd": round(spend, 6),
        "always_premium_cost_usd": round(premium, 6),
        "savings_usd": round(premium - spend, 6),
        "savings_pct": _savings_pct(spend, premium),
        "answered_n": len(answered),
        "answered_spend_usd": round(answered_spend, 6),
        "answered_premium_cost_usd": round(answered_premium, 6),
        "answered_savings_pct": _savings_pct(answered_spend, answered_premium),
        "rejected_n": sum(row.decision["outcome"] == "rejected" for row in routed),
        "fallback_n": len(faults),
        "fallback_gold_accuracy": round(_rate(fallback_hits, len(faults)), 4),
        "by_policy": by_policy,
        "by_category": by_category,
        "misses": misses,
        "oracle_disagreements": disagreements,
        "router_overhead_ms": {
            "n": len(overhead),
            "p50": round(percentile(overhead, 50), 3),
            "p95": round(percentile(overhead, 95), 3),
            "note": "Wall clock inside this process, including classification and scoring, excluding catalog model time. n is the corpus, not the bench.",
        },
    }


def _savings_pct(spend: float, premium: float) -> float:
    if premium <= 0:
        return 0.0
    return round(100 * (premium - spend) / premium, 2)


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Switchboard eval",
        "",
        "Generated by `make eval`. Gold labels are in `eval/corpus.yaml`.",
        "",
        f"Cases: **{summary['n']}**. Gold accuracy: **{summary['gold_accuracy'] * 100:.1f}%** "
        f"({summary['gold_hits']}/{summary['n']}).",
        "",
        "The cost-optimal oracle uses the router's eligibility and then picks the cheapest eligible model.",
        "Agreement is expected to be high on `cheapest` and on `weighted` after headroom has removed the borderline model.",
        "It drops on `quality-first`, which is the point of that policy.",
        "",
        "## Cost against always-premium",
        "",
        "Always-premium is the counterfactual catalog price of one Premium call on the same token estimate.",
        "Rejected requests contribute $0 spend and still count the Premium price, so the all-case savings figure",
        "includes requests the latency policy refused. Answered-only savings are the fairer bill comparison.",
        "",
        "| Slice | Spend | Always premium | Savings |",
        "|---|---:|---:|---:|",
        f"| All non-fault cases ({summary['routed_n']}) | ${summary['spend_usd']:.5f} | ${summary['always_premium_cost_usd']:.5f} | {summary['savings_pct']}% |",
        (
            f"| Answered only ({summary['answered_n']}) | ${summary['answered_spend_usd']:.5f} | "
            f"${summary['answered_premium_cost_usd']:.5f} | {summary['answered_savings_pct']}% |"
        ),
        "",
        f"Rejected without a call: {summary['rejected_n']}.",
        f"Fallback slice gold accuracy: {summary['fallback_gold_accuracy'] * 100:.1f}% "
        f"({summary['fallback_n']} injected faults).",
        f"Task-map heuristic vs gold, on non-rejected routed cases: "
        f"{summary['heuristic_accuracy_on_answered_gold'] * 100:.1f}%.",
        "",
        "## By policy",
        "",
        "| Policy | n | Gold | Oracle agreement | Savings vs premium |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, body in summary["by_policy"].items():
        lines.append(
            f"| {name} | {body['n']} | {body['gold_accuracy'] * 100:.1f}% | "
            f"{body['oracle_agreement'] * 100:.1f}% | {body['savings_pct']}% |"
        )
    lines += [
        "",
        "## By category",
        "",
        "| Category | n | Gold |",
        "|---|---:|---:|",
    ]
    for name, body in summary["by_category"].items():
        lines.append(f"| {name} | {body['n']} | {body['gold_accuracy'] * 100:.1f}% |")
    lines += [
        "",
        "## Where the router disagrees with the cheapest eligible model",
        "",
    ]
    if not summary["oracle_disagreements"]:
        lines.append("None on this corpus.")
    else:
        lines += [
            "| Case | Policy | Router | Oracle | Outcome |",
            "|---|---|---|---|---|",
        ]
        for item in summary["oracle_disagreements"]:
            lines.append(
                f"| {item['id']} | {item['policy']} | {item['router']} | {item['oracle']} | {item['outcome']} |"
            )
    if summary["misses"]:
        lines += ["", "## Gold misses", ""]
        for miss in summary["misses"]:
            lines.append(
                f"- `{miss['id']}` expected {miss['expected_outcome']}/{miss['expected_model']}, "
                f"got {miss['outcome']}/{miss['chosen_model']}"
            )
    lines += [
        "",
        "## Router overhead on this run",
        "",
        f"p50 {summary['router_overhead_ms']['p50']} ms, p95 {summary['router_overhead_ms']['p95']} ms. "
        f"{summary['router_overhead_ms']['note']}",
        "",
        "The bench in `reports/latency.md` is the one to quote for overhead. This block is just the corpus.",
        "",
    ]
    return "\n".join(lines)


def evaluate(runtime: Runtime | None = None) -> dict[str, Any]:
    runtime = runtime or _runtime()
    corpus = load_corpus()
    rows = [run_case(runtime, case) for case in corpus["cases"]]
    summary = summarize(rows)
    summary["corpus_version"] = corpus["version"]
    # Keep the candidate trace out of the summary. A compact per-case record is enough.
    summary["cases"] = [
        {
            "id": row.case["id"],
            "category": row.case["category"],
            "policy": row.case["policy"],
            "expected_model": row.case["expected_model"],
            "chosen_model": row.decision["chosen_model"],
            "outcome": row.decision["outcome"],
            "oracle_model": row.oracle_model,
            "heuristic_model": row.heuristic_model,
            "gold_hit": row.gold_hit,
            "task": row.decision["features"]["task"],
            "complexity": row.decision["features"]["complexity"],
            "sensitivity": row.decision["features"]["sensitivity"],
            "spend_usd": row.decision["comparison"]["spend_usd"],
            "always_premium_cost_usd": row.decision["comparison"]["always_premium_cost_usd"],
            "savings_pct": row.decision["comparison"]["savings_pct"],
            "degraded": row.decision["degraded"],
            "router_overhead_ms": row.decision["timing"]["router_overhead_ms"],
        }
        for row in rows
    ]
    return summary


def write_reports(summary: dict[str, Any], directory: Path | None = None) -> Path:
    folder = directory or REPORT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "eval.json").write_text(json.dumps(summary, indent=2) + "\n")
    (folder / "eval.md").write_text(render_markdown(summary))
    return folder / "eval.md"


def _runtime() -> Runtime:
    from switchboard.settings import Settings

    return Runtime(Settings(db_path=":memory:"))
