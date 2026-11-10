# ADR 0004: The control matrix is a mapping, not a certificate

* Status: accepted
* Date: 2026-11-10

## Context

The pack names EU AI Act articles and NIST AI RMF subcategories. That sentence is easy to over-read. A green cell next to "Art. 12" looks like a conformity assessment. It is not. Nobody in this repository is a notified body, and the inputs are synthetic.

The other failure is a single score. "76% compliant" would average a prohibited-practice control with a font choice, if we let it. We do not have a font choice. We do have a planted leak, and an average would soften it.

## Decision

Each catalog id has one function in `charter/mapping/matrix.py`. The function returns `met`, `partial`, or `gap`, plus a sentence that cites a model id, a rule id, or a request id. The YAML holds the title, a short paraphrase, and the treatment. It does not hold the status. Status in YAML would be a claim with no test.

A catalog id with no function is `unmapped`. `make eval` exits 1 if any control is unmapped. You cannot go green by adding a row and forgetting the code.

The shipped fixture is expected to show 10 met, 4 partial, 3 gap. The three gaps are locked by tests:

* EU-10, because `req-leak-01` left the EU
* EU-14, because `claims-triage-eu` is active high-risk with `human_oversight: false`
* EU-15, because the Lens quality status is `page`

The evidence markdown starts with "not a legal opinion and not a certification." The UI footer repeats it.

Statements in the catalog are paraphrases in our words. They are not quotations of the regulation or of NIST.

## Consequences

Good:

* A reviewer can disagree with a function. The disagreement is a code review, not a vibe.
* The demo is allowed to be red. Hiding the leak to make the README prettier fails the test.
* Treatments are mandatory text. An empty treatment does not load.

Bad:

* The functions encode judgment. "Quality paging means Art. 15 is a gap" is a choice. A team could argue it is partial because safety is only on a ticket. We wrote the stricter one down so it is not a surprise. Changing it is a commit that changes the test.
* Coverage is the catalog we wrote, not the regulation. Articles we did not list are not "met." They are absent. The README says 17 controls, not "the Act."
* A determined author can still write a function that returns `met` for everything. Review has to read the functions. The locked counts make a quiet rewrite of the story fail CI, which is the mitigation we actually have.

## Alternatives

* A percentage in the badge and nothing else. Rejected.
* Letting the model write the status from the article text. Rejected. It would not be stable, and it would read like the certificate this ADR exists to refuse.
* Only showing gaps, hiding the met rows. Rejected. The met rows are the evidence that logging, cards, and the prohibited-tier rule are doing something. A page of only bad news is not a pack.
