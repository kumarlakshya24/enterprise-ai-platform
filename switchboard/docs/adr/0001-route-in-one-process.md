# ADR 0001: Route in one process, not in each client

* Status: accepted
* Date: 2026-11-05

## Context

The model choice can live in every service's SDK, in a gateway, or in the notebook of whoever
is on call. Client-side routing drifts. Two services pin different "small" models, nobody records
the alternative, and a budget change means a pull request in each repo.

## Decision

Switchboard is a single process with one active policy and a per-request override that can only
tighten the ceiling. The demo UI, `make demo`, and the eval call the same pipeline.

## Consequences

Good: one version id (`default@2026.11.05`), one trace shape, one place to bench overhead.

Bad: traffic that never reaches the process is not routed. This project does not pretend to be
an egress proxy. Authentication is out of scope; Aegis already sits on that boundary.
