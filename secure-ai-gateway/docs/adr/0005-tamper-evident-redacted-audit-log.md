[Aegis](../../README.md) › [Docs](../README.md) › [Decision records](README.md) › **ADR 0005**

# ADR 0005: Tamper-evident, redacted audit log in Postgres

* Status: accepted
* Date: 2026-11-04

## Context

Legal and security need to answer: who sent what kind of data, where did it go, which
policy decided, who approved. The audit log must not become a second copy of the data we
are protecting, and it must be hard to edit quietly.

## Decision

* Store audit events in an append-only Postgres table. Database triggers reject UPDATE
  and DELETE (SQLite gets the same triggers in tests).
* Each event carries `prev_hash` and `hash = HMAC-SHA256(key, prev_hash || canonical_json(event))`.
  The HMAC key lives in the gateway's environment, not in the database, so someone with
  database write access cannot recompute a valid chain. `GET /audit/verify` recomputes the
  chain and returns the first broken sequence number.
* Appends are serialized by a row lock on a chain-head row, so concurrent replicas cannot
  fork the chain.
* Events contain placeholders, entity types, counts, offsets, detector names, confidences,
  labels, rule ids, and policy versions. Never raw values, never value hashes (an unkeyed
  hash of a card number is brute-forceable).
* Prompt text is stored in tokenized form only up to the INTERNAL label. CONFIDENTIAL and
  RESTRICTED prompts store a keyed fingerprint and length, so the confidential roadmap is
  not copied into the log.
* A regex scrubber runs over every event before it is written. Any hit is masked and
  counted. Tests run every demo scenario and then scan the whole audit table and the
  application log output for every synthetic PII value.

## Consequences

Good:

* Tampering (edit, delete, reorder) is detectable without trusting the DBA.
* Lawyers get decisions and reasons without the data itself.

Bad:

* Serialized appends cap throughput. Per-tenant chains or periodic Merkle roots
  anchored externally (WORM storage) are the scale-out path.
* Withholding CONFIDENTIAL content means an investigator cannot read what was asked.
  A legal-hold mode that writes encrypted evidence to a separate store with its own key
  and access process is a documented next step.
* Tamper evidence is not tamper prevention. An attacker who also has the HMAC key can
  rewrite the chain. External anchoring of the head hash closes that gap.
