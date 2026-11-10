# ADR 0002: Dual-write the delta, swap only when high-water marks meet

* Status: accepted
* Date: 2026-11-10

## Context

Re-embedding a corpus takes longer than the gap between CDC events. If the pipeline freezes the log, the active index goes stale for the whole backfill. If it keeps writing only the old model, the new generation is missing every event that arrived during the backfill. If it writes every new event to both generations immediately, the new generation can jump its high water past a gap and then look caught up.

The shadow generation cannot copy vectors. They are the wrong space. It has to re-embed the redacted text.

## Decision

Migration creates the other color as `building` and records source and target.

Backfill replays events the source has already applied, and only those, into the target. It does not move the consumer offset.

A live event is applied to the active generation always. It is applied to the shadow only when `shadow.high_water + 1 == event.seq`. Otherwise the shadow has a gap and backfill is the thing that fills it.

Swap runs only when the migration state is `ready_to_swap`: target high water is at least the source high water, and the consumer offset is at the log head. A new event that arrives after that check drops the state back to `dual_writing` if the shadow is no longer level. High water only moves forward, so a replay cannot rewind a generation that has already passed that seq.

## Consequences

Good:

* Readers stay on a complete index of one model the whole time.
* The shadow cannot report "caught up" while missing a middle slice of the log.
* The eval measures the cost: 570 embed calls to land 516 chunks, because changed chunks are re-embedded and deleted documents were embedded before the delete.

Bad:

* Until swap, search quality is the old model, even if the new one is better. The lag you show operators is "events the shadow has not applied," not a blended score.
* Two writers would need a lease. This process holds one lock.

Rejected:

* Stop-the-world reindex. Simple, and the index is stale for the whole job.
* Copy vectors into the new generation. They do not mean the same thing.
* Swap on a percentage ("90% backfilled"). The missing 10% is a random slice of the corpus, not a tail you can describe.
