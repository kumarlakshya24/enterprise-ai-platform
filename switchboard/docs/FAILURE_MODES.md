# Failure modes

What the router does when the happy path does not happen. Each row is implemented and covered
by `tests/unit/test_router.py`, `tests/integration/test_api.py`, or a case in `eval/corpus.yaml`.

| Failure | What Switchboard does | Why |
|---------|----------------------|-----|
| No model clears the floor and the SLO | `outcome: rejected`. No attempt is billed. The trace lists each reject reason | A 100 ms SLO plus a proof is a product decision, not a silent downgrade. Latency-first on hard math is the demo |
| Budget excludes the only model that clears the floor | If a weaker model cleared the floor but failed headroom, headroom relaxes and that model is used. The note says "Headroom relaxed" | Otherwise a tight budget would reject a request Fast Cheap can still answer. Case `budget-tight` |
| Budget excludes everyone, including the weak model | `rejected` | There is nothing legal to call |
| Request asks for a looser budget or SLO than the policy | The policy ceiling stands. The why-trace says the request number was ignored | Callers do not get to waive a team control |
| Chosen mock times out | The attempt is kept, input tokens are billed, the next eligible model in the fallback order is called. `outcome: fallback` if that call is accepted | Timeouts still cost input on most hosted APIs. The trace shows both attempts |
| Chosen mock returns an error | Same cascade as a timeout. Quality-first stops without a local escape | A flagship policy that wanted Premium should fail closed rather than quietly serve local |
| Quality below the policy gate | Treated as a failed attempt and billed as a full generation, because tokens came back. The next model is tried | Case `fallback-quality`. The gate is 0.50 on default, 0.45 on cost-saver, 0.55 on quality-first |
| All hosted attempts fail, escape allowed | Local is called even though it is not a peer. If it is under the floor or the gate, `degraded: true` and the answer is still returned | Default policy. The caller can see the flag. This is the wrong place to hide a weak answer |
| All hosted attempts fail, escape disabled | `failed`. Local is not called | Quality-first |
| Sensitive pin, local errors or times out | `failed`. No hosted model is added to the queue | The pin's `stop_fallback` is the control. Case `fallback-no-spill` |
| Sensitive pin, local quality is under the gate | The gate is waived, the answer is returned, `degraded` is true when capability is also under the floor | A confidential prompt that we refuse to send out still needs an answer if local produced one |
| Two pin rules disagree | The pin is cleared, both models are excluded, the request is rejected | A conflict is not a guess |
| Classifier misses the task | The request is routed as the task it detected, usually `chat` | This is the main accuracy risk. The corpus checks the lead-verb and keyword order. It will not catch a phrasing the lists do not contain |
| `latency_sensitivity: high` on a quality-first prompt | `R-REALTIME-HINT` tightens the SLO to 120 ms before selection. Premium becomes ineligible. Fast Cheap wins if it clears the floor | The rule beats the selection mode. Case `realtime-quality` |
| Dry-run | The chosen model is reported and not called. Nothing is added to `/v1/stats` | Operators can price a candidate policy without moving the dashboard |
| Candidate YAML is invalid | HTTP 422 with the `PolicyError` text. The active policy is unchanged | A dry-run must not half-apply |
| Unknown policy name | HTTP 404 | The active policy stays |
| Fault field set while fault injection is off | The fault is ignored and the why-trace says so | The default is on, because every backend in this repo is a mock. A later network client should turn it off |
| SQLite write fails | The exception propagates. The caller does not get a silent success | Same posture as an audit log: an unlogged route is worse than an error for this demo's stats |
| Decision log queried for the prompt | The row has a redacted preview and a SHA-256. Emails, test cards, and SSN-shaped numbers are masked | The log is not a second copy of the confidential note |
| Preview of a non-Luhn number | Left as digits. Only a Luhn-valid card becomes `[card]` | Avoids masking order ids and years |

## What is not a failure mode here

* A real provider's 429, regional outage, or streaming cutoff. The mock has three faults: `timeout`, `error`, `low_quality`.
* Prompt injection. This router does not try to detect it. Aegis does.
* Multi-tenant fairness, retries with jitter, or hedged requests. Fallback is a sequence, capped by `max_attempts`.
