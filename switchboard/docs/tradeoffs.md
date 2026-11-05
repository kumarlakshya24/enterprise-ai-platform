# Tradeoffs

The short version is the table in `ARCHITECTURE.md`. This file is the longer one.

## Headroom sends some easy work to Premium

Under `default`, a three-line "refactor for production" goes to Premium. Balanced's code
capability is 0.76 and the floor on that prompt is about 0.68, so the gap is 0.08, under the
0.10 headroom. Cost-saver sets headroom to 0 and picks Balanced for the same prompt.

That is intentional and it costs money. On the eval corpus the default policy still saves
61.74% against always-premium, because the easy chat and summarize rows stay off Premium.
The code and easy-math rows do not. If a team hates that, they lower `min_headroom` or they
use cost-saver. They should not "fix" it by deleting the reason from the trace.

## The oracle agrees with default, and that is not a trophy

The cost-optimal oracle uses the same eligibility code and then picks the cheapest survivor.
After headroom, the cheapest survivor on `default` is also the weighted winner on this corpus,
so agreement is 100%. The number that shows the selection mode doing work is quality-first:
50% agreement, two cases where the router pays for Premium and the oracle would have bought
Fast Cheap or Balanced.

A task-map heuristic (sensitive to local, real-time or latency-first to Fast Cheap, quality-first
to Premium, code/math/extract to Balanced or Premium) scores 89.3% against the gold labels.
The router is ahead on headroom, the tightened budget, and hard math under cost-saver. It is
not ahead because the gold labels were copied from a neural model.

## Savings depend on which slice you quote

| Slice | Savings vs always-premium | Do not say |
|-------|---------------------------|------------|
| Answered non-fault cases | 64.98% | |
| Default policy, 16 cases | 61.74% | |
| All non-fault, including 3 rejects | 69.02% | The rejects add fake savings |
| Latency-first, 6 cases | 99.34% | Three of those are refusals at $0 |

Prices are the catalog's showback rates. They are not an invoice from a vendor.

## Local is weaker on purpose

Local chat capability is 0.66, code 0.64, math 0.52. If it competed as a peer at its showback
price it would steal easy traffic from Fast Cheap and then lose on quality. Keeping it out of
the peer set means the sensitive pin is the only way it wins a normal request. The escape hatch
is the exception, and it sets `degraded`.

## The classifier will mis-label some real prompts

Leading verb wins, then a keyword scan, then `chat`. "Summarize this traceback" stays a summary
because of the lead verb. A paragraph that only implies code, with no fence and no keyword, becomes
chat and can land on Fast Cheap. That is the trade for a 0.079 ms p95 and a trace that names the
signal. An LLM judge would catch more of those and would also need a model, a timeout, and a bill
on the routing path. ADR 0002.

## Estimated latency is not a tail

Premium's base is 680 ms. The bench p95 of 0.079 ms is the router. Adding them and calling the sum
"p95 end to end" would be wrong: one number is a formula, the other is a measurement of a different
thing. The UI prints them on separate lines.
