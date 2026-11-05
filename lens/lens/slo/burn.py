"""Multi-window burn rates, in the SRE workbook sense.

error budget fraction = 1 - target.
burn rate = (error rate in the window) / (error budget fraction).

A burn of 1 spends the budget exactly over the SLO window (30 days here).
A burn of 14.4 spends about 2% of that budget in one hour, which is the fast page.
A burn of 6 spends about 5% of it in six hours, which is the slow page.

Hourly counters cannot see the 5-minute confirmation window the workbook pairs with
the 1-hour window. That limit is stated in docs/FAILURE_MODES.md; the math here is
the long window only.
"""

from __future__ import annotations


def window_error_rate(
    totals: list[int],
    goods: list[int],
    end: int,
    hours: int,
) -> float:
    if len(totals) != len(goods):
        raise ValueError("totals and goods length mismatch")
    if end < 0 or end >= len(totals):
        raise ValueError("end index out of range")
    start = max(0, end - hours + 1)
    total = sum(totals[start : end + 1])
    good = sum(goods[start : end + 1])
    if total <= 0:
        return 0.0
    return 1.0 - (good / total)


def burn_rate(error_rate: float, budget: float) -> float:
    if budget <= 0:
        raise ValueError("budget must be positive")
    return error_rate / budget


def budget_remaining(
    error_rate: float,
    budget: float,
    elapsed_hours: int,
    window_hours: int,
) -> float:
    """Share of the SLO-window budget still left. Negative means the budget is already gone.

    consumed = burn * (elapsed / window). At burn 1 the budget lasts exactly `window_hours`.
    """

    if window_hours <= 0:
        raise ValueError("window must be positive")
    return 1.0 - burn_rate(error_rate, budget) * (elapsed_hours / window_hours)
