"""Shared domain types: sensitivity labels, routes, entity types, findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class Label(IntEnum):
    """Sensitivity labels, ordered from least to most sensitive."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, value: str | int | Label) -> Label:
        if isinstance(value, Label):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.strip().upper()]


class Route(StrEnum):
    """What the gateway does with a request."""

    ALLOW = "allow"
    REDACT = "redact_and_continue"
    REQUIRE_APPROVAL = "require_approval"
    LOCAL_ONLY = "local_only"
    BLOCK = "block"

    @property
    def strictness(self) -> int:
        """Exposure ordering: higher means less data can reach a third party.

        `require_approval` can still send data out after a human says yes, so it is less
        strict than `local_only`, which never sends data out.
        """
        return _ROUTE_STRICTNESS[self]

    @property
    def sends_external(self) -> bool:
        return self in (Route.ALLOW, Route.REDACT)


_ROUTE_STRICTNESS = {
    Route.ALLOW: 0,
    Route.REDACT: 1,
    Route.REQUIRE_APPROVAL: 2,
    Route.LOCAL_ONLY: 3,
    Route.BLOCK: 4,
}


class EntityType(StrEnum):
    PERSON_NAME = "PERSON_NAME"
    ORG = "ORG"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    CREDIT_CARD = "CREDIT_CARD"
    SSN = "SSN"
    API_KEY = "API_KEY"
    PASSWORD = "PASSWORD"  # noqa: S105 - entity type name, not a secret
    PRIVATE_KEY = "PRIVATE_KEY"


SECRET_TYPES = frozenset({EntityType.API_KEY, EntityType.PASSWORD, EntityType.PRIVATE_KEY})


class EntityAction(StrEnum):
    TOKENIZE = "tokenize"  # reversible placeholder, value kept in the vault
    REDACT = "redact"  # irreversible placeholder, value discarded
    BLOCK = "block"  # whole request is blocked
    ALLOW = "allow"  # value passes through unchanged


class FindingStatus(StrEnum):
    APPLIED = "applied"
    BELOW_THRESHOLD = "below_threshold"
    ALLOWLISTED = "allowlisted"
    OVERLAPPED = "overlapped"


class RestoreScope(IntEnum):
    NEVER = 0
    MASKED = 1
    FULL = 2


@dataclass
class Finding:
    """One detected sensitive span. `value` is never serialized by `public_dict`."""

    entity_type: EntityType
    start: int
    end: int
    confidence: float
    detector: str
    explanation: str
    value: str = field(default="", repr=False)
    canonical: str = field(default="", repr=False)
    priority: int = 50
    status: FindingStatus = FindingStatus.APPLIED
    action: EntityAction = EntityAction.ALLOW
    placeholder: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "start": self.start,
            "end": self.end,
            "confidence": round(self.confidence, 3),
            "detector": self.detector,
            "explanation": self.explanation,
            "status": self.status.value,
            "action": self.action.value,
            "placeholder": self.placeholder,
        }
