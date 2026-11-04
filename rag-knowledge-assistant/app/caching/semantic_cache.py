"""Semantic answer cache on Redis (query engine HNSW index).

Correctness rules, in order of importance:
  1. *Partitioned by access scope.* The partition key hashes the user's team +
     roles + pipeline profile + filters, so an answer built from restricted
     documents can only be served to principals with the same entitlements.
  2. *Invalidated by source documents.* Each entry records the doc_ids it cited
     (`semcache:doc:<doc_id>` sets). Updating or deleting a document deletes every
     dependent answer. Refusals ("not found") depend on the whole corpus, so they
     are dropped on *any* index change.
  3. *Similarity threshold + specificity guard.* A hit needs cosine >= threshold
     AND the same "specific tokens" (numbers, codes, amounts): "VPN-ERR-809" must
     never be answered with the cached "VPN-ERR-503" answer even though the
     embeddings are nearly identical.
  4. *TTL* bounds staleness for anything rules 2-3 cannot see.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass

import numpy as np
import redis
from redis.commands.search.field import NumericField, TagField, TextField, VectorField
from redis.commands.search.query import Query

try:
    from redis.commands.search.index_definition import IndexDefinition, IndexType
except ImportError:  # redis-py < 6
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType  # type: ignore

from app.textproc import specific_tokens

log = logging.getLogger(__name__)
ANY_DOC = "__any__"


@dataclass
class CacheHit:
    answer: dict
    similarity: float
    cached_question: str
    age_s: float


class SemanticCache:
    def __init__(self, url: str, dim: int, threshold: float, ttl_s: int, namespace: str = "semcache"):
        self.r = redis.Redis.from_url(url)
        self.dim, self.threshold, self.ttl = dim, threshold, ttl_s
        self.ns = namespace
        self.prefix, self.index = f"{namespace}:entry:", f"{namespace}_idx"
        self._ensure_index()

    def _ensure_index(self) -> None:
        try:
            self.r.ft(self.index).info()
        except redis.ResponseError:
            self.r.ft(self.index).create_index(
                [TagField("part"), TextField("q"), NumericField("created"),
                 VectorField("vec", "HNSW", {"TYPE": "FLOAT32", "DIM": self.dim, "DISTANCE_METRIC": "COSINE"})],
                definition=IndexDefinition(prefix=[self.prefix], index_type=IndexType.HASH),
            )

    @staticmethod
    def partition(scope_key: str, profile: str, filters: dict | None) -> str:
        raw = json.dumps([scope_key, profile, filters or {}], sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()

    def lookup(self, qvec: np.ndarray, question: str, part: str) -> CacheHit | None:
        q = (Query(f"(@part:{{{part}}})=>[KNN 3 @vec $v AS dist]")
             .return_fields("q", "answer", "spec", "created", "dist").sort_by("dist").dialect(2))
        res = self.r.ft(self.index).search(q, query_params={"v": np.asarray(qvec, dtype=np.float32).tobytes()})
        want = specific_tokens(question)
        for doc in res.docs:
            sim = 1.0 - float(doc.dist)
            if sim < self.threshold:
                break
            if set(json.loads(doc.spec)) != want:
                self.r.incr(f"{self.ns}:stats:guard_rejects")
                continue
            self.r.incr(f"{self.ns}:stats:hits")
            return CacheHit(json.loads(doc.answer), sim, doc.q, time.time() - float(doc.created))
        self.r.incr(f"{self.ns}:stats:misses")
        return None

    def store(self, qvec: np.ndarray, question: str, part: str, answer: dict, doc_ids: list[str]) -> str:
        key = self.prefix + uuid.uuid4().hex
        deps = sorted(set(doc_ids)) or [ANY_DOC]
        pipe = self.r.pipeline()
        pipe.hset(key, mapping={
            "part": part, "q": question, "vec": np.asarray(qvec, dtype=np.float32).tobytes(),
            "answer": json.dumps(answer, default=str), "spec": json.dumps(sorted(specific_tokens(question))),
            "docs": ",".join(deps), "created": time.time(),
        })
        pipe.expire(key, self.ttl)
        for d in deps:
            pipe.sadd(f"{self.ns}:doc:{d}", key)
            pipe.expire(f"{self.ns}:doc:{d}", self.ttl)
        pipe.execute()
        return key

    def invalidate_docs(self, doc_ids: list[str]) -> int:
        removed = 0
        for d in set(doc_ids) | {ANY_DOC}:
            set_key = f"{self.ns}:doc:{d}"
            keys = list(self.r.smembers(set_key))
            if keys:
                removed += self.r.delete(*keys)
            self.r.delete(set_key)
        if removed:
            self.r.incrby(f"{self.ns}:stats:invalidated", removed)
            log.info("cache invalidated %d entries for %s", removed, doc_ids)
        return removed

    def clear(self) -> None:
        for k in self.r.scan_iter(f"{self.ns}:*"):
            self.r.delete(k)

    def stats(self) -> dict:
        g = lambda k: int(self.r.get(f"{self.ns}:stats:{k}") or 0)  # noqa: E731
        hits, misses = g("hits"), g("misses")
        info = self.r.ft(self.index).info()
        return {"hits": hits, "misses": misses, "hit_rate": round(hits / (hits + misses), 4) if hits + misses else 0.0,
                "guard_rejects": g("guard_rejects"), "invalidated": g("invalidated"),
                "entries": int(info.get("num_docs", 0)), "threshold": self.threshold, "ttl_s": self.ttl}

    def ping(self) -> bool:
        return bool(self.r.ping())
