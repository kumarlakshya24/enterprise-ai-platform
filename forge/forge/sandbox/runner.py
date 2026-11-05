"""Parent side of the sandbox. Spawns a fresh interpreter and reads one JSON result."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from forge.types import Limits, Outcome

CHILD = Path(__file__).resolve().with_name("child.py")


@dataclass
class SandboxResult:
    outcome: str
    rule: str
    stdout: str
    spawned: bool
    error: str = ""
    reasons: list[str] = field(default_factory=list)
    stderr: str = ""


def _environment(workspace: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(workspace),
        "TMPDIR": str(workspace),
        "TEMP": str(workspace),
        "TMP": str(workspace),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "FORGE_SANDBOX": "1",
    }


def _killed_rule(returncode: int) -> str:
    sig = -returncode
    if sig == signal.SIGXCPU:
        return "R-LIMIT-CPU"
    if sig in {signal.SIGKILL, signal.SIGSEGV, signal.SIGABRT, signal.SIGBUS}:
        return "R-LIMIT-MEMORY"
    return "R-SANDBOX-CRASH"


class SandboxRunner:
    def run(self, code: str, limits: Limits, workspace: Path) -> SandboxResult:
        timeout_s = (limits.timeout_ms / 1000) + 0.75
        payload = {
            "code": code,
            "allow_imports": sorted(limits.allow_imports),
            "deny_imports": sorted(limits.deny_imports),
            "max_output_bytes": limits.max_output_bytes,
            "max_code_bytes": limits.max_code_bytes,
            "max_memory_mb": limits.max_memory_mb,
            "cpu_seconds": int(timeout_s) + 5,
        }
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(CHILD)],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                timeout=timeout_s,
                cwd=str(workspace),
                env=_environment(workspace),
                start_new_session=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
            return SandboxResult(
                outcome=Outcome.LIMITED,
                rule="R-LIMIT-WALL",
                stdout=stdout[:200],
                spawned=True,
                error="wall clock exceeded",
                reasons=[f"killed after {limits.timeout_ms} ms"],
            )
        stderr = completed.stderr.decode("utf-8", errors="replace")[-500:]
        text = completed.stdout.decode("utf-8", errors="replace").strip()
        if not text:
            rule = _killed_rule(completed.returncode) if completed.returncode < 0 else "R-SANDBOX-CRASH"
            outcome = Outcome.LIMITED if rule.startswith("R-LIMIT") else Outcome.ERROR
            return SandboxResult(outcome, rule, "", True, rule, [rule], stderr)
        try:
            data = json.loads(text.splitlines()[-1])
        except json.JSONDecodeError:
            return SandboxResult(Outcome.ERROR, "R-SANDBOX-PROTOCOL", "", True, "protocol", ["protocol"], stderr)
        status = str(data.get("status") or "")
        rule = str(data.get("rule") or "R-SANDBOX-CRASH")
        stdout = str(data.get("stdout") or "")
        error = str(data.get("error") or "")
        if len(stdout.encode("utf-8")) > limits.max_output_bytes:
            stdout = stdout.encode("utf-8")[: limits.max_output_bytes].decode("utf-8", errors="ignore")
            status = "limited"
            rule = "R-LIMIT-OUTPUT"
        outcome = {
            "ok": Outcome.ALLOW,
            "deny": Outcome.DENY,
            "limited": Outcome.LIMITED,
            "error": Outcome.ERROR,
        }.get(status, Outcome.ERROR)
        return SandboxResult(outcome, rule, stdout, True, error, [rule], stderr)
