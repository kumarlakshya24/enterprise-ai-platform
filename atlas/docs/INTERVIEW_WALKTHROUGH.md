# Atlas interview walkthrough

Read this aloud, or run `make interview`. The tone to aim for is specific and a little slow.
The diagrams live in [`ARCHITECTURE.md`](../ARCHITECTURE.md). The numbers live in
[`eval_results/latest/summary.json`](../eval_results/latest/summary.json).

## 1. 30-second pitch

Atlas is a durable runtime for multi-agent work. A planner and a few specialists refund a
customer, onboard a vendor, or open an incident. The engine underneath checkpoints every
step, replays an event log after a crash, and sends side effects through idempotency keys
so a worker killed after a ledger debit does not debit again. It also stops for approval,
enforces a step and cost budget, and runs a compensating action when a later step fails.
Tool calls go through an Aegis-shaped guard. Policy lookups go through a Lumen-shaped
knowledge tool. The demo is offline. The model is a deterministic mock, on purpose: the
thing being proved is the runtime, not a prompt.

## 2. Problem and who it is for

The user is a platform team that already has agents calling tools: refunds, provisioning,
paging. Those tools move money and wake people up. The failure mode that shows up in
production is not a wrong adjective. It is a process restart. The worker died after the
payment API returned 200 and before the workflow row flipped to done. The retry charges
the customer again.

Today that team either builds a one-off "did I already do this?" check in every agent, or
they hope the framework retries safely. Atlas is the shared place where that check lives,
next to the approval gate and the budget, so individual agents do not reinvent it.

It is not a chatbot product. The operators who would sit in the UI are the people who
approve a refund and the people who get paged when a compensation fails.

## 3. Architecture tour

Five stops, in the order I would draw them.

1. **Two databases.** `atlas.db` is the event log and the checkpoints. `effects.db` is the
   stand-in for the ledger, the mailer, and the pager. They commit separately. The gap
   between those commits is the bug. The system-context diagram in ARCHITECTURE is this
   picture, with Aegis and Lumen on ports at the edge.

2. **The log is the state.** The `runs` row is a projection. Resume folds the log, from the
   last checkpoint whose hash still matches. The state machine diagram is the set of
   statuses a run can be in: running, paused for approval, waiting out a backoff, paused
   on budget, compensating, and the terminal ones.

3. **The model proposes, the engine commits.** The mock LLM's completion is written as
   `llm_decision` before the tool runs. Money amounts are not taken from the model. The
   quote tool parses the policy text and clamps. The engine binds the debit amount and
   the email recipient. The model can still propose a URL, and that URL is what the guard
   sees.

4. **The guard and the knowledge tool are ports.** Offline, the guard uses Aegis's
   verdicts and `R-TOOL-` rule ids. The knowledge tool returns Lumen's `answer`,
   `citations`, and refusal sentence. HTTP adapters exist and fail closed. We do not
   import the other two trees.

5. **A lease and a fencing epoch.** A second worker cannot claim a run whose lease is
   still live. When it does claim, the epoch increments, and the dead worker's late
   completion write is rejected. That is how "the process might not actually be dead"
   is handled without a double debit.

The two sequence diagrams in ARCHITECTURE are the happy refund and the kill after the
debit. I would leave those on screen during the demo.

## 4. Deep dive: one hard decision

The decision is ADR 0002. Effectively-once side effects, by putting an idempotency key in
the remote system, and healing locally if the key is already there.

What I rejected:

* **At-most-once.** If we do not retry, a crash before the debit means the customer never
  gets the refund. That is a silent failure. Operators hate it more than a visible pause.
* **At-least-once with no key.** The retry always calls the tool. That is the baseline in
  the eval. On `refund_crash_after_remote` it posts two debits.
* **One database transaction around "call the API and write done".** You cannot hold a
  SQL transaction open across a payment API. Pretending you can is how people build demos
  that pass tests and fail in production. The two files are there so the window is real.
  `SIGKILL` lands in it.

The tradeoff I would say out loud: this only works if the remote system honors the key.
If it does not, the engine refuses the tool. `sms.send` is the example. I would rather
fail that run than send two texts and call it durable.

The companion decision is that the model decision is logged before the call (ADR 0001 and
0004). Otherwise resume re-prompts, the model picks a new recipient, and the key does not
even match. Durability and determinism are the same problem here.

## 5. Demo script

From `atlas/`, with the venv activated.

### Terminal, the proof

```bash
make kill-resume
```

Say this while it runs. A child process starts the $40 refund for Dana Holloway, auto-approves
as Morgan so the crash is the subject, posts the debit to `effects.db`, and is killed with
signal 9 before the completion event. The parent prints:

* child exit code `-9`
* `post_ledger` still `running`, healed false
* `ledger.post` rows: 1, emails: 0
* a second worker is blocked because the lease is still live
* after the lease expires (under a second in the demo, 30 seconds by default): status
  `completed`, ledger still 1, email 1, case close 1, `healed` true, completed steps
  re-run 0

If the debit count is 2, the demo failed. It should not be.

### UI, the same window plus the human gate

```bash
make up
# http://127.0.0.1:8095
```

1. Leave the workflow on Customer refund, amount 40, email `dana.holloway@example.com`.
2. Set crash injection to "Kill after the ledger debit commits".
3. Start. The graph shows lookup and quote done, and the run paused. Say: nothing has
   been charged yet. The policy says amounts over $25 wait.
4. Approve. The banner says the worker stopped after a committed side effect. Ledger
   debits read **1**. Emails read **0**. `post_ledger` is not done.
5. Resume. Debits still **1**. Emails **1**. Cases closed **1**. The node says healed.
6. Click "Replay crash with a single agent". The note under the button reports **2**
   ledger debits. That is the same plan with no effect key.

Optional, if they ask about rollback: set injected fault to "Email fails after the debit",
clear the crash injection, start, approve. Status becomes compensated. Debits 1, credits 1.
Net zero. That is the saga.

`make demo` prints the happy path without the kill, if the UI is not up.
`make test` includes the SIGKILL test, so this is not a script that only works by hand.

## 6. Metrics

Suite `atlas-workflows-v1`, 16 cases, both engines, generated by `make eval`.

| | Atlas | Single-agent baseline |
|---|---:|---:|
| Task success | 16/16 | 3/16 |
| Mean completed steps re-run after a crash | 0 | 3.25 |
| Mean recovery time, simulated ms | 65.75 | 166.25 |
| Mean catch-up time, simulated ms | 12 | 103.75 |
| Mean accounted cost | $0.00750 | $0.01225 |

What this proves:

* On the four crash cases, Atlas never re-runs a step that had already completed. The
  baseline re-runs 3.25 of them on average, and on three of the four it duplicates a side
  effect. The one crash the baseline survives is `after_intent`, where nothing had been
  committed yet, so replaying the plan happens to post once. Atlas still only re-executes
  the in-flight step.
* The happy path and the $10 refund (no approval) pass on both. The gap is not "the
  baseline cannot finish a refund". The gap is everything that is not the happy path:
  denial, budgets, compensation, the blocked webhook, the Lumen refusal, the duplicate
  submit, the non-idempotent SMS.
* Recovery time is simulated from declared step latencies so it is stable. Healing is 1 ms
  plus the steps that had not run yet. The baseline pays the whole plan again. Catch-up
  time stops when the crashed step is resolved: 12 ms mean for Atlas, 104 ms for the
  baseline, on this suite.
* Accounted cost is lower for Atlas mostly because crashed baseline runs pay for the plan
  twice, and because several Atlas runs stop early (budget, denial, refusal) while the
  baseline keeps going. It is a price list, not an invoice. Actual model spend here is $0.

What this does not prove:

* It does not prove a frontier model will pick the right plan. The mock is a pure function,
  and the catalog is the allowlist. I would not quote 100% as a quality number in a design
  review. I would quote it as "the runtime held these 16 invariants".
* The wall-clock p50 and p95 in the Results section are engine overhead for a small refund,
  including opening SQLite. They are not model latency. They are measured, and they move a
  little between machines. The simulated recovery numbers do not.
* Sixteen cases written next to the engine are a regression suite. They are not a blind
  benchmark. The baseline is intentionally missing the machinery under test. That is the
  comparison I want. It is not a comparison against Temporal.

## 7. Failure modes and production

I would walk [`FAILURE_MODES.md`](FAILURE_MODES.md) in this order.

The ones the code already closes: the three crash windows, the stale epoch, compensation
including a crash mid-credit, approval and denial, both budgets, backoff, the blocked
webhook, Lumen refusal, duplicate submit, a tampered checkpoint.

The ones I would do before this held real money:

* Point the guard at Aegis for real. The stub does not tokenize and does not taint a session.
  The HTTP client is written. Aegis needs a small evaluate endpoint that returns the verdict
  it already computes in-process.
* Point knowledge at Lumen when the corpus is not three policies. The offline router is
  keywords. The adapter already speaks `/ask`.
* Move both SQLite files to Postgres. The SQL is isolated in `store.py`. The fencing
  `UPDATE ... WHERE lease_epoch` is the statement to keep.
* Give each parallel activity its own lease before running waves on more than one worker.
  Today the driver is deliberately one activity at a time.
* Put a deadline on the real HTTP call, not only on the tool's elapsed-time report.
* Back up both files together. Restoring one without the other heals against the wrong
  effects, or forgets effects that happened.

I would not add a second workflow language, and I would not let the model emit arbitrary
Python. The catalog is the product boundary.

## 8. Questions I would expect

**Why not Temporal?**
Temporal already does durable execution well. I would use it for a large platform. Atlas is
a small engine I can read end to end, with the agent-shaped pieces Temporal does not have:
a guard port, a knowledge port, a budget in dollars, and a mock model whose decisions are
events. The crash protocol is the same idea as an activity heartbeat and an idempotency key.
I am not claiming a new consensus algorithm.

**Why two databases?**
So the window is real. One transaction around "charge the card and mark done" cannot include
the card network. Two commits make the kill test honest. In production the second database
is the ledger's own idempotency table. Ours is the stand-in.

**What if the provider ignores the key?**
The run is refused before the call, `R-TOOL-NOT-IDEMPOTENT`. I would rather fail the SMS
workflow than send it twice and describe that as at-least-once.

**How do you stop the model changing the amount?**
The quote tool parses the policy and clamps. The engine copies that amount into the debit.
The model can write the email subject. It cannot set the dollars. The recipient comes from
the request, and the guard checks the domain.

**What happens if Morgan never approves?**
The run stays `paused_approval`. No later side effect runs. There is no auto-approve on a
timeout, on purpose. An expired approval that becomes a debit is a worse default. I would
add an explicit timeout that denies, and I have not yet.

**Is the 100% a model score?**
No. Same question I would ask a candidate. It is 16 deterministic invariants. The baseline
scores 3/16 on the same definitions. The interesting columns are the re-run counts and the
duplicate effects, not the headline rate.

**Why is recovery time simulated?**
Because the offline tools do not sleep, and a wall-clock of 2 ms does not teach anything
about a 45 ms ledger call versus replaying six steps. The simulation uses the latencies
declared on the activities, and the heal path substitutes 1 ms. Wall clock of the engine
is reported next to it and labeled measured.

**Can two workers run the status page and the page-out at once?**
The graph allows it. The driver will not. One lease per run, one activity at a time, ordered.
That is a scaling limit I would fix with per-activity leases before I ran a large fan-out.
Doing it now would complicate the crash proof without changing the result on this suite.

**Where is the audit log?**
Aegis has the hash-chained audit log. Atlas's event log is the workflow history. I would
ship the guard decisions to Aegis's log when the HTTP guard is on, not build a second chain
here. Duplicating that design badly is worse than calling it.

**What did the saga reject?**
Two-phase commit. We do not operate the ledger and the mailer. Compensations are explicit,
keyed, and allowed to fail into `compensation_failed`. A silent retry of a reverse is the
same class of bug as a silent retry of a debit.

**How would a real model plug in?**
Implement `LLM.complete`. The engine already stores the completion and replays it. The new
risk is latency and a bad first decision, not a different second decision. I would keep the
catalog allowlist. I would not let the model add tools.

## 9. How this sits with Aegis and Lumen

The three projects are one platform story.

Lumen is where an answer comes from. It cites a policy or it says the documents do not
contain it. Atlas calls that when a step needs a rule: refund cap, vendor onboarding,
SEV1. If Lumen refuses, Atlas does not invent a refund. That is `lumen_refusal`.

Aegis is where a tool call is judged. The model is not trusted with a side effect. Atlas
asks the guard with the bound arguments, including the URL the vendor specialist was
talked into. The block is `R-TOOL-URL-NOT-ALLOWLISTED`. Aegis, in its own repo, already
does the harder version of this: tokenization, taint, allowlists, four-eyes approval.
Atlas does not reimplement that. It treats Aegis as the enforcement point and keeps the
durability, the budget, and the saga.

The split I would defend: Aegis decides whether a call is allowed. Lumen decides what the
policy text is. Atlas decides whether the call already happened, whether we can afford
another step, and how to undo the ones that did. Putting all three in one process would
make a bigger demo and a worse outage.
