# ADR 0001: Enforce DLP in a gateway proxy, not in the client

* Status: accepted
* Date: 2026-11-04

## Context

Employees and agents send prompts to third-party LLMs from many places: a web chat UI,
IDE plugins, Python scripts, scheduled agents. We need one place where a policy is
applied, logged, and changed.

Options:

1. **Client-side filtering** (browser extension, SDK wrapper): redact in the client before
   the request is sent.
2. **Gateway proxy**: every LLM call goes through a service we run; the service redacts,
   routes, and logs.
3. **Provider-side controls** (vendor "no training" settings, vendor DLP add-ons).

## Decision

Build a gateway proxy. Clients authenticate to the gateway with the company IdP. The
gateway is the only component with network egress to external LLM providers and the only
holder of provider API keys.

## Consequences

Good:

* One policy, one version, one audit trail for every client. A rule change takes effect
  everywhere at once and goes through one regression gate.
* Clients never hold provider API keys, so a leaked laptop does not leak a key.
* The gateway sees tool calls as well as prompts, which client-side filtering on a chat
  box cannot.
* Provider is swappable by config (OpenAI, Azure, local vLLM) without touching clients.

Bad:

* An extra network hop and a component that must be highly available. Mitigated by
  stateless replicas (state is in Redis and Postgres) and a measured latency budget.
* It only protects traffic that reaches it. A personal ChatGPT tab bypasses it. That is
  why the demo has an unprotected pane: the gateway must be paired with egress controls
  (proxy or CASB blocking consumer AI domains on managed devices). Out of scope here,
  stated in the limitations.
* The gateway becomes a high-value target (it can de-tokenize). Mitigated by keeping the
  vault key out of the database, RBAC on restore, and short token TTLs.

Rejected:

* Client-side filtering cannot be trusted (the user controls the client), cannot see
  agent tool calls, and fragments policy across N client implementations.
* Provider-side controls are contractual, not technical. Data still leaves.
