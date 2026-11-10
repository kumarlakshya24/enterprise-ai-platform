from __future__ import annotations

import json
from pathlib import Path

from conduit.evalrun import run_eval
from conduit.pipeline import ROOT


def test_eval_gates_and_committed_report(tmp_path: Path) -> None:
    fresh = run_eval(tmp_path / "eval.db")
    assert fresh["gates_pass"] is True
    committed = json.loads((ROOT / "reports" / "eval.json").read_text(encoding="utf-8"))
    stable = (
        "recall_at_1",
        "recall_at_1_after_swap",
        "embed_reused_on_updates",
        "embed_calls_on_updates",
        "migration_embed_calls",
        "migration_reused",
        "migration_chunks",
        "rtbf_remaining_chunks",
        "resurrected_links_after_rebuild",
        "usd_per_million_docs_small",
        "reuse_rate_on_updates",
    )
    for key in stable:
        assert fresh[key] == committed[key], key
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "0.667" in readme or "66.7%" in readme or "2 of 3" in readme
    small = committed["usd_per_million_docs_small"]
    assert f"{small}" in readme
