[Aegis](../../README.md) › [Docs](../README.md) › [Decision records](README.md) › **ADR 0002**

# ADR 0002: Reversible placeholder tokenization instead of deletion

* Status: accepted
* Date: 2026-11-04

## Context

Once DLP finds `Dana Holloway`, `dana.holloway@example.com`, and a card number in a
support complaint, we can:

1. **Delete** the values (`I am  and my card is `).
2. **Mask** them (`****`).
3. **Tokenize** them with typed placeholders (`[PERSON_NAME_1]`, `[EMAIL_1]`,
   `[CREDIT_CARD_1]`) and keep the mapping in a vault so the answer can be restored.

The user wants a usable reply ("Dear Dana, ...") without the third party learning who Dana
is.

## Decision

Tokenize with typed, numbered placeholders. Same value gets the same placeholder within a
session (HMAC index), so the model can still reason that two mentions are one customer.
Restore placeholders in the answer for the authorized user only.

Vault properties:

* Value encrypted with AES-256-GCM. The AAD binds tenant, user, session, purpose, and
  placeholder, so a ciphertext copied to another session fails to decrypt.
* Short TTL (default 15 minutes). Redis runs with persistence disabled, so vault
  ciphertext never reaches disk.
* Restoration is role-scoped per entity type: `full`, `masked`, or `never`. A support
  agent sees the card as `•••• 1111`; a billing specialist sees it in full.
* Secrets (API keys, passwords) are redacted irreversibly: a placeholder with no vault
  entry. Private keys block the request.

## Consequences

Good:

* Answers stay useful. The model writes "Dear [PERSON_NAME_1]" and the user sees
  "Dear Dana Holloway".
* Placeholders are typed, so the model knows `[CREDIT_CARD_1]` is a card and can say
  "the card on file".
* Tokens in tool arguments are detectable: a `[CREDIT_CARD_1]` in a URL is a clear
  exfiltration signal (ADR 0004).

Bad:

* The vault is sensitive state. It needs a key, a TTL, and access control.
* Models sometimes mangle placeholders. The restorer accepts common variants
  (`EMAIL_1`, `[EMAIL 1]`) and leaves unknown ones untouched.
* Typed placeholders leak the type and count of entities to the third party
  ("there is one card"). Acceptable for this threat model; format-preserving fakes are a
  next step if even that is too much.
* Tokenization does not hide context. "The CFO of our largest customer threatened to
  churn" has no entity to tokenize. That is ADR 0003.
