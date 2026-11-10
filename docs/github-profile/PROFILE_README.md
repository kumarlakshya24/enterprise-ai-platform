# Profile README

Ready to paste into [`kumarlakshya24/kumarlakshya24`](https://github.com/kumarlakshya24/kumarlakshya24) as `README.md`. Paste from the heading below. Do not paste this preface.

The project links point at `kumarlakshya24/personal-projects`, which is **private** as of 10 Nov 2026. Visitors without access get a 404 until that repo is public, or until the six folders are published as their own repos (see [`PINNED_REPOS.md`](PINNED_REPOS.md)). The sentence in the README says that plainly so the profile does not pretend the links are public.

---

# Lakshya Kumar

I design and build applied AI systems: the gateway in front of the model, the retrieval behind the answer, the router that picks the model, the runtime that survives a crash, the sandbox around a tool call, and the eval loop that says when quality dropped.

## What I build

Six systems, one per hard part of putting LLMs in front of employees and agents. Each one runs offline, keeps its own architecture notes, and records what it measured. They live in one repository today: [personal-projects](https://github.com/kumarlakshya24/personal-projects). That repository is private, so the links below work for people who already have access.

| System | What it is | Where |
|---|---|---|
| **Aegis** | Security gateway. Placeholder tokenization, a private classifier, a deterministic tool guard, a tamper-evident audit log. | [secure-ai-gateway](https://github.com/kumarlakshya24/personal-projects/tree/main/secure-ai-gateway) |
| **Lumen** | Knowledge assistant. Cited answers, access control in the retrieval query, refusals, a semantic cache. | [rag-knowledge-assistant](https://github.com/kumarlakshya24/personal-projects/tree/main/rag-knowledge-assistant) |
| **Switchboard** | Model router. Versioned policy, hard constraints before selection, fallback that does not spill confidential prompts. | [switchboard](https://github.com/kumarlakshya24/personal-projects/tree/main/switchboard) |
| **Forge** | Sandbox for agent tool calls. Path and import denials before a process exists, then a short-lived restricted interpreter. | [forge](https://github.com/kumarlakshya24/personal-projects/tree/main/forge) |
| **Atlas** | Durable multi-agent workflows. Event log, idempotency keys, saga compensation, crash and resume. | [atlas](https://github.com/kumarlakshya24/personal-projects/tree/main/atlas) |
| **Lens** | LLMOps. Traces, a sampled judge, drift, error budgets, and a CI gate that blocks a bad prompt. | [lens](https://github.com/kumarlakshya24/personal-projects/tree/main/lens) |

Start with the repository [README](https://github.com/kumarlakshya24/personal-projects). Each project README has the problem, the architecture, the trade-offs, how to run it, and a demo.

## Stack

Python 3.12 · FastAPI · PostgreSQL and pgvector · Redis · SQLite · ONNX Runtime · spaCy · scikit-learn · OpenTelemetry-style traces · Docker Compose · GitHub Actions

Synthetic data only. No provider key is required to run the default path.
