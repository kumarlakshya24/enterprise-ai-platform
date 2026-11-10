<div align="center">

# Aegis

A security gateway between your people, your AI agents, and third-party LLMs.

[![CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/secure-ai-gateway.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/secure-ai-gateway.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](pyproject.toml)
![runs offline](https://img.shields.io/badge/runs-offline-6e7781)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/tests-200%20passing-2ea44f)
![Red-team recall](https://img.shields.io/badge/red--team%20recall-97%25-2ea44f)
![p95 overhead](https://img.shields.io/badge/p95%20overhead-9%20ms-0969da)
![Synthetic data](https://img.shields.io/badge/data-100%25%20synthetic-8250df)

[Overview](#overview) ·
[Quickstart](#quickstart) ·
[Usage](#usage) ·
[Architecture](#architecture) ·
[Design decisions](#design-decisions) ·
[Results](#results) ·
[Project layout](#project-layout) ·
[Where it fits](#where-it-fits) ·
[Documentation](#documentation) ·
[Limitations](#limitations)

<img src="docs/media/hero.gif" alt="The same customer complaint sent two ways. Left: a personal chatbot receives the name, email, and card number. Right: through Aegis, the model only sees placeholders and the reply is restored for the user." width="100%">

<sub>The same complaint sent two ways. <b>Left:</b> a personal chatbot receives the name, email, and full card number.
<b>Right:</b> through Aegis, the model sees only <code>[PERSON_NAME_1]</code>, <code>[EMAIL_1]</code>, and <code>[CREDIT_CARD_1]</code>, and the reply is restored for the support agent with the card masked.</sub>

</div>

---

## Overview

Companies want employees and agents to use the best models. Without controls, data leaves in four
ways, and a regex scanner catches only the first:

| | Leak path | Without a gateway | With Aegis |
|:-:|---|---|---|
| 1 | **Pasted PII** | A complaint with a name, email, and card goes straight to the provider. | PII is swapped for placeholders before the call, and the answer is restored for the user's role. |
| 2 | **Sensitive context** | A roadmap note has no name or card, so pattern-based DLP lets it through. | A private classifier labels it CONFIDENTIAL and the request goes to a local model instead. |
| 3 | **Agent tools** | An agent emails a customer record to a personal Gmail address. | The tool guard blocks personal domains. Risky calls wait for a second person to approve them. |
| 4 | **Prompt injection** | A wiki page tells the agent to put customer data in an image URL. | The injection is flagged, the session is tainted, and three independent rules block the URL. |

> [!IMPORTANT]
> Aegis assumes the model can be fooled. The demo's mock model obeys the injection on purpose,
> and the call is still blocked, because tool calls are checked by deterministic code, not by asking
> the model to behave.

## Quickstart

You need Docker with Compose v2. No API key, no account, and no real data.

```bash
git clone https://github.com/kumarlakshya24/personal-projects.git
cd personal-projects/secure-ai-gateway
make up      # creates .env with random keys, builds and starts 6 containers
```

Open **http://localhost:8080**, pick a scenario, and click **Run both paths**. To check everything
from the terminal instead:

```bash
make demo    # 20 end-to-end checks against the running stack, prints PASS / FAIL
make down
```

<details>
<summary><b>Run without Docker</b> (Python 3.11+)</summary>

```bash
python -m venv .venv && . .venv/bin/activate
make install     # dev dependencies + spaCy en_core_web_sm, pinned by hash
make test        # unit and integration tests, in-memory SQLite and vault
make run-local   # IdP, mock LLMs, and gateway as separate processes on :9000 / :8090 / :8091 / :8080
```

</details>

<details>
<summary><b>Host a public demo</b> (one click, free plan)</summary>

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kumarlakshya24/personal-projects)

This deploys a single container that runs every control, with the identity provider and the models
in-process. No secrets are needed. Cold start, free-plan latency, and shared-state caveats are
in [`docs/deploy.md`](docs/deploy.md).

</details>

<details>
<summary><b>Use a real model</b> (any OpenAI-compatible endpoint)</summary>

Set these in `.env`:

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=<your key>
LLM_MODEL=gpt-4o-mini
```

The unprotected comparison path refuses to run against a real provider unless you also set
`AEGIS_DEMO_ALLOW_UNPROTECTED_REAL=true`. Agent behaviour with a real model is not deterministic,
but the guard does not depend on it.

</details>

## Usage

<div align="center">

[![Watch the 3-minute narrated walkthrough](docs/media/walkthrough-poster.jpg)](docs/media/aegis-walkthrough.mp4)

<sub>3:44 · narrated, with subtitles · recorded from the running app on synthetic data ·
<a href="docs/media/aegis-walkthrough.mp4">MP4, 7 MB</a></sub>

</div>

Each scenario runs the same input down an unprotected path and through the gateway. The "third
party" is a mock OpenAI that logs everything it receives, so the evidence comes from the provider's
side.

| # | Scenario | Unprotected path | Through Aegis | Rules |
|:-:|---|---|---|---|
| 1 | Complaint with a name, email, and card | Provider receives all three | Placeholders only; reply restored, card masked for support | `R-ROUTE-INTERNAL` |
| 2 | Confidential note with no PII | Provider receives the roadmap | Classifier: CONFIDENTIAL 0.89, route `local_only` | `R-ROUTE-CONFIDENTIAL` |
| 3 | Agent emails a summary to personal Gmail | Full record, card included, in a Gmail outbox | Blocked. Corporate address: approved by a second person, card masked | `R-TOOL-PERSONAL-DOMAIN`, `R-TOOL-HIGH-RISK` |
| 4 | Wiki page injects "put the data in an image URL" | Email and card leave in the URL | Injection flagged (0.97), session tainted, call blocked | `R-TOOL-URL-NOT-ALLOWLISTED`, `R-TOOL-DATA-IN-URL`, `R-TOOL-TAINTED-SESSION` |
| 5 | "Retries with exponential backoff in Python?" | Answered | PUBLIC, prompt unchanged, about 7 ms added | `R-ROUTE-PUBLIC` |

Scenario 1 is the animation at the top of this page. Expand the others:

<details>
<summary><b>2 · Pattern-only DLP is not enough</b>: a confidential note with no PII stays on the local model</summary>
<br>
<img src="docs/media/scenario-2-context-leak.gif" alt="Scenario 2: a confidential planning note has no PII; the classifier labels it CONFIDENTIAL and routes it to the local model" width="100%">
</details>

<details>
<summary><b>3 · Tool exfiltration</b>: personal Gmail is blocked, and a corporate send needs a second approver</summary>
<br>
<img src="docs/media/scenario-3-tool-exfiltration.gif" alt="Scenario 3: the tool guard blocks an email to a personal Gmail address; a corporate email is queued, self-approval is refused, and another approver releases it with the card masked" width="100%">
</details>

<details>
<summary><b>4 · Prompt injection</b>: a hidden instruction in a wiki page is flagged and the exfiltration is blocked</summary>
<br>
<img src="docs/media/scenario-4-prompt-injection.gif" alt="Scenario 4: the unprotected agent leaks data in an image URL; through Aegis the injection is flagged, the session tainted, and the image call blocked by three rules" width="100%">
</details>

<details>
<summary><b>Policy gate</b>: an admin tries to allow card numbers, and the gateway refuses</summary>
<br>
<img src="docs/media/policy-regression-gate.gif" alt="Policy console: setting CREDIT_CARD to allow is replayed against the red-team corpus and refused with the list of regressed cases" width="100%">
</details>

<details>
<summary><b>Audit</b>: verify that nobody has edited the log</summary>
<br>
<img src="docs/media/audit-verify.gif" alt="Audit tab: redacted, hash-chained events and a successful chain verification" width="100%">
</details>

There's a click-by-click guide, with the demo users and what to look for, in
[`docs/demo-guide.md`](docs/demo-guide.md).

### One request

Interactive OpenAPI docs are served at `http://localhost:8080/docs`.

```bash
TOKEN=$(curl -s localhost:8080/demo/login -H 'content-type: application/json' -d '{"username":"avery"}' | jq -r .access_token)
curl -s localhost:8080/chat -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"message":"Hi, my name is Dana Holloway, card 4111 1111 1111 1111, email dana.holloway@example.com"}' \
  | jq '{sent: .sent_to_llm.prompt, answer, route: .decision.route}'
curl -s localhost:8090/_evidence/received | jq '.[-1].messages[-1].content'   # what the "third party" received
```

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/chat` | employee | Protected chat. Returns the answer, decision, entities, what was sent, audit ids, and latency |
| POST | `/agent/run` | employee | Protected agent run (bounded tool loop) |
| GET | `/agent/runs/{id}` | owner, approver | Run record (redacted) |
| GET / POST | `/approvals`, `/approvals/{id}/approve`, `/approvals/{id}/deny` | approver | Approval queue (four eyes, expiry) |
| POST | `/chat/approvals/{id}/resume` | requester | Resume a chat request after approval |
| POST | `/vault/detokenize` | session owner | Role-scoped restore |
| GET | `/policies` | employee | Effective policy for the caller |
| GET / PUT | `/admin/policies` | security admin | Policy bundles, behind the regression gate |
| POST | `/admin/policies/dry-run` | security admin | Preview a decision under a candidate policy |
| GET | `/admin/regression` | security admin | Gate status for the active policy |
| GET | `/audit`, `/audit/verify` | security admin | Query the log and verify the hash chain |
| GET | `/healthz` | anyone | Component status |
| * | `/demo/*`, `/` | demo mode only | UI, sign-in proxy, unprotected path, evidence |

### Demo users

Mock identity provider, all synthetic.

| User | Role | Used for |
|---|---|---|
| `avery` | support agent | Default user. Sees cards masked |
| `taylor` | billing specialist | Sees full card numbers on restore |
| `morgan` | approver | Approves risky tool calls |
| `sam` | security admin | Policy console, audit |
| `riley` | employee | RBAC denials |
| `legal-bot` | service account | Per-user override: everything stays local |
| `personal` | password login | Rejected: SSO only |
| `contractor` | other tenant | Rejected: wrong tenant |

## Architecture

Every prompt and every tool call goes through the same five steps. Nothing reaches a provider without
a decision that names the detector, the confidence, the rule, and the route.

<img src="docs/media/how-it-works.gif" alt="Animated architecture: a message flows through identity, detection, tokenization, labelling, and the policy decision" width="100%">

```mermaid
flowchart LR
    U(["Employee or agent<br/>signed in with SSO"]) --> ID

    subgraph GW ["Aegis gateway"]
        direction LR
        ID["1 · Identity<br/>JWT, tenant, RBAC"] --> DET["2 · Detect<br/>regex, checksums, NER"]
        DET --> TOK["3 · Tokenize<br/>encrypted vault"]
        TOK --> LAB["4 · Label<br/>private classifier"]
        LAB --> DEC{"5 · Decide<br/>policy engine"}
    end

    DEC -- "allow / redact" --> EXT["External LLM<br/>sees placeholders only"]
    DEC -- "local_only" --> LOC["Local model<br/>inside the boundary"]
    DEC -- "require_approval" --> HUM["Second person approves"]
    DEC -- "block" --> BLK["Refused, with the reason"]
    EXT --> RES["Answer restored<br/>for the user's role"]
    LOC --> RES
```

PII and secrets are always tokenized or redacted first. The route then depends on the label of what is
left:

| Label of the remaining text | Route | What the external provider receives |
|---|---|---|
| `PUBLIC` | `allow` | The prompt, byte for byte |
| `INTERNAL` | `redact_and_continue` | The prompt with placeholders such as `[EMAIL_1]` |
| `CONFIDENTIAL` | `local_only` | Nothing. A model inside the boundary answers. |
| `RESTRICTED` | `block` | Nothing |
| More than 5 restricted entities, or a high-risk tool call | `require_approval` | Nothing until a second person approves |

For agents, the same pipeline wraps the tool loop. Every tool call passes the **tool guard** and every
tool output passes the **injection detector** before the model sees it. The full design, with trust
boundaries and failure modes, is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

Python 3.11+, FastAPI, spaCy (`en_core_web_sm`), a scikit-learn classifier exported to JSON, an
AES-256-GCM vault, PostgreSQL, Redis, and Docker Compose. Offline, with no API key:
`make install`, `make test` (in-memory SQLite and vault), and `make run-local` (gateway on
port 8080). `make demo` checks a gateway that is already up, from `make up` or `make run-local`.
`make redteam`, `make regression`, and `make benchmark` write the reports under `reports/`.

### Features

<table>
<tr>
<td width="50%" valign="top">

**Detect and tokenize.** Regex with Luhn and IIN checks, secret patterns, spaCy NER, and Unicode
and zero-width normalization. Values become `[TYPE_N]` placeholders, stored with AES-256-GCM and bound to
the tenant, user, session, and purpose.

</td>
<td width="50%" valign="top">

**Private context classifier.** TF-IDF and logistic regression, exported to JSON (never pickle) and
checked against its SHA-256 at start-up. Each label comes with the words that drove it.

</td>
</tr>
<tr>
<td valign="top">

**Policy as data.** Five routes, per-tenant and per-user overrides, and versioned bundles. Every
decision returns its rule id, reasons, and policy version.

</td>
<td valign="top">

**Regression gate.** Each policy change replays the red-team corpus for every override. A change that
weakens protection is refused with HTTP 409, both in the admin API and in CI.

</td>
</tr>
<tr>
<td valign="top">

**Agent tool guard.** Recipient and URL allowlists, a personal-domain blocklist, DLP on decoded URLs
(percent, base64, hex), and four-eyes approvals that expire.

</td>
<td valign="top">

**Prompt-injection defense.** Weighted signals with an explanation, session taint, and an output
sanitizer that strips zero-click image exfiltration from answers.

</td>
</tr>
<tr>
<td valign="top">

**Identity and RBAC.** RS256 JWTs checked against JWKS, SSO-only and tenant-restricted sign-in, and
role-scoped restore: support agents see `•••• 1111`, billing sees the full card.

</td>
<td valign="top">

**Tamper-evident audit.** Append-only and HMAC hash-chained. Confidential content is withheld and a
regex scrubber runs before every write. One call verifies the chain.

</td>
</tr>
</table>

Aegis **fails closed**: if the vault, the audit store, or a detector fails, the request is refused
with a 503 rather than sent unprotected.

## Design decisions

| Decision | Record |
|---|---|
| Enforce DLP in a gateway proxy, not in the client | [ADR 0001](docs/adr/0001-gateway-proxy-not-client-side-filtering.md) |
| Reversible placeholders, not deletion | [ADR 0002](docs/adr/0002-placeholder-tokenization-not-deletion.md) |
| A private classifier labels context and picks the route | [ADR 0003](docs/adr/0003-private-classifier-for-label-and-route.md) |
| A deterministic tool guard with taint, not model self-defense | [ADR 0004](docs/adr/0004-deterministic-tool-guard-with-taint.md) |
| A hash-chained, redacted audit log | [ADR 0005](docs/adr/0005-tamper-evident-redacted-audit-log.md) |

The index is [`docs/adr/README.md`](docs/adr/README.md). Measured gaps are in
[`docs/tradeoffs-and-limitations.md`](docs/tradeoffs-and-limitations.md).

## Results

Every number is produced by the code in this repository and regenerated by a `make` target.

| What | Result | Reproduce |
|---|---|---|
| Demo scenarios | **5 / 5**: the unprotected path leaks, the protected path does not | `make demo` |
| Red-team suite | **84 cases · recall 97.0% · precision 95.5%** (2 misses, 3 over-routes, all explained) | [`reports/redteam.md`](reports/redteam.md) |
| Entity detection | **47 / 50** labelled values neutralized, **0** false redactions | [`reports/redteam.md`](reports/redteam.md) |
| Classifier, blind holdout | **86%** accuracy, **94%** recall on sensitive context (100 hand-written rows) | [`reports/classifier.md`](reports/classifier.md) |
| Added latency, p95, in-process | **7.5 ms** for a public question, **9.2 ms** with 3 entities | [`reports/latency.md`](reports/latency.md) |
| Added latency, p95, Docker stack | **16.7 ms** / **21.2 ms** with the Postgres audit and Redis vault in the loop (budget 300 ms) | [`reports/latency.md`](reports/latency.md) |
| Regression gate | **64** protected cases locked. Allowing `CREDIT_CARD` causes 7 regressions and a 409 | [`reports/regression.md`](reports/regression.md) |
| Tests | **200** unit and integration tests | `make test` |
| Security checklist | **13 / 13** automated checks | [`docs/security-checklist.md`](docs/security-checklist.md) |

> [!NOTE]
> The red-team corpus is a development set: gaps found there were fixed, then locked in by the
> regression gate. The classifier's holdout is blind, so its number is the unbiased one. The known
> misses are listed in [`docs/tradeoffs-and-limitations.md`](docs/tradeoffs-and-limitations.md).

## Project layout

```
secure-ai-gateway/
├── ARCHITECTURE.md          design, diagrams, trust boundaries, failure modes, tradeoffs
├── docker-compose.yml       gateway, Postgres, Redis, IdP, mock OpenAI, mock local model; segmented networks
├── Dockerfile  Makefile  pyproject.toml  requirements*.txt  .env.example
├── aegis/
│   ├── dlp/                 detectors (regex, checksums, secrets, cues), spaCy NER, normalization, engine
│   ├── vault/               AES-GCM cipher, Redis and memory backends, tokenize and restore
│   ├── classifier/          JSON model, pure-Python inference, trainer (scikit-learn, dev only)
│   ├── policy/              schema, default policy, decision engine, versioned store, regression gate
│   ├── guard/               tool guard, injection detector, output sanitizer, approvals, URL decoding
│   ├── agent/               sandboxed tools, bounded runner, unprotected demo runner
│   ├── audit/               hash-chained store and scrubber
│   ├── auth/                OIDC/JWT verification, RBAC, rate limit
│   ├── llm/                 provider interface, OpenAI-compatible client, deterministic mock model
│   ├── gateway/             FastAPI app, routes, pipeline, demo UI
│   ├── idp/  mock_llm/      mock identity provider and mock OpenAI services
│   └── demo/                synthetic customers, wiki pages, scenarios, fake secrets built at runtime
├── data/classifier/         synthetic training set (generated, seeded) and hand-written blind test set
├── eval/                    red-team corpus, regression baseline, runners
├── bench/latency.py         stage and end-to-end latency
├── scripts/                 demo checks, local runner, env init, security check, data generator
├── tests/                   unit and integration tests
├── reports/                 generated: red team, regression, latency, classifier
└── docs/                    ADRs, threat model, demo guide, checklist, tradeoffs, cost, deploy, media
```

## Where it fits

Aegis is the trust boundary of the platform: every prompt and every agent tool call is meant to pass
through it before anything leaves the company.

```mermaid
flowchart LR
  U([Employees and agents]) --> AEG[🛡️ Aegis<br/>DLP · private routing · tool guard · audit]
  AEG --> LLM[("hosted or local model")]
  AEG -. "then: which model?" .-> SW[🔀 Switchboard]
  ATL[🧭 Atlas] -. "is this tool call allowed?" .-> AEG
  AEG -. "spans" .-> LENS[🔬 Lens]
  classDef aegis fill:#cf222e,stroke:#a40e26,color:#fff
  classDef switchboard fill:#0969da,stroke:#0550ae,color:#fff
  classDef lumen fill:#bf8700,stroke:#9a6700,color:#fff
  classDef atlas fill:#1a7f37,stroke:#116329,color:#fff
  classDef forge fill:#bc4c00,stroke:#953800,color:#fff
  classDef lens fill:#8250df,stroke:#6639ba,color:#fff
  class AEG aegis
  class SW switchboard
  class ATL atlas
  class LENS lens
```

| Neighbour | What flows across it | Status today |
|:--|:--|:--|
| [🧭 Atlas](../atlas/) | Each tool call an agent proposes → `allow`, `require_approval`, or `block` with an `R-TOOL-…` rule id | ⚠️ Atlas ships an offline guard with the same verdicts and rule vocabulary. Its HTTP mode targets `/v1/tool-guard/evaluate`, which Aegis doesn't expose yet (Aegis runs the tool guard inside its own `/agent/run` loop), so live mode fails closed. |
| [🔀 Switchboard](../switchboard/) | After the security decision, pick the model | ⚠️ Not wired. Both pin confidential text to a local model. |
| [🔬 Lens](../lens/) | Route, policy and tool decisions → spans → drift, SLOs and judged samples | ⚠️ Lens has an Aegis adapter and synthetic traces; Aegis doesn't export that event schema yet. |
| [⚒️ Forge](../forge/), [🔀 Switchboard](../switchboard/) | Identity and prompt-injection defence | By design: both stay out of the auth path and rely on Aegis at the boundary. |
| [📜 Charter](../charter/) | Audit events (types, routes, labels, HMAC chain) → residency findings and the record-keeping control | ✅ Charter is tested against an offline Aegis-shaped stub. ⚠️ Aegis does not export to Charter. Region and data residency are join fields on the stub. |

<sub>See the <a href="../README.md">platform overview</a> for how the projects connect.</sub>

## Documentation

| Read this | To learn |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Components, data flow, trust boundaries, failure modes, tradeoffs |
| [`docs/adr/`](docs/adr/README.md) | The five design decisions, the options rejected, and why |
| [`docs/threat-model.md`](docs/threat-model.md) | 6 attackers and 19 attack vectors, each mapped to code and to the test that proves the control |
| [`docs/demo-guide.md`](docs/demo-guide.md) | What to click, what you should see, and why it matters |
| [`docs/security-checklist.md`](docs/security-checklist.md) | 20 controls with their proof, plus what production still needs |
| [`docs/tradeoffs-and-limitations.md`](docs/tradeoffs-and-limitations.md) | What this does not solve, measured gaps, what to build next |
| [`docs/cost-and-scaling.md`](docs/cost-and-scaling.md) | Cost per 1,000 requests, throughput, the first bottleneck |
| [`docs/deploy.md`](docs/deploy.md) | Hosting the single-container demo |

## Limitations

A gateway only protects traffic that reaches it, so a personal ChatGPT tab needs egress controls as well.
It does not stop an insider who retypes data by hand. Known detection misses include card numbers spelled
out as words and social-engineering injections that avoid the usual keywords. Each one, and what would fix
it, is in [`docs/tradeoffs-and-limitations.md`](docs/tradeoffs-and-limitations.md).

---

<div align="center">
<sub>Built with FastAPI, spaCy, scikit-learn, Postgres, Redis, and Docker Compose.
All names, emails, cards, and keys in this repository are synthetic.</sub>
</div>
