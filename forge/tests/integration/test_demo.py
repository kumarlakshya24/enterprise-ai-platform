from __future__ import annotations

from forge.demo.runner import run_demo, run_interview


def test_demo_passes() -> None:
    checks = run_demo()
    failed = [check for check in checks if not check.ok]
    assert not failed, [(check.id, check.detail) for check in failed]


def test_interview_passes() -> None:
    checks = run_interview()
    failed = [check for check in checks if not check.ok]
    assert not failed, [(check.id, check.detail) for check in failed]
