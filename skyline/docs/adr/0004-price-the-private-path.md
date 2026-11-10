# ADR 0004: Price the private path, and do not scan the retrieved context

* Status: accepted
* Date: 2026-11-10

## Context

A platform review that ends at "private subnets" has not told finance anything. Two mistakes follow.

1. One number, "$X per thousand requests", with the volume buried. Endpoint hours smeared over
   1,000 requests/day and over 100,000 requests/day are different products.
2. Treating the guardrail as free, or scanning every retrieved passage because the toggle was on.
   Guardrails are priced per text unit. The retrieved context is most of the tokens.

The other temptation is to claim the private endpoints "save the NAT charge". On this mix the
request is kilobytes. The NAT charge that matters is the hourly charge, and the endpoints cost more
of those hours than one NAT does.

## Decision

The unit is the 1,000-request mix in `eval/workload.yaml`. The console takes requests/day as a
parameter and smears fixed cost across it.

```
per_thousand = variable_per_thousand + fixed_per_day * 1000 / requests_per_day
```

Quantities (endpoint count, AZ count, CMKs, tasks, attachments, the guardrail) are counted from the
synth. Rates live only in `eval/pricing.yaml`. A new endpoint changes the bill without a second edit.
The test `test_quantities_match_the_template` locks the counts we currently expect: 18 interface
endpoints, 7 CMKs, 4 transit gateway attachments.

The naive column is a counterfactual, not a second stack: the same three services, one NAT, one CMK,
no transit gateway, no guardrail, Sonnet-class on every row except where the mix already names the
naive model. It is labeled that way in the pricing file.

The guardrail scans `user_chars` plus the output tokens. It does not scan `input_tokens`, which
include retrieved context. The report also computes the counterfactual where it does, so the avoided
line is visible. Lumen's access check is the control on the corpus. The guardrail is the control on
what the user typed and what the model said.

The prices are a frozen illustration of the public list's shape. The file says they are not a quote.
The eval does not pretend to have called the Price List API.

## Consequences

Good:

* At 1,000 requests/day Skyline is the more expensive unit. At 100,000 it is the cheaper one. The
  crossing is computed. A reviewer can see which line moved.
* The endpoint-versus-NAT crossing is far above any volume the console offers as a preset. The
  design in ADR 0003 is a security control with a known premium, not a FinOps win.
* Skipping the retrieved context is worth more than the routing savings it would erase. That is a
  reason, not a slogan, because both numbers are on the page.

Bad:

* The naive column can be argued with. A team that already routes well would not save the whole
  model delta. The mix is explicit so that argument has the rows in front of it.
* Smearing a monthly CMK charge across a day uses a 30-day month. It is a projection convention.
* KMS request cost assumes a 1% data-key cache miss. A cache that never hits would still be a small
  line next to tokens. A design that calls `GenerateDataKey` on the request path without a cache
  would not match this file, and the file would be wrong until someone changed the rate.
* Nothing here is an invoice. Replacing `eval/pricing.yaml` is a commit, which is what we want, and
  it is easy to forget before a budget meeting. The README limitations say so.

What breaks at 10× traffic: the fixed premium becomes noise and the guardrail text units become the
argument. What breaks at 10× context window: if someone "just scans the prompt", the guardrail line
passes the model line. The full-prompt counterfactual is there so that change has to delete a number
that is already on the page.
