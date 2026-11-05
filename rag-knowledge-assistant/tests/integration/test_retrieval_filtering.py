"""Retrieval (vector, BM25, hybrid) and pre-ranking filters (RBAC + audience)."""

import pytest

from app.models import Principal
from app.retrieval.filters import QueryFilters, build_where
from app.retrieval.search import bm25_search, vector_search
from tests.conftest import write_doc

pytestmark = pytest.mark.integration
ALICE = Principal("alice", "finance", ["employee", "analyst"])
BOB = Principal("bob", "sales", ["employee", "analyst"])
DAVE = Principal("dave", "hr", ["employee", "hr_admin"])


@pytest.fixture()
def corpus(svc, docdir):
    write_doc(
        docdir,
        "vpn.md",
        {"doc_id": "vpn", "title": "VPN Guide", "team": "it"},
        "# VPN Guide\n## Errors\nVPN-ERR-809 means the device certificate expired. Re-enroll in Company Portal.\n"
        "VPN-ERR-503 means the gateway is under maintenance on Sundays.",
    )
    write_doc(
        docdir,
        "fin.md",
        {"doc_id": "fin-remote", "title": "Finance Analyst Remote Work", "team": "finance", "audience": ["finance"]},
        "# Finance Analyst Remote Work\nFinance analysts may work remotely up to 4 days per week.",
    )
    write_doc(
        docdir,
        "sales.md",
        {"doc_id": "sales-remote", "title": "Sales Analyst Remote Work", "team": "sales", "audience": ["sales"]},
        "# Sales Analyst Remote Work\nSales operations analysts are remote-first and work from home.",
    )
    write_doc(
        docdir,
        "comp.md",
        {
            "doc_id": "comp",
            "title": "Compensation Bands",
            "team": "hr",
            "visibility": "restricted",
            "allowed_roles": ["hr_admin"],
        },
        "# Compensation Bands\nLevel L5 salary band ranges from $124,000 to $168,000.",
    )
    write_doc(
        docdir,
        "oncall.md",
        {"doc_id": "oncall", "title": "On-call Runbook", "team": "engineering", "visibility": "team"},
        "# On-call Runbook\nSEV1 pages must be acknowledged within 5 minutes.",
    )
    svc.indexer.ingest_directory(docdir)
    return svc


def _docs(cands):
    return [c.doc_id for c in cands]


def test_bm25_exact_code_lookup(corpus):
    where, params = build_where(None, None, enforce_acl=False)
    res = bm25_search(corpus.db, "VPN-ERR-809", 5, where, params)
    assert res and res[0].doc_id == "vpn" and res[0].scores["bm25"] > 0
    assert bm25_search(corpus.db, "zzzz unknownterm", 5, where, params) == []


def test_vector_search_returns_scored_candidates(corpus):
    where, params = build_where(None, None, enforce_acl=False)
    qv = corpus.embedder.embed(["certificate expired re-enroll company portal"])[0]
    res = vector_search(corpus.db, qv, 3, where, params)
    assert res[0].doc_id == "vpn" and res[0].scores["vector"] >= res[-1].scores["vector"]


@pytest.mark.parametrize("who,can_see", [(BOB, False), (ALICE, False), (DAVE, True)])
def test_restricted_docs_filtered_before_ranking(corpus, who, can_see):
    where, params = build_where(who, None, enforce_acl=True)
    qv = corpus.embedder.embed(["L5 salary band"])[0]
    found = set(_docs(vector_search(corpus.db, qv, 50, where, params))) | set(
        _docs(bm25_search(corpus.db, "L5 salary band", 50, where, params))
    )
    assert ("comp" in found) is can_see


def test_team_visibility(corpus):
    for who, ok in [(BOB, False), (Principal("frank", "engineering", ["employee"]), True)]:
        where, params = build_where(who, None, enforce_acl=True)
        assert ("oncall" in _docs(bm25_search(corpus.db, "SEV1 acknowledged", 10, where, params))) is ok


def test_audience_filter_removes_other_teams_policy(corpus):
    q = "remote work policy for analysts"
    for who, wanted, unwanted in [(ALICE, "fin-remote", "sales-remote"), (BOB, "sales-remote", "fin-remote")]:
        where, params = build_where(who, QueryFilters(audience_scope=True), enforce_acl=True)
        docs = _docs(bm25_search(corpus.db, q, 10, where, params))
        assert wanted in docs and unwanted not in docs


def test_full_pipeline_refuses_unauthorised_and_cites_authorised(corpus):
    r = corpus.ask("What is the L5 salary band?", BOB, "full", debug=True)
    assert r.refused and all(x["doc_id"] != "comp" for x in r.retrieved + r.candidates)
    r = corpus.ask("What is the L5 salary band?", DAVE, "full")
    assert not r.refused and r.citations[0]["doc_id"] == "comp" and "$124,000" in r.answer


def test_hybrid_profile_fuses_both_retrievers(corpus):
    r = corpus.ask("VPN-ERR-503 gateway", ALICE, "hybrid", debug=True)
    top = r.candidates[0]
    assert top["doc_id"] == "vpn" and "vector" in top["ranks"] and "bm25" in top["ranks"] and "fused" in top["ranks"]


def test_unsafe_profiles_are_marked():
    from app.service import UNSAFE_PROFILES

    assert {"baseline", "rerank", "hybrid", "multiquery", "filtered"} == UNSAFE_PROFILES
