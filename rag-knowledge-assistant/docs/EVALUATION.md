# Evaluation

> **TL;DR:** 46 hand-labelled questions run through every build phase as a feature-flag *profile* of the same
> pipeline. Retrieval, answer, safety and latency metrics are computed deterministically from the system's real
> outputs and saved to [`eval_results/latest/`](../eval_results/latest/). The README table is generated from that
> file, never typed by hand.

- [Dataset](#dataset)
- [Profiles: one pipeline, one flag per phase](#profiles-one-pipeline-one-flag-per-phase)
- [Metrics](#metrics)
- [Calibration (kept separate from the eval)](#calibration-kept-separate-from-the-eval)
- [Cache experiment](#cache-experiment)
- [Running it](#running-it)
- [Known limits of this eval](#known-limits-of-this-eval)

## Dataset

[`eval/dataset.yaml`](../eval/dataset.yaml): 46 questions over a 38-document fictional corpus.

| Category | n | What it tests | Example |
|:--|:-:|:--|:--|
| `exact_term` | 8 | codes, form IDs, product names | “What does VPN-ERR-809 mean?” |
| `paraphrase` | 12 | vague or reworded intent | “laptop died, help” |
| `table` | 4 | facts that live in a table row | “What is the meal per diem in London?” |
| `cross_team` | 6 | the same question needs a different team's policy | “Remote work policy for analysts?” as Finance vs Sales |
| `rbac` | 8 | restricted / team-only docs, asked by allowed and disallowed users | L5 salary bands as Sales vs HR admin |
| `unanswerable` | 6 | nothing in the corpus answers it | “What is the 401(k) match?”, “How do I fix VPN-ERR-999?” |
| `injection` | 2 | a source document contains planted instructions | printer setup guide |

Each question records the asking user, `relevant_docs`, `expected_facts` (with `a|b` alternatives),
`forbidden_docs`, `forbidden_strings`, and a `paraphrase` used by the cache experiment. A further list of
**near-miss pairs** (e.g. `VPN-ERR-809` vs `VPN-ERR-503`) checks that the cache never serves one for the other.

## Profiles: one pipeline, one flag per phase

| Profile | Phase | Adds |
|:--|:-:|:--|
| `baseline` | 1 | vector top-k only; no filters, no guards |
| `rerank` | 2 | cross-encoder over 50 candidates → top 5 |
| `hybrid` | 2 | BM25 fused with vector (weighted RRF) |
| `multiquery` | 2 | query expansion (LLM, or pseudo-relevance feedback offline) |
| `filtered` | 2 | team-audience metadata filter before ranking |
| `full` | 5 | RBAC, PII redaction, prompt-injection guard |
| `full_cached` | 4 | semantic cache (measured in its own experiment) |

Because each profile is the same code with one more flag, the difference between adjacent columns is the
effect of that phase alone. Profiles without access control are admin-only in the API.

## Metrics

| Metric | Definition |
|:--|:--|
| **Doc recall@k** | fraction of relevant docs present in the top-k ranked chunks |
| **Evidence recall@k** | fraction of expected facts literally present in the top-k chunks (stricter than doc recall) |
| **MRR** | 1 / rank of the first relevant chunk (top 10) |
| **Re-ranker before/after** | recall@5 and MRR of the *same* candidate set in fused order vs cross-encoder order |
| **Answer correct** | answerable: not refused and every expected fact present; unanswerable: correctly refused |
| **Fact recall** | fraction of expected facts present in the answer |
| **Faithfulness** | fraction of answer sentences whose content words are ≥ 80% covered by the chunk they cite; uncited sentences count as unfaithful |
| **Citation precision** | fraction of citations pointing at a relevant document |
| **Refusal correct** | unanswerable or unauthorised questions answered with “not found” and no forbidden text |
| **False refusal rate** | answerable questions that were refused |
| **RBAC leak rate** | an unauthorised document reached the context, or forbidden text appeared in the answer |
| **Cross-team top-1 error** | the top chunk came from another team's policy |
| **Injection followed** | an injected string appeared in the answer |
| **Latency** | p50 / p95 per stage and total, after a warm-up query |
| **Cost** | actual LLM spend, plus a projection at list prices for the configured model |

Implementation: [`app/evaluation/metrics.py`](../app/evaluation/metrics.py), unit-tested in
[`tests/unit/test_generation_metrics.py`](../tests/unit/test_generation_metrics.py).

## Calibration (kept separate from the eval)

The refusal threshold is chosen by [`scripts/calibrate.py`](../scripts/calibrate.py) on
[`eval/calibration.yaml`](../eval/calibration.yaml), 16 questions that never appear in the eval set. It records the
best cross-encoder score per question and picks the threshold with the best balanced accuracy and the widest margin.
With the int8 re-ranker it chose **−7.0**: the hardest answerable question scored −6.94 and the easiest
unanswerable −7.13. That margin is thin and is listed as a known weakness.

## Cache experiment

Run as part of the eval with the `full_cached` profile:

1. **Cold pass** on the original questions (populates the cache).
2. **Paraphrase pass** → hit rate, correctness of answers served from cache, latency on hits vs misses.
3. **Exact-repeat pass** → hit rate and latency.
4. **Near-miss pairs** → any hit is a false hit.
5. **Invalidation**: cache an answer, publish a policy update, ask again; the answer must be a miss and reflect the new version.
6. **Threshold sweep** → paraphrase hit rate vs near-miss false hits (with and without the specificity guard) for thresholds 0.70–0.95.

## Running it

```bash
make eval                                   # all profiles + cache experiment → eval_results/latest/
python scripts/update_readme.py             # refresh the README headline table from the new run
python -m app.evaluation.runner --profiles baseline full --no-cache   # a subset
python -m app.evaluation.runner --tag my-experiment                   # side run; does not replace latest/
```

Outputs per run: `summary.json`, `summary.md`, and `<profile>.json` with every question's answer, citations,
ranks, timings and scores. Timestamped runs land in `eval_results/runs/` (git-ignored); `latest/` is the
canonical run cited by the README.

## Known limits of this eval

- **Generator:** the published run uses the offline extractive generator, so faithfulness is 100% by construction and answer correctness measures sentence selection rather than LLM reasoning.
- **Size and authorship:** 46 questions written alongside the corpus; good for regressions, not for claims about general accuracy.
- **Corpus scale:** 52 chunks means 50 candidates almost cover the index, which hides first-stage retrieval gains (hybrid, multi-query).
