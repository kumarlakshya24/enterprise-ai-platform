"""Choose evidence-gate thresholds on the held-out calibration set.

Runs the `full` profile with the gates disabled, records the two evidence scores
the gates use (top cross-encoder chunk score, best extracted-segment score), and
grid-searches the pair that maximises balanced accuracy (answerable answered,
unanswerable refused). Prints the recommendation; it does not edit config.

Usage: python scripts/calibrate.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, get_settings  # noqa: E402
from app.security.acl import get_principal  # noqa: E402
from app.service import RAGService  # noqa: E402


def main() -> None:
    s = get_settings().model_copy(update={"min_rerank_score": -1e9, "min_sentence_score": -1e9})
    svc = RAGService(s, cache=None)
    qs = yaml.safe_load((ROOT / "eval" / "calibration.yaml").read_text())["questions"]
    rows = []
    for q in qs:
        p = get_principal(q["user"], s.users_file)
        r = svc.ask(q["question"], p, "full", debug=True)
        chunk = r.retrieved[0]["scores"].get("rerank", float("nan")) if r.retrieved else float("-inf")
        # best extracted-segment score on the same final context
        from app.models import Candidate
        ctx = [Candidate(chunk_id=x["chunk_id"], score=0, doc_id=x["doc_id"], title=x["title"], content=x["content"],
                         heading_path=[x["section"]] if x["section"] else []) for x in r.retrieved]
        g = svc.generator.extractive(q["question"], ctx, True) if ctx else None
        rows.append((q["answerable"], chunk, g.top_score if g and g.top_score is not None else float("-inf"), q["question"]))
    print(f"{'answerable':10s} {'chunk':>7s} {'segment':>8s}  question")
    for a, c, sg, qq in sorted(rows, key=lambda x: -x[1]):
        print(f"{str(a):10s} {c:7.2f} {sg:8.2f}  {qq}")
    best = None
    grid_c = np.arange(-12, 2.01, 0.25)
    grid_s = np.arange(-12, 2.01, 0.25)
    for tc, ts in itertools.product(grid_c, grid_s):
        tp = sum(1 for a, c, sg, _ in rows if a and c >= tc and sg >= ts)
        tn = sum(1 for a, c, sg, _ in rows if not a and (c < tc or sg < ts))
        pos, neg = sum(1 for r in rows if r[0]), sum(1 for r in rows if not r[0])
        bal = (tp / pos + tn / neg) / 2
        # tie-break: widest margin between each threshold and the nearest observed score,
        # so the decision boundary is not sitting on top of a calibration example
        margin = min(min(abs(c - tc) for _, c, _, _ in rows), min(abs(sg - ts) for _, _, sg, _ in rows))
        key = (bal, margin)
        if best is None or key > best[0]:
            best = (key, tc, ts, tp, tn, pos, neg)
    (bal, _), tc, ts, tp, tn, pos, neg = best
    print(f"\nrecommended MIN_RERANK_SCORE={tc:.2f} MIN_SENTENCE_SCORE={ts:.2f} "
          f"balanced_acc={bal:.3f} (answered {tp}/{pos}, refused {tn}/{neg})")
    svc.close()


if __name__ == "__main__":
    main()
