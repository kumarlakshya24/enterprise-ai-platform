"""Population Stability Index on attribute histograms.

PSI compares the share of mass in each bucket between a baseline window and a current
window. Common reading: under 0.10 is quiet, 0.10 to 0.25 is worth a look, over 0.25 is a
real shift. Empty buckets get a tiny floor so a brand-new prompt version cannot divide
by zero; the floor is documented and covered by a test.
"""

from __future__ import annotations

import math


def _probs(counts: dict[str, float], keys: list[str], eps: float) -> dict[str, float]:
    smoothed = {key: float(counts.get(key, 0.0)) + eps for key in keys}
    total = sum(smoothed.values())
    return {key: value / total for key, value in smoothed.items()}


def psi(expected: dict[str, float], actual: dict[str, float], *, eps: float = 1e-6) -> float:
    keys = sorted(set(expected) | set(actual))
    if not keys:
        return 0.0
    base = _probs(expected, keys, eps)
    cur = _probs(actual, keys, eps)
    total = 0.0
    for key in keys:
        total += (cur[key] - base[key]) * math.log(cur[key] / base[key])
    return total
