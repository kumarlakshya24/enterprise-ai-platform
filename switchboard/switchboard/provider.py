"""In-process mock models. No network, no sleep, deterministic text and quality."""

from __future__ import annotations

from dataclasses import dataclass

from switchboard.catalog import Catalog, ModelSpec, estimate_latency_ms, quality_score
from switchboard.classify import Features


class ProviderError(Exception):
    def __init__(self, kind: str, model: str) -> None:
        super().__init__(f"{model} {kind}")
        self.kind = kind
        self.model = model


@dataclass(frozen=True)
class Fault:
    model: str
    mode: str  # timeout, error, low_quality


@dataclass(frozen=True)
class Completion:
    model: str
    text: str
    quality: float
    simulated_latency_ms: float


def render_text(spec: ModelSpec, features: Features, prompt: str) -> str:
    first = " ".join(prompt.strip().split())[:160]
    return (
        f"[mock:{spec.id}] Deterministic offline completion. "
        f"Task={features.task}, complexity={features.complexity:.2f}, "
        f"sensitivity={features.sensitivity}. Echo: {first}"
    )


class MockProvider:
    """Catalog-backed stand-in. Faults fire only when the caller passes one."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def complete(
        self,
        model_id: str,
        features: Features,
        prompt: str,
        fault: Fault | None,
    ) -> Completion:
        spec = self.catalog.model(model_id)
        if fault is not None and fault.model == model_id and fault.mode in {"timeout", "error"}:
            raise ProviderError(fault.mode, model_id)
        quality = quality_score(spec, features.task, features.complexity)
        if fault is not None and fault.model == model_id and fault.mode == "low_quality":
            quality = 0.10
        return Completion(
            model=model_id,
            text=render_text(spec, features, prompt),
            quality=quality,
            simulated_latency_ms=round(estimate_latency_ms(spec, features.tokens_in), 2),
        )
