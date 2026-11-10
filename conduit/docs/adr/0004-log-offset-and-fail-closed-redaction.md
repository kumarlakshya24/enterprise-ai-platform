# ADR 0004: At-least-once apply, and quarantine when redaction throws

* Status: accepted
* Date: 2026-11-10

## Context

CDC delivery is at least once. The embedder is not in the same transaction as the source database, so exactly-once across that boundary is not on offer. At-most-once drops the update that arrived during the crash.

Redaction is on the path into the index. If the redactor is down and we embed anyway, the raw email is in a vector, which is the incident the redactor existed to prevent. If a single bad event blocks the offset, every later document waits.

Aegis tokenizes on its chat path. It does not serve `POST /v1/redact`. The default redactor is in-process so the demo and the tests do not need Aegis running. The HTTP adapter exists for the day that route exists.

## Decision

The log is append-only. The consumer stores `last_seq`. Apply and the offset update commit together. Applying the same `doc_version` again is a no-op. An older version does not overwrite a newer one. High water moves only forward.

The redactor runs before chunking. On success, findings become placeholders and subject tokens. On any exception, including a configured Aegis URL that errors or times out, the event is written to `quarantine` and the offset advances. The text is not embedded. `retry` runs the quarantined seqs again and clears a row only when redaction succeeds.

The OpenAI embedder is a separate adapter. It raises before any HTTP call when the key is missing. `make test` and `make eval` construct the fake embedder directly and do not read that key.

## Consequences

Good:

* Replay after a crash is safe. The tests rewind the offset and check the chunk count does not change.
* A redactor outage cannot write raw PII into the index, and it cannot pin the offset on one event.
* The poison sentinel in the demo and the three poison events in the eval are the regression for this. Zero of them are searchable.

Bad:

* Quarantined events are missing from the index until a person or a job retries them. The UI shows the count so that gap is visible.
* A producer that reuses a `doc_version` with different text is ignored. The version is part of the contract. Bump it or the edit does not land.
* The in-process redactor only finds the patterns it was given. A miss is embedded. That is a detector gap, the same class of problem as any other DLP list, and it is not papered over by the quarantine path. Quarantine runs when the component fails, not when it is quietly wrong.

Rejected:

* Exactly-once distributed transaction with the embedder. The fake embedder is pure, and a hosted one is not a transaction participant.
* Fail open when Aegis is unreachable. That writes the email into the space we then have to forget.
* Holding the offset on the poison event. One bad record stops the expense policy from updating.
