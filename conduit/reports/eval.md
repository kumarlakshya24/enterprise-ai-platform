# Conduit eval

Seed `17`, embedder `fake-hash`. Latency is measured on this machine. Prices are list-price projections.

| Check | Result |
| --- | --- |
| Recall@1 on 20 planted keywords, before swap | 100% |
| Recall@1 after swap to emb-v2 | 100% |
| Update reuse (30 docs, 2 of 3 chunks unchanged) | 60 reused, 30 embedded |
| Migration embed calls / shadow chunks | 570 / 516 |
| Poison events quarantined / indexed | 3 / 0 |
| RTBF remaining subject links | 0 |
| Links after a full rebuild from the scrubbed log | 0 |
| Apply latency p50 / p95 / p99 | 0.3475 / 0.4222 / 0.5312 ms (n=221) |
| Measured $/M docs, text-embedding-3-small | 3.2024 |
| Measured $/M docs, text-embedding-3-large | 20.8157 |
| Short memo (2,000 tokens) $/M docs, small model | 40.0 |
| Ten-page policy (8,000 tokens) $/M docs, small model | 160.0 |
| Gates | PASS |

The measured per-document token count is `chars/4` on this synthetic corpus, which is a few short paragraphs. The memo and ten-page rows hold the token count fixed and apply the same list price. They are not a measurement of those documents.
