"""Kill a worker with SIGKILL after a ledger debit has committed, then resume.

The child and the parent do not share a process. The debit is in effects.db.
The completion event is absent from atlas.db. Resume heals from the effect key.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from atlas.clock import SystemClock
from atlas.domain import LeaseHeld
from atlas.engine import Engine
from atlas.guard import OfflineAegisGuard
from atlas.knowledge import OfflineLumen
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store

ROOT = Path(__file__).resolve().parents[2]


def run_kill_resume(directory: Path, lease_s: float = 0.4) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    db = directory / "atlas.db"
    effects = directory / "effects.db"
    key = "kill-resume-refund"
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "atlas.demo.child",
            "--db",
            str(db),
            "--effects",
            str(effects),
            "--lease",
            str(lease_s),
            "--crash",
            "post_ledger:after_remote",
            "--idempotency-key",
            key,
        ],
        cwd=str(ROOT),
    )
    code = child.wait(timeout=30)
    killed = code < 0 or code == 137 or code == -9
    clock = SystemClock()
    store = Store(str(db))
    effect_store = EffectStore(str(effects))
    engine = Engine(
        store,
        effect_store,
        llm=MockLLM(),
        guard=OfflineAegisGuard(),
        knowledge=OfflineLumen(),
        clock=clock,
        lease_ttl=lease_s,
    )
    run = store.find_by_key(key)
    assert run is not None, "child exited without creating a run"
    run_id = run["id"]
    mid = engine.snapshot(run_id)
    ledger_mid = effect_store.counts(run_id).get("ledger.post", 0)
    post = next(item for item in mid["activities"] if item["id"] == "post_ledger")
    blocked = False
    try:
        store.claim(run_id, "resume", clock.now(), lease_s)
    except LeaseHeld:
        blocked = True
    # The stolen claim above only happens if the lease already expired.
    # When it is still held, wait it out and claim from the engine.
    deadline = time.time() + lease_s + 2
    resume_snap = None
    while time.time() < deadline:
        try:
            resume_snap = engine.resume(run_id, owner="resume", because_crash=True, auto_approve=True)
            break
        except LeaseHeld:
            time.sleep(0.05)
    if resume_snap is None:
        raise TimeoutError("lease never expired")
    final_counts = resume_snap["effect_counts"]
    report = {
        "child_code": code,
        "killed": killed or code < 0,
        "lease_blocked_immediate_claim": blocked,
        "mid_status": mid["status"],
        "mid_activity": post["status"],
        "mid_healed": post["healed"],
        "mid_ledger": ledger_mid,
        "mid_email": mid["effect_counts"].get("email.send", 0),
        "final_status": resume_snap["status"],
        "final_counts": final_counts,
        "recovery": resume_snap["recovery"],
        "healed": next(item["healed"] for item in resume_snap["activities"] if item["id"] == "post_ledger"),
    }
    report["pass"] = bool(
        report["killed"]
        and blocked
        and ledger_mid == 1
        and post["status"] == "running"
        and not post["healed"]
        and mid["effect_counts"].get("email.send", 0) == 0
        and resume_snap["status"] == "completed"
        and final_counts.get("ledger.post") == 1
        and final_counts.get("email.send") == 1
        and final_counts.get("case.close") == 1
        and report["healed"]
        and resume_snap["recovery"]["inflight_steps_rerun"] == 0
        and resume_snap["recovery"]["completed_steps_rerun"] == 0
    )
    return report


def format_report(report: dict[str, Any]) -> str:
    counts = report["final_counts"]
    lines = [
        "Atlas kill-and-resume",
        "workflow: refund",
        f"child exit code: {report['child_code']} (negative means SIGKILL)",
        "",
        "After SIGKILL, before resume:",
        f"  run status: {report['mid_status']}",
        f"  post_ledger: {report['mid_activity']} (healed={report['mid_healed']})",
        f"  ledger.post rows: {report['mid_ledger']}",
        f"  email.send rows: {report['mid_email']}",
        f"  second worker blocked by the live lease: {report['lease_blocked_immediate_claim']}",
        "",
        "After the lease expired and a new worker resumed:",
        f"  run status: {report['final_status']}",
        f"  ledger.post: {counts.get('ledger.post', 0)}",
        f"  email.send: {counts.get('email.send', 0)}",
        f"  case.close: {counts.get('case.close', 0)}",
        f"  post_ledger healed from the effect key: {report['healed']}",
        f"  completed steps re-run: {report['recovery']['completed_steps_rerun']}",
        f"  in-flight steps re-executed: {report['recovery']['inflight_steps_rerun']}",
        "",
        "PASS" if report["pass"] else "FAIL",
    ]
    return "\n".join(lines)


def main() -> None:
    import tempfile

    report = run_kill_resume(Path(tempfile.mkdtemp(prefix="atlas-kill-")))
    print(format_report(report))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
