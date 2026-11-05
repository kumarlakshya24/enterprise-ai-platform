[Aegis](../../README.md) › [Docs](../README.md) › **Decision records**

# Architecture decision records

Each record follows the usual ADR format: **context**, the **options**, the **decision**, and its
**consequences**, including what was rejected and why.

| ADR | Decision | Instead of | Main reason |
|---|---|---|---|
| [0001](0001-gateway-proxy-not-client-side-filtering.md) | Enforce DLP in a **gateway proxy** | Client-side filtering, provider-side controls | One policy and one audit trail for every client, and the gateway sees agent tool calls too |
| [0002](0002-placeholder-tokenization-not-deletion.md) | **Reversible placeholders** (`[EMAIL_1]`) in an encrypted vault | Deleting or masking values | The model can still reason about "the same customer", and the answer is restored for the user |
| [0003](0003-private-classifier-for-label-and-route.md) | A **private local classifier** labels context and drives routing | Keyword lists alone, a local LLM judge, or the provider's moderation endpoint | Catches sensitive text with no PII pattern in 0.05 ms, is measured on a blind holdout, and sends nothing out. Keyword markers remain as a floor. |
| [0004](0004-deterministic-tool-guard-with-taint.md) | A **deterministic tool guard** with session taint | Asking the model to resist injection | Security cannot depend on the model behaving. The demo model obeys the injection and is still stopped. |
| [0005](0005-tamper-evident-redacted-audit-log.md) | An **append-only, HMAC hash-chained, redacted** audit log | Ordinary application logs | Legal evidence that cannot be edited quietly and does not become a second copy of the data |

All five are **accepted**. The measured consequences, such as the throughput limit the audit chain
puts on writes, are in [cost and scaling](../cost-and-scaling.md) and
[tradeoffs and limitations](../tradeoffs-and-limitations.md).
