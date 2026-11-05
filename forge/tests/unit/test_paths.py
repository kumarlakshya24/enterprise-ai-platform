from __future__ import annotations

from pathlib import Path

import pytest

from forge.guard.imports import GuardError
from forge.guard.paths import resolve_workspace_path


def test_relative_file_resolves(tmp_path: Path) -> None:
    target = tmp_path / "notes" / "summary.txt"
    target.parent.mkdir()
    target.write_text("ok", encoding="utf-8")
    assert resolve_workspace_path(tmp_path, "notes/summary.txt") == target


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("../secret.txt", "R-PATH-TRAVERSAL"),
        ("notes/../../secret.txt", "R-PATH-TRAVERSAL"),
        ("/etc/hostname", "R-PATH-ABSOLUTE"),
        ("/tmp/forge-canary.txt", "R-PATH-ABSOLUTE"),
        ("", "R-PATH-INVALID"),
        (" notes/summary.txt", "R-PATH-INVALID"),
        ("notes/\x00x", "R-PATH-INVALID"),
        ("notes\\summary.txt", "R-PATH-INVALID"),
    ],
)
def test_rejected_paths(tmp_path: Path, path: str, rule: str) -> None:
    with pytest.raises(GuardError) as caught:
        resolve_workspace_path(tmp_path, path)
    assert caught.value.rule == rule


def test_symlink_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary.txt"
    canary.write_text("CANARY-OUTSIDE", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "alias.txt").symlink_to(canary)
    with pytest.raises(GuardError) as caught:
        resolve_workspace_path(workspace, "alias.txt")
    assert caught.value.rule == "R-PATH-SYMLINK"
