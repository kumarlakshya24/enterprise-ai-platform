<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/media/platform-banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/media/platform-banner-light.png">
  <img alt="Enterprise AI Platform: 10 projects, 477 tests, runs offline. Aegis, Lumen, Switchboard, Forge, Atlas, Lens, Charter, Arena, Conduit, Skyline." src="docs/media/platform-banner-dark.png" width="100%">
</picture>

<div align="center">

**Ten production-style systems that answer one question:<br>
how does a company let its people and its AI agents use LLMs *safely, cheaply, reliably, measurably, and in a way it can explain*?**

Each project solves one hard part on its own, runs offline with one command, and proves its claims with a saved evaluation.

![Projects](https://img.shields.io/badge/projects-10-6e56cf?labelColor=18181b)
![Automated tests](https://img.shields.io/badge/tests-477_passing-30a46c?labelColor=18181b)
![Offline](https://img.shields.io/badge/runs-offline,_no_API_key-52525b?labelColor=18181b)
![Data](https://img.shields.io/badge/data-100%25_synthetic-52525b?labelColor=18181b)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white&labelColor=18181b)

[**The platform**](#-the-platform-in-three-views) · [**The ten projects**](#-the-ten-projects) · [**How they connect**](#-how-the-projects-connect) · [**Engineering standards**](#-engineering-standards) · [**Where to start**](#-where-to-start)

</div>

---

## 💡 The problem in plain English

Every company wants its employees and its AI agents to use the best language models. The moment they do,
ten things go wrong:

| What goes wrong | Example | Which project fixes it |
|:--|:--|:--|
| **Private data leaks to a third party** | A support agent pastes a customer's card number into a chatbot | 🛡️ [**Aegis**](secure-ai-gateway/) |
| **The bill explodes, or answers are too slow** | Every “what is a load balancer?” goes to the most expensive model | 🔀 [**Switchboard**](switchboard/) |
| **The assistant makes up company policy** | “You get 30 days of leave”, when the handbook says 20 | 🔦 [**Lumen**](rag-knowledge-assistant/) |
| **An agent's code does something it shouldn't** | A generated script reads `../../secrets` or loops until the machine stalls | ⚒️ [**Forge**](forge/) |
| **A multi-step agent crashes halfway** | The refund is charged, the worker dies, and the retry charges the customer twice | 🧭 [**Atlas**](atlas/) |
| **Quality quietly gets worse and nobody notices** | A prompt change drops answer accuracy from 97% to 55% on part of the traffic | 🔬 [**Lens**](lens/) |
| **Nobody can prove which model was allowed to run** | An auditor asks whether EU customer data stayed in the EU, and the answer is a Slack thread | 📜 [**Charter**](charter/) |
| **Nobody can defend fine-tune vs RAG vs prompt** | The adapter still quotes last quarter's refund window, and the training bill was never compared with retrieval | 🏟️ [**Arena**](arena/) |
| **The platform has nowhere private to land** | Three products, one shared KMS key, and a public load balancer, because that was the tutorial | 🏙️ [**Skyline**](skyline/) |
| **The search index mixes two embedding models, or still holds someone who asked to be forgotten** | A model upgrade writes new vectors beside the old ones, and a deleted customer's text is still a nearest neighbour | 🔌 [**Conduit**](conduit/) |

Each project takes one of these problems and solves it the way a production team would: with a clear
architecture, a measured result, honest limitations, and a test that fails if the protection ever regresses.

## 🗺️ The platform in three views

Ten projects are too many for one drawing, so the platform is shown as three views. Each project keeps one colour in every view.

**1. The request path.** Who a person or an agent talks to, and what each call passes through.

```mermaid
%%{init: {"flowchart": {"curve": "linear", "nodeSpacing": 36, "rankSpacing": 80}}}%%
flowchart LR
  U(["Employees and AI agents"])
  LUM["<b>Lumen</b><br/>knowledge assistant"]
  ATL["<b>Atlas</b><br/>agent workflows"]
  FRG["<b>Forge</b><br/>tool sandbox"]
  AEG["<b>Aegis</b><br/>security gateway"]
  SW["<b>Switchboard</b><br/>model router"]
  LLM[("Hosted and local models")]

  U --> LUM
  U --> ATL
  U --> AEG
  ATL -. "what does the policy say?" .-> LUM
  ATL -. "run untrusted code" .-> FRG
  ATL -. "is this tool call allowed?" .-> AEG
  AEG -. "pick a model" .-> SW
  SW --> LLM
  AEG --> LLM

  classDef aegis fill:#18181b,stroke:#e5484d,stroke-width:2.5px,color:#fafafa
  classDef switchboard fill:#18181b,stroke:#3b9eff,stroke-width:2.5px,color:#fafafa
  classDef lumen fill:#18181b,stroke:#e2a336,stroke-width:2.5px,color:#fafafa
  classDef atlas fill:#18181b,stroke:#30a46c,stroke-width:2.5px,color:#fafafa
  classDef forge fill:#18181b,stroke:#f76b15,stroke-width:2.5px,color:#fafafa
  classDef lens fill:#18181b,stroke:#9e8cfc,stroke-width:2.5px,color:#fafafa
  classDef charter fill:#18181b,stroke:#12a594,stroke-width:2.5px,color:#fafafa
  classDef arena fill:#18181b,stroke:#e93d82,stroke-width:2.5px,color:#fafafa
  classDef skyline fill:#18181b,stroke:#8b98a9,stroke-width:2.5px,color:#fafafa
  classDef conduit fill:#18181b,stroke:#c08a5a,stroke-width:2.5px,color:#fafafa
  classDef neutral fill:#27272a,stroke:#52525b,stroke-width:1.5px,color:#fafafa
  class U neutral
  class LUM lumen
  class ATL atlas
  class FRG forge
  class AEG aegis
  class SW switchboard
  class LLM neutral
```

**2. Knowledge and data.** How documents reach the search index, and how the ways of answering are compared.

```mermaid
%%{init: {"flowchart": {"curve": "linear", "nodeSpacing": 36, "rankSpacing": 80}}}%%
flowchart LR
  DOCS[("Document changes")]
  AEG["<b>Aegis</b><br/>security gateway"]
  CON["<b>Conduit</b><br/>embedding pipeline"]
  ARN["<b>Arena</b><br/>fine-tune vs RAG vs prompt"]
  LUM["<b>Lumen</b><br/>knowledge assistant"]
  SW["<b>Switchboard</b><br/>model router"]

  DOCS --> CON
  AEG -. "redact before embed" .-> CON
  CON -. "one active index" .-> LUM
  ARN -. "RAG arm" .-> LUM
  ARN -. "which model serves the arm" .-> SW

  classDef aegis fill:#18181b,stroke:#e5484d,stroke-width:2.5px,color:#fafafa
  classDef switchboard fill:#18181b,stroke:#3b9eff,stroke-width:2.5px,color:#fafafa
  classDef lumen fill:#18181b,stroke:#e2a336,stroke-width:2.5px,color:#fafafa
  classDef atlas fill:#18181b,stroke:#30a46c,stroke-width:2.5px,color:#fafafa
  classDef forge fill:#18181b,stroke:#f76b15,stroke-width:2.5px,color:#fafafa
  classDef lens fill:#18181b,stroke:#9e8cfc,stroke-width:2.5px,color:#fafafa
  classDef charter fill:#18181b,stroke:#12a594,stroke-width:2.5px,color:#fafafa
  classDef arena fill:#18181b,stroke:#e93d82,stroke-width:2.5px,color:#fafafa
  classDef skyline fill:#18181b,stroke:#8b98a9,stroke-width:2.5px,color:#fafafa
  classDef conduit fill:#18181b,stroke:#c08a5a,stroke-width:2.5px,color:#fafafa
  classDef neutral fill:#27272a,stroke:#52525b,stroke-width:1.5px,color:#fafafa
  class DOCS neutral
  class AEG aegis
  class CON conduit
  class ARN arena
  class LUM lumen
  class SW switchboard
```

**3. Oversight and where it runs.** What watches the platform, what governs it, and the cloud layout it would land on.

```mermaid
%%{init: {"flowchart": {"curve": "linear", "nodeSpacing": 36, "rankSpacing": 80}}}%%
flowchart LR
  SKY["<b>Skyline</b><br/>cloud landing zone"]
  AEG["<b>Aegis</b><br/>security gateway"]
  LUM["<b>Lumen</b><br/>knowledge assistant"]
  SW["<b>Switchboard</b><br/>model router"]
  CHR["<b>Charter</b><br/>governance"]
  LENS["<b>Lens</b><br/>observability and evaluation"]
  CI{{"CI / release"}}

  SKY -. "account layout" .-> AEG
  SKY -. "account layout" .-> LUM
  SKY -. "account layout" .-> SW
  AEG -. "audit records" .-> CHR
  AEG -. "traces" .-> LENS
  LUM -. "traces" .-> LENS
  LENS -. "SLO snapshot" .-> CHR
  LENS -. "blocks a bad release" .-> CI

  classDef aegis fill:#18181b,stroke:#e5484d,stroke-width:2.5px,color:#fafafa
  classDef switchboard fill:#18181b,stroke:#3b9eff,stroke-width:2.5px,color:#fafafa
  classDef lumen fill:#18181b,stroke:#e2a336,stroke-width:2.5px,color:#fafafa
  classDef atlas fill:#18181b,stroke:#30a46c,stroke-width:2.5px,color:#fafafa
  classDef forge fill:#18181b,stroke:#f76b15,stroke-width:2.5px,color:#fafafa
  classDef lens fill:#18181b,stroke:#9e8cfc,stroke-width:2.5px,color:#fafafa
  classDef charter fill:#18181b,stroke:#12a594,stroke-width:2.5px,color:#fafafa
  classDef arena fill:#18181b,stroke:#e93d82,stroke-width:2.5px,color:#fafafa
  classDef skyline fill:#18181b,stroke:#8b98a9,stroke-width:2.5px,color:#fafafa
  classDef conduit fill:#18181b,stroke:#c08a5a,stroke-width:2.5px,color:#fafafa
  classDef neutral fill:#27272a,stroke:#52525b,stroke-width:1.5px,color:#fafafa
  class SKY skyline
  class AEG aegis
  class LUM lumen
  class SW switchboard
  class CHR charter
  class LENS lens
  class CI neutral
```

<sub>Solid arrows run today inside each project. Dashed arrows are the documented contracts between projects; which ones are live, and which are tested against a stand-in, is in <a href="#-how-the-projects-connect">How the projects connect</a>.</sub>

## 🧩 The ten projects

<table>
<tr>
<td width="50%" valign="top">

### 🛡️ [Aegis](secure-ai-gateway/) · security gateway

<a href="secure-ai-gateway/"><img src="secure-ai-gateway/docs/media/hero.gif" alt="Aegis: the same complaint sent to a chatbot directly and through Aegis; the model only sees placeholders" width="100%"></a>

Replaces names, emails and card numbers with placeholders before a prompt leaves the company, keeps
confidential text on a local model, checks every agent tool call, and writes a tamper-evident audit log.

**97.0% recall · 95.5% precision** on an 84-case red-team suite · **9.2 ms** p95 added latency · 200 tests

</td>
<td width="50%" valign="top">

### 🔦 [Lumen](rag-knowledge-assistant/) · knowledge assistant (RAG)

<a href="rag-knowledge-assistant/"><img src="rag-knowledge-assistant/docs/assets/crossteam.gif" alt="Lumen: two employees ask the same question and each gets their own team's policy, with citations" width="100%"></a>

Answers employee questions from company documents with citations, refuses when the answer isn't there,
and never shows anyone a document they aren't allowed to read.

Answer accuracy **63% → 89%** · restricted-doc leaks **100% → 0%** · cached answers in **5 ms** · 52 tests

</td>
</tr>
<tr>
<td valign="top">

### 🔀 [Switchboard](switchboard/) · model router

<a href="switchboard/"><img src="switchboard/docs/assets/switchboard-demo.gif" alt="Switchboard: one prompt under four routing policies, hard math to the premium model, a confidential note pinned to the local model" width="100%"></a>

Picks the cheapest model that is good enough for each request, under a versioned policy with latency
and budget ceilings, and falls back safely when a model times out.

**65% cheaper** than always using the premium model (answered requests) · **0.079 ms** p95 routing overhead · 29 tests

</td>
<td valign="top">

### ⚒️ [Forge](forge/) · sandbox for agent tool calls

<a href="forge/"><img src="forge/docs/assets/demo.gif" alt="Forge: an allowed sum, a path-traversal denial, an import denial, and the regression gate refusing a weaker policy" width="100%"></a>

Refuses dangerous file paths and imports *before* any process starts, runs the rest in a short-lived
restricted interpreter with resource limits, and logs every decision.

**55 / 55** eval cases · refuses in **0.21 ms** p95 · **41** protections locked by a regression gate · 54 tests

</td>
</tr>
<tr>
<td valign="top">

### 🧭 [Atlas](atlas/) · durable multi-agent workflows

<a href="atlas/"><img src="atlas/docs/assets/atlas-kill-resume.gif" alt="Atlas: a worker is killed right after a ledger debit; resume heals the step and the ledger still shows one debit" width="100%"></a>

Lets agents run multi-step business workflows that survive a crash at the worst moment, with approvals,
budgets, and automatic undo, without ever charging a customer twice.

**16 / 16** workflows succeed vs **3 / 16** for a naive agent · **0** duplicate charges after a crash · 30 tests

</td>
<td valign="top">

### 🔬 [Lens](lens/) · LLM observability & continuous evaluation

<a href="lens/"><img src="lens/docs/assets/lens-demo.gif" alt="Lens: SLO cards, a quality drop, drift alerts, a blocked tool span, and a seeded bad prompt failing the CI gate" width="100%"></a>

Traces every retrieval, model and tool step, judges a smart sample of traffic, catches drift, tracks
error budgets, and blocks a release in CI when quality drops.

Judge agreement **κ 0.76** with hand labels · a seeded regression is **blocked** on 5 of 6 gate rules · 23 tests

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 📜 [Charter](charter/) · AI governance control plane

<a href="charter/"><img src="charter/docs/assets/charter-demo.gif" alt="Charter: the auditor desk, a residency deny on the US model, the same request allowed after the residency file is removed, and the control matrix" width="100%"></a>

Decides which model may run on which data in which region, with Cedar-style policies a reviewer can diff, and writes an evidence pack an auditor can open. The pack is fed by an Aegis-shaped audit log and a Lens-shaped SLO snapshot.

**10 met · 4 partial · 3 gaps** on the control matrix · residency deny in **12 µs** p95 · deleting the residency file **fails the gate** · 20 tests

</td>
<td width="50%" valign="top">

### 🏟️ [Arena](arena/) · fine-tune vs RAG vs prompt

<a href="arena/"><img src="arena/docs/assets/arena-demo.gif" alt="Arena: a weekly desk ships RAG, the refund window is 30 days cited and 14 days stale, then volume flips the adapter and an 80 ms SLO leaves the student" width="100%"></a>

Runs one labeled support task through a prompt, RAG, a LoRA stub, and a distilled student, then writes a one-page memo for when the fine-tune loses.

RAG **25/25** cited on the current runbook · adapter stale on **3/3** amended policies · weekly desk ships RAG · 28 tests

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🏙️ [Skyline](skyline/) · where the platform lands

<a href="skyline/"><img src="skyline/docs/assets/skyline-demo.gif" alt="Skyline: six accounts, the cost per thousand requests as volume changes, then a security group opened to the world failing the gate" width="100%"></a>

The account layout for Aegis, Lumen, and Switchboard: no public subnet, a KMS key per tenant,
Bedrock only from Aegis, and a price per thousand requests that shows the private network is not the saving.

**$6.26** per 1,000 requests at 100k/day, against **$9.20** for always-premium · **$22.28** at 1k/day, where the endpoints cost more · **20/20** invariants · 24 tests

</td>
<td width="50%" valign="top">

### 🔌 [Conduit](conduit/) · embedding CDC

<a href="conduit/"><img src="conduit/docs/assets/demo.gif" alt="Conduit: events fill one index generation, a second embedding model catches up, reads swap, and a forgotten subject stays at zero after replay" width="100%"></a>

Streams document changes into versioned embedding indexes, swaps readers to a new model only after it has caught up, and proves a person's vectors are gone — including from the log a rebuild would replay.

Recall@1 **20 / 20** after the swap · update reuse **60 chunks kept, 30 embedded** · forgotten links **0** after a rebuild · 17 tests

</td>
</tr>
</table>

<sub>Every number above is produced by the project's own code and committed in its <code>reports/</code> or <code>eval_results/</code> folder. Test counts are from running each suite.</sub>

## 🔗 How the projects connect

The projects are built to fit together, but each one deploys and runs **on its own**. Where one project
depends on another, it talks to it through a small, documented contract (a *port*), and ships an offline
stand-in so its own demo and tests never need the other service running. That keeps every project
independently testable, and makes the seams between them explicit.

| Link | What flows across it | Status today |
|:--|:--|:--|
| **Atlas → Aegis** | Every tool call an agent proposes → `allow`, `require_approval`, or `block`, with an `R-TOOL-…` rule id | ✅ Tested against an offline Aegis-shaped guard (same verdicts and rule vocabulary). ⚠️ The HTTP mode targets `/v1/tool-guard/evaluate`, which Aegis doesn't expose yet, so it fails closed (blocks everything). |
| **Atlas → Lumen** | “What does the refund policy allow?” → a cited answer, or a refusal that stops the step | ✅ Tested against an offline Lumen-shaped stub. ⚠️ The `POST /ask` contract matches Lumen, but going live needs a service identity for Atlas in Lumen and Atlas's policies in Lumen's documents. |
| **Aegis, Lumen → Lens** | Retrieval, model and tool events → OpenTelemetry-style spans → judge, drift, SLOs, CI gate | ✅ Adapters plus a seeded 14-day synthetic trace log. ⚠️ Neither service exports Lens's event schema yet. |
| **Aegis → Switchboard** | After the security decision, choose which model answers | ⚠️ Not wired. Aegis calls any OpenAI-compatible endpoint; Switchboard routes between in-process mock models. They share the same idea of sensitivity: confidential text is pinned to a local model in both. |
| **Atlas → Forge** | Agent tools that run code or touch files | ⚠️ Not wired. Forge is the intended executor for code-running tools; Atlas's demo tools are ledger, email, pager and webhook calls. |
| **Switchboard, Forge ↔ Aegis** | Identity and prompt-injection defence | By design: both stay out of the auth path and rely on Aegis at the boundary (documented in their architecture decisions). |
| **Aegis → Charter** | Audit events (types, routes, labels, HMAC chain) → residency findings and the record-keeping control | ✅ Tested against an offline Aegis-shaped stub. ⚠️ Aegis does not export to Charter. Region and data residency are join fields on the stub. |
| **Lens → Charter** | SLO targets and status (`within_budget`, `ticket`, `page`) → the accuracy and monitoring controls | ✅ Targets match Lens. ⚠️ The snapshot is hand-shaped, not a live Lens export. Quality is paging on purpose so the pack cannot pretend accuracy is fine. |
| **Arena → Lumen** | The RAG arm calls a `POST /ask` shape and expects `answer`, `refused`, and `citations[].doc_id` | ✅ Tested against an offline Harborline index with that shape. ⚠️ `ARENA_LUMEN_URL` can probe a live Lumen; the eval stays on the stub, and the stub does not reimplement Lumen's ACL. |
| **Arena → Switchboard** | Which catalog model serves the winning arm | ✅ Offline stand-in: prompt and RAG → `balanced`, adapter → `premium` (the catalog has no adapter id), student → `fast-cheap`. ⚠️ A live route that disagrees is recorded and does not change Arena's winner. |
| **Skyline → Aegis, Lumen, Switchboard** | The account layout: private network, tenant keys, who may call Bedrock | ✅ Fixture synth and a diff. ⚠️ Not a live account, and the three products are not imported. The task images are `…:fixture`. |
| **Aegis → Conduit** | Identifiers replaced before a chunk is embedded | ✅ Tested against an offline Aegis-shaped redactor. ⚠️ Aegis has no `POST /v1/redact` yet, so HTTP mode fails closed: the event is quarantined, not embedded. |
| **Conduit → Lumen** | One active index generation, one embedding model, search hits | ✅ Offline read port. Content-hash reuse matches Lumen's indexer. ⚠️ Lumen still embeds into its own Postgres and does not call Conduit. |

**What “fully wired” would take** is small and well-defined: an authenticated tool-guard endpoint in Aegis,
a service identity plus three policy documents in Lumen, an event exporter in Aegis and Lumen, Switchboard
as Aegis's model endpoint, Forge behind Atlas's code-running tools, and an audit export plus a signed
policy bundle between Aegis and Charter. Those are the next steps, listed
openly rather than hidden.

## 📐 Engineering standards

Every project is held to the same bar, so a reviewer can trust the numbers without reading the code first.

Each project's workflow runs on every push:

[![Aegis CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/secure-ai-gateway.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/secure-ai-gateway.yml)
[![Lens CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/lens.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/lens.yml)
[![Lumen CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/rag-knowledge-assistant.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/rag-knowledge-assistant.yml)
[![Switchboard CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/switchboard.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/switchboard.yml)
[![Forge CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/forge.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/forge.yml)
[![Atlas CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/atlas.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/atlas.yml)
[![Charter CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/charter.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/charter.yml)
[![Arena CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/arena.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/arena.yml)
[![Skyline CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/skyline.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/skyline.yml)
[![Conduit CI](https://github.com/kumarlakshya24/personal-projects/actions/workflows/conduit.yml/badge.svg)](https://github.com/kumarlakshya24/personal-projects/actions/workflows/conduit.yml)

| | Aegis | Lumen | Switchboard | Forge | Atlas | Lens | Charter | Arena | Skyline | Conduit |
|:--|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Automated tests | 200 | 52 | 29 | 54 | 30 | 23 | 20 | 28 | 24 | 17 |
| Lint + format (Ruff) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| GitHub Actions on every push | ✅ | ✅ (pgvector + Redis 8) | ✅ | ✅ | ✅ (incl. SIGKILL test) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Strict type check (mypy) | ✅ | | | | | ✅ | ✅ | | ✅ | ✅ |
| Saved, reproducible evaluation | red team · classifier · latency | 46-question RAG eval | 36-case routing eval | 55-case corpus | 16 workflows vs baseline | gold set · judge κ | control matrix · residency gate | 61-question arm bench | synth diff · unit cost | recall · reuse · RTBF |
| Regression gate that fails CI | ✅ policy gate | | | ✅ policy gate | | ✅ quality gate | ✅ residency gate | ✅ eval gate | ✅ architecture gate | ✅ eval gates |
| Architecture doc + decision records | ✅ + 5 ADRs | ✅ | ✅ + ADRs | ✅ + ADRs | ✅ + 4 ADRs | ✅ + ADRs | ✅ + 4 ADRs | ✅ + 4 ADRs | ✅ + 4 ADRs | ✅ + 4 ADRs |
| Honest limitations section | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Runs offline, no API key | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Demo GIF / video | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ |

**Shared principles**

- **Measure, don't claim.** Every headline number is regenerated by a `make` target and saved next to the code.
- **Fail closed.** If a dependency, detector or guard is unavailable, the request is refused, never sent unprotected.
- **Deterministic code decides; models suggest.** Security and correctness checks never depend on a model behaving.
- **Lock what you protect.** Red-team and regression suites run in CI, so a weaker policy cannot ship quietly.
- **Say what doesn't work.** Each README ends with its known gaps and what would fix them.

## 🧭 Where to start

| If you want to… | Spend | Read |
|:--|:--|:--|
| **Skim the map** | 2 minutes | This page, then the GIF at the top of any project |
| **Read two systems** | 10 minutes | [Aegis](secure-ai-gateway/) and [Lumen](rag-knowledge-assistant/) READMEs: problem, demo, results, limitations. The [5-minute Lumen walkthrough](rag-knowledge-assistant/docs/assets/lumen-walkthrough.mp4) and the [narrated Aegis walkthrough](secure-ai-gateway/docs/media/aegis-walkthrough.mp4) |
| **Run one** | 30 minutes | Any project's `ARCHITECTURE.md` and its decision records, then `cd <project> && make install && make test && make demo` |

<details>
<summary><b>Run everything locally</b></summary>

Each project is self-contained. Python 3.12 is enough for Switchboard, Forge, Atlas, Lens, Charter, Arena, Skyline and Conduit; Aegis and
Lumen also run with Docker Compose. Switchboard, Forge, Atlas, Lens, Skyline and Conduit use distinct ports. Arena and Charter both default to 8097; set `ARENA_PORT` or `CHARTER_PORT` to run those two together. Skyline uses 8099. Conduit uses 8098.

| Project | Run | UI |
|:--|:--|:--|
| Aegis | `cd secure-ai-gateway && make up` | http://localhost:8080 |
| Lumen | `cd rag-knowledge-assistant && cp .env.example .env` (set `POSTGRES_PASSWORD`), `python scripts/fetch_models.py && make up` | http://localhost:8000 |
| Switchboard | `cd switchboard && make install && make run-local` | http://127.0.0.1:8092 |
| Forge | `cd forge && make install && make up` | http://127.0.0.1:8095 |
| Atlas | `cd atlas && make install && make up` | http://127.0.0.1:8096 |
| Lens | `cd lens && make install && make eval && make up` | http://127.0.0.1:8088 |
| Charter | `cd charter && make install && make eval && make up` | http://127.0.0.1:8097 |
| Arena | `cd arena && make install && make up` | http://127.0.0.1:8097 |
| Skyline | `cd skyline && make install && make eval && make up` | http://127.0.0.1:8099 |
| Conduit | `cd conduit && make install && make up` | http://127.0.0.1:8098 |

</details>

<details>
<summary><b>Technology</b></summary>

Python 3.12 · FastAPI · PostgreSQL + pgvector · Redis 8 · SQLite · ONNX Runtime (MiniLM embeddings,
MS MARCO cross-encoder) · spaCy · scikit-learn · OpenTelemetry-style tracing · Docker Compose ·
GitHub Actions · Playwright (demo capture) · Mermaid · fixture CloudFormation synth (Skyline)

</details>

---

<div align="center">
<sub>All names, emails, card numbers, keys and documents in this repository are synthetic.</sub>
</div>
