# ADR 0001: An adapter stub, not a GPU fine-tune

* Status: accepted
* Date: 2026-11-10

## Context

The question Arena answers is whether a team should prompt, retrieve, fine-tune, or distill for one domain task. A real LoRA run needs a GPU, a base model, and hours. None of that is available in CI, and a single training run would not make the decision reproducible: the next seed would move the score.

What the decision actually depends on is narrower. A fine-tune is frozen at a cutoff. It does not cite. It costs a program (review, repeats, an endpoint), not one GPU-hour. A student is smaller and forgets the long tail. Those properties can be implemented directly.

## Decision

The LoRA arm is a memory built only from the train split. Each train pair contributes the fact ids marked on the freeze corpus and the content words of the question. At answer time the arm emits the freeze text of the facts that clear a two-word score. It never reads a holdout label and it never cites.

The student is that same memory with two drops: facts that appear once, and facts marked long. Distillation here is a capacity limit, not a second network.

The README calls both of these stubs. The eval table is exact-phrase support on the labeled set, not a claim about a neural trainer.

## Consequences

Good: `make test` and `make eval` are deterministic on a laptop. The staleness result is a property of the artifact (the freeze text is what got stored), not a story written into the JSON.

Bad: a real model would paraphrase, so exact-phrase support is a lower bound on "the arm had the fact" and an upper bound on "the wording matched." A GPU fine-tune could also beat the keyword memory on the courtesy-credit rewording. That gap is the point of the holdout, and it is labeled as a stub.
