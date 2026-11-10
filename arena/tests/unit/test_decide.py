"""The memo is a function of saved metrics. The rules are the product."""

from __future__ import annotations

from arena.decide import decide
from arena.world import World


def _metrics(report: dict) -> dict:
    return report["arms"]


def test_locked_scenarios_pick_the_expected_arm(report: dict) -> None:
    winners = {scenario["id"]: scenario["winner"] for scenario in report["scenarios"]}
    assert winners == {
        "weekly-cited": "rag",
        "high-volume-stable": "lora",
        "narrow-fast": "distilled",
        "low-volume": "rag",
        "cited-stable": "rag",
    }
    by_id = {scenario["id"]: scenario for scenario in report["scenarios"]}
    assert by_id["weekly-cited"]["do_not_finetune"] is True
    assert by_id["high-volume-stable"]["do_not_finetune"] is False
    assert by_id["narrow-fast"]["do_not_finetune"] is False
    assert by_id["low-volume"]["do_not_finetune"] is True
    weekly_checks = {row["id"]: row["fired"] for row in by_id["weekly-cited"]["finetune_checks"]}
    assert weekly_checks["citations"] is True
    assert weekly_checks["change"] is True
    assert weekly_checks["quality-margin"] is True
    assert weekly_checks["amortization"] is True
    volume_checks = {row["id"]: row["fired"] for row in by_id["high-volume-stable"]["finetune_checks"]}
    assert volume_checks["amortization"] is False
    assert volume_checks["citations"] is False
    assert volume_checks["change"] is False


def test_quality_counts(report: dict) -> None:
    assert report["arms"]["rag"]["current_full"]["correct"] == 25
    assert report["arms"]["rag"]["current_full"]["citation_rate"] == 1.0
    assert report["arms"]["lora"]["freeze_full"]["correct"] == 19
    assert report["arms"]["lora"]["staleness"]["stale"] == 3
    assert report["arms"]["lora"]["staleness"]["correct"] == 0
    assert report["arms"]["distilled"]["freeze_full"]["correct"] == 15
    assert report["arms"]["distilled"]["freeze_common_short"]["correct"] == 15
    assert report["arms"]["prompt"]["freeze_full"]["correct"] == 8
    assert report["showcase"]["arms"]["rag"]["reason"] == "ok"
    assert report["showcase"]["arms"]["lora"]["reason"] == "stale"
    assert "30 days" in report["showcase"]["arms"]["rag"]["text"]
    assert "14 days" in report["showcase"]["arms"]["lora"]["text"]


def test_weekly_still_blocks_a_perfect_adapter(world: World, report: dict) -> None:
    metrics = report["arms"]
    patched = {arm: {name: dict(block) for name, block in slices.items()} for arm, slices in metrics.items()}
    for slice_name in patched["lora"]:
        patched["lora"][slice_name]["task_success"] = 1.0
        patched["lora"][slice_name]["citation_rate"] = 1.0
    scenario = next(row for row in world.scenarios if row["id"] == "weekly-cited")
    decision = decide(patched, scenario, world.price, world.policy, {})
    assert decision["winner"] == "rag"
    assert any("weekly" in reason for reason in decision["eliminated"]["lora"])


def test_impossible_slo_recommends_nobody(world: World, report: dict) -> None:
    scenario = {
        "id": "too-fast",
        "title": "Nothing is this fast",
        "monthly_requests": 2_000_000,
        "change_rate": "stable",
        "citations_required": False,
        "latency_slo_ms": 10,
        "monthly_budget_usd": 20_000,
        "scope": "common_short",
    }
    decision = decide(report["arms"], scenario, world.price, world.policy, {})
    assert decision["winner"] is None
    assert decision["do_not_finetune"] is True
    assert all("SLO" in reason for reason in decision["eliminated"]["distilled"])


def test_program_cost_dominates_at_low_volume(report: dict) -> None:
    low = next(row for row in report["scenarios"] if row["id"] == "low-volume")
    high = next(row for row in report["scenarios"] if row["id"] == "high-volume-stable")
    assert low["monthly_usd"]["lora"] > low["monthly_usd"]["rag"] * 10
    assert high["monthly_usd"]["lora"] < high["monthly_usd"]["rag"]
    assert report["cost"]["label"] == "projection"
    assert report["cost"]["per_request_usd"]["distilled"] < report["cost"]["per_request_usd"]["lora"]
    assert report["cost"]["model_latency_ms"]["distilled"] < 80
    assert report["cost"]["model_latency_ms"]["lora"] > 80
    assert report["overhead_ms"]["rag"]["p95"] < 20
    assert report["overhead_ms"]["note"].startswith("In-process")


def test_bad_scenario_is_rejected(world: World, report: dict) -> None:
    import pytest

    from arena.decide import scenario_from_item

    with pytest.raises(ValueError):
        scenario_from_item({"change_rate": "daily", "scope": "full"})
    decision = decide(
        report["arms"],
        scenario_from_item(
            {
                "monthly_requests": 2_000_000,
                "change_rate": "stable",
                "citations_required": True,
                "latency_slo_ms": 2000,
                "monthly_budget_usd": 20_000,
                "scope": "full",
            }
        ),
        world.price,
        world.policy,
        {},
    )
    assert decision["winner"] == "rag"
    assert any("citation" in reason for reason in decision["eliminated"]["lora"])
