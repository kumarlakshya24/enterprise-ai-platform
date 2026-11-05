# Experiment: fp32 vs int8 cross-encoder

Same container, same 46 questions, `rerank` and `full` profiles.

* **fp32** (`models/ms-marco-MiniLM-L-6-v2`): [`fp32-summary.md`](fp32-summary.md)
* **int8** (dynamic quantization, the default): the canonical run in [`../../latest/summary.md`](../../latest/summary.md)

Result: identical end-to-end correctness in `full`, and p95 latency drops from 939 ms (fp32) to 544 ms (int8),
so int8 is the default. Reproduce with:

```bash
RERANKER_MODEL_DIR=models/ms-marco-MiniLM-L-6-v2 python -m app.evaluation.runner --profiles rerank full --no-cache --tag fp32-reranker
```
