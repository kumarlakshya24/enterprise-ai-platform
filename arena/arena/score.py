"""Exact-phrase grading.

A correct answer contains the phrase for the world under test (current policy,
or the freeze policy) and does not contain the other version. A refusal is correct
only when the gold item is unanswerable and the text did not leak a fact phrase.
Stale is not the same as a hallucination: the old sentence used to be true.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from arena.arms import Answer
from arena.corpus import Fact, Item


@dataclass(frozen=True, slots=True)
class Grade:
    ok: bool
    reason: str
    stale: bool
    hallucination: bool
    cited: bool


def _contains(text: str, phrase: str | None) -> bool:
    if not phrase:
        return False
    return phrase.casefold() in text.casefold()


def _any_phrase(text: str, facts: Mapping[str, Fact]) -> bool:
    folded = text.casefold()
    for fact in facts.values():
        if fact.include.casefold() in folded or fact.freeze_include.casefold() in folded:
            return True
    return False


def grade(item: Item, answer: Answer, facts: Mapping[str, Fact], as_of: str) -> Grade:
    if item.refuse:
        leaked = _any_phrase(answer.text, facts)
        if answer.refused and not leaked:
            return Grade(ok=True, reason="ok", stale=False, hallucination=False, cited=False)
        return Grade(ok=False, reason="hallucinated", stale=False, hallucination=True, cited=False)

    missing = False
    stale = False
    for fact_id in item.fact_ids:
        fact = facts[fact_id]
        right = _contains(answer.text, fact.phrase(as_of))
        wrong = _contains(answer.text, fact.wrong_phrase(as_of))
        if wrong and not right:
            stale = True
        elif not right:
            missing = True
    cited = _cited(item, answer, facts)
    if answer.refused:
        return Grade(ok=False, reason="refused", stale=False, hallucination=False, cited=False)
    if stale:
        return Grade(ok=False, reason="stale", stale=True, hallucination=False, cited=cited)
    if missing:
        return Grade(ok=False, reason="missing", stale=False, hallucination=False, cited=cited)
    return Grade(ok=True, reason="ok", stale=False, hallucination=False, cited=cited)


def _cited(item: Item, answer: Answer, facts: Mapping[str, Fact]) -> bool:
    wanted = {facts[fact_id].doc_id for fact_id in item.fact_ids}
    got = {str(row.get("doc_id")) for row in answer.citations}
    return bool(wanted) and wanted <= got


def aggregate(rows: list[tuple[Item, Grade]]) -> dict[str, object]:
    n = len(rows)
    correct = sum(1 for _item, grade_ in rows if grade_.ok)
    hallucinations = sum(1 for _item, grade_ in rows if grade_.hallucination)
    cite_rows = [(item, grade_) for item, grade_ in rows if not item.refuse]
    cite_hits = sum(1 for _item, grade_ in cite_rows if grade_.cited)
    refusals = [(item, grade_) for item, grade_ in rows if item.refuse]
    refusal_ok = sum(1 for _item, grade_ in refusals if grade_.ok)
    return {
        "n": n,
        "correct": correct,
        "task_success": _rate(correct, n),
        "citation_hits": cite_hits,
        "citation_denominator": len(cite_rows),
        "citation_rate": _rate(cite_hits, len(cite_rows)),
        "hallucinations": hallucinations,
        "hallucination_rate": _rate(hallucinations, n),
        "refusal_correct": refusal_ok,
        "refusal_denominator": len(refusals),
        "refusal_accuracy": _rate(refusal_ok, len(refusals)) if refusals else None,
    }


def aggregate_with_facts(rows: list[tuple[Item, Grade]], facts: Mapping[str, Fact]) -> dict[str, object]:
    base = aggregate(rows)
    amended_rows = [
        (item, grade_) for item, grade_ in rows if any(facts[fact_id].amended for fact_id in item.fact_ids)
    ]
    stale = sum(1 for _item, grade_ in amended_rows if grade_.stale)
    base["stale"] = stale
    base["stale_denominator"] = len(amended_rows)
    base["stale_rate"] = _rate(stale, len(amended_rows)) if amended_rows else None
    return base


def _rate(hits: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(hits / total, 4)
