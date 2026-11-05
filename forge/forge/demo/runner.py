"""Run demo scenarios and the interview beats."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from forge.audit import AuditLog
from forge.config import audit_key
from forge.corpus import run_cases
from forge.demo.scenarios import SCENARIOS, Step
from forge.policy.regression import gate, load_baseline, weakened_pathlib_policy
from forge.policy.schema import Policy, load_default_policy
from forge.service import Session
from forge.types import RunResult, ToolRequest


@dataclass
class Check:
    id: str
    ok: bool
    detail: str


def run_demo(root: Path | None = None) -> list[Check]:
    if root is None:
        with tempfile.TemporaryDirectory(prefix="forge-demo-") as tmp:
            return _run(Path(tmp))
    return _run(root)


def _run(root: Path) -> list[Check]:
    policy = load_default_policy()
    session = Session(root / "workspace", AuditLog(root / "audit.jsonl", audit_key()), policy)
    checks: list[Check] = []
    for scenario in SCENARIOS:
        if scenario.kind == "regression":
            checks.extend(_regression(root, policy))
            continue
        for index, step in enumerate(scenario.steps, start=1):
            result = session.execute(_request(step))
            ok, detail = _judge_step(step, result)
            checks.append(Check(f"{scenario.id}.{index}", ok, detail))
    verify = session.audit.verify()
    checks.append(Check("audit-verify", bool(verify["ok"]), f"events={verify.get('events')} ok={verify.get('ok')}"))
    return checks


def _regression(root: Path, policy: Policy) -> list[Check]:
    weak = weakened_pathlib_policy(policy)
    results = run_cases(policy=weak, work_root=root / "weak")
    report = gate(results, load_baseline())
    names = [item["case"] for item in report.protection_regressions]
    refused = (not report.ok) and "prot-import-pathlib" in names and "prot-code-size" in names
    os_case = next(item for item in results if item.id == "prot-import-os")
    os_held = os_case.outcome == "deny" and os_case.rule == "R-IMPORT-HARD-DENY"
    return [
        Check(
            "s8-regression.gate",
            refused,
            f"gate_ok={report.ok} regressed={','.join(names)}",
        ),
        Check(
            "s8-regression.os-hard-deny",
            os_held,
            f"import os under the weak policy: {os_case.outcome} {os_case.rule}",
        ),
    ]


def run_interview(root: Path | None = None) -> list[Check]:
    if root is None:
        with tempfile.TemporaryDirectory(prefix="forge-interview-") as tmp:
            return _interview(Path(tmp))
    return _interview(root)


def _interview(root: Path) -> list[Check]:
    checks = run_demo(root / "demo")
    policy = load_default_policy()
    granted = policy.model_copy(
        update={"imports": policy.imports.model_copy(update={"allow": [*policy.imports.allow, "os"]})}
    )
    session = Session(root / "hard", AuditLog(root / "hard.jsonl", audit_key()), granted)
    result = session.execute(ToolRequest(tool="python", code='import os\nprint("RAN")'))
    checks.append(
        Check(
            "interview.os-not-grantable",
            result.outcome == "deny" and result.rule == "R-IMPORT-HARD-DENY" and result.spawned is False,
            f"{result.outcome} {result.rule} spawned={result.spawned}",
        )
    )
    outside = root / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    canary = outside / "canary.txt"
    canary.write_text("CANARY-OUTSIDE", encoding="utf-8")
    workspace = root / "linkws"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "alias.txt").symlink_to(canary)
    linked = Session(workspace, AuditLog(root / "link.jsonl", audit_key()), policy)
    link_result = linked.execute(ToolRequest(tool="read_file", path="alias.txt"))
    checks.append(
        Check(
            "interview.symlink",
            link_result.outcome == "deny"
            and link_result.rule == "R-PATH-SYMLINK"
            and "CANARY-OUTSIDE" not in link_result.stdout,
            f"{link_result.outcome} {link_result.rule}",
        )
    )
    record = session.audit.records()[-1]
    session.audit.path.write_text(
        session.audit.path.read_text(encoding="utf-8").replace(str(record["outcome"]), "allow", 1),
        encoding="utf-8",
    )
    verify = session.audit.verify()
    checks.append(
        Check(
            "interview.audit-tamper",
            verify["ok"] is False,
            f"broken_seq={verify.get('broken_seq')} reason={verify.get('reason')}",
        )
    )
    preview = session.execute(ToolRequest(tool="python", code='import socket\nprint("RAN")'))
    checks.append(
        Check(
            "interview.preview-not-executed",
            preview.preview.executed is False
            and preview.preview.would_allow is True
            and preview.spawned is False
            and "RAN" not in preview.stdout,
            preview.preview.note,
        )
    )
    return checks


def regression_checks(root: Path, policy: Policy | None = None) -> list[Check]:
    return _regression(root, policy or load_default_policy())


def _request(step: Step) -> ToolRequest:
    return ToolRequest(
        tool=step.tool,
        code=step.code,
        path=step.path,
        content=step.content,
        timeout_ms=step.timeout_ms,
        actor="demo",
    )


def _judge_step(step: Step, result: RunResult) -> tuple[bool, str]:
    ok = result.outcome == step.expect_outcome and result.rule == step.expect_rule
    if step.stdout_contains is not None and step.stdout_contains not in result.stdout:
        ok = False
    if step.spawned is not None and result.spawned is not step.spawned:
        ok = False
    if result.preview.executed:
        ok = False
    if result.preview.would_allow is not step.preview_would_allow:
        ok = False
    if "RAN" in result.stdout:
        ok = False
    detail = (
        f"{result.outcome} {result.rule} spawned={result.spawned} "
        f"preview={result.preview.would_allow}/{result.preview.risk} stdout={result.stdout.strip()[:40]!r}"
    )
    return ok, detail
