"""Tail sampling for failures, plus a deterministic stratified sample for evaluation.

Head sampling (keep 1% of arrivals) drops the rare safety failure and the slow trace.
Judging every request with a strong model does not scale. The decision here is:

- keep errors, slow traces, and explicit safety signals (tail)
- otherwise keep the trace when a stable hash of (app, model, trace id) falls under the
  stratum rate (unbiased eval sample)
- drop the body otherwise; attribute counters for drift still see every span
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SampleDecision:
    keep: bool
    reason: str


def _bucket(app: str, model: str, trace_id: str) -> int:
    raw = f"{app}|{model}|{trace_id}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16) % 10_000


def decide(
    *,
    trace_id: str,
    status: str,
    latency_ms: float,
    safety_signal: bool,
    app: str,
    model: str,
    rate: float,
    slow_ms: float,
) -> SampleDecision:
    if status != "ok":
        return SampleDecision(True, "error")
    if latency_ms >= slow_ms:
        return SampleDecision(True, "slow")
    if safety_signal:
        return SampleDecision(True, "safety_signal")
    if rate < 0 or rate > 1:
        raise ValueError("sample rate must be between 0 and 1")
    threshold = round(rate * 10_000)
    if _bucket(app, model, trace_id) < threshold:
        return SampleDecision(True, "eval_stratum")
    return SampleDecision(False, "drop")
