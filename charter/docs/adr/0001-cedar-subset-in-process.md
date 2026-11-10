# ADR 0001: A Cedar subset, evaluated in process

* Status: accepted
* Date: 2026-11-10

## Context

The control plane needs a policy an auditor can read and a program can execute, with the same result. Three familiar options:

1. Rego, by shelling out to OPA or embedding it.
2. Full Cedar, by shelling out to the Cedar CLI or embedding the Rust engine.
3. A small language with the same shape as Cedar's `permit` / `forbid` / `when`, implemented here.

OPA is the usual answer in infrastructure. It is a poor fit for this demo and a worse fit for the guarantee we want. A binary on `PATH` means `make test` fails on a clean laptop. An embedded engine means the answer depends on a version we did not vendor. Partial evaluation and negation-as-failure are hard to explain to someone who is not a policy author. If the text in the UI and the engine that decided can drift, the stamp is theater.

Full Cedar has entity hierarchies, `is`, and `in` on the entity graph. We do not have those graphs. Implementing them "a bit" would be a second product.

## Decision

Charter parses a subset:

* `permit` and `forbid`
* a head of `principal`, `action`, `resource`, each either open or `== Type::"id"`
* an optional `when` with `==`, `!=`, `in`, `&&`, `||`, and `!`
* strings, bools, and lists of strings
* `// @id` and `// @controls` on the lines above the statement

The parser and the evaluator live in `charter/policy/`. No other process is started. A file that uses syntax outside the subset does not load. A path the evaluator does not know, when that path is actually read, denies the request with `R-POLICY-ERROR`.

## Consequences

Good:

* The policy file in the UI is the policy that ran.
* `make test` needs Python and nothing else.
* A reviewer can learn the whole language from one screen.

Bad:

* There is no principal group. "The EU support team" is not expressible. Every permit is about the model and the context, not the person, except where a head names one id.
* There is no arithmetic and no string prefix. Regions are exact strings. `eu-central-1` does not match `eu`.
* We will rewrite this if a real Cedar bundle shows up and the subset starts lying about it. Until then, the subset is the contract, and the name "Cedar-style" in the README means the shape, not a claim of compatibility with the Cedar validator.

## Alternatives

* OPA as a sidecar. Rejected. The decision has to run in the same process as the tests, with no daemon.
* YAML of if-statements. Rejected. It evaluates fine and it reads like a config dump. The permit/forbid shape is the thing worth showing, because forbid-overrides is the actual rule.
* Natural language plus an LLM. Rejected. See the cost line in the pack. The projection is there so the zero is a comparison, not a slogan.
