"""Load the eval corpus and execute it against a policy."""

from __future__ import annotations

import json
from pathlib import Path

from forge.audit import AuditLog
from forge.config import PROJECT_ROOT, audit_key
from forge.policy.regression import CaseResult
from forge.policy.schema import Policy, load_default_policy
from forge.service import Session
from forge.types import ToolRequest

CORPUS_PATH = PROJECT_ROOT / "eval" / "cases" / "corpus.jsonl"


def load_cases(path: Path | None = None) -> list[dict[str, object]]:
    target = path or CORPUS_PATH
    cases: list[dict[str, object]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def case_code(case: dict[str, object]) -> str | None:
    if "code_pad" in case:
        unit = "x = 1\n"
        size = int(case["code_pad"])
        if size % len(unit) != 0:
            raise ValueError("code_pad must be a multiple of 6")
        return unit * (size // len(unit))
    code = case.get("code")
    return None if code is None else str(code)


def run_cases(
    cases: list[dict[str, object]] | None = None,
    policy: Policy | None = None,
    work_root: Path | None = None,
) -> list[CaseResult]:
    selected = cases if cases is not None else load_cases()
    active = policy or load_default_policy()
    root = work_root or (PROJECT_ROOT / "var" / "eval")
    root.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(root / "audit.jsonl", audit_key())
    results: list[CaseResult] = []
    for case in selected:
        case_id = str(case["id"])
        workspace = root / "cases" / case_id
        if workspace.exists():
            _clear(workspace)
        session = Session(workspace, audit, active)
        request = ToolRequest(
            tool=str(case["tool"]),
            code=case_code(case),
            path=None if case.get("path") is None else str(case.get("path")),
            content=None if case.get("content") is None else str(case.get("content")),
            timeout_ms=int(case["timeout_ms"]) if case.get("timeout_ms") else None,
            max_memory_mb=int(case["max_memory_mb"]) if case.get("max_memory_mb") else None,
            max_output_bytes=int(case["max_output_bytes"]) if case.get("max_output_bytes") else None,
            actor="eval",
        )
        result = session.execute(request)
        results.append(_judge(case, result.outcome, result.rule, result.stdout, result.spawned))
    return results


def _judge(case: dict[str, object], outcome: str, rule: str, stdout: str, spawned: bool) -> CaseResult:
    expect = str(case["expect"])
    ok = outcome == expect
    detail: list[str] = []
    if not ok:
        detail.append(f"outcome {outcome} != {expect}")
    if "rule" in case and rule != case["rule"]:
        ok = False
        detail.append(f"rule {rule} != {case['rule']}")
    if "stdout_contains" in case and str(case["stdout_contains"]) not in stdout:
        ok = False
        detail.append("stdout missing expected text")
    if "stdout_absent" in case and str(case["stdout_absent"]) in stdout:
        ok = False
        detail.append("stdout contained forbidden text")
    if "spawned" in case and bool(case["spawned"]) is not spawned:
        ok = False
        detail.append(f"spawned {spawned} != {case['spawned']}")
    if "max_stdout_bytes" in case and len(stdout.encode("utf-8")) > int(case["max_stdout_bytes"]):
        ok = False
        detail.append("stdout longer than cap")
    return CaseResult(
        id=str(case["id"]),
        klass=str(case.get("class") or ""),
        expect=expect,
        outcome=outcome,
        rule=rule,
        ok=ok,
        spawned=spawned,
        stdout=stdout,
        detail="; ".join(detail),
    )


def _clear(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
