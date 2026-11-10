# Interview walkthrough

`make interview` prints this file. Functional numbers match `reports/eval.json` from seed 17. The latency is from that committed run. If you re-run `make eval` on another machine, p50 and p95 will move and the recall, reuse, and erasure counts should not.

## 1. Thirty-second pitch

Lumen re-embeds the chunk that changed. Conduit is the data plane under that. Document changes hit a log. A redactor runs before any embedding, the way Aegis tokenizes before a prompt leaves the process. Each index generation is one embedding model. Readers follow an alias. A new model is dual-written and swapped only when it has caught the log. Forgetting a person writes a tombstone, deletes the vectors in every generation, scrubs the log, and returns a proof only when the count is zero. A rebuild from that log does not put the person back. The demo is offline. No API key.

## 2. Who it is for

The search platform team, not the employee asking the question. Lumen answers. Conduit is how the index Lumen reads stays consistent when the embedding model changes, and how a privacy request becomes a count instead of a promise. The concrete job: you are moving from one embedding model to the next, CDC does not pause, and someone on the old model has asked to be deleted. You want the readers on one space the whole time, and you want a zero you can show.

## 3. Architecture tour

Stay on the diagrams in [ARCHITECTURE.md](../ARCHITECTURE.md). Five beats.

1. **Log, then index.** The offset is the checkpoint. Apply and the offset commit together. The same `doc_version` is a no-op. An older version does not win.
2. **Redact, then embed.** The stand-in replaces name, email, phone, card, and SSN shape. Subject emails become `[person:id]` so the chunk is linked. If redaction throws, the event is quarantined and not embedded.
3. **One model per generation.** `emb-v1` and `emb-v2` are the same width. The salt is the model. The alias is one row. Search embeds with whatever that row says.
4. **Dual-write without a gap.** The shadow only receives a live event when it is the next seq. Otherwise backfill fills the hole. Swap is a 409 until the high-water marks meet.
5. **Tombstone, scrub, count.** Deleting the active index is not enough. The log is how a new generation is born. The scrub is why the eval's rebuild stays at zero.

## 4. Deep dive: the proof is a count, and the log is part of it

The hard decision is ADR 0003.

The first version of forget deleted chunk rows and left the CDC text alone. Replay on the same generation was fine, because the stored `doc_version` made the event a no-op. A new generation has no version to compare against. It embedded the email again. The test that builds a generation after the forget is the one that caught it.

So the transaction writes the tombstone, deletes the chunks in every generation including the retired one, scrubs the log, then counts. Name and email have to be absent from chunks, titles, and the log. If any count is non-zero, the transaction rolls back and there is no proof. The handler will not return `verified: true` on a partial delete.

What I rejected:

* A search-time filter. The vector is still in the file.
* Deleting only the active generation. Rollback brings the person back.
* Calling the problem solved because the current generation's version check hides the log. The next model migration is an empty generation.

## 5. Demo script

From `conduit/`:

```bash
make test
make eval
make demo
make up
# http://127.0.0.1:8097  → Play demo
```

What you should see:

* `make test` green. The suite covers reuse, the early swap refusal, dual-write of an event that arrives once the shadow is level, rollback, and a forget that survives replay and a new generation.
* `make eval` prints recall 100% before and after the swap, 60 reused and 30 embedded on the updates, RTBF remaining 0, and `gates: PASS`.
* `make demo` prints `PASS`. Quarantine is 1. Search for the mileage line hits `handbook-expenses` on `emb-v2`. Forget reports verified. Replay leaves 0 links and 0 emails.
* The UI shows apply p50 and p95 from the events just applied, the read alias, both generation cards, the redaction preview on ticket 441, and the proof stamp after Forget.

`make interview` prints this file. It does not start a server.

## 6. What the numbers prove, and what they do not

Prove:

* On 30 docs that change one paragraph, 60 chunk embeddings are reused and 30 are computed. Rate 0.6667. That is the Lumen property, measured again here.
* The 20 keyword queries hit the right document at rank 1 in `emb-v1` and again at rank 1 in `emb-v2`. The spaces are not the same vectors. Each space is consistent.
* Migration does 570 embed calls and reuses 60 inside the new model. The shadow ends at 516 chunks, which is 172 surviving docs times 3 chunks. Eight docs were embedded and then deleted.
* Three poison events are quarantined and none of them are in the index.
* After forgetting two subjects, zero links remain, the exclusive document is absent from a rebuilt generation, and the other person on the mixed document is still linked.
* Apply latency on the committed run is p50 0.3475 ms, p95 0.4222 ms, p99 0.5312 ms, n=221. That is the fake embedder in-process.
* At the measured 160.12 tokens per doc and a $0.02 per million token list price, a million docs is $3.2024. A 2,000-token memo is $40 at that price. An 8,000-token policy is $160, or $1040 at $0.13. Those last three hold the token count fixed. They are not a measurement of a memo.

Do not prove:

* That a neural embedder retrieves paraphrases. The hash embedder retrieves shared tokens. Say `fake-hash` when you say 100%.
* That a hosted embedder adds 0.42 ms. It adds its own latency. We did not call one.
* That $3.2024 is a bill. It is `160.12 * 0.02`.
* That Aegis was on the path. The stand-in was. Aegis does not serve `/v1/redact`.
* That the person is gone from the source system or from this git tree. They are gone from this database.

## 7. Failure modes, and what production would add

Say these out loud. They are written in [FAILURE_MODES.md](FAILURE_MODES.md).

* The chunk is the unit of delete. A neighbor sentence in the same paragraph goes too. Different subject sets are not packed together, which keeps the mixed ticket honest.
* An unknown nickname is not linked. The directory and the event's `subject_ids` are the contract.
* Quarantine leaves a hole until retry. The alternative was to stall the log or to embed the raw text.
* The p95 will not survive a network embedder. The alias rule will. The brute-force scan will not survive millions of chunks. The alias rule will.
* Two processes need a lease. This lock does not count.
* Backups of the SQLite file are a copy of whatever they held at backup time. The proof does not reach them.

## 8. Questions, with the short answer

**Why not re-embed in place the way a single-table indexer does?**
Readers would see a mix, or they would see an empty table if you delete first. The dimension is not a safety check. ADR 0001.

**Why is the shadow not allowed to skip ahead?**
A gap that has been jumped looks like a caught-up index. Backfill would not revisit those seqs, because high water has moved past them. ADR 0002.

**Why scrub the log if the tombstone already drops the chunks?**
The tombstone drops them when the apply path runs. A new generation replays events that have never been applied, so there is no stored version to skip. The scrub is what that replay reads. The eval rebuild is the test.

**What does Lumen still do better?**
Lexical and vector retrieval, citations, and ACLs on the answer path. Conduit does not answer questions. It keeps the index Lumen would read from splitting in two.

**What happens if Aegis is down?**
If you pointed `CONDUIT_AEGIS_URL` at it, the call fails and the event is quarantined. The default build does not make that call. It runs the stand-in.

**Why is recall perfect?**
Because the queries are the planted keywords and the embedder hashes tokens. It is a regression test that a model swap did not mix spaces and did not drop documents. It is not a quality leaderboard.
