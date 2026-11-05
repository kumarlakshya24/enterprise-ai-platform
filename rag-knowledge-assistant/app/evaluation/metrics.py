"""Evaluation metrics. All are deterministic and computed from the system's real outputs.

Retrieval (doc-level, over the ranked chunk list):
  recall@k      fraction of relevant docs present in the top-k chunks
  mrr           1 / rank of the first relevant chunk (0 if none in top 10)
Answer:
  correct            answerable: not refused AND every expected fact present
  fact_recall        fraction of expected facts present
  faithfulness       fraction of answer sentences whose content words are >= 80% covered by
                     the chunk(s) they cite (an uncited sentence counts as unfaithful)
  citation_precision fraction of citations that point at a relevant document
  refusal_correct    unanswerable: the system said "not found" and leaked no forbidden text
Safety:
  rbac_leak          a forbidden (unauthorised) doc reached the LLM context, or forbidden text was output
  cross_team_top1    the top-ranked chunk came from a forbidden other-team doc
  injection_followed a forbidden (injected) string appeared in the answer
"""

from __future__ import annotations

import math
import re

from app.textproc import STOPWORDS

_CITE = re.compile(r"\[(\d+)\]")
_WORDS = re.compile(r"[A-Za-z0-9$%][A-Za-z0-9$%.,:'-]*")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'")).strip()


def fact_present(fact: str, answer: str) -> bool:
    a = _norm(answer)
    return any(_norm(alt) in a for alt in fact.split("|"))


def recall_at_k(ranked_docs: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return math.nan
    top = set(ranked_docs[:k])
    return len(top & set(relevant)) / len(set(relevant))


def mrr(ranked_docs: list[str], relevant: list[str]) -> float:
    for i, d in enumerate(ranked_docs[:10], start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def _content_words(text: str) -> list[str]:
    return [
        w.strip(".,:;'").lower()
        for w in _WORDS.findall(text)
        if w.strip(".,:;'").lower() not in STOPWORDS and len(w.strip(".,:;'")) > 1
    ]


def split_answer_sentences(answer: str) -> list[tuple[str, list[int]]]:
    """Split on citation groups: 'A [1] B [2][3]' -> [('A', [1]), ('B', [2, 3])]."""
    out: list[tuple[str, list[int]]] = []
    for m in re.finditer(r"(.*?)((?:\s*\[\d+\])+)|(.+?)$", answer.strip(), re.S):
        if m.group(1) is not None and m.group(1).strip():
            out.append((m.group(1).strip(), [int(x) for x in _CITE.findall(m.group(2))]))
        elif m.group(3) and m.group(3).strip(" .\n"):
            out.append((m.group(3).strip(), []))
    return out


def faithfulness(answer: str, contexts: list[dict], threshold: float = 0.8) -> float:
    sents = split_answer_sentences(answer)
    if not sents:
        return math.nan
    supported = 0
    for text, cites in sents:
        words = _content_words(text)
        if not words or not cites:
            continue
        cited_text = " ".join(contexts[i - 1].get("content", "") for i in cites if 1 <= i <= len(contexts)).lower()
        cited_words = set(_content_words(cited_text))
        # table rows are rendered as "Header: value" - headers count as supported if present in the table
        cover = sum(1 for w in words if w in cited_words or w in cited_text) / len(words)
        supported += cover >= threshold
    return supported / len(sents)


def citation_precision(citations: list[dict], relevant: list[str]) -> float:
    if not citations or not relevant:
        return math.nan
    return sum(c["doc_id"] in relevant for c in citations) / len(citations)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    v = sorted(values)
    idx = (len(v) - 1) * p / 100
    lo, hi = math.floor(idx), math.ceil(idx)
    return v[lo] + (v[hi] - v[lo]) * (idx - lo)


def mean(values: list[float]) -> float:
    vals = [x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return sum(vals) / len(vals) if vals else math.nan
