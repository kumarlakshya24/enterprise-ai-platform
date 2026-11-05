import pytest

from switchboard.catalog import get_catalog
from switchboard.policy import PolicyError, load_policies, load_policy_text


def test_shipped_policies_load() -> None:
    policies = load_policies(known_models=set(get_catalog().models))
    assert set(policies) == {"default", "cost-saver", "latency-first", "quality-first"}
    assert policies["default"].min_headroom == 0.10
    assert policies["cost-saver"].selection == "cheapest"
    assert policies["latency-first"].latency_slo_ms == 100
    assert abs(sum(policies["quality-first"].weights.values()) - 1) < 1e-9


def test_weights_must_sum_to_one() -> None:
    text = """
version: "t"
name: bad
selection: weighted
weights: {capability: 0.2, cost: 0.2, latency: 0.2}
budget_usd: 1
latency_slo_ms: 1000
min_quality: 0.5
fallback: {order: [balanced], allow_local_on_total_failure: false, max_attempts: 1}
"""
    with pytest.raises(PolicyError, match="sum"):
        load_policy_text(text, known_models={"balanced", "local", "fast-cheap", "premium"})


def test_unknown_pin_is_rejected() -> None:
    text = """
version: "t"
name: bad
selection: cheapest
weights: {capability: 0.2, cost: 0.5, latency: 0.3}
budget_usd: 1
latency_slo_ms: 1000
min_quality: 0.5
fallback: {order: [balanced], max_attempts: 1}
rules:
  - id: R
    pin: missing
"""
    with pytest.raises(PolicyError, match="unknown model"):
        load_policy_text(text, known_models={"balanced"})
