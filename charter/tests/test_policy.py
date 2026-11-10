"""Parser and evaluator. These do not read the audit stub."""

from __future__ import annotations

import pytest

from charter.config import CANDIDATE_EXCLUDE, POLICIES_DIR, REGISTRY_PATH
from charter.policy.engine import Request, evaluate, load_policies
from charter.policy.syntax import PolicySyntaxError, parse_policies
from charter.registry.cards import load_registry


def _bundle(text: str):
    return parse_policies({"mem.cedar": text})


def test_annotations_and_excerpt() -> None:
    statements = _bundle(
        """
        // @id R-EXAMPLE
        // @controls EU-10, EU-12
        forbid (principal, action == Action::"invoke", resource)
        when { context.data_class == "RESTRICTED" };
        """
    )
    assert len(statements) == 1
    statement = statements[0]
    assert statement.rule_id == "R-EXAMPLE"
    assert statement.controls == ("EU-10", "EU-12")
    assert "forbid" in statement.excerpt
    assert statement.effect == "forbid"


def test_syntax_error_names_the_line() -> None:
    with pytest.raises(PolicySyntaxError) as caught:
        _bundle("?\npermit (principal, action, resource);")
    assert caught.value.line == 1


def test_unknown_path_fails_closed() -> None:
    from charter.policy.syntax import Bundle

    statements = _bundle(
        """
        // @id R-TYPO
        permit (principal, action, resource)
        when { context.colour == "red" };
        """
    )
    bundle = Bundle(statements, (("mem.cedar", ""),), "abc")
    decision = evaluate(
        bundle,
        Request("acme/u", "atlas-eu-mini", "customer_support", "PUBLIC", "EU"),
        {"type": "Model", "id": "atlas-eu-mini", "region": "eu-central-1"},
    )
    assert decision.effect == "deny"
    assert decision.primary_rule == "R-POLICY-ERROR"
    assert "colour" in decision.reason


def test_forbid_overrides_a_matching_permit() -> None:
    from charter.policy.syntax import Bundle

    statements = _bundle(
        """
        // @id R-KEEP-OUT
        forbid (principal, action, resource) when { context.data_class == "CONFIDENTIAL" };
        // @id R-WIDE
        permit (principal, action == Action::"invoke", resource);
        """
    )
    bundle = Bundle(statements, (), "abc")
    decision = evaluate(
        bundle,
        Request("acme/u", "m", "customer_support", "CONFIDENTIAL", "EU"),
        {"type": "Model", "id": "m"},
    )
    assert decision.effect == "deny"
    assert decision.primary_rule == "R-KEEP-OUT"
    assert decision.matched_permits == ("R-WIDE",)


def test_default_deny_when_nothing_matches() -> None:
    from charter.policy.syntax import Bundle

    statements = _bundle(
        """
        // @id R-ONLY-PUBLIC
        permit (principal, action, resource) when { context.data_class == "PUBLIC" };
        """
    )
    bundle = Bundle(statements, (), "abc")
    decision = evaluate(
        bundle,
        Request("acme/u", "m", "customer_support", "INTERNAL", "EU"),
        {"type": "Model", "id": "m"},
    )
    assert decision.effect == "deny"
    assert decision.primary_rule == "R-DEFAULT-DENY"


def test_unknown_model_never_reaches_a_permit() -> None:
    bundle = load_policies(POLICIES_DIR)
    decision = evaluate(
        bundle,
        Request("acme/u-support", "no-such-model", "customer_support", "PUBLIC", "EU"),
        None,
    )
    assert decision.primary_rule == "R-MODEL-UNKNOWN"
    assert decision.effect == "deny"


def test_shipped_rules_are_named_once() -> None:
    bundle = load_policies(POLICIES_DIR)
    ids = bundle.rule_ids()
    assert len(ids) == len(set(ids))
    assert all(not rule.startswith("R-UNNAMED") for rule in ids)
    assert "R-RESIDENCY-EU" in ids


def test_dropping_residency_file_removes_only_that_rule() -> None:
    shipped = load_policies(POLICIES_DIR).rule_ids()
    weakened = load_policies(POLICIES_DIR, exclude=CANDIDATE_EXCLUDE).rule_ids()
    assert "R-RESIDENCY-EU" in shipped
    assert "R-RESIDENCY-EU" not in weakened
    assert tuple(rule for rule in shipped if rule != "R-RESIDENCY-EU") == weakened


def test_in_operator_and_bool() -> None:
    registry = load_registry(REGISTRY_PATH)
    bundle = load_policies(POLICIES_DIR)
    card = registry.get("claims-triage-eu")
    assert card is not None
    decision = evaluate(
        bundle,
        Request("acme/u-claims", card.id, "claims_triage", "INTERNAL", "EU"),
        card.resource(),
    )
    assert decision.effect == "deny"
    assert "R-OVERSIGHT" in decision.rule_ids
    assert "R-PERMIT-CLAIMS" in decision.matched_permits
