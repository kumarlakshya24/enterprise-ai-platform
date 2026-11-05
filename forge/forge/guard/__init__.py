"""Argument checks that run before a process is spawned."""

from __future__ import annotations

from pathlib import Path

from forge.guard.ast_guard import check_python
from forge.guard.constants import KNOWN_TOOLS, SHELL_TOOL
from forge.guard.imports import GuardError
from forge.guard.paths import resolve_workspace_path
from forge.types import Limits, ToolRequest


def guard_request(workspace: Path, request: ToolRequest, limits: Limits | None) -> None:
    """Raise GuardError when the call must not proceed.

    `limits` is None when the tool is unknown or has no policy entry. Shell has
    no executor even when a policy marks it enabled.
    """
    tool = request.tool
    if tool == SHELL_TOOL:
        raise GuardError("R-TOOL-NO-EXECUTOR", "Forge has no shell executor")
    if tool not in KNOWN_TOOLS:
        raise GuardError("R-TOOL-UNKNOWN", f"unknown tool {tool}")
    if limits is None:
        raise GuardError("R-TOOL-DISABLED", f"{tool} is not enabled")

    if tool == "python":
        if request.code is None or request.code.strip() == "":
            raise GuardError("R-SYNTAX", "python tool requires code")
        check_python(
            request.code,
            allow=limits.allow_imports,
            deny=limits.deny_imports,
            max_bytes=limits.max_code_bytes,
        )
        return

    if tool in {"read_file", "write_file", "list_dir"}:
        user_path = request.path if request.path is not None else ("." if tool == "list_dir" else "")
        resolve_workspace_path(workspace, user_path)
        if tool == "write_file":
            content = request.content or ""
            if "\x00" in content:
                raise GuardError("R-PATH-INVALID", "write content contains a NUL")
            size = len(content.encode("utf-8"))
            if size > limits.max_write_bytes:
                raise GuardError("R-LIMIT-WRITE", f"write is {size} bytes; limit is {limits.max_write_bytes}")
