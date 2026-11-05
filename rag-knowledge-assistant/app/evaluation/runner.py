"""Evaluation runner: same questions through every pipeline profile, saved to disk.

Usage:
    python -m app.evaluation.runner                       # all profiles + cache experiment
    python -m app.evaluation.runner --profiles baseline full
    python -m app.evaluation.runner --no-reindex          # reuse the current index

Outputs: eval_results/latest/ (committed, cited by the README) and eval_results/runs/<timestamp>/ (local history, git-ignored):
    summary.json, summary.md   aggregated metrics per profile + cache experiment
    <profile>.json             per-question results (answer, citations, ranks, timings)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import shutil
import time
from pathlib import Path

import yaml

from app.config import ROOT, get_settings
from app.evaluation import metrics as M
from app.security.acl import get_principal
from app.service import PROFILES, RAGService

log = logging.getLogger("eval")
DATASET = ROOT / "eval" / "dataset.yaml"
RESULTS = ROOT / "eval_results"
STAGES = ["embed_query", "cache_lookup", "retrieval", "multiquery", "fusion", "rerank", "generation", "total"]


def load_dataset(path: Path = DATASET) -> dict:
    data = yaml.safe_load(path.read_text())
    for q in data["questions"]:
        q.setdefault("answerable", True)
        q.setdefault("relevant_docs", [])
        q.setdefault("expected_facts", [])
        q.setdefault("forbidden_docs", [])
        q.setdefault("forbidden_strings", [])
    return data


def score_one(q: dict, res: dict) -> dict:
    answer, refused = res["answer"], res["refused"]
    ctx_docs = [r["doc_id"] for r in res["retrieved"]]
    cited_docs = [c["doc_id"] for c in res["citations"]]
    forbidden_text = any(s.lower() in answer.lower() for s in q["forbidden_strings"])
    row = {
        "id": q["id"], "category": q["category"], "user": q["user"], "question": res["question"],
        "answerable": q["answerable"], "answer": answer, "refused": refused, "refusal_reason": res.get("refusal_reason"),
        "cited_docs": cited_docs, "context_docs": ctx_docs, "ranked_docs": res["ranked_doc_ids"],
        "pre_rerank_docs": res.get("pre_rerank_doc_ids", []), "timings_ms": res["timings_ms"],
        "degraded": res["degraded"], "cache_hit": res["cache"].get("hit", False), "cost": res["cost"],
        "query_variants": res.get("query_variants", []),
    }
    rel = q["relevant_docs"]
    facts_only = [f for f in q["expected_facts"] if "not found" not in f.lower()]
    if q["answerable"] and facts_only and res.get("candidates"):
        # chunk-level evidence recall: are the expected facts actually inside the top-k chunks?
        for k in (5, 10):
            blob = " ".join(c["content"] for c in res["candidates"][:k])
            row[f"evidence_recall@{k}"] = sum(M.fact_present(f, blob) for f in facts_only) / len(facts_only)
    if q["answerable"] and rel:
        ranked = res["ranked_doc_ids"]
        row["recall@5"] = M.recall_at_k(ranked, rel, 5)
        row["recall@10"] = M.recall_at_k(ranked, rel, 10)
        row["mrr"] = M.mrr(ranked, rel)
        if res.get("pre_rerank_doc_ids"):
            row["pre_rerank_recall@5"] = M.recall_at_k(res["pre_rerank_doc_ids"], rel, 5)
            row["pre_rerank_mrr"] = M.mrr(res["pre_rerank_doc_ids"], rel)
    if q["answerable"]:
        facts = [M.fact_present(f, answer) for f in q["expected_facts"]]
        row["fact_recall"] = (sum(facts) / len(facts)) if facts and not refused else 0.0
        row["correct"] = (not refused) and all(facts) and not forbidden_text
        row["false_refusal"] = refused and not any("not found" in f.lower() for f in q["expected_facts"])
        if any("not found" in f.lower() for f in q["expected_facts"]) and refused:
            row["correct"] = not forbidden_text
    else:
        row["refusal_correct"] = refused and not forbidden_text
        row["correct"] = row["refusal_correct"]
    if not refused:
        row["faithfulness"] = M.faithfulness(answer, res["retrieved"])
        if rel:
            row["citation_precision"] = M.citation_precision(res["citations"], rel)
    if q["category"] == "rbac" and not q["answerable"]:
        row["rbac_leak"] = bool(set(ctx_docs) & set(q["forbidden_docs"])) or forbidden_text
    if q["category"] == "cross_team" and q["forbidden_docs"]:
        row["cross_team_top1_error"] = bool(ctx_docs) and ctx_docs[0] in q["forbidden_docs"]
    if q["category"] == "injection":
        row["injection_followed"] = forbidden_text
    return row


def aggregate(rows: list[dict]) -> dict:
    def m(key: str, subset=None) -> float:
        src = subset if subset is not None else rows
        return M.mean([r[key] for r in src if key in r])

    def rate(key: str) -> float:
        vals = [r[key] for r in rows if key in r]
        return sum(vals) / len(vals) if vals else math.nan

    lat = {s: [r["timings_ms"][s] for r in rows if s in r["timings_ms"]] for s in STAGES}
    answerable = [r for r in rows if r["answerable"]]
    return {
        "n": len(rows),
        "recall@5": m("recall@5"), "recall@10": m("recall@10"), "mrr": m("mrr"),
        "evidence_recall@5": m("evidence_recall@5"), "evidence_recall@10": m("evidence_recall@10"),
        "pre_rerank_recall@5": m("pre_rerank_recall@5"), "pre_rerank_mrr": m("pre_rerank_mrr"),
        "answer_correct": rate("correct"),
        "answerable_correct": M.mean([float(r["correct"]) for r in answerable]),
        "fact_recall": m("fact_recall"),
        "faithfulness": m("faithfulness"),
        "citation_precision": m("citation_precision"),
        "refusal_correct": rate("refusal_correct"),
        "false_refusal_rate": rate("false_refusal"),
        "rbac_leak_rate": rate("rbac_leak"),
        "cross_team_top1_error": rate("cross_team_top1_error"),
        "injection_followed_rate": rate("injection_followed"),
        "latency_p50_ms": {s: round(M.percentile(v, 50), 1) for s, v in lat.items() if v},
        "latency_p95_ms": {s: round(M.percentile(v, 95), 1) for s, v in lat.items() if v},
        "cost_llm_usd_per_query": M.mean([r["cost"]["llm_usd"] for r in rows]),
        "cost_projected_usd_per_query": M.mean([r["cost"]["projected_usd"] for r in rows]),
        "degraded_rate": sum(bool(r["degraded"]) for r in rows) / len(rows),
        "by_category": {c: {"n": len(g), "correct": sum(r["correct"] for r in g) / len(g)}
                        for c in sorted({r["category"] for r in rows})
                        for g in [[r for r in rows if r["category"] == c]]},
    }


def run_profile(svc: RAGService, data: dict, profile: str, s, field: str = "question") -> list[dict]:
    rows = []
    for q in data["questions"]:
        principal = get_principal(q["user"], s.users_file)
        res = svc.ask(q[field], principal, profile, debug=True).to_dict()
        rows.append(score_one(q, res))
    return rows


def threshold_sweep(svc: RAGService, data: dict) -> list[dict]:
    """Hit rate on paraphrases vs false-hit rate on near-miss pairs, per similarity threshold."""
    from app.textproc import specific_tokens

    def pairs_sim(pairs):
        a = svc.embedder.embed([x for x, _ in pairs])
        b = svc.embedder.embed([y for _, y in pairs])
        return [(float(u @ v), specific_tokens(x) == specific_tokens(y)) for (x, y), u, v in zip(pairs, a, b)]

    para = pairs_sim([(q["question"], q["paraphrase"]) for q in data["questions"] if q.get("paraphrase")])
    near = pairs_sim([tuple(p) for p in data.get("cache_near_misses", [])])
    out = []
    for t in (0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95):
        out.append({"threshold": t,
                    "paraphrase_hit_rate": sum(sim >= t and same for sim, same in para) / len(para),
                    "near_miss_false_hit_rate": sum(sim >= t and same for sim, same in near) / max(1, len(near)),
                    "near_miss_false_hit_rate_without_guard": sum(sim >= t for sim, _ in near) / max(1, len(near))})
    return out


def cache_experiment(svc: RAGService, data: dict, s) -> dict:
    if not svc.cache:
        return {"skipped": "redis unavailable"}
    out: dict = {"threshold_sweep": threshold_sweep(svc, data)}
    svc.cache.clear()
    cold = run_profile(svc, data, "full_cached", s, "question")
    para = run_profile(svc, data, "full_cached", s, "paraphrase")
    repeat = run_profile(svc, data, "full_cached", s, "question")

    def summ(rows: list[dict]) -> dict:
        hits = [r for r in rows if r["cache_hit"]]
        misses = [r for r in rows if not r["cache_hit"]]
        return {
            "n": len(rows), "hit_rate": len(hits) / len(rows),
            "correct": sum(r["correct"] for r in rows) / len(rows),
            "correct_on_hits": (sum(r["correct"] for r in hits) / len(hits)) if hits else math.nan,
            "latency_p50_ms": round(M.percentile([r["timings_ms"]["total"] for r in rows], 50), 1),
            "latency_p95_ms": round(M.percentile([r["timings_ms"]["total"] for r in rows], 95), 1),
            "hit_latency_p50_ms": round(M.percentile([r["timings_ms"]["total"] for r in hits], 50), 1) if hits else None,
            "miss_latency_p50_ms": round(M.percentile([r["timings_ms"]["total"] for r in misses], 50), 1) if misses else None,
            "rbac_leak_rate": M.mean([float(r["rbac_leak"]) for r in rows if "rbac_leak" in r]),
        }

    out["cold_pass"] = summ(cold)
    out["paraphrase_pass"] = summ(para)
    out["exact_repeat_pass"] = summ(repeat)
    out["paraphrase_misses"] = [r["question"] for r in para if not r["cache_hit"]]
    out["paraphrase_wrong_hits"] = [r["question"] for r in para if r["cache_hit"] and not r["correct"]]

    # near-miss pairs: the second question must NOT be served from the first one's cache entry
    svc.cache.clear()
    alice = get_principal("alice", s.users_file)
    false_hits = []
    for a, b in data.get("cache_near_misses", []):
        svc.ask(a, alice, "full_cached")
        r = svc.ask(b, alice, "full_cached")
        if r.cache.get("hit"):
            false_hits.append({"asked": b, "served_from": r.cache.get("cached_question"), "similarity": r.cache.get("similarity")})
    out["near_miss"] = {"pairs": len(data.get("cache_near_misses", [])), "false_hits": false_hits,
                        "false_hit_rate": len(false_hits) / max(1, len(data.get("cache_near_misses", [])))}

    # invalidation: cache an answer, update the source doc, the next ask must miss and reflect v4.0
    svc.cache.clear()
    carol = get_principal("carol", s.users_file)
    q = "How many days a week do I need to be in the office?"
    first = svc.ask(q, carol, "full_cached")
    warm = svc.ask(q, carol, "full_cached")
    upd = svc.indexer.ingest_path(ROOT / "data" / "updates" / "remote-work-policy.md")
    after = svc.ask(q, carol, "full_cached")
    svc.indexer.ingest_path(s.docs_dir / "hr" / "remote-work-policy.md")  # restore v3.1 content
    out["invalidation"] = {
        "warm_hit_before_update": warm.cache.get("hit", False),
        "update_action": upd.action, "chunks_replaced": upd.chunks_replaced, "chunks_unchanged": upd.chunks_unchanged,
        "embeddings_computed": upd.embeddings_computed,
        "hit_after_update": after.cache.get("hit", False),
        "answer_before": first.answer, "answer_after": after.answer,
        "answer_after_reflects_update": "two anchor days" in after.answer.lower() or "tuesday and wednesday" in after.answer.lower(),
    }
    out["stats"] = svc.cache.stats()
    svc.cache.clear()
    return out


def _fmt(x, pct=True, nd=1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x * 100:.{nd}f}%" if pct else f"{x:.{nd}f}"


def render_markdown(summary: dict) -> str:
    p = summary["profiles"]
    names = [n for n in PROFILES if n in p]
    lines = [f"Run `{summary['run_id']}`: {summary['n_questions']} questions, "
             f"embedder `{summary['config']['embedder']}`, reranker `{summary['config']['reranker']}`, "
             f"generator `{summary['config']['llm']}`.", ""]
    hdr = "| Metric | " + " | ".join(names) + " |"
    lines += [hdr, "|" + "---|" * (len(names) + 1)]
    rows = [
        ("Doc recall@5", "recall@5", True), ("Doc recall@10", "recall@10", True), ("MRR", "mrr", False),
        ("Evidence recall@5 (facts in top-5 chunks)", "evidence_recall@5", True),
        ("Evidence recall@10", "evidence_recall@10", True),
        ("Answer correct (all questions)", "answer_correct", True), ("Fact recall (answerable)", "fact_recall", True),
        ("Faithfulness", "faithfulness", True), ("Citation precision", "citation_precision", True),
        ("Refusal correct (unanswerable)", "refusal_correct", True), ("False refusal rate", "false_refusal_rate", True),
        ("RBAC leak rate ↓", "rbac_leak_rate", True), ("Cross-team top-1 error ↓", "cross_team_top1_error", True),
        ("Injection followed ↓", "injection_followed_rate", True),
    ]
    for label, key, pct in rows:
        lines.append(f"| {label} | " + " | ".join(_fmt(p[n][key], pct, 1 if pct else 3) for n in names) + " |")
    lines.append("| p50 latency (ms) | " + " | ".join(_fmt(p[n]["latency_p50_ms"].get("total"), False, 0) for n in names) + " |")
    lines.append("| p95 latency (ms) | " + " | ".join(_fmt(p[n]["latency_p95_ms"].get("total"), False, 0) for n in names) + " |")
    lines.append("| LLM cost / query (actual) | " + " | ".join(f"${p[n]['cost_llm_usd_per_query']:.5f}" for n in names) + " |")
    lines.append(f"| Projected cost / query ({summary['config']['projection_model']}) | "
                 + " | ".join(f"${p[n]['cost_projected_usd_per_query']:.5f}" for n in names) + " |")
    rr = [n for n in names if not math.isnan(p[n]["pre_rerank_recall@5"])]
    if rr:
        lines += ["", "**Re-ranker effect on the same candidate set** (fused order → cross-encoder order):", "",
                  "| Profile | recall@5 before | recall@5 after | MRR before | MRR after |", "|---|---|---|---|---|"]
        for n in rr:
            lines.append(f"| {n} | {_fmt(p[n]['pre_rerank_recall@5'])} | {_fmt(p[n]['recall@5'])} | "
                         f"{_fmt(p[n]['pre_rerank_mrr'], False, 3)} | {_fmt(p[n]['mrr'], False, 3)} |")
    st = summary["profiles"].get("full", {}).get("latency_p95_ms", {})
    if st:
        lines += ["", "**Stage latency, `full` profile** (p50 / p95 ms):", "",
                  "| " + " | ".join(st) + " |", "|" + "---|" * len(st),
                  "| " + " | ".join(f"{p['full']['latency_p50_ms'][k]:.0f} / {v:.0f}" for k, v in st.items()) + " |"]
    c = summary.get("cache")
    if c and "cold_pass" in c:
        lines += ["", "**Semantic cache** (`full_cached`, threshold "
                  f"{c['stats']['threshold']}):", "",
                  "| Pass | Hit rate | Correct | p50 ms | p95 ms | p50 on hits | p50 on misses |", "|---|---|---|---|---|---|---|"]
        for k, label in [("cold_pass", "Cold (empty cache)"), ("paraphrase_pass", "Paraphrased questions"),
                         ("exact_repeat_pass", "Exact repeats")]:
            v = c[k]
            lines.append(f"| {label} | {_fmt(v['hit_rate'])} | {_fmt(v['correct'])} | {v['latency_p50_ms']:.0f} | "
                         f"{v['latency_p95_ms']:.0f} | {v['hit_latency_p50_ms'] or '–'} | {v['miss_latency_p50_ms'] or '–'} |")
        nm, inv = c["near_miss"], c["invalidation"]
        lines += ["", f"- Near-miss false hits: {len(nm['false_hits'])}/{nm['pairs']}"
                  + (f" ({'; '.join(h['asked'] for h in nm['false_hits'])})" if nm["false_hits"] else ""),
                  f"- Wrong answers served from cache on paraphrases: {len(c['paraphrase_wrong_hits'])}",
                  f"- Invalidation on document update: warm hit before = {inv['warm_hit_before_update']}, "
                  f"hit after update = {inv['hit_after_update']}, answer reflects v4.0 = {inv['answer_after_reflects_update']} "
                  f"({inv['chunks_replaced']} chunk replaced, {inv['chunks_unchanged']} reused, "
                  f"{inv['embeddings_computed']} embeddings computed)"]
    if c and c.get("threshold_sweep"):
        lines += ["", "**Cache threshold sweep** (cosine on all-MiniLM-L6-v2; guard = numbers/codes must match):", "",
                  "| Threshold | Paraphrase hit rate | Near-miss false hits (with guard) | Near-miss false hits (no guard) |",
                  "|---|---|---|---|"]
        for r in c["threshold_sweep"]:
            lines.append(f"| {r['threshold']:.2f} | {_fmt(r['paraphrase_hit_rate'])} | {_fmt(r['near_miss_false_hit_rate'])}"
                         f" | {_fmt(r['near_miss_false_hit_rate_without_guard'])} |")
    lines += ["", "**Correct by category**:", "", "| Category | n | " + " | ".join(names) + " |",
              "|---|---|" + "---|" * len(names)]
    for cat, v in p[names[-1]]["by_category"].items():
        lines.append(f"| {cat} | {v['n']} | " + " | ".join(_fmt(p[n]["by_category"][cat]["correct"]) for n in names) + " |")
    return "\n".join(lines) + "\n"


def run(profiles: list[str] | None = None, reindex: bool = True, with_cache: bool = True, tag: str | None = None) -> dict:
    s = get_settings()
    svc = RAGService(s)
    data = load_dataset()
    if reindex:
        svc.db.reset()
        svc.indexer.ingest_directory(s.docs_dir)
    if svc.cache:
        svc.cache.clear()
    # warm-up so model load / first-query JIT does not pollute latency percentiles
    warm = get_principal("alice", s.users_file)
    for prof in ("baseline", "full"):
        svc.ask("warm up query about laptops", warm, prof)

    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{tag}" if tag else "")
    out_dir = RESULTS / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"run_id": run_id, "n_questions": len(data["questions"]), "profiles": {},
               "config": {"embedder": svc.embedder.name, "reranker": svc.reranker.name if svc.reranker else None,
                          "llm": svc.llm.name, "projection_model": s.cost_projection_model if not svc.llm.generative else s.llm_model,
                          "candidate_k": s.candidate_k, "final_k": s.final_k, "fusion": s.fusion_method,
                          "weights": {"vector": s.hybrid_vector_weight, "bm25": s.hybrid_bm25_weight},
                          "min_rerank_score": s.min_rerank_score, "cache_threshold": s.cache_similarity_threshold}}
    for prof in profiles or [p for p in PROFILES if p != "full_cached"]:
        t0 = time.time()
        rows = run_profile(svc, data, prof, s)
        agg = aggregate(rows)
        summary["profiles"][prof] = agg
        (out_dir / f"{prof}.json").write_text(json.dumps(rows, indent=2, default=str))
        print(f"{prof:12s} correct={agg['answer_correct']:.3f} r@5={agg['recall@5']:.3f} "
              f"refusal={agg['refusal_correct']:.3f} leak={agg['rbac_leak_rate']:.3f} "
              f"p95={agg['latency_p95_ms']['total']:.0f}ms ({time.time() - t0:.1f}s)")
    if with_cache:
        summary["cache"] = cache_experiment(svc, data, s)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out_dir / "summary.md").write_text(render_markdown(summary))
    if not tag:  # tagged runs are side experiments; `latest` is the canonical run the README cites
        latest = RESULTS / "latest"
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(out_dir, latest)
    svc.close()
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", nargs="*")
    ap.add_argument("--no-reindex", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--tag", help="label for a side experiment; does not replace eval_results/latest")
    a = ap.parse_args()
    summ = run(a.profiles, reindex=not a.no_reindex, with_cache=not a.no_cache, tag=a.tag)
    print(render_markdown(summ))
