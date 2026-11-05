"""Regenerate the README's headline results table from the saved eval run.

The README never contains hand-typed metrics: everything between the
<!-- RESULTS:START --> / <!-- RESULTS:END --> markers is rendered here from
eval_results/latest/summary.json. The full report stays in
eval_results/latest/summary.md.

Usage: python scripts/update_readme.py
"""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
s = json.loads((ROOT / "eval_results" / "latest" / "summary.json").read_text().replace("NaN", "null"))
P = s["profiles"]
ORDER = [p for p in ["baseline", "rerank", "hybrid", "multiquery", "filtered", "full"] if p in P]
LABEL = {"baseline": "Baseline<br><sub>Phase 1</sub>", "rerank": "+ Re-rank<br><sub>Phase 2</sub>",
         "hybrid": "+ Hybrid<br><sub>Phase 2</sub>", "multiquery": "+ Multi-query<br><sub>Phase 2</sub>",
         "filtered": "+ Filters<br><sub>Phase 2</sub>", "full": "**Full**<br><sub>Phase 5</sub>"}


def pct(v):
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.1f}%"


ROWS = [
    ("Answer correct ↑", lambda p: pct(p["answer_correct"])),
    ("Refuses unanswerable ↑", lambda p: pct(p["refusal_correct"])),
    ("Restricted-doc leaks ↓", lambda p: pct(p["rbac_leak_rate"])),
    ("Wrong team's policy on top ↓", lambda p: pct(p["cross_team_top1_error"])),
    ("Followed injected instruction ↓", lambda p: pct(p["injection_followed_rate"])),
    ("Evidence recall@5 ↑", lambda p: pct(p["evidence_recall@5"])),
    ("MRR ↑", lambda p: f"{p['mrr']:.3f}"),
    ("p95 latency", lambda p: f"{p['latency_p95_ms']['total']:.0f} ms"),
]

lines = ["| Metric | " + " | ".join(LABEL[n] for n in ORDER) + " |",
         "|:--|" + ":-:|" * len(ORDER)]
for label, fn in ROWS:
    cells = [fn(P[n]) for n in ORDER]
    cells[-1] = f"**{cells[-1]}**"
    lines.append(f"| {label} | " + " | ".join(cells) + " |")

c = s.get("cache", {})
if "paraphrase_pass" in c:
    pp, nm, inv = c["paraphrase_pass"], c["near_miss"], c["invalidation"]
    lines += ["", f"**Semantic cache** (`full_cached`): {pct(pp['hit_rate'])} of reworded questions hit, "
              f"**{pp['hit_latency_p50_ms']:.1f} ms** p50 on a hit vs {pp['miss_latency_p50_ms']:.0f} ms on a miss, "
              f"{len(c.get('paraphrase_wrong_hits', []))} wrong answers served, "
              f"{len(nm['false_hits'])}/{nm['pairs']} near-miss false hits. "
              f"After a policy update the stale cached answer was "
              f"{'evicted' if not inv['hit_after_update'] else 'NOT evicted'}, and only {inv['embeddings_computed']} of "
              f"{inv['embeddings_computed'] + inv['chunks_unchanged']} chunks were re-embedded."]
lines += ["", f"<sub>Run `{s['run_id']}` · {s['n_questions']} questions · embedder `{s['config']['embedder']}` · "
              f"re-ranker `{s['config']['reranker']}` · generator `{s['config']['llm']}`. "
              f"Full report: [`eval_results/latest/summary.md`](eval_results/latest/summary.md).</sub>"]
block = "\n".join(lines) + "\n"

readme = ROOT / "README.md"
text = readme.read_text()
new, n = re.subn(r"(<!-- RESULTS:START -->\n).*?(<!-- RESULTS:END -->)", lambda m: m.group(1) + block + m.group(2), text, flags=re.S)
if n != 1:
    raise SystemExit("README.md is missing the RESULTS markers")
readme.write_text(new)
print("README results table regenerated from", s["run_id"])
