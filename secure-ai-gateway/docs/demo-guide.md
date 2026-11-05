[Aegis](../README.md) › [Docs](README.md) › **Demo guide**

# Demo guide

> [!TIP]
> **In short:** run `make up`, open http://localhost:8080, and for each scenario click **Run both paths**.
> The left pane is what leaks without a gateway. The right pane is the same input through Aegis.
> The whole tour takes about 8 minutes.

**Contents:** [Before you start](#before-you-start) · [1. Direct paste](#1-direct-paste-leak) ·
[2. Context leak](#2-pattern-only-dlp-is-not-enough) · [3. Tool exfiltration](#3-tool-exfiltration) ·
[4. Prompt injection](#4-prompt-injection) · [5. Legitimate work](#5-legitimate-work-still-flows) ·
[6. Policy gate](#6-rules-cannot-be-weakened-silently) · [7. Audit and identity](#7-audit-and-identity) ·
[Terminal version](#terminal-version)

---

## Before you start

```bash
make up      # build and start the stack (first run builds the image)
make demo    # optional: 20 automated checks, all should print PASS
```

Open http://localhost:8080. The header shows who you are signed in as, and you can switch users from
the drop-down. The "third party" is a mock OpenAI that logs every request it receives. When a pane says
*third party received*, that text was read back from the mock provider's log.

> [!NOTE]
> Click **Clear demo evidence** between scenarios so each pane shows only the current run.

| Switch to | When |
|---|---|
| Avery Quill (support agent) | Default. Runs the scenarios and sees cards masked |
| Taylor Brook (billing specialist) | Optional in scenario 1: sees the full card |
| Morgan Vale (approver) | Scenario 3: approves the email |
| Sam Ryder (security admin) | Scenarios 6 and 7: policy console and audit |
| Personal Account (password login) | Scenario 7: rejected, because sign-in is SSO only |

---

## 1. Direct paste leak

**Do:** Chat tab → *Scenario 1: Direct paste leak* → **Run both paths**.

| Pane | What you should see |
|---|---|
| Left (unprotected) | The provider received Dana's name, email, and full card number. |
| Right: badges | `ok` · `redact_and_continue` · `context INTERNAL` · `rule R-ROUTE-INTERNAL` · `policy r1-…` |
| Right: *sent to the model* | `[PERSON_NAME_1]`, `[CREDIT_CARD_1]`, `[EMAIL_1]`, plus a note that the provider's log shows exactly this |
| Right: *answer shown to you* | "Dear Dana Holloway…" with the card shown as `•••• 1111` |
| Right: *entities* | Each value with its detector, confidence, and action. The card is a Luhn-valid Visa at 0.99. |
| Right: *audit entries* | Four events: prompt, redaction, routing, and model call |

**Why it matters:** the provider never learns who the customer is, but the user still gets a usable
reply. Restore follows the user's role: switch to Taylor (billing) and run it again, and the full card
appears.

---

## 2. Pattern-only DLP is not enough

**Do:** *Scenario 2: Context leak with no pattern* → **Run both paths**.

| Pane | What you should see |
|---|---|
| Left | The provider received the confidential planning note. |
| Right | 0 entities found. The reasons list says *regex-only DLP would have: allow*. The classifier says CONFIDENTIAL at 0.89 (top words: *unannounced, sales, planning*). Route `local_only`, and *third party received nothing*. |

**Why it matters:** the most damaging leaks often contain no pattern at all. The private classifier
runs inside the gateway, so labelling the text never sends it anywhere.

<details>
<summary>Optional: make the policy stricter</summary>

As Sam, open the Policy console and set the CONFIDENTIAL route to `block`, then click **Apply**. It is
accepted because it is stricter. Run scenario 2 again as Avery and it is now `blocked`. Set the route
back to `local_only` afterwards, or click **Restore default policy**.

</details>

<details>
<summary>Show me</summary>
<br>
<img src="media/scenario-2-context-leak.gif" alt="Scenario 2 walkthrough" width="100%">
</details>

---

## 3. Tool exfiltration

**Do:** Agent tab → *Scenario 3: Tool exfiltration to personal Gmail* → **Run both paths**.

| Pane | What you should see |
|---|---|
| Left | The agent looked up the customer and emailed the full record, card included, to a Gmail address. |
| Right | `lookup_customer` → `allow`, then `send_email` → `block` with `R-TOOL-PERSONAL-DOMAIN`. |

The model only saw `[EMAIL_1]` as the recipient. The guard resolves the placeholder through the vault to
check the real domain, so tokenization does not blind the guard.

**Then the approval flow:**

1. Pick *Same task, corporate address, human approval* → **Run both paths**. The result is
   `pending_approval` (`R-TOOL-HIGH-RISK`).
2. Open the Approvals tab as Avery and click **Approve**. It fails with `403 four_eyes`, because nobody
   can approve their own request.
3. Switch to Morgan → Approvals → **Approve**. The outbox shows the email to `avery.quill@acme.example`
   with the card as `•••• 1111`.

**Why it matters:** obvious exfiltration is blocked outright, and legitimate but risky work keeps
moving with a second person in the loop. The approver sees a redacted preview, the approval expires
after 10 minutes, and the call is re-checked against the current policy when it runs.

<details>
<summary>Show me</summary>
<br>
<img src="media/scenario-3-tool-exfiltration.gif" alt="Scenario 3 walkthrough" width="100%">
</details>

---

## 4. Prompt injection

**Do:** Agent tab → *Scenario 4: Prompt injection exfiltration* → **Run both paths**.

| Pane | What you should see |
|---|---|
| Left | The wiki page hides an HTML comment telling the AI to append the customer's email and card to an image URL. The agent obeyed, and the egress log shows the data in a URL on `img-cdn.evil.example`. |
| Right | `read_wiki` flagged: *prompt injection detected (score 0.97): override_instructions, exfil_to_url, templated_url, hidden_html_comment, conceal_from_user · session tainted*. Then `render_image` is blocked by three independent rules. |

**Why it matters:** the mock model is deliberately gullible and follows the injection. The gateway
still stops it. Even if the detector had missed the injection, the URL allowlist and the data-in-URL
check would each block the call on their own.

<details>
<summary>Show me</summary>
<br>
<img src="media/scenario-4-prompt-injection.gif" alt="Scenario 4 walkthrough" width="100%">
</details>

---

## 5. Legitimate work still flows

**Do:** Chat tab → *Scenario 5* → **Run both paths**.

**See:** PUBLIC, `allow`, no redaction. The prompt reaches the model byte for byte, and the gateway adds
about 7 ms.

**Why it matters:** a security control that slows everyone down pushes people back to personal
accounts.

---

## 6. Rules cannot be weakened silently

**Do:** switch to Sam → Policy console → set *CREDIT_CARD action* to `allow` → add a note →
**Apply through regression gate**.

**See:** `REFUSED: 7 protected cases would regress`, with the cases listed. The old policy stays active
and the attempt is written to the audit log.

**Why it matters:** each policy write replays the 84-case red-team corpus for every tenant and user
override. The same gate runs in CI for code and detector changes.

<details>
<summary>Show me</summary>
<br>
<img src="media/policy-regression-gate.gif" alt="Policy regression gate walkthrough" width="100%">
</details>

---

## 7. Audit and identity

**Do:** as Sam, open the Audit tab → **Verify hash chain**.

**See:** *chain intact: N events*. Confidential prompts appear only as a keyed fingerprint and a length.

Then switch to *Personal Account [password login]*. The header shows
*rejected by gateway: 403 tenant_not_allowed*.

**Why it matters:** the log is append-only at the database level and chained with an HMAC key the
database never sees. A test runs every scenario and then scans the audit table, approvals, runs, and app
logs for every synthetic PII value.

<details>
<summary>Show me</summary>
<br>
<img src="media/audit-verify.gif" alt="Audit verification walkthrough" width="100%">
</details>

---

## Terminal version

```bash
make demo                                          # all scenarios, PASS / FAIL per check
python scripts/demo.py --base-url https://<host>   # the same checks against a hosted demo
```

To go deeper, see the [threat model](threat-model.md) for every attack and its test,
[tradeoffs and limitations](tradeoffs-and-limitations.md) for what this does not stop, and the
[latency report](../reports/latency.md) for per-stage timings.
