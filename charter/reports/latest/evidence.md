# Charter evidence pack

Tenant `acme`. Window 2026-10-22T00:00:00Z → 2026-11-04T23:00:00Z.

Synthetic data. This pack is a control mapping. It is not a legal opinion and not a certification.

Policy digest `94bac4e49b4ecedb`.

Controls: **10 met**, **4 partial**, **3 gap**.

## Gaps

- **EU-10 Data governance and residency** — 1 Aegis routing decision sent EU RESTRICTED data on route allow to us-east-1 (frontier-us-large, req-leak-01). Redaction of the card is not a residency control.
  Treatment: Investigate req-leak-01. Redaction of the card number did not keep the request in region. Fix the route, then keep R-RESIDENCY-EU.
- **EU-14 Human oversight** — Active high-risk models with no human oversight: claims-triage-eu. R-OVERSIGHT denies invocation. The deployment is still active.
  Treatment: Take claims-triage-eu out of active, or assign a reviewer and set human_oversight. Leave R-OVERSIGHT in the bundle either way.
- **EU-15 Accuracy, robustness, cybersecurity** — Lens quality is paging (SLI 0.91 vs target 0.95, 6h burn 7.8×). Article 15 accuracy is not met. Safety is ticket (SLI 0.9974).
  Treatment: Treat the Lens quality page as an accuracy failure. Do not close this control by editing the target in the same week as the drop.

## Partials

- **EU-26 Deployer duties** — Logging verifies. Oversight does not: claims-triage-eu is active high-risk with no reviewer.
- **NIST-GV-6.1 Third-party risk** — Active hosted models with no provider review: frontier-us-large.
- **NIST-MS-2.6 Safety evaluation** — Safety SLO is on a ticket (SLI 0.9974 vs 0.999, 6h burn 3.2x).
- **NIST-MG-4.1 Post-deployment monitoring** — Monitoring is on. Not quiet: quality, safety.

## Decisions

| Case | Effect | Primary rule |
|---|---|---|
| `eu-support-local` | allow | `R-PERMIT-SUPPORT-EU` |
| `eu-support-us` | deny | `R-RESIDENCY-EU` |
| `public-faq-us` | allow | `R-PERMIT-PUBLIC-US` |
| `internal-eu-on-us` | allow | `R-PERMIT-HOSTED-SUPPORT` |
| `restricted-local` | deny | `R-RESTRICTED-BLOCK` |
| `restricted-us` | deny | `R-RESTRICTED-BLOCK` |
| `credit-with-oversight` | allow | `R-PERMIT-CREDIT` |
| `credit-us-subject` | deny | `R-DEFAULT-DENY` |
| `claims-no-oversight` | deny | `R-OVERSIGHT` |
| `social-ranker` | deny | `R-PROHIBITED` |
| `incomplete-card` | deny | `R-CARD-INCOMPLETE` |
| `unknown-model` | deny | `R-MODEL-UNKNOWN` |
| `purpose-mismatch` | deny | `R-DEFAULT-DENY` |
| `export-weights` | deny | `R-DEFAULT-DENY` |
| `eu-confidential-faq-us` | deny | `R-RESIDENCY-EU` |

## Aegis stub

Chain ok: True. Events: 38. Planted violation `req-leak-01` at 2026-11-03T16:42:00Z: RESTRICTED on route `allow` to us-east-1 (frontier-us-large).

## Lens snapshot

Quality page (SLI 0.91 / 0.95). Safety ticket. These figures are the offline snapshot, not a live Lens export.

## Cost

Charter provider cost: $0. Projected external review of this pack: $0.054 (projection, not an invoice. Prices are stand-ins for a strong review model.).
