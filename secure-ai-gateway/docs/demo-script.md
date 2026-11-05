# Demo script

About 8 minutes in total. The 60-second version is in the README. Before the interview, run `make up` and
`make demo` once so the image is built and every check is green. Open `http://localhost:8080`
and a terminal side by side.

Tip: click **Clear demo evidence** between scenarios so the "third party received" boxes only show
the current run.

---

## 0. Frame the problem (30 s)

**Say:** "Employees paste customer data into AI tools, and agents can leak data through tools or
get hijacked by content they read. I built a gateway that sits between people, agents, and
third-party models, and I'll show the same input going through an unprotected path and through
the gateway. The 'third party' is a mock OpenAI that logs everything it receives, so we can see
exactly what would have left the company."

**Show:** the header shows *Signed in as Avery Quill (support_agent)* and the permissions list
next to it.

---

## 1. Direct paste leak (90 s)

**Click:** Chat tab → *Scenario 1: Direct paste leak* → **Run both paths**.

**Point at the left pane:** "This is a personal ChatGPT tab. The provider received Dana's name,
email, and full card number, and even echoed the card back."

**Point at the right pane, top to bottom:**
* Badges: `ok`, `redact_and_continue`, `context INTERNAL`, `rule R-ROUTE-INTERNAL`, `policy r1-…`.
* *Sent to the model*: "The provider got `[PERSON_NAME_1]`, `[CREDIT_CARD_1]`, `[EMAIL_1]`, and the
  note '(third party log shows exactly this)' is read from the mock provider's own log, not from
  our side."
* *Answer shown to you*: "Restored for Avery: 'Dear Dana Holloway'. The card is masked to
  •••• 1111 because a support agent doesn't need the full number. A billing specialist would
  see it in full: that's RBAC on de-tokenization."
* *Entities* table: "Each one names the detector, confidence, and action. The card is a
  Luhn-valid Visa at 0.99. The name came from a cue detector plus spaCy."
* *Audit entries*: "Four events (prompt, redaction, routing, model call), each with a hash."

**Optional:** switch the user to *Taylor Brook (billing_specialist)* and run again: the full card
appears in the answer.

---

## 2. Pattern-only DLP is not enough (60 s)

**Click:** *Scenario 2: Context leak with no pattern* → **Run both paths**.

**Say:** "No name, email, or card. A regex DLP finds nothing, and the reasons list says so
explicitly: 'regex-only DLP would have: allow (0 entities, sent to the external LLM)'. Our private
classifier, which runs inside the gateway, labels it CONFIDENTIAL at 0.89 because of
*unannounced, sales, planning, enterprise, raise*. Policy routes CONFIDENTIAL to the local model."

**Show:** left pane = the provider got the roadmap. Right pane = *(third party received nothing)*,
`local_only`.

**Optional live policy toggle:** switch to *Sam Ryder (security_admin)* → Policy console → set
CONFIDENTIAL route to `block` → **Apply**. It is accepted because it is stricter. Back to Chat as
Avery and run scenario 2 again: it is now `blocked`. Reset the route to `local_only` afterwards.

---

## 3. Tool exfiltration (90 s)

**Click:** Agent tab → *Scenario 3: Tool exfiltration to personal Gmail* → **Run both paths**.

**Left pane:** "The unprotected agent looked up the customer and emailed the full record, card
included, to a Gmail address."

**Right pane:** steps show `lookup_customer` → `allow`, then `send_email` → `block` with
`R-TOOL-PERSONAL-DOMAIN: recipient domain gmail.com is a personal email provider`.
**Say:** "The model only ever saw `[EMAIL_1]` as the recipient. The guard resolves the placeholder
through the vault to check the real domain, so tokenization doesn't blind the guard."

**Click:** scenario *Same task, corporate address, human approval* → **Run both paths**.
Result: `pending_approval` with `R-TOOL-HIGH-RISK`.

**Click:** Approvals tab as Avery → **Approve**. The response is `403 four_eyes`. "You can't approve your
own request."

**Switch user** to *Morgan Vale (approver)* → Approvals → **Approve**. The outbox shows the email to
`avery.quill@acme.example` with Dana's name restored and the card as `•••• 1111`.
**Say:** "The approver saw a redacted preview, the approval expires in 10 minutes, and the call
is re-checked against the current policy at execution time."

---

## 4. Prompt injection (90 s)

**Click:** Agent tab → *Scenario 4: Prompt injection exfiltration* → **Run both paths**.

**Left pane:** "The wiki page hides an HTML comment telling the AI to append the customer's email
and card to an image URL. The unprotected agent obeyed: the egress log shows the data in the URL
on `img-cdn.evil.example`."

**Right pane:** `read_wiki` is flagged in red, "prompt injection detected (score 0.97): override_instructions,
exfil_to_url, templated_url, hidden_html_comment, conceal_from_user · session tainted". Then
`render_image` is blocked by three independent rules.
**Say:** "The mock model is deliberately gullible: it followed the injection. The point is that
security doesn't depend on the model resisting. Even if the injection detector missed it, the URL
allowlist and the data-in-URL check would still block. The run fails closed and nothing left."

---

## 5. Legitimate work (30 s)

**Click:** Chat tab → *Scenario 5* → **Run both paths**.
**Say:** "PUBLIC, allowed, no redaction. The prompt is byte-for-byte what the user typed, and the
gateway added about 7 milliseconds."

---

## 6. Rules can't be weakened silently (60 s)

**Switch user** to Sam → Policy console → set *CREDIT_CARD action* to `allow` → note "test" →
**Apply through regression gate**.

**Show:** `REFUSED: 7 protected cases would regress`, with the cases listed.
**Say:** "Every policy write replays 84 red-team cases for every tenant and user override. A change
that loses protection on a case we protect today is refused, the old policy stays active, and the
attempt is in the audit log. The same gate runs in CI for code and detector changes."

---

## 7. Audit and identity (45 s)

**Click:** Audit tab as Sam → **Verify hash chain** → "chain intact: N events".
**Say:** "Append-only at the database level, HMAC-chained with a key the database never sees. The
content of confidential prompts is withheld; only a keyed fingerprint is kept. A test runs every
scenario and then scans the audit table, approvals, runs, and app logs for every synthetic PII value."

**Switch user** to *Personal Account [password login]*: the header shows "rejected by gateway:
403 tenant_not_allowed". "SSO-only: wrong tenant or no SSO in `amr` means no access."

---

## Likely follow-ups, with where to point

* "What does this not solve?" → `docs/tradeoffs-and-limitations.md` (insiders, egress bypass,
  spelled-out digits, social-engineering injection).
* "How fast?" → `reports/latency.md`: p95 9 ms in-process, 21 ms with Postgres and Redis.
* "How good is the classifier?" → `reports/classifier.md`: blind holdout 86%, sensitive recall 94%,
  misses listed.
* "Cost?" → `docs/cost-and-scaling.md`.
