"""Load model cards. A card is data. It does not execute."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TIERS = frozenset({"minimal", "limited", "high", "unacceptable"})
STATUSES = frozenset({"active", "proposed", "retired"})


class RegistryError(Exception):
    pass


@dataclass(frozen=True)
class ModelCard:
    id: str
    provider: str
    version: str
    region: str
    risk_tier: str
    status: str
    purpose: str
    intended_use: str
    out_of_scope: tuple[str, ...]
    owner: str
    training_data: str
    task_accuracy: float | None
    known_limitations: tuple[str, ...]
    card_complete: bool
    human_oversight: bool
    provider_reviewed: bool
    logging: str

    def resource(self) -> dict[str, str | bool]:
        """Scalar fields the policy language can compare."""
        return {
            "type": "Model",
            "id": self.id,
            "provider": self.provider,
            "version": self.version,
            "region": self.region,
            "risk_tier": self.risk_tier,
            "status": self.status,
            "purpose": self.purpose,
            "owner": self.owner,
            "card_complete": self.card_complete,
            "human_oversight": self.human_oversight,
            "provider_reviewed": self.provider_reviewed,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "version": self.version,
            "region": self.region,
            "risk_tier": self.risk_tier,
            "status": self.status,
            "purpose": self.purpose,
            "intended_use": self.intended_use,
            "out_of_scope": list(self.out_of_scope),
            "owner": self.owner,
            "training_data": self.training_data,
            "task_accuracy": self.task_accuracy,
            "known_limitations": list(self.known_limitations),
            "card_complete": self.card_complete,
            "human_oversight": self.human_oversight,
            "provider_reviewed": self.provider_reviewed,
            "logging": self.logging,
        }


@dataclass(frozen=True)
class Registry:
    models: tuple[ModelCard, ...]

    def get(self, model_id: str) -> ModelCard | None:
        for card in self.models:
            if card.id == model_id:
                return card
        return None

    def active(self) -> tuple[ModelCard, ...]:
        return tuple(card for card in self.models if card.status == "active")


def _text(raw: Mapping[str, Any], key: str, model_id: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{model_id}: {key} must be a non-empty string")
    return value


def _bool(raw: Mapping[str, Any], key: str, model_id: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise RegistryError(f"{model_id}: {key} must be true or false")
    return value


def _strings(raw: Mapping[str, Any], key: str, model_id: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise RegistryError(f"{model_id}: {key} must be a non-empty list of strings")
    return tuple(value)


def _card(raw: Mapping[str, Any]) -> ModelCard:
    model_id = raw.get("id")
    if not isinstance(model_id, str) or not model_id:
        raise RegistryError("model card is missing id")
    tier = _text(raw, "risk_tier", model_id)
    status = _text(raw, "status", model_id)
    if tier not in TIERS:
        raise RegistryError(f"{model_id}: risk_tier {tier!r} is not one of {sorted(TIERS)}")
    if status not in STATUSES:
        raise RegistryError(f"{model_id}: status {status!r} is not one of {sorted(STATUSES)}")
    provider = _text(raw, "provider", model_id)
    if provider not in ("local", "hosted"):
        raise RegistryError(f"{model_id}: provider must be local or hosted")
    accuracy = raw.get("task_accuracy")
    if accuracy is not None and not isinstance(accuracy, int | float):
        raise RegistryError(f"{model_id}: task_accuracy must be a number or null")
    return ModelCard(
        id=model_id,
        provider=provider,
        version=_text(raw, "version", model_id),
        region=_text(raw, "region", model_id),
        risk_tier=tier,
        status=status,
        purpose=_text(raw, "purpose", model_id),
        intended_use=_text(raw, "intended_use", model_id),
        out_of_scope=_strings(raw, "out_of_scope", model_id),
        owner=_text(raw, "owner", model_id),
        training_data=_text(raw, "training_data", model_id),
        task_accuracy=None if accuracy is None else float(accuracy),
        known_limitations=_strings(raw, "known_limitations", model_id),
        card_complete=_bool(raw, "card_complete", model_id),
        human_oversight=_bool(raw, "human_oversight", model_id),
        provider_reviewed=_bool(raw, "provider_reviewed", model_id),
        logging=_text(raw, "logging", model_id),
    )


def load_registry(path: Path) -> Registry:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("models"), list):
        raise RegistryError(f"{path} must contain a models list")
    cards = tuple(_card(item) for item in loaded["models"])
    ids = [card.id for card in cards]
    if len(ids) != len(set(ids)):
        raise RegistryError("duplicate model id")
    return Registry(cards)
