# Demo script

The UI is `make run-local`, then http://127.0.0.1:8092. `make demo` asserts the same outcomes
without a browser.

## Before you start

Say this once: every model on the page is an in-process mock. The millisecond number in the
decision is the router's wall clock. The 42 / 210 / 680 / 250 figures are the catalog, and the
router does not sleep them.

## 1. Same prompt, four policies

Click the first chip if it is not already selected. Click **Compare four policies**.

Say: one question, four contracts. Default keeps a 0.10 headroom, so Fast Cheap is legal on the
floor and still loses to Balanced. Cost-saver drops the headroom and buys the cheapest legal
model. Latency-first has a 100 ms catalog SLO, so Balanced is not even eligible, and the winner
happens to be the same cheap model for a different reason. Quality-first buys Premium. The
savings line under Premium is 0%. That is the point of the column.

## 2. Hard math

Click **Hard math**. Click **Route**.

Say: the floor moved. Balanced's math capability is 0.72 and the required number is higher, so
the only eligible peer is Premium. Spend equals the always-premium counterfactual.

## 3. The SLO that rejects

Click **Hard math under a 100 ms SLO**. Click **Route**.

Say: Premium can do the proof and misses 100 ms. Fast Cheap makes 100 ms and misses the floor.
The outcome is rejected, spend is zero, and nothing was called. I would rather show a refusal
than a late flagship.

## 4. Confidential stays local

Click **Confidential note**. Click **Route**.

Say: the word confidential and the address together floor the sensitivity at confidential.
Rule `R-SENSITIVE-LOCAL` pins local and stops fallback. An email on its own, with no
confidential marker, is only internal and still goes to a hosted model. That case is in the
eval corpus, not on a button.

## 5. Fallback, then no spill

Click **Fast Cheap times out**. Click **Route**. Point at the attempt list: timeout on
Fast Cheap, billed as input tokens, then Balanced accepted. Outcome is fallback.

Click **Local failure does not spill**. Outcome is failed, and the only non-skipped attempt
is local.

## 6. Stats

The bottom strip is `/v1/stats`. Dry-runs are excluded. **Reset stats** clears the SQLite file
the process opened.

## Terminal

`make demo` prints ten lines, PASS or FAIL, and a spend total. `make eval` reprints the corpus
report. `make interview` prints the talk track in `INTERVIEW_WALKTHROUGH.md`.
