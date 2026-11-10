# ADR 0003: Split measured overhead from projected cost and latency

* Status: accepted
* Date: 2026-11-10

## Context

The arms do not call a model. Sleeping the catalog latency would make the suite slow and would pretend a mock waited 216 ms. Adding the measured overhead (tens of microseconds) into the catalog millisecond figure would also be a lie: the SLO would move when the laptop is busy, and CI would disagree with the committed report.

The dollars have the same shape. Token prices and a training program are a price card. They are not an invoice. The interesting comparison is which term dominates: inference at two million requests, or the program cost at two thousand.

## Decision

Three columns, never added together.

* Task success, citations, and stale answers are computed from the labeled set and saved in `reports/latest.json`.
* Model latency and dollars come from `price_card.yaml` and are labeled `projection`. The SLO and the budget read these figures only.
* Pipeline overhead is `time.perf_counter` around the in-process arm, model time not slept. `make gate` does not compare it. The README quotes the committed run and says to re-run `make eval` for a local number.

The program cost is a fixed $2,400 for the adapter and $900 for the student, amortized over six months. A formula that only billed one GPU-hour of a 16k-token toy run made every volume look cheap, which hid the decision.

## Consequences

Good: the winner does not flicker with the clock. A reader can see that RAG's 216 ms is a catalog base plus a context term, and that the router's own p95 on this box was 0.070 ms.

Bad: the price card can be wrong about a real provider and the recommendation moves. That is a one-file change, and the memo prints the assumptions. It is not a measured bill.
