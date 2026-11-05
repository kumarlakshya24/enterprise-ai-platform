# Atlas architecture review

This is the script for a design review, not a feature demo. `make interview` prints it.
Put [`ARCHITECTURE.md`](../ARCHITECTURE.md) on the second screen: system diagram first, then
the decisions table, then the SLO table. The UI is evidence for one row of that table.

## 1. Thirty seconds

Atlas is the durability layer under a set of agents. The failure I designed for is a worker
that dies after a ledger API has committed and before the workflow history says so. The
design is two commits that are not one transaction, an event log you can fold, and an
idempotency key so resume heals instead of replaying the plan. Guardrails are an Aegis-shaped
port. Policy text is a Lumen-shaped port. The model in this repo is a deterministic mock
because the review is about the runtime. A sampled model plugs in behind the same event.

## 2. The problem, and who reviews it

The audience is the platform team that already has agents calling tools that move money or
wake people. They do not need another agent. They need one place that answers three
questions the agents keep answering differently: did this side effect already happen, are we
still inside the budget, and how do we undo the steps that did happen when a later one fails.

I would open the review by stating the non-goal. This is not a claim that the mock plans
better than a frontier model. The catalog is the allowlist. The suite locks invariants of
the engine.

## 3. Whiteboard

Draw the system diagram and stop. Two stores. The engine in the middle. The model, the
guard, and the knowledge tool as ports. Aegis and Lumen outside the process.

Then the decisions table, six rows, and do not skip the "what it costs" column:

1. **Durable store.** Log and effects commit separately. Rejected a mutable status row, and
   rejected one transaction around the remote call. Cost: two files, one writer on SQLite.
2. **Replay.** Fold the log from a hashed checkpoint. The model decision is an event written
   before the side effect. Rejected re-prompting on resume. Cost: the fold is deterministic,
   and a bad first decision sticks.
3. **Idempotency.** Heal if the key exists. Refuse tools that cannot take a key. Rejected
   at-most-once and rejected blind retry. Cost: the remote system must honor the key.
4. **Compensation.** A saga, each reverse keyed the same way. Rejected two-phase commit.
   Cost: `compensation_failed` is a terminal state a person has to see.
5. **Guardrail port.** Aegis's verdicts, fail closed. Rejected importing Aegis and rejected
   trusting the model. Cost: the offline stub is not the full gateway.
6. **Retrieval port.** Lumen's `POST /ask`, and a refusal fails the step. Rejected putting
   the policy in the prompt and rejected failing open. Cost: keywords until the real index
   is configured.

If they want one diagram after that, use the crash sequence: debit commits, `SIGKILL`,
lease blocks the second worker, heal, email once. The state machine is there to show that
a crash is not a status. It is an expired lease while an activity is `running`.

## 4. The decision I would spend the time on

Idempotency, because the other five hang off it.

At-most-once drops the refund when the process dies before the call. At-least-once with a
new call posts the debit twice. That second behavior is the baseline in the suite:
`refund_crash_after_remote` is two debits and four completed steps re-run. Atlas is one
debit, zero completed steps re-run, catch-up of 1 ms simulated plus whatever the lease TTL
is. The demo uses 0.4 seconds so you can watch it. The default is 30 seconds, and that is
the availability tradeoff I would say out loud.

The implementation detail that makes the test honest is that the effect commit and the
completion event are not the same transaction, and they are not the same file. A kill
between them is observable. One SQL transaction around "charge the card and mark done"
cannot include the card network.

The companion constraint is the replay model. If resume called the model again, the second
completion could change the payload, the key would conflict, and the heal would throw.
Recording `llm_decision` first is what makes the key stable. Money and the recipient are
not taken from the model anyway. The engine binds them from the quote and the request.
The model still chooses subjects and URLs, and those go through the guard. That is the
vendor case: the mock follows an injected instruction, the guard blocks
`R-TOOL-URL-NOT-ALLOWLISTED`, and provisioning still happens once.

I would rather refuse `sms.send` (`R-TOOL-NOT-IDEMPOTENT`) than describe two texts as
durable.

## 5. What I would show, and what it is evidence of

From `atlas/`:

```bash
make kill-resume
```

This is the evidence for the idempotency row, not a tour of the product. Narrate the
invariants, not the steps:

* Child exit code `-9`.
* Before resume: `post_ledger` is `running`, `ledger.post` is 1, emails are 0.
* A second worker is rejected while the lease is live. That is the fencing story. We do
  not steal a lease that might still belong to a live process.
* After the lease: status `completed`, ledger still 1, email 1, case close 1, healed true,
  completed steps re-run 0.

If the debit count is 2, the design is wrong.

The UI (`make up`, http://127.0.0.1:8096) is the same window with the approval gate in
front of it, which is a different row of the SLO table.

1. Customer refund, $40, `dana.holloway@example.com`, crash set to "Kill after the ledger
   debit commits".
2. Start. Paused. Say that the policy threshold is $25 and nothing has been charged. That
   is the approval budget: no high-risk effect before a decision.
3. Approve. Banner says the completion event was not written. Debits **1**, emails **0**.
4. Resume. Debits still **1**, emails **1**, cases **1**, the node says healed.
5. "Replay crash with a single agent" reports **2** debits. Same plan, no key.

If they ask about the saga: fault "Email fails after the debit", crash off, approve.
Status `compensated`, one debit, one credit. That is the compensation row. A kill during
the credit is `compensate_crash` in the suite: still one credit.

`make test` includes the SIGKILL test. The UI is not the only place this works.

## 6. Do the budgets hold?

Read the SLO table in ARCHITECTURE. I would only claim the rows the suite measures.

| Budget | Target | This run |
|---|---|---|
| Duplicate effects on crash cases | 0 | 0 / 4. Baseline 3 / 4 |
| Completed steps re-run | 0 | mean 0 vs 3.25 |
| Catch-up, simulated | heal, not a full replay | 12 ms vs 104 ms. Plus one lease TTL in the real process |
| Engine p95, small refund, no model | under 50 ms | measured p95 28.3 ms, p50 17.3 ms, SQLite setup included |
| Accounted cost | pause at $1.00 / 20 steps. This workflow class is about a cent | happy path $0.011. Suite mean $0.00750 vs baseline $0.01225 |
| Task invariants | the 16 cases | 16/16 vs 3/16 |

What I would not let a reviewer walk out believing:

* 16/16 is not a model-quality score. The mock is a pure function. I would call it "the
  runtime held these invariants."
* The baseline is missing the machinery under test on purpose. It is not a Temporal
  comparison. Temporal would also heal an activity with an idempotency key. I would say
  that before they do.
* Recovery milliseconds in the table are simulated from declared step latency so they do
  not move between laptops. The wall-clock p95 is measured and will move. The lease TTL
  dominates real recovery, and that is a chosen tradeoff, not an accident.
* Accounted dollars are the price list the enforcer sums. Actual model spend here is $0.
  The baseline costs more because it replays finished steps and because it does not stop
  on denial, budget, or refusal.

The one crash the baseline survives is `after_intent`, where nothing was committed. Both
end at one debit. Atlas still re-executes only the in-flight step. That is the distinction
I want in the notes.

## 7. What I would change before production, and what I would not

Walk [`FAILURE_MODES.md`](FAILURE_MODES.md) as a gap list, then the production mapping.

Already closed in this tree: the three crash windows, a stale fencing epoch, a crash
mid-credit, approval and denial, both budgets, backoff, the blocked webhook, a Lumen
refusal, duplicate submit, a tampered checkpoint.

The mapping I would propose, and the order:

| Now | Next |
|---|---|
| `atlas.db` | Postgres. Same tables. Keep the lease-epoch update. Restore the log and the effect records together |
| One `drive` loop | Temporal if the platform has it: history, activities, heartbeat. Otherwise a queue with the same epoch. I would not rewrite the heal rule |
| `effects.db` | The ledger's and the mailer's own idempotency tables |
| Mock LLM | The LLM gateway, which in this platform is Aegis. Record the completion before the activity either way |
| Guard stub | `ATLAS_GUARD=aegis`, fail closed. Leave tokenization and the audit chain in Aegis |
| Keyword corpus | `ATLAS_KNOWLEDGE=lumen`, `POST /ask`. Refusal still fails the step |
| Approval in-process | Same state, decision delivered on a queue. I would not add a timeout that becomes a debit |

I would not add a second workflow language, and I would not let the model emit tools.
Per-activity leases come before a real parallel fan-out. Today one lease covers the run
and the driver executes one ready activity at a time. That is a scaling limit I would
rather state than paper over.

## 8. Review questions

**Why is this not just Temporal?**
For a large platform I would use Temporal, and section 7 says so. Atlas is the smallest
engine that also has the agent-shaped ports: a guard, a knowledge tool, a dollar budget,
and a model decision stored as history. The crash rule is the same idea as an activity
heartbeat plus an idempotency key. I am not claiming a new consensus protocol.

**Why two databases?**
So the window in the sequence diagram exists. One transaction cannot include the card
network. In production the second database is theirs.

**What if they ignore the key?**
The tool is refused before the call. `sms.send` is the example in the suite.

**Who is allowed to set the amount?**
The quote tool, from the policy text, clamped. The engine copies that number. The model
can set a subject. It cannot set the dollars.

**What if nobody approves?**
The run stays `paused_approval`. Later side effects do not run. I have not built an
approval timeout. An expired approval that posts a debit is the wrong default. A timeout
that denies is a small follow-on, and I would say it is not done.

**Is 100% a quality number?**
No. Sixteen deterministic invariants. The baseline scores 3/16 on the same definitions.
The columns that matter are re-run counts and duplicate effects.

**Why simulate recovery time?**
The offline tools do not sleep. A 2 ms wall clock does not distinguish a healed ledger
call from replaying six steps. Declared `latency_ms` does. Wall clock of the engine is
next to it and labeled measured.

**Can status page and page-out run at once?**
The graph says yes. The driver says no. Fixing that is per-activity leases. I left it
serial so the crash proof stayed readable.

**Where is the tamper-evident audit log?**
In Aegis. Atlas's log is workflow history. Guard decisions should be shipped to Aegis's
chain when the HTTP guard is on. I would not build a second chain here and do it worse.

**Why a saga and not 2PC?**
We do not operate the ledger and the mailer. Compensations are explicit, keyed, and
allowed to end in `compensation_failed`.

**How does a real model plug in?**
`LLM.complete`. The engine already stores the completion. The new risk is a bad first
decision and the latency of the gateway, not a different second decision. The catalog
stays the allowlist.

## 9. Where Aegis and Lumen sit

Three boundaries, one platform.

Lumen answers from documents or refuses. Atlas calls it when a step needs a rule. A
refusal fails the quote. That is the retrieval row. Atlas does not grow its own index.

Aegis decides whether a tool call may run. Atlas sends the bound arguments, including the
URL a specialist was talked into. That is the guardrail row. Atlas does not grow its own
tokenizer or its own audit hash chain.

Atlas decides whether the call already happened, whether another step fits the budget, and
how to undo the ones that did. Putting the three in one process would make a wider demo
and a single outage. The ports are the architecture. The stubs are how the review runs
offline.
