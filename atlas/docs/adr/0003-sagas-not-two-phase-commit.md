# ADR 0003: Saga compensations, not two-phase commit

* Status: accepted
* Date: 2026-11-05

## Context

A refund posts a ledger debit and then sends email. The email can fail permanently. The
customer should not keep a debit for a message that never went out. The ledger and the
mailer do not share a transaction manager. Two-phase commit across them is not available,
and it would couple Atlas to systems it does not operate.

The other option is to do the side effects last and "hope the last one works". That fails
as soon as two side effects are both required, which is the normal shape of this work.

## Decision

Activities declare a `compensate` tool. On a permanent failure, Atlas skips unfinished
forward work and runs compensations in reverse order of completion. Each compensation uses
its own idempotency key, so a crash during the credit is the same heal protocol as a crash
during the debit (`compensate_crash` in the suite: one debit, one credit).

Compensations are not subject to the step or cost budget. Undoing a charge is not optional
because the run is over budget.

If a compensation itself fails, the run ends `compensation_failed`. It does not pretend to
be compensated.

A denial before any side effect is `denied`, not a saga. A denial after a side effect
starts the saga.

## Consequences

Good:

* The email-failure case ends `compensated` with a matching credit. The baseline leaves the
  debit in place and is marked a failure by the suite.
* The compensation crash test shows the credit is not applied twice.

Bad:

* Compensations have to be written, and they have to be right. A reverse that posts the
  wrong amount is a new bug, not a recovered one. The amount is copied from the quote result,
  not from the model.
* Some actions do not compensate cleanly. A page that already woke someone up is one. Those
  tools leave `compensate` empty, so they are not in the job list. Anything that did declare
  a compensation still runs. The gap is real: an activity that cannot be undone should be
  last, or it should not sit in front of a step that often fails. The refund workflow closes
  the case last and compensates both the debit and the close.
