# Failure modes

Each one is something this system does wrong, or cannot see, and the mitigation that is actually in the tree. "We would add a model" is not a mitigation.

## The language cannot name a team

Principals are an id and a type. There is no group, no "manager of," and no attribute on the person beyond the id. Every shipped permit leaves `principal` open. A request from `acme/u-support` and a request from anyone else follow the same rules.

Mitigation: the open principal is visible in the policy file, and the cases say which principal they use so a reader can see it does not matter. Adding a group syntax without the tests that pin it would be a new language. ADR 0001 is the boundary.

What this does not fix: a real deployment needs "this service account" versus "this human." That is a head constraint we can already write (`principal == User::"..."`). We have not needed it for these cases. It is not a group.

## A typo on the un-evaluated side of `&&` is silent

`when` short-circuits. A forbid whose first comparison is false never reads the rest. A misspelled path on the right does not raise `R-POLICY-ERROR`, and the forbid does not match. On a request where the first comparison is true, the same typo denies the whole call. The failure mode is the quiet side.

Mitigation: the residency rule's interesting side is covered by `eu-support-us`, `restricted-us`, and `eu-confidential-faq-us`. A unit test sends a permit with `context.colour` and expects `R-POLICY-ERROR`, which is the path that does get evaluated.

What this does not fix: short-circuit is still short-circuit. Evaluating every path always would make `&&` a different operator than the one the file looks like. We kept the ordinary operator and covered the clauses the demo depends on.

## The chain proves the file, not the gateway

`verify_chain` recomputes the HMAC with the published demo key. A flipped outcome fails the test. A log that was invented, hashed with that key, and committed verifies perfectly. EU-12 is met on this fixture because the chain matches, not because Aegis was running.

Mitigation: the pack and the README call it a stub. The generator is in the repo, and the test compares bytes, so the story cannot drift from the code that builds it. The key is the literal in `charter/config.py`, documented as not a secret.

What this does not fix: production has to verify with Aegis's key, which Charter does not have. Pointing this demo key at a real log would succeed only for logs we forged. That is the failure mode to say out loud if someone asks whether EU-12 is "done."

## Residency is the string on the card

`R-RESIDENCY-EU` compares `resource.region` to `eu-central-1`. The region comes from the model card. A card that says `eu-central-1` while the process runs in `us-east-1` is an allow. Charter does not open a socket.

Mitigation: the card is data, reviewed as a file. `frontier-us-large` says `us-east-1` in the registry the decision reads. The failure mode is a lie in the registry, which GOVERN 6.1 only partially covers (the provider review flag), not a traceroute.

What this does not fix: network policy. That belongs next to the gateway, not in this evaluator.

## `INTERNAL` may leave the EU

The residency forbid lists `CONFIDENTIAL` and `RESTRICTED` only. `internal-eu-on-us` is an allow, on purpose, and it is locked so a "fix" that starts blocking internal text has to edit the case in the same commit.

Mitigation: the case note says it is a written choice. Aegis labels names and emails as confidential, so the common support ticket is not this row. A ticket that is only `INTERNAL` can use the US model.

What this does not fix: a team that uses `INTERNAL` for things they would not say in the US. The label has to mean what the policy thinks it means. Charter does not re-classify the text. Aegis does that, and the stub already carries the label Aegis would have written.

## Denying the call does not retire the model

`claims-triage-eu` is `status: active`, `risk_tier: high`, `human_oversight: false`. `R-OVERSIGHT` denies invocation. EU-14 is still a gap. The treatment text says to un-activate the model or assign a reviewer. The policy is the backstop, not the staffing.

Mitigation: the matrix function looks at active cards, not at whether a permit exists. A test asserts the gap names `claims-triage-eu`.

What this does not fix: nothing in `make eval` edits the registry. The gap stays until a person changes the card. That is the correct direction.

## The gate only knows 15 cases

A new permit that allows a shape we did not list will pass `make gate`. The weakened bundle is one specific deletion, not an analysis of every possible edit.

Mitigation: the cases include the allow that should stay an allow, the deny that must stay a deny, the override, the default deny, the unknown model, and the action that is not `invoke`. `make eval` fails if removing the residency file suddenly satisfies every expectation. New production misses get a case in the same change as the rule. That is the treatment on EU-9.

What this does not fix: a bug that is not in the file. The operating rule is the same as Forge and Lens. The suite is a lock, not a proof.

## Record-keeping looks healthy while the route was wrong

EU-12 is met. EU-10 is a gap. Both read the same log. A reader who stops at "chain verified" misses the leak. The leak is a successful write. The chain is doing its job by preserving it.

Mitigation: the desk leads with the gap, not with the chain. The because-line on EU-10 names `req-leak-01`, the route, and the region. The evidence section says redaction of the card is not residency.

What this does not fix: a dashboard that someone later builds to show only the met count. The counts are three numbers on purpose. Do not replace them with one.

## At 10× the log, the desk is the wrong place to re-hash

Verify walks every event. Thirty-eight events is nothing. Ten times a real quarter is not something to do on each page view.

Mitigation: the API serves the summary (counts, violations, head hash), not the raw JSONL. The architecture note says to verify on ingest and cache the head. The evaluator does not read the log at all. A decision does not get slower because the quarter got longer.

What this does not fix: this repository still verifies on each `make eval` and on each UI startup. That is the right cost at this size. It is the wrong cost at 10×, and the split is already drawn so the change is where the summary is cached, not what a forbid means.
