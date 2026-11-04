"""Prompt-injection defences for retrieved content.

Retrieved text is *data*. Three layers:
  1. Ingestion-time scan: each chunk gets an `injection_risk` score from patterns
     that address an AI/assistant or try to override instructions.
  2. Query-time handling (INJECTION_MODE): `flag` keeps text but marks it,
     `strip` removes the offending sentences, `drop` removes the whole chunk.
  3. Prompt structure: chunks are wrapped in <document> tags with an explicit
     instruction that their content is untrusted and must never be obeyed
     (see app/generation/prompts.py). The extractive generator also never
     selects a flagged sentence.
"""
from __future__ import annotations

import re

from app.textproc import split_sentences

_RULES: list[tuple[re.Pattern, float]] = [
    (re.compile(r"\bignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)\b", re.I), 1.0),
    (re.compile(r"\b(disregard|forget|override) (all |your |the )?(previous |prior )?(instructions|rules|guidelines|system prompt)\b", re.I), 1.0),
    (re.compile(r"\byou are now\b|\bact as\b|\bpretend to be\b|\bmaintenance mode\b|\bdeveloper mode\b", re.I), 0.6),
    (re.compile(r"\b(note|message|instructions?) (to|for) (the )?(ai|assistant|llm|chatbot|model)s?\b", re.I), 0.7),
    (re.compile(r"\b(system prompt|reveal your|print your instructions)\b", re.I), 0.6),
    (re.compile(r"\b(email|send|share|give) (us |me )?(your|their) (password|credentials|mfa code|bypass code)\b", re.I), 0.9),
    (re.compile(r"</?(system|assistant|instructions?)>", re.I), 0.8),
]


_NEGATION = re.compile(r"\b(not|never|don't|do not|won't|will never|must not|no one)\b[^.]{0,40}$", re.I)


def sentence_risk(sentence: str) -> float:
    """Sum of matched rule weights, ignoring matches that are negated ("Do not share your password").

    Security guidance routinely *mentions* the dangerous action in order to forbid it;
    flagging it would make the guard strip exactly the advice users need.
    """
    total = 0.0
    for pat, w in _RULES:
        for m in pat.finditer(sentence):
            if not _NEGATION.search(sentence[: m.start()]):
                total += w
                break
    return min(1.0, total)


def score(text: str) -> float:
    return max((sentence_risk(s) for s in split_sentences(text)), default=0.0)


def is_risky(sentence: str, threshold: float = 0.6) -> bool:
    return sentence_risk(sentence) >= threshold


def strip_instructions(text: str, threshold: float = 0.6) -> tuple[str, int]:
    """Remove sentences that look like instructions to the model. Returns (text, removed)."""
    kept, removed = [], 0
    for line in text.split("\n"):
        if line.startswith("|") or line.startswith("#"):
            kept.append(line)
            continue
        sents = split_sentences(line)
        good = [s for s in sents if sentence_risk(s) < threshold]
        removed += len(sents) - len(good)
        if good:
            kept.append(" ".join(good))
    return "\n".join(kept), removed
