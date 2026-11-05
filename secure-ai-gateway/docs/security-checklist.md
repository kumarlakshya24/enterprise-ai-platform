# Security checklist

Each control, where it is implemented, and what proves it. `make security-check` automates the
repository and deployment items (13 checks); the tests prove the runtime behaviour.

| # | Control | Implementation | Proof |
|---|---------|----------------|-------|
| 1 | No secrets in code; secrets only via environment variables | `aegis/config.py` reads env only; `.env` is git-ignored; `make env` generates random keys locally | `scripts/security_check.py` (scans tracked files with the gateway's own secret detectors; fixtures may only hold synthetic, runtime-built values) |
| 2 | Production refuses to start without keys | `Settings.ensure_keys` raises in `AEGIS_ENV=prod`; demo mode warns and uses ephemeral keys | `security_check.py` |
| 3 | Synthetic data only | `.example` domains, impossible Gmail addresses (`-` in the local part), public test card numbers, 555-01xx phones | `security_check.py` (emails and cards) |
| 4 | No raw PII or secrets in logs | Audit events built from tokenized data; content withheld above INTERNAL; regex scrubber before every write; app logs never include prompt text | `tests/integration/test_no_pii_in_logs.py` scans audit, approvals, runs, and captured logs after all scenarios |
| 5 | Token vault encrypted, bound, short-lived | AES-256-GCM, AAD = tenant, user, session, purpose, placeholder; 15-minute TTL; Redis persistence off | `tests/unit/test_vault.py` (`test_no_plaintext_at_rest`, `test_aad_binding_blocks_copied_ciphertext`, `test_expiry`) |
| 6 | RBAC on de-tokenization | Session ownership; per-role restore scopes (`full`, `masked`, `never`); admins get no extra data access | `tests/integration/test_rbac.py`, `test_vault.py::test_rbac_scopes_mask_cards_for_support_agents` |
| 7 | SSO-only, tenant-restricted sign-in | RS256 only (no `none`/HS256), `iss`/`aud`/`exp` required, `tid` allowlist, `amr` must include `sso` | `tests/integration/test_auth.py` (forged signature, alg confusion, wrong tenant, password login) |
| 8 | Rate limiting | Per-user, per-bucket fixed window in Redis | `tests/integration/test_rate_limit.py` |
| 9 | Request size limits | 64 KB body limit (also for chunked bodies), field length validation, bounded agent steps | `tests/integration/test_limits.py` |
| 10 | Fail closed | Vault, audit, or detector failure returns 503; no fallback to an unprotected path | `test_limits.py::test_vault_outage_fails_closed`, `test_detectors.py::test_detector_failure_fails_closed` |
| 11 | Tool exfiltration controls | Recipient and URL allowlists, personal-domain blocklist, decoded-URL DLP, taint, approvals | `tests/unit/test_tool_guard.py`, red-team `tool_exfiltration` (15/15 attempts caught, 2/2 legitimate calls allowed) |
| 12 | Four-eyes approvals with expiry | Requester cannot approve; needs `tool:approve`; expired approvals never run; re-check at execution | `tests/integration/test_approvals.py` |
| 13 | Tamper-evident audit | Append-only triggers; HMAC chain with key outside the DB; verify endpoint | `tests/unit/test_audit.py` (edit, delete tail, rehash with the wrong key) |
| 14 | Policy changes cannot silently weaken protection | Regression gate in CI and on `PUT /admin/policies` | `tests/integration/test_policy_admin.py`, `make regression` |
| 15 | Model artifact integrity | Classifier is JSON, never pickle; SHA-256 checked at load | `tests/unit/test_classifier.py::test_refuses_tampered_artifact` |
| 16 | Zero-click exfiltration in answers | Output sanitizer removes external images and data-carrying URLs before restore; restore never writes into URLs | `tests/unit/test_output_sanitizer.py`, `test_vault.py::test_never_restores_inside_urls` |
| 17 | Hardened containers | Non-root user, read-only root filesystem, all capabilities dropped, `no-new-privileges`, data stores on an internal network with no egress | `security_check.py`, `docker-compose.yml` |
| 18 | Supply chain | Pinned dependency versions; spaCy model pinned by SHA-256 | `requirements.txt`, `Dockerfile`, `security_check.py` |
| 19 | Unprotected demo path cannot reach a real provider by accident | Refused unless the provider is the mock or an explicit override is set; off in prod | `tests/integration/test_scenarios.py::test_unprotected_path_is_refused_for_real_providers` |
| 20 | Browser hardening for the demo UI | CSP `default-src 'self'`, no inline script, `frame-ancestors 'none'`, `nosniff`, `no-store`; model output rendered as text, never HTML | `test_limits.py::test_security_headers` |

## Not done (would be required for production)

* TLS termination and mTLS between services (compose uses plain HTTP on private networks).
* Vault and audit keys in a KMS or HSM with rotation automation (the keyring supports rotation; the
  process is manual).
* External anchoring of the audit head hash (WORM storage) and alerting on `verify` failures.
* A real IdP integration test (Okta or Entra) and token revocation handling.
* SAST, dependency scanning (pip-audit), and container image scanning in CI.
