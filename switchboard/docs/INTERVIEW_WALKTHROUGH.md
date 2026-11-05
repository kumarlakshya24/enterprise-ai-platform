# Interview walkthrough

Spoken track for Switchboard. `make interview` prints this file. The diagrams it points at are in
`ARCHITECTURE.md`. Numbers are from `reports/eval.md` and `reports/latency.md` as of corpus
`2026.11.05`. If you re-run `make eval` or `make bench` and a figure moves, read the report, not this
paragraph from memory.

## 1. Problem (about 30 seconds)

Say: if every prompt goes to one flagship, you pay flagship prices for "what is a load balancer?"
If every prompt goes to the small model, a proof and a 100 millisecond budget both get the wrong
answer. The choice is usually hidden in a client. I wanted it in one place, with a version, a
reason, and a bill I can compare to always using Premium.

## 2. What I built (about 30 seconds)

Say: Switchboard is an offline router. Four mock models in-process: Fast Cheap, Balanced, Premium,
and Local. No API key. A request is classified, constrained by a YAML policy, scored, called, and
if that call times out or fails a quality gate, the next legal model is tried. Sensitive text is
pinned to local and does not spill. The demo UI runs the same prompt under four policies.

## 3. Architecture (about two minutes)

Open `ARCHITECTURE.md`. Point at the system diagram, then the decision flowchart.

Say: classification is rules. Task comes from a leading verb, then keywords, then chat.
Complexity is length plus a capped list of hard phrases. Sensitivity floors up: an email is
internal, a Luhn-valid card or the word confidential is confidential, an SSN-shaped number is
restricted. I did not put a model on this path. The bench for the whole route, including the
SQLite append and excluding model time, is p50 0.057 milliseconds and p95 0.079 milliseconds,
n=400. That number is not the model. Premium's catalog base is 680 milliseconds, and I do not
add those into one fake p95.

Then: constraints are a ceiling. Budget and SLO from the request can only get tighter. Headroom
on the default policy is 0.10. A model that barely clears the floor is dropped when a safer one
is still eligible. If nobody clears the headroom, I relax it and write that down, which is how a
$0.0001 budget still gets Fast Cheap instead of a rejection.

Selection is a named mode, not a hope that the weights do the right thing. Weighted, cheapest,
fastest, highest capability. The weights are still computed so the trace can say what the blend
would have done.

## 4. Demo (about two minutes)

Follow `docs/demo-script.md`. The four beats:

1. Compare. Default is Balanced, cost-saver and latency-first are Fast Cheap for different reasons, quality-first is Premium.
2. Hard math. Only Premium. Savings 0%.
3. Same math, 100 millisecond SLO. Rejected. No call.
4. Confidential note. Local. Then the no-spill button: local errors, and Premium is not tried.

If the UI is down, `make demo` prints 10 PASS lines.

## 5. Metrics (about a minute)

Say the limits before the percentages.

* Gold labels: 36 of 36. Those labels are the policy spec, checked in so a refactor cannot drift. They are not a claim that I beat a human rater I never had.
* Money: on 28 answered non-fault cases, catalog spend is $0.02421 against $0.06914 always-premium, 64.98% saved. Default policy alone, 16 cases, 61.74%. Do not quote latency-first's 99% saving. Three of its six cases are refusals.
* Oracle: cheapest legal model, same eligibility code, different selection. Agreement is 100% on default, cost-saver, and latency-first. Quality-first is 50%, two cases, because it pays for Premium on purpose.
* A task-map heuristic gets 89.3% of the non-rejected gold labels. The router picks up headroom, the tight budget, and hard math under cost-saver.
* Faults: 5 of 5. Timeout falls forward, low quality falls forward, Premium timeout on a hard proof escapes to a degraded local under default, quality-first does not escape, a pinned local error does not spill.
* Overhead: p95 0.079 milliseconds measured. Catalog latency p95 on that mix is 682 milliseconds estimated.

## 6. Failure modes (about 45 seconds)

Say three, not the whole table.

* The SLO and the floor can both be right and the request still dies. That is `rejected`, and it is better than a late flagship.
* Fallback bills the failed attempt. A timeout bills input tokens. A bad completion bills the full generation, because the tokens existed.
* Sensitive means one model. If local is down, the request fails. I will not "save" it by sending the note to Premium.

## 7. Tradeoff you should volunteer (about 30 seconds)

Say: default headroom sends a short "refactor for production" to Premium, because Balanced only clears the floor by 0.08. Cost-saver keeps that prompt on Balanced. I left the expensive behavior in default so the trace has something to explain. The classifier will also call a vague prompt "chat" when my lists miss it. That is the cost of not putting a judge model on the hot path.

## 8. What I would do next

A real tokenizer, a real provider behind the same attempt interface, and a learned task model only for the band the rules mark low-confidence. I would not put that model on every request until its own latency is inside the overhead budget I already measured.
