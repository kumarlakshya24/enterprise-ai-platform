"""Unprotected decision preview. This module never executes a tool call."""

from __future__ import annotations

from pathlib import Path

from forge.guard.ast_guard import check_python
from forge.guard.constants import KNOWN_TOOLS, SHELL_TOOL
from forge.guard.imports import GuardError
from forge.guard.paths import resolve_workspace_path
from forge.policy.engine import effective_limits
from forge.policy.schema import Policy
from forge.types import Preview, ToolRequest

_NOTES = {
    "shell": (
        "A host shell would accept a command string. Forge has no shell executor, "
        "and enabling the tool in policy does not create one."
    ),
    "unknown": "Without an allowlist, an agent runtime would try to dispatch this tool name.",
    "syntax": "The snippet is not valid Python, so a raw interpreter would reject it too.",
    "resource": "A raw interpreter would run this snippet with no size, time, or output cap.",
    "filesystem": "A raw file API would use this path on the host. Forge refuses it before any read or write.",
    "guard": "A raw interpreter would execute this snippet. Forge refused it and did not run it.",
    "none": "A raw interpreter would run this call. Forge runs it inside the sandbox and writes an audit record.",
}


def build_preview(request: ToolRequest, policy: Policy, workspace: Path) -> Preview:
    tool = request.tool
    if tool == SHELL_TOOL:
        return Preview(True, False, "shell", _NOTES["shell"])
    if tool not in KNOWN_TOOLS:
        return Preview(True, False, "unknown", _NOTES["unknown"])
    if tool == "python":
        return _python_preview(request, policy)
    return _path_preview(request, workspace)


def _python_preview(request: ToolRequest, policy: Policy) -> Preview:
    code = request.code or ""
    if not code.strip():
        return Preview(False, False, "syntax", _NOTES["syntax"])
    limits = effective_limits(policy, "python")
    allow = limits.allow_imports if limits else frozenset()
    deny = limits.deny_imports if limits else frozenset()
    max_bytes = limits.max_code_bytes if limits else 4000
    try:
        check_python(code, allow=allow, deny=deny, max_bytes=max_bytes)
    except GuardError as exc:
        if exc.rule == "R-SYNTAX":
            return Preview(False, False, "syntax", _NOTES["syntax"])
        if exc.rule == "R-LIMIT-CODE":
            return Preview(True, False, "resource", _NOTES["resource"])
        return Preview(True, False, exc.rule, _NOTES["guard"])
    return Preview(True, False, "none", _NOTES["none"])


def _path_preview(request: ToolRequest, workspace: Path) -> Preview:
    user_path = request.path if request.path is not None else "."
    try:
        resolve_workspace_path(workspace, user_path)
    except GuardError:
        return Preview(True, False, "filesystem", _NOTES["filesystem"])
    return Preview(True, False, "none", _NOTES["none"])
