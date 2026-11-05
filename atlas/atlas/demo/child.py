"""Worker process used by the SIGKILL demo. Not the API server."""

from __future__ import annotations

import argparse

from atlas.clock import SystemClock
from atlas.engine import CrashSpec, Engine
from atlas.guard import OfflineAegisGuard
from atlas.knowledge import OfflineLumen
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--effects", required=True)
    parser.add_argument("--lease", type=float, default=0.4)
    parser.add_argument("--crash", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args()
    clock = SystemClock()
    engine = Engine(
        Store(args.db),
        EffectStore(args.effects),
        llm=MockLLM(),
        guard=OfflineAegisGuard(),
        knowledge=OfflineLumen(),
        clock=clock,
        lease_ttl=args.lease,
    )
    engine.start(
        "refund",
        {
            "customer_id": "cus_1042",
            "amount_usd": 40,
            "email": "dana.holloway@example.com",
            "reason": "duplicate charge",
            "policy_question": "What is the customer refund policy?",
        },
        idempotency_key=args.idempotency_key,
        auto_approve=True,
        owner="child",
        crash=CrashSpec.parse(args.crash, mode="sigkill"),
    )


if __name__ == "__main__":
    main()
