"""Wall-clock the in-process arm. Do not sleep the catalog model latency."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence


def percentile(samples: Sequence[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return ordered[index]


def measure(fn: Callable[[str], object], questions: Sequence[str], repeats: int) -> dict[str, float | int]:
    samples: list[float] = []
    for _ in range(repeats):
        for question in questions:
            started = time.perf_counter()
            fn(question)
            samples.append((time.perf_counter() - started) * 1000)
    return {
        "p50": round(percentile(samples, 0.50), 3),
        "p95": round(percentile(samples, 0.95), 3),
        "n": len(samples),
    }
