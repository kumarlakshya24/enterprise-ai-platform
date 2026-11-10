"""Structural diff of two assemblies. Paths are stable because JSON keys are sorted."""

from __future__ import annotations

from typing import Any


def diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"after": after[key], "before": None, "op": "add", "path": child})
            elif key not in after:
                changes.append({"after": None, "before": before[key], "op": "remove", "path": child})
            else:
                changes.extend(diff(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        common = min(len(before), len(after))
        for index in range(common):
            changes.extend(diff(before[index], after[index], f"{path}[{index}]"))
        for index in range(common, len(before)):
            changes.append(
                {"after": None, "before": before[index], "op": "remove", "path": f"{path}[{index}]"}
            )
        for index in range(common, len(after)):
            changes.append({"after": after[index], "before": None, "op": "add", "path": f"{path}[{index}]"})
        return changes
    return [{"after": after, "before": before, "op": "change", "path": path or "$"}]
