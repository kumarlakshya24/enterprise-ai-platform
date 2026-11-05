"""Versioned routing policies. YAML in, validated objects out."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from switchboard.catalog import DATA_DIR

POLICY_DIR = DATA_DIR / "policies"
SELECTIONS = ("weighted", "cheapest", "fastest", "highest_capability")
WAIVERS = ("capability", "budget", "latency", "quality")


class PolicyError(ValueError):
    """A policy file or candidate body failed validation."""


@dataclass(frozen=True)
class Rule:
    id: str
    description: str
    when: dict[str, Any]
    pin: str | None = None
    waive: tuple[str, ...] = ()
    stop_fallback: bool = False
    max_latency_ms: float | None = None
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fallback:
    order: tuple[str, ...]
    allow_local_on_total_failure: bool
    max_attempts: int


@dataclass(frozen=True)
class Policy:
    name: str
    version: str
    description: str
    selection: str
    weights: dict[str, float]
    budget_usd: float
    latency_slo_ms: float
    min_quality: float
    min_headroom: float
    fallback: Fallback
    rules: tuple[Rule, ...]

    @property
    def version_id(self) -> str:
        return f"{self.name}@{self.version}"

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "version_id": self.version_id,
            "description": " ".join(self.description.split()),
            "selection": self.selection,
            "weights": self.weights,
            "budget_usd": self.budget_usd,
            "latency_slo_ms": self.latency_slo_ms,
            "min_quality": self.min_quality,
            "min_headroom": self.min_headroom,
            "fallback": {
                "order": list(self.fallback.order),
                "allow_local_on_total_failure": self.fallback.allow_local_on_total_failure,
                "max_attempts": self.fallback.max_attempts,
            },
            "rules": [
                {
                    "id": rule.id,
                    "description": " ".join(rule.description.split()),
                    "when": rule.when,
                    "pin": rule.pin,
                    "waive": list(rule.waive),
                    "stop_fallback": rule.stop_fallback,
                    "max_latency_ms": rule.max_latency_ms,
                    "exclude": list(rule.exclude),
                }
                for rule in self.rules
            ],
        }


def _weights(raw: dict[str, Any]) -> dict[str, float]:
    weights = {key: float(raw[key]) for key in ("capability", "cost", "latency")}
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise PolicyError(f"weights must sum to 1.0, got {total:.6f}")
    if any(value < 0 for value in weights.values()):
        raise PolicyError("weights must be non-negative")
    return weights


def parse_policy(raw: dict[str, Any], *, known_models: set[str]) -> Policy:
    if not isinstance(raw, dict):
        raise PolicyError("policy must be a mapping")
    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    if not name or not version:
        raise PolicyError("policy name and version are required")
    selection = str(raw.get("selection", ""))
    if selection not in SELECTIONS:
        raise PolicyError(f"selection must be one of {', '.join(SELECTIONS)}")
    fallback_raw = raw.get("fallback") or {}
    order = tuple(str(item) for item in fallback_raw.get("order", []))
    if not order:
        raise PolicyError("fallback.order must list at least one model")
    unknown = [item for item in order if item not in known_models]
    if unknown:
        raise PolicyError(f"fallback.order names unknown models: {', '.join(unknown)}")
    rules: list[Rule] = []
    for body in raw.get("rules") or []:
        pin = body.get("pin")
        if pin is not None and pin not in known_models:
            raise PolicyError(f"rule {body.get('id')} pins unknown model {pin}")
        exclude = tuple(str(item) for item in body.get("exclude") or [])
        missing = [item for item in exclude if item not in known_models]
        if missing:
            raise PolicyError(f"rule {body.get('id')} excludes unknown models: {', '.join(missing)}")
        waive = tuple(str(item) for item in body.get("waive") or [])
        bad = [item for item in waive if item not in WAIVERS]
        if bad:
            raise PolicyError(f"rule {body.get('id')} has unknown waivers: {', '.join(bad)}")
        rule_id = str(body.get("id", "")).strip()
        if not rule_id:
            raise PolicyError("every rule needs an id")
        rules.append(
            Rule(
                id=rule_id,
                description=str(body.get("description", "")),
                when=dict(body.get("when") or {}),
                pin=str(pin) if pin else None,
                waive=waive,
                stop_fallback=bool(body.get("stop_fallback", False)),
                max_latency_ms=(
                    float(body["max_latency_ms"]) if body.get("max_latency_ms") is not None else None
                ),
                exclude=exclude,
            )
        )
    return Policy(
        name=name,
        version=version,
        description=str(raw.get("description", "")),
        selection=selection,
        weights=_weights(raw.get("weights") or {}),
        budget_usd=float(raw["budget_usd"]),
        latency_slo_ms=float(raw["latency_slo_ms"]),
        min_quality=float(raw["min_quality"]),
        min_headroom=float(raw.get("min_headroom", 0)),
        fallback=Fallback(
            order=order,
            allow_local_on_total_failure=bool(fallback_raw.get("allow_local_on_total_failure", False)),
            max_attempts=int(fallback_raw.get("max_attempts", 3)),
        ),
        rules=tuple(rules),
    )


def load_policy_text(text: str, *, known_models: set[str]) -> Policy:
    loaded = yaml.safe_load(text)
    if loaded is None:
        raise PolicyError("policy YAML is empty")
    return parse_policy(loaded, known_models=known_models)


def load_policies(directory: Path | None = None, *, known_models: set[str]) -> dict[str, Policy]:
    folder = directory or POLICY_DIR
    found: dict[str, Policy] = {}
    for path in sorted(folder.glob("*.yaml")):
        policy = load_policy_text(path.read_text(), known_models=known_models)
        if policy.name != path.stem:
            raise PolicyError(f"{path.name} declares name {policy.name!r}; file stem must match")
        found[policy.name] = policy
    if "default" not in found:
        raise PolicyError("default policy is missing")
    return found


@dataclass
class Constraints:
    budget_usd: float
    latency_slo_ms: float
    required_capability: float
    min_quality: float
    min_headroom: float = 0.0
    waivers: list[str] = field(default_factory=list)
    applied_rules: list[str] = field(default_factory=list)
    pin: str | None = None
    stop_fallback: bool = False
    exclude: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "budget_usd": round(self.budget_usd, 6),
            "latency_slo_ms": self.latency_slo_ms,
            "required_capability": self.required_capability,
            "min_quality": self.min_quality,
            "min_headroom": self.min_headroom,
            "waivers": list(self.waivers),
            "applied_rules": list(self.applied_rules),
            "pin": self.pin,
            "stop_fallback": self.stop_fallback,
            "exclude": sorted(self.exclude),
        }
