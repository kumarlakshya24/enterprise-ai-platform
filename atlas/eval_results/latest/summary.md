Suite `atlas-workflows-v1` on Python 3.12.3. Deterministic regression suite. The mock LLM is a pure function. This is not an estimate of production task success with a sampled model. Recovery milliseconds are simulated from each activity's declared latency_ms. A healed step costs 1 ms of bookkeeping. Actual model spend is $0.

| Metric | Atlas | Single-agent baseline |
|---|---:|---:|
| Task success | 16/16 (100.0%) | 3/16 (18.8%) |
| Mean steps | 3.69 | 6.5 |
| Mean accounted cost (USD) | $0.00750 | $0.01225 |
| Mean completed steps re-run after a crash | 0 | 3.25 |
| Mean in-flight steps re-executed after a crash | 0.25 | 0.25 |
| Mean recovery time after a crash (simulated ms) | 65.75 | 166.25 |
| Mean catch-up time (simulated ms) | 12 | 103.75 |

Recovery time is simulated milliseconds from resume until the run is terminal again. Catch-up time stops when the crashed step is resolved. Engine overhead on 40 small refunds: p50 17.329 ms, p95 28.265 ms (measured wall clock, mock agents).

| Case | Atlas | Baseline | Atlas steps re-run (completed / in-flight) | Baseline steps re-run | Atlas recovery ms | Baseline recovery ms |
|---|---|---|---:|---:|---:|---:|
| refund_happy | pass | pass | — | — | — | — |
| refund_small | pass | pass | — | — | — | — |
| refund_crash_after_remote | pass | fail | 0 / 0 | 4 / 0 | 56 | 170 |
| refund_crash_after_intent | pass | pass | 0 / 1 | 3 / 1 | 100 | 170 |
| refund_denied | pass | fail | — | — | — | — |
| refund_step_budget | pass | fail | — | — | — | — |
| refund_cost_budget | pass | fail | — | — | — | — |
| refund_email_compensate | pass | fail | — | — | — | — |
| refund_email_retry | pass | fail | — | — | — | — |
| refund_ledger_timeout | pass | fail | — | — | — | — |
| compensate_crash | pass | fail | 0 / 0 | 4 / 0 | 1 | 150 |
| vendor_guard | pass | fail | — | — | — | — |
| incident_crash | pass | fail | 0 / 0 | 2 / 0 | 106 | 175 |
| duplicate_submit | pass | fail | — | — | — | — |
| lumen_refusal | pass | fail | — | — | — | — |
| sms_not_idempotent | pass | fail | — | — | — | — |
