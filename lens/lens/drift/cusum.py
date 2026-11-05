"""One-sided CUSUM on a fail-rate series.

s_t = max(0, s_{t-1} + x_t - (mu + k)). An alarm fires when s_t crosses h.
mu is the baseline fail rate, k is the slack (small noise does not accumulate),
h is the threshold. This detects a step sooner than a daily average, and it stays
quiet when the process is on its baseline mean.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CusumResult:
    path: tuple[float, ...]
    alarm_indexes: tuple[int, ...]

    @property
    def first_alarm(self) -> int | None:
        return self.alarm_indexes[0] if self.alarm_indexes else None


def cusum(values: list[float], *, mu: float, k: float, h: float) -> CusumResult:
    path: list[float] = []
    alarms: list[int] = []
    state = 0.0
    for index, value in enumerate(values):
        state = max(0.0, state + value - (mu + k))
        path.append(state)
        if state >= h:
            alarms.append(index)
            state = 0.0
    return CusumResult(tuple(path), tuple(alarms))
