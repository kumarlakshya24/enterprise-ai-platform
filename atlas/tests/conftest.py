"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.clock import ManualClock
from atlas.engine import Engine
from atlas.guard import OfflineAegisGuard
from atlas.knowledge import OfflineLumen
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store


class World:
    def __init__(self, tmp: Path) -> None:
        self.clock = ManualClock()
        self.store = Store(str(tmp / "atlas.db"))
        self.effects = EffectStore(str(tmp / "effects.db"))
        self.engine = Engine(
            self.store,
            self.effects,
            llm=MockLLM(),
            guard=OfflineAegisGuard(),
            knowledge=OfflineLumen(),
            clock=self.clock,
            lease_ttl=30,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def refund(**overrides: object) -> dict:
    payload = {
        "customer_id": "cus_1042",
        "amount_usd": 40,
        "email": "dana.holloway@example.com",
        "reason": "duplicate charge",
        "policy_question": "What is the customer refund policy?",
    }
    payload.update(overrides)
    return payload
