"""Semantic cache: hit, scope isolation, specificity guard, invalidation on document change."""

import numpy as np
import pytest

from app.models import Principal
from tests.conftest import write_doc

pytestmark = pytest.mark.integration
ALICE = Principal("alice", "finance", ["employee", "analyst"])
BOB = Principal("bob", "sales", ["employee"])


def _vec(seed):
    v = np.random.default_rng(seed).normal(size=384).astype(np.float32)
    return v / np.linalg.norm(v)


def test_hit_miss_partition_and_guard(svc):
    cache = svc.cache
    part_a = cache.partition(ALICE.scope_key(), "full_cached", None)
    part_b = cache.partition(BOB.scope_key(), "full_cached", None)
    v = _vec(1)
    cache.store(
        v, "What does VPN-ERR-809 mean?", part_a, {"answer": "cert expired", "refused": False, "citations": []}, ["vpn"]
    )
    hit = cache.lookup(v, "What does VPN-ERR-809 mean?", part_a)
    assert hit and hit.answer["answer"] == "cert expired" and hit.similarity > 0.99
    assert cache.lookup(v, "What does VPN-ERR-809 mean?", part_b) is None  # other access scope
    assert cache.lookup(v, "What does VPN-ERR-503 mean?", part_a) is None  # specificity guard
    assert cache.lookup(_vec(2), "unrelated", part_a) is None  # below threshold
    s = cache.stats()
    assert s["hits"] == 1 and s["misses"] == 3 and s["guard_rejects"] == 1


def test_invalidation_by_document_and_refusals_on_any_change(svc):
    cache = svc.cache
    part = cache.partition(ALICE.scope_key(), "full_cached", None)
    cache.store(_vec(3), "q about vpn", part, {"answer": "a", "refused": False, "citations": []}, ["vpn"])
    cache.store(_vec(4), "q about pto", part, {"answer": "b", "refused": False, "citations": []}, ["pto"])
    cache.store(_vec(5), "q about dogs", part, {"answer": "not found", "refused": True, "citations": []}, [])
    assert cache.invalidate_docs(["vpn"]) == 2  # the vpn answer + the corpus-dependent refusal
    assert cache.lookup(_vec(3), "q about vpn", part) is None
    assert cache.lookup(_vec(5), "q about dogs", part) is None
    assert cache.lookup(_vec(4), "q about pto", part) is not None


def test_end_to_end_update_invalidates_cached_answer(svc, docdir):
    front = {"doc_id": "office-days", "title": "Office Days", "team": "hr"}
    p = write_doc(
        docdir, "o.md", front, "# Office Days\n## Schedule\nEmployees work in the office three anchor days per week."
    )
    svc.indexer.ingest_path(p)
    q = "How many anchor days per week in the office?"
    first = svc.ask(q, ALICE, "full_cached")
    assert not first.cache["hit"] and "three" in first.answer
    assert svc.ask(q, ALICE, "full_cached").cache["hit"]
    write_doc(
        docdir, "o.md", front, "# Office Days\n## Schedule\nEmployees work in the office two anchor days per week."
    )
    svc.indexer.ingest_path(p)  # fires on_change -> cache invalidation
    after = svc.ask(q, ALICE, "full_cached")
    assert not after.cache["hit"] and "two" in after.answer and "three" not in after.answer
