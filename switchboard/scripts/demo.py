"""Run the locked demo scenarios and print PASS/FAIL. No server required.

python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchboard.demo_data import SCENARIOS
from switchboard.pipeline import RouteRequest, route
from switchboard.provider import Fault
from switchboard.runtime import Runtime
from switchboard.settings import Settings

GREEN, RED, DIM, BOLD, END = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def main() -> None:
    runtime = Runtime(Settings(db_path=":memory:"))
    failures = 0
    print(f"{BOLD}Switchboard demo{END}  {len(SCENARIOS)} scenarios, in-process mocks")
    for scenario in SCENARIOS:
        fault = Fault(**scenario["fault"]) if scenario.get("fault") else None
        decision = route(
            catalog=runtime.catalog,
            policy=runtime.policy(scenario["policy"]),
            provider=runtime.provider,
            store=runtime.store,
            request=RouteRequest(prompt=scenario["prompt"], fault=fault),
        )
        ok = (
            decision["features"]["task"] == scenario["expect_task"]
            and decision["chosen_model"] == scenario["expect_model"]
            and decision["outcome"] == scenario["expect_outcome"]
        )
        failures += 0 if ok else 1
        mark = f"{GREEN}PASS{END}" if ok else f"{RED}FAIL{END}"
        chosen = decision["chosen_model"] or "none"
        savings = decision["comparison"]["savings_pct"]
        print(f"  {mark}  {scenario['id']:<18} {decision['outcome']:<10} {chosen:<12} save {savings:>7}%")
        if not ok:
            print(
                f"       {DIM}expected {scenario['expect_outcome']} / {scenario['expect_model']} "
                f"task {scenario['expect_task']}{END}"
            )
        else:
            print(f"       {DIM}{scenario['blurb']}{END}")
    stats = runtime.store.stats()
    print(
        f"\nRecorded {stats['requests']} decisions. "
        f"Spend ${stats['spend_usd']:.5f} vs always-premium ${stats['always_premium_cost_usd']:.5f} "
        f"({stats['savings_pct']}% saved)."
    )
    if failures:
        print(f"{RED}{failures} failed{END}")
        raise SystemExit(1)
    print(f"{GREEN}{len(SCENARIOS)} / {len(SCENARIOS)} passed{END}")


if __name__ == "__main__":
    main()
