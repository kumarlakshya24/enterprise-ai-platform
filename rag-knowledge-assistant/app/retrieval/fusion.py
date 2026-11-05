"""Rank fusion for hybrid search.

* rrf      - weighted Reciprocal Rank Fusion: Σ w_i / (k + rank_i). Scale-free, robust
             to the very different score ranges of cosine and BM25. Default.
* weighted - weighted sum of min-max normalised scores. Sensitive to outliers but
             lets a very strong exact-match BM25 score dominate.
"""

from __future__ import annotations

from app.models import Candidate


def fuse(
    result_lists: dict[str, list[Candidate]],
    weights: dict[str, float],
    method: str = "rrf",
    rrf_k: int = 60,
    stage: str = "fused",
) -> list[Candidate]:
    pool: dict[str, Candidate] = {}
    fused: dict[str, float] = {}
    for name, results in result_lists.items():
        w = weights.get(name, 1.0)
        if not results or w == 0:
            continue
        if method == "weighted":
            hi, lo = max(r.score for r in results), min(r.score for r in results)
            span = (hi - lo) or 1.0
        for r in results:
            rank = r.ranks.get(name) or results.index(r) + 1
            contrib = w / (rrf_k + rank) if method == "rrf" else w * (r.score - lo) / span
            fused[r.chunk_id] = fused.get(r.chunk_id, 0.0) + contrib
            if r.chunk_id in pool:
                pool[r.chunk_id].ranks.update(r.ranks)
                pool[r.chunk_id].scores.update(r.scores)
            else:
                pool[r.chunk_id] = r
    ordered = sorted(pool.values(), key=lambda c: -fused[c.chunk_id])
    for i, c in enumerate(ordered):
        c.score = fused[c.chunk_id]
        c.scores[stage] = c.score
        c.ranks[stage] = i + 1
    return ordered
