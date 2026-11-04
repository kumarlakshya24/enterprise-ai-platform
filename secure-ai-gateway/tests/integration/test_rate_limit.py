"""Per-user rate limiting."""

from __future__ import annotations

from aegis.auth.ratelimit import RateLimiter
from aegis.vault.backends import MemoryBackend


def test_limiter_window() -> None:
    now = [1_000_000.0]
    rl = RateLimiter(MemoryBackend(), per_minute=3, clock=lambda: now[0])
    assert [rl.check("acme", "u", "chat").allowed for _ in range(4)] == [True, True, True, False]
    assert rl.check("acme", "other", "chat").allowed  # per user
    now[0] += 60
    assert rl.check("acme", "u", "chat").allowed  # next window


def test_gateway_returns_429_and_audits(gateway_factory) -> None:  # type: ignore[no-untyped-def]
    gw = gateway_factory(rate_limit_per_minute=2)
    codes = [gw.post("/chat", "avery", {"message": "hello there"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    events = gw.get("/audit", "sam", event_type="rate_limited").json()["events"]
    assert events and events[0]["user_id"] == "u-1001"
