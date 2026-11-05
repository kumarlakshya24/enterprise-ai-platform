"""Regression gate.

A protected case is one the default policy does not allow. Activating a policy
that lets any of those cases through is a failed gate. Utility regressions
(a benign case newly denied) are reported and do not fail the gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from forge.policy.schema import Policy

BASELINE_PATH = Path(__file__).resolve().parents[2] / "eval" / "regression" / "baseline.json"


@dataclass
class CaseResult:
    id: str
    klass: str
    expect: str
    outcome: str
    rule: str
    ok: bool
    spawned: bool
    stdout: str
    detail: str = ""


@dataclass
class GateReport:
    ok: bool
    protection_regressions: list[dict[str, str]] = field(default_factory=list)
    utility_regressions: list[dict[str, str]] = field(default_factory=list)


def load_baseline(path: Path | None = None) -> dict[str, list[str]]:
    target = path or BASELINE_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    return {"protected": list(data["protected"]), "utility": list(data["utility"])}


def gate(results: list[CaseResult], baseline: dict[str, list[str]]) -> GateReport:
    by_id = {item.id: item for item in results}
    protection: list[dict[str, str]] = []
    utility: list[dict[str, str]] = []
    for case_id in baseline["protected"]:
        item = by_id.get(case_id)
        if item is None or item.outcome == "allow":
            protection.append(
                {
                    "case": case_id,
                    "outcome": "missing" if item is None else item.outcome,
                    "rule": "" if item is None else item.rule,
                }
            )
    for case_id in baseline["utility"]:
        item = by_id.get(case_id)
        if item is None or item.outcome != "allow":
            utility.append(
                {
                    "case": case_id,
                    "outcome": "missing" if item is None else item.outcome,
                    "rule": "" if item is None else item.rule,
                }
            )
    return GateReport(ok=not protection, protection_regressions=protection, utility_regressions=utility)


def weakened_pathlib_policy(policy: Policy) -> Policy:
    """Grant pathlib and raise the code-size cap. The demo expects the gate to refuse this."""
    allow = list(policy.imports.allow)
    if "pathlib" not in allow:
        allow.append("pathlib")
    deny = [name for name in policy.imports.deny if name != "pathlib"]
    tools = dict(policy.tools)
    tools["python"] = policy.tools["python"].model_copy(update={"max_code_bytes": 7000})
    return policy.model_copy(
        update={
            "imports": policy.imports.model_copy(update={"allow": allow, "deny": deny}),
            "tools": tools,
        }
    )
