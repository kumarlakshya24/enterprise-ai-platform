[Aegis](../../README.md) › [Docs](../README.md) › [Decision records](README.md) › **ADR 0003**

# ADR 0003: A private local classifier labels context and drives routing

* Status: accepted
* Date: 2026-11-04

## Context

Pattern detection misses confidential context that has no pattern:

> Internal planning note: we will discontinue the Starter tier in Q3 and raise Enterprise
> prices 18%. The acquisition talks with our main competitor are still unannounced.

No name, no email, no card. Regex and NER find nothing, so a pattern-only DLP sends it to
the third party. We need a sensitivity label for the text itself, and that label must be
computed without sending the text anywhere.

Options:

1. Keyword lists only.
2. A small supervised classifier running in the gateway process.
3. A local LLM as a judge (Ollama, vLLM).
4. The external LLM's own moderation endpoint (sends the text out: disqualified).

## Decision

Use a TF-IDF (1-2 grams) plus multinomial logistic regression classifier trained on a
synthetic, labelled corpus, with four labels: PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED.

* Train with scikit-learn, then export vocabulary, IDF, and coefficients to JSON. The
  gateway runs inference in pure Python. No pickle is ever loaded, so a tampered model
  file cannot execute code. The artifact's SHA-256 is checked at startup.
* Classify the tokenized text, so the model never sees raw PII and its explanations never
  contain PII.
* Explain every label with the top weighted n-grams.
* A deterministic marker list sets a label floor ("attorney-client privileged" is always
  RESTRICTED). Markers are auditable and covered by the regression suite.
* Low-confidence predictions escalate to the more sensitive of the top two labels.
* Route by label through the policy: PUBLIC allow, INTERNAL redact and continue,
  CONFIDENTIAL local only, RESTRICTED block. Tenants and users can override.

## Consequences

Good:

* Sub-millisecond inference. No GPU. Deterministic and explainable.
* Catches context the regex layer cannot, and the gap is measured in the red-team report.

Bad:

* Trained on synthetic data, so it reflects my idea of what confidential looks like. A
  real deployment needs labelled samples from the company's own documents and a feedback
  loop from approvals and overrides.
* Bag-of-words models miss meaning carried by negation or subtle phrasing. The held-out
  test set and the red-team set report this honestly.
* An LLM judge would generalize better but costs 100 ms to seconds and GPU capacity. It is
  the planned upgrade for the uncertain band only (confidence between 0.4 and 0.7).
