"""The saved evaluation. Functional numbers are deterministic. Latency is measured."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conduit.embedder import FakeEmbedder
from conduit.metrics import lag_summary
from conduit.pipeline import ROOT, Conduit
from conduit.redact import InProcessRedactor
from conduit.synthetic import eval_phases, recall_queries

REPORTS = ROOT / "reports"


def run_eval(db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(db_path) if db_path is not None else REPORTS / "eval.db"
    if path.exists():
        path.unlink()
    conduit = Conduit(path, embedder=FakeEmbedder(), redactor=InProcessRedactor())
    try:
        phases = eval_phases()
        conduit.reset()
        conduit.ingest(phases["initial"])
        conduit.consume()
        after_initial_calls, after_initial_reused = conduit.store.embed_totals()
        recall = _recall(conduit, recall_queries())

        conduit.ingest(phases["updates"])
        conduit.consume()
        calls_now, reused_now = conduit.store.embed_totals()
        update_calls = calls_now - after_initial_calls
        update_reused = reused_now - after_initial_reused

        conduit.ingest(phases["deletes"])
        conduit.ingest(phases["poison"])
        conduit.consume()

        quarantine = len(conduit.store.quarantine_rows())
        poison_indexed = sum(
            1 for index in range(3) if f"poison-{index}" in conduit.store.doc_ids(conduit.store.active().id)
        )

        active = conduit.store.active()
        versions = conduit.store.model_versions(active.id)
        one_space = versions <= {active.model_version}

        projection = conduit.projection()
        measured = projection["usd_per_million_docs"]
        assert isinstance(measured, dict)

        # Migration re-embeds every surviving chunk under the new salt. Cache hits
        # across model versions would mean we mixed two spaces.
        calls_before, reused_before = conduit.store.embed_totals()
        conduit.start_migration("emb-v2")
        while conduit.store.migration().state == "dual_writing":
            conduit.migration_step(limit=100)
        calls_after, reused_after = conduit.store.embed_totals()
        migration_calls = calls_after - calls_before
        migration_reused = reused_after - reused_before
        shadow_id = conduit.store.migration().target_id
        assert shadow_id is not None
        shadow_chunks, _shadow_docs = conduit.store.generation_counts(shadow_id)
        conduit.swap()
        swapped = conduit.store.active()
        recall_after = _recall(conduit, recall_queries())
        swapped_versions = conduit.store.model_versions(swapped.id)

        proofs = [conduit.forget(subject_id) for subject_id in ("subj-ava-chen", "subj-mina-okonkwo")]
        remaining = 0
        for proof in proofs:
            left = proof["remaining_chunks"]
            if isinstance(left, bool) or not isinstance(left, int):
                raise RuntimeError("proof remaining_chunks was not an int")
            remaining += left
        # Rebuild a generation from the scrubbed log. This is the replay that
        # would resurrect a person if the log still held their text.
        conduit.start_migration("emb-v1")
        while conduit.store.migration().state == "dual_writing":
            conduit.migration_step(limit=200)
        conduit.swap()
        rebuilt = conduit.store.active()
        resurrected = conduit.store.subject_chunk_count("subj-ava-chen") + conduit.store.subject_chunk_count(
            "subj-mina-okonkwo"
        )
        email_back = conduit.store.count_like("ava.chen@northwind.example")
        ava_doc = "doc-20" in conduit.store.doc_ids(rebuilt.id)
        mixed = conduit.store.subject_chunk_count("subj-leo-martinez", rebuilt.id)

        lag = lag_summary(conduit.store.lag_values())
        chars, docs = conduit.store.embedded_chars(rebuilt.id)
        gates = {
            "recall_at_1_before": recall == 1.0,
            "recall_at_1_after_swap": recall_after == 1.0,
            "update_reused_two_thirds": update_reused == 60 and update_calls == 30,
            "one_model_per_generation": one_space and swapped_versions <= {swapped.model_version},
            "migration_embeds_each_new_hash_once": migration_calls == (180 * 3) + 30
            and migration_reused == 60,
            "shadow_keeps_surviving_chunks": shadow_chunks == (180 - 8) * 3,
            "poison_quarantined": quarantine == 3 and poison_indexed == 0,
            "rtbf_remaining_zero": remaining == 0 and all(proof["verified"] is True for proof in proofs),
            "rebuild_did_not_resurrect": resurrected == 0
            and email_back["chunks"] == 0
            and email_back["events"] == 0
            and not ava_doc,
            "mixed_doc_kept_the_other_person": mixed > 0,
            "lag_ordered": float(lag["p50"]) <= float(lag["p95"]) <= float(lag["p99"]),
            "lag_p95_under_100ms": float(lag["p95"]) < 100.0,
        }
        small = measured.get("text-embedding-3-small")
        report: dict[str, Any] = {
            "seed": 17,
            "embedder": "fake-hash",
            "docs_initial": 180,
            "chunks_per_doc": 3,
            "embed_calls_initial": after_initial_calls,
            "embed_reused_initial": after_initial_reused,
            "update_docs": 30,
            "embed_calls_on_updates": update_calls,
            "embed_reused_on_updates": update_reused,
            "reuse_rate_on_updates": round(update_reused / (update_reused + update_calls), 4),
            "recall_at_1": recall,
            "recall_at_1_after_swap": recall_after,
            "labeled_queries": 20,
            "migration_embed_calls": migration_calls,
            "migration_chunks": shadow_chunks,
            "swapped_model": swapped.model_version,
            "quarantine": quarantine,
            "poison_indexed": poison_indexed,
            "rtbf_subjects": 2,
            "migration_reused": migration_reused,
            "rtbf_remaining_chunks": remaining,
            "rtbf_verified": all(proof["verified"] is True for proof in proofs),
            "resurrected_links_after_rebuild": resurrected,
            "exclusive_doc_absent_after_rebuild": not ava_doc,
            "lag_ms": lag,
            "embedded_chars_after_rebuild": chars,
            "docs_after_rebuild": docs,
            "tokens_per_doc": projection["tokens_per_doc"],
            "usd_per_million_docs": measured,
            "scaled_usd_per_million_docs": projection["scaled_usd_per_million_docs"],
            "cost_label": "illustrative list price, not an invoice",
            "usd_per_million_docs_small": small,
            "gates": gates,
            "gates_pass": all(gates.values()),
        }
        return report
    finally:
        conduit.close()
        if path.exists() and path.name == "eval.db":
            path.unlink()


def write_reports(report: dict[str, Any]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "eval.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (REPORTS / "eval.md").write_text(_markdown(report), encoding="utf-8")


def _recall(conduit: Conduit, pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    hits = 0
    for query, doc_id in pairs:
        found = conduit.search(query, k=1)["hits"]
        assert isinstance(found, list)
        if found and found[0]["doc_id"] == doc_id:
            hits += 1
    return hits / len(pairs)


def _markdown(report: dict[str, Any]) -> str:
    lag = report["lag_ms"]
    prices = report["usd_per_million_docs"]
    scaled = report["scaled_usd_per_million_docs"]
    lines = [
        "# Conduit eval",
        "",
        f"Seed `{report['seed']}`, embedder `{report['embedder']}`. "
        "Latency is measured on this machine. Prices are list-price projections.",
        "",
        "| Check | Result |",
        "| --- | --- |",
        f"| Recall@1 on 20 planted keywords, before swap | {report['recall_at_1']:.0%} |",
        f"| Recall@1 after swap to emb-v2 | {report['recall_at_1_after_swap']:.0%} |",
        f"| Update reuse (30 docs, 2 of 3 chunks unchanged) | {report['embed_reused_on_updates']} reused, {report['embed_calls_on_updates']} embedded |",
        f"| Migration embed calls / shadow chunks | {report['migration_embed_calls']} / {report['migration_chunks']} |",
        f"| Poison events quarantined / indexed | {report['quarantine']} / {report['poison_indexed']} |",
        f"| RTBF remaining subject links | {report['rtbf_remaining_chunks']} |",
        f"| Links after a full rebuild from the scrubbed log | {report['resurrected_links_after_rebuild']} |",
        f"| Apply latency p50 / p95 / p99 | {lag['p50']} / {lag['p95']} / {lag['p99']} ms (n={lag['n']}) |",
        f"| Measured $/M docs, text-embedding-3-small | {prices['text-embedding-3-small']} |",
        f"| Measured $/M docs, text-embedding-3-large | {prices['text-embedding-3-large']} |",
        f"| Short memo (2,000 tokens) $/M docs, small model | {scaled['short_memo']['text-embedding-3-small']} |",
        f"| Ten-page policy (8,000 tokens) $/M docs, small model | {scaled['ten_page_policy']['text-embedding-3-small']} |",
        f"| Gates | {'PASS' if report['gates_pass'] else 'FAIL'} |",
        "",
        "The measured per-document token count is `chars/4` on this synthetic corpus, "
        "which is a few short paragraphs. The memo and ten-page rows hold the token count "
        "fixed and apply the same list price. They are not a measurement of those documents.",
        "",
    ]
    return "\n".join(lines)
