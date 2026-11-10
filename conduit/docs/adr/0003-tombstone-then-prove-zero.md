# ADR 0003: Tombstone, delete, scrub, then require a zero count

* Status: accepted
* Date: 2026-11-10

## Context

Deleting a document removes one `doc_id`. A person shows up in many documents. A search filter that hides `subject_id` leaves the vector in the table, in the retired generation, and in the log that a rebuild will replay.

The log is inside this process. If the forget only deletes chunk rows, the next empty generation embeds the raw text again and the person is back. The version check stops that on a generation that already applied the event. It does nothing for a generation that has never seen the event.

You also cannot edit a vector in place. The unit of deletion is the chunk whose embedded text contains the subject.

## Decision

`forget(subject_id)` does this in one transaction:

1. Insert the tombstone before any delete, so a concurrent apply sees it.
2. Delete every chunk, in every generation, whose subject links include that id. Drop cache rows for those hashes when no remaining chunk uses them.
3. Scrub the log. An event whose declared subjects are all tombstoned is replaced with `[erased]`. A mixed event loses the paragraphs that mention the subject, then any leftover name or email. Document titles are scrubbed the same way.
4. Count subject links, name, and email across chunks, the log, and document titles.
5. Commit the proof only if every count is zero. Otherwise roll back.

Later applies drop chunks that intersect the tombstone set. An event whose declared subjects are all tombstoned deletes the document instead of rewriting it. Replay from offset 0 and a brand-new generation are both tested.

Chunk packing does not glue two subject sets into one vector, so forgetting one person on a mixed ticket does not require deleting the other person's paragraph.

A second call returns the stored proof. It does not delete twice.

## Consequences

Good:

* The proof is a count you can fail the build on, not a screenshot.
* The retired generation cannot become active and bring the person back. Rollback was swept too.
* The eval rebuilds a generation after the scrub and expects zero links. That failed when the log still held the raw email, which is why the scrub exists.

Bad:

* A sentence next to the person's name, in the same paragraph, is erased with them. A vector has no span delete.
* The subject directory and the demo script in git still contain the synthetic name. This ADR covers the data plane, not the source tree and not the upstream system.
* A name the directory does not know, and that the event did not declare, is not linked. Forget will not find that chunk.

Rejected:

* Soft-delete flag. A dump of the table is a copy of the person.
* Delete from the active generation only. Swap and rollback resurrect them.
* Per-user encryption keys, dropped on forget. That is a stronger design and a different system. It does not replace the count, because you still have to know which rows were theirs.
