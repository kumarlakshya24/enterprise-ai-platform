"""Same questions, four different memories."""

from __future__ import annotations

from arena.world import World


def _text(world: World, arm: str, item_id: str, as_of: str = "current") -> str:
    item = world.by_id[item_id]
    if arm == "prompt":
        return world.prompt.answer(item.question).text
    if arm == "lora":
        return world.lora.answer(item.question).text
    if arm == "distilled":
        return world.distilled.answer(item.question).text
    rag = world.rag_freeze if as_of == "freeze" else world.rag_current
    return rag.answer(item.question).text


def test_prompt_knows_public_facts_and_refuses_the_runbook(world: World) -> None:
    assert "billing operations console" in _text(world, "prompt", "ho-product-what")
    assert world.prompt.answer(world.by_id["ho-product-what"].question).citations == []
    for item in world.items:
        if item.split == "train":
            continue
        if any(world.facts[fact_id].visibility == "internal" for fact_id in item.fact_ids) or item.refuse:
            assert world.prompt.answer(item.question).refused, item.id


def test_rag_cites_the_current_policy_and_the_freeze_policy(world: World) -> None:
    item = world.by_id["st-refund-window"]
    current = world.rag_current.answer(item.question)
    frozen = world.rag_freeze.answer(item.question)
    assert "30 days" in current.text and "14 days" not in current.text
    assert "14 days" in frozen.text and "30 days" not in frozen.text
    assert current.citations[0]["doc_id"] == "billing-refunds"
    assert current.citations[0]["section"] == "Window"
    added = world.rag_current.answer(world.by_id["st-webhook"].question)
    assert "X-Harborline-Signature" in added.text
    assert any(row["doc_id"] == "webhooks" for row in added.citations)
    assert world.rag_freeze.answer(world.by_id["st-webhook"].question).refused


def test_adapter_memorizes_train_wording_and_goes_stale(world: World) -> None:
    window = world.lora.answer(world.by_id["st-refund-window"].question)
    assert "14 days" in window.text
    assert "30 days" not in window.text
    assert window.citations == []
    courtesy = world.lora.answer(world.by_id["ho-credit"].question)
    assert courtesy.refused
    assert "50 USD" not in courtesy.text
    assert "50 USD" in world.rag_current.answer(world.by_id["ho-credit"].question).text
    assert world.lora.answer(world.by_id["st-webhook"].question).refused
    assert "every 30 minutes" in world.lora.answer(world.by_id["ho-bridge"].question).text
    assert "VAT reverse charge" in world.lora.answer(world.by_id["ho-vat"].question).text


def test_student_drops_long_procedures_and_one_off_facts(world: World) -> None:
    assert world.distilled.answer(world.by_id["ho-bridge"].question).refused
    assert world.distilled.answer(world.by_id["ho-cutover"].question).refused
    assert world.distilled.answer(world.by_id["ho-vat"].question).refused
    assert world.distilled.answer(world.by_id["ho-sandbox"].question).refused
    kept = world.distilled.answer(world.by_id["ho-refund-method"].question)
    assert "original payment method" in kept.text
    assert "incident.bridge" in world.pipeline_public()["dropped_long"]
    assert "tax.vat" in world.pipeline_public()["dropped_low_count"]
    assert "webhook.sign" in world.pipeline_public()["unseen_at_train"]
    assert len(world.lora.facts) == 19
    assert len(world.distilled.facts) == 15


def test_unanswerable_questions_do_not_leak_a_fact(world: World) -> None:
    phrases = [fact.include for fact in world.facts.values()]
    for item in world.items:
        if not item.refuse:
            continue
        for answer in (
            world.prompt.answer(item.question),
            world.rag_current.answer(item.question),
            world.lora.answer(item.question),
            world.distilled.answer(item.question),
        ):
            assert answer.refused, (item.id, answer.arm)
            folded = answer.text.casefold()
            assert not any(phrase.casefold() in folded for phrase in phrases)


def test_memory_is_built_from_the_train_split_only(world: World) -> None:
    assert set(world.lora.facts) == {fact_id for fact_id, count in world.train_counts.items() if count >= 1}
    assert set(world.distilled.facts) == {
        fact_id
        for fact_id, fact in world.facts.items()
        if world.train_counts.get(fact_id, 0) >= 2 and fact.length == "short"
    }
    assert "webhook.sign" not in world.lora.facts
    assert "dunning.retry" not in world.distilled.facts
    for groups in world.lora.question_tokens.values():
        assert groups
