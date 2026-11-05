"""Shared text processing: tokenization for BM25, sentence splitting, token estimates.

Tokenization keeps identifiers such as `VPN-ERR-809`, `HR-POL-104` or `$5,000`
intact as a single term *and* emits their parts, so exact-code lookups match
precisely while partial queries ("ERR 809") still score.
"""

import re
from collections import Counter

import snowballstemmer

_stemmer = snowballstemmer.stemmer("english")
_CODE_RE = re.compile(r"\b[A-Za-z]{2,}(?:-[A-Za-z0-9]+)+\b")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[.'][A-Za-z0-9]+)*")
STOPWORDS = frozenset(
    """a an and are as at be by can do does for from has have how i if in is it its me my of on or our
    so that the their them then there these they this to us was we what when where which who why will with
    you your am been being did i'm im should would could get got any all""".split()
)


def stem(word: str) -> str:
    return _stemmer.stemWord(word)


def tokenize(text: str) -> list[str]:
    """BM25 terms: lowercase, stopwords removed, stemmed; codes kept whole plus parts."""
    terms: list[str] = []
    for code in _CODE_RE.findall(text):
        if any(ch.isdigit() for ch in code) or code.isupper():
            terms.append(code.lower())
    for w in _WORD_RE.findall(text.lower()):
        w = w.replace("'", "")
        if w in STOPWORDS or len(w) < 2 and not w.isdigit():
            continue
        terms.append(stem(w) if not any(c.isdigit() for c in w) else w)
    return terms


def term_freqs(text: str) -> Counter:
    return Counter(tokenize(text))


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~1.3 tokens per word) used for chunk sizing and cost."""
    return max(1, round(len(text.split()) * 1.3))


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("|") or line.startswith("#"):
            out.append(line)
            continue
        out.extend(s.strip() for s in _SENT_RE.split(line) if s.strip())
    return out


def specific_tokens(text: str) -> set[str]:
    """Tokens that change the meaning of a question if they differ: numbers, codes, money."""
    toks = set(c.lower() for c in _CODE_RE.findall(text) if any(ch.isdigit() for ch in c))
    toks |= set(re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?", text))
    return toks


def identifiers(text: str) -> list[str]:
    """Policy codes / error codes / form IDs in a question (letters-hyphen-digits), lowercased."""
    return sorted({c.lower() for c in _CODE_RE.findall(text) if any(ch.isdigit() for ch in c)})
