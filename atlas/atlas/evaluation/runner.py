"""Run the workflow suite and write eval_results/latest.

The suite is a regression lock for the engine, not a model benchmark.
Agents are the deterministic mock. Both engines see the same workflows.
"""

from __future__ import annotations

import json
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from atlas import __version__
from atlas.baseline import BaselineAgent
from atlas.clock import ManualClock
from atlas.domain import CrashInjected
from atlas.engine import CrashSpec, Engine
from atlas.guard import OfflineAegisGuard
from atlas.knowledge import OfflineLumen
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store

ROOT = Path(__file__).resolve().parents[2]
LATEST = ROOT / "eval_results" / "latest"

REFUND = {
    "customer_id": "cus_1042",
    "amount_usd": 40,
    "email": "dana.holloway@example.com",
    "reason": "duplicate charge",
    "policy_question": "What is the customer refund policy?",
}


def cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "refund_happy",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "approve": "approved",
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "refund_small",
            "workflow": "refund",
            "inputs": {**REFUND, "amount_usd": 10},
            "approve": None,
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "refund_crash_after_remote",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "approve": "approved",
            "crash": "post_ledger:after_remote",
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "refund_crash_after_intent",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "approve": "approved",
            "crash": "post_ledger:after_intent",
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "refund_denied",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "approve": "denied",
            "expect": {"status": "denied", "effects": {}},
        },
        {
            "id": "refund_step_budget",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "budget": {"max_steps": 1, "max_cost_usd": 1.0, "on_exceeded": "pause"},
            "expect": {"status": "paused_budget", "effects": {}},
        },
        {
            "id": "refund_cost_budget",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "budget": {"max_steps": 20, "max_cost_usd": 0.0025, "on_exceeded": "pause"},
            "expect": {"status": "paused_budget", "effects": {}},
        },
        {
            "id": "refund_email_compensate",
            "workflow": "refund",
            "inputs": {**REFUND, "fail_tools": {"email.send": {"mode": "permanent"}}},
            "approve": "approved",
            "expect": {"status": "compensated", "effects": {"ledger.post": 1, "ledger.reverse": 1}},
        },
        {
            "id": "refund_email_retry",
            "workflow": "refund",
            "inputs": {**REFUND, "fail_tools": {"email.send": {"mode": "transient", "times": 1}}},
            "approve": "approved",
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "refund_ledger_timeout",
            "workflow": "refund",
            "inputs": {**REFUND, "fail_tools": {"ledger.post": {"mode": "timeout", "times": 1, "elapsed_ms": 5000}}},
            "approve": "approved",
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "compensate_crash",
            "workflow": "refund",
            "inputs": {**REFUND, "fail_tools": {"email.send": {"mode": "permanent"}}},
            "approve": "approved",
            "crash": "post_ledger:after_remote:compensate",
            "expect": {"status": "compensated", "effects": {"ledger.post": 1, "ledger.reverse": 1}},
        },
        {
            "id": "vendor_guard",
            "workflow": "vendor_onboarding",
            "inputs": {"vendor_id": "ven_9"},
            "approve": "approved",
            "expect": {"status": "completed", "effects": {"vendor.provision": 1, "email.send": 1}},
        },
        {
            "id": "incident_crash",
            "workflow": "incident_response",
            "inputs": {"incident_id": "inc_441"},
            "crash": "status_page:after_remote",
            "expect": {
                "status": "completed",
                "effects": {"status.publish": 1, "pager.page": 1, "postmortem.publish": 1},
            },
        },
        {
            "id": "duplicate_submit",
            "workflow": "refund",
            "inputs": dict(REFUND),
            "approve": "approved",
            "duplicate": True,
            "expect": {"status": "completed", "effects": {"ledger.post": 1, "email.send": 1, "case.close": 1}},
        },
        {
            "id": "lumen_refusal",
            "workflow": "refund",
            "inputs": {**REFUND, "policy_question": "What is the executive bonus formula?"},
            "expect": {"status": "failed", "effects": {}},
        },
        {
            "id": "sms_not_idempotent",
            "workflow": "sms_notice",
            "inputs": {"phone": "+15555550100"},
            "expect": {"status": "failed", "effects": {}},
        },
    ]


def run_suite(directory: Path | None = None) -> dict[str, Any]:
    if directory is None:
        with tempfile.TemporaryDirectory(prefix="atlas-eval-") as tmp:
            return run_suite(Path(tmp))
    rows = []
    for case in cases():
        rows.append(_run_case(case, directory, "atlas"))
        rows.append(_run_case(case, directory, "baseline"))
    latency = _latency_probe(directory)
    summary = _summarize(rows, latency)
    return summary


def _run_case(case: dict[str, Any], directory: Path, engine_name: str) -> dict[str, Any]:
    if engine_name == "atlas":
        result = _atlas(case, directory / f"{case['id']}-atlas")
    else:
        result = _baseline(case, directory / f"{case['id']}-baseline")
    expect = case["expect"]
    ok = result["status"] == expect["status"] and _effects_match(result["effects"], expect["effects"])
    recovery = result.get("recovery") or {}
    return {
        "id": case["id"],
        "engine": engine_name,
        "crash": bool(case.get("crash")),
        "task_success": ok,
        "status": result["status"],
        "expected_status": expect["status"],
        "effects": result["effects"],
        "expected_effects": expect["effects"],
        "steps": result["steps"],
        "cost_usd": result["cost_usd"],
        "llm_calls": result["llm_calls"],
        "llm_replays": result.get("llm_replays", 0),
        "backoff_ms_honored": result.get("backoff_ms_honored", 0),
        "completed_steps_rerun": recovery.get("completed_steps_rerun", 0) if case.get("crash") else 0,
        "inflight_steps_rerun": recovery.get("inflight_steps_rerun", 0) if case.get("crash") else 0,
        "recovery_ms": recovery.get("recovery_ms", 0) if case.get("crash") else 0,
        "catch_up_ms": recovery.get("catch_up_ms", 0) if case.get("crash") else 0,
        "wall_clock_recovery_ms": result.get("wall_clock_recovery_ms"),
        "error": result.get("error"),
    }


def _effects_match(actual: dict[str, int], expected: dict[str, int]) -> bool:
    actual_nz = {key: value for key, value in actual.items() if value}
    expected_nz = {key: value for key, value in expected.items() if value}
    return actual_nz == expected_nz


def _atlas(case: dict[str, Any], directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    clock = ManualClock()
    engine = Engine(
        Store(str(directory / "atlas.db")),
        EffectStore(str(directory / "effects.db")),
        llm=MockLLM(),
        guard=OfflineAegisGuard(),
        knowledge=OfflineLumen(),
        clock=clock,
    )
    crash = CrashSpec.parse(case.get("crash"))
    try:
        snap = engine.start(
            case["workflow"],
            case["inputs"],
            idempotency_key=case["id"],
            budget=case.get("budget"),
            crash=crash,
        )
    except CrashInjected as exc:
        snap = _resume_timed(engine, exc.run_id)
    snap = _pump(engine, clock, snap, case, crash)
    if case.get("duplicate"):
        snap = engine.start(
            case["workflow"],
            case["inputs"],
            idempotency_key=case["id"],
            budget=case.get("budget"),
        )
        snap = _pump(engine, clock, snap, case, None)
    return _from_snap(snap)


def _pump(
    engine: Engine, clock: ManualClock, snap: dict[str, Any], case: dict[str, Any], crash: CrashSpec | None
) -> dict[str, Any]:
    for _ in range(12):
        status = snap["status"]
        if status == "paused_approval" and case.get("approve"):
            try:
                snap = engine.decide(snap["id"], case["approve"], "morgan", crash=crash)
            except CrashInjected as exc:
                snap = _resume_timed(engine, exc.run_id)
            continue
        if status == "waiting_retry":
            wait = 0.0
            now = clock.now()
            for activity in snap["activities"]:
                if activity["status"] == "waiting_retry" and activity.get("retry_at"):
                    wait = max(wait, activity["retry_at"] - now)
            clock.advance(wait + 0.001)
            snap = engine.resume(snap["id"])
            continue
        return snap
    return snap


def _resume_timed(engine: Engine, run_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    snap = engine.resume(run_id, because_crash=True)
    snap["wall_clock_recovery_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return snap


def _from_snap(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": snap["status"],
        "effects": snap["effect_counts"],
        "steps": snap["steps"],
        "cost_usd": snap["cost_usd"],
        "llm_calls": snap["llm_calls"],
        "llm_replays": snap["llm_replays"],
        "backoff_ms_honored": snap["backoff_ms_honored"],
        "recovery": snap.get("recovery"),
        "error": snap.get("error"),
        "wall_clock_recovery_ms": snap.get("wall_clock_recovery_ms"),
    }


def _baseline(case: dict[str, Any], directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    effects = EffectStore(str(directory / "effects.db"))
    agent = BaselineAgent(effects, MockLLM(), OfflineLumen())
    crash = CrashSpec.parse(case.get("crash"))
    wall = None
    try:
        report = agent.run(case["workflow"], case["inputs"], crash=crash)
    except CrashInjected:
        started = time.perf_counter()
        report = agent.run(case["workflow"], case["inputs"])
        wall = (time.perf_counter() - started) * 1000
    if case.get("duplicate"):
        agent.run(case["workflow"], case["inputs"])
        report = agent.report()
    if wall is not None:
        report["wall_clock_recovery_ms"] = round(wall, 3)
    report["effects"] = report["effect_counts"]
    report["llm_replays"] = 0
    report["backoff_ms_honored"] = 0
    return report


def _latency_probe(directory: Path) -> dict[str, Any]:
    samples = []
    root = directory / "latency"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(40):
        clock = ManualClock()
        engine = Engine(
            Store(str(root / f"{index}.db")),
            EffectStore(str(root / f"{index}.effects")),
            llm=MockLLM(),
            guard=OfflineAegisGuard(),
            knowledge=OfflineLumen(),
            clock=clock,
        )
        started = time.perf_counter()
        engine.start("refund", {**REFUND, "amount_usd": 10}, idempotency_key=f"lat-{index}")
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "n": len(samples),
        "workflow": "refund_small",
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
        "label": "measured end-to-end wall clock of a small refund, including SQLite setup, mock agents, no network",
    }


def _summarize(rows: list[dict[str, Any]], latency: dict[str, Any]) -> dict[str, Any]:
    def side(name: str) -> dict[str, Any]:
        items = [row for row in rows if row["engine"] == name]
        crashes = [row for row in items if row["crash"]]
        successes = sum(1 for row in items if row["task_success"])
        return {
            "n": len(items),
            "task_success": successes,
            "task_success_rate": round(successes / len(items), 4),
            "task_success_label": f"{successes}/{len(items)}",
            "crash_cases": len(crashes),
            "crash_cases_with_duplicate_effects": sum(
                1 for row in crashes if not row["task_success"] and _has_dup(row)
            ),
            "mean_steps": round(statistics.mean(row["steps"] for row in items), 2),
            "mean_cost_usd": round(statistics.mean(row["cost_usd"] for row in items), 6),
            "mean_completed_steps_rerun": round(statistics.mean(row["completed_steps_rerun"] for row in crashes), 2)
            if crashes
            else 0,
            "mean_inflight_steps_rerun": round(statistics.mean(row["inflight_steps_rerun"] for row in crashes), 2)
            if crashes
            else 0,
            "mean_recovery_ms": round(statistics.mean(row["recovery_ms"] for row in crashes), 2) if crashes else 0,
            "mean_catch_up_ms": round(statistics.mean(row["catch_up_ms"] for row in crashes), 2) if crashes else 0,
        }

    return {
        "suite": "atlas-workflows-v1",
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "note": (
            "Deterministic regression suite. The mock LLM is a pure function. "
            "This is not an estimate of production task success with a sampled model. "
            "Recovery milliseconds are simulated from each activity's declared latency_ms. "
            "A healed step costs 1 ms of bookkeeping. Actual model spend is $0."
        ),
        "cases": rows,
        "latency_probe": latency,
        "summary": {"atlas": side("atlas"), "baseline": side("baseline")},
    }


def _has_dup(row: dict[str, Any]) -> bool:
    return any(value > 1 for value in row["effects"].values())


def render_markdown(report: dict[str, Any]) -> str:
    atlas = report["summary"]["atlas"]
    base = report["summary"]["baseline"]
    lines = [
        f"Suite `{report['suite']}` on Python {report['python']}. {report['note']}",
        "",
        "| Metric | Atlas | Single-agent baseline |",
        "|---|---:|---:|",
        f"| Task success | {atlas['task_success_label']} ({atlas['task_success_rate'] * 100:.1f}%) | {base['task_success_label']} ({base['task_success_rate'] * 100:.1f}%) |",
        f"| Mean steps | {atlas['mean_steps']} | {base['mean_steps']} |",
        f"| Mean accounted cost (USD) | ${atlas['mean_cost_usd']:.5f} | ${base['mean_cost_usd']:.5f} |",
        f"| Mean completed steps re-run after a crash | {atlas['mean_completed_steps_rerun']} | {base['mean_completed_steps_rerun']} |",
        f"| Mean in-flight steps re-executed after a crash | {atlas['mean_inflight_steps_rerun']} | {base['mean_inflight_steps_rerun']} |",
        f"| Mean recovery time after a crash (simulated ms) | {atlas['mean_recovery_ms']} | {base['mean_recovery_ms']} |",
        f"| Mean catch-up time (simulated ms) | {atlas['mean_catch_up_ms']} | {base['mean_catch_up_ms']} |",
        "",
        "Recovery time is simulated milliseconds from resume until the run is terminal again. "
        "Catch-up time stops when the crashed step is resolved. "
        f"Engine overhead on {report['latency_probe']['n']} small refunds: "
        f"p50 {report['latency_probe']['p50_ms']} ms, p95 {report['latency_probe']['p95_ms']} ms "
        "(measured wall clock, mock agents).",
        "",
        "| Case | Atlas | Baseline | Atlas steps re-run (completed / in-flight) | Baseline steps re-run | Atlas recovery ms | Baseline recovery ms |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for row in report["cases"]:
        by_id.setdefault(row["id"], {})[row["engine"]] = row
    for case_id, pair in by_id.items():
        a = pair["atlas"]
        b = pair["baseline"]
        lines.append(
            "| {id} | {as_} | {bs} | {ar} | {br} | {am} | {bm} |".format(
                id=case_id,
                as_="pass" if a["task_success"] else "fail",
                bs="pass" if b["task_success"] else "fail",
                ar=f"{a['completed_steps_rerun']} / {a['inflight_steps_rerun']}" if a["crash"] else "—",
                br=f"{b['completed_steps_rerun']} / {b['inflight_steps_rerun']}" if b["crash"] else "—",
                am=a["recovery_ms"] if a["crash"] else "—",
                bm=b["recovery_ms"] if b["crash"] else "—",
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_results(report: dict[str, Any], dest: Path | None = None) -> Path:
    dest = dest or LATEST
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    text = render_markdown(report)
    (dest / "summary.md").write_text(text)
    _splice_readme(text)
    return dest


def _splice_readme(block: str) -> None:
    path = ROOT / "README.md"
    if not path.is_file():
        return
    text = path.read_text()
    start = "<!-- EVAL:START -->"
    end = "<!-- EVAL:END -->"
    if start not in text or end not in text:
        return
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(f"{before}{start}\n{block}{end}{after}")


def main() -> None:
    report = run_suite()
    path = write_results(report)
    atlas = report["summary"]["atlas"]
    base = report["summary"]["baseline"]
    print(f"wrote {path}")
    print(f"atlas {atlas['task_success_label']}  baseline {base['task_success_label']}")
    print(f"crash recovery ms  atlas {atlas['mean_recovery_ms']}  baseline {base['mean_recovery_ms']}")
    if atlas["task_success"] != atlas["n"]:
        failed = [row["id"] for row in report["cases"] if row["engine"] == "atlas" and not row["task_success"]]
        raise SystemExit(f"atlas failures: {failed}")


if __name__ == "__main__":
    main()
