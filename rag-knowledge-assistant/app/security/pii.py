"""PII detection and redaction.

Detectors are deterministic regexes with validation (Luhn for cards, range checks
for SSNs) so they are fast enough to run on every chunk sent to an external model.
Redaction events record *types and counts only*; the matched values are never
logged or persisted.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


def _luhn(num: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", num)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _ssn_ok(m: str) -> bool:
    a, b, c = m.split("-")
    return a not in {"000", "666"} and not a.startswith("9") and b != "00" and c != "0000"


PATTERNS: list[tuple[str, re.Pattern, object]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b"), _luhn),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), _ssn_ok),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), None),
    ("EMPLOYEE_ID", re.compile(r"\bEMP-\d{5,7}\b"), None),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b"), None),
    ("IP_ADDRESS", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), None),
]

# Business contact points that are intentionally published (help desks, hotlines)
# are not personal data; redacting them would break legitimate answers.
DEFAULT_ALLOWLIST = frozenset({"security@lumen-analytics.com", "payroll@lumen-analytics.com", "+1 800 555 0199"})


@dataclass
class RedactionResult:
    text: str
    counts: Counter = field(default_factory=Counter)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)


def detect(text: str, allowlist: frozenset[str] = DEFAULT_ALLOWLIST) -> Counter:
    return redact(text, allowlist).counts


def redact(text: str, allowlist: frozenset[str] = DEFAULT_ALLOWLIST) -> RedactionResult:
    counts: Counter = Counter()
    out = text
    for label, pat, validator in PATTERNS:

        def sub(m: re.Match, label=label, validator=validator) -> str:
            val = m.group(0)
            if val.strip() in allowlist or (validator and not validator(val)):  # type: ignore[operator]
                return val
            counts[label] += 1
            return f"[{label}]"

        out = pat.sub(sub, out)
    return RedactionResult(out, counts)
