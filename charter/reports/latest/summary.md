Controls: 10 met, 4 partial, 3 gap.
Shipped gate: pass.
Residency file removed: blocked.
Decision p50 9.9 us, p95 11.8 us over 2000 rounds.
Audit events 38, chain ok True, residency violations 1.
Provider cost $0. Projected LLM review $0.054.

Weakened bundle failures (expected):
- eu-support-us: effect allow != deny (R-PERMIT-HOSTED-SUPPORT)
- restricted-us: missing R-RESIDENCY-EU; got R-RESTRICTED-BLOCK
- eu-confidential-faq-us: missing R-RESIDENCY-EU; got R-DEFAULT-DENY
