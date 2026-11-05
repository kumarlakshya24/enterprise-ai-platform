"""Kappa, PSI, burn rate, percentile. Hand-computed expected values."""

from __future__ import annotations

from lens.drift.cusum import cusum
from lens.drift.psi import psi
from lens.gate.check import percentile
from lens.judge.agreement import cohen_kappa, confusion
from lens.slo.burn import budget_remaining, burn_rate, window_error_rate


def test_kappa_matches_a_hand_calculation() -> None:
    gold = [True, True, True, False, False]
    pred = [True, True, False, False, False]
    # p_o = 0.8, p_e = 0.6*0.4 + 0.4*0.6 = 0.48, kappa = 0.32/0.52
    assert abs(cohen_kappa(gold, pred) - (0.32 / 0.52)) < 1e-12
    assert confusion(gold, pred) == {"tp": 2, "fp": 0, "tn": 2, "fn": 1}


def test_kappa_is_one_when_raters_agree_perfectly() -> None:
    labels = [True, False, True, True]
    assert cohen_kappa(labels, labels) == 1.0


def test_psi_textbook_two_bucket_shift() -> None:
    # (0.5-0.9)*ln(0.5/0.9) + (0.5-0.1)*ln(0.5/0.1) ≈ 0.8789
    value = psi({"a": 9000, "b": 1000}, {"a": 5000, "b": 5000})
    assert abs(value - 0.8789) < 0.01


def test_psi_is_quiet_when_the_mix_does_not_move() -> None:
    assert psi({"a": 50, "b": 50}, {"a": 500, "b": 500}) < 0.01


def test_burn_rate_fast_page_threshold() -> None:
    # 7.2% errors against a 0.5% budget is a 14.4x burn: 2% of a 30-day budget in one hour.
    assert abs(burn_rate(0.072, 0.005) - 14.4) < 1e-9


def test_budget_remaining_hits_zero_at_twice_the_budget() -> None:
    # Burn 2 for half the window consumes the whole budget.
    remaining = budget_remaining(0.10, 0.05, elapsed_hours=360, window_hours=720)
    assert abs(remaining) < 1e-9


def test_window_error_rate_uses_only_the_requested_hours() -> None:
    totals = [10, 10, 10, 10]
    goods = [10, 10, 8, 10]
    # end=3, 2 hours → indexes 2 and 3 (one bad hour). end=1, 2 hours → indexes 0 and 1 (clean).
    assert abs(window_error_rate(totals, goods, end=3, hours=2) - 0.1) < 1e-9
    assert abs(window_error_rate(totals, goods, end=1, hours=2) - 0.0) < 1e-9


def test_percentile_nearest_rank() -> None:
    values = [float(i) for i in range(1, 101)]
    assert percentile(values, 0.95) == 95.0
    assert percentile(values, 0.50) == 50.0


def test_cusum_stays_quiet_then_alarms_on_a_step() -> None:
    quiet = [0.04] * 20
    shifted = [0.40] * 6
    result = cusum(quiet + shifted, mu=0.04, k=0.03, h=0.25)
    assert result.first_alarm is not None
    assert result.first_alarm >= 20
    assert all(index >= 20 for index in result.alarm_indexes)
