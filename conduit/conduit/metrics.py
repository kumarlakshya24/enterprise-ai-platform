"""Percentiles and the cost projection. Pure functions, no I/O."""

from __future__ import annotations

import math


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile. `p` is in 0..1."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, math.ceil(p * len(ordered)))
    return ordered[rank - 1]


def lag_summary(values: list[float]) -> dict[str, float | int]:
    return {
        "p50": round(percentile(values, 0.50), 4),
        "p95": round(percentile(values, 0.95), 4),
        "p99": round(percentile(values, 0.99), 4),
        "n": len(values),
    }


def tokens_from_chars(chars: float, chars_per_token: float = 4.0) -> float:
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    return chars / chars_per_token


def usd_per_million_docs(tokens_per_doc: float, usd_per_million_tokens: float) -> float:
    """List-price projection. Not an invoice.

    A million documents at `tokens_per_doc` each, priced per million tokens.
    """
    return tokens_per_doc * usd_per_million_tokens
