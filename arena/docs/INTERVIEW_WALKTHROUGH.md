# Interview walkthrough

Spoken track for Arena. `make interview` prints this file. The diagrams it points at are in
`ARCHITECTURE.md`. Numbers are from `reports/latest.json` as of corpus hash `eb0792f71fc6`
and policy `2026.11.10`. If you re-run `make eval` and a figure moves, read the report, not this
paragraph from memory. Overhead will move. Quality will not, unless the corpus or the rules changed.

## 1. Problem (about 30 seconds)

Say: a team that fine-tunes on the runbook gets a confident answer from March after the policy
moved in April, and they still cannot tell you whether the training program was cheaper than
retrieval. A team that only prompts refuses every internal question. I wanted one labeled set,
four arms, and a memo that says when the fine-tune loses.

## 2. What I built (about 30 seconds)

Say: Arena is an offline bench. Same Harborline support questions for a prompt arm, a RAG arm,
a LoRA-style adapter stub, and a distilled student. No API key. The quality table is exact-phrase
support on a frozen labeled set. Dollars and model latency are a price card, labeled as
projections. The in-process overhead is measured and kept in its own column. The demo writes a
one-page memo from the saved JSON.

## 3. Architecture (about two minutes)

Open `ARCHITECTURE.md`. Point at the system diagram, then the arm diagram, then the decision flowchart.

Say: the prompt only sees the four public sections. RAG is BM25 over the snapshot you point it
at, and it cites the section. The adapter is not a GPU job. It stores the freeze text of facts
that appear in the train split, and it answers when two content words match. The student is that
memory with the long procedures and the one-off facts removed. Holdout labels are not read.

Then: the scenario picks the world. Stable scores the freeze index. Weekly throws out both tune
arms even if I patch their score to 1.0, because the weights do not move. The quality floor is
0.80. Citations, when required, need 0.80 as well, which only RAG can clear.

The bench for retrieval, including BM25 and excluding model time, is p95 0.070 ms, n=500.
RAG's catalog latency is 216 ms. I do not add those into one fake p95.

## 4. Demo (about two minutes)

Follow `docs/demo-script.md`. The beats:

1. Weekly, citations on. The banner says do not fine-tune. RAG is 25/25 on the current set and cites. The adapter is 19/25 and answers the old refund window.
2. The refund question. Prompt refuses. RAG says 30 days and cites billing-refunds. The adapter and the student say 14 days, marked stale.
3. High volume, corpus declared stable, citations off. The adapter wins on cost: $1,720 against $5,820. It is 19/20, RAG is 20/20. Quality did not justify the freeze. Volume did.
4. Common short answers, 80 ms SLO. The student at 42 ms is the only arm left. It is 15/16 on that slice and 15/20 on the full set, and the memo prints both.
5. Two thousand requests a month. The adapter program is $401 against RAG at $5.82. Retrieval wins.

If the UI is down, `make demo` prints 16 PASS lines.

## 5. Metrics (about a minute)

Say the limits before the fractions.

* The labeled set is 61 questions: 36 train, 16 holdout, 5 staleness, 4 unanswerable. Train is not in the decision slice.
* Current world, full slice, 25 questions. RAG 25/25 with citation rate 1.0. Adapter 19/25, and 3 of 3 amended policies come back as the old sentence. Student 15/25. Prompt 8/25, which is the public holdout plus the four refusals it should make.
* Frozen holdout: RAG 16/16, adapter 15/16. The miss is a goodwill-credit question rewritten as "courtesy money." RAG still finds "50 USD". The adapter has no shared content word and refuses. Margin is −0.0625. The rule to freeze for quality alone is +0.03. Quality does not justify it.
* Student on the full frozen set is 15/20, under the floor, because the bridge, the cutover, VAT, and the sandbox reset were dropped. On the common short slice it is 15/16, which clears.
* Money, projections: at 50,000 requests a week-changing desk, RAG is $185.50 a month. At 2,000,000 stable requests the adapter is $1,720 against RAG at $5,820. At 2,000 requests the adapter is $401.32 against RAG at $5.82.
* Overhead: RAG p95 0.070 ms measured, n=500. Catalog p95 is the price card, not that number.

## 6. Failure modes (about 45 seconds)

Say three, not the whole table.

* The weekly rule and the floor can both be right and the adapter still dies. That is the point. A perfect score on a frozen exam does not update a changed runbook.
* Stale is not a hallucination. "14 days" used to be the policy. The grade says `stale` so the memo does not call yesterday's truth a lie.
* If Lumen or Switchboard disagree or are down, the probe says so and the table stays on the stub. I will not copy a live refusal into the saved score.

## 7. Tradeoff you should volunteer (about 30 seconds)

Say: the adapter wins the high-volume row while being a worse exam than RAG, 19/20 against 20/20. I left that in. A bench that only recommends the most accurate arm never has to talk about cost, and cost is the reason people fine-tune. The other half of the tradeoff is the stub. A real LoRA might pass the courtesy-credit rewording. It would not grow citations, and it would not notice that the refund window moved, unless someone paid to train again.

## 8. What I would do next

A real tokenizer, a paraphrase-aware grader that is itself evaluated against this phrase scorer, and a Switchboard catalog id for an adapter endpoint so the premium mapping can retire. I would not put a GPU job in CI until the decision rules are the thing under test and the training run is a separate, seeded artifact.
