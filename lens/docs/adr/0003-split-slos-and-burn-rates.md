# ADR 0003: Four SLOs, multi-window burn, no blended score

* Status: accepted
* Date: 2026-11-05

## Context

A single "health" number hides the failure mode you have. In the synthetic log the latency histogram
shifts hard when `lumen-v2.4` rolls out (PSI about 2.7) while the latency SLO, "99% of requests under
1500 ms", stays green. A blended score would either page for a shift that is still inside the SLO, or
stay green through a quality drop, depending on the weights. Weights are how that argument gets lost.

Safety is worse. A 5% quality budget is a reasonable argument. A 5% safety budget would mean you have
agreed to leak for one request in twenty. The Aegis target is 99.9%, so the budget is 0.1%. An afternoon
at 8% unsafe burns that at roughly 100× for the hour it is happening.

## Decision

Four objectives, each with its own target, budget, and burn:

| Id | Target | SLI |
|---|---|---|
| availability | 99.5% | status ok, both apps |
| latency | 99% under 1500 ms | both apps |
| quality | 95% | Lumen rubric pass, eval sample only |
| safety | 99.9% | Aegis cheap screen, every request |

Burn rate is `error_rate / (1 - target)`, on 1h, 6h, 24h, and 72h windows, against a 30-day budget.
Remaining budget is `1 - burn * (elapsed / 30d)`, and it may go negative.

Paging rules, from the SRE workbook, reduced to the windows hourly data can support:

* Page when the 1h burn is at least 14.4, or the 6h burn is at least 6, and the window is full and has
  enough events (`burn_min_events` in `eval/slo.yaml`).
* Hold a page until the 6h burn falls under 4, so a noisy sample cannot open and close it every hour.
* Ticket when the 24h burn is at least 3, or the 72h burn is at least 1, with the same fullness rule.

The 5-minute confirmation window from the workbook is not implemented. Hourly counters cannot see it.

## Consequences

Good:

* The synthetic story separates cleanly. Quality stays on page after the ramp. Latency stays within
  budget while its PSI alerts. Availability pages for the blip hour and then recovers. Safety pages
  and then sits on a ticket because the 72h window still contains the bad afternoon.
* A dim burn chip means "not enough events", which is a decision, not a missing chart.

Bad:

* A one-hour blip pages even if, in a real system, it would have recovered inside the short window you
  cannot see. The failure-mode note says to add 5-minute counters before this is on call.
* Quality off-peak can fail the 1h minimum, so the fast page almost never fires for quality. That is
  intentional: quality pages on the 6h window. A real fast quality page would mean the rubric is failing
  most of a busy hour, which this ramp does not do.

Rejected:

* One composite score. The weights become the product, and nobody can say which objective broke.
* Paging on PSI alone. A new canary is a large PSI and may be fine. PSI is a page to go look. The gate
  is what blocks a deploy. See ADR 0004.
