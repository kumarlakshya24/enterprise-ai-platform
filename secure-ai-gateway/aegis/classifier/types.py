"""Classifier output and interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from aegis.types import Label


@dataclass
class Classification:
    label: Label
    confidence: float
    probabilities: dict[str, float]
    top_features: list[tuple[str, float]] = field(default_factory=list)
    escalated_from: Label | None = None
    model_version: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "label": self.label.name,
            "confidence": round(self.confidence, 3),
            "probabilities": {k: round(v, 3) for k, v in self.probabilities.items()},
            "top_features": [{"feature": t, "weight": round(w, 3)} for t, w in self.top_features],
            "escalated_from": self.escalated_from.name if self.escalated_from is not None else None,
            "model_version": self.model_version,
        }


class SensitivityClassifier(Protocol):
    version: str

    def classify(self, text: str, min_confidence: float = 0.0) -> Classification: ...
