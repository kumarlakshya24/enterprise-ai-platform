from __future__ import annotations

from conduit.models import Incoming
from conduit.pipeline import Conduit
from conduit.synthetic import demo_events


def _load(conduit: Conduit, events: list[Incoming] | None = None) -> None:
    conduit.ingest(events if events is not None else demo_events())
    conduit.consume()


def test_update_reuses_unchanged_chunks_and_ignores_a_stale_version(conduit: Conduit) -> None:
    _load(conduit)
    calls, reused = conduit.store.embed_totals()
    assert reused > 0
    assert calls > reused
    versions = conduit.store.model_versions(conduit.store.active().id)
    assert versions == {"emb-v1"}
    # An older event for a document that is already at v2 does not rewrite it.
    conduit.ingest(
        [
            Incoming(
                "stale-leave",
                "upsert",
                "handbook-leave",
                1,
                "Annual leave",
                "this would roll the policy backwards",
                (),
                "2026-11-02T15:09:00+00:00",
            )
        ]
    )
    conduit.consume()
    assert conduit.store.doc_version(conduit.store.active().id, "handbook-leave") == 2


def test_poison_is_quarantined_and_not_searchable(conduit: Conduit) -> None:
    _load(conduit)
    assert conduit.status()["quarantine"] == 1
    assert "poison-1" not in conduit.store.doc_ids(conduit.store.active().id)
    hits = conduit.search("Unreadable detector", k=3)["hits"]
    assert isinstance(hits, list)
    assert all(hit["doc_id"] != "poison-1" for hit in hits)


def test_search_uses_only_the_active_model(conduit: Conduit) -> None:
    _load(conduit)
    found = conduit.search("mileage reimbursement receipt", k=1)
    hits = found["hits"]
    assert isinstance(hits, list)
    assert hits[0]["doc_id"] == "handbook-expenses"
    assert found["model_version"] == "emb-v1"
    conduit.start_migration("emb-v2")
    try:
        conduit.swap()
    except Exception as exc:
        assert "not caught up" in str(exc)
    else:
        raise AssertionError("swap must fail while the shadow is behind")
    while conduit.store.migration().state == "dual_writing":
        conduit.migration_step(limit=20)
    conduit.swap()
    found = conduit.search("mileage reimbursement receipt", k=1)
    assert found["model_version"] == "emb-v2"
    assert found["generation"] == "green"
    hits = found["hits"]
    assert isinstance(hits, list)
    assert hits[0]["doc_id"] == "handbook-expenses"
    versions = conduit.store.model_versions(conduit.store.active().id)
    assert versions == {"emb-v2"}


def test_dual_write_keeps_a_new_event_in_both_generations_once_caught_up(conduit: Conduit) -> None:
    _load(conduit)
    conduit.start_migration("emb-v2")
    while conduit.store.migration().state == "dual_writing":
        conduit.migration_step(limit=20)
    assert conduit.store.migration().state == "ready_to_swap"
    conduit.ingest(
        [
            Incoming(
                "during-migration",
                "upsert",
                "runbook-rollback",
                1,
                "Rollback runbook",
                "Roll back the canary if error budget burn exceeds the page threshold for ten minutes.",
                (),
                "2026-11-02T16:00:00+00:00",
            )
        ]
    )
    conduit.consume()
    assert conduit.store.migration().state == "ready_to_swap"
    active = conduit.store.active()
    shadow_id = conduit.store.migration().target_id
    assert shadow_id is not None
    assert "runbook-rollback" in conduit.store.doc_ids(active.id)
    assert "runbook-rollback" in conduit.store.doc_ids(shadow_id)
    active_vec = next(row for row in conduit.store.iter_vectors(active.id) if row[0] == "runbook-rollback")
    shadow_vec = next(row for row in conduit.store.iter_vectors(shadow_id) if row[0] == "runbook-rollback")
    assert active_vec[4] != shadow_vec[4]


def test_rollback_restores_the_previous_model(conduit: Conduit) -> None:
    _load(conduit)
    conduit.start_migration("emb-v2")
    while conduit.store.migration().state == "dual_writing":
        conduit.migration_step(limit=20)
    conduit.swap()
    conduit.rollback()
    alias = conduit.status()["alias"]
    assert isinstance(alias, dict)
    assert alias["name"] == "blue"
    assert alias["model_version"] == "emb-v1"


def test_forget_then_replay_and_rebuild_do_not_restore_ava(conduit: Conduit) -> None:
    _load(conduit)
    before = conduit.search("ava.chen@northwind.example", k=3)
    before_hits = before["hits"]
    assert isinstance(before_hits, list)
    assert any(hit["doc_id"] == "ticket-441" for hit in before_hits)
    proof = conduit.forget("subj-ava-chen")
    assert proof["verified"] is True
    assert proof["remaining_chunks"] == 0
    assert proof["email_in_chunks"] == 0
    assert proof["email_in_log"] == 0
    assert proof["name_in_log"] == 0
    assert conduit.store.subject_chunk_count("subj-ava-chen") == 0
    # Leo's half of the mixed ticket is still there.
    assert conduit.store.subject_chunk_count("subj-leo-martinez") > 0
    conduit.replay()
    assert conduit.store.subject_chunk_count("subj-ava-chen") == 0
    assert conduit.store.count_like("ava.chen@northwind.example") == {"chunks": 0, "events": 0, "docs": 0}
    conduit.start_migration("emb-v2")
    while conduit.store.migration().state == "dual_writing":
        conduit.migration_step(limit=20)
    conduit.swap()
    assert conduit.store.subject_chunk_count("subj-ava-chen") == 0
    after = conduit.search("ava.chen@northwind.example", k=3)
    after_hits = after["hits"]
    assert isinstance(after_hits, list)
    assert all(hit["doc_id"] != "ticket-441" for hit in after_hits)
    assert "ticket-441" not in conduit.store.doc_ids(conduit.store.active().id)


def test_second_forget_is_idempotent(conduit: Conduit) -> None:
    _load(conduit)
    first = conduit.forget("subj-jonas-berg")
    second = conduit.forget("subj-jonas-berg")
    assert first == second
    assert first["verified"] is True


def test_replay_does_not_double_chunks(conduit: Conduit) -> None:
    _load(conduit)
    generation = conduit.store.active().id
    before, _docs = conduit.store.generation_counts(generation)
    calls, _reused = conduit.store.embed_totals()
    conduit.replay()
    after, _docs_after = conduit.store.generation_counts(generation)
    calls_after, _reused_after = conduit.store.embed_totals()
    assert after == before
    assert calls_after == calls


def test_api_happy_path(client: object) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    assert client.get("/healthz").json() == {"ok": True}
    loaded = client.post("/api/ingest", json={"script": "demo"})
    assert loaded.status_code == 200
    consumed = client.post("/api/consume", json={})
    assert consumed.status_code == 200
    body = consumed.json()
    assert body["lag_events"] == 0
    assert body["quarantine"] == 1
    assert body["preview"]["doc_id"] == "ticket-441"
    assert "ava.chen@" not in body["preview"]["redacted"]
    early = client.post("/api/swap")
    assert early.status_code == 409
    started = client.post("/api/migration/start", json={"model_version": "emb-v2"})
    assert started.status_code == 200
    for _ in range(10):
        stepped = client.post("/api/migration/step", json={"limit": 20})
        assert stepped.status_code == 200
        if stepped.json()["migration"]["state"] == "ready_to_swap":
            break
    swapped = client.post("/api/swap")
    assert swapped.status_code == 200
    assert swapped.json()["alias"]["model_version"] == "emb-v2"
    found = client.get("/api/search", params={"q": "mileage reimbursement receipt"})
    assert found.status_code == 200
    assert found.json()["hits"][0]["doc_id"] == "handbook-expenses"
    forgotten = client.post("/api/forget", json={"subject_id": "subj-ava-chen"})
    assert forgotten.status_code == 200
    assert forgotten.json()["proof"]["verified"] is True
    assert forgotten.json()["proof"]["remaining_chunks"] == 0
    rolled = client.post("/api/rollback")
    assert rolled.status_code == 200
    assert rolled.json()["alias"]["model_version"] == "emb-v1"
    assert client.get("/api/search", params={"q": "Ava Chen"}).json()["hits"] == [] or all(
        hit["doc_id"] != "ticket-441"
        for hit in client.get("/api/search", params={"q": "Ava Chen"}).json()["hits"]
    )
