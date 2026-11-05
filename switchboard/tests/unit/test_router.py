from switchboard.catalog import get_catalog
from switchboard.demo_data import EASY_CHAT, HARD_MATH, SCENARIOS, SENSITIVE
from switchboard.pipeline import RouteRequest, route
from switchboard.provider import Fault, MockProvider
from switchboard.runtime import Runtime


def _route(runtime: Runtime, prompt: str, policy: str, fault: dict | None = None) -> dict:
    return route(
        catalog=runtime.catalog,
        policy=runtime.policy(policy),
        provider=runtime.provider,
        store=runtime.store,
        request=RouteRequest(
            prompt=prompt,
            fault=Fault(**fault) if fault else None,
        ),
    )


def test_demo_scenarios_match_the_locked_routes(runtime: Runtime) -> None:
    for scenario in SCENARIOS:
        decision = _route(runtime, scenario["prompt"], scenario["policy"], scenario.get("fault"))
        assert decision["features"]["task"] == scenario["expect_task"], scenario["id"]
        assert decision["chosen_model"] == scenario["expect_model"], scenario["id"]
        assert decision["outcome"] == scenario["expect_outcome"], scenario["id"]


def test_request_cannot_loosen_the_policy_budget(runtime: Runtime) -> None:
    decision = route(
        catalog=runtime.catalog,
        policy=runtime.policy("cost-saver"),
        provider=runtime.provider,
        store=None,
        request=RouteRequest(prompt=EASY_CHAT, budget_usd=10),
    )
    assert decision["constraints"]["budget_usd"] == runtime.policy("cost-saver").budget_usd
    assert any("ceiling" in line for line in decision["why"])


def test_request_can_tighten_the_slo_until_nothing_fits(runtime: Runtime) -> None:
    decision = route(
        catalog=runtime.catalog,
        policy=runtime.policy("default"),
        provider=runtime.provider,
        store=None,
        request=RouteRequest(prompt=EASY_CHAT, latency_slo_ms=10),
    )
    assert decision["outcome"] == "rejected"
    assert decision["chosen_model"] is None


def test_email_alone_is_not_pinned_to_local(runtime: Runtime) -> None:
    decision = _route(runtime, "Ping ada@example.com about lunch.", "default")
    assert decision["features"]["sensitivity"] == "internal"
    assert decision["chosen_model"] != "local"


def test_sensitive_failure_does_not_call_a_hosted_model(runtime: Runtime) -> None:
    decision = _route(runtime, SENSITIVE, "default", {"model": "local", "mode": "error"})
    called = [item["model"] for item in decision["attempts"] if item["status"] != "skipped"]
    assert called == ["local"]
    assert decision["outcome"] == "failed"


def test_premium_outage_on_hard_math_escapes_to_local(runtime: Runtime) -> None:
    decision = _route(runtime, HARD_MATH, "default", {"model": "premium", "mode": "timeout"})
    assert decision["outcome"] == "fallback"
    assert decision["chosen_model"] == "local"
    assert decision["degraded"] is True
    hosted = [item for item in decision["attempts"] if item["status"] == "timeout"]
    assert hosted and hosted[0]["cost_usd"] > 0


def test_quality_first_does_not_escape_to_local(runtime: Runtime) -> None:
    decision = _route(runtime, HARD_MATH, "quality-first", {"model": "premium", "mode": "error"})
    assert decision["chosen_model"] is None
    assert decision["outcome"] == "failed"
    assert all(item["model"] != "local" or item["status"] == "skipped" for item in decision["attempts"])


def test_dry_run_does_not_add_spend(runtime: Runtime) -> None:
    route(
        catalog=runtime.catalog,
        policy=runtime.policy("default"),
        provider=MockProvider(get_catalog()),
        store=runtime.store,
        request=RouteRequest(prompt=EASY_CHAT, dry_run=True),
    )
    assert runtime.store.stats()["requests"] == 0


def test_decision_preview_has_no_raw_email(runtime: Runtime) -> None:
    decision = _route(runtime, SENSITIVE, "default")
    assert "ada@example.com" not in decision["prompt_preview"]
    stored = runtime.store.get(decision["id"])
    assert stored is not None
    assert "ada@example.com" not in stored["prompt_preview"]
    assert "ada@example.com" not in str(runtime.store.recent(5))
