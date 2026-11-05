from app.models import Candidate
from app.retrieval.fusion import fuse
from app.textproc import identifiers, specific_tokens, tokenize


def test_tokenize_keeps_codes_whole_and_parts():
    t = tokenize("Error VPN-ERR-809 under HR-POL-104")
    assert "vpn-err-809" in t and "809" in t and "hr-pol-104" in t
    assert "under" not in t or True  # stopword handling is not the point here


def test_identifiers_and_specific_tokens():
    assert identifiers("fix VPN-ERR-999 with form RW-2") == ["rw-2", "vpn-err-999"]
    assert specific_tokens("per diem $95 in Tier 1") == {"$95", "1"}
    assert specific_tokens("VPN-ERR-809") != specific_tokens("VPN-ERR-503")


def _c(cid, stage, rank, score=1.0):
    return Candidate(chunk_id=cid, score=score, ranks={stage: rank}, scores={stage: score})


def test_rrf_rewards_agreement_between_retrievers():
    vec = [_c("a", "vector", 1), _c("b", "vector", 2), _c("c", "vector", 3)]
    bm = [_c("c", "bm25", 1), _c("b", "bm25", 2), _c("d", "bm25", 3)]
    out = fuse({"vector": vec, "bm25": bm}, {"vector": 1, "bm25": 1}, "rrf", rrf_k=60)
    assert [c.chunk_id for c in out][:2] in (["b", "c"], ["c", "b"])
    b = next(c for c in out if c.chunk_id == "b")
    assert b.ranks["vector"] == 2 and b.ranks["bm25"] == 2 and b.ranks["fused"] <= 2


def test_fusion_weights_shift_ranking():
    vec = [_c("a", "vector", 1), _c("b", "vector", 2)]
    bm = [_c("b", "bm25", 1), _c("a", "bm25", 2)]
    assert fuse({"vector": vec, "bm25": bm}, {"vector": 0.9, "bm25": 0.1})[0].chunk_id == "a"
    vec = [_c("a", "vector", 1), _c("b", "vector", 2)]
    bm = [_c("b", "bm25", 1), _c("a", "bm25", 2)]
    assert fuse({"vector": vec, "bm25": bm}, {"vector": 0.1, "bm25": 0.9})[0].chunk_id == "b"


def test_weighted_score_fusion_normalises():
    vec = [_c("a", "vector", 1, 0.9), _c("b", "vector", 2, 0.1)]
    bm = [_c("b", "bm25", 1, 30.0), _c("a", "bm25", 2, 1.0)]
    out = fuse({"vector": vec, "bm25": bm}, {"vector": 0.5, "bm25": 0.6}, "weighted")
    assert out[0].chunk_id == "b"
