# ADR 0004: Aegis and Lumen behind ports, decisions recorded before the side effect

* Status: accepted
* Date: 2026-11-05

## Context

Atlas sits in a set with two existing projects:

* Aegis (`secure-ai-gateway`) decides whether a tool call may run.
* Lumen (`rag-knowledge-assistant`) answers from company documents, with citations, or refuses.

Importing either package would tie three deployables together and would break the offline
demo whenever those trees moved. Re-implementing them inside Atlas would fork the rules.

The model has a similar problem. If resume calls it again, a non-deterministic model will
pick a different subject, a different URL, or a different amount. The durability story
collapses.

## Decision

Guard and knowledge are ports.

* The offline guard uses Aegis's verdict set (`allow`, `require_approval`, `block`) and
  `R-TOOL-...` rule ids. The HTTP adapter POSTs `{AEGIS_BASE_URL}/v1/tool-guard/evaluate`
  and blocks with `R-AEGIS-UNAVAILABLE` if the call fails.
* The offline knowledge tool returns Lumen's shape and Lumen's refusal sentence. The HTTP
  adapter POSTs `{LUMEN_BASE_URL}/ask` with `X-User-Id`, which is Lumen's demo API. A
  transport failure becomes a refusal, and the quote step then fails closed.

The mock LLM is a pure function of the state message. Its completion is appended as
`llm_decision` before the tool runs. The catalog, not the model, decides which tools exist.
Extra activities proposed by the model are recorded and dropped. Money amounts and the
email recipient are bound by the engine from the quote and the request. The model may still
choose the subject, and may still propose a URL for `http.post`. Those arguments are what
the guard sees. The vendor workflow's mock "follows" an injected instruction and proposes
`hook.personal.test`. The guard blocks it. The safe provision step still runs.

## Consequences

Good:

* `make test` and `make eval` need neither sibling running.
* The vendor case shows the split: the model is gullible, the guard is not, and the block
  is a skipped activity rather than a crashed run (`on_block: skip`).
* A refusal from Lumen does not become a guessed refund.

Bad:

* The offline guard is a subset of Aegis. It does not tokenize, it does not taint a whole
  session, and it does not hash-chain an audit log. Those stay in Aegis. The rule ids are
  the contract, and they can drift if Aegis renames them.
* The HTTP guard path is a contract Atlas expects. Aegis does not publish
  `/v1/tool-guard/evaluate` today. Wiring the two for real is a thin translation at the
  edge of Aegis, not a change to Atlas's engine.
* Recording the completion makes the log bigger and makes a bad decision sticky. That is
  the trade for not double-sending when the model would have changed its mind.
