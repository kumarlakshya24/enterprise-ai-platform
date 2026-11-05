# ADR 0001: Sample off the request path, tail plus stratified hash

* Status: accepted
* Date: 2026-11-05

## Context

Lens has to see retrieval, model, and tool spans from Aegis and Lumen, and it has to score quality on a
sample of that traffic. Two bad designs are common.

1. Judge inside the request, before the user gets a response.
2. Keep 1% of arrivals as they come in (head sampling) and judge those.

The first adds latency and a new way for the product to fail. The second is unbiased only when the thing
you care about is common. A safety failure at 0.1% is not common. A 1% head sample of it is almost nothing,
and the one you do catch arrives late.

## Decision

Export spans asynchronously. The user path does not call Lens.

On the way in:

* Keep the trace if status is not ok, if latency is at or over 1500 ms, or if a safety signal is set
  (Aegis block, approval, or the cheap screen).
* Otherwise keep it when `sha256(app | model | trace id)` falls under the stratum rate.
* Otherwise drop the body and keep the attributes, which are enough for drift.

The quality SLI counts only the hash sample. The tail is for debugging and for the safety screen, which
runs on every Aegis span because it is cheap.

The demo rate is 10%, because the synthetic day is small. The production recommendation in `eval/slo.yaml`
is 5%.

## Consequences

Good:

* Replay is deterministic. The same trace id makes the same decision.
* Each app and model is sampled at the configured rate, not at whatever share of traffic it happens to be.
* A judge outage does not take down chat.
* The cost model is linear in the sample rate, which is the knob you turn.

Bad:

* A leak that looks like a normal `allow`, and that the cheap screen misses, is visible only in the sample.
  The label-bypass case is caught by the screen (confidential label on an external route). A subtle
  faithfulness bug is not, and 5% of those is what you get.
* Attribute drift can move while the quality sample is still quiet, or the other way around. That is why
  both are on the dashboard.

Rejected:

* Head sampling. It throws away the tail you most wanted.
* Judging 100% with a strong model. The pricing file shows what that costs at 50k requests a day, and 10×
  that is the next conversation.
* In-process judging before the response. It couples the product's latency budget to the rubric.
