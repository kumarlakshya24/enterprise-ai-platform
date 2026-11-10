"""Tokenization shared by retrieval and the adapter stub.

Numbers stay. One-character tokens drop, so "severity 1" would lose the digit.
The corpus spells those out ("severity one") on purpose.
"""

from __future__ import annotations

import re

STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "to",
        "and",
        "or",
        "for",
        "in",
        "on",
        "is",
        "are",
        "be",
        "we",
        "do",
        "does",
        "did",
        "what",
        "how",
        "when",
        "with",
        "per",
        "at",
        "by",
        "our",
        "it",
        "that",
        "this",
        "from",
        "as",
        "if",
        "can",
        "you",
        "your",
        "not",
        "no",
        "into",
        "than",
        "then",
        "there",
        "their",
        "they",
        "was",
        "were",
        "been",
        "have",
        "has",
        "will",
        "would",
        "should",
        "could",
        "about",
        "after",
        "before",
        "over",
        "under",
        "out",
        "only",
        "also",
        "other",
        "same",
        "next",
        "which",
        "who",
        "why",
        "where",
        "tell",
        "me",
        "please",
        "within",
        "until",
        "during",
        "without",
        "quote",
        "much",
        "many",
        "may",
        "get",
        "gets",
        "got",
        "just",
        "too",
        "very",
        "onto",
        "upon",
        "via",
        "let",
        "lets",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    raw = _TOKEN.findall(text.lower())
    return [part for part in raw if len(part) > 1 and part not in STOP]


def token_set(text: str) -> set[str]:
    return set(tokenize(text))
