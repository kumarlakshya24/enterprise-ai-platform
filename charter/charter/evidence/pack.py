"""Build the auditor pack from policies, the registry, and the two stubs.

The pack is a mapping with computed status. It is not a certificate and not a legal opinion.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from charter.config import (
    AUDIT_PATH,
    CASES_PATH,
    CONTROLS_PATH,
    POLICIES_DIR,
    PRICING_PATH,
    REGISTRY_PATH,
    REPORTS_DIR,
    SLO_PATH,
    TENANT,
    WINDOW_END,
    WINDOW_START,
)
from charter.ingest.aegis import AuditSummary, load_audit
from charter.ingest.lens import SloSnapshot, load_slo
from charter.mapping.matrix import Facts, Matrix, build_matrix
from charter.policy.engine import Bundle, Decision, Request, evaluate, load_policies
from charter.policy.syntax import Statement
from charter.registry.cards import Registry, load_registry


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    note: str
    request: Request
    effect: str
    includes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note,
            "request": self.request.as_dict(),
            "expect": {"effect": self.effect, "includes": list(self.includes)},
        }


@dataclass(frozen=True)
class CaseDecision:
    case: Case
    decision: Decision

    def as_dict(self) -> dict[str, object]:
        return {**self.case.as_dict(), "decision": self.decision.as_dict()}


@dataclass(frozen=True)
class GateResult:
    ok: bool
    failures: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "failures": list(self.failures)}


@dataclass(frozen=True)
class Report:
    bundle: Bundle
    registry: Registry
    audit: AuditSummary
    slo: SloSnapshot
    cases: tuple[CaseDecision, ...]
    matrix: Matrix
    gate: GateResult
    weakened: GateResult
    latency: dict[str, float]
    cost: dict[str, object]

    def decision_for(self, case_id: str) -> CaseDecision:
        for item in self.cases:
            if item.case.id == case_id:
                return item
        raise KeyError(case_id)


def load_cases(path: Path = CASES_PATH) -> tuple[Case, ...]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("cases"), list):
        raise ValueError("eval/cases.yaml must contain cases")
    cases: list[Case] = []
    for item in loaded["cases"]:
        if not isinstance(item, dict):
            raise ValueError("case must be a mapping")
        request = item["request"]
        expect = item["expect"]
        includes = expect.get("includes") or []
        cases.append(
            Case(
                id=str(item["id"]),
                title=str(item["title"]),
                note=str(item.get("note") or ""),
                request=Request(
                    principal=str(request["principal"]),
                    model_id=str(request["model"]),
                    purpose=str(request["purpose"]),
                    data_class=str(request["data_class"]),
                    data_residency=str(request["data_residency"]),
                    action=str(request.get("action") or "invoke"),
                    tenant=str(request.get("tenant") or TENANT),
                ),
                effect=str(expect["effect"]),
                includes=tuple(str(rule) for rule in includes),
            )
        )
    return tuple(cases)


def decide_all(bundle: Bundle, registry: Registry, cases: tuple[Case, ...]) -> tuple[CaseDecision, ...]:
    found: list[CaseDecision] = []
    for case in cases:
        card = registry.get(case.request.model_id)
        resource = None if card is None else card.resource()
        found.append(CaseDecision(case, evaluate(bundle, case.request, resource)))
    return tuple(found)


def gate(decisions: tuple[CaseDecision, ...]) -> GateResult:
    failures: list[str] = []
    for item in decisions:
        decision = item.decision
        case = item.case
        if decision.effect != case.effect:
            failures.append(f"{case.id}: effect {decision.effect} != {case.effect} ({decision.primary_rule})")
            continue
        missing = [rule for rule in case.includes if rule not in decision.rule_ids]
        if missing:
            failures.append(f"{case.id}: missing {', '.join(missing)}; got {', '.join(decision.rule_ids)}")
    return GateResult(ok=not failures, failures=tuple(failures))


def _measure(bundle: Bundle, registry: Registry, request: Request, rounds: int = 2000) -> dict[str, float]:
    card = registry.get(request.model_id)
    resource = None if card is None else card.resource()
    samples: list[float] = []
    for _ in range(rounds):
        started = time.perf_counter()
        evaluate(bundle, request, resource)
        samples.append((time.perf_counter() - started) * 1_000_000)
    samples.sort()

    def pct(q: float) -> float:
        index = min(len(samples) - 1, max(0, round(q * (len(samples) - 1))))
        return round(samples[index], 1)

    return {"rounds": float(rounds), "p50_us": pct(0.50), "p95_us": pct(0.95), "p99_us": pct(0.99)}


def _cost() -> dict[str, object]:
    raw = yaml.safe_load(PRICING_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pricing.yaml must be a mapping")
    review = raw["compliance_review"]
    usd = (review["input_tokens"] / 1_000_000) * review["usd_per_million_in"]
    usd += (review["output_tokens"] / 1_000_000) * review["usd_per_million_out"]
    return {
        "charter_usd": 0,
        "projected_llm_review_usd": round(usd, 4),
        "label": "projection",
        "input_tokens": review["input_tokens"],
        "output_tokens": review["output_tokens"],
        "note": str(raw.get("note") or ""),
    }


def build_report(
    *,
    policies_dir: Path = POLICIES_DIR,
    registry_path: Path = REGISTRY_PATH,
    audit_path: Path = AUDIT_PATH,
    slo_path: Path = SLO_PATH,
    controls_path: Path = CONTROLS_PATH,
    measure: bool = True,
) -> Report:
    bundle = load_policies(policies_dir)
    weakened_bundle = load_policies(policies_dir, exclude=frozenset({"002-residency.cedar"}))
    registry = load_registry(registry_path)
    cases = load_cases()
    decisions = decide_all(bundle, registry, cases)
    shipped_gate = gate(decisions)
    weakened = gate(decide_all(weakened_bundle, registry, cases))
    audit = load_audit(audit_path)
    slo = load_slo(slo_path)
    facts = Facts(
        models=registry.models,
        audit=audit,
        slo=slo,
        rule_ids=frozenset(bundle.rule_ids()),
        gate_passed=shipped_gate.ok,
    )
    matrix = build_matrix(facts, controls_path)
    measured_request = next(
        (item.case.request for item in decisions if item.case.id == "eu-support-us"),
        decisions[0].case.request if decisions else None,
    )
    latency = (
        _measure(bundle, registry, measured_request)
        if measure and measured_request is not None
        else {"rounds": 0.0, "p50_us": 0.0, "p95_us": 0.0, "p99_us": 0.0}
    )
    return Report(
        bundle=bundle,
        registry=registry,
        audit=audit,
        slo=slo,
        cases=decisions,
        matrix=matrix,
        gate=shipped_gate,
        weakened=weakened,
        latency=latency,
        cost=_cost(),
    )


def _statement(statement: Statement) -> dict[str, object]:
    return {
        "id": statement.rule_id,
        "effect": statement.effect,
        "controls": list(statement.controls),
        "file": statement.filename,
        "line": statement.line,
        "excerpt": statement.excerpt,
    }


def report_dict(report: Report) -> dict[str, Any]:
    counts = report.matrix.counts()
    gaps = [row.as_dict() for row in report.matrix.rows if row.status == "gap"]
    partials = [row.as_dict() for row in report.matrix.rows if row.status == "partial"]
    return {
        "tenant": TENANT,
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "classification": "synthetic — not a legal opinion and not a certification",
        "policy_digest": report.bundle.digest,
        "policy_files": [{"name": name, "text": text} for name, text in report.bundle.files],
        "rules": [_statement(statement) for statement in report.bundle.statements],
        "models": [card.as_dict() for card in report.registry.models],
        "matrix": report.matrix.as_dict(),
        "gaps": gaps,
        "partials": partials,
        "counts": counts,
        "decisions": [item.as_dict() for item in report.cases],
        "audit": report.audit.as_dict(),
        "slo": report.slo.as_dict(),
        "gate": {"shipped": report.gate.as_dict(), "weakened": report.weakened.as_dict()},
        "latency": report.latency,
        "cost": report.cost,
    }


def evidence_markdown(report: Report) -> str:
    data = report_dict(report)
    counts = data["counts"]
    lines = [
        "# Charter evidence pack",
        "",
        f"Tenant `{TENANT}`. Window {WINDOW_START} → {WINDOW_END}.",
        "",
        "Synthetic data. This pack is a control mapping. It is not a legal opinion and not a certification.",
        "",
        f"Policy digest `{report.bundle.digest[:16]}`.",
        "",
        f"Controls: **{counts['met']} met**, **{counts['partial']} partial**, **{counts['gap']} gap**.",
        "",
        "## Gaps",
        "",
    ]
    for row in data["gaps"]:
        lines.append(f"- **{row['id']} {row['title']}** — {row['because']}")
        lines.append(f"  Treatment: {row['treatment']}")
    lines.extend(["", "## Partials", ""])
    for row in data["partials"]:
        lines.append(f"- **{row['id']} {row['title']}** — {row['because']}")
    lines.extend(["", "## Decisions", ""])
    lines.append("| Case | Effect | Primary rule |")
    lines.append("|---|---|---|")
    for item in report.cases:
        lines.append(f"| `{item.case.id}` | {item.decision.effect} | `{item.decision.primary_rule}` |")
    violation = report.audit.violations[0] if report.audit.violations else None
    lines.extend(["", "## Aegis stub", ""])
    if violation is None:
        lines.append("No residency violation in the routing decisions.")
    else:
        lines.append(
            f"Chain ok: {report.audit.chain_ok}. Events: {len(report.audit.events)}. "
            f"Planted violation `{violation.request_id}` at {violation.ts}: "
            f"{violation.label} on route `{violation.route}` to {violation.region} ({violation.model})."
        )
    quality = report.slo.get("quality")
    lines.extend(["", "## Lens snapshot", ""])
    if quality is not None:
        lines.append(
            f"Quality {quality.status} (SLI {quality.sli:.2f} / {quality.target:.2f}). "
            f"Safety {report.slo.status('safety')}. "
            "These figures are the offline snapshot, not a live Lens export."
        )
    lines.extend(
        [
            "",
            "## Cost",
            "",
            f"Charter provider cost: $0. Projected external review of this pack: "
            f"${report.cost['projected_llm_review_usd']} ({report.cost['note']}).",
            "",
        ]
    )
    return "\n".join(lines)


def summary_markdown(report: Report) -> str:
    counts = report.matrix.counts()
    latency = report.latency
    weakened = "blocked" if not report.weakened.ok else "PASSED (this is a bug)"
    lines = [
        f"Controls: {counts['met']} met, {counts['partial']} partial, {counts['gap']} gap.",
        f"Shipped gate: {'pass' if report.gate.ok else 'FAIL'}.",
        f"Residency file removed: {weakened}.",
        f"Decision p50 {latency['p50_us']} us, p95 {latency['p95_us']} us "
        f"over {int(latency['rounds'])} rounds.",
        f"Audit events {len(report.audit.events)}, chain ok {report.audit.chain_ok}, "
        f"residency violations {len(report.audit.violations)}.",
        f"Provider cost $0. Projected LLM review ${report.cost['projected_llm_review_usd']}.",
        "",
    ]
    if report.gate.failures:
        lines.append("Shipped failures:")
        lines.extend(f"- {item}" for item in report.gate.failures)
    if report.weakened.failures:
        lines.append("Weakened bundle failures (expected):")
        lines.extend(f"- {item}" for item in report.weakened.failures)
    return "\n".join(lines) + "\n"


def write_reports(report: Report, directory: Path = REPORTS_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = report_dict(report)
    (directory / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (directory / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    (directory / "evidence.md").write_text(evidence_markdown(report), encoding="utf-8")
    (directory / "matrix.json").write_text(json.dumps(payload["matrix"], indent=2) + "\n", encoding="utf-8")
