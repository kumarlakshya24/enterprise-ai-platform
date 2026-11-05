"""First-stage retrieval: pgvector ANN and in-database BM25.

BM25 is computed in SQL over the `chunk_terms` inverted index:
    score(d, q) = Σ_t idf(t) · tf·(k1+1) / (tf + k1·(1 − b + b·|d|/avgdl))
    idf(t)      = ln(1 + (N − df + 0.5) / (df + 0.5))
Corpus statistics (N, avgdl, df) are global, so a user's scores do not depend on
which documents they can see (no side channel through IDF), while the candidate
set itself is ACL-filtered.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from app.db import Database
from app.models import Candidate
from app.textproc import tokenize

_COLS = """c.chunk_id, c.doc_id, d.title, c.team, c.content, c.heading_path, c.chunk_index, c.doc_version,
           d.version_label, c.injection_risk, c.pii_types, c.context_header"""


def _cand(row: dict, score: float, stage: str, rank: int) -> Candidate:
    return Candidate(
        chunk_id=row["chunk_id"],
        score=score,
        doc_id=row["doc_id"],
        title=row["title"],
        team=row["team"],
        content=row["content"],
        heading_path=list(row["heading_path"]),
        chunk_index=row["chunk_index"],
        doc_version=row["doc_version"],
        version_label=row["version_label"],
        injection_risk=row["injection_risk"],
        pii_types=list(row["pii_types"]),
        context_header=row["context_header"],
        ranks={stage: rank},
        scores={stage: score},
    )


def vector_search(
    db: Database, qvec: np.ndarray, k: int, where: str, params: dict, ef_search: int = 100
) -> list[Candidate]:
    sql = f"""SELECT {_COLS}, 1 - (c.embedding <=> %(qv)s) AS score
              FROM chunks c JOIN documents d USING (doc_id)
              WHERE {where}
              ORDER BY c.embedding <=> %(qv)s LIMIT %(k)s"""
    with db.conn() as conn, conn.transaction():
        conn.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
        # pgvector >= 0.8: keep scanning the graph until k rows pass the filter,
        # so restrictive ACL filters do not silently shrink recall.
        conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        rows = conn.execute(sql, {**params, "qv": np.asarray(qvec, dtype=np.float32), "k": k}).fetchall()
    rows.sort(key=lambda r: -r["score"])  # relaxed_order may return slightly out-of-order rows
    return [_cand(r, float(r["score"]), "vector", i + 1) for i, r in enumerate(rows)]


def bm25_search(
    db: Database, query: str, k: int, where: str, params: dict, k1: float = 1.2, b: float = 0.75
) -> list[Candidate]:
    q = Counter(tokenize(query))
    if not q:
        return []
    terms, qtf = list(q.keys()), list(q.values())
    sql = f"""
    WITH q AS (SELECT * FROM unnest(%(terms)s::text[], %(qtf)s::int[]) AS t(term, qtf)),
         stats AS (SELECT count(*)::float AS n, greatest(avg(term_count), 1)::float AS avgdl FROM chunks),
         df AS (SELECT ct.term, count(*)::float AS df FROM chunk_terms ct JOIN q USING (term) GROUP BY ct.term),
         scored AS (
            SELECT ct.chunk_id,
                   sum(q.qtf * ln(1 + (stats.n - df.df + 0.5) / (df.df + 0.5))
                       * ct.tf * (%(k1)s + 1)
                       / (ct.tf + %(k1)s * (1 - %(b)s + %(b)s * c.term_count / stats.avgdl))) AS score
            FROM chunk_terms ct
            JOIN q USING (term) JOIN df USING (term)
            JOIN chunks c ON c.chunk_id = ct.chunk_id
            CROSS JOIN stats
            WHERE {where}
            GROUP BY ct.chunk_id
            ORDER BY score DESC LIMIT %(k)s)
    SELECT {_COLS}, s.score FROM scored s JOIN chunks c USING (chunk_id) JOIN documents d USING (doc_id)
    ORDER BY s.score DESC"""
    with db.conn() as conn:
        rows = conn.execute(sql, {**params, "terms": terms, "qtf": qtf, "k1": k1, "b": b, "k": k}).fetchall()
    return [_cand(r, float(r["score"]), "bm25", i + 1) for i, r in enumerate(rows)]
