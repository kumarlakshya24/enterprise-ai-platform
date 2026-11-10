"""Four arms, one question shape.

Prompt reads public prose only. RAG reads the snapshot you point it at and cites
the section. The adapter and the student emit freeze-dated fact text and never cite.
Neither trainer reads a holdout label.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

from arena.corpus import Fact, Item
from arena.retrieve import Index, keep_hits
from arena.textutil import tokenize

REFUSAL = "I don't have this in the arm."
ARMS = ("prompt", "rag", "lora", "distilled")


@dataclass(slots=True)
class Answer:
    arm: str
    text: str
    refused: bool
    citations: list[dict[str, object]] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)

    def public(self) -> dict[str, object]:
        return {
            "arm": self.arm,
            "text": self.text,
            "refused": self.refused,
            "citations": self.citations,
            "fact_ids": self.fact_ids,
        }


def refuse(arm: str) -> Answer:
    return Answer(arm=arm, text=REFUSAL, refused=True)


def train_counts(items: list[Item]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        if item.split != "train":
            continue
        for fact_id in item.fact_ids:
            counts[fact_id] += 1
    return dict(counts)


def _cite(fact: Fact, index: int) -> dict[str, object]:
    return {
        "index": index,
        "doc_id": fact.doc_id,
        "title": fact.title,
        "section": fact.section,
    }


class RetrieverArm:
    """Prompt and RAG. The only difference is the index and whether we cite."""

    def __init__(
        self,
        name: str,
        index: Index,
        facts: Mapping[str, Fact],
        min_overlap: int,
        cite: bool,
    ) -> None:
        self.name = name
        self.index = index
        self.facts = facts
        self.min_overlap = min_overlap
        self.cite = cite

    def answer(self, question: str) -> Answer:
        kept = keep_hits(self.index.search(question, k=10), min_overlap=self.min_overlap)
        if not kept:
            return refuse(self.name)
        texts: list[str] = []
        citations: list[dict[str, object]] = []
        fact_ids: list[str] = []
        for offset, hit in enumerate(kept, start=1):
            fact = self.facts[hit.chunk.fact_id]
            texts.append(hit.chunk.text)
            fact_ids.append(fact.id)
            if self.cite:
                citations.append(_cite(fact, offset))
        return Answer(
            arm=self.name,
            text="\n".join(texts),
            refused=False,
            citations=citations,
            fact_ids=fact_ids,
        )


@dataclass(slots=True)
class Memory:
    """Keyword memory built from train questions. Not a weight file."""

    facts: dict[str, Fact]
    question_tokens: dict[str, list[frozenset[str]]]
    min_score: int
    keep_within: int
    name: str

    def answer(self, question: str) -> Answer:
        query = set(tokenize(question))
        scored: list[tuple[int, str]] = []
        for fact_id, fact in self.facts.items():
            memories = self.question_tokens.get(fact_id, [])
            memorized = max((len(query & tokens) for tokens in memories), default=0)
            alias_hits = len(query & fact.alias_tokens)
            score = memorized + 2 * alias_hits
            if score >= self.min_score:
                scored.append((score, fact_id))
        if not scored:
            return refuse(self.name)
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        best = scored[0][0]
        chosen = [fact_id for score, fact_id in scored if score >= best - self.keep_within]
        texts = [self.facts[fact_id].freeze_text for fact_id in chosen]
        return Answer(arm=self.name, text="\n".join(texts), refused=False, fact_ids=chosen)


def _memory_for(
    items: list[Item],
    facts: Mapping[str, Fact],
    allowed: set[str],
    name: str,
    min_score: int,
    keep_within: int,
) -> Memory:
    buckets: dict[str, list[frozenset[str]]] = defaultdict(list)
    for item in items:
        if item.split != "train":
            continue
        tokens = frozenset(tokenize(item.question))
        for fact_id in item.fact_ids:
            if fact_id in allowed:
                buckets[fact_id].append(tokens)
    kept = {fact_id: facts[fact_id] for fact_id in allowed}
    return Memory(
        facts=kept,
        question_tokens=dict(buckets),
        min_score=min_score,
        keep_within=keep_within,
        name=name,
    )


def build_adapter(
    items: list[Item],
    facts: Mapping[str, Fact],
    counts: Mapping[str, int],
    policy: Mapping[str, object],
) -> Memory:
    allowed = {fact_id for fact_id, count in counts.items() if count >= 1}
    return _memory_for(
        items,
        facts,
        allowed,
        "lora",
        int(policy["lora_min_score"]),
        int(policy["lora_keep_within"]),
    )


def build_student(
    items: list[Item],
    facts: Mapping[str, Fact],
    counts: Mapping[str, int],
    policy: Mapping[str, object],
) -> Memory:
    minimum = int(policy["distill_min_train_count"])
    allowed = {
        fact_id
        for fact_id, fact in facts.items()
        if counts.get(fact_id, 0) >= minimum and fact.length == "short"
    }
    return _memory_for(
        items,
        facts,
        allowed,
        "distilled",
        int(policy["lora_min_score"]),
        int(policy["lora_keep_within"]),
    )
