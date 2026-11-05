# ADR 0001: Event log and checkpoints, not a mutable status row

* Status: accepted
* Date: 2026-11-05

## Context

A workflow run dies in the middle. The row that said `running` is still `running` when the
process is gone. That row does not say whether the model had already chosen the email subject,
whether the debit had been sent, or which activities were already done.

Two shapes were on the table:

1. Update a row per activity. Resume reads the rows and continues.
2. Append an event for every decision and transition. Resume replays the log, optionally from
   a checkpoint, and continues from the folded state.

## Decision

Append-only events in SQLite are the source of truth. The `runs` row is a projection written
in the same transaction as the event. Checkpoints store the folded state and a SHA-256 of
that payload. Resume uses the newest checkpoint whose hash matches, then folds the tail.
A mismatch discards that checkpoint.

The mock model's completion is an event (`llm_decision`), written before the side effect.
Resume replays it instead of calling the model again.

## Consequences

Good:

* A kill leaves a precise prefix of the log. Replay is a function, so two workers that fold
  the same prefix agree.
* The test that tampers a checkpoint still rebuilds the same activities from the earlier
  checkpoint plus the tail.
* Swapping the model for a hostile one on resume does not change a decision that was recorded.

Bad:

* The workflow code that folds events has to be deterministic. A random choice or a clock
  read inside the fold would split the state. Time is passed in and recorded.
* The log grows with every retry and every guard decision. Checkpoints exist so resume does
  not read from the first event every time. They are not a substitute for the log.
