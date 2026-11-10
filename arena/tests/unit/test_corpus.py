"""The frozen runbooks and the labeled set stay aligned."""

from __future__ import annotations

from arena.retrieve import chunks_for
from arena.world import World


def test_fact_phrases_live_in_the_prose(world: World) -> None:
    for fact in world.facts.values():
        assert fact.include.casefold() in fact.current_text.casefold(), fact.id
        assert fact.freeze_include.casefold() in fact.freeze_text.casefold(), fact.id
        assert "<!--" not in fact.current_text
        assert "<!--" not in fact.freeze_text


def test_freeze_snapshot_drops_docs_added_after_cutoff(world: World) -> None:
    facts = list(world.facts.values())
    freeze_ids = {chunk.fact_id for chunk in chunks_for(facts, "freeze")}
    current_ids = {chunk.fact_id for chunk in chunks_for(facts, "current")}
    assert "webhook.sign" not in freeze_ids
    assert "dunning.retry" not in freeze_ids
    assert {"webhook.sign", "dunning.retry"} <= current_ids
    public = {chunk.fact_id for chunk in chunks_for(facts, "freeze", visibility="public")}
    assert public == {"product.what", "product.regions", "status.url", "support.hours"}


def test_amended_phrases_do_not_share_a_sentence(world: World) -> None:
    amended = [fact for fact in world.facts.values() if fact.amended]
    assert {fact.id for fact in amended} == {"refund.window", "session.idle", "sev2.response"}
    for fact in amended:
        assert fact.include.casefold() not in fact.freeze_text.casefold()
        assert fact.freeze_include.casefold() not in fact.current_text.casefold()


def test_labeled_set_shape(world: World) -> None:
    splits: dict[str, int] = {}
    for item in world.items:
        splits[item.split] = splits.get(item.split, 0) + 1
        for fact_id in item.fact_ids:
            assert fact_id in world.facts
    assert splits == {"train": 36, "holdout": 16, "staleness": 5, "unanswerable": 4}
    assert world.meta["freeze_date"] == "2026-03-01"
    assert len(world.facts) == 21
    assert world.doc_count == 12
