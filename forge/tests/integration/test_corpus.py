from __future__ import annotations

from pathlib import Path

from forge.corpus import load_cases, run_cases
from forge.policy.regression import gate, load_baseline, weakened_pathlib_policy
from forge.policy.schema import load_default_policy


def test_baseline_matches_corpus_exactly() -> None:
    cases = load_cases()
    baseline = load_baseline()
    protected = {str(case["id"]) for case in cases if case["expect"] != "allow"}
    utility = {str(case["id"]) for case in cases if case["expect"] == "allow"}
    assert set(baseline["protected"]) == protected
    assert set(baseline["utility"]) == utility
    assert protected.isdisjoint(utility)
    assert len(cases) >= 40


def test_default_policy_passes_corpus(tmp_path: Path) -> None:
    results = run_cases(work_root=tmp_path / "eval")
    missed = [item for item in results if not item.ok]
    assert not missed, [(item.id, item.detail, item.outcome, item.rule) for item in missed]
    report = gate(results, load_baseline())
    assert report.ok
    assert report.protection_regressions == []


def test_weakened_policy_fails_the_gate(tmp_path: Path) -> None:
    weak = weakened_pathlib_policy(load_default_policy())
    results = run_cases(policy=weak, work_root=tmp_path / "weak")
    report = gate(results, load_baseline())
    assert report.ok is False
    names = {item["case"] for item in report.protection_regressions}
    assert "prot-import-pathlib" in names
    assert "prot-code-size" in names
    os_case = next(item for item in results if item.id == "prot-import-os")
    assert os_case.outcome == "deny"
    assert os_case.rule == "R-IMPORT-HARD-DENY"
