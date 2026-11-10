"""Committed numbers have to match a fresh run. Wall clock does not."""

from __future__ import annotations

import json
from pathlib import Path

from arena.evaluate import build_report, fingerprint
from arena.settings import ROOT
from arena.world import World


def test_committed_report_matches_fresh_quality(world: World) -> None:
    path = ROOT / "reports" / "latest.json"
    assert path.exists(), "run make eval so reports/latest.json is committed"
    saved = json.loads(path.read_text(encoding="utf-8"))
    live = build_report(world, bench_n=1)
    assert fingerprint(saved) == fingerprint(live)
    assert saved["corpus_sha256"] == world.sha
    for scenario in saved["scenarios"]:
        assert scenario["winner"] == scenario["expect"]


def test_eval_markdown_is_written_beside_the_json(tmp_path: Path, world: World) -> None:
    from arena.evaluate import write_report

    report = build_report(world, bench_n=1)
    destination = tmp_path / "latest.json"
    write_report(report, destination)
    text = destination.with_suffix(".md").read_text(encoding="utf-8")
    assert "weekly-cited" in text
    assert "exact-phrase" in text
