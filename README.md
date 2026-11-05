# personal-projects
My favorite personal projects that I build in my spare time after work

## Projects

| Project | What it is |
|---------|------------|
| [secure-ai-gateway](secure-ai-gateway/) | **Aegis**: a secure gateway between employees, company agents, and third-party LLMs. DLP tokenization, private classifier routing, agent tool guardrails, prompt-injection defense, and a tamper-evident audit log, with a red-team suite, a regression gate, and a latency benchmark. Runs offline with one command. |
| [rag-knowledge-assistant](rag-knowledge-assistant/) | **Lumen**: production-style RAG for an internal employee knowledge base. Hybrid search, cross-encoder re-ranking, RBAC, PII redaction, prompt-injection guard, semantic cache, incremental indexing, and a saved evaluation suite, plus a walkthrough video. |
| [atlas](atlas/) | **Atlas**: durable execution for multi-agent workflows. A planner and specialists, SQLite checkpoints with event-sourced replay, idempotent tools, approval gates, budgets, and saga compensation. Kill a worker after a ledger debit and resume without a second debit. Calls Aegis for tool guardrails and Lumen for policy lookup. Offline, with a regression suite against a single-agent baseline. |
