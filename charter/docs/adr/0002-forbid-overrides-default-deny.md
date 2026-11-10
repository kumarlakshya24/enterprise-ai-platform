# ADR 0002: Forbid overrides permit, and silence is deny

* Status: accepted
* Date: 2026-11-10

## Context

Two statements can match one request. The hosted support permit is written wide on purpose: customer support, including confidential and restricted classes, on `frontier-us-large`. The residency forbid is the exception. If we evaluated "first match wins," the order of files would be the policy, and a reviewer would have to know that order.

The other edge is a request that matches nothing. An allow-by-default control plane ships every new model the day it is added to the registry.

## Decision

Evaluation order:

1. Unknown model id → deny `R-MODEL-UNKNOWN`, before any permit.
2. Incomplete context → deny `R-POLICY-ERROR`.
3. A `when` path that is missing, when it is evaluated → deny `R-POLICY-ERROR` for the whole request.
4. If any forbid matches → deny. The primary id is the highest severity, then the id. Severity does not change the effect.
5. Else if any permit matches → allow. The primary id is the first permit in file order.
6. Else → deny `R-DEFAULT-DENY`.

`002-residency.cedar` exists so that deleting one file is a coherent change. The wide permit stays. The forbid goes. `eu-support-us` flips from deny to allow. `make gate-weakened` exits 1.

The gate compares effect and the required rule ids. A case that stays deny but loses `R-RESIDENCY-EU` still fails. Effect alone would miss that.

## Consequences

Good:

* A new model with a finished card is not invocable until a permit names it, or a permit names the shape it has.
* Adding a permit cannot quietly legalize a forbidden shape. The forbid still matches.
* The UI can show both lists: permits that matched, forbids that won.

Bad:

* A forbid with a typo in a clause that short-circuits away does not fire, and does not raise `R-POLICY-ERROR`. `&&` does not evaluate the right side when the left is false. A typo on the right of a residency check that only runs for EU data will not be seen on a US request. The locked cases cover the EU path. They do not cover every short-circuit.
* Default deny is easy to mistake for a specific rule. The UI says so when there is no excerpt. `export_weights` is denied because no permit names that action, not because a forbid discusses exports.
* Severity is a second hidden order. It only chooses the stamp. The full forbid list is on the decision. If we start treating primary id as the only id that "counts," this ADR is being violated.

## Alternatives

* First match wins. Rejected. File order would be load-bearing and the weakened demo would depend on which file we deleted versus which we reordered.
* Deny only when a forbid matches, otherwise allow. Rejected. That is how a model with no permit becomes reachable.
* Most-specific permit wins, Cedar's actual satisfied-permit rules, without a default deny. Rejected for the same reason, and because "most specific" needs the hierarchy ADR 0001 refused to implement.
