# Failure modes

What the bench does when the happy path does not happen. Each row is implemented and covered by the unit tests, the API tests, or a locked scenario in `arena/data/scenarios.yaml`.

| Failure | What Arena does | Why |
|---------|-----------------|-----|
| No arm clears the floor and the SLO | `winner: null`. The memo says to loosen a constraint. A 10 ms SLO on the common short slice is the test | The student at 42 ms is still late. A fine-tune is not an escape hatch. |
| Weekly change, even if the adapter's score is patched to 1.0 | The tune arms are eliminated. RAG remains | The weights do not move when the runbook does. `test_weekly_still_blocks_a_perfect_adapter` |
| Citations required | Tune arms drop out on a citation rate of 0. RAG stays if it cleared the quality floor | The adapter and the student do not cite. `cited-stable` |
| Two thousand requests a month | The adapter's projected month is $401.32 against RAG at $5.82. RAG wins on a stable corpus | The $2,400 program does not amortize. `low-volume` |
| Amended policy, current index | RAG returns the new sentence and the section. The adapter and the student return the freeze sentence, reason `stale` | The refund window is 30 days now and 14 days in the freeze. `st-refund-window` |
| Document added after the cutoff | RAG on the current index answers and cites. The freeze index, the adapter, and the student refuse | Webhook signing and the dunning schedule were not in the train set. |
| Question worded unlike the train set | RAG retrieves "50 USD". The adapter refuses | "Courtesy money" shares no content words with "goodwill credit". That is the holdout gap. |
| Question is not in the runbook | Every arm refuses. The refusal text contains no fact phrase | Tea, golf, the office cat, the lobby sofa. |
| One shared content word | Score at most 3, under the minimum of 4. No fact is emitted | Stops "severity one" and the SSO paragraph from stealing a nearby question. |
| Student meets a long procedure or a one-off fact | Refusal. The adapter still answers | Bridge, cutover, VAT reverse charge, sandbox reset. |
| Prompt asked an internal question | Refusal. The public product question still answers | The prompt index is the four public sections. |
| Monthly budget under every survivor | The arm is eliminated. If that empties the set, the winner is `none` | The budget is a ceiling. |
| Scenario field is not one of the known values | HTTP 422. The saved report is unchanged | `change_rate=daily` |
| Saved report missing | HTTP 404 on `/v1/report` and `/v1/decide`, with `run make eval` | The table is the file. The UI does not invent a score. |
| Corpus edited without `make eval` | `/healthz` sets `report_stale` when the hash differs | The page says the table is stale. Compare still runs the live arms. |
| Lumen URL set and the request fails | The probe returns `ok: false`. The eval stays on the local index | Fail closed. A dead retrieval service is not a reason to serve the adapter as if it had cited. |
| Switchboard picks a different model | The probe records expected vs chosen. The Arena winner is unchanged | The premium mapping is a stand-in. A disagreement is data. |
| Train split used as if it were the exam | It is not in `freeze_full` or `current_full` | The decision slices are holdout, staleness, and unanswerable. |

## What is not a failure mode here

* A real model's paraphrase. Exact-phrase support will mark a correct paraphrase as missing. ADR 0001.
* Lumen's ACL. The stub has one audience. A live refusal can be an access decision. ADR 0004.
* A provider outage, a 429, or a streaming cutoff. There is no provider on the eval path.
* Prompt injection. This bench does not try to detect it. Aegis does.
