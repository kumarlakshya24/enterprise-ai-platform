"""Orchestrate guard, sandbox, workspace tools, and the audit log."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from forge.audit import AuditLog
from forge.audit.redact import preview
from forge.demo.seed import seed_workspace
from forge.guard import guard_request
from forge.guard.imports import GuardError
from forge.guard.paths import resolve_workspace_path
from forge.policy.engine import effective_limits, tighten
from forge.policy.schema import Policy, load_default_policy
from forge.sandbox.preview import build_preview
from forge.sandbox.runner import SandboxRunner
from forge.types import Outcome, RunResult, ToolRequest

_ERROR_RULES = {"R-PATH-NOT-FILE", "R-PATH-NOT-DIR", "R-IO"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Session:
    def __init__(
        self,
        workspace: Path,
        audit: AuditLog,
        policy: Policy | None = None,
        runner: SandboxRunner | None = None,
    ) -> None:
        self.workspace = workspace
        self.audit = audit
        self.policy = policy or load_default_policy()
        self.runner = runner or SandboxRunner()
        seed_workspace(self.workspace)

    def reset(self) -> None:
        import shutil

        for child in list(self.workspace.iterdir()):
            if child.is_symlink() or child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
        seed_workspace(self.workspace)
        self.audit.append(
            "session_reset",
            actor="ui",
            tool="session",
            outcome=Outcome.ALLOW,
            rule="R-RESET",
            detail={"workspace": self.workspace.name},
        )

    def execute(self, request: ToolRequest) -> RunResult:
        started = time.perf_counter()
        preview_decision = build_preview(request, self.policy, self.workspace)
        limits = effective_limits(self.policy, request.tool)
        if limits is not None:
            limits = tighten(
                limits,
                timeout_ms=request.timeout_ms,
                max_memory_mb=request.max_memory_mb,
                max_output_bytes=request.max_output_bytes,
            )
        try:
            guard_request(self.workspace, request, limits)
        except GuardError as exc:
            outcome = Outcome.ERROR if exc.rule in _ERROR_RULES else Outcome.DENY
            return self._finish(
                request, preview_decision, outcome, exc.rule, [exc.detail], "", False, started, exc.detail
            )

        assert limits is not None
        try:
            if request.tool == "python":
                sand = self.runner.run(request.code or "", limits, self.workspace)
                return self._finish(
                    request,
                    preview_decision,
                    sand.outcome,
                    sand.rule,
                    sand.reasons,
                    sand.stdout,
                    sand.spawned,
                    started,
                    sand.error,
                )
            if request.tool == "read_file":
                stdout = self._read(request.path or "", limits.max_output_bytes)
                return self._finish(
                    request,
                    preview_decision,
                    Outcome.ALLOW,
                    "R-ALLOW",
                    ["read inside the workspace"],
                    stdout,
                    False,
                    started,
                    "",
                )
            if request.tool == "write_file":
                stdout = self._write(request.path or "", request.content or "")
                return self._finish(
                    request,
                    preview_decision,
                    Outcome.ALLOW,
                    "R-ALLOW",
                    ["write inside the workspace"],
                    stdout,
                    False,
                    started,
                    "",
                )
            if request.tool == "list_dir":
                stdout = self._list(request.path or ".", limits.max_output_bytes)
                return self._finish(
                    request,
                    preview_decision,
                    Outcome.ALLOW,
                    "R-ALLOW",
                    ["list inside the workspace"],
                    stdout,
                    False,
                    started,
                    "",
                )
        except GuardError as exc:
            outcome = Outcome.ERROR if exc.rule in _ERROR_RULES else Outcome.DENY
            return self._finish(
                request, preview_decision, outcome, exc.rule, [exc.detail], "", False, started, exc.detail
            )
        return self._finish(
            request,
            preview_decision,
            Outcome.DENY,
            "R-TOOL-NO-EXECUTOR",
            ["no executor for this tool"],
            "",
            False,
            started,
            "no executor",
        )

    def _read(self, user_path: str, max_bytes: int) -> str:
        path = resolve_workspace_path(self.workspace, user_path)
        if path.is_symlink() or not path.is_file():
            raise GuardError("R-PATH-NOT-FILE", "path is not a file in the workspace")
        size = path.stat().st_size
        if size > max_bytes:
            raise GuardError("R-LIMIT-OUTPUT", f"file is {size} bytes; limit is {max_bytes}")
        return path.read_text(encoding="utf-8", errors="replace")

    def _write(self, user_path: str, content: str) -> str:
        path = resolve_workspace_path(self.workspace, user_path)
        if path.is_symlink():
            raise GuardError("R-PATH-SYMLINK", "symlinks are refused")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"wrote {len(content.encode('utf-8'))} bytes"

    def _list(self, user_path: str, max_bytes: int) -> str:
        path = resolve_workspace_path(self.workspace, user_path)
        if path.is_symlink() or not path.is_dir():
            raise GuardError("R-PATH-NOT-DIR", "path is not a directory in the workspace")
        names: list[str] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            if child.is_symlink():
                names.append(f"{child.name} (symlink refused)")
                continue
            names.append(child.name + ("/" if child.is_dir() else ""))
        text = "\n".join(names)
        if len(text.encode("utf-8")) > max_bytes:
            raise GuardError("R-LIMIT-OUTPUT", "directory listing exceeds the output limit")
        return text

    def _finish(
        self,
        request: ToolRequest,
        preview_decision: object,
        outcome: str,
        rule: str,
        reasons: list[str],
        stdout: str,
        spawned: bool,
        started: float,
        error: str,
    ) -> RunResult:
        from forge.types import Preview

        if not isinstance(preview_decision, Preview):
            raise TypeError("preview")
        duration_ms = (time.perf_counter() - started) * 1000
        code = request.code or ""
        record = self.audit.append(
            "tool_decision",
            actor=request.actor,
            tool=request.tool,
            outcome=outcome,
            rule=rule,
            detail={
                "reasons": reasons,
                "spawned": spawned,
                "duration_ms": round(duration_ms, 1),
                "path": request.path or "",
                "error": error[:180],
                "stdout_bytes": len(stdout.encode("utf-8")),
                "stdout_sha256": _sha(stdout),
                "stdout_preview": preview(stdout, 80),
                "code_sha256": _sha(code),
                "code_preview": preview(code, 80),
                "policy_version": self.policy.version,
            },
        )
        return RunResult(
            tool=request.tool,
            outcome=outcome,
            rule=rule,
            reasons=reasons,
            stdout=stdout,
            spawned=spawned,
            duration_ms=duration_ms,
            preview=preview_decision,
            error=error,
            audit_seq=int(record["seq"]),
            code_sha256=_sha(code),
        )
