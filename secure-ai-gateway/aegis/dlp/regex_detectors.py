"""Pattern detectors with validation (Luhn, IIN, SSN area rules, entropy) and context boosts."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

from aegis.dlp.base import (
    PRIORITY_CUE,
    PRIORITY_ENTROPY,
    PRIORITY_OBFUSCATED,
    PRIORITY_SECRET,
    PRIORITY_STRUCTURED,
)
from aegis.types import EntityType, Finding


def _context_window(text: str, start: int, end: int, before: int = 40, after: int = 10) -> str:
    return text[max(0, start - before) : min(len(text), end + after)].lower()


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# --------------------------------------------------------------------------- email


class EmailDetector:
    name = "regex.email"
    _re = re.compile(
        r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@"
        r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}(?![\w-])"
    )

    def detect(self, text: str) -> list[Finding]:
        return [
            Finding(
                EntityType.EMAIL,
                m.start(),
                m.end(),
                0.99,
                self.name,
                "RFC-5322-style address pattern",
                priority=PRIORITY_STRUCTURED,
            )
            for m in self._re.finditer(text)
        ]


class ObfuscatedEmailDetector:
    """`dana dot holloway at example dot com`, `dana[at]example[dot]com`, `dana @ example . com`."""

    name = "regex.email_obfuscated"
    _at = r"(?:\s*\[\s*at\s*\]\s*|\s*\(\s*at\s*\)\s*|\s*\{\s*at\s*\}\s*|\s+at\s+|\s+@\s*|\s*@\s+)"
    _dot = r"(?:\s*\[\s*dot\s*\]\s*|\s*\(\s*dot\s*\)\s*|\s*\{\s*dot\s*\}\s*|\s+dot\s+|\s*\.\s*)"
    _tlds = r"(?:com|org|net|io|co|edu|gov|example|info|biz|us|uk|de|fr|ca|au|in|dev|ai|app|me)"
    _re = re.compile(
        rf"(?<![\w@])((?:[A-Za-z0-9_%+-]+{_dot})*[A-Za-z0-9_%+-]+){_at}"
        rf"((?:[A-Za-z0-9-]+{_dot})+){_tlds}\b",
        re.IGNORECASE,
    )
    _word_markers = re.compile(r"\b(?:at|dot)\b|\[|\(|\{|\s@|@\s", re.IGNORECASE)

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for m in self._re.finditer(text):
            span = m.group(0)
            if not self._word_markers.search(span):
                continue  # a plain address; EmailDetector handles it
            local = m.group(1).lower()
            if local in {"me", "us", "him", "her", "them", "it", "you", "home", "work"}:
                continue  # "email me at work dot com" style false positives
            out.append(
                Finding(
                    EntityType.EMAIL,
                    m.start(),
                    m.end(),
                    0.8,
                    self.name,
                    "email written with at/dot words or brackets",
                    priority=PRIORITY_OBFUSCATED,
                )
            )
        return out


# --------------------------------------------------------------------------- phone

_PHONE_CONTEXT = re.compile(
    r"\b(phone|call|calling|tel|telephone|mobile|cell|text me|reach me|contact|fax|whatsapp|number)\b"
)


class PhoneDetector:
    name = "regex.phone"
    _nanp = re.compile(r"(?<![\w+])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?![\w])")
    _intl = re.compile(r"(?<![\w+])\+[2-9]\d{0,2}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?![\w])")

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for regex, kind in ((self._nanp, "NANP"), (self._intl, "international")):
            for m in regex.finditer(text):
                raw = m.group(0)
                digits = re.sub(r"\D", "", raw)
                if not 10 <= len(digits) <= 15:
                    continue
                formatted = bool(re.search(r"[\s().+-]", raw))
                conf = 0.85 if formatted else 0.45
                explanation = f"{kind} phone pattern" + ("" if formatted else " (bare digits)")
                if _PHONE_CONTEXT.search(_context_window(text, m.start(), m.end())):
                    conf = min(0.95, conf + 0.3)
                    explanation += " + phone context words"
                out.append(
                    Finding(
                        EntityType.PHONE,
                        m.start(),
                        m.end(),
                        conf,
                        self.name,
                        explanation,
                        priority=PRIORITY_STRUCTURED - 5,
                    )
                )
        return out


# --------------------------------------------------------------------------- credit card


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def card_brand(digits: str) -> str | None:
    n = len(digits)
    if digits[0] == "4" and n in (13, 16, 19):
        return "visa"
    p2, p4 = int(digits[:2]), int(digits[:4])
    if n == 16 and (51 <= p2 <= 55 or 2221 <= p4 <= 2720):
        return "mastercard"
    if n == 15 and p2 in (34, 37):
        return "amex"
    if n in (16, 19) and (
        digits.startswith("6011") or digits.startswith("65") or 644 <= int(digits[:3]) <= 649
    ):
        return "discover"
    if 16 <= n <= 19 and 3528 <= p4 <= 3589:
        return "jcb"
    if n == 14 and (p2 in (36, 38) or 300 <= int(digits[:3]) <= 305):
        return "diners"
    return None


_REGULAR_GROUPINGS = {(4, 4, 4, 4), (4, 6, 5), (4, 6, 4), (4, 4, 4, 4, 3), (4, 4, 4, 1), (4, 4, 4, 3)}


class CreditCardDetector:
    name = "regex.credit_card"
    _re = re.compile(r"(?<![\d])(?:\d[ \-.]?){12,18}\d(?![\d])")

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for m in self._re.finditer(text):
            raw = m.group(0)
            # \d also matches non-ASCII digits (e.g. fullwidth); convert to ASCII before Luhn.
            digits = "".join(str(int(ch)) for ch in raw if ch.isdigit())
            if not 13 <= len(digits) <= 19 or not luhn_valid(digits):
                continue
            if len(set(digits)) == 1:
                continue  # 0000000000000 passes Luhn; nobody's card
            groups = tuple(len(g) for g in re.split(r"[ \-.]", raw) if g)
            regular = len(groups) == 1 or set(groups) == {1} or groups in _REGULAR_GROUPINGS
            brand = card_brand(digits)
            if brand and regular:
                conf, why = 0.99, f"Luhn-valid {brand} number"
            elif brand:
                conf, why = 0.6, f"Luhn-valid {brand} number, irregular grouping"
            elif regular:
                conf, why = 0.8, "Luhn-valid number, unknown issuer"
            else:
                continue
            if set(groups) == {1} and len(groups) > 1:
                why += " (digits spaced out)"
            out.append(
                Finding(
                    EntityType.CREDIT_CARD,
                    m.start(),
                    m.end(),
                    conf,
                    self.name,
                    why,
                    priority=PRIORITY_STRUCTURED,
                )
            )
        return out


# --------------------------------------------------------------------------- SSN-like

_SSN_CONTEXT = re.compile(r"\b(ssn|social security|social sec|tax id|taxpayer|itin|tin)\b")


class SSNDetector:
    """US SSN-like identifiers. 9xx (ITIN range) is included on purpose: also sensitive."""

    name = "regex.ssn"
    _sep = re.compile(r"(?<![\d-])(?!000|666)(\d{3})([- .])(?!00)(\d{2})\2(?!0000)(\d{4})(?![\d-])")
    _bare = re.compile(r"(?<![\d-])(?!000|666)\d{3}(?!00)\d{2}(?!0000)\d{4}(?![\d-])")

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for m in self._sep.finditer(text):
            ctx = bool(_SSN_CONTEXT.search(_context_window(text, m.start(), m.end())))
            out.append(
                Finding(
                    EntityType.SSN,
                    m.start(),
                    m.end(),
                    0.95 if ctx else 0.85,
                    self.name,
                    "SSN-like ###-##-#### pattern" + (" + SSN context words" if ctx else ""),
                    priority=PRIORITY_STRUCTURED,
                )
            )
        for m in self._bare.finditer(text):
            if _SSN_CONTEXT.search(_context_window(text, m.start(), m.end())):
                out.append(
                    Finding(
                        EntityType.SSN,
                        m.start(),
                        m.end(),
                        0.75,
                        self.name,
                        "9 bare digits next to SSN context words",
                        priority=PRIORITY_STRUCTURED - 10,
                    )
                )
        return out


# --------------------------------------------------------------------------- secrets

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], EntityType, float]] = [
    (
        "openai_style_key",
        re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_\-]{20,}"),
        EntityType.API_KEY,
        0.95,
    ),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), EntityType.API_KEY, 0.95),
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22,}"),
        EntityType.API_KEY,
        0.95,
    ),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), EntityType.API_KEY, 0.9),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), EntityType.API_KEY, 0.9),
    ("stripe_style_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"), EntityType.API_KEY, 0.95),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        EntityType.API_KEY,
        0.85,
    ),
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|\Z)"
        ),
        EntityType.PRIVATE_KEY,
        0.99,
    ),
]

_URL_CREDENTIALS = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:([^\s:/@]{3,})@[^\s/]+", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|apikey|secret(?:[_-]?key)?|client[_-]?secret|access[_-]?token|auth[_-]?token"
    r"|bearer|token|passwd|password|pwd)\b[\"']?\s*(?:[:=]|\bis\b)\s*[\"']?([^\s\"',;]{6,})"
)
_NOT_A_SECRET = re.compile(
    r"^(?:\$\{?\w+\}?|<[^>]+>|\[[A-Z_]+_\d+\]|\*+|x+|true|false|null|none|redacted|changeme|example\w*|"
    r"required|optional|reset|expired|incorrect|wrong|missing|invalid)$",
    re.IGNORECASE,
)
_HIGH_ENTROPY = re.compile(r"(?<![\w/+=-])[A-Za-z0-9+/_\-]{32,}={0,2}(?![\w/+=-])")


class SecretDetector:
    name = "regex.secret"

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for label, regex, etype, conf in _SECRET_PATTERNS:
            for m in regex.finditer(text):
                out.append(
                    Finding(
                        etype,
                        m.start(),
                        m.end(),
                        conf,
                        f"{self.name}.{label}",
                        f"{label} format",
                        priority=PRIORITY_SECRET,
                    )
                )
        for m in _URL_CREDENTIALS.finditer(text):
            if _NOT_A_SECRET.match(m.group(1)):
                continue  # ${POSTGRES_PASSWORD} and friends are references, not secrets
            out.append(
                Finding(
                    EntityType.PASSWORD,
                    m.start(1),
                    m.end(1),
                    0.9,
                    f"{self.name}.url_credentials",
                    "password embedded in a connection URL",
                    priority=PRIORITY_SECRET,
                )
            )
        for m in _ASSIGNMENT.finditer(text):
            key, value = m.group(1).lower(), m.group(2)
            if _NOT_A_SECRET.match(value) or len(set(value)) < 3:
                continue
            etype = EntityType.PASSWORD if key in {"password", "passwd", "pwd"} else EntityType.API_KEY
            ent = shannon_entropy(value)
            conf = 0.9 if ent >= 3.0 else 0.75
            out.append(
                Finding(
                    etype,
                    m.start(2),
                    m.end(2),
                    conf,
                    f"{self.name}.assignment",
                    f"value assigned to '{key}' (entropy {ent:.1f} bits/char)",
                    priority=PRIORITY_SECRET - 5,
                )
            )
        for m in _HIGH_ENTROPY.finditer(text):
            tok = m.group(0)
            if not (re.search(r"[a-z]", tok) and re.search(r"[A-Z]", tok) and re.search(r"\d", tok)):
                continue  # hex digests, UUIDs, and words are not flagged
            ent = shannon_entropy(tok)
            if ent < 4.0:
                continue
            out.append(
                Finding(
                    EntityType.API_KEY,
                    m.start(),
                    m.end(),
                    0.65,
                    f"{self.name}.high_entropy",
                    f"high-entropy token ({ent:.1f} bits/char, mixed case + digits)",
                    priority=PRIORITY_ENTROPY,
                )
            )
        return out


# --------------------------------------------------------------------------- name cues

_CUE_NAME = re.compile(
    r"(?:\bmy name is|\bthis is|\bi am|\bi'm|\bname:|\bdear|\bsigned,?|\bregards,?|\bsincerely,?|\bthanks,?)"
    r"\s+((?:[A-Za-z][a-z'’-]+)(?:\s+[A-Za-z][a-z'’-]+){0,2})",
    re.IGNORECASE,
)
_CUE_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "not",
        "very",
        "so",
        "really",
        "just",
        "also",
        "here",
        "there",
        "going",
        "writing",
        "trying",
        "calling",
        "looking",
        "having",
        "sure",
        "sorry",
        "happy",
        "glad",
        "confused",
        "concerned",
        "furious",
        "upset",
        "frustrated",
        "angry",
        "worried",
        "new",
        "still",
        "from",
        "with",
        "about",
        "regarding",
        "following",
        "team",
        "support",
        "customer",
        "your",
        "our",
        "their",
        "an",
        "and",
        "or",
        "but",
        "to",
        "for",
        "of",
        "in",
        "on",
        "at",
        "interested",
        "available",
        "unable",
        "able",
        "done",
        "ready",
        "back",
        "working",
        "wondering",
        "contacting",
        "reaching",
        "hiring",
        "manager",
        "sir",
        "madam",
        "all",
        "everyone",
        "colleagues",
        "valued",
        "friends",
        "folks",
        "again",
        "everybody",
    ]
)


class NameCueDetector:
    """Names introduced by conversational cues. Catches lowercase names NER misses."""

    name = "cue.person_name"

    def __init__(self, first_names: Iterable[str]) -> None:
        self.first_names = frozenset(n.lower() for n in first_names)

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for m in _CUE_NAME.finditer(text):
            words = m.group(1).split()
            kept: list[str] = []
            for w in words:
                if w.lower().strip("'’") in _CUE_STOPWORDS:
                    break
                kept.append(w)
            if not kept:
                continue
            first = kept[0].lower()
            cue = m.group(0)[: m.start(1) - m.start()].strip().lower()
            is_first_name = first in self.first_names
            title_case = all(w[0].isupper() for w in kept)
            if cue in {"i am", "i'm", "this is"} and not (is_first_name or (title_case and len(kept) >= 2)):
                continue  # "I am Concerned" should not become a name
            if not is_first_name and not title_case:
                continue
            conf = 0.6 + (0.2 if is_first_name else 0.0) + (0.1 if len(kept) >= 2 else 0.0)
            start = m.start(1)
            end = start + _span_len(m.group(1), len(kept))
            out.append(
                Finding(
                    EntityType.PERSON_NAME,
                    start,
                    end,
                    min(conf, 0.92),
                    self.name,
                    f"name after cue '{cue}'" + (" (known first name)" if is_first_name else ""),
                    priority=PRIORITY_CUE,
                )
            )
        return out


def _span_len(s: str, n_words: int) -> int:
    """Length of the prefix of `s` that contains the first `n_words` words."""
    count = 0
    in_word = False
    for i, ch in enumerate(s):
        if ch.isspace():
            if in_word:
                count += 1
                if count == n_words:
                    return i
            in_word = False
        else:
            in_word = True
    return len(s)


def default_regex_detectors(first_names: Iterable[str]) -> list[object]:
    return [
        EmailDetector(),
        ObfuscatedEmailDetector(),
        PhoneDetector(),
        CreditCardDetector(),
        SSNDetector(),
        SecretDetector(),
        NameCueDetector(first_names),
    ]
