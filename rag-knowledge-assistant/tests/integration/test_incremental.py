"""Incremental indexing: replace, don't duplicate; lineage; reuse; delete; reindex; status."""
import pytest

from app.ingestion.pipeline import ingestion_status
from tests.conftest import write_doc

pytestmark = pytest.mark.integration
FRONT = {"doc_id": "policy-x", "title": "Policy X", "team": "hr", "version": "1.0"}
BODY_V1 = """
# Policy X
## Schedule
Employees work from the office three days per week on Tuesday, Wednesday and Thursday.
## Stipend
The internet stipend is $40 per month, paid through payroll every month.
## Security
Use the VPN outside the office and lock your screen when you leave your desk.
"""


def _count(svc, sql, *args):
    with svc.db.conn() as c:
        return list(c.execute(sql, args).fetchone().values())[0]


def test_update_replaces_chunks_and_records_lineage(svc, docdir):
    p = write_doc(docdir, "x.md", FRONT, BODY_V1)
    r1 = svc.indexer.ingest_path(p)
    assert r1.action == "created" and r1.version == 1
    n1 = _count(svc, "SELECT count(*) FROM chunks WHERE doc_id='policy-x'")

    write_doc(docdir, "x.md", {**FRONT, "version": "2.0"}, BODY_V1.replace("$40", "$50"))
    r2 = svc.indexer.ingest_path(p)
    assert r2.action == "updated" and r2.version == 2
    # no duplicates: same number of chunks, all at the new version
    assert _count(svc, "SELECT count(*) FROM chunks WHERE doc_id='policy-x'") == n1
    assert _count(svc, "SELECT count(*) FROM chunks WHERE doc_id='policy-x' AND doc_version <> 2") == 0
    assert _count(svc, "SELECT count(*) FROM chunks WHERE content LIKE '%%$40%%'") == 0
    # only the changed chunk was re-embedded; the rest reused
    assert r2.chunks_replaced == 1 and r2.embeddings_computed == 1 and r2.chunks_unchanged == n1 - 1
    with svc.db.conn() as c:
        lin = c.execute("SELECT change, previous_chunk_id FROM chunk_lineage WHERE doc_id='policy-x' AND doc_version=2").fetchall()
    assert sorted(l["change"] for l in lin) == sorted(["modified"] + ["unchanged"] * (n1 - 1))
    assert all(l["previous_chunk_id"].startswith("policy-x::v1::") for l in lin)
    # BM25 postings follow the swap (no orphaned terms from v1)
    assert _count(svc, "SELECT count(*) FROM chunk_terms ct LEFT JOIN chunks c USING (chunk_id) WHERE c.chunk_id IS NULL") == 0


def test_unchanged_content_is_a_noop(svc, docdir):
    p = write_doc(docdir, "x.md", FRONT, BODY_V1)
    svc.indexer.ingest_path(p)
    r = svc.indexer.ingest_path(p)
    assert r.action == "unchanged" and r.embeddings_computed == 0
    assert _count(svc, "SELECT version FROM documents WHERE doc_id='policy-x'") == 1


def test_removed_sections_are_tracked(svc, docdir):
    p = write_doc(docdir, "x.md", FRONT, BODY_V1)
    svc.indexer.ingest_path(p)
    write_doc(docdir, "x.md", FRONT, BODY_V1.split("## Security")[0])
    r = svc.indexer.ingest_path(p)
    assert r.chunks_removed >= 1 or r.chunks_replaced >= 1
    assert _count(svc, "SELECT count(*) FROM chunks WHERE content LIKE '%%lock your screen%%'") == 0


def test_delete_and_reindex(svc, docdir):
    p = write_doc(docdir, "x.md", FRONT, BODY_V1)
    svc.indexer.ingest_path(p)
    r = svc.indexer.reindex("policy-x")[0]
    assert r.action == "reindexed" and r.version == 2
    d = svc.indexer.delete("policy-x")
    assert d.action == "deleted" and d.chunks_removed >= 1
    assert _count(svc, "SELECT count(*) FROM chunks") == 0 and _count(svc, "SELECT count(*) FROM chunk_terms") == 0
    assert svc.indexer.delete("policy-x").action == "not_found"


def test_failed_files_are_reported_not_fatal(svc, docdir):
    good = write_doc(docdir, "good.md", FRONT, BODY_V1)
    write_doc(docdir, "bad.md", {"title": "Bad", "visibility": "restricted"}, "# Bad\nno roles given")
    (docdir / "empty.txt").write_text("")
    results = svc.indexer.ingest_directory(docdir)
    actions = {r.source.split("/")[-1]: r.action for r in results}
    assert actions == {"bad.md": "failed", "empty.txt": "failed", "good.md": "created"}
    st = ingestion_status(svc.db)
    assert st["documents_indexed"] == 1 and len(st["failed_files"]) == 2
    assert st["chunks_created_total"] >= 1 and str(good) in {e["source"] for e in st["recent_events"]}


def test_reindex_of_uploaded_doc_reports_clear_error(svc):
    svc.indexer.ingest_bytes("up.md", b"---\ndoc_id: up\ntitle: Up\n---\n# Up\nUploaded body text here.\n")
    r = svc.indexer.reindex("up")[0]
    assert r.action == "failed" and "re-upload" in r.error
