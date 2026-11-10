# Demo script

UI: `make up`, then http://127.0.0.1:8097. The same beats are `make demo` if you are not in a browser.
The clip in the README is these frames, two seconds each.

## 1. Weekly, with citations

The page opens on **Weekly + cites**. 50,000 requests, change rate weekly, citations on, SLO 2,000 ms.

Say: the banner is "Do not fine-tune." RAG is 25/25 and cites. The adapter is 19/25, and the old-policy column is 3/3. Every "when not to fine-tune" row is blocking: citations, weekly change, the program cost at this volume, the quality margin, and the student's coverage.

## 2. One question, four answers

Open the question "After approval, what is the refund window?"

| Arm | What you should see |
|-----|---------------------|
| Prompt | Refusal |
| RAG | "30 days", citation `billing-refunds · Window` |
| LoRA stub | "14 days", chip `stale` |
| Student | "14 days", chip `stale` |

The grade grid under the cards is the saved report. The courtesy-money row is RAG `ok`, adapter `refused`.

## 3. High volume, corpus declared stable

Click **High volume**. Citations off, two million requests, stable.

Say: "Ship the adapter." It is $1,720 against RAG at $5,820. It is also 19/20 against RAG at 20/20. The quality-margin row still blocks a freeze that you would justify on accuracy alone. Volume is the reason, and the banner says that.

## 4. Narrow contract, tight SLO

Click **80 ms narrow**. Common short answers, 80 ms.

Say: "Ship the student." Prompt, RAG, and the adapter are over 80 ms on the price card. The student is 42 ms and 15/16 on this slice. The last row still says it is 15/20 on the full set. Shipping it means accepting that the bridge procedure is out of the contract.

## 5. Too little traffic

Click **Low volume**. Two thousand requests, stable, citations off.

Say: the adapter is accurate enough and still the wrong spend. $401 against $5.82. RAG is selected. The program cost is the whole story.

## 6. The memo

The paper memo is the same decision in one page. It names the slice, the four monthly figures, which "do not fine-tune" checks apply, and what would reverse it. It also says the adapter is not a neural trainer.

## Terminal

```bash
make demo     # 16 PASS lines
make eval     # rewrites reports/latest.json
make gate     # quality must match the committed file; wall clock is not compared
make interview
```
