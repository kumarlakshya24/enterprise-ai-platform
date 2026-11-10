# Interview walkthrough

`make interview` prints this file. Numbers are from `make eval` on the committed stubs (p95 11.8 µs over 2,000 rounds, 38 audit events, matrix 10 / 4 / 3). If you re-run eval and a latency figure moves, the ceiling in the test is 2 ms and the README is the place to update the measured number in the same commit. Nothing here is a live measurement of Aegis or Lens.

## 1. Thirty-second pitch

Aegis stops a prompt. Lens tells you the quality SLO moved. Charter is the control plane behind both: which model may run, on which class of data, in which region, and which article that maps to. Policies are a Cedar subset, forbid overrides permit, and silence is deny. The evidence pack is computed from an Aegis-shaped audit stub and a Lens-shaped SLO snapshot. It is offline, it has no API key, and it is not a certificate. The interesting result is a deny, and three gaps we did not hide.

## 2. Who it is for

The person who has to answer an auditor, or who has to review a policy change before it is the bundle Aegis would pin. Not the employee in the support queue. They should not wait on Charter. Charter is off the request path on purpose.

The concrete job: someone wants `frontier-us-large` to draft a reply to an EU customer ticket. The permit for hosted support would allow it. You want a deterministic no, with the rule id, and you want CI to fail if a later change deletes that no. Separately, you want the pack to still show last quarter's bad route, because blocking the next call does not rewrite the log.

## 3. Architecture tour

Stay on the diagrams in [ARCHITECTURE.md](../ARCHITECTURE.md). Five beats.

1. **Control plane, not data plane.** Policies, cards, and the matrix are the things a human edits. The evaluator does not call a model. A provider outage cannot change a stamp, because there is no provider.
2. **Decisions at a glance.** Subset, not OPA. Forbid wins. Stubs, not imports. The matrix is a mapping. Those four are the ADRs.
3. **Happy path, then the failure.** EU ticket on `atlas-eu-mini` allows. The same ticket on `frontier-us-large` denies, and the permit is on the decision so you can see what lost. Delete `002-residency.cedar` and that case allows. The gate exits 1.
4. **The log and the SLOs are inputs, not the decider.** EU-12 can be met while EU-10 is a gap. The chain preserved the leak. Quality paging makes Art. 15 a gap even though latency is fine. Do not blend them.
5. **Trust boundaries.** The person talks to a local UI. Policy files parse or refuse. Cards contribute scalars. Stubs are checked. No prompt leaves the process.

## 4. Deep dive: the wide permit under the forbid

The hard decision is ADR 0002, and the file that makes it obvious is `003-permits.cedar`.

`R-PERMIT-HOSTED-SUPPORT` matches customer support on the US model for public, internal, confidential, and restricted classes. That looks careless. It is the point. If the only way to deny the EU ticket is "no permit," then deleting a forbid would not be visible, because the request would still default-deny. I wanted a deletion that changes the effect. The forbid is the control. The permit is the thing the control is holding down.

What the weakened bundle actually does, from the eval output:

* `eu-support-us` flips to allow, primary rule `R-PERMIT-HOSTED-SUPPORT`.
* `restricted-us` stays deny, because `R-RESTRICTED-BLOCK` is in another file, but it loses `R-RESIDENCY-EU`, so the gate still fails.
* `eu-confidential-faq-us` stays deny as `R-DEFAULT-DENY`, and the gate fails because the residency id is gone.

Checking only the effect would have missed two of the three. That is why the case file has `includes`.

What I rejected:

* First match wins. Then the order of files is the policy, and I can break residency by sorting.
* Allow by default. Then a new card is live.
* Asking a model whether the call was compliant. It will not fail the same way twice, and the pack already prices a review at $0.054 so the comparison is on the page. Charter's number is $0 because it did not call one.

## 5. Demo script

From `charter/`:

```bash
make test
make eval
make gate
make gate-weakened ; echo "exit $?"
```

What you should see:

* `make test` green. Parser, forbid-overrides, the chain, the tamper, the 10/4/3 counts, the API flip.
* `make eval` prints `10 met, 4 partial, 3 gap`, shipped gate pass, residency file removed blocked.
* `make gate` exits 0.
* `make gate-weakened` exits 1. Three mismatched cases, named.

Then the UI:

```bash
make up
# http://127.0.0.1:8097
```

Desk first. The gap banner is `req-leak-01`. Open Decisions on `eu-support-us` and read the deny stamp. Toggle "Drop residency file" and read the allow. The matrix filter "Gaps" is the three rows. The evidence pack repeats the finding and says it is not a certification.

`make interview` prints this file. It does not start a server.

## 6. What the numbers prove, and what they do not

Prove:

* On the shipped bundle, the 15 locked cases match effect and rule ids. On the bundle without `002-residency.cedar`, three of them do not, and one of those changes from deny to allow.
* The matrix functions, given this registry and these stubs, return 10 met, 4 partial, 3 gap. The gap sentences name `req-leak-01`, `claims-triage-eu`, and the quality SLI.
* The audit file's HMAC chain matches the generator, and one edited outcome breaks it. There is exactly one residency violation, and it is the request we planted.
* A decision of the residency case is about 12 µs at p95 on this machine (measured 11.8 µs, 2,000 rounds). The test fails if that reaches 2 ms. That number is CPU, not a service.
* Provider cost of `make eval` is $0. The $0.054 next to it is `eval/pricing.yaml`, marked as a projection.

Do not prove:

* That the company is 10/17ths of the way to complying with the EU AI Act. The catalog is 17 controls we chose to implement. Absent articles are not met.
* That Aegis leaked a real card number on 3 November. The log is synthetic, hashed with a demo key, and the README says so.
* That Lens's production quality is 0.91. Those are the snapshot's numbers, using Lens's targets and Lens's status words.
* That 12 µs is the time to produce an auditor's answer. It is the time to evaluate one request against ten statements.
* That `INTERNAL` leaving the EU is safe. It is allowed by the file. The case exists so that choice stays visible.

## 7. Failure modes, and what production would add

Say these out loud. They are written up in [FAILURE_MODES.md](FAILURE_MODES.md).

* No principal groups. A named principal is possible. A team is not, until the language grows and the tests grow with it.
* The HMAC proves this file was not edited after sealing. It does not prove Aegis wrote it.
* The region is a string on the card. A lie in the registry is an allow.
* `R-OVERSIGHT` stops the call and leaves EU-14 red, because the model is still active. Closing the gap is a registry edit, not a quieter policy.
* The gate is 15 cases. A bypass we did not write down will ship. The rule is: the miss becomes a case.
* At 10× the log, verify on ingest and keep the summary. Do not re-hash the quarter inside the page render. The evaluator does not read the log, so the decision latency does not care.

Production, in the order I would actually do it: a signed bundle Aegis pins, the real HMAC key out of a secret store, an exporter that fills `data_residency` and `region` on `routing_decision`, and identity on the UI. Not a bigger language, and not an LLM reviewer.

## 8. Questions, with the short answer

**Why not OPA?**
Because I want the file in the UI to be the file that ran, and I want `make test` to need nothing but Python. Rego is the right tool when the policy team already lives in it. This portfolio would have been a thin wrapper around a binary. ADR 0001.

**Why is the hosted permit so wide?**
So the forbid has something to override. If I only default-denied, deleting the residency file would not change the effect, and the demo of "this change is dangerous" would be a lie. ADR 0002.

**Isn't a green EU-12 dishonest if there was a leak?**
No. The log worked. It kept the bad route. EU-10 is the leak. Mixing them into one score is how the leak gets a passing average. ADR 0004.

**Why is Art. 15 a gap when safety is only a ticket?**
Because the quality objective is paging, and I treated accuracy as not met when the quality SLO is paging. Safety being a ticket is MEASURE 2.6, which is partial. They are different rows so a latency-green week cannot cancel a quality-red week.

**Does Charter call Aegis?**
No. The stub uses Aegis's event types, routes, labels, and HMAC construction. Charter does not import it. The join fields (region, model, residency) are what an exporter would add. ADR 0003.

**What would you add after this?**
The signed bundle and the exporter. The language is large enough to show the decision. Growing it before something consumes the bundle is how you get a second unused policy engine.
