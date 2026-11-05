"""Shared records. Spans follow the OpenTelemetry trace model; observations are what the judge scores."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    start_ns: int
    end_ns: int
    status_code: str
    status_message: str
    attributes: dict[str, str | int | float | bool]
    service_name: str

    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns


@dataclass(frozen=True)
class Observation:
    """One judged unit. Built from a gold case or from a sampled trace."""

    id: str
    app: str
    question: str
    context: tuple[str, ...]
    output: str
    top_score: float | None
    route: str | None
    label: str | None
    latency_ms: int
    safety_critical: bool


@dataclass(frozen=True)
class Verdict:
    faithful: bool
    relevant: bool
    safe: bool
    refusal_correct: bool
    passed: bool
    faithfulness: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GoldCase:
    id: str
    app: str
    category: str
    safety_critical: bool
    question: str
    context: tuple[str, ...]
    top_score: float | None
    route_baseline: str | None
    route_regressed: str | None
    label_baseline: str | None
    label_regressed: str | None
    output_baseline: str
    output_regressed: str
    latency_ms_baseline: int
    latency_ms_regressed: int
    gold_faithful: bool
    gold_relevant: bool
    gold_safe: bool
    gold_refusal_correct: bool
    regressed_defect: str | None
    known_heuristic_gap: str | None
    note: str

    @property
    def gold_pass(self) -> bool:
        return self.gold_faithful and self.gold_relevant and self.gold_safe and self.gold_refusal_correct

    def observation(self, side: str) -> Observation:
        if side == "baseline":
            output, route, label, latency = (
                self.output_baseline,
                self.route_baseline,
                self.label_baseline,
                self.latency_ms_baseline,
            )
        elif side == "regressed":
            output, route, label, latency = (
                self.output_regressed,
                self.route_regressed,
                self.label_regressed,
                self.latency_ms_regressed,
            )
        else:
            raise ValueError(f"unknown side {side}")
        return Observation(
            id=self.id,
            app=self.app,
            question=self.question,
            context=self.context,
            output=output,
            top_score=self.top_score,
            route=route,
            label=label,
            latency_ms=latency,
            safety_critical=self.safety_critical,
        )
