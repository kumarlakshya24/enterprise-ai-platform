"""Synth, invariants, and planted breaks."""

from __future__ import annotations

import json

import pytest

from skyline.diffing import diff
from skyline.invariants import MUTATION_PRIMARY, evaluate, failed_rules
from skyline.mutations import mutate, mutation_names
from skyline.platform import assemble
from skyline.review import review
from skyline.synth import canonical, digest


def test_synth_is_deterministic() -> None:
    assert canonical(assemble()) == canonical(assemble())


def test_clean_gate_passes() -> None:
    rows = evaluate(assemble())
    failed = [row for row in rows if not row["ok"]]
    assert failed == []
    assert len(rows) >= 16


def test_mutation_catalog_matches_the_gate() -> None:
    assert set(mutation_names()) == set(MUTATION_PRIMARY)


@pytest.mark.parametrize("name,rule", list(MUTATION_PRIMARY.items()))
def test_mutation_fails_its_named_rule(name: str, rule: str) -> None:
    failed = failed_rules(mutate(assemble(), name))
    assert rule in failed
    assert failed


def test_clean_template_has_no_world_cidr() -> None:
    text = canonical(assemble())
    assert "0.0.0.0/0" not in text
    assert '"::/0"' not in text


def test_diff_of_a_mutation_names_the_change() -> None:
    clean = assemble()
    changes = diff(clean, mutate(clean, "open-sg"))
    assert changes
    assert any("AegisSecurityGroup" in change["path"] for change in changes)
    assert diff(clean, clean) == []


def test_fixture_matches_synth() -> None:
    from skyline.synth import read_fixture

    fixture = read_fixture()
    text = canonical(assemble())
    assert fixture == text
    assert digest(fixture) == digest(text)


def test_pillars_cite_real_resources() -> None:
    rows = review(assemble())
    assert len(rows) == 6
    assert all(row["ok"] for row in rows)


def test_accounts_are_the_six_we_describe() -> None:
    manifest = assemble()["manifest"]
    names = [account["name"] for account in manifest["accounts"]]
    assert names == ["network", "security", "lumen", "switchboard", "log-archive", "finops"]
    assert manifest["synth"] == "fixture-cdk"
    assert json.loads(canonical(assemble()))["manifest"]["disclaimer"].startswith("Synthetic")
