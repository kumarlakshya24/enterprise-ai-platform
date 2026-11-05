"""Policy engine: routing by label, markers, bulk rule, overrides, schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aegis.classifier.model import load_default_classifier
from aegis.classifier.types import Classification
from aegis.dlp.engine import DLPEngine
from aegis.gateway.pipeline import classifier_view
from aegis.policy.engine import decide
from aegis.policy.schema import Policy, PolicyBundle, deep_merge
from aegis.policy.store import load_bundle_file
from aegis.types import Label, Route

clf = load_default_classifier()


def run(text: str, policy: Policy, dlp: DLPEngine, classification: Classification | None = None):  # type: ignore[no-untyped-def]
    scan = dlp.scan(text, policy)
    view = text
    for f in sorted(scan.applied, key=lambda x: x.start, reverse=True):
        view = view[: f.start] + f"[{f.entity_type.value}]" + view[f.end :]
    c = classification or clf.classify(classifier_view(view), policy.classifier.min_confidence)
    return decide(text=text, scan=scan, classification=c, policy=policy, policy_version="test")


def fixed(label: Label, conf: float = 0.9) -> Classification:
    return Classification(label, conf, {label.name: conf})


@pytest.mark.parametrize(
    ("label", "route"),
    [
        (Label.PUBLIC, Route.ALLOW),
        (Label.INTERNAL, Route.REDACT),
        (Label.CONFIDENTIAL, Route.LOCAL_ONLY),
        (Label.RESTRICTED, Route.BLOCK),
    ],
)
def test_default_routing_table(
    label: Label, route: Route, default_policy: Policy, dlp_engine: DLPEngine
) -> None:
    d = run("Summarize the notes.", default_policy, dlp_engine, fixed(label))
    assert d.route is route and d.rule_id == f"R-ROUTE-{label.name}"


def test_entities_force_at_least_internal(default_policy: Policy, dlp_engine: DLPEngine) -> None:
    d = run("Send it to dana.holloway@example.com", default_policy, dlp_engine, fixed(Label.PUBLIC))
    assert d.context_label is Label.INTERNAL and d.route is Route.REDACT


def test_context_marker_sets_a_floor(default_policy: Policy, dlp_engine: DLPEngine) -> None:
    d = run(
        "Attorney-client privileged: what are our options?", default_policy, dlp_engine, fixed(Label.PUBLIC)
    )
    assert d.context_label is Label.RESTRICTED and d.route is Route.BLOCK
    assert d.markers and d.markers[0]["id"] == "M-001"


def test_regex_only_baseline_would_have_leaked_context(default_policy: Policy, dlp_engine: DLPEngine) -> None:
    text = "We will discontinue the Starter tier in Q3; the acquisition talks are still unannounced."
    d = run(text, default_policy, dlp_engine)
    assert d.regex_only_baseline == {"route": "allow", "entities": 0, "sends_to_external_llm": True}
    assert d.route in (Route.LOCAL_ONLY, Route.BLOCK)


def test_bulk_rule(default_policy: Policy, dlp_engine: DLPEngine) -> None:
    cards = ", ".join(
        [
            "4111 1111 1111 1111",
            "5555 5555 5555 4444",
            "3782 822463 10005",
            "6011 1111 1111 1117",
            "4012 8888 8888 1881",
        ]
    )
    d = run(f"Reconcile these cards: {cards}", default_policy, dlp_engine, fixed(Label.INTERNAL))
    assert d.route is Route.REQUIRE_APPROVAL and d.rule_id == "R-BULK"


def test_private_key_blocks_regardless_of_label(default_policy: Policy, dlp_engine: DLPEngine) -> None:
    from aegis.demo.fakes import fake_private_key

    d = run(fake_private_key(), default_policy, dlp_engine, fixed(Label.PUBLIC))
    assert d.route is Route.BLOCK and d.rule_id == "R-ENTITY-BLOCK"


def test_user_override_applies_only_to_that_user() -> None:
    bundle = load_bundle_file()
    assert bundle.effective("acme", "u-legal-bot").routing.INTERNAL is Route.LOCAL_ONLY
    assert bundle.effective("acme", "u-1001").routing.INTERNAL is Route.REDACT


def test_tenant_override_then_user_override_precedence() -> None:
    bundle = load_bundle_file().model_copy(deep=True)
    bundle.tenant_overrides["acme"] = {"routing": {"CONFIDENTIAL": "block"}}
    bundle.user_overrides["acme/u-7"] = {"routing": {"CONFIDENTIAL": "require_approval"}}
    assert bundle.effective("acme", "u-1").routing.CONFIDENTIAL is Route.BLOCK
    assert bundle.effective("acme", "u-7").routing.CONFIDENTIAL is Route.REQUIRE_APPROVAL
    assert bundle.effective("other", None).routing.CONFIDENTIAL is Route.LOCAL_ONLY


def test_invalid_policies_are_rejected() -> None:
    doc = load_bundle_file().model_dump(mode="json")
    with pytest.raises(ValidationError):
        PolicyBundle.model_validate(deep_merge(doc, {"base": {"routing": {"PUBLIC": "yolo"}}}))
    with pytest.raises(ValidationError):
        PolicyBundle.model_validate(
            deep_merge(doc, {"base": {"context_markers": [{"id": "x", "pattern": "(", "label": "PUBLIC"}]}})
        )
    del doc["base"]["entities"]["CREDIT_CARD"]
    with pytest.raises(ValidationError):
        PolicyBundle.model_validate(doc)


def test_allowlist_matching(default_policy: Policy) -> None:
    assert default_policy.is_allowlisted("AWS Lambda")
    assert default_policy.is_allowlisted("Cloud Run")
    assert not default_policy.is_allowlisted("Northwind Traders")
    assert not default_policy.is_allowlisted("Acme AWS Consulting LLC")


def test_digest_changes_with_content() -> None:
    a = load_bundle_file()
    b = a.model_copy(deep=True)
    b.base.routing.CONFIDENTIAL = Route.BLOCK
    assert a.digest() != b.digest()
