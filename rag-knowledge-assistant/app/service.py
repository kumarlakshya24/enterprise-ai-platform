"""RAG orchestration: one pipeline, feature-flagged by *profiles*.

Profiles map 1:1 to the build phases so the eval can show each step's effect:

    baseline     Phase 1  vector top-k only, no filters, no guards
    rerank       Phase 2a + cross-encoder over 50 candidates -> top 5
    hybrid       Phase 2b + BM25 fused with vector (RRF)
    multiquery   Phase 2c + query expansion (LLM, or PRF offline)
    filtered     Phase 2d + audience metadata filter before ranking
    full         Phase 5  + RBAC, PII redaction, prompt-injection guard
    full_cached  Phase 4  + semantic cache

Every stage is timed; re-ranking and generation have latency budgets with a
degraded fallback (fused order / extractive answer) instead of an error.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from dataclasses import asdict, dataclass, field, replace

import numpy as np

from app.caching.semantic_cache import SemanticCache
from app.config import Settings
from app.db import Database
from app.generation.generator import GenerationResult, Generator
from app.ingestion.pipeline import Indexer
from app.models import Candidate, Principal
from app.providers.embeddings import Embedder, build_embedder
from app.providers.llm import LLM, build_llm
from app.ranking.reranker import Reranker, build_reranker
from app.retrieval import multiquery
from app.retrieval.filters import QueryFilters, build_where
from app.retrieval.fusion import fuse
from app.retrieval.search import bm25_search, vector_search
from app.security import injection, pii
from app.textproc import estimate_tokens, identifiers, stem

log = logging.getLogger("rag")


@dataclass(frozen=True)
class PipelineOptions:
    name: str
    hybrid: bool = False
    rerank: bool = False
    multiquery: bool = False
    audience_filter: bool = False
    enforce_acl: bool = False
    pii: bool = False
    injection_guard: bool = False
    cache: bool = False


PROFILES: dict[str, PipelineOptions] = {
    "baseline": PipelineOptions("baseline"),
    "rerank": PipelineOptions("rerank", rerank=True),
    "hybrid": PipelineOptions("hybrid", rerank=True, hybrid=True),
    "multiquery": PipelineOptions("multiquery", rerank=True, hybrid=True, multiquery=True),
    "filtered": PipelineOptions("filtered", rerank=True, hybrid=True, multiquery=True, audience_filter=True),
    "full": PipelineOptions("full", rerank=True, hybrid=True, multiquery=True, audience_filter=True,
                            enforce_acl=True, pii=True, injection_guard=True),
    "full_cached": PipelineOptions("full_cached", rerank=True, hybrid=True, multiquery=True, audience_filter=True,
                                   enforce_acl=True, pii=True, injection_guard=True, cache=True),
}
# Profiles that disable access control exist only to measure Phase 1-2 behaviour.
UNSAFE_PROFILES = {n for n, p in PROFILES.items() if not p.enforce_acl}


@dataclass
class AskResult:
    request_id: str
    question: str
    answer: str
    refused: bool
    citations: list[dict]
    profile: str
    cache: dict
    timings_ms: dict
    degraded: list[str]
    cost: dict
    refusal_reason: str | None = None
    query_variants: list[str] = field(default_factory=list)
    retrieved: list[dict] = field(default_factory=list)       # final context, with per-stage ranks
    candidates: list[dict] = field(default_factory=list)      # top candidates before/after rerank (debug)
    ranked_doc_ids: list[str] = field(default_factory=list)   # ordered (post-rerank) doc ids, for eval
    pre_rerank_doc_ids: list[str] = field(default_factory=list)  # same candidates in fused order
    redactions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _section(c: Candidate) -> str:
    sec = c.heading_path[-1] if c.heading_path else ""
    return "" if sec.lower() == c.title.lower() else sec


def _cand_view(c: Candidate) -> dict:
    return {"chunk_id": c.chunk_id, "doc_id": c.doc_id, "title": c.title, "team": c.team,
            "section": _section(c), "chunk_index": c.chunk_index,
            "version": c.version_label, "ranks": dict(c.ranks), "scores": {k: round(v, 4) for k, v in c.scores.items()},
            "injection_flagged": c.injection_risk >= 0.6, "pii_types": c.pii_types, "content": c.content}


class RAGService:
    def __init__(self, settings: Settings, db: Database | None = None, embedder: Embedder | None = None,
                 reranker: Reranker | None | str = "auto", llm: LLM | None = None, cache: SemanticCache | None | str = "auto"):
        self.s = settings
        self.db = db or Database(settings.database_url, settings.embedding_dim)
        self.db.migrate()
        self.embedder = embedder or build_embedder(settings)
        self.reranker = build_reranker(settings) if reranker == "auto" else reranker
        self.llm = llm or build_llm(settings)
        if cache == "auto":
            try:
                cache = SemanticCache(settings.redis_url, settings.embedding_dim,
                                      settings.cache_similarity_threshold, settings.cache_ttl_s)
            except Exception as e:  # noqa: BLE001 - the cache is an optimisation, not a dependency
                log.warning("semantic cache unavailable: %s", e)
                cache = None
        self.cache: SemanticCache | None = cache  # type: ignore[assignment]
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="rag")
        self.generator = Generator(self.llm, self.reranker, self.embedder, settings.llm_max_tokens,
                                   settings.min_sentence_score, self.executor)
        self.indexer = Indexer(self.db, self.embedder, settings.chunk_max_tokens, settings.chunk_min_tokens,
                               on_change=self._on_docs_changed)

    def _on_docs_changed(self, doc_ids: list[str]) -> None:
        if self.cache:
            self.cache.invalidate_docs(doc_ids)

    # ------------------------------------------------------------------ helpers
    def _df(self, stems: list[str]) -> tuple[dict[str, int], int]:
        with self.db.conn() as c:
            rows = c.execute("SELECT term, count(*) AS n FROM chunk_terms WHERE term = ANY(%s) GROUP BY term",
                             (stems,)).fetchall()
            n = c.execute("SELECT count(*) AS n FROM chunks").fetchone()["n"]
        return {r["term"]: r["n"] for r in rows}, n

    def _retrieve_one(self, query: str, qvec: np.ndarray, opts: PipelineOptions, where: str, params: dict,
                      k: int, tag: str) -> dict[str, list[Candidate]]:
        lists = {f"vector{tag}": vector_search(self.db, qvec, k, where, params, self.s.hnsw_ef_search)}
        for c in lists[f"vector{tag}"]:
            c.ranks[f"vector{tag}"] = c.ranks.pop("vector")
            c.scores[f"vector{tag}"] = c.scores.pop("vector")
        if opts.hybrid:
            bm = bm25_search(self.db, query, k, where, params, self.s.bm25_k1, self.s.bm25_b)
            for c in bm:
                c.ranks[f"bm25{tag}"] = c.ranks.pop("bm25")
                c.scores[f"bm25{tag}"] = c.scores.pop("bm25")
            lists[f"bm25{tag}"] = bm
        return lists

    def _weights(self, lists: dict) -> dict[str, float]:
        w = {}
        for name in lists:
            base = self.s.hybrid_bm25_weight if name.startswith("bm25") else self.s.hybrid_vector_weight
            w[name] = base * (1.0 if name in ("vector", "bm25") else 0.6)  # variants count less than the original
        return w

    # ------------------------------------------------------------------ main entry
    def ask(self, question: str, principal: Principal | None, profile: str = "full",
            filters: QueryFilters | None = None, debug: bool = False) -> AskResult:
        opts = PROFILES[profile]
        rid = uuid.uuid4().hex[:12]
        t_start = time.perf_counter()
        timings: dict[str, float] = {}
        degraded: list[str] = []
        redactions: Counter = Counter()
        question = question.strip()
        if opts.enforce_acl and principal is None:
            raise PermissionError("authenticated principal required")

        def lap(name: str, t0: float) -> None:
            timings[name] = round((time.perf_counter() - t0) * 1000, 2)

        # ---- PII in the query itself (only matters if text leaves our boundary)
        send_external = opts.pii and (self.llm.is_external or self.s.pii_mode == "always") and self.s.pii_mode != "off"
        llm_question = question
        if send_external:
            r = pii.redact(question)
            if r.redacted:
                llm_question = r.text
                redactions.update({f"query:{k}": v for k, v in r.counts.items()})

        t0 = time.perf_counter()
        qvec = self.embedder.embed([question])[0]
        lap("embed_query", t0)

        # ---- semantic cache
        cache_info = {"enabled": bool(opts.cache and self.cache), "hit": False}
        part = None
        if opts.cache and self.cache:
            t0 = time.perf_counter()
            fdict = asdict(filters) if filters else None
            part = SemanticCache.partition(principal.scope_key() if principal else "anon", opts.name, fdict)
            try:
                hit = self.cache.lookup(qvec, question, part)
            except Exception as e:  # noqa: BLE001
                log.warning("cache lookup failed: %s", e)
                hit, cache_info["error"] = None, type(e).__name__
            lap("cache_lookup", t0)
            if hit:
                timings["total"] = round((time.perf_counter() - t_start) * 1000, 2)
                a = hit.answer
                return AskResult(rid, question, a["answer"], a["refused"], a["citations"], opts.name,
                                 {**cache_info, "hit": True, "similarity": round(hit.similarity, 4),
                                  "cached_question": hit.cached_question, "age_s": round(hit.age_s, 1)},
                                 timings, [], {"llm_usd": 0.0, "projected_usd": 0.0, "note": "served from cache"},
                                 a.get("refusal_reason"), [], a.get("retrieved", []) if debug else [],
                                 [], a.get("ranked_doc_ids", []))

        # ---- retrieval (filters applied inside SQL, before ranking)
        f = filters or QueryFilters(audience_scope=opts.audience_filter)
        if filters is not None and not opts.audience_filter:
            f = replace(filters, audience_scope=False)
        where, params = build_where(principal, f, opts.enforce_acl)
        k = self.s.candidate_k if (opts.rerank or opts.hybrid) else max(self.s.final_k, 10)
        t0 = time.perf_counter()
        lists = self._retrieve_one(question, qvec, opts, where, params, k, "")
        lap("retrieval", t0)

        variants: list[str] = []
        mq_tokens = (0, 0)
        if opts.multiquery:
            t0 = time.perf_counter()
            seed = fuse(lists, self._weights(lists), self.s.fusion_method, self.s.rrf_k) if opts.hybrid else lists["vector"]
            try:
                if self.llm.generative:
                    variants, i_t, o_t = multiquery.llm_variants(self.llm, llm_question, self.s.multiquery_variants,
                                                                 self.s.llm_timeout_s)
                    mq_tokens = (i_t, o_t)
                else:
                    words = {stem(w.lower()) for c in seed[:5] for w in multiquery.feedback_words(question, c)}
                    df, n = self._df(sorted(words))
                    variants = multiquery.prf_variants(question, seed[:5], df, n, self.s.multiquery_variants)
            except Exception as e:  # noqa: BLE001
                log.warning("multi-query expansion failed: %s", e)
                degraded.append("multiquery_failed")
            if variants:
                vvecs = self.embedder.embed(variants)
                for i, (v, vv) in enumerate(zip(variants, vvecs), start=1):
                    lists.update(self._retrieve_one(v, vv, opts, where, params, k, f"_q{i}"))
            lap("multiquery", t0)

        t0 = time.perf_counter()
        if len(lists) > 1:
            cands = fuse(lists, self._weights(lists), self.s.fusion_method, self.s.rrf_k)[:k]
        else:
            cands = lists["vector"]
            for c in cands:
                c.ranks["fused"], c.scores["fused"] = c.ranks["vector"], c.scores["vector"]
        lap("fusion", t0)
        if timings["retrieval"] + timings.get("multiquery", 0) > self.s.retrieval_budget_ms:
            degraded.append("retrieval_over_budget")

        # ---- prompt-injection guard on candidates
        if opts.injection_guard and self.s.injection_mode != "off":
            guarded = []
            for c in cands:
                if c.injection_risk >= 0.6:
                    if self.s.injection_mode == "drop":
                        continue
                    if self.s.injection_mode == "strip":
                        c.content, _ = injection.strip_instructions(c.content)
                guarded.append(c)
            cands = guarded

        # ---- re-ranking with latency budget and slow-path fallback
        reranked = False
        before = [c.chunk_id for c in cands[:10]]
        pre_rerank_docs = [c.doc_id for c in cands[:10]]
        if opts.rerank and self.reranker is not None and cands:
            t0 = time.perf_counter()
            fut = self.executor.submit(self.reranker.score, question,
                                       [f"{c.context_header}\n{c.content}" for c in cands])
            try:
                scores = fut.result(timeout=self.s.rerank_budget_ms / 1000)
                for c, sc in zip(cands, scores):
                    c.scores["rerank"] = float(sc)
                cands.sort(key=lambda c: -c.scores["rerank"])
                for i, c in enumerate(cands):
                    c.ranks["rerank"] = i + 1
                reranked = True
            except FutTimeout:
                degraded.append("rerank_timeout")
                log.warning("rerank exceeded %d ms budget; using fused order", self.s.rerank_budget_ms)
            lap("rerank", t0)
        after = [c.chunk_id for c in cands[:10]]
        if reranked:
            log.info("rerank %s", json.dumps({"request_id": rid, "before": before[:5], "after": after[:5],
                                               "moved_into_top5": [x for x in after[:5] if x not in before[:5]]}))

        final = cands[: self.s.final_k]

        # ---- evidence gate: refuse rather than guess
        t0 = time.perf_counter()
        if not final:
            gen = self.generator.refusal("no_accessible_documents")
        elif reranked and final[0].scores["rerank"] < self.s.min_rerank_score:
            gen = self.generator.refusal("low_rerank_score")
        elif not reranked and final[0].scores.get("vector", final[0].scores.get("fused", 1)) < self.s.min_vector_score \
                and "vector" in final[0].scores:
            gen = self.generator.refusal("low_vector_score")
        elif opts.rerank and (missing := [i for i in identifiers(question)
                                          if not any(i in c.content.lower() or i in c.context_header.lower()
                                                     for c in final)]):
            # The question names a specific code (e.g. VPN-ERR-999) that no retrieved
            # evidence mentions: answering would mean substituting a different code's policy.
            gen = self.generator.refusal(f"identifier_not_in_evidence:{','.join(missing)}")
        else:
            gen = self.generator.generate(llm_question, final, principal, redact_pii=send_external,
                                          guard_injection=opts.injection_guard,
                                          budget_ms=self.s.generation_budget_ms)
            degraded += gen.degraded
            redactions.update({f"context:{k}": v for k, v in gen.redactions.items()})
        lap("generation", t0)

        if redactions:
            self._log_redactions(rid, redactions)

        cost = self._cost(gen, mq_tokens, opts)
        result = AskResult(
            rid, question, gen.text, gen.refused, gen.citations, opts.name, cache_info, timings, degraded, cost,
            gen.reason, variants,
            retrieved=[_cand_view(c) for c in final],
            candidates=[_cand_view(c) for c in cands[:10]] if debug else [],
            ranked_doc_ids=[c.doc_id for c in cands[:10]],
            pre_rerank_doc_ids=pre_rerank_docs,
            redactions=dict(redactions),
        )
        if opts.cache and self.cache and part and not degraded:
            try:
                self.cache.store(qvec, question, part, {
                    "answer": gen.text, "refused": gen.refused, "citations": gen.citations,
                    "refusal_reason": gen.reason, "ranked_doc_ids": result.ranked_doc_ids,
                    "retrieved": result.retrieved}, [c["doc_id"] for c in gen.citations])
            except Exception as e:  # noqa: BLE001
                log.warning("cache store failed: %s", e)
        timings["total"] = round((time.perf_counter() - t_start) * 1000, 2)
        if not debug:
            for r in result.retrieved:
                r.pop("content", None)
        return result

    # ------------------------------------------------------------------ accounting
    def _cost(self, gen: GenerationResult, mq_tokens: tuple[int, int], opts: PipelineOptions) -> dict:
        pin, pout = self.s.llm_price_input_per_mtok / 1e6, self.s.llm_price_output_per_mtok / 1e6
        actual = (gen.input_tokens + mq_tokens[0]) * pin + (gen.output_tokens + mq_tokens[1]) * pout
        p_in, p_out = gen.projected_input_tokens, gen.projected_output_tokens
        if opts.multiquery and not self.llm.generative:  # an LLM expansion call we did not make
            p_in += estimate_tokens(multiquery.PROMPT) + 20
            p_out += 45
        return {"llm_usd": round(actual, 6), "projected_usd": round(p_in * pin + p_out * pout, 6),
                "projected_tokens": {"input": p_in, "output": p_out},
                "projection_model": self.s.llm_model if self.llm.generative else self.s.cost_projection_model,
                "llm": self.llm.name}

    def _log_redactions(self, rid: str, counts: Counter) -> None:
        # Types and counts only - never the matched values.
        log.info("pii_redaction %s", json.dumps({"request_id": rid, "counts": dict(counts)}))
        with self.db.conn() as c:
            for key, n in counts.items():
                stage, typ = key.split(":", 1)
                c.execute("INSERT INTO redaction_events (request_id, stage, pii_type, count) VALUES (%s,%s,%s,%s)",
                          (rid, stage, typ, n))

    def health(self) -> dict:
        out = {"db": False, "redis": False, "embedder": self.embedder.name,
               "reranker": self.reranker.name if self.reranker else None, "llm": self.llm.name}
        try:
            out["db"] = self.db.ping()
        except Exception as e:  # noqa: BLE001
            out["db_error"] = str(e)
        try:
            out["redis"] = bool(self.cache and self.cache.ping())
        except Exception as e:  # noqa: BLE001
            out["redis_error"] = str(e)
        out["status"] = "ok" if out["db"] else "degraded"
        return out

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.db.close()
