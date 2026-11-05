"""Process-level kill. The worker is SIGKILL'd; a second process resumes."""

from __future__ import annotations

from atlas.demo.kill_resume import run_kill_resume


def test_sigkill_after_the_debit_resumes_without_a_duplicate(tmp_path) -> None:
    report = run_kill_resume(tmp_path, lease_s=0.4)
    assert report["killed"]
    assert report["lease_blocked_immediate_claim"]
    assert report["mid_ledger"] == 1
    assert report["mid_activity"] == "running"
    assert report["final_counts"]["ledger.post"] == 1
    assert report["final_counts"]["email.send"] == 1
    assert report["final_counts"]["case.close"] == 1
    assert report["healed"]
    assert report["recovery"]["completed_steps_rerun"] == 0
    assert report["recovery"]["inflight_steps_rerun"] == 0
    assert report["pass"]
