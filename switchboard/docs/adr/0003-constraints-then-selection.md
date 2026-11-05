# ADR 0003: Hard constraints, then an explicit selection mode

* Status: accepted
* Date: 2026-11-05

## Context

A single weighted score of capability, cost, and latency looks flexible and is unstable. On an
easy chat the four catalog costs sit so close together, relative to a loose budget, that a 0.01
weight change flips the winner. I want the demo to show four policies on one prompt and I want
the winner to survive a one-token edit.

## Decision

Remove illegal models first: capability floor, headroom when a safer model exists, budget, SLO,
peer flag, pin, excludes. Then rank with a named mode: `weighted`, `cheapest`, `fastest`, or
`highest_capability`. Still compute the weighted score so the trace can show it.

Headroom relaxes when it would empty the set. A tight budget can therefore fall through to
Fast Cheap instead of rejecting.

## Consequences

Good: default, cost-saver, latency-first, and quality-first disagree for reasons you can point at.
Quality-first agrees with the cheapest-legal oracle on only 50% of its four corpus cases.

Bad: default headroom sends some short code and easy math to Premium. That costs money. It is
recorded in `reports/eval.md` rather than tuned away.
