from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from forge.guard.constants import HARD_DENY_MODULES
from forge.policy.engine import effective_limits
from forge.policy.schema import load_default_policy
from forge.sandbox.runner import SandboxRunner
from forge.types import ToolRequest

ROOT = Path(__file__).resolve().parents[2]


def test_sum_runs_in_a_subprocess(session) -> None:
    result = session.execute(ToolRequest(tool="python", code="print(sum(range(1, 101)))"))
    assert result.outcome == "allow"
    assert result.rule == "R-ALLOW"
    assert result.spawned is True
    assert "5050" in result.stdout
    assert result.preview.executed is False
    assert session.audit.verify()["ok"] is True


def test_import_os_never_spawns(session) -> None:
    result = session.execute(ToolRequest(tool="python", code='import os\nprint("RAN")'))
    assert result.outcome == "deny"
    assert result.rule == "R-IMPORT-HARD-DENY"
    assert result.spawned is False
    assert "RAN" not in result.stdout
    assert result.preview.would_allow is True
    assert result.preview.executed is False


def test_child_rechecks_when_parent_guard_is_skipped(tmp_path: Path) -> None:
    limits = effective_limits(load_default_policy(), "python")
    assert limits is not None
    granted = type(limits)(
        timeout_ms=limits.timeout_ms,
        max_memory_mb=limits.max_memory_mb,
        max_output_bytes=limits.max_output_bytes,
        max_code_bytes=limits.max_code_bytes,
        max_write_bytes=limits.max_write_bytes,
        allow_imports=frozenset(set(limits.allow_imports) | {"os"}),
        deny_imports=limits.deny_imports,
    )
    result = SandboxRunner().run('import os\nprint("RAN")', granted, tmp_path)
    assert result.spawned is True
    assert result.outcome == "deny"
    assert result.rule == "R-IMPORT-HARD-DENY"
    assert "RAN" not in result.stdout


def test_traversal_does_not_return_outside_bytes(tmp_path: Path, session) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("CANARY-OUTSIDE", encoding="utf-8")
    result = session.execute(ToolRequest(tool="read_file", path="../../outside.txt"))
    assert result.rule == "R-PATH-TRAVERSAL"
    assert "CANARY-OUTSIDE" not in result.stdout
    assert outside.read_text(encoding="utf-8") == "CANARY-OUTSIDE"


def test_write_then_read(session) -> None:
    written = session.execute(ToolRequest(tool="write_file", path="notes/draft.txt", content="draft for Northwind"))
    read = session.execute(ToolRequest(tool="read_file", path="notes/draft.txt"))
    assert written.outcome == "allow"
    assert "draft for Northwind" in read.stdout


def test_zero_division_is_an_error_not_an_allow(session) -> None:
    result = session.execute(ToolRequest(tool="python", code="print(1 / 0)"))
    assert result.spawned is True
    assert result.outcome == "error"
    assert result.rule == "R-SANDBOX-EXCEPTION"
    assert "ZeroDivisionError" in result.error


def test_wall_clock(session) -> None:
    result = session.execute(ToolRequest(tool="python", code="while True:\n    pass", timeout_ms=700))
    assert result.spawned is True
    assert result.outcome == "limited"
    assert result.rule == "R-LIMIT-WALL"


def test_output_cap(session) -> None:
    result = session.execute(ToolRequest(tool="python", code='print("A" * 20000)'))
    assert result.outcome == "limited"
    assert result.rule == "R-LIMIT-OUTPUT"
    assert len(result.stdout.encode("utf-8")) <= 8192


def test_shell_enabled_still_has_no_executor(session) -> None:
    session.policy = session.policy.model_copy(
        update={
            "tools": {
                **session.policy.tools,
                "shell": session.policy.tools["shell"].model_copy(update={"enabled": True}),
            }
        }
    )
    result = session.execute(ToolRequest(tool="shell", code="echo hello"))
    assert result.rule == "R-TOOL-NO-EXECUTOR"
    assert result.spawned is False


def test_audit_hook_blocks_host_open() -> None:
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from forge.sandbox.hook import install_audit_hook\n"
        "install_audit_hook()\n"
        "try:\n"
        "    open('/etc/hostname', 'r')\n"
        "    print('OPENED')\n"
        "except PermissionError:\n"
        "    print('BLOCKED')\n"
    )
    completed = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "BLOCKED" in completed.stdout
    assert "OPENED" not in completed.stdout


def test_pathlib_grant_still_cannot_read_workspace_file(tmp_path: Path) -> None:
    from forge.audit import AuditLog
    from forge.policy.regression import weakened_pathlib_policy
    from forge.policy.schema import load_default_policy
    from forge.service import Session

    session = Session(
        tmp_path / "ws",
        AuditLog(tmp_path / "audit.jsonl", b"k"),
        weakened_pathlib_policy(load_default_policy()),
    )
    result = session.execute(
        ToolRequest(
            tool="python",
            code='import pathlib\nprint(pathlib.Path("notes/summary.txt").read_text())',
        )
    )
    assert result.spawned is True
    assert result.outcome == "deny"
    assert result.rule == "R-SANDBOX-OPEN"
    assert "Northwind" not in result.stdout


def test_hard_deny_set_covers_process_and_network() -> None:
    for name in ("os", "sys", "subprocess", "socket", "ctypes", "pickle", "shutil"):
        assert name in HARD_DENY_MODULES
    assert "pathlib" not in HARD_DENY_MODULES
    assert "math" not in HARD_DENY_MODULES


def test_child_never_writes_bytecode(tmp_path: Path, monkeypatch) -> None:
    """The child must run with -B.

    Without it, importing an allowed stdlib module on an interpreter with no cached
    .pyc (a fresh CI toolcache) calls marshal.dumps, which the audit hook blocks.
    """
    import forge.sandbox.runner as runner_module

    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=b'{"status": "ok", "rule": "R-ALLOW"}', stderr=b"")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)
    limits = effective_limits(load_default_policy(), "python")
    assert limits is not None
    SandboxRunner().run("print(1)", limits, tmp_path)
    assert seen and seen[0][1:3] == ["-I", "-B"], seen
