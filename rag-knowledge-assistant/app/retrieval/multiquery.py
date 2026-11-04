"""Multi-query expansion.

With a generative LLM: ask for N short paraphrases that target different
intents (support / policy / process), e.g. "laptop died, help" ->
"laptop will not power on troubleshooting", "laptop hardware warranty repair",
"request loaner or replacement laptop".

Without an LLM (offline mode): pseudo-relevance feedback (RM3-style). Run the
original query, take the top documents, and build one variant per distinct
document from its most discriminative terms (high tf in the feedback chunk,
low document frequency in the corpus). This is a classic IR technique, not an
LLM; it helps vague queries less than an LLM would, and the eval reports it as such.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter

from app.models import Candidate
from app.providers.llm import LLM
from app.textproc import STOPWORDS, stem

log = logging.getLogger(__name__)

PROMPT = """Rewrite the employee's question into {n} different search queries for a company knowledge base.
Each query should target a different likely intent (for example: troubleshooting, policy, request process).
Keep each under 12 words. Return only a JSON array of strings.

Question: {q}"""


def llm_variants(llm: LLM, question: str, n: int, timeout_s: float) -> tuple[list[str], int, int]:
    res = llm.complete("You generate search queries. Output JSON only.", PROMPT.format(n=n, q=question), 200, timeout_s)
    m = re.search(r"\[.*\]", res.text, re.S)
    out = [v for v in json.loads(m.group(0)) if isinstance(v, str)][:n] if m else []
    return out, res.input_tokens, res.output_tokens


def feedback_words(question: str, cand: Candidate) -> list[str]:
    q_words = {w.lower() for w in re.findall(r"[A-Za-z0-9-]+", question)}
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", f"{cand.title} {cand.content}")
            if w.lower() not in STOPWORDS and w.lower() not in q_words]


def prf_variants(question: str, feedback: list[Candidate], df: dict[str, int], n_docs: int, n: int,
                 terms_per_variant: int = 5) -> list[str]:
    """`df` maps *stemmed* terms to chunk document-frequency."""
    seen_docs, variants = set(), []
    for cand in feedback:
        if cand.doc_id in seen_docs:
            continue
        seen_docs.add(cand.doc_id)
        words = feedback_words(question, cand)
        tf = Counter(w.lower() for w in words)
        scored = sorted(tf, key=lambda w: -tf[w] * math.log(1 + n_docs / (1 + df.get(stem(w), 0))))
        if scored:
            variants.append(f"{question} {' '.join(scored[:terms_per_variant])}")
        if len(variants) >= n:
            break
    return variants
