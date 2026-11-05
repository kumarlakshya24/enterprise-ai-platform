# ADR 0002: Deterministic features, not a judge model, on the hot path

* Status: accepted
* Date: 2026-11-05

## Context

Task type drives the capability floor. I can get it from keywords or from another model call
before the real call. A judge model generalizes past my lists. It also adds a timeout, a failure
mode, and a bill to every request, including the ones that were only ever going to be Fast Cheap.

## Decision

Classify with a leading verb, a short keyword scan, a complexity function, and a sensitivity
floor. Every feature shows up in the trace as a signal name. No network, no weights file.

## Consequences

Good: the bench p95 for the whole route is 0.079 ms, measured, n=400, and a wrong task is
visible in the signal list.

Bad: a prompt that only implies code, with no fence and no keyword, is chat. The eval corpus
locks the phrases I do handle. It does not measure the phrases I have not written down.
A judge model is the right follow-up for a low-confidence band, not for every request.
