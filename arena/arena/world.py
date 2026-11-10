"""Load the frozen bench once. Training the stub is part of loading."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arena.arms import ARMS, Memory, RetrieverArm, build_adapter, build_student, train_counts
from arena.corpus import Fact, Item, corpus_sha256, load_facts, load_questions
from arena.costing import model_latency_ms, per_request_usd, serving_stub
from arena.ports import build_local_rag
from arena.retrieve import Index, chunks_for
from arena.settings import Settings


@dataclass(slots=True)
class World:
    settings: Settings
    meta: dict[str, str]
    facts: dict[str, Fact]
    items: list[Item]
    by_id: dict[str, Item]
    train_counts: dict[str, int]
    policy: dict[str, Any]
    price: dict[str, Any]
    scenarios: list[dict[str, Any]]
    prompt: RetrieverArm
    rag_freeze: RetrieverArm
    rag_current: RetrieverArm
    lora: Memory
    distilled: Memory
    sha: str
    doc_count: int
    train_adapter_ms: float
    train_student_ms: float
    per_request: dict[str, float]
    model_latency: dict[str, float]
    serving: dict[str, dict[str, str]]

    def pipeline_public(self) -> dict[str, Any]:
        long_ids = sorted(fact_id for fact_id, fact in self.facts.items() if fact.length == "long")
        rare_ids = sorted(fact_id for fact_id, count in self.train_counts.items() if count == 1)
        unseen = sorted(fact_id for fact_id in self.facts if self.train_counts.get(fact_id, 0) == 0)
        return {
            "freeze_date": self.meta["freeze_date"],
            "teacher": (
                "Train pairs are the train split. Each pair carries the fact ids marked on the "
                "freeze corpus. Holdout labels are not read."
            ),
            "adapter_fact_ids": sorted(self.lora.facts),
            "student_fact_ids": sorted(self.distilled.facts),
            "dropped_long": long_ids,
            "dropped_low_count": rare_ids,
            "unseen_at_train": unseen,
            "lumen": "POST /ask shape, offline stub unless ARENA_LUMEN_URL is set",
            "switchboard": "catalog model per arm, offline stub unless ARENA_SWITCHBOARD_URL is set",
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a mapping")
    return loaded


def load_world(settings: Settings | None = None) -> World:
    settings = settings or Settings.from_env()
    data = settings.data_dir
    facts = load_facts(data / "corpus")
    meta, items = load_questions(data / "questions.yaml")
    fact_map = {fact.id: fact for fact in facts}
    unknown = sorted({fact_id for item in items for fact_id in item.fact_ids} - set(fact_map))
    if unknown:
        raise ValueError(f"questions cite unknown facts {unknown}")
    policy = _load_yaml(data / "policy.yaml")
    price = _load_yaml(data / "price_card.yaml")
    scenario_file = _load_yaml(data / "scenarios.yaml")
    scenarios = list(scenario_file["scenarios"])
    counts = train_counts(items)
    min_overlap = int(policy["min_overlap"])

    started = time.perf_counter()
    adapter = build_adapter(items, fact_map, counts, policy)
    adapter_ms = round((time.perf_counter() - started) * 1000, 3)
    started = time.perf_counter()
    student = build_student(items, fact_map, counts, policy)
    student_ms = round((time.perf_counter() - started) * 1000, 3)

    prompt = RetrieverArm(
        "prompt",
        Index(chunks_for(facts, "freeze", visibility="public")),
        fact_map,
        min_overlap,
        cite=False,
    )
    rag_freeze = build_local_rag(Index(chunks_for(facts, "freeze")), fact_map, min_overlap)
    rag_current = build_local_rag(Index(chunks_for(facts, "current")), fact_map, min_overlap)

    return World(
        settings=settings,
        meta=meta,
        facts=fact_map,
        items=items,
        by_id={item.id: item for item in items},
        train_counts=counts,
        policy=policy,
        price=price,
        scenarios=scenarios,
        prompt=prompt,
        rag_freeze=rag_freeze,
        rag_current=rag_current,
        lora=adapter,
        distilled=student,
        sha=corpus_sha256(data),
        doc_count=len(list((data / "corpus").glob("*.md"))),
        train_adapter_ms=adapter_ms,
        train_student_ms=student_ms,
        per_request={arm: per_request_usd(arm, price) for arm in ARMS},
        model_latency={arm: model_latency_ms(arm, price) for arm in ARMS},
        serving=serving_stub(price),
    )
