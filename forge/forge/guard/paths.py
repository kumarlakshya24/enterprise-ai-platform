"""Workspace path rules.

Absolute paths, parent segments, and symlinks are refused. The check is lexical
plus an lstat of each component so a symlink is not followed.
"""

from __future__ import annotations

from pathlib import Path

from forge.guard.imports import GuardError


def resolve_workspace_path(workspace: Path, user_path: str) -> Path:
    if not isinstance(user_path, str) or user_path == "" or user_path != user_path.strip():
        raise GuardError("R-PATH-INVALID", "path must be a non-empty relative path")
    if len(user_path) > 200 or "\x00" in user_path or "\\" in user_path:
        raise GuardError("R-PATH-INVALID", "path contains an illegal character")
    raw = Path(user_path)
    if raw.is_absolute():
        raise GuardError("R-PATH-ABSOLUTE", "absolute paths are outside the workspace")
    if any(part == ".." for part in raw.parts):
        raise GuardError("R-PATH-TRAVERSAL", "parent segments are not allowed")
    if len(raw.parts) > 8:
        raise GuardError("R-PATH-INVALID", "path is too deep")

    base = workspace.resolve()
    current = base
    for part in raw.parts:
        if part == ".":
            continue
        current = current / part
        if current.is_symlink():
            raise GuardError("R-PATH-SYMLINK", "symlinks are refused")
    if current != base and base not in current.parents:
        raise GuardError("R-PATH-ESCAPE", "path escapes the workspace")
    return current
