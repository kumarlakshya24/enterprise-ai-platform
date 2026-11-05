import json
from pathlib import Path

from switchboard.evaluation import evaluate

ROOT = Path(__file__).resolve().parents[2]


def test_corpus_matches_the_router_and_the_committed_report() -> None:
    fresh = evaluate()
    assert fresh["n"] == 36
    assert fresh["gold_accuracy"] == 1.0
    assert fresh["misses"] == []
    assert fresh["by_policy"]["quality-first"]["oracle_agreement"] < 1
    assert fresh["by_policy"]["default"]["savings_pct"] > 50
    assert fresh["fallback_gold_accuracy"] == 1.0
    committed = json.loads((ROOT / "reports" / "eval.json").read_text())
    assert committed["gold_accuracy"] == fresh["gold_accuracy"]
    assert committed["savings_pct"] == fresh["savings_pct"]
    assert committed["answered_savings_pct"] == fresh["answered_savings_pct"]
    assert committed["by_policy"] == fresh["by_policy"]


def test_latency_report_is_labeled_as_measured_overhead() -> None:
    report = json.loads((ROOT / "reports" / "latency.json").read_text())
    assert report["n"] >= 100
    assert report["sleep"] is False
    assert report["router_overhead_ms"]["p95"] < 5
    assert "not wall clock" in report["catalog_latency_ms"]["note"].lower()
