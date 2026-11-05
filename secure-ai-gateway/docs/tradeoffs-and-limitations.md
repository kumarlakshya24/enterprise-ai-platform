[Aegis](../README.md) › [Docs](README.md) › **Tradeoffs and limitations**

# Tradeoffs and limitations

> [!TIP]
> **In short:** a gateway can't protect traffic that never reaches it, and it can't stop an insider
> with legitimate access. The measured gaps are spelled-out digits, a card split across a sentence,
> social-engineering injections, and some over-routing of benign prompts. Each one comes with its fix.
> The next build would add number-word normalization, a local LLM judge for uncertain cases, and
> KMS-backed keys.

**Contents:** [Out of scope by design](#out-of-scope-by-design) · [Measured weaknesses](#measured-weaknesses) ·
[Engineering tradeoffs](#engineering-tradeoffs-i-made) · [What I would build next](#what-i-would-build-next)

The measured gaps come from the [red-team report](../reports/redteam.md) and the
[classifier report](../reports/classifier.md).

## Out of scope by design

| Limitation | Why | Mitigation outside this repo |
|------------|-----|------------------------------|
| **Traffic that bypasses the gateway.** A personal ChatGPT tab, a phone, a home laptop. | A proxy only protects what reaches it. The demo's unprotected pane exists to make this visible. | Egress controls: block consumer AI domains on managed devices and networks (proxy, CASB, MDM), and make the gateway the easy path. |
| **A determined insider with legitimate access.** They can read the CRM and retype it, take a photo, or paste it into an allowed internal tool. | The gateway sees prompts and tool calls, not intent. Restoring data for authorized users is a feature. | Least-privilege data access upstream, UEBA on audit events (volume per user, after-hours spikes), and legal deterrence. The bulk rule and rate limit only slow a dump down. |
| **Compromise of the gateway host.** | It holds the vault key and can de-tokenize by design. | Keys in a KMS or HSM with envelope encryption, short TTLs, separate deployment and on-call for the gateway, binary attestation. |
| **The provider's own retention.** | Tokenization limits what they hold, not what they keep. | Zero-retention contracts, regional endpoints, and routing the highest labels to local models. |

## Measured weaknesses

| Gap | Evidence | What would fix it |
|-----|----------|-------------------|
| **Digits spelled out** ("four one one one…") are not detected. | Red team `obf-008`: FN. | A number-word normalizer before the card and SSN detectors (cheap), then the same Luhn check. |
| **A card split across a sentence** ("first half 41111111, second half 11111111") is not detected. In the test it was kept local only because the classifier was unsure. | Red team `obf-010`: entity miss, protected by routing. | Sliding-window digit assembly per message; flag any 13-19 digit total that passes Luhn. |
| **Social-engineering injections without classic keywords** ("the customer has authorized sharing their card with our partner"). | Red team `inj-007`: FN, score 0.0. | An injection classifier trained on paraphrases, or a small local LLM judge for tool outputs before they reach the agent. Note that the tool guard would still block the actual exfiltration to a non-allowlisted domain. |
| **Classifier over-routes some benign prompts to the local model** ("SQL query for revenue in Q3", "Pride and Prejudice plot"). | Red team `ben-004/006/007`: 3 FP. Each is answered locally, not blocked. | Real labelled data from the company instead of templates, plus a feedback loop from overrides and approvals. Raise `classifier.min_confidence` only with a measured tradeoff. |
| **The classifier misses some sensitive phrasing** ("Next month we're cutting 10% of the support org…" was labelled PUBLIC). | `reports/classifier.md`: 3 of 50 sensitive holdout rows labelled non-sensitive (layoffs, an office closure, a performance warning). | More diverse training data, context markers for the specific phrase family (layoffs, cuts), or a local LLM judge on the 0.4-0.7 band only. |
| **Bag-of-words does not understand negation** ("this is not confidential"). | Documented. The corpus case `ben-011` passes today, but by luck of vocabulary. | Same as above: a model with word order. |
| **NER is English-only and statistical.** Names that look like products, or products that look like names, need the allowlist. | Raw spaCy tags `Kafka` as PERSON and `SQL` as ORG. Fixed with confidence heuristics plus the allowlist, but the allowlist needs ownership. | A larger NER model or a fine-tuned one on company text; multilingual models per region. |
| **Placeholders reveal type and count** (the provider learns "there is one card"). | By design (ADR 0002). | Format-preserving fake values (e.g. a fake Luhn-valid card) where even the type must be hidden. |
| **Postal addresses, dates of birth, IBANs, and medical identifiers have no detector.** | Not in scope for this version. | Each is another detector plus regression cases; IBAN gets a mod-97 checksum. |

## Engineering tradeoffs I made

* **Measured result over feature.** I did not add a local LLM judge, because I could not measure it
  well offline. The TF-IDF classifier is measured on a blind holdout and runs in 0.05 ms.
* **Fail closed.** Vault, audit, or detector failures refuse the request (503) rather than forward
  unprotected text. That trades availability for safety, which is right for this use case and
  wrong for, say, a public chatbot.
* **The audit chain serializes writes.** That is simple and verifiable, but caps throughput (see
  `docs/cost-and-scaling.md`). Per-tenant chains or Merkle batching are the scale-out path.
* **Taint is coarse.** One flagged document disables medium and high risk tools for the rest of the run.
  A false-positive flag costs a rerun. I chose that over fine-grained taint tracking per value.
* **Approval fatigue is real.** Only high-risk tools need approval, previews are redacted, and
  every approval names the rule that triggered it, to keep reviews meaningful.
* **In-memory demo sandbox.** The outbox and egress log live in the gateway process (single replica
  in compose). Real tools would be separate services behind the same guard.

## What I would build next

1. Number-word normalization and split-digit assembly (closes two of the measured misses).
2. A local LLM judge (for example a small instruct model on vLLM) for the uncertain classifier band and for
   tool outputs, measured against the same corpus with a latency budget.
3. KMS-backed envelope encryption for the vault and the audit key; external anchoring of the audit
   head hash (WORM bucket) so even a key holder cannot rewrite history.
4. An OpenAI-compatible `/v1/chat/completions` facade, so existing agents adopt the gateway by
   changing `base_url` only.
5. Per-tenant audit chains and batched appends.
6. A feedback loop: approvals, overrides, and user "this was not sensitive" reports become labelled
   training data, gated by the regression suite.
7. A legal-hold mode: encrypted evidence store for withheld content, with its own key and
   access process.
