"""Fixed-window per-user rate limit, shared across replicas through the KV backend."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from aegis.vault.backends import KVBackend


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: int


class RateLimiter:
    def __init__(self, backend: KVBackend, per_minute: int, clock: Callable[[], float] = time.time) -> None:
        self.backend = backend
        self.per_minute = per_minute
        self.clock = clock

    def check(self, tenant_id: str, subject: str, bucket: str = "default") -> RateDecision:
        if self.per_minute <= 0:
            return RateDecision(True, 0, 0)
        now = self.clock()
        window = int(now // 60)
        n = self.backend.incr(f"aegis:v1:rl:{tenant_id}:{subject}:{bucket}:{window}", 120)
        if n > self.per_minute:
            return RateDecision(False, 0, 60 - int(now % 60))
        return RateDecision(True, self.per_minute - n, 0)
