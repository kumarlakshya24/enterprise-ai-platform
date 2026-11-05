# ADR 0005: Measure router overhead, estimate model latency

* Status: accepted
* Date: 2026-11-05

## Context

The catalog gives Premium a 680 ms base latency. Sleeping that in tests would make the suite
slow and would still not be a measurement of a GPU. Reporting it as "p95 latency" next to a
wall-clock number would mix two kinds of evidence.

## Decision

The mock returns immediately. `timing.simulated_latency_ms` is the catalog formula.
`timing.router_overhead_ms` is `perf_counter` around classify, score, the mock, and the SQLite
append. `make bench` writes `reports/latency.md` with both, labeled. The decision log stores a
redacted preview and a SHA-256 of the prompt, not the prompt, so the overhead bench is not also
a place where fixtures with emails get persisted in the clear.

## Consequences

Good: `make test`, `make demo`, and `make eval` finish in about a second. The README can say
which figure was measured.

Bad: a real provider's queueing, TLS, and token streaming are not in the 0.079 ms p95. The
attempt interface is where that client would go. Fault injection has to be turned off first,
or a test fault could fire against a live model.
