# ADR 0004: Local is a pin and an escape hatch, not a peer

* Status: accepted
* Date: 2026-11-05

## Context

The on-prem model has a low showback price. If it competes in the normal score, it wins easy
chat on cost and then does a worse job than Fast Cheap or Balanced. Operators also need a hard
guarantee that confidential text does not leave the machine, including when the cheap hosted
model is down.

## Decision

`local` is `peer: false`. It is eligible when a rule pins it (confidential or restricted), and
the pin waives floor, budget, SLO, and the quality gate, and it sets `stop_fallback`. It is also
called after every hosted attempt has failed, only if the policy sets
`allow_local_on_total_failure`. That answer is marked `degraded` when local is under the floor
or the gate. Quality-first turns the escape off. Latency-first turns it off too, except for the
sensitive pin, which waives the SLO on purpose.

## Consequences

Good: an email alone does not pin. The word confidential does. A local error on a pinned prompt
does not call Premium.

Bad: the escape hatch will sometimes return a weak proof. The flag is the mitigation, not a
promise that local can do the math. Local's math capability in the catalog is 0.52.
