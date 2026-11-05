Run `20261104-010701-fp32-reranker`: 46 questions, embedder `onnx:all-MiniLM-L6-v2`, reranker `onnx:ms-marco-MiniLM-L-6-v2`, generator `extractive`.

| Metric | rerank | full |
|---|---|---|
| Doc recall@5 | 100.0% | 100.0% |
| Doc recall@10 | 100.0% | 100.0% |
| MRR | 0.954 | 0.958 |
| Evidence recall@5 (facts in top-5 chunks) | 100.0% | 100.0% |
| Evidence recall@10 | 100.0% | 100.0% |
| Answer correct (all questions) | 76.1% | 89.1% |
| Fact recall (answerable) | 87.5% | 90.3% |
| Faithfulness | 100.0% | 100.0% |
| Citation precision | 87.5% | 90.3% |
| Refusal correct (unanswerable) | 50.0% | 90.0% |
| False refusal rate | 0.0% | 0.0% |
| RBAC leak rate ↓ | 100.0% | 0.0% |
| Cross-team top-1 error ↓ | 25.0% | 0.0% |
| Injection followed ↓ | 100.0% | 0.0% |
| p50 latency (ms) | 876 | 796 |
| p95 latency (ms) | 1029 | 939 |
| LLM cost / query (actual) | $0.00000 | $0.00000 |
| Projected cost / query (claude-opus-5-5) | $0.00358 | $0.00444 |

**Re-ranker effect on the same candidate set** (fused order → cross-encoder order):

| Profile | recall@5 before | recall@5 after | MRR before | MRR after |
|---|---|---|---|---|
| rerank | 95.8% | 100.0% | 0.851 | 0.954 |
| full | 100.0% | 100.0% | 0.887 | 0.958 |

**Stage latency, `full` profile** (p50 / p95 ms):

| embed_query | retrieval | multiquery | fusion | rerank | generation | total |
|---|---|---|---|---|---|---|
| 4 / 9 | 3 / 5 | 32 / 39 | 0 / 0 | 609 / 742 | 136 / 218 | 796 / 939 |

**Correct by category**:

| Category | n | rerank | full |
|---|---|---|---|
| cross_team | 6 | 83.3% | 83.3% |
| exact_term | 8 | 87.5% | 87.5% |
| injection | 2 | 0.0% | 100.0% |
| paraphrase | 12 | 91.7% | 91.7% |
| rbac | 8 | 50.0% | 100.0% |
| table | 4 | 75.0% | 75.0% |
| unanswerable | 6 | 83.3% | 83.3% |
