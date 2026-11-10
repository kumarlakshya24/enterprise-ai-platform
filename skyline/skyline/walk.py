"""Walk a synthesized assembly. Invariants and FinOps both use this."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_resources(assembly: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    stacks = assembly["stacks"]
    for stack_name in sorted(stacks):
        resources = stacks[stack_name]["Resources"]
        for logical in sorted(resources):
            yield stack_name, logical, resources[logical]


def skyline_meta(resource: dict[str, Any]) -> dict[str, Any]:
    meta = resource.get("Metadata", {}).get("Skyline", {})
    if isinstance(meta, dict):
        return meta
    return {}


def statements_of(document: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not document:
        return []
    raw = document.get("Statement", [])
    if isinstance(raw, dict):
        return [raw]
    return list(raw)


def role_statements(resource: dict[str, Any]) -> list[dict[str, Any]]:
    props = resource["Properties"]
    found: list[dict[str, Any]] = []
    for attached in props.get("Policies", []):
        found.extend(statements_of(attached.get("PolicyDocument")))
    return found


def actions(statement: dict[str, Any]) -> list[str]:
    raw = statement.get("Action", [])
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def resources_of(statement: dict[str, Any]) -> list[str]:
    raw = statement.get("Resource", [])
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw]


def principal_is_wildcard(principal: Any) -> bool:
    if principal == "*":
        return True
    if isinstance(principal, dict):
        aws = principal.get("AWS", [])
        values = [aws] if isinstance(aws, str) else list(aws)
        return any(item == "*" for item in values)
    return False
