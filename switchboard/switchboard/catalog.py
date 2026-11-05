"""Model sheet and the accounting formulas shared by the router and the eval oracle.

Token counts, prices, catalog latency, and the capability floor live here so
the cost-optimal oracle does not reimplement the price sheet. Selection does
not live here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"
TASKS = ("chat", "code", "summarize", "extract", "math")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    tier: str
    peer: bool
    price_in: float
    price_out: float
    latency_base_ms: float
    latency_per_1k_ms: float
    capability: dict[str, float]
    notes: str

    def capability_for(self, task: str) -> float:
        return self.capability[task]


@dataclass(frozen=True)
class TaskRequirement:
    base: float
    span: float


@dataclass(frozen=True)
class Catalog:
    version: str
    tasks: tuple[str, ...]
    output_ratio: dict[str, float]
    min_output_tokens: int
    requirements: dict[str, TaskRequirement]
    models: dict[str, ModelSpec]
    order: tuple[str, ...]

    def model(self, model_id: str) -> ModelSpec:
        return self.models[model_id]

    def public(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "tasks": list(self.tasks),
            "output_tokens_ratio": self.output_ratio,
            "min_output_tokens": self.min_output_tokens,
            "requirements": {
                task: {"base": req.base, "span": req.span} for task, req in self.requirements.items()
            },
            "models": [
                {
                    "id": spec.id,
                    "display_name": spec.display_name,
                    "tier": spec.tier,
                    "peer": spec.peer,
                    "price_per_1k": {"input": spec.price_in, "output": spec.price_out},
                    "latency_ms": {
                        "base": spec.latency_base_ms,
                        "per_1k_input": spec.latency_per_1k_ms,
                    },
                    "capability": spec.capability,
                    "notes": spec.notes.strip(),
                }
                for spec in self.models.values()
            ],
        }


def estimate_tokens(text: str) -> int:
    """Rough token count. Four characters per token, at least one."""
    return max(1, math.ceil(len(text) / 4))


def estimate_output_tokens(catalog: Catalog, task: str, tokens_in: int) -> int:
    ratio = catalog.output_ratio[task]
    return max(catalog.min_output_tokens, math.ceil(tokens_in * ratio))


def required_capability(catalog: Catalog, task: str, complexity: float) -> float:
    req = catalog.requirements[task]
    return round(req.base + complexity * req.span, 4)


def estimate_cost(spec: ModelSpec, tokens_in: int, tokens_out: int, *, output: bool = True) -> float:
    cost = (tokens_in / 1000) * spec.price_in
    if output:
        cost += (tokens_out / 1000) * spec.price_out
    return cost


def estimate_latency_ms(spec: ModelSpec, tokens_in: int) -> float:
    return spec.latency_base_ms + spec.latency_per_1k_ms * (tokens_in / 1000)


def quality_score(spec: ModelSpec, task: str, complexity: float) -> float:
    """Deterministic stand-in for a grader. Weaker models fall faster as complexity rises."""
    raw = spec.capability_for(task) * (1 - 0.25 * complexity)
    return round(min(1.0, max(0.0, raw)), 4)


def load_catalog(path: Path | None = None) -> Catalog:
    raw = yaml.safe_load((path or DATA_DIR / "catalog.yaml").read_text())
    models: dict[str, ModelSpec] = {}
    order: list[str] = []
    for item in raw["models"]:
        spec = ModelSpec(
            id=item["id"],
            display_name=item["display_name"],
            tier=item["tier"],
            peer=bool(item["peer"]),
            price_in=float(item["price_per_1k"]["input"]),
            price_out=float(item["price_per_1k"]["output"]),
            latency_base_ms=float(item["latency_ms"]["base"]),
            latency_per_1k_ms=float(item["latency_ms"]["per_1k_input"]),
            capability={task: float(item["capability"][task]) for task in raw["tasks"]},
            notes=str(item.get("notes", "")).strip(),
        )
        models[spec.id] = spec
        order.append(spec.id)
    requirements = {
        task: TaskRequirement(base=float(body["base"]), span=float(body["span"]))
        for task, body in raw["requirements"].items()
    }
    return Catalog(
        version=str(raw["version"]),
        tasks=tuple(raw["tasks"]),
        output_ratio={task: float(raw["output_tokens_ratio"][task]) for task in raw["tasks"]},
        min_output_tokens=int(raw["min_output_tokens"]),
        requirements=requirements,
        models=models,
        order=tuple(order),
    )


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    return load_catalog()
