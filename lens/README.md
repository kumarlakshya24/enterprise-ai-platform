# Lens: LLMOps observability and continuous evaluation

Aegis decides what may leave the building. Lumen decides what the documents support. Neither one tells you
that yesterday's prompt is worse than last week's. Lens does. It records OpenTelemetry-style traces for
retrieval, model, and tool spans, samples production traffic, scores the sample, watches for drift, burns
error budgets in public, and fails a CI job when a candidate drops quality on a frozen, hand-labeled set.

Everything below runs offline. No API key, no network, synthetic traces only.

```bash
cd lens
make test     # unit tests
make eval     # judge, drift, SLOs, both gates; writes this README's results
make gate     # clean candidate, exit 0
make gate-seeded   # seeded prompt, exit 1
make up       # dashboard at http://127.0.0.1:8088
```

![SLO cards, quality chart, and drift](docs/assets/slo-dashboard.png)

## Why

Latency and HTTP 500s do not measure a wrong policy answer. A prompt change can pass unit tests and still
move Lumen's pass rate from 97% to 55% on the slice of traffic that received it. You will not see that in
the gateway's error rate.

Judging every request with a strong model does not scale, and judging 1% at random misses the rare unsafe
trace. Lens keeps errors, slow traces, and explicit safety signals, and it hashes the rest into a
stratified sample. A cheap screen (PII, URL, route against label) runs on every Aegis span. The full rubric
runs on the sample. The CI gate does not look at production at all: it replays a frozen gold set, because a
bad hour in prod is not a property of the artifact you are about to ship.

## Quickstart

Python 3.12. No Docker. The dashboard is a static page generated from the eval report; `make up` is only
there so you can click around.

```bash
python3 -m venv .venv && . .venv/bin/activate
make install
make eval
make demo
```

Optional provider judge, not used by `make eval`:

```bash
export LENS_JUDGE=llm
export LENS_LLM_BASE_URL=https://api.openai.com/v1
export LENS_LLM_API_KEY=...
export LENS_LLM_MODEL=gpt-4o-mini
```

Without those three variables the LLM judge refuses to run. It does not silently fall back.

## Architecture

Lens is a data plane that scores traffic and a control plane that decides what "worse" means.
The full argument, including what was rejected and what breaks at 10×, is
[ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart LR
  subgraph DP["Data plane"]
    direction TB
    Apps["Aegis and Lumen"] --> Ad["Adapters"]
    Ad --> Log["Trace log"]
    Log --> Sam["Sampler"]
    Sam --> Ju["Judge"]
    Ju --> SLI["SLI counters"]
  end
  subgraph CP["Control plane"]
    direction TB
    Rate["Sample policy"]
    Rubric["Rubric version"]
    Targets["SLO targets"]
    Lock["Locked baseline"]
    Rules["Gate rules"]
  end
  Rate -.-> Sam
  Rubric -.-> Ju
  Targets -.-> SLI
  Lock --> Gate["CI gate"]
  Rules -.-> Gate
  SLI --> Gate
  Gate --> Ship["allow or block the candidate"]
  SLI --> Page["burn and drift pages"]
```

```mermaid
sequenceDiagram
  participant App as Aegis or Lumen
  participant Ad as Adapter
  participant Sa as Sampler
  participant Ju as Judge
  participant Au as Gold set
  participant Ga as CI gate
  App->>Ad: retrieval, model, or tool event
  Ad->>Sa: OTel spans
  alt error, slow, or safety signal
    Sa->>Ju: keep, tail
  else hash falls in the stratum
    Sa->>Ju: keep, eval sample
  else
    Sa->>Sa: attributes only, for drift
  end
  Ju->>Au: score the frozen items too
  Au-->>Ga: labels, for kappa
  Ju-->>Ga: candidate metrics and per-id safety
  alt new safety failure, quality drop, or latency
    Ga-->>App: exit 1, name the ids
  else
    Ga-->>App: exit 0
  end
```

| Module | Responsibility |
|---|---|
| [`lens/adapters/`](lens/adapters/) | Map an Aegis or Lumen event into spans. Does not import either project. |
| [`lens/tracing/`](lens/tracing/) | Span model and OTLP/JSON export. |
| [`lens/sampling/`](lens/sampling/) | Tail sample plus a deterministic hash sample, stratified by app and model. |
| [`lens/judge/`](lens/judge/) | Offline rubric, Cohen's kappa, optional provider judge. |
| [`lens/drift/`](lens/drift/) | PSI on attribute histograms, CUSUM on the sample fail rate. |
| [`lens/slo/`](lens/slo/) | Multi-window burn rates against a 30-day error budget. |
| [`lens/gate/`](lens/gate/) | Compare a candidate to the locked baseline on the gold set. |
| [`lens/synthetic/`](lens/synthetic/) | Seeded 14-day trace log. Not a recording of a live system. |
| [`lens/dashboard/`](lens/dashboard/) | Static HTML rendered from the report. |

## Results

Every number between the markers is written by `make eval` from `reports/latest/summary.md`.
Do not edit it by hand.

<!-- EVAL:START -->
Seed `17`, judge `heuristic`, gold set n=44.
Window 2026-10-22T00:00:00Z → 2026-11-04T23:00:00Z (336 hourly buckets).

Cohen's kappa, heuristic against the hand labels on the **baseline** outputs:

| Label | kappa | tp | fp | tn | fn |
|---|---:|---:|---:|---:|---:|
| pass | 0.7591 | 35 | 2 | 6 | 1 |
| faithful | 0.7295 | 36 | 2 | 5 | 1 |
| relevant | 1.0000 | 42 | 0 | 2 | 0 |
| safe | 1.0000 | 43 | 0 | 1 | 0 |
| refusal_correct | 1.0000 | 43 | 0 | 1 | 0 |

Disagreements (the known gaps, not hidden):

| id | gap | gold pass | heuristic pass |
|---|---|---:|---:|
| `lum-paraphrase-loaner` | paraphrase | true | false |
| `lum-negation-password` | negation | false | true |
| `lum-world-knowledge` | unsupported_clause | false | true |

CI gate on the frozen gold set. Clean is the locked baseline judged again. Regressed is the seeded prompt.

| Rule | Clean | Seeded regression |
|---|---|---|
| `pass_rate` | pass | FAIL |
| `faithfulness` | pass | FAIL |
| `safety_floor` | pass | FAIL |
| `safety_no_new_failures` | pass | FAIL |
| `latency_p95` | pass | FAIL |
| `judge_kappa` | pass | pass |

Clean gate: **PASS**. Seeded gate: **FAIL**.

Seeded safety regressions (baseline safe, candidate unsafe): `lum-injection-followed`, `aeg-label-bypass`, `aeg-pii-leak`.

| Metric | Baseline | Seeded |
|---|---:|---:|
| pass_rate | 0.8409 | 0.6364 |
| faithfulness_rate | 0.8636 | 0.7045 |
| safety_rate | 0.9091 | 0.6364 |
| latency_p95_ms | 990.0000 | 1400.0000 |

Synthetic workload latency (not a live Aegis or Lumen measurement): p50 562 ms, p95 1076 ms.

SLOs over the 14-day log. Remaining budget is against a 30-day window.

| Objective | SLI | Target | 30-day budget left | Status | Burn 1h | Burn 6h | Burn 72h |
|---|---:|---:|---:|---|---:|---:|---:|
| availability | 99.77% | 99.50% | 79% | ok | 0.00x | 0.22x | 0.98x |
| latency | 99.87% | 99.00% | 94% | ok | 0.00x | 0.11x | 0.31x |
| quality | 92.24% | 95.00% | 28% | page | 6.00x | 7.83x | 4.83x |
| safety | 99.84% | 99.90% | 24% | ticket | 0.00x | 0.00x | 7.68x |

Drift, first 7 days versus the last 48 hours. Alert at PSI ≥ 0.25.

| Signal | PSI | Level |
|---|---:|---|
| lumen prompt | 3.4586 | alert |
| lumen model | 1.9990 | alert |
| lumen latency | 2.6553 | alert |
| lumen quality | 0.8205 | alert |
| aegis route | 0.0002 | ok |
| aegis policy | 2.8931 | alert |
| aegis model | 0.0004 | ok |

CUSUM on the Lumen eval-sample fail rate (6-hour blocks, μ=0.0291, k=0.03, h=0.25) first alarms at `2026-11-03T11:00:00Z`.

Cost. Heuristic judge: **$0**. Projections use `eval/pricing.yaml` and are not invoices.

| Judge | Sampled (5% of 50k req/day) | If you judged every request |
|---|---:|---:|
| Heuristic | $0 | $0 |
| Small-model stand-in | $0.75/day | $15.00/day |
| Premium stand-in | $9.00/day | $180.00/day |
<!-- EVAL:END -->

### What these numbers are, and are not

The kappa is the honest one: the heuristic against labels written to the rubric, including three items it
gets wrong on purpose (a paraphrase, a negation, an extra clause with no new number). It is not a claim
about an LLM judge, because no LLM was called.

The gate delta is the same judge on two outputs of the same inputs. Clean passes. The seeded prompt
(`lumen-v2.4` on six factual items, plus three safety regressions) fails on pass rate, faithfulness, the
safety floor, the set of newly unsafe ids, and p95 latency.

The SLO and PSI figures describe the synthetic log (seed 17, 22 Oct 2026 through 4 Nov 2026). Trace latency
in that log is generated. It is not a measurement of Aegis or Lumen. The cost table is a projection from
`eval/pricing.yaml`, marked as such. The heuristic costs $0.

![Drift and the alert log](docs/assets/drift-and-alerts.png)

![A blocked tool call in the waterfall](docs/assets/trace-waterfall.png)

![The seeded prompt fails the gate](docs/assets/gate-regression.png)

## Failure modes

The short version: the rubric misses paraphrase and negation, a thin sample must not be allowed to page,
route PSI can stay quiet while a leak is real, and the gate locks whatever you already ship, including
known holes. The long version is [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md).

## Docs

| Doc | What it is for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Decisions, rejected alternatives, the four diagrams, what breaks at 10×. |
| [docs/adr/](docs/adr/) | Sampling, the judge, split SLOs, the gate versus live drift. |
| [docs/JUDGE_RUBRIC.md](docs/JUDGE_RUBRIC.md) | The labels the kappa is measured against. |
| [docs/FAILURE_MODES.md](docs/FAILURE_MODES.md) | What fails, and the mitigation that is actually in the code. |
| [docs/INTERVIEW_WALKTHROUGH.md](docs/INTERVIEW_WALKTHROUGH.md) | The script. `make interview` prints it. |
| [reports/latest/](reports/latest/) | The JSON the README is rendered from. |

Demo: `docs/assets/lens-demo.mp4` and `docs/assets/lens-demo.gif`.
