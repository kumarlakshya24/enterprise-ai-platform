"""Turn registry, audit, SLO, and policy facts into a control matrix.

Status is computed. The catalog supplies the words and the treatment.
A control id with no rule function is `unmapped`, and the report refuses to
call that a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from charter.ingest.aegis import AuditSummary
from charter.ingest.lens import SloSnapshot
from charter.registry.cards import ModelCard


@dataclass(frozen=True)
class ControlResult:
    status: str
    because: str


@dataclass(frozen=True)
class ControlRow:
    id: str
    framework: str
    ref: str
    title: str
    statement: str
    treatment: str
    status: str
    because: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "framework": self.framework,
            "ref": self.ref,
            "title": self.title,
            "statement": self.statement,
            "treatment": self.treatment,
            "status": self.status,
            "because": self.because,
        }


@dataclass(frozen=True)
class Matrix:
    rows: tuple[ControlRow, ...]

    def counts(self) -> dict[str, int]:
        counts = {"met": 0, "partial": 0, "gap": 0, "unmapped": 0}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts

    def by_id(self, control_id: str) -> ControlRow:
        for row in self.rows:
            if row.id == control_id:
                return row
        raise KeyError(control_id)

    def as_dict(self) -> dict[str, object]:
        return {"counts": self.counts(), "controls": [row.as_dict() for row in self.rows]}


@dataclass(frozen=True)
class Facts:
    models: tuple[ModelCard, ...]
    audit: AuditSummary
    slo: SloSnapshot
    rule_ids: frozenset[str]
    gate_passed: bool

    def active(self) -> tuple[ModelCard, ...]:
        return tuple(card for card in self.models if card.status == "active")


Rule = Callable[[Facts], ControlResult]

_ENFORCEABLE = frozenset(
    {"R-PROHIBITED", "R-RESIDENCY-EU", "R-CARD-INCOMPLETE", "R-OVERSIGHT", "R-RESTRICTED-BLOCK"}
)


def _met(because: str) -> ControlResult:
    return ControlResult("met", because)


def _partial(because: str) -> ControlResult:
    return ControlResult("partial", because)


def _gap(because: str) -> ControlResult:
    return ControlResult("gap", because)


def _eu5(facts: Facts) -> ControlResult:
    active_bad = [card.id for card in facts.active() if card.risk_tier == "unacceptable"]
    if active_bad:
        return _gap(f"Active models with an unacceptable tier: {', '.join(active_bad)}.")
    if "R-PROHIBITED" not in facts.rule_ids:
        return _gap("No active prohibited model, and the policy is missing R-PROHIBITED.")
    proposed = [card.id for card in facts.models if card.risk_tier == "unacceptable"]
    named = ", ".join(proposed) if proposed else "none"
    return _met(f"No active model is unacceptable. Proposed and blocked by R-PROHIBITED: {named}.")


def _eu9(facts: Facts) -> ControlResult:
    if "R-RESIDENCY-EU" not in facts.rule_ids:
        return _gap("The risk treatment for residency is not in the policy bundle.")
    if not facts.gate_passed:
        return _partial("Policies exist, but the regression gate does not pass.")
    return _met("Versioned policies pass the locked decision cases, including the residency forbid.")


def _eu10(facts: Facts) -> ControlResult:
    if not facts.audit.violations:
        return _met("No EU confidential or restricted routing decision left the EU region.")
    first = facts.audit.violations[0]
    return _gap(
        f"{len(facts.audit.violations)} Aegis routing decision sent EU {first.label} data "
        f"on route {first.route} to {first.region} ({first.model}, {first.request_id}). "
        "Redaction of the card is not a residency control."
    )


def _documented(card: ModelCard) -> bool:
    return bool(
        card.card_complete
        and card.intended_use
        and card.out_of_scope
        and card.known_limitations
        and card.training_data
    )


def _eu11(facts: Facts) -> ControlResult:
    missing = [card.id for card in facts.active() if not _documented(card)]
    if missing:
        return _partial(f"Active models with an incomplete card: {', '.join(missing)}.")
    if "R-CARD-INCOMPLETE" not in facts.rule_ids:
        return _partial("Active cards are complete. Nothing denies an incomplete card at invocation.")
    return _met(
        "Every active model card has use, limits, training notes, and an owner. R-CARD-INCOMPLETE is loaded."
    )


def _eu12(facts: Facts) -> ControlResult:
    if not facts.audit.chain_ok:
        return _gap(f"Audit chain does not verify: {facts.audit.chain_error}.")
    if not facts.audit.events:
        return _gap("Audit log is empty.")
    return _met(
        f"HMAC chain verifies across {len(facts.audit.events)} Aegis-shaped events "
        f"({facts.audit.by_type.get('routing_decision', 0)} routing decisions)."
    )


def _eu13(facts: Facts) -> ControlResult:
    missing = [card.id for card in facts.active() if not card.intended_use or not card.out_of_scope]
    if missing:
        return _gap(f"Active models missing intended use or out-of-scope: {', '.join(missing)}.")
    return _met("Every active model card states intended use and what it must not be used for.")


def _eu14(facts: Facts) -> ControlResult:
    blind = [card.id for card in facts.active() if card.risk_tier == "high" and not card.human_oversight]
    if blind:
        extra = ""
        if "R-OVERSIGHT" in facts.rule_ids:
            extra = " R-OVERSIGHT denies invocation. The deployment is still active."
        return _gap(f"Active high-risk models with no human oversight: {', '.join(blind)}.{extra}")
    return _met("Every active high-risk model card has human oversight.")


def _eu15(facts: Facts) -> ControlResult:
    quality = facts.slo.get("quality")
    safety = facts.slo.get("safety")
    if quality is None or safety is None:
        return _gap("Lens quality or safety objective is missing.")
    if quality.status == "page":
        return _gap(
            f"Lens quality is paging (SLI {quality.sli:.2f} vs target {quality.target:.2f}, "
            f"6h burn {quality.burn_6h:.1f}×). Article 15 accuracy is not met. "
            f"Safety is {safety.status} (SLI {safety.sli:.4f})."
        )
    if quality.status != "within_budget" or safety.status != "within_budget":
        return _partial(f"Quality is {quality.status} and safety is {safety.status}.")
    return _met("Lens quality and safety are both within budget.")


def _eu26(facts: Facts) -> ControlResult:
    blind = [card.id for card in facts.active() if card.risk_tier == "high" and not card.human_oversight]
    if not facts.audit.chain_ok and blind:
        return _gap("Deployer log does not verify and a high-risk model has no oversight.")
    if not facts.audit.chain_ok:
        return _gap("Deployer log does not verify.")
    if blind:
        return _partial(
            f"Logging verifies. Oversight does not: {', '.join(blind)} is active high-risk with no reviewer."
        )
    return _met("The audit chain verifies and every active high-risk model has a reviewer.")


def _gv11(facts: Facts) -> ControlResult:
    missing = sorted(_ENFORCEABLE - facts.rule_ids)
    if not missing:
        return _met("Each enforceable article in this catalog is named by a policy rule.")
    if len(missing) == len(_ENFORCEABLE):
        return _gap("No enforceable rule is linked to the catalog.")
    return _partial(f"Policy is missing {', '.join(missing)}.")


def _gv61(facts: Facts) -> ControlResult:
    hosted = [card for card in facts.active() if card.provider == "hosted"]
    if not hosted:
        return _met("No active model is hosted by a third party.")
    unreviewed = [card.id for card in hosted if not card.provider_reviewed]
    if unreviewed:
        return _partial(f"Active hosted models with no provider review: {', '.join(unreviewed)}.")
    return _met("Every active hosted model is marked provider-reviewed.")


def _mp11(facts: Facts) -> ControlResult:
    missing = [card.id for card in facts.active() if not card.intended_use or not card.purpose]
    if missing:
        return _gap(f"Active models missing a purpose: {', '.join(missing)}.")
    return _met("Every active model has an intended use and a single approved purpose.")


def _ms11(facts: Facts) -> ControlResult:
    needed = ("availability", "latency", "quality", "safety")
    missing = [item for item in needed if facts.slo.get(item) is None]
    if missing:
        return _gap(f"SLO snapshot is missing {', '.join(missing)}.")
    bits = []
    for item in needed:
        objective = facts.slo.get(item)
        if objective is None:
            return _gap(f"SLO snapshot is missing {item}.")
        bits.append(f"{item} {objective.target:.3g}")
    return _met("Lens targets are present: " + ", ".join(bits) + ".")


def _ms26(facts: Facts) -> ControlResult:
    safety = facts.slo.get("safety")
    if safety is None:
        return _gap("No safety objective in the Lens snapshot.")
    if safety.status == "page":
        return _gap(f"Safety SLO is paging (SLI {safety.sli:.4f} vs {safety.target:.3f}).")
    if safety.status == "ticket":
        return _partial(
            f"Safety SLO is on a ticket (SLI {safety.sli:.4f} vs {safety.target:.3f}, "
            f"6h burn {safety.burn_6h:.1f}x)."
        )
    return _met(f"Safety SLO is within budget (SLI {safety.sli:.4f}).")


def _ms27(facts: Facts) -> ControlResult:
    if not facts.audit.chain_ok:
        return _gap("Cannot use the audit log as a security evaluation while the chain is broken.")
    has_dlp = facts.audit.by_type.get("dlp_redaction", 0) > 0
    has_block = (
        facts.audit.by_type.get("request_blocked", 0) + facts.audit.by_type.get("tool_call_blocked", 0) > 0
    )
    if has_dlp and has_block:
        return _met("The stub records DLP outcomes and at least one blocked request or tool call.")
    return _partial("The chain verifies, but the stub has no DLP event or no block.")


def _mg22(facts: Facts) -> ControlResult:
    # Treatment text is checked by the builder. This rule only reflects the gate.
    if facts.gate_passed:
        return _met("Every gap and partial in this pack has a treatment, and the decision gate passes.")
    return _partial(
        "Treatments are written. The decision gate does not pass, so the treatment is not in force."
    )


def _mg41(facts: Facts) -> ControlResult:
    noisy = [item.id for item in facts.slo.objectives if item.status in ("page", "ticket")]
    if not facts.slo.objectives:
        return _gap("No post-deployment objectives were provided.")
    if noisy:
        return _partial(f"Monitoring is on. Not quiet: {', '.join(noisy)}.")
    return _met("Availability, latency, quality, and safety are all within budget.")


RULES: dict[str, Rule] = {
    "EU-5": _eu5,
    "EU-9": _eu9,
    "EU-10": _eu10,
    "EU-11": _eu11,
    "EU-12": _eu12,
    "EU-13": _eu13,
    "EU-14": _eu14,
    "EU-15": _eu15,
    "EU-26": _eu26,
    "NIST-GV-1.1": _gv11,
    "NIST-GV-6.1": _gv61,
    "NIST-MP-1.1": _mp11,
    "NIST-MS-1.1": _ms11,
    "NIST-MS-2.6": _ms26,
    "NIST-MS-2.7": _ms27,
    "NIST-MG-2.2": _mg22,
    "NIST-MG-4.1": _mg41,
}


def _catalog(path: Path) -> list[dict[str, str]]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("controls"), list):
        raise ValueError(f"{path} must contain controls")
    rows: list[dict[str, str]] = []
    for item in loaded["controls"]:
        if not isinstance(item, dict):
            raise ValueError("control must be a mapping")
        row: dict[str, str] = {}
        for key in ("id", "framework", "ref", "title", "statement", "treatment"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"control {item.get('id')} is missing {key}")
            row[key] = value.strip()
        rows.append(row)
    return rows


def build_matrix(facts: Facts, catalog_path: Path) -> Matrix:
    catalog = _catalog(catalog_path)
    rows: list[ControlRow] = []
    for item in catalog:
        rule = RULES.get(item["id"])
        if rule is None:
            result = ControlResult("unmapped", "No status rule is implemented for this control.")
        else:
            result = rule(facts)
        if not item["treatment"]:
            result = ControlResult("gap", "Treatment text is empty.")
        rows.append(
            ControlRow(
                id=item["id"],
                framework=item["framework"],
                ref=item["ref"],
                title=item["title"],
                statement=item["statement"],
                treatment=item["treatment"],
                status=result.status,
                because=result.because,
            )
        )
    return Matrix(tuple(rows))


def catalog_ids(path: Path) -> list[str]:
    return [item["id"] for item in _catalog(path)]


def unimplemented(path: Path) -> list[str]:
    return [control_id for control_id in catalog_ids(path) if control_id not in RULES]


def rule_map() -> dict[str, Any]:
    return dict(RULES)
