"""Print one refund trace. `make demo`."""

from __future__ import annotations

import tempfile
from pathlib import Path

from atlas.clock import ManualClock
from atlas.engine import Engine
from atlas.guard import OfflineAegisGuard
from atlas.knowledge import OfflineLumen
from atlas.llm import MockLLM
from atlas.store import EffectStore, Store


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="atlas-demo-"))
    clock = ManualClock()
    engine = Engine(
        Store(str(root / "atlas.db")),
        EffectStore(str(root / "effects.db")),
        llm=MockLLM(),
        guard=OfflineAegisGuard(),
        knowledge=OfflineLumen(),
        clock=clock,
    )
    inputs = {
        "customer_id": "cus_1042",
        "amount_usd": 40,
        "email": "dana.holloway@example.com",
        "reason": "duplicate charge",
    }
    paused = engine.start("refund", inputs, idempotency_key="demo-refund")
    print(f"paused for approval: {paused['status']}  steps={paused['steps']}")
    print(f"  plan: {paused['plan_rationale']}")
    done = engine.decide(paused["id"], "approved", "morgan")
    print(f"after morgan approves: {done['status']}  cost=${done['cost_usd']:.3f}")
    for activity in done["activities"]:
        print(f"  {activity['agent']:10} {activity['id']:16} {activity['status']}")
    print("side effects:")
    for effect in done["effects"]:
        print(f"  {effect['tool']:16} {effect['payload']}")
    print("\nFor the SIGKILL proof: make kill-resume")


if __name__ == "__main__":
    main()
