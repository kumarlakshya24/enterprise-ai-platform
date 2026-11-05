"""Load workflow YAML and normalize activity definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from atlas.domain import PlanError
from atlas.jsonutil import money
from atlas.tools import TOOL_META

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"

_DEFAULTS: dict[str, Any] = {
    "deps": [],
    "cost_usd": 0.0,
    "latency_ms": 20,
    "timeout_ms": 2000,
    "max_attempts": 3,
    "backoff_ms": 20,
    "side_effect": False,
    "idempotent": True,
    "risk": "low",
    "args": {},
    "when": None,
    "compensate": None,
    "on_block": "fail",
    "order": 100,
    "agent": "specialist",
}


def load_workflow(workflow_id: str) -> dict[str, Any]:
    path = WORKFLOWS / f"{workflow_id}.yaml"
    if not path.is_file():
        raise PlanError(f"unknown workflow {workflow_id}")
    data = yaml.safe_load(path.read_text())
    if data.get("id") != workflow_id:
        raise PlanError(f"{path.name} id does not match the file name")
    return normalize(data)


def list_workflows() -> list[dict[str, Any]]:
    items = []
    for path in sorted(WORKFLOWS.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        items.append(
            {
                "id": data["id"],
                "title": data.get("title", data["id"]),
                "summary": data.get("summary", ""),
            }
        )
    return items


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    activities = [_activity(raw) for raw in data["activities"]]
    _validate(activities)
    budget = dict(data.get("budget") or {})
    budget.setdefault("max_steps", 20)
    budget.setdefault("max_cost_usd", 1.0)
    budget.setdefault("on_exceeded", "pause")
    return {
        "id": data["id"],
        "title": data.get("title", data["id"]),
        "summary": data.get("summary", ""),
        "on_failure": data.get("on_failure", "compensate"),
        "budget": budget,
        "activities": activities,
    }


def _activity(raw: dict[str, Any]) -> dict[str, Any]:
    item = dict(_DEFAULTS)
    item.update(raw)
    item["deps"] = list(item.get("deps") or [])
    item["args"] = dict(item.get("args") or {})
    item["cost_usd"] = money(item["cost_usd"])
    item["latency_ms"] = int(item["latency_ms"])
    item["timeout_ms"] = int(item["timeout_ms"])
    item["max_attempts"] = int(item["max_attempts"])
    item["backoff_ms"] = int(item["backoff_ms"])
    item["side_effect"] = bool(item["side_effect"])
    item["idempotent"] = bool(item["idempotent"])
    meta = TOOL_META.get(item["tool"])
    if meta and not meta["idempotent"]:
        item["idempotent"] = False
    if meta and meta["side_effect"]:
        item["side_effect"] = True
    return item


def _validate(activities: list[dict[str, Any]]) -> None:
    ids = [item["id"] for item in activities]
    if len(ids) != len(set(ids)):
        raise PlanError("duplicate activity id")
    known = set(ids)
    for item in activities:
        if item["tool"] not in TOOL_META and item["tool"] != "approval.gate":
            raise PlanError(f"unknown tool {item['tool']}")
        for dep in item["deps"]:
            if dep not in known:
                raise PlanError(f"{item['id']} depends on unknown activity {dep}")
        if item["compensate"] and item["compensate"] not in TOOL_META:
            raise PlanError(f"unknown compensation tool {item['compensate']}")
    _cycles(activities)


def _cycles(activities: list[dict[str, Any]]) -> None:
    deps = {item["id"]: item["deps"] for item in activities}
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise PlanError(f"cycle at {node}")
        visiting.add(node)
        for dep in deps[node]:
            walk(dep)
        visiting.remove(node)
        visited.add(node)

    for node in deps:
        walk(node)
