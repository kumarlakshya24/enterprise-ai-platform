[Aegis](../README.md) › **Docs**

# Documentation

Every document starts with a short summary. Pick a path based on what you need.

| If you have… | Read |
|---|---|
| **5 minutes** | The [README](../README.md) and the [3-minute walkthrough video](media/aegis-walkthrough.mp4) |
| **15 minutes, reviewing the design** | [Architecture](../ARCHITECTURE.md), then the [decision records](adr/README.md) |
| **15 minutes, reviewing security** | [Threat model](threat-model.md), then the [security checklist](security-checklist.md) |
| **A laptop and Docker** | [Demo guide](demo-guide.md) (`make up`, then click through five scenarios) |
| **Questions about production** | [Tradeoffs and limitations](tradeoffs-and-limitations.md), [cost and scaling](cost-and-scaling.md) |

## All documents

| Document | What it answers |
|---|---|
| [Architecture](../ARCHITECTURE.md) | What are the components, how does a request flow, where are the trust boundaries, what happens when something fails? |
| [Decision records](adr/README.md) | Why a gateway, why tokenization, why a private classifier, why a deterministic tool guard, why a hash-chained audit log? |
| [Threat model](threat-model.md) | Who attacks this, how, and which code and test stop each attack? |
| [Security checklist](security-checklist.md) | Which controls exist, what proves each one, and what production still needs? |
| [Demo guide](demo-guide.md) | What should I click, and what should I see? |
| [Tradeoffs and limitations](tradeoffs-and-limitations.md) | What does this not solve, where is it measurably weak, and what comes next? |
| [Cost and scaling](cost-and-scaling.md) | What does it cost per 1,000 requests, how far does one replica go, and what breaks first? |
| [Deploy](deploy.md) | How do I host the single-container demo? |

## Generated reports

These are written by the code (`make redteam`, `make regression`, `make benchmark`, `make train`).
Don't edit them by hand.

| Report | Headline |
|---|---|
| [Red team](../reports/redteam.md) | 84 cases, recall 97.0%, precision 95.5%, every miss explained |
| [Regression gate](../reports/regression.md) | 64 protected cases, 0 protection regressions |
| [Latency](../reports/latency.md) | p95 overhead of 9.2 ms in-process and 21.2 ms in the Docker stack |
| [Classifier](../reports/classifier.md) | Blind holdout: 86% accuracy, 94% recall on sensitive context |

## Media

GIFs and the walkthrough video live in [`media/`](media/). They are cut from one narrated recording of
the running app, made with synthetic data.
