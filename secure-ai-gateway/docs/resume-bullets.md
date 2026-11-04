# Resume bullets

For an AI Solutions Architect role. Every number below is produced by this repository (see
`reports/`), and each one is a portfolio project result, not a production deployment. Pick 5 to 7.

* **Designed and built a secure AI agent gateway** (Python, FastAPI, Postgres, Redis, Docker
  Compose) that tokenizes PII and secrets before prompts reach third-party LLMs and restores them
  only for authorized users, with **5/5 end-to-end leak scenarios** blocked and verified against the
  provider's own request log.

* **Built a layered DLP engine**: checksum-validated regex detectors, spaCy NER with confidence
  heuristics, and Unicode/zero-width normalization. It neutralizes **47 of 50 labelled entities with
  zero false redactions** on an 84-case red-team suite at **97% case recall and 95.5% precision**.

* **Closed the pattern-only DLP gap** with a private TF-IDF + logistic-regression sensitivity
  classifier (JSON export, no pickle, hash-verified) that routes confidential context to a local
  model. It scored **94% recall on sensitive prompts** in a blind 100-row holdout, at
  **0.05 ms per prediction**.

* **Engineered deterministic agent tool guardrails**: vault-resolved recipient allowlists, decoded
  URL/base64/hex payload DLP, session taint after prompt-injection detection, and four-eyes
  approvals with expiry. They caught **15/15 exfiltration attempts with 0 false blocks** in the tool suite, including an
  injection that a deliberately gullible model obeyed.

* **Kept security overhead to 9 ms p95** in-process and **21 ms p95** with Postgres audit and Redis
  vault in the loop, against a 300 ms budget. Profiling found NER as the bottleneck, and running
  only the NER component made it **2.5× faster**.

* **Made policy changes regression-safe**: every rule edit replays the red-team corpus across all
  tenant and user overrides, in CI and in the admin API. The gateway refuses changes that weaken
  protection (for example, allowing card numbers produces **7 regressions and HTTP 409**).

* **Delivered legal-grade auditability**: an append-only, HMAC hash-chained audit log that withholds
  confidential content. Tamper detection is verified by tests, and an automated scan shows **no
  synthetic PII** in audit, approval, run, or application logs across all scenarios.

Short version (one line):
*Built an LLM security gateway (DLP tokenization, private classifier routing, agent tool guardrails,
hash-chained audit) with 97% red-team recall and 21 ms p95 added latency.*
