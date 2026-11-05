# ADR 0002: Idempotency keys in a second database, not at-most-once delivery

* Status: accepted
* Date: 2026-11-05

## Context

The worker can die in three places that matter:

* after it decided to call the tool, before the call
* after the remote system committed, before we recorded success
* after we recorded success

"Don't retry" (at-most-once) loses the refund in the first two windows. "Always retry"
(at-least-once) double-charges in the second window. The second window is the one operators
actually hit, because the remote call is the slow part.

## Decision

Side effects go to a separate SQLite file, `effects.db`, under a primary key
`{run_id}:{activity_id}` (and `:compensate` for the reversing call). That commit returns
before the engine appends `activity_completed`. The two files are two transactions on purpose,
so a kill between them is visible.

On resume, an activity left in `running` is handled as follows:

* if the effect key exists, append `activity_healed` and do not call the tool
* if it does not, call the tool again under the same key

A second call with the same key and the same payload returns the original row. A second call
with a different payload raises `IdempotencyConflict` instead of writing.

Tools that cannot accept a key (`sms.send`) are marked non-idempotent. The guard blocks them
with `R-TOOL-NOT-IDEMPOTENT` before any call.

`make kill-resume` uses `SIGKILL` in this window. The suite's `refund_crash_after_remote`
case records 0 completed steps re-run and one debit.

## Consequences

Good:

* The effect count is the proof, not a log line. The UI shows the debit staying at 1.
* Healing costs 1 ms of bookkeeping in the simulated recovery time, not another full step.

Bad:

* A real ledger has to enforce the same unique key. `effects.db` is a stand-in that does.
  A provider that only dedupes inside a ten-minute window will eventually double-charge,
  and Atlas cannot see that.
* The local journal and the remote commit are not one atomic commit. That is the point of
  the protocol, and it is also why the heal path has to exist.
