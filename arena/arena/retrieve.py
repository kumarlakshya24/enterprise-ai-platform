"""BM25 over a few dozen runbook sections.

The index is rebuilt when the snapshot changes (freeze vs current). It is not an
approximation of a vector database. Twenty sections do not need one, and a lexical
score is something the memo can explain.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from arena.corpus import Fact
from arena.textutil import token_set, tokenize


@dataclass(frozen=True, slots=True)
class Chunk:
    fact_id: str
    doc_id: str
    title: str
    section: str
    visibility: str
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Hit:
    score: float
    overlap: int
    chunk: Chunk


def chunks_for(facts: list[Fact], as_of: str, visibility: str | None = None) -> list[Chunk]:
    built: list[Chunk] = []
    for fact in facts:
        if as_of == "freeze" and not fact.in_freeze:
            continue
        if visibility is not None and fact.visibility != visibility:
            continue
        text = fact.text_as_of(as_of)
        built.append(
            Chunk(
                fact_id=fact.id,
                doc_id=fact.doc_id,
                title=fact.title,
                section=fact.section,
                visibility=fact.visibility,
                text=text,
                tokens=tuple(tokenize(text)),
            )
        )
    return built


class Index:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._n = len(chunks)
        self._df: Counter[str] = Counter()
        total = 0
        for chunk in chunks:
            total += len(chunk.tokens)
            for token in set(chunk.tokens):
                self._df[token] += 1
        self._avgdl = (total / self._n) if self._n else 1.0

    def search(self, question: str, k: int = 5) -> list[Hit]:
        if self._n == 0:
            return []
        query = tokenize(question)
        if not query:
            return []
        query_set = set(query)
        scored: list[Hit] = []
        for chunk in self.chunks:
            overlap = len(query_set & set(chunk.tokens))
            score = self._bm25(query, chunk)
            if score > 0 or overlap > 0:
                scored.append(Hit(score=score, overlap=overlap, chunk=chunk))
        scored.sort(key=lambda hit: (hit.score, hit.overlap, hit.chunk.fact_id), reverse=True)
        return scored[:k]

    def _bm25(self, query: list[str], chunk: Chunk, k1: float = 1.5, b: float = 0.75) -> float:
        tf = Counter(chunk.tokens)
        dl = len(chunk.tokens) or 1
        score = 0.0
        for token in set(query):
            freq = tf.get(token, 0)
            if freq == 0:
                continue
            n = self._df[token]
            idf = math.log(1.0 + (self._n - n + 0.5) / (n + 0.5))
            denom = freq + k1 * (1 - b + b * dl / self._avgdl)
            score += idf * (freq * (k1 + 1)) / denom
        return score


def keep_hits(hits: list[Hit], min_overlap: int = 2, k: int = 2, ratio: float = 0.45) -> list[Hit]:
    eligible = [hit for hit in hits if hit.overlap >= min_overlap and hit.score > 0]
    if not eligible:
        return []
    best = eligible[0].score
    kept = [hit for hit in eligible if hit.score >= ratio * best]
    return kept[:k]


def overlap_count(question: str, text: str) -> int:
    return len(token_set(question) & token_set(text))
