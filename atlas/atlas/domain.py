"""Shared types, statuses, and errors."""

from __future__ import annotations

TERMINAL = frozenset({"completed", "failed", "denied", "compensated", "compensation_failed"})
PAUSED = frozenset({"paused_approval", "paused_budget", "waiting_retry"})
SATISFIED = frozenset({"completed", "skipped"})
HEAL_MS = 1

CHECKPOINT_EVENTS = frozenset(
    {
        "activity_completed",
        "activity_healed",
        "activity_failed",
        "activity_skipped",
        "compensation_completed",
        "run_status",
        "budget_paused",
        "plan_recorded",
    }
)


class CrashInjected(Exception):
    """The worker stopped in a crash window. Committed work stays committed."""

    def __init__(self, run_id: str, activity_id: str, phase: str) -> None:
        super().__init__(f"crashed {run_id} at {activity_id}:{phase}")
        self.run_id = run_id
        self.activity_id = activity_id
        self.phase = phase


class LeaseHeld(Exception):
    def __init__(self, run_id: str, owner: str, expires_at: float) -> None:
        super().__init__(f"run {run_id} is leased to {owner} until {expires_at}")
        self.run_id = run_id
        self.owner = owner
        self.expires_at = expires_at


class StaleLease(Exception):
    """A write lost the fencing epoch. The caller must not retry the side effect."""

    def __init__(self, run_id: str, epoch: int) -> None:
        super().__init__(f"stale lease epoch {epoch} on {run_id}")
        self.run_id = run_id
        self.epoch = epoch


class IdempotencyConflict(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"idempotency key {key} was reused with a different payload")
        self.key = key


class PlanError(Exception):
    pass
