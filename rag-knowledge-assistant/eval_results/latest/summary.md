Run `20261104-010419`: 46 questions, embedder `onnx:all-MiniLM-L6-v2`, reranker `onnx:ms-marco-MiniLM-L-6-v2-int8`, generator `extractive`.

| Metric | baseline | rerank | hybrid | multiquery | filtered | full |
|---|---|---|---|---|---|---|
| Doc recall@5 | 95.8% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Doc recall@10 | 95.8% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| MRR | 0.851 | 0.954 | 0.954 | 0.954 | 0.958 | 0.958 |
| Evidence recall@5 (facts in top-5 chunks) | 94.3% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Evidence recall@10 | 97.1% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Answer correct (all questions) | 63.0% | 73.9% | 73.9% | 73.9% | 80.4% | 89.1% |
| Fact recall (answerable) | 75.0% | 84.7% | 84.7% | 84.7% | 87.5% | 90.3% |
| Faithfulness | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| Citation precision | 89.1% | 87.5% | 87.5% | 87.5% | 91.7% | 91.7% |
| Refusal correct (unanswerable) | 30.0% | 50.0% | 50.0% | 50.0% | 70.0% | 90.0% |
| False refusal rate | 11.1% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| RBAC leak rate ↓ | 100.0% | 100.0% | 100.0% | 100.0% | 50.0% | 0.0% |
| Cross-team top-1 error ↓ | 25.0% | 25.0% | 25.0% | 25.0% | 0.0% | 0.0% |
| Injection followed ↓ | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% |
| p50 latency (ms) | 101 | 488 | 473 | 512 | 478 | 445 |
| p95 latency (ms) | 121 | 545 | 550 | 620 | 592 | 544 |
| LLM cost / query (actual) | $0.00000 | $0.00000 | $0.00000 | $0.00000 | $0.00000 | $0.00000 |
| Projected cost / query (claude-opus-5-5) | $0.00338 | $0.00360 | $0.00361 | $0.00481 | $0.00460 | $0.00443 |

**Re-ranker effect on the same candidate set** (fused order → cross-encoder order):

| Profile | recall@5 before | recall@5 after | MRR before | MRR after |
|---|---|---|---|---|
| baseline | 95.8% | 95.8% | 0.851 | 0.851 |
| rerank | 95.8% | 100.0% | 0.851 | 0.954 |
| hybrid | 97.2% | 100.0% | 0.888 | 0.954 |
| multiquery | 100.0% | 100.0% | 0.874 | 0.954 |
| filtered | 100.0% | 100.0% | 0.887 | 0.958 |
| full | 100.0% | 100.0% | 0.887 | 0.958 |

**Stage latency, `full` profile** (p50 / p95 ms):

| embed_query | retrieval | multiquery | fusion | rerank | generation | total |
|---|---|---|---|---|---|---|
| 5 / 9 | 3 / 5 | 33 / 42 | 0 / 0 | 331 / 418 | 72 / 113 | 445 / 544 |

**Semantic cache** (`full_cached`, threshold 0.85):

| Pass | Hit rate | Correct | p50 ms | p95 ms | p50 on hits | p50 on misses |
|---|---|---|---|---|---|---|
| Cold (empty cache) | 0.0% | 89.1% | 436 | 547 | – | 435.7 |
| Paraphrased questions | 23.9% | 91.3% | 415 | 504 | 5.2 | 448.2 |
| Exact repeats | 100.0% | 89.1% | 3 | 6 | 2.7 | – |

- Near-miss false hits: 0/6
- Wrong answers served from cache on paraphrases: 0
- Invalidation on document update: warm hit before = True, hit after update = False, answer reflects v4.0 = True (2 chunk replaced, 4 reused, 2 embeddings computed)

**Cache threshold sweep** (cosine on all-MiniLM-L6-v2; guard = numbers/codes must match):

| Threshold | Paraphrase hit rate | Near-miss false hits (with guard) | Near-miss false hits (no guard) |
|---|---|---|---|
| 0.70 | 69.6% | 16.7% | 83.3% |
| 0.75 | 54.3% | 16.7% | 83.3% |
| 0.80 | 43.5% | 0.0% | 50.0% |
| 0.85 | 23.9% | 0.0% | 50.0% |
| 0.88 | 19.6% | 0.0% | 33.3% |
| 0.90 | 13.0% | 0.0% | 33.3% |
| 0.92 | 0.0% | 0.0% | 33.3% |
| 0.95 | 0.0% | 0.0% | 16.7% |

**Correct by category**:

| Category | n | baseline | rerank | hybrid | multiquery | filtered | full |
|---|---|---|---|---|---|---|---|
| cross_team | 6 | 83.3% | 66.7% | 66.7% | 66.7% | 83.3% | 83.3% |
| exact_term | 8 | 75.0% | 87.5% | 87.5% | 87.5% | 87.5% | 87.5% |
| injection | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% |
| paraphrase | 12 | 75.0% | 91.7% | 91.7% | 91.7% | 91.7% | 91.7% |
| rbac | 8 | 50.0% | 50.0% | 50.0% | 50.0% | 75.0% | 100.0% |
| table | 4 | 75.0% | 75.0% | 75.0% | 75.0% | 75.0% | 75.0% |
| unanswerable | 6 | 33.3% | 83.3% | 83.3% | 83.3% | 83.3% | 83.3% |
