# ADR 0002: A heuristic judge, with kappa as the admission test

* Status: accepted
* Date: 2026-11-05

## Context

Someone has to say whether an output is faithful, relevant, safe, and right to refuse. Three options:

1. An LLM judge as the source of truth.
2. A heuristic, and a claim that it is "good enough" with no measurement.
3. A heuristic measured against a hand-labeled set, with an LLM judge available as a second rater that has
   to clear the same bar.

An LLM judge is not ground truth. It has its own bias, it costs money, and it will drift when the provider
updates the model. A heuristic with no measurement will be trusted past the point where it is wrong.
The failures we already know about are exactly the ones a keyword check misses: paraphrase and negation.

## Decision

`make eval` runs the heuristic in `lens/judge/heuristic.py`. The gold set in `lens/evalset/cases.py` is
labeled to the rubric in `docs/JUDGE_RUBRIC.md`, including three items the heuristic gets wrong:

* `lum-paraphrase-loaner` — "two weeks" against "14 days".
* `lum-negation-password` — the chunk says do not share the password; the answer says you should.
* `lum-world-knowledge` — "which sends phone alerts" is not in the chunk, and there is no new number.

Cohen's kappa on the pass bit has to be at least 0.60 or the gate fails, including the clean candidate.
A test also fails if kappa reaches 0.95, so deleting the gaps to inflate the number does not pass CI.

The provider judge in `lens/judge/llm.py` builds the same rubric into a prompt and parses a JSON verdict.
It raises if the key, URL, or model is missing. It is not called by `make eval`. If it is ever used to
move the locked baseline, it has to clear the same kappa floor on this set. That comparison is the point
of the floor: you do not swap raters without re-measuring.

## Consequences

Good:

* The offline path is deterministic and costs $0.
* The README table is agreement, not a vibe. The three misses are listed beside the kappa.
* A future LLM judge has a bar that is already in the gate.

Bad:

* The absolute quality numbers are the heuristic's opinion. Where it disagrees with the label, the gate
  is scoring the wrong way on that item, on both sides, so the delta is still fair. The level is not.
  Do not quote the pass rate as "84% of answers are good" without the kappa next to it.
* The refusal check looks for one sentence, `Not found in the provided documents.` A paraphrased refusal
  is scored as not a refusal. The gold set uses that sentence on purpose.

Rejected:

* LLM-as-judge as the definition of correct. Unmeasured, and not available offline.
* Hiding the three gaps so the table looks cleaner. The upper bound in the test exists to prevent that.
