"""Demo scenarios. Denied snippets are one-line policy checks, not exploits."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    tool: str
    code: str | None = None
    path: str | None = None
    content: str | None = None
    timeout_ms: int | None = None
    expect_outcome: str = "allow"
    expect_rule: str = "R-ALLOW"
    stdout_contains: str | None = None
    spawned: bool | None = None
    preview_would_allow: bool = True


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    say: str
    steps: tuple[Step, ...] = ()
    kind: str = "tool"


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="s1-sum",
        title="Arithmetic in the sandbox",
        say="A normal snippet runs, and the audit records an allow.",
        steps=(
            Step(
                tool="python",
                code="print(sum(range(1, 101)))",
                stdout_contains="5050",
                spawned=True,
            ),
        ),
    ),
    Scenario(
        id="s2-read",
        title="Read a workspace note",
        say="read_file can see the seeded note. It cannot see the rest of the disk.",
        steps=(
            Step(
                tool="read_file",
                path="notes/summary.txt",
                stdout_contains="Northwind",
                spawned=False,
            ),
        ),
    ),
    Scenario(
        id="s3-write",
        title="Write, then read, inside the workspace",
        say="Tools may change files under the workspace. The Python tool still has no open().",
        steps=(
            Step(
                tool="write_file",
                path="notes/draft.txt",
                content="draft for Northwind",
                stdout_contains="wrote",
                spawned=False,
            ),
            Step(
                tool="read_file",
                path="notes/draft.txt",
                stdout_contains="draft for Northwind",
                spawned=False,
            ),
        ),
    ),
    Scenario(
        id="s4-traversal",
        title="Path traversal is refused before any read",
        say="The preview says a raw file API would use the path. Forge does not open it.",
        steps=(
            Step(
                tool="read_file",
                path="../../secret.txt",
                expect_outcome="deny",
                expect_rule="R-PATH-TRAVERSAL",
                spawned=False,
            ),
        ),
    ),
    Scenario(
        id="s5-import",
        title="Process and network modules stay denied",
        say="Policy cannot grant these modules. The snippet is not executed.",
        steps=(
            Step(
                tool="python",
                code='import os\nprint("RAN")',
                expect_outcome="deny",
                expect_rule="R-IMPORT-HARD-DENY",
                spawned=False,
            ),
            Step(
                tool="python",
                code='import socket\nprint("RAN")',
                expect_outcome="deny",
                expect_rule="R-IMPORT-HARD-DENY",
                spawned=False,
            ),
        ),
    ),
    Scenario(
        id="s6-shell",
        title="There is no shell executor",
        say="Marking shell enabled in a policy file still does not create a shell.",
        steps=(
            Step(
                tool="shell",
                code="echo hello",
                expect_outcome="deny",
                expect_rule="R-TOOL-NO-EXECUTOR",
                spawned=False,
            ),
        ),
    ),
    Scenario(
        id="s7-wall",
        title="A tight loop hits the wall clock",
        say="The process is killed. The audit outcome is limited, not allow.",
        steps=(
            Step(
                tool="python",
                code="while True:\n    pass",
                timeout_ms=800,
                expect_outcome="limited",
                expect_rule="R-LIMIT-WALL",
                spawned=True,
            ),
        ),
    ),
    Scenario(
        id="s8-regression",
        title="A weaker policy is refused",
        say="Granting pathlib and raising the code cap fails the locked regression gate.",
        kind="regression",
    ),
)


def public_scenarios() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        payload.append(
            {
                "id": scenario.id,
                "title": scenario.title,
                "say": scenario.say,
                "kind": scenario.kind,
                "steps": [
                    {"tool": step.tool, "code": step.code, "path": step.path, "content": step.content}
                    for step in scenario.steps
                ],
            }
        )
    return payload


def by_id(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(scenario_id)
