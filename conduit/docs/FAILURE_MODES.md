# Failure modes

Each one is a limit of this system, and the mitigation that is actually implemented.

## The log is not the upstream system

Forget scrubs `cdc_events`, chunk text, and document titles in this SQLite file. The demo script in the repository still contains the synthetic names. A source database that keeps emitting the raw event will append a new row. The tombstone stops that row from being indexed, which the replay test covers. It does not delete the row in the source.

Mitigation: declared subjects on the event plus the tombstone. The proof counts this file. Backups and replicas of this file are out of band. A production eraser has to delete those copies on purpose. This demo does not.

## Erasure is a chunk, not a span

A paragraph that mentions Ava Chen is one vector. Deleting it removes the invoice sentence in the same paragraph. A paragraph that does not mention her, and does not share her subject set, stays. That is why ticket 443 can lose Ava's half and keep Leo's.

Mitigation: the chunker refuses to pack different subject sets into one chunk. Overlap is zero, so a person's tokens are not copied into the next piece. Turning overlap on without retagging would widen the delete. Do not turn it on quietly.

What this does not fix: a nickname, or a sentence that identifies someone without their directory name. If the event did not declare the subject and the redactor did not emit `[person:…]`, there is no link, and forget will not find the chunk.

## The redactor can be wrong while looking healthy

Quarantine runs when redaction throws. A pattern the redactor does not know is replaced with nothing and then embedded. The eval's poison sentinel is the throw. It is not a test of unknown formats.

Mitigation: the patterns that are implemented (name, email, phone, Luhn-checked card, SSN shape) have a unit test that the raw value is absent from the output. Subject emails become a person token rather than a generic `[email]`, so the chunk is linked. An HTTP Aegis call that fails quarantines the event instead of embedding the raw body.

What this does not fix: a new identifier shape. That is a detector change, reviewed like any other DLP rule.

## A quarantined event is a hole, not a pause

The offset moves past a poison event so the rest of the log applies. Until retry succeeds, that document is absent. The demo shows `quarantine 1` after the stream. The eval requires 3 quarantined and 0 indexed.

Mitigation: the row stays in `quarantine` and in the log. Retry re-applies that seq. A redactor that is still down leaves the row in place.

What this does not fix: nobody retries. The count is on the status payload so the UI cannot hide it. It is not a pager.

## Swap is refused early, and rollback is a different model

Swap returns 409 while the shadow high water is behind. That is tested. After swap, search embeds with the new model. Rollback points the alias at the old generation and search embeds with the old model. A caller who stored vectors from before the rollback is searching the wrong space. The read port does not accept those vectors.

Mitigation: the server embeds the query. The generation's chunk versions are checked to be a single model before swap and before search.

## The hash embedder is not a neural embedder

Recall@1 is 20 / 20 because each query is a keyword planted in one document, hashed with two buckets so a single collision cannot outrank it. A paraphrase with no shared token will not retrieve. Scores under 0.25 are dropped as collision noise.

Mitigation: the number is reported next to the embedder name `fake-hash`. The same 20 queries are run again after the alias moves to `emb-v2`, which only proves the new space is internally consistent.

What this does not fix: quality of a hosted model. The OpenAI adapter is not called by `make eval`.

## Latency has no network in it

p50 0.3435 ms and p95 0.4614 ms are the in-process apply of 221 events on the machine that wrote `reports/eval.json`. A hosted embedder adds its own RTT, and the dual-write adds a second call. Those are not in the measurement.

Mitigation: the JSON labels the embedder, and the cost file is a projection. The p95 gate is "under 100 ms," which only catches a hang, not a regression of a tenth of a millisecond.

## One writer

The lock is in-process. Two processes on one SQLite file will not keep a single offset. At a real 10× this file is the wrong store. The generation alias and the tombstone rule are what you carry to Postgres or to an ANN index. The brute-force scan is what you throw away.

## Reused versions drop edits

An event with a `doc_version` less than or equal to the stored version is ignored. A producer that edits the body and reuses the version will not see the edit. The stale-version test locks this. Bump the version.

## The dollar figure is arithmetic

$3.2024 per million documents is 160.12 measured tokens times a $0.02 list price. The $40 and $160 rows assume 2,000 and 8,000 tokens. They are not a measurement of those documents and not an invoice. `eval/pricing.yaml` says the same thing.
