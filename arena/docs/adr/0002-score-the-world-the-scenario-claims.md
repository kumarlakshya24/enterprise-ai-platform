# ADR 0002: Score the world the scenario claims

* Status: accepted
* Date: 2026-11-10

## Context

RAG can be pointed at a freeze index or at today's index. A fine-tune cannot, unless someone pays to train again. If every scenario is scored against today's runbook, a team that swears the policy will not change is punished for an update that has not happened. If every scenario is scored against the freeze, a team whose runbook changes weekly looks fine shipping a stale adapter.

## Decision

`change_rate` picks the world.

* `stable` scores the freeze index and the freeze phrases, on holdout plus unanswerable. Documents added after the cutoff are not in that world. Staleness is reported beside the table and does not veto.
* `weekly` eliminates both tune arms outright. The weights do not move when the runbook does. Quality is still computed on the current index so the memo can show the miss.
* `monthly` keeps a tune arm only when its staleness-slice task success clears 0.70. On this corpus it does not: the adapter answers the pre-cutoff sentence.

The quality floor is applied to the slice the scenario asked for (`full` or `common_short`). A team that drops long procedures from the contract is scored on the common short slice, and the memo still prints the full-set score.

## Consequences

Good: "ship the adapter" and "do not fine-tune" can both be true, for different claims about the corpus. The UI says which claim it used (`freeze_full` vs `current_full`).

Bad: a stable scenario hides today's amendments from the gate. The "old policy" column stays on screen so the risk is not buried. A team that marks the corpus stable and is wrong will ship a stale answer. That is the scenario lying, and the memo says so.
