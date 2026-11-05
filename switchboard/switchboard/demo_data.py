"""Fixed prompts the demo, the UI, and the tests all share.

Expected routes are locked after the router is run against these exact strings.
If a prompt changes, re-check the expectation. Do not generate the expectation
from the router inside this file.
"""

from __future__ import annotations

from typing import Any

EASY_CHAT = "What is a load balancer, in two sentences?"

MODERATE_CHAT = (
    "Explain cache invalidation for a production API. Cover stale reads, thundering "
    "herds, and the edge cases that show up when two regions write the same key. "
    "I want the tradeoffs a reviewer would ask about, including what you give up "
    "by caching at the edge versus caching in the service. Keep it concrete."
)

HARD_MATH = (
    "Prove the theorem formally and show the asymptotic bound step by step. "
    "Then prove the edge case where the bound is tight, and state the assumptions "
    "you needed for the formal argument."
)

MEDIUM_CODE = (
    "Refactor this function for production.\n\n"
    "```python\n"
    "def load(path):\n"
    "    return open(path).read()\n"
    "```\n"
)

HARD_CODE = (
    "Refactor this service for a concurrent production migration. Optimize the "
    "hot path and cover the edge cases around partial failure.\n\n"
    "```python\n"
    "def handle(events):\n"
    "    for event in events:\n"
    "        write(event)\n"
    "```\n"
    "The migration has to keep the old reader working while the new writer is "
    "turned on, region by region. Call out what breaks under concurrent writers."
)

SENSITIVE = (
    "Confidential note: Ada's email is ada@example.com. Summarize the billing "
    "complaint for the on-call engineer and do not send it to a hosted tool."
)

REALTIME = "Reply asap, in one sentence: what is a load balancer?"


# Expectations below are the product spec for these prompts, not a dump of one run.
# default headroom 0.10 drops fast-cheap on easy chat when balanced still qualifies.
# cost-saver headroom 0 keeps fast-cheap. latency-first SLO 100 ms also keeps it.
# quality-first takes the highest capability that clears the floor.
SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "easy-chat",
        "title": "Easy chat, default policy",
        "blurb": (
            "Short public question. Fast Cheap clears the floor but not the 0.10 headroom, so Balanced wins."
        ),
        "prompt": EASY_CHAT,
        "policy": "default",
        "expect_task": "chat",
        "expect_model": "balanced",
        "expect_outcome": "success",
    },
    {
        "id": "easy-cost",
        "title": "Same question, cost-saver",
        "blurb": "Headroom is 0. Fast Cheap is eligible and cheapest.",
        "prompt": EASY_CHAT,
        "policy": "cost-saver",
        "expect_task": "chat",
        "expect_model": "fast-cheap",
        "expect_outcome": "success",
    },
    {
        "id": "easy-latency",
        "title": "Same question, latency-first",
        "blurb": "Catalog SLO is 100 ms. Only Fast Cheap fits, and it still clears the floor.",
        "prompt": EASY_CHAT,
        "policy": "latency-first",
        "expect_task": "chat",
        "expect_model": "fast-cheap",
        "expect_outcome": "success",
    },
    {
        "id": "easy-quality",
        "title": "Same question, quality-first",
        "blurb": "Highest capability among models that clear the floor. That is Premium.",
        "prompt": EASY_CHAT,
        "policy": "quality-first",
        "expect_task": "chat",
        "expect_model": "premium",
        "expect_outcome": "success",
    },
    {
        "id": "hard-math",
        "title": "Hard math",
        "blurb": "The floor rises past Balanced. Only Premium is eligible.",
        "prompt": HARD_MATH,
        "policy": "default",
        "expect_task": "math",
        "expect_model": "premium",
        "expect_outcome": "success",
    },
    {
        "id": "latency-reject",
        "title": "Hard math under a 100 ms SLO",
        "blurb": (
            "Premium can do the math and misses the SLO. "
            "Fast Cheap makes the SLO and misses the floor. Reject."
        ),
        "prompt": HARD_MATH,
        "policy": "latency-first",
        "expect_task": "math",
        "expect_model": None,
        "expect_outcome": "rejected",
    },
    {
        "id": "sensitive",
        "title": "Confidential note",
        "blurb": "The sensitivity rule pins local and forbids a hosted fallback.",
        "prompt": SENSITIVE,
        "policy": "default",
        "expect_task": "summarize",
        "expect_model": "local",
        "expect_outcome": "success",
    },
    {
        "id": "fallback-timeout",
        "title": "Fast Cheap times out",
        "blurb": "Cost-saver picks Fast Cheap, the mock times out, Balanced accepts the retry.",
        "prompt": EASY_CHAT,
        "policy": "cost-saver",
        "fault": {"model": "fast-cheap", "mode": "timeout"},
        "expect_task": "chat",
        "expect_model": "balanced",
        "expect_outcome": "fallback",
    },
    {
        "id": "quality-gate",
        "title": "Quality gate fails the cheap model",
        "blurb": "A low-quality completion is billed, then the router steps up to Balanced.",
        "prompt": EASY_CHAT,
        "policy": "cost-saver",
        "fault": {"model": "fast-cheap", "mode": "low_quality"},
        "expect_task": "chat",
        "expect_model": "balanced",
        "expect_outcome": "fallback",
    },
    {
        "id": "no-spill",
        "title": "Local failure does not spill",
        "blurb": "A confidential prompt stays on local even when that call errors.",
        "prompt": SENSITIVE,
        "policy": "default",
        "fault": {"model": "local", "mode": "error"},
        "expect_task": "summarize",
        "expect_model": None,
        "expect_outcome": "failed",
    },
]


def public_scenarios() -> list[dict[str, Any]]:
    """What the UI needs. Expectations stay on the server for the demo script."""
    hidden = {"expect_task", "expect_model", "expect_outcome"}
    return [{key: value for key, value in scenario.items() if key not in hidden} for scenario in SCENARIOS]
