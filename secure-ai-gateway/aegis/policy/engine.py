"""Policy decision: entities + classifier label + context markers -> one explainable route."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aegis.classifier.types import Classification
from aegis.dlp.engine import ScanResult
from aegis.policy.schema import Policy
from aegis.types import Label, Route


@dataclass
class Decision:
    route: Route
    context_label: Label
    data_label: Label | None
    rule_id: str
    reasons: list[str]
    policy_version: str
    markers: list[dict[str, str]] = field(default_factory=list)
    classifier: dict[str, Any] | None = None
    regex_only_baseline: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_label(self) -> Label:
        return max(self.context_label, self.data_label) if self.data_label is not None else self.context_label

    def public(self) -> dict[str, Any]:
        return {
            "route": self.route.value,
            "rule_id": self.rule_id,
            "context_label": self.context_label.name,
            "data_label": self.data_label.name if self.data_label is not None else None,
            "effective_label": self.effective_label.name,
            "reasons": self.reasons,
            "policy_version": self.policy_version,
            "context_markers": self.markers,
            "classifier": self.classifier,
            "regex_only_baseline": self.regex_only_baseline,
        }


def regex_only_baseline(scan: ScanResult) -> dict[str, Any]:
    """What a pattern-only DLP (regex, no NER, no classifier) would have done with this prompt."""
    regex_hits = [f for f in scan.applied if f.detector.startswith("regex.")]
    if any(f.action.value == "block" for f in regex_hits):
        route = Route.BLOCK
    elif regex_hits:
        route = Route.REDACT
    else:
        route = Route.ALLOW
    return {
        "route": route.value,
        "entities": len(regex_hits),
        "sends_to_external_llm": route.sends_external,
    }


def decide(
    *,
    text: str,
    scan: ScanResult,
    classification: Classification | None,
    policy: Policy,
    policy_version: str,
) -> Decision:
    reasons: list[str] = []
    applied = scan.applied
    data_label = max((policy.rule(f.entity_type).label for f in applied), default=None)
    markers = [
        {"id": m.id, "label": m.label.name, "description": m.description}
        for m, rx in policy.compiled_markers
        if rx.search(text)
    ]
    baseline = regex_only_baseline(scan)

    if scan.blocking:
        types = sorted({f.entity_type.value for f in scan.blocking})
        reasons.append(f"entity policy blocks {', '.join(types)}: the request cannot be sent anywhere")
        return Decision(
            Route.BLOCK,
            Label.RESTRICTED,
            data_label,
            "R-ENTITY-BLOCK",
            reasons,
            policy_version,
            markers,
            classification.public() if classification else None,
            baseline,
        )

    # 1. Context label from the private classifier (run on tokenized text).
    if classification is not None:
        context = classification.label
        msg = f"classifier labelled the context {context.name} ({classification.confidence:.2f})"
        if classification.escalated_from is not None:
            msg += f", escalated from {classification.escalated_from.name} because confidence was low"
        reasons.append(msg)
    else:
        context = Label.INTERNAL
        reasons.append("classifier disabled by policy: context defaults to INTERNAL")

    # 2. Deterministic markers set a floor.
    if markers:
        floor = max(Label[m["label"]] for m in markers)
        if floor > context:
            reasons.append(
                f"context marker {', '.join(m['id'] for m in markers)} raised the label {context.name} -> {floor.name}"
            )
            context = floor

    # 3. A prompt that contained customer data is never PUBLIC, even once tokenized.
    if applied and context < Label.INTERNAL:
        reasons.append("prompt contained sensitive entities: context raised to INTERNAL")
        context = Label.INTERNAL

    route = policy.routing.for_label(context)
    rule_id = f"R-ROUTE-{context.name}"
    reasons.append(f"policy routes {context.name} context to {route.value}")

    # 4. Bulk rule: many restricted values look like a data dump.
    restricted = sum(1 for f in applied if policy.rule(f.entity_type).label is Label.RESTRICTED)
    if restricted >= policy.bulk.max_restricted_entities and policy.bulk.action.strictness > route.strictness:
        reasons.append(
            f"{restricted} RESTRICTED values (limit {policy.bulk.max_restricted_entities - 1}): "
            f"bulk rule escalates to {policy.bulk.action.value}"
        )
        route, rule_id = policy.bulk.action, "R-BULK"

    if route is Route.ALLOW and applied:
        route = Route.REDACT
    if route is Route.REDACT and applied:
        counts = scan.entity_counts()
        reasons.append(
            "tokenized " + ", ".join(f"{n} {t}" for t, n in sorted(counts.items())) + " before sending"
        )

    return Decision(
        route,
        context,
        data_label,
        rule_id,
        reasons,
        policy_version,
        markers,
        classification.public() if classification else None,
        baseline,
    )
