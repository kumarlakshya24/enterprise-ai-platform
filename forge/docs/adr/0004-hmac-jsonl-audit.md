# ADR 0004: HMAC JSONL audit log

* Status: accepted
* Date: 2026-11-05

## Context

The demo needs a verify command and no database. The log must not become a second copy of workspace files or of secrets that happened to be in a snippet.

## Decision

Each decision is one JSON line. The hash is HMAC-SHA256 over the canonical record, including the previous hash. The key is `FORGE_AUDIT_KEY` or the documented demo placeholder. Records store a short redacted preview and a SHA-256 prefix of the code and stdout, not the full bodies. `verify` recomputes the chain.

## Consequences

Edit, reorder, and truncation are visible. An attacker who has the HMAC key can rebuild a valid chain, so this is tamper evidence. The demo key is public by design. Production replaces it and can anchor the head hash outside the file.
