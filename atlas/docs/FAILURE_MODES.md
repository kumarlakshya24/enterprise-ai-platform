# Failure modes

What Atlas does when something goes wrong, and what it still does not handle.
Mitigations that exist in code are named with the test or the suite case that locks them.

## 1. Worker dies after the remote commit

**What happens.** The debit is in `effects.db`. The completion event is not in the log.
The activity stays `running`. The lease is held until its TTL.

**What we do.** A new worker waits out the lease (the old one might still be alive), claims
with a new fencing epoch, sees the effect key, and appends `activity_healed`. The tool is
not called. `make kill-resume` and `refund_crash_after_remote`.

**Residual risk.** If the remote system committed and then lost the response, and it also
ignores the idempotency key, we cannot tell. We refuse tools that have no key rather than
guess (`sms_not_idempotent`).

## 2. Worker dies before the remote commit

**What happens.** `activity_started` is in the log. No effect row.

**What we do.** Resume calls the tool again under the same key. Only that step re-executes.
Completed steps stay completed. `refund_crash_after_intent`: in-flight re-run 1, completed
re-run 0.

## 3. Two workers, one stale

**What happens.** Worker A committed the debit, then lost the lease. Worker B claimed and
incremented the epoch. A still tries to append the completion.

**What we do.** The append checks `lease_epoch` and raises `StaleLease`. A does not retry
the side effect. B heals from the key. `test_stale_epoch_cannot_complete_a_second_debit`.

**Residual risk.** Clock skew longer than the lease TTL can delay pickup. It should not
allow two live writers, because the epoch moves on every successful claim. A clock that
jumps backward could make a lease look unexpired. Production should use a monotonic lease
service, not a laptop clock. The demo clock is injectable for that reason.

## 4. The model changes its mind on resume

**What happens.** A sampled model, asked again, picks a new recipient or a new amount.

**What we do.** The completion is logged before the call. Resume replays it. Money and the
recipient are not taken from the model in the first place; the engine binds them. A test
installs a model that throws if the email step is re-decided.

**Residual risk.** A tool that calls a model internally, outside `llm_decision`, bypasses
this. The rule is that tools are deterministic given their arguments. The mock is the only
model in the default path.

## 5. Email fails after the debit

**What happens.** The customer was charged and not told, or the send returned a permanent
error before the message left.

**What we do.** The email failure is permanent, so there is no retry. The ledger activity
declares `ledger.reverse`. The saga posts one credit under a compensate key and ends
`compensated`. `refund_email_compensate`. A crash during that credit heals instead of
crediting twice. `compensate_crash`.

**Residual risk.** If the mailer actually delivered and then we also reversed, the customer
got the email and the money back. The tool treats the injected failure as "did not commit".
A real mailer that cannot tell "accepted" from "maybe" needs its own idempotency key, which
is the same protocol. If the reverse tool fails, the run is `compensation_failed` and a
person has to look. We do not loop compensations of compensations.

## 6. Approval

**What happens.** The amount is over $25, or a high-risk tool has no approval on the run.

**What we do.** The run parks in `paused_approval` and releases progress. No side effect
from a later activity has run. Denial with a clean run is `denied` and an empty effect
set. `refund_denied`. The baseline does not wait, posts the debit, and fails the case.

**Residual risk.** There is no approval timeout in this version. A paused run waits until
someone decides or the operator deletes it. A timeout that auto-denies is a small addition
on the same state; it is not built, because an expired approval should not be a surprise
debit. Rubber-stamping is a human problem. The approval payload shows the amount and the
rule, not a raw model transcript.

## 7. Budget overrun

**What happens.** The next attempt would pass `max_steps` or `max_cost_usd`.

**What we do.** Park in `paused_budget` before that attempt. Side effects that have not
started do not start. `refund_step_budget` stops after the lookup. `refund_cost_budget`
stops before the quote. Raising the budget resumes. Compensations ignore the cap.

**Residual risk.** Cost is the declared price list, not a meter on a provider invoice.
A tool that spends money the declaration does not mention will not trip the cap. The
declaration has to be honest. Retries do count as steps, so a flapping tool cannot spin
for free.

## 8. Timeout and transient errors

**What happens.** The tool reports a timeout or a transient error before it commits.

**What we do.** Schedule `backoff_ms * 2^(attempt-1)` and park in `waiting_retry`. The
suite's email retry honors 50 ms and then sends once. A timeout that happens after the
effect committed is treated as success and healed like a crash, not retried.

**Residual risk.** The offline tools report elapsed time; they do not actually sleep.
A real HTTP client needs a deadline around the call so a stuck socket cannot hold the
lease forever. The lease TTL is the backstop today: a stuck worker loses the lease and
the next worker reconciles.

## 9. Poisoned tool proposal

**What happens.** The specialist proposes a personal webhook for bank details, with a
rationale that says to ignore previous instructions.

**What we do.** The guard blocks `R-TOOL-URL-NOT-ALLOWLISTED`. The activity is `on_block:
skip`, so the rest of vendor onboarding continues. No webhook row is written.
`vendor_guard`. Personal email domains are blocked the same way, and if the debit already
happened the saga reverses it.

**Residual risk.** The offline guard is not Aegis. It does not tokenize payloads, decode
nested encodings, or taint the whole session after one injection. A novel exfiltration
channel that is not a blocked host or a freemail domain will pass this stub. Point
`ATLAS_GUARD=aegis` at the real gateway before this leaves a demo.

## 10. Knowledge miss

**What happens.** The question is not in the corpus ("executive bonus formula").

**What we do.** The Lumen port returns "Not found in the provided documents." The quote
step fails permanent. No debit. `lumen_refusal`. The HTTP adapter does the same when Lumen
is down, so a network blip does not become a made-up policy.

**Residual risk.** The offline router is keyword matching, not Lumen's retriever. It will
miss paraphrases Lumen would hit, and it will not apply Lumen's ACL. Use the HTTP adapter
against the real index when the corpus is the company's.

## 11. Duplicate submit

**What happens.** The same idempotency key is posted twice.

**What we do.** The second start returns the existing run and does not drive new side
effects. `duplicate_submit`. The baseline has no key and posts twice.

## 12. Checkpoint tampering or corruption

**What happens.** A checkpoint payload no longer hashes to the stored SHA-256.

**What we do.** Skip it and fold from the previous valid checkpoint, or from the start of
the log. The test tampers the newest checkpoint and checks the activities still match.

**Residual risk.** A checkpoint and the hash rewritten together would be trusted. The hash
is not a signature. An attacker who can write the database can rewrite history. The hash
catches torn writes and accidents, not a malicious DBA.

## 13. What this does not try to survive

* A remote API with no idempotency support, used anyway. The engine's answer is to refuse
  the tool. Bypassing that check reintroduces duplicates.
* Two workers executing different ready activities of the same run at once. The lease is
  per run. Parallel activities are scheduled one at a time.
* A model call hidden inside a tool.
* Region loss of both SQLite files. They are local files. Durability here means process
  crash, not disk loss. Backups are ordinary file backups; they must include both files,
  or a restore will heal against effects that no longer match the log.
